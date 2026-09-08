"""Explicit replacement of stopped legacy transports, without replay or inference."""
import hashlib
from pathlib import Path
from . import campaign, pilot_dispatch, pilot_handoff, planner_runtime
from .host_runtime import Runner, persist_transport
from .host_context import compact_knowledge
from .runtime_store import read, write
from .agent_architecture import enabled as split_enabled,roles,registration_key


def preflight(root, server, sessions, *, allow_missing_unused=False):
    directory=root/'host_runtime'
    action=read(root/'NEXT_ACTION.json')['next_action'];game=action['game']
    rows=campaign.read_jsonl(campaign.game_dir(root,game)/'decisions.jsonl')
    records=pilot_dispatch.registry(root,game)
    board=planner_runtime.workboard(root,game)
    if board.get('active'):raise RuntimeError('A planner reservation requires separate reconciliation.')
    expected={(a,r) for a in campaign.PILOT_GAMEPLAN_FILES for r in roles(root,game)}
    keys={(s['actor'],s['role']) for s in sessions}
    complete=keys<=expected and {(a,'decider') for a in campaign.PILOT_GAMEPLAN_FILES}<=keys if split_enabled(root,game) else keys==expected
    if len(keys)!=len(sessions) or not complete:
        raise RuntimeError('Recovery requires eight distinct registered seat roles.')
    values={}
    for row in sessions:
        actor,role,thread=row['actor'],row['role'],row['thread']
        agent=row.get('agent','/app-server/'+thread)
        record=(records if role=='decider' else board['planners']).get(actor if role=='decider' else registration_key(actor,role),{})
        value=read(directory/'context'/f'{pilot_handoff.seat_slug(actor)}_{role}.json',{})
        if (record.get('agent')!=agent or value.get('thread')!=thread or
                value.get('checkpoint_pending') or value.get('replacement_thread') or
                not pilot_handoff.can_resume_session(value.get('seat_session'),root,game,actor,rows)):
            raise RuntimeError('Recovery identity, branch or replacement intent is ambiguous.')
        if role=='decider' and not pilot_handoff.can_resume_session(record.get('seat_session'),root,game,actor,rows):
            raise RuntimeError('Registered pilot branch is incompatible.')
        try:metadata=server.call('thread/read',{'threadId':thread,'includeTurns':False})['thread']
        except RuntimeError as error:
            if (not allow_missing_unused or 'thread not loaded: '+thread not in str(error) or
                    value.get('transport_version')!=2 or value.get('turns')!=0 or value.get('delivered_chars')!=0):raise
            # The historical replacement journal proves this unused transport
            # came from an explicit completed recovery, not an adopted context.
            journals=[read(path,{}) for path in directory.glob(f'transport_recovery_{game}_*.json')]
            if not any(j.get('state')=='complete' and any(r.get('new')==thread and r.get('agent')==agent
                       for r in j.get('replacements',[])) for j in journals):raise
            value['_missing_transport']=True;metadata=None
        if metadata and (metadata.get('status',{}).get('type')!='notLoaded' or Path(metadata['cwd']).resolve()!=directory):
            raise RuntimeError('All original transports must be stopped and unloaded in this workspace.')
        values[thread]={**value,'agent':agent}
    return values


def restore_unused(root,server,sessions):
    """Explicitly repair only journaled transports that never received input."""
    from .host_context import Contexts
    from .host_routing import Routing
    runner=Runner.__new__(Runner);runner.root=root;runner.directory=root/'host_runtime';runner.server=server
    runner.game=read(root/'NEXT_ACTION.json')['next_action']['game'];runner.model=None;runner.routing=Routing()
    runner.contexts=Contexts(runner);values=preflight(root,server,sessions,allow_missing_unused=True)
    tape=campaign.game_dir(root,runner.game)/'decisions.jsonl';prefix=tape.read_bytes()
    path=runner.directory/f'unused_transport_recovery_{runner.game}_{len(runner.rows())}.json'
    if path.exists():raise RuntimeError('Unused transport recovery already attempted; reconcile its journal.')
    audit={'state':'replacing','inference_turns':0,'replacements':[],'prefix_sha256':hashlib.sha256(prefix).hexdigest()}
    write(path,audit)
    for row in sessions:
        value=values[row['thread']]
        if not value.pop('_missing_transport',False):continue
        old=row['thread'];params=runner.context_parameters(row['actor'],row['role'])
        params['model']=value['model']
        if value.get('reasoning_effort'):params['config']={'model_reasoning_effort':value['reasoning_effort']}
        result=server.call('thread/start',params);fresh=result['thread']['id']
        audit['replacements'].append({'old':old,'new':fresh,'actor':row['actor'],'role':row['role'],'agent':value['agent']})
        write(path,audit)
        if fresh in values or result.get('model')!=value['model']:raise RuntimeError('Unused replacement model/identity mismatch.')
        persist_transport(server,fresh)
        value['thread']=fresh;row.update(thread=fresh,agent=value['agent'])
        runner.contexts.values[fresh]=value;runner.contexts.save(fresh)
    if tape.read_bytes()!=prefix:raise RuntimeError('Unused recovery changed the accepted prefix.')
    write(runner.directory/'sessions.json',sessions);audit['state']='complete';write(path,audit)
    return sessions


def preview(root,server,sessions):
    """Read-only reconciliation, reporting sizes rather than private seat prose."""
    from .host_context import Contexts, chars, checkpoint_knowledge, bounded_knowledge
    runner=Runner.__new__(Runner)
    runner.root=root;runner.directory=root/'host_runtime';runner.server=server
    runner.game=read(root/'NEXT_ACTION.json')['next_action']['game']
    runner.active=set();runner.pending={};runner.contexts=Contexts(runner)
    runner.contexts.values=preflight(root,server,sessions)
    report=[]
    for thread,value in runner.contexts.values.items():
        value['knowledge']=bounded_knowledge(value.get('knowledge',{}))
        retained=runner.contexts.retained(thread,recovery=True)
        report.append({'actor':value['actor'],'role':value['role'],
                       'continuity_chars':chars(retained),'knowledge_chars':chars(checkpoint_knowledge(value['knowledge']))})
    return report


class ReplacementRunner(Runner):
    """Caller must preflight, journal authorization and fence the stopped route."""
    def resume_contexts(self):
        audit_path=self.directory/f'transport_recovery_{self.game}_{len(self.rows())}.json'
        audit=read(audit_path,{})
        if audit.get('state')!='fenced' or not audit.get('user_authorized'):
            raise RuntimeError('Explicit authorized recovery journal required.')
        values=preflight(self.root,self.server,self.resume_sessions)
        # Build every private retained packet before the first transport mutation.
        for row in self.resume_sessions:
            thread=row['thread'];self.contexts.values[thread]=values[thread]
            from .host_context import bounded_knowledge
            values[thread]['knowledge']=bounded_knowledge(values[thread].get('knowledge',{}))
            values[thread]['retained']=self.contexts.retained(thread,recovery=True)
        audit['state']='replacing';audit['replacements']=[];write(audit_path,audit)
        for row in self.resume_sessions:
            old=row['thread'];actor,role=row['actor'],row['role'];value=values[old]
            params=self.context_parameters(actor,role)
            if value.get('reasoning_effort'):params['config']={'model_reasoning_effort':value['reasoning_effort']}
            result=self.server.call('thread/start',params);fresh=result['thread']['id']
            audit['replacements'].append({'actor':actor,'role':role,'old':old,'new':fresh,'agent':value['agent'],
                                          'model':result.get('model')})
            write(audit_path,audit)
            if result.get('model')!=params['model'] or fresh in values or fresh in self.threads:
                raise RuntimeError('Replacement model or transport identity is inconsistent.')
            persist_transport(self.server,fresh)
            self.server.call('thread/archive',{'threadId':old})
            value.update(thread=fresh,transport_version=2,turns=0,delivered_chars=0,
                         checkpoints=value.get('checkpoints',0)+1,checkpoint_pending=False,
                         baseline_required=role=='decider',memory_delivery_pending=True,verify_baseline=True,baseline_input_tokens=None,
                         model=result['model'],reasoning_effort=result.get('reasoningEffort'),
                         model_provider=result.get('modelProvider',result['thread'].get('modelProvider')))
            self.contexts.values.pop(old);self.contexts.values[fresh]=value
            self.seats[(actor,role)]=fresh;self.threads[fresh]=(actor,role)
            if role=='decider':self.contexts.baselines.add(fresh)
            self.first_delivery.add(fresh);self.contexts.save(fresh)
        if (campaign.game_dir(self.root,self.game)/'decisions.jsonl').read_bytes()!=self.resume_prefix:
            raise RuntimeError('Accepted prefix changed during transport replacement.')
        self.save_sessions()
        audit.update(state='complete',prefix_sha256=hashlib.sha256(self.resume_prefix).hexdigest(),
                     inference_turns=0,policy=self.routing.policy())
        write(audit_path,audit)
        (self.root/'HOST_PAUSED.json').unlink()
