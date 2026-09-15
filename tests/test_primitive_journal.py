"""Host replay reconstructs projections without any game or model execution."""
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet import primitive_journal as journal,primitive_planning as planning
from edh_gauntlet.rules_state import RulesViolation
from edh_gauntlet.runtime_store import read


class HostJournalTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'game'
        self.game=PrimitiveCampaign._create(self.path,seed=93,starting_player='Omo')
        self.addCleanup(self.game.close)

    def test_action_plan_and_message_receipts_replay_without_dispatch(self):
        q=self.game.kernel.pending_choice
        self.game.submit('Omo','keep',{'kind':'answer','revision':self.game.kernel.revision,
            'request_id':q.request_id,'indexes':[0]},rationale='Synthetic keep.')
        job=planning.claim(self.game,'Omo',planning.LONG)
        planning.publish(self.game,'Omo',planning.LONG,job['job_id'],'long_term',
            {'long_term_plan':'Synthetic strategy.','diplomacy':[{'id':'hello','text':'Synthetic hello.','expires_turn':20}]})
        job=planning.claim(self.game,'Omo',planning.DIPLOMAT)
        planning.publish(self.game,'Omo',planning.DIPLOMAT,job['job_id'],'message',{'authorized_ids':['hello'],'urgent_material_plan_change':{'hello':0}})
        before=self.game.store.committed_head()
        with patch.object(self.game.store,'submit',side_effect=AssertionError('Replay must not execute')):
            self.assertEqual(journal.head(self.game.store.connection),journal.verify(self.game.store.connection,self.game.binding))
        self.assertEqual(before,self.game.store.committed_head())

    def test_noop_and_failed_transaction_do_not_advance_journal(self):
        before=journal.head(self.game.store.connection)
        with self.game.transaction():pass
        self.assertEqual(before,journal.head(self.game.store.connection))
        with self.assertRaisesRegex(RuntimeError,'fixture'):
            with self.game.transaction() as state:
                state['paused']={'reason':'must roll back'}
                self.game.record('Omo','fixture',{'value':'must roll back'})
                raise RuntimeError('fixture')
        self.assertEqual(before,journal.verify(self.game.store.connection,self.game.binding))
        self.assertFalse(self.game.evidence('Omo',kinds=('fixture',)))

    def test_unjournaled_state_edit_is_detected(self):
        state=self.game.state();state['transport_generation']=999
        self.game.store.connection.execute('UPDATE host_state SET value=? WHERE id=1',(json.dumps(state),))
        with self.assertRaisesRegex(RulesViolation,'state differs'):journal.verify(self.game.store.connection,self.game.binding)

    def test_boolean_substitution_for_integer_is_not_equal_replay(self):
        state=self.game.state();state['transport_generation']=False
        self.game.store.connection.execute('UPDATE host_state SET value=? WHERE id=1',(json.dumps(state),))
        with self.assertRaisesRegex(RulesViolation,'state differs'):journal.verify(self.game.store.connection,self.game.binding)

    def test_receipt_mutations_require_an_active_transaction_capture(self):
        with self.assertRaises(sqlite3.OperationalError):
            self.game.store.connection.execute('DELETE FROM host_evidence')
        journal.verify(self.game.store.connection,self.game.binding)

    def test_corrupt_journal_is_rejected_on_open_before_recovery(self):
        self.game.store.connection.execute('UPDATE host_journal SET payload=? WHERE seq=0',(b'corrupt',))
        self.game.close()
        with self.assertRaisesRegex(RulesViolation,'journal encoding'):PrimitiveCampaign.open(self.path)

    def test_terminal_seal_binds_host_and_rules_prefixes(self):
        self.game.rules_blocker('Omo','Synthetic rule blocker.')
        seal=read(self.path/'game_01/terminal_result.json')
        self.assertEqual(journal.verify(self.game.store.connection,self.game.binding),seal['host_commit'])
        self.assertEqual(self.game.store.committed_head(),seal['rules_commit'])
