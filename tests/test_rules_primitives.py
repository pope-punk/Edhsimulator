"""Conformance examples exercise shared semantics, not named runtime handlers."""
import json
import unittest
from edh_gauntlet.rules_state import RulesState, Zone, ZoneMove, RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel, ChoiceRequest, PriorityBoundary
from edh_gauntlet.rules_program import encode, decode, validate, Proliferate
from edh_gauntlet.rules_scenarios import fixture_programs


class PrimitiveTests(unittest.TestCase):
    def setUp(self):
        self.state = RulesState(('A', 'B'))

    def add(self, key, definition, zone, owner='A', **kwargs):
        return self.state.add_card(key, definition, owner, zone, **kwargs)

    def kernel(self):
        return RulesKernel(self.state, fixture_programs())

    def answer(self, kernel, indexes):
        request = kernel.pending_choice
        return kernel.answer(request.request_id, request.actor, indexes)

    def drain(self, kernel):
        for _ in range(100):
            boundary = kernel.advance()
            if boundary is None:
                return
            if isinstance(boundary, PriorityBoundary):
                kernel.pass_priority(boundary.actor)
            else:
                raise AssertionError('Unexpected choice: ' + boundary.kind)
        self.fail('Rules did not settle')

    def test_zone_batch_is_atomic_and_references_expire(self):
        a = self.add('a', 'creature', Zone.BATTLEFIELD)
        b = self.add('b', 'land', Zone.HAND)
        before = self.state.snapshot()
        with self.assertRaises(RulesViolation):
            self.state.move((ZoneMove(a, Zone.EXILE), ZoneMove(b, Zone.HAND)), 'invalid')
        self.assertEqual(before, self.state.snapshot())
        self.state.move((ZoneMove(a, Zone.EXILE),), 'blink-out')
        self.state.move((ZoneMove(self.state.current('a'), Zone.BATTLEFIELD),), 'blink-in')
        with self.assertRaises(RulesViolation):
            self.state.get(a)
        self.assertEqual(2, self.state.current('a').incarnation)
        self.state.assert_invariants()

    def test_copy_inherits_both_uro_triggers_and_sacrifices_copy(self):
        uro = self.add('uro-card', 'uro', Zone.GRAVEYARD)
        body = self.add('copy-card', 'body-double', Zone.HAND)
        self.add('draw-card', 'creature', Zone.LIBRARY)
        kernel = self.kernel()
        self.assertEqual('entry_copy', kernel.enter(body).kind)
        self.answer(kernel, [0])
        self.assertEqual('trigger_order', kernel.pending_choice.kind)
        created = [e for e in kernel.semantic_events if e['kind'] == 'trigger_created']
        self.assertEqual({'sacrifice-unless-escaped', 'gain-draw-land'}, {e['ability'] for e in created})
        self.assertTrue(all(e['source']['card_id'] == 'copy-card' for e in created))
        self.answer(kernel, [0, 1])
        self.drain(kernel)
        self.assertEqual(Zone.GRAVEYARD, self.state.get(self.state.current('copy-card')).zone)
        self.assertEqual(uro, self.state.current('uro-card'))
        self.assertEqual(43, self.state.life('A'))
        self.assertEqual(Zone.HAND, self.state.get(self.state.current('draw-card')).zone)

    def test_escaped_uro_keeps_its_body(self):
        uro = self.add('u', 'uro', Zone.GRAVEYARD)
        self.add('d', 'creature', Zone.LIBRARY)
        kernel = self.kernel()
        kernel.enter(uro, entry_flags=('escaped',))
        self.answer(kernel, [0, 1])
        self.drain(kernel)
        self.assertEqual(Zone.BATTLEFIELD, self.state.get(self.state.current('u')).zone)

    def test_upkeep_target_then_optional_resolution_checkpoint(self):
        self.add('s', 'starfield', Zone.BATTLEFIELD)
        target = self.add('e', 'enchantment', Zone.GRAVEYARD)
        kernel = self.kernel()
        request = kernel.begin_step('A', 'upkeep')
        self.assertEqual('trigger_targets', request.kind)
        self.assertEqual(target, request.options[0].ref)
        saved = json.loads(json.dumps(kernel.snapshot()))
        restored = RulesKernel.restore(saved, fixture_programs())
        for candidate in (kernel, restored):
            self.answer(candidate, [0])
            candidate.pass_priority('A')
            boundary = candidate.pass_priority('B')
            self.assertEqual('may', boundary.kind)
            self.answer(candidate, [0])
        self.assertEqual(kernel.snapshot(), restored.snapshot())
        self.assertEqual(Zone.BATTLEFIELD, self.state.get(self.state.current('e')).zone)

    def test_other_players_upkeep_does_not_trigger_starfield(self):
        self.add('s', 'starfield', Zone.BATTLEFIELD)
        self.add('e', 'enchantment', Zone.GRAVEYARD)
        kernel = self.kernel()
        self.assertIsNone(kernel.begin_step('B', 'upkeep'))
        self.assertFalse(kernel.pending_triggers)

    def test_remand_commander_destination_once_and_draw(self):
        for choice, zone in ((0, Zone.COMMAND), (1, Zone.HAND)):
            with self.subTest(zone=zone):
                self.state = RulesState(('A', 'B'))
                commander = self.add('c', 'creature', Zone.COMMAND, commander=True)
                remand = self.add('r', 'remand', Zone.HAND, owner='B')
                self.add('d', 'creature', Zone.LIBRARY, owner='B')
                kernel = self.kernel()
                kernel.stage_spell_for_scenario(commander, 'A')
                kernel.pass_priority('A')
                kernel.stage_spell_for_scenario(remand, 'B', (self.state.current('c'),))
                kernel.pass_priority('B')
                request = kernel.pass_priority('A')
                self.assertEqual('commander_destination', request.kind)
                self.assertEqual('A', request.actor)
                self.answer(kernel, [choice])
                self.drain(kernel)
                self.assertEqual(zone, self.state.get(self.state.current('c')).zone)
                self.assertEqual(1, self.state.command_casts('A'))
                self.assertEqual(Zone.HAND, self.state.get(self.state.current('d')).zone)
                self.assertEqual(1, len(kernel.accepted))
                self.state.assert_invariants()

    def test_proliferate_batches_players_and_permanents(self):
        source = self.add('s', 'sage', Zone.BATTLEFIELD)
        opponent = self.add('b', 'creature', Zone.BATTLEFIELD, owner='B')
        empty = self.add('e', 'creature', Zone.BATTLEFIELD)
        self.state.add_counters(opponent, '+1/+1', 2)
        self.state.add_counters(opponent, 'shield', 1)
        self.state.add_player_counters('A', 'energy', 3)
        kernel = self.kernel()
        request = kernel.execute_for_scenario(source, 'A', (Proliferate(),))
        self.assertEqual('proliferate', request.kind)
        self.assertEqual(2, len(request.options))
        before = kernel.snapshot()
        with self.assertRaises(RulesViolation):
            kernel.answer(request.request_id, 'B', [0])
        self.assertEqual(before, kernel.snapshot())
        self.answer(kernel, [0, 1])
        self.assertEqual({'+1/+1': 3, 'shield': 2}, dict(self.state.get(opponent).counters))
        self.assertEqual({'energy': 4}, dict(self.state.player_counters('A')))
        self.assertFalse(self.state.get(empty).counters)
        self.assertEqual(1, len(kernel.accepted))

    def test_program_round_trip_and_closed_vocabulary(self):
        for program in fixture_programs():
            self.assertEqual(program, validate(decode(json.loads(json.dumps(encode(program))))))
        with self.assertRaises(RulesViolation):
            decode({'node': 'RunPython', 'code': 'arbitrary'})


    def test_stale_target_does_not_follow_returned_card(self):
        self.add('s', 'starfield', Zone.BATTLEFIELD)
        target = self.add('e', 'enchantment', Zone.GRAVEYARD)
        kernel = self.kernel()
        kernel.begin_step('A', 'upkeep')
        self.answer(kernel, [0])
        # Harness models an intervening zone change while players have priority.
        self.state.move((ZoneMove(target, Zone.EXILE),), 'intervening-effect')
        self.state.move((ZoneMove(self.state.current('e'), Zone.GRAVEYARD),), 'return')
        self.drain(kernel)
        self.assertEqual(Zone.GRAVEYARD, self.state.get(self.state.current('e')).zone)
        self.assertTrue(any(e['kind'] == 'all_targets_illegal' for e in kernel.semantic_events))
        self.assertEqual(1, len(kernel.accepted))  # No optional-resolution prompt.

    def test_answer_cannot_be_replayed(self):
        source = self.add('s', 'sage', Zone.BATTLEFIELD)
        self.state.add_player_counters('A', 'energy', 1)
        kernel = self.kernel()
        request = kernel.execute_for_scenario(source, 'A', (Proliferate(),))
        self.answer(kernel, [0])
        before = kernel.snapshot()
        with self.assertRaises(RulesViolation):
            kernel.answer(request.request_id, 'A', [0])
        self.assertEqual(before, kernel.snapshot())

    def test_nested_selections_preserve_outer_binding(self):
        from edh_gauntlet.rules_program import Select, Selector, AddCounters
        source = self.add('s', 'sage', Zone.BATTLEFIELD)
        own = self.add('a', 'creature', Zone.BATTLEFIELD)
        other = self.add('b', 'creature', Zone.BATTLEFIELD, owner='B')
        effects = (Select(Selector(Zone.BATTLEFIELD, ('Creature',), 'controlled', True), 1, 1,
            (Select(Selector(Zone.BATTLEFIELD, ('Creature',), 'opponent_controlled'), 1, 1,
                (AddCounters('selected', 'shield', 1),)),
             AddCounters('selected', '+1/+1', 1))),)
        kernel = self.kernel()
        kernel.execute_for_scenario(source, 'A', effects)
        self.assertIsNone(kernel.pending_choice)
        self.assertEqual({'+1/+1': 1}, dict(self.state.get(own).counters))
        self.assertEqual({'shield': 1}, dict(self.state.get(other).counters))

    def test_apnap_trigger_placement(self):
        from edh_gauntlet.rules_program import CardProgram, AbilityProgram, EventPattern, GainLife
        observer = CardProgram('observer', 'Observer fixture', ('Enchantment',), abilities=(
            AbilityProgram('observe-entry', EventPattern('zone_changed', to_zone=Zone.BATTLEFIELD), (GainLife(1),)),))
        self.add('a', 'observer', Zone.BATTLEFIELD)
        self.add('b', 'observer', Zone.BATTLEFIELD, owner='B')
        land = self.add('l', 'land', Zone.HAND)
        kernel = RulesKernel(self.state, (*fixture_programs(), observer))
        kernel.enter(land)
        self.assertEqual(['A', 'B'], [f['controller'] for f in kernel.stack])
        self.assertEqual('A', kernel.priority)
        self.drain(kernel)
        resolved = [e['frame'] for e in kernel.semantic_events if e['kind'] == 'resolution_started']
        placed = [e['frame'] for e in kernel.semantic_events if e['kind'] == 'trigger_placed']
        self.assertEqual(list(reversed(placed)), resolved)

    def test_checkpoint_rejects_changed_rules_bundle(self):
        from dataclasses import replace
        source = self.add('s', 'sage', Zone.BATTLEFIELD)
        kernel = self.kernel()
        programs = list(fixture_programs())
        programs[0] = replace(programs[0], abilities=())
        with self.assertRaises(RulesViolation):
            RulesKernel.restore(kernel.snapshot(), programs)


    def test_identity_conservation_under_many_zone_changes(self):
        import random
        rng = random.Random(904)
        for index in range(12):
            self.add(str(index), 'creature', Zone.HAND, owner=('A', 'B')[index % 2])
        zones = (Zone.HAND, Zone.BATTLEFIELD, Zone.EXILE, Zone.GRAVEYARD, Zone.LIBRARY)
        for _ in range(500):
            objects = rng.sample(list(self.state.objects()), rng.randint(1, 5))
            moves = tuple(ZoneMove(o.ref, rng.choice([z for z in zones if z != o.zone])) for o in objects)
            self.state.move(moves, 'generated-conservation-case')
            self.state.assert_invariants()
            self.assertEqual(12, len(self.state.objects()))
        restored = RulesState.restore(json.loads(json.dumps(self.state.snapshot())))
        self.assertEqual(self.state.snapshot(), restored.snapshot())

    def test_renaming_definitions_does_not_change_copy_behavior(self):
        from dataclasses import replace
        self.add('original', 'renamed-uro', Zone.GRAVEYARD)
        body = self.add('copy', 'renamed-body-double', Zone.HAND)
        self.add('draw', 'renamed-creature', Zone.LIBRARY)
        programs = tuple(replace(p, definition_id='renamed-' + p.definition_id,
                                name='Anonymous ' + str(index))
                         for index, p in enumerate(fixture_programs()))
        kernel = RulesKernel(self.state, programs)
        kernel.enter(body)
        self.answer(kernel, [0])
        self.answer(kernel, [0, 1])
        self.drain(kernel)
        self.assertEqual(43, self.state.life('A'))
        self.assertEqual(Zone.GRAVEYARD, self.state.get(self.state.current('copy')).zone)

    def test_departed_source_does_not_erase_its_triggers(self):
        self.add('original', 'uro', Zone.GRAVEYARD)
        body = self.add('copy', 'body-double', Zone.HAND)
        self.add('draw', 'creature', Zone.LIBRARY)
        kernel = self.kernel()
        kernel.enter(body)
        self.answer(kernel, [0])
        self.answer(kernel, [0, 1])
        self.state.move((ZoneMove(self.state.current('copy'), Zone.EXILE),), 'intervening-effect')
        self.drain(kernel)
        self.assertEqual(43, self.state.life('A'))
        self.assertEqual(Zone.EXILE, self.state.get(self.state.current('copy')).zone)

    def test_unbound_program_subject_is_rejected(self):
        from edh_gauntlet.rules_program import CardProgram, Move
        for subject in ('selected', 'target'):
            with self.subTest(subject=subject), self.assertRaisesRegex(RulesViolation, 'Unbound subject'):
                validate(CardProgram('bad', 'Bad', ('Instant',),
                                     spell_effects=(Move(subject, Zone.EXILE),)))

    def test_proliferate_checkpoint_and_duplicate_selection(self):
        source = self.add('s', 'sage', Zone.BATTLEFIELD)
        self.state.add_player_counters('A', 'energy', 2)
        kernel = self.kernel()
        request = kernel.execute_for_scenario(source, 'A', (Proliferate(),))
        before = kernel.snapshot()
        with self.assertRaises(RulesViolation):
            kernel.answer(request.request_id, 'A', [0, 0])
        self.assertEqual(before, kernel.snapshot())
        restored = RulesKernel.restore(before, fixture_programs())
        self.answer(kernel, [0])
        self.answer(restored, [0])
        self.assertEqual(kernel.snapshot(), restored.snapshot())


if __name__ == '__main__':
    unittest.main()
