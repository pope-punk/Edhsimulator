"""Local, opt-in assistant notification for pending pilot help; never plays a game."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
import uuid


def read(path):
    return json.loads(path.read_text())


def write(path,value):
    temp=path.with_suffix('.tmp')
    with temp.open('w') as stream:
        json.dump(value,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    os.replace(temp,path)


def support_resolved(run, request_id):
    """Read-only postcondition; successful CLI exit alone is not recovery evidence."""
    action=read(run/'NEXT_ACTION.json').get('next_action',{})
    game=action.get('game')
    if not isinstance(game,int):return False
    database=run/f'game_{game:02d}'/'rules.sqlite'
    connection=sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True)
    try:state=json.loads(connection.execute('select value from host_state').fetchone()[0])
    finally:connection.close()
    pending=state.get('help_request') or {}
    if (run/'HOST_PAUSED.json').exists():return True
    if pending.get('id')==request_id:return False
    if pending or state.get('terminal'):return True
    # A stop/pause or superseding request remains authoritative. An answered
    # request left at its help-answer pause still needs an explicit resume.
    return not state.get('paused')


def support_prompt(message, root, directory, dashboard_url, key_file):
    return ("You are an independent technical-support agent, separate from the development conversation. "
        "The user authorized this support lane. Handle only this exact request, then end. "
        f"Read {root}/AGENTS.md, docs/GAUNTLET_WORKFLOW.md and the technical-help section of "
        "docs/PRIMITIVE_COORDINATION.md. Read only the help question and necessary schema/command facts. "
        "Never choose actions, targets, colors, payments or strategy; never inspect hidden decks or unrelated "
        "private plans. Never edit repository/runtime source, migrate a started contract, create a game, "
        "replay an accepted action/stage, send messages to other people, or start watchers/agents. "
        "You may write bounded technical-answer/recovery files under archive/releases. "
        "Only supported help-status, exact-prefix answer-help and the existing fenced dashboard resume are "
        "authorized mutations. Confirm owned processes have stopped and contexts are unloaded. "
        f"Before answering and before resuming, check {directory}/STOP and the run's HOST_PAUSED.json; "
        "if either exists, stop. "
        "If the exact request was already answered or superseded, report stale and do nothing. "
        "Give a self-contained schema answer; never tell the pilot what gameplay choice to make. "
        f"For authorized resume use {dashboard_url} with bearer key read from {key_file}; "
        "never print the key. After answering, explicitly resume once and verify progress or report the exact "
        "remaining blocker. Do not repair source or repeat successful recovery. Write a concise final result "
        "with UTC timestamps, request ID, accepted prefix, answer/resume status and unresolved issue, without private strategy. "
        "Prioritize a concise answer to the submitted schema question; do not run broad validation or investigate unrelated improvements. "
        "If another help request arrives, leave it for the next support invocation. " + message)


def tick(runs,directory,thread,send=subprocess.run,mode='queue',*,dashboard_url='http://127.0.0.1:8765',key_file=None,run_id=None):
    """A durable pre-send receipt prevents duplicate/uncertain queue retries."""
    if (directory/'STOP').exists():return []
    notices=[]
    key_file=key_file or runs.parent/'archive/dashboard/capability.key'
    for path in sorted(runs.glob('*/NEXT_ACTION.json')):
        run=path.parent
        if run_id is not None and run.name!=run_id:continue
        try:
            action=read(path).get('next_action',{})
            if action.get('kind')!='await_pilot_help' or (run/'HOST_PAUSED.json').exists():continue
            if not all(k in action for k in ('game','actor','request_id','commit')):continue
            identity={'run':run.name,**{k:action[k] for k in ('game','request_id','commit')}}
            key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
            receipt=directory/(key+'.json')
            if receipt.exists():continue
            if (directory/'STOP').exists():break
            nonce=str(uuid.uuid4())
            value={'identity':identity,'actor':action['actor'],'nonce':nonce,'state':'dispatching','created':time.time()}
            write(receipt,value)
            message=(f'User-authorized pilot-help notification {nonce}. {action["actor"]} requested technical help in {run}. '
                f'Request ID {action["request_id"]}; game {action["game"]}; accepted prefix {action["commit"]}. '
                'Recheck current NEXT_ACTION and help-status; this notification may be stale. '
                'If this exact request is still pending, handle only its technical/schema question using the '
                'documented answer-help command bound to the verified stopped prefix, then resume via the existing '
                'fenced dashboard route when safe and not user-paused. Never choose gameplay actions, replay '
                'accepted actions or stages, change a started contract, or create a duplicate game. '
                'Do not duplicate recovery already being handled in this conversation. Respect all later user '
                f'pause/stop instructions; stop this watcher with {directory / "STOP"} if requested. '
                f'Notification receipt: {receipt}. If already answered or no longer pending, acknowledge without further action.')
            try:
                if mode=='support':
                    command=['codex','exec','--sandbox','danger-full-access','-c','approval_policy="never"',
                             '--cd',str(runs.parent),'--json','--output-last-message',str(receipt.with_suffix('.answer.txt')),
                             support_prompt(message,runs.parent,directory,dashboard_url,key_file)]
                else:command=['codex','queue','--thread',thread,'--message',message]
                if mode=='support' and send is subprocess.run:
                    # Stream evidence while the worker runs; record its identity before waiting.
                    with receipt.with_suffix('.events.jsonl').open('w') as output, receipt.with_suffix('.stderr.log').open('w') as error:
                        worker=subprocess.Popen(command,cwd=str(runs.parent),stdout=output,stderr=error,start_new_session=True)
                        value.update(worker_pid=worker.pid,started=time.time());write(receipt,value)
                        try:code=worker.wait(timeout=300)
                        except subprocess.TimeoutExpired:
                            import signal
                            os.killpg(worker.pid,signal.SIGTERM)
                            worker.wait(timeout=10)
                            raise TimeoutError('Technical worker exceeded 300 seconds; inspect streamed receipt before recovery')
                    result=subprocess.CompletedProcess(command,code,stdout='',stderr=receipt.with_suffix('.stderr.log').read_text()[-2000:])
                else:
                    result=send(command,cwd=str(runs.parent),capture_output=True,text=True,
                                timeout=300 if mode=='support' else 30)
                if mode=='support':
                    if send is not subprocess.run:receipt.with_suffix('.events.jsonl').write_text(result.stdout)
                    resolved=result.returncode==0 and support_resolved(run,action['request_id'])
                    value.update(state='support_finished' if resolved else 'uncertain',
                                 returncode=result.returncode,resolved=resolved,stderr=result.stderr[-2000:])
                else:
                    value.update(state='queued' if result.returncode==0 else 'uncertain',returncode=result.returncode,
                                 stdout=result.stdout,stderr=result.stderr)
            except Exception as error:value.update(state='uncertain',error=str(error))
            if mode=='support' and value['state']=='uncertain' and not (directory/'STOP').exists():
                # Escalate uncertainty once; never launch a second support attempt.
                try:
                    fallback=send(['codex','queue','--thread',thread,'--message',
                        'Independent pilot support ended with an uncertain outcome. Inspect its receipt and current '
                        'owned processes/accepted prefix before any recovery; never duplicate accepted work. '+message],
                        cwd=str(runs.parent),capture_output=True,text=True,timeout=30)
                    value['escalation_returncode']=fallback.returncode
                except Exception as error:value['escalation_error']=str(error)
            value['finished']=time.time()
            write(receipt,value);notices.append(value)
        except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):
            # A partially replaced/unreadable observation is retried next poll;
            # any prepared delivery receipt remains authoritative.
            continue
    return notices


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs',type=Path,required=True)
    parser.add_argument('--state-dir',type=Path,required=True)
    parser.add_argument('--thread',required=True)
    parser.add_argument('--interval',type=float,default=2)
    parser.add_argument('--mode',choices=('queue','support'),default='queue')
    parser.add_argument('--dashboard-url',default='http://127.0.0.1:8765')
    parser.add_argument('--key-file',type=Path)
    parser.add_argument('--run-id',help='Handle only this run; stop when it closes')
    args=parser.parse_args();thread=str(uuid.UUID(args.thread))
    if args.interval<1:parser.error('interval must be at least one second')
    directory=args.state_dir.resolve();directory.mkdir(parents=True,exist_ok=True)
    with (directory/'lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        write(directory/'process.json',{'pid':os.getpid(),'thread':thread,'runs':str(args.runs.resolve()),'interval':args.interval,'mode':args.mode,'dashboard_url':args.dashboard_url})
        while not (directory/'STOP').exists():
            if args.run_id:
                action=read(args.runs/args.run_id/'NEXT_ACTION.json').get('next_action',{})
                if action.get('reason') in ('cohort_complete','cohort_cancelled') or action.get('kind') in ('postgame_review','advance_game'):
                    (directory/'STOP').write_text('Selected game closed.\n');break
            notices=tick(args.runs.resolve(),directory,thread,mode=args.mode,dashboard_url=args.dashboard_url,key_file=args.key_file,run_id=args.run_id)
            for notice in notices:print(json.dumps({'state':notice['state'],'identity':notice['identity']}),flush=True)
            time.sleep(args.interval)


if __name__=='__main__':main()
