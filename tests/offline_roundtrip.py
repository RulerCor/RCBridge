"""Exercise the packaged service with fake loopback WeRC + AstrBot; never loads a user profile."""
import json, os, queue, subprocess, sys, tempfile, threading, time, uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler, Request
from websockets.sync.server import serve
from test_werc import row


def run(bundle):
    key=uuid.uuid4().hex; result=queue.Queue(); connected=threading.Event(); sent=[]
    class Fake(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def reply(self,obj):
            data=json.dumps(obj).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(data)
        def do_GET(self):
            assert self.headers['Authorization']=='Bearer demo'
            if self.path.startswith('/api/v1/messages/native/stream?'):
                assert self.headers['Last-Event-ID']=='0';connected.wait(4);self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers();self.wfile.write(('event: message.received\nid: 7\ndata: '+json.dumps(row())+'\n\n').encode());self.wfile.flush();return
            if self.path.startswith('/api/v1/messages/native?'):self.reply({'data_mode':'native_observations','data':[],'next_cursor':0})
            elif self.path.startswith('/api/v1/contacts?'):self.reply({'data':[]})
            else:self.send_error(404)
        def do_POST(self):
            assert self.path=='/api/v1/messages/send-text';sent.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))));self.reply({'data':{'state':'queued','metadata':{'id':'test-ticket'}}})
    def bot(ws):
        try:
            assert ws.request.headers["Authorization"] == "Bearer mock-onebot"
            connected.set()
            while True:
                event=json.loads(ws.recv(timeout=12))
                if event.get('post_type')=='message':break
            assert event['message_type']=='private';assert 'hello' in str(event['message']);ws.send(json.dumps({'action':'send_private_msg','params':{'user_id':event['user_id'],'message':'offline reply'},'echo':'case'}));
            while True:
                res=json.loads(ws.recv(timeout=7))
                if res.get('echo')=='case':break
            assert res['status']=='async' and res['data']['receipts'][0]['task']=='test-ticket';result.put(True)
        except Exception as e:result.put(e)
    with ThreadingHTTPServer(('127.0.0.1',0),Fake) as w, serve(bot,'127.0.0.1',0) as ws, tempfile.TemporaryDirectory() as tmp:
        for server in (w,ws):threading.Thread(target=server.serve_forever,daemon=True).start()
        cfg=json.loads((bundle/'app/bridge/config.example.json').read_text('utf8'));cfg.update(web_port=0,werc_account_id='test-account',werc_token='demo',werc_base_url=f'http://127.0.0.1:{w.server_port}/api/v1',message_source='werc',send_method='werc',buffer_seconds=0.1,onebot_token="mock-onebot",onebot_ws_url=f'ws://127.0.0.1:{ws.socket.getsockname()[1]}/ws',bot_nicknames=[],bot_wxid='',astrbot_config_file='');(Path(tmp)/'config.json').write_text(json.dumps(cfg),'utf8')
        proc=subprocess.Popen([str(bundle/'python/python.exe'),'-I','-B','-X','utf8',str(bundle/'app/desktop/desktop_service.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=dict(os.environ,RCBRIDGE_SESSION=key,RCBRIDGE_HOME=tmp),text=True,encoding='utf8')
        try:
            line=proc.stdout.readline();assert line.startswith('RCBRIDGE_READY'),line
            req=Request('http://127.0.0.1:'+line.split()[1]+'/start',method='POST',headers={'X-RCBridge-Session':key});opener=build_opener(ProxyHandler({}));
            base=req.full_url.rsplit('/',1)[0]; headers={'X-RCBridge-Session':key}
            people=json.load(opener.open(Request(base+'/api/people',headers=headers),timeout=3));assert not people['astrbot_enabled']
            try:opener.open(Request(base+'/api/astrbot-restart',headers=headers,method='POST'),timeout=3)
            except HTTPError as e:assert e.code==409
            else:raise AssertionError('generic mode allowed AstrBot restart')
            assert json.load(opener.open(req,timeout=5))['ok'];out=result.get(timeout=17)
            if isinstance(out,Exception):raise out
            assert len(sent)==1 and sent[0]['username']=='friend' and sent[0]['text']=='offline reply';print('PASS: synthetic WeRC SSE -> OneBot -> WeRC HTTP outbox -> asynchronous receipt')
        finally:
            proc.stdin.close();proc.wait(timeout=12);ws.shutdown();w.shutdown()

if __name__=='__main__':run(Path(sys.argv[1]).resolve())
