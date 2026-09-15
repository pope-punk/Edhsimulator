"""Operator lifecycle emits metadata, never a seat decision or hidden packet."""
import io,json
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet.primitive_lifecycle import main,extend_horizon,stopped_prefix
from edh_gauntlet.rules_state import RulesViolation
from edh_gauntlet.runtime_store import read,write


class PrimitiveLifecycleTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'game'
        self.game=PrimitiveCampaign._create(self.path,seed=93,starting_player='Omo')
        self.addCleanup(self.game.close)

    def call(self,*args):
        output=io.StringIO()
        with redirect_stdout(output):main(['--cohort',str(self.path),*args])
        return json.loads(output.getvalue())

    def test_live_status_does_not_open_or_recover_the_engine(self):
        q=self.game.kernel.pending_choice
        self.game.prepare('Omo','prepared',{'kind':'answer','revision':self.game.kernel.revision,
            'request_id':q.request_id,'indexes':[0]},rationale='Synthetic pending input.')
        result=self.call('status')
        self.assertNotIn('hand',str(result));self.assertEqual(0,self.game.store.generation)
        self.assertEqual('prepared',self.game.state()['pending'])

    def test_journal_audit_reports_only_hashes_and_does_not_recover(self):
        q=self.game.kernel.pending_choice
        self.game.prepare('Omo','audit-pending',{'kind':'answer','revision':self.game.kernel.revision,
            'request_id':q.request_id,'indexes':[0]},rationale='Synthetic pending input.')
        result=self.call('verify-journal')
        self.assertTrue(result['verified'])
        self.assertEqual({'verified','host_commit','rules_commit'},set(result))
        self.assertEqual(0,self.game.store.generation)
        self.assertEqual('audit-pending',self.game.state()['pending'])

    def test_pause_marker_does_not_make_a_game_action(self):
        before=self.game.store.committed_head()
        result=self.call('pause','--reason','operator pause')
        self.assertTrue(result['pause_requested'])
        self.assertEqual('operator pause',read(self.path/'HOST_PAUSED.json')['reason'])
        self.assertEqual(before,self.game.store.committed_head())

    def test_explicit_pause_resume_rejects_wrong_prefix(self):
        self.call('pause','--reason','operator pause')
        with self.assertRaisesRegex(RulesViolation,'prefix changed'):
            self.call('resume-pause','--expected-sequence','99','--expected-sha256','wrong')
        self.assertTrue((self.path/'HOST_PAUSED.json').exists())

    def test_fresh_initialization_stays_gated(self):
        with self.assertRaises(RulesViolation):
            main(['--cohort',str(Path(self.tmp.name)/'fresh'),'init','--seed','94',
                  '--starting-player','Omo','--learning','disabled'])
        self.assertFalse((Path(self.tmp.name)/'fresh').exists())

    def test_horizon_extension_is_recorded_once_without_a_game_action(self):
        self.game.kernel.state._turn_number=65
        before=self.game.store.committed_head()
        self.assertEqual('resolve_horizon_stop',self.game.next_action()['kind'])
        receipt=extend_horizon(self.game,expected=before,max_rounds=20)
        self.assertEqual(receipt,extend_horizon(self.game,expected=before,max_rounds=20))
        self.assertEqual(before,self.game.store.committed_head())
        self.assertEqual(16,self.game.config['max_rounds'])
        self.assertEqual('dispatch_pilot',self.game.next_action()['kind'])
        self.assertIsNone(self.game.state()['terminal'])
        for actor in self.game.state()['actors']:
            self.assertEqual(1,len(self.game.evidence(actor,kinds=('horizon_extension',))))

    def test_horizon_extension_preserves_operator_pause_and_claim(self):
        self.game.kernel.state._turn_number=65
        with self.game.transaction() as state:
            state['paused']={'reason':'operator pause'}
            state['claim']={'claim_id':'retained'}
        extend_horizon(self.game,expected=self.game.store.committed_head(),max_rounds=20)
        self.assertEqual('host_paused',self.game.next_action()['reason'])
        self.assertEqual({'claim_id':'retained'},self.game.state()['claim'])

    def test_horizon_extension_rejects_early_terminal_or_pending_changes(self):
        before=self.game.store.committed_head()
        with self.assertRaisesRegex(RulesViolation,'not been reached'):
            extend_horizon(self.game,expected=before,max_rounds=20)
        self.game.kernel.state._turn_number=65
        with self.game.transaction() as state:state['pending']='unreconciled'
        with self.assertRaisesRegex(RulesViolation,'pending input'):
            extend_horizon(self.game,expected=before,max_rounds=20)
        with self.game.transaction() as state:
            state['pending']=None;state['terminal']={'kind':'draw'}
        with self.assertRaisesRegex(RulesViolation,'terminal'):
            extend_horizon(self.game,expected=before,max_rounds=20)

    def test_stopped_transport_requires_binding_and_generation(self):
        head=self.game.store.committed_head()
        process={'active':False,'contexts_unloaded':True,'binding':self.game.binding,
                 'commit':head,'generation':self.game.state()['transport_generation']}
        path=self.path/'host_runtime/process.json'
        write(path,process)
        self.assertEqual(process,stopped_prefix(self.game,head))
        for field,value in [('active',True),('contexts_unloaded',False),('binding',{}),('generation',99)]:
            write(path,{**process,field:value})
            with self.assertRaises(RulesViolation):stopped_prefix(self.game,head)
