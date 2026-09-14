"""Read-only action quotes and atomic resource-payment commits.

This experimental slice uses already-produced, unrestricted mana and one atomic
activation zone-cost group or fixed source-counter costs. Spells may pay one
selected sacrifice group plus fixed/variable unrestricted mana, or a graveyard
alternative with one selected exile group and fixed unrestricted mana. Separately ordered
cost groups, restricted mana and mana during announcement remain unsupported.
Fixed alternative costs may carry entry facts; their consequences compose ordinary triggers. Life payments reach the shared loss boundary. Creature readiness and basic land
mana use shared turn-history and characteristic rules.
"""
from collections import Counter, deque
from dataclasses import dataclass, replace
from .rules_state import PlayerRef,target_from_json,ObjectRef, Zone, ZoneMove, RulesViolation, ResourcePayment, RulesObject
from .rules_choices import ManaPaymentBoundary
from .rules_program import ConvokeCast,IfQuantityAtLeast,MovedCount,KickerCast,CleanupCast,ColoredSpellEvent,WithZoneResult,DelayedNextStep,EventPattern,Sacrifice,SpellEventPattern, division_spec, GraveyardAlternativeCost, EntryAlternativeCost, ACTOR_EVENTS, event_player_matches, ChosenX, ManaCost, CostSpec, ActivatedProgram, AddMana, ChooseMana, ChooseCommanderMana, Move, encode, decode, immediate_effect_nodes
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
    alternative_id: str | None = None
    counter_division: tuple = ()
    kicker: bool = False

    def to_json(self):
        return {'action_id': self.action_id, 'kind': self.kind, 'actor': self.actor,
            'source': self.source.to_json(), 'targets': [ref.to_json() for ref in self.targets],
            'ability_id': self.ability_id, 'x_value': self.x_value, 'revision': self.revision,
            'bundle': self.bundle, 'implementation': self.implementation, 'cost': encode(self.cost),
            'counter_division':[{'ref':ref.to_json(),'amount':amount} for ref,amount in self.counter_division],
            'kicker':self.kicker,'alternative_id':self.alternative_id,'mode_choices':[{'mode_id':key,'targets':[ref.to_json() for ref in targets]} for key,targets in self.mode_choices]}

    @classmethod
    def from_json(cls, value):
        value = dict(value)
        value['source'] = ObjectRef.from_json(value['source'])
        value['targets'] = tuple(target_from_json(ref) for ref in value['targets'])
        value['cost'] = decode(value['cost'])
        value['counter_division']=tuple((ObjectRef.from_json(row['ref']),row['amount']) for row in value.get('counter_division',[]))
        value['mode_choices']=tuple((row['mode_id'],tuple(target_from_json(ref) for ref in row['targets'])) for row in value.get('mode_choices',[]))
        return cls(**value)


@dataclass(frozen=True)
class Payment:
    mana: tuple[tuple[str, int], ...] = ()
    taps: tuple[ObjectRef, ...] = ()
    zone_costs: tuple = ()
    convoke: tuple = ()

    def to_json(self):
        result={'mana':dict(self.mana),'taps':[ref.to_json() for ref in self.taps],
            'zone_costs':{key:[ref.to_json() for ref in refs] for key,refs in self.zone_costs}}
        if self.convoke:result['convoke']=[{'ref':ref.to_json(),'color':color} for ref,color in self.convoke]
        return result

    @classmethod
    def from_json(cls, value):
        if (not isinstance(value,dict) or not {'mana','taps'}<=set(value) or set(value)-{'mana','taps','zone_costs','convoke'}
                or not isinstance(value['mana'],dict) or not isinstance(value.get('zone_costs',{}),dict)
                or not isinstance(value.get('convoke',[]),list)
                or any(not isinstance(row,dict) or set(row)!={'ref','color'} for row in value.get('convoke',[]))):
            raise RulesViolation('Invalid payment packet')
        return cls(tuple(sorted(value['mana'].items())), tuple(ObjectRef.from_json(ref) for ref in value['taps']),
            tuple((key,tuple(ObjectRef.from_json(ref) for ref in refs)) for key,refs in sorted(value.get('zone_costs',{}).items())),
            tuple((ObjectRef.from_json(row['ref']),row['color']) for row in value.get('convoke',[])))


class CastingRules:
    def _payment_waiting(self):
        window=self.mana_payment
        return bool(window and not window['completed'] and not self.pending_choice and not self.announcement
            and self.resolving is not None and self.resolving['id']==window['parent']['id'])

    def _payment_boundary(self):
        window=self.mana_payment
        return ManaPaymentBoundary(window['actor'],window['id'],encode(decode(window['mana'])),self.revision)

    def pay_resolution_mana(self,action_id,actor,request_id,payment,*,revision):
        """Commit exactly one authored pay/decline after any immediate mana abilities."""
        if not self._payment_waiting():raise RulesViolation('No resolution payment is awaiting an answer')
        window=self.mana_payment
        if (revision!=self.revision or request_id!=window['id'] or actor!=window['actor']
                or actor not in self.state.live_players):raise RulesViolation('Stale or unauthorized resolution payment')
        if type(action_id) is not str or not action_id or len(action_id)>128 or action_id in self.action_receipts:
            raise RulesViolation('Resolution payment requires a fresh bounded action identity')
        resources=None
        if payment is not None:
            if not isinstance(payment,Payment) or payment.taps!=() or payment.zone_costs!=() or payment.convoke!=():
                raise RulesViolation('Resolution payment accepts mana only')
            resources=ResourcePayment(actor,payment.mana)
            self.state.validate_payment(resources)
            cost=decode(window['mana']);paid=dict(payment.mana)
            if (not _mana_symbols_satisfied(cost.symbols,paid)
                    or sum(paid.values())!=cost.generic+len(cost.symbols)):
                raise RulesViolation('Resolution payment must match the fixed mana cost exactly')
        # All preconditions precede the sole resource mutation.
        if resources is not None:self.state.move((),'resolution_payment',payment=resources)
        window['completed']=True;window['paid']=resources is not None
        receipt={'request_id':request_id,'actor':actor,'paid':window['paid'],
                 'mana':dict(resources.mana) if resources is not None else {}}
        self.action_receipts[action_id]=receipt
        self._event('resolution_payment_completed',action_id=action_id,**receipt)
        return self.advance()

    def activated_abilities(self, source):
        """Basic land types confer mana abilities independently of printed text."""
        abilities = self.definition(source).activated
        view = self.effective(source.ref)
        if source.zone == Zone.BATTLEFIELD:abilities+=view.granted_abilities
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
        maximum=x_value if isinstance(spec.maximum,ChosenX) else len(self.state.live_players) if spec.maximum is None else spec.maximum
        if not minimum <= len(targets) <= maximum or len(set(targets)) != len(targets):raise RulesViolation('Illegal announced targets')
        if not targets:return
        legal = {o.ref if o.ref is not None else PlayerRef(o.player) for o in self._target_options(spec, {'source': source.to_json(), 'controller': actor, 'chosen_x': x_value})}
        if not set(targets)<=legal:raise RulesViolation('Illegal announced targets')
        if spec.group_by_controller and len({ref.player if isinstance(ref,PlayerRef) else self.state.get(ref).controller for ref in targets}) != len(targets):
            raise RulesViolation('More than one target in a controller group')

    def _prepare_action(self, action_id, kind, actor, ref, targets, ability_id, x_value, mode_choices=(),alternative_id=None,counter_division=(),kicker=False):
        resolution_mana=kind=='activate' and self._payment_waiting()
        if not resolution_mana:self._idle()
        if not isinstance(action_id, str) or not action_id or len(action_id) > 128:
            raise RulesViolation('Action requires a bounded nonempty identity')
        if action_id in self.action_receipts:
            raise RulesViolation('Action was already accepted')
        owner=self.mana_payment['actor'] if resolution_mana else self.priority
        if actor not in self.state.live_players or owner != actor:
            raise RulesViolation('Actor does not own the action window')
        source = self.state.get(ref)
        program = self.definition(source)
        if kind == 'cast':
            alternative=next((a for a in program.cast.alternatives if a.alternative_id==alternative_id),None) if program.cast else None
            origins=(Zone.GRAVEYARD,) if isinstance(alternative,GraveyardAlternativeCost) else program.cast.origin_zones if program.cast else ()
            if program.cast is None or source.zone not in origins or source.owner != actor:
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
            if resolution_mana and (not specification.mana_ability or specification.timing!='instant'):
                raise RulesViolation('Only mana abilities are available during a resolution payment')
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
        if type(kicker) is not bool or kicker and (kind!='cast' or not isinstance(specification,KickerCast)):
            raise RulesViolation('Invalid kicker declaration')
        cost = specification.cost
        if alternative_id is not None:
            if kind!='cast' or type(alternative_id) is not str:raise RulesViolation('Invalid alternative casting declaration')
            alternative=next((a for a in specification.alternatives if a.alternative_id==alternative_id),None)
            if alternative is None or not self._condition_holds(alternative.condition,replace(source,controller=actor)):
                raise RulesViolation('Alternative casting cost is unavailable')
            cost=alternative.cost
        if kicker:
            extra=specification.kicker.mana
            cost=replace(cost,mana=ManaCost(cost.mana.generic+extra.generic,
                cost.mana.symbols+extra.symbols,cost.mana.x_symbols))
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
        effect_nodes=program.spell_effects if kind=='cast' else specification.effects
        division=division_spec(effect_nodes,target_spec)
        if not isinstance(counter_division,tuple):raise RulesViolation('Counter division must be immutable')
        if division is None:
            if counter_division:raise RulesViolation('Action has no counter division')
        else:
            if (any(not isinstance(row,tuple) or len(row)!=2 or not isinstance(row[0],ObjectRef)
                    or type(row[1]) is not int or row[1]<=0 for row in counter_division)
                    or len(counter_division)!=len(targets)
                    or len({row[0] for row in counter_division})!=len(counter_division)
                    or {row[0] for row in counter_division}!=set(targets)
                    or sum(row[1] for row in counter_division)!=division.amount):
                raise RulesViolation('Counter division must assign the fixed total positively across every target')
            amounts=dict(counter_division)
            counter_division=tuple((target,amounts[target]) for target in targets)
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
        generic-=self._quantity(specification.generic_reduction,{'source':source.to_json(),'controller':actor})
        if kind == 'cast':
            if source.commander and source.zone == Zone.COMMAND:
                generic += 2 * self.state.commander_casts(ref.card_id)
            proposed = replace(source, zone=Zone.STACK, controller=actor, cast_x=x_value)
            proposed_view=base(proposed,self.definitions)
            for permanent in self.state.objects(Zone.BATTLEFIELD):
                if permanent.phased:
                    continue
                for restriction in self.definition(permanent).casting_restrictions:
                    if source.zone in restriction.origin_zones and matches(restriction.selector,proposed,proposed_view,permanent):
                        raise RulesViolation('A battlefield effect prohibits this spell from its origin zone')
                for modifier in self.definition(permanent).cost_modifiers:
                    if (not modifier.origin_zones or source.zone in modifier.origin_zones) and matches(modifier.selector, proposed, proposed_view, permanent):
                        generic += modifier.generic_delta
        cost = replace(cost, mana=ManaCost(max(0, generic), cost.mana.symbols))
        return PreparedAction(action_id, kind, actor, ref, targets, ability_id, x_value,
                              self.revision, self.bundle, IMPLEMENTATION_ID, cost,mode_choices,alternative_id,counter_division,kicker)

    def quote_cast(self, action_id, actor, source, targets=(), *, x_value=0, mode_choices=(),alternative_id=None,counter_division=(),kicker=False):
        return self._prepare_action(action_id, 'cast', actor, source, targets, None, x_value,mode_choices,alternative_id,counter_division,kicker)

    def quote_activation(self, action_id, actor, source, ability_id, targets=(), *, x_value=0,counter_division=()):
        return self._prepare_action(action_id, 'activate', actor, source, targets, ability_id, x_value,counter_division=counter_division)

    def _resource_payment(self, quote, payment, *, source=None):
        if not isinstance(payment, Payment):
            raise RulesViolation('Payment must be an authored payment packet')
        source = source or self.state.get(quote.source)
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
        convoked,colors=self._convoke_contributions(quote,payment,source)
        taps+=convoked
        resources = ResourcePayment(quote.actor, payment.mana, quote.cost.life, taps,
            tuple((quote.source,c.kind,c.amount) for c in quote.cost.counter_costs))
        self.state.validate_payment(resources)
        paid = dict(payment.mana)
        for color,amount in colors.items():paid[color]=paid.get(color,0)+amount
        if not _mana_symbols_satisfied(quote.cost.mana.symbols,paid):
            raise RulesViolation('Mana payment does not satisfy colored/colorless requirements')
        if sum(dict(payment.mana).values())+len(payment.convoke) != quote.cost.mana.generic + len(quote.cost.mana.symbols):
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
                                     quote.targets, quote.ability_id, quote.x_value,quote.mode_choices,quote.alternative_id,quote.counter_division,quote.kicker)
        if fresh != quote:
            raise RulesViolation('Quote does not match the current declaration and cost')
        resources = self._resource_payment(quote, payment)
        zone_refs=self._zone_cost_refs(quote,payment)
        if quote.cost.zone_costs:
            source=self.state.get(quote.source);origin_source=source
            ability=None;announced_frame=None
            if quote.kind=='cast':
                # The announced spell is public on the stack throughout payment.
                # Validate the complete declaration/payment before this first mutation.
                source=self.state.move((ZoneMove(source.ref,Zone.STACK,quote.actor,cast_x=quote.x_value),),'spell_announced')[0].after
                announced_frame=self._spell_frame(source,quote)
            else:
                ability=next(a for a in self.activated_abilities(source) if a.ability_id==quote.ability_id)
                if not ability.mana_ability:
                    announced_frame=self._frame(source,quote.actor,ability.effects,targets=quote.targets,target_spec=ability.targets,chosen_x=quote.x_value)
                    announced_frame['ability_id']=ability.ability_id
            if announced_frame is not None:
                self._bind_announced_values(announced_frame,quote)
                self.stack.append(announced_frame)
            self.announcement={'frame_id':announced_frame['id'] if announced_frame else None,'quote':quote.to_json(),'payment':payment.to_json(),
                'source':source.to_json(),'origin_source':origin_source.to_json(),
                'source_types':sorted(self.effective(source.ref).types),'ability':encode(ability),
                'refs':[ref.to_json() for ref in zone_refs]}
            self._event('spell_announced' if quote.kind=='cast' else 'activation_announced',action_id=quote.action_id,actor=quote.actor)
            boundary=self.advance()
            if boundary is None and ability is not None and ability.mana_ability and quote.actor in self.state.live_players:self.priority=quote.actor
            return boundary
        mana_ability=self._commit_prepared(quote,resources,convoke=payment.convoke)
        boundary=self.advance()
        if boundary is None and mana_ability and quote.actor in self.state.live_players:self.priority=quote.actor
        return boundary

    def _produce_mana(self,player,symbols,*,tapped_for_mana=False):
        symbols=self._mana_after_replacements(player,symbols,tapped_for_mana=tapped_for_mana)
        self.state.add_mana(player,symbols)
        self._event('mana_added',player=player,symbols=list(symbols))

    def revealed_ability_sources(self):
        """Only current hand incarnations revealed by live announced abilities."""
        frames=list(self.stack)
        if self.resolving:frames.append(self.resolving)
        if self.mana_payment:frames.append(self.mana_payment['parent'])
        result={}
        for frame in frames:
            value=frame.get('announced_source')
            if value is None:continue
            try:source=self.state.get(ObjectRef.from_json(value['ref']))
            except RulesViolation:continue
            if source.zone==Zone.HAND:result[source.ref]=source
        return tuple(result.values())

    def _bind_announced_values(self,frame,quote):
        if quote.kind=='activate' and frame['source']['zone']==Zone.HAND.value:
            frame['announced_source']=dict(frame['source'])
        if quote.counter_division:
            frame['values']['counter_division']=[{'ref':ref.to_json(),'amount':amount} for ref,amount in quote.counter_division]

    def _spell_frame(self,source,quote):
        program=self.definition(source)
        effects = program.spell_effects
        if not effects and not {'Instant', 'Sorcery'} & set(program.types):
            effects = (Move('source', Zone.BATTLEFIELD),)
        sorcery_timing=self.active==quote.actor and self.phase in {'precombat_main','postcombat_main'} and not self.stack
        if isinstance(program.cast,CleanupCast) and not sorcery_timing:
            effects=(WithZoneResult(Move('source',Zone.BATTLEFIELD),Zone.BATTLEFIELD,(
                IfQuantityAtLeast(MovedCount(),1,(
                    DelayedNextStep(EventPattern('step_began',step='cleanup'),
                        (Sacrifice('moved',by_subject_controller=True),)),)),)),)
        frame = self._frame(source, quote.actor, effects, spell=True, targets=quote.targets,
                            target_spec=program.spell_targets,chosen_x=quote.x_value)
        self._bind_announced_values(frame,quote)
        if quote.alternative_id is not None:
            frame['alternative_id']=quote.alternative_id
            alternative=next(a for a in program.cast.alternatives if a.alternative_id==quote.alternative_id)
            if isinstance(alternative,(EntryAlternativeCost,GraveyardAlternativeCost)):
                frame['entry_flags']=list(alternative.entry_flags)
            if isinstance(alternative,GraveyardAlternativeCost) and alternative.exile_on_stack_exit:
                frame['exile_on_stack_exit']=True
        if isinstance(program.cast,CleanupCast):frame['cast_timing']='sorcery' if sorcery_timing else 'other'
        if isinstance(program.cast,KickerCast):
            frame['kicker']=quote.kicker
            if quote.kicker:frame['entry_flags']=list(dict.fromkeys(frame['entry_flags']+list(program.cast.entry_flags)))
        if program.modal is not None:
            selected=dict(quote.mode_choices)
            frame['mode_groups']=[];frame['tasks']=[];frame['targets']=[]
            for mode in program.modal.modes:
                if mode.mode_id not in selected:continue
                refs=[ref.to_json() for ref in selected[mode.mode_id]]
                frame['mode_groups'].append({'mode_id':mode.mode_id,'targets':refs,'target_spec':encode(mode.targets)})
                frame['targets'].extend(refs)
                frame['tasks'].extend({'id':self._id('effect'),'effect':encode(effect),'mode_id':mode.mode_id,'bindings':{},'values':{}} for effect in mode.effects)
        return frame

    def _commit_prepared(self,quote,resources,*,paid=False,source=None,ability=None,zone_payment=None,previous_types=None,prepared_frame=None,convoke=()):
        source = source or self.state.get(quote.source)
        immediate_mana=();tapped_for_mana=False
        tap_observers=self._tap_observers(resources.taps) if not paid else ()
        if quote.kind == 'cast':
            if paid:
                if prepared_frame is None:raise RulesViolation('Missing announced spell frame')
                frame=prepared_frame
                stack_source=self.state.get(ObjectRef.from_json(frame['source']['ref']))
            else:
                events=self.state.move((ZoneMove(source.ref,Zone.STACK,quote.actor,cast_x=quote.x_value),),'cast',payment=resources)
                stack_source=events[0].after
                frame=self._spell_frame(stack_source,quote);self.stack.append(frame)
            if source.commander and source.zone==Zone.COMMAND:
                self.state.record_command_cast(quote.actor,source.ref.card_id)
            source=stack_source
            event_kind='spell_cast'
            mana_ability=False
        else:
            ability = ability or next(ability for ability in self.activated_abilities(source) if ability.ability_id == quote.ability_id)
            if not paid:
                self.state.move((), 'activation_payment', payment=resources)
                source=self.state.get(quote.source)
            mana_ability = ability.mana_ability
            tapped_for_mana=mana_ability and quote.cost.tap_source and source.zone==Zone.BATTLEFIELD
            if mana_ability and not all(isinstance(effect,AddMana) for effect in ability.effects):
                frame=self._frame(source,quote.actor,ability.effects,chosen_x=quote.x_value)
                frame.update(ability_id=ability.ability_id,mana_ability=True,return_priority=quote.actor,tapped_for_mana=tapped_for_mana)
                self.resolving=frame
            elif mana_ability:
                immediate_mana=ability.effects
                frame = None
            else:
                frame = prepared_frame or self._frame(source, quote.actor, ability.effects, targets=quote.targets, target_spec=ability.targets,chosen_x=quote.x_value)
                frame['source']=source.to_json();frame['ability_id'] = ability.ability_id
                if prepared_frame is None:self.stack.append(frame)
            event_kind = 'ability_activated'
        if frame is not None:self._bind_announced_values(frame,quote)
        receipt = {'action': quote.to_json(), 'payment': {'mana': dict(resources.mana), 'life': resources.life,
            'taps': [ref.to_json() for ref in resources.taps]}, 'frame': frame['id'] if frame else None,
            'mana_ability': mana_ability}
        if convoke:receipt['payment']['convoke']=[{'ref':ref.to_json(),'color':color} for ref,color in convoke]
        if resources.counters:
            receipt['payment']['counters']=[{'source':ref.to_json(),'kind':kind,'amount':amount} for ref,kind,amount in resources.counters]
        if zone_payment is not None:receipt['payment']['zone_costs']=zone_payment
        self.action_receipts[quote.action_id] = receipt
        self._event('costs_paid', action_id=quote.action_id, **receipt['payment'])
        self._event(event_kind, action_id=quote.action_id, source=source.ref.to_json(), controller=quote.actor)
        self.priority = None if self.mana_payment else quote.actor
        self.passes = []
        self._collect_announcement(event_kind, source, quote.actor,previous_types=previous_types)
        self._collect_tapped(resources.taps,tap_observers)
        for effect in immediate_mana:
            self._produce_mana(quote.actor,effect.symbols,tapped_for_mana=tapped_for_mana)
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
        source=RulesObject.from_json(pending['source']);ability=decode(pending['ability'])
        resources=self._resource_payment(quote,payment,source=source);cost=quote.cost.zone_costs[0]
        prepared_frame=next((frame for frame in self.stack if frame['id']==pending['frame_id']),None)
        if (quote.kind=='cast' or not ability.mana_ability) and prepared_frame is None:
            raise RulesViolation('Announced action frame disappeared during payment')
        refs=tuple(ObjectRef.from_json(ref) for ref in pending['refs'])
        # Capture derived battlefield information immediately before payment.
        # A suspended replacement choice reruns this pure read; it cannot pay twice.
        views=self.characteristics()
        observations={}
        if quote.kind=='cast':
            observations['paid_cost_stats']={cost.cost_id:{stat:sum(getattr(views[ref],stat) or 0 for ref in refs)
                for stat in ('power','toughness','mana_value')}}
        # New subtype facts are restricted to public battlefield payments.
        if all(self.state.get(ref).zone==Zone.BATTLEFIELD for ref in refs):
            observations['paid_cost_subtypes']={cost.cost_id:sorted({subtype for ref in refs for subtype in views[ref].subtypes})}
        frame={'source':pending['source'],'controller':quote.actor,'bindings':{}}
        destination={'sacrifice':Zone.GRAVEYARD,'discard':Zone.GRAVEYARD,'exile':Zone.EXILE,'return':Zone.HAND}[cost.kind]
        events=self._move(refs,destination,frame,quote.action_id+':cost',cause=cost.kind,controller_mode='owner',payment=resources)
        if quote.kind=='cast':
            source=RulesObject.from_json(pending['origin_source'])
        else:
            source=next((event.before for event in events if event.before.ref==quote.source),source)
        if prepared_frame is not None:
            prepared_frame['values'].update(observations)
            for task in prepared_frame['tasks']:
                if 'values' in task:task['values'].update(observations)
        self.announcement=None
        self._commit_prepared(quote,resources,paid=True,source=source,ability=ability,
            zone_payment={cost.cost_id:pending['refs']},previous_types=pending['source_types'],prepared_frame=prepared_frame,convoke=payment.convoke)

    def _collect_announcement(self, kind, announced, actor,*,previous_types=None,values=None):
        observers = list(self.state.objects(Zone.BATTLEFIELD))
        if kind == 'spell_cast':
            observers.append(announced)
        types=None
        for source in observers:
            if source.phased:
                continue
            for ability in self._trigger_abilities(source,kind):
                pattern = ability.event
                if source.zone == Zone.STACK and pattern.subject != 'self':
                    continue
                if pattern.kind != kind or pattern.subject == 'self' and source.ref != announced.ref:
                    continue
                if not event_player_matches(pattern,source.controller,actor):
                    continue
                excluded=pattern.excluded_types if isinstance(pattern,SpellEventPattern) else ()
                colors=pattern.colors if isinstance(pattern,ColoredSpellEvent) else ()
                if colors and not set(colors)<=self.effective(announced.ref).colors:continue
                if pattern.types or excluded:
                    if types is None:
                        try:types=self.effective(announced.ref).types
                        except RulesViolation:types=set(previous_types) if previous_types is not None else self._damage_source(announced)[1].types
                    if not set(pattern.types) <= types or set(excluded)&types:continue
                captured={"event_x":announced.cast_x} if kind=="spell_cast" else dict(values or {})
                if kind in ACTOR_EVENTS:captured["event_controllers"]=[actor]
                self._trigger(source, ability, values=captured)
