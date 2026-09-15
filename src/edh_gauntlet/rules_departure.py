"""CR 800.4 departure planning and resumable execution for resolved control effects.

Supports ordinary loss conditions, stack/owned-object removal, replacement-aware
exile and surviving-seat routing. Concessions during suspended choices, static
control dependencies, lose/win exceptions and player-lost triggers remain gated.
"""
from dataclasses import dataclass
import hashlib
import json
from .rules_state import ObjectRef,Zone,RulesViolation


def state_identity(state):
    return hashlib.sha256(json.dumps(state.snapshot(),sort_keys=True,separators=(',',':')).encode()).hexdigest()


@dataclass(frozen=True)
class DeparturePlan:
    state_identity: str
    players: tuple[str,...]
    owned_objects: tuple[ObjectRef,...]
    ended_control_effects: tuple[str,...]
    control_changes: tuple[tuple[ObjectRef,str],...]
    exile_objects: tuple[ObjectRef,...]

    def validate_state(self,state):
        if state_identity(state)!=self.state_identity:raise RulesViolation('Stale departure plan')


def plan_departure(state,players):
    """Plan a simultaneous departure without mutating state or making choices.

    Owned objects leave irrespective of controller or phased status. Effects
    granting control to departing players end, revealing the latest remaining
    effect or the battlefield entry controller. Objects still controlled by a
    departing player must be exiled; ownership alone cannot determine this.
    """
    players=tuple(players)
    if not players or len(set(players))!=len(players) or any(p not in state.live_players for p in players):
        raise RulesViolation('Departure requires distinct registered players')
    departing=set(players);snapshot=state.snapshot()
    effects=snapshot['control_effects'];bases=snapshot['control_bases']
    owned=tuple(obj.ref for obj in state.objects() if obj.owner in departing and obj.zone!=Zone.OUTSIDE)
    leaving=set(owned)
    ended=tuple(key for key,row in effects.items() if row['controller'] in departing or ObjectRef.from_json(row['ref']) in leaving)
    ended_set=set(ended);changes=[];exile=[]
    for obj in state.objects():
        if obj.ref in leaving or obj.zone==Zone.OUTSIDE:continue
        controller=obj.controller
        if obj.zone==Zone.BATTLEFIELD and obj.ref.card_id in bases:
            remaining=[row for key,row in effects.items() if key not in ended_set and ObjectRef.from_json(row['ref'])==obj.ref]
            controller=max(remaining,key=lambda row:row['timestamp'])['controller'] if remaining else bases[obj.ref.card_id]
        if controller!=obj.controller:changes.append((obj.ref,controller))
        # Only battlefield permanents and spells are controlled objects in the
        # supported card state; hand/graveyard controller fields are placeholders.
        if obj.zone in {Zone.BATTLEFIELD,Zone.STACK} and controller in departing:exile.append(obj.ref)
    return DeparturePlan(state_identity(state),tuple(p for p in state.players if p in departing),
        owned,ended,tuple(changes),tuple(exile))


@dataclass(frozen=True)
class GameResult:
    kind: str
    winners: tuple[str,...]
    departed: tuple[str,...]


class DepartureRules:
    def turn_order(self):
        start=self.state.players.index(self.active)
        return tuple(p for p in self.state.players[start:]+self.state.players[:start] if p in self.state.live_players)

    def priority_player(self):
        return next(iter(self.turn_order()),None)

    def next_live_player(self,player):
        start=self.state.players.index(player)
        return next((p for p in self.state.players[start+1:]+self.state.players[:start+1] if p in self.state.live_players),None)

    def _depart_players(self,players):
        plan=plan_departure(self.state,players);plan.validate_state(self.state)
        before=self.state.objects(Zone.BATTLEFIELD);views=self.characteristics();before_live_players=self.state.live_players
        self.state.mark_departed(plan.players)
        events=self.state.remove_owned_objects(plan.players)
        remaining_keys=tuple(key for key in plan.ended_control_effects if key in self.state._control_effects)
        self.state.end_control_effects(remaining_keys)
        self.stack=[frame for frame in self.stack if frame['controller'] in self.state.live_players
            and not (frame['spell'] and self._source(frame).owner in plan.players)]
        self.pending_triggers=[row for row in self.pending_triggers if row['controller'] in self.state.live_players]
        self.delayed_triggers=[row for row in self.delayed_triggers if row['controller'] in self.state.live_players]
        self.placement=None;self.passes=[];self.priority=self.priority_player()
        self.departure={'players':list(plan.players),'exile':[ref.to_json() for ref in plan.exile_objects]}
        self._event('players_departed',players=list(plan.players))
        # Phased-out owned objects leave, but do not generate leaves observations.
        observed=tuple(event for event in events if not event.before.phased)
        self._collect(observed,before,self.state.objects(Zone.BATTLEFIELD),views,before_live_players=before_live_players)
        self._prune_attachment_rules();self._combat_prune()
        if len(self.state.live_players)<=1:
            self.outcome={'kind':'win' if self.state.live_players else 'draw',
                'winners':list(self.state.live_players),'departed':[p for p in self.state.players if p not in self.state.live_players]}
            self.departure=None;self.priority=None
            self._event('game_finished',result=self.outcome)

    def _continue_departure(self):
        from .rules_state import ObjectRef
        refs=tuple(ObjectRef.from_json(row) for row in self.departure['exile'])
        if refs:
            source=self.state.get(refs[0])
            self._move(refs,Zone.EXILE,{'source':source.to_json(),'controller':self.priority_player()},
                'departure-exile:'+':'.join(self.departure['players']),cause='departed_controller_exile')
        self.departure=None

    def _exile_abandoned_control(self):
        refs=tuple(obj.ref for obj in self.state.objects(Zone.BATTLEFIELD) if obj.controller not in self.state.live_players)
        if not refs:return False
        source=self.state.get(refs[0])
        self._move(refs,Zone.EXILE,{'source':source.to_json(),'controller':self.priority_player()},
            'abandoned-control:'+str(self.state.sequence),cause='departed_controller_exile')
        return True
