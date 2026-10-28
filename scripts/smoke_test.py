"""Start a temporary local server and check a clean installation (no platform login)."""
from __future__ import annotations
import json,os,socket,subprocess,sys,tempfile,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    with tempfile.TemporaryDirectory(prefix='spt-smoke-') as folder:
        base=Path(folder);workspace=base/'工作区';workspace.mkdir()
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env=dict(os.environ,SPT_SKIP_INSTALLED_SKILLS='1',SPT_WORKSPACE=str(workspace),SPT_CACHE=str(base/'cache'),MEDIA_DB=str(base/'media.sqlite3'),PYTHONUTF8='1')
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with (base/'server.log').open('wb') as log:
            process=subprocess.Popen([sys.executable,str(ROOT/'app/server.py'),'--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=log)
            try:
                address=f'http://127.0.0.1:{port}'
                last_error=None
                for attempt in range(100):
                    try:
                        with opener.open(address+'/api/health',timeout=1) as response:health=json.load(response)
                        break
                    except Exception as error:
                        last_error=error
                        if process.poll() is not None:raise RuntimeError('Server exited during startup') from error
                        time.sleep(.1)
                else:raise RuntimeError('Server did not start') from last_error
                assert health['app']=='media-workspace'
                for path in ('/workspace/','/workspace/spt.js','/api/spt/health','/api/publishing','/api/publishing/queue'):
                    with opener.open(address+path,timeout=10) as response:
                        body=response.read();assert response.status==200 and body,path
                        if path=='/api/spt/health':
                            info=json.loads(body);assert info.get('share') is not True,'Full features were hidden'
                        if path=='/api/publishing':assert json.loads(body)['accounts']==[],'Bundled account found'
                        if path=='/api/publishing/queue':assert json.loads(body)['jobs']==[],'Bundled queue found'
                print('Clean startup passed: UI, asset, library health, empty accounts, empty queue, full features.')
            finally:
                process.terminate()
                try:process.wait(timeout=8)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    return 0
if __name__=='__main__':raise SystemExit(main())
