import tempfile, unittest
from unittest.mock import patch, Mock
from edh_gauntlet.dashboard import write_json, linux_process_identity
import os
from pathlib import Path
from edh_gauntlet.dashboard import Dashboard

class DashboardTests(unittest.TestCase):
    def test_unstarted_next_game_keeps_completed_record(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Dashboard(Path(directory),'secret','python');root=app.root('run')
            write_json(root/'cohort.json',{'active_game':4})
            write_json(root/'NEXT_ACTION.json',{'next_action':{'kind':'advance_game','game':4}})
            write_json(root/'game_03/status.json',{'state':'complete','decision_count':374,'result':{'winner':'Reaminatour'}})
            result=app.snapshot('run')
            self.assertEqual(result['game'],3);self.assertEqual(result['pending_game'],4)
            self.assertEqual(result['status']['decision_count'],374)
            self.assertEqual(result['next_action']['game'],4)
            write_json(root/'game_04/status.json',{'state':'need_decision'})
            self.assertEqual(app.snapshot('run')['game'],4)

    def test_rejects_unsafe_run_id(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Dashboard(Path(directory),'secret','python')
            with self.assertRaises(ValueError):app.root('../escape')

    def test_empty_run_list(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(Dashboard(Path(directory),'secret','python').list_runs(),[])

    def test_restarted_dashboard_recognizes_verified_host(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Dashboard(Path(directory),'secret','python');root=app.root('run')
            identity={'start_ticks':123,'boot_id':'boot'}
            write_json(root/'dashboard/launch.json',{'pid':42,'linux_process_identity':identity})
            with patch('edh_gauntlet.dashboard.linux_process_identity',return_value=identity):
                self.assertTrue(app.host('run',root)['alive'])
            with patch('edh_gauntlet.dashboard.linux_process_identity',return_value={'start_ticks':124,'boot_id':'boot'}):
                self.assertFalse(app.host('run',root)['alive'])

    def test_old_child_does_not_hide_recovered_host(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Dashboard(Path(directory),'secret','python');root=app.root('run')
            identity={'start_ticks':123,'boot_id':'boot'}
            write_json(root/'dashboard/launch.json',{'pid':42,'linux_process_identity':identity})
            app.processes['run']=Mock(pid=41,returncode=1)
            with patch('edh_gauntlet.dashboard.linux_process_identity',return_value=identity):
                result=app.host('run',root)
                self.assertTrue(result['alive']);self.assertNotIn('exit_code',result)

    def test_start_does_not_duplicate_recovered_host(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Dashboard(Path(directory),'secret','python');root=app.root('run')
            write_json(root/'cohort.json',{})
            with patch.object(app,'host',return_value={'alive':True}), \
                 patch.object(app,'snapshot',return_value={'existing':True}), \
                 patch('edh_gauntlet.dashboard.subprocess.Popen') as launch:
                self.assertEqual(app.start('run',{}),{'existing':True})
                launch.assert_not_called()

    def test_start_rejects_lifecycle_blocker_without_launching(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Dashboard(Path(directory),'secret','python');root=app.root('run')
            write_json(root/'cohort.json',{})
            write_json(root/'NEXT_ACTION.json',{'next_action':{'kind':'repair_rules_work_items'}})
            with patch('edh_gauntlet.dashboard.subprocess.Popen') as launch:
                with self.assertRaisesRegex(ValueError,'repair_rules_work_items'):app.start('run',{})
                launch.assert_not_called()

    def test_start_requires_fenced_recovery_for_existing_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Dashboard(Path(directory),'secret','python');root=app.root('run')
            write_json(root/'cohort.json',{})
            write_json(root/'NEXT_ACTION.json',{'next_action':{'kind':'dispatch_pilot'}})
            write_json(root/'host_runtime/sessions.json',[])
            with patch('edh_gauntlet.dashboard.subprocess.Popen') as launch:
                with self.assertRaisesRegex(ValueError,'fenced recovery'):app.start('run',{})
                launch.assert_not_called()

    def test_start_routes_opted_in_run_to_supervisor(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Dashboard(Path(directory),'secret','python');root=app.root('run')
            write_json(root/'cohort.json',{})
            write_json(root/'SUPERVISOR.json',{'enabled':True})
            with patch.object(app,'start_supervisor',return_value={'supervised':True}) as start:
                self.assertEqual(app.start('run',{}),{'supervised':True})
                start.assert_called_once_with('run',root)

    def test_pause_can_interrupt_supervisor_without_gameplay_host(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Dashboard(Path(directory),'secret','python');root=app.root('run')
            snapshot={'host':{'alive':False},'supervisor':{'alive':True},'status':{'decision_count':3}}
            with patch.object(app,'snapshot',return_value=snapshot):app.pause('run')
            from edh_gauntlet.dashboard import read_json
            self.assertEqual(read_json(root/'HOST_PAUSED.json'),{'reason':'user_stop','accepted':3})

    @unittest.skipUnless(Path('/proc/self/stat').exists(),'Linux process identity')
    def test_current_process_identity(self):
        self.assertIsNotNone(linux_process_identity(os.getpid()))
        self.assertIsNone(linux_process_identity(None))

    def test_chat_projection_preserves_text_and_omits_metadata(self):
        from edh_gauntlet.campaign import _messageboard_markdown
        from edh_gauntlet.dashboard import chat_messages
        entries=[{'message_id':'M0001','author':'Aminatou','round':2,'turn':5,'phase':'precombat_main',
                  'address':{'kind':'all'},'text':'<script> & keep ```text literal.'}]
        original=_messageboard_markdown(1,entries)
        messages=chat_messages(original)
        self.assertEqual(messages,[{'sender':'Aminatou','turn':'5','phase':'precombat_main','message':entries[0]['text']}])
        self.assertEqual(original,_messageboard_markdown(1,entries))

    def test_canonical_recovery_record_overrides_failed_start(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Dashboard(Path(directory),'secret','python');root=app.root('run')
            identity={'start_ticks':123,'boot_id':'boot'}
            write_json(root/'dashboard/launch.json',{'pid':99})
            write_json(root/'host_runtime/launch.json',{'pid':42,'linux_process_identity':identity})
            with patch('edh_gauntlet.dashboard.linux_process_identity',return_value=identity):
                result=app.host('run',root)
                self.assertTrue(result['alive']);self.assertEqual(result['pid'],42)

if __name__=='__main__':unittest.main()
