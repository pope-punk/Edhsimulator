"""Bounded hand-aware source preferences, not Arena's unpublished algorithm.

The ordinary payment solver remains the legality authority. Candidate portfolios
only rank exact legal payments. Lookahead uses this actor's hand, never a library
or another actor's private objects, and estimates mana affordability, not effects.
"""
from collections import Counter
from itertools import combinations
import json
from .rules_state import Zone, ObjectRef, RulesViolation
from .rules_program import CostSpec

MAX_CANDIDATES = 24
MAX_HAND = 10
MAX_PROFILES = 4096


def hand_costs(kernel, actor, source):
    """Conservative fixed printed costs for a bounded heuristic, never legality."""
    costs=[]
    for obj in kernel.state.objects(Zone.HAND):
        if obj.owner!=actor or obj.ref==source:continue
        spec=kernel.definition(obj).cast
        if spec is None or not isinstance(spec.cost,CostSpec):continue
        mana=spec.cost.mana
        if mana.x_symbols or any(c not in 'WUBRGC' for c in mana.symbols):continue
        if not isinstance(spec.generic_reduction,int):continue
        colored=Counter(mana.symbols)
        generic=max(0,mana.generic-spec.generic_reduction)
        costs.append((generic+len(mana.symbols),tuple(colored[c] for c in 'WUBRGC')))
    return sorted(costs)[:MAX_HAND]


def profiles(pool, sources):
    """Mutually exclusive outputs stay exclusive; one dual is never two mana."""
    rows={pool}
    for _,choices in sources:
        rows={tuple(min(30,a+b) for a,b in zip(row,mana))
              for row in rows for mana,_ in choices}
        if len(rows)>MAX_PROFILES:return None
    return rows


def affordable(cost, rows):
    total,colors=cost
    return any(sum(row)>=total and all(a>=b for a,b in zip(row,colors)) for row in rows)


def portfolio_score(costs, rows):
    if rows is None:return (0,0)
    singles=sum(affordable(cost,rows) for cost in costs)
    # A simultaneously payable subset estimates consecutive casts without
    # assuming future draws, mana-producing effects, or successful resolution.
    for count in range(min(singles,len(costs)),0,-1):
        for group in combinations(costs,count):
            cost=(sum(c[0] for c in group),tuple(sum(c[1][i] for c in group) for i in range(6)))
            if affordable(cost,rows):return count,singles
    return 0,singles


def preferred_payment(kernel,actor,command):
    from .primitive_autotap import _payment,options,COLORS,quote
    q=quote(kernel,actor,command)
    sources=[(o,options(kernel,actor,o)) for o in sorted(kernel.state.objects(Zone.BATTLEFIELD),key=lambda o:o.ref.card_id)]
    sources=[row for row in sources if row[1]]
    # Always retain the base solver's exact feasible solution. Alternative
    # searches cannot turn a proven payment into an affordability failure.
    try:baseline=_payment(kernel,actor,command,sources=sources)
    except RulesViolation:
        # No pilot-supplied tag choices are needed in the automatic policy.
        # Find a legal tagged prefix before reporting ordinary infeasibility.
        baseline=None
    variants=[]
    tags=kernel.state.mana_tags(actor)
    if 'tagged_mana' not in command.get('autotap',{}) and q.source is not None:
        legal=[]
        for unit in sorted(tags):
            try:kernel._tagged_resources(actor,(unit,),quote=q,source=kernel.state.get(q.source))
            except RulesViolation:continue
            legal.append(unit)
        need=q.cost.mana.generic+len(q.cost.mana.symbols)
        groups=[legal]+[[u for u in legal if tags[u]['symbol']==c] for c in COLORS]
        from copy import deepcopy
        for group in groups:
            for n in range(1,min(need,len(group))+1):
                v=deepcopy(command);v.setdefault('autotap',{})['tagged_mana']=group[:n]
                variants.append(v)
    tag_candidates=[]
    for variant in variants[:MAX_CANDIDATES]:
        try:tag_candidates.append(_payment(kernel,actor,variant,sources=sources,allow_filters=False))
        except RulesViolation:continue
    if baseline is None:
        if not tag_candidates:return _payment(kernel,actor,command,sources=sources)
        baseline=tag_candidates[0]
    # The fallback paid-filter line is already exact and validated at execution.
    # Free-source portfolio scoring must not treat filter output as free mana.
    if any(row.get('payment',{}).get('mana') for row in baseline.get('mana_actions',[])):return baseline
    costs=hand_costs(kernel,actor,q.source)
    demand=tuple(sum(c[1][i] for c in costs) for i in range(6))
    def scarcity(row):
        mana=[m for m,_ in row[1]]
        return (sum(max(m[i] for m in mana)*demand[i] for i in range(6)),
                len({i for m in mana for i,n in enumerate(m) if n}),row[0].ref.card_id)
    orders=[sorted(sources,key=scarcity)]
    # Retain alternative source allocations, including avoiding any single
    # source used in the baseline. All variations share precomputed eligibility.
    used={ObjectRef.from_json(a['source']) for a in baseline.get('mana_actions',[]) if a['kind']=='activate'}
    orders += [[row for row in sources if row[0].ref!=ref] for ref in sorted(used,key=lambda r:r.card_id)]
    for i in range(6):
        orders.append(sorted(sources,key=lambda row:(max(m[i] for m,_ in row[1]),scarcity(row))))
    candidates={json.dumps(p,sort_keys=True):p for p in [baseline]+tag_candidates}
    for order in orders[:MAX_CANDIDATES-1]:
        try:p=_payment(kernel,actor,command,sources=order,allow_filters=False)
        except RulesViolation:continue
        candidates[json.dumps(p,sort_keys=True)]=p
    for color in COLORS:
        try:p=_payment(kernel,actor,command,sources=sources,spend_order=COLORS.replace(color,'')+color,allow_filters=False)
        except RulesViolation:continue
        candidates[json.dumps(p,sort_keys=True)]=p
    excluded={q.source}
    for refs in command.get('payment',{}).get('zone_costs',{}).values():excluded.update(ObjectRef.from_json(r) for r in refs)
    excluded.update(ObjectRef.from_json(r) for r in command.get('payment',{}).get('taps',[]))
    def score(p):
        pool=dict(kernel.state.mana_pool(actor))
        for unit,row in tags.items():
            if unit not in p.get('tagged_mana',[]):pool[row['symbol']]=pool.get(row['symbol'],0)-1
        lines=p.get('mana_actions',[]);spent_sources=set();remaining=[pool.get(c,0)-p['mana'].get(c,0) for c in COLORS]
        for obj,choices in sources:
            if not any(a.get('source')==obj.ref.to_json() for a in lines):continue
            spent_sources.add(obj.ref)
            idx=next(i for i,a in enumerate(lines) if a.get('source')==obj.ref.to_json())
            match=next((m for m,cmds in choices if lines[idx:idx+len(cmds)]==cmds),None)
            if match is None:raise RulesViolation('Internal automatic payment source mismatch')
            remaining=[a+b for a,b in zip(remaining,match)]
        left=[row for row in sources if row[0].ref not in spent_sources|excluded]
        rows=profiles(tuple(remaining),left)
        playable=portfolio_score(costs,rows)
        flexibility=sum(len({i for m,_ in opts for i,n in enumerate(m) if n}) for _,opts in left)
        # Retain optionality, then untapped capacity (floating mana expires).
        return (*playable,len(left),flexibility,-sum(remaining),-len(lines))
    return max(candidates.values(),key=score)
