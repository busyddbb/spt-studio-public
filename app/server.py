from __future__ import annotations
import argparse,json,mimetypes,traceback,os
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit,parse_qs
from pathlib import Path
if __package__:
 from . import core, media_uploads, planning, operations, local_access, publishing, studio_bridge, work_publishing
else:
 import core, media_uploads, planning, operations, local_access, publishing, studio_bridge, work_publishing
STATIC=Path(__file__).resolve().parent/'static'
class Handler(BaseHTTPRequestHandler):
 server_version='MediaWorkspace/1.0'
 def log_message(self,fmt,*args): pass
 def send(self,status,data,content_type='application/json; charset=utf-8',filename=None):
  body=json.dumps(data,ensure_ascii=False).encode() if content_type.startswith('application/json') else (data.encode() if isinstance(data,str) else data)
  self.send_response(status); self.send_header('Content-Type',content_type); self.send_header('Content-Length',str(len(body)))
  self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
  self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'self'; frame-ancestors 'self'; form-action 'self'")
  if filename: self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
  self.end_headers(); self.wfile.write(body)
 def send_file(self,path,content_type,filename=None,remove=False):
  try:
   with Path(path).open('rb') as source:
    self.send_response(200)
    self.send_header('Content-Type',content_type)
    self.send_header('Content-Length',str(Path(path).stat().st_size))
    self.send_header('Cache-Control','no-store')
    self.send_header('X-Content-Type-Options','nosniff')
    if filename: self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
    self.end_headers()
    while chunk:=source.read(256*1024): self.wfile.write(chunk)
  except (BrokenPipeError,ConnectionResetError): pass
  finally:
   if remove: Path(path).unlink(missing_ok=True)
 def allowed(self):
  port=self.server.server_port; hosts={f'127.0.0.1:{port}',f'localhost:{port}'}
  if self.headers.get('Host') not in hosts: self.send(403,{'error':'仅允许本机访问'}); return False
  origin=self.headers.get('Origin')
  if origin and origin not in {f'http://{h}' for h in hosts}: self.send(403,{'error':'拒绝跨站请求'}); return False
  return True
 def do_GET(self):
  if not self.allowed(): return
  u=urlsplit(self.path); q=parse_qs(u.query); path=u.path
  if studio_bridge.handle(self): return
  try:
   if path=='/api/health': return self.send(200,{'status':'ok','app':'media-workspace','version':'0.6.0','remote_publishing_enabled':False,'official_web_publishing':True})
   if path=='/api/publishing': return self.send(200,publishing.snapshot())
   if path=='/api/publishing/queue': return self.send(200,work_publishing.snapshot())
   if path=='/api/publishing/work': return self.send(200,work_publishing.preview(q.get('work_id',[''])[0]))
   if path=='/api/publishing/workspace': return self.send(200,publishing.workspace(q.get('account_id',[''])[0],q.get('draft_id',[None])[0],q.get('target',[None])[0]))
   if path=='/api/publishing/upload': return self.send(200,publishing.upload_context(q.get('id',[''])[0]))
   if path=='/api/operations': return self.send(200,operations.snapshot())
   if path=='/api/operations/manifest': return self.send(200,operations.package_manifest(q.get('draft_id',[''])[0]))
   if path=='/api/operations/package':
    return self.send_file(operations.prepare_package(q.get('draft_id',[''])[0]),'application/zip','media-publish-package.zip',remove=True)
   if path=='/api/operations/backup': return self.send_file(operations.backup(),'application/zip','media-desk-backup.zip',remove=True)
   if path=='/api/operations/media':
    image_path,mime=local_access.preview_image(q.get('id',[''])[0])
    return self.send_file(image_path,mime)
   if path=='/api/planning': return self.send(200,planning.get_workspace(q.get('account_id',[None])[0]))
   if path=='/api/planning/export':
    account_id=q.get('account_id',[None])[0]
    if not account_id: raise core.ValidationError('请选择需要导出的账号')
    return self.send(200,planning.export_plan(q.get('batch_id',[None])[0],account_id),filename='media-content-plan.json')
   if path=='/api/media': return self.send(200,media_uploads.snapshot())
   if path=='/api/state': return self.send(200,core.state(q.get('dataset',['real'])[0],q.get('account_id',[None])[0]))
   if path=='/api/research': return self.send(200,core.research())
   if path=='/api/template': return self.send(200,core.template(q.get('kind',['social'])[0]),'text/csv; charset=utf-8','media-template.csv')
   if path=='/api/export/drafts': return self.send(200,core.export_drafts(),filename='media-drafts.json')
   if path.startswith('/api/'): return self.send(404,{'error':'没有此接口'})
   asset_path=path[len('/static/'):] if path.startswith('/static/') else path.lstrip('/')
   target=(STATIC/(asset_path or 'index.html')).resolve()
   if not target.is_relative_to(STATIC.resolve()) or not target.is_file(): return self.send(404,{'error':'页面不存在'})
   mime=mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
   return self.send(200,target.read_bytes(),mime+('; charset=utf-8' if mime.startswith('text/') or mime=='application/javascript' else ''))
  except core.ValidationError as e: self.send(400,{'error':str(e)})
  except Exception:
   traceback.print_exc(); self.send(500,{'error':'读取失败，请查看本地服务日志'})
 def mutation(self,method):
  if not self.allowed(): return
  if studio_bridge.handle(self): return
  try:
   path=urlsplit(self.path).path
   if method=='POST' and path.startswith('/api/media/local/') and path.endswith('/chunk'):
    if self.headers.get('Content-Type','').split(';')[0]!='application/octet-stream': raise core.ValidationError('分块必须使用 application/octet-stream')
    length=int(self.headers.get('Content-Length','0'))
    if not 0<length<=4*1024*1024: raise core.ValidationError('每块最多 4 MiB')
    offset=int(self.headers.get('X-Upload-Offset','-1'))
    body=self.rfile.read(length)
    if len(body)!=length: raise core.ValidationError('分块接收不完整')
    return self.send(200,media_uploads.append_chunk(path.split('/')[-2],offset,body))
   if self.headers.get('Content-Type','').split(';')[0]!='application/json': raise core.ValidationError('请使用 application/json')
   length=int(self.headers.get('Content-Length','0'))
   if not 0<length<6_000_000: raise core.ValidationError('请求体大小不正确')
   data=json.loads(self.rfile.read(length))
   if not isinstance(data,dict): raise core.ValidationError('请求必须是 JSON 对象')
   if method=='POST':
    if path=='/api/publishing/action': result=publishing.dispatch(data.get('action'),data.get('arguments',{}))
    elif path=='/api/operations/action':
     if data.get('action')=='open_local': result=local_access.open_local(data.get('arguments',{}))
     else: result=operations.dispatch(data.get('action'),data.get('arguments',{}))
    elif path=='/api/planning/action': result=planning.dispatch(data.get('action'),data.get('arguments',{}))
    elif path=='/api/media/register': result=media_uploads.register_files(data.get('paths'))
    elif path=='/api/media/provider': result=media_uploads.configure(data.get('api_key'))
    elif path=='/api/media/action': result=media_uploads.job_action(data.get('id'),data.get('action'))
    elif path=='/api/media/local/init': result=media_uploads.init_local_upload(data.get('name'),data.get('size'))
    elif path.startswith('/api/media/local/') and path.endswith('/finish'): result=media_uploads.finish_local_upload(path.split('/')[-2])
    elif path.startswith('/api/media/local/') and path.endswith('/discard'): result=media_uploads.discard_local_upload(path.split('/')[-2])
    elif path=='/api/import': result=core.import_csv(data.get('kind'),data.get('csv_text'),data.get('filename','数据导入.csv'))
    elif path=='/api/drafts': result=core.create_draft(data)
    elif path=='/api/accounts': result=core.create_account(data)
    elif path=='/api/analyze': result=core.analyze(data.get('dataset','real'),data.get('account_id'),data.get('platform_id'))
    else: return self.send(404,{'error':'没有此接口'})
   elif path.startswith('/api/drafts/'): result=core.update_draft(path.split('/')[-1],data)
   elif path.startswith('/api/accounts/'): result=core.update_account(path.split('/')[-1],data)
   else: return self.send(404,{'error':'没有此接口'})
   self.send(200,result)
  except (core.ValidationError,ValueError,TypeError,KeyError) as e: self.send(400,{'error':str(e)})
  except Exception:
   traceback.print_exc(); self.send(500,{'error':'保存失败，请查看本地服务日志'})
 def do_POST(self): self.mutation('POST')
 def do_PATCH(self): self.mutation('PATCH')
 def do_HEAD(self):
  if not self.allowed(): return
  if not studio_bridge.handle(self): self.send_error(405)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8766);args=p.parse_args()
 # The UI and MCP can rebuild their own disposable caches independently.
 # Work files and deterministic work IDs remain shared.
 os.environ.setdefault('SPT_CACHE',str(Path(__file__).resolve().parents[1]/'data'/'spt-app-cache'))
 server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
 media_uploads.start_worker()
 print(f'Media Workspace → http://127.0.0.1:{args.port}',flush=True)
 try: server.serve_forever()
 except KeyboardInterrupt: pass
 finally: server.server_close()
