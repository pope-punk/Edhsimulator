"""Noncreature permanents have no P/T; dormant changes survive animation."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_characteristics import evaluate,evaluate_exhaustive
from edh_gauntlet.rules_bundle import load_reviewed


class NoncreatureStatisticTests(unittest.TestCase):
    def game(self,extra=()):
        vehicle=CardProgram('vehicle','Vehicle',('Artifact',),subtypes=('Vehicle',),power=4,toughness=5)
        self.programs=(vehicle,*extra);self.state=RulesState(('A','B'))
        self.ref=self.state.add_card('vehicle','vehicle','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs)

    def test_printed_stats_exist_outside_battlefield_but_not_on_noncreature_permanent(self):
        self.game();hand=self.state.add_card('hand','vehicle','A',Zone.HAND)
        view=self.kernel.effective(self.ref);self.assertEqual((None,None),(view.power,view.toughness))
        view=self.kernel.effective(hand);self.assertEqual((4,5),(view.power,view.toughness))

    def test_dormant_setter_and_modifier_apply_when_object_becomes_creature(self):
        self.game();self.kernel.execute_for_scenario(self.ref,'A',(UntilEndOfTurn('source',(SetPT(6,6),ModifyPT(1,1))),))
        self.assertIsNone(self.kernel.effective(self.ref).power)
        self.kernel.execute_for_scenario(self.ref,'A',(UntilEndOfTurn('source',(ChangeTypes(add=('Creature',)),)),))
        view=self.kernel.effective(self.ref);self.assertEqual((7,7),(view.power,view.toughness))
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        for kernel in (self.kernel,restored):kernel._finish_cleanup_actions()
        self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertIsNone(self.kernel.effective(self.ref).power)

    def test_characteristic_definition_does_not_give_noncreature_permanent_stats(self):
        programs=tuple(r['program'] for r in load_reviewed().values());state=RulesState(('A','B'))
        ref=state.add_card('hydra','catalog:ulvenwald-hydra','A',Zone.BATTLEFIELD);state.add_card('land','catalog:forest','A',Zone.BATTLEFIELD)
        kernel=RulesKernel(state,programs)
        kernel.execute_for_scenario(ref,'A',(UntilEndOfTurn('source',(ChangeTypes(add=('Artifact',),remove=('Creature',)),)),GainLife(SourceStat('power'))))
        self.assertIsNone(kernel.effective(ref).power);self.assertEqual(40,state.life('A'))

    def test_power_selectors_and_type_dependencies_use_actual_pt_existence(self):
        reader=CardProgram('reader','Reader',('Enchantment',),continuous=(ContinuousProgram('qualified',Selector(Zone.BATTLEFIELD,types=('Artifact',),characteristics=(CharacteristicRange('power',4),)),(ChangeTypes(add=('Enchantment',)),)),))
        animator=CardProgram('animator','Animator',('Enchantment',),continuous=(ContinuousProgram('animate',Selector(Zone.BATTLEFIELD,types=('Artifact',)),(ChangeTypes(add=('Creature',)),)),))
        self.game((reader,animator));self.state.add_card('reader','reader','A',Zone.BATTLEFIELD)
        self.assertNotIn('Enchantment',self.kernel.effective(self.ref).types)
        self.state.add_card('animator','animator','A',Zone.BATTLEFIELD)
        optimized=evaluate(self.state.objects(),self.kernel.definitions);exhaustive=evaluate_exhaustive(self.state.objects(),self.kernel.definitions)
        self.assertEqual(optimized,exhaustive);self.assertIn('Enchantment',optimized[self.ref].types)

    def test_departed_noncreature_does_not_regain_pt_from_its_graveyard_card(self):
        programs=tuple(r['program'] for r in load_reviewed().values());state=RulesState(('A','B'))
        ref=state.add_card('hydra','catalog:ulvenwald-hydra','A',Zone.BATTLEFIELD);state.add_card('land','catalog:forest','A',Zone.BATTLEFIELD)
        kernel=RulesKernel(state,programs)
        kernel.execute_for_scenario(ref,'A',(UntilEndOfTurn('source',(ChangeTypes(add=('Artifact',),remove=('Creature',)),)),Move('source',Zone.GRAVEYARD),GainLife(SourceStat('power'))))
        self.assertEqual(40,state.life('A'));self.assertIsNone(kernel.last_known[ref][1].power)
        self.assertEqual(1,kernel.effective(state.current('hydra')).power)
