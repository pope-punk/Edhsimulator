"""Role ownership and scheduling layered on the contract-4 planner workboard.

No transport, gameplay choices, or second packet archive lives here. Immutable
inputs, component publications and compatibility plan views use existing stores.
"""
from .background_slots import reservation

import time
from .agent_architecture import SHORT,LONG,DIPLOMACY,enabled
from .runtime_store import read,write,get,put,identity,locked
from . import component_store as components


def expand(root,game,boundaries):
    result=[]
    for item in boundaries:
        if 'role' in item:result.append(item);continue
        reason=item.get('reason');roles=[SHORT]
        if reason=='standing_initialization' or item.get('long_term_requested') or item.get('scope')=='long_term':roles=[LONG]
        if reason=='opening_hand_settled':roles=[LONG,SHORT]
        for role in roles:
            result.append({**item,'role':role,'cadence_id':item['cadence_id']+'|'+role,
                           'scope':'standing' if reason=='standing_initialization' else 'long_term' if role==LONG else 'short_term'})
    return result


def eligible(root,game,state,pending):
    if not enabled(root,game):return pending
    values={actor:components.current(root,game,actor) for actor in {j['actor'] for j in pending}}
    long_pending={j['actor'] for j in pending if j.get('role')==LONG}
    return [j for j in pending if j.get('role')==LONG and
            (j['scope']=='standing' or 'standing' in values[j['actor']]) or
            j.get('role')==SHORT and {'standing','long_term'}<=set(values[j['actor']]) and (state.get('role_slots') in {1,2} or j['actor'] not in long_pending) or
            j.get('role')==DIPLOMACY and (state.get('role_slots') in {1,2} or j['mandatory'] or j['actor'] not in long_pending)]


def cursor(root,game,actor,role):
    # Publication coverage is separate from unchanged component identity.
    d=components.directory(root,game)
    row=read(d/'role_coverage'/(identity([actor,role])+'.json'),{})
    from .planner_runtime import _compatible
    return row.get('event_seq',0) if row and _compatible(row['source_session'],root,game,actor) else 0


def sort_pending(root,game,pending):
    if not pending:return
    urgent=None
    if enabled(root,game):
        action=read(components.directory(root,game).parent.parent/'NEXT_ACTION.json',{}).get('next_action',{})
        actor=action.get('actor')
        if actor:
            current=components.current(root,game,actor)
            if not {'standing','long_term'}<=set(current):urgent=actor
    from .planner_runtime import _state
    state_concurrent=_state(components.directory(root,game)).get('role_slots') in {1,2}
    def priority(job):
        if state_concurrent and job.get('role')==SHORT and 'short_term' not in components.current(root,game,job['actor']):return -1
        if state_concurrent and time.time()-job['queued_at']>=120:return 0
        if job.get('role')==LONG and job['actor']==urgent:return 0
        # Finish the brief -> public-post transaction before routine planning
        # can consume its validity window. Publication still validates against
        # current facts; a queued strategic watch is not itself revocation.
        if job.get('role')==DIPLOMACY and job['mandatory']:return 1
        # An explicit blocked tactical/authorization question must release its
        # dependent work before another routine maintenance batch. No new wake.
        if job.get('role')==LONG and job.get('requirements',{}).get('request_id'):return 2
        if job.get('role')==SHORT and job.get('requirements',{}).get('reason') in {'strategic_answer','material_goal_revision'}:return 2
        if job.get('role')==SHORT and job.get('requirements',{}).get('full_turn_batch_required'):return 2
        return 3 if job['mandatory'] else 4
    def sort_key(job):
        rank=priority(job)
        return (rank,job.get('requirements',{}).get('preceding_opponent_turns',3) if rank==2 else 0,
                job['queued_at'],job['id'])
    pending.sort(key=sort_key)


def stages(value):
    if value['role']==LONG:return ['standing'] if value['standing_only'] else ['long_term']
    return ['short_term','actions']


def fields(stage):
    from .planner_stages import FIELDS
    extra={'short_term':{'strategic_disposition','strategic_review'},'actions':{'combo_proposal','phase_coverage'},
           'long_term':{'dependencies','watches','diplomacy_brief','diplomacy_brief_action'}}
    from .goal_validity import FIELDS as VALIDITY_FIELDS
    return FIELDS[stage]|extra.get(stage,set())|(VALIDITY_FIELDS if stage=='short_term' else set())


def instruction(stage,boundaries=()):
    from .planner_stages import instruction as base
    value=base(stage,True,boundaries);value['fields']=sorted(fields(stage))
    if stage=='actions':value['fields'].remove('phase_coverage')
    if stage=='standing':
        value['target_words']=280
        value['instruction']+=' Output budget: aim for about 280 words total, preferably six compact functional groups. This is a soft drafting target below the unchanged 3600-character maximum. Card names count toward the budget. Preserve concrete engines, win routes and recovery; omit redundant examples. Do not aim near the hard character ceiling.'
    elif stage in {'short_term','long_term'}:
        value['target_words']=60 if stage=='short_term' else 130
        value['instruction']+=f" Aim for about {value['target_words']} words, while respecting the existing character limits."
    if stage=='short_term':
        value['strategic_disposition']=['continue','review_requested','review_pending']
        value['instruction']+=' Include strategic_disposition. continue needs no extra prose. Escalate a lost route, acquired missing pieces, obsolete survival assumptions or repeated strategic rejection via strategic_review:{question,evidence,interim,useful_by}. question/interim max 600 characters, evidence max 8 factual references or changed assumptions (200 characters each), useful_by max 160 characters. This publication queues real Sol work and ends this batch, releasing capacity. review_pending acknowledges already outstanding work and also ends this batch. Do not wait or issue a separate request call. Keep interim prose concrete; never rewrite the goal.'
    if stage=='long_term':
        value['instruction']=value['instruction'].replace('Write long_term_action:revise,','Write long_term_action:keep or revise,')
        value['instruction']+=' Answer strategic_reviews explicitly in long_term_rationale. KEEP answers them without replacing the goal; omit long_term_plan. Initial goal requires REVISE. Optional dependencies are factual JSON Pointers; optional watches replace up to eight conservative strategic wake conditions. You never write continuity, tactical prose or actions. Diplomacy requires the separately bound async_diplomacy contract.'
        value['instruction']+=' When async_diplomacy is enabled, every changed goal (including the initial goal), diplomacy authorization question and diplomacy_refresh_required job MUST include diplomacy_brief in this same publication. A valid existing brief may instead be explicitly reauthorized with diplomacy_brief_action:keep; omit its text. Every completed long-term review, including unchanged goal/brief KEEP, schedules a mandatory public post. Draft authorized text in the retained messaging personality voice. Supply at least one public-safe disclosure of at most 300 characters, usable even without an open offer; do not expose the private goal. Exact atoms are not instructions to paraphrase. valid_through_event_seq must exceed rationale_interval.through_event_seq and be at most 2000 later. Commitments require authorized offer IDs.'
    return value


def present(value,boundaries):
    result={**value,'publication_stages':[instruction(s,boundaries) for s in stages(value)]}
    if value.get('decision_roles')==1:
        from .table_talk_plan import GUIDANCE as talk_guidance
        for stage in result['publication_stages']:
            if stage['stage']=='short_term':
                from .goal_validity import GUIDANCE as validity_guidance
                stage['fields']=[f for f in stage['fields'] if f not in {'table_talk','strategic_disposition','strategic_review'}]
                stage.pop('strategic_disposition',None)
                before,_,_=stage['instruction'].partition(' Include strategic_disposition.')
                stage['instruction']=before+' '+validity_guidance
                stage['instruction']=stage['instruction'].replace(talk_guidance,'')+' All public talk, including openers, belongs to the diplomat. Do not send a pilot table-talk draft.'
            if stage['stage']=='actions':
                stage['instruction']+=' Optional combo_proposal:{proposal_text,seat_turn,phase,requires} supplies a demonstrated loop, its repeatability and claimed outcome (text <=1200 characters), exact own-turn ordinal, main phase, and at most eight factual guards. Omit when no concrete loop is ready. The pilot must choose whether to submit this proof for adjudication; it never executes as an approved sequence step. A newer actions publication clears an omitted proposal.'
        for stage in result['publication_stages']:
            if stage['stage']=='long_term':
                stage['instruction']+=' Read the latest short-term prose and goal_assessment even when it is valid. Keep strategy concrete about named win packages, missing pieces and survival priorities; immediate land-drop and spell sequencing belong to short-term planning, and completed milestones must not remain future instructions. An invalid assessment of the current goal requires REVISE with changed strategic guidance and renewed diplomatic authorization in this publication; keeping the goal or re-submitting the same prose cannot discharge it. A tag for a replaced goal does not invalidate its successor.'
        if 'symbolic_vocabulary' in result:
            from copy import deepcopy
            result['symbolic_vocabulary']=deepcopy(result['symbolic_vocabulary'])
            result['symbolic_vocabulary'].setdefault('sequence_format',{})['phase_transition']='Empty main phases and priority windows with no material actions advance without a decision. Propose an executable prefix including known mandatory targets/modes. Add a PASS step only for a real actionable window you intend to decline; never invent greeting, combo, concede-only or phase-exit decisions. Opponent passes may preserve resume_after_passes; new information or intervention stops execution.'
    else:
        for stage in result['publication_stages']:
            stage['fields']=[f for f in stage['fields'] if f not in {'combo_proposal','long_term_validity','long_term_invalid_reason'}]
    from .combat_proposals import apply
    from .turn_batches import present as batch_present
    return batch_present(apply(result))


def project(root,game,actor,value):
    role=value['role'];d=components.directory(root,game)
    config=read(d.parent/'game_config.json',{})
    if role==SHORT:
        for key in ('combat_proposals','turn_batches'):
            if config.get(key)==1:value[key]=1
    current=components.current(root,game,actor)
    value['agent_architecture']=1
    from .agent_architecture import diplomacy_enabled
    value['async_diplomacy']=diplomacy_enabled(root,game)
    value['component_refs']={kind:{'component_id':identity(v),'version':v['version'],
        'coverage':v['coverage']} for kind,v in current.items()
        if (kind!='diplomacy_brief' or role==LONG) and (kind!='standing' or role==SHORT)}
    for kind in ('diplomacy_outcomes','diplomacy_brief'):
        if kind in current and (kind!='diplomacy_brief' or role==LONG):
            value[kind]=get(d/'plan_components',current[kind]['content_id'])[kind]
    if role==LONG and value['async_diplomacy']:
        from .diplomacy import applicable
        source=current.get('diplomacy_brief')
        value['diplomacy_brief_review']={'can_keep':bool(source and applicable(value['diplomacy_brief'],source,get(d/'snapshots',value['snapshot']),d)),
            'instruction':'Every completed long-term review requires a diplomat message, including KEEP. Use diplomacy_brief_action:keep to retain valid text without resending it, or revise with diplomacy_brief. Missing/expired/invalid authorization requires revise. Keeping the brief also explicitly reauthorizes it for a revised goal.'}
    if value.get('diplomacy_outcomes'):
        from .diplomacy import project_outcomes
        value['diplomacy_outcomes']=project_outcomes(value['diplomacy_outcomes'],get(d/'snapshots',value['snapshot']),d)
    prior=value.get('prior_plan') or {}
    keep={'long_term_plan','continuity','short_term_plan'}
    value['prior_plan']={k:v for k,v in prior.items() if k in keep}
    if 'short_term' in current:
        tactical=get(d/'plan_components',current['short_term']['content_id'])
        value['prior_plan']['short_term_plan']=tactical['short_term_plan']
        from .goal_validity import project as project_assessment
        assessment=project_assessment(tactical.get('goal_assessment'),identity(current['long_term']) if 'long_term' in current else None)
        if assessment:value['goal_assessment']=assessment
    if role==SHORT:
        value['standing_plan']=get(d/'plan_components',current['standing']['content_id']) if 'standing' in current else None
    else:value.pop('standing_plan',None)
    from .decision_roles import enabled as decision_roles_enabled
    value['decision_roles']=1 if decision_roles_enabled(root,game) else 0
    value['standing_only']=all(r.get('scope')=='standing' for r in value['requirements'])
    value['initial_goal_required']='long_term' not in current
    state=read(d/'workboard.json',{})
    pending=state.get('strategic_reviews',{}).get(actor)
    value['strategic_reviews']=([get(d/'review_requests',key) for key in pending['request_ids']]
        if pending and role==LONG else [])
    if role==SHORT:
        value['strategic_review_status']= {'state':'pending','request_ids':pending['request_ids']} if pending else {'state':'none'}
        if 'strategic_answer' in current:
            value['strategic_answer']=get(d/'plan_components',current['strategic_answer']['content_id'])['strategic_answer']
    else:
        # Targeted review plus latest own rationale evidence, never the entire
        # accumulated tactical execution report or full symbolic vocabulary.
        decisions=value['decisions_since_prior_plan']
        value['rationale_evidence_omitted']=max(0,len(decisions)-8)
        value['decisions_since_prior_plan']=decisions[-8:]
        for key in ('execution_comparison','sequence_reviews','symbolic_vocabulary','previous_watches','latest_decision_context'):
            value.pop(key,None)
        value['rationale_evidence_guidance']='Latest eight own rationales shown. Earlier complete evidence remains available through history/decision inspection; omission does not mean no decisions occurred.'
    value['inspection']=['state','history','decision ID','component ID','card NAME_OR_ID','object UID','role NAME_OR_ID','deck zone=ZONE']
    if role==LONG:value['inspection']+=['roles','deck','seed','personality']
    value['guidance']=('Long-term role: retain seed/roles/deck knowledge and perform targeted strategic review. Own the current goal; publish standing only if explicitly requested as a legacy stage. Do not maintain continuity. '
        if role==LONG else 'Short-term role: read current goal, continuity, ALL supplied own rationales, deviations and review answers. Own continuity and concrete tactical sequencing. Targeted factual inspection is available; broad seed/catalog surveys belong to Sol. ')
    value['guidance']+='Follow publication_stages. No gameplay, routing, polling or waiting. Each stage is a separate publication; stop when next is null. Current plans enter the next real recipient packet, never an active inference.'
    if role==SHORT:
        from .scheduler import CHOICE_GUIDANCE
        value['guidance']+=' '+CHOICE_GUIDANCE+' Each executable step includes its intended scheduler object; table snooze belongs on the final step. Do not propose a policy that suppresses later steps you want executed.'
        from .planner_facts import references
        value['visible_rule_refs']=references(d,get(d/'snapshots',value['snapshot']),actor)
        value['guidance']+=' Check material card conditions with targeted inspection. Count only the objects controlled by the player named in the rule; opposing permanents do not satisfy your own control requirements. Do not spend an inspection round on facts already supplied.'
        value['symbolic_vocabulary']['sequence_format']['command_zone_cast']={'kind':'main_action','choice':{'action':'commander','source':{'uid':'COMMANDER_UID'},'args':{}}}
        value['symbolic_vocabulary']['sequence_format']['ordinary_hand_cast']={'kind':'main_action','choice':{'action':'cast','source':{'uid':'CARD_UID'},'args':{'miracle':False,'x_value':0}}}
        value['symbolic_vocabulary']['sequence_format']['finish_main_phase']={'kind':'main_action','phase':'precombat_main','choice':None}
        value['symbolic_vocabulary']['sequence_format']['finish_main_priority']={'kind':'priority_action','phase':'precombat_main','choice':None}
        value['symbolic_vocabulary']['sequence_format']['phase_transition']='To move from precombat spells to combat, explicitly propose main_action PASS, then the end-of-main priority_action PASS when you intend to pass that window; both use precombat_main. hold_full_control keeps that priority decision open. Never assume a phase exit or your own priority is automatically approved. Opponent passes may preserve a pilot-approved resume_after_passes batch; a new opposing action invalidates it. Include intervening targets/modes only when their exact choices are known.'
        value['symbolic_vocabulary']['sequence_format']['exact_matching']='Command-zone casts use action commander, not cast. Action kinds and argument dictionaries must match exactly; never infer an omitted parameter. Copy a known legal symbol where available; leave unknown modes/targets to a real decision.'
    else:
        value['guidance']+=' For strategic reviews, prefer ordinary named-card/package inspection and retained knowledge. detail=full bypasses compact presentation; use it only to resolve a specific omission, not as a default on role surveys.'
        value['guidance']+=' Card watches require an exact name from your frozen deck or publicly observed cards. A plausible opposing deck inclusion is not known information; do not register speculative card watches. Object watches use visible frozen UIDs.'
    value['wake_guidance']='Mandatory EOT short-term maintenance; no draw wakes. Strategic watches and explicit pilot/short-term requests queue Sol. Python coalesces pending work; frozen inputs do not change.'
    for requirement in value['requirements']:
        requirement['long_term_policy']='Only the long-term role publishes strategy; short-term requests are scheduled through strategic_disposition.'
    value.update(present(value,[r['cadence_id'] for r in value['requirements']]))


def _review(root,game,actor,state,batch,snapshot,response,*,_invalid_goal=None):
    from . import planner_runtime as runtime
    disposition=response.get('strategic_disposition')
    if disposition not in {'continue','review_requested','review_pending'}:
        raise ValueError('Include strategic_disposition: continue, review_requested or review_pending.')
    pending=state.setdefault('strategic_reviews',{}).get(actor)
    if disposition!='review_requested':
        if 'strategic_review' in response:raise ValueError('Only review_requested carries strategic_review.')
        if disposition=='review_pending' and not pending:raise ValueError('No strategic review is pending; request one or continue.')
        return {'state':'already_pending','request_ids':pending['request_ids']} if disposition=='review_pending' else None
    review=response.get('strategic_review')
    if not isinstance(review,dict) or set(review)!={'question','evidence','interim','useful_by'}:
        raise ValueError('strategic_review needs exactly question, evidence, interim and useful_by.')
    for field,limit in [('question',600),('interim',600),('useful_by',160)]:
        if not isinstance(review[field],str) or len(review[field])>limit or (field!='interim' and not review[field].strip()):
            raise ValueError(f'Invalid strategic_review.{field}.')
    if not isinstance(review['evidence'],list) or not 1<=len(review['evidence'])<=8 or any(not isinstance(x,str) or not x.strip() or len(x)>200 for x in review['evidence']):
        raise ValueError('Review evidence needs 1–8 concise references or changed assumptions.')
    d=components.directory(root,game);signature=identity([batch['role'],'invalid_goal',_invalid_goal] if _invalid_goal else [batch['role'],review])
    existing=(pending or {}).get('request_ids',[])
    if any(get(d/'review_requests',key)['signature']==signature for key in existing):
        return {'state':'already_pending','request_ids':existing}
    if len(existing)>=4:raise ValueError('Four strategic questions already pending; use review_pending until answered.')
    key=put(d/'review_requests',{'actor':actor,'game':game,'signature':signature,'source_session':batch['source_session'],
        'snapshot':batch['snapshot'],'requested_at':time.time(),'requesting_role':batch['role'],
        **({'invalid_goal_component_id':_invalid_goal} if _invalid_goal else {}),**review})
    state['strategic_reviews'][actor]={'request_ids':existing+[key]}
    runtime._queue_boundary(root,game,state,{'actor':actor,'role':LONG,'scope':'long_term','required':True,
        'cadence_id':'strategic_review|'+key,'reason':'diplomacy_authorization' if batch['role']==DIPLOMACY else 'short_term_review',
        'request_id':key},batch['snapshot'],batch['source_session'])
    return {'state':'coalesced' if pending else 'queued','request_ids':existing+[key]}


def _view(d,actor,game,batch,snapshot,pointers,stage,final):
    envelopes={k:get(d/'plan_components',v) for k,v in pointers.items()}
    pointers=dict(pointers)
    if envelopes.get('actions',{}).get('dependent_versions',{}).get('short_term')!=envelopes.get('short_term',{}).get('version'):
        pointers.pop('actions',None)
    source=envelopes.get('short_term') or envelopes.get('long_term') or envelopes['standing']
    # Strategic publication cannot rejuvenate tactical freshness or discard it.
    frozen=get(d/'snapshots',source['snapshot'])
    source_session=source['source_session'];snapshot_id=source['snapshot'];event_seq=source['coverage']['through_event_seq']
    from .pilot_handoff import seat_slug
    previous=read(d/'mailboxes'/(seat_slug(actor)+'.json'),{})
    previous=get(d/'plans',previous['plan_id']) if previous.get('plan_id') else {}
    if batch.get('role')==SHORT:
        source_session=batch['source_session'];snapshot_id=batch['snapshot'];event_seq=snapshot['event_seq'];frozen=snapshot
    elif 'short_term' in envelopes and previous.get('snapshot'):
        source_session=previous['source_session'];snapshot_id=previous['snapshot'];event_seq=previous['event_seq']
        frozen=get(d/'snapshots',snapshot_id)
    plan={'schema':1,'agent_architecture':1,'planning_contract':4,'actor':actor,'game':game,
        'generation':batch['generation'],'batch_id':identity(batch),'source_session':source_session,
        'snapshot':snapshot_id,'board_tag':frozen['board_tag'],'event_seq':event_seq,
        'publication_stage':stage,'publication_complete':final,'covered_boundaries':[],
        'short_term_plan':None,'long_term_plan':None,'continuity':'','action_sequence':[],'recommendations':[],
        'watches':[],'dependencies':envelopes.get('short_term',{}).get('dependencies',[]),
        'tier_origins':{k:{'after_decision':v['source_session']['accepted_prefix_count'],
            'event_seq':v['coverage']['through_event_seq'],'published_at':v['published_at']}
            for k,v in envelopes.items() if k in {'standing','long_term','short_term'}},
        'owned_component_ids':pointers}
    return put(d/'plans',plan)


def publish(root,game,actor,batch_id,generation,stage,response):
    from . import planner_runtime as runtime,planner_stages,planning_contract,sequence_contract,pilot_handoff
    from .active_plan import normalize_plan_delta
    d=components.directory(root,game)
    with locked(d,'planning'):
        components.recover(root,game)
        _,state,batch,snapshot=runtime._batch(root,game,actor,batch_id,generation)
        binding=read(d/'inputs'/(batch_id+'.json'))
        if not binding:raise ValueError('Read the frozen input before publishing.')
        value=get(d/'frozen_inputs',binding['input_id']);order=stages(value)
        if stage not in order or not isinstance(response,dict) or set(response)-fields(stage):raise ValueError('Publication fields do not belong to this role/stage.')
        digest=identity(response);operation=batch_id+':'+stage
        saved=components.receipt(root,game,actor,operation,digest)
        if saved:return saved
        progress=reservation(state,batch_id).get('completed_stages',[])
        if reservation(state,batch_id).get('published_at') or len(progress)>=len(order) or order[len(progress)]!=stage:
            raise ValueError('Publish only the next unfinished stage of this reserved role.')
        updates={};review=None;deps=response.get('dependencies',[]);now=time.time()
        if stage=='standing':
            text=response.get('standing_plan')
            if not isinstance(text,str) or not text.strip() or len(text)>3600:raise ValueError('Standing plan requires 1–3600 characters.')
            updates['standing']={'standing_plan':text.strip()}
        elif stage=='short_term':
            short=normalize_plan_delta(response.get('short_term_plan'))
            if len(short)>600:raise ValueError('Short-term prose maximum is 600 characters.')
            continuity=normalize_plan_delta(response.get('continuity'))
            boundaries=[state['jobs'][key]['boundary'] for key in batch['job_ids']]
            notes=response.get('boundary_notes',{})
            if not isinstance(notes,dict) or set(notes)-set(boundaries) or len(boundaries)>1 and set(notes)!=set(boundaries):
                raise ValueError('boundary_notes must cover the exact coalesced boundary keys.')
            notes={k:normalize_plan_delta(v) for k,v in notes.items()}
            updates['short_term']={'short_term_plan':short,'boundary_notes':notes}
            if value.get('decision_roles')==1:
                from .goal_validity import assess
                assessment,review=assess(root,game,actor,state,batch,snapshot,value,response)
                updates['short_term']['goal_assessment']=assessment
            else:
                if {'long_term_validity','long_term_invalid_reason'} & set(response):raise ValueError('This frozen packet uses strategic_disposition; follow its stage fields.')
                review=_review(root,game,actor,state,batch,snapshot,response)
                updates['short_term']['strategic_disposition']=response['strategic_disposition']
            if 'table_talk' in response:
                if value.get('decision_roles')==1:raise ValueError('Table talk belongs exclusively to the diplomat in this game.')
                from .table_talk_plan import normalize
                updates['short_term']['table_talk']=normalize(response['table_talk'],actor,snapshot['board'])
            updates['continuity']={'continuity':continuity}
        elif stage=='long_term':
            action=response.get('long_term_action');rationale=normalize_plan_delta(response.get('long_term_rationale'))
            if action not in {'keep','revise'}:raise ValueError('long_term_action must be keep or revise.')
            current=components.current(root,game,actor)
            from .agent_architecture import diplomacy_enabled
            goal_changed=action=='revise' and (not current.get('long_term') or
                get(d/'plan_components',current['long_term']['content_id']) !=
                {'long_term_plan':normalize_plan_delta(response.get('long_term_plan'))} or
                current['long_term']['dependencies']!=deps)
            from .goal_validity import requires_revision
            invalid_goal=requires_revision(value,identity(current['long_term']) if 'long_term' in current else None)
            if invalid_goal and (action!='revise' or not goal_changed or get(d/'plan_components',current['long_term']['content_id']).get('long_term_plan')==normalize_plan_delta(response.get('long_term_plan'))):
                raise ValueError('An invalid current goal requires REVISE with changed long-term guidance and a fresh diplomacy brief.')
            brief_refresh=any(r.get('reason')=='diplomacy_refresh_required' for r in value['requirements'])
            brief_refresh=brief_refresh or any(r.get('requesting_role')==DIPLOMACY for r in value.get('strategic_reviews',[]))
            brief_action=response.get('diplomacy_brief_action')
            if brief_action is not None and (not diplomacy_enabled(root,game) or brief_action not in {'keep','revise'}):
                raise ValueError('diplomacy_brief_action must be keep or revise in an asynchronous diplomacy game.')
            if brief_action=='keep' and 'diplomacy_brief' in response:raise ValueError('KEEP the brief by reference; omit replacement diplomacy_brief text.')
            if brief_action=='revise' and 'diplomacy_brief' not in response:raise ValueError('REVISE requires diplomacy_brief.')
            if diplomacy_enabled(root,game) and (goal_changed or brief_refresh) and 'diplomacy_brief' not in response and brief_action!='keep':
                raise ValueError('A changed long-term goal or diplomacy authorization request requires a fresh diplomacy_brief in this same publication.')
            if diplomacy_enabled(root,game) and 'diplomacy_brief' not in response:
                from .diplomacy import applicable
                prior_brief=current.get('diplomacy_brief')
                if not prior_brief or not applicable(get(d/'plan_components',prior_brief['content_id'])['diplomacy_brief'],prior_brief,snapshot,d):
                    raise ValueError('The diplomacy brief cannot be kept: missing or invalid authorization requires a fresh diplomacy_brief.')
                if goal_changed:
                    updates['diplomacy_brief']=get(d/'plan_components',prior_brief['content_id'])
            if action=='keep':
                if 'long_term_plan' in response or 'long_term' not in current:raise ValueError('KEEP requires a prior goal and must omit replacement text.')
            else:updates['long_term']={'long_term_plan':normalize_plan_delta(response.get('long_term_plan'))}
            requests=[identity(r) for r in value.get('strategic_reviews',[])]
            updates['strategic_answer']={'strategic_answer':{'request_ids':requests,'action':action,'rationale':rationale,'through_event_seq':snapshot['event_seq']}}
            pending=state.setdefault('strategic_reviews',{}).get(actor)
            if pending:
                remaining=[key for key in pending['request_ids'] if key not in requests]
                if remaining:pending['request_ids']=remaining
                else:state['strategic_reviews'].pop(actor,None)
            # A waiting tactical request genuinely needs its strategic answer.
            # KEEP alone never creates unrelated maintenance or a new goal ID.
            if any(r.get('requesting_role',SHORT)==SHORT for r in value.get('strategic_reviews',[])):
                runtime._queue_boundary(root,game,state,{'actor':actor,'role':SHORT,'scope':'short_term',
                    'cadence_id':'review_answer|'+batch_id,'reason':'strategic_answer','required':True},
                    state.get('snapshots',{}).get(actor,batch['snapshot']),
                    get(d/'snapshots',state.get('snapshots',{}).get(actor,batch['snapshot']))['source_session'])
            if 'diplomacy_brief' in response:
                from .diplomacy import normalize_brief
                updates['diplomacy_brief']={'diplomacy_brief':normalize_brief(root,game,actor,response['diplomacy_brief'],snapshot)}
        else:
            vocabulary=value['symbolic_vocabulary']
            if not {'action_sequence','watches'}<=set(response):raise ValueError('Actions stage requires action_sequence and watches.')
            sequence=sequence_contract.proposals(response['action_sequence'],actor,snapshot['board'],set(vocabulary['object_uids']))
            if value.get('combat_proposals')==1:
                from .combat_proposals import validate
                validate(sequence)
            from .turn_batches import full_required,validate_coverage
            if full_required(value):validate_coverage(value,sequence,response.get('phase_coverage'))
            elif 'phase_coverage' in response:raise ValueError('phase_coverage is only requested for mandatory pre-turn batches.')
            updates['actions']={'action_sequence':sequence,'recommendations':sequence_contract.cast_recommendations(sequence,actor,snapshot['board']),
                'watches':planning_contract.watches(response['watches'],snapshot['board'],set(vocabulary['cards']),set(vocabulary['object_uids']))}
        if stage=='actions' and 'phase_coverage' in response:updates['actions']['phase_coverage']=response['phase_coverage']
        if 'combo_proposal' in response:
            from .decision_roles import normalize_combo
            if value.get('decision_roles')!=1:raise ValueError('This game did not bind planner-owned combo proposals.')
            updates['actions']['combo_proposal']=normalize_combo(response['combo_proposal'],actor,snapshot['board'])
        # Symbolic watches for Sol use the same validated factual vocabulary.
        if stage=='long_term' and 'watches' in response:
            cards,uids=planning_contract.known_facts(snapshot['board'],set(snapshot.get('known_cards',[]))|
                {get(d/'inspection',v).get('name') for v in snapshot.get('catalog',{}).values()}-{None})
            watches=planning_contract.watches(response['watches'],snapshot['board'],cards,uids)
            state.setdefault('strategic_watch_sources',{})[actor]={'plan_id':operation,'checked_seq':snapshot['event_seq'],'watches':watches,'fired':[]}
        from .turn_batches import full_required
        final=stage==order[-1] or (review is not None and not full_required(value))
        dependent_versions={k:v['version'] for k,v in value.get('component_refs',{}).items()}
        if stage=='long_term' and 'diplomacy_brief' in updates:
            dependent_versions['long_term']=current.get('long_term',{}).get('version',0)+int(goal_changed)
            dependent_versions['diplomacy_refresh']=(operation if brief_refresh else
                current.get('diplomacy_brief',{}).get('dependent_versions',{}).get('diplomacy_refresh'))
        if stage=='actions':
            current_short=components.current(root,game,actor).get('short_term')
            if current_short:dependent_versions['short_term']=current_short['version']
        pointers,changed=components.prepare(root,game,actor,batch['role'],operation,updates,
            source_session=batch['source_session'],snapshot=batch['snapshot'],event_seq=snapshot['event_seq'],
            dependencies={k:deps for k in updates if k in {'short_term','long_term'}},
            change_rationale=response.get('long_term_rationale'),
            dependent_versions=dependent_versions)
        rework=[]
        if 'long_term' in changed:
            current=components.current(root,game,actor)
            short=current.get('short_term')
            if short:
                from .sequence_contract import pointer
                before=get(d/'snapshots',short['snapshot'])['board']
                rework=[p for p in short['dependencies'] if pointer(before,p)!=pointer(snapshot['board'],p)]
                if rework:
                    runtime._queue_boundary(root,game,state,{'actor':actor,'role':SHORT,'scope':'short_term','required':True,
                        'cadence_id':'material_goal_rework|'+pointers['long_term'],'reason':'material_goal_revision',
                        'changed_dependencies':rework},state.get('snapshots',{}).get(actor,batch['snapshot']),
                        latest_source(state,d,actor,batch)['source_session'])
        plan_id=_view(d,actor,game,batch,snapshot,pointers,stage,final)
        if stage=='long_term' and value.get('async_diplomacy') and 'diplomacy_brief' in pointers:
            # Only unclaimed obsolete briefs coalesce. Frozen work and receipts
            # remain immutable, and incoming-message jobs are never discarded.
            for job in state['jobs'].values():
                if job['actor']==actor and job['status']=='pending' and job['requirements'].get('reason')=='actionable_brief':
                    job['status']='superseded'
            runtime._queue_boundary(root,game,state,{'actor':actor,'role':DIPLOMACY,'scope':'diplomacy','required':True,
                'cadence_id':'brief_review|'+operation,'reason':'actionable_brief',
                'brief_component_id':pointers['diplomacy_brief'],'brief_changed':'diplomacy_brief' in changed},
                state.get('snapshots',{}).get(actor,batch['snapshot']),latest_source(state,d,actor,batch)['source_session'])
        result={'batch_id':batch_id,'plan_id':plan_id,'state':'published' if final else 'stage_published',
            'stage':stage,'stage_response_digest':digest,'response_digest':digest,'published_at':now,
            'role':batch['role'],'changed_components':changed,'next':None if final else next(row for row in present(value,[])['publication_stages'] if row['stage']==order[len(progress)+1])}
        if review:result['strategic_review']=review
        if updates.get('short_term',{}).get('goal_assessment'):result['goal_assessment']=updates['short_term']['goal_assessment']
        if rework:result['tactical_rework']={'reason':'revised_goal_and_changed_declared_tactical_dependencies','paths':rework}
        result['telemetry']={'queued_seconds':now-min(state['jobs'][k]['queued_at'] for k in batch['job_ids']),
            'reserved_seconds':now-reservation(state,batch_id)['reserved_at'],'source_decision':batch['source_session']['accepted_prefix_count'],
            'latest_decision':latest_source(state,d,actor,batch)['source_session']['accepted_prefix_count'],
            'goal_version_changed':'long_term' in changed,'goal_validity':updates.get('short_term',{}).get('goal_assessment',{}).get('status'),'coalesced_jobs':len(batch['job_ids'])}
        reservation(state,batch_id).setdefault('completed_stages',[]).append(stage)
        for key in batch['job_ids']:
            state['jobs'][key]['plan_id']=plan_id
            if final:state['jobs'][key]['status']='published'
        if final:reservation(state,batch_id)['published_at']=now
        if stage=='actions':
            state.setdefault('watch_sources',{})[actor]={'plan_id':plan_id,'checked_seq':snapshot['event_seq'],
                'watches':updates['actions']['watches'],'fired':[]}
        # Catch material changes during inference before committing pointers.
        from . import planner_wakes
        latest=get(d/'snapshots',state.get('snapshots',{}).get(actor,batch['snapshot']))
        for name,role in [('watch_sources',SHORT),('strategic_watch_sources',LONG)]:
            source=state.get(name,{}).get(actor)
            if source:
                for item in planner_wakes.evaluate_watches(actor,source,planner_wakes.history(d,latest,source['checked_seq'])):
                    runtime._queue_boundary(root,game,state,{**item,'role':role,'scope':'long_term' if role==LONG else 'short_term'},
                        state.get('snapshots',{}).get(actor,batch['snapshot']),latest['source_session'])
        writes=[(components.index_path(d,actor),pointers),
            (d/'mailboxes'/(pilot_handoff.seat_slug(actor)+'.json'),{'plan_id':plan_id,'published_at':now}),
            (d/'stage_publications'/(batch_id+'.'+stage+'.json'),result),(d/'workboard.json',state)]
        if final:
            writes.extend([(d/'publications'/(batch_id+'.json'),result),
                (d/'role_coverage'/(identity([actor,batch['role']])+'.json'),
                 {'source_session':batch['source_session'],'event_seq':snapshot['event_seq']})])
        result=components.commit(root,game,actor,operation,digest,batch['source_session'],writes,result)
        from . import operator_view
        operator_view.refresh_plans(root,game)
        return result


def latest_source(state,d,actor,batch):
    return get(d/'snapshots',state.get('snapshots',{}).get(actor,batch['snapshot']))
