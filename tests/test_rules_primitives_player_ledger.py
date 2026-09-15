"""Restored player resources must obey the same invariants as live mutations."""
from copy import deepcopy
import unittest
from edh_gauntlet.rules_state import RulesState,RulesViolation


class PlayerLedgerTests(unittest.TestCase):
    def test_restored_life_requires_exact_integers_but_allows_negative_life(self):
        state=RulesState(('A','B'));baseline=state.snapshot()
        for value in (True,False,1.5,'40',None):
            modified=deepcopy(baseline);modified['life']['A']=value
            with self.subTest(value=value),self.assertRaises(RulesViolation):RulesState.restore(modified)
        state.lose_life_batch(('A',),45);restored=RulesState.restore(state.snapshot())
        self.assertEqual(-5,restored.life('A'));self.assertEqual(('A',),restored.losing_players())

    def test_restored_player_counter_rows_require_exact_player_set(self):
        baseline=RulesState(('A','B')).snapshot()
        for rows in ({'A':{}},{'A':{},'B':{},'C':{}}):
            modified=deepcopy(baseline);modified['player_counters']=rows
            with self.assertRaises(RulesViolation):RulesState.restore(modified)

    def test_restored_counter_kinds_and_amounts_are_canonical(self):
        baseline=RulesState(('A','B')).snapshot()
        for row in ({'poison':True},{'poison':-1},{'poison':0},{'poison':1.5},{'':1},{1:2}):
            modified=deepcopy(baseline);modified['player_counters']['A']=row
            with self.subTest(row=row),self.assertRaises(RulesViolation):RulesState.restore(modified)

    def test_zero_addition_is_a_true_noop_and_invalid_kind_is_rejected(self):
        state=RulesState(('A','B'));before=state.snapshot()
        state.add_player_counters('A','poison',0);self.assertEqual(before,state.snapshot())
        for kind in ('',None,1):
            with self.assertRaises(RulesViolation):state.add_player_counters('A',kind,1)
            self.assertEqual(before,state.snapshot())

    def test_positive_counters_roundtrip_and_departed_player_addition_is_ignored(self):
        state=RulesState(('A','B','C'));state.add_player_counters('A','poison',2)
        restored=RulesState.restore(state.snapshot());self.assertEqual((('poison',2),),restored.player_counters('A'))
        restored.mark_departed(('C',));before=restored.snapshot();restored.add_player_counters('C','energy',1)
        self.assertEqual(before,restored.snapshot())
