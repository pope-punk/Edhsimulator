"""Bounded, engine-validated fallback for mana abilities with additional costs."""
from copy import deepcopy
from itertools import combinations,product,islice
from collections import deque
from .rules_state import Zone,RulesViolation,ObjectRef
from .rules_program import CostSpec,AddMana,ChooseMana,ChooseCommanderMana,LandMana,ProduceMana
from .rules_casting import Payment

MAX_NODES=64
MAX_DEPTH=12

def clone(kernel):
    trial=type(kernel).restore(kernel.snapshot(),kernel._base_definitions.values())
    trial._automatic_payment=True
    return trial

def execute(kernel,actor,row,identity):
    """Only mana activations and their color choices can enter a payment bundle."""
    from .rules_adapter import RulesActorAdapter
    row=deepcopy(row);row['revision']=kernel.revision
    if row.get('kind')=='activate':
        obj=kernel.state.get(ObjectRef.from_json(row['source']))
        ability=next((a for a in kernel.activated_abilities(obj) if a.ability_id==row['ability_id']),None)
        if ability is None or not ability.mana_ability:raise RulesViolation('Automatic payment requires a mana ability')
        row['action_id']=identity
    elif row.get('kind')=='answer':
        pending=kernel.pending_choice
        if not pending or pending.actor!=actor or pending.kind!='mana_choice':raise RulesViolation('Automatic payment cannot answer a non-mana choice')
        row['request_id']=pending.request_id
    else:raise RulesViolation('Automatic payment contains a non-mana action')
    return RulesActorAdapter(kernel)._execute(actor,row)

def costs(kernel,actor,q,pool):
    from .primitive_autotap import spends,COLORS
    if type(q.cost) is not CostSpec:return
    source=kernel.state.get(q.source);context={'source':source.to_json(),'controller':actor}
    taps=[()] if not q.cost.tap_count else list(islice(combinations(sorted((o.ref for o in kernel._query(q.cost.tap_selector,context) if not o.tapped),key=lambda r:r.card_id),q.cost.tap_count),32))
    groups=[]
    for cost in q.cost.zone_costs:
        if cost.selector is None:continue
        refs=sorted((o.ref for o in kernel._query(cost.selector,context)),key=lambda r:r.card_id)
        groups.append([(cost.cost_id,chosen) for chosen in islice(combinations(refs,cost.count),32)])
    for spent in spends(pool,q.cost.mana):
        for tap in taps:
            for selected in product(*groups):
                value={'mana':{c:n for c,n in zip(COLORS,spent) if n},'taps':[r.to_json() for r in tap]}
                if selected:value['zone_costs']={key:[r.to_json() for r in refs] for key,refs in selected}
                try:
                    payment=Payment.from_json(value)
                    kernel._resource_payment(q,payment);kernel._zone_cost_refs(q,payment)
                except RulesViolation:continue
                yield value

def additional(kernel,obj,ability):
    cost=ability.cost
    if ('Creature' in kernel.effective(obj.ref).types or type(cost) is not CostSpec
        or cost.life or cost.tap_count or cost.zone_costs or cost.counter_costs
        or not cost.tap_source or len(ability.effects)!=1
        or type(ability.effects[0]) not in (AddMana,ChooseMana,ChooseCommanderMana,LandMana,ProduceMana)
        or type(getattr(ability.effects[0],'amount',1)) is not int):return True
    from .primitive_priority import _orientation_sensitive
    for observer in kernel.state.objects(Zone.BATTLEFIELD):
        if observer.phased:continue
        if _orientation_sensitive(kernel.definition(observer).continuous):return True
        for kind in ('becomes_tapped','ability_activated'):
            for trigger in kernel._trigger_abilities(observer,kind):
                pattern=trigger.event
                if pattern.subject=='self' and observer.ref!=obj.ref:continue
                if pattern.controller_only and observer.controller!=obj.controller:continue
                if pattern.types and not set(pattern.types)<=kernel.effective(obj.ref).types:continue
                return True
    return False


def successors(kernel,actor,excluded,index):
    from .primitive_autotap import free_pool
    needs_funding=any(additional(kernel,o,a) and (a.cost.mana.generic or a.cost.mana.symbols) for o in kernel.state.objects(Zone.BATTLEFIELD) if o.controller==actor for a in kernel.activated_abilities(o) if a.mana_ability)
    for obj in sorted(kernel.state.objects(Zone.BATTLEFIELD),key=lambda o:o.ref.card_id):
        if obj.controller!=actor or obj.phased or obj.ref in excluded:continue
        for ability in kernel.activated_abilities(obj):
            if not ability.mana_ability or ability.targets is not None:continue
            if not needs_funding and not additional(kernel,obj,ability):continue
            try:q=kernel.quote_activation('auto-search-quote',actor,obj.ref,ability.ability_id)
            except RulesViolation:continue
            for n,payment in enumerate(costs(kernel,actor,q,free_pool(kernel,actor))):
                if n>=32:break
                row={'kind':'activate','source':obj.ref.to_json(),'ability_id':ability.ability_id,'targets':[],'x_value':0,'payment':payment}
                trial=clone(kernel)
                try:execute(trial,actor,row,f'auto-search:{index}:{n}')
                except RulesViolation:continue
                pending=trial.pending_choice
                if pending is None:
                    if (not trial.resolving or trial._payment_waiting()) and not trial.announcement:yield trial,[row]
                elif pending.actor==actor and pending.kind=='mana_choice' and pending.minimum==pending.maximum==1:
                    for choice in range(len(pending.options)):
                        branch=clone(trial);answer={'kind':'answer','indexes':[choice]}
                        try:execute(branch,actor,answer,'auto-search-answer')
                        except RulesViolation:continue
                        if not branch.pending_choice and (not branch.resolving or branch._payment_waiting()) and not branch.announcement:yield branch,[row,answer]

def upper_bound(kernel,actor):
    """Optimistic production bound: reject obvious shortages before simulation."""
    total=sum(dict(kernel.state.mana_pool(actor)).values())
    for obj in kernel.state.objects(Zone.BATTLEFIELD):
        if obj.controller!=actor or obj.phased:continue
        amounts=[]
        for a in kernel.activated_abilities(obj):
            if not a.mana_ability or a.cost.tap_source and obj.tapped:continue
            if not a.cost.tap_source:return None
            amount=0
            for e in a.effects:
                if type(e) is AddMana:amount+=len(e.symbols)
                elif type(e) is ChooseMana:amount+=max(map(len,e.options),default=0)
                elif type(e) in (ChooseCommanderMana,LandMana):amount+=1
                elif type(e) is ProduceMana and type(e.amount) is int:amount+=e.amount
                else:return None
            amounts.append(max(len(kernel._mana_after_replacements(actor,(c,)*amount,tapped_for_mana=a.cost.tap_source)) for c in 'WUBRGC'))
        total+=max(amounts,default=0)
    return total


def payment(kernel,actor,command):
    from .primitive_autotap import _payment,quote
    q=quote(kernel,actor,command)
    capacity=upper_bound(kernel,actor)
    if capacity is not None and capacity<q.cost.mana.generic+len(q.cost.mana.symbols):
        raise RulesViolation(f'Automatic payment found no payment: at most {capacity} mana is available for a cost of {q.cost.mana.generic+len(q.cost.mana.symbols)}. No costs were paid.')
    if not any(additional(kernel,o,a) for o in kernel.state.objects(Zone.BATTLEFIELD) if o.controller==actor for a in kernel.activated_abilities(o) if a.mana_ability):
        return _payment(kernel,actor,command)
    resolution=command.get('kind')=='pay_mana' and kernel._payment_waiting()
    if not resolution and (kernel.priority!=actor or kernel.resolving or kernel.pending_choice):
        raise RulesViolation('Additional-cost automatic mana search requires an owned priority window')
    excluded={q.source}
    base=command.get('payment') or {}
    excluded.update(ObjectRef.from_json(r) for r in base.get('taps',[]))
    for refs in base.get('zone_costs',{}).values():excluded.update(ObjectRef.from_json(r) for r in refs)
    queue=deque([(clone(kernel),[],frozenset())]);seen=set();lethal=None
    for index in range(MAX_NODES):
        if not queue:break
        state,line,used=queue.popleft()
        if line:
            try:
                tail=_payment(state,actor,command)
                result=deepcopy(tail);result['mana_actions']=line+tail.get('mana_actions',[])
                final=deepcopy(command);final.pop('autotap',None);final['payment']=result
                from .rules_adapter import RulesActorAdapter
                check=clone(kernel);final['revision']=check.revision
                RulesActorAdapter(check)._execute(actor,final)
                if check.state.life(actor)>0:return result
                if lethal is None:lethal=result
            except RulesViolation:pass
        if len(used)>=MAX_DEPTH:continue
        for branch,rows in successors(state,actor,excluded|used,index):
            # Each physical source may be used once in this bounded search.
            ref=ObjectRef.from_json(rows[0]['source']);key=(frozenset((*used,ref)),tuple(branch.state.mana_pool(actor)),branch.state.life(actor),repr([r.get('payment',{}) for r in line+rows if r['kind']=='activate']))
            if key in seen:continue
            seen.add(key);queue.append((branch,line+rows,used|{ref}))
            if len(queue)+len(seen)>MAX_NODES*4:break
    if lethal is not None:return lethal
    raise RulesViolation('Automatic payment found no executable payment within its bounded search, including life, tap, counter and zone costs. No costs were paid; revise the action or supply a planner sequence.')
