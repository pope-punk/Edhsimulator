"""Admission requires matching local release evidence, never fixture counts alone."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import subprocess
from edh_gauntlet import primitive_release as release
from edh_gauntlet.rules_admission import readiness,require_production_ready
from edh_gauntlet.rules_launch_preflight import preflight
from edh_gauntlet.rules_adapter import digest
from edh_gauntlet.rules_state import RulesViolation
from edh_gauntlet.runtime_store import write
from edh_gauntlet.paths import PROJECT_ROOT


class ReleaseEvidenceTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'receipt.json'
        self.body={'schema':1,'scope':release.SCOPE,'fingerprint':release.fingerprint(),
                   'test_count':100,'checks':{key:True for key in release.CHECKS}}

    def save(self,body=None):
        body=body or self.body;write(self.path,{'evidence':body,'sha256':digest(body)})

    def test_changed_code_or_failed_check_cannot_admit(self):
        for change in [{'fingerprint':{}},{'checks':{}},{'test_count':0},{'scope':'different'}]:
            self.save({**self.body,**change})
            with patch.dict('os.environ',{'EDH_PRIMITIVE_RELEASE_RECEIPT':str(self.path)}):
                self.assertIsNone(release.evidence()[0])

    def test_matching_receipt_allows_only_supported_host_scope(self):
        self.save()
        with patch.dict('os.environ',{'EDH_PRIMITIVE_RELEASE_RECEIPT':str(self.path)}):
            self.assertTrue(require_production_ready(scope='host')['production_ready'])
            with self.assertRaisesRegex(RulesViolation,'generic production factories'):require_production_ready()
            target=Path(self.tmp.name)/'fresh'
            report=preflight(target)
            self.assertEqual('ready',report['status']);self.assertFalse(target.exists())
            self.assertIn('edh_gauntlet.primitive_lifecycle',report['launch_command'])
            self.assertIsNone(preflight(target,games=2)['launch_command'])
            self.assertIsNone(preflight(target,learning='enabled')['launch_command'])
            self.assertEqual(0,readiness()['certified_card_count']) # Host validation is not a whole-card guarantee.

    def test_failed_validation_never_publishes_receipt(self):
        with patch('edh_gauntlet.primitive_release.subprocess.run',side_effect=subprocess.CalledProcessError(1,'tests')):
            with self.assertRaises(subprocess.CalledProcessError):release.validate(PROJECT_ROOT,self.path)
        self.assertFalse(self.path.exists())
