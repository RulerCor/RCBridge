"""Offline adapter contract checks. No network, secrets or WeChat required."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bridge'))
from werc_adapter import WeRC, sse_events


def row(peer='friend',type_=1):
    return {'position':7,'payload':{'schema_version':3,'account_id':'test-account','id':'msg7','target_id':peer,'sender_id':'me','route':{'sender':peer,'receiver':'me','conversation':peer},'message':{'message_type':type_,'text':'hello'}}}

class Contract(unittest.TestCase):
    def setUp(self):
        self.w=WeRC('http://127.0.0.1:5031/api/v1','test-only','test-account');self.w.request=Mock()
        self.state=NS(get_session_id=lambda uid:'friend' if uid==7 else None,get_member_name=lambda uid:None)
        self.cfg=NS(MENTION_AS_TEXT=True,QUOTE_REPLY_PREFIX=False,ASTRBOT_ATTACHMENTS='')
    def send(self,msg):return self.w.send_onebot('send_private_msg',{'user_id':7,'message':msg},self.state,self.cfg)
    def test_normalize_export(self):self.assertEqual(self.w.base_url,'http://127.0.0.1:5031')
    def test_refuse_nonlocal(self):
        for url in ['https://example.com','http://127.0.0.1@other.invalid','http://localhost/api?x=1']:
            with self.assertRaises(ValueError):WeRC(url,'T','A')
    def test_private(self):self.assertEqual(self.w.event(row(),lambda _:None)['senderWxid'],'friend')
    def test_group_envelope(self):
        d=self.w.event(row('group@chatroom'),lambda _:'room');self.assertTrue(d['_roomEnvelope']);self.assertFalse(d['senderWxid'])
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
        self.w.request.return_value.json.return_value={'data':{'state':'unknown'}};self.assertEqual(self.send('hello')['status'],'failed');self.assertEqual(self.w.request.call_count,1)
    def test_unknown_target_never_sent(self):
        self.state.get_session_id=lambda uid:None;self.assertEqual(self.send('hello')['status'],'failed');self.w.request.assert_not_called()
    def test_media_upload_before_submit(self):
        def response(data):m=Mock();m.json.return_value={'data':data};return m
        for kind,plural,endpoint in [('image','images','image'),('file','files','file'),('video','videos','video'),('record','audio','voice')]:
            self.w.request.reset_mock();self.w.request.side_effect=[response({'id':'asset'}),response({'state':'recipient_confirmed'})];r=self.send([{'type':kind,'data':{'file':'base64://YQ=='}}]);self.assertEqual(r['status'],'ok');self.assertEqual([c.args[1] for c in self.w.request.call_args_list],['media/'+plural,'messages/send-'+endpoint]);self.assertEqual(self.w.request.call_args.kwargs['json']['asset_id'],'asset')
    def test_reject_external_media(self):
        self.assertEqual(self.send([{'type':'file','data':{'file':'https://invalid.invalid/remote'}}])['status'],'failed');self.w.request.assert_not_called()

if __name__=='__main__':unittest.main()
