"""Primitive campaign persistence and lifecycle; never chooses for a pilot.

A prepared host input survives any uncertain rules commit. Recovery resubmits its
same durable request ID; an acknowledged command returns its receipt without
executing again. Host projections finish before another role can be admitted.
"""
from copy import deepcopy
from contextlib import contextmanager
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid
import zlib
from .paths import PROJECT_ROOT
from .runtime_store import write, read, locked
from .rules_adapter import AcceptedTransitionError, digest
from .rules_actor import decision_for_actor
from .rules_bundle import load_reviewed
from .rules_durable import DurableRulesAdapter, encoded
from .rules_identity import IMPLEMENTATION_ID
from .rules_setup import fresh_pod
from .rules_state import RulesViolation

ROLES = ('decider', 'short_term_planner', 'long_term_planner', 'diplomacy')
CONFIG_FILES = ('data/catalog/cards.json', 'data/rules/primitive_cards.json',
                'data/decks/pod_decklists.json', 'data/decks/pod_configuration.json')



def host_implementation():
    """Bind the host and shared transport code, independently of kernel identity."""
    package=Path(__file__).parent
    files=sorted(set(package.glob('primitive_*.py')) | {
        package/name for name in ('host_runtime.py','host_routing.py','host_failures.py',
        'host_telemetry.py','communications.py','agent_architecture.py','scheduler.py')})
    return digest({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files})


def frozen_strategy(root):
    catalog=json.loads((root/'data/strategy/standing_plans/catalog.json').read_text(encoding='utf-8'))['pilots']
    return {actor:{key:(root/'data/strategy'/directory/row['file']).read_text(encoding='utf-8')
                   for key,directory in (('standing','standing_plans'),('seed','gameplan_seeds'),
                                         ('personality','messaging_personalities'))}
            for actor,row in catalog.items()}


def configuration(root, *, seed, starting_player, max_rounds):
    if type(max_rounds) is not int or max_rounds < 1:
        raise RulesViolation('Use a positive round horizon')
    return {'schema': 1, 'rules_engine': 'primitives-v1', 'implementation': IMPLEMENTATION_ID,
            'host_implementation':host_implementation(),'strategy_sha256':digest(frozen_strategy(root)),
            'seed': seed, 'starting_player': starting_player, 'max_rounds': max_rounds,
            'learning_enabled': False, 'planning_contract': 4, 'agent_architecture': 1,
            'short_term_sol_fast': 1, 'async_diplomacy': 1, 'decision_roles': 1,
            'static_standing': 1, 'planner_stages': True, 'plan_tiers': True,
            'context_handling': 1, 'turn_batches': 1, 'primitive_surface': 1,
            'coordination_document': 1, 'pilot_document': 1, 'mana_only_priority': 1, 'combat_stage_batches': 1, 'autotap': 1, 'automatic_decider_mana': 1, 'strategic_review': 1,
            'assets': {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in CONFIG_FILES}}


class PrimitiveCampaign:
    @classmethod
    def create(cls, path, *, seed, starting_player, max_rounds=16, games=1, root=PROJECT_ROOT):
        from .rules_admission import require_production_ready
        require_production_ready(root,scope='host')
        return cls._create(path, seed=seed, starting_player=starting_player, max_rounds=max_rounds, games=games, root=root)

    @classmethod
    def _create(cls, path, *, seed, starting_player, max_rounds=16, games=1, root=PROJECT_ROOT):
        """Internal construction also used by offline conformance, below admission."""
        path=Path(path).resolve();root=Path(root)
        if type(games) is not int or not 1 <= games <= 1000:
            raise RulesViolation('Use 1–1000 games')
        config=configuration(root, seed=seed, starting_player=starting_player, max_rounds=max_rounds)
        from .primitive_reports import deck_rows
        config['campaign']={'target_games':games,'seed_start':seed,'starting_player':starting_player,
                            'max_rounds':max_rounds,'deck_sha256':digest(deck_rows(root))}
        kernel=fresh_pod(seed=seed, starting_player=starting_player, root=root)
        # No existing directory, even an empty one, is adopted or overwritten.
        path.mkdir(mode=0o700, parents=True, exist_ok=False)
        binding={'cohort_id':str(uuid.uuid4()),'game_number':1,'branch_id':str(uuid.uuid4()),
                 'contract_sha256':digest(config)}
        write(path/'deck_snapshot.json',deck_rows(root))
        write(path/'cohort.json',{'schema':2,'rules_engine':'primitives-v1','binding':binding,
                                 'active_game':1,'target_games':games,'learning_enabled':False,
                                 'seed_start':seed,'starting_player':starting_player,'max_rounds':max_rounds})
        return cls._initialize(path,root,config,kernel,binding)

    @classmethod
    def _initialize(cls,path,root,config,kernel,binding,*,directory=None,publish=True):
        directory=directory or path/f"game_{binding['game_number']:02d}"
        directory.mkdir(mode=0o700)
        write(directory/'game_config.json',config)
        store=DurableRulesAdapter.create(directory/'rules.sqlite',kernel,binding=binding)
        try:
            connection=store.connection
            connection.executescript('''
                CREATE TABLE host_state (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
                CREATE TABLE host_inputs (request_id TEXT PRIMARY KEY, actor TEXT NOT NULL,
                                         payload TEXT NOT NULL, state TEXT NOT NULL, receipt TEXT);
                CREATE TABLE host_publications (id TEXT PRIMARY KEY, actor TEXT NOT NULL, role TEXT NOT NULL, input_sha TEXT NOT NULL, receipt TEXT NOT NULL);
                CREATE TABLE host_messages (id TEXT PRIMARY KEY, actor TEXT NOT NULL, text TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(actor,text));
                CREATE TABLE host_evidence (seq INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL,
                                            kind TEXT NOT NULL, rules_seq INTEGER NOT NULL, payload BLOB NOT NULL);
                CREATE INDEX host_evidence_actor_seq ON host_evidence(actor,seq);
                CREATE INDEX host_evidence_actor_kind_seq ON host_evidence(actor,kind,seq);
            ''')
            strategy=frozen_strategy(root)
            actors={actor:{**strategy[actor],
                    'plans':{},'jobs':{},'approved':None,'snooze':None,'kept':False,
                    'evidence_cursor':{},'boundaries':{},'next_job':0}
                    for actor in kernel.state.players}
            state={'schema':1,'pending':None,'paused':None,'blocker':None,'terminal':None,
                   'actors':actors,'messages':[],'claim':None,'last_rules_commit':store.committed_head(),
                   'last_turn':None,'registrations':{},'transport_generation':0}
            connection.execute('INSERT INTO host_state VALUES (1,?)',(encoded(state),))
            from .primitive_journal import initialize
            initialize(connection,binding,store.committed_head(),state)
            self=cls.__new__(cls);self.root=path;self.assets=root;self.config=config;self.binding=binding;self.store=store
            self.directory=directory
            with self.transaction() as state:
                self._capture(state,initial=True)
            if publish:self.publish_next()
            return self
        except BaseException:
            store.close();raise

    @classmethod
    def open(cls,path,*,root=PROJECT_ROOT,recover=True,telemetry_repair=None,scheduler_upgrade=None,payment_repair=None):
        path=Path(path).resolve();root=Path(root)
        manifest=read(path/'cohort.json',{})
        if manifest.get('rules_engine')!='primitives-v1':raise RulesViolation('Not a primitive campaign; never adopt a legacy run')
        if manifest.get('active_game')!=manifest.get('binding',{}).get('game_number'):
            raise RulesViolation('Active game does not match its binding')
        directory=path/f"game_{manifest['active_game']:02d}"
        config=read(directory/'game_config.json',{})
        if digest(config)!=manifest['binding']['contract_sha256'] or config.get('implementation')!=IMPLEMENTATION_ID:
            raise RulesViolation('Campaign contract or rules implementation changed; use its historical checkout')
        if config.get('campaign'):
            if (any(manifest.get(key)!=value for key,value in config['campaign'].items() if key!='deck_sha256') or
                digest(read(path/'deck_snapshot.json',[]))!=config['campaign']['deck_sha256']):
                raise RulesViolation('Frozen campaign schedule or report deck changed')
        elif manifest.get('target_games',1)!=1:
            raise RulesViolation('Historical single-game contracts cannot become multi-game campaigns')
        if any(hashlib.sha256((root/name).read_bytes()).hexdigest()!=value for name,value in config['assets'].items()):
            raise RulesViolation('Bound primitive assets changed')
        self=cls.__new__(cls);self.root=path;self.assets=root;self.config=config;self.binding=manifest['binding'];self.directory=directory
        if telemetry_repair is not None and (recover or config.get('host_implementation')==host_implementation()):
            raise RulesViolation('Telemetry repair candidates are only for stopped installation without recovery')
        payment_upgrade=None
        if payment_repair is not None or (path/'host_runtime/payment_repair.json').exists():
            from .primitive_payment_repair import validate
            if payment_repair is not None and (recover or telemetry_repair is not None or scheduler_upgrade is not None):
                raise RulesViolation('Payment repair requires stopped installation without other upgrades')
            payment_upgrade=payment_repair if payment_repair is not None else read(path/'host_runtime/payment_repair.json',{})
            validate(payment_upgrade,self.binding,config,root)
        upgrade = None
        if scheduler_upgrade is not None and (recover or telemetry_repair is not None or config.get('host_implementation')==host_implementation()):
            raise RulesViolation('Scheduler upgrades require stopped installation without recovery')
        if scheduler_upgrade is not None or (path/'host_runtime/scheduler_upgrade.json').exists():
            from .primitive_scheduler_upgrade import validate
            upgrade=scheduler_upgrade if scheduler_upgrade is not None else read(path/'host_runtime/scheduler_upgrade.json',{})
            validate(upgrade,self.binding,config,root)
        repair = None
        if upgrade is None and payment_upgrade is None and config.get('host_implementation')!=host_implementation():
            from .primitive_telemetry_repair import validate
            repair = telemetry_repair if telemetry_repair is not None else read(path/'host_runtime/telemetry_repair.json', {})
            validate(repair, self.binding, config, root)
        self._reopen()
        try:
            from .primitive_journal import verify
            verify(self.store.connection,self.binding)
            if payment_upgrade is not None:
                from .primitive_payment_repair import verify_prefix
                verify_prefix(self,payment_upgrade,candidate=payment_repair is not None)
            if upgrade is not None:
                from .primitive_scheduler_upgrade import verify_prefix
                verify_prefix(self,upgrade,candidate=scheduler_upgrade is not None)
            if repair is not None:
                from .primitive_telemetry_repair import verify_prefix
                verify_prefix(self, repair, candidate=telemetry_repair is not None)
            strategy={actor:{key:seat[key] for key in ('standing','seed','personality')}
                      for actor,seat in self.state()['actors'].items()}
            if digest(strategy)!=config['strategy_sha256']:
                raise RulesViolation('Frozen strategy does not match the campaign contract')
            if recover:self.recover()
        except BaseException:
            self.close();raise
        return self

    def _reopen(self):
        definitions=tuple(row['program'] for row in load_reviewed(self.assets).values())
        self.store=DurableRulesAdapter.open(self.directory/'rules.sqlite',definitions,binding=self.binding)

    @property
    def kernel(self):return self.store._adapter.kernel

    def close(self):self.store.close()

    def state(self):
        self.store._current()
        return json.loads(self.store.connection.execute('SELECT value FROM host_state WHERE id=1').fetchone()[0])

    @contextmanager
    def transaction(self):
        connection=self.store.connection
        from .primitive_journal import capture,delta,append
        rows=capture(connection)
        connection.execute('BEGIN IMMEDIATE')
        try:
            state=self.state()
            before=deepcopy(state)
            yield state
            connection.execute('UPDATE host_state SET value=? WHERE id=1',(encoded(state),))
            changes=delta(before,state)
            if changes or rows:append(connection,self.binding,self.store.committed_head(),changes,rows)
            connection.execute('COMMIT')
        except BaseException:
            if connection.in_transaction:connection.execute('ROLLBACK')
            raise
        finally:connection.create_function('edh_capture',-1,None)

    def evidence(self,actor,*,after=0,through=None,limit=None,kinds=None):
        if actor not in self.kernel.state.players:raise RulesViolation('Unknown actor')
        query='SELECT seq,kind,rules_seq,payload FROM host_evidence WHERE actor=? AND seq>?'
        args=[actor,after]
        if through is not None:query+=' AND seq<=?';args.append(through)
        if kinds is not None:
            if not kinds or any(type(kind) is not str for kind in kinds):raise RulesViolation('Invalid evidence kinds')
            query+=' AND kind IN ('+','.join('?' for _ in kinds)+')';args.extend(kinds)
        query+=' ORDER BY seq'
        if limit is not None:
            if type(limit) is not int or limit<1:raise RulesViolation('Invalid evidence page size')
            query+=' LIMIT ?';args.append(limit)
        return [{'id':seq,'kind':kind,'rules_sequence':rules_seq,'value':json.loads(zlib.decompress(payload))}
                for seq,kind,rules_seq,payload in self.store.connection.execute(query,args)]

    def evidence_position(self,actor):
        return self.store.connection.execute('SELECT COALESCE(MAX(seq),0) FROM host_evidence WHERE actor=?',(actor,)).fetchone()[0]

    def record(self,actor,kind,value):
        self.store.connection.execute('INSERT INTO host_evidence(actor,kind,rules_seq,payload) VALUES (?,?,?,?)',
            (actor,kind,self.store.generation,zlib.compress(encoded(value).encode(),level=1)))

    def _capture(self,state,*,initial=False):
        # Every actor gets its own lossless observation. Compression keeps full
        # evidence cheap without permitting a private engine checkpoint in egress.
        for actor in self.kernel.state.players:
            self.record(actor,'observation',self.store.packet(actor))
        from .primitive_reports import capture_statistics
        capture_statistics(self,state)
        state['last_rules_commit']=self.store.committed_head()
        from .primitive_planning import observe
        observe(self,state)
        from .primitive_scheduling import observe as observe_alarms
        observe_alarms(self,state)
        if self.kernel.outcome is not None and not state['terminal']:
            state['terminal']={'kind':self.kernel.outcome['kind'],'winners':self.kernel.outcome['winners'],
                'rules_commit':self.store.committed_head(),'contract_sha256':self.binding['contract_sha256'],
                'learning':'skipped_by_configuration'}
        if self.store._adapter.failed and not state['blocker']:
            state['blocker']={'kind':'accepted_execution_failure','rules_commit':self.store.committed_head()}
            state['terminal']={'kind':'draw','winners':[],'tag':'rules_review',
                'rules_commit':self.store.committed_head(),'contract_sha256':self.binding['contract_sha256'],
                'learning':'skipped_by_configuration'}

    def next_action(self):
        state=self.state();number=self.binding['game_number']
        base={'game':number,'rules_engine':'primitives-v1','commit':self.store.committed_head()}
        if state.get('help_request') and (not state['paused'] or state['paused']['reason']=='pilot_help_requested'):
            request=state['help_request']
            return {**base,'kind':'await_pilot_help','actor':request['actor'],'request_id':request['id']}
        combo=state.get('combo')
        if combo and (not state['paused'] or state['paused'].get('reason')=='combo_adjudication'):
            if combo['remaining']:return {**base,'kind':'dispatch_pilot','actor':combo['remaining'][0],'decision_kind':'combo_consent','revision':self.kernel.revision}
            return {**base,'kind':'adjudicate_combo','request_path':str(self.directory/'combo_request.json'),'proposal_id':combo['request']['proposal_id']}
        if state['paused']:return {**base,'kind':'none','reason':'host_paused'}
        if state['pending']:return {**base,'kind':'recover_host_input'}
        if state['blocker']:return {**base,'kind':'repair_rules_work_items','terminal':state['terminal']}
        if state['terminal']:
            if number<read(self.root/'cohort.json',{}).get('target_games',1):
                return {**base,'kind':'advance_game','game':number+1,'completed_game':number,'terminal':state['terminal']}
            return {**base,'kind':'none','reason':'cohort_complete','terminal':state['terminal']}
        horizon=state.get('round_horizon',self.config['max_rounds'])
        if self.kernel.state.turn_number>horizon*len(self.kernel.state.players):
            return {**base,'kind':'resolve_horizon_stop','max_rounds':horizon}
        for actor in self.kernel.state.live_players:
            decision=decision_for_actor(self.kernel,actor)
            if decision['kind'] not in {'waiting','finished','engine_pending'}:
                return {**base,'kind':'dispatch_pilot','actor':actor,'decision_kind':decision['kind'],'revision':self.kernel.revision}
        return {**base,'kind':'fix_release_blocker','reason':'kernel_has_no_actor_boundary'}

    def publish_next(self):
        action=self.next_action()
        write(self.root/'NEXT_ACTION.json',{'schema':1,'next_action':action})
        if action['kind']=='adjudicate_combo':write(self.directory/'combo_request.json',self.state()['combo']['request'])
        seal=self.state()['terminal']
        if seal:
            from .primitive_journal import head
            seal={**seal,'host_commit':head(self.store.connection)}
            write(self.directory/'terminal_result.json',seal)
            write(self.directory/'postgame_learning/skipped.json',
                  {'status':'skipped_by_configuration','terminal_sha256':digest(seal),'rules_commit':seal['rules_commit']})
        return action

    def prepare(self,actor,request_id,command,*,rationale,plan_refs=None,control=None):
        if type(request_id) is not str or not request_id or len(request_id)>128:raise RulesViolation('Invalid host request ID')
        no_pass_rationale=type(command) is dict and command.get('kind')=='pass' and rationale is None
        if not no_pass_rationale and (type(rationale) is not str or not rationale.strip() or len(rationale)>2400):
            raise RulesViolation('A bounded pilot-authored rationale is required for non-pass actions')
        payload={'command':command,'rationale':rationale,'plan_refs':plan_refs or {},'control':control}
        with self.transaction() as state:
            existing=self.store.connection.execute('SELECT actor,payload,state,receipt FROM host_inputs WHERE request_id=?',(request_id,)).fetchone()
            if existing:
                if existing[:2]!=(actor,encoded(payload)):raise RulesViolation('Host request ID reused with different content')
                return existing[2]
            action=self.next_action()
            combo=state.get('combo',{})
            admin=(action['kind']=='adjudicate_combo' and command.get('kind')=='adjudicated_combo' and combo.get('response')==command.get('response') and actor==combo['request']['actor'])
            if not admin and (action['kind']!='dispatch_pilot' or action['actor']!=actor):raise RulesViolation('Actor does not own the campaign frontier')
            if state['pending']:raise RulesViolation('Recover the prepared input first')
            self.store.connection.execute('INSERT INTO host_inputs VALUES (?,?,?,?,NULL)',(request_id,actor,encoded(payload),'prepared'))
            state['pending']=request_id
        return 'prepared'

    def submit(self,actor,request_id,command,*,rationale,plan_refs=None,control=None):
        status=self.prepare(actor,request_id,command,rationale=rationale,plan_refs=plan_refs,control=control)
        if status=='rejected':raise RulesViolation('This host request was rejected; correct it using a new ID')
        if status=='prepared':self.recover()
        row=self.store.connection.execute('SELECT receipt FROM host_inputs WHERE request_id=?',(request_id,)).fetchone()
        return json.loads(row[0])

    def recover(self):
        state=self.state();pending=state['pending']
        if not pending:return self.publish_next()
        if state['paused'] and not state.get('combo',{}).get('response') and not self.store.connection.execute('SELECT 1 FROM commands WHERE request_id=?',(pending,)).fetchone():
            return self.publish_next()
        actor,payload_text,status=self.store.connection.execute('SELECT actor,payload,state FROM host_inputs WHERE request_id=?',(pending,)).fetchone()
        if status!='prepared':raise RulesViolation('Inconsistent prepared host input')
        payload=json.loads(payload_text);error=None
        try:
            receipt=self.store.submit(actor,pending,payload['command'])
        except AcceptedTransitionError:
            # Durable failure receipts are retained; sealing never rolls back.
            if self.store.connection is None:self._reopen()
            receipt={'request_id':pending,'commit':self.store.committed_head(),'accepted_failure':True}
        except RulesViolation as exc:
            if self.store.connection is None:self._reopen()
            receipt={'request_id':pending,'rejected':True,'reason':str(exc)};error=exc
        try:
            with self.transaction() as state:
                if state['pending']!=pending:raise RulesViolation('Prepared input changed during recovery')
                if not error:
                    from .primitive_actions import apply_control,observe
                    apply_control(self,state,actor,payload.get('control'))
                    observe(self,state,actor,payload['command'])
                    state['actors'][actor].pop('last_rejection',None)
                    state['actors'][actor].pop('last_rejection_context',None)
                    self.record(actor,'rationale',{'request_id':pending,**payload})
                    self._capture(state)
                self.store.connection.execute('UPDATE host_inputs SET state=?,receipt=? WHERE request_id=?',
                    ('rejected' if error else 'accepted',encoded({k:v for k,v in receipt.items() if k!='packet'}),pending))
                state['pending']=None
                # A rejected command leaves the frozen decision and its owner intact.
                # Only acceptance releases it and permits queued public delivery.
                if not error:state['claim']=None
                from .primitive_diplomacy import flush_state
                flush_state(self,state)
        except BaseException as exc:
            if not error:
                raise AcceptedTransitionError('Rules command committed; reconcile the exact pending host receipt before dispatch') from exc
            raise
        self.publish_next()
        if error:raise error
        return receipt

    def pause(self,reason):
        with self.transaction() as state:state['paused']={'reason':str(reason)[:300],'commit':self.store.committed_head()}
        return self.publish_next()

    def rules_blocker(self,actor,reason):
        """Seal the exact accepted prefix without inventing another game action."""
        if actor not in self.kernel.state.players:
            raise RulesViolation('Unknown reporting actor')
        if type(reason) is not str or not reason.strip() or len(reason)>1200:
            raise RulesViolation('A bounded rules issue explanation is required')
        with self.transaction() as state:
            if state['pending']:
                raise RulesViolation('Reconcile the pending receipt before sealing the prefix')
            if state['terminal']:
                raise RulesViolation('The game is already sealed')
            head=self.store.committed_head()
            state['blocker']={'kind':'reported_rules_issue','actor':actor,
                              'reason':reason,'rules_commit':head}
            state['terminal']={'kind':'draw','winners':[],'tag':'rules_review',
                'rules_commit':head,'contract_sha256':self.binding['contract_sha256'],
                'learning':'skipped_by_configuration'}
            state['claim']=None
            for seat in state['actors'].values():
                seat['approved']=None;seat['snooze']=None
            self.record(actor,'rules_issue',state['blocker'])
        return self.publish_next()
