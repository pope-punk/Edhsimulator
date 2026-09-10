import json
import unittest
from edh_gauntlet.rules_state import RulesState, Zone
from edh_gauntlet.rules_program import (CardProgram, ZoneReplacement, Move,
    AbilityProgram, EventPattern, GainLife, Select, Selector)
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_scenarios import fixture_programs


class ReplacementTests(unittest.TestCase):
    def setUp(self):
        self.state = RulesState(('A', 'B'))
        self.programs = list(fixture_programs())

    def field(self, key, *replacements, owner='A', abilities=()):
        self.programs.append(CardProgram(key, key, ('Enchantment',),
            abilities=abilities, replacements=tuple(replacements)))
        return self.state.add_card(key, key, owner, Zone.BATTLEFIELD)

    def kernel(self):
        return RulesKernel(self.state, self.programs)

    def answer(self, kernel, indexes):
        request = kernel.pending_choice
        return kernel.answer(request.request_id, request.actor, indexes)

    def test_replaced_death_does_not_emit_dies_trigger(self):
        source = self.field('exiler', ZoneReplacement('exile-instead', Zone.GRAVEYARD, Zone.EXILE))
        death = AbilityProgram('dies', EventPattern('zone_changed', from_zone=Zone.BATTLEFIELD,
            to_zone=Zone.GRAVEYARD, types=('Creature',)), (GainLife(1),))
        self.field('observer', abilities=(death,))
        creature = self.state.add_card('c', 'creature', 'A', Zone.BATTLEFIELD)
        kernel = self.kernel()
        kernel.execute_for_scenario(creature, 'A', (Move('source', Zone.GRAVEYARD),))
        self.assertEqual(Zone.EXILE, self.state.get(self.state.current('c')).zone)
        self.assertFalse(any(e['kind'] == 'trigger_created' for e in kernel.semantic_events))
        self.assertEqual(1, len(self.state.events))

    def test_affected_controller_orders_replacements_and_checkpoint(self):
        self.field('exiler', ZoneReplacement('exile', Zone.GRAVEYARD, Zone.EXILE))
        self.field('bouncer', ZoneReplacement('hand', Zone.GRAVEYARD, Zone.HAND))
        creature = self.state.add_card('c', 'creature', 'A', Zone.BATTLEFIELD, controller='B')
        kernel = self.kernel()
        original = self.state.snapshot()
        request = kernel.execute_for_scenario(creature, 'B', (Move('source', Zone.GRAVEYARD),))
        self.assertEqual('replacement_order', request.kind)
        self.assertEqual('B', request.actor)
        self.assertEqual(original, self.state.snapshot())
        restored = RulesKernel.restore(json.loads(json.dumps(kernel.snapshot())), self.programs)
        self.answer(kernel, [1])
        self.answer(restored, [1])
        self.assertEqual(kernel.snapshot(), restored.snapshot())
        self.assertEqual(Zone.HAND, self.state.get(self.state.current('c')).zone)

    def test_ordinary_replacements_each_apply_once(self):
        self.field('out', ZoneReplacement('out', Zone.GRAVEYARD, Zone.EXILE))
        self.field('back', ZoneReplacement('back', Zone.EXILE, Zone.GRAVEYARD))
        creature = self.state.add_card('c', 'creature', 'A', Zone.BATTLEFIELD)
        kernel = self.kernel()
        kernel.execute_for_scenario(creature, 'A', (Move('source', Zone.GRAVEYARD),))
        self.assertEqual(Zone.GRAVEYARD, self.state.get(self.state.current('c')).zone)
        self.assertEqual(2, len([e for e in kernel.semantic_events if e['kind'] == 'replacement_considered']))
        self.assertEqual(1, len(self.state.events))

    def test_commander_exception_can_be_reconsidered(self):
        self.field('redirect', ZoneReplacement('hand-to-library', Zone.HAND, Zone.LIBRARY))
        creature = self.state.add_card('c', 'creature', 'A', Zone.BATTLEFIELD, commander=True)
        kernel = self.kernel()
        kernel.execute_for_scenario(creature, 'A', (Move('source', Zone.HAND),))
        self.answer(kernel, [0])  # Choose commander replacement first.
        self.assertEqual('commander_destination', kernel.pending_choice.kind)
        self.answer(kernel, [1])  # Decline hand -> command.
        self.assertEqual('commander_destination', kernel.pending_choice.kind)
        self.answer(kernel, [0])  # Other replacement made destination library.
        self.assertEqual(Zone.COMMAND, self.state.get(self.state.current('c')).zone)
        commander = [e for e in kernel.semantic_events if e.get('replacement_kind') == 'commander']
        self.assertEqual([False, True], [e['accepted'] for e in commander])

    def test_optional_replacement_decline_does_not_loop(self):
        self.field('optional', ZoneReplacement('exile', Zone.GRAVEYARD, Zone.EXILE, optional=True))
        creature = self.state.add_card('c', 'creature', 'B', Zone.BATTLEFIELD)
        kernel = self.kernel()
        request = kernel.execute_for_scenario(creature, 'B', (Move('source', Zone.GRAVEYARD),))
        self.assertEqual('B', request.actor)
        self.answer(kernel, [1])
        self.assertIsNone(kernel.pending_choice)
        self.assertEqual(Zone.GRAVEYARD, self.state.get(self.state.current('c')).zone)

    def test_simultaneous_batch_waits_for_all_choices_in_apnap_order(self):
        source = self.field('optional', ZoneReplacement('exile', Zone.GRAVEYARD, Zone.EXILE, optional=True))
        b = self.state.add_card('b', 'creature', 'B', Zone.BATTLEFIELD)
        a = self.state.add_card('a', 'creature', 'A', Zone.BATTLEFIELD)
        kernel = self.kernel()
        kernel.execute_for_scenario(source, 'A', (Select(Selector(Zone.BATTLEFIELD, ('Creature',)), 2, 2,
            (Move('selected', Zone.GRAVEYARD),)),))
        self.assertEqual('replacement_optional',kernel.pending_choice.kind)  # Forced set, then APNAP choices.
        self.assertEqual('A', kernel.pending_choice.actor)
        self.answer(kernel, [0])
        self.assertEqual('B', kernel.pending_choice.actor)
        self.assertEqual(Zone.BATTLEFIELD, self.state.get(a).zone)
        self.assertEqual(Zone.BATTLEFIELD, self.state.get(b).zone)
        saved = kernel.snapshot()
        restored = RulesKernel.restore(saved, self.programs)
        self.answer(kernel, [1])
        self.answer(restored, [1])
        self.assertEqual(kernel.snapshot(), restored.snapshot())
        self.assertEqual(Zone.EXILE, self.state.get(self.state.current('a')).zone)
        self.assertEqual(Zone.GRAVEYARD, self.state.get(self.state.current('b')).zone)
        self.assertEqual(1, len({event.batch for event in self.state.events}))

    def test_copy_entry_precedes_other_entry_replacement(self):
        self.field('redirect', ZoneReplacement('creature-entry', Zone.BATTLEFIELD, Zone.EXILE,
                                             types=('Creature',)))
        self.state.add_card('u', 'uro', 'A', Zone.GRAVEYARD)
        body = self.state.add_card('b', 'body-double', 'A', Zone.HAND)
        kernel = self.kernel()
        self.assertEqual('entry_copy', kernel.enter(body).kind)
        self.answer(kernel, [0])
        self.assertEqual(Zone.EXILE, self.state.get(self.state.current('b')).zone)
        self.assertFalse(any(e['kind'] == 'trigger_created' for e in kernel.semantic_events))
        kinds = [e['replacement_kind'] for e in kernel.semantic_events if e['kind'] == 'replacement_considered']
        self.assertEqual(['copy', 'redirect'], kinds)
