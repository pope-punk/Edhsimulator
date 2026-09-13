"""Conformance cases for draft paid/revealed entry; production remains gated."""
import json
import unittest
from dataclasses import replace

from edh_gauntlet.rules_actor import project_actor
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_program import (
    CardProgram, EntryModifier, EntryPayment, LifeCondition, Move, SelectAll,
    Selector, ZoneReplacement, decode, encode, validate,
)
from edh_gauntlet.rules_state import (
    ResourcePayment, RulesState, RulesViolation, Zone, ZoneMove,
)


class EntryPaymentTests(unittest.TestCase):
    def setUp(self):
        self.shock = CardProgram('shock', 'Shock', ('Land',),
            entry_modifiers=(EntryPayment('life', life=2),))
        self.snarl = CardProgram('snarl', 'Snarl', ('Land',),
            entry_modifiers=(EntryPayment('reveal', reveal=Selector(
                Zone.HAND, types=('Land',), relation='owned',
                any_subtypes=('Forest', 'Island'))),))
        self.forest = CardProgram('forest', 'Forest', ('Land',),
            subtypes=('Forest',), supertypes=('Basic',))
        self.dual = CardProgram('dual', 'Typed dual', ('Land',),
            subtypes=('Forest', 'Island'))
        self.source = CardProgram('source', 'Source', ('Enchantment',))
        self.programs = (self.shock, self.snarl, self.forest, self.dual, self.source)
        self.state = RulesState(('A', 'B'))

    def kernel(self, *extra):
        return RulesKernel(self.state, self.programs + extra)

    def answer(self, kernel, key):
        request = kernel.pending_choice
        indexes = [] if key is None else [
            next(i for i, option in enumerate(request.options) if option.key == key)]
        return kernel.answer(request.request_id, request.actor, indexes)

    def reveal(self, kernel, ref):
        request = kernel.pending_choice
        index = next(i for i, option in enumerate(request.options) if option.ref == ref)
        return kernel.answer(request.request_id, request.actor, [index])

    def test_payment_and_decline_are_optional_without_using_the_stack(self):
        for key, life, tapped in (('pay', 38, False), ('decline', 40, True)):
            with self.subTest(key=key):
                state = RulesState(('A', 'B'))
                ref = state.add_card('entry', 'shock', 'A', Zone.HAND)
                kernel = RulesKernel(state, self.programs)
                before = state.snapshot()
                request = kernel.enter(ref)
                self.assertEqual('entry_life_payment', request.kind)
                self.assertEqual(before, state.snapshot())
                self.answer(kernel, key)
                self.assertEqual(life, state.life('A'))
                self.assertEqual(tapped, state.get(state.current('entry')).tapped)
                self.assertEqual([], kernel.stack)
                self.assertFalse(any(e['kind'] == 'damage_dealt' for e in kernel.semantic_events))

    def test_wrong_actor_cannot_pay_and_exact_choice_survives_restore(self):
        ref = self.state.add_card('entry', 'shock', 'A', Zone.HAND)
        kernel = self.kernel()
        request = kernel.enter(ref)
        before = kernel.snapshot()
        with self.assertRaises(RulesViolation):
            kernel.answer(request.request_id, 'B', [0])
        self.assertEqual(before, kernel.snapshot())
        restored = RulesKernel.restore(json.loads(json.dumps(before)), self.programs)
        self.answer(kernel, 'pay')
        self.answer(restored, 'pay')
        self.assertEqual(kernel.snapshot(), restored.snapshot())
        self.assertEqual(38, self.state.life('A'))
        with self.assertRaises(RulesViolation):
            kernel.answer(request.request_id, 'A', [0])
        self.assertEqual(38, self.state.life('A'))

    def test_payment_cannot_be_offered_with_insufficient_life(self):
        self.state.lose_life_batch(('A',), 39)
        ref = self.state.add_card('entry', 'shock', 'A', Zone.HAND)
        kernel = self.kernel()
        request = kernel.enter(ref)
        self.assertEqual(['decline'], [option.key for option in request.options])
        self.answer(kernel, 'decline')
        self.assertEqual(1, self.state.life('A'))
        self.assertTrue(self.state.get(self.state.current('entry')).tapped)

    def test_last_two_life_can_be_paid_before_state_based_loss(self):
        self.state.lose_life_batch(('A',), 38)
        ref = self.state.add_card('entry', 'shock', 'A', Zone.HAND)
        kernel = self.kernel()
        kernel.enter(ref)
        self.answer(kernel, 'pay')
        self.assertEqual(0, self.state.life('A'))
        self.assertNotIn('A', self.state.live_players)

    def test_entering_controller_pays_instead_of_card_owner(self):
        ref = self.state.add_card('entry', 'shock', 'A', Zone.HAND)
        kernel = self.kernel()
        self.assertEqual('B', kernel.enter(ref, controller='B').actor)
        self.answer(kernel, 'pay')
        self.assertEqual(40, self.state.life('A'))
        self.assertEqual(38, self.state.life('B'))
        self.assertEqual('B', self.state.get(self.state.current('entry')).controller)

    def test_paying_does_not_undo_an_instruction_to_enter_tapped(self):
        ref = self.state.add_card('entry', 'shock', 'A', Zone.HAND)
        kernel = self.kernel()
        kernel.execute_for_scenario(ref, 'A', (Move('source', Zone.BATTLEFIELD, tapped=True),))
        self.answer(kernel, 'pay')
        self.assertEqual(38, self.state.life('A'))
        self.assertTrue(self.state.get(self.state.current('entry')).tapped)

    def test_replacement_order_can_override_declined_entry_tapping(self):
        program = replace(self.shock, entry_modifiers=(
            EntryPayment('life', life=2), EntryModifier('untapped', tapped=False)))
        ref = self.state.add_card('entry', 'shock', 'A', Zone.HAND)
        kernel = RulesKernel(self.state, (program,))
        request = kernel.enter(ref)
        self.assertEqual('replacement_order', request.kind)
        self.answer(kernel, next(o.key for o in request.options if o.key.endswith(':life')))
        self.answer(kernel, 'decline')
        self.assertFalse(self.state.get(self.state.current('entry')).tapped)
        self.assertEqual(40, self.state.life('A'))

    def test_simultaneous_payments_share_one_budget_and_one_commit(self):
        self.state.lose_life_batch(('A',), 37)  # Three life cannot pay twice.
        first = self.state.add_card('first', 'shock', 'A', Zone.HAND)
        second = self.state.add_card('second', 'shock', 'A', Zone.HAND)
        kernel = self.kernel()
        before = self.state.snapshot()
        kernel.execute_for_scenario(first, 'A', (SelectAll(
            Selector(Zone.HAND, types=('Land',), relation='owned'),
            (Move('selected', Zone.BATTLEFIELD),)),))
        self.answer(kernel, 'pay')
        self.assertEqual(before, self.state.snapshot())
        self.assertEqual(['decline'], [o.key for o in kernel.pending_choice.options])
        restored = RulesKernel.restore(json.loads(json.dumps(kernel.snapshot())), self.programs)
        self.answer(kernel, 'decline')
        self.answer(restored, 'decline')
        self.assertEqual(kernel.snapshot(), restored.snapshot())
        self.assertEqual(1, self.state.life('A'))
        entered = [event for event in self.state.events if event.after.zone == Zone.BATTLEFIELD]
        self.assertEqual(2, len(entered))
        self.assertEqual(1, len({event.batch for event in entered}))
        self.assertEqual([False, True], sorted(event.after.tapped for event in entered))

    def test_simultaneous_life_conditions_use_pre_payment_totals(self):
        self.state.lose_life_batch(('A',), 26)  # Fourteen life before entry.
        threshold = CardProgram('threshold', 'Threshold', ('Land',),
            entry_modifiers=(EntryModifier('threshold',
                condition=LifeCondition(maximum=13), unless=True),))
        ref = self.state.add_card('shock', 'shock', 'A', Zone.HAND)
        self.state.add_card('threshold', 'threshold', 'A', Zone.HAND)
        kernel = self.kernel(threshold)
        kernel.execute_for_scenario(ref, 'A', (SelectAll(
            Selector(Zone.HAND, relation='owned'), (Move('selected', Zone.BATTLEFIELD),)),))
        self.answer(kernel, 'pay')
        self.assertEqual(12, self.state.life('A'))
        self.assertTrue(self.state.get(self.state.current('threshold')).tapped)

    def test_redirect_before_entry_choice_requires_no_payment(self):
        redirect = CardProgram('redirect', 'Redirect', ('Enchantment',),
            replacements=(ZoneReplacement('exile', Zone.BATTLEFIELD, Zone.EXILE),))
        self.state.add_card('redirect', 'redirect', 'B', Zone.BATTLEFIELD)
        ref = self.state.add_card('entry', 'shock', 'A', Zone.HAND)
        kernel = self.kernel(redirect)
        request = kernel.enter(ref)
        self.answer(kernel, next(o.key for o in request.options if o.key.endswith(':exile')))
        self.assertIsNone(kernel.pending_choice)
        self.assertEqual(40, self.state.life('A'))
        self.assertEqual(Zone.EXILE, self.state.get(self.state.current('entry')).zone)

    def test_entry_copy_inherits_payment_choice_before_commit(self):
        copier = CardProgram('copy', 'Copy', ('Artifact',),
            entry_copy=Selector(Zone.GRAVEYARD, types=('Land',)))
        self.state.add_card('model', 'shock', 'A', Zone.GRAVEYARD)
        ref = self.state.add_card('entry', 'copy', 'A', Zone.HAND)
        kernel = self.kernel(copier)
        request = kernel.enter(ref)
        self.assertEqual('entry_copy', request.kind)
        self.answer(kernel, request.options[0].key)
        self.assertEqual('entry_life_payment', kernel.pending_choice.kind)
        self.assertEqual(Zone.HAND, self.state.get(ref).zone)
        self.answer(kernel, 'pay')
        self.assertEqual('shock', self.state.get(self.state.current('entry')).copied_definition)
        self.assertEqual(38, self.state.life('A'))

    def test_reveal_is_optional_and_only_matching_own_hand_cards_are_offered(self):
        ref = self.state.add_card('entry', 'snarl', 'A', Zone.HAND)
        forest = self.state.add_card('forest', 'forest', 'A', Zone.HAND)
        dual = self.state.add_card('dual', 'dual', 'A', Zone.HAND)
        self.state.add_card('other-owner', 'forest', 'B', Zone.HAND)
        self.state.add_card('other-zone', 'forest', 'A', Zone.BATTLEFIELD)
        self.state.add_card('other-type', 'source', 'A', Zone.HAND)
        kernel = self.kernel()
        request = kernel.enter(ref)
        self.assertEqual({forest, dual}, {o.ref for o in request.options})
        self.answer(kernel, None)
        self.assertTrue(self.state.get(self.state.current('entry')).tapped)
        self.assertEqual([], [e for e in kernel.semantic_events if e['kind'] == 'cards_revealed'])

    def test_nonbasic_subtype_reveal_stays_in_hand_and_is_public(self):
        ref = self.state.add_card('entry', 'snarl', 'A', Zone.HAND)
        dual = self.state.add_card('dual', 'dual', 'A', Zone.HAND)
        self.state.add_card('secret', 'source', 'A', Zone.HAND)
        kernel = self.kernel()
        kernel.enter(ref)
        other = project_actor(kernel, 'B')
        self.assertEqual('waiting', other['decision']['kind'])
        self.assertNotIn('public_entry_reveals', other)
        self.assertNotIn('Typed dual', json.dumps(other))
        self.reveal(kernel, dual)
        self.assertFalse(self.state.get(self.state.current('entry')).tapped)
        self.assertEqual(Zone.HAND, self.state.get(dual).zone)
        public = project_actor(kernel, 'B')['public_entry_reveals']
        self.assertEqual(['Typed dual'], public[0]['names'])
        self.assertEqual([dual.to_json()], public[0]['refs'])
        self.assertNotIn('secret', json.dumps(public))

    def test_reveal_uses_entering_controllers_hand(self):
        ref = self.state.add_card('entry', 'snarl', 'A', Zone.HAND)
        self.state.add_card('owners-card', 'forest', 'A', Zone.HAND)
        eligible = self.state.add_card('controllers-card', 'forest', 'B', Zone.HAND)
        kernel = self.kernel()
        request = kernel.enter(ref, controller='B')
        self.assertEqual('B', request.actor)
        self.assertEqual([eligible], [o.ref for o in request.options])
        self.reveal(kernel, eligible)
        self.assertFalse(self.state.get(self.state.current('entry')).tapped)

    def test_no_matching_hand_card_enters_tapped_without_private_disclosure(self):
        ref = self.state.add_card('entry', 'snarl', 'A', Zone.HAND)
        self.state.add_card('secret', 'source', 'A', Zone.HAND)
        kernel = self.kernel()
        kernel.enter(ref)
        self.assertIsNone(kernel.pending_choice)
        self.assertTrue(self.state.get(self.state.current('entry')).tapped)
        self.assertNotIn('public_entry_reveals', project_actor(kernel, 'B'))

    def test_simultaneously_entering_land_can_be_revealed(self):
        ref = self.state.add_card('entry', 'snarl', 'A', Zone.HAND)
        forest = self.state.add_card('forest', 'forest', 'A', Zone.HAND)
        kernel = self.kernel()
        kernel.execute_for_scenario(ref, 'A', (SelectAll(
            Selector(Zone.HAND, relation='owned'), (Move('selected', Zone.BATTLEFIELD),)),))
        self.reveal(kernel, forest)
        self.assertFalse(self.state.get(self.state.current('entry')).tapped)
        self.assertEqual(Zone.BATTLEFIELD, self.state.get(self.state.current('forest')).zone)
        self.assertEqual([forest.to_json()], project_actor(kernel, 'B')['public_entry_reveals'][0]['refs'])
        self.assertEqual(1, len({event.batch for event in self.state.events}))

    def test_same_hand_card_can_be_revealed_for_two_entries_across_restore(self):
        ref = self.state.add_card('first', 'snarl', 'A', Zone.HAND)
        self.state.add_card('second', 'snarl', 'A', Zone.HAND)
        forest = self.state.add_card('forest', 'forest', 'A', Zone.HAND)
        kernel = self.kernel()
        kernel.execute_for_scenario(ref, 'A', (SelectAll(
            Selector(Zone.HAND, relation='owned'), (Move('selected', Zone.BATTLEFIELD),)),))
        self.reveal(kernel, forest)
        self.assertEqual('entry_hand_reveal', kernel.pending_choice.kind)
        restored = RulesKernel.restore(json.loads(json.dumps(kernel.snapshot())), self.programs)
        self.reveal(kernel, forest)
        self.reveal(restored, forest)
        self.assertEqual(kernel.snapshot(), restored.snapshot())
        self.assertEqual(2, len(project_actor(kernel, 'B')['public_entry_reveals']))
        self.assertTrue(all(not event.after.tapped for event in self.state.events))

    def test_low_level_life_validation_is_atomic_and_includes_other_costs(self):
        ref = self.state.add_card('entry', 'shock', 'A', Zone.HAND)
        self.state.lose_life_batch(('A',), 37)
        before = self.state.snapshot()
        for payments in ((('A', 4),), (('A', 2), ('A', 2)), (('A', True),), (('unknown', 2),)):
            with self.subTest(payments=payments), self.assertRaises(RulesViolation):
                self.state.move((ZoneMove(ref, Zone.BATTLEFIELD),), 'entry', entry_life=payments)
            self.assertEqual(before, self.state.snapshot())
        with self.assertRaises(RulesViolation):
            self.state.move((ZoneMove(ref, Zone.BATTLEFIELD),), 'entry',
                payment=ResourcePayment('A', life=2), entry_life=(('A', 2),))
        self.assertEqual(before, self.state.snapshot())

    def test_compiler_round_trip_and_invalid_payment_specs(self):
        self.assertEqual(self.shock, decode(encode(validate(self.shock))))
        self.assertEqual(self.snarl, decode(encode(validate(self.snarl))))
        for modifier in (
            EntryPayment('empty'), EntryPayment('negative', life=-1),
            EntryPayment('bool', life=True), EntryPayment('untap', life=2, tapped=False),
            EntryPayment('conditional', life=2, condition=LifeCondition(minimum=20)),
            EntryPayment('both', life=2, reveal=Selector(Zone.HAND, relation='owned')),
            EntryPayment('library', reveal=Selector(Zone.LIBRARY, relation='owned')),
            EntryPayment('any-hand', reveal=Selector(Zone.HAND)),
            EntryPayment('global', life=2, selector=Selector(Zone.BATTLEFIELD)),
        ):
            with self.subTest(modifier=modifier), self.assertRaises(RulesViolation):
                validate(replace(self.shock, entry_modifiers=(modifier,)))
