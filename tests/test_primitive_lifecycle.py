"""Operator lifecycle emits metadata, never a seat decision or hidden packet."""
import io,json
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet.primitive_lifecycle import main
from edh_gauntlet.rules_state import RulesViolation
from edh_gauntlet.runtime_store import read


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
