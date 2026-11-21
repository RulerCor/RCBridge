"""WeRC v1.2 public HTTP adapter. No access to WeChat processes or databases."""
import base64
import json
import logging
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

import requests

from state import _wxid_to_int

log = logging.getLogger('ob11-bridge')
MEDIA = {'image': ('images', 'image'), 'file': ('files', 'file'), 'video': ('videos', 'video'), 'record': ('audio', 'voice')}


WECHAT_ID = re.compile(r'[A-Za-z0-9_.@-]{1,127}')
HTTP_ERRORS = {
    422: ('invalid_request', '请求字段不符合 WeRC 接口要求'),
    429: ('rate_limited', 'WeRC 忙或已达限额，未自动重试'),
    415: ('unsupported_media', 'WeRC 不支持该媒体类型或格式'),
}


def sse_events(lines):
    kind, parts = '', []
    for line in lines:
        line = line.decode('utf-8') if isinstance(line, bytes) else line
        if not line:
            if parts: yield kind, json.loads('\n'.join(parts))
            kind, parts = '', []
        elif line.startswith('event:'): kind = line[6:].strip()
        elif line.startswith('data:'): parts.append(line[5:].lstrip(' '))


def onebot_segments(message, auto_escape=False):
    if not isinstance(message, str):
        return message
    if auto_escape or '[CQ:reply,' not in message:
        return [{'type': 'text', 'data': {'text': message}}]
    # String form of the same reply segment. Do not treat escaped CQ codes as segments.
    parts = re.split(r'\[CQ:reply,([^\]]*)\]', message)
    chain = []
    for i, part in enumerate(parts):
        if i % 2:
            mid = re.fullmatch(r'id=([0-9]+)', part)
            chain.append({'type': 'reply', 'data': {'id': mid[1] if mid else None}})
        elif part:
            chain.append({'type': 'text', 'data': {'text': part.replace('&#91;', '[').replace('&#93;', ']').replace('&amp;', '&')}})
    return chain


class WeRCError(ValueError):
    def __init__(self, path, status):
        self.status = status
        self.code, detail = HTTP_ERRORS.get(status, ('http_error', '检查账号、授权范围及连接状态'))
        super().__init__(f'WeRC {path}: HTTP {status}（{detail}）')


class WeRC:
    name = 'werc'

    def __init__(self, address, token, account):
        url = urlsplit(address)
        if url.scheme not in ('http', 'https') or url.hostname not in ('localhost', '127.0.0.1', '::1') or url.username or url.password or url.query or url.fragment or url.path.rstrip('/') not in ('', '/api/v1'):
            raise ValueError('WeRC 地址必须是本机 HTTP(S) 服务根地址')
        if not token or not account:
            raise ValueError('请在连接设置填写 WeRC 账号 ID 与授权令牌，并重新打开桌面端')
        self.base_url, self.token, self.account = f'{url.scheme}://{url.netloc}', token, account
        # This cache belongs to the account-bound adapter, not the shared name/legacy-source cache.
        self._sessions = {}
        self._session_lock = threading.Lock()
        self._history_lock = threading.Lock()
        self._history_after = 0

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
            raise WeRCError(path, response.status_code)
        return response

    def page(self, after, limit=100):
        data = self.request('GET', 'messages/native', params={'account_id': self.account, 'after': after, 'limit': limit}).json()
        if (not isinstance(data, dict) or data.get('data_mode') != 'native_observations'
                or not isinstance(data.get('data'), list)
                or type(data.get('next_cursor')) is not int or data['next_cursor'] < 0):
            raise ValueError('不是 WeRC 原生接收页')
        return data

    def check(self):
        try:
            self.page(-1, 1)
            return True, 200, 'WeRC 原生观测接口已授权（不代表微信在线）'
        except WeRCError as e:
            return False, e.status, str(e)
        except ValueError as e:
            return False, 400, str(e)
        except requests.RequestException as e:
            return False, 0, str(e)

    def detect_identity(self):
        rows = self.page(-1, 1)['data']
        wxid = rows[-1]['payload']['sender_id'] if rows else ''
        return {'ok': bool(wxid), 'wxid': wxid, 'nicknames': [], 'source': 'WeRC', 'error': '' if wxid else '暂无原生观测，无法确认登录身份'}

    def fetch_contacts(self):
        rows = self.request('GET', 'contacts', params={'account_id': self.account}).json()['data']
        return [{'username': x['username'], 'displayName': x.get('remark') or x.get('nickname') or x['username']} for x in rows]

    def fetch_group_names(self):
        try:
            return self.request('GET', 'contacts/group-names', params={'account_id': self.account}).json()
        except WeRCError as e:
            if e.status in (401, 403):
                raise ValueError('请在 WeRC 重新签发勾选了「允许同步群名」的令牌，并在 RCBridge 导入。') from None
            if e.status == 404:
                raise ValueError('请使用支持群名同步的 WeRC，并确认已绑定当前微信来源；也可手动导入 JSON。') from None
            raise

    def fetch_friends(self):
        try:
            document = self.request('GET', 'contacts/friends', params={'account_id': self.account}).json()
        except WeRCError as e:
            if e.status in (401, 403):
                raise ValueError('好友列表未授权：请在 WeRC 签发勾选了「允许读取好友列表」的令牌。') from None
            if e.status == 404:
                raise ValueError('好友目录不可用：需要支持好友列表的 WeRC，并绑定当前微信来源。旧版通讯录无法确认好友关系。') from None
            raise
        if (not isinstance(document, dict) or document.get('account_id') != self.account
                or document.get('data_mode') != 'local_friend_directory'
                or not isinstance(document.get('data'), list)):
            raise ValueError('WeRC 未返回当前授权账号的好友目录。')
        return document['data']

    def fetch_directory(self):
        document = self.request('GET', 'contacts/directory', params={'account_id': self.account}).json()
        if (not isinstance(document, dict) or document.get('account_id') != self.account
                or document.get('data_mode') != 'local_categorized_directory'
                or not isinstance(document.get('data'), list)):
            raise ValueError('WeRC 未返回当前授权账号的分类通讯录。')
        return document['data']

    def fetch_group_members(self, room):
        # No verified member identities in a native room envelope or contact snapshot.
        return []

    def fetch_messages(self, *a, **kw):
        return {'messages': []}  # Never substitute snapshot history for native observations.

    def native_peer(self, row, *, include_outgoing=False):
        payload = row.get('payload') if isinstance(row, dict) else None
        if (not isinstance(payload, dict) or payload.get('account_id') != self.account
                or payload.get('schema_version') != 3):
            return ''
        route = payload.get('route')
        peer, me = payload.get('target_id'), payload.get('sender_id')
        if (not isinstance(route, dict) or route.get('conversation') != peer or peer == me
                or not all(isinstance(x, str) and WECHAT_ID.fullmatch(x) for x in (peer, me))):
            return ''
        endpoints = route.get('sender'), route.get('receiver')
        if endpoints == (peer, me) or (include_outgoing and endpoints == (me, peer)):
            return peer
        return ''

    def _remember_sessions(self, peers):
        with self._session_lock:
            for peer in peers:
                if not peer:
                    continue
                key = (_wxid_to_int(peer), peer.endswith('@chatroom'))
                if self._sessions.setdefault(key, peer) != peer:
                    self._sessions[key] = None  # Known collisions must not route to either target.

    def _resolve_session(self, ob_id, group):
        key = (ob_id, group)
        with self._history_lock:
            with self._session_lock:
                if key in self._sessions:
                    return self._sessions[key]
            # Build the ID index from durable observations without forwarding them or
            # changing the SSE cursor. Bound the scan to the current head.
            head = self.page(-1, 1)['next_cursor']
            after = self._history_after
            peers = set()
            while after < head:
                page = self.page(after)
                if not page['data'] or page['next_cursor'] <= after:
                    raise ValueError('WeRC 原生会话历史分页未推进')
                peers.update(self.native_peer(row, include_outgoing=True) for row in page['data'])
                after = page['next_cursor']
            self._remember_sessions(peers)
            self._history_after = after
            with self._session_lock:
                return self._sessions.get(key)

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
        # Schema 3 authenticates the envelope, not the group member: sender_id
        # is the local login, and route.sender is the room for incoming groups.
        event = dict(content=text, sessionId=peer, sessionType='group' if room else 'private',
                     sourceName=name, groupName=name if room else '', senderName='未标识群成员' if room else name,
                     senderWxid='' if room else peer, talkerId='' if room else peer, rawid=p['id'], type=kind,
                     timestamp=int(time.time()), _roomEnvelope=room)
        if kind == 3: event['_alphaMediaUrl'] = 'werc-image:' + str(int(row['position']))
        server_id, position = msg.get('native_message_id'), row.get('position')
        if (kind == 1 and isinstance(server_id, str) and server_id.isascii()
                and server_id.isdecimal() and not server_id.startswith('0')
                and len(server_id) <= 20 and int(server_id) < 2**64
                and type(position) is int and position > 0):
            event['_wercQuote'] = {'account_id': self.account, 'username': peer,
                                   'position': position,
                                   'server_id': server_id}
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
                    self._remember_sessions((peer or self.native_peer(body, include_outgoing=True),))
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
        outcome = '普通发送'
        phase, error_code = 'prepare', 'invalid_request'
        try:
            chain = onebot_segments(params['message'], params.get('auto_escape', False))
            replies = [seg['data'].get('id') for seg in chain if seg['type'] == 'reply']
            if replies:
                outcome = '原生引用不可用'
            group = action == 'send_group_msg' or (action == 'send_msg' and (params.get('message_type') == 'group' or 'group_id' in params))
            target = int(params['group_id' if group else 'user_id'])
            phase, error_code = 'resolve', 'session_unconfirmed'
            peer = self._resolve_session(target, group)
            if not peer:
                raise ValueError('当前 WeRC 账号的原生记录没有唯一可确认的微信会话映射，不按昵称猜测')
            phase, error_code = 'prepare', 'invalid_request'
            quote = None
            if replies:
                if len(replies) != 1:
                    raise ValueError('一个发送请求只能引用一条原消息')
                original = state.get_message(replies[0]) or {}
                quote = original.get('werc_quote')
                if not quote or quote['account_id'] != self.account or quote['username'] != peer:
                    raise ValueError('没有当前账号和会话中可核验的原消息（只支持近期普通文字）')
            jobs = []; text = ''
            for seg in chain:
                kind, d = seg['type'], seg['data']
                if kind == 'text': text += d['text']
                elif kind == 'at':
                    if config.MENTION_AS_TEXT: text += '@' + str(state.get_member_name(int(d['qq'])) or d['qq'] if str(d['qq']).isdigit() else d['qq']) + ' '
                elif kind == 'reply':
                    continue
                elif kind in MEDIA:
                    if text.strip(): jobs.append(('text', text.strip()))
                    text = ''; jobs.append((MEDIA[kind][1], (kind, d)))
                else: raise ValueError(f'不支持的 OneBot 段：{kind}')
            if text.strip(): jobs.append(('text', text.strip()))
            if not jobs: raise ValueError('没有可发送内容')
            if quote:
                # WeRC supports a text quote bubble, not a quoted attachment.
                # Send it first so a rejected/unknown quote cannot send media or plain text.
                if jobs[0][0] != 'text':
                    raise ValueError('原生引用需要以可发送的文字开头')
                jobs[0] = ('quote', jobs[0][1])
            else:
                # Keep ordinary sends' existing upload-before-send behavior.
                phase = 'upload'
                jobs = [(kind, value if kind == 'text' else
                         self._asset(*value, config.ASTRBOT_ATTACHMENTS)) for kind, value in jobs]
            for kind, value in jobs:
                key = uuid.uuid4().hex
                if kind == 'quote':
                    outcome = '原生引用发送未确认'
                    message = {k: v for k, v in quote.items() if k != 'account_id'}
                    phase = 'send'
                    ticket = self.request('POST', 'messages/send/quote', json={
                        'account_id': self.account,
                        'message': {**message, 'text': value, 'idempotency_key': key},
                    }).json()['data']
                else:
                    outcome = '普通发送'
                    if kind != 'text' and quote:
                        phase = 'upload'
                        value = self._asset(*value, config.ASTRBOT_ATTACHMENTS)
                    payload = {'text': value, 'wait_seconds': 2} if kind == 'text' else {'asset_id': value}
                    phase = 'send'
                    ticket = self.request('POST', 'messages/send-' + kind, headers={'Idempotency-Key':key}, json={'account_id':self.account, 'username':peer, **payload}).json()['data']
                status = ticket['state']; receipts.append({'kind':kind,'state':status,'task':ticket.get('metadata',{}).get('id')})
                log.info('WeRC %s发件箱：%s', '原生引用' if kind == 'quote' else '普通发送', status)
                if status not in ('queued','submitting','awaiting_approval','server_accepted','recipient_confirmed'):
                    phase = 'outbox'
                    not_sent = status in ('rejected', 'canceled', 'expired')
                    error_code = 'outbox_not_sent' if not_sent else 'outbox_unknown'
                    if not_sent and kind == 'quote':
                        outcome = '原生引用未发送'
                    raise ValueError(f'发件箱状态 {status}，请在 WeRC 核对；未自动重发')
            done = all(r['state'] in ('server_accepted','recipient_confirmed') for r in receipts)
            return {'status':'ok' if done else 'async','retcode':0 if done else 1,'data':{'receipts':receipts}}
        except (ValueError, KeyError, TypeError, OSError, requests.RequestException) as e:
            error = {'phase': phase, 'code': error_code}
            if isinstance(e, WeRCError):
                error.update(code=e.code, http_status=e.status)
            detail = str(e)
            if phase == 'send' and (not isinstance(e, WeRCError) or e.status >= 500 or e.status == 408):
                error['code'] = 'send_unconfirmed'
                detail += '；发送结果未确认，请在 WeRC 核对；未自动重发'
            if phase == 'send' and isinstance(e, WeRCError) and e.status < 500 and e.status != 408:
                outcome = '原生引用不可用' if outcome.startswith('原生引用') else '普通发送被拒绝'
            elif outcome == '普通发送' and error['code'] in ('outbox_unknown', 'send_unconfirmed'):
                outcome = '普通发送未确认'
            wording = f'{outcome}：{detail}'
            if outcome.startswith('原生引用'):
                wording += '；未补发普通文本'
            log.warning('WeRC [%s/%s] %s', phase, error['code'], wording)
            return {'status':'failed','retcode':100,'wording':wording,
                    'data':{'receipts':receipts, 'error':error}}
