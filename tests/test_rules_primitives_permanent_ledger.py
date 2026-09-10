"""Permanent counter restoration and direct additions share strict invariants."""
from copy import deepcopy
import unittest
from edh_gauntlet.rules_state import RulesState,RulesViolation,Zone


class PermanentLedgerTests(unittest.TestCase):
    def setUp(self):
        self.state=RulesState(('A','B'))
        self.ref=self.state.add_card('body','body','A',Zone.BATTLEFIELD)

    def test_restored_counter_rows_reject_bad_amounts_kinds_and_duplicates(self):
        baseline=self.state.snapshot()
        for rows in ((("charge",True),),(("charge",-1),),(("charge",0),),(("charge",1.5),),(("",1),),((1,2),),(("charge",1),("charge",2)),(("charge",),)):
            modified=deepcopy(baseline);modified['objects'][0]['counters']=rows
            with self.subTest(rows=rows),self.assertRaises(RulesViolation):RulesState.restore(modified)

    def test_zero_addition_is_noop_and_bad_kinds_are_rejected_without_mutation(self):
        before=self.state.snapshot()
        self.state.add_counters(self.ref,'charge',0);self.assertEqual(before,self.state.snapshot())
        for kind in ('',None,1):
            with self.assertRaises(RulesViolation):self.state.add_counters(self.ref,kind,1)
            self.assertEqual(before,self.state.snapshot())

    def test_direct_and_batch_additions_match_and_opposing_counters_roundtrip(self):
        other=RulesState.restore(self.state.snapshot())
        self.state.add_counters(self.ref,'+1/+1',3)
        other.put_counters_batch(((self.ref,(('+1/+1',3),)),))
        self.assertEqual(other.snapshot(),self.state.snapshot())
        self.state.add_counters(self.ref,'-1/-1',2)
        restored=RulesState.restore(self.state.snapshot())
        self.assertEqual(2,restored.cancel_opposing_counters(self.ref))
        self.assertEqual((('+1/+1',1),),restored.get(self.ref).counters)
        restored.assert_invariants()

    def test_unavailable_permanent_rejects_even_zero_addition(self):
        self.state.phase(self.ref,True);before=self.state.snapshot()
        for amount in (0,1):
            with self.assertRaises(RulesViolation):self.state.add_counters(self.ref,'charge',amount)
            self.assertEqual(before,self.state.snapshot())
        hand=self.state.add_card('hand','body','A',Zone.HAND);before=self.state.snapshot()
        with self.assertRaises(RulesViolation):self.state.add_counters(hand,'charge',0)
        self.assertEqual(before,self.state.snapshot())
