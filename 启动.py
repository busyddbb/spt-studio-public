from __future__ import annotations
from pathlib import Path
import argparse,base64,json,ntpath,os,shutil,subprocess,sys,time,urllib.request,webbrowser
ROOT=Path(__file__).resolve().parent
url='http://127.0.0.1:8766'
MAC=sys.platform=='darwin'
WINDOWS=os.name=='nt'
# 本机地址不走系统代理（Windows 上常有代理软件把 127.0.0.1 也转出去）。
LOCAL=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def healthy():
 try:
  with LOCAL.open(url+'/api/health',timeout=1) as r:return json.load(r).get('app')=='media-workspace'
 except Exception:return False
def workspace_folder():
 try:
  sys.path.insert(0,str(ROOT));from spt.server.config import custom_workspace;custom=custom_workspace()
 except Exception:custom=None
 return custom or ROOT/'工作区'
def desktop_link(link=None,target=None,create=True):
 """桌面上的「工作区」是指向 SPT 工作区的快捷方式，Lemonade 的工具靠它把文件写进来。
 没有或者坏了就重建；指向别处或不是快捷方式就只提醒，不动它。返回给人看的一句话，没事返回空。
 分享出去的那份（create=False）不在别人桌面上建东西，只检查已有的。
 Windows 上建符号链接要管理员权限，也没有 Lemonade 的工具，整个跳过。"""
 if WINDOWS:return ''
 link=link or Path.home()/'Desktop'/'工作区';target=target or workspace_folder()
 if not target.is_dir() or target==link:return ''
 if link.is_symlink() and not link.exists():
  if not create:return ''
  link.unlink();link.symlink_to(target);return '已修好桌面上的「工作区」快捷方式。'
 if not link.exists():
  if not create:return ''
  link.symlink_to(target);return '已在桌面建好「工作区」快捷方式。'
 if link.resolve()==target.resolve():return ''
 if link.is_symlink():return f'桌面上的「工作区」指向 {link.resolve()}，不是 SPT 的工作区。'
 return '桌面上的「工作区」是个普通文件夹，不是指向 SPT 工作区的快捷方式。'
def server_command(windows=WINDOWS,executable=sys.executable):
 """(命令, Popen 额外参数)。Windows 用 pythonw（没有黑窗口），没有就用 python 加 CREATE_NO_WINDOW；
 都放进自己的进程组，关掉启动用的命令行窗口也不会带走服务。"""
 if not windows:return [executable,str(ROOT/'app'/'server.py'),'--port','8766'],{'start_new_session':True}
 quiet=Path(executable).with_name('pythonw.exe')
 python=str(quiet) if quiet.is_file() else executable
 flags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0x200)|(getattr(subprocess,'DETACHED_PROCESS',0x8) if quiet.is_file() else getattr(subprocess,'CREATE_NO_WINDOW',0x8000000))
 env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8')   # 日志和中文路径都按 UTF-8
 return [python,str(ROOT/'app'/'server.py'),'--port','8766'],{'creationflags':flags,'env':env,'stdin':subprocess.DEVNULL}
def native_app():
 """装在「应用程序」里的 SPT 优先；分享包用文件夹里自带的 SPT.app；只有 Mac 有。"""
 if not MAC:return None
 apps=[Path.home()/'Applications'/'SPT.app',ROOT/'SPT.app',ROOT/'native'/'build'/'SPT.app']
 return next((app for app in apps if app.is_dir()),None)
# Windows：SPT 用 Edge（Windows 10/11 自带）或 Chrome 的「应用模式」开成自己的窗口，和 Mac 应用一样只有 SPT 一个界面。
APP_BROWSERS=(('edge-profile',(('ProgramFiles(x86)','Microsoft','Edge','Application','msedge.exe'),('ProgramFiles','Microsoft','Edge','Application','msedge.exe'),('LocalAppData','Microsoft','Edge','Application','msedge.exe')),'msedge'),
 ('chrome-profile',(('ProgramFiles','Google','Chrome','Application','chrome.exe'),('ProgramFiles(x86)','Google','Chrome','Application','chrome.exe'),('LocalAppData','Google','Chrome','Application','chrome.exe')),'chrome'))
def app_browser(env=None,exists=os.path.isfile,which=shutil.which):
 """(浏览器路径, 资料夹名)：先 Edge 再 Chrome，各自先看安装位置再看 PATH；都没有返回 None。"""
 env=os.environ if env is None else env
 for profile,places,command in APP_BROWSERS:
  for variable,*parts in places:
   base=env.get(variable)
   if base and exists(ntpath.join(base,*parts)):return ntpath.join(base,*parts),profile
  found=which(command)
  if found:return found,profile
 return None
def app_window_command(browser,profile,address):
 """单独的资料夹（data/edge-profile）让 SPT 窗口的大小、缩放和平时上网的浏览器互不影响。"""
 return [browser,'--app='+address,'--user-data-dir='+str(ROOT/'data'/profile),'--window-size=1280,860','--no-first-run','--no-default-browser-check']
def open_window(address,find=app_browser,popen=subprocess.Popen,fallback=webbrowser.open):
 """Windows：开成 SPT 自己的窗口；没有 Edge 和 Chrome 才退回默认浏览器。关掉窗口服务照常在后台。"""
 found=find()
 if found:
  try:
   popen(app_window_command(found[0],found[1],address),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True)
   return 'app'
  except OSError:pass
 fallback(address);return 'browser'
def shortcut_script(link_name,target,arguments,folder,icon):
 """PowerShell：桌面上还没有 SPT.lnk 才建（桌面在 OneDrive 里也找得到）。"""
 quote=lambda text:"'"+str(text).replace("'","''")+"'"
 return ('$desktop=[Environment]::GetFolderPath("Desktop");$path=Join-Path $desktop '+quote(link_name)+';'
  'if(-not (Test-Path -LiteralPath $path)){$link=(New-Object -ComObject WScript.Shell).CreateShortcut($path);'
  '$link.TargetPath='+quote(target)+';$link.Arguments='+quote(arguments)+';$link.WorkingDirectory='+quote(folder)+';'
  '$link.IconLocation='+quote(str(icon)+',0')+';$link.Description="SPT";$link.Save()}')
def desktop_shortcut(executable=sys.executable,run=subprocess.run,marker=None):
 """第一次在 Windows 上打开时，在桌面放一个「SPT」图标（指向 pythonw 启动.py，没有黑窗口），以后双击它就行。
 只建一次（data/.desktop-shortcut 记着）：删掉了就不再自己冒出来。建不成也不打扰。"""
 marker=marker or ROOT/'data'/'.desktop-shortcut'
 if marker.exists():return False
 quiet=Path(executable).with_name('pythonw.exe')
 target,arguments=(str(quiet),'"'+str(ROOT/'启动.py')+'"') if quiet.is_file() else (str(ROOT/'启动SPT.bat'),'')
 script=shortcut_script('SPT.lnk',target,arguments,ROOT,ROOT/'native'/'SPT.ico')
 try:
  run(['powershell','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-EncodedCommand',base64.b64encode(script.encode('utf-16-le')).decode('ascii')],
   stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0x8000000))
 except (OSError,subprocess.SubprocessError):return False
 marker.parent.mkdir(exist_ok=True);marker.write_text('SPT.lnk\n',encoding='utf-8');return True
def tell(text):
 """命令行里打印；Windows 上从桌面图标（pythonw）打开时没有命令行，出错就弹一个对话框。"""
 if sys.stdout is not None:print(text)
 elif WINDOWS:
  try:
   import ctypes;ctypes.windll.user32.MessageBoxW(None,text,'SPT',0x40)
  except Exception:pass
def windows_runtime():
 """Windows default: keep the account windows and background workers together."""
 try:
  from windows.runtime import main
  return main()
 except ModuleNotFoundError:
  tell('Windows 执行组件未安装。请先双击「安装Windows.bat」，完成后再打开 SPT。');return 1
 except Exception:
  tell('Windows 执行器未能启动。请先运行「安装Windows.bat」补齐浏览器组件；详情见 data/windows-runtime.log。');return 1
if __name__=='__main__':
 if WINDOWS:os.environ['PATH']=str(ROOT/'.venv'/'Scripts')+os.pathsep+os.environ.get('PATH','')
 p=argparse.ArgumentParser();p.add_argument('--no-open',action='store_true');p.add_argument('--browser',action='store_true',help='显式使用浏览器窗口');args=p.parse_args()
 note=desktop_link(create=not (ROOT/'spt'/'settings.share.json').is_file())
 if note:tell(note)
 if not healthy():
  (ROOT/'data').mkdir(exist_ok=True)
  command,extra=server_command()
  with open(ROOT/'data'/'server.log','a',encoding='utf-8') as log:
   process=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=log,**extra)
  # Windows 第一次启动常被杀毒软件扫描，多等一会儿
  for _ in range(100 if WINDOWS else 30):
   if healthy():break
   if process.poll() is not None:break
   time.sleep(.2)
  if not healthy():
   tell('启动失败，请查看 data/server.log；8766 端口可能被其他程序占用。');sys.exit(1)
 if sys.stdout is not None:print('SPT 已启动：'+url+'/workspace/')
 if WINDOWS:desktop_shortcut()
 if not args.no_open:
  native=native_app()
  if WINDOWS and not args.browser:sys.exit(windows_runtime())
  elif args.browser or native is None:webbrowser.open(url+'/workspace/')
  else:subprocess.run(['/usr/bin/open',str(native)],check=True)
