"""Read-only action quotes and atomic resource-payment commits.

This experimental slice uses already-produced, unrestricted mana and one atomic
activation zone-cost group or fixed source-counter costs. Casting zone costs, separately ordered activation
cost groups, alternative costs, restricted mana and mana during announcement
remain unsupported. Life payments reach the shared loss boundary. Creature readiness and basic land
mana use shared turn-history and characteristic rules.
"""
from collections import Counter, deque
from dataclasses import dataclass, replace
from .rules_state import PlayerRef,target_from_json,ObjectRef, Zone, ZoneMove, RulesViolation, ResourcePayment, RulesObject
from .rules_program import ChosenX, ManaCost, CostSpec, ActivatedProgram, AddMana, ChooseMana, ChooseCommanderMana, Move, encode, decode, immediate_effect_nodes
from .rules_characteristics import base, matches
from .rules_identity import IMPLEMENTATION_ID
from .rules_modal import prepare_modal


def _mana_symbols_satisfied(symbols,paid):
    """Match fixed and two-color hybrid pips against unrestricted paid mana."""
    remaining=dict(paid);hybrids=Counter()
    for symbol,amount in Counter(symbols).items():
        if '/' in symbol:hybrids['/'.join(sorted(symbol.split('/')))]+=amount
        else:
            if remaining.get(symbol,0)<amount:return False
            remaining[symbol]=remaining.get(symbol,0)-amount
    if not hybrids:return True
    # Aggregate identical hybrid pips. A tiny residual network handles overlap
    # without enumerating color choices or expanding repeated symbols.
    edges={};capacity={}
    def edge(a,b,n):
        edges.setdefault(a,[]).append(b);edges.setdefault(b,[]).append(a)
        capacity[a,b]=n;capacity[b,a]=0
    need=sum(hybrids.values());flow=0
    for pair,n in hybrids.items():
        edge('cost',pair,n)
        for color in pair.split('/'):edge(pair,color,n)
    for color in 'WUBRG':edge(color,'paid',remaining.get(color,0))
    while flow<need:
        parents={'cost':None};queue=deque(('cost',))
        while queue and 'paid' not in parents:
            a=queue.popleft()
            for b in edges.get(a,()):
                if b not in parents and capacity[a,b]>0:parents[b]=a;queue.append(b)
        if 'paid' not in parents:return False
        amount=need-flow;b='paid'
        while parents[b] is not None:
            a=parents[b];amount=min(amount,capacity[a,b]);b=a
        b='paid'
        while parents[b] is not None:
            a=parents[b];capacity[a,b]-=amount;capacity[b,a]+=amount;b=a
        flow+=amount
    return True


@dataclass(frozen=True)
class PreparedAction:
    action_id: str
    kind: str
    actor: str
    source: ObjectRef
    targets: tuple[ObjectRef | PlayerRef, ...]
    ability_id: str | None
    x_value: int
    revision: str
    bundle: str
    implementation: str
    cost: object
    mode_choices: tuple = ()

    def to_json(self):
        return {'action_id': self.action_id, 'kind': self.kind, 'actor': self.actor,
            'source': self.source.to_json(), 'targets': [ref.to_json() for ref in self.targets],
            'ability_id': self.ability_id, 'x_value': self.x_value, 'revision': self.revision,
            'bundle': self.bundle, 'implementation': self.implementation, 'cost': encode(self.cost),
            'mode_choices':[{'mode_id':key,'targets':[ref.to_json() for ref in targets]} for key,targets in self.mode_choices]}

    @classmethod
    def from_json(cls, value):
        value = dict(value)
        value['source'] = ObjectRef.from_json(value['source'])
        value['targets'] = tuple(target_from_json(ref) for ref in value['targets'])
        value['cost'] = decode(value['cost'])
        value['mode_choices']=tuple((row['mode_id'],tuple(target_from_json(ref) for ref in row['targets'])) for row in value.get('mode_choices',[]))
        return cls(**value)


@dataclass(frozen=True)
class Payment:
    mana: tuple[tuple[str, int], ...] = ()
    taps: tuple[ObjectRef, ...] = ()
    zone_costs: tuple = ()

    @classmethod
    def from_json(cls, value):
        if not {'mana','taps'}<=set(value) or set(value)-{'mana','taps','zone_costs'} or not isinstance(value['mana'], dict) or not isinstance(value.get('zone_costs',{}),dict):
            raise RulesViolation('Invalid payment packet')
        return cls(tuple(sorted(value['mana'].items())), tuple(ObjectRef.from_json(ref) for ref in value['taps']),
            tuple((key,tuple(ObjectRef.from_json(ref) for ref in refs)) for key,refs in sorted(value.get('zone_costs',{}).items())))


class CastingRules:
    def activated_abilities(self, source):
        """Basic land types confer mana abilities independently of printed text."""
        abilities = self.definition(source).activated
        view = self.effective(source.ref)
        if source.zone == Zone.BATTLEFIELD and 'Land' in view.types:
            intrinsic = tuple(ActivatedProgram('intrinsic-land:' + subtype, CostSpec(tap_source=True),
                (AddMana((symbol,)),), mana_ability=True)
                for subtype, symbol in (('Plains','W'),('Island','U'),('Swamp','B'),('Mountain','R'),('Forest','G'))
                if subtype in view.subtypes)
            abilities += intrinsic
        return abilities

    def open_window_for_scenario(self, active, phase='precombat_main', priority_actor=None):
        """Explicit test fixture boundary, not a production turn scheduler."""
        self._idle()
        if self.turn_schedule is not None:raise RulesViolation('A running turn cannot be replaced with a fixture window')
        if self.stack or active not in self.state.live_players or phase not in {'precombat_main', 'postcombat_main', 'upkeep'}:
            raise RulesViolation('Invalid scenario priority window')
        actor = priority_actor or active
        if actor not in self.state.live_players:
            raise RulesViolation('Unknown priority player')
        if self.phase != phase or self.active != active:
            self.state.empty_mana_pools()
        self.phase = phase
        self.active = active
        self.priority = actor
        self.passes = []
        self._event('scenario_priority_window', active=active, actor=actor, phase=phase)

    def _announcement_targets(self, source, actor, spec, targets, x_value=0):
        if not isinstance(targets, tuple) or any(not isinstance(ref, (ObjectRef,PlayerRef)) for ref in targets):
            raise RulesViolation('Targets must be a tuple of exact object or player references')
        if spec is None:
            if targets:
                raise RulesViolation('Action has no target specification')
            return
        minimum=x_value if isinstance(spec.minimum,ChosenX) else spec.minimum
        maximum=x_value if isinstance(spec.maximum,ChosenX) else spec.maximum
        if not minimum <= len(targets) <= maximum or len(set(targets)) != len(targets):raise RulesViolation('Illegal announced targets')
        if not targets:return
        legal = {o.ref if o.ref is not None else PlayerRef(o.player) for o in self._target_options(spec, {'source': source.to_json(), 'controller': actor})}
        if not set(targets)<=legal:raise RulesViolation('Illegal announced targets')
        if spec.group_by_controller and len({ref.player if isinstance(ref,PlayerRef) else self.state.get(ref).controller for ref in targets}) != len(targets):
            raise RulesViolation('More than one target in a controller group')

    def _prepare_action(self, action_id, kind, actor, ref, targets, ability_id, x_value, mode_choices=()):
        self._idle()
        if not isinstance(action_id, str) or not action_id or len(action_id) > 128:
            raise RulesViolation('Action requires a bounded nonempty identity')
        if action_id in self.action_receipts:
            raise RulesViolation('Action was already accepted')
        if actor not in self.state.live_players or self.priority != actor:
            raise RulesViolation('Actor does not hold priority')
        source = self.state.get(ref)
        program = self.definition(source)
        if kind == 'cast':
            if source.zone not in {Zone.HAND, Zone.COMMAND} or source.owner != actor:
                raise RulesViolation('Unsupported spell origin or permission')
            if source.zone == Zone.COMMAND and not source.commander:
                raise RulesViolation('Only a commander has this command-zone permission')
            if program.cast is None:
                raise RulesViolation('No reviewed casting specification for this fixture')
            specification = program.cast
            target_spec = program.spell_targets
        elif kind == 'activate':
            specification = next((ability for ability in self.activated_abilities(source) if ability.ability_id == ability_id), None)
            if specification is None:
                raise RulesViolation('Unknown activated ability')
            permitted_actor=source.controller if source.zone==Zone.BATTLEFIELD else source.owner
            if source.zone!=specification.zone or source.phased or permitted_actor!=actor:
                raise RulesViolation('Unavailable activated ability source')
            if any(isinstance(effect,ChooseCommanderMana) for effect in immediate_effect_nodes(specification.effects)):
                self.state.commander_identity(actor)
            target_spec = specification.targets
        else:
            raise RulesViolation('Unsupported action kind')
        if specification.timing == 'sorcery' and not (kind=='cast' and 'flash' in self.effective(ref).keywords) and (self.active != actor or self.phase not in {'precombat_main', 'postcombat_main'} or self.stack):
            raise RulesViolation('Action requires sorcery timing')
        cost = specification.cost
        if type(x_value) is not int or x_value < 0 or x_value and not cost.mana.x_symbols:
            raise RulesViolation('Invalid announced X')
        if kind=='activate' and x_value<specification.minimum_x:raise RulesViolation('Announced X is below the activation minimum')
        if not isinstance(mode_choices,tuple):raise RulesViolation('Mode choices must be immutable')
        modal=self.definition(source).modal if kind=='cast' else None
        if modal is not None:
            if targets:raise RulesViolation('Modal targets must be bound to their selected modes')
            mode_choices=prepare_modal(self,source,actor,modal,mode_choices,x_value=x_value)
        elif mode_choices:
            raise RulesViolation('Nonmodal action has no mode choices')
        self._announcement_targets(source, actor, target_spec, targets,x_value)
        if cost.life > self.state.life(actor):
            raise RulesViolation('Insufficient life for payment')
        if any(dict(source.counters).get(c.kind,0)<c.amount for c in cost.counter_costs):
            raise RulesViolation('Insufficient source counters for payment')
        if cost.tap_source:
            if source.tapped:
                raise RulesViolation('Source is already tapped')
            view = self.effective(ref)
            if 'Creature' in view.types and 'haste' not in view.keywords and not self.state.ready_since_turn_start(ref):
                raise RulesViolation('Creature has not been controlled since its controller’s turn began')
        generic = cost.mana.generic + cost.mana.x_symbols * x_value
        if kind == 'cast':
            if source.commander and source.zone == Zone.COMMAND:
                generic += 2 * self.state.commander_casts(ref.card_id)
            proposed = replace(source, zone=Zone.STACK, controller=actor, cast_x=x_value)
            proposed_view=base(proposed,self.definitions)
            generic-=self._quantity(self.definition(source).cast.generic_reduction,
                {'source':source.to_json(),'controller':actor})
            for permanent in self.state.objects(Zone.BATTLEFIELD):
                if permanent.phased:
                    continue
                for modifier in self.definition(permanent).cost_modifiers:
                    if matches(modifier.selector, proposed, proposed_view, permanent):
                        generic += modifier.generic_delta
        cost = replace(cost, mana=ManaCost(max(0, generic), cost.mana.symbols))
        return PreparedAction(action_id, kind, actor, ref, targets, ability_id, x_value,
                              self.revision, self.bundle, IMPLEMENTATION_ID, cost,mode_choices)

    def quote_cast(self, action_id, actor, source, targets=(), *, x_value=0, mode_choices=()):
        return self._prepare_action(action_id, 'cast', actor, source, targets, None, x_value,mode_choices)

    def quote_activation(self, action_id, actor, source, ability_id, targets=(), *, x_value=0):
        return self._prepare_action(action_id, 'activate', actor, source, targets, ability_id, x_value)

    def _resource_payment(self, quote, payment):
        if not isinstance(payment, Payment):
            raise RulesViolation('Payment must be an authored payment packet')
        source = self.state.get(quote.source)
        taps = payment.taps
        if not isinstance(taps, tuple) or any(not isinstance(ref, ObjectRef) for ref in taps) or len(taps) != quote.cost.tap_count:
            raise RulesViolation('Wrong number of tap-cost selections')
        if quote.cost.tap_selector:
            legal = {obj.ref for obj in self._query(quote.cost.tap_selector,
                {'source': source.to_json(), 'controller': quote.actor})}
            if not set(taps) <= legal:
                raise RulesViolation('Illegal tap-cost selection')
        if quote.cost.tap_source:
            taps = (quote.source,) + taps
        resources = ResourcePayment(quote.actor, payment.mana, quote.cost.life, taps,
            tuple((quote.source,c.kind,c.amount) for c in quote.cost.counter_costs))
        self.state.validate_payment(resources)
        paid = dict(payment.mana)
        if not _mana_symbols_satisfied(quote.cost.mana.symbols,paid):
            raise RulesViolation('Mana payment does not satisfy colored/colorless requirements')
        if sum(paid.values()) != quote.cost.mana.generic + len(quote.cost.mana.symbols):
            raise RulesViolation('Mana payment must match the total cost exactly')
        return resources

    def commit_action(self, quote, payment):
        if not isinstance(quote, PreparedAction):
            raise RulesViolation('Missing prepared action')
        if quote.action_id in self.action_receipts:
            raise RulesViolation('Action was already accepted')
        if quote.implementation != IMPLEMENTATION_ID or quote.bundle != self.bundle or quote.revision != self.revision:
            raise RulesViolation('Stale action quote or changed rules bundle')
        fresh = self._prepare_action(quote.action_id, quote.kind, quote.actor, quote.source,
                                     quote.targets, quote.ability_id, quote.x_value,quote.mode_choices)
        if fresh != quote:
            raise RulesViolation('Quote does not match the current declaration and cost')
        resources = self._resource_payment(quote, payment)
        zone_refs=self._zone_cost_refs(quote,payment)
        if quote.cost.zone_costs:
            source=self.state.get(quote.source)
            ability=next(a for a in self.activated_abilities(source) if a.ability_id==quote.ability_id)
            announced_frame=None
            if not ability.mana_ability:
                announced_frame=self._frame(source,quote.actor,ability.effects,targets=quote.targets,target_spec=ability.targets,chosen_x=quote.x_value)
                announced_frame['ability_id']=ability.ability_id;self.stack.append(announced_frame)
            self.announcement={'frame_id':announced_frame['id'] if announced_frame else None,'quote':quote.to_json(),'payment':{'mana':dict(payment.mana),'taps':[r.to_json() for r in payment.taps],
                'zone_costs':{key:[r.to_json() for r in refs] for key,refs in payment.zone_costs}},
                'source':source.to_json(),'source_types':sorted(self.effective(source.ref).types),'ability':encode(ability),
                'refs':[ref.to_json() for ref in zone_refs]}
            self._event('activation_announced',action_id=quote.action_id,actor=quote.actor)
            boundary=self.advance()
            if boundary is None and ability.mana_ability and quote.actor in self.state.live_players:self.priority=quote.actor
            return boundary
        mana_ability=self._commit_prepared(quote,resources)
        boundary=self.advance()
        if boundary is None and mana_ability and quote.actor in self.state.live_players:self.priority=quote.actor
        return boundary

    def _commit_prepared(self,quote,resources,*,paid=False,source=None,ability=None,zone_payment=None,previous_types=None,prepared_frame=None):
        source = source or self.state.get(quote.source)
        program = self.definition(source)
        immediate_mana=()
        if quote.kind == 'cast':
            events = self.state.move((ZoneMove(source.ref, Zone.STACK, quote.actor, cast_x=quote.x_value),),
                                     'cast', payment=resources)
            if source.commander and source.zone == Zone.COMMAND:
                self.state.record_command_cast(quote.actor, source.ref.card_id)
            source = events[0].after
            effects = program.spell_effects
            if not effects and not {'Instant', 'Sorcery'} & set(program.types):
                effects = (Move('source', Zone.BATTLEFIELD),)
            frame = self._frame(source, quote.actor, effects, spell=True, targets=quote.targets,
                                target_spec=program.spell_targets,chosen_x=quote.x_value)
            if program.modal is not None:
                selected=dict(quote.mode_choices)
                frame['mode_groups']=[];frame['tasks']=[];frame['targets']=[]
                for mode in program.modal.modes:
                    if mode.mode_id not in selected:continue
                    refs=[ref.to_json() for ref in selected[mode.mode_id]]
                    frame['mode_groups'].append({'mode_id':mode.mode_id,'targets':refs,'target_spec':encode(mode.targets)})
                    frame['targets'].extend(refs)
                    frame['tasks'].extend({'id':self._id('effect'),'effect':encode(effect),'mode_id':mode.mode_id,'bindings':{},'values':{}} for effect in mode.effects)
            self.stack.append(frame)
            event_kind = 'spell_cast'
            mana_ability = False
        else:
            ability = ability or next(ability for ability in self.activated_abilities(source) if ability.ability_id == quote.ability_id)
            if not paid:
                self.state.move((), 'activation_payment', payment=resources)
                source=self.state.get(quote.source)
            mana_ability = ability.mana_ability
            if mana_ability and not all(isinstance(effect,AddMana) for effect in ability.effects):
                frame=self._frame(source,quote.actor,ability.effects,chosen_x=quote.x_value)
                frame.update(ability_id=ability.ability_id,mana_ability=True,return_priority=quote.actor)
                self.resolving=frame
            elif mana_ability:
                immediate_mana=ability.effects
                frame = None
            else:
                frame = prepared_frame or self._frame(source, quote.actor, ability.effects, targets=quote.targets, target_spec=ability.targets,chosen_x=quote.x_value)
                frame['source']=source.to_json();frame['ability_id'] = ability.ability_id
                if prepared_frame is None:self.stack.append(frame)
            event_kind = 'ability_activated'
        receipt = {'action': quote.to_json(), 'payment': {'mana': dict(resources.mana), 'life': resources.life,
            'taps': [ref.to_json() for ref in resources.taps]}, 'frame': frame['id'] if frame else None,
            'mana_ability': mana_ability}
        if resources.counters:
            receipt['payment']['counters']=[{'source':ref.to_json(),'kind':kind,'amount':amount} for ref,kind,amount in resources.counters]
        if zone_payment is not None:receipt['payment']['zone_costs']=zone_payment
        self.action_receipts[quote.action_id] = receipt
        self._event('costs_paid', action_id=quote.action_id, **receipt['payment'])
        self._event(event_kind, action_id=quote.action_id, source=source.ref.to_json(), controller=quote.actor)
        self.priority = quote.actor
        self.passes = []
        self._collect_announcement(event_kind, source, quote.actor,previous_types=previous_types)
        for effect in immediate_mana:
            self.state.add_mana(quote.actor,effect.symbols)
            self._event('mana_added',player=quote.actor,symbols=list(effect.symbols))
        return mana_ability

    def _zone_cost_refs(self,quote,payment):
        try:selections=dict(payment.zone_costs)
        except (TypeError,ValueError) as exc:raise RulesViolation('Invalid zone-cost selections') from exc
        if len(selections)!=len(payment.zone_costs):raise RulesViolation('Duplicate zone-cost selection key')
        costs=quote.cost.zone_costs
        expected={cost.cost_id for cost in costs if cost.selector is not None}
        if set(selections)!=expected:raise RulesViolation('Zone-cost selections do not match the required costs')
        refs=[];source=self.state.get(quote.source)
        for cost in costs:
            chosen=selections[cost.cost_id] if cost.selector is not None else (quote.source,)
            if not isinstance(chosen,tuple) or len(chosen)!=cost.count or any(not isinstance(ref,ObjectRef) for ref in chosen) or len(set(chosen))!=len(chosen):
                raise RulesViolation('Wrong or duplicate zone-cost selections')
            legal={obj.ref for obj in self._query(cost.selector,{'source':source.to_json(),'controller':quote.actor})} if cost.selector else {quote.source}
            if not set(chosen)<=legal:raise RulesViolation('Illegal zone-cost selection')
            refs.extend(chosen)
        return tuple(refs)

    def _continue_announcement(self):
        pending=self.announcement;quote=PreparedAction.from_json(pending['quote']);payment=Payment.from_json(pending['payment'])
        resources=self._resource_payment(quote,payment);cost=quote.cost.zone_costs[0]
        source=RulesObject.from_json(pending['source']);ability=decode(pending['ability'])
        frame={'source':pending['source'],'controller':quote.actor,'bindings':{}}
        destination={'sacrifice':Zone.GRAVEYARD,'discard':Zone.GRAVEYARD,'exile':Zone.EXILE,'return':Zone.HAND}[cost.kind]
        events=self._move(tuple(ObjectRef.from_json(ref) for ref in pending['refs']),destination,frame,
            quote.action_id+':cost',cause=cost.kind,controller_mode='owner',payment=resources)
        source=next((event.before for event in events if event.before.ref==quote.source),source)
        prepared_frame=next((frame for frame in self.stack if frame['id']==pending['frame_id']),None)
        if not ability.mana_ability and prepared_frame is None:raise RulesViolation('Announced ability frame disappeared during payment')
        self.announcement=None
        self._commit_prepared(quote,resources,paid=True,source=source,ability=ability,
            zone_payment={cost.cost_id:pending['refs']},previous_types=pending['source_types'],prepared_frame=prepared_frame)

    def _collect_announcement(self, kind, announced, actor,*,previous_types=None,values=None):
        observers = list(self.state.objects(Zone.BATTLEFIELD))
        if kind == 'spell_cast':
            observers.append(announced)
        types=None
        for source in observers:
            if source.phased:
                continue
            for ability in self.definition(source).abilities:
                pattern = ability.event
                if source.zone == Zone.STACK and pattern.subject != 'self':
                    continue
                if pattern.kind != kind or pattern.subject == 'self' and source.ref != announced.ref:
                    continue
                if pattern.controller_only and source.controller != actor:
                    continue
                if pattern.types:
                    if types is None:
                        try:types=self.effective(announced.ref).types
                        except RulesViolation:types=set(previous_types) if previous_types is not None else self._damage_source(announced)[1].types
                    if not set(pattern.types) <= types:continue
                self._trigger(source, ability, values={"event_x":announced.cast_x} if kind=="spell_cast" else values)
