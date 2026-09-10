"""Tapped-state selection is shared by targets, queries and conditions."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_characteristics import evaluate,evaluate_exhaustive


class OrientationTests(unittest.TestCase):
    def setUp(self):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(CardProgram('body','Body',('Creature',),power=4,toughness=4),)
        self.state=RulesState(('A','B'));self.kernel=RulesKernel(self.state,self.programs)
        self.body=self.state.add_card('body','body','B',Zone.BATTLEFIELD)
        self.spell=self.state.add_card('spell','catalog:deadly-riposte','A',Zone.HAND)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('W','C'))

    def cast(self):
        self.state.set_tapped_batch((self.body,),True)
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.spell,(self.body,)),Payment((('W',1),('C',1))))

    def drain(self):
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)

    def test_damage_and_life_gain_pay_printed_cost(self):
        self.cast();self.drain()
        self.assertEqual(3,self.state.get(self.body).damage_marked);self.assertEqual(42,self.state.life('A'))
        self.assertEqual((),self.state.mana_pool('A'))

    def test_untapped_target_rejected_without_payment(self):
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',self.spell,(self.body,))
        self.assertEqual(before,self.kernel.snapshot())

    def test_target_untapped_in_response_prevents_entire_spell_resolving(self):
        self.cast();self.state.set_tapped_batch((self.body,),False);self.drain()
        self.assertEqual(0,self.state.get(self.body).damage_marked);self.assertEqual(40,self.state.life('A'))
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('spell')).zone)

    def test_orientation_condition_updates_layers_and_matches_exhaustive(self):
        selector=Selector(Zone.BATTLEFIELD,types=('Creature',),tapped=False)
        program=CardProgram('buff','Buff',('Enchantment',),continuous=(ContinuousProgram('boost',selector,(ModifyPT(2,2),)),))
        self.kernel=RulesKernel(self.state,self.programs+(program,));self.state.add_card('buff','buff','A',Zone.BATTLEFIELD)
        for tapped,power in ((False,6),(True,4),(False,6)):
            self.state.set_tapped_batch((self.body,),tapped)
            self.assertEqual(power,self.kernel.effective(self.body).power)
            self.assertEqual(evaluate(self.state.objects(),self.kernel.definitions),evaluate_exhaustive(self.state.objects(),self.kernel.definitions))

    def test_orientation_validation_and_roundtrip(self):
        for selector in (Selector(Zone.BATTLEFIELD,tapped=1),Selector(Zone.GRAVEYARD,tapped=False)):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Sorcery',),spell_targets=TargetSpec(selector)))
        selector=Selector(Zone.BATTLEFIELD,tapped=False)
        self.assertEqual(selector,decode(encode(selector)))
