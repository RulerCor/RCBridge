"""WeRC v1.2 public HTTP adapter. No access to WeChat processes or databases."""
import base64
import json
import logging
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

import requests

log = logging.getLogger('ob11-bridge')
MEDIA = {'image': ('images', 'image'), 'file': ('files', 'file'), 'video': ('videos', 'video'), 'record': ('audio', 'voice')}


def sse_events(lines):
    kind, parts = '', []
    for line in lines:
        line = line.decode('utf-8') if isinstance(line, bytes) else line
        if not line:
            if parts: yield kind, json.loads('\n'.join(parts))
            kind, parts = '', []
        elif line.startswith('event:'): kind = line[6:].strip()
        elif line.startswith('data:'): parts.append(line[5:].lstrip(' '))


class WeRC:
    name = 'werc'

    def __init__(self, address, token, account):
        url = urlsplit(address)
        if url.scheme not in ('http', 'https') or url.hostname not in ('localhost', '127.0.0.1', '::1') or url.username or url.password or url.query or url.fragment or url.path.rstrip('/') not in ('', '/api/v1'):
            raise ValueError('WeRC 地址必须是本机 HTTP(S) 服务根地址')
        if not token or not account:
            raise ValueError('请在连接设置填写 WeRC 账号 ID 与授权令牌，并重新打开桌面端')
        self.base_url, self.token, self.account = f'{url.scheme}://{url.netloc}', token, account

    @classmethod
    def from_config(cls, cfg):
        return cls(cfg.get('werc_base_url', 'http://127.0.0.1:5031'), cfg.get('werc_token', ''), cfg.get('werc_account_id', ''))

    def request(self, method, path, **kw):
        headers = {'Authorization': 'Bearer ' + self.token, **kw.pop('headers', {})}
        with requests.Session() as session:
            session.trust_env = False
            response = session.request(method, self.base_url + '/api/v1/' + path, headers=headers,
                                       allow_redirects=False, timeout=(4, 35), **kw)
        if not 200 <= response.status_code < 300:
            raise ValueError(f'WeRC {path}: HTTP {response.status_code}（检查账号、授权范围及连接状态）')
        return response

    def page(self, after, limit=100):
        data = self.request('GET', 'messages/native', params={'account_id': self.account, 'after': after, 'limit': limit}).json()
        if data.get('data_mode') != 'native_observations' or not isinstance(data.get('data'), list):
            raise ValueError('不是 WeRC 原生接收页')
        return data

    def check(self):
        try:
            self.page(-1, 1)
            return True, 200, 'WeRC 原生观测接口已授权（不代表微信在线）'
        except (ValueError, requests.RequestException) as e:
            return False, 0, str(e)

    def detect_identity(self):
        rows = self.page(-1, 1)['data']
        wxid = rows[-1]['payload']['sender_id'] if rows else ''
        return {'ok': bool(wxid), 'wxid': wxid, 'nicknames': [], 'source': 'WeRC', 'error': '' if wxid else '暂无原生观测，无法确认登录身份'}

    def fetch_contacts(self):
        rows = self.request('GET', 'contacts', params={'account_id': self.account}).json()['data']
        return [{'username': x['username'], 'displayName': x.get('remark') or x.get('nickname') or x['username']} for x in rows]

    def fetch_group_members(self, room):
        # No verified member identities in a native room envelope or contact snapshot.
        return []

    def fetch_messages(self, *a, **kw):
        return {'messages': []}  # Never substitute snapshot history for native observations.

    def native_peer(self, row):
        p = row.get('payload') or {}
        route = p.get('route') or {}
        peer, me = p.get('target_id'), p.get('sender_id')
        if (p.get('account_id') == self.account and p.get('schema_version') == 3
                and isinstance(peer, str) and peer and me and peer != me
                and route.get('sender') == peer and route.get('receiver') == me
                and route.get('conversation') == peer):
            return peer
        return ''

    def recent_groups(self):
        # Inspect a bounded window of observations, without forwarding old messages.
        head = self.page(-1, 1)['next_cursor']
        after = max(0, head - 300)
        rooms = set()
        while after < head:
            page = self.page(after)
            for row in page['data']:
                peer = self.native_peer(row)
                if peer.endswith('@chatroom'):
                    rooms.add(peer)
            next_pos = page['next_cursor']
            if next_pos <= after:
                break
            after = next_pos
        return rooms

    def event(self, row, name_of):
        peer = self.native_peer(row)
        if not peer:
            return None
        p = row['payload']
        room = peer.endswith('@chatroom'); msg = p['message']; kind = msg.get('message_type', 1)
        card = row.get('card') or {}; text = msg.get('text', '')
        if kind == 3: text = '[图片]'
        elif kind == 49: text = card.get('text') or card.get('title') or ''
        elif kind != 1: return None
        if not text.strip(): return None
        name = name_of(peer) or peer
        event = dict(content=text, sessionId=peer, sessionType='group' if room else 'private',
                     sourceName=name, groupName=name if room else '', senderName='未标识群成员' if room else name,
                     senderWxid='' if room else peer, talkerId='' if room else peer, rawid=p['id'], type=kind,
                     timestamp=int(time.time()), _roomEnvelope=room)
        if kind == 3: event['_alphaMediaUrl'] = 'werc-image:' + str(int(row['position']))
        return event

    def download_media(self, url):
        prefix, _, pos = url.partition(':')
        if prefix != 'werc-image' or not pos.isdecimal(): raise ValueError('无效原生图片位置')
        path = f'messages/native/{int(pos)}/image'; q = {'account_id': self.account}
        self.request('POST', path, params=q)
        return self.request('GET', path, params=q)

    def listen(self, bridge, state):
        # Cursor belongs to this bridge run: reconnect resumes; explicit fresh start tails only new events.
        if not hasattr(bridge, 'werc_cursor'):
            bridge.werc_cursor = self.page(-1, 1)['next_cursor']
            bridge._prefetch_contact_names()
        try:
            stream = self.request('GET', 'messages/native/stream', stream=True,
                                  params={'account_id': self.account},
                                  headers={'Last-Event-ID': str(bridge.werc_cursor), 'Accept':'text/event-stream'})
            with stream:
                if 'text/event-stream' not in stream.headers.get('Content-Type',''):
                    raise ValueError('WeRC 未返回原生消息流')
                bridge._sse_session = stream
                for kind, body in sse_events(stream.iter_lines(chunk_size=128)):
                    if not state.running or bridge.stop_requested.is_set(): return
                    if kind == 'stream.closed': raise ValueError('WeRC 已关闭消息流，请检查授权和连接')
                    if kind == 'receive.status':
                        bridge.werc_connected = True
                        gaps = body.get('gaps') or 0
                        if gaps != getattr(bridge,'werc_gaps',0): log.warning('WeRC 原生观测缺口：%s',gaps)
                        bridge.werc_gaps = gaps
                        continue
                    if kind != 'message.received': continue
                    pos = int(body['position'])
                    if pos <= bridge.werc_cursor: continue
                    peer = self.native_peer(body)
                    if peer.endswith('@chatroom'):
                        state.note_observed_groups((peer,))
                    event = self.event(body, state.get_chat_name)
                    if event and not state.paused.is_set() and not bridge.ignore_reason(event): bridge.add_to_buffer(event)
                    bridge.werc_cursor = pos
        finally:
            bridge._sse_session = None
            bridge.werc_connected = False

    def _asset(self, kind, data, attachments):
        value = data.get('file') or data.get('url') or ''
        filename = Path(data.get('name') or ('attachment.' + {'image':'png','file':'bin','record':'wav','video':'mp4'}[kind])).name
        if value.startswith('base64://'):
            if len(value) > 12 * 1024**2: raise ValueError('内联附件过大')
            raw = base64.b64decode(value[9:], validate=True)
        else:
            if value.startswith('file:///'): value = url2pathname(value[7:])
            if '://' in value or value.startswith(('\\\\','//')): raise ValueError('不从远程路径读取附件')
            path = Path(value).resolve()
            if not attachments or not path.is_relative_to(Path(attachments).resolve()) or not path.is_file():
                raise ValueError('仅接收 base64 或已配置附件目录内的文件')
            if path.stat().st_size > 8 * 1024**2: raise ValueError('附件超过本桥接 8 MiB 限制')
            raw = path.read_bytes(); filename = path.name
        return self.request('POST', 'media/' + MEDIA[kind][0], params={'account_id': self.account}, files={'file': (filename, raw)}).json()['data']['id']

    def send_onebot(self, action, params, state, config):
        receipts = []
        try:
            group = action == 'send_group_msg' or (action == 'send_msg' and (params.get('message_type') == 'group' or 'group_id' in params))
            peer = state.get_session_id(int(params['group_id' if group else 'user_id']))
            if not peer or group != peer.endswith('@chatroom'): raise ValueError('没有已确认的微信会话映射，不按昵称猜测')
            chain = params['message']; chain = [{'type':'text','data':{'text':chain}}] if isinstance(chain,str) else chain
            jobs = []; text = ''
            for seg in chain:
                kind, d = seg['type'], seg['data']
                if kind == 'text': text += d['text']
                elif kind == 'at':
                    if config.MENTION_AS_TEXT: text += '@' + str(state.get_member_name(int(d['qq'])) or d['qq'] if str(d['qq']).isdigit() else d['qq']) + ' '
                elif kind == 'reply':
                    if config.QUOTE_REPLY_PREFIX:
                        original = state.get_message(d.get('id')) or {}
                        if original: text += f"〔回复 {original.get('sender', '?')}：{original.get('content', '')[:40]}〕\n"
                elif kind in MEDIA:
                    if text.strip(): jobs.append(('text', {'text':text.strip()}))
                    text = ''; jobs.append((MEDIA[kind][1], {'asset_id':self._asset(kind, d, config.ASTRBOT_ATTACHMENTS)}))
                else: raise ValueError(f'不支持的 OneBot 段：{kind}')
            if text.strip(): jobs.append(('text', {'text':text.strip()}))
            if not jobs: raise ValueError('没有可发送内容')
            for kind, payload in jobs:
                if kind == 'text': payload['wait_seconds'] = 2
                ticket = self.request('POST', 'messages/send-' + kind, headers={'Idempotency-Key':uuid.uuid4().hex}, json={'account_id':self.account, 'username':peer, **payload}).json()['data']
                status = ticket['state']; receipts.append({'state':status,'task':ticket.get('metadata',{}).get('id')})
                log.info('WeRC 发件箱：%s', status)
                if status not in ('queued','submitting','awaiting_approval','server_accepted','recipient_confirmed'):
                    raise ValueError(f'发件箱状态 {status}，请在 WeRC 核对；未自动重发')
            done = all(r['state'] in ('server_accepted','recipient_confirmed') for r in receipts)
            return {'status':'ok' if done else 'async','retcode':0 if done else 1,'data':{'receipts':receipts}}
        except (ValueError, KeyError, TypeError, OSError, requests.RequestException) as e:
            log.warning('WeRC 发送未确认：%s', e)
            return {'status':'failed','retcode':100,'wording':str(e),'data':{'receipts':receipts}}
