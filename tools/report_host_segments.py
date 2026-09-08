"""Combine complete local telemetry segments without counting recovery downtime."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
from analyze_cache_probe import analyze
from report_host_game import read, stats


def summarize(paths):
    segments=[];requests=[];decisions=[];handoffs=[];planners=[];memory=[];failures=[]
    communication=defaultdict(Counter);inspection=defaultdict(Counter);dispatch=Counter()
    for path in paths:
        collection=read(path/'collection.json');launch=read(path/'launch.json')
        events=[json.loads(line) for line in (path/'timing.jsonl').read_text().splitlines()]
        if collection['gaps'] or collection['events']!=len(events):
            raise ValueError(f'Incomplete telemetry segment: {path}')
        start=datetime.fromisoformat(launch['launched_utc'].replace('Z','+00:00')).timestamp()
        segments.append({'path':str(path),'start':start,'end':max(e['epoch'] for e in events),
                         'accepted_start':launch.get('resumed_at_decision',0),
                         'accepted_end':collection['accepted'],'next':collection['next'],'events':len(events)})
        result=analyze(events)
        requests.extend({**r,'segment':str(path)} for r in result['requests'])
        packets={};starts={};last=None
        for e in events:
            tid=e.get('thread');kind=e['event']
            if kind=='packet' and e.get('decision_id'):
                packets[tid]=e
                if last and last.get('actor')!=e.get('actor'):handoffs.append(e['epoch']-last['epoch'])
                last=None
            elif kind=='tool_arrived' and e.get('tool')=='edh_act':
                packet=packets.pop(tid,None)
                if packet:decisions.append({'decision_id':packet['decision_id'],'actor':packet.get('actor'),
                                           'seconds':e['epoch']-packet['epoch']})
                last=e
            elif kind=='turn_request' and e.get('role') in {'planner','short_term_planner','long_term_planner'}:starts[tid]=e['epoch']
            elif kind=='turn_completed' and tid in starts:
                planners.append({'actor':e.get('actor'),'status':e.get('status'),
                                 'seconds':e['epoch']-starts.pop(tid)})
            if kind=='tool_returned' and e.get('success') is False:
                failures.append({k:e.get(k) for k in ('actor','role','state','publication_stage',
                    'validation_sections','publication_lengths','error_sha256')})
        memory.extend(json.loads(line) for line in (path/'memory.jsonl').read_text().splitlines())
        metrics=read(path/'metrics.json')
        for role,values in metrics.get('communication_chars',{}).items():communication[role].update(values)
        for role,values in metrics.get('inspection_chars',{}).items():inspection[role].update(values)
        values=metrics.get('dispatch_seconds',{})
        dispatch['count']+=values.get('count',0);dispatch['total']+=values.get('total',0)
        dispatch['max']=max(dispatch['max'],values.get('max',0))
    segments.sort(key=lambda r:r['start'])
    for left,right in zip(segments,segments[1:]):
        if left['end']>right['start'] or left['accepted_end']!=right['accepted_start']:
            raise ValueError('Telemetry segments overlap or omit an accepted prefix.')
    groups=defaultdict(list)
    for r in requests:groups[(r.get('role'),r['origin'])].append(r)
    grouped=[]
    for (role,origin),rows in groups.items():
        inp=sum(r['usage'].get('inputTokens',0) for r in rows)
        cache=sum(r['usage'].get('cachedInputTokens',0) for r in rows)
        grouped.append({'role':role,'origin':origin,'requests':len(rows),
            'seconds':stats([r['seconds'] for r in rows if r['seconds'] is not None]),
            'first_output_seconds':stats([r['first_output_seconds'] for r in rows if 'first_output_seconds' in r]),
            'input_tokens':stats([r['usage']['inputTokens'] for r in rows if 'inputTokens' in r['usage']]),
            'zero_cache':sum(r['usage'].get('cachedInputTokens')==0 for r in rows),
            'cache_read_fraction':cache/inp if inp else None})
    duration=sum(s['end']-s['start'] for s in segments)
    return {'segments':segments,'active_runtime_seconds':duration,
        'accepted':segments[-1]['accepted_end'],'decision_seconds':stats([d['seconds'] for d in decisions]),
        'handoff_seconds':stats(handoffs),'planner_turn_seconds':stats([p['seconds'] for p in planners if p['status']=='completed']),
        'communication_chars':dict(communication),'inspection_chars':dict(inspection),
        'dispatch_seconds':dict(dispatch),'groups':grouped,'failures':failures,
        'memory_summed_working_set_bytes':stats([m['summed_working_set_bytes'] for m in memory if m.get('summed_working_set_bytes') is not None]),
        'memory_coverage':{'samples':len(memory),'unavailable':sum(m.get('summed_working_set_bytes') is None for m in memory)},
        'decision_samples':decisions,'planner_samples':planners,'request_samples':requests,
        'caveats':['Recovery downtime is excluded. Segments must cover contiguous accepted prefixes.',
                   'Packet-to-submission and cross-seat gaps include engine work and any required startup planning.',
                   'Planner turns may contain several inference requests and publication stages.',
                   'First-output observations are not internal backend timestamps. Working-set sums can double-count shared pages.']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('segments',nargs='+',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();result=summarize(args.segments)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:result[k] for k in ('accepted','active_runtime_seconds','decision_seconds','planner_turn_seconds')}))
