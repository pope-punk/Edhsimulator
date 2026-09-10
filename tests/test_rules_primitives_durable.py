"""Durable acknowledgment boundaries, duplicate suppression and crash recovery."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from edh_gauntlet.rules_program import CardProgram,ActivatedProgram,CostSpec,AddMana
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_adapter import AcceptedTransitionError
from edh_gauntlet.rules_durable import DurableRulesAdapter,DurableStoreError,StaleDurableStore


BINDING={'cohort_id':'synthetic-cohort','game_number':1,'branch_id':'original','contract_sha256':'1'*64}

def fixture():
    programs=(CardProgram('rock','Rock',('Artifact',),activated=(ActivatedProgram('mana',CostSpec(tap_source=True),(AddMana(('G',)),),mana_ability=True),)),)
    state=RulesState(('A','B'));ref=state.add_card('rock','rock','A',Zone.BATTLEFIELD);kernel=RulesKernel(state,programs);kernel.open_window_for_scenario('A')
    command={'kind':'activate','revision':kernel.revision,'action_id':'mana','ability_id':'mana','source':ref.to_json(),'targets':[],'x_value':0,'payment':{'mana':{},'taps':[]}}
    return programs,kernel,command


class DurableTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)/'journal.sqlite'
        self.programs,self.kernel,self.command=fixture()
    def create(self,interval=32):
        store=DurableRulesAdapter.create(self.path,self.kernel,binding=BINDING,checkpoint_interval=interval);self.addCleanup(store.close);return store
    def reopen(self):
        store=DurableRulesAdapter.open(self.path,self.programs,binding=BINDING);self.addCleanup(store.close);return store

    def test_commit_reopen_and_duplicate_request_do_not_pay_or_add_mana_again(self):
        store=self.create();reply=store.submit('A','request',self.command);expected=store.archive();store.close()
        restored=self.reopen();duplicate=restored.submit('A','request',self.command)
        self.assertFalse(reply['duplicate']);self.assertTrue(duplicate['duplicate']);self.assertEqual(reply['accepted_revision'],duplicate['accepted_revision'])
        self.assertEqual(expected,restored.archive());self.assertEqual((('G',1),),restored._adapter.kernel.state.mana_pool('A'))

    def test_duplicate_acknowledges_old_revision_but_delivers_current_packet(self):
        second=self.kernel.state.add_card('second','rock','A',Zone.BATTLEFIELD)
        self.command['revision']=self.kernel.revision
        store=self.create();first=store.submit('A','first',self.command)
        another={**self.command,'revision':store._adapter.kernel.revision,'action_id':'second','source':second.to_json()}
        latest=store.submit('A','second',another)
        duplicate=store.submit('A','first',self.command)
        self.assertEqual(first['accepted_revision'],duplicate['accepted_revision'])
        self.assertEqual(latest['packet'],duplicate['packet']);self.assertEqual(2,store.generation)
        self.assertEqual(first['commit'],duplicate['commit']);self.assertNotEqual(latest['commit'],duplicate['commit'])

    def test_production_factory_remains_closed_without_creating_a_file(self):
        with self.assertRaisesRegex(RulesViolation,'not admitted'):DurableRulesAdapter.for_production(self.path,self.kernel)
        self.assertFalse(self.path.exists())

    def test_duplicate_identity_is_bound_to_actor_and_exact_command(self):
        store=self.create();store.submit('A','request',self.command);expected=store.archive()
        with self.assertRaisesRegex(RulesViolation,'different input'):store.submit('B','request',self.command)
        store=self.reopen();self.assertEqual(expected,store.archive())
        changed={**self.command,'action_id':'another'}
        with self.assertRaisesRegex(RulesViolation,'different input'):store.submit('A','request',changed)

    def test_rejected_command_has_no_receipt_or_persisted_mutation(self):
        store=self.create();initial=store.archive()
        with self.assertRaises(RulesViolation):store.submit('A','bad',{**self.command,'revision':'stale'})
        restored=self.reopen();self.assertEqual(initial,restored.archive());self.assertEqual(0,restored.generation)
        restored.submit('A','bad',self.command);self.assertEqual(1,restored.generation)

    def test_checkpoint_bounds_replayed_tail(self):
        store=self.create(interval=2)
        # Repeat distinct mana abilities on separate untapped artifacts.
        store.close();self.path.unlink()
        for i in range(4):self.kernel.state.add_card('rock'+str(i),'rock','A',Zone.BATTLEFIELD)
        store=self.create(interval=2)
        for i in range(5):
            ref=store._adapter.kernel.state.current('rock' if i==0 else 'rock'+str(i-1))
            command={**self.command,'revision':store._adapter.kernel.revision,'action_id':str(i),'source':ref.to_json()}
            store.submit('A',str(i),command)
        expected=store.archive();store.close();restored=self.reopen()
        self.assertEqual(1,restored.replayed_count);self.assertEqual(expected,restored.archive())

    def test_normal_append_does_not_write_a_full_checkpoint(self):
        store=self.create()
        with patch.object(store._adapter.kernel,'snapshot',side_effect=AssertionError('Unexpected whole-history checkpoint')):
            store.submit('A','request',self.command)
        self.assertEqual(1,store.generation)

    def test_second_writer_is_fenced_after_first_advances(self):
        first=self.create();second=self.reopen();first.submit('A','request',self.command)
        with self.assertRaises(StaleDurableStore):second.packet('A')
        with self.assertRaises(StaleDurableStore):second.submit('A','other',self.command)
        self.assertEqual(1,self.reopen().generation)

    def test_error_after_acceptance_commits_failed_checkpoint_without_reexecution(self):
        store=self.create()
        with patch.object(store._adapter.kernel.state,'add_mana',side_effect=RulesViolation('Injected execution failure')):
            with self.assertRaises(AcceptedTransitionError):store.submit('A','request',self.command)
        self.assertEqual('engine_stopped',store.packet('A')['decision']['kind']);store.close()
        # The injected failure is gone; recovery must use the forced checkpoint.
        restored=self.reopen();self.assertEqual(0,restored.replayed_count);self.assertTrue(restored._adapter.failed)
        with self.assertRaises(AcceptedTransitionError):restored.submit('A','request',self.command)
        self.assertEqual(1,self.reopen().generation)

    def test_file_creation_never_overwrites_and_archive_stays_private(self):
        store=self.create();before=self.path.read_bytes()
        with self.assertRaises(FileExistsError):DurableRulesAdapter.create(self.path,self.kernel,binding=BINDING)
        self.assertEqual(before,self.path.read_bytes());self.assertNotIn('records',store.packet('A'))
        if os.name!='nt':self.assertEqual(0o600,self.path.stat().st_mode&0o777)

    def test_corrupt_record_is_rejected(self):
        store=self.create();store.submit('A','request',self.command);store.close()
        with sqlite3.connect(self.path) as db:db.execute("UPDATE commands SET request_id='tampered'")
        with self.assertRaises(DurableStoreError):self.reopen()

    def test_corrupt_checkpoint_is_rejected(self):
        store=self.create();store.close()
        with sqlite3.connect(self.path) as db:db.execute("UPDATE checkpoint SET state='{}'")
        with self.assertRaises(DurableStoreError):self.reopen()

    def crash(self,stage):
        store=self.create();store.close()
        script=r'''
import os,sys
from edh_gauntlet.rules_program import CardProgram,ActivatedProgram,CostSpec,AddMana
from edh_gauntlet.rules_durable import DurableRulesAdapter
programs=(CardProgram('rock','Rock',('Artifact',),activated=(ActivatedProgram('mana',CostSpec(tap_source=True),(AddMana(('G',)),),mana_ability=True),)),)
s=DurableRulesAdapter.open(sys.argv[1],programs,binding={'cohort_id':'synthetic-cohort','game_number':1,'branch_id':'original','contract_sha256':'1'*64})
k=s._adapter.kernel
command={'kind':'activate','revision':k.revision,'action_id':'mana','ability_id':'mana','source':k.state.current('rock').to_json(),'targets':[],'x_value':0,'payment':{'mana':{},'taps':[]}}
original=s.connection
class Connection:
 def __getattr__(self,name):return getattr(original,name)
 def execute(self,sql,*args):
  if sql=='COMMIT' and sys.argv[2]=='before_commit':os._exit(23)
  result=original.execute(sql,*args)
  if sql=='COMMIT':os._exit(24)
  return result
s.connection=Connection()
s.submit('A','request',command)
'''
        result=subprocess.run([sys.executable,'-c',script,str(self.path),stage],capture_output=True,text=True)
        self.assertEqual(23 if stage=='before_commit' else 24,result.returncode,result.stderr)
        return self.reopen()

    def test_process_crash_before_commit_leaves_only_previous_prefix(self):
        restored=self.crash('before_commit');self.assertEqual(0,restored.generation)
        reply=restored.submit('A','request',self.command);self.assertFalse(reply['duplicate']);self.assertEqual((('G',1),),restored._adapter.kernel.state.mana_pool('A'))

    def test_process_crash_after_commit_recovers_receipt_without_second_execution(self):
        restored=self.crash('after_commit');self.assertEqual(1,restored.generation)
        reply=restored.submit('A','request',self.command);self.assertTrue(reply['duplicate']);self.assertEqual((('G',1),),restored._adapter.kernel.state.mana_pool('A'))

    def test_wrong_lifecycle_binding_rejects_before_restoring_engine(self):
        store=self.create();store.close()
        for field,value in (('cohort_id','other-run'),('game_number',2),('branch_id','rewound'),('contract_sha256','2'*64)):
            with patch.object(RulesKernel,'restore',side_effect=AssertionError('Wrong game restored')):
                with self.assertRaisesRegex(DurableStoreError,'binding mismatch'):
                    DurableRulesAdapter.open(self.path,self.programs,binding={**BINDING,field:value})

    def test_invalid_bindings_reject_before_creating_a_file(self):
        for binding in ({}, {**BINDING,'game_number':True}, {**BINDING,'cohort_id':''}, {**BINDING,'contract_sha256':'bad'}, {**BINDING,'extra':1}):
            with self.assertRaises(RulesViolation):DurableRulesAdapter.create(self.path,self.kernel,binding=binding)
            self.assertFalse(self.path.exists())
        supplied=dict(BINDING);store=DurableRulesAdapter.create(self.path,self.kernel,binding=supplied);self.addCleanup(store.close)
        supplied['branch_id']='mutated';store.close();self.reopen()

    def test_retained_receipt_rejects_an_older_valid_backup(self):
        store=self.create();backup=Path(self.temp.name)/'old.sqlite'
        with sqlite3.connect(backup) as destination:store.connection.backup(destination)
        receipt=store.submit('A','request',self.command)['commit'];store.close()
        with self.assertRaisesRegex(DurableStoreError,'required commit receipt'):
            DurableRulesAdapter.open(backup,self.programs,binding=BINDING,minimum_commit=receipt)
        restored=DurableRulesAdapter.open(self.path,self.programs,binding=BINDING,minimum_commit=receipt);self.addCleanup(restored.close)
        self.assertEqual(receipt,restored.committed_head())

    def test_retained_receipt_rejects_a_different_prefix_at_the_same_sequence(self):
        first=self.create();receipt=first.submit('A','request',self.command)['commit']
        other_path=Path(self.temp.name)/'fork.sqlite'
        other=DurableRulesAdapter.create(other_path,self.kernel,binding=BINDING);self.addCleanup(other.close)
        other.submit('A','different-request',{**self.command,'action_id':'other'});other.close()
        with self.assertRaisesRegex(DurableStoreError,'required commit receipt'):
            DurableRulesAdapter.open(other_path,self.programs,binding=BINDING,minimum_commit=receipt)

    def test_retained_ancestor_allows_later_commit_with_lost_reply(self):
        second=self.kernel.state.add_card('second','rock','A',Zone.BATTLEFIELD);self.command['revision']=self.kernel.revision
        store=self.create();genesis=store.committed_head();first=store.submit('A','first',self.command)
        later={**self.command,'revision':store.packet('A')['revision'],'source':second.to_json(),'action_id':'later'}
        last=store.submit('A','later',later);store.close()
        for minimum in (genesis,first['commit']):
            restored=DurableRulesAdapter.open(self.path,self.programs,binding=BINDING,minimum_commit=minimum);self.addCleanup(restored.close)
            reply=restored.submit('A','later',later);self.assertTrue(reply['duplicate']);self.assertEqual(last['commit'],reply['commit']);restored.close()

    def test_invalid_commit_receipts_reject_before_opening_storage(self):
        for receipt in ({}, {'sequence':True,'sha256':'a'*64}, {'sequence':-1,'sha256':'a'*64}, {'sequence':1,'sha256':'bad'}):
            with patch.object(DurableRulesAdapter,'_connect',side_effect=AssertionError('Storage opened')):
                with self.assertRaises(RulesViolation):DurableRulesAdapter.open(self.path,self.programs,binding=BINDING,minimum_commit=receipt)
