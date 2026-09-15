"""Pregame declarations, free mulligans, privacy and accepted-prefix replay."""
import json
import unittest
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_program import CardProgram
from edh_gauntlet.rules_state import RulesState, Zone, RulesViolation


class OpeningTests(unittest.TestCase):
    def game(self, players=('A', 'B', 'C', 'D'), starting='A'):
        self.programs = (CardProgram('land', 'Test land', ('Land',)),)
        state = RulesState(players, seed=731)
        for actor in players:
            for i in range(30):
                state.add_card(f'{actor}-{i}', 'land', actor, Zone.LIBRARY)
        self.kernel = RulesKernel(state, self.programs)
        self.kernel.begin_mulligans(starting)
        self.adapter = RulesActorAdapter(self.kernel)

    def answer(self, choice):
        request = self.kernel.pending_choice
        indexes = [next(i for i, option in enumerate(request.options) if option.key == choice)] if isinstance(choice, str) else choice
        self.adapter.submit(request.actor, {'kind': 'answer', 'revision': self.kernel.revision,
                            'request_id': request.request_id, 'indexes': indexes})

    def test_declarations_precede_redraw_and_kept_players_leave_rounds(self):
        self.game(starting='B')
        initial = {p: self.kernel.state.zone(p, Zone.HAND) for p in 'ABCD'}
        self.assertEqual('B', self.kernel.pending_choice.actor)
        self.answer('mulligan')
        self.answer('keep')
        self.answer('keep')
        self.assertEqual(initial['B'], self.kernel.state.zone('B', Zone.HAND))
        self.answer('keep')
        self.assertEqual('B', self.kernel.pending_choice.actor)
        self.assertNotEqual(initial['B'], self.kernel.state.zone('B', Zone.HAND))
        self.assertEqual(7, len(self.kernel.state.zone('B', Zone.HAND)))
        for actor in 'ACD':
            self.assertEqual(initial[actor], self.kernel.state.zone(actor, Zone.HAND))
        self.answer('keep')
        self.assertIsNone(self.kernel.mulligans)
        self.assertEqual(1, self.kernel.state.turn_number)
        self.assertEqual('B', self.kernel.active)

    def test_second_multiplayer_redraw_bottoms_before_next_declaration(self):
        self.game()
        self.answer('mulligan')
        for _ in range(3): self.answer('keep')
        self.answer('mulligan')
        self.assertEqual('mulligan_bottom', self.kernel.pending_choice.kind)
        selected = self.kernel.pending_choice.options[2].ref.card_id
        self.answer([2])
        self.assertEqual('mulligan', self.kernel.pending_choice.kind)
        self.assertEqual(6, len(self.kernel.state.zone('A', Zone.HAND)))
        self.assertEqual(selected, self.kernel.state.zone('A', Zone.LIBRARY)[0].ref.card_id)
        self.answer('mulligan')
        request = self.kernel.pending_choice
        chosen = [request.options[i].ref.card_id for i in [3, 1]]
        self.answer([3, 1])
        self.assertEqual(chosen, [o.ref.card_id for o in self.kernel.state.zone('A', Zone.LIBRARY)[:2]])

    def test_two_player_first_redraw_costs_one_card(self):
        self.game(players=('A', 'B'))
        self.answer('mulligan');self.answer('keep')
        self.assertEqual('mulligan_bottom', self.kernel.pending_choice.kind)
        self.assertEqual(1, self.kernel.pending_choice.minimum)

    def test_checkpoint_and_adapter_replay_at_every_choice(self):
        self.game()
        for choice in ['mulligan', 'mulligan', 'keep', 'keep', 'mulligan', 'keep', [0], 'keep']:
            snapshot = self.kernel.snapshot()
            restored = RulesKernel.restore(snapshot, self.programs)
            self.assertEqual(snapshot, restored.snapshot())
            self.answer(choice)
            replayed = RulesActorAdapter.replay(self.adapter.archive(), self.programs)
            self.assertEqual(self.kernel.snapshot(), replayed.kernel.snapshot())

    def test_opponent_projection_does_not_include_private_choices_or_library(self):
        self.game()
        self.answer('mulligan')
        for _ in range(3): self.answer('keep')
        self.answer('mulligan')
        own = self.adapter.packet('A');other = self.adapter.packet('B')
        self.assertEqual('mulligan_bottom', own['decision']['choice']['kind'])
        self.assertEqual({'kind': 'waiting', 'actor': 'A'}, other['decision'])
        encoded = json.dumps(other)
        for obj in self.kernel.state.zone('A', Zone.HAND) + self.kernel.state.zone('A', Zone.LIBRARY):
            self.assertNotIn(obj.ref.card_id, encoded)
        self.assertNotIn('shuffle_seed', encoded)
        self.assertNotIn('mulligan_bottom', encoded)

    def test_rejected_answer_never_changes_prefix(self):
        self.game()
        before = self.adapter.archive();request = self.kernel.pending_choice
        with self.assertRaises(RulesViolation):
            self.adapter.submit('B', {'kind': 'answer', 'revision': self.kernel.revision,
                               'request_id': request.request_id, 'indexes': [0]})
        self.assertEqual(before, self.adapter.archive())
        with self.assertRaises(RulesViolation): self.answer([9])
        self.assertEqual(before, self.adapter.archive())

    def test_zero_card_hand_cannot_take_another_mulligan(self):
        self.game(players=('A', 'B'))
        self.answer('mulligan');self.answer('keep')
        for n in range(1, 8):
            self.assertEqual(n, self.kernel.pending_choice.minimum)
            self.answer(list(range(n)))
            if n < 7: self.answer('mulligan')
        self.assertEqual(['keep'], [o.key for o in self.kernel.pending_choice.options])
        self.answer('keep')
        self.assertEqual(0, len(self.kernel.state.zone('A', Zone.HAND)))
        self.assertEqual(1, self.kernel.state.turn_number)

    def test_cannot_restart_mulligans_or_skip_them(self):
        self.game()
        before = self.kernel.snapshot()
        with self.assertRaises(RulesViolation): self.kernel.begin_mulligans('A')
        with self.assertRaises(RulesViolation): self.kernel.begin_opening_hand_actions('A')
        self.assertEqual(before, self.kernel.snapshot())


class FixedPodSetupTests(unittest.TestCase):
    def test_complete_pod_has_bound_commanders_and_private_opening_hands(self):
        from edh_gauntlet.rules_setup import fresh_pod
        kernel = fresh_pod(seed=812, starting_player='Omo')
        self.assertEqual(400, len(kernel.state.objects()))
        self.assertEqual(334, len({obj.definition for obj in kernel.state.objects()}))
        self.assertEqual('Omo', kernel.pending_choice.actor)
        for actor in kernel.state.players:
            self.assertEqual(40, kernel.state.life(actor))
            self.assertEqual(7, len(kernel.state.zone(actor, Zone.HAND)))
            self.assertEqual(92, len(kernel.state.zone(actor, Zone.LIBRARY)))
            commander, = kernel.state.zone(actor, Zone.COMMAND)
            self.assertTrue(commander.commander)
            self.assertEqual(actor, commander.controller)
            self.assertTrue(kernel.state.commander_identity(actor))
        self.assertEqual(0, kernel.state.turn_number)

    def test_seeded_construction_is_reproducible_and_never_uses_legacy_engine(self):
        from edh_gauntlet.rules_setup import fresh_pod
        first = fresh_pod(seed=913, starting_player='Elenda')
        second = fresh_pod(seed=913, starting_player='Elenda')
        self.assertEqual(first.snapshot(), second.snapshot())
        third = fresh_pod(seed=914, starting_player='Elenda')
        self.assertNotEqual(first.snapshot(), third.snapshot())
        self.assertEqual([], first.accepted)
        self.assertEqual(0, first.state.turn_number)

    def test_durable_restart_retains_a_pregame_choice_without_redealing(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from edh_gauntlet.rules_durable import DurableRulesAdapter
        from edh_gauntlet.rules_setup import fresh_pod
        kernel = fresh_pod(seed=515, starting_player='Reaminatour')
        binding = {'cohort_id': 'opening-test', 'game_number': 1, 'branch_id': 'original', 'contract_sha256': 'a'*64}
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'rules.sqlite'
            store = DurableRulesAdapter.create(path, kernel, binding=binding, checkpoint_interval=2)
            try:
                request = kernel.pending_choice
                command = {'kind': 'answer', 'revision': kernel.revision,
                           'request_id': request.request_id, 'indexes': [1]}
                receipt = store.submit('Reaminatour', 'submission-1', command)
                head = store.committed_head()
                packets = {actor: store.packet(actor) for actor in kernel.state.players}
            finally:
                store.close()
            reopened = DurableRulesAdapter.open(path, tuple(kernel.definitions.values()), binding=binding, minimum_commit=head)
            try:
                self.assertEqual(packets, {actor: reopened.packet(actor) for actor in kernel.state.players})
                self.assertEqual({**receipt, 'duplicate': True}, reopened.submit('Reaminatour', 'submission-1', command))
                self.assertEqual(head, reopened.committed_head())
            finally:
                reopened.close()
