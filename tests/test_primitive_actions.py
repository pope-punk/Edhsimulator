"""Only explicit pilot approvals can drive primitive commands or priority passes."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet import primitive_actions as actions
from edh_gauntlet.rules_state import RulesViolation


class PrimitiveActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.game=PrimitiveCampaign._create(Path(self.tmp.name)/'game',seed=93,starting_player='Omo')
        self.addCleanup(self.game.close)
        while self.game.kernel.pending_choice:
            q=self.game.kernel.pending_choice
            self.game.submit(q.actor,'setup:'+q.request_id,
                {'kind':'answer','revision':self.game.kernel.revision,'request_id':q.request_id,
                 'indexes':[0] if q.kind=='mulligan' else []},rationale='Offline fixture initialization.')

    def test_unapproved_priority_never_advances(self):
        before=self.game.store.committed_head()
        self.assertFalse(actions.automatic(self.game))
        self.assertEqual(before,self.game.store.committed_head())

    def test_claim_freezes_plans_and_requires_exact_actor(self):
        claim=actions.claim(self.game,'Omo')
        with self.game.transaction() as state:state['actors']['Omo']['plans']['new']={'id':'later','value':{}}
        self.assertEqual(claim,actions.claim(self.game,'Omo'))
        with self.assertRaises(RulesViolation):actions.claim(self.game,'Elenda')
        with self.assertRaises(RulesViolation):actions.submit(self.game,'Elenda',claim['claim_id'],'wrong',{'kind':'pass'},'Test',{'mode':'hold_full_control'})
        self.assertEqual(4,self.game.store.generation)

    def test_explicit_batch_pass_yields_to_opponent_without_choosing_for_them(self):
        claim=actions.claim(self.game,'Omo')
        actions.approve(self.game,'Omo',claim['claim_id'],approve_ids=[],reject_ids=[],pass_priority=True)
        self.assertTrue(actions.automatic(self.game))
        self.assertNotEqual('Omo',self.game.next_action()['actor'])
        before=self.game.store.committed_head()
        self.assertFalse(actions.automatic(self.game))
        self.assertEqual(before,self.game.store.committed_head())

    def test_batch_opt_out_does_not_pass_and_added_steps_are_validated(self):
        claim=actions.claim(self.game,'Omo')
        with self.assertRaises(RulesViolation):actions.approve(self.game,'Omo',claim['claim_id'],approve_ids=[],reject_ids=[],added=[{'id':'bad'}])
        actions.approve(self.game,'Omo',claim['claim_id'],approve_ids=[],reject_ids=[],pass_priority=False)
        before=self.game.store.committed_head();self.assertFalse(actions.automatic(self.game))
        self.assertEqual(before,self.game.store.committed_head())

    def test_normal_pass_continuation_can_be_explicitly_disabled(self):
        claim=actions.claim(self.game,'Omo')
        actions.approve(self.game,'Omo',claim['claim_id'],approve_ids=[],reject_ids=[],resume_after_passes=False)
        actions.automatic(self.game)
        actor=self.game.next_action()['actor'];claim=actions.claim(self.game,actor)
        actions.submit(self.game,actor,claim['claim_id'],'opponent-pass',{'kind':'pass'},'Offline response.',{'mode':'hold_full_control'})
        self.assertIsNone(self.game.state()['actors']['Omo']['approved'])

    def test_required_choice_is_never_filled_by_automatic_execution(self):
        self.game.close()
        self.game=PrimitiveCampaign._create(Path(self.tmp.name)/'opening',seed=94,starting_player='Omo')
        self.addCleanup(self.game.close)
        with self.game.transaction() as state:
            state['actors']['Omo']['snooze']={'mode':'snooze_table','remaining':1,'time':{'occurrences':1,'edge':'beginning','phase':'upkeep'},'wake_condition':'deadline_only'}
        self.assertFalse(actions.automatic(self.game))
        self.assertEqual(0,self.game.store.generation)
