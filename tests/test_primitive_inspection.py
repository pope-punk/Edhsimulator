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
