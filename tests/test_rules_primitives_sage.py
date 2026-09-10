"""Sage's mana, animation and Gate tap costs compose without card branches."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class SageTests(unittest.TestCase):
    def game(self,zone=Zone.BATTLEFIELD):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(CardProgram('gate','Gate',('Land',),subtypes=('Gate',)),CardProgram('gate-body','Gate Body',('Land','Creature'),subtypes=('Gate',),power=1,toughness=1))
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('sage','catalog:sage-of-the-maze','A',zone)
        self.state.start_turn('A');self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)

    def test_printed_cast_readiness_and_distinct_two_color_bundles(self):
        self.game(Zone.HAND);self.state.add_mana('A',('C','C','G'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.ref),Payment((('C',2),('G',1))));self.drain();self.ref=self.state.current('sage')
        self.kernel.open_window_for_scenario('A')
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('mana','A',self.ref,'mana')
        self.state.start_turn('A');q=self.kernel.commit_action(self.kernel.quote_activation('mana','A',self.ref,'mana'),Payment())
        self.assertEqual(15,len(q.options));self.assertFalse(self.kernel.stack)
        self.kernel.answer(q.request_id,'A',[next(i for i,o in enumerate(q.options) if o.label=='{W}{U}')])
        self.assertEqual((('U',1),('W',1)),self.state.mana_pool('A'))

    def test_gate_count_is_captured_at_resolution_and_types_expire_with_replay(self):
        self.game();target=self.state.add_card('target','gate','A',Zone.BATTLEFIELD)
        self.kernel.commit_action(self.kernel.quote_activation('animate','A',self.ref,'animate',(target,)),Payment())
        self.state.add_card('second','gate','A',Zone.BATTLEFIELD)
        self.state.add_card('opponent','gate','B',Zone.BATTLEFIELD)
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.drain();self.drain(replay.kernel);self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot())
        view=self.kernel.effective(target);self.assertEqual(4,view.power);self.assertEqual({'Land','Creature'},set(view.types));self.assertTrue({'Gate','Citizen'}<=view.subtypes);self.assertIn('haste',view.keywords)
        self.state.add_card('third','gate','A',Zone.BATTLEFIELD);self.assertEqual(4,self.kernel.effective(target).power)
        self.kernel._finish_cleanup_actions();view=self.kernel.effective(target)
        self.assertEqual({'Land'},set(view.types));self.assertEqual({'Gate'},set(view.subtypes));self.assertNotIn('haste',view.keywords)

    def test_tapping_fresh_gate_creature_is_a_valid_cost_and_untaps_on_resolution(self):
        self.game();gate=self.state.add_card('gate','gate-body','A',Zone.BATTLEFIELD)
        self.state.set_tapped_batch((self.ref,),True)
        self.kernel.commit_action(self.kernel.quote_activation('untap','A',self.ref,'untap'),Payment(taps=(gate,)))
        self.assertTrue(self.state.get(gate).tapped);self.assertTrue(self.state.get(self.ref).tapped)
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs);self.drain();self.drain(restored)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertFalse(self.state.get(self.ref).tapped)

    def test_tap_cost_rejects_wrong_type_controller_or_tapped_gate(self):
        for mode in ('land','opponent','tapped'):
            self.game();gate=self.state.add_card('gate','catalog:forest' if mode=='land' else 'gate','B' if mode=='opponent' else 'A',Zone.BATTLEFIELD)
            if mode=='tapped':self.state.set_tapped_batch((gate,),True)
            before=self.kernel.snapshot()
            with self.assertRaises(RulesViolation):self.kernel.commit_action(self.kernel.quote_activation('untap','A',self.ref,'untap'),Payment(taps=(gate,)))
            self.assertEqual(before,self.kernel.snapshot())

    def test_animation_requires_own_land_and_sorcery_timing(self):
        self.game();other=self.state.add_card('other','gate','B',Zone.BATTLEFIELD)
        for target in (self.ref,other):
            with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',self.ref,'animate',(target,))
        target=self.state.add_card('target','gate','A',Zone.BATTLEFIELD);self.kernel.open_window_for_scenario('B',priority_actor='A')
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',self.ref,'animate',(target,))

    def test_zero_gate_animation_dies_to_state_based_actions(self):
        self.game();target=self.state.add_card('land','catalog:forest','A',Zone.BATTLEFIELD)
        self.kernel.commit_action(self.kernel.quote_activation('animate','A',self.ref,'animate',(target,)),Payment());self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('land')).zone)
