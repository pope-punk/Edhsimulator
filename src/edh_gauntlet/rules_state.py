"""Experimental rules state: physical identity, incarnations and atomic zone events.

No production host imports this module. Zone collections are derived read-only
views; callers cannot separately append the same card to another zone.
"""
from __future__ import annotations
from dataclasses import dataclass,replace,asdict
from enum import Enum
import hashlib
from typing import Iterable


class RulesViolation(ValueError):pass


class Zone(str,Enum):
    LIBRARY='library'
    HAND='hand'
    BATTLEFIELD='battlefield'
    GRAVEYARD='graveyard'
    EXILE='exile'
    STACK='stack'
    COMMAND='command'
    OUTSIDE='outside'


@dataclass(frozen=True,order=True)
class ObjectRef:
    card_id:str
    incarnation:int

    def to_json(self):return {'card_id':self.card_id,'incarnation':self.incarnation}

    @classmethod
    def from_json(cls,value):
        if set(value)!={'card_id','incarnation'} or not isinstance(value['card_id'],str) or type(value['incarnation']) is not int or value['incarnation']<0:
            raise RulesViolation('Invalid object reference')
        return cls(**value)


@dataclass(frozen=True,order=True)
class PlayerRef:
    player: str

    def to_json(self):return {'player':self.player}

    @classmethod
    def from_json(cls,value):
        if type(value) is not dict or set(value)!={'player'} or type(value['player']) is not str or not value['player']:
            raise RulesViolation('Invalid player target')
        return cls(value['player'])


def target_from_json(value):
    return PlayerRef.from_json(value) if type(value) is dict and 'player' in value else ObjectRef.from_json(value)


@dataclass(frozen=True)
class RulesObject:
    ref:ObjectRef
    definition:str
    owner:str
    controller:str
    zone:Zone
    token:bool=False
    commander:bool=False
    copied_definition:str|None=None
    counters:tuple[tuple[str,int],...]=()
    entry_flags:frozenset[str]=frozenset()
    tapped:bool=False
    phased:bool=False
    attached_to:ObjectRef|None=None
    timestamp:int=0
    cast_x:int=0
    controlled_since:int=0
    damage_marked:int=0
    deathtouch_hit:bool=False
    combat_departure:int=0
    copied_add_types:tuple[str,...]=()

    @property
    def effective_definition(self):return self.copied_definition or self.definition

    def to_json(self):
        return {**asdict(self),'ref':self.ref.to_json(),'zone':self.zone.value,'entry_flags':sorted(self.entry_flags),'copied_add_types':list(self.copied_add_types)}

    @classmethod
    def from_json(cls,value):
        value=dict(value);value['ref']=ObjectRef.from_json(value['ref']);value['zone']=Zone(value['zone'])
        value['attached_to']=ObjectRef.from_json(value['attached_to']) if value['attached_to'] else None
        value['entry_flags']=frozenset(value['entry_flags']);value['counters']=tuple(tuple(row) for row in value['counters'])
        value['copied_add_types']=tuple(value['copied_add_types'])
        return cls(**value)


@dataclass(frozen=True)
class ResourcePayment:
    actor: str
    mana: tuple[tuple[str, int], ...] = ()
    life: int = 0
    taps: tuple[ObjectRef, ...] = ()
    counters: tuple[tuple[ObjectRef,str,int], ...] = ()


@dataclass(frozen=True)
class ZoneMove:
    source:ObjectRef
    destination:Zone
    controller:str|None=None
    copied_definition:str|None=None
    entry_flags:frozenset[str]=frozenset()
    # None: append to destination (top for library); 0: bottom of library.
    position:int|None=None
    attached_to:ObjectRef|None=None
    cast_x:int=0
    tapped:bool=False
    counters:tuple[tuple[str,int],...]=()
    copied_add_types:tuple[str,...]=()


@dataclass(frozen=True)
class ZoneEvent:
    sequence:int
    batch:int
    cause:str
    before:RulesObject
    after:RulesObject

    def to_json(self):return {'sequence':self.sequence,'batch':self.batch,'cause':self.cause,'before':self.before.to_json(),'after':self.after.to_json()}


class RulesState:
    """Single physical-card index; immutable objects returned to every caller."""
    CHECKPOINT_SCHEMA=12

    def __init__(self,players:Iterable[str],*,seed=0,commander_identities=None,starting_life=40):
        if type(seed) is not int or seed<0:raise RulesViolation('Invalid shuffle seed')
        self._shuffle_seed=seed;self._shuffle_nonce=0
        self.players=tuple(players)
        if not self.players or len(set(self.players))!=len(self.players):raise RulesViolation('Players must be unique')
        if commander_identities is not None:
            if (not isinstance(commander_identities,dict) or set(commander_identities)!=set(self.players)
                    or any(not isinstance(colors,(list,tuple)) or any(type(c) is not str or c not in 'WUBRG' or len(c)!=1 for c in colors)
                           or len(set(colors))!=len(colors) for colors in commander_identities.values())):
                raise RulesViolation('Invalid bound commander color identities')
            self._commander_identities={p:tuple(c for c in 'WUBRG' if c in commander_identities[p]) for p in self.players}
        else:self._commander_identities=None
        self._objects:dict[str,RulesObject]={}
        self._order:dict[tuple[str,Zone],list[str]]={(p,z):[] for p in self.players for z in Zone}
        self._physical:set[str]=set();self._issued:set[str]=set();self._sequence=0;self._batch=0
        self._events:list[ZoneEvent]=[]
        totals={p:starting_life for p in self.players} if type(starting_life) is int else starting_life
        if (not isinstance(totals,dict) or set(totals)!=set(self.players)
                or any(type(n) is not int or n<=0 for n in totals.values())):
            raise RulesViolation('Invalid starting life totals')
        self._starting_life=dict(totals)
        self._life=dict(totals);self._player_counters={p:{} for p in self.players}
        self._command_casts={p:0 for p in self.players}
        self._commander_casts={};self._mana={p:{} for p in self.players}
        self._turn_starts={p:0 for p in self.players};self._turn_number=0;self._turn_active=None
        self._commander_damage={}
        self._control_effects={};self._control_bases={}
        self._departed=set();self._failed_draws=set()

    def commander_identity(self,player):
        if self._commander_identities is None or player not in self.players:
            raise RulesViolation('Commander color identities are not bound for this player')
        return self._commander_identities[player]

    @property
    def live_players(self):return tuple(p for p in self.players if p not in self._departed)

    def fail_draw(self,player):
        if player in self.live_players:self._failed_draws.add(player);self._sequence+=1

    def losing_players(self):
        return tuple(p for p in self.live_players if self._life[p]<=0 or self._player_counters[p].get('poison',0)>=10
            or p in self._failed_draws or any(player==p and n>=21 for (player,card),n in self._commander_damage.items()))

    def mark_departed(self,players):
        players=tuple(players)
        if not players or len(set(players))!=len(players) or any(p not in self.live_players for p in players):
            raise RulesViolation('Invalid departing players')
        self._departed.update(players);self._sequence+=1
        for player in players:self._mana[player]={}

    def remove_owned_objects(self,players):
        # OUTSIDE is an archival location, not a replacement-eligible zone move.
        objects=[o for o in self.objects() if o.owner in players and o.zone!=Zone.OUTSIDE]
        self._batch+=1;events=[]
        for before in objects:
            self._control_bases.pop(before.ref.card_id,None)
            self._control_effects={k:r for k,r in self._control_effects.items() if r['ref']!=before.ref}
            self._sequence+=1
            after=RulesObject(ObjectRef(before.ref.card_id,before.ref.incarnation+1),before.definition,before.owner,before.owner,Zone.OUTSIDE,
                token=before.token,commander=before.commander,timestamp=self._sequence,controlled_since=self._sequence)
            self._order[(before.owner,before.zone)].remove(before.ref.card_id)
            self._order[(before.owner,Zone.OUTSIDE)].append(before.ref.card_id);self._objects[before.ref.card_id]=after
            events.append(ZoneEvent(self._sequence,self._batch,'owner_left_game',before,after))
        self._events.extend(events);self.assert_invariants();return tuple(events)

    @property
    def events(self):return tuple(self._events)

    @property
    def event_count(self):return len(self._events)

    def events_since(self,index):
        if type(index) is not int or not 0<=index<=len(self._events):raise RulesViolation('Invalid event cursor')
        return tuple(self._events[index:])

    @property
    def sequence(self):return self._sequence

    def life(self,player):return self._life[player]
    def starting_life(self,player):return self._starting_life[player]

    def player_counters(self,player):return tuple(sorted(self._player_counters[player].items()))

    def command_casts(self,player):return self._command_casts[player]

    def commander_casts(self,card_id):return self._commander_casts.get(card_id,0)

    def mana_pool(self,player):return tuple(sorted(self._mana[player].items()))

    def add_card(self,card_id,definition,owner,zone,*,controller=None,token=False,commander=False):
        """Scenario/bootstrap API; real creation effects must be separately modeled."""
        zone=Zone(zone);controller=controller or owner
        if not card_id or card_id in self._issued:raise RulesViolation('Duplicate physical identity')
        if owner not in self.players or controller not in self.players:raise RulesViolation('Unknown player')
        self._sequence+=1
        obj=RulesObject(ObjectRef(card_id,0),definition,owner,controller,zone,token,commander,timestamp=self._sequence,controlled_since=self._sequence)
        self._issued.add(card_id)
        self._objects[card_id]=obj;self._order[(owner,zone)].append(card_id)
        if not token:self._physical.add(card_id)
        self.assert_invariants();return obj.ref

    def get(self,ref:ObjectRef):
        if not isinstance(ref,ObjectRef):raise RulesViolation('Expected exact object reference')
        obj=self._objects.get(ref.card_id)
        if obj is None or obj.ref!=ref:raise RulesViolation('Stale or unknown object incarnation')
        return obj

    def current(self,card_id):return self._objects[card_id].ref

    def objects(self,zone=None,*,owner=None,controller=None):
        zone=Zone(zone) if zone is not None else None
        return tuple(obj for obj in self._objects.values() if (zone is None or obj.zone==zone) and
                     (owner is None or obj.owner==owner) and (controller is None or obj.controller==controller))

    def zone(self,owner,zone):
        return tuple(self._objects[card_id] for card_id in self._order[(owner,Zone(zone))])

    def move(self,moves:Iterable[ZoneMove],cause:str,*,detaches=(),counter_pairs=(),payment=None,creates=()):
        """Commit a validated simultaneous move, or leave all state unchanged.

        Replacement choices must already be resolved by the rules interpreter.
        Same-zone operations are not zone changes; reordering has a separate API.
        """
        moves=tuple(moves);detaches=tuple(detaches);counter_pairs=tuple(counter_pairs)
        creates=tuple(creates);new={}
        for obj in creates:
            if (not isinstance(obj,RulesObject) or not isinstance(obj.ref,ObjectRef) or obj.ref.incarnation!=0
                    or not obj.ref.card_id or obj.ref.card_id in self._issued or obj.ref.card_id in new
                    or obj.owner not in self.live_players or not obj.definition
                    or obj!=RulesObject(obj.ref,obj.definition,obj.owner,obj.owner,Zone.OUTSIDE,token=True)):
                raise RulesViolation('Invalid fresh token proposal')
            new[obj.ref.card_id]=obj
        if set(new)!={m.source.card_id for m in moves if m.source.card_id in new}:raise RulesViolation('Every fresh token must have an entry proposal')
        if payment is not None:
            self.validate_payment(payment)
        if payment is not None and payment.counters and (moves or detaches or counter_pairs):raise RulesViolation('Counter payment cannot be combined with zone or state-action groups')
        for refs in (detaches,counter_pairs):
            if len(set(refs))!=len(refs):raise RulesViolation('Duplicate non-zone state action')
            for ref in refs:
                obj=self.get(ref)
                if obj.zone!=Zone.BATTLEFIELD or obj.phased:raise RulesViolation('Unavailable state-action object')
        if len({m.source.card_id for m in moves})!=len(moves):raise RulesViolation('One object cannot move twice in a simultaneous event')
        pending=[]
        for move in moves:
            before=new.get(move.source.card_id) or self.get(move.source);destination=Zone(move.destination)
            if before.ref!=move.source:raise RulesViolation('Invalid fresh token reference')
            if payment is not None and before.ref in payment.taps:before=replace(before,tapped=True)
            if before.zone==destination:raise RulesViolation('Same-zone movement is not a zone change')
            if before.phased and cause!='departed_controller_exile':raise RulesViolation('Phased object is unavailable')
            if before.ref.card_id not in new and before.token and before.zone not in {Zone.BATTLEFIELD,Zone.STACK}:raise RulesViolation('A departed token cannot change zones again')
            if before.zone==Zone.OUTSIDE and before.ref.card_id not in new:raise RulesViolation('Out-of-game object cannot return without a supported rule')
            controller=move.controller or before.owner
            if controller not in self.players:raise RulesViolation('Unknown destination controller')
            if destination in {Zone.BATTLEFIELD,Zone.STACK} and controller not in self.live_players:continue
            if type(move.cast_x) is not int or move.cast_x<0 or move.cast_x and destination!=Zone.STACK:raise RulesViolation('Invalid announced X')
            if move.position is not None and (type(move.position) is not int or move.position<0):raise RulesViolation('Invalid destination position')
            if (not isinstance(move.counters,tuple) or any(not isinstance(row,tuple) or len(row)!=2 or type(row[0]) is not str or not row[0] or type(row[1]) is not int or row[1]<=0 for row in move.counters)
                    or len({row[0] for row in move.counters})!=len(move.counters)):raise RulesViolation('Invalid entry counters')
            if (not isinstance(move.copied_add_types,tuple) or any(type(t) is not str or t not in {'Artifact','Battle','Creature','Enchantment','Instant','Kindred','Land','Planeswalker','Sorcery'} for t in move.copied_add_types)
                    or len(set(move.copied_add_types))!=len(move.copied_add_types) or move.copied_add_types and not move.copied_definition):raise RulesViolation('Invalid copiable type exception')
            if type(move.tapped) is not bool:raise RulesViolation('Invalid entry tapped status')
            if destination!=Zone.BATTLEFIELD and (move.copied_definition or move.entry_flags or move.attached_to or move.tapped or move.counters or move.copied_add_types):raise RulesViolation('Entry attributes require battlefield entry')
            after=RulesObject(ObjectRef(before.ref.card_id,before.ref.incarnation+1),before.definition,before.owner,
                controller,destination,before.token,before.commander,move.copied_definition,
                copied_add_types=tuple(sorted(move.copied_add_types)),counters=tuple(sorted(move.counters)),entry_flags=move.entry_flags,tapped=move.tapped,attached_to=move.attached_to,timestamp=self._sequence+len(pending)+1,cast_x=move.cast_x,controlled_since=self._sequence+len(pending)+1)
            pending.append((move,before,after))
        if not pending and not detaches and not counter_pairs and payment is None:return ()
        self._batch+=1;events=[]
        for move,before,after in pending:
            self._control_bases.pop(before.ref.card_id,None)
            self._control_effects={key:row for key,row in self._control_effects.items() if row['ref']!=before.ref}
            if before.ref.card_id in new:self._issued.add(before.ref.card_id)
            else:self._order[(before.owner,before.zone)].remove(before.ref.card_id)
            self._objects[after.ref.card_id]=after
            destination=self._order[(after.owner,after.zone)]
            if move.position is None:destination.append(after.ref.card_id)
            else:destination.insert(move.position,after.ref.card_id)
            self._sequence+=1;events.append(ZoneEvent(self._sequence,self._batch,cause,before,after))
        # Non-zone state actions share this commit. Departed objects already
        # lost their attachments/counters; before-event snapshots remain intact.
        for ref in detaches:
            current=self._objects.get(ref.card_id)
            if current is not None and current.ref==ref and current.attached_to is not None:
                self._objects[ref.card_id]=replace(current,attached_to=None);self._sequence+=1
        for ref in counter_pairs:
            current=self._objects.get(ref.card_id)
            if current is not None and current.ref==ref:self.cancel_opposing_counters(ref)
        if payment is not None:
            pool=self._mana[payment.actor]
            for symbol,amount in payment.mana:
                pool[symbol]-=amount
                if not pool[symbol]:del pool[symbol]
            self._life[payment.actor]-=payment.life
            moved_refs={before.ref for _,before,_ in pending}
            for ref in payment.taps:
                if ref not in moved_refs:self._objects[ref.card_id]=replace(self.get(ref),tapped=True)
            for ref,kind,amount in payment.counters:
                obj=self.get(ref);counts=dict(obj.counters);counts[kind]-=amount
                self._objects[ref.card_id]=replace(obj,counters=tuple(sorted((k,n) for k,n in counts.items() if n)))
            self._sequence+=1
        self._events.extend(events);self.assert_invariants();return tuple(events)

    def attach(self, ref, target):
        obj = self.get(ref)
        attached = self.get(target)
        if obj.zone != Zone.BATTLEFIELD or obj.phased or attached.phased or ref.card_id == target.card_id:
            raise RulesViolation('Invalid attachment')
        if obj.attached_to==target:return False
        self._objects[ref.card_id] = replace(obj, attached_to=target, timestamp=self._sequence+1)
        self._sequence += 1
        return True

    def cease_token(self,ref):
        obj=self.get(ref)
        if not obj.token or obj.zone in {Zone.BATTLEFIELD,Zone.STACK}:raise RulesViolation('Token cannot cease in this zone')
        self._order[(obj.owner,obj.zone)].remove(ref.card_id);del self._objects[ref.card_id]
        self._sequence+=1;self.assert_invariants()

    def reorder(self,owner,zone,refs):
        refs=tuple(refs);zone=Zone(zone);existing=self.zone(owner,zone)
        if len(refs)!=len(existing) or set(refs)!={obj.ref for obj in existing}:raise RulesViolation('Reorder must be a complete exact permutation')
        self._order[(owner,zone)]=[ref.card_id for ref in refs];self._sequence+=1

    def _random_order(self,values):
        ids=list(values);draw=0
        for index in range(len(ids)-1,0,-1):
            bound=index+1;limit=(2**256//bound)*bound
            while True:
                value=int.from_bytes(hashlib.sha256(f'{self._shuffle_seed}:{self._shuffle_nonce}:{draw}'.encode()).digest(),'big');draw+=1
                if value<limit:break
            other=value%bound;ids[index],ids[other]=ids[other],ids[index]
        return ids

    def random_bottom(self,owner,refs):
        """Randomize only the selected library subset and put it on the bottom."""
        if owner not in self.live_players:raise RulesViolation('Unavailable library owner')
        refs=tuple(refs)
        if len(set(refs))!=len(refs):raise RulesViolation('Duplicate random-bottom reference')
        objects=tuple(self.get(ref) for ref in refs)
        if any(obj.zone!=Zone.LIBRARY or obj.owner!=owner for obj in objects):raise RulesViolation('Invalid random-bottom subset')
        if not refs:return
        ids=self._random_order(obj.ref.card_id for obj in objects);chosen=set(ids)
        middle=[card for card in self._order[(owner,Zone.LIBRARY)] if card not in chosen]
        self._shuffle_nonce+=1;self._sequence+=1
        for card in ids:
            obj=self._objects[card];self._objects[card]=replace(obj,ref=ObjectRef(card,obj.ref.incarnation+1))
        self._order[(owner,Zone.LIBRARY)]=ids+middle;self.assert_invariants()

    def shuffle_library(self,owner):
        if owner not in self.live_players:raise RulesViolation('Unavailable library owner')
        ids=self._random_order(self._order[(owner,Zone.LIBRARY)])
        # Reordering hidden objects retires earlier inspection references. This
        # is not a zone change and must not produce leaves/entry events.
        self._shuffle_nonce+=1;self._sequence+=1
        for card in ids:
            obj=self._objects[card]
            self._objects[card]=replace(obj,ref=ObjectRef(card,obj.ref.incarnation+1))
        self._order[(owner,Zone.LIBRARY)]=ids;self.assert_invariants()

    def change_control(self,ref,controller,*,duration='indefinite'):
        """Create a resolved, fixed-recipient control effect, even for the current controller.

        Static control abilities and dependencies are not represented by this API.
        A same-controller effect must still exist when an earlier effect expires.
        """
        keys=self.change_control_batch((ref,),controller,duration=duration)
        return keys[0] if keys else None

    def change_control_batch(self,refs,controller,*,duration='indefinite'):
        refs=tuple(refs)
        if controller not in self.players or duration not in {'indefinite','until_end_of_turn'}:
            raise RulesViolation('Invalid control effect')
        if len(set(refs))!=len(refs):raise RulesViolation('Duplicate control recipient')
        if controller not in self.live_players:return ()
        objects=[self.get(ref) for ref in refs]
        if any(obj.zone!=Zone.BATTLEFIELD or obj.phased for obj in objects):raise RulesViolation('Invalid control change')
        keys=[]
        for obj in objects:
            self._control_bases.setdefault(obj.ref.card_id,obj.controller)
            self._sequence+=1;key='control:'+str(self._sequence);keys.append(key)
            self._control_effects[key]={'ref':obj.ref,'controller':controller,'timestamp':self._sequence,'duration':duration}
            if obj.controller!=controller:
                self._objects[obj.ref.card_id]=replace(obj,controller=controller,controlled_since=self._sequence)
        self.assert_invariants();return tuple(keys)

    def end_control_effects(self,keys):
        keys=tuple(keys)
        if len(set(keys))!=len(keys) or any(key not in self._control_effects for key in keys):
            raise RulesViolation('Unknown or duplicate control effect')
        if not keys:return ()
        affected={self._control_effects[key]['ref'] for key in keys}
        for key in keys:del self._control_effects[key]
        self._sequence+=1;changed=[]
        for ref in sorted(affected):
            obj=self.get(ref)
            remaining=[row for row in self._control_effects.values() if row['ref']==ref]
            controller=max(remaining,key=lambda row:row['timestamp'])['controller'] if remaining else self._control_bases.pop(ref.card_id)
            if controller!=obj.controller:
                self._objects[ref.card_id]=replace(obj,controller=controller,controlled_since=self._sequence)
                changed.append(ref)
        self.assert_invariants();return tuple(changed)

    def expire_turn_control(self):
        return self.end_control_effects(tuple(key for key,row in self._control_effects.items() if row['duration']=='until_end_of_turn'))

    def set_tapped_batch(self,refs,tapped):
        refs=tuple(refs)
        if type(tapped) is not bool or len(set(refs))!=len(refs):raise RulesViolation('Invalid orientation batch')
        objects=tuple(self.get(ref) for ref in refs)
        if any(obj.zone!=Zone.BATTLEFIELD or obj.phased for obj in objects):raise RulesViolation('Unavailable orientation object')
        changed=tuple(obj for obj in objects if obj.tapped!=tapped)
        for obj in changed:self._objects[obj.ref.card_id]=replace(obj,tapped=tapped)
        if changed:self._sequence+=1
        return tuple(obj.ref for obj in changed)

    def start_turn(self, active):
        """Atomic ordinary untap; the interpreter owns phasing/untap restrictions."""
        if active not in self.players:raise RulesViolation('Unknown active player')
        self._sequence+=1;self._turn_starts[active]=self._sequence
        self._turn_number+=1;self._turn_active=active
        for key,obj in self._objects.items():
            if obj.zone==Zone.BATTLEFIELD and obj.controller==active and not obj.phased and obj.tapped:
                self._objects[key]=replace(obj,tapped=False)

    def ready_since_turn_start(self, ref):
        obj=self.get(ref)
        return obj.zone==Zone.BATTLEFIELD and obj.controlled_since<self._turn_starts[obj.controller]

    @property
    def turn_number(self):return self._turn_number

    @property
    def turn_active(self):return self._turn_active

    def phase(self,ref,out):
        obj=self.get(ref)
        if obj.zone!=Zone.BATTLEFIELD or type(out) is not bool:raise RulesViolation('Only battlefield objects phase')
        self._objects[ref.card_id]=replace(obj,phased=out,combat_departure=self._sequence+1 if out else obj.combat_departure);self._sequence+=1

    def damage_batch(self, assignments):
        """Atomic nonprevented damage; keyword semantics are supplied by the kernel."""
        assignments=tuple(assignments);life=dict(self._life);marked={};touch=set();gains={};counter_updates={};changed=False
        commander_damage=dict(self._commander_damage)
        for row in assignments:
            amount=row['amount'];target=row['target'];source=row['source']
            gain=row.get('lifelink_gain',amount)
            if type(gain) is not int or gain<0 or 'lifelink_gain' in row and not row.get('lifelink'):raise RulesViolation('Invalid lifelink gain')
            if type(amount) is not int or amount<0 or not isinstance(source,RulesObject):raise RulesViolation('Invalid damage assignment')
            if source.controller not in self.players or any(type(row.get(key,False)) is not bool for key in ('lifelink','deathtouch','combat')):raise RulesViolation('Invalid damage source')
            if isinstance(target,str):
                if target not in self.players:raise RulesViolation('Unknown damage recipient')
                if target not in self.live_players or not amount:continue
                life[target]-=amount
                if row.get('combat') and source.commander:
                    key=(target,source.ref.card_id);commander_damage[key]=commander_damage.get(key,0)+amount
            else:
                obj=self.get(target)
                if obj.zone!=Zone.BATTLEFIELD or obj.phased:raise RulesViolation('Unavailable damage recipient')
                recipient_types=row.get('recipient_types',('Creature',))
                if (not isinstance(recipient_types,tuple) or not recipient_types
                        or any(type(kind) is not str or kind not in {'Creature','Planeswalker','Battle'} for kind in recipient_types)
                        or len(set(recipient_types))!=len(recipient_types)):
                    raise RulesViolation('Invalid damage recipient characteristics')
                if not amount:continue
                if 'Creature' in recipient_types:
                    marked[target]=marked.get(target,obj.damage_marked)+amount
                    if row.get('deathtouch') and amount:touch.add(target)
                for card_type,counter in (('Planeswalker','loyalty'),('Battle','defense')):
                    if card_type in recipient_types:
                        counts=counter_updates.setdefault(target,dict(obj.counters))
                        remaining=max(0,counts.get(counter,0)-amount)
                        if remaining:counts[counter]=remaining
                        else:counts.pop(counter,None)
            changed=True
            if row.get('lifelink') and amount and source.controller in self.live_players:
                life[source.controller]+=gain;gains[source.controller]=gains.get(source.controller,0)+gain
        if not changed:return {}
        self._life=life;self._commander_damage=commander_damage
        for ref,amount in marked.items():
            obj=self.get(ref);self._objects[ref.card_id]=replace(obj,damage_marked=amount,deathtouch_hit=obj.deathtouch_hit or ref in touch)
        for ref,counts in counter_updates.items():
            self._objects[ref.card_id]=replace(self.get(ref),counters=tuple(sorted(counts.items())))
        self._sequence+=1
        return gains

    def clear_deathtouch_history(self):
        refs=[obj.ref for obj in self.objects(Zone.BATTLEFIELD) if obj.deathtouch_hit]
        for ref in refs:self._objects[ref.card_id]=replace(self.get(ref),deathtouch_hit=False)
        if refs:self._sequence+=1

    def allocate_effect_timestamp(self):
        """Order a new continuous effect against permanent and attachment timestamps."""
        self._sequence+=1
        return self._sequence

    def clear_damage(self):
        changed=False
        for key,obj in self._objects.items():
            if obj.damage_marked or obj.deathtouch_hit:
                self._objects[key]=replace(obj,damage_marked=0,deathtouch_hit=False);changed=True
        if changed:self._sequence+=1

    def put_counters_batch(self,placements):
        """Commit validated permanent/player counter additions in one mutation."""
        placements=tuple(placements);seen=set();objects={};players={}
        for recipient,additions in placements:
            if not isinstance(recipient,(ObjectRef,PlayerRef)) or recipient in seen:raise RulesViolation('Invalid or duplicate counter recipient')
            seen.add(recipient)
            if not isinstance(additions,tuple) or not additions:raise RulesViolation('Counter additions must be a nonempty tuple')
            kinds=[]
            for kind,amount in additions:
                if type(kind) is not str or not kind or type(amount) is not int or amount<=0:raise RulesViolation('Invalid counter addition')
                kinds.append(kind)
            if len(kinds)!=len(set(kinds)):raise RulesViolation('Duplicate counter kind')
            if isinstance(recipient,PlayerRef):
                if recipient.player not in self.live_players:raise RulesViolation('Unavailable counter recipient')
                counts=dict(self._player_counters[recipient.player])
            else:
                obj=self.get(recipient)
                if obj.zone!=Zone.BATTLEFIELD or obj.phased:raise RulesViolation('Unavailable counter recipient')
                counts=dict(obj.counters)
            for kind,amount in additions:counts[kind]=counts.get(kind,0)+amount
            if isinstance(recipient,PlayerRef):players[recipient.player]=counts
            else:objects[recipient]=replace(obj,counters=tuple(sorted(counts.items())))
        if not placements:return
        for ref,obj in objects.items():self._objects[ref.card_id]=obj
        self._player_counters.update(players);self._sequence+=1

    def add_counters(self,ref,kind,amount):
        obj=self.get(ref)
        if obj.zone!=Zone.BATTLEFIELD or obj.phased or type(kind) is not str or not kind or type(amount) is not int or amount<0:raise RulesViolation('Invalid counter placement')
        if not amount:return
        self.put_counters_batch(((ref,((kind,amount),)),))

    def cancel_opposing_counters(self, ref):
        obj = self.get(ref)
        counters = dict(obj.counters)
        amount = min(counters.get('+1/+1', 0), counters.get('-1/-1', 0))
        if obj.zone != Zone.BATTLEFIELD or obj.phased or not amount:
            return 0
        for kind in ('+1/+1', '-1/-1'):
            counters[kind] -= amount
        self._objects[ref.card_id] = replace(obj, counters=tuple(sorted((kind, count) for kind, count in counters.items() if count)))
        self._sequence += 1
        return amount

    def add_player_counters(self,player,kind,amount):
        if type(kind) is not str or not kind or type(amount) is not int or amount<0:raise RulesViolation('Invalid player counters')
        if not amount or player not in self.live_players:return
        self.put_counters_batch(((PlayerRef(player),((kind,amount),)),))

    def lose_life_batch(self,players,amount):
        """Apply a nontargeting loss instruction atomically; no damage or payment."""
        players=tuple(players)
        if type(amount) is not int or amount<0 or len(set(players))!=len(players) or any(p not in self.live_players for p in players):
            raise RulesViolation('Invalid life-loss batch')
        if not amount or not players:return {}
        self._life={p:life-amount if p in players else life for p,life in self._life.items()}
        self._sequence+=1
        return {player:amount for player in players}

    def gain_life(self,player,amount):
        if type(amount) is not int or amount<0:raise RulesViolation('Invalid life gain')
        if player not in self.live_players:return
        self._life[player]+=amount;self._sequence+=1

    def add_mana(self, player, symbols):
        symbols=tuple(symbols)
        if player not in self.players or any(symbol not in tuple('WUBRGC') for symbol in symbols):
            raise RulesViolation('Invalid mana production')
        if player not in self.live_players:return
        for symbol in symbols:self._mana[player][symbol]=self._mana[player].get(symbol,0)+1
        if symbols:self._sequence+=1

    def empty_mana_pools(self):
        if any(self._mana.values()):
            self._mana={player:{} for player in self.players};self._sequence+=1

    def validate_payment(self, payment):
        if not isinstance(payment,ResourcePayment) or payment.actor not in self.live_players:
            raise RulesViolation('Invalid resource payment')
        if type(payment.life) is not int or not 0<=payment.life<=self._life[payment.actor]:
            raise RulesViolation('Insufficient life for payment')
        if not isinstance(payment.mana,tuple) or any(not isinstance(row,tuple) or len(row)!=2 for row in payment.mana):
            raise RulesViolation('Invalid mana payment')
        symbols=[symbol for symbol,_ in payment.mana]
        if any(symbol not in tuple('WUBRGC') for symbol in symbols) or len(set(symbols))!=len(symbols):
            raise RulesViolation('Invalid or duplicate mana symbol')
        for symbol,amount in payment.mana:
            if type(amount) is not int or amount<=0 or self._mana[payment.actor].get(symbol,0)<amount:
                raise RulesViolation('Insufficient or invalid mana payment')
        if not isinstance(payment.taps,tuple) or any(not isinstance(ref,ObjectRef) for ref in payment.taps) or len(set(payment.taps))!=len(payment.taps):
            raise RulesViolation('Duplicate tap payment')
        for ref in payment.taps:
            obj=self.get(ref)
            if obj.zone!=Zone.BATTLEFIELD or obj.phased or obj.tapped or obj.controller!=payment.actor:
                raise RulesViolation('Unavailable tap payment')

        if (not isinstance(payment.counters,tuple) or any(not isinstance(row,tuple) or len(row)!=3
                or not isinstance(row[0],ObjectRef) or type(row[1]) is not str or not row[1]
                or type(row[2]) is not int or row[2]<1 for row in payment.counters)):
            raise RulesViolation('Invalid counter payment')
        if len({(ref,kind) for ref,kind,_ in payment.counters})!=len(payment.counters):raise RulesViolation('Duplicate counter payment')
        for ref,kind,amount in payment.counters:
            obj=self.get(ref)
            if obj.zone!=Zone.BATTLEFIELD or obj.phased or obj.controller!=payment.actor or dict(obj.counters).get(kind,0)<amount:
                raise RulesViolation('Unavailable counter payment')

    def record_command_cast(self,player,card_id=None):
        self._command_casts[player]+=1
        if card_id is not None:self._commander_casts[card_id]=self._commander_casts.get(card_id,0)+1
        self._sequence+=1

    def assert_invariants(self):
        if type(self._shuffle_seed) is not int or self._shuffle_seed<0 or type(self._shuffle_nonce) is not int or self._shuffle_nonce<0:raise RulesViolation('Invalid shuffle ledger')
        if not self._departed<=set(self.players) or not self._failed_draws<=set(self.players):raise RulesViolation('Invalid player status ledger')
        if set(self._starting_life)!=set(self.players) or any(type(n) is not int or n<=0 for n in self._starting_life.values()):raise RulesViolation('Invalid starting life ledger')
        controlled=set()
        for key,row in self._control_effects.items():
            obj=self.get(row['ref']);controlled.add(obj.ref.card_id)
            if (obj.zone!=Zone.BATTLEFIELD or row['controller'] not in self.players
                    or type(row['timestamp']) is not int or not 0<row['timestamp']<=self._sequence
                    or key!='control:'+str(row['timestamp']) or row['duration'] not in {'indefinite','until_end_of_turn'}):
                raise RulesViolation('Invalid control effect ledger')
        if controlled!=set(self._control_bases) or any(p not in self.players for p in self._control_bases.values()):
            raise RulesViolation('Invalid default-control ledger')
        for card in controlled:
            latest=max((row for row in self._control_effects.values() if row['ref'].card_id==card),key=lambda row:row['timestamp'])
            if self._objects[card].controller!=latest['controller']:raise RulesViolation('Control ledger disagrees with object')
        if set(self._mana)!=set(self.players) or set(self._life)!=set(self.players):raise RulesViolation('Invalid player resource ledger')
        if any(type(n) is not int for n in self._life.values()):raise RulesViolation('Invalid life ledger')
        if set(self._player_counters)!=set(self.players):raise RulesViolation('Invalid player counter ledger')
        for counts in self._player_counters.values():
            if any(type(kind) is not str or not kind or type(amount) is not int or amount<=0 for kind,amount in counts.items()):
                raise RulesViolation('Invalid player counter ledger')
        for pool in self._mana.values():
            if any(symbol not in tuple('WUBRGC') or type(amount) is not int or amount<=0 for symbol,amount in pool.items()):raise RulesViolation('Invalid mana ledger')
        if set(self._command_casts)!=set(self.players) or any(type(n) is not int or n<0 for n in self._command_casts.values()):raise RulesViolation('Invalid command cast ledger')
        if any(card not in self._physical or type(n) is not int or n<0 for card,n in self._commander_casts.items()):raise RulesViolation('Invalid per-card commander ledger')
        if any(player not in self.players or card not in self._physical or not self._objects[card].commander
               or type(n) is not int or n<0 for (player,card),n in self._commander_damage.items()):
            raise RulesViolation('Invalid commander damage ledger')
        if set(self._turn_starts)!=set(self.players) or any(type(n) is not int or not 0<=n<=self._sequence for n in self._turn_starts.values()):raise RulesViolation('Invalid turn-start ledger')
        if type(self._turn_number) is not int or self._turn_number<0 or self._turn_active is not None and self._turn_active not in self.players:raise RulesViolation('Invalid turn ledger')
        seen=[]
        for (owner,zone),ids in self._order.items():
            for card_id in ids:
                obj=self._objects[card_id]
                if obj.owner!=owner or obj.zone!=zone:raise RulesViolation('Location index mismatch')
                if obj.owner in self._departed and obj.zone!=Zone.OUTSIDE:raise RulesViolation('Departed owner still has an in-game object')
                if obj.controller not in self.players or type(obj.controlled_since) is not int or not 0<=obj.controlled_since<=self._sequence:raise RulesViolation('Invalid continuous-control history')
                if type(obj.damage_marked) is not int or obj.damage_marked<0 or type(obj.deathtouch_hit) is not bool or type(obj.combat_departure) is not int or not 0<=obj.combat_departure<=self._sequence:raise RulesViolation('Invalid damage/combat history')
                if (not isinstance(obj.counters,tuple) or any(not isinstance(row,tuple) or len(row)!=2 or type(row[0]) is not str or not row[0] or type(row[1]) is not int or row[1]<=0 for row in obj.counters)
                        or len({row[0] for row in obj.counters})!=len(obj.counters)):raise RulesViolation('Invalid object counter ledger')
                seen.append(card_id)
        if len(seen)!=len(set(seen)) or set(seen)!=set(self._objects):raise RulesViolation('Physical card location is not unique')
        if not set(self._objects)<=self._issued:raise RulesViolation('Unissued object identity')
        if self._physical!={obj.ref.card_id for obj in self._objects.values() if not obj.token}:raise RulesViolation('Physical card conservation failed')

    def snapshot(self):
        return {'schema':self.CHECKPOINT_SCHEMA,'starting_life':dict(self._starting_life),'commander_identities':None if self._commander_identities is None else {p:list(c) for p,c in self._commander_identities.items()},'players':list(self.players),'objects':[o.to_json() for o in self._objects.values()],
            'order':[{'owner':p,'zone':z.value,'ids':list(ids)} for (p,z),ids in self._order.items()],
            'physical':sorted(self._physical),'issued':sorted(self._issued),'sequence':self._sequence,'batch':self._batch,
            'events':[e.to_json() for e in self._events],'life':dict(self._life),
            'player_counters':{p:dict(c) for p,c in self._player_counters.items()},'command_casts':dict(self._command_casts),'commander_casts':dict(self._commander_casts),
            'mana':{player:dict(pool) for player,pool in self._mana.items()},
            'turn_starts':dict(self._turn_starts),'turn_number':self._turn_number,'turn_active':self._turn_active,
            'commander_damage':[{'player':player,'card_id':card,'amount':amount} for (player,card),amount in sorted(self._commander_damage.items())],
            'shuffle_seed':self._shuffle_seed,'shuffle_nonce':self._shuffle_nonce,
            'departed':sorted(self._departed),'failed_draws':sorted(self._failed_draws),
            'control_bases':dict(self._control_bases),
            'control_effects':{key:{**row,'ref':row['ref'].to_json()} for key,row in self._control_effects.items()}}

    @classmethod
    def restore(cls,value):
        if value.get('schema')!=cls.CHECKPOINT_SCHEMA:raise RulesViolation('Unknown state schema')
        state=cls(value['players'],commander_identities=value['commander_identities'],starting_life=value.get('starting_life'));objects=[RulesObject.from_json(o) for o in value['objects']]
        if len({o.ref.card_id for o in objects})!=len(objects):raise RulesViolation('Duplicate restored identity')
        state._objects={o.ref.card_id:o for o in objects}
        state._order={(r['owner'],Zone(r['zone'])):list(r['ids']) for r in value['order']}
        if len(state._order)!=len(value['order']) or set(state._order)!={(p,z) for p in state.players for z in Zone}:raise RulesViolation('Invalid restored zone index')
        state._issued=set(value['issued'])
        state._physical=set(value['physical']);state._sequence=value['sequence'];state._batch=value['batch']
        state._life=dict(value['life']);state._player_counters={p:dict(c) for p,c in value['player_counters'].items()};state._command_casts=dict(value['command_casts'])
        state._commander_casts=dict(value['commander_casts']);state._mana={player:dict(pool) for player,pool in value['mana'].items()}
        state._turn_starts=dict(value['turn_starts']);state._turn_number=value['turn_number'];state._turn_active=value['turn_active']
        state._commander_damage={(row['player'],row['card_id']):row['amount'] for row in value['commander_damage']}
        state._shuffle_seed=value['shuffle_seed'];state._shuffle_nonce=value['shuffle_nonce']
        state._departed=set(value['departed']);state._failed_draws=set(value['failed_draws'])
        state._control_bases=dict(value['control_bases'])
        state._control_effects={key:{**row,'ref':ObjectRef.from_json(row['ref'])} for key,row in value['control_effects'].items()}
        if len(state._commander_damage)!=len(value['commander_damage']):raise RulesViolation('Duplicate commander damage ledger entry')
        state._events=[ZoneEvent(e['sequence'],e['batch'],e['cause'],RulesObject.from_json(e['before']),RulesObject.from_json(e['after'])) for e in value['events']]
        state.assert_invariants();return state
