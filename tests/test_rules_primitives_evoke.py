"""Reviewed evoke programs: real casting, entry facts, ordinary triggers and LTB targets.

Rules basis: CR 702.74a, 400.7/400.7d, 601.2b/f-h, 603.3b/603.4 and 608.2b.
Wizards' Commander Masters and Modern Horizons release notes clarify controller
changes and the opportunity to respond before an evoked permanent is sacrificed.
"""
from collections import Counter as Counts
from dataclasses import replace
import json
from pathlib import Path
import unittest

from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_characteristics import condition_selectors
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_program import (
    AbilityProgram, AddKeywords, AllConditions, AlternativeCost, CardProgram,
    CastSpec, ContinuousProgram, CostModifier, CostSpec, Counter, CounterAbilities,
    EntryAlternativeCost, EntryFlagCondition, EventPattern, GainLife, ManaCost,
    Move, NotCondition, SelectAll, Selector, TargetSpec, WithMoved, ZoneCost, ZoneReplacement, decode, encode, validate,
)
from edh_gauntlet.rules_state import RulesState, RulesViolation, Zone, ZoneMove


class EvokeCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        rows = load_reviewed(root)
        cls.cards = {key: rows[key]['program'] for key in ('mulldrifter', 'reveillark', 'vesperlark')}
        cls.reviewed = tuple(row['program'] for row in rows.values())
        cls.fixtures = (
            CardProgram('fixture:one', 'One power', ('Creature',), power=1, toughness=3),
            CardProgram('fixture:two', 'Two power', ('Creature',), power=2, toughness=3),
            CardProgram('fixture:three', 'Three power', ('Creature',), power=3, toughness=3),
            CardProgram('fixture:negative', 'Negative power', ('Creature',), power=-1, toughness=3),
            CardProgram('fixture:artifact', 'Artifact', ('Artifact',)),
            CardProgram('fixture:blink', 'Blink fixture', ('Instant',),
                        spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD, types=('Creature',))),
                        spell_effects=(WithMoved('target', Zone.EXILE,
                            (Move('moved', Zone.BATTLEFIELD, controller='owner'),)),)),
            CardProgram('fixture:counter', 'Counter fixture', ('Instant',),
                        spell_targets=TargetSpec(Selector(Zone.STACK)),
                        spell_effects=(Counter('target'),)),
            CardProgram('fixture:counter-abilities', 'Counter abilities fixture', ('Instant',),
                        spell_effects=(CounterAbilities('all'),)),
        )

    def game(self, *extra):
        self.programs = self.reviewed + self.fixtures + extra
        self.state = RulesState(('A', 'B'))
        self.kernel = RulesKernel(self.state, self.programs)
        self.kernel.open_window_for_scenario('A')

    def add(self, key, name=None, owner='A', zone=Zone.HAND):
        definition = self.cards[key].definition_id if key in self.cards else key if key.startswith('fixture:') else 'catalog:' + key
        return self.state.add_card(name or key, definition, owner, zone)

    def current(self, ref):
        return self.state.get(self.state.current(ref.card_id))

    def library(self, count=8):
        for index in range(count):
            self.add('forest', 'draw-' + str(index), zone=Zone.LIBRARY)

    def cast(self, ref, generic, color, alternative='evoke'):
        pool = ('C',) * generic + (color,)
        self.state.add_mana('A', pool)
        quote = self.kernel.quote_cast('cast-' + ref.card_id, 'A', ref, alternative_id=alternative)
        self.assertEqual(ManaCost(generic, (color,)), quote.cost.mana)
        self.kernel.commit_action(quote, Payment(tuple(Counts(pool).items())))
        return quote

    def resolve_one(self, kernel=None):
        kernel = kernel or self.kernel
        frame_id = kernel.stack[-1]['id']
        for _ in range(32):
            if kernel.pending_choice:
                break
            if not any(frame['id'] == frame_id for frame in kernel.stack) and (
                    kernel.resolving is None or kernel.resolving['id'] != frame_id):
                break
            kernel.pass_priority(kernel.priority)
        else:
            self.fail('One stack object did not reach a boundary')
        return kernel.pending_choice

    def drain(self, kernel=None):
        kernel = kernel or self.kernel
        for _ in range(100):
            if not kernel.stack or kernel.pending_choice:
                return kernel.pending_choice
            kernel.pass_priority(kernel.priority)
        self.fail('Stack did not settle')

    def order(self, last):
        request = self.kernel.pending_choice
        self.assertEqual('trigger_order', request.kind)
        index = next(i for i, option in enumerate(request.options) if ': ' + last + ' [' in option.label)
        indexes = [i for i in range(len(request.options)) if i != index] + [index]
        self.kernel.answer(request.request_id, request.actor, indexes)

    def targets(self, refs):
        request = self.kernel.pending_choice
        self.assertEqual('trigger_targets', request.kind)
        indexes = [next(i for i, option in enumerate(request.options) if option.ref == ref) for ref in refs]
        self.kernel.answer(request.request_id, request.actor, indexes)

    def test_normal_costs_leave_all_three_creatures_and_mulldrifter_draws(self):
        for key, generic, color, stats in (
                ('mulldrifter', 4, 'U', (2, 2)), ('reveillark', 4, 'W', (4, 3)),
                ('vesperlark', 2, 'W', (2, 1))):
            with self.subTest(card=key):
                self.game()
                self.library()
                ref = self.add(key)
                self.cast(ref, generic, color, alternative=None)
                self.drain()
                obj = self.current(ref)
                self.assertEqual(Zone.BATTLEFIELD, obj.zone)
                self.assertEqual(frozenset(), obj.entry_flags)
                view = self.kernel.effective(obj.ref)
                self.assertEqual(stats, (view.power, view.toughness))
                self.assertIn('flying', view.keywords)
                self.assertEqual(2 if key == 'mulldrifter' else 0, len(self.state.zone('A', Zone.HAND)))
                self.assertFalse(any(event['kind'] == 'trigger_created' and
                                     event['ability'] == 'evoke-sacrifice' for event in self.kernel.semantic_events))

    def test_mulldrifter_both_trigger_orders_pay_once_and_preserve_mana_value(self):
        for first in ('draw', 'evoke-sacrifice'):
            with self.subTest(first=first):
                self.game()
                self.library()
                ref = self.add('mulldrifter')
                self.cast(ref, 2, 'U')
                self.assertEqual(5, self.kernel.effective(self.current(ref).ref).mana_value)
                self.assertEqual((), self.state.mana_pool('A'))
                request = self.resolve_one()
                self.assertEqual('trigger_order', request.kind)
                self.assertEqual(Zone.BATTLEFIELD, self.current(ref).zone)
                self.assertEqual(frozenset({'evoked'}), self.current(ref).entry_flags)
                self.order(first)
                self.assertEqual(2, len(self.kernel.stack))
                self.resolve_one()
                self.assertEqual(2 if first == 'draw' else 0, len(self.state.zone('A', Zone.HAND)))
                self.assertEqual(Zone.BATTLEFIELD if first == 'draw' else Zone.GRAVEYARD, self.current(ref).zone)
                self.drain()
                self.assertEqual(2, len(self.state.zone('A', Zone.HAND)))
                self.assertEqual(Zone.GRAVEYARD, self.current(ref).zone)
                self.assertEqual(frozenset(), self.current(ref).entry_flags)
                self.assertEqual(1, len(self.kernel.action_receipts))

    def test_evoke_costs_include_reveillarks_more_expensive_alternative(self):
        for key, generic in (('reveillark', 5), ('vesperlark', 1)):
            with self.subTest(card=key):
                self.game()
                ref = self.add(key)
                self.cast(ref, generic, 'W')
                self.resolve_one()
                self.assertEqual(Zone.BATTLEFIELD, self.current(ref).zone)
                self.assertEqual(['evoke-sacrifice'], [frame['ability_id'] for frame in self.kernel.stack])
                self.drain()
                self.assertEqual(Zone.GRAVEYARD, self.current(ref).zone)

    def test_blink_before_sacrifice_resets_entry_facts_and_cannot_hit_new_incarnation(self):
        self.game()
        self.library()
        ref = self.add('mulldrifter')
        self.cast(ref, 2, 'U')
        self.resolve_one()
        self.order('evoke-sacrifice')
        old = self.current(ref).ref
        blink = self.add('fixture:blink')
        self.kernel.stage_spell_for_scenario(blink, 'A', (old,))
        self.resolve_one()
        current = self.current(ref)
        self.assertEqual(old.incarnation + 2, current.ref.incarnation)
        self.assertEqual(frozenset(), current.entry_flags)
        self.drain()
        self.assertEqual(Zone.BATTLEFIELD, self.current(ref).zone)
        self.assertEqual(4, len(self.state.zone('A', Zone.HAND)))
        self.assertEqual(1, sum(event['kind'] == 'trigger_created' and
                               event['ability'] == 'evoke-sacrifice' for event in self.kernel.semantic_events))

    def test_current_controller_sacrifices_and_owns_the_ltb_trigger(self):
        self.game()
        own = self.add('fixture:one', 'a-grave', zone=Zone.GRAVEYARD)
        enemy = self.add('fixture:one', 'b-grave', 'B', Zone.GRAVEYARD)
        ref = self.add('vesperlark')
        self.cast(ref, 1, 'W')
        self.resolve_one()
        self.state.change_control(self.current(ref).ref, 'B')
        self.resolve_one()
        request = self.kernel.pending_choice
        self.assertEqual('B', request.actor)
        self.assertEqual([enemy], [option.ref for option in request.options])
        self.assertEqual(Zone.GRAVEYARD, self.current(ref).zone)
        self.targets((enemy,))
        self.drain()
        self.assertEqual(Zone.BATTLEFIELD, self.current(enemy).zone)
        self.assertEqual('B', self.current(enemy).controller)
        self.assertEqual(Zone.GRAVEYARD, self.current(own).zone)

    def test_countering_evoke_trigger_leaves_creature_and_countering_spell_never_enters(self):
        for counter_trigger in (False, True):
            with self.subTest(counter_trigger=counter_trigger):
                self.game()
                ref = self.add('vesperlark')
                self.cast(ref, 1, 'W')
                if counter_trigger:
                    self.resolve_one()
                spell = self.add('fixture:counter-abilities' if counter_trigger else 'fixture:counter')
                targets = () if counter_trigger else (self.current(ref).ref,)
                self.kernel.stage_spell_for_scenario(spell, 'A', targets)
                self.drain()
                self.assertEqual(Zone.BATTLEFIELD if counter_trigger else Zone.GRAVEYARD, self.current(ref).zone)
                self.assertEqual(1 if counter_trigger else 0,
                                 sum(event['kind'] == 'trigger_created' and event['ability'] == 'evoke-sacrifice'
                                     for event in self.kernel.semantic_events))

    def test_direct_entry_and_body_double_copy_do_not_inherit_an_evoke_payment(self):
        for key in ('mulldrifter', 'reveillark', 'vesperlark'):
            with self.subTest(card=key):
                self.game()
                self.library()
                ref = self.add(key)
                self.kernel.enter(ref)
                self.drain()
                self.assertEqual(Zone.BATTLEFIELD, self.current(ref).zone)
                self.assertEqual(frozenset(), self.current(ref).entry_flags)
        self.game()
        self.add('vesperlark', zone=Zone.GRAVEYARD)
        copy = self.add('body-double')
        self.kernel.enter(copy)
        request = self.kernel.pending_choice
        chosen = next(i for i, option in enumerate(request.options) if option.ref is not None)
        self.kernel.answer(request.request_id, 'A', [chosen])
        self.drain()
        obj = self.current(copy)
        self.assertEqual('catalog:vesperlark', obj.effective_definition)
        self.assertEqual(frozenset(), obj.entry_flags)
        self.assertFalse(any(event['kind'] == 'trigger_created' and event['ability'] == 'evoke-sacrifice'
                             for event in self.kernel.semantic_events))

    def test_lark_departures_to_hand_exile_or_graveyard_use_power_and_owner_filters(self):
        for key, threshold in (('reveillark', 2), ('vesperlark', 1)):
            for destination in (Zone.HAND, Zone.EXILE, Zone.GRAVEYARD):
                with self.subTest(card=key, destination=destination):
                    self.game()
                    ref = self.add(key, zone=Zone.BATTLEFIELD)
                    one = self.add('fixture:one', 'one', zone=Zone.GRAVEYARD)
                    two = self.add('fixture:two', 'two', zone=Zone.GRAVEYARD)
                    negative = self.add('fixture:negative', 'negative', zone=Zone.GRAVEYARD)
                    self.add('fixture:three', 'three', zone=Zone.GRAVEYARD)
                    self.add('fixture:artifact', 'artifact', zone=Zone.GRAVEYARD)
                    self.add('fixture:one', 'foreign', 'B', Zone.GRAVEYARD)
                    self.kernel.execute_for_scenario(ref, 'A', (Move('source', destination),))
                    request = self.kernel.pending_choice
                    expected = {one, negative} | ({two} if threshold == 2 else set())
                    self.assertEqual(expected, {option.ref for option in request.options})
                    selected = (one, negative) if key == 'reveillark' else (one,)
                    self.targets(selected)
                    self.drain()
                    for target in selected:
                        self.assertEqual(Zone.BATTLEFIELD, self.current(target).zone)
                        self.assertEqual('A', self.current(target).controller)
                    entries = [event for event in self.state.events if event.before.ref in selected]
                    self.assertEqual(1, len({event.batch for event in entries}))

    def test_reveillark_can_choose_zero_and_one_departed_target_does_not_stop_the_other(self):
        for count in (0, 2):
            with self.subTest(count=count):
                self.game()
                ref = self.add('reveillark', zone=Zone.BATTLEFIELD)
                one = self.add('fixture:one', 'one', zone=Zone.GRAVEYARD)
                two = self.add('fixture:two', 'two', zone=Zone.GRAVEYARD)
                self.kernel.execute_for_scenario(ref, 'A', (Move('source', Zone.EXILE),))
                self.targets(() if count == 0 else (one, two))
                if count:
                    self.state.move((ZoneMove(two, Zone.EXILE),), 'response')
                self.drain()
                self.assertEqual(Zone.BATTLEFIELD if count else Zone.GRAVEYARD, self.current(one).zone)
                self.assertEqual(Zone.EXILE if count else Zone.GRAVEYARD, self.current(two).zone)

    def test_graveyard_entry_prohibition_is_respected_and_vesperlark_target_is_required(self):
        self.game()
        ref = self.add('vesperlark', zone=Zone.BATTLEFIELD)
        target = self.add('fixture:one', zone=Zone.GRAVEYARD)
        self.add('kunoros-hound-of-athreos', zone=Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(ref, 'A', (Move('source', Zone.EXILE),))
        request = self.kernel.pending_choice
        before = self.kernel.snapshot()
        with self.assertRaises(RulesViolation):
            self.kernel.answer(request.request_id, 'A', [])
        self.assertEqual(before, self.kernel.snapshot())
        self.targets((target,))
        self.drain()
        self.assertEqual(Zone.GRAVEYARD, self.current(target).zone)

    def test_reduction_and_commander_tax_apply_to_the_selected_alternative(self):
        reducer = CardProgram('fixture:reducer', 'Cost reduction', ('Artifact',), cost_modifiers=(
            CostModifier('reduce', Selector(Zone.STACK, relation='controlled'), -20),))
        self.game(reducer)
        self.add('fixture:reducer', zone=Zone.BATTLEFIELD)
        ref = self.add('vesperlark')
        self.cast(ref, 0, 'W')
        self.resolve_one()
        self.assertEqual(frozenset({'evoked'}), self.current(ref).entry_flags)
        commander = replace(self.cards['vesperlark'], definition_id='fixture:commander',
                            name='Commander fixture', supertypes=('Legendary',))
        self.game(commander)
        ref = self.state.add_card('commander', 'fixture:commander', 'A', Zone.COMMAND, commander=True)
        self.state.record_command_cast('A', ref.card_id)
        self.state.record_command_cast('A', ref.card_id)
        self.cast(ref, 5, 'W')
        self.resolve_one()
        self.assertEqual(frozenset({'evoked'}), self.current(ref).entry_flags)

    def test_bad_payment_unknown_alternative_and_duplicate_cast_leave_state_unchanged(self):
        self.game()
        ref = self.add('vesperlark')
        quote = self.kernel.quote_cast('unpaid', 'A', ref, alternative_id='evoke')
        before = self.kernel.snapshot()
        with self.assertRaises(RulesViolation):
            self.kernel.commit_action(quote, Payment())
        self.assertEqual(before, self.kernel.snapshot())
        with self.assertRaises(RulesViolation):
            self.kernel.quote_cast('unknown', 'A', ref, alternative_id='unknown')
        self.assertEqual(before, self.kernel.snapshot())
        self.state.add_mana('A', ('C', 'W'))
        quote = self.kernel.quote_cast('paid', 'A', ref, alternative_id='evoke')
        payment = Payment((('C', 1), ('W', 1)))
        self.kernel.commit_action(quote, payment)
        before = self.kernel.snapshot()
        with self.assertRaises(RulesViolation):
            self.kernel.commit_action(quote, payment)
        self.assertEqual(before, self.kernel.snapshot())

    def test_actor_archive_replays_paid_evoke_and_pending_trigger_order_exactly(self):
        self.game()
        self.library()
        ref = self.add('mulldrifter')
        self.state.add_mana('A', ('C', 'C', 'U'))
        adapter = RulesActorAdapter(self.kernel)
        adapter.submit('A', {'kind': 'cast', 'revision': self.kernel.revision, 'action_id': 'evoke',
                            'source': ref.to_json(), 'targets': [], 'x_value': 0, 'alternative_id': 'evoke',
                            'payment': {'mana': {'C': 2, 'U': 1}, 'taps': []}})
        for _ in range(32):
            if self.kernel.pending_choice:
                break
            adapter.submit(self.kernel.priority, {'kind': 'pass', 'revision': self.kernel.revision})
        else:
            self.fail('Paid evoke did not offer its trigger-order boundary')
        replay = RulesActorAdapter.replay(adapter.archive(), self.programs)
        self.assertEqual(adapter.archive(), replay.archive())
        request = self.kernel.pending_choice
        indexes = list(range(len(request.options)))
        command = {'kind': 'answer', 'revision': self.kernel.revision,
                   'request_id': request.request_id, 'indexes': indexes}
        adapter.submit(request.actor, command)
        replay.submit(request.actor, command)
        for _ in range(32):
            if not self.kernel.stack:
                break
            command = {'kind': 'pass', 'revision': self.kernel.revision}
            actor = self.kernel.priority
            adapter.submit(actor, command)
            replay.submit(actor, command)
        else:
            self.fail('Evoke replay did not settle')
        self.assertEqual(adapter.archive(), replay.archive())
        self.assertEqual(Zone.GRAVEYARD, self.current(ref).zone)
        self.assertEqual(2, len(self.state.zone('A', Zone.HAND)))

    def test_stack_and_ltb_target_checkpoints_preserve_payment_and_choices(self):
        self.game()
        ref = self.add('vesperlark')
        target = self.add('fixture:one', zone=Zone.GRAVEYARD)
        self.cast(ref, 1, 'W')
        restored = RulesKernel.restore(json.loads(json.dumps(self.kernel.snapshot())), self.programs)
        self.drain()
        self.drain(restored)
        self.assertEqual(self.kernel.snapshot(), restored.snapshot())
        request = self.kernel.pending_choice
        restored = RulesKernel.restore(json.loads(json.dumps(self.kernel.snapshot())), self.programs)
        for kernel in (self.kernel, restored):
            index = next(i for i, option in enumerate(request.options) if option.ref == target)
            kernel.answer(request.request_id, request.actor, [index])
            self.drain(kernel)
        self.assertEqual(self.kernel.snapshot(), restored.snapshot())
        self.assertEqual(Zone.BATTLEFIELD, self.current(target).zone)
        old = self.kernel.snapshot()
        old['schema'] = 109
        with self.assertRaises(RulesViolation):
            RulesKernel.restore(old, self.programs)

    def test_entry_fact_conditions_compose_without_fake_selector_dependencies(self):
        condition = AllConditions((EntryFlagCondition('chosen'), NotCondition(EntryFlagCondition('other'))))
        fixture = CardProgram('fixture:condition', 'Condition fixture', ('Creature',), power=1, toughness=1,
            continuous=(ContinuousProgram('haste', Selector(Zone.BATTLEFIELD), (AddKeywords(('haste',)),),
                                          subject='self', condition=condition),),
            abilities=(AbilityProgram('life', EventPattern('zone_changed', to_zone=Zone.BATTLEFIELD, subject='self'),
                                      (GainLife(2),), intervening_if=condition),))
        self.game(fixture)
        ref = self.add('fixture:condition')
        self.kernel.enter(ref, entry_flags=('chosen',))
        self.drain()
        self.assertEqual(42, self.state.life('A'))
        self.assertIn('haste', self.kernel.effective(self.current(ref).ref).keywords)
        self.assertEqual((), tuple(condition_selectors(condition)))
        self.assertEqual(condition, decode(encode(condition)))

    def test_new_nodes_reject_malformed_facts_nonpermanents_and_unsupported_costs(self):
        program = self.cards['vesperlark']
        alternative = program.cast.alternatives[0]
        for flags in ((), [], ('',), ('evoked', 'evoked'), (True,)):
            with self.subTest(flags=flags), self.assertRaises(RulesViolation):
                validate(replace(program, cast=replace(program.cast,
                    alternatives=(replace(alternative, entry_flags=flags),))))
        for flag in ('', None, 1, True):
            with self.subTest(flag=flag), self.assertRaises(RulesViolation):
                validate(replace(program, abilities=(replace(program.abilities[1],
                    intervening_if=EntryFlagCondition(flag)),)))
        with self.assertRaises(RulesViolation):
            validate(CardProgram('instant', 'Instant', ('Instant',),
                cast=CastSpec(CostSpec(), timing='instant', alternatives=(alternative,))))
        for cost in (CostSpec(zone_costs=(ZoneCost('discard', 'discard'),)),
                     CostSpec(tap_selector=Selector(Zone.BATTLEFIELD, relation='controlled'), tap_count=1)):
            with self.assertRaises(RulesViolation):
                validate(replace(program, cast=replace(program.cast,
                    alternatives=(replace(alternative, cost=cost),))))
        self.assertEqual(program, decode(encode(program)))
        # The base alternative node retains its old serialized field set.
        base = AlternativeCost('plain', CostSpec(ManaCost(1)))
        self.assertEqual({'node', 'alternative_id', 'cost', 'condition'}, set(encode(base)))

    def test_reveillark_finds_creatures_that_leave_in_the_same_batch(self):
        self.game()
        source = self.add('reveillark', zone=Zone.BATTLEFIELD)
        one = self.add('fixture:one', 'one', zone=Zone.BATTLEFIELD)
        two = self.add('fixture:two', 'two', zone=Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(source, 'A', (
            SelectAll(Selector(Zone.BATTLEFIELD, types=('Creature',), relation='controlled'),
                      (Move('selected', Zone.GRAVEYARD),)),))
        request = self.kernel.pending_choice
        targets = (self.current(one).ref, self.current(two).ref)
        self.assertEqual(set(targets), {option.ref for option in request.options})
        self.targets(targets)
        self.drain()
        self.assertEqual(Zone.GRAVEYARD, self.current(source).zone)
        self.assertEqual(Zone.BATTLEFIELD, self.current(one).zone)
        self.assertEqual(Zone.BATTLEFIELD, self.current(two).zone)

    def test_redirected_entry_does_not_record_entry_facts_or_fire_evoke(self):
        redirect = CardProgram('fixture:redirect', 'Redirect fixture', ('Artifact',), replacements=(
            ZoneReplacement('redirect', Zone.BATTLEFIELD, Zone.EXILE, from_zone=Zone.STACK,
                            types=('Creature',)),))
        self.game(redirect)
        self.add('fixture:redirect', zone=Zone.BATTLEFIELD)
        self.library()
        ref = self.add('mulldrifter')
        self.cast(ref, 2, 'U')
        self.drain()
        self.assertEqual(Zone.EXILE, self.current(ref).zone)
        self.assertEqual(frozenset(), self.current(ref).entry_flags)
        self.assertEqual(0, len(self.state.zone('A', Zone.HAND)))
        self.assertFalse(any(event['kind'] == 'trigger_created' for event in self.kernel.semantic_events))
