"""Authored casting/payment cases; these do not certify full card programs."""
import unittest
from dataclasses import replace
from edh_gauntlet.rules_program import (CardProgram, CastSpec, CostSpec, ManaCost,
    ActivatedProgram, AddMana, GainLife, Selector, TargetSpec, CostModifier,
    AbilityProgram, EventPattern)
from edh_gauntlet.rules_state import RulesState, Zone, ZoneMove, RulesViolation, ResourcePayment, ObjectRef
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment, PreparedAction


class CastingTests(unittest.TestCase):
    def setup_game(self, cost=CostSpec(ManaCost(1, ('U',))), **kwargs):
        self.program = CardProgram('spell', 'Test instant', ('Instant',), mana_value=2,
            cast=CastSpec(cost, 'instant'), spell_effects=(GainLife(3),), **kwargs)
        self.state = RulesState(('A', 'B'))
        self.source = self.state.add_card('s', 'spell', 'A', Zone.HAND)
        self.kernel = RulesKernel(self.state, (self.program,))
        self.kernel.open_window_for_scenario('A')
        self.state.add_mana('A', ('U', 'C', 'C', 'G'))
        return self.kernel.quote_cast('cast-1', 'A', self.source)

    def drain(self):
        for _ in range(30):
            boundary = self.kernel.advance()
            if boundary is None: return
            self.kernel.pass_priority(boundary.actor)
        self.fail('Did not settle')

    def test_quote_is_pure_and_payment_resolves(self):
        quote = self.setup_game()
        before = self.kernel.snapshot()
        self.assertEqual(quote, self.kernel.quote_cast('cast-1', 'A', self.source))
        self.assertEqual(before, self.kernel.snapshot())
        self.kernel.commit_action(quote, Payment((('U', 1), ('C', 1))))
        self.assertEqual({'C': 1, 'G': 1}, dict(self.state.mana_pool('A')))
        self.assertEqual(40, self.state.life('A'))
        self.drain()
        self.assertEqual(43, self.state.life('A'))
        self.assertEqual(Zone.GRAVEYARD, self.state.get(self.state.current('s')).zone)

    def test_bad_payments_do_not_mutate(self):
        quote = self.setup_game()
        for mana in ((('C', 2),), (('U', 1),), (('U', 1), ('C', 2)),
                     (('U', 1), ('U', 1)), (('U', -1), ('C', 3))):
            before = self.kernel.snapshot()
            with self.assertRaises(RulesViolation): self.kernel.commit_action(quote, Payment(mana))
            self.assertEqual(before, self.kernel.snapshot())

    def test_forged_stale_and_replayed_quotes_rejected(self):
        quote = self.setup_game()
        with self.assertRaises(RulesViolation):
            self.kernel.commit_action(replace(quote, cost=CostSpec()), Payment())
        self.state.add_mana('A', ('U',))
        with self.assertRaises(RulesViolation): self.kernel.commit_action(quote, Payment((('U', 2),)))
        quote = self.kernel.quote_cast('cast-1', 'A', self.source)
        self.kernel.commit_action(quote, Payment((('U', 2),)))
        restored = RulesKernel.restore(self.kernel.snapshot(), (self.program,))
        before = restored.snapshot()
        with self.assertRaises(RulesViolation): restored.commit_action(quote, Payment((('C', 2),)))
        self.assertEqual(before, restored.snapshot())

    def test_quote_round_trip_and_checkpoint_commit_parity(self):
        quote = self.setup_game()
        restored = RulesKernel.restore(self.kernel.snapshot(), (self.program,))
        payment = Payment.from_json({'mana': {'U': 1, 'C': 1}, 'taps': []})
        restored.commit_action(PreparedAction.from_json(quote.to_json()), payment)
        self.kernel.commit_action(quote, payment)
        self.assertEqual(self.kernel.snapshot(), restored.snapshot())

    def test_colorless_symbol_and_x_value(self):
        quote = self.setup_game(CostSpec(ManaCost(0, ('C',), 2)))
        quote = self.kernel.quote_cast('x', 'A', self.source, x_value=1)
        self.assertEqual(2, quote.cost.mana.generic)
        self.kernel.commit_action(quote, Payment((('C', 2), ('U', 1))))
        self.assertEqual(4, self.kernel.effective(self.state.current('s')).mana_value)
        self.drain()
        self.assertEqual(2, self.kernel.effective(self.state.current('s')).mana_value)

    def test_sorcery_timing_and_target_permissions(self):
        self.setup_game()
        sorcery = replace(self.program, cast=CastSpec(self.program.cast.cost))
        kernel = RulesKernel(self.state, (sorcery,))
        kernel.open_window_for_scenario('B', priority_actor='A')
        with self.assertRaises(RulesViolation): kernel.quote_cast('x', 'A', self.source)
        kernel.open_window_for_scenario('A', phase='upkeep')
        with self.assertRaises(RulesViolation): kernel.quote_cast('x', 'A', self.source)
        kernel.open_window_for_scenario('A')
        self.assertIsNotNone(kernel.quote_cast('x', 'A', self.source))
        targeted = replace(self.program, spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD)))
        kernel = RulesKernel(self.state, (targeted,)); kernel.open_window_for_scenario('A')
        with self.assertRaises(RulesViolation): kernel.quote_cast('x', 'A', self.source, (self.source,))

    def test_generic_modifiers_preserve_colored_cost(self):
        self.setup_game()
        reducer = CardProgram('reducer', 'Reducer', ('Artifact',), cost_modifiers=(
            CostModifier('reduce', Selector(Zone.STACK, relation='controlled'), -5),))
        self.state.add_card('r', 'reducer', 'A', Zone.BATTLEFIELD)
        self.kernel = RulesKernel(self.state, (self.program, reducer))
        self.kernel.open_window_for_scenario('A'); self.state.add_mana('A', ('U',))
        quote = self.kernel.quote_cast('x', 'A', self.source)
        self.assertEqual(ManaCost(0, ('U',)), quote.cost.mana)
        self.kernel.commit_action(quote, Payment((('U', 1),)))

    def test_commander_tax_is_per_card(self):
        self.setup_game(CostSpec())
        first = self.state.add_card('c1', 'spell', 'A', Zone.COMMAND, commander=True)
        second = self.state.add_card('c2', 'spell', 'A', Zone.COMMAND, commander=True)
        self.state.record_command_cast('A', 'c1')
        self.assertEqual(2, self.kernel.quote_cast('one', 'A', first).cost.mana.generic)
        quote = self.kernel.quote_cast('two', 'A', second)
        self.assertEqual(0, quote.cost.mana.generic)
        self.kernel.commit_action(quote, Payment())
        self.assertEqual(1, self.state.commander_casts('c2'))
        self.assertEqual(1, self.state.commander_casts('c1'))

    def ability_game(self, cost, effects=(GainLife(2),), mana=False, creature=False):
        program = CardProgram('a', 'Ability source', ('Creature',) if creature else ('Artifact',),
            power=2 if creature else None, toughness=2 if creature else None,
            activated=(ActivatedProgram('use', cost, effects, mana_ability=mana),))
        self.state = RulesState(('A', 'B'))
        self.source = self.state.add_card('a', 'a', 'A', Zone.BATTLEFIELD)
        self.kernel = RulesKernel(self.state, (program,)); self.kernel.open_window_for_scenario('A')

    def test_tap_mana_ability_is_immediate_and_retains_priority(self):
        self.ability_game(CostSpec(tap_source=True), (AddMana(('U',)),), True)
        quote = self.kernel.quote_activation('mana', 'A', self.source, 'use')
        self.kernel.commit_action(quote, Payment())
        self.assertEqual((('U', 1),), self.state.mana_pool('A'))
        self.assertEqual([], self.kernel.stack)
        self.assertEqual('A', self.kernel.priority)
        with self.assertRaises(RulesViolation): self.kernel.quote_activation('again', 'A', self.source, 'use')
        self.kernel.open_window_for_scenario('A', 'postcombat_main')
        self.assertEqual((), self.state.mana_pool('A'))

    def test_life_cost_and_source_independent_resolution(self):
        self.ability_game(CostSpec(life=3, tap_source=True))
        self.kernel.commit_action(self.kernel.quote_activation('use', 'A', self.source, 'use'), Payment())
        self.assertEqual(37, self.state.life('A'))
        self.state.move((ZoneMove(self.source, Zone.EXILE),), 'test-removal')
        self.drain()
        self.assertEqual(39, self.state.life('A'))

    def test_unready_creature_and_unpayable_life_cost_stop_before_payment(self):
        for cost, creature in ((CostSpec(tap_source=True), True), (CostSpec(life=41), False)):
            self.ability_game(cost, creature=creature)
            before = self.kernel.snapshot()
            with self.assertRaises(RulesViolation): self.kernel.quote_activation('use', 'A', self.source, 'use')
            self.assertEqual(before, self.kernel.snapshot())

    def test_paying_all_remaining_life_is_legal_but_loses_before_ability_resolves(self):
        self.ability_game(CostSpec(life=40))
        result=self.kernel.commit_action(self.kernel.quote_activation('use','A',self.source,'use'),Payment())
        self.assertEqual(('B',),result.winners)
        self.assertEqual(0,self.state.life('A'))
        self.assertFalse(self.kernel.stack)

    def test_tap_selection_cost(self):
        self.ability_game(CostSpec(tap_selector=Selector(Zone.BATTLEFIELD, relation='controlled'), tap_count=1))
        quote = self.kernel.quote_activation('use', 'A', self.source, 'use')
        with self.assertRaises(RulesViolation): self.kernel.commit_action(quote, Payment())
        self.kernel.commit_action(quote, Payment(taps=(self.source,)))
        self.assertTrue(self.state.get(self.source).tapped)

    def test_cast_trigger_above_spell_and_nonactive_caster_keeps_priority(self):
        self.setup_game(CostSpec())
        observer = CardProgram('o', 'Observer', ('Artifact',), abilities=(
            AbilityProgram('cast-life', EventPattern('spell_cast'), (GainLife(1),)),))
        self.state.add_card('o', 'o', 'B', Zone.BATTLEFIELD)
        self.kernel = RulesKernel(self.state, (self.program, observer))
        self.kernel.open_window_for_scenario('B', priority_actor='A')
        self.kernel.commit_action(self.kernel.quote_cast('use', 'A', self.source), Payment())
        self.assertEqual('A', self.kernel.priority)
        self.assertEqual('cast-life', self.kernel.stack[-1]['ability_id'])
        self.drain(); self.assertEqual(41, self.state.life('B'))

    def test_state_payment_and_moves_are_atomic(self):
        self.setup_game()
        before = self.state.snapshot()
        with self.assertRaises(RulesViolation):
            self.state.move((ZoneMove(ObjectRef('missing', 0), Zone.STACK),), 'bad',
                payment=ResourcePayment('A', (('U', 1),)))
        self.assertEqual(before, self.state.snapshot())
        with self.assertRaises(RulesViolation):
            self.state.move((ZoneMove(self.source, Zone.STACK),), 'bad',
                payment=ResourcePayment('A', (('U', 1),), taps=(self.source,)))
        self.assertEqual(before, self.state.snapshot())

    def test_own_spell_cast_trigger_functions_on_stack(self):
        self.setup_game(CostSpec(), abilities=(AbilityProgram('self-cast',
            EventPattern('spell_cast', subject='self'), (GainLife(1),)),))
        self.kernel.commit_action(self.kernel.quote_cast('x', 'A', self.source), Payment())
        self.assertEqual('self-cast', self.kernel.stack[-1]['ability_id'])
        self.drain(); self.assertEqual(44, self.state.life('A'))

    def test_competing_quotes_cannot_both_commit_at_old_revision(self):
        first = self.setup_game(CostSpec())
        second_source = self.state.add_card('s2', 'spell', 'A', Zone.HAND)
        first = self.kernel.quote_cast('first', 'A', self.source)
        second = self.kernel.quote_cast('second', 'A', second_source)
        self.kernel.commit_action(first, Payment())
        before = self.kernel.snapshot()
        with self.assertRaises(RulesViolation): self.kernel.commit_action(second, Payment())
        self.assertEqual(before, self.kernel.snapshot())

    def test_tap_selected_creature_does_not_require_tap_symbol_readiness(self):
        self.ability_game(CostSpec(tap_selector=Selector(Zone.BATTLEFIELD, ('Creature',), 'controlled'), tap_count=1), creature=True)
        self.kernel.commit_action(self.kernel.quote_activation('tap', 'A', self.source, 'use'), Payment(taps=(self.source,)))
        self.assertTrue(self.state.get(self.source).tapped)

    def test_malformed_resource_checkpoint_is_rejected(self):
        self.setup_game()
        checkpoint = self.state.snapshot()
        checkpoint['mana']['A']['U'] = -1
        with self.assertRaises(RulesViolation): RulesState.restore(checkpoint)

    def test_mana_production_cannot_be_misclassified_as_stack_activation(self):
        with self.assertRaises(RulesViolation):
            self.ability_game(CostSpec(), (AddMana(('U',)),), False)

