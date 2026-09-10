"""Queue bounded self-resume reminders for one explicitly authorized Codex thread.

Local process only: it cannot wake a stopped codespace. The receiving agent
acknowledges pending.json after consuming a ping and creates STOP on completion
or a user pause. No gameplay dispatch or model subprocess is launched here.
"""
import argparse
import fcntl
import json
from pathlib import Path
import subprocess
import time
import uuid


def run(directory):
    directory=Path(directory).resolve()
    config=json.loads((directory/'config.json').read_text())
    thread=str(uuid.UUID(config['thread']))
    interval=config['interval_seconds']
    if type(interval) is not int or interval<60:raise ValueError('Interval must be at least 60 seconds')
    with (directory/'lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        pending=directory/'pending.json';stop=directory/'STOP'
        deadline=time.monotonic()+interval
        while not stop.exists():
            if time.monotonic()<deadline:
                time.sleep(max(0,min(1,deadline-time.monotonic())));continue
            deadline=time.monotonic()+interval
            if pending.exists():continue
            nonce=str(uuid.uuid4())
            with pending.open('x') as out:json.dump({'nonce':nonce,'queued_at':time.time()},out)
            message=(f'User-authorized migration heartbeat {nonce}. Continue the existing full migration goal '
                'if unfinished and not paused by the user. Respect all later stop/pause instructions. '
                f'After reading this ping, acknowledge it by removing {pending} only if its nonce matches. '
                f'If the full goal is verified complete, or the user asks to pause/stop, create {stop} '
                'and stop this heartbeat. Do not launch duplicate work or replay accepted game actions.')
            try:
                result=subprocess.run(['codex','queue','--thread',thread,'--message',message],
                    cwd=config['cwd'],capture_output=True,text=True,timeout=60)
                receipt={'nonce':nonce,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
            except Exception as error:
                receipt={'nonce':nonce,'error':str(error)}
            # Keep pending on uncertain delivery: never blindly replay a queue call.
            with (directory/'deliveries.jsonl').open('a') as out:out.write(json.dumps(receipt)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    run(parser.parse_args().directory)
