"""Printed Animate Dead through shared casting, attachment and delayed-trigger code."""
import json
from pathlib import Path
import unittest

from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_actor import project_actor
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_program import (
    Attach, CardProgram, CastSpec, CostSpec, Counter, CounterAbilities, ManaCost,
    Move, SelectAll, Selector, TargetSpec, WithMoved, ZoneReplacement,
)
from edh_gauntlet.rules_state import RulesState, RulesViolation, Zone


class AnimateDeadCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        rows = load_reviewed(root)
        cls.animate = rows['animate-dead']['program']
        cls.reviewed = tuple(row['program'] for row in rows.values())
        cls.fixtures = (
            CardProgram('fixture:body', 'Body', ('Creature',), power=3, toughness=4),
            CardProgram('fixture:elf', 'Unrelated Elf', ('Creature',), subtypes=('Elf',), power=2, toughness=3),
            CardProgram('fixture:artifact', 'Artifact', ('Artifact',)),
            CardProgram('fixture:remove', 'Remove permanent', ('Instant',),
                        spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD)),
                        spell_effects=(Move('target', Zone.EXILE),)),
            CardProgram('fixture:grave-exile', 'Exile grave card', ('Instant',),
                        spell_targets=TargetSpec(Selector(Zone.GRAVEYARD)),
                        spell_effects=(Move('target', Zone.EXILE),)),
            CardProgram('fixture:blink', 'Blink creature', ('Instant',),
                        spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD, types=('Creature',))),
                        spell_effects=(WithMoved('target', Zone.EXILE,
                            (Move('moved', Zone.BATTLEFIELD, controller='owner'),)),)),
            CardProgram('fixture:counter-abilities', 'Counter abilities', ('Instant',),
                        spell_effects=(CounterAbilities('all'),)),
            CardProgram('fixture:counter-spell', 'Counter spell', ('Instant',),
                        spell_targets=TargetSpec(Selector(Zone.STACK)),
                        spell_effects=(Counter('target'),)),
        )

    def game(self, *extra):
        self.programs = self.reviewed + self.fixtures + extra
        self.state = RulesState(('A', 'B'))
        self.kernel = RulesKernel(self.state, self.programs)
        self.kernel.open_window_for_scenario('A')

    def add(self, key, name=None, owner='A', zone=Zone.BATTLEFIELD, **kwargs):
        definition = self.animate.definition_id if key == 'animate-dead' else key if key.startswith('fixture:') else 'catalog:' + key
        return self.state.add_card(name or key, definition, owner, zone, **kwargs)

    def current(self, ref):
        return self.state.get(self.state.current(ref.card_id))

    def drain(self, kernel=None):
        kernel = kernel or self.kernel
        for _ in range(150):
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

    def choose_refs(self, refs, kind, kernel=None):
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

    def cast_aura(self, target):
        aura = self.add('animate-dead', zone=Zone.HAND)
        self.state.add_mana('A', ('C', 'B'))
        quote = self.kernel.quote_cast('animate', 'A', aura, (target,))
        self.assertEqual(ManaCost(1, ('B',)), quote.cost.mana)
        self.kernel.commit_action(quote, Payment((('C', 1), ('B', 1))))
        self.resolve_one()  # Resolve only the Aura spell; keep its entry trigger.
        return self.current(aura).ref

    def reanimate(self, target):
        aura = self.cast_aura(target)
        self.drain()
        return aura, self.current(target).ref

    def response(self, key, target=None):
        if not self.kernel.stack:
            self.kernel.open_window_for_scenario('A')
        for _ in range(4):
            if self.kernel.priority == 'A':
                break
            self.kernel.pass_priority(self.kernel.priority)
        else:
            self.fail('A did not receive response priority')
        spell = self.add(key, 'response-' + str(self.state.sequence), zone=Zone.HAND)
        self.kernel.stage_spell_for_scenario(spell, 'A', (target,) if target else ())
        return self.resolve_one()

    def test_printed_cast_returns_from_either_graveyard_and_attaches_with_minus_one_power(self):
        for owner in ('A', 'B'):
            with self.subTest(owner=owner):
                self.game()
                target = self.add('fixture:body', owner=owner, zone=Zone.GRAVEYARD)
                aura = self.cast_aura(target)
                self.assertEqual(target, self.state.get(aura).attached_to)
                self.assertEqual(Zone.GRAVEYARD, self.current(target).zone)
                self.assertEqual((), self.state.mana_pool('A'))
                self.assertEqual({'Enchantment'}, set(self.kernel.effective(aura).types))
                self.assertIn('Aura', self.kernel.effective(aura).subtypes)
                self.assertEqual({'B'}, set(self.kernel.effective(aura).colors))
                self.drain()
                creature = self.current(target)
                self.assertEqual((Zone.BATTLEFIELD, 'A', owner), (creature.zone, creature.controller, creature.owner))
                self.assertEqual(creature.ref, self.state.get(aura).attached_to)
                view = self.kernel.effective(creature.ref)
                self.assertEqual((2, 4), (view.power, view.toughness))
                self.assertEqual(1, len(self.kernel.delayed_triggers))

    def test_graveyard_shroud_and_hexproof_allow_cast_and_nontargeted_attachment(self):
        for keyword in ('shroud', 'hexproof'):
            protected = CardProgram('fixture:protected', 'Protected', ('Creature',),
                                    power=4, toughness=4, keywords=(keyword,))
            with self.subTest(keyword=keyword):
                self.game(protected)
                target = self.add('fixture:protected', owner='B', zone=Zone.GRAVEYARD)
                self.assertIn(keyword, self.kernel.effective(target).keywords)
                aura, creature = self.reanimate(target)
                self.assertEqual(creature, self.state.get(aura).attached_to)
                self.assertEqual((3, 4), (self.kernel.effective(creature).power, self.kernel.effective(creature).toughness))

    def test_shroud_and_hexproof_on_creature_spells_do_not_prevent_counterspell(self):
        for keyword in ('shroud', 'hexproof'):
            protected = CardProgram('fixture:protected', 'Protected spell', ('Creature',),
                                    power=4, toughness=4, keywords=(keyword,), cast=CastSpec(CostSpec()))
            with self.subTest(keyword=keyword):
                self.game(protected)
                victim = self.add('fixture:protected', owner='B', zone=Zone.HAND)
                counter = self.add('counterspell', zone=Zone.HAND)
                self.kernel.open_window_for_scenario('B')
                self.kernel.stage_spell_for_scenario(victim, 'B')
                self.kernel.pass_priority('B')
                self.state.add_mana('A', ('U', 'U'))
                self.kernel.commit_action(self.kernel.quote_cast('counter', 'A', counter,
                    (self.current(victim).ref,)), Payment((('U', 2),)))
                self.drain()
                self.assertEqual(Zone.GRAVEYARD, self.current(victim).zone)
                self.assertEqual(Zone.GRAVEYARD, self.current(counter).zone)

    def test_battlefield_keyword_permissions_still_reject_opponents_and_shroud_self_targets(self):
        for keyword, controller, allowed in (('shroud', 'A', False), ('shroud', 'B', False),
                                              ('hexproof', 'A', True), ('hexproof', 'B', False)):
            with self.subTest(keyword=keyword, controller=controller):
                protected = CardProgram('fixture:protected', 'Protected', ('Creature',),
                                        power=4, toughness=4, keywords=(keyword,))
                self.game(protected)
                target = self.add('fixture:protected', owner='B', controller=controller)
                spell = self.add('fixture:remove', zone=Zone.HAND)
                if allowed:
                    self.kernel.stage_spell_for_scenario(spell, 'A', (target,))
                    self.drain()
                    self.assertEqual(Zone.EXILE, self.current(target).zone)
                else:
                    before = self.kernel.snapshot()
                    with self.assertRaises(RulesViolation):
                        self.kernel.stage_spell_for_scenario(spell, 'A', (target,))
                    self.assertEqual(before, self.kernel.snapshot())

    def test_wrong_cast_targets_are_rejected_before_payment(self):
        self.game()
        artifact = self.add('fixture:artifact', zone=Zone.GRAVEYARD)
        battlefield = self.add('fixture:body')
        hand = self.add('fixture:body', 'hand-body', zone=Zone.HAND)
        aura = self.add('animate-dead', zone=Zone.HAND)
        self.state.add_mana('A', ('C', 'B'))
        before = self.kernel.snapshot()
        for targets in ((), (artifact,), (battlefield,), (hand,)):
            with self.subTest(targets=targets), self.assertRaises(RulesViolation):
                self.kernel.quote_cast('invalid', 'A', aura, targets)
            self.assertEqual(before, self.kernel.snapshot())

    def test_target_leaving_graveyard_before_spell_resolution_counters_the_aura(self):
        self.game()
        target = self.add('fixture:body', owner='B', zone=Zone.GRAVEYARD)
        aura = self.add('animate-dead', zone=Zone.HAND)
        self.state.add_mana('A', ('C', 'B'))
        self.kernel.commit_action(self.kernel.quote_cast('animate', 'A', aura, (target,)),
                                  Payment((('C', 1), ('B', 1))))
        self.response('fixture:grave-exile', target)
        self.drain()
        self.assertEqual(Zone.GRAVEYARD, self.current(aura).zone)
        self.assertEqual(Zone.EXILE, self.current(target).zone)
        self.assertFalse(self.kernel.delayed_triggers)

    def test_countered_aura_spell_never_returns_the_creature(self):
        self.game()
        target = self.add('fixture:body', zone=Zone.GRAVEYARD)
        aura = self.add('animate-dead', zone=Zone.HAND)
        self.state.add_mana('A', ('C', 'B'))
        self.kernel.commit_action(self.kernel.quote_cast('animate', 'A', aura, (target,)),
                                  Payment((('C', 1), ('B', 1))))
        self.response('fixture:counter-spell', self.current(aura).ref)
        self.drain()
        self.assertEqual(Zone.GRAVEYARD, self.current(aura).zone)
        self.assertEqual(Zone.GRAVEYARD, self.current(target).zone)
        self.assertFalse(self.kernel.delayed_triggers)

    def test_countered_entry_trigger_keeps_aura_attached_to_graveyard_card(self):
        self.game()
        target = self.add('fixture:body', zone=Zone.GRAVEYARD)
        aura = self.cast_aura(target)
        self.response('fixture:counter-abilities')
        self.drain()
        self.assertEqual(Zone.BATTLEFIELD, self.state.get(aura).zone)
        self.assertEqual(target, self.state.get(aura).attached_to)
        self.assertEqual(3, self.kernel.effective(target).power)
        self.assertFalse(self.kernel.delayed_triggers)

    def test_removing_aura_before_entry_trigger_prevents_reanimation(self):
        self.game()
        target = self.add('fixture:body', zone=Zone.GRAVEYARD)
        aura = self.cast_aura(target)
        self.response('fixture:remove', aura)
        self.drain()
        self.assertEqual(Zone.EXILE, self.current(aura).zone)
        self.assertEqual(Zone.GRAVEYARD, self.current(target).zone)
        self.assertFalse(self.kernel.delayed_triggers)

    def test_entry_trigger_controller_keeps_return_instruction_after_aura_control_changes(self):
        self.game()
        target = self.add('fixture:body', owner='B', zone=Zone.GRAVEYARD)
        aura = self.cast_aura(target)
        self.state.change_control(aura, 'B')
        self.drain()
        self.assertEqual('A', self.current(target).controller)
        self.assertEqual('B', self.state.get(aura).controller)
        self.assertEqual(self.current(target).ref, self.state.get(aura).attached_to)
        self.assertEqual('A', self.kernel.delayed_triggers[0]['controller'])

    def test_delayed_trigger_controller_is_fixed_but_current_creature_controller_sacrifices(self):
        self.game()
        target = self.add('fixture:body', owner='B', zone=Zone.GRAVEYARD)
        aura, creature = self.reanimate(target)
        self.state.change_control(aura, 'B')
        self.state.change_control(creature, 'B')
        self.kernel.execute_for_scenario(aura, 'B', (Move('source', Zone.HAND, controller='owner'),))
        self.assertEqual('A', self.kernel.stack[-1]['controller'])
        self.assertEqual(Zone.BATTLEFIELD, self.state.get(creature).zone)
        self.drain()
        self.assertEqual(Zone.GRAVEYARD, self.current(target).zone)
        self.assertEqual('B', self.current(target).owner)
        self.assertFalse(self.kernel.delayed_triggers)

    def test_blink_resets_the_creature_and_old_sacrifice_cannot_hit_new_incarnation(self):
        self.game()
        target = self.add('fixture:body', owner='B', zone=Zone.GRAVEYARD)
        aura, creature = self.reanimate(target)
        self.response('fixture:blink', creature)
        self.drain()
        self.assertNotEqual(creature, self.current(target).ref)
        self.assertEqual(Zone.BATTLEFIELD, self.current(target).zone)
        self.assertEqual('B', self.current(target).controller)
        self.assertEqual(3, self.kernel.effective(self.current(target).ref).power)
        self.assertEqual(Zone.GRAVEYARD, self.current(aura).zone)
        self.assertFalse(self.kernel.delayed_triggers)

    def test_noncreature_god_cannot_be_attached_and_is_sacrificed_after_aura_falls_off(self):
        self.game()
        target = self.add('xenagos-god-of-revels', zone=Zone.GRAVEYARD)
        aura = self.cast_aura(target)
        self.resolve_one()
        god = self.current(target)
        self.assertEqual(Zone.BATTLEFIELD, god.zone)
        self.assertNotIn('Creature', self.kernel.effective(god.ref).types)
        self.assertEqual(Zone.GRAVEYARD, self.current(aura).zone)
        self.assertIsNone(self.current(aura).attached_to)
        self.assertTrue(self.kernel.stack)
        self.drain()
        self.assertEqual(Zone.GRAVEYARD, self.current(target).zone)

    def test_blocked_or_redirected_reanimation_never_attaches_or_registers_sacrifice(self):
        redirect = CardProgram('fixture:redirect', 'Redirect entry', ('Enchantment',),
            replacements=(ZoneReplacement('exile', Zone.BATTLEFIELD, Zone.EXILE, types=('Creature',)),))
        for blocker, destination in (('kunoros-hound-of-athreos', Zone.GRAVEYARD),
                                      ('fixture:redirect', Zone.EXILE)):
            with self.subTest(blocker=blocker):
                self.game(redirect)
                self.add(blocker, owner='B')
                target = self.add('fixture:body', zone=Zone.GRAVEYARD)
                aura = self.cast_aura(target)
                self.drain()
                self.assertEqual(destination, self.current(target).zone)
                self.assertEqual(Zone.GRAVEYARD, self.current(aura).zone)
                self.assertFalse(self.kernel.delayed_triggers)

    def test_changed_enchant_rule_rejects_an_unrelated_creature(self):
        self.game()
        target = self.add('fixture:body', zone=Zone.GRAVEYARD)
        other = self.add('fixture:elf')
        aura, creature = self.reanimate(target)
        self.kernel.execute_for_scenario(aura, 'A', (SelectAll(
            Selector(Zone.BATTLEFIELD, subtypes=('Elf',)), (Attach('source', 'selected'),)),))
        self.assertEqual(creature, self.state.get(aura).attached_to)
        self.assertEqual(2, self.kernel.effective(creature).power)
        self.assertEqual(2, self.kernel.effective(other).power)

    def test_starfield_returns_aura_with_owner_chosen_graveyard_attachment(self):
        self.game()
        self.add('starfield-of-nyx')
        target = self.add('fixture:body', owner='B', zone=Zone.GRAVEYARD)
        aura = self.add('animate-dead', zone=Zone.GRAVEYARD)
        self.kernel.begin_step('A', 'upkeep')
        self.choose_refs((aura,), 'trigger_targets')
        self.drain()
        self.choose('yes')
        self.choose_refs((target,), 'aura_attachment')
        self.drain()
        self.assertEqual(self.current(target).ref, self.current(aura).attached_to)
        self.assertEqual('A', self.current(target).controller)

    def test_oblivion_ring_returns_aura_after_delayed_sacrifice_puts_creature_in_graveyard(self):
        self.game()
        target = self.add('fixture:body', owner='B', zone=Zone.GRAVEYARD)
        aura, creature = self.reanimate(target)
        ring = self.add('oblivion-ring', owner='B', zone=Zone.HAND)
        self.kernel.enter(ring)
        self.choose_refs((aura,), 'trigger_targets')
        self.drain()
        self.assertEqual(Zone.EXILE, self.current(aura).zone)
        self.assertEqual(Zone.GRAVEYARD, self.current(target).zone)
        self.kernel.execute_for_scenario(self.current(ring).ref, 'B', (Move('source', Zone.GRAVEYARD),))
        self.drain()
        self.assertEqual('A', self.kernel.pending_choice.actor)
        self.choose_refs((self.current(target).ref,), 'aura_attachment')
        self.drain()
        self.assertNotEqual(creature, self.current(target).ref)
        self.assertEqual(self.current(target).ref, self.current(aura).attached_to)

    def test_three_relic_warder_cycles_replay_and_stop_at_an_explicit_decline(self):
        self.game()
        warder = self.add('leonin-relic-warder', zone=Zone.GRAVEYARD)
        aura = self.add('animate-dead', zone=Zone.HAND)
        self.state.add_mana('A', ('C', 'B'))
        adapter = RulesActorAdapter(self.kernel)
        adapter.submit('A', {'kind': 'cast', 'revision': self.kernel.revision,
            'action_id': 'animate', 'source': aura.to_json(), 'targets': [warder.to_json()],
            'x_value': 0, 'payment': {'mana': {'C': 1, 'B': 1}, 'taps': []}})
        accepted = 0
        checked = False
        for _ in range(150):
            request = self.kernel.pending_choice
            if request:
                if request.kind == 'trigger_targets':
                    ref = self.current(aura).ref
                    indexes = [next(i for i, option in enumerate(request.options) if option.ref == ref)]
                elif request.kind == 'may':
                    key = 'yes' if accepted < 3 else 'no'
                    if key == 'yes':
                        accepted += 1
                    indexes = [next(i for i, option in enumerate(request.options) if option.key == key)]
                elif request.kind == 'aura_attachment':
                    ref = self.current(warder).ref
                    indexes = [next(i for i, option in enumerate(request.options) if option.ref == ref)]
                    if not checked:
                        replay = RulesActorAdapter.replay(adapter.archive(), self.programs)
                        self.assertEqual(adapter.archive(), replay.archive())
                        checked = True
                else:
                    self.fail('Unexpected cycle choice: ' + request.kind)
                adapter.submit(request.actor, {'kind': 'answer', 'revision': self.kernel.revision,
                    'request_id': request.request_id, 'indexes': indexes})
            elif self.kernel.stack:
                adapter.submit(self.kernel.priority, {'kind': 'pass', 'revision': self.kernel.revision})
            else:
                break
        else:
            self.fail('Finite optional cycles did not settle')
        self.assertTrue(checked)
        self.assertEqual(3, accepted)
        self.assertEqual(Zone.BATTLEFIELD, self.current(aura).zone)
        self.assertEqual(self.current(warder).ref, self.current(aura).attached_to)
        self.assertEqual((1, 2), (self.kernel.effective(self.current(warder).ref).power,
                                    self.kernel.effective(self.current(warder).ref).toughness))
        self.assertEqual(3, sum(event.before.ref.card_id == warder.card_id and
                               event.after.zone == Zone.GRAVEYARD for event in self.state.events))
        self.assertEqual(1, len(self.kernel.delayed_triggers))
        self.assertNotIn('linked_exile', project_actor(self.kernel, 'B'))
        replay = RulesActorAdapter.replay(adapter.archive(), self.programs)
        self.assertEqual(adapter.archive(), replay.archive())

    def test_entry_trigger_checkpoint_preserves_attachment_and_delayed_identity(self):
        self.game()
        target = self.add('fixture:body', owner='B', zone=Zone.GRAVEYARD)
        aura = self.cast_aura(target)
        restored = RulesKernel.restore(json.loads(json.dumps(self.kernel.snapshot())), self.programs)
        self.drain()
        self.drain(restored)
        self.assertEqual(self.kernel.snapshot(), restored.snapshot())
        self.assertEqual(self.current(target).ref, self.state.get(aura).attached_to)
        self.assertEqual(1, len(self.kernel.delayed_triggers))
        old = self.kernel.snapshot()
        old['schema'] = 111
        with self.assertRaises(RulesViolation):
            RulesKernel.restore(old, self.programs)
