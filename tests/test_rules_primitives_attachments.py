import json
import unittest
from edh_gauntlet.rules_state import RulesState, Zone, ZoneMove
from edh_gauntlet.rules_program import Move, WithMoved
from edh_gauntlet.rules_kernel import RulesKernel, PriorityBoundary
from edh_gauntlet.rules_scenarios import fixture_programs


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.state = RulesState(('A', 'B'))
        self.programs = fixture_programs()

    def add(self, key, definition, zone, owner='A'):
        return self.state.add_card(key, definition, owner, zone)

    def answer(self, kernel, indexes):
        request = kernel.pending_choice
        return kernel.answer(request.request_id, request.actor, indexes)

    def drain(self, kernel):
        for _ in range(80):
            boundary = kernel.advance()
            if boundary is None:
                return
            if isinstance(boundary, PriorityBoundary):
                kernel.pass_priority(boundary.actor)
            else:
                self.fail('Unexpected choice: ' + boundary.kind)
        self.fail('Did not settle')

    def resolve_top(self, kernel):
        # Resolve exactly one stack object, retaining subsequent trigger choices.
        for _ in self.state.players:
            result = kernel.pass_priority(kernel.priority)
        return result

    def reanimated(self):
        self.add('c', 'creature', Zone.GRAVEYARD)
        aura = self.add('a', 'animate', Zone.HAND)
        kernel = RulesKernel(self.state, self.programs)
        self.assertEqual('aura_attachment', kernel.enter(aura).kind)
        self.answer(kernel, [0])
        self.drain(kernel)
        aura = self.state.get(self.state.current('a'))
        creature = self.state.get(self.state.current('c'))
        self.assertEqual(creature.ref, aura.attached_to)
        self.assertEqual(Zone.BATTLEFIELD, creature.zone)
        self.assertEqual((1,2), (kernel.effective(creature.ref).power,kernel.effective(creature.ref).toughness))
        return kernel, aura.ref, creature.ref

    def test_aura_removal_creates_delayed_sacrifice(self):
        kernel, aura, creature = self.reanimated()
        boundary = kernel.execute_for_scenario(aura, 'A', (Move('source', Zone.EXILE),))
        self.assertIsInstance(boundary, PriorityBoundary)
        self.assertEqual(Zone.BATTLEFIELD, self.state.get(creature).zone)
        self.assertEqual(2,kernel.effective(creature).power)
        self.drain(kernel)
        self.assertEqual(Zone.GRAVEYARD, self.state.get(self.state.current('c')).zone)
        self.assertEqual(Zone.EXILE, self.state.get(self.state.current('a')).zone)
        self.assertFalse(kernel.delayed_triggers)
        self.assertFalse(kernel.attachment_rules)

    def test_blink_creature_drops_aura_without_sacrificing_returned_object(self):
        kernel, aura, creature = self.reanimated()
        kernel.execute_for_scenario(creature, 'A', (WithMoved('source', Zone.EXILE,
            (Move('moved', Zone.BATTLEFIELD, controller='owner'),)),))
        self.assertEqual(Zone.GRAVEYARD, self.state.get(self.state.current('a')).zone)
        self.assertNotEqual(creature, self.state.current('c'))
        saved = json.loads(json.dumps(kernel.snapshot()))
        restored = RulesKernel.restore(saved, self.programs)
        self.drain(kernel)
        self.drain(restored)
        self.assertEqual(kernel.snapshot(), restored.snapshot())
        self.assertEqual(Zone.BATTLEFIELD, self.state.get(self.state.current('c')).zone)
        self.assertEqual(1, len([e for e in kernel.semantic_events if e['kind'] == 'delayed_trigger_fired']))

    def test_delayed_sacrifice_uses_creatures_current_controller(self):
        kernel, aura, creature = self.reanimated()
        self.state.change_control(creature, 'B')
        kernel.execute_for_scenario(aura, 'A', (Move('source', Zone.EXILE),))
        self.assertEqual('A', kernel.stack[-1]['controller'])
        self.drain(kernel)
        self.assertEqual(Zone.GRAVEYARD, self.state.get(self.state.current('c')).zone)

    def test_departed_aura_does_not_reanimate_when_etb_resolves(self):
        creature = self.add('c', 'creature', Zone.GRAVEYARD)
        aura = self.add('a', 'animate', Zone.HAND)
        kernel = RulesKernel(self.state, self.programs)
        kernel.enter(aura)
        self.answer(kernel, [0])
        self.state.move((ZoneMove(self.state.current('a'), Zone.EXILE),), 'intervening-removal')
        self.drain(kernel)
        self.assertEqual(creature, self.state.current('c'))
        self.assertFalse(kernel.delayed_triggers)
        self.assertTrue(any(e['kind'] == 'intervening_condition_failed' for e in kernel.semantic_events))

    def test_aura_without_legal_attachment_stays_in_origin(self):
        aura = self.add('a', 'animate', Zone.HAND)
        kernel = RulesKernel(self.state, self.programs)
        self.assertIsNone(kernel.enter(aura))
        self.assertEqual(aura, self.state.current('a'))
        self.assertEqual(Zone.HAND, self.state.get(aura).zone)
        self.assertFalse(self.state.events)

    def test_aura_spell_uses_announced_target_without_new_attachment_prompt(self):
        target = self.add('c', 'creature', Zone.GRAVEYARD)
        aura = self.add('a', 'animate', Zone.HAND)
        kernel = RulesKernel(self.state, self.programs)
        kernel.stage_spell_for_scenario(aura, 'A', (target,))
        self.drain(kernel)
        self.assertEqual(self.state.current('c'), self.state.get(self.state.current('a')).attached_to)
        self.assertFalse(kernel.accepted)

    def test_body_double_felidar_blink_sequence(self):
        self.add('original', 'felidar', Zone.GRAVEYARD)
        self.add('copy', 'body-double', Zone.GRAVEYARD)
        aura = self.add('a', 'animate', Zone.HAND)
        kernel = RulesKernel(self.state, self.programs)
        kernel.enter(aura)
        self.answer(kernel, [1])  # Enchant Body Double's card.
        self.assertEqual('entry_copy', self.resolve_top(kernel).kind)
        self.answer(kernel, [0])  # Copy Felidar.
        self.assertEqual('trigger_targets', kernel.pending_choice.kind)
        self.answer(kernel, [0])  # Felidar can blink the Aura.
        self.assertEqual('may', self.resolve_top(kernel).kind)
        self.answer(kernel, [0])
        self.assertEqual('aura_attachment', kernel.pending_choice.kind)
        restored = RulesKernel.restore(json.loads(json.dumps(kernel.snapshot())), self.programs)
        self.answer(restored, [0])
        # Original Felidar is the only creature card now in a graveyard.
        self.answer(kernel, [0])
        self.assertEqual('trigger_order', kernel.pending_choice.kind)
        self.assertEqual(kernel.snapshot(), restored.snapshot())
        # The old delayed sacrifice and new Aura ETB are independent occurrences.
        self.assertEqual(2, len(kernel.pending_choice.options))
        old_copy = self.state.current('copy')
        self.assertEqual(Zone.BATTLEFIELD, self.state.get(old_copy).zone)
        self.assertNotEqual(aura, self.state.current('a'))
        self.assertEqual(1, len([e for e in kernel.semantic_events if e['kind'] == 'delayed_trigger_fired']))


    def test_felidar_blinks_reanimated_body_double_and_aura_falls_off(self):
        self.add('original', 'felidar', Zone.GRAVEYARD)
        self.add('copy', 'body-double', Zone.GRAVEYARD)
        aura = self.add('a', 'animate', Zone.HAND)
        other = self.add('other', 'felidar', Zone.HAND)
        kernel = RulesKernel(self.state, self.programs)
        kernel.enter(aura)
        self.answer(kernel, [1])
        self.resolve_top(kernel)
        self.answer(kernel, [0])  # Body Double enters as Felidar.
        self.answer(kernel, [0])  # Its first blink targets the Aura.
        self.resolve_top(kernel)
        self.answer(kernel, [1])  # Decline that optional blink.
        old_copy = self.state.current('copy')
        self.assertEqual(old_copy, self.state.get(self.state.current('a')).attached_to)
        kernel.enter(other)
        request = kernel.pending_choice
        index = next(i for i, option in enumerate(request.options) if option.ref == old_copy)
        self.answer(kernel, [index])
        self.resolve_top(kernel)
        self.answer(kernel, [0])  # Other Felidar blinks Body Double.
        self.assertEqual('entry_copy', kernel.pending_choice.kind)
        # No state-based actions interrupt the resolving blink.
        self.assertEqual(Zone.BATTLEFIELD, self.state.get(self.state.current('a')).zone)
        self.answer(kernel, [0])
        self.assertEqual(Zone.GRAVEYARD, self.state.get(self.state.current('a')).zone)
        self.assertNotEqual(old_copy, self.state.current('copy'))
        self.assertEqual('trigger_order', kernel.pending_choice.kind)
        self.answer(kernel, [0, 1])
        if kernel.pending_choice:
            self.assertEqual('trigger_targets', kernel.pending_choice.kind)
            self.answer(kernel, [0])
        for _ in range(30):
            boundary = kernel.advance()
            if boundary is None:
                break
            if isinstance(boundary, PriorityBoundary):
                kernel.pass_priority(boundary.actor)
            elif boundary.kind == 'may':
                self.answer(kernel, [1])
            else:
                self.fail('Unexpected boundary ' + boundary.kind)
        self.assertIsNone(kernel.advance())
        self.assertEqual(Zone.BATTLEFIELD, self.state.get(self.state.current('copy')).zone)
        self.assertEqual(1, len([e for e in kernel.semantic_events if e['kind'] == 'delayed_trigger_fired']))
        self.assertFalse(kernel.delayed_triggers)


    def test_reanimated_body_double_inherits_uro_and_aura_cleanup(self):
        self.add('u', 'uro', Zone.GRAVEYARD)
        self.add('copy', 'body-double', Zone.GRAVEYARD)
        self.add('draw', 'creature', Zone.LIBRARY)
        aura = self.add('a', 'animate', Zone.HAND)
        kernel = RulesKernel(self.state, self.programs)
        kernel.enter(aura)
        self.answer(kernel, [1])
        self.resolve_top(kernel)
        self.answer(kernel, [0])
        self.assertEqual('trigger_order', kernel.pending_choice.kind)
        self.answer(kernel, [1, 0])  # Sacrifice resolves before the value trigger.
        self.drain(kernel)
        self.assertEqual(Zone.GRAVEYARD, self.state.get(self.state.current('copy')).zone)
        self.assertEqual(Zone.GRAVEYARD, self.state.get(self.state.current('a')).zone)
        self.assertEqual(43, self.state.life('A'))
        self.assertEqual(Zone.HAND, self.state.get(self.state.current('draw')).zone)
        self.assertFalse(kernel.delayed_triggers)

    def test_illegal_stack_aura_uses_replaced_graveyard_destination(self):
        from edh_gauntlet.rules_program import CardProgram, ZoneReplacement
        replacement = CardProgram('exiler', 'Exiler fixture', ('Enchantment',), replacements=(
            ZoneReplacement('exile-instead', Zone.GRAVEYARD, Zone.EXILE),))
        self.add('exiler', 'exiler', Zone.BATTLEFIELD)
        aura = self.add('a', 'animate', Zone.STACK)
        kernel = RulesKernel(self.state, (*self.programs, replacement))
        kernel.execute_for_scenario(aura, 'A', (Move('source', Zone.BATTLEFIELD),))
        self.assertEqual(Zone.EXILE, self.state.get(self.state.current('a')).zone)
        self.assertEqual(1, len(self.state.events))
        self.assertFalse(kernel.delayed_triggers)

    def test_replaced_reanimation_cannot_attach_to_exiled_creature(self):
        from edh_gauntlet.rules_program import CardProgram, ZoneReplacement
        replacement = CardProgram('exiler', 'Entry exiler fixture', ('Enchantment',), replacements=(
            ZoneReplacement('exile-instead', Zone.BATTLEFIELD, Zone.EXILE, types=('Creature',)),))
        self.add('exiler', 'exiler', Zone.BATTLEFIELD)
        self.add('c', 'creature', Zone.GRAVEYARD)
        aura = self.add('a', 'animate', Zone.HAND)
        kernel = RulesKernel(self.state, (*self.programs, replacement))
        kernel.enter(aura)
        self.answer(kernel, [0])
        self.drain(kernel)
        self.assertEqual(Zone.EXILE, self.state.get(self.state.current('c')).zone)
        self.assertEqual(Zone.GRAVEYARD, self.state.get(self.state.current('a')).zone)
        self.assertFalse(kernel.delayed_triggers)


    def test_simultaneous_aura_and_creature_departure_has_one_delayed_trigger(self):
        from edh_gauntlet.rules_program import Select, Selector
        kernel, aura, creature = self.reanimated()
        count = len(self.state.events)
        kernel.execute_for_scenario(aura, 'A', (Select(Selector(Zone.BATTLEFIELD), 2, 2,
            (Move('selected', Zone.GRAVEYARD),)),))
        self.assertIsNone(kernel.pending_choice)
        self.drain(kernel)
        self.assertEqual(count + 2, len(self.state.events))
        self.assertEqual(self.state.events[-1].batch, self.state.events[-2].batch)
        self.assertEqual(1, len([e for e in kernel.semantic_events if e['kind'] == 'delayed_trigger_fired']))

    def test_multiple_illegal_auras_move_in_one_state_based_batch(self):
        from edh_gauntlet.rules_program import CardProgram, Selector
        aura_program = CardProgram('plain-aura', 'Plain Aura fixture', ('Enchantment',),
                                   enchant=Selector(Zone.BATTLEFIELD, ('Creature',)))
        creature = self.add('c', 'creature', Zone.BATTLEFIELD)
        first = self.add('a', 'plain-aura', Zone.BATTLEFIELD)
        second = self.add('b', 'plain-aura', Zone.BATTLEFIELD)
        self.state.attach(first, creature)
        self.state.attach(second, creature)
        kernel = RulesKernel(self.state, (*self.programs, aura_program))
        kernel.execute_for_scenario(creature, 'A', (WithMoved('source', Zone.EXILE,
            (Move('moved', Zone.BATTLEFIELD),)),))
        cleanup = [event for event in self.state.events if event.cause == 'permanent_sba']
        self.assertEqual(2, len(cleanup))
        self.assertEqual(1, len({event.batch for event in cleanup}))
