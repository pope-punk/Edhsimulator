"""Opt-in software dispatch with resident, isolated App Server seat contexts.

Only dynamic tool arguments enter the referee. No model routes another seat.
Use a fresh contract-4 game; never adopt desktop collaboration subagents.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from .paths import PROJECT_ROOT
import queue
import subprocess
import threading
import time
import uuid

from . import campaign, handoff_runtime, pilot_dispatch, pilot_handoff, pilot_session, planner_runtime, sequence_runtime
from .runtime_store import read, write, locked,identity
from . import plan_tiers
from . import host_contract, host_failures
from .agent_architecture import is_planner,is_background,registration_key

TOOL_RESULT_GUIDANCE=('TOOL RESULTS: In exec, emit the complete result with text(await tools.edh_act(...)) '
    '(likewise edh_inspect, edh_publish, edh_planner_alarm and edh_rules_issue). '
    'For edh_act, start exec with // @exec: {"yield_time_ms":120000} so its bounded host wait does not create a separate polling inference. '
    'Do not extract .content[0].text or print a receipt/fallback: that discards returned decisions, inspections and validation errors. '
    'A returned decision requires another answer even after your previous answer snoozed. End only on parked or stop.')


def tool_result_guidance(role,split=False):
    if not split:return TOOL_RESULT_GUIDANCE
    if is_planner(role):
        return ('In exec emit the complete result of edh_inspect and edh_publish using text(await tools.NAME(...)). '
            'Generate only the requested publication stage. Await its result before the next stage. When next is null, end immediately without repeating the published prose. No routing, polling, gameplay or extra planning turn.')
    if role=='diplomacy':
        return 'Emit the complete edh_inspect or edh_diplomacy result. After the one diplomacy publication, end immediately; no polling or forced reply, and do not repeat the submitted text in a final response.'
    return TOOL_RESULT_GUIDANCE+(' When the current packet offers useful, still-timely sequence steps, prefer reviewing them in this actual edh_act batch (approve/reject/edit/add), with resume_after_passes:true unless renewed judgment is needed. '
        'Use a pilot-authored added step for a changed current action. Do not create a separate adoption call. Expired or irrelevant proposals need no extra rejection turn; decide ordinarily.')


class AppServer:
    """JSON-lines RPC transport. Notifications stay in RAM, not a growing log."""
    def __init__(self, executable='codex', *, observer=None, config_overrides=()):
        self.observer=observer
        arguments=[executable,'app-server','--stdio']
        for setting in config_overrides:arguments.extend(['-c',setting])
        self.process=subprocess.Popen(arguments,stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf8',bufsize=1,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.events=queue.Queue();self.replies={};self.serial=0;self.usage={}
        threading.Thread(target=self._read,daemon=True).start()
        try:
            self.call('initialize',{'clientInfo':{'name':'edh_gauntlet','version':'1'},
                                   'capabilities':{'experimentalApi':True}})
            self.send({'method':'initialized','params':{}})
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                message=json.loads(line)
                if getattr(self,'timing',None):self.timing.observe(message)
                if self.observer:self.observer(message)
                if message.get('method')=='thread/tokenUsage/updated':
                    params=message['params'];self.record_usage(params['threadId'],params['tokenUsage'])
                if 'id' in message and 'method' not in message:
                    pending=self.replies.get(message['id'])
                    if pending:pending.put(message)
                # Streaming prose is private context, not coordinator telemetry.
                elif message.get('method') in {'item/tool/call','turn/completed','error'} or 'id' in message:
                    self.events.put(message)
        except Exception as error:
            self.events.put({'method':'error','params':{'error':{
                'codexErrorInfo':'HostTransportReadError','message':type(error).__name__}}})
        finally:
            for pending in list(self.replies.values()):pending.put({'error':'App Server connection closed'})
            self.events.put({'method':'connection/closed'})

    def record_usage(self,thread,usage):
        # A planner can inspect and publish several stages before its next idle
        # admission. Preserve the first measured input separately from growth.
        previous=self.usage.pop(thread,{})
        first=previous.get('first',{})
        if not first.get('inputTokens') and usage.get('last',{}).get('inputTokens'):
            first=dict(usage['last'])
        self.usage[thread]={**usage,'first':first}
        while len(self.usage)>32:self.usage.pop(next(iter(self.usage)),None)

    def send(self,value):
        self.process.stdin.write(json.dumps(value,ensure_ascii=False)+'\n');self.process.stdin.flush()

    def call(self,method,params):
        self.serial+=1;key=self.serial;pending=queue.Queue();self.replies[key]=pending
        self.send({'id':key,'method':method,'params':params})
        try:
            try:result=pending.get(timeout=60)
            except queue.Empty as error:
                # Never let the event loop mistake an ambiguous RPC timeout
                # for its ordinary empty notification queue and continue play.
                raise RuntimeError('App Server RPC timed out: '+method+'; reconcile before resuming.') from error
            if 'error' in result:raise RuntimeError('App Server rejected '+method+': '+str(result['error']))
            return result['result']
        finally:self.replies.pop(key,None)

    def respond(self,key,value,success=True):
        if getattr(self,'timing',None):self.timing.returned(key,value,success)
        self.send({'id':key,'result':{'success':success,'contentItems':[
            {'type':'inputText','text':json.dumps(value,ensure_ascii=False,separators=(',',':'))}]}})

    def close(self):
        try:self.process.stdin.close()
        except (OSError,ValueError):pass
        try:self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)


def tool(name,description,properties,required):
    return {'type':'function','name':name,'description':description,'inputSchema':{
        'type':'object','properties':properties,'required':required,'additionalProperties':False}}


INSPECT=tool('edh_inspect','Inspect your own frozen/current seat information. Batch queries.',
             {'queries':{'type':'array','items':{'type':'string'},'maxItems':12}},['queries'])
ACT=tool('edh_act','Submit your exact answer or approved batch. Wait for the next own-seat packet in this tool; never route or poll.',
         {'response':host_contract.RESPONSE},['response'])
PUBLISH=tool('edh_publish','Publish one complete planner response, then end this turn.',
             {'response':{'type':'object'}},['response'])
STAGED_PUBLISH=tool('edh_publish','Publish only the requested stage; await its result before generating the next. End when next is null.',
    {'stage':{'type':'string','enum':['standing','short_term','actions','long_term']},'response':{
        **host_contract.PLANNER_RESPONSE,'properties':{k:v for k,v in host_contract.PLANNER_RESPONSE['properties'].items()
            if k not in {'strategic_disposition','strategic_review','diplomacy_brief','diplomacy_brief_action','combo_proposal','long_term_validity','long_term_invalid_reason'}}}},['stage','response'])
ISSUE=tool('edh_rules_issue','Record a recoverable rules issue using public facts only. No repair or rewind.',
           {'reason':{'type':'string','maxLength':2000}},['reason'])
ALARM=tool('edh_planner_alarm','Set, replace or cancel your planner alarm while you have priority.',
           {'alarm':{'type':'object'}},['alarm'])


def persist_transport(server,thread):
    # thread/start alone need not create a durable rollout before its first
    # input. Persist idle contexts without a model turn or private packet.
    server.call('thread/inject_items',{'threadId':thread,'items':[{'type':'message','role':'user',
        'content':[{'type':'input_text','text':'Software transport initialized. Await the next actual seat packet. No inference or tool execution is requested by this marker.'}]}]})


class Runner:
    def __init__(self,root,server,*,model=None,decider_model=None,planner_model=None,warm_seconds=30,max_decisions=None,
                 resume_fenced=False,fresh_contexts=False,context_tokens=64000,timing_events=512):
        self.root=Path(root).resolve();self.server=server;self.model=model
        from .host_routing import Routing
        self.routing=Routing(model=model,decider=decider_model,planner=planner_model)
        self.warm_seconds=warm_seconds;self.max_decisions=max_decisions
        self.seats={};self.threads={};self.pending={};self.active=set();self.claims={};self.invocations={}
        self.table_waiters=set();self.parking=set()
        self.output_contract_delivered=set()
        self.seen_calls=set();self.anchor_ids={}
        self.validation_failures={};self.turn_ids={}
        self.turn_tools={};self.turn_errors={};self.retry_pending={};self.retry_counts={}
        self.unanswered_continuations={}
        self.backgrounds={};self.done=False;self.resume_fenced=resume_fenced
        self.fresh_contexts=fresh_contexts;self.first_delivery=set()
        self.metrics={'dispatches':0,'warm_returns':0,'parked':0,
                                                     'auto_choices':0,'dispatch_seconds':{'count':0,'total':0,'max':0}}
        self.directory=self.root/'host_runtime';self.directory.mkdir(exist_ok=True)
        from .host_telemetry import Timing
        if not 64<=timing_events<=4096:raise ValueError('Timing retention must be between 64 and 4096 events.')
        self.timing=Timing(self.directory/'timing.json',limit=timing_events);self.server.timing=self.timing
        action=self.action();self.game=action.get('game')
        from . import agent_architecture
        if agent_architecture.enabled(self.root,self.game):self.routing.primary.update(agent_architecture.MODELS)
        if (action.get('kind')!='dispatch_pilot' or not self.game or
                read(campaign.game_dir(self.root,self.game)/'game_config.json').get('planning_contract')!=4):
            raise SystemExit('Host runner requires a playing contract-4 game.')
        self.require_fresh()
        from .background_slots import enable
        if not self.resume_fenced and not self.rows() and agent_architecture.enabled(self.root,self.game):enable(self.root,self.game)
        self.concurrent_roles=planner_runtime.workboard(self.root,self.game).get('role_slots')==1
        from .host_context import Contexts
        self.contexts=Contexts(self,context_tokens)
        if self.resume_fenced:self.resume_contexts()
        self.check_pause()

    @property
    def planner(self):
        return next(iter(self.backgrounds.items())) if len(self.backgrounds)==1 else None

    @planner.setter
    def planner(self,value):
        self.backgrounds={} if value is None else {value[0]:value[1]}

    def inference_count(self):
        return len(self.active-self.pending.keys()-self.parking) if self.concurrent_roles else len(self.active)

    def require_fresh(self):
        if self.resume_fenced:
            pause=read(self.root/'HOST_PAUSED.json',{})
            if pause!={'reason':'host_stopped','accepted':len(self.rows())}:
                raise SystemExit('Fenced resume requires the exact stopped-host marker for this accepted prefix.')
            board=planner_runtime.workboard(self.root,self.game)
            if board.get('active'):
                raise SystemExit('Fenced resume refuses an active planner reservation.')
            sessions=read(self.directory/'sessions.json',[])
            planners=board.get('planners',{})
            # A connection failure cancels the planner that was running.  Its
            # stopped workboard identity is authoritative; discard only that
            # unregistered planner context and recreate it on the next job.
            sessions=[row for row in sessions if not (
                is_background(row.get('role')) and
                (planners.get(registration_key(row.get('actor'),row.get('role'))) or {}).get('agent')!=row.get('agent','/app-server/'+str(row.get('thread'))))]
            keys={(row.get('actor'),row.get('role')) for row in sessions}
            deciders={(actor,'decider') for actor in campaign.PILOT_GAMEPLAN_FILES}
            from .agent_architecture import roles
            allowed={(actor,role) for actor in campaign.PILOT_GAMEPLAN_FILES for role in roles(self.root,self.game)}
            if not deciders.issubset(keys) or len(keys)!=len(sessions) or not keys<=allowed:
                raise SystemExit('Fenced resume requires all four deciders and only registered idle planners.')
            write(self.directory/'sessions.json',sessions)
            action=self.action();route=read(campaign.game_dir(self.root,self.game)/'handoffs'/'routes'/
                                           (action['dispatch']['route_id']+'.json'),{})
            if route.get('claim_id'):
                raise SystemExit('Fence the failed route before resuming its host contexts.')
            self.resume_prefix=(campaign.game_dir(self.root,self.game)/'decisions.jsonl').read_bytes()
            self.resume_sessions=sessions
            return
        if self.fresh_contexts:
            if not self.rows():
                raise SystemExit('Fresh-prefix recovery is only for a retained nonempty accepted prefix.')
            board=planner_runtime.workboard(self.root,self.game)
            route=(self.action().get('dispatch') or {})
            if (pilot_dispatch.registry(self.root,self.game) or
                    (self.directory/'sessions.json').exists() or board.get('planners') or
                    board.get('active') or route.get('kind')!='spawn' or route.get('mode')!='fresh'):
                raise SystemExit('Fresh-prefix recovery requires cleared context identities and a fresh spawn route.')
            return
        if self.rows() or pilot_dispatch.registry(self.root,self.game) or (self.directory/'sessions.json').exists():
            raise SystemExit('Use a fresh game: existing contexts require explicit fenced recovery, not automatic adoption.')

    def resume_contexts(self):
        # Validate all durable intents before loading any transport or clearing a pause.
        for row in self.resume_sessions:
            value=read(self.contexts.path(row['actor'],row['role']),{})
            if value.get('checkpoint_pending') or value.get('transport_version')!=2:
                raise RuntimeError('Legacy or interrupted context replacement requires explicit reconciliation.')
        records=pilot_dispatch.registry(self.root,self.game)
        planners=planner_runtime.workboard(self.root,self.game).get('planners',{})
        for row in self.resume_sessions:
            actor,role,thread=row['actor'],row['role'],row['thread']
            expected=(records.get(actor,{}).get('agent') if role=='decider'
                      else (planners.get(registration_key(actor,role)) or {}).get('agent'))
            if expected!=row.get('agent','/app-server/'+thread):
                raise SystemExit(f'Saved {actor} {role} context does not match its registered host identity.')
            if role=='decider' and not pilot_handoff.can_resume_session(
                    records[actor].get('seat_session'),self.root,self.game,actor,self.rows()):
                raise SystemExit(f'Saved {actor} decider does not match the accepted branch.')
            metadata=self.server.call('thread/read',{'threadId':thread,'includeTurns':False})['thread']
            if metadata.get('status',{}).get('type')!='notLoaded':
                raise SystemExit(f'Saved {actor} {role} context is not stopped and unloaded.')
            if Path(metadata['cwd']).resolve()!=self.directory:
                raise SystemExit(f'Saved {actor} {role} context belongs to another workspace.')
            result=self.server.call('thread/resume',{'threadId':thread,'excludeTurns':True,
                'approvalPolicy':'never','sandbox':'read-only'})
            if (result['thread']['id']!=thread or
                    result['thread'].get('status',{}).get('type')!='idle'):
                raise SystemExit(f'Saved {actor} {role} context did not resume idle.')
            key=(actor,role);self.seats[key]=thread;self.threads[thread]=key
            self.contexts.bind(thread,actor,role,resume=True)
            if self.contexts.values[thread].get('checkpoint_pending'):
                raise RuntimeError('Interrupted context checkpoint requires explicit reconciliation.')
            # A warm tool response is a one-way write. A stopped server may
            # have exited before persisting the last packet, even if its pipe
            # accepted it. Re-establish presentation baselines on explicit
            # resume instead of referencing that unconfirmed delivery.
            self.contexts.values[thread].pop('communication_state',None)
            self.contexts.values[thread].pop('component_delivery',None)
            self.contexts.values[thread]['inspection_delivery_pending']=True
            self.contexts.save(thread)
            self.first_delivery.add(thread)
        current=(campaign.game_dir(self.root,self.game)/'decisions.jsonl').read_bytes()
        if hashlib.sha256(current).digest()!=hashlib.sha256(self.resume_prefix).digest():
            raise SystemExit('Accepted prefix changed during fenced context resume.')
        (self.root/'HOST_PAUSED.json').unlink()

    def action(self):return read(self.root/'NEXT_ACTION.json')['next_action']
    def rows(self):return campaign.read_jsonl(campaign.game_dir(self.root,self.game)/'decisions.jsonl')

    def check_pause(self):
        if (self.root/'PROBE_PAUSED.json').exists() or (self.root/'HOST_PAUSED.json').exists():
            raise SystemExit('Run is paused.')

    def agent(self,thread):
        return self.contexts.values.get(thread,{}).get('agent','/app-server/'+thread)

    def save_sessions(self):
        write(self.directory/'sessions.json',[{'actor':a,'role':r,'thread':t,'agent':self.agent(t)}
              for (a,r),t in self.seats.items()])

    def rotate_context(self,thread):
        """Replace transport context only; stable seat registration never changes."""
        actor,role=self.threads[thread];value=self.contexts.values[thread]
        params=self.context_parameters(actor,role)
        if value.get('model'):params['model']=value['model']
        if value.get('model_provider'):params['modelProvider']=value['model_provider']
        if value.get('reasoning_effort'):params['config']={'model_reasoning_effort':value['reasoning_effort']}
        result=self.server.call('thread/start',params)
        fresh=result['thread']['id']
        if fresh==thread or fresh in self.threads:raise RuntimeError('Context replacement reused an existing transport.')
        # Intent remains durable until the old context is archived and both
        # registries have committed. An interrupted replacement never auto-resumes.
        value['replacement_thread']=fresh;self.contexts.save(thread)
        persist_transport(self.server,fresh)
        if value.get('model') and result.get('model',value['model'])!=value['model']:
            raise RuntimeError('Context replacement changed the configured model.')
        if value.get('reasoning_effort') and result.get('reasoningEffort',value['reasoning_effort'])!=value['reasoning_effort']:
            raise RuntimeError('Context replacement changed reasoning effort.')
        self.server.call('thread/archive',{'threadId':thread})
        self.seats[(actor,role)]=fresh
        self.threads.pop(thread);self.threads[fresh]=(actor,role)
        self.contexts.values.pop(thread);self.contexts.values[fresh]=value
        value['thread']=fresh;value.pop('replacement_thread',None)
        value.pop('communication_state',None);value.pop('component_delivery',None)
        self.contexts.baselines.discard(thread)
        self.claims.pop(thread,None);self.invocations.pop(thread,None);self.turn_ids.pop(thread,None)
        self.turn_tools.pop(thread,None);self.retry_counts.pop(thread,None);self.turn_errors.pop(thread,None)
        self.unanswered_continuations.pop(thread,None)
        if hasattr(self,'claim_failures'):
            self.claim_failures={k:v for k,v in self.claim_failures.items() if k[0]!=thread}
        self.seen_calls={call for call in self.seen_calls if call[0]!=thread}
        if hasattr(self.server,'usage'):self.server.usage.pop(thread,None)
        self.anchor_ids.pop((actor,role),None)
        self.output_contract_delivered.discard(thread)
        self.save_sessions()
        return fresh

    def context(self,actor,role):
        key=(actor,role)
        tiered=plan_tiers.enabled(self.root,self.game)
        anchor=plan_tiers.anchors(self.root,self.game,actor,role) if tiered else None
        if tiered and role=='decider':
            request=read(campaign.game_dir(self.root,self.game)/'request.json',{})
            waits=self.__dict__.setdefault('planning_waits',{})
            if not plan_tiers.pilot_ready(self.root,self.game,actor,request):
                waits.setdefault(actor,{'since':time.monotonic(),'decision_id':request.get('decision_id')})
                return None
            if actor in waits:
                wait=waits.pop(actor);elapsed=time.monotonic()-wait['since']
                metric=self.metrics.setdefault('planning_gate_wait',{'count':0,'seconds':0,'max_seconds':0})
                metric['count']+=1;metric['seconds']+=elapsed;metric['max_seconds']=max(metric['max_seconds'],elapsed)
                self.timing.record('planning_gate_ready',actor=actor,decision_id=wait['decision_id'],seconds=elapsed)
        if key in self.seats:
            thread=self.seats[key]
            if self.contexts.due(thread):
                if thread in self.active:
                    if thread in self.pending:
                        self.park(thread,'End this turn for a software context checkpoint. No planning or summary response.','checkpoint')
                    return None
                self.contexts.checkpoint(thread,anchor)
                thread=self.seats[key]
            return thread
        params=self.context_parameters(actor,role)
        result=self.server.call('thread/start',params);thread=result['thread']['id']
        persist_transport(self.server,thread)
        self.seats[key]=thread;self.threads[thread]=key
        self.contexts.bind(thread,actor,role)
        self.contexts.values[thread].update(model=result.get('model',params.get('model')),
            model_provider=result.get('modelProvider',result['thread'].get('modelProvider')),
            reasoning_effort=result.get('reasoningEffort'))
        self.contexts.save(thread)
        self.save_sessions()
        return thread

    def context_parameters(self,actor,role):
        tiered=plan_tiers.enabled(self.root,self.game)
        docs=PROJECT_ROOT/'docs'
        names=['MANUAL_REFEREE_PROTOCOL.md','SPLIT_RUNTIME_POLICY.md',
               'PLANNER_RUNTIME_POLICY.md' if is_planner(role) else 'APPROVED_SEQUENCES.md']
        policy='\n'.join((docs/name).read_text(encoding='utf8') for name in names)
        instructions=(f'You are the isolated {actor} {role} for one game. Use only edh_* tools and supplied seat inputs. '
            'No shell, filesystem, network, other agents or other seats. Never see ordered libraries. '
            'The host handles all routing and identities. Host policy overrides the direct-handoff portions below: '
            'never call another agent. edh_act takes {response:{answer:...}} or {response:{batch:...}}; '
            'the host adds frozen claim identities, never strategic fields. Normally include resume_after_passes:true '
            'to authorize remaining approved steps after opponents only pass; omit it if you require a fresh decision. '
            'All new items need rationale and snooze. '
            'While edh_act waits, do nothing. On parked or stop, end immediately with no gameplay or polling. '
            'A later input resumes this same isolated context. Rules defects are recorded, never patched here. '
            'Planners must inspect roles, deck and seed on initialization and read all supplied own rationales. '
            'Planners publish once and end; they never execute gameplay.\n'+policy)
        from . import planner_stages
        staged=planner_stages.enabled(self.root,self.game)
        if staged:
            instructions+='\nSTAGED PUBLICATION overrides single-publication and opening long-term rules above: use separate edh_publish calls for short_term prose, then actions, then long_term only if the frozen input requests it. Await each result before generating the next stage. Never repeat frozen input or unchanged fields. End when next is null. The seed supplies the opening strategic baseline until requested long-term maintenance.'
        if tiered:
            instructions+='\nTHREE-TIER CONTRACT overrides earlier planning cadence: immutable standing deck reference at initialization; automatically establish the opening-hand long-term goal; then concise short-term card sequencing and symbolic actions. Requested strategic replacements precede short-term sequencing. Follow publication_stages exactly. Only the planner writes any plan; pilots adapt actions and may request replacement of the long-term goal using planner_alarm long_term:true. Standing never changes. Retained strategic references are developer context, preserved independently of summarized conversation history.'
        if role=='decider':
            from .pilot_plan_packet import GUIDANCE
            instructions+='\nPILOT STRATEGIC PRIORITY: '+GUIDANCE
        if self.contexts.enabled:
            from .host_instructions import instructions as role_instructions
            from . import static_standing
            instructions=role_instructions(actor,role,static_standing=static_standing.enabled(self.root,self.game))
            if role=='decider':instructions+='\nPILOT STRATEGIC PRIORITY: '+GUIDANCE
        if role=='decider':instructions+='\n'+host_contract.GUIDANCE
        params={'cwd':str(self.directory),'environments':[],'selectedCapabilityRoots':[],
                'sandbox':'read-only','approvalPolicy':'never','baseInstructions':instructions,
                'dynamicTools':[INSPECT,STAGED_PUBLISH if staged else PUBLISH] if is_planner(role) else [INSPECT,ACT,ISSUE,ALARM]}
        from . import agent_architecture
        if agent_architecture.enabled(self.root,self.game):
            from . import static_standing
            static=static_standing.enabled(self.root,self.game)
            if role in agent_architecture.EFFORTS:params['config']={'model_reasoning_effort':agent_architecture.EFFORTS[role]}
            if is_planner(role):
                from .split_planning import fields
                stages=['standing','long_term'] if role==agent_architecture.LONG else ['short_term','actions']
                if static and role==agent_architecture.LONG:stages=['long_term']
                allowed=set().union(*(fields(stage) for stage in stages))
                if read(self.root/f'game_{self.game:02d}'/'game_config.json',{}).get('turn_batches')!=1:
                    allowed.discard('phase_coverage')
                from .decision_roles import enabled as decision_roles_enabled
                if decision_roles_enabled(self.root,self.game):allowed-= {'table_talk','strategic_disposition','strategic_review'} if role==agent_architecture.SHORT else set()
                else:allowed-= {'combo_proposal','long_term_validity','long_term_invalid_reason'}
                schema={**host_contract.PLANNER_RESPONSE,'properties':{k:v for k,v in host_contract.PLANNER_RESPONSE['properties'].items() if k in allowed}}
                params['dynamicTools']=[INSPECT,tool('edh_publish','Publish the next stage owned by your role. End when next is null.',
                    {'stage':{'type':'string','enum':stages},'response':schema},['stage','response'])]
            elif role=='diplomacy':
                from .diplomacy import RESPONSE_SCHEMA
                params['dynamicTools']=[INSPECT,tool('edh_diplomacy','Compose one authorized post, remain silent, or request strategic authorization. End after publication.',
                    {'response':RESPONSE_SCHEMA},['response'])]
        from .decision_roles import enabled as decision_roles_enabled
        if role=='decider' and decision_roles_enabled(self.root,self.game):
            import copy
            act=copy.deepcopy(ACT)
            for field in ('message_text','message_address','message_recipient'):
                act['inputSchema']['properties']['response']['oneOf'][0]['properties']['answer']['properties'].pop(field,None)
            params['dynamicTools']=[INSPECT,act,ISSUE,ALARM]
            params['baseInstructions']+='\nPublic speech and mandatory greetings belong only to your diplomat. A combo menu option carries the short-term planner’s proof; select it only if valid now, with your approval rationale. No self-authored combo proposals.'
        if self.contexts.enabled:params['historyMode']='legacy'
        turn_batches=read(self.root/f'game_{self.game:02d}'/'game_config.json',{}).get('turn_batches')==1
        if role=='short_term_planner' and turn_batches:
            params['baseInstructions']+='\nBOUND PRE-TURN POLICY: each of the two preceding living opponents\' end steps queues mandatory short-term work. When full_turn_batch_required is present, an invalid goal still proceeds to interim actions while Sol works concurrently; it does not end this batch. Follow the supplied target own-turn ordinal and full three-phase coverage. Keep known plays concrete, with per-step rationale and snooze; unknown draws do not excuse an empty known-card line.'
        if role=='decider':
            import copy
            params['dynamicTools']=copy.deepcopy(params['dynamicTools'])
            if turn_batches:
                from .turn_batches import PILOT_GUIDANCE
                params['baseInstructions']+='\nBOUND TURN-BATCH POLICY overrides earlier batch defaults: '+PILOT_GUIDANCE
            else:
                for entry in params['dynamicTools']:
                    if entry['name']=='edh_act':
                        entry['inputSchema']['properties']['response']['oneOf'][1]['properties']['batch']['properties'].pop('pass_priority',None)
        params['model']=self.routing.primary[role]
        return params

    def start_turn(self,thread,text):
        actor,role=self.threads[thread]
        self.timing.bind(thread,actor,role)
        model=self.routing.select(role)
        if self.routing.delay(model)>0:
            raise RuntimeError('All configured models are cooling down; stop admission rather than spend inference.')
        value=self.contexts.values[thread]
        params={'threadId':thread,'model':model,'input':[{'type':'text','text':text}]}
        if value.get('reasoning_effort'):params['effort']=value['reasoning_effort']
        self.timing.record('turn_request',thread,input_chars=len(text),model=model,
            previous_model=value.get('model'),effort=value.get('reasoning_effort'))
        result=self.server.call('turn/start',params)
        value['model']=model;self.contexts.save(thread)
        counts=self.metrics.setdefault('model_turns',{}).setdefault(role,{})
        counts[model]=counts.get(model,0)+1
        write(self.directory/'routing.json',{'policy':self.routing.policy(),'turns':self.metrics['model_turns']})
        return result

    @staticmethod
    def compact(packet):
        # Current prose is already present once in the plan-first brief.
        omitted={'continuity','packet_directory'}
        if packet.get('context_handling')==1 and packet.get('state')=='decision':
            omitted.update({'claim_id','route_id','invocation_id','pilot_context_id'})
        result={k:v for k,v in packet.items() if k not in omitted}
        if packet.get('context_handling')==1 and packet.get('state')=='decision':
            plan_id=(packet.get('continuity') or {}).get('plan_id')
            if plan_id:result['plan_id']=plan_id
        return result

    def deliver(self,thread,packet):
        actor,role=self.threads[thread];key=(actor,role)
        if packet.get('actor',actor)!=actor or packet.get('role',role)!=role or packet.get('game',self.game)!=self.game:
            raise RuntimeError('Refusing packet delivery to a different seat, role or game.')
        if thread in self.active and thread not in self.pending:return False
        if thread not in self.output_contract_delivered:
            from .agent_architecture import enabled as split_enabled
            packet={**packet,'tool_result_contract':tool_result_guidance(role,split_enabled(self.root,self.game))}
        self.timing.bind(thread,actor,role)
        metadata={}
        if packet.get('agent_architecture')==1 or (packet.get('continuity') or {}).get('component_refs'):
            if role=='decider':
                request=read(campaign.game_dir(self.root,self.game)/'request.json',{})
                metadata={k:request.get(k) for k in ('round','turn','phase')}
            else:
                metadata={k:packet.get('board',{}).get(k) for k in ('round','turn','phase')}
                metadata.update(batch_id=packet.get('batch_id'),source_decision=packet.get('source_session',{}).get('accepted_prefix_count'))
        self.timing.record('packet',thread,decision_id=packet.get('decision_id'),warm=thread in self.pending,**metadata)
        anchor_id=None
        if plan_tiers.enabled(self.root,self.game):
            anchor=plan_tiers.anchors(self.root,self.game,actor,role)
            anchor_id=identity(anchor)
            if self.anchor_ids.get(key)!=anchor_id:
                packet={**packet,'retained_strategic_reference':anchor}
        value=self.contexts.values[thread]
        if value.get('memory_delivery_pending') or value.get('inspection_delivery_pending'):
            from .host_context import checkpoint_knowledge
            retained=value.get('retained',{}) if value.get('memory_delivery_pending') else {}
            packet={**packet,'seat_continuity':{**retained,
                     'inspected_knowledge':checkpoint_knowledge(value.get('knowledge',{}))}}
        prefetched=[]
        if role=='short_term_planner' and packet.get('visible_rule_refs'):
            from .planner_facts import prepare
            packet,prefetched=prepare(planner_runtime.directory_for(self.root,self.game),packet,value.get('knowledge',{}))
        if thread in self.first_delivery:
            packet={**packet,'host_resume_notice':(
                'The prior software host stopped. Its route was fenced and the '
                'accepted prefix was verified during explicit recovery. Prior tool invocations ended with that host; '
                'do not retry them. Use only this current packet and retain your own-seat context.')}
        if is_planner(role) and self.contexts.enabled:
            from .planner_memory import inventory
            packet={**packet,'knowledge_inventory':inventory(value.get('knowledge',{}),
                bool(anchor_id or self.anchor_ids.get(key)))}
        packet=self.compact(packet)
        if role=='decider' and self.claims.get(thread,{}).get('continuity',{}).get('component_refs'):
            packet={**packet,'component_refs':self.claims[thread]['continuity']['component_refs']}
        from . import communications
        before_chars=communications.size(packet)
        previous=value.get('communication_state',{})
        if previous.get('thread')!=thread:previous={}
        packet,communication_state=communications.prepare(packet,role,previous.get('delivery'))
        new_turn=thread not in self.pending
        if thread in self.pending:
            request,_=self.pending[thread]
            self.server.respond(request,packet)
            self.pending.pop(thread)
            if thread in self.table_waiters:
                self.metrics['table_warm_returns']=self.metrics.get('table_warm_returns',0)+1
                self.table_waiters.discard(thread)
            self.metrics['warm_returns']+=1
        else:
            result=self.start_turn(thread,json.dumps(packet,ensure_ascii=False,separators=(',',':')))
            self.active.add(thread)
            self.turn_ids[thread]=result['turn']['id']
            self.turn_tools[thread]=0
        # Commit delivery knowledge only after the transport accepted the send.
        # An exception remains a stopped/ambiguous transport, never an automatic
        # retry. Preserve its pending request and all undelivered references.
        if anchor_id is not None:self.anchor_ids[key]=anchor_id
        self.first_delivery.discard(thread)
        self.record_delivery(thread,packet,communication_state,new_turn,before_chars,prefetched=prefetched)
        self.output_contract_delivered.add(thread)
        return True

    def record_delivery(self,thread,packet,communication_state,new_turn,source_chars,*,prefetched=()):
        """Commit the model view after a successful primary or refreshed delivery."""
        from . import communications
        role=self.threads[thread][1]
        self.contexts.values[thread]['communication_state']={'thread':thread,'delivery':communication_state}
        refs=packet.get('component_refs',{})
        if refs:
            self.contexts.values[thread]['component_delivery']={'thread':thread,
                'offered':{k:v['component_id'] for k,v in refs.items()},
                'acknowledged':self.contexts.values[thread].get('component_delivery',{}).get('acknowledged',{})}
        # Count all roles, including plain diplomatic packets. Encoding is not
        # a prerequisite for measuring actual delivered context.
        count=self.metrics.setdefault('communication_chars',{}).setdefault(role,{'packets':0,'source':0,'delivered':0})
        count['packets']+=1;count['source']+=source_chars;count['delivered']+=communications.size(packet)
        self.contexts.delivered(thread,packet,new_turn)
        if prefetched:
            self.contexts.inspected(thread,prefetched,count_delivery=False)
            counts=self.metrics.setdefault('prefetched_card_definitions',{})
            counts[role]=counts.get(role,0)+sum(len(row['result']['catalog_records']) for row in prefetched)

    def park(self,thread,instruction,reason):
        request,_=self.pending.pop(thread)
        self.table_waiters.discard(thread)
        self.parking.add(thread)
        self.server.respond(request,{'state':'parked','instruction':instruction})
        self.metrics['parked']+=1
        self.timing.record('park_requested',thread,reason=reason)

    def slot_available(self,thread):
        if self.concurrent_roles:
            actor,role=self.threads[thread]
            occupied=self.active-self.pending.keys()-self.parking
            return thread in occupied or (len(occupied)<4 and not any(self.threads[t][1]==role for t in occupied))
        if thread in self.active or len(self.active)<4:return True
        # Waiting turns count against capacity until host completion is observed.
        # A prior park already releases the needed slot when it completes. Do
        # not drain other warm seats while that final response is still running.
        if self.parking & self.active:return False
        if self.pending:
            candidates=self.table_waiters & self.pending.keys() or self.pending
            oldest=min(candidates,key=lambda key:self.pending[key][1])
            self.park(oldest,'Release capacity; end this turn.','slot_pressure')
        return False

    def pump(self):
        # Keep retained goal selection and the claim's plan version atomic.
        with locked(self.root),locked(planner_runtime.directory_for(self.root,self.game),'planning'):
            return self._pump()

    def _pump(self):
        self.check_pause();action=self.action()
        if action.get('kind')!='dispatch_pilot' or action.get('game')!=self.game:
            self.done=True;return
        if self.max_decisions is not None and len(self.rows())>=self.max_decisions:
            write(self.root/'HOST_PAUSED.json',{'reason':'decision_limit','accepted':len(self.rows())})
            self.done=True;return
        from .diplomacy import flush
        if flush(self.root,self.game):action=self.action()
        from .decision_roles import flush as flush_combos
        if flush_combos(self.root,self.game):action=self.action()
        continued=sequence_runtime.continue_pending(self.root)
        if continued['state']=='continued':
            self.metrics['auto_choices']+=continued['accepted'];return self.pump()
        if continued['state']=='stop':self.done=True;return
        action=self.action();actor=action['actor'];thread=self.context(actor,'decider')
        if thread is not None and (thread not in self.active or thread in self.pending):
            if thread not in self.active and self.routing.delay(self.routing.select('decider'))>0:return
            if not self.slot_available(thread):return
            before=time.monotonic()
            if not pilot_dispatch.registry(self.root,self.game).get(actor):
                pilot_dispatch.register(self.root,actor,self.agent(thread));action=self.action()
            if thread not in self.active:self.invocations[thread]=str(uuid.uuid4())
            claim=handoff_runtime.claim_read(self.root,actor,action['dispatch']['route_id'],self.invocations[thread],
                                            context_checkpoint=thread in self.contexts.baselines)
            self.claims[thread]=claim;self.deliver(thread,claim)
            self.metrics['dispatches']+=1;elapsed=time.monotonic()-before;metric=self.metrics['dispatch_seconds']
            metric['count']+=1;metric['total']+=elapsed;metric['max']=max(metric['max'],elapsed)
        # Independent role lanes share no active-job pointer. Waiting pilot
        # tools retain their contexts without occupying an inference lane.
        from .agent_architecture import SHORT,LONG,DIPLOMACY
        lanes=(SHORT,LONG,DIPLOMACY) if self.concurrent_roles else (None,)
        for lane in lanes:
            board=planner_runtime.workboard(self.root,self.game,role=lane)
            if not board['next_actor']:continue
            role=board.get('next_role') or 'planner'
            if any(job.get('role','planner')==role for job in self.backgrounds.values()):continue
            if self.routing.delay(self.routing.select(role))>0:continue
            thread=self.context(board['next_actor'],role)
            if thread is None or not self.slot_available(thread):continue
            expected=(board['next_actor'],role)
            job=planner_runtime.reserve(self.root,self.game,admission_id=str(uuid.uuid4()),
                host_capacity=4,host_active=self.inference_count(),expected_identity=expected)
            if job.get('state') in {'idle','reschedule'}:
                self.timing.record('background_rescheduled',thread,reason=job.get('reason',job['state']))
                if job.get('state')=='reschedule':
                    # A local scheduling change must not wait for a model token.
                    self.server.events.put({'method':'host/background/rescheduled','params':{}})
                continue
            if (job['actor'],job.get('role','planner'))!=self.threads[thread]:
                raise RuntimeError('Reserved background identity differs from its prepared context.')
            self.backgrounds[thread]=job
            self.timing.record('planner_reserved',thread,actor=job['actor'],role=job.get('role','planner'),
                source_accepted=job['source_session']['accepted_prefix_count'],accepted=len(self.rows()),
                snapshot_refresh=job.get('snapshot_refresh'),background_active=len(self.backgrounds),
                queue_seconds=job.get('queue_seconds'))
            planner_runtime.dispatched(self.root,self.game,job['batch_id'],agent=self.agent(thread),outcome='accepted')
            packet=planner_runtime.read_job(self.root,self.game,job['actor'],job['batch_id'],job['generation'])
            self.deliver(thread,packet)

    def expire_waiters(self):
        for thread,due in list(self.retry_pending.items()):
            if time.monotonic()<due:continue
            self.check_pause()
            if self.action().get('kind')!='dispatch_pilot':continue
            actor,role=self.threads[thread]
            if role=='decider' and (self.action().get('actor')!=actor or
                    self.action().get('decision_id')!=self.claims[thread]['decision_id']):
                raise RuntimeError('Capacity retry lost its original decision; reconcile before continuing.')
            if is_background(role):
                if thread not in self.backgrounds:
                    raise RuntimeError('Capacity retry lost its original planner job.')
                job=self.backgrounds[thread];active=planner_runtime.reservation(planner_runtime.workboard(self.root,self.game),job['batch_id']) or {}
                if active.get('batch_id')!=job['batch_id'] or active.get('generation')!=job['generation']:
                    raise RuntimeError('Capacity retry lost its frozen planner generation.')
            delay=self.routing.delay(self.routing.select(role))
            if delay>0:
                self.retry_pending[thread]=time.monotonic()+delay;continue
            result=self.start_turn(thread,
                'The preceding inference failed before any tool call. Continue the same unanswered frozen input already in this context. Do not replay an earlier accepted action.')
            self.turn_ids[thread]=result['turn']['id'];self.turn_tools[thread]=0
            self.retry_pending.pop(thread)
        for thread,(request,since) in list(self.pending.items()):
            if time.monotonic()-since>=self.warm_seconds:
                self.park(thread,'End this turn; retain your seat context.','warm_timeout')

    def handle(self,message):
        method=message['method'];params=message.get('params',{})
        if method in {'item/tool/call','turn/completed'}:
            self.contexts.verify_baseline(params.get('threadId'))
        if method in {'connection/closed','error'}:
            record=host_failures.metadata(method,params)
            record.update(game=self.game,accepted=len(self.rows()))
            write(self.directory/'last_failure.json',record)
            thread=params.get('threadId')
            if method=='error' and record['will_retry']:
                return  # App Server owns this bounded upstream retry, not a new host turn.
            if method=='error' and thread in self.active and record['code']=='server_overloaded':
                self.turn_errors[thread]=record
                return  # Wait for authoritative turn completion; never replay a tool.
            raise RuntimeError('Host failure ('+record['code']+'); see bounded last_failure.json and reconcile before resuming.')
        if method=='turn/completed':
            thread=params['threadId'];self.active.discard(thread)
            if thread in self.contexts.values:self.contexts.save(thread)
            if self.turn_ids.get(thread) and params['turn'].get('id',self.turn_ids[thread])!=self.turn_ids[thread]:
                self.active.add(thread)
                raise RuntimeError('Completion does not match the active turn; reconcile before retrying.')
            self.parking.discard(thread)
            error=self.turn_errors.pop(thread,None) or host_failures.metadata(method,params)
            if params['turn'].get('status')!='completed':
                write(self.directory/'last_failure.json',{**error,'game':self.game,'accepted':len(self.rows()),
                      'tool_calls':self.turn_tools.get(thread,0)})
                if (error['code']=='server_overloaded' and not self.turn_tools.get(thread,0) and
                        thread not in self.pending and self.retry_counts.get(thread,0)<2):
                    self.check_pause()
                    self.routing.overloaded(self.contexts.values[thread]['model'])
                    count=self.retry_counts.get(thread,0)+1;self.retry_counts[thread]=count
                    self.retry_pending[thread]=time.monotonic()+2**count
                    self.active.add(thread)  # Reserve its slot while waiting without inference.
                    self.metrics['capacity_retries']=self.metrics.get('capacity_retries',0)+1
                    return
                raise RuntimeError('Seat turn failed or capacity retries exhausted; see last_failure.json.')
            if self.retry_counts.pop(thread,None):
                write(self.directory/'last_failure.json',{'game':self.game,'accepted':len(self.rows()),
                      'thread_id':thread,'code':'server_overloaded','state':'recovered'})
            if thread in self.backgrounds:
                active=planner_runtime.reservation(planner_runtime.workboard(self.root,self.game),self.backgrounds[thread]['batch_id']) or {}
                unpublished=not active.get('published_at')
                role=self.threads[thread][1]
                planner_runtime.stopped(self.root,self.game,self.backgrounds[thread]['batch_id'],host_status='completed');self.backgrounds.pop(thread)
                if unpublished:
                    self.timing.record('background_unpublished',thread,optional=role=='diplomacy' and not active.get('requires_public_post'))
                    self.metrics['background_unpublished']=self.metrics.get('background_unpublished',0)+1
                    if role in {'short_term_planner','long_term_planner'} or active.get('requires_public_post'):
                        raise RuntimeError('Background planner ended without completing publication; preserve its work for explicit recovery.')
            elif thread in self.pending:raise RuntimeError('Waiting tool lost its active turn.')
            elif thread in self.claims:
                claim=self.claims[thread];action=self.action()
                if (action.get('kind')=='dispatch_pilot' and action.get('actor')==claim['actor'] and
                        action.get('decision_id')==claim['decision_id']):
                    # A warm packet can be delivered just before the model ends
                    # its turn. That input is already claimed by this invocation.
                    # Continue it once; never mint a competing invocation or
                    # duplicate the packet, and never replay an accepted answer.
                    self.check_pause()
                    handoff_runtime.validate_claim(self.root,claim['actor'],claim['claim_id'])
                    if self.unanswered_continuations.get(thread)==claim['claim_id']:
                        write(self.directory/'last_failure.json',{'game':self.game,'accepted':len(self.rows()),
                            'actor':claim['actor'],'role':'decider','code':'unanswered_decision',
                            'decision_id':claim['decision_id']})
                        raise RuntimeError('Pilot ended twice without answering its current frozen decision.')
                    self.unanswered_continuations[thread]=claim['claim_id']
                    prompt=('Your latest frozen decision '+claim['decision_id']+' remains unanswered. '
                        'Continue that input already in this context using edh_act. Do not repeat an earlier accepted action. '
                        'If the previous edh_act result contained a decision, it requires your response even if your prior answer snoozed.')
                    result=self.start_turn(thread,prompt)
                    self.active.add(thread);self.turn_ids[thread]=result['turn']['id'];self.turn_tools[thread]=0
                    self.contexts.delivered(thread,{'instruction':prompt},True)
                    self.metrics['unanswered_turn_continuations']=self.metrics.get('unanswered_turn_continuations',0)+1
            return
        if method!='item/tool/call':
            if 'id' in message:raise RuntimeError('Unexpected host request; no permission is auto-approved.')
            return
        self.check_pause();thread=params['threadId'];actor,role=self.threads[thread]
        self.turn_tools[thread]=self.turn_tools.get(thread,0)+1
        call=(thread,params.get('callId',message['id']))
        if call in self.seen_calls:raise RuntimeError('Repeated host tool call; reconcile rather than rebinding it to a newer decision.')
        self.seen_calls.add(call)
        name=params['tool'];args=params['arguments'];request=message['id']
        delivery=self.contexts.values[thread].get('component_delivery')
        if delivery and delivery['thread']==thread:
            delivery['acknowledged']=dict(delivery['offered']);self.contexts.save(thread)
        try:
            if is_background(role) and (thread not in self.backgrounds or
                    (self.backgrounds[thread]['actor'],self.backgrounds[thread].get('role','planner'))!=(actor,role)):
                raise RuntimeError('Background tool context does not own the reserved seat and role.')
            if name=='edh_inspect':
                if is_background(role):
                    job=self.backgrounds[thread]
                    value=planner_runtime.inspect_many(self.root,self.game,actor,job['batch_id'],job['generation'],args['queries'])
                else:value=pilot_session.inspect_many(self.root,actor,args['queries'],claim_id=self.claims[thread]['claim_id'])
                from . import communications_inspection
                if is_planner(role) and self.contexts.enabled:
                    from . import planner_memory
                    anchor=plan_tiers.anchors(self.root,self.game,actor,role)
                    seed=(anchor.get('full_seed_plan') if self.anchor_ids.get((actor,role))==identity(anchor) else None)
                    baseline=self.contexts.values[thread].get('communication_state',{})
                    baseline=baseline.get('delivery',{}) if baseline.get('thread')==thread else {}
                    delivered=planner_memory.present(value,self.contexts.values[thread].get('knowledge',{}),seed,
                        current_board=baseline.get('board'),snapshot=baseline.get('snapshot'))
                else:delivered=communications_inspection.present(value)
                self.server.respond(request,delivered)
                self.contexts.inspected(thread,value,delivered=delivered)
                counts=self.metrics.setdefault('inspection_chars',{}).setdefault(role,{'raw':0,'delivered':0})
                counts['raw']+=communications_inspection.size(value)
                counts['delivered']+=communications_inspection.size(delivered)
                if is_planner(role) and self.contexts.enabled:
                    counts=self.metrics.setdefault('planner_inspection_chars',{'raw':0,'delivered':0})
                    counts['raw']+=planner_memory.size(value)
                    counts['delivered']+=planner_memory.size(delivered)
            elif name=='edh_diplomacy' and role=='diplomacy':
                from .diplomacy import publish
                job=self.backgrounds[thread]
                self.server.respond(request,publish(self.root,self.game,actor,job['batch_id'],job['generation'],args['response']))
            elif name=='edh_publish' and is_planner(role):
                job=self.backgrounds[thread]
                host_contract.validate_frozen_planner_response(self.root,self.game,actor,job,args['response'])
                from . import planner_stages
                if planner_stages.enabled(self.root,self.game):
                    result=planner_stages.publish(self.root,self.game,actor,job['batch_id'],job['generation'],args['stage'],args['response'])
                else:result=planner_runtime.publish(self.root,self.game,actor,job['batch_id'],job['generation'],args['response'])
                from . import communications
                self.server.respond(request,communications.receipt({'state':'published',**result},schema_available=True))
            elif name=='edh_rules_issue' and role=='decider':
                from . import quarantine
                handoff_runtime.validate_claim(self.root,actor,self.claims[thread]['claim_id'])
                quarantine.quarantine_games(campaign.DEFAULT_STRATEGY_FILE,self.root,[self.game],args['reason'])
                campaign.next_action(self.root)
                action=self.action()
                packet=handoff_runtime.claim_read(self.root,actor,action['dispatch']['route_id'],self.invocations[thread])
                self.claims[thread]=packet
                from . import communications
                compact=self.compact(packet)
                current,communication_state=communications.prepare(compact,'decider')
                self.server.respond(request,{'state':'recorded','repairs':'deferred',
                    'current':current})
                self.record_delivery(thread,current,communication_state,False,communications.size(compact))
            elif name=='edh_planner_alarm' and role=='decider':
                value=planner_runtime.control_alarm(self.root,actor,self.claims[thread]['claim_id'],str(uuid.uuid4()),args['alarm'])
                self.server.respond(request,value)
            elif name=='edh_act' and role=='decider':
                body=args['response']
                host_contract.validate_response(body)
                claim=self.claims[thread]
                envelope={k:claim[k] for k in ('game','actor','decision_id','pilot_context_id','claim_id')}|body
                submitted=pilot_session.submit_payload(self.root,actor,envelope)
                # Capture this submission's scheduler before pump can continue
                # another seat's approved program and change the last tape row.
                table=body.get('answer',{}).get('snooze_table')
                if 'batch' in body and submitted.get('accepted',0)>0:
                    scheduler=self.rows()[-1].get('auxiliary_payload',{}).get('scheduler',{})
                    table=scheduler if scheduler.get('mode')=='snooze_table' else None
                self.pending[thread]=(request,time.monotonic())
                if table is not None:
                    self.table_waiters.add(thread)
                # Dispatch first, while the outgoing tool remains pending.
                self.pump()
                if thread in self.pending and table is not None:
                    if table.get('wake_condition')=='opponent_action' and self.warm_seconds>0:
                        # Transport residency does not lift a game snooze. Only
                        # the referee's next real own-seat claim can return here.
                        self.metrics['table_warm_holds']=self.metrics.get('table_warm_holds',0)+1
                    else:
                        self.park(thread,'Table snoozed; end this turn.','table_snooze')
            else:raise ValueError('Tool unavailable to this seat role.')
        except (ValueError,SystemExit) as error:
            # Ordinary validation errors can be corrected under the same claim.
            # Any uncertain committed submission stops instead of being retried.
            if name=='edh_act' and self.action().get('decision_id')!=self.claims[thread]['decision_id']:raise
            counts=self.validation_failures.setdefault(self.agent(thread),{})
            category=host_failures.validation_key(str(error))
            counts[category]=counts.get(category,0)+1
            claim_id=(self.claims.get(thread,{}).get('claim_id') if role=='decider' else
                      self.backgrounds.get(thread,{}).get('batch_id'))
            claim_key=(thread,claim_id)
            failures=getattr(self,'claim_failures',{})
            failures[claim_key]=failures.get(claim_key,0)+1
            self.claim_failures={key:count for key,count in failures.items()
                                 if key[0]!=thread or key==claim_key}
            self.metrics['validation_rejections']=self.metrics.get('validation_rejections',0)+1
            if failures[claim_key]>=3 or (category!='other' and counts[category]>=6):
                write(self.directory/'last_failure.json',{'game':self.game,'accepted':len(self.rows()),
                    'actor':actor,'role':role,'code':'repeated_validation_failure','category':category})
                raise RuntimeError('Repeated validation failure; stop instead of spending more inference.') from error
            result={'state':'rejected','error':str(error)}
            if role=='decider':result['ordinary_answer_format']=host_contract.GUIDANCE
            else:
                from . import planner_stages
                if planner_stages.enabled(self.root,self.game):
                    job=self.backgrounds[thread]
                    result['next']=planner_stages.pending_instruction(self.root,self.game,actor,job['batch_id'],job['generation'])
                    result['length_feedback']=planner_stages.length_feedback(args.get('stage'),args.get('response'),plan_tiers.enabled(self.root,self.game))
                    if result['length_feedback']:
                        result['correction']='Rewrite the rejected field(s) substantially shorter, aiming at target_chars. Keep all other fields of this unpublished stage valid. Do not republish an accepted stage.'
                else:result['planner_action_format']=host_contract.PLANNER_GUIDANCE
            from . import communications
            self.server.respond(request,communications.receipt(result,schema_available=True),False)

    def run(self):
        try:
            self.pump()
            while not self.done:
                try:
                    self.handle(self.server.events.get(timeout=.2))
                    if not self.done:self.pump()
                except queue.Empty:self.check_pause()
                self.expire_waiters()
        except (Exception,SystemExit) as error:
            failure=read(self.directory/'last_failure.json',{})
            if failure.get('accepted')!=len(self.rows()) or not failure or failure.get('state')=='recovered':
                write(self.directory/'last_failure.json',{'game':self.game,'accepted':len(self.rows()),
                    'code':'local_host_stop','exception_type':type(error).__name__,
                    'message_sha256':hashlib.sha256(str(error).encode()).hexdigest()})
            raise
        finally:
            # Closing the owned server terminates waiting calls and inference.
            self.server.close()
            for thread in self.contexts.values:self.contexts.save(thread)
            for job in list(self.backgrounds.values()):
                planner_runtime.stopped(self.root,self.game,job['batch_id'],host_status='cancelled')
            write(self.directory/'metrics.json',self.metrics)
            if self.action().get('kind')=='dispatch_pilot':
                if not (self.root/'HOST_PAUSED.json').exists():
                    write(self.root/'HOST_PAUSED.json',{'reason':'host_stopped','accepted':len(self.rows())})
            elif self.action().get('kind') not in {'adjudicate_combo','resolve_horizon_stop'}:
                # App-server thread IDs are useful only while this exact game can
                # still accept pilot decisions.  Keeping them after a lifecycle
                # boundary makes the next fresh game look like an unsafe resume
                # and retains references to contexts that must never be reused.
                sessions=self.directory/'sessions.json'
                if sessions.exists():sessions.unlink()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort',type=Path,required=True)
    parser.add_argument('--codex',default='codex');parser.add_argument('--model')
    parser.add_argument('--decider-model',help='Pilot primary; defaults to gpt-5.6-terra.')
    parser.add_argument('--planner-model',help='Planner primary; defaults to gpt-5.6-sol.')
    parser.add_argument('--warm-seconds',type=float,default=30)
    parser.add_argument('--timing-events',type=int,default=512,help='Bounded metadata retention, 64–4096 events.')
    parser.add_argument('--resume-fenced',action='store_true',
                        help='resume eight verified stopped App Server contexts after explicit route fencing')
    parser.add_argument('--fresh-contexts',action='store_true',
                        help='create new isolated contexts on a retained prefix after rewind invalidation')
    parser.add_argument('--max-decisions',type=int,required=True)
    parser.add_argument('--context-tokens',type=int,default=64000,
                        help='Checkpoint completed seat transcripts at this input-token threshold.')
    args=parser.parse_args(argv)
    if not 0<=args.warm_seconds<=60 or args.max_decisions<1:parser.error('Use 0–60 warm seconds and a positive decision cap.')
    if args.resume_fenced and args.fresh_contexts:parser.error('Choose one recovery mode.')
    if args.context_tokens<16000:parser.error('Context threshold must be at least 16000 tokens.')
    root=args.cohort.resolve()
    # OS-owned lock prevents two software drivers, with no stale lock recovery.
    with locked(root,'host-driver',timeout=0):
        server=AppServer(args.codex)
        try:
            runner=Runner(root,server,model=args.model,decider_model=args.decider_model,
                          planner_model=args.planner_model,warm_seconds=args.warm_seconds,timing_events=args.timing_events,
                          max_decisions=args.max_decisions,resume_fenced=args.resume_fenced,
                          fresh_contexts=args.fresh_contexts,context_tokens=args.context_tokens)
            write(root/'HOST_RUNTIME.json',{'max_decisions':args.max_decisions})
            runner.run()
        except BaseException:
            if server.process.poll() is None:server.close()
            raise


if __name__=='__main__':main()
