"""Existing web views and exports work with the primitive campaign surface."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch,Mock
from edh_gauntlet.dashboard import Dashboard
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet.runtime_store import write,read
from edh_gauntlet.supervisor import Supervisor


class PrimitiveDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'run'
        self.game=PrimitiveCampaign._create(self.root,seed=94,starting_player='Omo',games=2)
        self.addCleanup(self.game.close)
        self.app=Dashboard(self.root.parent,'secret','python')

    def test_existing_snapshot_schema_has_four_hands_and_current_choice(self):
        before=self.game.store.committed_head();value=self.app.snapshot('run')
        self.assertEqual(4,len(value['operator']));self.assertEqual('Omo',value['status']['request']['actor'])
        self.assertEqual(4,len(value['status']['public_state']['players']))
        self.assertTrue(all(len(p['hand'])==7 for p in value['status']['public_state']['players'].values()))
        self.assertEqual(before,self.game.store.committed_head())
        self.assertFalse(value['config']['learning_enabled']);self.assertNotIn('all_decisions',value)

    def test_cardwise_covers_full_deck_before_any_game_finishes(self):
        report=self.app.cardwise('run')
        self.assertEqual(100,report['deck_size']);self.assertEqual(1,report['pending_games'])
        self.assertEqual(0,report['completed_games']);self.assertTrue(all(r['won_if_seen'] is None for r in report['rows']))

    def test_create_refuses_learning_before_starting_a_subprocess(self):
        with patch('edh_gauntlet.dashboard.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError,'disabled learning'):self.app.create({'id':'new','learning':'enabled'})
            run.assert_not_called()
        self.assertFalse((self.root.parent/'new').exists())

    def test_supervisor_does_not_launch_a_rules_repair_agent_for_primitive_blocker(self):
        write(self.root/'SUPERVISOR.json',{'enabled':True,'auto_advance':True,'hotfixes':True})
        self.game.rules_blocker('Omo','Synthetic rules blocker.')
        supervisor=Supervisor(self.root)
        with patch.object(supervisor,'repair') as repair,patch.object(supervisor,'command') as command:
            self.assertEqual('needs_attention',supervisor.tick());repair.assert_not_called();command.assert_not_called()

    def test_explicit_resume_refuses_live_or_unfenced_transport(self):
        with patch.object(self.app,'host',return_value={'alive':False}),patch.object(self.app,'supervisor',return_value={'alive':False}):
            write(self.root/'host_runtime/process.json',{'active':True,'contexts_unloaded':False})
            with patch('edh_gauntlet.dashboard.subprocess.run') as run:
                with self.assertRaisesRegex(ValueError,'unloaded'):self.app.resume('run')
                run.assert_not_called()

    def test_acceptance_is_shown_in_decision_log_without_changing_actor_packets(self):
        q=self.game.kernel.pending_choice
        self.game.submit(q.actor,'keep',{'kind':'answer','revision':self.game.kernel.revision,'request_id':q.request_id,'indexes':[0]},rationale='Synthetic private rationale.')
        value=self.app.snapshot('run');self.assertEqual(1,value['decision_log_total'])
        self.assertEqual('Synthetic private rationale.',value['decision_log'][0]['rationale'])
        self.assertNotIn('Synthetic private rationale.',str(self.game.store.packet('Elenda')))
