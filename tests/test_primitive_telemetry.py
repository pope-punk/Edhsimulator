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

    def test_aggregate_counts_survive_rolling_event_eviction(self):
        with TemporaryDirectory() as directory:
            timing=Timing(Path(directory)/'timing.json',limit=2)
            try:
                for _ in range(5):timing.record('automatic_action',kind='pass',seconds=.1)
                self.assertEqual(2,len(timing.events))
                aggregate=timing.aggregates['automatic_action|host|pass']
                self.assertEqual(5,aggregate['count']);self.assertAlmostEqual(.5,aggregate['seconds_sum'])
            finally:timing.close()

    def test_first_tool_latency_survives_eviction_and_excludes_waiting_tool(self):
        from unittest.mock import patch
        with TemporaryDirectory() as directory:
            timing=Timing(Path(directory)/'timing.json',limit=2)
            try:
                timing.bind('fixture','Omo','short_term_planner')
                with patch('edh_gauntlet.host_telemetry.time.monotonic',side_effect=[10,14,100,103]):
                    timing.record('input_delivered','fixture')
                    timing.record('tool_arrived','fixture')
                    timing.record('tool_returned','fixture',seconds=80)
                    timing.record('tool_arrived','fixture') # No new input: not a new latency sample.
                    timing.record('input_delivered','fixture',warm=True)
                    timing.record('tool_arrived','fixture')
                for _ in range(4):timing.record('model_item','fixture')
                aggregate=timing.aggregates['input_to_first_tool|short_term_planner|']
                self.assertEqual(2,aggregate['count'])
                self.assertEqual(7,aggregate['seconds_sum'])
                self.assertEqual(4,aggregate['seconds_max'])
            finally:timing.close()
