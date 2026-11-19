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
    group_response = {'account_id':'test-account', 'data':{'sample@chatroom':'Synced title','directory-only@chatroom':'Directory only'}}
    friend_response = {'account_id':'test-account','data_mode':'local_friend_directory','data':[
        {'username':'friend','nickname':'Test friend','remark':'Test remark'},
        {'username':'quiet-friend','nickname':'Quiet friend','remark':None},
        {'username':'sample@chatroom','nickname':'Not a friend','remark':None},
    ]}
    class Fake(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def reply(self,obj):
            data=json.dumps(obj).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(data)
        def do_GET(self):
            assert self.headers['Authorization']=='Bearer demo'
            if self.path.startswith('/api/v1/messages/native/stream?'):
                assert self.headers['Last-Event-ID']=='7';connected.wait(4);self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                for pos, peer in [(8, 'friend'), (9, 'other@chatroom')]:
                    self.wfile.write((f'event: message.received\nid: {pos}\ndata: '+json.dumps(dict(row(peer), position=pos))+'\n\n').encode())
                self.wfile.flush();return
            if self.path.startswith('/api/v1/messages/native?'):
                # Discovery sees a known group while the imported contact snapshot is empty.
                data = [row('sample@chatroom', type_=43)]
                pos = 7 if data else 0
                self.reply({'data_mode':'native_observations','data':data,'next_cursor':pos})
            elif self.path.startswith('/api/v1/contacts?'):self.reply({'data':[]})
            elif self.path == '/api/v1/contacts/group-names?account_id=test-account':self.reply(group_response)
            elif self.path == '/api/v1/contacts/friends?account_id=test-account':self.reply(friend_response)
            else:self.send_error(404)
        def do_POST(self):
            assert self.path=='/api/v1/messages/send-text';sent.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))));self.reply({'data':{'state':'queued','metadata':{'id':'test-ticket'}}})
    def bot(ws):
        try:
            assert ws.request.headers["Authorization"] == "Bearer mock-onebot"
            connected.set()
            events = {}
            while len(events) < 2:
                event = json.loads(ws.recv(timeout=12))
                if event.get('post_type') == 'message': events[event['message_type']] = event
            def call(action, params=None):
                ws.send(json.dumps({'action':action,'params':params or {},'echo':action}))
                while True:
                    response = json.loads(ws.recv(timeout=7))
                    if response.get('echo') == action: return response
            private = events['private']
            assert 'hello' in str(private['message'])
            response = call('get_friend_list')
            assert response['status']=='ok' and len(response['data'])==2
            by_name = {f['nickname']: f for f in response['data']}
            assert by_name['Test friend'] == {'user_id':private['user_id'],'nickname':'Test friend','remark':'Test remark'}
            assert by_name['Quiet friend']['remark'] == ''
            friend_response['account_id'] = 'different-account'
            response = call('get_friend_list')
            assert response['status']=='failed' and response['data'] is None
            response = call('get_group_list')
            assert response['status']=='ok'
            assert next(g['group_name'] for g in response['data'] if g['group_id']==events['group']['group_id']) == 'Second group'
            assert {'Synced title', 'Directory only'} <= {g['group_name'] for g in response['data']}
            res = call('send_private_msg', {'user_id':private['user_id'],'message':'offline reply'})
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
            refresh = Request(base+'/api/refresh-people', data=b'{}', headers=headers, method='POST')
            assert json.load(opener.open(refresh, timeout=5))['groups'] == 1
            people=json.load(opener.open(Request(base+'/api/people',headers=headers),timeout=3));assert not people['astrbot_enabled']
            assert [(g['session'], g['name']) for g in people['groups']] == [('sample@chatroom', 'sample@chatroom')]
            previous_id = people['groups'][0]['gid']
            def contact(username, nickname, remark=None, deleted=0):
                return {'record_type':'contact','record':{'anchor':{'username':username},
                        'nickname':nickname,'remark':remark,'delete_flag':deleted}}
            directory = {'schema_version':1,'account_id':'test-account', 'data_mode':'local_directory_cache',
                         'selection':{'kind':'contacts'},'rows':[
                             contact('sample@chatroom', 'Default title', 'Real group title'),
                             contact('other@chatroom', 'Second group'),
                             contact('deleted@chatroom', 'Deleted group', deleted=1),
                             contact('friend', 'Private contact'),
                         ]}
            def import_names(document):
                request = Request(base+'/api/group-names/import', data=json.dumps(document).encode(), headers=headers)
                return json.load(opener.open(request, timeout=5))
            try: import_names(dict(directory, account_id='different-account'))
            except HTTPError as e: assert e.code == 400
            else: raise AssertionError('Imported another WeRC account')
            assert import_names(directory)['imported'] == 2
            roster = json.load(opener.open(Request(base+'/api/people',headers=headers),timeout=3))['groups']
            assert {g['session']:g['name'] for g in roster} == {'sample@chatroom':'Real group title','other@chatroom':'Second group'}
            assert next(g['gid'] for g in roster if g['session']=='sample@chatroom') == previous_id
            saved_names = json.loads((Path(tmp)/'data/werc_group_names.json').read_text('utf8'))
            assert saved_names == {'test-account':{'sample@chatroom':'Real group title','other@chatroom':'Second group'}}
            sync = Request(base+'/api/group-names/sync', data=b'{}', headers=headers)
            assert json.load(opener.open(sync, timeout=5))['imported'] == 2
            roster = json.load(opener.open(Request(base+'/api/people', headers=headers), timeout=3))['groups']
            assert next((g['gid'], g['name']) for g in roster if g['session']=='sample@chatroom') == (previous_id, 'Synced title')
            assert {g['session'] for g in roster} == {'sample@chatroom', 'other@chatroom', 'directory-only@chatroom'}
            path = Path(tmp)/'data/werc_group_names.json'
            before = path.read_bytes()
            group_response['data'] = {}
            assert json.load(opener.open(sync, timeout=5))['imported'] == 0
            group_response.update(account_id='different-account', data={'sample@chatroom':'Wrong title'})
            try: opener.open(sync, timeout=5)
            except HTTPError as e: assert e.code == 400
            else: raise AssertionError('Synced another WeRC account')
            assert path.read_bytes() == before
            assert not sent  # discovery before starting never forwards or sends an observation
            toggle = Request(base+'/api/session-toggle', data=b'{"session":"sample@chatroom","muted":true}', headers=headers, method='POST')
            assert json.load(opener.open(toggle, timeout=3))['muted']
            assert any(g['session']=='sample@chatroom' and g['muted'] for g in json.load(opener.open(Request(base+'/api/people', headers=headers), timeout=3))['groups'])
            try:opener.open(Request(base+'/api/astrbot-restart',headers=headers,method='POST'),timeout=3)
            except HTTPError as e:assert e.code==409
            else:raise AssertionError('generic mode allowed AstrBot restart')
            assert json.load(opener.open(req,timeout=5))['ok'];out=result.get(timeout=17)
            if isinstance(out,Exception):raise out
            assert len(sent)==1 and sent[0]['username']=='friend' and sent[0]['text']=='offline reply';print('PASS: routed friend/group IDs, directory names, account rejection and synthetic message roundtrip')
        finally:
            proc.stdin.close();proc.wait(timeout=12);ws.shutdown();w.shutdown()

if __name__=='__main__':run(Path(sys.argv[1]).resolve())
