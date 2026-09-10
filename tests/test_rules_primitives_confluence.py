"""A life-payment mana land composes existing costs, choices and state actions."""
import unittest
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter


class ConfluenceTests(unittest.TestCase):
    def game(self,life=40):
        self.programs=tuple(r['program'] for r in load_reviewed().values())
        self.state=RulesState(('A','B','C'));self.ref=self.state.add_card('land','catalog:mana-confluence','A',Zone.BATTLEFIELD)
        self.state.lose_life_batch(('A',),40-life)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def activate(self):
        return self.kernel.commit_action(self.kernel.quote_activation('mana','A',self.ref,'mana'),Payment())

    def test_all_colors_pay_life_and_tap_once_then_resume_from_checkpoint(self):
        for index,symbol in enumerate('WUBRG'):
            self.game();request=self.activate()
            self.assertEqual(39,self.state.life('A'));self.assertTrue(self.state.get(self.ref).tapped)
            self.assertFalse(self.kernel.stack);self.assertEqual((),self.state.mana_pool('A'))
            self.assertEqual('mana_choice',request.kind)
            restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
            for k in (self.kernel,restored):k.answer(request.request_id,'A',[index])
            self.assertEqual(self.kernel.snapshot(),restored.snapshot())
            self.assertEqual(((symbol,1),),self.state.mana_pool('A'));self.assertEqual('A',self.kernel.priority)
            self.assertFalse(any(e['kind']=='damage_dealt' for e in self.kernel.semantic_events))

    def test_zero_life_and_tapped_source_reject_before_mutation(self):
        for life,tapped in ((0,False),(40,True)):
            self.game(life);self.state.set_tapped_batch((self.ref,),tapped);before=self.kernel.snapshot()
            with self.assertRaises(RulesViolation):self.activate()
            self.assertEqual(before,self.kernel.snapshot())

    def test_one_life_payment_finishes_mana_choice_before_departure(self):
        self.game(1);request=self.activate()
        self.assertEqual(0,self.state.life('A'));self.assertIn('A',self.state.live_players)
        self.assertIsNotNone(self.kernel.resolving)
        self.kernel.answer(request.request_id,'A',[0])
        self.assertNotIn('A',self.state.live_players);self.assertIsNone(self.kernel.resolving)
        self.assertEqual(1,len(self.kernel.action_receipts))

    def test_actor_replay_includes_paid_choice_and_rejects_duplicate(self):
        self.game();adapter=RulesActorAdapter(self.kernel)
        adapter.submit('A',{'kind':'activate','revision':self.kernel.revision,'action_id':'mana','source':self.ref.to_json(),'ability_id':'mana','targets':[],'x_value':0,'payment':{'mana':{},'taps':[]}})
        request=self.kernel.pending_choice
        command={'kind':'answer','revision':self.kernel.revision,'request_id':request.request_id,'indexes':[4]}
        adapter.submit('A',command);before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):adapter.submit('A',command)
        self.assertEqual(before,self.kernel.snapshot())
        replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        for actor in ('A','B','C'):self.assertEqual(adapter.packet(actor),replay.packet(actor))
