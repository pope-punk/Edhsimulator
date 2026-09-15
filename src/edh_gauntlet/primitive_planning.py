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
        if kind=='turn_began':
            actor=event['active'];seat=state['actors'][actor]
            seat['turns']=seat.get('turns',0)+1
        if kind=='step_began' and event['step']=='end_step':
            players=campaign.kernel.state.live_players
            if event['active'] in players:
                index=players.index(event['active'])
                upcoming=[players[(index+i)%len(players)] for i in range(1,len(players))][:2]
                for actor in upcoming:queue(state,actor,SHORT,f'pre_turn:{event["index"]}')
        if kind=='step_began' and event['step']=='cleanup':
            queue(state,event['active'],SHORT,f'own_turn_complete:{event["index"]}')
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
        if job is None:return None
        if job['input'] is None:
            board=public_board(campaign) if role==DIPLOMAT else campaign.store.packet(actor)
            cursor=seat['evidence_cursor'].get(role,0)
            evidence=campaign.evidence(actor,after=cursor) if role!=DIPLOMAT else []
            job['input']={'job_id':job['id'],'actor':actor,'role':role,'game':1,
                'context_handling':1,'board':board,'snapshot':digest(board),'reasons':job['reasons'][:],
                'plans':deepcopy(seat['plans']),'target_seat_turn':max(1,seat.get('turns',0)+int(
                    campaign.kernel.active!=actor or campaign.kernel.phase in {'end_step','cleanup'})),
                'rationales':[row for row in evidence if row['kind']=='rationale'],
                'evidence_after':cursor,'evidence_through':evidence[-1]['id'] if evidence else cursor}
            if role==LONG:job['input'].update(seed=seat['seed'],personality=seat['personality'],invalid_goal=deepcopy(seat.get('invalid_goal')))
            elif role==SHORT:job['input']['standing']=seat['standing']
            else:
                job['input'].pop('plans')
                brief=seat['plans'].get('diplomacy_brief',{}).get('value',[])
                job['input'].update(authorized_messages=deepcopy(brief),personality=seat['personality'],
                    requires_public_post=any(r.startswith('strategic_publication:') for r in job['reasons']),
                    messages=deepcopy(state['messages'][-24:]))
            from .primitive_inspection import freeze
            job['input']['_knowledge']=freeze(campaign,actor,board)
        return {**deepcopy(job['input']),'stage':STAGES[role][job['stage']]}


def validate_actions(value,job):
    if set(value)!={'action_sequence','phase_coverage'}:raise RulesViolation('Actions require action_sequence and phase_coverage')
    steps=value['action_sequence'];coverage=value['phase_coverage']
    if type(steps) is not list or len(steps)>16 or len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode())>12000:
        raise RulesViolation('Action proposals exceed the bound')
    if type(coverage) is not dict or set(coverage)!=set(PHASES):raise RulesViolation('Cover all three turn phases')
    ids=set()
    for step in steps:
        if type(step) is not dict or set(step)!={'id','seat_turn','phase','command','rationale','scheduler'}:
            raise RulesViolation('Each step requires id, seat_turn, phase, command, rationale and scheduler')
        key=text_field(step,'id',48)
        if key in ids:raise RulesViolation('Duplicate proposal step ID')
        ids.add(key);text_field(step,'rationale',300)
        if step['phase'] not in PHASES or type(step['seat_turn']) is not int or step['seat_turn']<1:
            raise RulesViolation('Invalid proposal timing')
        if any(r.startswith('pre_turn:') for r in job['reasons']) and step['seat_turn']!=job['input']['target_seat_turn']:
            raise RulesViolation('Pre-turn proposals must target the requested turn')
        if type(step['command']) is not dict or set(step['command']) & {'revision','actor','action_id'}:
            raise RulesViolation('Host supplies command revision, actor binding and action identity')
        if step['command'].get('kind') not in {'cast','activate','play_land','unlock_room','attack','block','damage','pass','answer','pay_mana','decline_cast','allocate_counters'}:
            raise RulesViolation('Unsupported proposed primitive command')
        from .scheduler import normalize_directive
        normalize_directive(step['scheduler'])
    for phase,row in coverage.items():
        if type(row) is not dict or set(row)-{'status','reason'} or row.get('status') not in {'planned','no_action','reassess'}:
            raise RulesViolation('Invalid phase coverage')
        if row['status']!='planned':text_field(row,'reason',180)
        if (row['status']=='planned')!=any(s['phase']==phase for s in steps):raise RulesViolation('Phase coverage disagrees with proposed steps')


def publish(campaign,actor,role,job_id,stage,value):
    if role not in STAGES or type(value) is not dict:raise RulesViolation('Invalid role publication')
    with campaign.transaction() as state:
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
            if set(value)!={'long_term_plan','diplomacy'}:raise RulesViolation('Strategic publication requires goal and diplomacy authorization')
            text_field(value,'long_term_plan',1200)
            if (seat.get('invalid_goal') and
                    value['long_term_plan']==seat['plans'].get('long_term',{}).get('value',{}).get('long_term_plan')):
                raise RulesViolation('An invalid current goal requires revised strategic prose')
            messages=value['diplomacy']
            if type(messages) is not list or not 1<=len(messages)<=8:raise RulesViolation('Authorize at least one bounded public message')
            seen=set()
            for row in messages:
                if type(row) is not dict or set(row)!={'id','text','expires_turn'}:raise RulesViolation('Invalid authorized message')
                key=text_field(row,'id',80);text_field(row,'text',300)
                if key in seen or type(row['expires_turn']) is not int or row['expires_turn']<campaign.kernel.state.turn_number:
                    raise RulesViolation('Duplicate or expired diplomatic authorization')
                seen.add(key)
        elif stage=='short_term':
            if set(value)!={'short_term_plan','continuity','long_term_validity','long_term_invalid_reason'}:
                raise RulesViolation('Supply tactical prose, continuity and strategic validity')
            text_field(value,'short_term_plan',600);text_field(value,'continuity',1200)
            if value['long_term_validity'] not in {'valid','invalid'}:raise RulesViolation('Invalid strategic assessment')
            if value['long_term_validity']=='invalid':text_field(value,'long_term_invalid_reason',300)
            elif type(value['long_term_invalid_reason']) is not str:raise RulesViolation('Validity reason must be text')
        elif stage=='actions':validate_actions(value,job)
        elif stage=='message':
            if set(value)!={'authorized_ids'} or type(value['authorized_ids']) is not list:raise RulesViolation('Select authorized public messages by ID')
            ids=value['authorized_ids'];authorized={m['id']:m for m in job['input']['authorized_messages']
                        if m['expires_turn']>=campaign.kernel.state.turn_number}
            if len(set(ids))!=len(ids) or any(key not in authorized for key in ids):raise RulesViolation('Message authorization is missing or expired')
            if not ids and job['input']['requires_public_post'] and authorized:raise RulesViolation('A strategic review requires an authorized public post')
            if not ids and job['input']['requires_public_post'] and not authorized:queue(state,actor,LONG,'renew_expired_diplomacy')
            posted=0
            for key in ids:
                message={'id':receipt_key+':'+key,'actor':actor,'text':authorized[key]['text'],'turn':campaign.kernel.state.turn_number}
                # Exact repeated speech is retained as a suppressed publication,
                # never posted twice by retries or duplicate authorizations.
                normalized=' '.join(message['text'].split())
                if not campaign.store.connection.execute('SELECT 1 FROM host_messages WHERE actor=? AND text=?',(actor,normalized)).fetchone():
                    campaign.store.connection.execute('INSERT INTO host_messages VALUES (?,?,?,?)',(message['id'],actor,normalized,json.dumps(message)))
                    posted+=1
                    state['messages']=(state['messages']+[message])[-24:]
                    for recipient in state['actors']:
                        campaign.record(recipient,'message',message)
                        if recipient!=actor:queue(state,recipient,DIPLOMAT,'incoming:'+message['id'])
            if ids and not posted and job['input']['requires_public_post']:
                queue(state,actor,LONG,'renew_duplicate_diplomacy:'+job_id)
        component_value={'long_term_plan':value['long_term_plan']} if stage=='long_term' else deepcopy(value)
        component={'id':digest({'stage':stage,'value':component_value}),'job_id':job_id,'value':component_value}
        old=seat['plans'].get(stage)
        if stage=='short_term':
            component['assessed_goal']=job['input']['plans'].get('long_term',{}).get('id')
            component['id']=digest({'stage':stage,'value':component_value,'assessed_goal':component['assessed_goal']})
            if old is None or old['id']!=component['id']:seat['plans'].pop('actions',None)
        if stage=='actions':
            component['short_term_id']=seat['plans'].get('short_term',{}).get('id')
            component['id']=digest({'stage':stage,'value':component_value,'short_term_id':component['short_term_id']})
        if stage!='message':seat['plans'][stage]=component
        if stage=='long_term':
            brief={'id':digest({'stage':'diplomacy_brief','value':value['diplomacy']}),'job_id':job_id,'value':deepcopy(value['diplomacy'])}
            seat['plans']['diplomacy_brief']=brief
            campaign.record(actor,'publication',{'role':role,'stage':'diplomacy_brief',**brief})
            seat['invalid_goal']=None
        campaign.record(actor,'publication',{'role':role,'stage':stage,**component})
        if stage=='long_term':
            if old is None or seat.get('invalid_goal') or any(r.startswith(('invalid_goal:','pilot_alarm:')) for r in job['reasons']):
                queue(state,actor,SHORT,'strategic_publication:'+job_id)
            queue(state,actor,DIPLOMAT,'strategic_publication:'+job_id)
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
        return result
