"""Ignored damage must not create state revisions or zero-valued ledgers."""
import unittest
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation


class DamageNoopTests(unittest.TestCase):
    def game(self):
        self.state=RulesState(('A','B','C'));ref=self.state.add_card('source','source','A',Zone.BATTLEFIELD,commander=True)
        self.source=self.state.get(ref)

    def test_damage_to_departed_player_is_noop_including_lifelink(self):
        self.game();self.state.mark_departed(('C',));before=self.state.snapshot()
        self.assertEqual({},self.state.damage_batch(({'source':self.source,'target':'C','amount':3,'lifelink':True},)))
        self.assertEqual(before,self.state.snapshot())

    def test_zero_commander_damage_does_not_add_ledger_row_in_mixed_batch(self):
        self.game();self.state.damage_batch(({'source':self.source,'target':'B','amount':0,'combat':True},
            {'source':self.source,'target':'C','amount':2,'combat':True}))
        self.assertEqual([{'player':'C','card_id':'source','amount':2}],self.state.snapshot()['commander_damage'])
        self.assertEqual(40,self.state.life('B'));self.assertEqual(38,self.state.life('C'))

    def test_zero_damage_still_validates_and_rejects_atomically(self):
        self.game();before=self.state.snapshot()
        for row in ({'source':self.source,'target':'unknown','amount':0},
                    {'source':self.source,'target':self.source.ref,'amount':0,'recipient_types':('Land',)},
                    {'source':self.source,'target':'B','amount':True}):
            with self.assertRaises(RulesViolation):self.state.damage_batch(({'source':self.source,'target':'B','amount':2},row))
            self.assertEqual(before,self.state.snapshot())
