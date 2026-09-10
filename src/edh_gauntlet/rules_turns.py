"""Turn-based actions and special land plays for the experimental interpreter.

Combat and player departures delegate to shared interpreters. Initialization,
mulligans and unsupported turn actions remain gated.
"""
from dataclasses import dataclass
from .rules_state import Zone, RulesViolation
from .rules_program import decode, Draw, Move, Select, Selector, Discard
from .rules_choices import PriorityBoundary


@dataclass(frozen=True)
class TurnActionBoundary:
    actor: str
    kind: str
    revision: str


class TurnRules:
    def player_permissions(self):
        """One public-source scan serves all seats; permissions are never consumed by source."""
        result={player:{'land_play_limit':1,'maximum_hand_size':7,'land_zones':[Zone.HAND.value]} for player in self.state.players}
        def apply(player,permissions):
            row=result[player]
            row['land_play_limit']+=permissions.additional_land_plays
            if permissions.no_maximum_hand_size:row['maximum_hand_size']=None
            row['land_zones']=sorted(set(row['land_zones'])|{zone.value for zone in permissions.land_zones})
        for obj in self.state.objects(Zone.BATTLEFIELD):
            if not obj.phased and obj.controller in self.state.live_players:
                apply(obj.controller,self.definition(obj).player_permissions)
        for effect in self.player_effects:
            if effect['controller'] in self.state.live_players:apply(effect['controller'],decode(effect['permissions']))
        return result

    def begin_turn_for_scenario(self, active):
        self._idle()
        if self.stack or self.turn_schedule is not None or active not in self.state.live_players:
            raise RulesViolation('Turn fixtures require an unstarted empty stack')
        self._validate_untap(active)
        self.turn_schedule = {'land_plays':0, 'advance':False, 'cleanup_priority':False}
        self._start_turn(active)
        return self.advance()

    def _validate_untap(self, active):
        if any(obj.phased for obj in self.state.objects(Zone.BATTLEFIELD, controller=active)):
            raise RulesViolation('Automatic phasing and attachment propagation are not yet supported')

    def _start_turn(self, active):
        self._validate_untap(active)
        self.state.empty_mana_pools(); self.state.start_turn(active)
        self.active = active; self.priority = active; self.passes = []
        self.turn_schedule.update(land_plays=0, advance=False, cleanup_priority=False)
        self.combat=None
        self._event('turn_began', active=active, turn=self.state.turn_number)
        self._begin_phase('upkeep')

    def _begin_phase(self, phase):
        self.state.empty_mana_pools(); self.phase = phase; self.priority = self.priority_player(); self.passes = []
        if phase=='postcombat_main':self.combat=None
        self._event('step_began', active=self.active, step=phase)
        self._collect_step(phase)

    def _advance_phase(self):
        self.turn_schedule['advance'] = False
        if self.phase == 'cleanup':
            self._begin_cleanup(); return
        if self.phase=='declare_attackers' and self.combat and self.combat['declared_any']:
            self._begin_phase('declare_blockers');self.priority=None;return
        if self.phase=='declare_blockers':
            self._start_damage_step(first=True);return
        if self.phase=='first_strike_damage':
            self._start_damage_step();return
        if self.phase=='combat_damage':
            self._begin_phase('end_combat');return
        following = {'upkeep':'draw', 'draw':'precombat_main', 'precombat_main':'begin_combat',
                     'begin_combat':'declare_attackers', 'declare_attackers':'end_combat',
                     'end_combat':'postcombat_main', 'postcombat_main':'end_step', 'end_step':'cleanup'}
        if self.phase not in following:raise RulesViolation('Unsupported turn transition')
        phase = following[self.phase]
        if phase == 'cleanup':
            self._begin_cleanup(); return
        if phase == 'draw':
            library = self.state.zone(self.active, Zone.LIBRARY)
            self._begin_phase(phase)
            if self.active not in self.state.live_players:return
            if not library:
                self.state.fail_draw(self.active);self._event('draw_failed',player=self.active);return
            source = library[-1]
            # This is a turn-based execution frame, never an object on the stack.
            self.resolving = self._frame(source, self.active, (Draw(),))
            self.resolving['turn_based'] = True
        else:
            self._begin_phase(phase)
            if phase == 'declare_attackers':self.priority = None

    def _begin_cleanup(self):
        self.turn_schedule['cleanup_priority'] = False
        self._begin_phase('cleanup'); self.priority = None
        hand = self.state.zone(self.active, Zone.HAND)
        limit=self.player_permissions()[self.active]['maximum_hand_size']
        excess = 0 if limit is None else max(0, len(hand)-limit)
        if excess:
            self.resolving = self._frame(hand[0], self.active, (
                Select(Selector(Zone.HAND, relation='owned'), excess, excess, (Discard('selected'),)),))
            self.resolving['turn_based'] = True
            self.resolving['cleanup_after'] = True
        else:self._finish_cleanup_actions()

    def _finish_cleanup_actions(self):
        if self.temporary_effects:
            self.temporary_effects=[]
            self.state.allocate_effect_timestamp()
            self._event('temporary_effects_expired')
        if self.player_effects:
            self.player_effects=[]
            self._event('player_permissions_expired')
        changed=self.state.expire_turn_control()
        self.state.clear_damage()
        if changed:self._event('control_effects_expired',refs=[ref.to_json() for ref in changed])

    def _turn_boundary(self):
        if self.turn_schedule['advance']:
            self._advance_phase()
            return self.advance()
        if self.phase == 'declare_attackers' and self.priority is None:
            return TurnActionBoundary(self.active, 'declare_attackers', self.revision)
        if self.phase == 'cleanup' and not self.turn_schedule['cleanup_priority']:
            following = self.next_live_player(self.active)
            self._start_turn(following)
            return self.advance()
        if self.priority is None:self.priority = self.priority_player()
        return PriorityBoundary(self.priority, ())

    def _mark_cleanup_priority(self):
        if self.turn_schedule is not None and self.phase == 'cleanup':
            self.turn_schedule['cleanup_priority'] = True

    def play_land(self, action_id, actor, ref, *, revision):
        self._idle()
        if not isinstance(action_id,str) or not action_id or len(action_id)>128 or action_id in self.action_receipts:
            raise RulesViolation('Invalid or already accepted action identity')
        if (self.turn_schedule is None or revision != self.revision or actor != self.active
                or self.priority != actor or self.stack or self.phase not in {'precombat_main','postcombat_main'}):
            raise RulesViolation('Land play requires current main-phase priority and an empty stack')
        source = self.state.get(ref)
        permissions=self.player_permissions()[actor]
        if source.zone.value not in permissions['land_zones'] or source.owner != actor or 'Land' not in self.effective(ref).types:
            raise RulesViolation('No permission to play this land')
        if self.turn_schedule['land_plays'] >= permissions['land_play_limit']:
            raise RulesViolation('No land plays remaining this turn')
        self.turn_schedule['land_plays'] += 1
        self.action_receipts[action_id] = {'kind':'play_land','actor':actor,'source':ref.to_json(),'revision':revision}
        self._event('land_played', actor=actor, source=ref.to_json(), action_id=action_id)
        self.resolving = self._frame(source, actor, (Move('source', Zone.BATTLEFIELD),))
        self.resolving['special_action'] = True
        self.priority = None; self.passes = []
        return self.advance()
