import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from edh_gauntlet.supervisor import Supervisor, environment, fingerprint, repair_prompt
from edh_gauntlet.runtime_store import read,write


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        project=patch('edh_gauntlet.supervisor.PROJECT_ROOT',Path(self.temp.name));project.start();self.addCleanup(project.stop)
        self.root=Path(self.temp.name)/'run';self.root.mkdir()
        write(self.root/'cohort.json',{'cohort_state':'active'})
        write(self.root/'SUPERVISOR.json',{'enabled':True,'hotfixes':True,'auto_advance':True})
        self.worker=Supervisor(self.root)
        self.action={'kind':'repair_rules_work_items','game':1,'issues':['issue']}
        write(self.root/'NEXT_ACTION.json',{'next_action':self.action})
        self.receipt=self.root/'supervisor/attempts'/fingerprint(self.action)/'receipt.json'

    def fake_command(self,args,log,**kwargs):
        if args[0]=='codex':
            write(Path(args[args.index('-o')+1]),{'status':'repaired','summary':'Regression fixed.','tests':['test_combat']})
        if 'repair-rules' in args:
            write(self.root/'NEXT_ACTION.json',{'next_action':{'kind':'advance_game','game':2}})

    def test_repair_runs_independent_gates_before_recording(self):
        with patch.object(self.worker,'command',side_effect=self.fake_command) as command:
            self.assertEqual(self.worker.tick(),'repaired')
        commands=[call.args[0] for call in command.call_args_list]
        self.assertEqual(len(commands),4)
        self.assertIn('unittest',commands[1]);self.assertIn('verify',commands[2]);self.assertIn('repair-rules',commands[3])
        self.assertEqual(read(self.receipt)['state'],'complete')

    def test_failed_gate_never_records_or_retries(self):
        def fail(args,log,**kwargs):
            self.fake_command(args,log,**kwargs)
            if 'unittest' in args:raise RuntimeError('regression failed')
        with patch.object(self.worker,'command',side_effect=fail) as command:
            self.assertEqual(self.worker.tick(),'needs_attention')
            count=command.call_count
            self.assertEqual(self.worker.tick(),'needs_attention');self.assertEqual(command.call_count,count)
        self.assertEqual(self.worker.action(),self.action)

    def test_worker_cannot_change_accepted_evidence(self):
        tape=self.root/'game_01/decisions.jsonl';tape.parent.mkdir();tape.write_text('original')
        def tamper(args,log,**kwargs):
            self.fake_command(args,log,**kwargs);tape.write_text('changed')
        with patch.object(self.worker,'command',side_effect=tamper) as command:
            self.assertEqual(self.worker.tick(),'needs_attention');self.assertEqual(command.call_count,1)
        self.assertIn('Protected',read(self.receipt)['error'])

    def test_pause_prevents_repair(self):
        write(self.root/'HOST_PAUSED.json',{'reason':'user_stop'})
        with patch.object(self.worker,'command') as command:
            self.assertEqual(self.worker.tick(),'paused');command.assert_not_called()

    def test_hotfix_opt_out_prevents_inference(self):
        write(self.root/'SUPERVISOR.json',{'enabled':True,'hotfixes':False})
        with patch.object(self.worker,'command') as command:
            self.assertEqual(self.worker.tick(),'needs_attention');command.assert_not_called()

    def test_live_host_prevents_repair(self):
        with patch.object(self.worker.app,'host',return_value={'alive':True}),patch.object(self.worker,'command') as command:
            self.assertEqual(self.worker.tick(),'watching');command.assert_not_called()

    def test_existing_prefix_cannot_restart_unfenced(self):
        write(self.root/'NEXT_ACTION.json',{'next_action':{'kind':'dispatch_pilot','game':1}})
        tape=self.root/'game_01/decisions.jsonl';tape.parent.mkdir();tape.write_text('{}\n')
        with patch.object(self.worker.app,'start') as start:
            self.assertEqual(self.worker.tick(),'needs_attention');start.assert_not_called()

    def test_fresh_frontier_launches_once(self):
        write(self.root/'NEXT_ACTION.json',{'next_action':{'kind':'dispatch_pilot','game':1}})
        with patch.object(self.worker.app,'start') as start:
            self.assertEqual(self.worker.tick(),'starting')
            self.assertEqual(self.worker.tick(),'needs_attention');start.assert_called_once()

    def test_review_and_learning_recovery_are_not_bypassed(self):
        for kind in ('postgame_review','retry_learning_transaction','adjudicate_combo','resolve_horizon_stop'):
            write(self.root/'NEXT_ACTION.json',{'next_action':{'kind':kind,'game':1}})
            with patch.object(self.worker,'command') as command:
                self.assertEqual(self.worker.tick(),'needs_attention');command.assert_not_called()

    def test_api_billing_environment_is_removed(self):
        with patch.dict('os.environ',{'OPENAI_API_KEY':'secret','CODEX_API_KEY':'secret'}):
            self.assertNotIn('OPENAI_API_KEY',environment());self.assertNotIn('CODEX_API_KEY',environment())

    def test_prompt_separates_repair_from_gameplay(self):
        prompt=repair_prompt(self.root,self.action)
        self.assertIn('never a gameplay pilot',prompt)
        self.assertIn('Do not execute campaign lifecycle commands',prompt)

    def test_changed_sealed_result_cannot_be_recorded(self):
        seal={'decision_count':1,'decisions_sha256':'hash','result':{'winner':'A'}}
        write(self.root/'game_01/terminal_result.json',seal)
        def mismatch(args,log,**kwargs):
            self.fake_command(args,log,**kwargs)
            if 'edh_gauntlet.cardwise_replay' in args:
                write(log,{'accepted':1,'decisions_sha256':'hash','state':'terminal','result':{'winner':'B'}})
        with patch.object(self.worker,'command',side_effect=mismatch):
            self.assertEqual(self.worker.tick(),'needs_attention')
        self.assertEqual(self.worker.action(),self.action)
