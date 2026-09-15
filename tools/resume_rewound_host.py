"""Resume an explicitly rewound, stopped Linux host using fresh seat contexts.

The archived pre-rewind cohort supplies transport identities and the original
accepted tape. No archived pilot content is delivered to the new contexts.
"""
import argparse,hashlib,json
from pathlib import Path
from edh_gauntlet import host_runtime as host,planner_runtime,pilot_dispatch,quarantine
from edh_gauntlet.dashboard import linux_process_identity
from edh_gauntlet.runtime_store import locked,read,write


def validate(root,archive,game,accepted):
    prior=read(archive/'host_runtime/launch.json')
    if not prior.get('linux_process_identity') or linux_process_identity(prior['pid']) is not None:
        raise SystemExit('The archived owned host must be stopped.')
    action=read(root/'NEXT_ACTION.json')['next_action']
    if action.get('kind')!='dispatch_pilot' or action.get('game')!=game:
        raise SystemExit('The rewound game must own a gameplay frontier.')
    old=host.campaign.read_jsonl(archive/f'game_{game:02d}'/'decisions.jsonl')
    rows=host.campaign.read_jsonl(root/f'game_{game:02d}'/'decisions.jsonl')
    rejections=host.campaign.read_jsonl(root/f'game_{game:02d}'/'rejections.jsonl')
    if not 0<accepted<len(old) or len(rows)!=accepted or rows!=old[:accepted] or not rejections:
        raise SystemExit('The exact retained pre-rewind prefix is required.')
    rejection=rejections[-1]
    digest=hashlib.sha256(json.dumps(old[accepted:],sort_keys=True).encode()).hexdigest()
    if (rejection.get('from_decision')!=old[accepted]['decision_id'] or
        rejection.get('discarded_count')!=len(old)-accepted or rejection.get('discarded_sha256')!=digest):
        raise SystemExit('The rejection journal does not match the archived branch.')
    board=planner_runtime.workboard(root,game)
    if (pilot_dispatch.registry(root,game) or (root/'host_runtime/sessions.json').exists() or
        board.get('planners') or board.get('active') or board.get('active_by_role') or
        action.get('dispatch',{}).get('kind')!='spawn' or action['dispatch'].get('mode')!='fresh'):
        raise SystemExit('Rewind must invalidate every old seat identity and route.')
    if read(root/'HOST_PAUSED.json',{}).get('reason') not in {'user_stop','rules_audit'} or (root/'PROBE_PAUSED.json').exists():
        raise SystemExit('Expected the authorized rewind pause and no independent pause.')
    if quarantine.pending_repairs(root,game):raise SystemExit('Rules repairs remain pending.')
    return rows,prior


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort',type=Path,required=True)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--game',type=int,required=True)
    parser.add_argument('--accepted',type=int,required=True)
    parser.add_argument('--max-decisions',type=int,required=True)
    args=parser.parse_args();root=args.cohort.resolve();archive=args.archive.resolve()
    if args.max_decisions<=args.accepted:parser.error('Decision cap must exceed retained prefix.')
    with locked(root,'host-driver',timeout=0):
        rows,prior=validate(root,archive,args.game,args.accepted)
        server=host.AppServer();started=False
        try:
            sessions=read(archive/'host_runtime/sessions.json')
            for session in sessions:
                metadata=server.call('thread/read',{'threadId':session['thread'],'includeTurns':False})['thread']
                if metadata.get('status',{}).get('type')!='notLoaded' or Path(metadata['cwd']).resolve()!=root/'host_runtime':
                    raise SystemExit('An archived transport is still loaded or belongs to another host.')
            validate(root,archive,args.game,args.accepted)
            write(root/'host_runtime'/f'rewind_recovery_{args.game}_{args.accepted}.json',{
                'game':args.game,'accepted':args.accepted,'previous_launch':prior,
                'archive':str(archive),'unloaded_old_contexts':len(sessions),
                'prefix_sha256':host.campaign._sha256_file(root/f'game_{args.game:02d}'/'decisions.jsonl'),
                'context_policy':'fresh_after_rewind'})
            (root/'HOST_PAUSED.json').unlink();started=True
            runner=host.Runner(root,server,fresh_contexts=True,max_decisions=args.max_decisions,timing_events=4096)
            runner.run()
        finally:
            if server.process.poll() is None:server.close()
            if started and not (root/'HOST_PAUSED.json').exists() and read(root/'NEXT_ACTION.json')['next_action']['kind']=='dispatch_pilot':
                write(root/'HOST_PAUSED.json',{'reason':'host_stopped','accepted':len(host.campaign.read_jsonl(root/f'game_{args.game:02d}'/'decisions.jsonl'))})


if __name__=='__main__':main()
