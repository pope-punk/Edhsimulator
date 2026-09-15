"""Inspection stays bound to the delivered seat and historical frontier."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet.primitive_actions import claim
from edh_gauntlet.primitive_inspection import inspect
from edh_gauntlet.rules_state import RulesViolation


class PrimitiveInspectionTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.game=PrimitiveCampaign._create(Path(self.tmp.name)/'game',seed=93,starting_player='Omo')
        self.addCleanup(self.game.close)

    def test_frozen_history_cannot_read_later_records(self):
        frozen=claim(self.game,'Omo')
        with self.game.transaction():self.game.record('Omo','rationale',{'rationale':'Later private test record'})
        result=inspect(self.game,'Omo','decider',frozen,[{'kind':'history','after':0}])
        self.assertNotIn('Later private test record',str(result))

    def test_another_hand_and_unknown_reference_have_same_rejection(self):
        frozen=claim(self.game,'Omo');hidden=self.game.store.packet('Elenda')['hand'][0]['ref']
        errors=[]
        for ref in (hidden,{'card_id':'unknown','incarnation':0}):
            with self.assertRaises(RulesViolation) as raised:
                inspect(self.game,'Omo','decider',frozen,[{'kind':'object','source':ref}])
            errors.append(str(raised.exception))
        self.assertEqual(errors[0],errors[1])

    def test_deck_and_personal_history_are_not_diplomat_inspections(self):
        frozen={'board':{}}
        for query in ({'kind':'deck'},{'kind':'history','after':0}):
            with self.assertRaises(RulesViolation):inspect(self.game,'Omo','diplomacy',frozen,[query])

    def test_own_deck_and_printed_text_are_available_without_future_order(self):
        frozen=claim(self.game,'Omo')
        result=inspect(self.game,'Omo','long_term_planner',frozen,[{'kind':'deck'},{'kind':'card','name':'Island'}])
        self.assertEqual(100,sum(row['quantity'] for row in result['results'][0]['cards']))
        self.assertEqual('Island',result['results'][1]['name'])

    def test_decider_claim_does_not_load_historical_decisions_or_boards(self):
        import zlib
        from unittest.mock import patch
        with self.game.transaction():
            self.game.record('Omo','rationale',{'rationale':'Keep the complete reason.','command':{'kind':'pass'}})
            for _ in range(10):self.game.record('Omo','observation',{'board':'Archived fixture board'})
        with patch('edh_gauntlet.primitive_campaign.zlib.decompress',wraps=zlib.decompress) as decompress:
            frozen=claim(self.game,'Omo')
        self.assertEqual(0,decompress.call_count)
        self.assertNotIn('rationales',frozen)
        self.assertNotIn('Keep the complete reason.',str(frozen))
        self.assertEqual(self.game.evidence_position('Omo'),frozen['evidence_through'])
        self.assertNotIn('Archived fixture board',str(frozen))

    def test_current_choice_is_small_and_stays_bound_after_frontier_changes(self):
        frozen=claim(self.game,'Omo');before=frozen['board']['decision']
        q=self.game.kernel.pending_choice
        self.game.submit('Omo','keep',{'kind':'answer','revision':self.game.kernel.revision,
            'request_id':q.request_id,'indexes':[0]},rationale='Synthetic keep.')
        result=inspect(self.game,'Omo','decider',frozen,[{'kind':'decision'}])
        self.assertEqual(before,result['results'][0])
        self.assertEqual(q.request_id,result['results'][0]['choice']['request_id'])

    def test_history_omits_passes_without_changing_audit_or_page_cursor(self):
        with self.game.transaction():
            self.game.record('Omo','rationale',{'rationale':'PASS OMIT','command':{'kind':'pass'}})
            self.game.record('Omo','rationale',{'rationale':'CAST KEEP','command':{'kind':'cast'}})
        rows=self.game.evidence('Omo',kinds=('rationale',));frozen=claim(self.game,'Omo')
        first=inspect(self.game,'Omo','decider',frozen,[{'kind':'history','after':rows[0]['id']-1,'page_size':1}])['results'][0]
        self.assertEqual([],first['records']);self.assertEqual(rows[0]['id'],first['next'])
        second=inspect(self.game,'Omo','decider',frozen,[{'kind':'history','after':first['next'],'page_size':1}])['results'][0]
        self.assertIn('CAST KEEP',str(second));self.assertEqual(rows,self.game.evidence('Omo',kinds=('rationale',)))

    def test_large_inspection_requires_narrowing_without_truncating_facts(self):
        frozen={'board':{'decision':{'kind':'choice','choice':{'request_id':'exact'}},
                         'large':[{'name':'Card '+str(i),'text':'x'*1000} for i in range(50)]}}
        result=inspect(self.game,'Omo','decider',frozen,[{'kind':'state'}])['results'][0]
        self.assertTrue(result['inspection_too_large'])
        choice=inspect(self.game,'Omo','decider',frozen,[{'kind':'decision'}])['results'][0]
        self.assertEqual('exact',choice['choice']['request_id'])
        page=inspect(self.game,'Omo','decider',frozen,[{'kind':'state','path':'/large','offset':32,'limit':2}])['results'][0]
        self.assertEqual(32,page['offset']);self.assertEqual(50,page['total'])
        self.assertEqual(frozen['board']['large'][32:34],page['items'])
