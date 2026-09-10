"""Bounded symbolic proposals and exact, pilot-approved choice matching.

No policy evaluation or text/menu-number parsing: only current legal option
identities can execute. Unknown option representations always require a pilot.
"""
from __future__ import annotations

import json
from .runtime_store import identity

PHASES=('precombat_main','combat','postcombat_main')
MAX_STEPS=16
MAX_BYTES=12000


def proposal_readiness(plan,actor,request,executed_ids=()):
    """Factual timing/choice compatibility only, never an approval or policy."""
    board=request.get('public_state',{});clock=board.get('planning_clock',{})
    turn=clock.get('seat_turns',{}).get(actor,0)
    active=clock.get('active_player',board.get('active'))
    phase_order={'upkeep':-2,'draw':-1,'precombat_main':0,'combat':1,'postcombat_main':2,'end_step':3,'cleanup':4}
    current_phase=phase_order.get(request.get('phase'))
    result={'expired_ids':[],'future_ids':[],'timely_ids':[],'matches_current_choice_ids':[]}
    if executed_ids:result['executed_ids']=list(executed_ids)
    for step in plan.get('action_sequence',[]):
        if step['id'] in executed_ids:continue
        if step['seat_turn']<turn or step['seat_turn']==turn and (active!=actor or current_phase is not None and phase_order[step['phase']]<current_phase):
            result['expired_ids'].append(step['id'])
        elif step['seat_turn']>turn:result['future_ids'].append(step['id'])
        else:
            result['timely_ids'].append(step['id'])
            if request.get('kind') in {'main_action','land_play'} and not guards_hold(step.get('requires',[]),board):
                try:match(step,request)
                except ValueError as error:
                    choice=step.get('choice')
                    if str(error)=='unavailable_or_ambiguous_choice' and isinstance(choice,dict) and choice.get('action') in {'cast','commander'}:
                        candidates=[row['value'] for row in request.get('symbolic_options',[]) if
                            isinstance(row.get('value'),dict) and row['value'].get('action') in {'cast','commander'} and
                            row['value'].get('source')==choice.get('source')]
                        # Exact legal alternatives are information, never an
                        # implicit override or an execution match.
                        if candidates and len(result.get('current_choice_alternatives',[]))<3:
                            prior=result.get('current_choice_alternatives',[])
                            entry={'step_id':step['id'],'reason':str(error),'legal_choices':[], 'choices_omitted':len(candidates)}
                            for candidate in candidates[:4]:
                                trial={**entry,'legal_choices':entry['legal_choices']+[candidate],
                                       'choices_omitted':entry['choices_omitted']-1}
                                if size(prior+[trial])>1800:break
                                entry=trial
                            if entry['legal_choices']:result['current_choice_alternatives']=prior+[entry]
                    continue
                result['matches_current_choice_ids'].append(step['id'])
    return result


def size(value):
    return len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8'))


def symbol(value, depth=0):
    from .engine import CardObj, Perm, PlayerState
    if depth>8:raise ValueError('Option is too deeply nested')
    if isinstance(value,(CardObj,Perm)):return {'uid':value.uid}
    if isinstance(value,PlayerState):return {'seat':value.name}
    if value is None or type(value) in (bool,int,str):return value
    if isinstance(value,tuple) and len(value)==3 and isinstance(value[0],str):
        return {'action':value[0],'source':symbol(value[1],depth+1),'args':symbol(value[2],depth+1)}
    if isinstance(value,(list,tuple)):return [symbol(item,depth+1) for item in value]
    if isinstance(value,dict) and all(isinstance(key,str) for key in value):
        return {key:symbol(item,depth+1) for key,item in value.items()}
    raise ValueError('Option has no stable symbolic representation')


def options(objects):
    result=[]
    for obj in objects:
        try:
            value=symbol(obj)
            result.append({'value':value} if size(value)<=1500 else {'manual':True})
        except ValueError:result.append({'manual':True})
    return result


def _refs(value, board, uids):
    if isinstance(value,dict):
        if 'uid' in value and (set(value)!={'uid'} or value['uid'] not in uids):
            raise ValueError('Choice UID must be visible in the frozen input')
        if 'seat' in value and (set(value)!={'seat'} or value['seat'] not in board.get('players',{})):
            raise ValueError('Choice seat must be a known player')
        for item in value.values():_refs(item,board,uids)
    elif isinstance(value,list):
        for item in value:_refs(item,board,uids)


def proposals(values, actor, board, uids):
    from .scheduler import normalize_directive
    if not isinstance(values,list) or len(values)>MAX_STEPS or size(values)>MAX_BYTES:
        raise ValueError('action_sequence is limited to 16 steps and 12,000 UTF-8 bytes')
    result=[];ids=set()
    for raw in values:
        if not isinstance(raw,dict) or set(raw)-{'id','phase','kind','choice','rationale','scheduler','requires','seat_turn'}:
            raise ValueError('Unsupported action-sequence fields')
        step=dict(raw)
        for key,limit in (('id',48),('kind',80),('rationale',300)):
            if not isinstance(step.get(key),str) or not step[key].strip() or len(step[key])>limit:
                raise ValueError(f'{key} requires nonempty text of at most {limit} characters')
        if step['id'] in ids:raise ValueError('Sequence step IDs must be unique')
        ids.add(step['id'])
        if step.get('phase') not in PHASES:raise ValueError('Sequence phases are precombat_main, combat, postcombat_main')
        turn=step.get('seat_turn')
        if type(turn) is not int or not 1<=turn<=1000000:raise ValueError('seat_turn must be a positive ordinal')
        if turn<board.get('planning_clock',{}).get('seat_turns',{}).get(actor,0):
            raise ValueError('Sequence predates the frozen seat turn')
        if 'choice' not in step:raise ValueError('Each step requires an exact symbolic choice; null means PASS')
        if size(step['choice'])>1500:raise ValueError('Symbolic choice exceeds 1,500 bytes')
        _refs(step['choice'],board,uids)
        step['scheduler']=normalize_directive(step.get('scheduler'))
        if step['scheduler']['mode']=='snooze_stack':raise ValueError('Use resolve_my_sequence')
        if len(step['scheduler'].get('objects',[]))>16:raise ValueError('At most 16 snoozed objects per step')
        if any(uid not in uids for uid in step['scheduler'].get('objects',[])):raise ValueError('Unknown snooze object')
        guards=step.get('requires',[])
        if not isinstance(guards,list) or len(guards)>8:raise ValueError('At most eight prerequisites per step')
        for guard in guards:
            if (not isinstance(guard,dict) or set(guard)!={'path','op','value'} or
                    not isinstance(guard['path'],str) or not guard['path'].startswith('/') or len(guard['path'])>200 or
                    guard['op'] not in {'eq','gte','lte','present'} or size(guard['value'])>300):
                raise ValueError('Prerequisite requires bounded path, op=eq/gte/lte/present and value')
            if guard['op']=='present' and type(guard['value']) is not bool:raise ValueError('present requires a boolean')
            if guard['op'] in {'gte','lte'} and type(guard['value']) not in (int,float):raise ValueError('Threshold requires a number')
        step['requires']=guards
        result.append(step)
    return result


def approve(value, plan, actor, board, uids, *, concise_overrides=False):
    if not isinstance(value,dict) or set(value)-{'approve','reject','overrides','add','resume_after_passes','pass_priority','rejection_rationale'} or size(value)>MAX_BYTES:
        raise ValueError('Batch requires approve IDs, reject IDs and optional overrides/add, within 12,000 bytes')
    if 'rejection_rationale' in value and (not isinstance(value['rejection_rationale'],str)
            or not value['rejection_rationale'].strip() or len(value['rejection_rationale'])>300):
        raise ValueError('rejection_rationale must be nonempty text of at most 300 characters')
    if type(value.get('resume_after_passes',False)) is not bool:
        raise ValueError('resume_after_passes must be a boolean')
    if type(value.get('pass_priority',False)) is not bool:
        raise ValueError('pass_priority must be a boolean')
    if 'pass_priority' in value and not concise_overrides:
        raise ValueError('pass_priority requires the game-bound turn_batches policy')
    steps={step['id']:step for step in plan.get('action_sequence',[])}
    added=proposals(value.get('add',[]),actor,board,uids)
    if any(step['id'] in steps for step in added):raise ValueError('Added step IDs must be new; use overrides for existing IDs')
    steps.update({step['id']:step for step in added})
    ordered=value.get('approve');rejected=value.get('reject')
    if not isinstance(ordered,list) or not ordered or not isinstance(rejected,list):
        raise ValueError('Approve at least one step in execution order; reject all other IDs explicitly')
    all_ids=ordered+rejected
    if any(not isinstance(key,str) for key in all_ids) or len(set(all_ids))!=len(all_ids) or set(all_ids)!=set(steps):
        raise ValueError('Approve or reject every recommendation exactly once')
    if any(step['id'] not in ordered for step in added):raise ValueError('Every added step must appear in approve')
    overrides=value.get('overrides',{})
    if not isinstance(overrides,dict) or set(overrides)-set(ordered):raise ValueError('Overrides must name approved IDs')
    selected=[]
    for key in ordered:
        edit=overrides.get(key,{})
        if not isinstance(edit,dict) or set(edit)-{'choice','rationale','scheduler','requires'}:
            raise ValueError('Overrides can change choice, rationale, scheduler and prerequisites')
        selected.append({**steps[key],**edit})
    selected=proposals(selected,actor,board,uids)
    if concise_overrides:
        for step in selected:
            original=steps[step['id']]
            if all(step.get(key,[])==original.get(key,[]) for key in ('choice','scheduler','requires')):
                step['rationale']=original['rationale']
    if len({step['seat_turn'] for step in selected})!=1:raise ValueError('An approval covers one own turn only')
    if any(PHASES.index(a['phase'])>PHASES.index(b['phase']) for a,b in zip(selected,selected[1:])):
        raise ValueError('Approved order cannot go backwards through phases')
    if any(step['scheduler']['mode']=='snooze_table' for step in selected[:-1]):
        raise ValueError('Table snooze is allowed only on the final approved step; it could suppress later actions')
    return selected


def pointer(board,path):
    node=board
    for part in path.split('/')[1:]:
        part=part.replace('~1','/').replace('~0','~')
        if isinstance(node,list):
            matches=[item for item in node if isinstance(item,dict) and item.get('uid')==part]
            if len(matches)!=1:return False,None
            node=matches[0]
        elif isinstance(node,dict) and part in node:node=node[part]
        else:return False,None
    return True,node


def guards_hold(guards,board):
    for guard in guards:
        present,value=pointer(board,guard['path']);op=guard['op'];expected=guard['value']
        if op=='present':ok=present==expected
        elif not present:ok=False
        elif op=='eq':ok=value==expected
        else:ok=type(value) in (int,float) and (value>=expected if op=='gte' else value<=expected)
        if not ok:return guard['path']
    return None


def match(step,request):
    if request.get('response_type') in {'block_declaration','combat_damage'}:raise ValueError('manual_choice_required')
    if step['kind']!=request['kind'] or step['phase']!=request['phase']:raise ValueError('unapproved_decision')
    if 'symbolic_options' not in request:raise ValueError('manual_choice_required')
    if request.get('messageboard',{}).get('opening_salutation_required'):raise ValueError('opening_salutation_required')
    choice=step['choice']
    if isinstance(choice,dict) and choice.get('action','').startswith(('messageboard','propose_combo','concede')):
        raise ValueError('manual_choice_required')
    if choice is None:
        if not request['allow_pass'] or request.get('required_indexes'):raise ValueError('required_choice')
        return [] if request.get('multi_select') else None
    def one(value):
        matches=[i for i,row in enumerate(request['symbolic_options']) if 'value' in row and identity(row['value'])==identity(value)]
        if len(matches)!=1:raise ValueError('unavailable_or_ambiguous_choice')
        return matches[0]
    if request.get('multi_select'):
        if not isinstance(choice,list):raise ValueError('multi_select_requires_list')
        from .decision_selection import validate_count
        indexes=[one(item) for item in choice]
        validate_count(request,indexes)
        if len(set(indexes))!=len(indexes) or not set(request.get('required_indexes',[])).issubset(indexes):
            raise ValueError('required_or_duplicate_choice')
        if not indexes and not request['allow_pass']:raise ValueError('required_choice')
        return indexes
    return one(choice)


def cast_recommendations(steps,actor,board):
    names={}
    for player in board.get('players',{}).values():
        for zone in ('hand','battlefield','graveyard','exile','commander'):
            values=player.get(zone,[])
            if isinstance(values,(dict,str)):values=[values]
            for value in values or []:
                if isinstance(value,str) and ':' in value:
                    uid,name=value.split(':',1);names[uid]=name
                elif isinstance(value,dict) and value.get('uid') and value.get('name'):
                    names[value['uid']]=value['name']
    result=[]
    for step in steps:
        choice=step['choice']
        if not isinstance(choice,dict) or choice.get('action') not in {'cast','commander'}:continue
        source=choice.get('source') or {};uid=source.get('uid') if isinstance(source,dict) else None
        if uid in names:result.append({'intent_id':step['id'],'action':'cast','card':names[uid],'uid':uid,
            'window':{'seat':actor,'seat_turn':step['seat_turn'],'phases':[step['phase']]}})
    return result
