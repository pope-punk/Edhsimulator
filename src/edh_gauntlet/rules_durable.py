"""Private durable transport receipts for the experimental primitive adapter.

No model calls or external effects run inside a transaction. A result is returned
only after commit. Reopening restores a checkpoint and deterministically rebuilds
the bounded engine tail; it never redispatches pilot tools or changes game contracts.
"""
import json
import os
from pathlib import Path
import sqlite3
from .rules_adapter import RulesActorAdapter, AcceptedTransitionError, digest
from .rules_kernel import RulesKernel
from .rules_identity import IMPLEMENTATION_ID
from .rules_state import RulesViolation


class DurableStoreError(RulesViolation):
    pass


class StaleDurableStore(DurableStoreError):
    pass


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


def journal_binding(value):
    """Caller-supplied lifecycle identity, never inferred from a file path."""
    if type(value) is not dict or set(value)!={'cohort_id','game_number','branch_id','contract_sha256'}:
        raise RulesViolation('A complete durable game binding is required')
    if any(type(value[k]) is not str or not value[k].strip() or len(value[k])>256 for k in ('cohort_id','branch_id')):
        raise RulesViolation('Invalid durable cohort or branch identity')
    if type(value['game_number']) is not int or value['game_number']<1:
        raise RulesViolation('Invalid durable game number')
    if not hash_value(value['contract_sha256']):raise RulesViolation('Invalid durable contract fingerprint')
    return dict(value)


def hash_value(value):
    return type(value) is str and len(value)==64 and all(c in '0123456789abcdef' for c in value)


def commit_receipt(value):
    if (type(value) is not dict or set(value)!={'sequence','sha256'} or type(value['sequence']) is not int
            or value['sequence']<0 or not hash_value(value['sha256'])):
        raise RulesViolation('Invalid required commit receipt')
    return dict(value)


class DurableRulesAdapter:
    SCHEMA=2

    @classmethod
    def for_production(cls,*args,**kwargs):
        from .rules_admission import require_production_ready
        require_production_ready()

    @staticmethod
    def _connect(path):
        connection=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=rw',uri=True,isolation_level=None,timeout=0)
        try:
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('PRAGMA journal_mode=WAL')
            return connection
        except BaseException:
            connection.close();raise

    @classmethod
    def create(cls,path,kernel,*,binding,checkpoint_interval=32):
        binding=journal_binding(binding)
        if type(checkpoint_interval) is not int or not 1<=checkpoint_interval<=1024:
            raise RulesViolation('Invalid durable checkpoint interval')
        path=Path(path)
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
        connection=cls._connect(path)
        adapter=RulesActorAdapter(kernel)
        header={'schema':cls.SCHEMA,'implementation':IMPLEMENTATION_ID,'checkpoint_interval':checkpoint_interval,'binding':binding,'initial':adapter.initial}
        genesis=digest(header)
        try:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('CREATE TABLE header (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL, sha TEXT NOT NULL)')
            connection.execute('CREATE TABLE head (id INTEGER PRIMARY KEY CHECK(id=1), seq INTEGER NOT NULL, chain TEXT NOT NULL)')
            connection.execute('CREATE TABLE checkpoint (id INTEGER PRIMARY KEY CHECK(id=1), seq INTEGER NOT NULL, state TEXT NOT NULL, sha TEXT NOT NULL)')
            connection.execute('CREATE TABLE commands (seq INTEGER PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, entry TEXT NOT NULL, sha TEXT NOT NULL)')
            connection.execute('INSERT INTO header VALUES (1,?,?)',(encoded(header),genesis))
            connection.execute('INSERT INTO head VALUES (1,0,?)',(genesis,))
            connection.execute('INSERT INTO checkpoint VALUES (1,0,?,?)',(encoded(adapter.initial),digest(adapter.initial)))
            connection.execute('COMMIT')
        finally:
            connection.close()
        return cls.open(path,tuple(kernel.definitions.values()),binding=binding)

    @classmethod
    def open(cls,path,definitions,*,binding,minimum_commit=None):
        binding=journal_binding(binding)
        minimum_commit=commit_receipt(minimum_commit) if minimum_commit is not None else None
        connection=cls._connect(path)
        try:
            connection.execute('BEGIN')
            header_text,genesis=connection.execute('SELECT data,sha FROM header WHERE id=1').fetchone()
            header=json.loads(header_text)
            if digest(header)!=genesis or header.get('schema')!=cls.SCHEMA or header.get('implementation')!=IMPLEMENTATION_ID:
                raise DurableStoreError('Incompatible or corrupt durable header')
            if header.get('binding')!=binding:raise DurableStoreError('Durable game or branch binding mismatch')
            interval=header.get('checkpoint_interval')
            if type(interval) is not int or not 1<=interval<=1024:raise DurableStoreError('Invalid durable checkpoint interval')
            head_seq,head_chain=connection.execute('SELECT seq,chain FROM head WHERE id=1').fetchone()
            checkpoint_seq,state_text,state_sha=connection.execute('SELECT seq,state,sha FROM checkpoint WHERE id=1').fetchone()
            checkpoint=json.loads(state_text)
            if digest(checkpoint)!=state_sha or not 0<=checkpoint_seq<=head_seq:
                raise DurableStoreError('Corrupt durable checkpoint')
            entries=[];chain=genesis;commits=[genesis]
            for seq,request_id,payload,sha in connection.execute('SELECT seq,request_id,entry,sha FROM commands ORDER BY seq'):
                entry=json.loads(payload)
                if (seq!=len(entries)+1 or entry.get('seq')!=seq or entry.get('request_id')!=request_id
                        or entry.get('previous')!=chain or digest(entry)!=sha
                        or entry.get('command_sha256')!=digest({'actor':entry.get('actor'),'command':entry.get('record',{}).get('command')})):
                    raise DurableStoreError('Corrupt durable command chain')
                record=entry['record']
                if record['actor']!=entry['actor'] or record['sha256']!=digest({k:v for k,v in record.items() if k!='sha256'}):
                    raise DurableStoreError('Corrupt adapter record')
                entries.append(entry);chain=sha;commits.append(sha)
            if head_seq-checkpoint_seq>=interval:raise DurableStoreError('Durable replay tail exceeds checkpoint bound')
            if any(entry['record']['error'] for entry in entries[:-1]):raise DurableStoreError('Command follows a stopped prefix')
            if entries and entries[-1]['record']['error'] and checkpoint_seq!=head_seq:raise DurableStoreError('Failure checkpoint is missing')
            if len(entries)!=head_seq or chain!=head_chain:
                raise DurableStoreError('Durable head does not match command prefix')
            if minimum_commit is not None and (minimum_commit['sequence']>=len(commits) or commits[minimum_commit['sequence']]!=minimum_commit['sha256']):
                raise DurableStoreError('Durable prefix does not contain the required commit receipt')
            adapter=RulesActorAdapter(RulesKernel.restore(checkpoint,definitions))
            adapter.initial=header['initial']
            adapter.records=[entry['record'] for entry in entries[:checkpoint_seq]]
            adapter.chain=digest({'implementation':IMPLEMENTATION_ID,'initial':adapter.initial})
            for record in adapter.records:
                if record['previous']!=adapter.chain:raise DurableStoreError('Broken adapter prefix')
                adapter.chain=record['sha256']
            adapter.failed=bool(adapter.records and adapter.records[-1]['error'])
            for entry in entries[checkpoint_seq:]:
                record=entry['record']
                try:adapter.submit(record['actor'],record['command'])
                except AcceptedTransitionError:
                    if not record['error']:raise DurableStoreError('Unexpected recovered execution failure')
                if adapter.records[-1]!=record:raise DurableStoreError('Recovered engine tail diverged')
            if adapter.kernel.revision!=(entries[-1]['record']['after'] if entries else adapter.kernel.revision):
                raise DurableStoreError('Recovered revision differs from committed head')
            connection.execute('COMMIT')
            self=cls.__new__(cls);self.path=Path(path);self.connection=connection;self._adapter=adapter
            self.generation=head_seq;self.chain=head_chain;self.interval=header['checkpoint_interval']
            self.replayed_count=head_seq-checkpoint_seq
            return self
        except BaseException:
            connection.close();raise

    def close(self):
        if self.connection is not None:
            self.connection.close();self.connection=None

    def _current(self):
        if self.connection is None:raise DurableStoreError('Store is closed; reopen before using it')
        row=self.connection.execute('SELECT seq,chain FROM head WHERE id=1').fetchone()
        if row!=(self.generation,self.chain):raise StaleDurableStore('Another writer advanced this store; reopen it')

    def committed_head(self):
        self._current()
        return {'sequence':self.generation,'sha256':self.chain}

    def packet(self,actor):
        self._current()
        return self._adapter.packet(actor)

    def archive(self):
        self._current()
        return self._adapter.archive()

    def submit(self,actor,request_id,command):
        if type(request_id) is not str or not request_id or len(request_id)>128:
            raise RulesViolation('Invalid transport request identity')
        try:command=json.loads(encoded(command))
        except (ValueError,TypeError) as exc:raise RulesViolation('Command must be JSON data') from exc
        if self.connection is None:raise DurableStoreError('Store is closed; reopen before using it')
        command_sha=digest({'actor':actor,'command':command})
        accepted_error=None
        try:
            self.connection.execute('BEGIN IMMEDIATE');self._current()
            existing=self.connection.execute('SELECT entry,sha FROM commands WHERE request_id=?',(request_id,)).fetchone()
            if existing:
                entry=json.loads(existing[0])
                if digest(entry)!=existing[1] or entry.get('request_id')!=request_id:raise DurableStoreError('Corrupt durable receipt')
                if entry['actor']!=actor or entry['command_sha256']!=command_sha:
                    raise RulesViolation('Transport request identity was already used for different input')
                self.connection.execute('COMMIT')
                if entry['record']['error']:raise AcceptedTransitionError('This request committed an execution failure; dispatch remains stopped')
                return {'request_id':request_id,'accepted_revision':entry['record']['after'],'duplicate':True,'commit':{'sequence':entry['seq'],'sha256':existing[1]},'packet':self._adapter.packet(actor)}
            before=len(self._adapter.records)
            try:self._adapter.submit(actor,command)
            except AcceptedTransitionError as exc:
                if len(self._adapter.records)==before:raise
                accepted_error=exc
            record=self._adapter.records[-1]
            entry={'seq':self.generation+1,'request_id':request_id,'actor':actor,'command_sha256':command_sha,'record':record,'previous':self.chain}
            chain=digest(entry)
            self.connection.execute('INSERT INTO commands VALUES (?,?,?,?)',(entry['seq'],request_id,encoded(entry),chain))
            self.connection.execute('UPDATE head SET seq=?,chain=? WHERE id=1',(entry['seq'],chain))
            if accepted_error or entry['seq']%self.interval==0:
                checkpoint=self._adapter.kernel.snapshot()
                self.connection.execute('UPDATE checkpoint SET seq=?,state=?,sha=? WHERE id=1',(entry['seq'],encoded(checkpoint),digest(checkpoint)))
            self.connection.execute('COMMIT')
            self.generation=entry['seq'];self.chain=chain
        except BaseException:
            # A transaction that did not commit must not leave an in-memory head
            # available for further dispatch. Reopen resolves any uncertain commit.
            if self.connection is not None:
                try:
                    if self.connection.in_transaction:self.connection.execute('ROLLBACK')
                finally:self.close()
            raise
        if accepted_error:raise accepted_error
        return {'request_id':request_id,'accepted_revision':record['after'],'duplicate':False,'commit':{'sequence':entry['seq'],'sha256':chain},'packet':self._adapter.packet(actor)}
