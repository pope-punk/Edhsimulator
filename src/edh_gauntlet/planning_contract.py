"""Contract 3's small, factual vocabulary. No strategy or executable policy.

Windows name an actual seat's turn ordinal, so extra turns do not alias rounds.
Watches are one-shot edges evaluated on actor-visible committed events.
"""
from __future__ import annotations

PHASES = ('upkeep', 'draw', 'precombat_main', 'combat', 'postcombat_main', 'end_step', 'cleanup')
PRIORITY_KINDS = frozenset({'main_action', 'priority_action', 'counterspell_response',
                          'summary_dismissal_abilities', 'heroic_intervention',
                          'evacuation_response', 'combo_response', 'combo_consent'})


def priority_request(request):
    return request.get('kind') in PRIORITY_KINDS


def _integer(value, label, minimum=1):
    if type(value) is not int or not minimum <= value <= 1000000:
        raise ValueError(f'{label} must be an integer from {minimum} to 1000000')
    return value


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError(f'{label} must be nonempty text of at most 200 characters')
    return value


def known_facts(board, catalog_names=()):
    cards=set(catalog_names); uids=set()
    for player in board.get('players', {}).values():
        for zone in ('hand', 'battlefield', 'graveyard', 'exile', 'commander'):
            values=player.get(zone, [])
            if isinstance(values, (dict,str)): values=[values]
            if not isinstance(values, list): continue
            for obj in values:
                if isinstance(obj,str) and ':' in obj:
                    uid,name=obj.split(':',1);uids.add(uid);cards.add(name)
                    continue
                if not isinstance(obj, dict): continue
                if obj.get('uid'): uids.add(obj['uid'])
                if obj.get('identity_visible', True):
                    name=obj.get('name') or obj.get('card')
                    if isinstance(name, str): cards.add(name)
    return cards, uids


def predicate(value, board, cards, uids):
    if not isinstance(value, dict): raise ValueError('A watch condition must be an object')
    kind=value.get('kind')
    fields={'card_cast': {'kind','seat','card'}, 'object_left': {'kind','uid'},
            'life_at_most': {'kind','seat','value'}}
    if kind not in fields or set(value)!=fields[kind]:
        raise ValueError('Use card_cast {seat,card}, object_left {uid}, or life_at_most {seat,value}')
    if 'seat' in value and value['seat'] not in board.get('players', {}):
        raise ValueError('Condition seat must be a known player')
    if kind=='card_cast' and value['card'] not in cards:
        raise ValueError('Card watch must name a card in the frozen known-card vocabulary')
    if kind=='object_left' and value['uid'] not in uids:
        raise ValueError('Object watch must name a visible frozen object UID')
    if kind=='life_at_most': _integer(value['value'], 'Life threshold', 0)
    return dict(value)


def recommendations(values, actor, board, cards, uids):
    if not isinstance(values, list) or len(values)>12:
        raise ValueError('recommendations must be a list of at most 12 advisory casts')
    result=[]; ids=set()
    for value in values:
        if not isinstance(value, dict) or set(value)-{'intent_id','action','card','uid','window','condition','alternative_group'}:
            raise ValueError('Unsupported recommendation fields')
        intent=_text(value.get('intent_id'), 'intent_id')
        if intent in ids: raise ValueError('intent_id must be unique within a plan')
        ids.add(intent)
        if value.get('action')!='cast' or value.get('card') not in cards:
            raise ValueError('A recommendation names action=cast and an exact known card name')
        if 'uid' in value and value['uid'] not in uids:
            raise ValueError('Recommendation UID must be visible in the frozen snapshot')
        window=value.get('window')
        if not isinstance(window, dict) or set(window)!={'seat','seat_turn','phases'}:
            raise ValueError('window requires seat, seat_turn and phases')
        if window['seat'] not in board.get('players', {}): raise ValueError('Unknown window seat')
        _integer(window['seat_turn'], 'seat_turn')
        phases=window['phases']
        if not isinstance(phases,list) or not phases or any(p not in PHASES for p in phases) or len(set(phases))!=len(phases):
            raise ValueError('window phases must be a nonempty distinct list of supported phases')
        if window['seat_turn']<board.get('planning_clock',{}).get('seat_turns',{}).get(window['seat'],0):
            raise ValueError('Recommendation window predates the source turn')
        item=dict(value)
        if 'condition' in value: item['condition']=predicate(value['condition'],board,cards,uids)
        if 'alternative_group' in value: _text(value['alternative_group'],'alternative_group')
        result.append(item)
    return result


def watches(values, board, cards, uids):
    if not isinstance(values,list) or len(values)>8:
        raise ValueError('watches must be a list of at most eight one-shot conditions')
    result=[]; ids=set()
    for value in values:
        if not isinstance(value,dict) or set(value)!={'watch_id','condition'}:
            raise ValueError('Each watch requires watch_id and condition')
        key=_text(value['watch_id'],'watch_id')
        if key in ids: raise ValueError('Duplicate watch_id')
        ids.add(key)
        result.append({'watch_id':key,'condition':predicate(value['condition'],board,cards,uids)})
    return result


def fired(condition, event):
    kind=condition['kind']
    if kind=='card_cast':
        return event.get('type') in {'cast','cast_transformed'} and event.get('actor')==condition['seat'] and event.get('card')==condition['card']
    if kind=='object_left':
        return event.get('type')=='ltb' and event.get('uid')==condition['uid']
    if kind=='life_at_most':
        return (event.get('type')=='planner_life_change' and event.get('actor')==condition['seat']
                and event['before']>condition['value']>=event['after'])
    return False


def alarm(value, actor, request):
    """Normalize an independent, replaceable decider control (not a game choice)."""
    from .referee import parse_pass_on_schedule
    if request.get('planning_contract',1)<3 or not priority_request(request):
        raise ValueError('Planner alarms require contract 3 and an existing priority decision')
    if not isinstance(value,dict) or value.get('mode') not in {'now','schedule','cancel'}:
        raise ValueError('planner_alarm mode must be now, schedule or cancel')
    extra={}
    if 'long_term' in value:
        if not request.get('planner_stages') or value['mode']=='cancel' or not isinstance(value['long_term'],bool):
            raise ValueError('long_term is a boolean request on staged now/schedule alarms only')
        value=dict(value);extra={'long_term':value.pop('long_term')}
    if value['mode'] in {'now','cancel'}:
        if set(value)!={'mode'}: raise ValueError('now/cancel takes only mode')
        return dict(value)|extra
    if set(value)!={'mode','seat','time'}: raise ValueError('schedule requires mode, seat and time')
    if value['seat'] not in request.get('public_state',{}).get('players',{}): raise ValueError('Unknown alarm seat')
    schedule=parse_pass_on_schedule(value['time'])
    if value['seat']==actor and schedule['edge']=='end' and schedule['phase']=='end_step':
        raise ValueError('Own EOT already has mandatory maintenance; choose another boundary')
    return {'mode':'schedule','seat':value['seat'],'time':schedule}|extra


def in_window(event, window):
    return (event.get('active_player')==window['seat'] and event.get('seat_turn')==window['seat_turn']
            and event.get('phase') in window['phases'])


def window_closed(window, events):
    last=max(PHASES.index(p) for p in window['phases'])
    for event in events:
        if event.get('active_player')!=window['seat']: continue
        turn=event.get('seat_turn',0)
        if turn>window['seat_turn']: return True
        if turn!=window['seat_turn']: continue
        if event.get('type')=='planner_turn_boundary' and event.get('reason')=='own_turn_completed': return True
        if (event.get('type')=='planner_phase_boundary' and event.get('edge')=='beginning'
                and PHASES.index(event['boundary_phase'])>last): return True
    return False


def compare(plans, deliveries, events, actor, since=0):
    """Compare only exposed recommendations. A countered cast still counts.

    deliveries are accepted decisions with immutable plan IDs. No publication
    timestamp is treated as exposure. Conditional misses require planner review.
    """
    deliveries=sorted(deliveries,key=lambda d:d['seq'])
    by_decision={d.get('decision_id'):d for d in deliveries if d.get('decision_id')}
    first_exposure={}; superseded={}; previous=None
    for delivery in deliveries:
        plan_id=delivery.get('plan_id')
        first_exposure.setdefault(plan_id,delivery['seq'])
        if previous and previous.get('plan_id')!=plan_id:
            superseded.setdefault(previous.get('plan_id'),delivery['seq'])
        previous=delivery
    closure_cache={}
    def closed_at(window):
        key=(window['seat'],window['seat_turn'],tuple(window['phases']))
        if key not in closure_cache:
            closure_cache[key]=next((e['seq'] for e in events if window_closed(window,[e])),None)
        return closure_cache[key]
    casts=[]; index=0; current=None
    for event in events:
        while index<len(deliveries) and deliveries[index]['seq']<=event['seq']:
            current=deliveries[index]; index+=1
        if event.get('actor')==actor and event.get('type') in {'cast','cast_transformed'}:
            origin=by_decision.get(event['cast_decision_id']) if 'cast_decision_id' in event else current
            casts.append({**event,'delivered_plan_id':origin.get('plan_id') if origin else None,
                          'decision_id':origin.get('decision_id') if origin else None})
    rows=[]; used=set()
    for plan_id, plan in plans.items():
        exposure=first_exposure.get(plan_id)
        items=plan.get('recommendations',[])
        eligible_by_intent={item['intent_id']:[e for e in casts if e['delivered_plan_id']==plan_id and e.get('card')==item['card']
                            and ('uid' not in item or e.get('uid')==item['uid'])] for item in items}
        exact={item['intent_id']:[e for e in eligible_by_intent[item['intent_id']] if in_window(e,item['window'])] for item in items}
        owners={}
        def assign(intent,seen):
            for event in exact[intent]:
                seq=event['seq']
                if seq in seen:continue
                seen.add(seq)
                if seq not in owners or assign(owners[seq],seen):
                    owners[seq]=intent
                    return True
            return False
        # Match in-window casts before allocating outside-window fallbacks. One
        # early miss must not steal a later recommendation's exact cast.
        for item in sorted(items,key=lambda i:len(exact[i['intent_id']])):assign(item['intent_id'],set())
        matched={intent:next(e for e in exact[intent] if e['seq']==seq) for seq,intent in owners.items()}
        used.update(owners)
        for item in items:
            closed=closed_at(item['window'])
            eligible=[e for e in eligible_by_intent[item['intent_id']] if e['seq'] not in used]
            inside=matched.get(item['intent_id'])
            cast=inside or next(iter(eligible),None)
            if cast:
                status='matched' if inside else 'cast_outside_window'; used.add(cast['seq'])
            elif exposure is None: status='never_delivered'
            elif closed is not None and closed<exposure: status='delivered_after_window'
            elif plan_id in superseded and (closed is None or superseded[plan_id]<=closed): status='superseded'
            elif 'condition' in item: status='conditional_review'
            elif closed is not None: status='window_closed_without_cast'
            else: status='pending_window'
            rows.append({'plan_id':plan_id,**item,'status':status,'cast_seq':cast['seq'] if cast else None,
                         'first_delivered_seq':exposure,'window_closed_seq':closed})
    groups={(r['plan_id'],r['alternative_group']) for r in rows if r.get('alternative_group') and r['status']=='matched'}
    for row in rows:
        if row.get('alternative_group') and (row['plan_id'],row['alternative_group']) in groups and row['status'] in {'window_closed_without_cast','conditional_review','pending_window'}:
            row['status']='alternative_satisfied'
    return {'recommendations':rows,
            'actual_casts':[{k:e.get(k) for k in ('seq','actor','card','uid','turn','active_player','seat_turn','phase','decision_id','delivered_plan_id')} |
                          {'status':'associated_recommendation' if e['seq'] in used else 'unplanned_cast'} for e in casts if e['seq']>since],
            'scope':'Factual cast/window comparison, not compliance or strategic grading. Casts count even if countered; resolution outcomes remain in history.'}
