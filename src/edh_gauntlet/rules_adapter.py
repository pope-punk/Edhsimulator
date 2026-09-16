"""Seat-bound primitive commands and an internal deterministic replay journal.

The caller supplies the authenticated seat; command bodies cannot select one.
This adapter is not installed in a production host while admission is closed.
Replay archives contain private state and must never be delivered to a pilot.
"""
from copy import deepcopy
import hashlib
import json
from .rules_actor import project_actor,decision_for_actor,PUBLIC_ZONES
from .rules_state import PlayerRef,ObjectRef,Zone,RulesViolation
from .rules_casting import Payment
from .rules_kernel import RulesKernel
from .rules_identity import IMPLEMENTATION_ID
from .rules_program import encode


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


class AcceptedTransitionError(RuntimeError):
    """Execution failed after acceptance; preserve the prefix and stop dispatch."""


class RulesActorAdapter:
    def __init__(self,kernel):
        self.kernel=kernel
        self.initial=kernel.snapshot()
        self.records=[]
        self.chain=digest({'implementation':IMPLEMENTATION_ID,'initial':self.initial})
        self.failed=False

    @classmethod
    def for_production(cls,*args,**kwargs):
        from .rules_admission import require_production_ready
        require_production_ready()

    def packet(self,actor):
        packet=project_actor(self.kernel,actor)
        if self.failed:packet['decision']={'kind':'engine_stopped'}
        return packet

    def inspect(self,actor,query):
        """Read visible rules without exporting a checkpoint or reserving an action.

        Programs describe available vocabulary, not an assertion that an action
        is legal now. The ordinary atomic submission still validates timing,
        targets, costs and the exact revision.
        """
        if self.failed:raise AcceptedTransitionError('Adapter stopped after an accepted execution failure')
        if actor not in self.kernel.state.live_players:raise RulesViolation('Unavailable actor')
        if type(query) is not dict or set(query)!={'kind','source'} or query['kind']!='card_rules':
            raise RulesViolation('Unsupported inspection request')
        ref=self._visible_ref(query['source'],actor)
        obj=self.kernel.state.get(ref)
        return {'kind':'card_rules','actor':actor,'revision':self.kernel.revision,
                'source':ref.to_json(),'program':encode(self.kernel.definition(obj)),
                'activated_abilities':encode(self.kernel.activated_abilities(obj)),
                'legality':'Submission validates current timing, targets and payment.'}

    def _visible_ref(self,value,actor):
        try:ref=ObjectRef.from_json(value)
        except (TypeError,KeyError,ValueError) as exc:raise RulesViolation('Invalid object reference') from exc
        # Direct lookup is O(1); hidden and nonexistent identities have the same
        # external rejection. Never return details from the failed lookup.
        try:obj=self.kernel.state.get(ref)
        except RulesViolation:raise RulesViolation('Object reference is not visible to this actor') from None
        top=self.kernel._visible_library_top(obj.owner,actor) if obj.zone==Zone.LIBRARY else None
        if obj.zone not in (*PUBLIC_ZONES,Zone.STACK) and not (top is not None and top.ref==ref) and not (obj.zone==Zone.HAND and (obj.owner==actor or ref in {o.ref for o in self.kernel.revealed_ability_sources()})):
            raise RulesViolation('Object reference is not visible to this actor')
        return ref

    def _visible_target(self,value,actor):
        if type(value) is dict and 'player' in value:
            ref=PlayerRef.from_json(value)
            if ref.player not in self.kernel.state.live_players:raise RulesViolation('Unavailable player target')
            return ref
        return self._visible_ref(value,actor)

    def _execute(self,actor,command):
        if type(command) is not dict or type(command.get('kind')) is not str:
            raise RulesViolation('Invalid actor command')
        kind=command['kind']
        required={'adjudicated_combo':{'action_id','response'},'answer':{'request_id','indexes'},'allocate_counters':{'request_id','allocations'},'pass':set(),'concede':set(),
            'decline_cast':{'action_id','request_id'},
            'pay_mana':{'action_id','request_id','payment'},
            'cast':{'action_id','source','targets','x_value','payment'},
            'activate':{'action_id','source','targets','x_value','payment','ability_id'},
            'unlock_room':{'action_id','source','door','payment'},'play_land':{'action_id','source'},'attack':{'attackers'},
            'block':{'assignments'},'damage':{'assignments'}}
        optional={'face','modes','alternative_id','counter_division','kicker','replicate','life_costs','hybrid_choices'} if kind=='cast' else {'counter_division'} if kind=='activate' else {'payment'} if kind=='attack' else {'face'} if kind=='play_land' else set()
        if kind not in required or set(command)-optional!={'kind','revision',*required[kind]}:
            raise RulesViolation('Unsupported command or unexpected command fields')
        if command['revision']!=self.kernel.revision:raise RulesViolation('Stale actor command')
        decision=decision_for_actor(self.kernel,actor)['kind']
        expected={'adjudicated_combo':'priority','answer':'choice','allocate_counters':'choice','pass':'priority','concede':'priority','cast':'priority','activate':'priority','pay_mana':'mana_payment','decline_cast':'resolution_cast',
                  'unlock_room':'priority','play_land':'priority','attack':'declare_attackers','block':'declare_blockers','damage':'combat_damage'}
        if decision!=expected[kind] and not (kind=='activate' and decision in {'mana_payment','casting_mana'} or kind=='cast' and decision=='resolution_cast'):
            raise RulesViolation('Actor does not own this decision stage')
        k=self.kernel
        if kind=='adjudicated_combo':
            from .rules_combo import apply
            return apply(k,actor,command)
        if kind=='answer':return k.answer(command['request_id'],actor,command['indexes'])
        if kind=='allocate_counters':return k.allocate_counters(command['request_id'],actor,command['allocations'])
        if kind=='decline_cast':return k.decline_resolution_cast(command['action_id'],actor,command['request_id'],revision=command['revision'])
        if kind=='pass':return k.pass_priority(actor)
        if kind=='concede':return k.concede_at_priority(actor)
        if kind=='pay_mana':
            try:payment=None if command['payment'] is None else Payment.from_json(command['payment'])
            except (TypeError,KeyError,ValueError) as exc:raise RulesViolation('Invalid resolution payment') from exc
            if payment is not None and payment.mana_actions:
                from .primitive_autotap import commit_resolution_payment
                return commit_resolution_payment(k,actor,command,payment)
            return k.pay_resolution_mana(command['action_id'],actor,command['request_id'],payment,revision=command['revision'])
        if kind in {'cast','activate'}:
            source=self._visible_ref(command['source'],actor)
            if type(command['targets']) is not list:raise RulesViolation('Invalid targets')
            targets=tuple(self._visible_target(row,actor) for row in command['targets'])
            try:payment=Payment.from_json(command['payment'])
            except (TypeError,KeyError,ValueError) as exc:raise RulesViolation('Invalid payment') from exc
            for ref in payment.taps:self._visible_ref(ref.to_json(),actor)
            for ref,color in payment.convoke:self._visible_ref(ref.to_json(),actor)
            for _,refs in payment.zone_costs:
                for ref in refs:self._visible_ref(ref.to_json(),actor)
            modes=command.get('modes',[])
            if type(modes) is not list or any(type(row) is not dict or set(row)!={'mode_id','targets'}
                    or type(row['targets']) is not list for row in modes):raise RulesViolation('Invalid modal choices')
            choices=tuple((row['mode_id'],tuple(self._visible_target(ref,actor) for ref in row['targets'])) for row in modes)
            division=command.get('counter_division',[])
            if type(division) is not list or any(type(row) is not dict or set(row)!={'ref','amount'} for row in division):
                raise RulesViolation('Invalid counter division')
            division=tuple((self._visible_ref(row['ref'],actor),row['amount']) for row in division)
            if kind=='cast':quote=k.quote_cast(command['action_id'],actor,source,targets,x_value=command['x_value'],mode_choices=choices,alternative_id=command.get('alternative_id'),counter_division=division,kicker=command.get('kicker',False),replicate=command.get('replicate',0),life_costs=tuple(command.get('life_costs',())),hybrid_choices=tuple(command.get('hybrid_choices',())),face=command.get('face'))
            else:quote=k.quote_activation(command['action_id'],actor,source,command['ability_id'],targets,x_value=command['x_value'],counter_division=division)
            return k.commit_action(quote,payment)
        if kind=='unlock_room':
            try:payment=Payment.from_json(command['payment'])
            except (TypeError,KeyError,ValueError) as exc:raise RulesViolation('Invalid unlock payment') from exc
            return k.unlock_room(command['action_id'],actor,self._visible_ref(command['source'],actor),command['door'],payment,revision=command['revision'])
        if kind=='play_land':return k.play_land(command['action_id'],actor,self._visible_ref(command['source'],actor),revision=command['revision'],face=command.get('face','front'))
        if kind=='attack':
            if type(command['attackers']) is not list:raise RulesViolation('Invalid attackers')
            attackers={}
            for row in command['attackers']:
                if type(row) is not dict or set(row)!={'source','defender'}:
                    raise RulesViolation('Invalid attack declaration')
                ref=self._visible_ref(row['source'],actor)
                if ref in attackers:raise RulesViolation('Duplicate attacker')
                destination=row['defender']
                if isinstance(destination,dict):destination=self._visible_ref(destination,actor)
                elif type(destination) is not str:raise RulesViolation('Invalid defending object or player')
                attackers[ref]=destination
            return k.declare_attackers(actor,attackers,revision=command['revision'],payment=Payment.from_json(command['payment']) if 'payment' in command else None)
        if kind=='block':return k.declare_blockers(actor,command['assignments'],revision=command['revision'])
        return k.assign_combat_damage(actor,command['assignments'],revision=command['revision'])

    def submit(self,actor,command):
        if self.failed:raise AcceptedTransitionError('Adapter stopped after an accepted execution failure')
        if actor not in self.kernel.state.live_players:raise RulesViolation('Unavailable actor')
        # A JSON round trip detaches caller-owned containers and rejects values
        # the actual transport cannot preserve. No model callback is involved.
        try:command=json.loads(json.dumps(command,allow_nan=False))
        except (TypeError,ValueError) as exc:raise RulesViolation('Command must be JSON data') from exc
        before=self.kernel.revision;accepted_before=(len(self.kernel.accepted),len(self.kernel.action_receipts));event_start=len(self.kernel.semantic_events);zone_start=self.kernel.state.event_count
        error=None
        try:self._execute(actor,command)
        except Exception as exc:
            if self.kernel.revision==before and accepted_before==(len(self.kernel.accepted),len(self.kernel.action_receipts)):raise
            error={'type':type(exc).__name__,'message':str(exc)};self.failed=True
        record={'actor':actor,'command':command,'before':before,'after':self.kernel.revision,
                'events_sha256':digest(self.kernel.semantic_events[event_start:]),
                'zones_sha256':digest([event.to_json() for event in self.kernel.state.events_since(zone_start)]),
                'error':error,'previous':self.chain}
        self.chain=digest(record);self.records.append({**record,'sha256':self.chain})
        if error:raise AcceptedTransitionError('Accepted execution failed; preserve this journal and stop dispatch')
        return self.packet(actor)

    def archive(self):
        return {'schema':1,'implementation':IMPLEMENTATION_ID,'initial':deepcopy(self.initial),
                'records':deepcopy(self.records),'chain':self.chain,'failed':self.failed,
                'final_sha256':digest(self.kernel.snapshot())}

    @classmethod
    def replay(cls,archive,definitions):
        if archive.get('schema')!=1 or archive.get('implementation')!=IMPLEMENTATION_ID:
            raise RulesViolation('Incompatible replay archive')
        adapter=cls(RulesKernel.restore(archive['initial'],definitions))
        for expected in archive['records']:
            try:adapter.submit(expected['actor'],expected['command'])
            except AcceptedTransitionError:
                if not expected['error']:raise RulesViolation('Replay failed unexpectedly')
            if not adapter.records or adapter.records[-1]!=expected:raise RulesViolation('Replay prefix mismatch')
        if adapter.archive()!=archive:raise RulesViolation('Replay final state mismatch')
        return adapter
