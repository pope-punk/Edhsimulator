"""Frozen pilot claims and explicitly approved primitive sequences.

Only the decider can authorize execution. Host-added revisions and action IDs
bind the command to its actual execution frontier, never invent its substance.
"""
from copy import deepcopy
from .rules_adapter import digest
from .rules_state import RulesViolation,ObjectRef
from .scheduler import normalize_directive


def phase_group(phase):
    return 'combat' if phase in {'begin_combat','declare_attackers','declare_blockers','first_strike_damage','combat_damage','end_combat'} else phase


def claim(campaign,actor):
    with campaign.transaction() as state:
        action=campaign.next_action()
        if action.get('kind')!='dispatch_pilot' or action.get('actor')!=actor:raise RulesViolation('Actor does not own the decision')
        existing=state['claim']
        if existing:
            if existing['actor']!=actor or existing['revision']!=campaign.kernel.revision:raise RulesViolation('Stale frozen claim')
            return deepcopy(existing)
        seat=state['actors'][actor];packet=campaign.store.packet(actor)
        value={'actor':actor,'game':1,'revision':campaign.kernel.revision,'board':packet,
               'plans':deepcopy(seat['plans']),'previous_board':deepcopy(seat.get('last_delivered_board')),
               'snooze':deepcopy(seat['snooze']),'context_handling':1,
               'rejection':seat.get('last_rejection')}
        if 'long_term' not in seat['plans']:value['standing']=seat['standing']
        from .primitive_inspection import freeze
        value['_knowledge']=freeze(campaign,actor,packet)
        rows=campaign.evidence(actor)
        value['evidence_through']=rows[-1]['id'] if rows else 0
        value['rationales']=[row for row in rows if row['kind'] in {'rationale','batch_approval'}]
        value['messages']=deepcopy(state['messages'])
        state['claim_serial']=state.get('claim_serial',0)+1
        value['claim_id']=digest({'binding':campaign.binding,'commit':campaign.store.committed_head(),'actor':actor,'claim_serial':state['claim_serial']})
        state['claim']=value
        return deepcopy(value)


def delivered(campaign,actor,claim_id):
    with campaign.transaction() as state:
        current=state['claim']
        if not current or current['actor']!=actor or current['claim_id']!=claim_id:raise RulesViolation('Unknown delivery claim')
        state['actors'][actor]['last_delivered_board']=deepcopy(current['board'])


def bind_command(campaign,actor,value,request_id):
    if type(value) is not dict or set(value)&{'revision','actor','action_id'}:raise RulesViolation('Host supplies revision, actor and action identity')
    def resolve(value):
        if type(value) is dict and set(value)=={'owned_card','zone'}:
            # An explicitly proposed symbolic source follows a known own card
            # only when it is visible in the approved destination at execution.
            try:obj=campaign.kernel.state.get(campaign.kernel.state.current(value['owned_card']))
            except (RulesViolation,KeyError):raise RulesViolation('Symbolic object is unavailable') from None
            campaign.store._adapter._visible_ref(obj.ref.to_json(),actor)
            if obj.owner!=actor or obj.zone.value!=value['zone']:raise RulesViolation('Symbolic object is unavailable')
            return obj.ref.to_json()
        if type(value) is dict:return {k:resolve(v) for k,v in value.items()}
        if type(value) is list:return [resolve(v) for v in value]
        return value
    result=resolve(deepcopy(value));result['revision']=campaign.kernel.revision
    if result.get('kind') in {'cast','activate','play_land','unlock_room','pay_mana','decline_cast'}:result['action_id']=request_id
    return result


def submit(campaign,actor,claim_id,request_id,command,rationale,scheduler):
    state=campaign.state();current=state['claim']
    if not current or current['actor']!=actor or current['claim_id']!=claim_id:raise RulesViolation('Answer does not own the frozen claim')
    directive=normalize_directive(scheduler)
    if directive['mode']=='snooze_stack':raise RulesViolation('Use resolve_my_sequence')
    bound=bind_command(campaign,actor,command,request_id)
    if current['revision']!=campaign.kernel.revision:raise RulesViolation('Frozen decision revision changed')
    return campaign.submit(actor,request_id,bound,rationale=rationale,
        plan_refs={k:v['id'] for k,v in current['plans'].items()},control={'scheduler':directive,'clear_approval':True})


def approve(campaign,actor,claim_id,*,approve_ids,reject_ids,added=(),overrides=None,rejection_rationale="",pass_priority=True,resume_after_passes=True):
    if type(approve_ids) is not list or type(reject_ids) is not list or type(pass_priority) is not bool or type(resume_after_passes) is not bool:
        raise RulesViolation('Invalid batch approval')
    with campaign.transaction() as state:
        frontier=campaign.next_action()
        if frontier.get('kind')!='dispatch_pilot' or frontier.get('actor')!=actor:
            raise RulesViolation('Actor does not own the campaign frontier')
        current=state['claim'];seat=state['actors'][actor]
        if not current or current['actor']!=actor or current['claim_id']!=claim_id:raise RulesViolation('Batch does not own this frozen claim')
        if current['revision']!=campaign.kernel.revision:raise RulesViolation('Frozen decision revision changed')
        if current['board']['decision']['kind']!='priority':raise RulesViolation('Batch approval requires a priority decision')
        proposal=current['plans'].get('actions',{})
        steps=proposal.get('value',{}).get('action_sequence',[]);by_id={s['id']:s for s in steps}
        if (len(set(approve_ids+reject_ids))!=len(approve_ids+reject_ids)
                or set(approve_ids+reject_ids)!=set(by_id)):
            raise RulesViolation('Approve or reject every frozen proposal exactly once')
        overrides=overrides or {}
        if type(overrides) is not dict or set(overrides)-set(approve_ids):raise RulesViolation('Overrides require approved step IDs')
        if reject_ids and (type(rejection_rationale) is not str or not rejection_rationale.strip() or len(rejection_rationale)>300):
            raise RulesViolation('Explain rejected proposals in at most 300 characters')
        chosen=[]
        for key in approve_ids:
            original=by_id[key];replacement=overrides.get(key,original)
            if type(replacement) is not dict or replacement.get('id')!=key:raise RulesViolation('Override must retain its step ID')
            if {k:v for k,v in replacement.items() if k!='rationale'}=={k:v for k,v in original.items() if k!='rationale'}:replacement=original
            chosen.append(deepcopy(replacement))
        if not isinstance(added,(list,tuple)):raise RulesViolation('Added steps require a list')
        chosen.extend(deepcopy(added))
        from .primitive_planning import validate_actions,PHASES
        coverage={phase:{'status':'planned'} if any(s.get('phase')==phase for s in chosen) else {'status':'no_action','reason':'No step included in this explicit approval.'} for phase in PHASES}
        validate_actions({'action_sequence':chosen,'phase_coverage':coverage},{'reasons':[]})
        seat['approved']={'id':digest({'claim':claim_id,'approve':approve_ids,'reject':reject_ids,
                                      'pass_priority':pass_priority,'resume_after_passes':resume_after_passes,'steps':chosen}),
            'steps':chosen,'cursor':0,'pass_priority':pass_priority,'resume_after_passes':resume_after_passes,
            'proposal_id':proposal.get('id'),'turn_limit':max([s['seat_turn'] for s in chosen]+[seat.get('turns',0)+1])}
        campaign.record(actor,'batch_approval',{'claim_id':claim_id,**seat['approved'],'rejected':reject_ids,'rejection_rationale':rejection_rationale})
        state['claim']=None
        return {'accepted':True,'approved':len(chosen),'approval_id':seat['approved']['id']}


def apply_control(campaign,state,actor,control):
    seat=state['actors'][actor]
    if not control:return
    if control.get('clear_approval'):seat['approved']=None
    if 'sequence' in control:
        expected=control['sequence'];approved=seat['approved']
        if not approved or approved['id']!=expected['id'] or approved['cursor']!=expected['cursor']:
            raise RulesViolation('Prepared approved-sequence cursor changed')
        if expected.get('advance'):approved['cursor']+=1
    if 'scheduler' in control:
        directive=deepcopy(control['scheduler'])
        directive['remaining']=directive.get('time',{}).get('occurrences')
        seat['snooze']=directive


def observe(campaign,state,actor,command):
    # Unapproved responses and new opposing actions stop sequence execution.
    # An ordinary opposing pass preserves only explicit continuation approval.
    for other,seat in state['actors'].items():
        approved=seat['approved']
        if other!=actor and approved and (command['kind']!='pass' or not approved['resume_after_passes']):seat['approved']=None
        snooze=seat['snooze']
        if not snooze:continue
        wake=snooze.get('wake_condition')
        if other!=actor and command['kind']!='pass' and (snooze['mode']=='resolve_my_sequence' or wake=='opponent_action'):
            seat['snooze']=None
        elif command['kind']=='cast' and (wake=='any_spell' or wake=='opponent_spell' and other!=actor):seat['snooze']=None
        elif wake=='targeted_or_attacked' and command['kind'] in {'cast','activate','attack'}:
            # Conservative wake on new targeting/combat, never a silent pass.
            seat['snooze']=None
    events=campaign.kernel.semantic_events[state.get('scheduler_event_cursor',0):]
    previous=state.get('scheduler_phase')
    for event in events:
        if event['kind']=='trigger_placed':
            for owner,seat in state['actors'].items():
                if event['controller']!=owner:
                    seat['approved']=None
                    if seat['snooze'] and (seat['snooze']['mode']=='resolve_my_sequence' or seat['snooze'].get('wake_condition')=='opponent_action'):seat['snooze']=None
        if event['kind']!='step_began':continue
        if event['step']=='cleanup':state['actors'][event['active']]['approved']=None
        phase=phase_group(event['step'])
        for seat in state['actors'].values():
            snooze=seat['snooze']
            if not snooze or not snooze.get('time'):continue
            deadline=snooze['time']
            hit=(phase==deadline['phase'] and phase!=previous if deadline['edge']=='beginning'
                 else previous==deadline['phase'] and phase!=previous)
            if hit:
                snooze['remaining']-=1
                if snooze['remaining']<=0:seat['snooze']=None
        previous=phase
    state['scheduler_phase']=previous;state['scheduler_event_cursor']=len(campaign.kernel.semantic_events)


def automatic(campaign):
    state=campaign.state();action=campaign.next_action()
    if state['claim'] or action.get('kind')!='dispatch_pilot':return False
    actor=action['actor'];seat=state['actors'][actor];approved=seat['approved']
    if action['decision_kind']!='priority':
        if approved:
            with campaign.transaction() as value:value['actors'][actor]['approved']=None
        return False
    chosen=None;control=None;rationale=None
    if approved:
        cursor=approved['cursor'];steps=approved['steps'];turn=seat.get('turns',0);phase=phase_group(campaign.kernel.phase)
        if turn>approved['turn_limit']:
            with campaign.transaction() as value:value['actors'][actor]['approved']=None
            return False
        if cursor<len(steps) and steps[cursor]['seat_turn']==turn and steps[cursor]['phase']==phase:
            step=steps[cursor];chosen=step['command'];rationale=step['rationale']
            control={'scheduler':normalize_directive(step['scheduler']),
                     'sequence':{'id':approved['id'],'cursor':cursor,'advance':True}}
        elif approved['pass_priority']:
            chosen={'kind':'pass'};rationale='Priority pass explicitly authorized by batch '+approved['id']
            control={'sequence':{'id':approved['id'],'cursor':cursor,'advance':False}}
    if chosen is None and seat['snooze']:
        snooze=seat['snooze'];mode=snooze['mode']
        active_own=any(frame['controller']==actor for frame in campaign.kernel.stack)
        if mode=='snooze_table' or mode=='resolve_my_sequence' and active_own:
            chosen={'kind':'pass'};rationale='Priority pass under the pilot-authored '+mode+' directive.'
    if chosen is None:return False
    request_id='auto:'+digest({'commit':campaign.store.committed_head(),'actor':actor,'command':chosen,'control':control})
    try:
        command=bind_command(campaign,actor,chosen,request_id)
        campaign.submit(actor,request_id,command,rationale=rationale,control=control)
    except RulesViolation as exc:
        with campaign.transaction() as value:
            value['actors'][actor]['approved']=None;value['actors'][actor]['snooze']=None
            value['actors'][actor]['last_rejection']=str(exc)
        return False
    return True
