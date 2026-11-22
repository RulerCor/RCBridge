"""Offline adapter contract checks. No network, secrets or WeChat required."""
import base64
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import requests

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bridge'))
from werc_adapter import WeRC, WeRCError, sse_events
import state as bridge_state
from state import _wxid_to_int


def row(peer='friend', type_=1, position=7, server_id=None):
    return {'position': position, 'payload': {'schema_version':3,'account_id':'test-account',
            'id':f'msg{position}','target_id':peer,'sender_id':'me',
            'route':{'sender':peer,'receiver':'me','conversation':peer},
            'message':{'message_type':type_,'text':'hello',
                       'native_message_id': server_id if server_id is not None else str(2**53 + position)}}}


GIF_B64 = 'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'
GIF_BYTES = base64.b64decode(GIF_B64)


def quoted(mid=12, text='reply'):
    return [{'type':'reply','data':{'id':mid}}, {'type':'text','data':{'text':text}}]

class Contract(unittest.TestCase):
    def setUp(self):
        self.w=WeRC('http://127.0.0.1:5031/api/v1','test-only','test-account');self.w.request=Mock()
        self.state=NS(get_member_name=lambda uid:None)
        self.w._remember_sessions(('friend',))
        self.cfg=NS(MENTION_AS_TEXT=True,ASTRBOT_ATTACHMENTS='')
        old = self.w.event(row(position=10), lambda _:None)['_wercQuote']
        new = self.w.event(row(position=11), lambda _:None)['_wercQuote']
        self.messages = {12: {'werc_quote': old}, 13: {'werc_quote': new}}
        self.state.get_message = lambda mid: self.messages.get(int(mid)) if mid else None
    def send(self, msg, peer='friend', group=False):
        action, target = ('send_group_msg', 'group_id') if group else ('send_private_msg', 'user_id')
        return self.w.send_onebot(action, {target: _wxid_to_int(peer), 'message': msg}, self.state, self.cfg)
    def test_normalize_export(self):self.assertEqual(self.w.base_url,'http://127.0.0.1:5031')
    def test_refuse_nonlocal(self):
        for url in ['https://example.com','http://127.0.0.1@other.invalid','http://localhost/api?x=1']:
            with self.assertRaises(ValueError):WeRC(url,'T','A')
    def test_private(self):self.assertEqual(self.w.event(row(),lambda _:None)['senderWxid'],'friend')
    def test_group_envelope(self):
        observation = row('group@chatroom')
        observation['payload']['message']['text'] = 'wxid_spoofed:\nhello'
        event = self.w.event(observation, lambda _:'room')
        self.assertTrue(event['_roomEnvelope'])
        self.assertEqual(event['sessionId'], 'group@chatroom')
        self.assertEqual(event['senderName'], '未标识群成员')
        self.assertFalse(event['senderWxid'])
        self.assertEqual(event['content'], 'wxid_spoofed:\nhello')
    def test_reject_ambiguous_and_self_and_wrong_scope(self):
        for patch in [{'route':None},{'schema_version':1},{'account_id':'other'},{'route':{'sender':'me','receiver':'friend','conversation':'friend'}}]:
            d=row();d['payload'].update(patch);self.assertIsNone(self.w.event(d,lambda _:None))
    def test_group_discovery_reads_metadata_without_forwarding_messages(self):
        a = row('first@chatroom', type_=43)  # a video still identifies the group
        b = row('second@chatroom')
        foreign = row('foreign@chatroom')
        foreign['payload']['account_id'] = 'different-account'
        ambiguous = row('unknown@chatroom')
        ambiguous['payload']['route'] = None
        self.w.page = Mock(side_effect=[
            {'data': [b], 'next_cursor': 350},
            {'data': [a, foreign, ambiguous, row()], 'next_cursor': 151},
            {'data': [a, b], 'next_cursor': 350},
        ])
        self.assertEqual(self.w.recent_groups(), {'first@chatroom', 'second@chatroom'})
        self.assertEqual([c.args for c in self.w.page.call_args_list], [(-1, 1), (50,), (151,)])
        self.w.request.assert_not_called()

    def test_inbound_image(self):self.assertEqual(self.w.event(row(type_=3),lambda _:None)['_alphaMediaUrl'],'werc-image:7')
    def test_sse(self):
        frame=[': keep-alive','','event: receive.status','data: {"gaps":0}','','event: message.received','id: 7','data: '+json.dumps(row()),''];self.assertEqual(list(sse_events(frame)),[('receive.status',{'gaps':0}),('message.received',row())])
    def test_pending_not_delivered(self):
        self.w.request.return_value.json.return_value={'data':{'state':'queued','metadata':{'id':'ticket'}}};r=self.send('hello');self.assertEqual(r['status'],'async');args=self.w.request.call_args;self.assertEqual(args.args,('POST','messages/send-text'));self.assertEqual(args.kwargs['json']['username'],'friend');self.assertGreaterEqual(len(args.kwargs['headers']['Idempotency-Key']),16)
    def test_failure_not_retried(self):
        self.w.request.return_value.json.return_value = {'data': {'state': 'unknown', 'metadata': {'id': 'ticket'}}}
        chain = [{'type': 'text', 'data': {'text': 'first'}},
                 {'type': 'image', 'data': {'file': 'base64://YQ=='}},
                 {'type': 'text', 'data': {'text': 'third'}}]
        with patch.object(self.w, '_asset', return_value='asset'), self.assertLogs('ob11-bridge', 'WARNING') as log:
            result = self.send(chain)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['data']['error'], {'phase': 'outbox', 'code': 'outbox_unknown'})
        self.assertEqual(result['data']['receipts'], [{'kind': 'text', 'state': 'unknown', 'task': 'ticket'}])
        self.assertIn('普通发送未确认', log.output[-1])
        self.assertIn('未自动重发', log.output[-1])
        self.w.request.assert_called_once()

    def test_restart_recovers_account_native_private_and_group_from_old_pages(self):
        direct = row('known-private', position=2)
        room = row('known-room@chatroom', type_=43, position=503)
        outgoing = row('sent-only', position=600)
        outgoing['payload']['route'].update(sender='me', receiver='sent-only')
        self.w.page = Mock(side_effect=[
            {'data': [outgoing], 'next_cursor': 600},  # snapshot head
            {'data': [direct], 'next_cursor': 2},
            {'data': [room, outgoing], 'next_cursor': 600},
        ])
        self.assertIsNone(self.w.event(outgoing, lambda _: None))
        self.w.request.return_value.json.return_value = {'data': {'state': 'server_accepted'}}
        for name, group in [('known-private', False), ('known-room@chatroom', True), ('sent-only', False)]:
            self.assertEqual(self.send('proactive', name, group)['status'], 'ok')
            self.assertEqual(self.w.request.call_args.kwargs['json']['username'], name)
            self.assertEqual(self.w.request.call_args.kwargs['json']['account_id'], 'test-account')
        self.assertEqual([c.args for c in self.w.page.call_args_list], [(-1, 1), (0,), (2,)])

    def test_unknown_target_never_uses_name_or_another_account(self):
        foreign = row('foreign', position=8)
        foreign['payload']['account_id'] = 'other'
        legacy = row('legacy', position=9)
        legacy['payload'].update(schema_version=2, route=None)
        invalid = row('not-a-member', position=10)
        invalid['payload']['route']['conversation'] = 'actual'
        self.state.get_session_id = Mock(return_value='foreign')
        self.state.get_contact = Mock(return_value='nickname')
        records = {'data': [foreign, legacy, invalid], 'next_cursor': 10}
        self.w.page = Mock(return_value=records)
        for name, group in [('foreign', False), ('legacy', False), ('not-a-member', False), ('friend', True)]:
            result = self.send('hello', name, group)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['data']['error']['code'], 'session_unconfirmed')
        self.w.request.assert_not_called()
        self.state.get_session_id.assert_not_called()
        self.state.get_contact.assert_not_called()

    def test_historical_id_collision_does_not_send(self):
        records = {'data': [row('first', position=1), row('second', position=2)], 'next_cursor': 2}
        self.w.page = Mock(return_value=records)
        with patch('werc_adapter._wxid_to_int', return_value=_wxid_to_int('first')):
            result = self.send('hello', 'first')
        self.assertEqual(result['data']['error']['code'], 'session_unconfirmed')
        self.w.request.assert_not_called()

    def test_http_errors_are_distinct_and_not_retried(self):
        for status, code, phase, path, message in [
            (422, 'invalid_request', 'send', 'messages/send-text', 'hello'),
            (429, 'rate_limited', 'send', 'messages/send-text', 'hello'),
            (415, 'unsupported_media', 'upload', 'media/images',
             [{'type': 'image', 'data': {'file': 'base64://YQ=='}}]),
            (503, 'send_unconfirmed', 'send', 'messages/send-text', 'hello'),
        ]:
            with self.subTest(status=status), self.assertLogs('ob11-bridge', 'WARNING') as log:
                self.w.request.reset_mock(side_effect=True)
                self.w.request.side_effect = WeRCError(path, status)
                result = self.send(message)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['data']['error'], {'code': code, 'phase': phase, 'http_status': status})
                self.assertIn(f'[{phase}/{code}]', log.output[-1])
                self.w.request.assert_called_once()
                self.assertEqual(self.w.request.call_args.args, ('POST', path))
    def test_http_error_preserves_only_safe_upstream_fields(self):
        client = WeRC('http://127.0.0.1:5031', 'test-only', 'test-account')
        cases = [
            ({'error': {'code': 'RECEIVED_MEDIA_INVALID', 'message': 'private content', 'retryable': False}}, 'RECEIVED_MEDIA_INVALID', False),
            ({'error': {'code': 'INVALID\nprivate content', 'retryable': 'false'}}, None, None),
            ({'error': {'code': 'X' * 65, 'retryable': True}}, None, True),
            ({'error': {'retryable': 0}}, None, None),
            ({'error': None}, None, None),
            ([], None, None),
            (ValueError('invalid JSON'), None, None),
        ]
        for body, code, retryable in cases:
            response = Mock(status_code=422)
            if isinstance(body, Exception): response.json.side_effect = body
            else: response.json.return_value = body
            with self.subTest(code=code), patch('werc_adapter.requests.Session') as session:
                session.return_value.__enter__.return_value.request.return_value = response
                with self.assertRaises(WeRCError) as caught:
                    client.request('POST', 'messages/native/7/image')
                self.assertEqual(caught.exception.code, 'invalid_request')
                self.assertEqual(caught.exception.upstream_code, code)
                self.assertIs(caught.exception.retryable, retryable)
                self.assertNotIn('private content', str(caught.exception))
                if code:
                    self.assertIn(code, str(caught.exception))
                    self.assertIn('媒体元数据无效', str(caught.exception))

    def test_download_failure_never_repeats_post_or_reads_after_a_rejected_post(self):
        path = 'messages/native/7/image'
        for method, status, code in [('POST', 422, 'RECEIVED_MEDIA_INVALID'),
                                      ('POST', 429, 'RECEIVED_MEDIA_BUSY'),
                                      ('GET', 503, 'NATIVE_DISCONNECTED')]:
            self.w.request.reset_mock()
            error = WeRCError(path, status, code, retryable=False)
            self.w.request.side_effect = [error] if method == 'POST' else [Mock(), error]
            with self.subTest(method=method, status=status), self.assertRaises(WeRCError) as caught:
                self.w.download_media('werc-image:7')
            self.assertIs(caught.exception, error)
            self.assertEqual([c.args for c in self.w.request.call_args_list],
                             [('POST', path)] if method == 'POST' else [('POST', path), ('GET', path)])

    def test_send_uncertain_keeps_upstream_code(self):
        self.w.request.side_effect = WeRCError('messages/send-text', 503, 'NATIVE_DISCONNECTED')
        with self.assertLogs('ob11-bridge', 'WARNING') as log:
            result = self.send('hello')
        self.assertEqual(result['data']['error'], {
            'phase': 'send', 'code': 'send_unconfirmed', 'http_status': 503,
            'werc_code': 'NATIVE_DISCONNECTED',
        })
        self.assertIn('NATIVE_DISCONNECTED', result['wording'])
        self.assertIn('NATIVE_DISCONNECTED', log.output[-1])
    def test_media_upload_before_submit(self):
        def response(data):m=Mock();m.json.return_value={'data':data};return m
        for kind,plural,endpoint in [('image','images','image'),('file','files','file'),('video','videos','video'),('record','audio','voice')]:
            self.w.request.reset_mock();self.w.request.side_effect=[response({'id':'asset'}),response({'state':'recipient_confirmed'})];r=self.send([{'type':kind,'data':{'file':'base64://YQ=='}}]);self.assertEqual(r['status'],'ok');self.assertEqual([c.args[1] for c in self.w.request.call_args_list],['media/'+plural,'messages/send-'+endpoint]);self.assertEqual(self.w.request.call_args.kwargs['json']['asset_id'],'asset')
    def test_image_content_routes_gif_and_preserves_static_image_route(self):
        with TemporaryDirectory() as folder:
            self.cfg.ASTRBOT_ATTACHMENTS = folder
            local = Path(folder) / 'no-gif-extension.png'
            local.write_bytes(b'GIF87a' + GIF_BYTES[6:])
            cases = [
                ({'file': 'base64://' + GIF_B64, 'name': 'pretend.jpg'}, GIF_BYTES, 'emoticons', 'emoticon', 'pretend.gif'),
                ({'file': str(local)}, local.read_bytes(), 'emoticons', 'emoticon', 'no-gif-extension.gif'),
                ({'file': 'base64:///9j/4A==', 'name': 'pretend.gif'}, b'\xff\xd8\xff\xe0', 'images', 'image', 'pretend.gif'),
                ({'file': 'base64://iVBORw0KGgo='}, b'\x89PNG\r\n\x1a\n', 'images', 'image', 'attachment.png'),
            ]
            for data, raw, upload, send, filename in cases:
                with self.subTest(data=data):
                    self.w.request.reset_mock()
                    self.w.request.side_effect = [Mock(**{'json.return_value': {'data': {'id': 'test-asset'}}}),
                                                  Mock(**{'json.return_value': {'data': {'state': 'server_accepted'}}})]
                    result = self.send([{'type': 'image', 'data': data}])
                    self.assertEqual(result['data']['receipts'][0]['kind'], send)
                    up, post = self.w.request.call_args_list
                    self.assertEqual(up.args, ('POST', 'media/' + upload))
                    expected = (filename, raw, 'image/gif') if send == 'emoticon' else (filename, raw)
                    self.assertEqual(up.kwargs['files'], {'file': expected})
                    self.assertEqual(post.args, ('POST', 'messages/send-' + send))
                    self.assertEqual(post.kwargs['json'], {'account_id': 'test-account', 'username': 'friend', 'asset_id': 'test-asset'})

    def test_gif_after_quote_uses_native_emoticon_route(self):
        self.w.request.side_effect = [Mock(**{'json.return_value': {'data': {'state': 'server_accepted'}}}),
                                      Mock(**{'json.return_value': {'data': {'id': 'test-asset'}}}),
                                      Mock(**{'json.return_value': {'data': {'state': 'queued'}}})]
        result = self.send(quoted() + [{'type': 'image', 'data': {'file': 'base64://' + GIF_B64}}])
        self.assertEqual(result['status'], 'async')
        self.assertEqual([c.args[1] for c in self.w.request.call_args_list],
                         ['messages/send/quote', 'media/emoticons', 'messages/send-emoticon'])

    def test_reject_external_media(self):
        self.assertEqual(self.send([{'type':'file','data':{'file':'https://invalid.invalid/remote'}}])['status'],'failed');self.w.request.assert_not_called()

    def test_exact_quote_for_identical_text_and_cq_string(self):
        self.w.request.return_value.json.return_value = {'data': {'state':'server_accepted'}}
        for chain, position in [(quoted(12), 10), ('[CQ:reply,id=13]reply', 11)]:
            with self.assertLogs('ob11-bridge', 'INFO') as log:
                result = self.send(chain)
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(result['data']['receipts'][0]['kind'], 'quote')
            self.assertIn('原生引用发件箱：server_accepted', log.output[0])
            call = self.w.request.call_args
            self.assertEqual(call.args, ('POST', 'messages/send/quote'))
            body = call.kwargs['json']
            self.assertEqual(body['account_id'], 'test-account')
            self.assertEqual(body['message']['position'], position)
            self.assertEqual(body['message']['server_id'], str(2**53 + position))
            self.assertEqual(body['message']['username'], 'friend')
            self.assertEqual(body['message']['text'], 'reply')
            self.assertNotIn('selection', body['message'])
        self.assertEqual(self.w.request.call_count, 2)

    def test_unavailable_quote_never_becomes_plain_text(self):
        self.messages[14] = {'werc_quote': dict(self.messages[12]['werc_quote'], username='other')}
        self.messages[15] = {'werc_quote': dict(self.messages[12]['werc_quote'], account_id='other')}
        for message in [quoted(0), quoted(999), quoted(14), quoted(15), quoted()[:1], quoted()+quoted(13)]:
            with self.assertLogs('ob11-bridge', 'WARNING') as log:
                result = self.send(message)
            self.assertEqual(result['status'], 'failed')
            self.assertIn('原生引用不可用', log.output[-1])
        self.w.request.assert_not_called()

    def test_uncertain_quote_or_unsupported_api_is_never_retried(self):
        for error, expected in [(None, '原生引用发送未确认'), (requests.Timeout(), '原生引用发送未确认'),
                                (WeRCError('messages/send/quote', 404), '原生引用不可用')]:
            self.w.request.reset_mock()
            self.w.request.side_effect = error
            self.w.request.return_value.json.return_value = {'data': {'state':'unknown'}}
            with self.assertLogs('ob11-bridge', 'INFO') as log:
                result = self.send(quoted() + [{'type':'image','data':{'file':'base64://YQ=='}}])
            self.assertEqual(result['status'], 'failed')
            self.assertIn(expected, log.output[-1])
            self.assertIn('未补发普通文本', result['wording'])
            self.w.request.assert_called_once()
            self.assertEqual(self.w.request.call_args.args, ('POST', 'messages/send/quote'))

    def test_normal_send_and_auto_escaped_cq_are_logged_separately(self):
        self.w.request.return_value.json.return_value = {'data': {'state':'recipient_confirmed'}}
        with self.assertLogs('ob11-bridge', 'INFO') as log:
            text = '[CQ:reply,id=12] literal'
            result = self.w.send_onebot('send_private_msg', {'user_id':_wxid_to_int('friend'),'message':text,'auto_escape':True}, self.state, self.cfg)
        self.assertEqual(result['status'], 'ok')
        self.assertIn('普通发送发件箱：recipient_confirmed', log.output[0])
        self.assertEqual(self.w.request.call_args.kwargs['json']['text'], text)

    def test_missing_server_id_and_media_are_not_quote_sources(self):
        for r in (row(type_=3), row(server_id='0'), row(server_id='-1'), row(server_id=str(2**64))):
            self.assertNotIn('_wercQuote', self.w.event(r, lambda _:None))

    def test_ids_are_not_reused_after_restart(self):
        start = bridge_state._MSG_ID_START
        with TemporaryDirectory() as tmp, patch.object(bridge_state, '_msg_id_path', Path(tmp)/'id'), \
                patch.object(bridge_state, '_msg_id_seq', start), patch.object(bridge_state, '_msg_id_limit', start):
            old = bridge_state.next_message_id()
            self.assertEqual(bridge_state.next_message_id(), old+1)
            with patch.object(bridge_state, '_msg_id_seq', start), patch.object(bridge_state, '_msg_id_limit', start):
                new = bridge_state.next_message_id()
            self.assertGreater(new, old+1)
            self.assertLessEqual(new, 2**31-1)

if __name__=='__main__':unittest.main()
