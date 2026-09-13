"""Linked exile drafts: distinct entry/departure abilities and exact exile objects."""
from collections import Counter as Counts
from dataclasses import replace
import json
from pathlib import Path
import unittest

from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_actor import project_actor
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_program import (
    AbilityProgram, ActivatedProgram, CardProgram, CostSpec, CounterAbilities,
    EntryPayment, EventPattern, ExileLinked, GainLife,
    Move, SelectAll, Selector, TargetSpec, WithLinkedExile,
    WithMoved, ZoneReplacement, decode, encode, immediate_effect_nodes, validate,
)
from edh_gauntlet.rules_state import RulesState, RulesViolation, Zone


class LinkedExileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        bundle = json.loads((root / 'data/rules/draft_cards.json').read_text(encoding='utf-8'))
        cls.drafts = {row['card_id']: validate(decode(row['program'])) for row in bundle['drafts']}
        cls.reviewed = tuple(row['program'] for row in load_reviewed(root).values())
        cls.fixtures = (
            CardProgram('fixture:body', 'Body', ('Creature',), power=3, toughness=3),
            CardProgram('fixture:artifact', 'Artifact', ('Artifact',)),
            CardProgram('fixture:artifact-land', 'Artifact land', ('Artifact', 'Land')),
            CardProgram('fixture:enchantment', 'Enchantment', ('Enchantment',)),
            CardProgram('fixture:bounce', 'Bounce', ('Instant',),
                        spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD)),
                        spell_effects=(Move('target', Zone.HAND, controller='owner'),)),
            CardProgram('fixture:remove', 'Remove', ('Instant',),
                        spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD)),
                        spell_effects=(Move('target', Zone.GRAVEYARD),)),
            CardProgram('fixture:counter', 'Counter abilities', ('Instant',),
                        spell_effects=(CounterAbilities('all'),)),
            CardProgram('fixture:links', 'Link fixture', ('Artifact',),
                        abilities=(AbilityProgram('return', EventPattern(
                            'zone_changed', from_zone=Zone.BATTLEFIELD, subject='self'),
                            (WithLinkedExile('exile', (Move('linked', Zone.BATTLEFIELD, controller='owner'),)),)),)),
            CardProgram('fixture:aura', 'Aura', ('Enchantment',), subtypes=('Aura',),
                        enchant=Selector(Zone.BATTLEFIELD, types=('Creature',))),
        )

    def game(self, *extra):
        self.programs = self.reviewed + tuple(self.drafts.values()) + self.fixtures + extra
        self.state = RulesState(('A', 'B'))
        self.kernel = RulesKernel(self.state, self.programs)
        self.kernel.open_window_for_scenario('A')

    def add(self, key, name=None, owner='A', zone=Zone.BATTLEFIELD, **kwargs):
        definition = self.drafts[key].definition_id if key in self.drafts else key if key.startswith('fixture:') else 'catalog:' + key
        return self.state.add_card(name or key, definition, owner, zone, **kwargs)

    def current(self, ref):
        return self.state.get(self.state.current(ref.card_id))

    def drain(self, kernel=None):
        kernel = kernel or self.kernel
        for _ in range(200):
            if kernel.pending_choice or not kernel.stack:
                return kernel.pending_choice
            kernel.pass_priority(kernel.priority)
        self.fail('Stack did not settle')

    def resolve_one(self):
        frame_id = self.kernel.stack[-1]['id']
        for _ in range(40):
            if self.kernel.pending_choice or not any(frame['id'] == frame_id for frame in self.kernel.stack):
                return self.kernel.pending_choice
            self.kernel.pass_priority(self.kernel.priority)
        self.fail('Stack object did not reach a boundary')

    def choose_refs(self, refs, kind='trigger_targets', kernel=None):
        kernel = kernel or self.kernel
        request = kernel.pending_choice
        self.assertEqual(kind, request.kind)
        indexes = [next(i for i, option in enumerate(request.options) if option.ref == ref) for ref in refs]
        return kernel.answer(request.request_id, request.actor, indexes)

    def choose(self, key, kernel=None):
        kernel = kernel or self.kernel
        request = kernel.pending_choice
        index = next(i for i, option in enumerate(request.options) if option.key == key)
        return kernel.answer(request.request_id, request.actor, [index])

    def enter(self, key, target, name=None, accept=True):
        ref = self.add(key, name, zone=Zone.HAND)
        self.kernel.enter(ref)
        self.choose_refs((target,))
        self.drain()
        if key == 'leonin-relic-warder':
            self.assertEqual('may', self.kernel.pending_choice.kind)
            self.choose('yes' if accept else 'no')
            self.drain()
        return self.current(ref).ref

    def depart(self, ref, destination=Zone.GRAVEYARD):
        self.kernel.execute_for_scenario(ref, self.state.get(ref).controller,
                                         (Move('source', destination, controller='owner'),))
        return self.drain()

    def response(self, key, target=None):
        while self.kernel.priority != 'A':
            self.kernel.pass_priority(self.kernel.priority)
        ref = self.add(key, 'response-' + str(self.state.sequence), zone=Zone.HAND)
        self.kernel.stage_spell_for_scenario(ref, 'A', (target,) if target else ())
        return self.resolve_one()

    def test_both_cards_cast_at_printed_costs_and_return_to_owner(self):
        for key, symbols in (('oblivion-ring', ('C', 'C', 'W')),
                             ('leonin-relic-warder', ('W', 'W'))):
            with self.subTest(card=key):
                self.game()
                target = self.add('fixture:artifact', owner='B', controller='A')
                ref = self.add(key, zone=Zone.HAND)
                self.state.add_mana('A', symbols)
                quote = self.kernel.quote_cast('cast', 'A', ref)
                self.assertEqual(self.drafts[key].cast.cost, quote.cost)
                self.kernel.commit_action(quote, Payment(tuple(Counts(symbols).items())))
                self.drain()
                self.choose_refs((target,))
                self.drain()
                if key == 'leonin-relic-warder':
                    self.choose('yes')
                    self.drain()
                self.assertEqual((), self.state.mana_pool('A'))
                self.assertEqual(Zone.EXILE, self.current(target).zone)
                self.assertEqual([], self.kernel.delayed_triggers)
                self.depart(self.current(ref).ref)
                self.assertEqual(Zone.BATTLEFIELD, self.current(target).zone)
                self.assertEqual('B', self.current(target).controller)
                self.assertIsNone(self.kernel.pending_choice)

    def test_target_domains_preserve_nonland_another_and_artifact_or_enchantment(self):
        for key in ('oblivion-ring', 'leonin-relic-warder'):
            with self.subTest(card=key):
                self.game()
                body = self.add('fixture:body')
                artifact = self.add('fixture:artifact')
                enchantment = self.add('fixture:enchantment', owner='B')
                artifact_land = self.add('fixture:artifact-land')
                self.add('forest')
                self.add('fixture:artifact', 'hand', zone=Zone.HAND)
                ref = self.add(key, zone=Zone.HAND)
                self.kernel.enter(ref)
                options = {option.ref for option in self.kernel.pending_choice.options}
                expected = {artifact, enchantment, body} if key == 'oblivion-ring' else {artifact, enchantment, artifact_land}
                self.assertEqual(expected, options)
                self.assertEqual((1, 1), (self.kernel.pending_choice.minimum, self.kernel.pending_choice.maximum))

    def test_warder_optional_exile_is_chosen_after_required_target(self):
        self.game()
        target = self.add('fixture:artifact')
        ref = self.add('leonin-relic-warder', zone=Zone.HAND)
        request = self.kernel.enter(ref)
        before = self.kernel.snapshot()
        with self.assertRaises(RulesViolation):
            self.kernel.answer(request.request_id, request.actor, [])
        self.assertEqual(before, self.kernel.snapshot())
        self.choose_refs((target,))
        self.drain()
        self.assertEqual('may', self.kernel.pending_choice.kind)
        self.choose('no')
        self.assertEqual({}, self.kernel.linked_exile)
        self.assertEqual(Zone.BATTLEFIELD, self.current(target).zone)
        self.depart(self.current(ref).ref)
        self.assertEqual(Zone.BATTLEFIELD, self.current(target).zone)

    def test_warder_can_exile_itself_when_it_is_an_artifact(self):
        program = replace(self.drafts['leonin-relic-warder'],
                          definition_id='fixture:artifact-warder', types=('Artifact', 'Creature'))
        self.game(program)
        ref = self.add('fixture:artifact-warder', zone=Zone.HAND)
        self.kernel.enter(ref)
        self.choose_refs((self.current(ref).ref,))
        self.drain()
        self.choose('yes')
        self.drain()
        # Its departure trigger sees the link registered by the resolving entry ability.
        self.assertEqual(Zone.BATTLEFIELD, self.current(ref).zone)
        self.assertEqual('trigger_targets', self.kernel.pending_choice.kind)
        self.choose_refs((self.current(ref).ref,))
        self.drain()
        self.choose('no')
        self.assertFalse(self.kernel.stack)

    def test_departure_before_entry_resolution_leaves_old_exile_link(self):
        for key in ('oblivion-ring', 'leonin-relic-warder'):
            with self.subTest(card=key):
                self.game()
                old_target = self.add('fixture:artifact', 'old-target', owner='B')
                new_target = self.add('fixture:artifact', 'new-target', owner='B')
                source = self.add(key, zone=Zone.HAND)
                self.kernel.enter(source)
                old_source = self.current(source).ref
                self.choose_refs((old_target,))
                self.response('fixture:bounce', old_source)
                self.assertEqual('return-exiled', self.kernel.stack[-1]['ability_id'])
                self.resolve_one()
                self.assertEqual(Zone.BATTLEFIELD, self.current(old_target).zone)
                self.drain()
                if key == 'leonin-relic-warder':
                    self.choose('yes')
                    self.drain()
                self.assertEqual(Zone.EXILE, self.current(old_target).zone)
                # The same physical source returns with a fresh, separate pair of abilities.
                self.kernel.enter(self.current(source).ref)
                self.choose_refs((new_target,))
                self.drain()
                if key == 'leonin-relic-warder':
                    self.choose('yes')
                    self.drain()
                self.depart(self.current(source).ref)
                self.assertEqual(Zone.BATTLEFIELD, self.current(new_target).zone)
                self.assertEqual(Zone.EXILE, self.current(old_target).zone)

    def test_two_sources_and_control_changes_keep_independent_links(self):
        self.game()
        first = self.add('fixture:artifact', 'first', owner='B', controller='A')
        second = self.add('fixture:artifact', 'second')
        one = self.enter('oblivion-ring', first, 'one')
        two = self.enter('oblivion-ring', second, 'two')
        self.state.change_control(one, 'B')
        self.depart(one, Zone.HAND)
        self.assertEqual(('B', Zone.BATTLEFIELD), (self.current(first).controller, self.current(first).zone))
        self.assertEqual(Zone.EXILE, self.current(second).zone)
        self.depart(two, Zone.EXILE)
        self.assertEqual(('A', Zone.BATTLEFIELD), (self.current(second).controller, self.current(second).zone))

    def test_exiled_object_that_leaves_and_reenters_exile_is_not_the_linked_object(self):
        self.game()
        target = self.add('fixture:artifact', owner='B')
        source = self.enter('oblivion-ring', target)
        original_exile = self.current(target).ref
        self.kernel.execute_for_scenario(original_exile, 'A',
            (WithMoved('source', Zone.HAND, (Move('moved', Zone.EXILE),)),))
        self.assertNotEqual(original_exile, self.current(target).ref)
        self.assertNotIn('linked_exile', project_actor(self.kernel, 'A'))
        self.depart(source)
        self.assertEqual(Zone.EXILE, self.current(target).zone)

    def test_countered_entry_or_return_ability_does_not_register_or_return(self):
        for phase in ('entry', 'return'):
            with self.subTest(phase=phase):
                self.game()
                target = self.add('fixture:artifact', owner='B')
                source = self.add('oblivion-ring', zone=Zone.HAND)
                self.kernel.enter(source)
                self.choose_refs((target,))
                if phase == 'return':
                    self.drain()
                    self.kernel.execute_for_scenario(self.current(source).ref, 'A',
                                                     (Move('source', Zone.GRAVEYARD),))
                self.response('fixture:counter')
                self.drain()
                self.assertEqual(Zone.BATTLEFIELD if phase == 'entry' else Zone.EXILE, self.current(target).zone)
                if phase == 'entry':
                    self.assertEqual({}, self.kernel.linked_exile)

    def test_illegal_target_on_resolution_does_not_create_a_link_or_optional_choice(self):
        for key in ('oblivion-ring', 'leonin-relic-warder'):
            with self.subTest(card=key):
                self.game()
                target = self.add('fixture:artifact', owner='B')
                source = self.add(key, zone=Zone.HAND)
                self.kernel.enter(source)
                self.choose_refs((target,))
                self.response('fixture:bounce', target)
                self.drain()
                self.assertIsNone(self.kernel.pending_choice)
                self.assertEqual({}, self.kernel.linked_exile)
                self.assertEqual(Zone.HAND, self.current(target).zone)

    def test_replaced_exile_is_not_recorded_and_pending_choice_is_atomic(self):
        redirect = CardProgram('fixture:redirect', 'Redirect', ('Enchantment',),
            replacements=(ZoneReplacement('hand', Zone.EXILE, Zone.HAND, types=('Artifact',), optional=True),))
        for redirecting in (False, True):
            with self.subTest(redirecting=redirecting):
                self.game(redirect)
                self.add('fixture:redirect', owner='B')
                target = self.add('fixture:artifact', owner='B')
                source = self.add('oblivion-ring', zone=Zone.HAND)
                self.kernel.enter(source)
                self.choose_refs((target,))
                self.drain()
                self.assertEqual(Zone.BATTLEFIELD, self.current(target).zone)
                self.assertEqual({}, self.kernel.linked_exile)
                restored = RulesKernel.restore(json.loads(json.dumps(self.kernel.snapshot())), self.programs)
                request = self.kernel.pending_choice
                before = self.kernel.snapshot()
                with self.assertRaises(RulesViolation):
                    self.kernel.answer(request.request_id, 'A', [0])
                self.assertEqual(before, self.kernel.snapshot())
                for kernel in (self.kernel, restored):
                    self.choose('yes' if redirecting else 'no', kernel)
                    self.drain(kernel)
                self.assertEqual(self.kernel.snapshot(), restored.snapshot())
                self.assertEqual(not redirecting, bool(self.kernel.linked_exile))
                self.assertEqual(Zone.HAND if redirecting else Zone.EXILE, self.current(target).zone)

    def test_multiple_actual_exiles_append_and_return_in_one_batch(self):
        self.game()
        source = self.add('fixture:links')
        first = self.add('fixture:body', 'first', owner='A')
        second = self.add('fixture:body', 'second', owner='B')
        effect = SelectAll(Selector(Zone.BATTLEFIELD, types=('Creature',)),
                           (ExileLinked('selected', 'exile'),))
        self.kernel.execute_for_scenario(source, 'A', (effect,))
        third = self.add('fixture:body', 'third', owner='B')
        self.kernel.execute_for_scenario(source, 'A', (effect,))
        self.assertEqual(3, len(next(iter(self.kernel.linked_exile.values()))))
        self.depart(source)
        refs = {self.current(ref).ref for ref in (first, second, third)}
        returned = [event for event in self.state.events if event.after.ref in refs]
        self.assertEqual(3, len(returned))
        self.assertEqual(1, len({event.batch for event in returned}))
        self.assertEqual(['A', 'B', 'B'], [self.current(ref).controller for ref in (first, second, third)])

    def test_distinct_link_names_and_nested_bindings_do_not_overwrite_each_other(self):
        self.game()
        source = self.add('fixture:links')
        body = self.add('fixture:body')
        artifact = self.add('fixture:artifact', owner='B')
        self.kernel.execute_for_scenario(source, 'A', (
            SelectAll(Selector(Zone.BATTLEFIELD, types=('Creature',)), (ExileLinked('selected', 'outer'),)),
            SelectAll(Selector(Zone.BATTLEFIELD, types=('Artifact',), exclude_source=True),
                      (ExileLinked('selected', 'inner'),)),
            WithLinkedExile('outer', (
                WithLinkedExile('inner', (Move('linked', Zone.HAND, controller='owner'),)),
                Move('linked', Zone.BATTLEFIELD, controller='owner'),
            )),
        ))
        self.assertEqual(Zone.BATTLEFIELD, self.current(body).zone)
        self.assertEqual(Zone.HAND, self.current(artifact).zone)

    def test_tokens_cease_and_never_return(self):
        self.game()
        token = self.add('fixture:artifact', token=True, owner='B')
        source = self.enter('oblivion-ring', token)
        self.assertFalse(any(obj.ref.card_id == token.card_id for obj in self.state.objects()))
        self.assertNotIn('linked_exile', project_actor(self.kernel, 'A'))
        self.depart(source)
        self.assertFalse(any(obj.ref.card_id == token.card_id for obj in self.state.objects()))

    def test_return_uses_shared_aura_entry_with_owner_choice_and_no_legal_attachment(self):
        for creature_remains in (True, False):
            with self.subTest(creature_remains=creature_remains):
                self.game()
                body = self.add('fixture:body', owner='B')
                aura = self.add('fixture:aura', owner='B', zone=Zone.HAND)
                self.kernel.enter(aura)
                self.choose_refs((body,), 'aura_attachment')
                source = self.enter('oblivion-ring', self.current(aura).ref)
                if not creature_remains:
                    self.depart(body, Zone.HAND)
                request = self.depart(source)
                if creature_remains:
                    self.assertEqual(('aura_attachment', 'B'), (request.kind, request.actor))
                    self.choose_refs((body,), 'aura_attachment')
                    self.assertEqual(body, self.current(aura).attached_to)
                    self.assertEqual('B', self.current(aura).controller)
                else:
                    self.assertIsNone(request)
                    self.assertEqual(Zone.EXILE, self.current(aura).zone)

    def test_return_entry_replacement_and_checkpoint_keep_link_and_pending_payment(self):
        # An artifact land is a legal Relic-Warder target, including paid entry on return.
        land = CardProgram('fixture:paid-land', 'Paid artifact land', ('Artifact', 'Land'),
                           entry_modifiers=(EntryPayment('pay', life=2),))
        self.game(land)
        target = self.add('fixture:paid-land', owner='B')
        source = self.enter('leonin-relic-warder', target)
        request = self.depart(source)
        self.assertEqual(('entry_life_payment', 'B'), (request.kind, request.actor))
        self.assertEqual(Zone.EXILE, self.current(target).zone)
        restored = RulesKernel.restore(json.loads(json.dumps(self.kernel.snapshot())), self.programs)
        for kernel in (self.kernel, restored):
            self.choose('pay', kernel)
            self.drain(kernel)
        self.assertEqual(self.kernel.snapshot(), restored.snapshot())
        self.assertEqual(38, self.state.life('B'))
        self.assertEqual(Zone.BATTLEFIELD, self.current(target).zone)
        self.assertNotIn('linked_exile', project_actor(self.kernel, 'A'))
        old = self.kernel.snapshot()
        old['schema'] = 110
        with self.assertRaises(RulesViolation):
            RulesKernel.restore(old, self.programs)

    def test_actor_replay_preserves_registered_link_and_public_projection(self):
        self.game()
        target = self.add('fixture:artifact', owner='B')
        self.add('fixture:body', 'hidden-hand', owner='B', zone=Zone.HAND)
        self.add('fixture:body', 'hidden-library', owner='B', zone=Zone.LIBRARY)
        source = self.add('oblivion-ring', zone=Zone.HAND)
        self.kernel.enter(source)
        adapter = RulesActorAdapter(self.kernel)
        request = self.kernel.pending_choice
        index = next(i for i, option in enumerate(request.options) if option.ref == target)
        adapter.submit(request.actor, {'kind': 'answer', 'revision': self.kernel.revision,
                                      'request_id': request.request_id, 'indexes': [index]})
        while self.kernel.stack:
            adapter.submit(self.kernel.priority, {'kind': 'pass', 'revision': self.kernel.revision})
        replay = RulesActorAdapter.replay(adapter.archive(), self.programs)
        self.assertEqual(adapter.archive(), replay.archive())
        packet = project_actor(self.kernel, 'A')
        links = packet['linked_exile']
        self.assertEqual([self.current(target).ref.to_json()], links[0]['exiled'])
        self.assertEqual(self.current(source).ref.to_json(), links[0]['source'])
        self.assertEqual(links, project_actor(self.kernel, 'B')['linked_exile'])
        self.assertNotIn('hidden-hand', json.dumps(packet))
        self.assertNotIn('hidden-library', json.dumps(packet))
        # The source's historical battlefield ref is public; later hidden incarnations are not.
        self.depart(self.current(source).ref, Zone.HAND)
        self.assertNotIn('linked_exile', project_actor(self.kernel, 'B'))

    def test_entry_copy_has_its_own_link_and_cannot_inherit_the_models_exile(self):
        self.game()
        first = self.add('fixture:artifact', 'first', owner='B')
        second = self.add('fixture:artifact', 'second', owner='B')
        original = self.enter('leonin-relic-warder', first, 'original')
        model = self.add('leonin-relic-warder', 'model', zone=Zone.GRAVEYARD)
        copy = self.add('body-double', zone=Zone.HAND)
        self.kernel.enter(copy)
        self.choose_refs((model,), 'entry_copy')
        self.choose_refs((second,))
        self.drain()
        self.choose('yes')
        self.drain()
        self.assertEqual('draft:leonin-relic-warder', self.current(copy).effective_definition)
        self.depart(self.current(copy).ref)
        self.assertEqual(Zone.BATTLEFIELD, self.current(second).zone)
        self.assertEqual(Zone.EXILE, self.current(first).zone)
        self.depart(original)
        self.assertEqual(Zone.BATTLEFIELD, self.current(first).zone)

    def test_link_vocabulary_is_closed_and_nested_effects_are_checked(self):
        good = CardProgram('fixture:valid', 'Valid', ('Artifact',), spell_effects=(
            ExileLinked('source', 'one'), WithLinkedExile('one', (Move('linked', Zone.BATTLEFIELD),)),))
        self.assertEqual(good, decode(encode(validate(good))))
        for effect in (ExileLinked('missing', 'one'), ExileLinked('source', ''),
                       ExileLinked('source', True), WithLinkedExile(' ', ()),
                       WithLinkedExile('one', [Move('linked', Zone.HAND)]),
                       WithLinkedExile('one', (Move('missing', Zone.HAND),)),
                       Move('linked', Zone.BATTLEFIELD)):
            with self.subTest(effect=effect), self.assertRaises(RulesViolation):
                validate(replace(good, spell_effects=(effect,)))
        with self.assertRaises(RulesViolation):
            validate(replace(good, spell_targets=TargetSpec(players='opponents'),
                             spell_effects=(ExileLinked('target', 'one'),)))
        with self.assertRaises(RulesViolation):
            validate(CardProgram('fixture:hidden', 'Hidden', ('Artifact',),
                activated=(ActivatedProgram('exile', CostSpec(), (ExileLinked('source', 'one'),),
                                            zone=Zone.HAND),)))
        nested = WithLinkedExile('one', (Move('linked', Zone.BATTLEFIELD), GainLife(1)))
        self.assertEqual(3, len(tuple(immediate_effect_nodes((nested,)))))
