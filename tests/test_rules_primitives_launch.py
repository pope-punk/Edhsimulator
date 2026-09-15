import tempfile
import unittest
from pathlib import Path
from edh_gauntlet.rules_launch_preflight import preflight
from edh_gauntlet.rules_state import RulesViolation


class LaunchTests(unittest.TestCase):
    def test_unready_launch_does_not_initialize_or_fall_back_to_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'new-cohort'
            report=preflight(target,learning='disabled')
            self.assertFalse(target.exists());self.assertFalse(report['initialized'])
            self.assertIsNone(report['launch_command'])
            self.assertEqual('blocked_rules_migration',report['status'])
            self.assertEqual(108,report['unreviewed_program_count'])
            self.assertEqual(1,report['requested']['short_term_sol_fast'])
            self.assertFalse(report['requested']['learning_enabled'])
            self.assertEqual(report,preflight(target,learning='disabled'))

    def test_existing_cohort_and_implicit_learning_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RulesViolation):preflight(directory)
            with self.assertRaises(RulesViolation):preflight(Path(directory)/'new',learning=None)
