"""Execute one explicit pilot approval in a replay, with one final checkpoint.

Approvals are immutable references, not an agent-authored program. No waiting,
background polling, retries of alternate plays, or action selection occurs here.
"""
from __future__ import annotations

from pathlib import Path
import time

from . import sequence_contract as contract
from .runtime_store import get,put,read,write,identity,serialized
from .referee import DecisionTape


def batch_directory(root,game):
    return Path(root)/f'game_{game:02d}'/'handoffs'/'sequences'


def executed_plan_steps(root,game,actor,plan_id,plan,rows=None):
    """Factual progress follows the action component across strategic view updates."""
    from . import campaign,planner_runtime
    from .planner_stages import load_plan
    if not plan.get('action_sequence'):return []
    if rows is None:rows=campaign.read_jsonl(Path(root)/f'game_{game:02d}'/'decisions.jsonl')
    target=plan.get('owned_component_ids',{}).get('actions')
    matching={plan_id:True};ids=[]
    for row in rows:
        batch=row.get('auxiliary_payload',{}).get('batch')
        if row.get('actor')!=actor or not batch or batch.get('automatic_priority'):continue
        key=batch['plan_id']
        if key not in matching:
            other=load_plan(planner_runtime.directory_for(root,game),key)
            matching[key]=bool(target and other.get('owned_component_ids',{}).get('actions')==target)
        if matching[key] and batch['step'] not in ids:ids.append(batch['step'])
    return ids


class SequenceTape(DecisionTape):
    def __init__(self,path,request_path,execution):
        super().__init__(path,request_path)
        self.execution=execution;self.generated=[];self.planned_generated=0;self.contexts={};self.runtime=None
        self.reason='sequence_complete';self.stop_context={};self.last_event_index=None;self.blocked_reason=None
        self.limit=read(Path(path).parent.parent/'HOST_RUNTIME.json',{}).get('max_decisions')

    def resolve(self,request):
        if request['decision_id'] in self.script:
            result=super().resolve(request)
            row=self.script[request['decision_id']]
            if row.get('auxiliary_payload',{}).get('batch',{}).get('id')==self.execution['id']:
                self.last_event_index=len(self.runtime.events)
            elif self.last_event_index is not None:
                if (request['actor']==self.execution['actor'] or request['kind']!='priority_action'
                        or result[0] is not None):
                    self.blocked_reason='intervening_choice'
            return result
        runtime=self.runtime;execution=self.execution;actor=execution['actor']
        position=execution.get('offset',0)+self.planned_generated;steps=execution['steps']
        def stop(reason):
            self.reason=reason
            expected=steps[position] if position<len(steps) else {}
            self.stop_context={'decision_id':request['decision_id'],'actual_kind':request['kind'],
                'actual_phase':request['phase'],'expected_kind':expected.get('kind'),'expected_phase':expected.get('phase')}
            return super(SequenceTape,self).resolve(request)
        if self.limit is not None and len(self.script)>=self.limit:return stop('decision_limit')
        if position>=len(steps):return stop('sequence_complete')
        if request['actor']!=actor:return stop('handoff')
        if self.blocked_reason:return stop(self.blocked_reason)
        step=steps[position]
        if request.get('rebase_existing_decision'):return stop('branch_changed')
        board=request.get('public_state',{})
        clock=board.get('planning_clock',{})
        if board.get('active')!=actor or clock.get('seat_turns',{}).get(actor)!=step['seat_turn']:
            return stop('turn_changed')
        if self.last_event_index is not None:
            for index in range(self.last_event_index,len(runtime.events)):
                event=runtime.events[index]
                kind=event['type'];who=event.get('actor')
                if kind in {'draw','reveal','reveal_hand','reveal_to_hand','explore_reveal','miracle_reveal','random_choice'} or (
                        who==actor and kind in {'look_top','top_reorder','scry','surveil','tutor','tutor_top','put_on_top'}):
                    return stop('new_information')
                if who not in {None,actor} and (kind in {'cast','cast_transformed','stack_add','attack','declare_attackers','combat_damage'}
                                                or 'activat' in kind):
                    return stop('opponent_intervention')
                if kind.startswith('combat_damage') or kind in {
                        'counterspell','countered','spell_fizzle','ability_countered','ability_fizzle','trigger_countered',
                        'control_change','control_exchange','phase_out','phase_in','phased_out','phased_in',
                        'eliminated','leaves_game','mill','discard','ltb','messageboard_message'}:
                    return stop('material_event:'+kind)
        automatic=(execution.get('policy',{}).get('pass_priority',False)
                   and request['kind']=='priority_action' and request['phase'] in contract.PHASES
                   and request.get('allow_pass') and not request.get('required_indexes')
                   and not (step['kind']==request['kind'] and step['phase']==request['phase']))
        if automatic:
            if execution.get('automatic_priority_passes',0)+len(self.generated)-self.planned_generated>=64:
                return stop('priority_pass_budget')
            step={'id':'priority:'+request['decision_id'],'kind':request['kind'],'phase':request['phase'],
                  'choice':None,'requires':[],'rationale':'Pass priority under the approved sequence policy.',
                  'scheduler':{k:v for k,v in request.get('scheduler',{}).get('active',{'mode':'hold_full_control'}).items()
                               if k in {'mode','time','wake_condition','objects'}}}
        failed=contract.guards_hold(step['requires'],board)
        if failed:return stop('prerequisite_changed:'+failed)
        try:index=contract.match(step,request)
        except ValueError as exc:return stop(str(exc))
        # Validate snoozed object availability before the referee consumes it.
        from .scheduler import PilotScheduler
        if not automatic and step['scheduler'].get('objects'):
            legal_uids={item.source_uid for item in PilotScheduler.eligible_objects(runtime,runtime.players[actor])}
            if any(uid not in legal_uids for uid in step['scheduler']['objects']):
                return stop('snoozed_object_changed')
        fields=({'choice_indexes':index,'chosen_labels':[request['options'][i] for i in index]}
                if request.get('multi_select') else
                {'choice_index':index,'chosen_label':request['options'][index] if index is not None else None})
        if automatic:source='approved_priority_policy'
        elif any(item['id']==step['id'] for item in execution['approval'].get('add',[])):source='pilot_added'
        elif ('rationale' in execution['approval'].get('overrides',{}).get(step['id'],{})
              and step['id'] not in execution.get('ignored_rationale_overrides',[])):source='pilot_override'
        else:source='adopted_planner'
        batch={'id':execution['id'],'step':step['id'],'plan_id':execution['plan_id'],
               'origin_claim':execution['claim_id'],'rationale_source':source,
               'symbolic_choice':{key:step[key] for key in ('kind','phase','choice')}}
        if automatic:batch['automatic_priority']=True
        record={'decision_id':request['decision_id'],'actor':actor,**fields,'rationale':step['rationale'],
                'accepted_at':execution['now'](),'chunk':execution['prefix_count']+len(self.generated)+1,
                'auxiliary_payload':{'scheduler':step['scheduler'],'batch':batch}}
        # One compact audit object per batch, never a full packet per internal choice.
        keep=('decision_id','game','actor','kind','phase','round','turn','prompt','options',
              'allow_pass','multi_select','required_indexes','rationale_policy','seat_view','turn_order')
        audit={key:request[key] for key in keep if key in request}
        audit['scheduler']={'active':step['scheduler']}
        self.contexts[request['decision_id']]={'context_id':identity(audit),'request':audit}
        batch['context_id']=identity(audit)
        self.script[request['decision_id']]=record;self.generated.append(record)
        if not automatic:self.planned_generated+=1
        self.last_event_index=len(runtime.events)
        return super().resolve(request)


@serialized
def submit(root,actor,envelope):
    from . import campaign,handoff_runtime,pilot_handoff,pilot_dispatch,planner_runtime
    if (not isinstance(envelope,dict) or set(envelope)!={'game','actor','decision_id','pilot_context_id','claim_id','batch'}
            or type(envelope.get('game')) is not int or contract.size(envelope)>contract.MAX_BYTES+1024):
        raise SystemExit('A batch envelope contains game, actor, decision_id, pilot_context_id, claim_id and batch only.')
    game=envelope['game'];directory=batch_directory(root,game)
    hdir=handoff_runtime.directory_for(root,game)
    claim=handoff_runtime.claim_record(hdir,envelope['claim_id'])
    if any(envelope.get(key)!=claim.get(key) for key in ('game','actor','decision_id','pilot_context_id')) or claim['actor']!=actor:
        raise SystemExit('Batch identity does not match this seat claim.')
    if read(directory.parent.parent/'game_config.json',{}).get('planning_contract')!=4:
        raise SystemExit('Approved sequences require planning contract 4; never migrate a started game.')
    binding={'claim_id':envelope['claim_id'],'approval':envelope['batch']}
    batch_id=identity(binding);path=directory/'executions'/(batch_id+'.json')
    rows=campaign.read_jsonl(directory.parent.parent/'decisions.jsonl')
    accepted=[row for row in rows if row.get('auxiliary_payload',{}).get('batch',{}).get('id')==batch_id]
    if accepted:
        # Acceptance wins over a lost final acknowledgement. Never run the suffix.
        if handoff_runtime._current(root).get('decision_id') in {row['decision_id'] for row in accepted}:
            campaign.advance(root,game)
        route=read(handoff_runtime._route_path(hdir,claim['route_id']))
        if route and route.get('state')!='completed':
            route.update(state='completed',completed_at=time.time(),batch_id=batch_id,accepted=len(accepted),recovered_commit=True)
            write(handoff_runtime._route_path(hdir,claim['route_id']),route)
        return {'state':'already_accepted','game':game,'batch_id':batch_id,'accepted':len(accepted),'invocation_id':claim['invocation_id']}
    if any(row['decision_id']==claim['decision_id'] for row in rows):
        raise SystemExit('The origin decision already accepted a different response.')
    action,_,route,claim=handoff_runtime.validate_claim(root,actor,envelope['claim_id'])
    if (Path(root)/'PROBE_PAUSED.json').exists():raise SystemExit('The probe is paused.')
    packet=read(Path(action['context']))
    if pilot_handoff.fingerprint(packet)!=claim['pilot_context_id']:
        raise SystemExit('Current seat packet changed after this claim was frozen.')
    request=pilot_handoff.packet_request(packet)
    config=campaign._game_config_with_bound_surface(root,campaign.load_manifest(root),game)
    concise=config.get('turn_batches')==1
    if concise and request.get('turn_batches')!=1:
        raise SystemExit('Batch policy was not advertised in the frozen pilot input.')
    if request['phase'] not in {'precombat_main','postcombat_main'} or request['kind'] not in {'main_action','land_play'}:
        raise SystemExit('Approve a sequence during an existing own main-phase action, never a separate planning turn.')
    attachment=get(hdir/'attachments',claim['attachment_id']);plan_id=attachment.get('plan_id')
    if not plan_id:raise SystemExit('No completed plan was delivered for this claim; use an ordinary decision.')
    plan=planner_runtime.load_plan(planner_runtime.directory_for(root,game),plan_id)
    from .planning_contract import known_facts
    _,uids=known_facts(request['public_state'])
    try:
        steps=contract.approve(envelope['batch'],plan,actor,request['public_state'],uids,concise_overrides=concise)
        if plan.get('agent_architecture')==1:
            executed=executed_plan_steps(root,game,actor,plan_id,plan,rows)
            repeated=[s['id'] for s in steps if s['id'] in executed]
            if repeated:raise ValueError('already_executed_steps:'+','.join(repeated))
        contract.match(steps[0],request)
        failed=contract.guards_hold(steps[0]['requires'],request['public_state'])
        if failed:raise ValueError('prerequisite_changed:'+failed)
        if request['public_state'].get('planning_clock',{}).get('seat_turns',{}).get(actor)!=steps[0]['seat_turn']:
            raise ValueError('turn_changed')
    except ValueError as exc:raise SystemExit('Batch not accepted: '+str(exc)) from exc
    if request['public_state'].get('active')!=actor:raise SystemExit('A sequence belongs to the active seat only.')
    approval_id=put(directory/'approvals',binding)
    assert approval_id==batch_id
    from .turn_batches import execution_policy
    policy=execution_policy(config,envelope['batch'])
    originals={s['id']:s for s in plan.get('action_sequence',[])}
    ignored=[s['id'] for s in steps if concise and s['id'] in originals
             and 'rationale' in envelope['batch'].get('overrides',{}).get(s['id'],{})
             and all(s.get(k,[])==originals[s['id']].get(k,[]) for k in ('choice','scheduler','requires'))]
    execution={'id':batch_id,'actor':actor,'steps':steps,'approval':envelope['batch'],
               'policy':policy,'ignored_rationale_overrides':ignored,
               'claim_id':envelope['claim_id'],'plan_id':plan_id,'prefix_count':len(rows),'now':campaign.now}
    handoff_runtime.acknowledge(root,actor,envelope['claim_id'])
    manifest=campaign.load_manifest(root);config=campaign._game_config_with_bound_surface(root,manifest,game)
    candidate=directory.parent.parent/'.candidate_sequence.jsonl'
    pending=directory.parent.parent/'.candidate_sequence_request.json'
    route.update(state='submitting',submitting_at=time.time())
    write(handoff_runtime._route_path(hdir,claim['route_id']),route)
    try:
        outcome=campaign._run(root,config,directory.parent.parent/'decisions.jsonl',pending,sequence_execution=execution)
        if outcome['state']=='release_blocker':
            write(path,{'state':'rules_blocker','accepted':0})
            campaign._adjudicate_rules_blocker_draw(root,game,outcome['error'])
            return {'state':'stop','game':game,'reason':'rules_blocker','accepted':0}
        tape=execution['tape']
        if not tape.generated:
            raise SystemExit('Batch accepted no choices: '+tape.reason)
        if outcome.get('request',{}).get('rebase_existing_decision'):
            raise SystemExit('Batch stopped at a changed accepted branch; no choices committed.')
        result={'state':'accepted','game':game,'batch_id':batch_id,'accepted':len(tape.generated),
                'planned_accepted':tape.planned_generated,'automatic_priority_passes':len(tape.generated)-tape.planned_generated,
                'reason':tape.reason if outcome['state']=='need_decision' else outcome['state'],
                'stop_context':tape.stop_context,
                'invocation_id':claim['invocation_id']}
        # Audit precedes the atomic tape commit; one file stores all compact contexts.
        record={'result':result,'contexts':tape.contexts,'plan_id':plan_id,'origin_claim':envelope['claim_id'],
                'ignored_rationale_overrides':ignored}
        if policy['resume_after_passes']:
            record['program_id']=put(directory/'programs',{'steps':steps,'actor':actor,'approval_id':batch_id,'policy':policy})
        _save_continuation(root,game,batch_id,record,rows+tape.generated)
        campaign.write_jsonl(candidate,[*rows,*tape.generated])
        candidate.replace(directory.parent.parent/'decisions.jsonl')
        campaign._commit_checkpoint_outcome(root,manifest,config,outcome)
        route.update(state='completed',completed_at=time.time(),batch_id=batch_id,accepted=len(tape.generated))
        write(handoff_runtime._route_path(hdir,claim['route_id']),route)
        pilot_dispatch.mark_observed(root,action)
        return result
    except BaseException:
        committed=any(row.get('auxiliary_payload',{}).get('batch',{}).get('id')==batch_id
                      for row in campaign.read_jsonl(directory.parent.parent/'decisions.jsonl'))
        route.update(state='accepted_pending_checkpoint' if committed else 'claimed')
        write(handoff_runtime._route_path(hdir,claim['route_id']),route)
        raise
    finally:
        candidate.unlink(missing_ok=True);pending.unlink(missing_ok=True)


def _save_continuation(root,game,batch_id,record,rows):
    """One small pending index; the bounded approved program is stored once."""
    from . import pilot_handoff
    directory=batch_directory(root,game)
    index=read(directory/'pending.json',{})
    if record.get('program_id'):
        program=get(directory/'programs',record['program_id']);actor=program['actor']
        record['resume_session']=pilot_handoff.session_descriptor(root,game,actor,rows)
        if record['result']['reason']=='handoff' and record['result'].get('planned_accepted',record['result']['accepted'])<len(program['steps']):
            index[actor]=batch_id
        elif index.get(actor)==batch_id:index.pop(actor)
    write(directory/'executions'/(batch_id+'.json'),record)
    if index or (directory/'pending.json').exists():write(directory/'pending.json',index)


@serialized
def continue_pending(root):
    """Host-only pre-dispatch hook. Never claims an input or chooses an action."""
    from . import campaign,handoff_runtime,pilot_handoff
    root=Path(root);action=read(root/'NEXT_ACTION.json',{}).get('next_action',{})
    if action.get('kind')!='dispatch_pilot' or (root/'PROBE_PAUSED.json').exists() or (root/'HOST_PAUSED.json').exists():
        return {'state':'idle'}
    campaign._require_no_prepared_learning_transaction(root,'continue an approved sequence')
    game=action['game'];actor=action['actor'];directory=batch_directory(root,game)
    index=read(directory/'pending.json',{});batch_id=index.get(actor)
    if not batch_id:return {'state':'idle'}
    route=read(handoff_runtime._route_path(directory.parent,action['dispatch']['route_id']))
    # An already delivered input must remain immutable, even if nobody answered.
    if route.get('state')!='prepared':return {'state':'idle'}
    record=read(directory/'executions'/(batch_id+'.json'))
    rows=campaign.read_jsonl(directory.parent.parent/'decisions.jsonl')
    if any(row['decision_id']==action['decision_id'] for row in rows):
        # The tape committed but a previous host died during checkpoint writing.
        campaign.advance(root,game)
        return {'state':'reconciled'}
    def clear(reason):
        index.pop(actor,None);write(directory/'pending.json',index)
        record['continuation_stopped']=reason;write(directory/'executions'/(batch_id+'.json'),record)
        return {'state':'invalidated','reason':reason}
    if not pilot_handoff.can_resume_session(record['resume_session'],root,game,actor,rows):return clear('branch_changed')
    program=get(directory/'programs',record['program_id'])
    approved=get(directory/'approvals',batch_id)
    config=campaign._game_config_with_bound_surface(root,campaign.load_manifest(root),game)
    from .turn_batches import execution_policy
    policy=execution_policy(config,approved['approval'])
    if (program['actor']!=actor or program['approval_id']!=batch_id or not policy['resume_after_passes']
            or program.get('policy',policy)!=policy):
        raise SystemExit('Continuation program does not match the pilot approval.')
    origin=handoff_runtime.claim_record(directory.parent,approved['claim_id'])
    if origin['actor']!=actor or record['origin_claim']!=approved['claim_id']:
        raise SystemExit('Continuation origin belongs to another claim.')
    if get(directory.parent/'attachments',origin['attachment_id']).get('plan_id')!=record['plan_id']:
        raise SystemExit('Continuation plan binding changed.')
    execution={'id':batch_id,'actor':actor,'steps':program['steps'],'approval':approved['approval'],
               'policy':policy,'ignored_rationale_overrides':record.get('ignored_rationale_overrides',[]),
               'automatic_priority_passes':record['result'].get('automatic_priority_passes',0),
               'claim_id':record['origin_claim'],'plan_id':record['plan_id'],
               'offset':record['result'].get('planned_accepted',record['result']['accepted']),'prefix_count':len(rows),'now':campaign.now}
    config=campaign._game_config_with_bound_surface(root,campaign.load_manifest(root),game)
    request_path=directory.parent.parent/'.continuation_request.json'
    candidate=directory.parent.parent/'.continuation_tape.jsonl'
    try:
        outcome=campaign._run(root,config,directory.parent.parent/'decisions.jsonl',request_path,sequence_execution=execution)
        if outcome['state']=='release_blocker':
            clear('rules_blocker');campaign._adjudicate_rules_blocker_draw(root,game,outcome['error'])
            return {'state':'stop','reason':'rules_blocker'}
        tape=execution['tape']
        if outcome.get('request',{}).get('rebase_existing_decision'):return clear('branch_changed')
        if not tape.generated:return clear(tape.reason)
        # Audit and continuation binding precede the tape commit. Crash retries
        # must reconcile the committed tape before calling this hook again.
        record['contexts'].update(tape.contexts)
        record['result']={**record['result'],'accepted':record['result']['accepted']+len(tape.generated),
                          'planned_accepted':execution['offset']+tape.planned_generated,
                          'automatic_priority_passes':execution['automatic_priority_passes']+len(tape.generated)-tape.planned_generated,
                          'reason':tape.reason if outcome['state']=='need_decision' else outcome['state'],'stop_context':tape.stop_context}
        _save_continuation(root,game,batch_id,record,rows+tape.generated)
        campaign.write_jsonl(candidate,rows+tape.generated);candidate.replace(directory.parent.parent/'decisions.jsonl')
        campaign._commit_checkpoint_outcome(root,campaign.load_manifest(root),config,outcome)
        route.update(state='continued',completed_at=time.time(),accepted=len(tape.generated),batch_id=batch_id)
        write(handoff_runtime._route_path(directory.parent,route['route_id']),route)
        return {'state':'continued','accepted':len(tape.generated),'batch_id':batch_id}
    finally:
        request_path.unlink(missing_ok=True);candidate.unlink(missing_ok=True)


def planner_report(root,game,actor,rows,decision_ids):
    """Only frozen, accepted execution provenance; proposals are referenced by ID."""
    grouped={};directory=batch_directory(root,game)
    for row in rows:
        batch=row.get('auxiliary_payload',{}).get('batch')
        if row.get('actor')==actor and row['decision_id'] in decision_ids and batch and not batch.get('automatic_priority'):
            grouped.setdefault(batch['id'],[]).append(batch['step'])
    reports=[]
    for batch_id,executed in list(grouped.items())[-16:]:
        approval=get(directory/'approvals',batch_id)['approval']
        execution=read(directory/'executions'/(batch_id+'.json'))
        reports.append({'batch_id':batch_id,'executed':executed,
                        'approved':approval['approve'],'rejected':approval['reject'],
                        'added':[step['id'] for step in approval.get('add',[])],
                        'overridden':sorted(set(approval.get('overrides',{}))-set(execution.get('ignored_rationale_overrides',[]))),
                        **({'rejection_rationale':approval['rejection_rationale']} if 'rejection_rationale' in approval else {}),
                        'stopped_reason':execution.get('continuation_stopped',execution['result']['reason'])})
    result={'batches':reports,'earlier_batches_omitted':max(0,len(grouped)-16)}
    earlier=[]
    for batch_id in list(grouped)[:-16]:
        approval=get(directory/'approvals',batch_id)['approval']
        if 'rejection_rationale' in approval:
            earlier.append({'batch_id':batch_id,'rejection_rationale':approval['rejection_rationale']})
    if earlier:result['earlier_rejection_explanations']=earlier
    return result


def review_context(directory,row):
    batch=row['auxiliary_payload']['batch']
    execution=read(Path(directory)/'handoffs'/'sequences'/'executions'/(batch['id']+'.json'))
    context=execution['contexts'][row['decision_id']]
    if identity(context['request'])!=context['context_id'] or context['context_id']!=batch['context_id']:
        raise ValueError('Batch review context changed')
    return context


def review_deliveries(root,game,actor,rows):
    """One receipt per delivery and one approval per batch, referenced by decisions."""
    from . import handoff_runtime
    hdir=handoff_runtime.directory_for(root,game);directory=batch_directory(root,game)
    deliveries={};batches={};decisions={}
    for row in rows:
        if row.get('actor')!=actor:continue
        auxiliary=row.get('auxiliary_payload',{})
        batch=auxiliary.get('batch');binding=auxiliary.get('runtime')
        if batch:
            batch_id=batch['id']
            if batch_id not in batches:
                approval=get(directory/'approvals',batch_id)
                claim=handoff_runtime.claim_record(hdir,approval['claim_id'])
                attachment_id=claim['attachment_id']
                deliveries.setdefault(attachment_id,get(hdir/'attachments',attachment_id))
                execution=read(directory/'executions'/(batch_id+'.json'))
                batches[batch_id]={'approval':approval['approval'],'plan_id':batch['plan_id'],
                                  'attachment_id':attachment_id,'result':execution['result']}
            decisions[row['decision_id']]={'batch_id':batch_id,'step':batch['step'],
                                          'rationale_source':batch['rationale_source']}
        elif binding:
            key=binding['attachment_id']
            deliveries.setdefault(key,get(hdir/'attachments',key))
            decisions[row['decision_id']]={'attachment_id':key}
    # Full publications already occur once in private_continuity.plans.
    return {'decisions':decisions,'batches':batches,
            'attachments':{key:{k:v for k,v in value.items() if k!='plan'} for key,value in deliveries.items()}}
