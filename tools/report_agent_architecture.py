"""Compare split-role work and bounded artifacts using collected metadata.

No prompts, rationale text, cards or message bodies enter the report. Use only
after the local collector closes the requested segment.
"""
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
from analyze_cache_probe import analyze
from report_host_game import read,stats


def report(root,game,segments):
    roles=defaultdict(list);counts=Counter();errors=[];events=[]
    for segment in segments:
        collection=read(segment/'collection.json')
        data=[json.loads(s) for s in (segment/'timing.jsonl').read_text(encoding='utf8').splitlines() if s.strip()]
        if collection['gaps'] or len(data)!=collection['events']:raise ValueError('Telemetry segment is incomplete; do not certify it.')
        events+=data
        for row in analyze(data)['requests']:roles[row.get('role','unknown')].append(row)
    for event in events:
        if event['event']=='tool_arrived':
            counts['tool:'+str(event.get('tool'))]+=1
            counts['tool:'+str(event.get('role'))+':'+str(event.get('tool'))]+=1
            if event.get('strategic_disposition'):counts['strategic:'+event['strategic_disposition']]+=1
        if event['event']=='tool_returned' and event.get('success') is False:
            errors.append({k:event.get(k) for k in ('role','publication_stage','error_sha256','validation_sections')})
    grouped={};per_round={}
    for role,rows in roles.items():
        for row in rows:
            bucket=per_round.setdefault(str(row.get('source_round')),{}).setdefault(role,{'requests':0,'input_tokens':0,'output_tokens':0})
            bucket['requests']+=1
            bucket['input_tokens']+=row['usage'].get('inputTokens',0)
            bucket['output_tokens']+=row['usage'].get('outputTokens',0)
        grouped[role]={'inference_requests':len(rows),'inference_seconds':stats([r['seconds'] for r in rows if r['seconds'] is not None]),
            'input_tokens':stats([r['usage']['inputTokens'] for r in rows if 'inputTokens' in r['usage']]),
            'input_tokens_sum':sum(r['usage'].get('inputTokens',0) for r in rows),
            'cached_input_tokens_sum':sum(r['usage'].get('cachedInputTokens',0) for r in rows),
            'output_tokens_sum':sum(r['usage'].get('outputTokens',0) for r in rows),
            'reasoning_output_tokens_sum':sum(r['usage'].get('reasoningOutputTokens',0) for r in rows),
            'origins':dict(Counter(r['origin'] for r in rows))}
    d=root/f'game_{game:02d}'/'continuity';state=read(d/'workboard.json');publications=[]
    for path in (d/'stage_publications').glob('*.json'):
        value=read(path)
        publications.append({k:value.get(k) for k in ('role','stage','changed_components','state','telemetry')})
    stages=Counter((r.get('role') or 'planner',r['stage']) for r in publications)
    goal_revisions=sum('long_term' in (r.get('changed_components') or []) for r in publications)
    current={}
    for path in (d/'current_components').glob('*.json'):
        current[path.stem]={}
        for kind,key in read(path).items():
            envelope=read(d/'plan_components'/(key+'.json'))
            current[path.stem][kind]={'version':envelope['version'],'writer':envelope['writer'],
                'source_decision':envelope['source_session']['accepted_prefix_count']}
    reviews=[]
    for path in (d/'review_requests').glob('*.json'):
        value=read(path);reviews.append({'actor':value['actor'],'source_decision':value['source_session']['accepted_prefix_count'],
            'requested_at':value['requested_at'],'requesting_role':value.get('requesting_role')})
    files=[{'path':str(p.relative_to(root/f'game_{game:02d}')),'bytes':p.stat().st_size}
        for p in (root/f'game_{game:02d}').rglob('*') if p.is_file()]
    files.sort(key=lambda r:r['bytes'],reverse=True)
    records=[json.loads(s) for s in (root/f'game_{game:02d}'/'decisions.jsonl').read_text(encoding='utf8').splitlines() if s.strip()]
    approvals=Counter();plan_availability=Counter();main_availability=Counter();accepted_batches=Counter()
    for path in (root/f'game_{game:02d}'/'handoffs/sequences/approvals').glob('*.json'):
        value=read(path).get('approval',{});approvals['batches']+=1
        for k in ('approve','reject','add','overrides'):approvals[k]+=len(value.get(k,[]))
    observed_claims=set()
    for row in records:
        aux=row.get('auxiliary_payload',{});receipt=aux.get('runtime',{})
        if aux.get('batch'):
            approvals['executed_steps']+=1
            accepted_batches[aux['batch']['id']]+=1
            receipt=read(root/f'game_{game:02d}'/'handoffs/claims'/(aux['batch']['origin_claim']+'.json'))
        claim_key=receipt.get('claim_id',aux.get('batch',{}).get('origin_claim')) or row['decision_id']
        if claim_key in observed_claims:continue
        observed_claims.add(claim_key)
        if not receipt.get('attachment_id'):continue
        attachment=read(root/f'game_{game:02d}'/'handoffs/attachments'/(receipt['attachment_id']+'.json'))
        from edh_gauntlet.pilot_handoff import packet_path,packet_request
        context_id=receipt.get('pilot_context_id') or aux.get('pilot_context_id')
        current_request=packet_request(read(packet_path(root/f'game_{game:02d}',row['actor'],context_id))) if context_id else {}
        own_main=(current_request.get('kind') in {'land_play','main_action'} and
                  current_request.get('phase') in {'precombat_main','postcombat_main'})
        plan_availability['ordinary_claims']+=1
        main_availability['claims']+=own_main
        if not attachment.get('plan_id'):continue
        from edh_gauntlet.planner_stages import load_plan
        plan=load_plan(d,attachment['plan_id'])
        plan_availability['with_goal']+=bool(plan.get('long_term_plan'))
        plan_availability['with_short_prose']+=bool(plan.get('short_term_plan'))
        plan_availability['with_symbolic_sequence']+=bool(plan.get('action_sequence'))
        if own_main:
            for name,field in [('with_goal','long_term_plan'),('with_short_prose','short_term_plan'),('with_symbolic_sequence','action_sequence')]:
                main_availability[name]+=bool(plan.get(field))
        plan_availability['with_diplomacy_outcomes']+=bool(attachment.get('diplomacy_outcomes'))
        readiness=attachment.get('proposal_readiness')
        if readiness is not None:
            plan_availability['readiness_observed']+=1
            plan_availability['with_timely_steps']+=bool(readiness.get('timely_ids'))
            plan_availability['with_matching_current_choice']+=bool(readiness.get('matches_current_choice_ids'))
            plan_availability['with_only_expired_steps']+=bool(readiness.get('expired_ids')) and not (readiness.get('timely_ids') or readiness.get('future_ids'))
            plan_availability['with_exact_repair_alternatives']+=bool(readiness.get('current_choice_alternatives'))
            if own_main:
                main_availability['with_matching_current_choice']+=bool(readiness.get('matches_current_choice_ids'))
                main_availability['with_timely_steps']+=bool(readiness.get('timely_ids'))
    approvals['additional_steps_without_pilot_inference']=sum(max(0,n-1) for n in accepted_batches.values())
    approvals['multi_step_batches']=sum(n>1 for n in accepted_batches.values())
    batch_results=[]
    for key,count in accepted_batches.items():
        execution=read(root/f'game_{game:02d}'/'handoffs/sequences/executions'/(key+'.json'))
        program=read(root/f'game_{game:02d}'/'handoffs/sequences/programs'/(execution['program_id']+'.json'))
        batch_results.append({'batch_id':key,'executed':count,'approved_steps':len(program['steps']),
            'all_approved_steps_executed':count==len(program['steps']),
            'stop_reason':execution.get('continuation_stopped',execution['result']['reason'])})
    offers=read(d/'diplomatic_offers.json') if (d/'diplomatic_offers.json').exists() else {}
    reservations=[e for e in events if e['event']=='planner_reserved']
    refreshes=[e['snapshot_refresh'] for e in reservations if e.get('snapshot_refresh')]
    return {'game':game,'accepted':len(records),
        'scope':{'inference_and_timing_segments':[str(p) for p in segments],
                 'artifacts_and_approvals':'cumulative through accepted count; not restricted to timing segments'},
        'role_inference':grouped,'inference_by_input_round':per_round,
        'reservation_freshness':{'observed':len(reservations),
            'stale_at_admission':sum(e['source_accepted']!=e['accepted'] for e in reservations),
            'refreshed':len(refreshes),'replayed':sum(bool(e.get('replayed')) for e in refreshes),
            'refresh_seconds':stats([e['seconds'] for e in refreshes])},
        'planning_gate_wait_seconds':stats([e['seconds'] for e in events if e['event']=='planning_gate_ready']),
        'calls':dict(counts),'validation_errors':errors,
        'background_unpublished_completions':sum(e['event']=='background_unpublished' for e in events),
        'stage_counts':{role+':'+stage:n for (role,stage),n in stages.items()},'goal_content_revisions':goal_revisions,
        'publications':publications,'current_components':current,'strategic_requests':reviews,
        'pending_review_seats':len(state.get('strategic_reviews',{})),
        'jobs_by_role_status':dict(Counter(j.get('role','planner')+':'+j['status'] for j in state['jobs'].values())),
        'plan_availability':dict(plan_availability),'main_action_plan_availability':dict(main_availability),
        'batch_approvals':dict(approvals),'batch_results':batch_results,
        'diplomacy':{'posts':len(read(d/'diplomacy_posts.json')) if (d/'diplomacy_posts.json').exists() else 0,
            'offer_states':dict(Counter(v['state'] for v in offers.values()))},
        'files':{'count':len(files),'bytes':sum(r['bytes'] for r in files),'largest':files[:10]},
        'limits':['Input-token sums include cached tokens; this is not billable token usage.',
            'Counts include all observed request origins, including inspections, final responses and validation retries.',
            'Availability and approval do not establish optimal play. Assess strategic-review usefulness and actual diplomatic influence from private evidence after the segment.',
            'Round attribution follows the frozen real input; None means older telemetry lacked it. Do not claim controlled speedup from one seed.',
            'Current pointers are bounded; immutable evidence archives intentionally grow. Full seed/catalog context is retained by Sol.']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort',type=Path,required=True);parser.add_argument('--game',type=int,default=1)
    parser.add_argument('--segments',type=Path,nargs='+',required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();value=report(args.cohort.resolve(),args.game,args.segments)
    args.output.write_text(json.dumps(value,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:value[k] for k in ('accepted','stage_counts','plan_availability','batch_approvals','diplomacy')}))
