"""Analyze bounded host metadata, never gameplay packets or model prose."""
import argparse
from collections import defaultdict, deque
import json
from pathlib import Path
import statistics


def analyze(events):
    current={};finished=defaultdict(deque);packets={};models={};seen=set();requests=[];held=set()
    for e in events:
        tid=e.get('thread');kind=e['event'];now=e['epoch']
        if kind=='packet':packets[tid]=e
        elif kind=='turn_request':
            models[tid]=e.get('model')
            current[tid]={'thread':tid,'actor':e.get('actor'),'role':e.get('role'),'model':models[tid],
                'origin':'segment_first_turn' if tid not in seen else 'new_turn','start':now,
                'decision_id':packets.get(tid,{}).get('decision_id'),'source_round':packets.get(tid,{}).get('round')}
            seen.add(tid)
        elif kind=='turn_started' and current.get(tid):current[tid]['turn']=e.get('turn')
        elif kind=='first_output_event' and current.get(tid):
            if current[tid]['start'] is not None:current[tid].setdefault('first_output_seconds',round(now-current[tid]['start'],3))
        elif kind=='tool_arrived' and current.get(tid):
            row=current.pop(tid);row['tool']=e.get('tool');row['seconds']=round(now-row['start'],3) if row['start'] is not None else None
            row['request_id']=e.get('request');finished[tid].append(row)
            held.add(tid)
        elif (kind=='model_item' and e.get('kind')=='reasoning' and e.get('edge')=='started'
              and tid in held and not current.get(tid)):
            # Exec can yield while an edh_* call is still pending and make the
            # model call wait. Its request start is not visible in host timing.
            current[tid]={'thread':tid,'actor':e.get('actor'),'role':e.get('role'),'model':models.get(tid),
                'origin':'tool_wait_continuation','start':None,'first_observed':now,'source_round':packets.get(tid,{}).get('round')}
        elif kind=='tool_returned' and tid:
            held.discard(tid)
            if current.get(tid,{}).get('origin')=='tool_wait_continuation':finished[tid].append(current.pop(tid))
            state=e.get('state');origin={'decision':'warm_decision','inspections':'inspection',
                'parked':'park_final','stage_published':'planner_stage','published':'planner_final',
                'rejected':'validation_retry'}.get(state,'tool_continuation')
            current[tid]={'thread':tid,'actor':e.get('actor'),'role':e.get('role'),'model':models.get(tid),
                'origin':origin,'start':now,'decision_id':packets.get(tid,{}).get('decision_id') if state=='decision' else None,
                'source_round':packets.get(tid,{}).get('round'),
                'preceding_tool_wait_seconds':round(e.get('seconds',0),3),
                'returned_chars':e.get('response_chars')}
        elif kind=='usage' and not e.get('repeated_usage'):
            row=finished[tid].popleft() if finished[tid] else current.pop(tid,None)
            if row:
                row.setdefault('seconds',round(now-row['start'],3) if row['start'] is not None else None)
                row['usage']=e.get('usage',{});row['turn']=e.get('turn');requests.append(row)
        elif kind=='turn_completed':current.pop(tid,None)
    grouped=defaultdict(list)
    for row in requests:grouped[(row.get('role'),row['origin'])].append(row)
    groups=[]
    for (role,origin),rows in grouped.items():
        timed=[r['seconds'] for r in rows if r['seconds'] is not None]
        input_tokens=sum(r['usage'].get('inputTokens',0) for r in rows)
        cached=sum(r['usage'].get('cachedInputTokens',0) for r in rows)
        groups.append({'role':role,'origin':origin,'requests':len(rows),
            'zero_cache':sum(r['usage'].get('cachedInputTokens')==0 for r in rows),
            'cache_read_fraction':round(cached/input_tokens,4) if input_tokens else None,
            'timed_requests':len(timed),'median_seconds':round(statistics.median(timed),3) if timed else None,'max_seconds':max(timed) if timed else None})
    return {'requests':requests,'groups':groups,'incomplete_requests':[row for rows in finished.values() for row in rows],
        'unmatched_tool_requests':sum(map(len,finished.values())),
        'caveat':'First requests after resume/checkpoint are separated. Tool waits are excluded from request latency. Missing first-output events are unknown.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('timing',type=Path)
    p.add_argument('--report',type=Path,required=True);args=p.parse_args()
    data=json.loads(args.timing.read_text(encoding='utf8'));result=analyze(data['retained_events'])
    result['source_events']=data['total_events'];result['retention_truncated']=data['total_events']>len(data['retained_events'])
    args.report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='requests'}))


if __name__=='__main__':main()
