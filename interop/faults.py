"""Local fault injector; used only against an explicitly supplied test application."""
import copy
import json
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer


class FaultServer:
    def __init__(self,application,mode):
        self.application=application;self.mode=mode;self.requests=[];owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def handle_request(self):
                payload=None
                if self.command=='POST':payload=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
                owner.requests.append((self.command,self.path,copy.deepcopy(payload)))
                operation=self.path.rsplit('/',1)[-1];code=200
                if mode=='unavailable':
                    code=503;result={'protocol_version':'1.0','request_id':None,'episode_id':None,'error':{'code':'TIMEOUT','message':'fixture unavailable','details':{}}}
                else:result=owner.application.dispatch(self.command,self.path,payload)
                data=None
                if operation=='step':
                    if mode=='wrong_request':result['request_id']='unrelated_request'
                    elif mode=='wrong_episode':result['episode_id']=result['observation']['episode_id']='unrelated_episode'
                    elif mode=='stale_time':result['time']=result['observation']['time']=payload['time']
                    elif mode=='undeclared_partial' and result['command_results']:result['command_results'][0]['status']='rejected'
                    elif mode=='lost_after_commit':
                        code=504;result={'protocol_version':'1.0','request_id':payload['request_id'],'episode_id':payload['episode_id'],
                                         'error':{'code':'TIMEOUT','message':'fixture lost committed response','details':{}}}
                    elif mode=='malformed_json':data=b'{'
                    elif mode=='oversize':data=b' '*65537
                if data is None:data=json.dumps(result,ensure_ascii=False,allow_nan=False).encode('utf-8')
                self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.end_headers()
                try:self.wfile.write(data)
                except (BrokenPipeError,ConnectionResetError):pass
            do_GET=handle_request;do_POST=handle_request
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
    @property
    def url(self):return 'http://127.0.0.1:'+str(self.server.server_address[1])
    def __enter__(self):self.thread.start();return self
    def __exit__(self,*args):self.server.shutdown();self.server.server_close();self.thread.join()
