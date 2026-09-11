"""Named subtype sets are shared by static and temporary continuous effects."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_subtypes import CREATURE_TYPES,LAND_TYPES,expanded_subtypes
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_characteristics import evaluate,evaluate_exhaustive
from edh_gauntlet.rules_actor import _card

class SubtypeEffectTests(unittest.TestCase):
    def game(self):
        # Only the continuous clauses are modeled here, not Omo's targeting trigger.
        watcher=CardProgram('watcher','Subtype fixture',('Enchantment',),continuous=(
            ContinuousProgram('lands',Selector(Zone.BATTLEFIELD,types=('Land',),counters=(CounterRange('everything'),)),(AddSubtypes('Land',sets=('land',)),)),
            ContinuousProgram('creatures',Selector(Zone.BATTLEFIELD,types=('Creature',),excluded_types=('Land',),counters=(CounterRange('everything'),)),(AddSubtypes('Creature',sets=('creature',)),))))
        animated=CardProgram('animated','Animated',('Land','Creature'),subtypes=('Forest','Elf'),power=2,toughness=2)
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(watcher,animated)
        self.state=RulesState(('A','B'));self.source=self.state.add_card('watcher','watcher','A',Zone.BATTLEFIELD)
        self.land=self.state.add_card('land','catalog:forest','B',Zone.BATTLEFIELD)
        self.creature=self.state.add_card('creature','catalog:elvish-mystic','B',Zone.BATTLEFIELD)
        self.animated=self.state.add_card('animated','animated','B',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def test_counter_selected_categories_apply_across_controllers(self):
        self.game()
        for ref in (self.land,self.creature,self.animated):self.state.add_counters(ref,'everything',1)
        self.assertEqual(LAND_TYPES,self.kernel.effective(self.land).subtypes)
        self.assertEqual(CREATURE_TYPES,self.kernel.effective(self.creature).subtypes)
        self.assertEqual(LAND_TYPES|{'Elf'},self.kernel.effective(self.animated).subtypes)
        self.assertEqual(5,len([a for a in self.kernel.activated_abilities(self.state.get(self.land)) if a.ability_id.startswith('intrinsic-land:')]))
        self.assertTrue(_card(self.kernel,self.state.get(self.creature),self.kernel.characteristics())['all_creature_types'])

    def test_counter_source_departure_and_phasing_remove_continuous_grants(self):
        for phased in (True,False):
            self.game();self.state.add_counters(self.creature,'everything',1)
            if phased:self.state.phase(self.source,True)
            else:self.state.move((ZoneMove(self.source,Zone.HAND),),'scenario_departure')
            self.assertEqual({'Elf','Druid'},set(self.kernel.effective(self.creature).subtypes))
            self.assertEqual({'everything':1},dict(self.state.get(self.creature).counters))

    def test_temporary_named_set_replays_and_expires_without_losing_printed_types(self):
        self.game();self.kernel.execute_for_scenario(self.land,'B',(UntilEndOfTurn('source',(AddSubtypes('Land',sets=('nonbasic_land',)),)),))
        self.assertEqual(LAND_TYPES-{'Island','Swamp','Mountain','Plains'},self.kernel.effective(self.land).subtypes)
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.kernel._finish_cleanup_actions();restored._finish_cleanup_actions()
        self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertEqual({'Forest'},set(self.kernel.effective(self.land).subtypes))

    def test_subtype_dependencies_use_expanded_sets_and_match_reference_layers(self):
        self.game();self.state.add_counters(self.land,'everything',1)
        reader=CardProgram('reader','Reader',('Enchantment',),continuous=(ContinuousProgram('gate',Selector(Zone.BATTLEFIELD,types=('Land',),subtypes=('Gate',)),(ChangeTypes(('Artifact',),()),)),))
        # Earlier reader timestamp must wait for the later effect that grants Gate.
        state=RulesState(('A','B'));state.add_card('reader','reader','A',Zone.BATTLEFIELD)
        state.add_card('watcher','watcher','A',Zone.BATTLEFIELD);land=state.add_card('land','catalog:forest','B',Zone.BATTLEFIELD);state.add_counters(land,'everything',1)
        kernel=RulesKernel(state,self.programs+(reader,))
        self.assertIn('Artifact',kernel.effective(land).types)
        self.assertEqual(evaluate(state.objects(),kernel.definitions),evaluate_exhaustive(state.objects(),kernel.definitions))

    def test_set_validation_and_bounded_immutable_expansion(self):
        effect=AddSubtypes('Land',('Forest',),('nonbasic_land',));self.assertEqual(effect,decode(encode(effect)))
        first=expanded_subtypes(effect.subtypes,effect.sets);self.assertIs(first,expanded_subtypes(effect.subtypes,effect.sets))
        self.assertIsInstance(first,frozenset);self.assertEqual(128,expanded_subtypes.cache_info().maxsize)
        for bad in (AddSubtypes('Land'),AddSubtypes('Land',sets=('creature',)),AddSubtypes('Creature',sets=('land',)),AddSubtypes('Land',sets=['land']),AddSubtypes('Land',sets=('land','land'))):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Sorcery',),spell_effects=(UntilEndOfTurn('source',(bad,)),)))
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Enchantment',),continuous=(ContinuousProgram('bad',Selector(Zone.BATTLEFIELD,types=(bad.card_type,)),(bad,)),)))

if __name__=='__main__':unittest.main()
