import unittest
from edh_gauntlet.rules_admission import readiness, require_production_ready
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_state import RulesViolation,RulesState


class AdmissionTests(unittest.TestCase):
    def test_fixture_coverage_cannot_be_mistaken_for_whole_card_support(self):
        report = readiness()
        self.assertFalse(report['production_ready'])
        self.assertEqual(RulesKernel(RulesState(('A','B')),()).snapshot()['schema'],report['kernel_checkpoint_schema'])
        self.assertEqual(3, report['fixture_card_count'])
        self.assertEqual(7, sum(card['fixture_program'] is not None for card in report['cards']))
        body = next(card for card in report['cards'] if card['card_id'] == 'body-double')
        self.assertEqual('program_authored', body['status'])
        self.assertIsNotNone(body['fixture_sha256'])
        self.assertEqual(0, report['certified_card_count'])
        self.assertEqual(report['card_count'], len(report['cards']))
        self.assertTrue(all(not card['production_certified'] for card in report['cards']))
        starfield = next(card for card in report['cards'] if card['card_id'] == 'starfield-of-nyx')
        self.assertEqual('fixture_only', starfield['status'])
        self.assertEqual(64, len(starfield['fixture_sha256']))
        self.assertGreater(len(report['blockers']), 0)

    def test_production_entrypoint_rejects_before_any_state_is_constructed(self):
        with self.assertRaisesRegex(RulesViolation, 'not admitted for production'):
            RulesKernel.for_production()
        with self.assertRaisesRegex(RulesViolation, 'Casting and activation'):
            require_production_ready()

    def test_readiness_fingerprints_are_deterministic(self):
        self.assertEqual(readiness(), readiness())
