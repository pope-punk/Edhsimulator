"""Campaign boundaries exercise real commands, durable recovery and seat privacy."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet.rules_state import RulesViolation
from edh_gauntlet.rules_adapter import AcceptedTransitionError
from edh_gauntlet.runtime_store import read


class PrimitiveCampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'cohort'
        self.game=PrimitiveCampaign._create(self.path,seed=931,starting_player='Omo')
        self.addCleanup(lambda:self.game.close())

    def answer(self,index=0):
        q=self.game.kernel.pending_choice
        return q.actor,{'kind':'answer','revision':self.game.kernel.revision,'request_id':q.request_id,'indexes':[index]}

    def test_next_action_contains_only_metadata_and_matches_file(self):
        action=self.game.next_action()
        self.assertEqual('Omo',action['actor']);self.assertEqual('dispatch_pilot',action['kind'])
        self.assertNotIn('hand',str(action));self.assertNotIn('options',str(action))
        self.assertEqual(action,read(self.path/'NEXT_ACTION.json')['next_action'])
        self.assertFalse((self.path/'game_01/postgame_learning/skipped.json').exists())

    def test_duplicate_host_submission_never_reexecutes_or_loses_rationale(self):
        actor,command=self.answer()
        receipt=self.game.submit(actor,'first',command,rationale='Keep this synthetic test hand.')
        head=self.game.store.committed_head()
        self.assertEqual(receipt,self.game.submit(actor,'first',command,rationale='Keep this synthetic test hand.'))
        self.assertEqual(head,self.game.store.committed_head())
        evidence=self.game.evidence(actor)
        self.assertEqual(1,len([e for e in evidence if e['kind']=='rationale']))
        self.assertFalse(any(e['kind']=='rationale' for e in self.game.evidence('Elenda')))
        with self.assertRaises(RulesViolation):self.game.submit(actor,'first',command,rationale='Different input')

    def test_restart_after_rules_commit_finishes_host_prefix_without_second_action(self):
        actor,command=self.answer()
        self.game.prepare(actor,'first',command,rationale='Keep the fixture hand.')
        self.game.store.submit(actor,'first',command)
        head=self.game.store.committed_head();self.game.close()
        self.game=PrimitiveCampaign.open(self.path)
        self.assertEqual(head,self.game.store.committed_head())
        self.assertIsNone(self.game.state()['pending'])
        self.assertEqual(1,len([e for e in self.game.evidence(actor) if e['kind']=='rationale']))

    def test_rejected_choice_can_be_corrected_without_resetting_the_game(self):
        actor,command=self.answer();before=self.game.store.committed_head()
        with self.assertRaises(RulesViolation):self.game.submit(actor,'bad',{**command,'indexes':[99]},rationale='Invalid fixture selection.')
        self.assertEqual(before,self.game.store.committed_head())
        self.assertIsNone(self.game.state()['pending'])
        self.game.submit(actor,'fixed',command,rationale='Correct the rejected test selection.')
        self.assertEqual(1,self.game.store.generation)

    def test_paused_campaign_cannot_accept_another_choice(self):
        actor,command=self.answer();self.game.pause('operator pause')
        with self.assertRaises(RulesViolation):self.game.submit(actor,'first',command,rationale='Keep.')
        self.assertEqual(0,self.game.store.generation)
        self.assertEqual('host_paused',self.game.next_action()['reason'])

    def test_pause_prevents_recovery_from_executing_a_prepared_uncommitted_choice(self):
        actor,command=self.answer()
        self.game.prepare(actor,'first',command,rationale='Keep the test hand.')
        self.game.pause('operator pause');self.game.close()
        self.game=PrimitiveCampaign.open(self.path)
        self.assertEqual(0,self.game.store.generation)
        self.assertEqual('first',self.game.state()['pending'])
        self.assertEqual('host_paused',self.game.next_action()['reason'])

    def test_existing_directory_and_legacy_campaign_are_not_adopted(self):
        with self.assertRaises(FileExistsError):PrimitiveCampaign._create(self.path,seed=9,starting_player='Omo')
        other=Path(self.temp.name)/'legacy';other.mkdir()
        with self.assertRaises(RulesViolation):PrimitiveCampaign.open(other)

    def test_production_constructor_remains_gated(self):
        with self.assertRaises(RulesViolation):PrimitiveCampaign.create(Path(self.temp.name)/'not-admitted',seed=9,starting_player='Omo')
        self.assertFalse((Path(self.temp.name)/'not-admitted').exists())

    def test_host_projection_failure_after_acceptance_is_not_reported_as_a_rejected_action(self):
        actor,command=self.answer()
        with patch.object(self.game,'_capture',side_effect=RulesViolation('Synthetic projection defect')):
            with self.assertRaises(AcceptedTransitionError):
                self.game.submit(actor,'accepted',command,rationale='Keep the fixture hand.')
        self.assertEqual(1,self.game.store.generation)
        self.assertEqual('accepted',self.game.state()['pending'])
        before=self.game.store.committed_head()
        self.game.recover()
        self.assertEqual(before,self.game.store.committed_head())
        self.assertIsNone(self.game.state()['pending'])
        self.assertEqual(1,len(self.game.evidence(actor,kinds=('rationale',))))
