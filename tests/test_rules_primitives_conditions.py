"""Intervening clauses use occurrence-time evidence and recheck on resolution."""
import unittest
from dataclasses import replace
from edh_gauntlet.rules_state import RulesState, Zone, ZoneMove, RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_program import (CardProgram, AbilityProgram, EventPattern,
    CountCondition, Selector, GainLife, IfCondition, Move, validate)


class ConditionTests(unittest.TestCase):
    def setup_game(self, minimum=2, event=None, condition_in_effect=False):
        self.state = RulesState(('A', 'B'))
        condition = CountCondition(Selector(Zone.BATTLEFIELD, ('Creature',), 'controlled'), minimum)
        self.ability = AbilityProgram('conditional', event or EventPattern('step_began', step='upkeep'),
            (IfCondition(condition, (GainLife(5),)),) if condition_in_effect else (GainLife(5),),
            intervening_if=None if condition_in_effect else condition)
        self.program = CardProgram('source', 'Conditional source', ('Creature',), power=2, toughness=2,
            abilities=(self.ability,))
        self.plain = CardProgram('plain', 'Plain creature', ('Creature',), power=2, toughness=2)
        self.source = self.state.add_card('source', 'source', 'A', Zone.BATTLEFIELD)
        self.other = self.state.add_card('other', 'plain', 'A', Zone.BATTLEFIELD)
        self.kernel = RulesKernel(self.state, (self.program, self.plain))

    def drain(self):
        for _ in range(30):
            boundary = self.kernel.advance()
            if boundary is None: return
            self.kernel.pass_priority(boundary.actor)
        self.fail('Did not settle')

    def test_false_at_event_does_not_trigger_later(self):
        self.setup_game(3)
        self.assertIsNone(self.kernel.begin_step('A', 'upkeep'))
        self.state.add_card('extra', 'plain', 'A', Zone.BATTLEFIELD)
        self.drain(); self.assertEqual(40, self.state.life('A'))
        self.assertTrue(any(e['kind']=='trigger_condition_failed' for e in self.kernel.semantic_events))

    def test_true_at_event_false_at_resolution(self):
        self.setup_game(); self.kernel.begin_step('A', 'upkeep')
        self.state.move((ZoneMove(self.other, Zone.EXILE),), 'response')
        self.drain(); self.assertEqual(40, self.state.life('A'))
        self.assertTrue(any(e['kind']=='intervening_condition_failed' for e in self.kernel.semantic_events))

    def test_condition_uses_trigger_controller_after_source_changes_control(self):
        self.setup_game(1); self.kernel.begin_step('A', 'upkeep')
        self.state.change_control(self.source, 'B')
        self.drain(); self.assertEqual(45, self.state.life('A')); self.assertEqual(40, self.state.life('B'))

    def test_source_can_leave_without_cancelling_an_unrelated_condition(self):
        self.setup_game(1); self.kernel.begin_step('A', 'upkeep')
        self.state.move((ZoneMove(self.source, Zone.EXILE),), 'response')
        self.drain(); self.assertEqual(45, self.state.life('A'))

    def test_condition_inside_effect_is_not_an_intervening_clause(self):
        self.setup_game(3, condition_in_effect=True)
        self.assertIsNotNone(self.kernel.begin_step('A', 'upkeep'))
        self.state.add_card('extra', 'plain', 'A', Zone.BATTLEFIELD)
        self.drain(); self.assertEqual(45, self.state.life('A'))

    def test_effect_condition_checked_at_its_execution_point(self):
        self.setup_game(2)
        condition = self.ability.intervening_if
        self.kernel.execute_for_scenario(self.source, 'A', (
            Move('source', Zone.EXILE), IfCondition(condition, (GainLife(5),))))
        self.assertEqual(40, self.state.life('A'))

    def test_leaves_trigger_uses_pre_event_count_then_current_resolution_count(self):
        self.setup_game(2, EventPattern('zone_changed', from_zone=Zone.BATTLEFIELD, subject='self'))
        boundary = self.kernel.execute_for_scenario(self.source, 'A', (Move('source', Zone.EXILE),))
        self.assertIsNotNone(boundary)
        self.assertTrue(any(e['kind']=='trigger_created' for e in self.kernel.semantic_events))
        self.drain(); self.assertEqual(40, self.state.life('A'))

    def test_entry_condition_includes_the_new_source(self):
        self.setup_game(3, EventPattern('zone_changed', to_zone=Zone.BATTLEFIELD, subject='self'))
        self.state.move((ZoneMove(self.source, Zone.HAND),), 'setup')
        # Source plus two existing creatures meet the condition after entry.
        self.state.add_card('extra', 'plain', 'A', Zone.BATTLEFIELD)
        self.kernel.enter(self.state.current('source'))
        self.drain(); self.assertEqual(45, self.state.life('A'))

    def test_condition_frame_survives_checkpoint(self):
        self.setup_game(); self.kernel.begin_step('A', 'upkeep')
        restored = RulesKernel.restore(self.kernel.snapshot(), (self.program, self.plain))
        self.drain(); expected = self.kernel.snapshot()
        self.kernel = restored; self.state = restored.state; self.drain()
        self.assertEqual(expected, self.kernel.snapshot())

    def test_condition_rejects_hidden_zones_and_invalid_thresholds(self):
        self.setup_game()
        for condition in (CountCondition(Selector(Zone.LIBRARY), 1),
                          CountCondition(Selector(Zone.BATTLEFIELD), -1)):
            with self.assertRaises(RulesViolation):
                validate(replace(self.program, abilities=(replace(self.ability, intervening_if=condition),)))

    def test_simultaneous_entry_condition_observes_the_whole_batch(self):
        from edh_gauntlet.rules_program import Select
        self.setup_game(3, EventPattern('zone_changed', to_zone=Zone.BATTLEFIELD, subject='self'))
        self.state.move((ZoneMove(self.source, Zone.HAND),), 'setup')
        self.state.add_card('extra', 'plain', 'A', Zone.HAND)
        boundary = self.kernel.execute_for_scenario(self.state.current('source'), 'A', (
            Select(Selector(Zone.HAND, ('Creature',)), 2, 2, (Move('selected', Zone.BATTLEFIELD),)),))
        self.assertIsNone(self.kernel.pending_choice)
        self.drain(); self.assertEqual(45, self.state.life('A'))
