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

    def test_executed_proposal_step_cannot_be_approved_again(self):
        step={'id':'pass-once','seat_turn':1,'phase':'precombat_main','command':{'kind':'pass'},
              'rationale':'Synthetic pass proposal.','scheduler':{'mode':'hold_full_control'}}
        with self.game.transaction() as state:
            seat=state['actors']['Omo']
            seat['plans']['actions']={'id':'proposal','value':{'action_sequence':[step]}}
            seat['executed_steps']={'proposal':['pass-once']}
        frozen=actions.claim(self.game,'Omo')
        self.assertEqual(['pass-once'],frozen['executed_steps'])
        before=self.game.store.committed_head()
        with self.assertRaisesRegex(RulesViolation,'already executed'):
            actions.approve(self.game,'Omo',frozen['claim_id'],approve_ids=['pass-once'],reject_ids=[])
        self.assertEqual(before,self.game.store.committed_head())

    def test_own_draw_stops_an_approved_continuation(self):
        with self.game.transaction() as state:
            state['actors']['Omo']['approved']={'resume_after_passes':True}
            state['scheduler_event_cursor']=len(self.game.kernel.semantic_events)
            self.game.kernel.semantic_events.append({'index':len(self.game.kernel.semantic_events)+1,
                                                     'kind':'card_drawn','player':'Omo'})
            actions.observe(self.game,state,'Omo',{'kind':'pass'})
            self.assertIsNone(state['actors']['Omo']['approved'])
            self.game.kernel.semantic_events.pop()

    def approval(self,**changes):
        step={'id':'test-step','seat_turn':1,'phase':'precombat_main','command':{'kind':'pass'},
              'rationale':'Synthetic timing check.','scheduler':{'mode':'hold_full_control'}}
        return {'id':'test-approval','steps':[step],'cursor':0,'turn_limit':2,
                'pass_priority':False,'resume_after_passes':True,'proposal_id':None,**changes}

    def test_matching_phase_on_opponents_turn_does_not_execute_own_step(self):
        actor=self.game.next_action()['actor']
        self.game.kernel.active=next(p for p in self.game.state()['actors'] if p!=actor)
        self.game.kernel.phase='precombat_main'
        with self.game.transaction() as state:
            state['actors'][actor]['turns']=1
            state['actors'][actor]['approved']=self.approval()
        before=self.game.store.committed_head()
        self.assertFalse(actions.automatic(self.game))
        self.assertEqual(before,self.game.store.committed_head())
        self.assertEqual(0,self.game.state()['actors'][actor]['approved']['cursor'])

    def test_missed_phase_clears_sequence_without_passing(self):
        actor=self.game.next_action()['actor'];self.game.kernel.phase='postcombat_main'
        with self.game.transaction() as state:
            state['actors'][actor]['turns']=1
            state['actors'][actor]['approved']=self.approval(pass_priority=True)
        before=self.game.store.committed_head()
        self.assertFalse(actions.automatic(self.game))
        self.assertEqual(before,self.game.store.committed_head())
        self.assertIsNone(self.game.state()['actors'][actor]['approved'])

    def test_nonchronological_added_steps_are_rejected(self):
        frozen=actions.claim(self.game,'Omo')
        first=self.approval()['steps'][0]
        second={**first,'id':'earlier','seat_turn':1}
        first={**first,'seat_turn':2}
        with self.assertRaisesRegex(RulesViolation,'chronological'):
            actions.approve(self.game,'Omo',frozen['claim_id'],approve_ids=[],reject_ids=[],added=[first,second])
        self.assertEqual(frozen['claim_id'],self.game.state()['claim']['claim_id'])

    def test_unsupported_scheduler_is_rejected_before_acceptance(self):
        frozen=actions.claim(self.game,'Omo');before=self.game.store.committed_head()
        with self.assertRaisesRegex(RulesViolation,'not yet available'):
            actions.submit(self.game,'Omo',frozen['claim_id'],'unsupported',{'kind':'pass'},'Test.',
                {'mode':'snooze_objects','objects':['legacy-id'],'time':'1 beginning of upkeep',
                 'wake_condition':'deadline_only'})
        self.assertEqual(before,self.game.store.committed_head())
        self.assertEqual(frozen['claim_id'],self.game.state()['claim']['claim_id'])
