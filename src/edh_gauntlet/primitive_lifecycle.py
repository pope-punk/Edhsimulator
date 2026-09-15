"""Explicit fresh primitive-cohort lifecycle, with metadata-only operator output."""
import argparse
import json
from pathlib import Path
from .primitive_campaign import PrimitiveCampaign
from .rules_state import RulesViolation
from .runtime_store import locked,read,write


def stopped_prefix(campaign,expected):
    process=read(campaign.root/'host_runtime/process.json',{})
    if process and (process.get('active') or not process.get('contexts_unloaded')):
        raise RulesViolation('Stop and unload the owned transport before changing lifecycle state')
    if campaign.store.committed_head()!=expected:raise RulesViolation('Accepted prefix changed')
    if process and (process.get('binding')!=campaign.binding or
                    process.get('commit')!=expected or
                    process.get('generation')!=campaign.state()['transport_generation']):
        raise RulesViolation('Stopped transport does not match the bound campaign prefix')
    return process


def extend_horizon(campaign,*,expected,max_rounds):
    """An operator extension changes no game action or original game contract."""
    stopped_prefix(campaign,expected)
    with campaign.transaction() as state:
        if state['terminal'] or state['blocker']:raise RulesViolation('A terminal game cannot extend its horizon')
        if state['pending']:raise RulesViolation('Reconcile the pending input before extending the horizon')
        old=state.get('round_horizon',campaign.config['max_rounds'])
        receipt={'commit':expected,'from':old,'to':max_rounds}
        prior=state.get('horizon_extension')
        if prior and prior['commit']==expected and prior['to']==max_rounds:return prior
        if type(max_rounds) is not int or max_rounds<=old:
            raise RulesViolation('The new round horizon must increase')
        turn=campaign.kernel.state.turn_number;players=len(campaign.kernel.state.players)
        if turn<=old*players:raise RulesViolation('The round horizon has not been reached')
        if turn>max_rounds*players:raise RulesViolation('The new horizon must include the current turn')
        state['round_horizon']=max_rounds;state['horizon_extension']=receipt
        for actor in state['actors']:campaign.record(actor,'horizon_extension',receipt)
        return receipt


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort',type=Path,required=True)
    commands=parser.add_subparsers(dest='command',required=True)
    init=commands.add_parser('init')
    init.add_argument('--seed',type=int,required=True)
    init.add_argument('--starting-player',required=True)
    init.add_argument('--max-rounds',type=int,default=16)
    init.add_argument('--games',type=int,default=1)
    init.add_argument('--learning',choices=['disabled'],required=True,
                      help='Learning remains disabled for primitive campaigns.')
    advance_command=commands.add_parser('advance');advance_command.add_argument('--game',type=int,required=True)
    commands.add_parser('status')
    commands.add_parser('verify-journal')
    pause=commands.add_parser('pause');pause.add_argument('--reason',required=True)
    resume=commands.add_parser('resume-pause')
    resume.add_argument('--expected-sequence',type=int,required=True)
    resume.add_argument('--expected-sha256',required=True)
    help_status=commands.add_parser('help-status')
    help_answer=commands.add_parser('answer-help')
    help_answer.add_argument('--request-id',required=True)
    help_answer.add_argument('--response',type=Path,required=True)
    help_answer.add_argument('--expected-sequence',type=int,required=True)
    help_answer.add_argument('--expected-sha256',required=True)
    extend=commands.add_parser('extend-horizon')
    extend.add_argument('--expected-sequence',type=int,required=True)
    extend.add_argument('--expected-sha256',required=True)
    extend.add_argument('--max-rounds',type=int,required=True)
    fence=commands.add_parser('fence-crash')
    fence.add_argument('--expected-sequence',type=int,required=True)
    fence.add_argument('--expected-sha256',required=True)
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
                                               max_rounds=args.max_rounds,games=args.games)
        else:campaign=PrimitiveCampaign.open(root,recover=False)
        try:
            if args.command=='advance':
                if args.game==campaign.binding['game_number']:
                    intent=read(root/'ADVANCE.json',{})
                    if intent:
                        if (intent.get('binding')!=campaign.binding or intent.get('to_game')!=args.game or
                            campaign.store.generation or intent.get('config')!=campaign.config):
                            raise RulesViolation('Interrupted advancement does not match the fresh game')
                        write(root/f"game_{intent['from_game']:02d}"/'advancement.json',intent)
                        (root/'ADVANCE.json').unlink()
                else:
                    from .primitive_multigame import advance
                    previous=campaign
                    try:campaign=advance(previous,args.game)
                    finally:previous.close()
            if args.command=='verify-journal':
                from .primitive_journal import head
                # Open already reconstructed and checked the host projections.
                print(json.dumps({'verified':True,'host_commit':head(campaign.store.connection),
                                  'rules_commit':campaign.store.committed_head()},indent=2))
                return
            if args.command=='fence-crash':
                from .primitive_recovery import fence_crash
                fence_crash(campaign,{'sequence':args.expected_sequence,'sha256':args.expected_sha256})
            if args.command=='help-status':
                print(json.dumps({'request':campaign.state().get('help_request'),'next_action':campaign.next_action()},indent=2))
                return
            if args.command=='answer-help':
                from .primitive_help import answer
                answer(campaign,expected={'sequence':args.expected_sequence,'sha256':args.expected_sha256},
                       request_id=args.request_id,response=read(args.response,{}))
            if args.command=='resume-pause':
                expected={'sequence':args.expected_sequence,'sha256':args.expected_sha256}
                process=stopped_prefix(campaign,expected)
                if campaign.state()['terminal']:raise RulesViolation('A terminal game cannot resume')
                if campaign.state().get('help_request'):raise RulesViolation('Answer the outstanding pilot help request before resuming')
                with campaign.transaction() as state:
                    for actor in state['actors']:campaign.record(actor,'operator_resume',{'commit':expected})
                    state['paused']={'reason':'host_stopped','commit':expected} if process else None
                (root/'HOST_PAUSED.json').unlink(missing_ok=True)
            if args.command=='extend-horizon':
                extend_horizon(campaign,expected={'sequence':args.expected_sequence,'sha256':args.expected_sha256},
                               max_rounds=args.max_rounds)
            marker=read(root/'HOST_PAUSED.json',{})
            if marker:campaign.pause(marker['reason'])
            action=campaign.publish_next()
            print(json.dumps({'cohort':str(root),'next_action':action},indent=2))
        finally:campaign.close()


if __name__=='__main__':main()
