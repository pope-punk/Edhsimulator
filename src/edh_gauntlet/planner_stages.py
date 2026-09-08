"""Bounded progressive planner publication; immutable components are stored once."""
from .background_slots import reservation
from .runtime_store import read,write,get,put,identity,locked

FIELDS={
    'standing':{'standing_plan'},
    'short_term':{'short_term_plan','continuity','dependencies','boundary_notes','table_talk'},
    'actions':{'action_sequence','watches'},
    'long_term':{'long_term_action','long_term_rationale','long_term_plan'},
}

def enabled(root,game):
    from . import campaign
    return read(campaign.game_dir(root,game)/'game_config.json',{}).get('planner_stages',False)

def required(input_value):
    return any(r.get('long_term_requested',False) for r in input_value['requirements'])

def sequence(input_value):
    if input_value.get('agent_architecture')==1:
        from .split_planning import stages
        return stages(input_value)
    if input_value.get('plan_tiers'):
        from .plan_tiers import order
        return order(input_value)
    return ['short_term','actions']+(['long_term'] if required(input_value) else [])

def boundary_contract(boundaries):
    from .active_plan import PLAN_DELTA_MAX_CHARS
    return {'allowed_keys':list(boundaries),'required':len(boundaries)>1,
            'values':f'One nonempty factual continuity note per key, at most {PLAN_DELTA_MAX_CHARS} characters. Use exact keys; never invent labels.'}

def instruction(stage,tiered=False,boundaries=()):
    from .active_plan import PLAN_DELTA_MAX_CHARS
    value=_instruction(stage,tiered)
    limits={'standing':{'standing_plan':3600},'short_term':{
        'short_term_plan':600 if tiered else PLAN_DELTA_MAX_CHARS,'continuity':PLAN_DELTA_MAX_CHARS},
        'long_term':{'long_term_plan':PLAN_DELTA_MAX_CHARS,'long_term_rationale':PLAN_DELTA_MAX_CHARS}}
    if stage in limits:
        value['max_chars']=limits[stage]
        value['target_chars']={key:int(limit*.75) for key,limit in limits[stage].items()}
        value['instruction']+=' Aim for target_chars, leaving space below each hard maximum. Preserve concrete decisions and contingencies; remove repeated explanations.'
    if stage=='short_term':
        from .table_talk_plan import GUIDANCE as TABLE_TALK_GUIDANCE
        value['boundary_notes']=boundary_contract(boundaries)
        value['dependencies']={'max_items':24,'items':'Factual projection JSON Pointer paths; never prose conditions.'}
        value['instruction']+=' boundary_notes must cover every allowed key when required; otherwise it may be omitted. Dependencies are optional.'
        value['instruction']+=' '+TABLE_TALK_GUIDANCE
    return value


def length_feedback(stage,response,tiered=False):
    """Measured private response sizes only; never trim planner-authored content."""
    import unicodedata
    if stage not in FIELDS or not isinstance(response,dict):return []
    limits=instruction(stage,tiered).get('max_chars',{})
    rows=[]
    for field,limit in limits.items():
        text=response.get(field)
        if not isinstance(text,str):continue
        if field!='standing_plan':text=unicodedata.normalize('NFC',text.replace('\r\n','\n').replace('\r','\n')).strip()
        if len(text)>limit:rows.append({'field':field,'received_chars':len(text),'max_chars':limit,'target_chars':int(limit*.75)})
    return rows

def present_input(value,boundaries):
    """Refresh delivery instructions without rewriting immutable job evidence."""
    if value.get('role')=='diplomacy':return value
    if value.get('agent_architecture')==1:
        from .split_planning import present
        return present(value,boundaries)
    if 'publication_stages' not in value:return value
    return {**value,'publication_stages':[instruction(s,value.get('plan_tiers',False),boundaries) for s in sequence(value)]}

def pending_instruction(root,game,actor,batch_id,generation):
    from . import planner_runtime as runtime
    directory,state,batch,_=runtime._batch(root,game,actor,batch_id,generation)
    binding=read(directory/'inputs'/(batch_id+'.json'))
    if not binding:return None
    value=get(directory/'frozen_inputs',binding['input_id'])
    if value.get('role')=='diplomacy':return None if reservation(state,batch_id).get('published_at') else {'stage':'diplomacy','instruction':value['guidance']}
    if value.get('agent_architecture')==1:
        if reservation(state,batch_id).get('published_at'):return None
        from .split_planning import present as split_present
        progress=reservation(state,batch_id).get('completed_stages',[])
        return next(row for row in split_present(value,[])['publication_stages'] if row['stage']==sequence(value)[len(progress)])
    boundaries=[state['jobs'][key]['boundary'] for key in batch['job_ids']]
    for stage in sequence(value):
        if not read(directory/'stage_publications'/(batch_id+'.'+stage+'.json')):
            return instruction(stage,value.get('plan_tiers',False),boundaries)
    return None

def _instruction(stage,tiered=False):
    from .host_contract import PLANNER_GUIDANCE
    if stage=='actions':return {'stage':stage,'fields':sorted(FIELDS[stage]),'instruction':
        'Publish action_sequence and watches, following the frozen input and accepted short-term prose. '+PLANNER_GUIDANCE}
    if tiered:
        return {'stage':stage,'fields':sorted(FIELDS[stage]),'instruction':{
            'standing':'Write the immutable deck-level standing_plan from the seed, roles and deck. Explain engines, capabilities, win routes and recovery in about 2700 characters. Group cards by functional package; do not repeat the deck inventory or every seed example. No hand-specific or current-board advice. Hard maximum 3600 characters, not words or tokens.',
            'long_term':'Write long_term_action:revise, long_term_rationale, and long_term_plan. In concise prose name the reachable core, events it actually generates, matching payoff, missing card/role and concrete acquisition path, survival constraint and observable pivot cue. Separate stabilization from a kill; a blink loop does not supply deaths without a sacrifice/recursion connection. If no core is reachable, name the development/search route and its pivot condition. Do not repeat deck doctrine or unknown-opponent boilerplate. Maximum 1200 characters. This goal precedes the upcoming sequence.',
            'short_term':'Write short_term_plan as literal card sequencing for the upcoming turn that advances the new/current long-term goal. Maximum 600 characters. Also write continuity. Do not rewrite strategy.',
            'actions':'Convert that short-term sequence into action_sequence plus watches. Include specific timing, rationales and snooze policies. Do not repeat prose.'}[stage]}
    return {'stage':stage,'fields':sorted(FIELDS[stage]),'instruction':
        {'short_term':'Publish concise short-term prose and continuity now. Do not generate symbolic actions or a long-term update yet.',
         'actions':'Publish the symbolic action_sequence and conservative watches now, using the same frozen input and the prose you just published. Do not repeat prose or write a long-term plan.',
         'long_term':'The pilot requested a long-term update. Publish KEEP plus rationale, or REVISE plus rationale and the complete long-term replacement. Do not repeat prose or actions.'}[stage]}

def load_plan(directory,plan_id):
    plan=get(directory/'plans',plan_id)
    owned=plan.get('owned_component_ids')
    if owned:
        for component in owned.values():
            envelope=get(directory/'plan_components',component)
            plan.update(get(directory/'plan_components',envelope['content_id']))
    components=plan.pop('component_ids',None)
    if components:
        for component in components.values():plan.update(get(directory/'plan_components',component))
    return plan

def store_plan(directory,plan):
    value=dict(plan);components={}
    for name,keys in FIELDS.items():
        selected=keys|({'recommendations'} if name=='actions' else set())
        components[name]=put(directory/'plan_components',{k:value.pop(k) for k in selected if k in value})
    value['component_ids']=components
    return put(directory/'plans',value)

def publish(root,game,actor,batch_id,generation,stage,response):
    from . import planner_runtime as runtime
    from . import agent_architecture
    if agent_architecture.enabled(root,game):
        if stage=='diplomacy':
            from .diplomacy import publish as diplomacy_publish
            try:return diplomacy_publish(root,game,actor,batch_id,generation,response)
            except ValueError as exc:raise SystemExit(str(exc)) from exc
        from .split_planning import publish as split_publish
        try:return split_publish(root,game,actor,batch_id,generation,stage,response)
        except ValueError as exc:raise SystemExit(str(exc)) from exc
    if not enabled(root,game):raise SystemExit('This game uses single planner publication.')
    directory=runtime.directory_for(root,game)
    with locked(directory,'planning'):
        _,state,batch,_=runtime._batch(root,game,actor,batch_id,generation)
        binding=read(directory/'inputs'/(batch_id+'.json'))
        if not binding:raise SystemExit('Read the frozen planner input first.')
        input_value=get(directory/'frozen_inputs',binding['input_id']);order=sequence(input_value)
        boundaries=[state['jobs'][key]['boundary'] for key in batch['job_ids']]
        if stage not in order or not isinstance(response,dict) or set(response)-FIELDS[stage]:
            raise SystemExit('Supply only fields for the requested planner stage.')
        # Receipts are durable before the state checkpoint; recover that narrow crash window.
        progress=[]; latest=None
        for name in order:
            saved=read(directory/'stage_publications'/(batch_id+'.'+name+'.json'))
            if not saved:break
            progress.append(name);latest=saved
        old_progress=reservation(state,batch_id).get('completed_stages',[])
        if progress!=old_progress:
            reservation(state,batch_id)['completed_stages']=list(progress)
            for key in batch['job_ids']:
                state['jobs'][key]['plan_id']=latest['plan_id']
                if len(progress)==len(order):state['jobs'][key]['status']='published'
            if len(progress)==len(order):
                reservation(state,batch_id)['published_at']=latest['published_at']
                write(directory/'publications'/(batch_id+'.json'),latest)
            if 'actions' in progress and 'actions' not in old_progress:
                actions_receipt=read(directory/'stage_publications'/(batch_id+'.actions.json'))
                runtime._install_watches(root,game,actor,directory,state,actions_receipt['plan_id'])
            runtime._save(directory,state)
        path=directory/'stage_publications'/(batch_id+'.'+stage+'.json')
        receipt=read(path);digest=identity(response)
        if receipt:
            if receipt['stage_response_digest']!=digest:raise SystemExit('This stage already published different content.')
            return {**receipt,'next':instruction(order[len(progress)],input_value.get('plan_tiers',False),boundaries) if len(progress)<len(order) else None}
        if len(progress)>=len(order) or stage!=order[len(progress)]:raise SystemExit('Planner stages must publish in order.')
        necessary={'standing':{'standing_plan'},'short_term':{'short_term_plan','continuity'},'actions':{'action_sequence','watches'},'long_term':{'long_term_action','long_term_rationale'}}[stage]
        if not necessary<=set(response):raise SystemExit('Missing required stage fields.')
        combined={'covered_boundaries':boundaries}
        if progress:
            prior=read(directory/'stage_publications'/(batch_id+'.'+progress[-1]+'.json'))
            plan=load_plan(directory,prior['plan_id'])
            for previous in progress:
                combined.update({k:plan[k] for k in FIELDS[previous] if k in plan})
        combined.update(response)
        result=runtime.publish(root,game,actor,batch_id,generation,combined,_stage=stage,_stage_digest=digest)
        return {**result,'next':instruction(order[len(progress)+1],input_value.get('plan_tiers',False),boundaries) if len(progress)+1<len(order) else None}
