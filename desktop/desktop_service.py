"""Isolated RCBridge desktop control service. Started/owned by the Windows shell."""
import hmac
import json
import logging
import os
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / 'bridge'
sys.path.insert(0, str(CORE))


def initialize(home):
    home.mkdir(parents=True, exist_ok=True)
    os.environ['RCBRIDGE_HOME'] = str(home)
    path = home / 'config.json'
    if not path.exists():
        clean = json.loads((CORE/'config.example.json').read_text('utf8'))
        clean.update(message_source='werc', send_method='werc', werc_base_url='http://127.0.0.1:5031/api/v1',
                     werc_token='', werc_account_id='', web_host='127.0.0.1', web_port=18766,
                     access_token='', alpha_access_token='', alpha_account_id='', bot_wxid='', bot_nicknames=[],
                     astrbot_attachments='', astrbot_config_file='')
        with path.open('x', encoding='utf8') as f: json.dump(clean, f, ensure_ascii=False, indent=2)
    os.chdir(home)


def make_handler(key):
    import config, state
    from web_panel import WebHandler
    from werc_adapter import WeRC
    ui = HERE/'ui'
    page = (ui/'index.html').read_text('utf8')
    for part in ('members','settings'):
        page = page.replace('<!--'+part.upper()+'-->', (ui/(part+'.html')).read_text('utf8'))
    static = {'/':('text/html',page.encode()), '/icon.png':('image/png',(HERE/'assets/icon.png').read_bytes())}
    for path in [*ui.glob('*.css'), *ui.glob('*.js')]:
        static['/'+path.name] = ('text/css' if path.suffix=='.css' else 'text/javascript',path.read_bytes())

    class Panel(WebHandler):
        def authorized(self):
            if not hmac.compare_digest(self.headers.get('X-RCBridge-Session',''),key):
                self.send_error(403);return False
            return True

        def log_message(self,*args): pass  # Never log headers, URLs, config or form bodies.

        def send_json(self, data, code=200):
            body=json.dumps(data,ensure_ascii=False).encode('utf8')
            self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)))
            self.end_headers();self.wfile.write(body)

        def integration_allowed(self):
            if self.path in ('/api/admins','/api/astrbot','/api/astrbot-restart','/api/astrbot-status','/api/sync-umo-names') and not os.path.isfile(config.ASTRBOT_CONFIG_FILE):
                self.send_json({'ok':False,'error':'该操作属于 AstrBot 集成，请先指定有效的主配置文件。'},409);return False
            return True

        def do_GET(self):
            if not self.authorized() or not self.integration_allowed(): return
            if self.path in static:
                mime, body = static[self.path];self.send_response(200)
                self.send_header('Content-Type',mime+'; charset=utf-8' if mime.startswith('text/') else mime)
                self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)))
                self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body);return
            if self.path == '/api/contact-directory':
                from werc_adapter import WeRCError
                try:
                    if config.MESSAGE_SOURCE != 'werc':
                        raise ValueError('分类通讯录需要 WeRC 接收源。')
                    client = WeRC.from_config(config.config)
                    try:
                        rows = client.fetch_directory()
                    except WeRCError as e:
                        if e.status not in (401, 403, 404):
                            raise
                        from ob_protocol import read_friend_directory
                        try:
                            friends = read_friend_directory()
                        except ValueError:
                            raise ValueError('请更新 WeRC，并导入勾选了「允许读取分类通讯录」的令牌。') from None
                        self.send_json({'ok': True, 'contacts': [dict(row, category='friend', identifier=row['user_id']) for row in friends], 'friend_only': True});return
                    contacts = []
                    for row in rows:
                        if not isinstance(row, dict) or not isinstance(row.get('username'), str) or not row['username']:
                            continue
                        username = row['username']
                        category = row.get('category')
                        category = category if isinstance(category, str) else 'other'
                        has_onebot_id = (category == 'group' and username.endswith('@chatroom')) or (
                            category == 'friend' and not username.endswith(('@chatroom', '@im.chatroom')))
                        contacts.append({'category': category, 'nickname': row.get('nickname') or '',
                                         'remark': row.get('remark') or '',
                                         'identifier': state._wxid_to_int(username) if has_onebot_id else username})
                    self.send_json({'ok': True, 'contacts': contacts, 'friend_only': False})
                except ValueError as e:
                    self.send_json({'ok': False, 'error': str(e)}, 400)
                except OSError:
                    self.send_json({'ok': False, 'error': '无法连接 WeRC，请检查 API 服务后重试。'}, 503)
                return
            if self.path == '/api/werc-outbox':
                try:
                    client = WeRC.from_config(config.config)
                    rows = client.request('GET','outbox',params={'account_id':client.account}).json()['data']
                    self.send_json({'ok':True,'rows':[{'task':row['metadata']['id'],'state':row['state']} for row in rows[:25]]})
                except Exception as e: self.send_json({'ok':False,'error':str(e)},400)
                return
            if self.path not in ('/status','/api/config','/api/people','/api/detect-bot','/api/exit-reason','/api/sync-umo-names','/api/astrbot-status'):
                self.send_error(404);return
            try: super().do_GET()
            except Exception as e: self.send_json({'ok':False,'error':str(e)},400)

        def do_POST(self):
            if not self.authorized() or not self.integration_allowed(): return
            try:
                if self.path == '/start' and not state.running:
                    if 'werc' in (config.MESSAGE_SOURCE, config.SEND_METHOD): WeRC.from_config(config.config)
                if self.path == '/api/test-werc':
                    count=int(self.headers.get('Content-Length',0))
                    if not 0 < count < 16384: raise ValueError('配置长度无效')
                    candidate = WeRC.from_config(json.loads(self.rfile.read(count)))
                    ok, _, msg = candidate.check();self.send_json({'ok':ok,'message':msg});return
                if self.path == '/api/group-names/sync':
                    from people import save_werc_group_names
                    if config.MESSAGE_SOURCE != 'werc':
                        raise ValueError('当前接收源不是 WeRC。')
                    document = WeRC.from_config(config.config).fetch_group_names()
                    with self.server.edit_lock:
                        imported = save_werc_group_names(document)
                    self.send_json({'ok': True, 'imported': imported});return
                if self.path == '/api/group-names/import':
                    from people import import_werc_group_names
                    count = int(self.headers.get('Content-Length', 0))
                    if not 0 < count <= 32 * 1024 * 1024:
                        raise ValueError('请选择不超过 32 MB 的 WeRC 通讯录 JSON。')
                    try:
                        document = json.loads(self.rfile.read(count).decode('utf-8-sig'))
                    except (ValueError, UnicodeError):
                        raise ValueError('文件不是有效的通讯录 JSON。') from None
                    with self.server.edit_lock:
                        imported = import_werc_group_names(document)
                    self.send_json({'ok': True, 'imported': imported});return
                with self.server.edit_lock: super().do_POST()
            except (ValueError,OSError,KeyError) as e: self.send_json({'ok':False,'error':str(e)},400)
    return Panel


def run():
    home=Path(os.environ.get('RCBRIDGE_HOME') or Path(os.environ['LOCALAPPDATA'])/'RCBridge').resolve()
    key=os.environ.pop('RCBRIDGE_SESSION');initialize(home)
    import config, state, exit_reason, main
    from http.server import ThreadingHTTPServer
    server=ThreadingHTTPServer(('127.0.0.1', int(config.WEB_PORT)),make_handler(key));server.edit_lock=threading.Lock()
    state._self_id_int=state._wxid_to_int(config.BOT_WXID or 'wechat_bot')
    exit_reason.install();exit_reason.set_phase('桌面控制台')
    def watch_owner():
        sys.stdin.buffer.read();server.shutdown()
    threading.Thread(target=watch_owner,daemon=True).start()
    print('RCBRIDGE_READY '+str(server.server_port),flush=True)
    try: server.serve_forever(poll_interval=.15)
    finally:
        server.server_close()
        if state.running: main._stop_bridge()
        exit_reason.note_exit('桌面窗口已关闭')

if __name__ == '__main__': run()
