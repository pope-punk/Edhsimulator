"""Local metadata collection only. Never dispatches models or reads seat packets."""
import json,time,ctypes,subprocess,argparse
from datetime import datetime
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--cohort',type=Path,required=True)
parser.add_argument('--game',type=int,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args();root=args.cohort;out=args.output;out.mkdir(parents=True,exist_ok=True)
def read(path):
    # Windows may briefly deny a reader during an atomic metadata replacement.
    # Retry reads only; never replay a host operation or inference.
    for attempt in range(7):
        try:return json.loads(path.read_text(encoding='utf-8-sig'))
        except PermissionError:
            if attempt==6:raise
            time.sleep(.01*2**attempt)
launch=read(root/'host_runtime/launch.json')
if launch['game']!=args.game:raise RuntimeError('Launch game differs from requested game')
started=datetime.fromisoformat(launch['process_started_utc'].replace('Z','+00:00')).timestamp()
pid=int(launch['pid'])
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.OpenProcess.restype=ctypes.c_void_p
kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
handle=kernel.OpenProcess(0x100000,False,pid)
if not handle:raise RuntimeError('Owned host process is absent')
last=0;sampled=0;reported=0;gaps=[]
with (out/'timing.jsonl').open('x',encoding='utf8') as stream, (out/'memory.jsonl').open('x',encoding='utf8') as memory:
    while True:
        try:value=read(root/'host_runtime/timing.json')
        except FileNotFoundError:
            # A fresh collector can start before the host's first timing write.
            # Wait locally; never restart the host or request model status.
            if kernel.WaitForSingleObject(handle,0)!=258:
                raise RuntimeError('Host stopped before creating timing metadata')
            time.sleep(1);continue
        total=value['total_events'];events=value['retained_events']
        if not events or events[-1]['epoch']<started:
            if kernel.WaitForSingleObject(handle,0)!=258:raise RuntimeError('Host stopped before emitting timing')
            time.sleep(1);continue
        first=total-len(events)+1
        if first>last+1:gaps.append({'after':last,'next':first})
        for seq,event in enumerate(events,first):
            if seq>last:stream.write(json.dumps(event,separators=(',',':'))+'\n')
        last=total;stream.flush()
        alive=kernel.WaitForSingleObject(handle,0)==258
        if time.time()-sampled>=60 and alive:
            sampled=time.time()
            command='$rows=Get-CimInstance Win32_Process; $ids=@('+str(pid)+'); do { $add=@($rows | Where-Object { $_.ParentProcessId -in $ids -and $_.ProcessId -notin $ids } | ForEach-Object { [int]$_.ProcessId }); $ids+=$add } while ($add.Count); $owned=@($rows | Where-Object { $_.ProcessId -in $ids }); @{processes=$owned.Count;summed_working_set_bytes=($owned | Measure-Object WorkingSetSize -Sum).Sum} | ConvertTo-Json -Compress'
            result=subprocess.run(['powershell.exe','-NoProfile','-Command',command],capture_output=True,text=True,creationflags=0x08000000)
            try:
                sample=json.loads(result.stdout) if result.returncode==0 else {'unavailable':True}
            except (ValueError, TypeError):
                sample={'unavailable':True}
            # PowerShell can exit successfully after a non-terminating CIM access
            # error. An empty process set is unavailable, never zero memory use.
            if not sample.get('processes') or sample.get('summed_working_set_bytes') is None:
                sample={'unavailable':True,'reason':'process_tree_query_failed'}
            memory.write(json.dumps({'epoch':sampled,**sample})+'\n');memory.flush()
        action=read(root/'NEXT_ACTION.json')['next_action']
        with (root/f'game_{args.game:02d}'/'decisions.jsonl').open('rb') as tape:accepted=sum(bool(line.strip()) for line in tape)
        if accepted>=reported+40 or not alive:
            print(json.dumps({'accepted':accepted,'next':action['kind'],'alive':alive,'events':total}),flush=True);reported=accepted
        if not alive:break
        time.sleep(10)
for name in ('metrics.json','launch.json','timing.json'):
    (out/name).write_bytes((root/'host_runtime'/name).read_bytes())
(out/'collection.json').write_text(json.dumps({'gaps':gaps,'accepted':accepted,'host_pid':pid,'events':last,'next':action['kind']},indent=2)+'\n')
