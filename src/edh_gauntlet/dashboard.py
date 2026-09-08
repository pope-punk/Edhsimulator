"""Capability-key Codespace API for the private EDH operator dashboard."""
from __future__ import annotations

import argparse, hashlib, hmac, json, os, re, secrets, subprocess, sys, threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

STATIC = Path(__file__).with_name("dashboard_static")
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
API_ENV = ("OPENAI_API_KEY", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID")

def read_json(path, default=None):
    try: return json.loads(Path(path).read_text(encoding="utf8"))
    except (OSError, json.JSONDecodeError): return default

def write_json(path, value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,indent=2)+'\n',encoding='utf8'); tmp.replace(path)

class Dashboard:
    def __init__(self,runs,key,python):
        self.runs=Path(runs).resolve();self.runs.mkdir(parents=True,exist_ok=True)
        self.key=key;self.python=python;self.processes={};self.lock=threading.Lock()
    def root(self,run_id):
        if not SAFE_ID.fullmatch(run_id):raise ValueError('Invalid run id')
        result=(self.runs/run_id).resolve()
        if result.parent!=self.runs:raise ValueError('Invalid run path')
        return result
    def host(self,run_id,root):
        process=self.processes.get(run_id);alive=bool(process and process.poll() is None)
        result=read_json(root/'dashboard'/'launch.json',{}) or {};result['alive']=alive
        if process and not alive:result['exit_code']=process.returncode
        return result
    def snapshot(self,run_id):
        root=self.root(run_id);manifest=read_json(root/'manifest.json',{}) or {}
        next_doc=read_json(root/'NEXT_ACTION.json',{}) or {};action=next_doc.get('next_action') or {}
        game=int(action.get('game') or manifest.get('active_game') or 1);directory=root/f'game_{game:02d}'
        status=read_json(directory/'status.json',{}) or {};config=read_json(directory/'game_config.json',{}) or {}
        operator={p.stem:p.read_text(encoding='utf8',errors='replace') for p in sorted((root/'operator').glob('*.md'))} if (root/'operator').exists() else {}
        event_file=directory/'events.jsonl'
        if not event_file.exists():event_file=directory/'decisions.jsonl'
        events=[]
        if event_file.exists():
            for line in event_file.read_text(encoding='utf8',errors='replace').splitlines()[-40:]:
                try:events.append(json.loads(line))
                except json.JSONDecodeError:pass
        files=[p for p in (root/'NEXT_ACTION.json',root/'manifest.json',directory/'status.json',event_file) if p.exists()]
        source='|'.join(f'{p}:{p.stat().st_mtime_ns}:{p.stat().st_size}' for p in files)
        host=self.host(run_id,root);state='running' if host['alive'] else status.get('state') or ('configured' if manifest else 'missing')
        return {'id':run_id,'revision':hashlib.sha256(source.encode()).hexdigest()[:16],'state':state,'game':game,
                'manifest':manifest,'config':config,'next_action':action,'status':status,'operator':operator,
                'events':events,'host':host,'auth_mode':'Codex ChatGPT session; API-key environment removed'}
    def list_runs(self):
        return [{k:s.get(k) for k in ('id','revision','state','game','next_action','host')} for p in sorted(self.runs.iterdir(),reverse=True) if p.is_dir() and SAFE_ID.fullmatch(p.name) for s in [self.snapshot(p.name)]]
    def create(self,body):
        run_id=str(body.get('id') or datetime.now(timezone.utc).strftime('run-%Y%m%d-%H%M%S'));root=self.root(run_id)
        if root.exists():raise FileExistsError('Run already exists')
        specs={'games':(1,1000,20),'seed_start':(1,2**63-1,2026090101),'max_rounds':(1,1000,16)};values={}
        for key,(low,high,default) in specs.items():
            value=int(body.get(key,default))
            if not low<=value<=high:raise ValueError(f'{key} out of range')
            values[key]=value
        learning=body.get('learning','disabled');publication=body.get('planner_publication','staged')
        if learning not in ('enabled','disabled') or publication not in ('staged','single'):raise ValueError('Invalid run configuration')
        command=[self.python,'-m','edh_gauntlet','--cohort',str(root),'init','--games',str(values['games']),
                 '--seed-start',str(values['seed_start']),'--max-rounds',str(values['max_rounds']),'--learning',learning,
                 '--planning-contract','4','--planner-publication',publication,'--agent-architecture']
        if body.get('async_diplomacy',True):command.append('--async-diplomacy')
        result=subprocess.run(command,capture_output=True,text=True,timeout=300)
        if result.returncode:raise RuntimeError((result.stderr or result.stdout)[-2000:])
        write_json(root/'OPERATOR_VIEW.json',{'enabled':True})
        write_json(root/'dashboard'/'configuration.json',{**values,'learning':learning,'planner_publication':publication,'async_diplomacy':bool(body.get('async_diplomacy',True))})
        return self.snapshot(run_id)
    def start(self,run_id,body):
        root=self.root(run_id)
        if not (root/'manifest.json').exists():raise FileNotFoundError('Unknown run')
        with self.lock:
            current=self.processes.get(run_id)
            if current and current.poll() is None:return self.snapshot(run_id)
            maximum=int(body.get('max_decisions',10000));tokens=int(body.get('context_tokens',64000));timing=int(body.get('timing_events',4096))
            if not 1<=maximum<=1_000_000 or not 8000<=tokens<=400000 or not 64<=timing<=4096:raise ValueError('Host limit out of range')
            command=[self.python,'-m','edh_gauntlet.host_runtime','--cohort',str(root),'--max-decisions',str(maximum),'--context-tokens',str(tokens),'--timing-events',str(timing)]
            env=os.environ.copy()
            for name in API_ENV:env.pop(name,None)
            log_path=root/'dashboard'/'host.log';log_path.parent.mkdir(parents=True,exist_ok=True);log=log_path.open('ab',buffering=0)
            process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,cwd=Path.cwd(),env=env,start_new_session=True)
            self.processes[run_id]=process
            write_json(root/'dashboard'/'launch.json',{'pid':process.pid,'started_at':datetime.now(timezone.utc).isoformat(),'max_decisions':maximum,'context_tokens':tokens,'timing_events':timing,'auth_mode':'chatgpt_session_only'})
        return self.snapshot(run_id)
    def pause(self,run_id):
        root=self.root(run_id);accepted=int((self.snapshot(run_id).get('status') or {}).get('decision_count') or 0)
        write_json(root/'HOST_PAUSED.json',{'reason':'user_stop','accepted':accepted});return self.snapshot(run_id)

class Handler(BaseHTTPRequestHandler):
    server_version='EDHDashboard/1'
    @property
    def app(self):return self.server.app
    def auth(self):
        supplied=self.headers.get('Authorization','').removeprefix('Bearer ')
        return bool(supplied) and hmac.compare_digest(supplied,self.app.key)
    def send_value(self,value,status=200,content_type='application/json; charset=utf-8'):
        data=value if isinstance(value,bytes) else (json.dumps(value).encode() if content_type.startswith('application/json') else str(value).encode())
        self.send_response(status);self.send_header('Content-Type',content_type);self.send_header('Cache-Control','no-store');self.send_header('Access-Control-Allow-Origin','*');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def body(self):
        size=int(self.headers.get('Content-Length','0'))
        if size>65536:raise ValueError('Request too large')
        return json.loads(self.rfile.read(size) or b'{}')
    def do_GET(self):
        path=urlparse(self.path).path
        if path.startswith('/api/'):
            if not self.auth():return self.send_value({'error':'unauthorized'},401)
            try:
                if path=='/api/runs':return self.send_value({'runs':self.app.list_runs()})
                match=re.fullmatch(r'/api/runs/([^/]+)',path)
                return self.send_value(self.app.snapshot(match.group(1))) if match else self.send_value({'error':'not found'},404)
            except Exception as exc:return self.send_value({'error':str(exc)},400)
        name='index.html' if path in ('/','/index.html') else path.lstrip('/')
        if name not in ('index.html','app.js','styles.css'):return self.send_value('not found',404,'text/plain')
        target=STATIC/name;types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8'}
        return self.send_value(target.read_bytes(),content_type=types[target.suffix])
    def do_POST(self):
        if not self.auth():return self.send_value({'error':'unauthorized'},401)
        try:
            path=urlparse(self.path).path;body=self.body()
            if path=='/api/runs':return self.send_value(self.app.create(body),201)
            match=re.fullmatch(r'/api/runs/([^/]+)/(start|pause)',path)
            if not match:return self.send_value({'error':'not found'},404)
            return self.send_value(self.app.start(match.group(1),body) if match.group(2)=='start' else self.app.pause(match.group(1)))
        except FileExistsError as exc:return self.send_value({'error':str(exc)},409)
        except Exception as exc:return self.send_value({'error':str(exc)},400)
    def do_OPTIONS(self):
        self.send_response(204);self.send_header('Access-Control-Allow-Origin','*');self.send_header('Access-Control-Allow-Headers','Authorization, Content-Type');self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS');self.end_headers()
    def log_message(self,fmt,*args):sys.stderr.write('dashboard: '+fmt%args+'\n')

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8765);parser.add_argument('--runs',type=Path,default=Path('runs'));parser.add_argument('--python',default=sys.executable);args=parser.parse_args(argv)
    key=os.environ.get('EDH_DASHBOARD_KEY') or secrets.token_urlsafe(32);server=ThreadingHTTPServer((args.host,args.port),Handler);server.app=Dashboard(args.runs,key,args.python)
    print(f'EDH dashboard: http://{args.host}:{args.port}',flush=True);print(f'Capability key: {key}',flush=True);server.serve_forever()

if __name__=='__main__':main()
