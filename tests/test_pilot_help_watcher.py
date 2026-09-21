"""Notification-only watcher: duplicate suppression and explicit stop boundaries."""
import importlib.util,json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
spec=importlib.util.spec_from_file_location('help_watcher',Path(__file__).resolve().parents[1]/'tools/watch_pilot_help.py')
watcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(watcher)


class WatcherTests(TestCase):
    def setUp(self):
        root=Path(self.enterContext(TemporaryDirectory()));self.runs=root/'runs';self.run=self.runs/'fixture';self.run.mkdir(parents=True)
        self.directory=root/'watcher';self.directory.mkdir();self.calls=[]
        self.action={'kind':'await_pilot_help','actor':'Omo','game':1,'request_id':'help-1','commit':{'sequence':4,'sha256':'fixture'}}
        self.publish()
    def publish(self): (self.run/'NEXT_ACTION.json').write_text(json.dumps({'next_action':self.action}))
    def send(self,args,**kwargs):self.calls.append(args);return SimpleNamespace(returncode=0,stdout='Queued fixture',stderr='')
    def tick(self,send=None):return watcher.tick(self.runs,self.directory,'thread-fixture',send or self.send)
    def test_one_notification_per_request_and_new_request_notifies(self):
        self.assertEqual('queued',self.tick()[0]['state']);self.assertEqual([],self.tick())
        self.action['request_id']='help-2';self.publish();self.assertEqual(1,len(self.tick()));self.assertEqual(2,len(self.calls))
        self.assertEqual(['codex','queue','--thread','thread-fixture'],self.calls[0][:4])
        self.assertIn('Never choose gameplay actions',self.calls[0][-1])
    def test_user_pause_stop_and_nonhelp_do_not_notify(self):
        (self.run/'HOST_PAUSED.json').write_text('{}');self.assertEqual([],self.tick())
        (self.run/'HOST_PAUSED.json').unlink();(self.directory/'STOP').touch();self.assertEqual([],self.tick())
        (self.directory/'STOP').unlink();self.action['kind']='dispatch_pilot';self.publish();self.assertEqual([],self.tick());self.assertFalse(self.calls)
    def test_uncertain_delivery_is_not_replayed(self):
        def fail(*args,**kwargs):raise TimeoutError('Unknown queue outcome')
        self.assertEqual('uncertain',self.tick(fail)[0]['state']);self.assertEqual([],self.tick());self.assertFalse(self.calls)

    def test_support_runs_separate_exec_once_and_verifies_resolution(self):
        from unittest.mock import patch
        with patch.object(watcher,'support_resolved',return_value=True):
            result=watcher.tick(self.runs,self.directory,'thread-fixture',self.send,mode='support')
        self.assertEqual('support_finished',result[0]['state'])
        self.assertTrue(self.calls[0][1].endswith('run_pilot_help.py'))
        self.assertNotIn('codex', self.calls[0])
        self.assertEqual([],watcher.tick(self.runs,self.directory,'thread-fixture',self.send,mode='support'))
        self.assertEqual(1,len(self.calls))

    def test_support_unresolved_exit_escalates_once_without_retry(self):
        from unittest.mock import patch
        with patch.object(watcher,'support_resolved',return_value=False):
            result=watcher.tick(self.runs,self.directory,'thread-fixture',self.send,mode='support')
        self.assertEqual('uncertain',result[0]['state'])
        self.assertTrue(self.calls[0][1].endswith('run_pilot_help.py'))
        self.assertEqual(['codex','queue'],self.calls[1][:2])
        self.assertEqual([],watcher.tick(self.runs,self.directory,'thread-fixture',self.send,mode='support'))
        self.assertEqual(2,len(self.calls))

    def test_support_checks_durable_state_not_exit_text(self):
        import sqlite3
        game=self.run/'game_01';game.mkdir()
        c=sqlite3.connect(game/'rules.sqlite');c.execute('create table host_state(value text)')
        def state(value):
            c.execute('delete from host_state');c.execute('insert into host_state values (?)',(json.dumps(value),));c.commit()
        state({'help_request':{'id':'help-1'}})
        self.assertFalse(watcher.support_resolved(self.run,'help-1'))
        state({'help_responses':{'help-1':{}},'paused':{'reason':'pilot_help_answered'}})
        self.assertFalse(watcher.support_resolved(self.run,'help-1'))
        state({'help_responses':{'help-1':{}},'paused':None})
        self.assertTrue(watcher.support_resolved(self.run,'help-1'))
        c.close()

    def test_support_uses_explicit_new_run_dashboard_and_key_path(self):
        from unittest.mock import patch
        with patch.object(watcher,'support_resolved',return_value=True):
            watcher.tick(self.runs,self.directory,'thread-fixture',self.send,mode='support',
                         dashboard_url='http://127.0.0.1:8766',key_file=Path('/private/key'))
        prompt=self.calls[0]
        self.assertIn('http://127.0.0.1:8766',prompt)
        self.assertIn('/private/key',prompt)
        self.assertNotIn('localhost:8765',prompt)
