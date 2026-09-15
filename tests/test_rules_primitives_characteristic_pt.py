"""Count-based characteristic P/T works in all zones before ordinary setters."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_characteristics import evaluate,evaluate_exhaustive


class CharacteristicPTTests(unittest.TestCase):
    def game(self,zone=Zone.BATTLEFIELD):
        self.programs=tuple(r['program'] for r in load_reviewed().values())
        self.state=RulesState(('A','B'));self.hydra=self.state.add_card('hydra','catalog:ulvenwald-hydra','A',zone)
        self.lands=[self.state.add_card('land'+str(i),'catalog:forest','A',Zone.BATTLEFIELD) for i in range(2)]
        self.state.add_card('otherland','catalog:forest','B',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs)

    def test_all_zones_use_owner_or_current_controller_land_count(self):
        for zone in Zone:
            self.game(zone);view=self.kernel.effective(self.hydra);self.assertEqual((2,2),(view.power,view.toughness))
        self.game();self.state.change_control_batch((self.hydra,),'B');self.assertEqual(1,self.kernel.effective(self.hydra).power)
        self.assertIn('reach',self.kernel.effective(self.hydra).keywords);self.assertNotIn('trample',self.kernel.effective(self.hydra).keywords)

    def test_land_departures_update_stats_and_zero_toughness_state_action(self):
        self.game();self.kernel.execute_for_scenario(self.lands[0],'A',(Move('source',Zone.EXILE),))
        self.assertEqual(1,self.kernel.effective(self.hydra).toughness)
        self.kernel.execute_for_scenario(self.lands[1],'A',(Move('source',Zone.EXILE),))
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('hydra')).zone)
        self.assertEqual(0,self.kernel.effective(self.state.current('hydra')).toughness)

    def test_setters_modifiers_counters_and_cleanup_layer_correctly(self):
        self.game();self.state.add_counters(self.hydra,'+1/+1',1)
        self.kernel.execute_for_scenario(self.hydra,'A',(UntilEndOfTurn('source',(SetPT(7,8),ModifyPT(1,2))),))
        self.state.add_card('third','catalog:forest','A',Zone.BATTLEFIELD)
        view=self.kernel.effective(self.hydra);self.assertEqual((9,11),(view.power,view.toughness))
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        for kernel in (self.kernel,restored):kernel._finish_cleanup_actions()
        self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertEqual(4,self.kernel.effective(self.hydra).power)

    def test_copy_inherits_definition_and_optimized_evaluation_matches(self):
        self.game();copy=self.state.add_card('copy','catalog:forest','B',Zone.HAND)
        self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,copied_definition='catalog:ulvenwald-hydra'),),'fixture-copy')
        self.assertEqual(1,self.kernel.effective(self.state.current('copy')).power)
        self.assertEqual(evaluate(self.state.objects(),self.kernel.definitions),evaluate_exhaustive(self.state.objects(),self.kernel.definitions))

    def test_printed_cast_and_optional_tapped_land_search(self):
        self.game(Zone.HAND);land=self.state.add_card('searchland','catalog:forest','A',Zone.LIBRARY)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('G','G','C','C','C','C'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.hydra),Payment((('G',2),('C',4))))
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)
        q=self.kernel.pending_choice;self.assertEqual('may',q.kind);self.kernel.answer(q.request_id,'A',[0])
        q=self.kernel.pending_choice;self.assertEqual('library_search',q.kind);self.kernel.answer(q.request_id,'A',[0])
        self.assertTrue(self.state.get(self.state.current('searchland')).tapped)
        self.assertEqual(3,self.kernel.effective(self.state.current('hydra')).power);self.assertEqual((),self.state.mana_pool('A'))

    def test_definition_validation_and_codec(self):
        good=CardProgram('good','Good',('Creature',),power=0,toughness=0,characteristic_pt=CountObjects(Selector(Zone.BATTLEFIELD,types=('Land',),relation='controlled')))
        self.assertEqual(good,decode(encode(validate(good))))
        for bad in (replace(good,types=('Artifact',)),replace(good,characteristic_pt=1),replace(good,characteristic_pt=CountObjects(Selector(Zone.HAND))),replace(good,characteristic_pt=CountObjects(Selector(Zone.BATTLEFIELD,characteristics=(CharacteristicRange('power',1),))))):
            with self.assertRaises(RulesViolation):validate(bad)
