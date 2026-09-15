"""Local, opt-in assistant notification for pending pilot help; never plays a game."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
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


def tick(runs,directory,thread,send=subprocess.run):
    """A durable pre-send receipt prevents duplicate/uncertain queue retries."""
    if (directory/'STOP').exists():return []
    notices=[]
    for path in sorted(runs.glob('*/NEXT_ACTION.json')):
        run=path.parent
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
                result=send(['codex','queue','--thread',thread,'--message',message],cwd=str(runs.parent),
                            capture_output=True,text=True,timeout=30)
                value.update(state='queued' if result.returncode==0 else 'uncertain',returncode=result.returncode,
                             stdout=result.stdout,stderr=result.stderr)
            except Exception as error:value.update(state='uncertain',error=str(error))
            write(receipt,value);notices.append(value)
        except (OSError,ValueError,KeyError,TypeError):
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
    args=parser.parse_args();thread=str(uuid.UUID(args.thread))
    if args.interval<1:parser.error('interval must be at least one second')
    directory=args.state_dir.resolve();directory.mkdir(parents=True,exist_ok=True)
    with (directory/'lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        write(directory/'process.json',{'pid':os.getpid(),'thread':thread,'runs':str(args.runs.resolve()),'interval':args.interval})
        while not (directory/'STOP').exists():
            notices=tick(args.runs.resolve(),directory,thread)
            for notice in notices:print(json.dumps({'state':notice['state'],'identity':notice['identity']}),flush=True)
            time.sleep(args.interval)


if __name__=='__main__':main()
