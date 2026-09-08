"""Durable contract-3 wake sources, called under the planning lock.

The host still owns dispatch. These functions only accumulate idempotent work.
"""
from __future__ import annotations

from . import planning_contract as contract
from .runtime_store import identity, get
from .planner_stages import load_plan


def boundary(actor, key, reason, seq):
    return {'actor':actor,'required':False,'scope':'both','cadence_id':key,
            'reason':reason,'event_seq':seq}


def apply_alarm(state, actor, value, key, seq):
    alarms=state.setdefault('decider_alarms',{})
    alarms.pop(actor,None)
    if value['mode']=='now': return boundary(actor,key,'decider_now',seq)|{'long_term_requested':value.get('long_term',False)}
    if value['mode']=='schedule':
        alarms[actor]={'id':key,'armed_after':seq,**value,'remaining':value['time']['occurrences']}
    return None


def evaluate_watches(actor, source, events):
    result=[]; fired_ids=source.setdefault('fired',[])
    for event in events:
        if event['seq']<=source['checked_seq']: continue
        for watch in source['watches']:
            if watch['watch_id'] not in fired_ids and contract.fired(watch['condition'],event):
                fired_ids.append(watch['watch_id'])
                result.append(boundary(actor,identity([source['plan_id'],watch['watch_id']]),
                                       'planner_watch',event['seq']) |
                              {'watch_id':watch['watch_id'],'condition':watch['condition']})
    if events: source['checked_seq']=max(source['checked_seq'],events[-1]['seq'])
    return result


def checkpoint(state, runtime, rows, project):
    boundaries=[]; since=state.get('wake_event_seq',0)
    by_decision={row['decision_id']:row.get('auxiliary_payload',{}).get('planner_alarm') for row in rows}
    for event in runtime.events:
        if event['seq']<=since: continue
        if event['type']=='llm_decision' and by_decision.get(event.get('decision_id')):
            item=apply_alarm(state,event['actor'],by_decision[event['decision_id']],
                             event['decision_id']+'|planner_alarm',event['seq'])
            if item: boundaries.append(item)
        for actor, alarm in list(state.get('decider_alarms',{}).items()):
            timing=alarm['time']
            if (event['seq']>alarm['armed_after'] and event['type']=='planner_phase_boundary'
                    and event.get('actor')==alarm['seat'] and event['edge']==timing['edge']
                    and event['boundary_phase']==timing['phase']):
                alarm['remaining']-=1
                if alarm['remaining']==0:
                    boundaries.append(boundary(actor,alarm['id'],'decider_alarm',event['seq'])|{'long_term_requested':alarm.get('long_term',False)})
                    del state['decider_alarms'][actor]
    state['wake_event_seq']=runtime.seq
    for actor, source in state.get('watch_sources',{}).items():
        events=[view for event in runtime.events if event['seq']>source['checked_seq']
                if (view:=project(event,actor)) is not None]
        boundaries.extend(evaluate_watches(actor,source,events))
        source['checked_seq']=runtime.seq
    for actor,source in state.get('strategic_watch_sources',{}).items():
        events=[view for event in runtime.events if event['seq']>source['checked_seq']
                if (view:=project(event,actor)) is not None]
        boundaries.extend({**item,'long_term_requested':True} for item in evaluate_watches(actor,source,events))
        source['checked_seq']=runtime.seq
    return boundaries


def history(directory, snapshot, since=0):
    chunks=[]
    while snapshot:
        chunks.append([e for e in snapshot['events'] if e['seq']>since])
        if snapshot['event_seq']<=since or not snapshot.get('previous_snapshot'): break
        snapshot=get(directory/'snapshots',snapshot['previous_snapshot'])
    return [e for chunk in reversed(chunks) for e in chunk]


def decision_rationales(events, rows, actor):
    """Join existing accepted answers to the frozen seat-private event interval.

    Do not parse prose from log detail or ask the decider to restate its intent.
    The caller bounds rows/events to the planner's immutable source frontier.
    """
    accepted={row['decision_id']:row for row in rows if row.get('actor')==actor}
    result=[]
    for event in events:
        if event.get('type')!='llm_decision' or event.get('actor')!=actor:continue
        row=accepted.get(event.get('decision_id'))
        if row is None:continue
        options=event.get('options',[])
        if row.get('auxiliary_payload',{}).get('batch'):
            chosen=row.get('chosen_labels',row.get('chosen_label'))
            if chosen is None:chosen='PASS'
        elif 'choice_value' in row:chosen=row['choice_value']
        elif 'choice_indexes' in row:chosen=[options[i] for i in row['choice_indexes']]
        else:
            index=row.get('choice_index')
            chosen=options[index] if index is not None else 'PASS'
        result.append({**{key:event.get(key) for key in ('seq','round','turn','phase','decision_id')},
                       'kind':event.get('decision_kind'),'chosen':chosen,
                       'rationale':row.get('rationale',''),
                       **({'batch':{key:row['auxiliary_payload']['batch'][key]
                                    for key in ('id','step','plan_id','rationale_source')
                                    if key in row['auxiliary_payload']['batch']}}
                          if row.get('auxiliary_payload',{}).get('batch') else {})})
    return result


def report(root, game, actor, directory, state, snapshot, rows, since):
    from . import handoff_runtime
    events=history(directory,snapshot)
    event_ids={event['decision_id']:event['seq'] for event in events if event['type']=='llm_decision' and event['actor']==actor}
    deliveries=[]; plans={}
    for row in rows[:snapshot['source_session']['accepted_prefix_count']]:
        if row.get('actor')!=actor or row['decision_id'] not in event_ids: continue
        receipt=row.get('auxiliary_payload',{}).get('runtime')
        batch=row.get('auxiliary_payload',{}).get('batch')
        if batch:plan_id=batch['plan_id']
        elif receipt:
            attachment=get(handoff_runtime.directory_for(root,game)/'attachments',receipt['attachment_id'])
            plan_id=attachment.get('plan_id')
        else:continue
        deliveries.append({'decision_id':row['decision_id'],'seq':event_ids[row['decision_id']],'plan_id':plan_id})
        if plan_id: plans[plan_id]=load_plan(directory,plan_id)
    for job in state['jobs'].values():
        if job['actor']==actor and job['status']=='published' and job.get('plan_id'):
            plan=load_plan(directory,job['plan_id'])
            if plan['event_seq']<=snapshot['event_seq']: plans[job['plan_id']]=plan
    result=contract.compare(plans,deliveries,events,actor,since)
    # Completed comparisons already covered by the previous planner packet need
    # not grow every future prompt. Keep active windows and new cast outcomes.
    result['recommendations']=[r for r in result['recommendations'] if
        r['status']=='pending_window' or (r['cast_seq'] or 0)>since or
        r['window_closed_seq'] is None or r['window_closed_seq']>since]
    return result
