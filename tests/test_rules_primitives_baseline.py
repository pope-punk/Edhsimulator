import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from edh_gauntlet.rules_baseline import capture, verify
from edh_gauntlet.rules_inventory import inventory


class BaselineTests(unittest.TestCase):
    def test_reproducible_snapshot_excludes_live_memory_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'src').mkdir()
            source = root / 'src/example.py'
            source.write_text('value = 1\n')
            (root / 'runs').mkdir()
            (root / 'runs/private.json').write_text('private pilot packet')
            baseline = capture(root, root / 'baselines')
            original = baseline.read_bytes()
            self.assertEqual(baseline, capture(root, root / 'baselines'))
            self.assertEqual(original, baseline.read_bytes())
            manifest = verify(baseline)
            self.assertEqual({'src/example.py'}, set(manifest['files']))
            source.write_text('value = 2\n')
            self.assertNotEqual(baseline, capture(root, root / 'baselines'))
            with tarfile.open(baseline, 'r:gz') as archive:
                rows = [(m, archive.extractfile(m).read()) for m in archive.getmembers()]
            with tarfile.open(baseline, 'w:gz') as archive:
                for member, data in rows:
                    if member.name == 'src/example.py':
                        data = b'tampered\n'
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
            with self.assertRaisesRegex(ValueError, 'content mismatch'):
                verify(baseline)

    def test_inventory_does_not_convert_metadata_into_verified_coverage(self):
        report = inventory()
        self.assertGreater(report['card_count'], 0)
        self.assertIsNone(report['coverage_percentage'])
        self.assertEqual(report['record_count'], len(report['records']))
        self.assertTrue(all(row['review_state'] == 'unreviewed' for row in report['records']))
        for row in report['records']:
            if row['execution_class'] == 'legacy_adapter':
                self.assertTrue(row['handler'].startswith('legacy:'))


    def test_fixture_card_text_matches_the_reviewed_source_fingerprints(self):
        import hashlib
        from edh_gauntlet.paths import PROJECT_ROOT
        manifest = json.loads((PROJECT_ROOT / 'data/reference/rules_primitives_sources.json').read_text())
        catalog = json.loads((PROJECT_ROOT / manifest['card_text_source']).read_text())
        rows = catalog['cards'] if isinstance(catalog, dict) else catalog
        cards = {card['card_id']: card for card in rows}
        self.assertEqual(6, len(manifest['card_text_fingerprints']))
        for binding in manifest['card_text_fingerprints']:
            with self.subTest(card=binding['name']):
                self.assertEqual(binding['oracle_sha256'],
                    hashlib.sha256(cards[binding['card_id']]['oracle_text'].encode()).hexdigest())
