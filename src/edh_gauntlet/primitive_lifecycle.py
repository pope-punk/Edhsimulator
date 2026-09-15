"""Explicit fresh primitive-cohort lifecycle, with metadata-only operator output."""
import argparse
import json
from pathlib import Path
from .primitive_campaign import PrimitiveCampaign
from .rules_state import RulesViolation
from .runtime_store import locked,read,write


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort',type=Path,required=True)
    commands=parser.add_subparsers(dest='command',required=True)
    init=commands.add_parser('init')
    init.add_argument('--seed',type=int,required=True)
    init.add_argument('--starting-player',required=True)
    init.add_argument('--max-rounds',type=int,default=16)
    init.add_argument('--learning',choices=['disabled'],required=True,
                      help='This initial primitive host supports explicitly disabled learning only.')
    commands.add_parser('status')
    pause=commands.add_parser('pause');pause.add_argument('--reason',required=True)
    resume=commands.add_parser('resume-pause')
    resume.add_argument('--expected-sequence',type=int,required=True)
    resume.add_argument('--expected-sha256',required=True)
    args=parser.parse_args(argv);root=args.cohort.resolve()
    if args.command=='status':
        if read(root/'cohort.json',{}).get('rules_engine')!='primitives-v1':raise RulesViolation('Not a primitive cohort')
        print(json.dumps({'cohort':str(root),'next_action':read(root/'NEXT_ACTION.json',{}).get('next_action'),
                          'host':read(root/'host_runtime/status.json',{}),
                          'pause_requested':bool(read(root/'HOST_PAUSED.json',{}))},indent=2))
        return
    if args.command=='pause':
        # An operator stop is a marker the current host observes before admission;
        # it does not race a second kernel writer against an accepted command.
        if not (root/'cohort.json').exists():raise RulesViolation('Unknown cohort')
        if read(root/'cohort.json').get('rules_engine')!='primitives-v1':
            raise RulesViolation('Use the legacy lifecycle for this cohort')
        if not args.reason.strip() or len(args.reason)>300:raise RulesViolation('Supply a bounded pause reason')
        write(root/'HOST_PAUSED.json',{'reason':args.reason,'operator':True})
        print(json.dumps({'pause_requested':True,'reason':args.reason}))
        return
    with locked(root,'host-driver',timeout=0):
        if args.command=='init':
            campaign=PrimitiveCampaign.create(root,seed=args.seed,starting_player=args.starting_player,
                                               max_rounds=args.max_rounds)
        else:campaign=PrimitiveCampaign.open(root,recover=False)
        try:
            if args.command=='resume-pause':
                process=read(root/'host_runtime/process.json',{})
                expected={'sequence':args.expected_sequence,'sha256':args.expected_sha256}
                if process and (process.get('active') or not process.get('contexts_unloaded')):
                    raise RulesViolation('Stop and unload the owned transport before resuming a pause')
                if campaign.store.committed_head()!=expected:raise RulesViolation('Accepted prefix changed')
                if campaign.state()['terminal']:raise RulesViolation('A terminal game cannot resume')
                with campaign.transaction() as state:
                    for actor in state['actors']:campaign.record(actor,'operator_resume',{'commit':expected})
                    state['paused']={'reason':'host_stopped','commit':expected} if process else None
                (root/'HOST_PAUSED.json').unlink(missing_ok=True)
            marker=read(root/'HOST_PAUSED.json',{})
            if marker:campaign.pause(marker['reason'])
            action=campaign.publish_next()
            print(json.dumps({'cohort':str(root),'next_action':action},indent=2))
        finally:campaign.close()


if __name__=='__main__':main()
