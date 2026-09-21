"""Support sees minimal evidence; lifecycle operations remain fenced and single-shot."""
import importlib.util
import json
from pathlib import Path
import queue
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('bounded_help',Path(__file__).resolve().parents[1]/'tools/run_pilot_help.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)

class FakeServer:
    result={'answer':'Use an object keyed by the supplied source UID.'}
    calls=[]
    def __init__(self, **kwargs):
        self.events=queue.Queue();self.usage={};self.closed=False
        self.events.put({'id':4,'method':'item/tool/call','params':{'threadId':'thread','turnId':'turn','tool':'support_result','arguments':self.result}})
    def call(self, method, params):
        self.calls.append((method,params))
        if method=='turn/interrupt':self.events.put({'method':'turn/completed'})
        return {'thread':{'id':'thread'},'turn':{'id':'turn'}}
    def close(self):self.closed=True

class SupportTests(TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(TemporaryDirectory()));self.run=self.root/'run';self.run.mkdir()
        self.directory=self.root/'support';self.directory.mkdir()
        self.identity={'game':1,'request_id':'request','commit':{'sequence':4,'sha256':'abc'}}
        self.state={'help_request':{'id':'request','commit':self.identity['commit'],'question':'What shape?','intended_action':'Submit damage'},
                    'claim':{'board':{'secret':'never include','decision':{'kind':'combat_damage','specification':{}}},
                             'plans':'secret plan','previous_board':'history'},'paused':{'reason':'pilot_help_requested'}}
        (self.run/'NEXT_ACTION.json').write_text(json.dumps({'next_action':{'kind':'await_pilot_help',**self.identity}}))
        (self.run/'host_runtime').mkdir();(self.run/'host_runtime/process.json').write_text(json.dumps({
            'active':False,'contexts_unloaded':True,'commit':self.identity['commit'],'host_identity':{},'transport_identity':{}}))
    def test_packet_has_schema_without_board_history_or_plans(self):
        value=helper.packet(self.state,{'automatic_decider_mana':1,'pilot_document':1})
        self.assertIn('damage_schema',value);self.assertIn('damage',value['command_fields'])
        self.assertNotIn('secret',json.dumps(value));self.assertNotIn('previous_board',value)
        self.assertLess(len(json.dumps(value)),6000)
    def test_oversized_evidence_escalates_without_truncating(self):
        self.state['claim']['rejection']='x'*25000
        with self.assertRaisesRegex(RuntimeError,'exceeds'):helper.packet(self.state,{})
    def test_model_has_one_tool_no_repository_or_execution(self):
        FakeServer.calls=[];FakeServer.result={'answer':'Technical clarification'}
        result,metrics=helper.infer({'question':'schema'},factory=FakeServer)
        params=FakeServer.calls[0][1]
        self.assertTrue(params['cwd'].startswith('/tmp/edh-support-'))
        self.assertEqual(['support_result'],[t['name'] for t in params['dynamicTools']])
        self.assertTrue(all(v is False for v in params['config']['features'].values()))
        self.assertEqual('turn/interrupt',FakeServer.calls[-1][0]);self.assertEqual(1,metrics['tool_calls'])
    def test_invalid_result_and_escalation(self):
        FakeServer.result={'answer':'x','escalate':'y'}
        with self.assertRaisesRegex(RuntimeError,'Invalid'):helper.infer({},factory=FakeServer)
        FakeServer.result={'escalate':'Missing engine fact'}
        self.assertIn('escalate',helper.infer({},factory=FakeServer)[0])
    def test_guard_stale_paused_active_or_blocked(self):
        with patch.object(helper,'state_at',return_value=self.state),patch.object(helper,'verify_exited'):
            helper.guard(self.run,self.directory,self.identity)
            self.state['help_request']['id']='other'
            with self.assertRaisesRegex(RuntimeError,'stale'):helper.guard(self.run,self.directory,self.identity)
            self.state['help_request']['id']='request';self.state['blocker']={'reason':'rules'}
            with self.assertRaisesRegex(RuntimeError,'blocker'):helper.guard(self.run,self.directory,self.identity)
            self.state.pop('blocker');(self.run/'HOST_PAUSED.json').write_text('{}')
            with self.assertRaisesRegex(RuntimeError,'operator'):helper.guard(self.run,self.directory,self.identity)
    def test_resume_timeout_never_retries_answer_or_post(self):
        key=self.root/'key';key.write_text('secret')
        with patch.object(helper,'guard'),patch.object(helper.subprocess,'run') as command,patch.object(helper.urllib.request,'urlopen',side_effect=TimeoutError) as post:
            with self.assertRaises(TimeoutError):helper.recover(self.run,self.directory,self.identity,{'answer':'schema'},'http://localhost',key,self.directory/'receipt.json')
            self.assertEqual(1,command.call_count);self.assertEqual(1,post.call_count)
    def test_stop_between_answer_and_resume_prevents_post(self):
        with patch.object(helper,'guard',side_effect=[self.state,RuntimeError('operator stop')]),patch.object(helper.subprocess,'run') as command,patch.object(helper.urllib.request,'urlopen') as post:
            with self.assertRaisesRegex(RuntimeError,'operator'):helper.recover(self.run,self.directory,self.identity,{'answer':'schema'},'http://localhost',self.root/'key',self.directory/'receipt.json')
            self.assertEqual(1,command.call_count);post.assert_not_called()
