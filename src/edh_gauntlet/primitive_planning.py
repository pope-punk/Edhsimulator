"""Seat-owned planning jobs for the primitive surface of split contract four.

Jobs freeze their input when claimed, publish stages exactly once and coalesce
later wakeups separately. No publication executes a proposed game action.
"""
from copy import deepcopy
import json
from .rules_adapter import digest
from .rules_state import RulesViolation

SHORT='short_term_planner';LONG='long_term_planner';DIPLOMAT='diplomacy'
STAGES={SHORT:('short_term','actions'),LONG:('long_term',),DIPLOMAT:('message',)}
PHASES=('precombat_main','combat','postcombat_main')


def text_field(value,name,maximum):
    result=value.get(name)
    if type(result) is not str or not result.strip() or len(result)>maximum:
        raise RulesViolation(f'{name} requires nonempty text of at most {maximum} characters')
    return result


def queue(state,actor,role,reason):
    seat=state['actors'][actor]
    job=seat['jobs'].get(role)
    if job:
        if (reason.startswith('invalid_goal:') and job.get('input') and job['input'].get('invalid_goal') and
                str((job['input'].get('invalid_goal') or {}).get('goal_id'))==reason.removeprefix('invalid_goal:')):
            return
        reasons=job.setdefault('queued',[]) if job.get('input') is not None else job['reasons']
        if reason not in reasons:reasons.append(reason)
    else:
        seat['next_job']+=1
        seat['jobs'][role]={'id':f'{actor}:{role}:{seat["next_job"]}',
                           'reasons':[reason],'input':None,'stage':0,'receipts':{},'queued':[]}


def observe(campaign,state):
    events=campaign.kernel.semantic_events
    for event in events[state.get('event_cursor',0):]:
        kind=event['kind']
        if kind=='mulligan_declared' and event['choice']=='keep':
            actor=event['actor'];state['actors'][actor]['kept']=True
            queue(state,actor,LONG,'opening_hand_kept')
            queue(state,actor,SHORT,'opening_hand_kept')
        if kind=='turn_began':
            completed=state.pop('cleanup_actor',None)
            if completed:queue(state,completed,SHORT,f'own_turn_complete:{event["index"]}')
            actor=event['active'];seat=state['actors'][actor]
            seat['turns']=seat.get('turns',0)+1
        if kind=='step_began' and event['step']=='end_step':
            players=campaign.kernel.state.live_players
            if event['active'] in players:
                index=players.index(event['active'])
                # No immediately preceding-seat gate. With two survivors only
                # own-cleanup maintenance remains; three seats use two steps away.
                if len(players)>=3:
                    actor=players[(index-2)%len(players)]
                    from .primitive_cadence import changed
                    wake=changed(campaign,state,actor)
                    campaign.record(actor,'planning_gate',{'gate':'opposite_end_step','wake':wake,'event':event['index']})
                    if wake:queue(state,actor,SHORT,f'pre_turn:{event["index"]}')
        if kind=='step_began' and event['step']=='cleanup':
            state['cleanup_actor']=event['active']
    state['event_cursor']=len(events)


def public_board(campaign):
    packets=[campaign.store.packet(actor) for actor in campaign.kernel.state.players]
    first=packets[0]
    board={key:deepcopy(first[key]) for key in ('turn','zones','combat','outcome')}
    board['players']=[{k:v for k,v in row.items() if k!='tagged_mana'} for row in first['players']]
    def common_frame(key,index=None):
        values=[p[key][index] if index is not None else p[key] for p in packets]
        if all(v==values[0] for v in values):return deepcopy(values[0])
        frame=values[0] or {}
        return {'kind':'effect','controller':frame.get('controller')}
    board['stack']=[common_frame('stack',i) for i in range(len(first['stack']))]
    board['resolving']=common_frame('resolving')
    return board


def claim(campaign,actor,role):
    if role not in STAGES:raise RulesViolation('Only a planning or diplomatic role can claim a job')
    with campaign.transaction() as state:
        if state['paused'] or state['blocker'] or state['terminal'] or state['pending']:
            raise RulesViolation('Planning admission is stopped')
        seat=state['actors'].get(actor)
        if seat is None or actor not in campaign.kernel.state.live_players:raise RulesViolation('Unavailable actor')
        job=seat['jobs'].get(role)
        if job is None or role in (SHORT,LONG) and not seat['kept']:return None
        if role==DIPLOMAT and not seat['plans'].get('diplomacy_brief'):return None
        if job['input'] is None:
            board=public_board(campaign) if role==DIPLOMAT else campaign.store.packet(actor)
            cursor=seat['evidence_cursor'].get(role,0)
            evidence=campaign.evidence(actor,after=cursor,kinds=('rationale',)) if role!=DIPLOMAT else []
            from .primitive_inspection import decision_records
            job['input']={'job_id':job['id'],'actor':actor,'role':role,'game':campaign.binding['game_number'],
                '_event_cursor':len(campaign.kernel.semantic_events),'_zone_cursor':campaign.kernel.state.event_count,
                'context_handling':1,'board':board,'snapshot':digest(board),'reasons':job['reasons'][:],
                'plans':deepcopy(seat['plans']),'target_seat_turn':max(1,seat.get('turns',0)+int(
                    campaign.kernel.active!=actor or campaign.kernel.phase in {'end_step','cleanup'})),
                'rationales':decision_records(evidence),
                'evidence_after':cursor,'evidence_through':campaign.evidence_position(actor) if role!=DIPLOMAT else cursor}
            if role==LONG:job['input'].update(seed=seat['seed'],personality=seat['personality'],invalid_goal=deepcopy(seat.get('invalid_goal')),brief_change_requests=deepcopy(seat.get('brief_change_requests',[])))
            elif role==SHORT:
                job['input']['standing']=seat['standing']
                from .primitive_cadence import summary
                seat['tactical_baseline']=summary(board,actor)
            else:
                job['input'].pop('plans')
                brief=seat['plans'].get('diplomacy_brief',{}).get('value',[])
                job['input'].update(**({'brief':deepcopy(brief)} if type(brief) is dict else {'authorized_messages':deepcopy(brief)}),
                    requests=deepcopy(seat.get('diplomacy_requests',[])),
                    holds=deepcopy({k:v for k,v in seat.get('diplomatic_holds',{}).items() if v['expires_turn']>campaign.kernel.state.turn_number}),
                    brief_id=seat['plans'].get('diplomacy_brief',{}).get('id'),personality=seat['personality'],
                    requires_public_post=any(r.startswith(('strategic_publication:','undelivered:')) for r in job['reasons']),
                    messages=deepcopy(state['messages'][-24:]))
            from .primitive_inspection import freeze
            job['input']['_knowledge']=freeze(campaign,actor,board) if role!=DIPLOMAT else {}
        return {**deepcopy(job['input']),'stage':STAGES[role][job['stage']]}


def validate_actions(value,job):
    if not {'action_sequence','phase_coverage'}<=set(value) or set(value)-{'action_sequence','phase_coverage','diplomacy_request'}:raise RulesViolation('Actions require action_sequence and phase_coverage')
    steps=value['action_sequence'];coverage=value['phase_coverage']
    if type(steps) is not list or len(steps)>64 or len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode())>12000:
        raise RulesViolation('Action proposals exceed the bound')
    if type(coverage) is not dict or set(coverage)!=set(PHASES):raise RulesViolation('Cover all three turn phases')
    ids=set();previous_window=None
    for index,step in enumerate(steps):
        if type(step) is not dict or set(step)!={'id','seat_turn','phase','command','rationale','scheduler'}:
            raise RulesViolation('Each step requires id, seat_turn, phase, command, rationale and scheduler')
        key=text_field(step,'id',48)
        if key in ids:raise RulesViolation('Duplicate proposal step ID')
        ids.add(key);text_field(step,'rationale',300)
        if step['phase'] not in PHASES or type(step['seat_turn']) is not int or step['seat_turn']<1:
            raise RulesViolation('Invalid proposal timing')
        window=(step['seat_turn'],PHASES.index(step['phase']))
        if previous_window is not None and window<previous_window:
            raise RulesViolation('Sequence steps must follow chronological turn and phase order')
        previous_window=window
        if any(r.startswith('pre_turn:') for r in job['reasons']) and step['seat_turn']!=job['input']['target_seat_turn']:
            raise RulesViolation('Pre-turn proposals must target the requested turn')
        if type(step['command']) is not dict or set(step['command']) & {'revision','actor','action_id'}:
            raise RulesViolation('Host supplies command revision, actor binding and action identity')
        if step['command'].get('kind') not in {'cast','activate','play_land','unlock_room','attack','block','damage','pass','answer','pay_mana','decline_cast','allocate_counters'}:
            raise RulesViolation('Unsupported proposed primitive command')
        from .primitive_actions import normalize_scheduler
        normalize_scheduler(step['scheduler'])
        from .primitive_batch_choices import validate as validate_choice
        validate_choice(steps,index)
    for phase,row in coverage.items():
        if type(row) is not dict or set(row)-{'status','reason'} or row.get('status') not in {'planned','no_action','reassess'}:
            raise RulesViolation('Invalid phase coverage')
        if row['status']!='planned':text_field(row,'reason',180)
        if (row['status']=='planned')!=any(s['phase']==phase for s in steps):raise RulesViolation('Phase coverage disagrees with proposed steps')


def publish(campaign,actor,role,job_id,stage,value):
    if role not in STAGES or type(value) is not dict:raise RulesViolation('Invalid role publication')
    with campaign.transaction() as state:
        if stage=='brief_decision':
            from .primitive_negotiation import decide_brief
            return decide_brief(campaign,state,actor,role,job_id,value)
        if stage!='short_term_and_actions':return _publish(campaign,state,actor,role,job_id,stage,value)
        if role!=SHORT or set(value)!={'short_term','actions'}:
            raise RulesViolation('Combined publication requires short_term and actions from the short-term planner')
        # Both stages commit together or neither does. Existing individual receipts
        # remain authoritative, so retrying cannot replay either accepted stage.
        first=_publish(campaign,state,actor,role,job_id,'short_term',value['short_term'])
        second=_publish(campaign,state,actor,role,job_id,'actions',value['actions'])
        return {'accepted':True,'components':{'short_term':first['component_id'],'actions':second['component_id']},'next':None}


def _publish(campaign,state,actor,role,job_id,stage,value):
    if type(value) is not dict:raise RulesViolation('Publication stage requires an object')
    if state['paused'] or state['blocker'] or state['terminal'] or state['pending']:
        raise RulesViolation('Publication is stopped')
    seat=state['actors'][actor];job=seat['jobs'].get(role)
    # Completed-stage receipts survive job completion and future jobs.
    receipt_key=job_id+':'+stage
    receipt=campaign.store.connection.execute('SELECT actor,role,input_sha,receipt FROM host_publications WHERE id=?',(receipt_key,)).fetchone()
    if receipt:
        if receipt[:3]!=(actor,role,digest(value)):raise RulesViolation('Accepted stage cannot be replaced')
        return json.loads(receipt[3])
    if job is None or job['id']!=job_id or job['input'] is None or STAGES[role][job['stage']]!=stage:
        raise RulesViolation('Publication does not own this frozen stage')
    if stage=='long_term':
        if not {'long_term_plan','diplomacy'}<=set(value) or set(value)-{'long_term_plan','diplomacy'}:raise RulesViolation('Strategic publication requires goal and diplomacy authorization')
        text_field(value,'long_term_plan',1200)
        if (job['input'].get('invalid_goal') and
                job['input']['invalid_goal']['goal_id']==seat['plans'].get('long_term',{}).get('id') and
                value['long_term_plan']==seat['plans'].get('long_term',{}).get('value',{}).get('long_term_plan')):
            raise RulesViolation('An invalid current goal requires revised strategic prose')
        messages=value['diplomacy']
        if type(messages) is dict:
            from .primitive_negotiation import brief
            brief(messages,actor,state['actors'])
        else:
            if type(messages) is not list or not 1<=len(messages)<=8:raise RulesViolation('Authorize at least one bounded public message')
            seen=set()
            for row in messages:
                if type(row) is not dict or not {'id','text','expires_turn'}<=set(row) or set(row)-{'id','text','expires_turn','to','reply_to'}:
                    raise RulesViolation('Invalid authorized message')
                recipients=row.get('to',[])
                if type(recipients) is not list or any(type(p) is not str or p not in state['actors'] or p==actor for p in recipients) or len(set(recipients))!=len(recipients):
                    raise RulesViolation('Address only distinct other seats')
                if row.get('reply_to') is not None and (type(row['reply_to']) is not str or len(row['reply_to'])>300 or not campaign.store.connection.execute('SELECT 1 FROM host_messages WHERE id=?',(row['reply_to'],)).fetchone()):
                    raise RulesViolation('Reply must name a committed public message')
                key=text_field(row,'id',80);text_field(row,'text',300)
                if key in seen or type(row['expires_turn']) is not int or row['expires_turn']<campaign.kernel.state.turn_number:
                    raise RulesViolation('Duplicate or expired diplomatic authorization')
                seen.add(key)
    elif stage=='short_term':
        required={'short_term_plan','continuity','long_term_validity','long_term_invalid_reason'}
        if not required<=set(value) or set(value)-required-{'dependencies'}:
            raise RulesViolation('Supply tactical prose, continuity and strategic validity')
        text_field(value,'short_term_plan',600);text_field(value,'continuity',1200)
        if value['long_term_validity'] not in {'valid','invalid','pending'}:raise RulesViolation('Invalid strategic assessment')
        if (value['long_term_validity']=='pending') != ('long_term' not in job['input']['plans']):
            raise RulesViolation('Use pending exactly when this frozen input has no long-term goal')
        if value['long_term_validity']=='invalid':text_field(value,'long_term_invalid_reason',300)
        elif type(value['long_term_invalid_reason']) is not str:raise RulesViolation('Validity reason must be text')
        from .primitive_dependencies import freeze
        dependencies=freeze(job['input']['board'],value.get('dependencies',[]))
    elif stage=='actions':
        validate_actions(value,job)
        if 'diplomacy_request' in value:
            if job['stage']<1:raise RulesViolation('Publish initial tactical prose before requesting diplomacy')
            request=value['diplomacy_request']
            if type(request) is not dict or set(request)!={'objective','player'} or request['player'] not in state['actors'] or request['player']==actor:raise RulesViolation('Diplomacy request requires objective and opposing player')
            text_field(request,'objective',600)
            pending=seat.setdefault('diplomacy_requests',[])
            pending.append({'id':receipt_key,**deepcopy(request)})
            seat['diplomacy_requests']=pending[-4:]
            if type(seat['plans'].get('diplomacy_brief',{}).get('value')) is dict:queue(state,actor,DIPLOMAT,'tactical_request:'+receipt_key)
    elif stage=='message':
        from .primitive_diplomacy import prepare
        prepare(campaign,state,actor,job,receipt_key,value)
    component_value={'long_term_plan':value['long_term_plan']} if stage=='long_term' else deepcopy(value)
    component={'id':digest({'stage':stage,'value':component_value}),'job_id':job_id,'value':component_value}
    old=seat['plans'].get(stage)
    diplomacy_review=bool(job['reasons']) and all(r.startswith('diplomat_request:') for r in job['reasons'])
    if stage=='long_term' and diplomacy_review:
        decision=job.get('brief_decision')
        if decision is None:raise RulesViolation('Decide the brief change first with brief_decision')
        if value['diplomacy']!=seat['plans']['diplomacy_brief']['value']:raise RulesViolation('Keep the approved or veto-retained brief in this diplomatic review')
    if stage=='short_term':
        component['assessed_goal']=job['input']['plans'].get('long_term',{}).get('id')
        component['id']=digest({'stage':stage,'value':component_value,'assessed_goal':component['assessed_goal']})
        if old is None or old['id']!=component['id']:seat['plans'].pop('actions',None)
        seat['tactical_dependencies']={'component_id':component['id'],'goal_id':component['assessed_goal'],
                                      'values':dependencies}
    if stage=='actions':
        component['short_term_id']=seat['plans'].get('short_term',{}).get('id')
        component['id']=digest({'stage':stage,'value':component_value,'short_term_id':component['short_term_id']})
    if stage!='message':seat['plans'][stage]=component
    else:
        consumed={r['id'] for r in job['input'].get('requests',[])}
        seat['diplomacy_requests']=[r for r in seat.get('diplomacy_requests',[]) if r['id'] not in consumed]
    if stage=='long_term':
        brief={'id':digest({'stage':'diplomacy_brief','value':value['diplomacy']}),'job_id':job_id,'value':deepcopy(value['diplomacy'])}
        seat['plans']['diplomacy_brief']=brief
        campaign.record(actor,'publication',{'role':role,'stage':'diplomacy_brief',**brief})
        if not seat.get('invalid_goal') or seat['invalid_goal']['goal_id']!=component['id']:
            seat['invalid_goal']=None
    campaign.record(actor,'publication',{'role':role,'stage':stage,**component})
    if stage=='long_term':
        if old is None or seat.get('invalid_goal') or any(r.startswith(('invalid_goal:','pilot_alarm:','diplomatic_override:')) for r in job['reasons']):
            queue(state,actor,SHORT,'strategic_publication:'+job_id)
        if not diplomacy_review:queue(state,actor,DIPLOMAT,'strategic_publication:'+job_id)
    if stage=='short_term' or stage=='long_term' and old is not None and old['id']!=component['id']:
        dependency=seat.get('tactical_dependencies',{})
        goal=seat['plans'].get('long_term',{}).get('id')
        if dependency.get('values') and dependency.get('goal_id')!=goal:
            from .primitive_dependencies import changed
            paths=changed(campaign.store.packet(actor),dependency['values'])
            if paths:
                reason='changed_dependencies:'+digest({'tactical':dependency['component_id'],'goal':goal})
                queue(state,actor,SHORT,reason)
                campaign.record(actor,'dependency_review',{'reason':reason,'paths':paths,'goal_id':goal,
                                                          'short_term_id':dependency['component_id']})
    if stage=='short_term' and value['long_term_validity']=='invalid':
        assessed=job['input']['plans'].get('long_term',{}).get('id')
        current_goal=seat['plans'].get('long_term',{}).get('id')
        if assessed==current_goal:
            seat['invalid_goal']={'goal_id':assessed,'reason':value['long_term_invalid_reason']}
            queue(state,actor,LONG,'invalid_goal:'+str(assessed))
    job['stage']+=1
    next_stage=STAGES[role][job['stage']] if job['stage']<len(STAGES[role]) else None
    result={'accepted':True,'component_id':component['id'],'next':next_stage}
    campaign.store.connection.execute('INSERT INTO host_publications VALUES (?,?,?,?,?)',(receipt_key,actor,role,digest(value),json.dumps(result)))
    if next_stage is None:
        seat['evidence_cursor'][role]=job['input']['evidence_through']
        queued=job['queued'];del seat['jobs'][role]
        for reason in queued:queue(state,actor,role,reason)
    from .primitive_diplomacy import flush_state
    flush_state(campaign,state)
    return result
