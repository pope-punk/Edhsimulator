"""Game-bound pre-turn planning and explicit sequence-continuation policy."""
PHASES=('precombat_main','combat','postcombat_main')
COVERAGE_SCHEMA={'type':'object','properties':{phase:{'type':'object','properties':{
    'status':{'type':'string','enum':['planned','no_action','reassess']},
    'reason':{'type':'string','maxLength':180}},'required':['status'],'additionalProperties':False}
    for phase in PHASES},'required':list(PHASES),'additionalProperties':False}

PILOT_GUIDANCE=('Batch acceptance authorizes passing unplanned, unforced own priority windows until the next approved action; '
    'pass_priority:false opts out. An explicitly approved priority action is still executed, never replaced by a pass. '
    'resume_after_passes defaults true; opponents still choose for themselves. New opposing actions, new information, '
    'required choices, changed legality and combat damage stop execution. Keep the planner rationale on unchanged steps: '
    'do not submit rationale-only overrides or restate unchanged scheduler fields. A changed choice, scheduler or prerequisite '
    'may include an updated rationale. Python discards rationale-only rewrites without requesting another inference.')


def execution_policy(config,approval):
    enabled=config.get('turn_batches')==1
    return {'pass_priority':enabled and approval.get('pass_priority',True),
            'resume_after_passes':approval.get('resume_after_passes',enabled)}


def boundaries(runtime,ending):
    """At each opponent EOT, wake the next two living seats once each."""
    names=runtime.turn_order;start=names.index(ending.name)
    upcoming=[names[(start+i)%len(names)] for i in range(1,len(names))
              if not runtime.players[names[(start+i)%len(names)]].eliminated][:2]
    return [{'actor':actor,'required':True,'role':'short_term_planner','scope':'short_term',
             'reason':'pre_turn_update','cadence_id':f'{actor}|after_turn:{runtime.turn_number}|pre_turn_update',
             'event_seq':runtime.seq,'turn':runtime.turn_number,'seat_turn':runtime.planning_turns.get(actor,0),
             'target_seat_turn':runtime.planning_turns.get(actor,0)+1,'preceding_opponent_turns':distance,
             'full_turn_batch_required':True}
            for distance,actor in enumerate(upcoming,1)]


def full_required(value):
    return value.get('turn_batches')==1 and any(r.get('full_turn_batch_required') for r in value.get('requirements',[]))


def target_turn(value):
    requested=max(r['target_seat_turn'] for r in value['requirements'] if r.get('full_turn_batch_required'))
    board=value.get('board',{});actor=value.get('actor')
    current=board.get('planning_clock',{}).get('seat_turns',{}).get(actor,0)
    # A delayed job must not publish instructions for a turn already over.
    return max(requested,current+int(board.get('active')!=actor or board.get('phase') in {'end_step','cleanup'}))


def validate_coverage(value,sequence,coverage):
    if not isinstance(coverage,dict) or set(coverage)!=set(PHASES):raise ValueError('phase_coverage must cover precombat_main, combat and postcombat_main.')
    target=target_turn(value)
    if any(step['seat_turn']!=target for step in sequence):raise ValueError('The pre-turn batch must target the requested upcoming seat turn.')
    for phase,row in coverage.items():
        if not isinstance(row,dict) or set(row)-{'status','reason'}:raise ValueError('Coverage requires status and optional bounded reason.')
        status=row.get('status');reason=row.get('reason','')
        if status not in ('planned','no_action','reassess') or not isinstance(reason,str) or len(reason)>180:raise ValueError('Invalid phase coverage.')
        if status!='planned' and not reason.strip():raise ValueError('Unplanned phases need a concrete reason or unknown-information boundary.')
        if (status=='planned')!=any(step['phase']==phase for step in sequence):raise ValueError('Planned phases must have steps; no_action/reassess phases must not.')


def present(value):
    if value.get('turn_batches')!=1:return value
    value['wake_guidance']=value.get('wake_guidance','')+' Additionally mandatory: each of the two preceding living opponents’ end steps; these updates require full-turn actions. Gameplay never waits.'
    if 'symbolic_vocabulary' in value:
        value['symbolic_vocabulary']['sequence_format']['priority_continuation']=PILOT_GUIDANCE
        value['symbolic_vocabulary']['sequence_format']['phase_transition']='Include main_action PASS only for a real actionable window you intend to decline; empty phases advance without a prompt. Routine unplanned own priority windows pass under batch policy, so do not pad the sequence with priority passes. Include explicit priority actions such as land activations when intended.'
    for stage in value.get('publication_stages',[]):
        if stage['stage']=='short_term' and full_required(value):
            stage['instruction']=stage['instruction'].replace(
                'Invalid publication releases this background slot;',
                'Invalid publication queues long-term work concurrently, but this mandatory pre-turn batch must still publish interim actions;')
            stage['instruction']=stage['instruction'].replace(
                'This publication queues real Sol work and ends this batch, releasing capacity. review_pending acknowledges already outstanding work and also ends this batch.',
                'This publication queues real Sol work concurrently. review_pending acknowledges outstanding work. This mandatory pre-turn batch still proceeds to actions; publish concrete interim actions without waiting for Sol.')
        if stage['stage']=='actions' and full_required(value):
            stage['fields']=list(dict.fromkeys([*stage['fields'],'phase_coverage']))
            stage['instruction']+=' This mandatory pre-turn update must supply a complete upcoming-turn action_sequence: land, spells/abilities, known targets/modes, combat and postcombat sequencing, each with rationale and scheduler. Include phase_coverage for all three phases: {status:planned|no_action|reassess,reason:optional <=180 chars}. planned requires steps; other statuses require a concrete reason and no steps for that phase. reassess identifies genuinely unknown information; do not fabricate future cards or mandatory choices. Even if the goal needs revision, publish the best concrete interim batch; the pilot will review it during an actual decision.'
            stage['instruction']+=f' Target seat_turn:{target_turn(value)}.'
            stage['instruction']+=' An unknown draw is not a reason to omit an executable line from cards already known. Cover known plays first; mark only genuinely blocked phases for reassessment.'
    return value
