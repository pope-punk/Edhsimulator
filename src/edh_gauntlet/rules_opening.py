"""Deterministic pregame mulligans using the ordinary seat-bound choice journal.

CR 103.5: declarations precede all redraws; each redraw is followed by its
ordered bottom selection before the next declaration round. CR 103.5c grants
one free mulligan in games starting with more than two players. These methods
support the fixed pod, not pregame variants such as Vanguard or Serum Powder.
"""
from .rules_choices import Option
from .rules_state import Zone, ZoneMove, RulesViolation


class OpeningRules:
    def begin_mulligans(self, starting_player, *, hand_size=7):
        self._idle()
        if (type(hand_size) is not int or hand_size < 1 or starting_player not in self.state.live_players
                or self.state.turn_number or self.phase is not None or self.turn_schedule is not None
                or self.stack or self.priority is not None or self.opening_actions is not None
                or self.mulligans is not None or self.accepted or self.semantic_events
                or any(obj.zone not in {Zone.LIBRARY, Zone.COMMAND} for obj in self.state.objects())
                or any(len(self.state.zone(p, Zone.LIBRARY)) < hand_size for p in self.state.players)):
            raise RulesViolation('Mulligans require a fresh game with undrawn libraries')
        self.active = starting_player
        index = self.state.players.index(starting_player)
        players = list(self.state.players[index:] + self.state.players[:index])
        self.mulligans = {'id': self._id('mulligans'), 'players': players, 'eligible': players[:],
                         'hand_size': hand_size, 'free': int(len(players) > 2),
                         'counts': {p: 0 for p in players}, 'round': 0, 'cursor': 0,
                         'phase': 'declare', 'redraw': []}
        for actor in players:
            self.state.shuffle_library(actor)
        self._opening_draw(players, hand_size)
        self._event('mulligans_began', starting_player=starting_player, hand_size=hand_size)
        return self.advance()

    def _opening_draw(self, players, hand_size):
        # Initial/mulligan dealing happens before normal game event processing.
        moves = tuple(ZoneMove(obj.ref, Zone.HAND) for actor in players
                      for obj in reversed(self.state.zone(actor, Zone.LIBRARY)[-hand_size:]))
        self.state.move(moves, 'opening_hand_dealt')

    def _continue_mulligans(self):
        window = self.mulligans
        if window['phase'] == 'declare':
            while window['cursor'] < len(window['eligible']):
                actor = window['eligible'][window['cursor']]
                key = f"{window['id']}:{window['round']}:{actor}:declare"
                can_redraw = window['counts'][actor] < window['hand_size'] + window['free']
                options = (Option('keep', 'Keep this hand'),)
                if can_redraw:
                    options += (Option('mulligan', 'Take a mulligan'),)
                selected = self._choose(key, actor, 'mulligan', 'Keep this hand or take a mulligan?', options, 1, 1)
                if selected[0].key == 'mulligan':
                    window['redraw'].append(actor)
                self._event('mulligan_declared', actor=actor, choice=selected[0].key,
                            mulligans_taken=window['counts'][actor])
                window['cursor'] += 1
            if not window['redraw']:
                self.mulligans = None
                self._event('mulligans_completed')
                self._start_opening_actions(self.active)
                return
            # No player sees a new hand before every declaration is accepted.
            self.state.move(tuple(ZoneMove(obj.ref, Zone.LIBRARY) for actor in window['redraw']
                                  for obj in self.state.zone(actor, Zone.HAND)), 'mulligan_return')
            for actor in window['redraw']:
                self.state.shuffle_library(actor)
                window['counts'][actor] += 1
            self._opening_draw(window['redraw'], window['hand_size'])
            window['phase'] = 'bottom'
            window['cursor'] = 0
            self._event('mulligan_hands_dealt', actors=window['redraw'][:])
        while window['cursor'] < len(window['redraw']):
            actor = window['redraw'][window['cursor']]
            count = max(0, window['counts'][actor] - window['free'])
            if count:
                key = f"{window['id']}:{window['round']}:{actor}:bottom"
                options = self._options(self.state.zone(actor, Zone.HAND))
                selected = self._choose(key, actor, 'mulligan_bottom',
                    f'Put {count} cards on the bottom, deepest card first.', options, count, count, ordered=True)
                # State inserts each position-zero move in order, hence reverse
                # the chosen deepest-first sequence before a single atomic move.
                self.state.move(tuple(ZoneMove(o.ref, Zone.LIBRARY, position=0)
                                      for o in reversed(selected)), 'mulligan_bottom')
                self._event('mulligan_cards_bottomed', actor=actor, count=count)
            window['cursor'] += 1
        window['eligible'] = window['redraw']
        window['redraw'] = []
        window['cursor'] = 0
        window['round'] += 1
        window['phase'] = 'declare'
