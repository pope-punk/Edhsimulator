"""Unvalidated tool arguments must not crash the transport's metadata observer."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from edh_gauntlet.host_telemetry import Timing


class PrimitiveTelemetryTests(TestCase):
    def test_structured_and_malformed_inspections_record_only_categories(self):
        with TemporaryDirectory() as directory:
            timing=Timing(Path(directory)/'timing.json')
            try:
                timing.observe({'method':'item/tool/call','id':'fixture','params':{'threadId':'fixture',
                    'tool':'edh_inspect','arguments':{'queries':[{'kind':'deck'},'history',{'kind':['bad']},
                        {'kind':'object','source':{'card_id':'private-source','incarnation':0}},None]}}})
                row=timing.events[-1]
                self.assertEqual(['deck','history','other','object','other'],row['inspection_categories'])
                self.assertNotIn('private-source',str(row))
            finally:timing.close()

    def test_malformed_proposals_reach_validation_without_breaking_telemetry(self):
        with TemporaryDirectory() as directory:
            timing=Timing(Path(directory)/'timing.json')
            try:
                for sequence in (None,17,{'bad':'shape'}):
                    timing.observe({'method':'item/tool/call','id':'fixture','params':{'threadId':'fixture',
                        'tool':'edh_publish','arguments':{'response':{'action_sequence':sequence}}}})
                    self.assertEqual(0,timing.events[-1]['proposed_actions'])
            finally:timing.close()
