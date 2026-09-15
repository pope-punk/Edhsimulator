"""Explicit Linux reboot recovery at a verified, unchanged stopped frontier."""
import argparse,hashlib,os
from pathlib import Path
from edh_gauntlet import host_runtime as host,pilot_handoff,planner_runtime,handoff_runtime,quarantine
from edh_gauntlet.agent_architecture import registration_key
from edh_gauntlet.dashboard import linux_process_identity
from edh_gauntlet.runtime_store import read,write,locked


def resume(root,game,accepted,max_decisions):
    root=root.resolve();directory=root/'host_runtime';journal=directory/f'restart_recovery_{game}_{accepted}.json'
    with locked(root,'host-driver',timeout=0):
        if journal.exists():raise ValueError('Recovery was already attempted; reconcile its journal before retrying.')
        previous=read(root/'dashboard/launch.json')
        identity=previous.get('linux_process_identity',{})
        if not identity.get('boot_id') or identity['boot_id']==Path('/proc/sys/kernel/random/boot_id').read_text().strip():
            raise ValueError('This recovery requires a verified previous-boot host.')
        if linux_process_identity(previous['pid'])==identity:raise ValueError('Previous host is still alive.')
        tape=root/f'game_{game:02d}'/'decisions.jsonl';prefix=tape.read_bytes()
        if len(host.campaign.read_jsonl(tape))!=accepted:raise ValueError('Accepted prefix changed.')
        if read(root/'HOST_PAUSED.json')!={'reason':'host_stopped','accepted':accepted} or (root/'PROBE_PAUSED.json').exists():
            raise ValueError('Expected the exact stopped frontier and no independent pause.')
        action=read(root/'NEXT_ACTION.json')['next_action']
        if action.get('game')!=game or action.get('kind')!='dispatch_pilot':raise ValueError('Current route is not playable.')
        if (tape.parent/host.campaign.ANSWER_TRANSACTION_FILE).exists():raise ValueError('An answer transaction requires separate reconciliation.')
        host.campaign._require_no_prepared_learning_transaction(root,'resume after restart')
        quarantine.require_clean(host.campaign.DEFAULT_STRATEGY_FILE,root,game)
        sessions=read(directory/'sessions.json');board=planner_runtime.workboard(root,game)
        records=host.pilot_dispatch.registry(root,game);keys=set();contexts={}
        for row in sessions:
            actor,role=row['actor'],row['role'];key=(actor,role)
            if key in keys:raise ValueError('Duplicate seat role.')
            keys.add(key);value=read(directory/'context'/f'{pilot_handoff.seat_slug(actor)}_{role}.json')
            record=(records if role=='decider' else board['planners']).get(actor if role=='decider' else registration_key(actor,role),{})
            if (record.get('agent')!=row.get('agent','/app-server/'+row['thread']) or value.get('thread')!=row['thread'] or
                value.get('transport_version')!=2 or value.get('checkpoint_pending') or value.get('replacement_thread') or
                not pilot_handoff.can_resume_session(value.get('seat_session'),root,game,actor,host.campaign.read_jsonl(tape))):
                raise ValueError('Saved seat identity or checkpoint is ambiguous.')
            contexts[row['thread']]=value
        if not {(actor,'decider') for actor in host.campaign.PILOT_GAMEPLAN_FILES}<=keys:raise ValueError('Missing decider.')
        server=host.AppServer();started=False
        try:
            for row in sessions:
                metadata=server.call('thread/read',{'threadId':row['thread'],'includeTurns':False})['thread']
                if metadata.get('status',{}).get('type')!='notLoaded' or Path(metadata['cwd']).resolve()!=directory:
                    raise ValueError('Every original context must be unloaded in this host workspace.')
            reservations=list(board.get('active_by_role',{}).values()) or ([board['active']] if board.get('active') else [])
            audit={'state':'fencing','game':game,'accepted':accepted,'prefix_sha256':hashlib.sha256(prefix).hexdigest(),
                   'previous_launch':previous,'user_authorized_resume':True,'unloaded_contexts':len(sessions),
                   'interrupted_batches':[x['batch_id'] for x in reservations]}
            write(journal,audit)
            # These processes ended with the previous boot. Requeue only jobs
            # still marked running; preserve already published work and identities.
            for reservation in reservations:planner_runtime.stopped(root,game,reservation['batch_id'],host_status='idle')
            handoff_runtime.recover(root,action['dispatch']['route_id'],host_status='idle',host_agent=action['dispatch']['agent'])
            if tape.read_bytes()!=prefix:raise ValueError('Fencing changed the accepted prefix.')
            runner=host.Runner(root,server,resume_fenced=True,max_decisions=max_decisions,context_tokens=64000,timing_events=4096)
            started=True
            # Re-establish committed memory and a full presentation baseline;
            # unfinished previous-boot turns are never submitted again.
            for thread,(actor,role) in list(runner.threads.items()):
                if role!='decider' or actor==runner.action()['actor']:
                    runner.contexts.checkpoint(thread,None)
            if tape.read_bytes()!=prefix:raise ValueError('Context recovery changed the accepted prefix.')
            launch={'pid':os.getpid(),'linux_process_identity':linux_process_identity(os.getpid()),'game':game,
                    'max_decisions':max_decisions,'context_tokens':64000,'timing_events':4096,'recovery':'verified_previous_boot'}
            write(directory/'launch.json',launch);write(root/'dashboard/launch.json',launch)
            write(journal,{**audit,'state':'running','pid':os.getpid()})
            print(f'Resumed game {game} after {accepted} choices with {len(runner.threads)} seat-role contexts.',flush=True)
            runner.run()
            write(journal,{**audit,'state':'stopped','accepted_after':len(host.campaign.read_jsonl(tape))})
        finally:
            if server.process.poll() is None:server.close()
            if started and not (root/'HOST_PAUSED.json').exists() and read(root/'NEXT_ACTION.json')['next_action'].get('kind')=='dispatch_pilot':
                write(root/'HOST_PAUSED.json',{'reason':'host_stopped','accepted':len(host.campaign.read_jsonl(tape))})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cohort',type=Path,required=True)
    p.add_argument('--game',type=int,required=True);p.add_argument('--accepted',type=int,required=True)
    p.add_argument('--max-decisions',type=int,default=10000);p.add_argument('--user-resume',action='store_true',required=True)
    a=p.parse_args()
    if a.max_decisions<=a.accepted:p.error('Decision cap must exceed the stopped count.')
    resume(a.cohort,a.game,a.accepted,a.max_decisions)
