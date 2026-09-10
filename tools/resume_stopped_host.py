"""Explicit fenced recovery after an idle, undispatched checkpoint-capacity stop.

Requires a stopped process (checked by the hidden launcher), exact prefix, registered
unloaded seat/role contexts, no ambiguous checkpoint RPC, and no dispatched reservation.
Never substitutes gameplay answers or clears a rules/lifecycle pause.
An explicit --user-resume permits the user_stop marker after renewed authorization.
"""
import argparse
import hashlib
import json
from pathlib import Path
from edh_gauntlet import host_runtime as host, planner_runtime, handoff_runtime, pilot_handoff
from edh_gauntlet.runtime_store import read, write, locked
from edh_gauntlet.agent_architecture import roles,is_background,registration_key


def validate_pause(pause,accepted,user_resume,decision_limit_resume=False):
    if user_resume and decision_limit_resume:raise SystemExit('Choose one resume cause.')
    if decision_limit_resume:
        if pause!={'reason':'decision_limit','accepted':accepted}:raise SystemExit('Decision-limit resume requires the exact capped prefix.')
    elif user_resume:
        if pause.get('reason')!='user_stop':raise SystemExit('Explicit user resume requires a user_stop marker.')
    elif pause!={'reason':'host_stopped','accepted':accepted}:
        raise SystemExit('The exact stopped accepted prefix is required.')


def validate_unanswered_failure(failure,action,accepted):
    if (failure.get('code')!='unanswered_decision' or failure.get('accepted')!=accepted or
            failure.get('role')!='decider' or failure.get('actor')!=action.get('actor') or
            failure.get('decision_id')!=action.get('decision_id')):
        raise SystemExit('Expected the exact stopped unanswered decision and actor.')


def capacity_continuation(path,game,accepted,sessions,action,failure,previous_launch):
    """Reconcile a completed act followed by overload at a new unanswered input.

    Explicit stopped-host continuation only: never retry the failed turn or tools.
    The usual prefix, unloaded-context and route-fencing checks still apply.
    """
    collection=read(path/'collection.json');launch=read(path/'launch.json')
    if (launch!=previous_launch or launch.get('game')!=game or
            collection.get('accepted')!=accepted or collection.get('gaps')!=[] or
            collection.get('next')!='dispatch_pilot' or collection.get('host_pid')!=launch.get('pid')):
        raise SystemExit('Capacity continuation requires complete telemetry for the exact stopped host.')
    seat=next((s for s in sessions if s['actor']==action.get('actor') and s['role']=='decider'),{})
    if (failure.get('code')!='server_overloaded' or failure.get('will_retry') is not False or
            failure.get('game')!=game or failure.get('accepted')!=accepted or
            failure.get('thread_id')!=seat.get('thread') or failure.get('tool_calls')!=1):
        raise SystemExit('Expected a terminal one-tool capacity failure on the current decider.')
    events=[json.loads(line) for line in (path/'timing.jsonl').read_text(encoding='utf8').splitlines()]
    if len(events)!=collection.get('events'):
        raise SystemExit('Capacity telemetry event count is incomplete.')
    events=[e for e in events if e.get('thread')==seat['thread']]
    starts=[i for i,e in enumerate(events) if e['event']=='turn_request']
    if not starts:raise SystemExit('Capacity telemetry lacks the failed turn start.')
    segment=events[starts[-1]:]
    calls=[e for e in segment if e['event']=='tool_arrived']
    if (len(calls)!=1 or calls[0].get('tool')!='edh_act' or
            calls[0].get('turn')!=failure.get('turn_id')):
        raise SystemExit('Failed turn has ambiguous or unreconciled tool calls.')
    returns=[e for e in segment if e['event']=='tool_returned']
    packets=[e for e in segment if e['event']=='packet']
    complete=[e for e in segment if e['event']=='turn_completed']
    if (len(returns)!=1 or returns[0].get('request')!=calls[0].get('request') or
            returns[0].get('success') is not True or returns[0].get('state')!='decision' or
            len(packets)!=1 or packets[0].get('decision_id')!=action.get('decision_id') or
            packets[0].get('actor')!=action.get('actor') or not packets[0].get('warm') or
            len(complete)!=1 or complete[0].get('status')!='failed' or
            complete[0].get('turn')!=failure.get('turn_id') or
            not calls[0]['epoch']<=packets[0]['epoch']<=returns[0]['epoch']<=complete[0]['epoch']):
        raise SystemExit('Capacity continuation requires a returned next decision and a terminal failed turn.')
    return {'thread':seat['thread'],'failed_turn':failure['turn_id'],
            'completed_tool_request':calls[0]['request'],'unanswered_decision':action['decision_id']}

def registered_sessions(sessions,planners,*,opening_planner=False):
    """A capped host may have canceled its active planner before shutdown."""
    kept=[row for row in sessions if row['role']=='decider' or
          (planners.get(registration_key(row['actor'],row['role'])) or {}).get('agent')==row.get('agent','/app-server/'+row['thread'])]
    keys={(row['actor'],row['role']) for row in kept}
    deciders={(actor,'decider') for actor in host.campaign.PILOT_GAMEPLAN_FILES}
    if (not opening_planner and not deciders<=keys) or len(keys)!=len(kept):raise SystemExit('Registered resume seats are incomplete or duplicated.')
    if opening_planner and any(not is_background(row['role']) for row in sessions):raise SystemExit('Opening planner recovery cannot omit initialized deciders.')
    return kept


def baseline_usage_recovery(path,game,accepted,sessions,contexts,failure,*,bounded_memory=False):
    """Restore numeric first/last samples from a complete, stopped collector segment."""
    expected=hashlib.sha256(b'Fresh checkpoint baseline exceeds context budget; stop instead of repeatedly replacing context.').hexdigest()
    if failure.get('message_sha256')!=expected or failure.get('accepted')!=accepted or failure.get('game')!=game:
        raise SystemExit('Baseline recovery requires the exact diagnosed guard failure.')
    collection=read(path/'collection.json');launch=read(path/'launch.json')
    if collection.get('accepted')!=accepted or collection.get('gaps')!=[] or launch.get('game')!=game:
        raise SystemExit('Baseline recovery requires complete telemetry for this stopped prefix.')
    usage={};started=set()
    for line in (path/'timing.jsonl').read_text(encoding='utf8').splitlines():
        event=json.loads(line);thread=event.get('thread')
        if event['event']=='turn_request':started.add(thread)
        if event['event']!='usage' or not event.get('usage',{}).get('inputTokens'):continue
        if thread not in started:raise SystemExit('Telemetry omits a request start; baseline is ambiguous.')
        value=usage.setdefault(thread,{'first':dict(event['usage'])})
        value['last']=dict(event['usage'])
    for row in sessions:
        value=read(contexts/f"{pilot_handoff.seat_slug(row['actor'])}_{row['role']}.json")
        if value.get('verify_baseline'):
            if row['thread'] not in usage:raise SystemExit('Missing first input usage for an unverified context.')
            if usage[row['thread']]['first']['inputTokens']>=64000 and not bounded_memory:
                raise SystemExit('Measured fresh baseline really exceeds the budget; recovery cannot waive it.')
    return {row['thread']:usage[row['thread']] for row in sessions if row['thread'] in usage}


def combo_sessions(root,game,accepted,telemetry):
    """Recover only a completed combo boundary, including the old manifest-loss bug."""
    directory=root/'host_runtime';collection=read(telemetry/'collection.json');launch=read(telemetry/'launch.json')
    stopped=read(directory/f'stopped_{game}_{accepted}.json',{})
    if (collection.get('next')!='adjudicate_combo' or collection.get('accepted')!=accepted or
            collection.get('gaps')!=[] or launch.get('game')!=game or
            stopped.get('previous_launch')!=launch):
        raise SystemExit('Combo recovery requires the exact stopped host and complete boundary telemetry.')
    journal=host.campaign.read_jsonl(root/f'game_{game:02d}'/'combo_adjudications.jsonl')
    if not journal or journal[-1].get('accepted_decision_count')!=accepted:
        raise SystemExit('No adjudication was committed at this exact accepted prefix.')
    records=host.pilot_dispatch.registry(root,game)
    planners=planner_runtime.workboard(root,game).get('planners',{})
    rows=host.campaign.read_jsonl(root/f'game_{game:02d}'/'decisions.jsonl')
    restored=[]
    for actor in host.campaign.PILOT_GAMEPLAN_FILES:
        for role in roles(root,game):
            registry=records if role=='decider' else planners
            registry_key=actor if role=='decider' else registration_key(actor,role)
            if role!='decider' and registry_key not in registry:continue
            value=read(directory/'context'/f'{pilot_handoff.seat_slug(actor)}_{role}.json',{})
            if (value.get('actor')!=actor or value.get('role')!=role or
                    value.get('transport_version')!=2 or value.get('checkpoint_pending') or
                    not value.get('thread') or value.get('agent')!=(registry.get(registry_key) or {}).get('agent') or
                    not pilot_handoff.can_resume_session(value.get('seat_session'),root,game,actor,rows)):
                raise SystemExit('Combo checkpoint does not match its registered seat and accepted branch.')
            restored.append({key:value[key] for key in ('actor','role','thread','agent')})
    saved=read(directory/'sessions.json',None)
    if saved is not None and registered_sessions(saved,planners)!=restored:
        # Session order is immaterial; identities are not.
        if {tuple(sorted(row.items())) for row in registered_sessions(saved,planners)}!={tuple(sorted(row.items())) for row in restored}:
            raise SystemExit('Saved and reconstructed combo sessions disagree.')
    return restored


def diagnostic_pause_recovery(path,game,accepted,failure,previous_launch):
    collection=read(path/'collection.json');launch=read(path/'launch.json')
    events=[json.loads(line) for line in (path/'timing.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
    if (collection.get('gaps')!=[] or not events or len(events)!=collection.get('events') or collection.get('accepted')!=accepted or
            collection.get('next')!='dispatch_pilot' or launch.get('game')!=game or
            collection.get('host_pid')!=launch.get('pid') or
            not previous_launch or previous_launch.get('pid')!=launch.get('pid') or
            previous_launch.get('process_started_utc')!=launch.get('process_started_utc')):
        raise SystemExit('Diagnostic resume requires complete telemetry for the exact stopped process and prefix.')
    if (failure.get('game')!=game or failure.get('accepted')!=accepted or
            failure.get('code')!='local_host_stop' or failure.get('exception_type')!='SystemExit' or
            failure.get('message_sha256')!=hashlib.sha256(b'Run is paused.').hexdigest()):
        raise SystemExit('Diagnostic resume requires the exact cooperative pause, not another failure.')
    return {'host_pid':launch['pid'],'accepted':accepted,'telemetry':str(path)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort',type=Path,required=True)
    parser.add_argument('--game',type=int,required=True)
    parser.add_argument('--accepted',type=int,required=True)
    parser.add_argument('--max-decisions',type=int,default=10000)
    parser.add_argument('--timing-events',type=int,default=512)
    parser.add_argument('--baseline-telemetry',type=Path,help='Explicit recovery of the diagnosed first-versus-last baseline guard using a complete local collector segment.')
    parser.add_argument('--bounded-memory-recovery',action='store_true',help='With baseline telemetry, checkpoint retained oversized planner contexts using the bounded rules cache before inference; never waive the budget.')
    parser.add_argument('--combo-telemetry',type=Path,help='Explicit continuation after a committed combo adjudication at the same prefix.')
    parser.add_argument('--capacity-telemetry',type=Path,help='Explicit continuation after a completed act and terminal overload at the next unanswered input.')
    parser.add_argument('--seat-role-lanes',action='store_true',help='Enable 16 independent seat/role lanes at a verified diagnostic stop.')
    parser.add_argument('--concurrent-background',action='store_true',help='Explicitly enable independent role lanes at this verified diagnostic stop.')
    parser.add_argument('--reservation-telemetry',type=Path,help='Fence a diagnosed misrouted background input with no accepted output and discard its context.')
    parser.add_argument('--diagnostic-pause-telemetry',type=Path,help='Explicit continuation after a cooperative investigation pause, verified against complete local telemetry.')
    parser.add_argument('--unanswered-decision-recovery',action='store_true',help='Explicit recovery after diagnosed tool-result loss at an unanswered decision.')
    parser.add_argument('--user-resume',action='store_true',help='Explicitly authorized continuation after user_stop')
    parser.add_argument('--decision-limit-resume',action='store_true',help='Explicitly authorized continuation after an exact decision-limit pause')
    parser.add_argument('--claim-completion-recovery',action='store_true',help='Explicit recovery after the diagnosed unanswered warm-decision invocation conflict.')
    parser.add_argument('--restore-unused-transports',action='store_true',help='Explicitly reconcile journaled replacement contexts that never received input and were not persisted.')
    parser.add_argument('--planner-validation-recovery',action='store_true',help='Resume after a diagnosed planner contract error, retaining published plans and restarting its cancelled pending work.')
    args=parser.parse_args();root=args.cohort.resolve();directory=root/'host_runtime'
    if args.bounded_memory_recovery and not args.baseline_telemetry:parser.error('Bounded-memory recovery requires baseline telemetry.')
    if args.concurrent_background and args.seat_role_lanes:parser.error('Choose one lane upgrade version.')
    if (args.concurrent_background or args.seat_role_lanes) and not args.diagnostic_pause_telemetry:parser.error('Role-slot upgrade requires a verified diagnostic pause.')
    if args.max_decisions<=args.accepted:parser.error('Decision cap must exceed the stopped accepted count.')
    with locked(root,'host-driver',timeout=0):
        action=read(root/'NEXT_ACTION.json')['next_action']
        if action.get('game')!=args.game or action.get('kind')!='dispatch_pilot':
            raise SystemExit('The requested game no longer owns a gameplay frontier.')
        tape=root/f'game_{args.game:02d}'/'decisions.jsonl'
        prefix=tape.read_bytes();digest=hashlib.sha256(prefix).hexdigest()
        if len(host.campaign.read_jsonl(tape))!=args.accepted:
            raise SystemExit('The exact stopped accepted prefix is required.')
        pause=read(root/'HOST_PAUSED.json',{})
        if args.combo_telemetry:
            if pause:raise SystemExit('Combo continuation cannot clear an independent pause.')
        else:validate_pause(pause,args.accepted,args.user_resume,args.decision_limit_resume)
        if sum((args.user_resume,args.decision_limit_resume,args.claim_completion_recovery,args.planner_validation_recovery,args.unanswered_decision_recovery,bool(args.baseline_telemetry),bool(args.combo_telemetry),bool(args.capacity_telemetry),bool(args.diagnostic_pause_telemetry),bool(args.reservation_telemetry)))>1:raise SystemExit('Choose one recovery cause.')
        if (root/'PROBE_PAUSED.json').exists():raise SystemExit('An independent pause remains.')
        sessions=combo_sessions(root,args.game,args.accepted,args.combo_telemetry) if args.combo_telemetry else read(directory/'sessions.json')
        opening_planner=(args.planner_validation_recovery and args.accepted==0 and len(sessions)==1 and is_background(sessions[0]['role']))
        expected={(actor,role) for actor in host.campaign.PILOT_GAMEPLAN_FILES for role in roles(root,args.game)}
        keys={(row['actor'],row['role']) for row in sessions}
        if not keys<=expected or len(keys)!=len(sessions) or not (opening_planner or 4<=len(sessions)<=len(expected)):
            raise SystemExit('Expected original deciders and at most one saved context per configured seat/role.')
        for row in sessions:
            checkpoint=read(directory/'context'/f"{pilot_handoff.seat_slug(row['actor'])}_{row['role']}.json")
            if checkpoint.get('transport_version')!=2:
                raise SystemExit('Legacy rollback contexts require explicit recovery before any route fencing or resumption.')
            if checkpoint.get('checkpoint_pending') or checkpoint.get('thread')!=row['thread']:
                raise SystemExit('An ambiguous or mismatched checkpoint cannot be retried.')
        board=planner_runtime.workboard(root,args.game);active=board.get('active')
        registered_sessions(sessions,board.get('planners',{}),opening_planner=opening_planner)
        if active and active.get('wake')!='not_attempted':
            raise SystemExit('Only a never-dispatched planner reservation can be released here.')
        stopped=read(directory/f'stopped_{args.game}_{args.accepted}.json',{})
        failed_planner=None
        restored_usage={}
        reconciled_capacity=None
        diagnostic=None;reservation=None
        if args.reservation_telemetry:
            if active:raise SystemExit('Reservation recovery requires all background work stopped.')
            from reservation_recovery import validate
            reservation=validate(root,args.reservation_telemetry,args.game,args.accepted,sessions,
                read(directory/'last_failure.json',{}),stopped.get('previous_launch'))
        elif args.diagnostic_pause_telemetry:
            diagnostic=diagnostic_pause_recovery(args.diagnostic_pause_telemetry,args.game,args.accepted,
                read(directory/'last_failure.json',{}),stopped.get('previous_launch'))
        elif args.capacity_telemetry:
            if active:raise SystemExit('Capacity continuation requires all planner work stopped.')
            reconciled_capacity=capacity_continuation(args.capacity_telemetry,args.game,args.accepted,sessions,
                action,read(directory/'last_failure.json',{}),stopped.get('previous_launch'))
        elif args.baseline_telemetry:
            if args.bounded_memory_recovery:
                collection=read(args.baseline_telemetry/'collection.json')
                launch=read(args.baseline_telemetry/'launch.json')
                events=(args.baseline_telemetry/'timing.jsonl').read_text(encoding='utf8').splitlines()
                if (launch!=stopped.get('previous_launch') or collection.get('host_pid')!=launch.get('pid')
                        or collection.get('events')!=len(events)):
                    raise SystemExit('Bounded-memory recovery requires the exact complete stopped process telemetry.')
            restored_usage=baseline_usage_recovery(args.baseline_telemetry,args.game,args.accepted,sessions,
                directory/'context',read(directory/'last_failure.json',{}),bounded_memory=args.bounded_memory_recovery)
        elif args.unanswered_decision_recovery:
            validate_unanswered_failure(read(directory/'last_failure.json',{}),action,args.accepted)
        elif args.planner_validation_recovery:
            failure=read(directory/'last_failure.json',{})
            if (failure.get('code')!='repeated_validation_failure' or not is_background(failure.get('role')) or
                    failure.get('accepted')!=args.accepted or active):
                raise SystemExit('Expected the exact cancelled planner validation stop.')
            failed_planner=failure['actor']
            if registration_key(failed_planner,failure['role']) in board.get('planners',{}):raise SystemExit('Failed planner remains registered; reconcile its execution first.')
        elif args.claim_completion_recovery:
            failure=read(directory/'last_failure.json',{})
            expected=hashlib.sha256(b'Another invocation owns this decision. Inspect host status before recovery.').hexdigest()
            if failure.get('message_sha256')!=expected or failure.get('accepted')!=args.accepted:
                raise SystemExit('This recovery requires the exact diagnosed invocation-conflict stop.')
        elif not (args.user_resume or args.decision_limit_resume or args.combo_telemetry) and 'Seat continuity exceeds checkpoint capacity' not in (stopped.get('stderr') or ''):
            raise SystemExit('This recovery is limited to the diagnosed checkpoint-capacity failure.')
        server=host.AppServer()
        try:
            if args.restore_unused_transports:
                if not args.claim_completion_recovery:raise SystemExit('Unused restoration requires the reconciled invocation-conflict recovery.')
                from edh_gauntlet.host_recovery import restore_unused
                sessions=restore_unused(root,server,sessions)
                # Verify the repaired never-used contexts survive a real
                # process boundary before the ordinary unloaded-seat resume.
                server.close();server=host.AppServer()
            for row in sessions:
                metadata=server.call('thread/read',{'threadId':row['thread'],'includeTurns':False})['thread']
                if metadata.get('status',{}).get('type')!='notLoaded' or Path(metadata['cwd']).resolve()!=directory:
                    raise SystemExit('Every original context must be stopped and unloaded in this workspace.')
            # Preserve prior segment aggregates before Runner overwrites them.
            audit={'game':args.game,'accepted':args.accepted,'prefix_sha256':digest,
                   'diagnostic_pause_continuation':diagnostic,'reservation_recovery':reservation,
                   'concurrent_background_upgrade':args.concurrent_background,
                   'seat_role_lanes_upgrade':args.seat_role_lanes,
                   'previous_pause':pause,'user_authorized_resume':args.user_resume,
                   'combo_continuation':bool(args.combo_telemetry),
                   'decision_limit_resume':args.decision_limit_resume,
                   'claim_completion_recovery':args.claim_completion_recovery,
                   'unanswered_decision_recovery':args.unanswered_decision_recovery,
                   'capacity_continuation':reconciled_capacity,
                   'restarted_cancelled_planner':failed_planner,
                   'unloaded_contexts':len(sessions),'released_unattempted_batch':active['batch_id'] if active else None,
                   'previous_metrics':read(directory/'metrics.json',{}),
                   'previous_failure':read(directory/'last_failure.json',{}),
                   'restored_baseline_usage':restored_usage,
                   'bounded_memory_recovery':args.bounded_memory_recovery,
                   'previous_launch':read(directory/f'stopped_{args.game}_{args.accepted}.json',{}).get('previous_launch')}
            write(directory/f'recovery_{args.game}_{args.accepted}.json',audit)
            if args.concurrent_background or args.seat_role_lanes:
                from edh_gauntlet.background_slots import enable
                enable(root,args.game,role_slots=2 if args.seat_role_lanes else 1)
            if reservation:
                from reservation_recovery import discard
                sessions=discard(root,args.game,sessions,reservation,server)
            if failed_planner:
                discarded=[row for row in sessions if row['actor']==failed_planner and row['role']==failure['role']]
                if len(discarded)!=1:raise SystemExit('Expected exactly one cancelled planner context.')
                server.call('thread/archive',{'threadId':discarded[0]['thread']})
                sessions=[row for row in sessions if row not in discarded]
                write(directory/'sessions.json',sessions)
            if args.combo_telemetry:write(directory/'sessions.json',sessions)
            if args.user_resume or args.decision_limit_resume or args.combo_telemetry:write(root/'HOST_PAUSED.json',{'reason':'host_stopped','accepted':args.accepted})
            if active:planner_runtime.stopped(root,args.game,active['batch_id'],host_status='idle')
            handoff_runtime.recover(root,action['dispatch']['route_id'],
                                    host_status='idle',host_agent=action['dispatch']['agent'])
            if tape.read_bytes()!=prefix:raise SystemExit('Accepted prefix changed during fencing; inspect NEXT_ACTION.')
            if opening_planner:
                if sessions or host.pilot_dispatch.registry(root,args.game) or planner_runtime.workboard(root,args.game).get('planners'):
                    raise SystemExit('Opening recovery requires no surviving initialized seats.')
                # Only the cancelled, unpublished opening planner existed. No
                # decider or accepted gameplay context is being replaced.
                (directory/'sessions.json').unlink()
                if read(root/'HOST_PAUSED.json')!={'reason':'host_stopped','accepted':0} or tape.read_bytes()!=prefix:
                    raise SystemExit('Opening prefix or pause changed before restarting the cancelled planner.')
                (root/'HOST_PAUSED.json').unlink()
            runner=host.Runner(root,server,resume_fenced=not opening_planner,max_decisions=args.max_decisions,context_tokens=64000,timing_events=args.timing_events)
            retained=registered_sessions(sessions,planner_runtime.workboard(root,args.game).get('planners',{}),opening_planner=opening_planner)
            if set(runner.threads)!={row['thread'] for row in retained}:
                raise SystemExit('Recovery changed seat identities.')
            for thread,usage in restored_usage.items():
                if thread in runner.threads:
                    if args.bounded_memory_recovery and usage['first']['inputTokens']>=64000:
                        if not is_background(runner.threads[thread][1]):raise SystemExit('Oversized-baseline recovery is restricted to idle background roles.')
                        runner.contexts.checkpoint(thread,None)
                        continue
                    server.usage[thread]=usage
                    runner.contexts.verify_baseline(thread)
            # Lost process-local token telemetry must not defer the diagnosed
            # pilot checkpoint until after another oversized inference turn.
            actor=runner.action()['actor'];thread=runner.seats.get((actor,'decider'))
            if thread and runner.contexts.values[thread]['turns'] and not (args.claim_completion_recovery or args.planner_validation_recovery or args.unanswered_decision_recovery or args.baseline_telemetry or args.combo_telemetry or args.capacity_telemetry or args.reservation_telemetry or args.diagnostic_pause_telemetry):
                from edh_gauntlet import plan_tiers
                runner.contexts.checkpoint(thread,plan_tiers.anchors(root,args.game,actor,'decider'))
            if args.user_resume:
                from edh_gauntlet import plan_tiers
                for (seat,role),thread in list(runner.seats.items()):
                    if is_background(role) and runner.contexts.values[thread]['turns']:
                        runner.contexts.checkpoint(thread,plan_tiers.anchors(root,args.game,seat,role))
            if tape.read_bytes()!=prefix:raise SystemExit('Checkpoint altered the accepted prefix.')
            write(root/'HOST_RUNTIME.json',{'max_decisions':args.max_decisions})
            audit['resumed_registered_seats']=len(retained)
            audit['transport_version']=2
            write(directory/f'recovery_{args.game}_{args.accepted}.json',audit)
            write(directory/'last_failure.json',{'game':args.game,'accepted':args.accepted,
                'state':'recovered','code':audit['previous_failure'].get('code','explicit_resume')})
            runner.run()
        finally:
            if server.process.poll() is None:server.close()
            if (read(root/'NEXT_ACTION.json')['next_action'].get('kind')=='dispatch_pilot'
                    and not (root/'HOST_PAUSED.json').exists()):
                write(root/'HOST_PAUSED.json',{'reason':'host_stopped',
                    'accepted':len(host.campaign.read_jsonl(tape))})


if __name__=='__main__':main()
