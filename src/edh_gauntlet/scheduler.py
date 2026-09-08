"""Replayable, pilot-authored prompting policy. This module never chooses a play.

One directive replaces the acting seat's previous policy. Deadlines are game
boundaries, never wall-clock time. All policy and telemetry is actor-private.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import wraps
from typing import Any
import json

SURFACE_REVISION = 6
MODES = {'hold_full_control', 'snooze_table', 'snooze_stack', 'resolve_my_sequence', 'snooze_objects'}
WAKE_CONDITIONS = {'opponent_spell', 'opponent_action', 'any_spell',
                   'targeted_or_attacked', 'deadline_only'}
CHOICE_GUIDANCE = (
    'Choose the least repeated prompting compatible with your intended play: '
    'resolve_my_sequence after committing a spell/ability when you intend to pass on your own follow-ups; '
    'snooze_objects for specific sources you will not use until their deadline/wake; '
    'snooze_table when finished acting until a named boundary or event. '
    'hold_full_control preserves optional interventions you actually intend to reconsider. '
    'Required choices still wake you. Snooze is a decision policy, never permission to skip opponents.'
)

HELP = (
    'Append exactly one scheduler directive to every answer: --hold_full_control; '
    '--resolve_my_sequence; --snooze_table JSON {time,wake_condition}; '
    'or --snooze_objects JSON {objects,time,wake_condition}. '
    'A new directive replaces your prior policy. Attacks and mandatory choices always wake you. '
    'Time is "N beginning|end of PHASE". Wake conditions: opponent_action, '
    'opponent_spell, any_spell, targeted_or_attacked, deadline_only. '
    'Resolve my sequence is a snooze: pass optional priority through my spell and its resulting '
    'triggers or abilities; wake for another player\'s new stack action, a required choice, or sequence completion. '
    'Use hold_full_control to retain every actionable decision.'
)

COMPACT_LEGEND = (
    'Scheduler legend (append one; replaces current):\n'
    '--hold_full_control = every actionable decision.\n'
    '--snooze_table {time,wake_condition} = auto-pass all optional decisions until time/wake.\n'
    '--resolve_my_sequence = snooze optional priority through my spell and its resulting triggers/abilities; '
    'wake for another player\'s new stack action, a required choice, or sequence completion.\n'
    '--snooze_objects {objects,time,wake_condition} = suppress listed exact-UID priority actions; '
    'moved/control-changed UIDs drop out.\n'
    'time = "N beginning|end of PHASE". wake: opponent_spell = opponent casts; '
    'opponent_action = opponent adds spell/ability/trigger to stack; any_spell = any cast; '
    'targeted_or_attacked = you/your object targeted or you attacked; deadline_only = time. '
    'Attacks and mandatory choices always wake.'
)


def normalize_directive(value: Any) -> dict:
    # Local import avoids a referee/scheduler module initialization cycle.
    from .referee import parse_pass_on_schedule
    if not isinstance(value, dict):
        raise ValueError('A scheduler directive must be an object')
    mode = value.get('mode')
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError('Choose exactly one valid scheduler mode')
    expected = {'mode'}
    if mode in {'snooze_table', 'snooze_objects'}:
        expected |= {'time', 'wake_condition'}
    if mode == 'snooze_objects':
        expected.add('objects')
    if set(value) != expected:
        raise ValueError(f'{mode} requires exactly these fields: {", ".join(sorted(expected))}')
    result = {'mode': mode}
    if 'time' in expected:
        result['time'] = parse_pass_on_schedule(value['time'])
        if not isinstance(value['wake_condition'], str) or value['wake_condition'] not in WAKE_CONDITIONS:
            raise ValueError('Unknown scheduler wake_condition')
        result['wake_condition'] = value['wake_condition']
    if 'objects' in expected:
        uids = value['objects']
        if (not isinstance(uids, list) or not uids or len(uids) > 200 or
                any(not isinstance(uid, str) or not uid.strip() or len(uid) > 160 for uid in uids)):
            raise ValueError('snooze_objects requires a nonempty list of exact object UIDs')
        if len(uids) != len(set(uids)):
            raise ValueError('snooze_objects cannot repeat a UID')
        result['objects'] = sorted(uids)
    return result


def directive_from_flags(*, hold_full_control=False, snooze_stack=False, resolve_my_sequence=False,
                         snooze_table=None, snooze_objects=None) -> dict | None:
    choices = [bool(hold_full_control), bool(snooze_stack), bool(resolve_my_sequence),
               snooze_table is not None, snooze_objects is not None]
    if not any(choices):
        return None
    if sum(choices) != 1:
        raise ValueError('Exactly one scheduler directive is required')
    if hold_full_control:
        return {'mode': 'hold_full_control'}
    if snooze_stack:
        return {'mode': 'snooze_stack'}
    if resolve_my_sequence:
        return {'mode': 'resolve_my_sequence'}
    mode = 'snooze_table' if snooze_table is not None else 'snooze_objects'
    raw = snooze_table if snooze_table is not None else snooze_objects
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f'{mode} requires a JSON object') from exc
    if not isinstance(raw, dict) or 'mode' in raw:
        raise ValueError(f'{mode} requires its payload without a mode field')
    return normalize_directive({'mode': mode, **raw})


@dataclass
class ObjectSchedule:
    source: Any
    source_uid: str
    source_name: str
    source_zone: str


@dataclass
class SeatPolicy:
    directive: dict
    decision_id: str
    armed_turn: int
    wake_ordinal: int = 0
    objects: list[ObjectSchedule] = field(default_factory=list)
    stack_started: bool = False
    spell_epoch: int = 0
    allow_initial_spell: bool = False


def resolution_sequence(method):
    """Keep transient empty stacks inside synchronous resolution from waking seats.

    A suspended/failed referee call must not publish a sequence-complete event.
    Old scheduler modes never consult this depth and retain their exact replay.
    """
    @wraps(method)
    def wrapped(game, *args, **kwargs):
        depth = getattr(game, '_resolution_sequence_depth', 0)
        game._resolution_sequence_depth = depth + 1
        try:
            result = method(game, *args, **kwargs)
        except BaseException:
            game._resolution_sequence_depth = depth
            raise
        game._resolution_sequence_depth = depth
        if depth == 0:
            game.scheduler.finish_sequence(game)
        return result
    return wrapped


class PilotScheduler:
    def __init__(self):
        self.policies: dict[str, SeatPolicy] = {}

    @staticmethod
    def eligible_objects(game, player):
        # Known objects only. In particular, never enumerate a library here.
        rows = []
        for zone in ('hand', 'battlefield', 'graveyard', 'exile', 'commander'):
            sources = ([player.commander] if player.commander else []) if zone == 'commander' else getattr(player, zone)
            for obj in sources:
                if game.priority_source_zone(player, obj) != zone:
                    continue
                if zone == 'battlefield' and not game._battlefield_identity_visible_to(player.name, obj):
                    continue
                rows.append(ObjectSchedule(obj, obj.uid, game.priority_source_name(obj), zone))
        return sorted(rows, key=lambda row: row.source_uid)

    def accept(self, game, player, value, decision_id):
        directive = normalize_directive(value)
        sources = {row.source_uid: row for row in self.eligible_objects(game, player)}
        if any(uid not in sources for uid in directive.get('objects', [])):
            raise ValueError('Scheduler object is stale, foreign, hidden, or unavailable')
        # Validate everything before replacing any existing policy.
        selected = [sources[uid] for uid in directive.get('objects', [])]
        schedule = directive.get('time')
        ordinal = (game.priority_boundary_counts.get((schedule['edge'], schedule['phase']), 0)
                   + schedule['occurrences']) if schedule else 0
        player.dungeon.pop('priority_holds', None)
        self.policies.pop(player.name, None)
        if directive['mode'] != 'hold_full_control':
            self.policies[player.name] = SeatPolicy(
                directive, decision_id, game.turn_number, ordinal, selected,
                stack_started=bool(game.stack), spell_epoch=game.spell_cast_epoch,
                allow_initial_spell=True)
        game.log('scheduler_control', player.name, None, directive['mode'],
                 decision_id=decision_id, directive=directive)

    def wake(self, game, player, reason):
        policy = self.policies.pop(player.name, None)
        if policy:
            game.log('scheduler_wake', player.name, None, reason,
                     policy_decision_id=policy.decision_id)
        return policy is not None

    def current(self, game, player):
        policy = self.policies.get(player.name)
        if not policy:
            return None
        if player.eliminated:
            self.wake(game, player, 'player_left')
            return None
        schedule = policy.directive.get('time')
        if schedule and game.priority_boundary_counts.get((schedule['edge'], schedule['phase']), 0) >= policy.wake_ordinal:
            self.wake(game, player, 'time_boundary')
            return None
        if policy.directive['mode'] == 'snooze_objects':
            live = [row for row in policy.objects
                    if game.priority_source_zone(player, row.source) == row.source_zone]
            if len(live) != len(policy.objects):
                policy.objects = live
                if not live:
                    self.wake(game, player, 'objects_changed_zone_or_controller')
                    return None
        if policy.directive['mode'] == 'snooze_stack':
            if policy.stack_started and not game.stack:
                self.wake(game, player, 'stack_empty')
                return None
            if policy.stack_started and game.spell_cast_epoch != policy.spell_epoch:
                self.wake(game, player, 'new_spell')
                return None
            if not policy.stack_started and game.turn_number != policy.armed_turn:
                self.wake(game, player, 'no_stack_created_by_answer')
                return None
        return policy

    def table_snoozed(self, game, player):
        policy = self.current(game, player)
        return policy if policy and policy.directive['mode'] == 'snooze_table' else None

    def stack_snoozed(self, game, player):
        policy = self.current(game, player)
        if policy and policy.stack_started:policy.allow_initial_spell=False
        return bool(policy and policy.directive['mode'] in {'snooze_stack', 'resolve_my_sequence'} and policy.stack_started)

    def finish_sequence(self, game):
        """Called after an outer resolution returns, including its generated triggers."""
        if game.stack or getattr(game, '_resolution_sequence_depth', 0):
            return
        for player in getattr(game, 'players', {}).values():
            policy = self.policies.get(player.name)
            if policy and policy.directive['mode'] == 'resolve_my_sequence':
                self.wake(game, player, 'sequence_complete')

    def object_schedules(self, game, player):
        policy = self.current(game, player)
        return list(policy.objects) if policy and policy.directive['mode'] == 'snooze_objects' else []

    def before_decision(self, game, player, *, passable):
        policy = self.current(game, player)
        if not policy:
            return False
        policy.allow_initial_spell=False
        if not passable:
            self.wake(game, player, 'mandatory_decision')
            return False
        if policy.directive['mode'] == 'snooze_table':
            return True
        # Object and stack policies do not infer choices in resolving effects.
        return False

    def targeted(self, game, player):
        policy = self.current(game, player)
        if policy and policy.directive.get('wake_condition') == 'targeted_or_attacked':
            self.wake(game, player, 'targeted')

    def observe(self, game, event_type, actor, *, is_spell=False, targets=()):
        if event_type.startswith('scheduler_'):
            return
        for player in getattr(game, 'players', {}).values():
            policy = self.policies.get(player.name)
            if not policy:
                continue
            mode = policy.directive['mode']
            if policy.directive.get('wake_condition')=='targeted_or_attacked' and actor!=player.name:
                own={obj.uid for obj in player.battlefield}|{player.name}
                if isinstance(targets,(list,tuple)) and any(isinstance(uid,str) and uid in own for uid in targets):
                    self.wake(game,player,'targeted')
                    continue
            if mode == 'resolve_my_sequence':
                # New opposing stack activity is intervention; the initiating
                # spell and its controller's cascading triggers are the sequence.
                if actor != player.name and (is_spell or event_type in {'stack_add', 'trigger_stack_add'}):
                    self.wake(game, player, 'opponent_action')
                    continue
                if actor == player.name and event_type in {'stack_add', 'trigger_stack_add'}:
                    policy.stack_started = True
                if event_type in {'priority_closed', 'cleanup', 'untap'}:
                    self.finish_sequence(game)
            elif mode == 'snooze_stack':
                if is_spell and actor == player.name and policy.allow_initial_spell:
                    # The spell selected by this very answer belongs to the
                    # requested stack; a later spell restores control.
                    policy.stack_started = False
                    policy.allow_initial_spell = False
                elif is_spell:
                    self.wake(game, player, 'new_spell')
                    continue
                if not policy.stack_started and event_type in {'stack_add', 'trigger_stack_add'}:
                    if actor == player.name:
                        policy.stack_started = True
                        policy.spell_epoch = game.spell_cast_epoch
                        policy.allow_initial_spell = False
                    else:
                        self.wake(game, player, 'unrelated_stack')
                        continue
                if not policy.stack_started and event_type in {'priority_closed', 'cleanup', 'untap'}:
                    self.wake(game, player, 'no_stack_created_by_answer')
                    continue
            else:
                condition = policy.directive['wake_condition']
                is_action = is_spell or event_type in {'stack_add', 'trigger_stack_add'}
                if ((condition == 'any_spell' and is_spell) or
                    (condition == 'opponent_spell' and actor != player.name and is_spell) or
                    (condition == 'opponent_action' and actor != player.name and is_action)):
                    self.wake(game, player, condition)
                    continue
            self.current(game, player)

    def describe(self, game, player):
        policy = self.current(game, player)
        if not policy:
            return {'mode': 'hold_full_control'}
        result = {**policy.directive, 'decision_id': policy.decision_id}
        schedule = policy.directive.get('time')
        if schedule:
            result['remaining_occurrences'] = policy.wake_ordinal - game.priority_boundary_counts.get(
                (schedule['edge'], schedule['phase']), 0)
        if policy.objects:
            result['objects'] = [row.source_uid for row in policy.objects]
        return result

    def metadata(self, game, player):
        return {'schema': 1, 'required': True, 'help': HELP,
                'compact_legend': COMPACT_LEGEND,
                'active': self.describe(game, player),
                'eligible_objects': [dict(uid=row.source_uid, name=row.source_name, zone=row.source_zone)
                                     for row in self.eligible_objects(game, player)],
                'wake_conditions': sorted(WAKE_CONDITIONS)}
