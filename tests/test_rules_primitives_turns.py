"""Explicit turn boundaries, special actions, intrinsic mana and readiness."""
import unittest
from dataclasses import replace
from edh_gauntlet.rules_state import RulesState, Zone, ZoneMove, ResourcePayment, RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_turns import TurnActionBoundary
from edh_gauntlet.rules_program import (CardProgram, CostSpec, ActivatedProgram, AddMana,
    AbilityProgram, EventPattern, GainLife, ContinuousProgram, ChangeTypes, SetPT, Selector)
from edh_gauntlet.rules_casting import Payment


class TurnTests(unittest.TestCase):
    def setUp(self):
        self.state = RulesState(('A','B'))
        self.land = CardProgram('land','Forest fixture',('Land',),subtypes=('Forest',))
        self.creature = CardProgram('creature','Creature fixture',('Creature',),power=2,toughness=2,
            activated=(ActivatedProgram('mana',CostSpec(tap_source=True),(AddMana(('G',)),),mana_ability=True),))
        self.definitions = [self.land,self.creature]
        for player in self.state.players:
            for index in range(5): self.state.add_card(player+str(index),'land',player,Zone.LIBRARY)
        self.kernel = RulesKernel(self.state,self.definitions)

    def pass_round(self):
        for _ in self.state.players:
            result = self.kernel.pass_priority(self.kernel.priority)
        return result

    def main_phase(self):
        self.kernel.begin_turn_for_scenario('A'); self.pass_round(); self.pass_round()
        self.assertEqual('precombat_main',self.kernel.phase)

    def end_empty_combat(self):
        self.pass_round(); boundary=self.pass_round()
        self.assertIsInstance(boundary,TurnActionBoundary)
        self.kernel.declare_attackers('A',{},revision=boundary.revision)
        self.pass_round(); self.assertEqual('end_combat',self.kernel.phase)
        self.pass_round(); self.assertEqual('postcombat_main',self.kernel.phase)

    def test_turn_draw_and_main_phase_need_all_priority_passes(self):
        self.kernel.begin_turn_for_scenario('A')
        self.assertEqual('upkeep',self.kernel.phase)
        self.kernel.pass_priority('A'); self.assertEqual('upkeep',self.kernel.phase)
        self.kernel.pass_priority('B'); self.assertEqual('draw',self.kernel.phase)
        self.assertEqual(1,len(self.state.zone('A',Zone.HAND)))
        self.pass_round(); self.assertEqual('precombat_main',self.kernel.phase)
        self.assertEqual([],self.kernel.stack)

    def test_land_special_action_and_intrinsic_mana(self):
        self.main_phase(); source=self.state.zone('A',Zone.HAND)[0].ref
        self.kernel.play_land('land','A',source,revision=self.kernel.revision)
        self.assertEqual([],self.kernel.stack)
        source=self.state.current(source.card_id)
        quote=self.kernel.quote_activation('mana','A',source,'intrinsic-land:Forest')
        self.kernel.commit_action(quote,Payment())
        self.assertEqual((('G',1),),self.state.mana_pool('A'))
        self.assertTrue(self.state.get(source).tapped)
        self.assertFalse(any(e['kind']=='spell_cast' for e in self.kernel.semantic_events))

    def test_no_extra_land_play_and_no_duplicate_submission(self):
        self.main_phase(); source=self.state.zone('A',Zone.HAND)[0].ref
        self.kernel.play_land('land','A',source,revision=self.kernel.revision)
        extra=self.state.add_card('extra','land','A',Zone.HAND)
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.play_land('second','A',extra,revision=self.kernel.revision)
        with self.assertRaises(RulesViolation):self.kernel.play_land('land','A',source,revision=self.kernel.revision)
        self.assertEqual(before,self.kernel.snapshot())

    def test_land_entry_trigger_uses_normal_pipeline(self):
        observer=CardProgram('observer','Land observer',('Enchantment',),abilities=(AbilityProgram('landfall',
            EventPattern('zone_changed',to_zone=Zone.BATTLEFIELD,types=('Land',)),(GainLife(1),)),))
        self.state.add_card('o','observer','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.definitions+[observer]);self.main_phase()
        self.kernel.play_land('land','A',self.state.zone('A',Zone.HAND)[0].ref,revision=self.kernel.revision)
        self.assertEqual(1,len(self.kernel.stack));self.pass_round()
        self.assertEqual(41,self.state.life('A'))

    def test_mana_clears_only_when_the_phase_ends(self):
        self.main_phase();self.state.add_mana('A',('G',))
        self.kernel.pass_priority('A');self.assertEqual((('G',1),),self.state.mana_pool('A'))
        self.kernel.pass_priority('B');self.assertEqual((),self.state.mana_pool('A'))

    def test_summoning_readiness_requires_own_turn_start(self):
        self.state.start_turn('A')
        source=self.state.add_card('elf','creature','A',Zone.BATTLEFIELD)
        self.state.start_turn('B')
        self.assertFalse(self.state.ready_since_turn_start(source))
        self.state.start_turn('A');self.assertTrue(self.state.ready_since_turn_start(source))
        self.kernel.open_window_for_scenario('A')
        self.kernel.commit_action(self.kernel.quote_activation('mana','A',source,'mana'),Payment())
        self.assertEqual((('G',1),),self.state.mana_pool('A'))

    def test_control_loss_and_blink_reset_readiness(self):
        source=self.state.add_card('elf','creature','A',Zone.BATTLEFIELD)
        self.state.start_turn('A');self.assertTrue(self.state.ready_since_turn_start(source))
        self.state.change_control(source,'A');self.assertTrue(self.state.ready_since_turn_start(source))
        self.state.change_control(source,'B');self.state.change_control(source,'A')
        self.assertFalse(self.state.ready_since_turn_start(source))
        self.state.start_turn('A');self.state.move((ZoneMove(source,Zone.EXILE),),'blink-out')
        self.state.move((ZoneMove(self.state.current('elf'),Zone.BATTLEFIELD),),'blink-in')
        self.assertFalse(self.state.ready_since_turn_start(self.state.current('elf')))

    def test_haste_allows_new_creature_mana(self):
        haste=replace(self.creature,keywords=('haste',))
        source=self.state.add_card('elf','creature','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,[self.land,haste]);self.kernel.open_window_for_scenario('A')
        self.kernel.commit_action(self.kernel.quote_activation('mana','A',source,'mana'),Payment())
        self.assertEqual((('G',1),),self.state.mana_pool('A'))

    def test_animated_land_uses_creature_readiness(self):
        effect=CardProgram('animation','Animation',('Enchantment',),continuous=(ContinuousProgram('animate',
            Selector(Zone.BATTLEFIELD,('Land',)),(ChangeTypes(add=('Creature',)),SetPT(2,2))),))
        self.state.add_card('a','animation','A',Zone.BATTLEFIELD)
        source=self.state.add_card('forest','land','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.definitions+[effect]);self.kernel.open_window_for_scenario('A')
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('mana','A',source,'intrinsic-land:Forest')
        self.state.start_turn('A')
        self.assertIsNotNone(self.kernel.quote_activation('mana','A',source,'intrinsic-land:Forest'))

    def test_attack_declaration_requires_an_explicit_valid_mapping(self):
        self.main_phase();self.pass_round();boundary=self.pass_round()
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.pass_priority('A')
        with self.assertRaises(RulesViolation):self.kernel.declare_attackers('A',{'unknown':'B'},revision=boundary.revision)
        self.assertEqual(before,self.kernel.snapshot())
        self.kernel.declare_attackers('A',{},revision=boundary.revision)
        self.assertEqual('declare_attackers',self.kernel.phase)
        self.assertEqual('A',self.kernel.priority)

    def test_cleanup_discards_in_one_choice_and_next_turn_untaps(self):
        source=self.state.add_card('forest','land','B',Zone.BATTLEFIELD)
        self.state.move((),'tap',payment=ResourcePayment('B',taps=(source,)))
        self.main_phase();self.end_empty_combat()
        for index in range(8):self.state.add_card('hand'+str(index),'land','A',Zone.HAND)
        self.pass_round();boundary=self.pass_round()
        self.assertEqual('selection',boundary.kind);self.assertEqual(2,boundary.minimum)
        self.kernel.answer(boundary.request_id,'A',[0,1])
        self.assertEqual(7,len(self.state.zone('A',Zone.HAND)))
        self.assertEqual('B',self.kernel.active);self.assertEqual('upkeep',self.kernel.phase)
        self.assertFalse(self.state.get(source).tapped)

    def test_turn_boundary_restores_without_repeating_draw(self):
        self.kernel.begin_turn_for_scenario('A');self.pass_round()
        restored=RulesKernel.restore(self.kernel.snapshot(),self.definitions)
        self.pass_round();expected=self.kernel.snapshot()
        self.kernel=restored;self.state=restored.state;self.pass_round()
        self.assertEqual(expected,self.kernel.snapshot())
        self.assertEqual(1,len(self.state.zone('A',Zone.HAND)))

    def test_failed_turn_draw_loses_the_game(self):
        for obj in self.state.zone('A',Zone.LIBRARY):
            self.state.move((ZoneMove(obj.ref,Zone.EXILE),),'empty-library-fixture')
        self.kernel.begin_turn_for_scenario('A');self.kernel.pass_priority('A')
        result=self.kernel.pass_priority('B')
        self.assertEqual(('B',),result.winners)
        self.assertEqual(('B',),self.state.live_players)
        self.assertEqual(result,self.kernel.advance())
        self.assertEqual('draw',self.kernel.phase)

    def test_cleanup_trigger_requires_another_priority_round(self):
        observer=CardProgram('o','Cleanup trigger',('Enchantment',),abilities=(AbilityProgram('cleanup',
            EventPattern('step_began',step='cleanup'),(GainLife(1),)),))
        source=self.state.add_card('o','o','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.definitions+[observer]);self.main_phase();self.end_empty_combat()
        self.pass_round();self.pass_round();self.assertEqual('cleanup',self.kernel.phase)
        self.pass_round();self.assertEqual(41,self.state.life('A'))
        self.assertEqual('cleanup',self.kernel.phase);self.assertEqual('A',self.kernel.priority)
        # Remove the repeating source, then all-pass cleanup begins a new cleanup
        # before the next player's turn, rather than skipping that boundary.
        self.state.move((ZoneMove(source,Zone.EXILE),),'response-fixture')
        self.pass_round();self.assertEqual('B',self.kernel.active)
