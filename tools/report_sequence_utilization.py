"""Read-only accepted-prefix accounting; counts execution separately from savings."""
import argparse,json
from collections import defaultdict,Counter
from pathlib import Path
from edh_gauntlet import sequence_runtime
from edh_gauntlet.runtime_store import read,get,write


def report(root,game,rows=None):
    directory=sequence_runtime.batch_directory(root,game)
    if rows is None:rows=[json.loads(line) for line in (Path(root)/f'game_{game:02d}'/'decisions.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
    seats={actor:{'decision_points':0,'approval_batches':0,'executed_steps':0,'additional_decisions_without_submission':0,
                  'approved_steps':0,'rejected_steps':0,'pilot_added_steps':0,'modified_steps':0,
                  'automatic_priority_passes':0,'ignored_rationale_overrides':0} for actor in ('Omo','Minsc & Boo','Reaminatour','Elenda')}
    groups=defaultdict(list);stops=Counter()
    for row in rows:
        seats[row['actor']]['decision_points']+=1
        batch=row.get('auxiliary_payload',{}).get('batch')
        if batch:groups[batch['id']].append(row)
    for key,items in groups.items():
        actor=items[0]['actor'];stats=seats[actor];approval=get(directory/'approvals',key)['approval']
        automatic=sum(bool(r['auxiliary_payload']['batch'].get('automatic_priority')) for r in items)
        stats['approval_batches']+=1;stats['executed_steps']+=len(items)-automatic
        stats['automatic_priority_passes']+=automatic
        stats['additional_decisions_without_submission']+=max(0,len(items)-1)
        stats['approved_steps']+=len(approval['approve']);stats['rejected_steps']+=len(approval['reject'])
        stats['pilot_added_steps']+=len(approval.get('add',[]));stats['modified_steps']+=len(approval.get('overrides',{}))
        result=read(directory/'executions'/(key+'.json'))
        ignored=len(result.get('ignored_rationale_overrides',[]))
        stats['modified_steps']-=ignored;stats['ignored_rationale_overrides']+=ignored
        stops[result.get('continuation_stopped',result.get('result',{}).get('reason','unknown'))]+=1
    totals={key:sum(row[key] for row in seats.values()) for key in next(iter(seats.values()))}
    totals['shortcut_percent']=round(100*totals['additional_decisions_without_submission']/len(rows),2) if rows else 0
    return {'game':game,'through_decision':rows[-1]['decision_id'] if rows else None,'totals':totals,'seats':seats,
            'batch_stop_reasons':dict(stops),'definition':'Each accepted approval needs one pilot submission. Only subsequent accepted steps in that batch are counted as skipped separate submissions. Single-step batches save none. Excludes snooze-suppressed windows, failed attempts, and speculative wall-time estimates.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--cohort',type=Path,required=True)
    parser.add_argument('--game',type=int,required=True);parser.add_argument('--output',type=Path)
    args=parser.parse_args();value=report(args.cohort,args.game)
    if args.output:write(args.output,value)
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
