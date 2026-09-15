"""Crash fencing proves process exit and preserves the exact pending frontier."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,skipUnless
import subprocess
import sys
from unittest.mock import patch
from edh_gauntlet.primitive_recovery import identity,verify_exited,fence_crash
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet.rules_state import RulesViolation
from edh_gauntlet.runtime_store import read,write


class ProcessEvidenceTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.proc=Path(self.tmp.name)
        boot=self.proc/'sys/kernel/random/boot_id';boot.parent.mkdir(parents=True);boot.write_text('boot-one')

    def process(self,pid,*,session=None,ticks=100,state='S'):
        path=self.proc/str(pid);path.mkdir(exist_ok=True)
        fields=[state,'1','1',str(session or pid)]+['0']*15+[str(ticks)]
        (path/'stat').write_text(str(pid)+' (complex (process) name) '+' '.join(fields))

    def test_live_identity_rejected_and_pid_reuse_does_not_count_as_owned_process(self):
        self.process(10);owned=identity(10,self.proc)
        self.assertEqual(100,owned['start_ticks'])
        with self.assertRaisesRegex(RulesViolation,'still running'):verify_exited(owned,proc=self.proc)
        self.process(10,ticks=200)
        verify_exited(owned,proc=self.proc)

    def test_exited_wrapper_does_not_hide_live_session_child(self):
        self.process(10);owned=identity(10,self.proc)
        (self.proc/'10/stat').unlink()
        self.process(11,session=10)
        with self.assertRaisesRegex(RulesViolation,'session process'):verify_exited(owned,session=10,proc=self.proc)
        self.process(11,session=10,state='Z')
        verify_exited(owned,session=10,proc=self.proc)

    @skipUnless(Path('/proc/sys/kernel/random/boot_id').exists(),'Linux process identity check')
    def test_real_isolated_process_must_exit_before_fencing(self):
        process=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True)
        try:
            owned=identity(process.pid)
            self.assertIsNotNone(owned)
            with self.assertRaisesRegex(RulesViolation,'still running'):
                verify_exited(owned,session=process.pid)
        finally:
            process.terminate();process.wait(timeout=5)
        verify_exited(owned,session=process.pid)

    def test_reboot_missing_evidence_and_corrupt_stat(self):
        self.process(10);owned=identity(10,self.proc)
        with self.assertRaises(RulesViolation):verify_exited(None,proc=self.proc)
        (self.proc/'10/stat').write_text('corrupt')
        with self.assertRaises(RulesViolation):verify_exited(owned,proc=self.proc)
        (self.proc/'sys/kernel/random/boot_id').write_text('boot-two')
        verify_exited(owned,session=10,proc=self.proc)


class CrashFenceTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.game=PrimitiveCampaign._create(Path(self.tmp.name)/'game',seed=93,starting_player='Omo')
        self.addCleanup(self.game.close)
        self.path=self.game.root/'host_runtime/process.json'
        self.head=self.game.store.committed_head()
        self.process={'binding':self.game.binding,'generation':0,'active':True,'contexts_unloaded':False,
            'host_identity':{'pid':10,'boot_id':'fixture','start_ticks':1},
            'transport_identity':{'pid':11,'boot_id':'fixture','start_ticks':2},'transport_session':11}
        write(self.path,self.process)

    def test_fence_is_idempotent_and_does_not_submit_pending_input(self):
        q=self.game.kernel.pending_choice
        self.game.prepare('Omo','pending',{'kind':'answer','revision':self.game.kernel.revision,
            'request_id':q.request_id,'indexes':[0]},rationale='Synthetic pending choice.')
        with patch('edh_gauntlet.primitive_recovery.verify_exited') as verify:
            fence_crash(self.game,self.head);fence_crash(self.game,self.head)
        self.assertEqual(2,verify.call_count)
        self.assertEqual('pending',self.game.state()['pending'])
        self.assertEqual(self.head,self.game.store.committed_head())
        self.assertEqual('host_stopped',self.game.state()['paused']['reason'])
        self.assertTrue(read(self.path)['contexts_unloaded'])
        self.assertEqual(1,len(self.game.evidence('Omo',kinds=('crash_fence',))))

    def test_live_process_or_wrong_generation_cannot_publish_a_fence(self):
        with patch('edh_gauntlet.primitive_recovery.verify_exited',side_effect=RulesViolation('still running')):
            with self.assertRaises(RulesViolation):fence_crash(self.game,self.head)
        self.assertTrue(read(self.path)['active'])
        write(self.path,{**self.process,'generation':99})
        with self.assertRaisesRegex(RulesViolation,'generation'):fence_crash(self.game,self.head)
        self.assertFalse(self.game.evidence('Omo',kinds=('crash_fence',)))

    def test_retry_after_marker_write_failure_preserves_operator_pause(self):
        self.game.pause('operator pause')
        with patch('edh_gauntlet.primitive_recovery.verify_exited'):
            with patch('edh_gauntlet.primitive_recovery.write',side_effect=OSError('fixture')):
                with self.assertRaises(OSError):fence_crash(self.game,self.head)
            fence_crash(self.game,self.head)
        self.assertEqual('operator pause',self.game.state()['paused']['reason'])
        self.assertEqual(1,len(self.game.evidence('Omo',kinds=('crash_fence',))))
