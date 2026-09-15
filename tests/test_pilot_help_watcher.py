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
