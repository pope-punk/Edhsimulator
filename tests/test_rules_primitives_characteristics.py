import json
import unittest
from dataclasses import replace
from edh_gauntlet.rules_state import RulesState, Zone, ZoneMove
from edh_gauntlet.rules_program import (CardProgram, ContinuousProgram, Selector, CountCondition,
    ChangeTypes, SetPT, ModifyPT, SwitchPT, Move, Select, AbilityProgram, EventPattern, GainLife)
from edh_gauntlet.rules_kernel import RulesKernel, PriorityBoundary
from edh_gauntlet.rules_scenarios import fixture_programs


class CharacteristicTests(unittest.TestCase):
    def setUp(self):
        self.state = RulesState(('A', 'B'))
        self.programs = list(fixture_programs())

    def add(self, key, definition, zone=Zone.BATTLEFIELD, owner='A'):
        return self.state.add_card(key, definition, owner, zone)

    def define(self, name, types, *, effects=(), **kwargs):
        self.programs.append(CardProgram(name, name, types, continuous=effects, **kwargs))
        return name

    def kernel(self):
        return RulesKernel(self.state, self.programs)

    def answer(self, kernel, indexes):
        choice = kernel.pending_choice
        return kernel.answer(choice.request_id, choice.actor, indexes)

    def drain(self, kernel):
        for _ in range(50):
            boundary = kernel.advance()
            if boundary is None:
                return
            self.assertIsInstance(boundary, PriorityBoundary)
            kernel.pass_priority(boundary.actor)
        self.fail('Did not settle')

    def field(self, name, *changes, selector=None, subject='any', condition=None):
        self.define(name, ('Enchantment',), effects=(ContinuousProgram(name,
            selector or Selector(Zone.BATTLEFIELD, ('Creature',)), changes, subject, condition),))
        return self.add(name, name)

    def starfield_board(self, others=4):
        source = self.add('s', 'starfield')
        refs = [self.add('e'+str(i), 'enchantment') for i in range(others)]
        return source, refs

    def test_starfield_threshold_is_dynamic_and_excludes_itself(self):
        source, refs = self.starfield_board(3)
        kernel = self.kernel()
        self.assertNotIn('Creature', kernel.effective(refs[0]).types)
        extra = self.add('extra', 'enchantment')
        self.assertEqual((2, 2), (kernel.effective(refs[0]).power, kernel.effective(refs[0]).toughness))
        self.assertIn('Creature', kernel.effective(refs[0]).types)
        self.assertNotIn('Creature', kernel.effective(source).types)
        self.state.move((ZoneMove(extra, Zone.EXILE),), 'threshold-change')
        self.assertNotIn('Creature', kernel.effective(refs[0]).types)

    def test_aura_counts_for_threshold_but_is_not_animated(self):
        source, refs = self.starfield_board(3)
        aura = self.add('aura', 'animate')
        kernel = self.kernel()
        self.assertIn('Creature', kernel.effective(refs[0]).types)
        self.assertNotIn('Creature', kernel.effective(aura).types)
        self.assertIn('Aura', kernel.effective(aura).subtypes)

    def test_two_starfields_animate_each_other(self):
        source, refs = self.starfield_board(3)
        second = self.add('second', 'starfield')
        kernel = self.kernel()
        self.assertIn('Creature', kernel.effective(source).types)
        self.assertEqual(5, kernel.effective(source).toughness)
        self.assertEqual(5, kernel.effective(second).power)

    def test_phased_and_opponent_enchantments_do_not_meet_threshold(self):
        source, refs = self.starfield_board(3)
        self.add('opponent', 'enchantment', owner='B')
        phased = self.add('phased', 'enchantment')
        self.state.phase(phased, True)
        kernel = self.kernel()
        self.assertNotIn('Creature', kernel.effective(refs[0]).types)
        self.state.phase(phased, False)
        self.assertIn('Creature', kernel.effective(refs[0]).types)

    def test_base_set_modifiers_counters_then_switch(self):
        creature = self.add('c', 'creature')
        self.field('switch', SwitchPT())
        self.field('modifier', ModifyPT(3, -1))
        self.field('setter', SetPT(4, 6))
        self.state.add_counters(creature, '+1/+1', 2)
        self.state.add_counters(creature, '-1/-1', 1)
        kernel = self.kernel()
        view = kernel.effective(creature)
        self.assertEqual((6, 8), (view.power, view.toughness))
        self.assertEqual(2, self.state.get(creature).counters[0][1])

    def test_later_setter_wins_and_blink_changes_timestamp(self):
        creature = self.add('c', 'creature')
        first = self.field('first', SetPT(3, 3))
        self.field('second', SetPT(7, 7))
        kernel = self.kernel()
        self.assertEqual(7, kernel.effective(creature).power)
        self.state.move((ZoneMove(first, Zone.EXILE),), 'out')
        self.state.move((ZoneMove(self.state.current('first'), Zone.BATTLEFIELD),), 'in')
        self.assertEqual(3, kernel.effective(creature).power)

    def test_dependency_precedes_timestamp(self):
        artifact = self.add('c', self.define('artifact', ('Artifact',), mana_value=4))
        self.field('earlier', ChangeTypes(add=('Enchantment',)),
                   selector=Selector(Zone.BATTLEFIELD, ('Creature',)))
        self.field('later', ChangeTypes(add=('Creature',)),
                   selector=Selector(Zone.BATTLEFIELD, ('Artifact',)))
        kernel = self.kernel()
        self.assertEqual({'Artifact', 'Creature', 'Enchantment'}, kernel.effective(artifact).types)
        self.assertEqual(('later', 'earlier'), kernel.effective(artifact).applied)

    def test_multilayer_effect_keeps_original_recipients(self):
        artifact = self.add('c', self.define('artifact', ('Artifact',), mana_value=4))
        self.field('animator', ChangeTypes(add=('Creature',), remove=('Artifact',)), SetPT(4, 5),
                   selector=Selector(Zone.BATTLEFIELD, ('Artifact',)))
        kernel = self.kernel()
        self.assertEqual({'Creature'}, kernel.effective(artifact).types)
        self.assertEqual((4, 5), (kernel.effective(artifact).power, kernel.effective(artifact).toughness))

    def test_zero_toughness_cleanup_uses_derived_view(self):
        creature = self.add('c', self.define('fragile', ('Creature',), power=1, toughness=0))
        buff = self.field('buff', ModifyPT(0, 1))
        kernel = self.kernel()
        self.assertIsNone(kernel.advance())
        kernel.execute_for_scenario(buff, 'A', (Move('source', Zone.EXILE),))
        self.assertEqual(Zone.GRAVEYARD, self.state.get(self.state.current('c')).zone)

    def test_losing_starfield_threshold_changes_target_legality(self):
        source, refs = self.starfield_board()
        kernel = self.kernel()
        context = {'source': self.state.get(source).to_json(), 'controller': 'A'}
        selector = Selector(Zone.BATTLEFIELD, ('Creature',))
        self.assertEqual(set(refs), {obj.ref for obj in kernel._query(selector, context)})
        self.state.move((ZoneMove(refs[-1], Zone.EXILE),), 'threshold-change')
        self.assertFalse(kernel._query(selector, context))

    def test_animated_enchantment_death_uses_pre_event_types(self):
        source, refs = self.starfield_board()
        death = AbilityProgram('dies', EventPattern('zone_changed', from_zone=Zone.BATTLEFIELD,
            to_zone=Zone.GRAVEYARD, types=('Creature',)), (GainLife(1),))
        self.add('observer', self.define('observer', ('Artifact',), abilities=(death,)))
        kernel = self.kernel()
        kernel.execute_for_scenario(refs[0], 'A', (Move('source', Zone.GRAVEYARD),))
        self.drain(kernel)
        self.assertEqual(41, self.state.life('A'))
        self.assertNotIn('Creature', kernel.effective(refs[1]).types)

    def test_simultaneous_effect_timestamps_are_player_chosen_and_checkpointed(self):
        for name, size in (('small', 3), ('large', 7)):
            self.define(name, ('Enchantment',), effects=(ContinuousProgram(name,
                Selector(Zone.BATTLEFIELD, ('Creature',)), (SetPT(size, size),)),))
            self.add(name, name, Zone.HAND)
        creature = self.add('c', 'creature')
        kernel = self.kernel()
        kernel.execute_for_scenario(creature, 'A', (Select(Selector(Zone.HAND, ('Enchantment',)), 2, 2,
            (Move('selected', Zone.BATTLEFIELD),)),))
        self.assertEqual('timestamp_order', kernel.pending_choice.kind)
        self.assertEqual(Zone.HAND, self.state.get(self.state.current('small')).zone)
        restored = RulesKernel.restore(json.loads(json.dumps(kernel.snapshot())), self.programs)
        self.answer(kernel, [1, 0])
        self.answer(restored, [1, 0])
        self.assertEqual(kernel.snapshot(), restored.snapshot())
        self.assertEqual(3, kernel.effective(creature).power)

    def test_read_only_views_are_immutable_and_mutations_invalidate_cache(self):
        creature = self.add('c', 'creature')
        kernel = self.kernel()
        first = kernel.characteristics()
        self.assertIs(first, kernel.characteristics())
        with self.assertRaises(TypeError):
            first[creature] = None
        self.state.add_counters(creature, '+1/+1', 1)
        self.assertEqual(2, first[creature].power)
        self.assertEqual(3, kernel.effective(creature).power)
        self.assertIsNot(first, kernel.characteristics())


    def test_dependency_cycle_uses_timestamp_then_rechecks_remaining_effects(self):
        creature = self.add('c', self.define('hybrid', ('Creature', 'Artifact'), power=2, toughness=2))
        self.field('earlier', ChangeTypes(remove=('Artifact',)), selector=Selector(Zone.BATTLEFIELD, ('Creature',)))
        self.field('later', ChangeTypes(remove=('Creature',)), selector=Selector(Zone.BATTLEFIELD, ('Artifact',)))
        kernel = self.kernel()
        self.assertEqual({'Creature'}, kernel.effective(creature).types)
        self.assertEqual(('earlier',), kernel.effective(creature).applied)

    def test_copied_values_do_not_copy_modifiers_or_counters(self):
        self.add('u', 'uro', Zone.GRAVEYARD)
        body = self.add('b', 'body-double', Zone.HAND)
        self.add('draw', 'creature', Zone.LIBRARY)
        self.field('buff', ModifyPT(2, 1))
        kernel = self.kernel()
        kernel.enter(body)
        self.answer(kernel, [0])
        view = kernel.effective(self.state.current('b'))
        self.assertEqual((8, 7, 3), (view.power, view.toughness, view.mana_value))
        self.assertEqual('uro', self.state.get(self.state.current('b')).copied_definition)

    def test_multiple_zero_toughness_creatures_leave_simultaneously(self):
        fragile = self.define('fragile', ('Creature',), power=1, toughness=0)
        self.add('a', fragile)
        self.add('b', fragile)
        kernel = self.kernel()
        self.assertIsNone(kernel.advance())
        deaths = [event for event in self.state.events if event.cause == 'permanent_sba']
        self.assertEqual(2, len(deaths))
        self.assertEqual(1, len({event.batch for event in deaths}))


    def test_creature_death_replacement_sees_animated_enchantment(self):
        from edh_gauntlet.rules_program import ZoneReplacement
        source, refs = self.starfield_board()
        replacement = ZoneReplacement('exile-creatures', Zone.GRAVEYARD, Zone.EXILE,
                                      from_zone=Zone.BATTLEFIELD, types=('Creature',))
        self.add('exiler', self.define('exiler', ('Artifact',), replacements=(replacement,)))
        kernel = self.kernel()
        kernel.execute_for_scenario(refs[0], 'A', (Move('source', Zone.GRAVEYARD),))
        self.assertEqual(Zone.EXILE, self.state.get(self.state.current('e0')).zone)
        self.assertEqual(1, len(self.state.events))

    def test_entry_lookahead_does_not_count_incoming_fifth_enchantment(self):
        from edh_gauntlet.rules_program import ZoneReplacement
        source, refs = self.starfield_board(3)
        replacement = ZoneReplacement('exile-creature-entry', Zone.BATTLEFIELD, Zone.EXILE, types=('Creature',))
        self.add('exiler', self.define('exiler', ('Artifact',), replacements=(replacement,)))
        entering = self.add('incoming', 'enchantment', Zone.HAND)
        kernel = self.kernel()
        kernel.enter(entering)
        self.assertEqual(Zone.BATTLEFIELD, self.state.get(self.state.current('incoming')).zone)
        self.assertIn('Creature', kernel.effective(self.state.current('incoming')).types)
        self.assertIn('Creature', kernel.effective(refs[0]).types)

    def test_rules_definitions_cannot_be_mutated_behind_cached_views(self):
        creature = self.add('c', 'creature')
        kernel = self.kernel()
        before = kernel.effective(creature)
        with self.assertRaises(TypeError):
            kernel.definitions['creature'] = replace(kernel.definitions['creature'], power=99)
        self.assertIs(before, kernel.effective(creature))


    def test_entry_replacement_uses_already_active_animation(self):
        from edh_gauntlet.rules_program import ZoneReplacement
        source, refs = self.starfield_board(4)
        replacement = ZoneReplacement('exile-creature-entry', Zone.BATTLEFIELD, Zone.EXILE, types=('Creature',))
        self.add('exiler', self.define('exiler', ('Artifact',), replacements=(replacement,)))
        entering = self.add('incoming', 'enchantment', Zone.HAND)
        kernel = self.kernel()
        kernel.enter(entering)
        self.assertEqual(Zone.EXILE, self.state.get(self.state.current('incoming')).zone)


    def test_opposing_counters_cancel_before_proliferate_choice(self):
        from edh_gauntlet.rules_program import Proliferate
        creature = self.add('c', 'creature')
        self.state.add_counters(creature, '+1/+1', 2)
        self.state.add_counters(creature, '-1/-1', 1)
        kernel = self.kernel()
        self.assertIsNone(kernel.advance())
        self.assertEqual({'+1/+1': 1}, dict(self.state.get(creature).counters))
        kernel.execute_for_scenario(creature, 'A', (Proliferate(),))
        self.answer(kernel, [0])
        self.assertEqual({'+1/+1': 2}, dict(self.state.get(creature).counters))
        self.assertEqual(4, kernel.effective(creature).toughness)

    def test_target_groups_reject_invalid_announcement_without_mutation(self):
        from edh_gauntlet.rules_program import TargetSpec
        from edh_gauntlet.rules_state import RulesViolation
        self.define('group-spell', ('Instant',), spell_targets=TargetSpec(
            Selector(Zone.BATTLEFIELD, ('Creature',)), 2, 2, True), spell_effects=(GainLife(1),))
        spell = self.add('spell', 'group-spell', Zone.HAND)
        targets = (self.add('a', 'creature', owner='B'), self.add('b', 'creature', owner='B'))
        kernel = self.kernel()
        before = kernel.snapshot()
        with self.assertRaises(RulesViolation):
            kernel.stage_spell_for_scenario(spell, 'A', targets)
        self.assertEqual(before, kernel.snapshot())

    def test_impossible_required_target_groups_do_not_create_unanswerable_choice(self):
        from edh_gauntlet.rules_program import TargetSpec
        self.define('group-trigger', ('Artifact',), abilities=(AbilityProgram('groups',
            EventPattern('zone_changed', to_zone=Zone.BATTLEFIELD, subject='self'),
            (GainLife(1),), TargetSpec(Selector(Zone.BATTLEFIELD, ('Creature',)), 2, 2, True)),))
        source = self.add('source', 'group-trigger', Zone.HAND)
        self.add('a', 'creature', owner='B')
        self.add('b', 'creature', owner='B')
        kernel = self.kernel()
        self.assertIsNone(kernel.enter(source))
        self.assertFalse(kernel.pending_choice)
        self.assertTrue(any(event['kind'] == 'trigger_unplaceable' for event in kernel.semantic_events))


    def test_creature_aura_detaches_before_unattached_aura_cleanup(self):
        creature = self.add('c', 'creature')
        self.define('plain-aura', ('Enchantment',), enchant=Selector(Zone.BATTLEFIELD, ('Creature',)))
        aura = self.add('aura', 'plain-aura')
        self.state.attach(aura, creature)
        self.field('animate-auras', ChangeTypes(add=('Creature',)), SetPT(2, 2),
                   selector=Selector(Zone.BATTLEFIELD, subtypes=('Aura',)))
        kernel = self.kernel()
        self.assertIsNone(kernel.advance())
        departure = next(event for event in self.state.events if event.before.ref == aura)
        self.assertIsNone(departure.before.attached_to)
        self.assertTrue(any(event['kind'] == 'detached' for event in kernel.semantic_events))
        self.assertEqual(Zone.BATTLEFIELD, self.state.get(creature).zone)

    def test_invalid_mixed_state_action_batch_is_atomic(self):
        from edh_gauntlet.rules_state import RulesViolation, ObjectRef
        creature = self.add('c', 'creature')
        before = self.state.snapshot()
        with self.assertRaises(RulesViolation):
            self.state.move((ZoneMove(creature, Zone.EXILE),), 'invalid-mixed-batch',
                            counter_pairs=(ObjectRef('missing', 0),))
        self.assertEqual(before, self.state.snapshot())


    def test_omitted_creature_stats_are_rejected_instead_of_assumed_zero(self):
        from edh_gauntlet.rules_program import validate
        from edh_gauntlet.rules_state import RulesViolation
        with self.assertRaisesRegex(RulesViolation, 'explicit base power'):
            validate(CardProgram('incomplete', 'Incomplete', ('Creature',)))


    def test_checkpoint_rejects_a_different_engine_implementation(self):
        from edh_gauntlet.rules_state import RulesViolation
        self.add('c', 'creature')
        kernel = self.kernel()
        snapshot = kernel.snapshot()
        snapshot['implementation'] = 'a-different-source-bundle'
        with self.assertRaisesRegex(RulesViolation, 'implementation or Python runtime changed'):
            RulesKernel.restore(snapshot, self.programs)
