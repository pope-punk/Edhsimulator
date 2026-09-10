"""Common target permissions at announcement, trigger placement and resolution."""
import unittest
from dataclasses import replace
from edh_gauntlet.rules_program import (CardProgram, TargetRestriction, CastSpec,
    CostSpec, Selector, TargetSpec, Move, AbilityProgram, EventPattern, Select, validate)
from edh_gauntlet.rules_state import RulesState, Zone, ZoneMove, RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment


class PermissionTests(unittest.TestCase):
    def setup_game(self, opponents_only=True, controller='B', zone=Zone.BATTLEFIELD):
        self.state = RulesState(('A', 'B'))
        self.creature = CardProgram('protected', 'Protected fixture', ('Creature',), power=2, toughness=2,
            target_restrictions=(TargetRestriction(opponents_only),))
        self.spell = CardProgram('spell', 'Targeted fixture', ('Instant',), cast=CastSpec(CostSpec(), 'instant'),
            spell_targets=TargetSpec(Selector(zone)), spell_effects=(Move('target', Zone.EXILE),))
        self.source = self.state.add_card('s', 'spell', 'A', Zone.HAND)
        self.target = self.state.add_card('p', 'protected', 'B', zone, controller=controller)
        self.kernel = RulesKernel(self.state, (self.creature, self.spell))
        self.kernel.open_window_for_scenario('A')

    def drain(self):
        for _ in range(30):
            boundary = self.kernel.advance()
            if boundary is None: return
            self.kernel.pass_priority(boundary.actor)
        self.fail('Did not settle')

    def test_hexproof_uses_controller_and_allows_own_target(self):
        self.setup_game()
        with self.assertRaises(RulesViolation): self.kernel.quote_cast('x', 'A', self.source, (self.target,))
        self.state.change_control(self.target, 'A')
        quote = self.kernel.quote_cast('x', 'A', self.source, (self.target,))
        self.kernel.commit_action(quote, Payment()); self.drain()
        self.assertEqual(Zone.EXILE, self.state.get(self.state.current('p')).zone)

    def test_shroud_blocks_both_controllers_and_scenario_adapter(self):
        self.setup_game(False, 'A')
        for call in (lambda: self.kernel.quote_cast('x', 'A', self.source, (self.target,)),
                     lambda: self.kernel.stage_spell_for_scenario(self.source, 'A', (self.target,))):
            before = self.kernel.snapshot()
            with self.assertRaises(RulesViolation): call()
            self.assertEqual(before, self.kernel.snapshot())

    def test_hexproof_and_shroud_in_graveyard_do_not_block_targets(self):
        for opponents_only in (False, True):
            self.setup_game(opponents_only, zone=Zone.GRAVEYARD)
            self.kernel.commit_action(self.kernel.quote_cast('x', 'A', self.source, (self.target,)), Payment())
            self.drain(); self.assertEqual(Zone.EXILE, self.state.get(self.state.current('p')).zone)

    def test_control_change_revalidates_resolution_targets(self):
        self.setup_game(controller='A')
        self.kernel.commit_action(self.kernel.quote_cast('x', 'A', self.source, (self.target,)), Payment())
        self.state.change_control(self.target, 'B')
        self.drain()
        self.assertEqual(Zone.BATTLEFIELD, self.state.get(self.target).zone)
        self.assertTrue(any(e['kind']=='all_targets_illegal' for e in self.kernel.semantic_events))

    def test_trigger_target_menu_filters_permissions(self):
        self.setup_game()
        observer = CardProgram('observer', 'Observer', ('Artifact',), abilities=(
            AbilityProgram('upkeep', EventPattern('step_began', step='upkeep', controller_only=True),
                (Move('target', Zone.EXILE),), TargetSpec(Selector(Zone.BATTLEFIELD, ('Creature',)))),))
        self.state.add_card('o', 'observer', 'A', Zone.BATTLEFIELD)
        self.kernel = RulesKernel(self.state, (self.creature, self.spell, observer))
        self.assertIsNone(self.kernel.begin_step('A', 'upkeep'))
        self.assertTrue(any(e['kind']=='trigger_unplaceable' for e in self.kernel.semantic_events))

    def test_nontargeted_selection_is_not_blocked(self):
        self.setup_game(False)
        boundary = self.kernel.execute_for_scenario(self.source, 'A', (
            Select(Selector(Zone.BATTLEFIELD), 1, 1, (Move('selected', Zone.EXILE),)),))
        self.assertIsNone(boundary)
        self.assertEqual(Zone.EXILE, self.state.get(self.state.current('p')).zone)

    def test_entry_copy_inherits_target_restrictions(self):
        self.setup_game()
        original = CardProgram('plain', 'Plain fixture', ('Creature',), power=2, toughness=2)
        ref = self.state.add_card('copy', 'plain', 'B', Zone.HAND)
        self.state.move((ZoneMove(ref, Zone.BATTLEFIELD, 'B', copied_definition='protected'),), 'copy-fixture')
        self.kernel = RulesKernel(self.state, (self.creature, self.spell, original))
        self.kernel.open_window_for_scenario('A')
        with self.assertRaises(RulesViolation):
            self.kernel.quote_cast('x', 'A', self.source, (self.state.current('copy'),))
        restored = RulesKernel.restore(self.kernel.snapshot(), (self.creature, self.spell, original))
        self.assertEqual(self.kernel.characteristics(), restored.characteristics())

    def test_reject_unreviewed_restriction_values(self):
        self.setup_game()
        with self.assertRaises(RulesViolation):
            validate(replace(self.creature, target_restrictions=(TargetRestriction('ward'),)))
