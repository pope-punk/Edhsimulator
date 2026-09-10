"""Additive subtype layers feed intrinsic mana, selectors and permissions."""
import unittest
from dataclasses import replace
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_characteristics import evaluate,evaluate_exhaustive
from edh_gauntlet.rules_adapter import RulesActorAdapter


class SubtypeGrantTests(unittest.TestCase):
    def setUp(self):
        self.programs=tuple(r['program'] for r in load_reviewed().values())
        self.state=RulesState(('A','B'));self.kernel=RulesKernel(self.state,self.programs)
    def add(self,key,definition,actor='A',zone=Zone.BATTLEFIELD):return self.state.add_card(key,'catalog:'+definition,actor,zone)

    def test_yavimaya_affects_itself_and_opponents_but_not_other_zones(self):
        source=self.add('yavimaya','yavimaya-cradle-of-growth');enemy=self.add('enemy','island','B')
        hand=self.add('hand','island',zone=Zone.HAND)
        self.assertIn('Forest',self.kernel.effective(source).subtypes)
        self.assertEqual({'Island','Forest'},self.kernel.effective(enemy).subtypes)
        self.assertEqual({'Island'},self.kernel.effective(hand).subtypes)
        self.assertNotIn('Basic',self.kernel.effective(source).supertypes)
        self.assertEqual(frozenset(),self.kernel.effective(source).colors)

    def test_added_forest_confers_real_tap_green_mana_ability(self):
        source=self.add('yavimaya','yavimaya-cradle-of-growth');self.kernel.open_window_for_scenario('A')
        self.kernel.commit_action(self.kernel.quote_activation('mana','A',source,'intrinsic-land:Forest'),Payment())
        self.assertEqual((('G',1),),self.state.mana_pool('A'));self.assertTrue(self.state.get(source).tapped)

    def test_dryad_grants_all_five_only_to_controlled_lands(self):
        self.add('dryad','dryad-of-the-ilysian-grove');own=self.add('own','urza-s-tower');enemy=self.add('enemy','island','B')
        types={'Plains','Island','Swamp','Mountain','Forest'}
        self.assertTrue(types<=self.kernel.effective(own).subtypes)
        self.assertTrue({"Urza's",'Tower'}<=self.kernel.effective(own).subtypes)
        self.assertEqual({'Island'},self.kernel.effective(enemy).subtypes)
        abilities={a.ability_id for a in self.kernel.activated_abilities(self.state.get(own))}
        self.assertTrue({'intrinsic-land:'+s for s in types}<=abilities);self.assertIn('mana',abilities)

    def test_source_departure_removes_grants_but_keeps_original_subtype(self):
        dryad=self.add('dryad','dryad-of-the-ilysian-grove');land=self.add('island','island')
        self.kernel.execute_for_scenario(dryad,'A',(Move('source',Zone.GRAVEYARD),))
        self.assertEqual({'Island'},self.kernel.effective(land).subtypes)
        self.kernel.open_window_for_scenario('A')
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',land,'intrinsic-land:Forest')

    def test_control_and_phasing_change_grant_membership(self):
        dryad=self.add('dryad','dryad-of-the-ilysian-grove');land=self.add('island','island')
        self.state.change_control(dryad,'B');self.assertEqual({'Island'},self.kernel.effective(land).subtypes)
        self.state.change_control(land,'B');self.assertIn('Forest',self.kernel.effective(land).subtypes)
        self.state.phase(dryad,True);self.assertEqual({'Island'},self.kernel.effective(land).subtypes)

    def test_overlapping_sources_retain_subtype_after_one_leaves(self):
        yavimaya=self.add('yavimaya','yavimaya-cradle-of-growth');dryad=self.add('dryad','dryad-of-the-ilysian-grove')
        land=self.add('island','island');self.kernel.execute_for_scenario(dryad,'A',(Move('source',Zone.EXILE),))
        self.assertEqual({'Forest','Island'},self.kernel.effective(land).subtypes)
        self.kernel.execute_for_scenario(yavimaya,'A',(Move('source',Zone.EXILE),));self.assertEqual({'Island'},self.kernel.effective(land).subtypes)

    def test_subtype_dependent_layers_match_exhaustive_evaluation(self):
        early=CardProgram('early','Early',('Enchantment',),continuous=(ContinuousProgram('dependent',
            Selector(Zone.BATTLEFIELD,types=('Land',),subtypes=('Forest',)),(AddSubtypes('Land',('Island',)),)),))
        self.state.add_card('early','early','A',Zone.BATTLEFIELD)
        self.add('yavimaya','yavimaya-cradle-of-growth');land=self.add('tower','urza-s-tower')
        defs={p.definition_id:p for p in self.programs+(early,)}
        fast=evaluate(self.state.objects(),defs);slow=evaluate_exhaustive(self.state.objects(),defs)
        self.assertEqual(slow,fast);self.assertTrue({'Forest','Island'}<=fast[land].subtypes)

    def test_dryad_additional_land_permission_disappears_with_source(self):
        dryad=self.add('dryad','dryad-of-the-ilysian-grove')
        self.assertEqual(2,self.kernel.player_permissions()['A']['land_play_limit'])
        self.assertEqual(1,self.kernel.player_permissions()['B']['land_play_limit'])
        self.state.phase(dryad,True);self.assertEqual(1,self.kernel.player_permissions()['A']['land_play_limit'])

    def test_copied_dryad_inherits_types_and_permissions_and_replays(self):
        self.add('dead','dryad-of-the-ilysian-grove',zone=Zone.GRAVEYARD);land=self.add('land','island')
        copy=self.add('copy','body-double',zone=Zone.HAND);self.kernel.enter(copy,'A')
        request=self.kernel.pending_choice;index=next(i for i,o in enumerate(request.options) if o.ref.card_id=='dead')
        self.kernel.answer(request.request_id,'A',(index,))
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.assertEqual(adapter.packet('A'),replay.packet('A'))
        self.assertIn('Forest',replay.kernel.effective(land).subtypes)
        self.assertEqual(2,replay.kernel.player_permissions()['A']['land_play_limit'])

    def test_invalid_or_untyped_subtype_changes_reject(self):
        for selector,change in [(Selector(Zone.BATTLEFIELD),AddSubtypes('Land',('Forest',))),
                (Selector(Zone.BATTLEFIELD,types=('Land',)),AddSubtypes('Land',())),
                (Selector(Zone.BATTLEFIELD,types=('Land',)),AddSubtypes('Land',('Forest','Forest')))]:
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Enchantment',),
                continuous=(ContinuousProgram('bad',selector,(change,)),)))

    def test_dryad_pays_printed_cost_and_grants_only_after_entry(self):
        dryad=self.add('dryad','dryad-of-the-ilysian-grove',zone=Zone.HAND);land=self.add('land','island')
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('G','C','C'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',dryad),Payment((('G',1),('C',2))))
        self.assertEqual({'Island'},self.kernel.effective(land).subtypes)
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
        self.assertIn('Forest',self.kernel.effective(land).subtypes);self.assertEqual((),self.state.mana_pool('A'))
