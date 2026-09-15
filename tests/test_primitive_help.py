"""Technical help preserves the decision, prefix and logical pilot ownership."""
import io,json
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet import primitive_actions as actions,primitive_planning as planning
from edh_gauntlet.primitive_help import request,answer
from edh_gauntlet.primitive_lifecycle import main
from edh_gauntlet.rules_state import RulesViolation
from edh_gauntlet.runtime_store import write
from edh_gauntlet.primitive_host import PrimitiveRunner
from test_primitive_host import FakeServer


class HelpTests(TestCase):
    def setUp(self):
        self.temp=self.enterContext(TemporaryDirectory())
        self.game=PrimitiveCampaign._create(Path(self.temp)/'game',seed=93,starting_player='Omo')
        self.addCleanup(self.game.close)
        self.claim=actions.claim(self.game,'Omo');self.prefix=self.game.store.committed_head()
        self.question={'intended_action':'Choose whether to keep this synthetic hand.','question':'What is the answer command format?'}

    def ask(self):return request(self.game,'Omo',self.claim['claim_id'],'help-1',self.question)

    def respond(self,**kw):
        return answer(self.game,expected=kw.get('expected',self.prefix),request_id=kw.get('request_id','help-1'),
                      response=kw.get('response',{'answer':'Use kind answer with the supplied request_id and selected indexes.'}))

    def resume(self):
        with redirect_stdout(io.StringIO()):main(['--cohort',str(self.game.root),'resume-pause',
            '--expected-sequence',str(self.prefix['sequence']),'--expected-sha256',self.prefix['sha256']])
        self.game.close();self.game._reopen()

    def test_help_preserves_prefix_claim_approvals_and_snoozes_without_terminal(self):
        with self.game.transaction() as state:
            state['actors']['Elenda']['snooze']={'fixture':'retained'}
            state['actors']['Elenda']['approved']={'fixture':'retained'}
        old=self.game.state();self.ask();state=self.game.state()
        self.assertEqual(self.prefix,self.game.store.committed_head())
        self.assertEqual(old['claim'],state['claim']);self.assertEqual(old['actors'],state['actors'])
        self.assertIsNone(state['terminal']);self.assertIsNone(state['blocker'])
        self.assertEqual('await_pilot_help',self.game.next_action()['kind'])
        with self.assertRaises(RulesViolation):planning.claim(self.game,'Omo',planning.SHORT)
        q=self.game.kernel.pending_choice
        with self.assertRaises(RulesViolation):self.game.submit('Omo','must-not-run',
            {'kind':'answer','revision':self.game.kernel.revision,'request_id':q.request_id,'indexes':[0]},rationale='Fixture.')
        with self.assertRaisesRegex(RulesViolation,'help request'):self.resume()

    def test_wrong_owner_and_stale_claim_cannot_request_help(self):
        before=self.game.state()
        for actor,claim in [('Elenda',self.claim['claim_id']),('Omo','stale')]:
            with self.assertRaises(RulesViolation):request(self.game,actor,claim,'bad',self.question)
        self.assertEqual(before,self.game.state())

    def test_answer_is_bound_and_idempotent_and_does_not_execute(self):
        self.ask()
        for kwargs in ({'request_id':'wrong'},{'expected':{**self.prefix,'sequence':999}},
                       {'response':{'answer':'Explain.','command':{'kind':'pass'}}}):
            with self.assertRaises(RulesViolation):self.respond(**kwargs)
        receipt=self.respond();self.assertEqual(receipt,self.respond())
        with self.assertRaises(RulesViolation):self.respond(response={'answer':'Changed answer.'})
        state=self.game.state();self.assertEqual('pilot_help_answered',state['paused']['reason'])
        self.assertEqual(self.prefix,self.game.store.committed_head());self.assertIsNone(state['terminal'])
        self.assertEqual(self.claim['claim_id'],state['claim']['claim_id'])
        self.assertEqual('Omo',state['claim']['technical_help']['actor'])

    def test_explicit_resume_returns_help_to_same_pilot_and_advances_only_its_choice(self):
        self.ask();self.respond();self.resume()
        claim=actions.claim(self.game,'Omo')
        self.assertEqual(self.claim['claim_id'],claim['claim_id']);self.assertIn('technical_help',claim)
        q=self.game.kernel.pending_choice
        actions.submit(self.game,'Omo',claim['claim_id'],'pilot-choice',
            {'kind':'answer','request_id':q.request_id,'indexes':[0]},'Synthetic pilot-authored keep.',{'mode':'hold_full_control'})
        self.assertEqual(self.prefix['sequence']+1,self.game.store.generation)
        other=self.game.next_action()['actor'];self.assertNotEqual('Omo',other)
        self.assertNotIn('technical_help',actions.claim(self.game,other))

    def test_help_answer_preserves_independent_operator_pause(self):
        self.ask();self.game.pause('user_stop');self.respond()
        self.assertEqual('user_stop',self.game.state()['paused']['reason'])
        self.assertEqual('host_paused',self.game.next_action()['reason'])

    def test_active_transport_cannot_be_answered(self):
        self.ask();write(self.game.root/'host_runtime/process.json',{'active':True,'contexts_unloaded':False})
        with self.assertRaisesRegex(RulesViolation,'Stop and unload'):self.respond()

    def test_host_help_tool_stops_instead_of_sealing(self):
        server=FakeServer();runner=PrimitiveRunner(self.game,server);self.addCleanup(runner.timing.close)
        runner.pump();thread=runner.lanes[('Omo','decider')]
        runner.handle({'id':'help-call','method':'item/tool/call','params':{'threadId':thread,
            'turnId':runner.running[thread],'callId':'help-call','tool':'edh_request_help','arguments':self.question}})
        self.assertTrue(runner.done);self.assertIsNone(self.game.state()['terminal'])
        self.assertEqual('pilot_help_requested',server.replies[-1][1]['reason'])
        self.assertEqual(self.prefix,self.game.store.committed_head())

    def test_operator_cli_round_trip_persists_request_and_answer(self):
        self.ask();self.game.close();self.game._reopen()
        out=io.StringIO()
        with redirect_stdout(out):main(['--cohort',str(self.game.root),'help-status'])
        status=json.loads(out.getvalue());self.assertEqual(self.question['question'],status['request']['question'])
        response=Path(self.temp)/'response.json';response.write_text(json.dumps({'answer':'Use the current choice request_id and selected indexes.'}))
        with redirect_stdout(io.StringIO()):main(['--cohort',str(self.game.root),'answer-help',
            '--request-id','help-1','--response',str(response),'--expected-sequence',str(self.prefix['sequence']),
            '--expected-sha256',self.prefix['sha256']])
        self.assertEqual(self.prefix,self.game.store.committed_head())
        self.assertIsNone(self.game.state().get('help_request'))
        self.assertEqual('host_paused',self.game.next_action()['reason'])
        self.assertEqual('help-1',self.game.state()['claim']['technical_help']['id'])
