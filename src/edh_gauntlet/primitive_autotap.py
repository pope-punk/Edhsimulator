"""Bounded deterministic payment selection for explicitly authorized auto-taps.

Only side-effect-free tap-for-mana abilities, including finite paid filters, are eligible. Reservations describe
simultaneously available mana after payment, not a preference to ignore on failure.
"""
import hashlib
from collections import Counter
from copy import deepcopy
from .rules_state import RulesViolation, Zone, ObjectRef
from .rules_program import CostSpec, AddMana, ChooseMana, ChooseCommanderMana, LandMana, ProduceMana, ActivatedProgram, LoyaltyCost
from .rules_casting import Payment, _mana_symbols_satisfied

COLORS = 'WUBRGC'
LIMIT = 20000


def validate(command):
    if 'autotap' not in command:return
    spec=command['autotap']
    if command.get('kind') not in ('cast','activate','pay_mana') or type(spec) is not dict or set(spec)-{'reserve','tagged_mana'}:
        raise RulesViolation('autotap is a cast/activate option with optional reserve counts and tagged_mana IDs')
    tags=spec.get('tagged_mana',[])
    if type(tags) is not list or any(type(unit) is not str for unit in tags) or len(set(tags))!=len(tags):
        raise RulesViolation('autotap.tagged_mana requires unique current owned mana unit IDs')
    reserve=spec.get('reserve',{})
    if (type(reserve) is not dict or set(reserve)-set(COLORS)
            or any(type(n) is not int or not 0<=n<=10 for n in reserve.values()) or sum(reserve.values())>10):
        raise RulesViolation('autotap.reserve requires W/U/B/R/G/C counts, totaling at most 10')
    payment=command.get('payment',{'mana':{},'taps':[]})
    if type(payment) is not dict or payment.get('mana') or any(payment.get(k) for k in ('mana_actions','convoke','tagged_mana','cost_order')):
        raise RulesViolation('autotap supplies mana and mana_actions; specify other payment costs explicitly')
    try:Payment.from_json(payment)
    except (KeyError,TypeError,ValueError) as exc:raise RulesViolation('Invalid explicit non-mana payment for autotap') from exc


def options(kernel,actor,obj,*,reserve_check=False,available=None):
    """Return finite ordinary mana options, never strategic side-effect choices."""
    from .primitive_priority import _orientation_sensitive
    if (obj.zone!=Zone.BATTLEFIELD or obj.controller!=actor or obj.tapped or obj.phased
            or 'Creature' in kernel.effective(obj.ref).types):return []
    for observer in kernel.state.objects(Zone.BATTLEFIELD):
        if observer.phased:continue
        if _orientation_sensitive(kernel.definition(observer).continuous):return []
        for kind in ('becomes_tapped','ability_activated'):
            for trigger in kernel._trigger_abilities(observer,kind):
                pattern=trigger.event
                if pattern.subject=='self' and observer.ref!=obj.ref:continue
                if pattern.controller_only and observer.controller!=actor:continue
                if pattern.types and not set(pattern.types)<=kernel.effective(obj.ref).types:continue
                return []
    result=[]
    for ability in kernel.activated_abilities(obj):
        if (not ability.mana_ability or ability.zone!=Zone.BATTLEFIELD
                or type(ability.cost) is not CostSpec or ability.cost!=CostSpec(mana=ability.cost.mana,tap_source=True)
                or len(ability.effects)!=1 or ability.targets is not None):continue
        if ability.cost.mana.x_symbols or ability.cost.mana.generic+len(ability.cost.mana.symbols)>30:continue
        if available is None and (ability.cost.mana.generic or ability.cost.mana.symbols):continue
        cost=ability.cost.mana
        if reserve_check:
            # A pending trigger-order choice need not invalidate physical capacity.
            # For this post-payment proof admit only unrestricted instant abilities.
            if type(ability) is not ActivatedProgram or ability.timing!='instant':continue
        else:
            try:
                quoted=kernel.quote_activation('autotap-eligibility',actor,obj.ref,ability.ability_id)
                if type(quoted.cost) is not CostSpec or quoted.cost!=CostSpec(mana=quoted.cost.mana,tap_source=True):continue
                cost=quoted.cost.mana
            except RulesViolation:continue
        e=ability.effects[0]
        if type(e) is AddMana:bundles=(e.symbols,)
        elif type(e) is ChooseMana:bundles=e.options
        elif type(e) is ChooseCommanderMana:bundles=tuple((c,) for c in kernel.state.commander_identity(actor))
        elif type(e) is LandMana:bundles=tuple((c,) for c in kernel.land_mana_options(e,actor))
        elif type(e) is ProduceMana and type(e.amount) is int and 0<e.amount<=20:bundles=tuple((c,)*e.amount for c in e.options)
        else:continue
        for index,bundle in enumerate(bundles):
            counts=Counter(kernel._mana_after_replacements(actor,bundle,tapped_for_mana=True))
            if not counts or set(counts)-set(COLORS):continue
            for spent in spends(available or (0,)*6,cost):
                command={'kind':'activate','source':obj.ref.to_json(),'ability_id':ability.ability_id,
                         'targets':[],'x_value':0,'payment':{'mana':{c:n for c,n in zip(COLORS,spent) if n},'taps':[]}}
                commands=[command]
                if len(bundles)>1:commands.append({'kind':'answer','indexes':[index]})
                result.append((tuple(counts[c]-n for c,n in zip(COLORS,spent)),commands))
    return result



def free_pool(kernel,actor):
    tagged=Counter(v['symbol'] for v in kernel.state.mana_tags(actor).values())
    pool=dict(kernel.state.mana_pool(actor))
    return tuple(pool.get(c,0)-tagged[c] for c in COLORS)


def spends(pool,cost):
    """Exact, finite payments from already-produced unrestricted mana."""
    total=cost.generic+len(cost.symbols)
    if cost.x_symbols or total>sum(pool):return
    count=0
    def walk(i,left,prefix):
        nonlocal count
        if i==5:
            if 0<=left<=pool[i]:
                row=prefix+(left,);count+=1
                if count>LIMIT:raise RulesViolation('Filter payment search limit reached')
                if _mana_symbols_satisfied(cost.symbols,dict(zip(COLORS,row))):yield row
            return
        for n in range(max(0,left-sum(pool[i+1:])),min(pool[i],left)+1):
            yield from walk(i+1,left-n,prefix+(n,))
    yield from walk(0,total,())


def filter_payment(kernel,actor,q,pool,reserve,excluded):
    """Search ordered pure mana production; each permanent taps at most once.

    Costs are paid before output is credited. No source can bootstrap itself or
    mutually fund another unfunded filter. Commands are revalidated atomically.
    The fast free-source solver is always attempted before this fallback.
    """
    from collections import deque
    objects=[o for o in sorted(kernel.state.objects(Zone.BATTLEFIELD),key=lambda o:o.ref.card_id) if o.ref not in excluded]
    # Probe structural eligibility without mutating mana or objects. Costs in
    # the actual search must be funded by its reachable pool, not this probe.
    potential=[(o,options(kernel,actor,o,available=(30,)*6)) for o in objects]
    if not any(any(line[0]['payment']['mana'] for _,line in choices) for _,choices in potential):return None
    sources=[(o,options(kernel,actor,o)) for o,choices in potential if choices]
    need=q.cost.mana.generic+len(q.cost.mana.symbols)
    cap=need+30+sum(reserve)
    initial=tuple(min(cap,n) for n in pool)
    queue=deque([(0,initial,[]) ]);seen={(0,initial)};cache={};work=0
    while queue:
        mask,available,line=queue.popleft()
        for spent in spends(available,q.cost.mana):
            remainder=tuple(a-n for a,n in zip(available,spent))
            reachable={tuple(min(r,n) for r,n in zip(reserve,remainder))}
            for i,(_,choices) in enumerate(sources):
                if mask&(1<<i):continue
                reachable|={tuple(min(r,h+n) for r,h,n in zip(reserve,held,mana)) for held in tuple(reachable) for mana,_ in choices}
                if reserve in reachable:break
            if reserve in reachable:return mask.bit_count(),line,spent
        for i,(obj,_) in enumerate(sources):
            if mask&(1<<i):continue
            key=(i,available)
            if key not in cache:cache[key]=options(kernel,actor,obj,available=available)
            for net,commands in cache[key]:
                work+=1
                if work>LIMIT:raise RulesViolation('Automatic filter-mana search limit reached; no payment was made')
                after=tuple(min(cap,a+n) for a,n in zip(available,net))
                state=(mask|(1<<i),after)
                if state in seen:continue
                seen.add(state);queue.append((*state,line+commands))
    return None


def quote(kernel,actor,command):
    if command.get('kind')=='pay_mana':
        from types import SimpleNamespace
        from .rules_program import decode
        window=kernel.mana_payment
        if not kernel._payment_waiting() or window['actor']!=actor or window['id']!=command.get('request_id'):
            raise RulesViolation('No matching current mana payment')
        return SimpleNamespace(cost=CostSpec(mana=decode(window['mana'])),source=None,actor=actor,kind='pay_mana')
    from .rules_adapter import RulesActorAdapter
    adapter=RulesActorAdapter(kernel)
    source=adapter._visible_ref(command['source'],actor)
    targets=tuple(adapter._visible_target(v,actor) for v in command['targets'])
    division=tuple((adapter._visible_ref(v['ref'],actor),v['amount']) for v in command.get('counter_division',[]))
    if command['kind']=='activate':
        return kernel.quote_activation(command['action_id'],actor,source,command['ability_id'],targets,x_value=command['x_value'],counter_division=division)
    return kernel.quote_cast(command['action_id'],actor,source,targets,x_value=command['x_value'],
        mode_choices=tuple((v['mode_id'],tuple(adapter._visible_target(t,actor) for t in v['targets'])) for v in command.get('modes',[])),
        alternative_id=command.get('alternative_id'),counter_division=division,kicker=command.get('kicker',False),
        replicate=command.get('replicate',0),life_costs=tuple(command.get('life_costs',[])),
        hybrid_choices=tuple(command.get('hybrid_choices',[])),face=command.get('face'))


def payment(kernel,actor,command,*,smart=False):
    if smart:
        command=deepcopy(command)
        if isinstance(command.get('payment'),dict):
            command['payment'].setdefault('mana',{})
            command['payment'].setdefault('taps',[])
        from .primitive_mana_preferences import preferred_payment
        return preferred_payment(kernel,actor,command)
    return _payment(kernel,actor,command)


def _payment(kernel,actor,command,*,sources=None,spend_order=COLORS,allow_filters=True):
    validate(command)
    q=quote(kernel,actor,command)
    if type(q.cost) not in (CostSpec,LoyaltyCost):raise RulesViolation('autotap requires an ordinary quoted cost; use explicit payment for this cost')
    need=q.cost.mana.generic+len(q.cost.mana.symbols)
    if need>30:raise RulesViolation('autotap bounded search supports costs up to 30 mana; use explicit payment')
    reserve=tuple(command['autotap'].get('reserve',{}).get(c,0) for c in COLORS)
    tags=kernel.state.mana_tags(actor)
    selected=command['autotap'].get('tagged_mana',[])
    # The pilot selects consequential/restricted units; Python pays the remainder.
    if selected:kernel._tagged_resources(actor,tuple(selected),quote=q,source=kernel.state.get(q.source))
    forced=Counter(tags[unit]['symbol'] for unit in selected)
    unavailable=Counter(row['symbol'] for unit,row in tags.items() if unit not in selected)
    pool=tuple(dict(kernel.state.mana_pool(actor)).get(c,0)-unavailable[c] for c in COLORS)
    if sum(forced.values())>need:raise RulesViolation('Selected tagged mana exceeds this action cost')
    excluded={q.source}
    base=deepcopy(command.get('payment',{'mana':{},'taps':[]}))
    if selected:base['tagged_mana']=list(selected)
    excluded.update(ObjectRef.from_json(r) for r in base.get('taps',[]))
    for refs in base.get('zone_costs',{}).values():
        excluded.update(ObjectRef.from_json(r) for r in refs)
    # State is (available pool, mana producible by sources explicitly left untapped).
    # Each source can contribute to either side once, never to both.
    cap=tuple(need+r for r in reserve)
    states={(tuple(min(p,c) for p,c in zip(pool,cap)),(0,)*6):(0,[])}
    for obj,choices in (sources if sources is not None else [(o,options(kernel,actor,o)) for o in sorted(kernel.state.objects(Zone.BATTLEFIELD),key=lambda o:o.ref.card_id)]):
        if obj.ref in excluded:continue
        if not choices:continue
        nxt=dict(states)
        for (available,held),(taps,commands) in states.items():
            for mana,line in choices:
                candidates=[((tuple(min(c,a+m) for c,a,m in zip(cap,available,mana)),held),(taps+1,commands+line))]
                if any(reserve):candidates.append(((available,tuple(min(r,h+m) for r,h,m in zip(reserve,held,mana))),(taps,commands)))
                for key,value in candidates:
                    if key not in nxt or value[0]<nxt[key][0]:nxt[key]=value
        if len(nxt)>LIMIT:raise RulesViolation('autotap search limit reached; use explicit payment or a smaller reservation')
        states=nxt
    attempts=0
    def expenditures(limits,total,prefix=()):
        nonlocal attempts
        if len(limits)==1:
            if 0<=total<=limits[0]:
                attempts+=1
                if attempts>LIMIT:raise RulesViolation('autotap expenditure search limit reached; use explicit payment')
                yield prefix+(total,)
            return
        for n in range(max(0,total-sum(limits[1:])),min(limits[0],total)+1):
            yield from expenditures(limits[1:],total-n,prefix+(n,))
    best=None
    for (available,held),(taps,commands) in sorted(states.items(),key=lambda row:row[1][0]):
        if best is not None and taps>best[0]:break
        if sum(available)<need:continue
        limits=[min(a,need,max(0,a+h-r)) for a,h,r in zip(available,held,reserve)]
        if any(a+h<r for a,h,r in zip(available,held,reserve)):continue
        # Enumerate exact expenditures, bounded by cost; no gratuitous mana spending.
        order=[COLORS.index(c) for c in spend_order]
        for ordered_spend in expenditures([limits[i] for i in order],need):
            mapping=dict(zip(order,ordered_spend));spend=tuple(mapping[i] for i in range(6))
            if all(n>=forced[c] for c,n in zip(COLORS,spend)) and _mana_symbols_satisfied(q.cost.mana.symbols,dict(zip(COLORS,spend))):
                best=(taps,commands,spend);break
        if best is not None:break
    if best is None and allow_filters and not selected:
        best=filter_payment(kernel,actor,q,pool,reserve,excluded)
    if best is None:
        if not any(reserve):raise RulesViolation('autotap found no payment using eligible ordinary mana sources; no reserve was requested. Consequential mana sources still require planner-authored sequencing; tapped or restricted sources may be unavailable.')
        raise RulesViolation('autotap cannot pay while preserving the requested reserve using ordinary mana sources; edit the reservation or pay explicitly')
    base['mana']={c:n for c,n in zip(COLORS,best[2]) if n}
    if best[1]:base['mana_actions']=best[1]
    if any(reserve):
        from .rules_adapter import RulesActorAdapter
        trial=type(kernel).restore(kernel.snapshot(),kernel._base_definitions.values())
        final=deepcopy(command);final.pop('autotap');final['payment']=base
        RulesActorAdapter(trial)._execute(actor,final)
        unselected=Counter(row['symbol'] for row in trial.state.mana_tags(actor).values())
        remaining=tuple(dict(trial.state.mana_pool(actor)).get(c,0)-unselected[c] for c in COLORS)
        reachable={tuple(min(r,n) for r,n in zip(reserve,remaining))}
        for obj in trial.state.objects(Zone.BATTLEFIELD):
            choices=options(trial,actor,obj,reserve_check=True)
            reachable|={tuple(min(r,h+n) for r,h,n in zip(reserve,held,mana))
                        for held in tuple(reachable) for mana,_ in choices}
            if reserve in reachable:break
        if reserve not in reachable:
            raise RulesViolation('autotap cannot preserve the reserve after the complete action costs; revise the payment or reserve')
    return base


def commit_priority(kernel,q,payment):
    """Atomically execute the exact selected mana actions and final action.

No inference, priority passing or non-mana choice is admitted inside this bundle.
The isolated trial is committed only after the entire payment validates.
"""
    from dataclasses import replace
    from .rules_adapter import RulesActorAdapter
    if kernel.priority!=q.actor or kernel.pending_choice or kernel.resolving:
        raise RulesViolation('Bundled ordinary mana payment requires priority')
    trial=type(kernel).restore(kernel.snapshot(),kernel._base_definitions.values())
    adapter=RulesActorAdapter(trial);lines=list(payment.mana_actions);index=0
    while index<len(lines):
        cmd=lines[index]
        if cmd.get('kind')!='activate':raise RulesViolation('Bundled mana must begin with an ordinary activation')
        obj=trial.state.get(ObjectRef.from_json(cmd['source']))
        match=next((line for _,line in options(trial,q.actor,obj,available=free_pool(trial,q.actor)) if lines[index:index+len(line)]==line),None)
        if match is None:raise RulesViolation('Bundled mana contains an unavailable or consequential mana action')
        for row in match:
            bound=deepcopy(row);bound['revision']=trial.revision
            if row['kind']=='activate':bound['action_id']='autotap:'+hashlib.sha256((q.action_id+':'+str(index)).encode()).hexdigest()
            else:
                request=trial.pending_choice
                if request is None or request.actor!=q.actor or request.kind!='mana_choice':raise RulesViolation('Bundled mana choice is unavailable')
                bound['request_id']=request.request_id
            adapter._execute(q.actor,bound);index+=1
        if trial.pending_choice or trial.resolving or trial.priority!=q.actor:
            raise RulesViolation('Bundled mana encountered an execution boundary')
    result=trial.commit_action(replace(q,revision=trial.revision),replace(payment,mana_actions=()))
    state=kernel.state;state.__dict__.update(trial.state.__dict__)
    kernel.__dict__.update(trial.__dict__);kernel.state=state
    return result


def commit_resolution_payment(kernel, actor, command, payment):
    """Execute only prevalidated ordinary mana lines and the fixed payment atomically."""
    from .rules_adapter import RulesActorAdapter
    trial=type(kernel).restore(kernel.snapshot(),kernel._base_definitions.values())
    adapter=RulesActorAdapter(trial);lines=list(payment.mana_actions);index=0
    quote(trial,actor,command)  # Fence the exact current resolution request first.
    while index<len(lines):
        row=lines[index]
        if row.get('kind')!='activate':raise RulesViolation('Bundled mana requires an activation')
        obj=trial.state.get(ObjectRef.from_json(row['source']))
        match=next((cmds for _,cmds in options(trial,actor,obj,available=free_pool(trial,actor)) if lines[index:index+len(cmds)]==cmds),None)
        if match is None:raise RulesViolation('Unavailable ordinary mana bundle')
        for item in match:
            item=deepcopy(item);item['revision']=trial.revision
            if item['kind']=='activate':item['action_id']='autotap:'+hashlib.sha256((command['action_id']+':'+str(index)).encode()).hexdigest()
            else:
                pending=trial.pending_choice
                if not pending or pending.actor!=actor or pending.kind!='mana_choice':raise RulesViolation('Mana choice boundary changed')
                item['request_id']=pending.request_id
            adapter._execute(actor,item);index+=1
        quote(trial,actor,command)
    final=deepcopy(command);final['revision']=trial.revision;final['payment']=payment.to_json();final['payment'].pop('mana_actions',None)
    result=adapter._execute(actor,final)
    state=kernel.state;state.__dict__.update(trial.state.__dict__)
    kernel.__dict__.update(trial.__dict__);kernel.state=state
    return result
