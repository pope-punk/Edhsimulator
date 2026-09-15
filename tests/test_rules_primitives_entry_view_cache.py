"""Prospective entry caching ignores bookkeeping, never material characteristics."""
from dataclasses import replace
from unittest.mock import patch
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone
from edh_gauntlet.rules_kernel import RulesKernel,evaluate_characteristics
from edh_gauntlet.rules_replacements import ZoneProposal
from edh_gauntlet.rules_entry_view_benchmark import UncachedEntryKernel,fixture,measure

class EntryViewCacheTests(unittest.TestCase):
    def test_order_bookkeeping_reuses_one_immutable_evaluation(self):
        k,proposals=fixture(RulesKernel,1);p=proposals[0];before=k.snapshot()
        with patch('edh_gauntlet.rules_kernel.evaluate_characteristics',wraps=evaluate_characteristics) as evaluate:
            first=k._proposal_view(p)
            for i in range(10):self.assertIs(first,k._proposal_view(replace(p,used=frozenset({str(i)}),trace=({'step':i},),commander_considered=bool(i%2))))
            self.assertEqual(1,evaluate.call_count)
        self.assertEqual(before,k.snapshot())
        with self.assertRaises(AttributeError):first[1].types.add('Land')
    def test_controller_copy_counters_tapping_and_source_are_material(self):
        k,proposals=fixture(RulesKernel,2);p=proposals[0]
        variants=(p,replace(p,controller='B'),replace(p,copied_definition='anthem'),replace(p,counters=(('+1/+1',2),)),replace(p,tapped=True),proposals[1])
        with patch('edh_gauntlet.rules_kernel.evaluate_characteristics',wraps=evaluate_characteristics) as evaluate:
            for variant in variants:self.assertEqual(k._compute_proposal_view(variant),k._proposal_view(variant))
            self.assertEqual(2*len(variants),evaluate.call_count)
        self.assertEqual(6,len(k._entry_view_cache))
    def test_state_mutation_invalidates_previous_epoch(self):
        k,proposals=fixture(RulesKernel,1);p=proposals[0];first=k._proposal_view(p)
        k.state.phase(k.state.current('board0'),True);second=k._proposal_view(p)
        self.assertNotEqual(first[1].power,second[1].power);self.assertEqual(1,len(k._entry_view_cache))
        k.state.change_control(k.state.current('board1'),'B');self.assertEqual(k._compute_proposal_view(p),k._proposal_view(p))
        k.state.gain_life('A',1);self.assertEqual(k._compute_proposal_view(p),k._proposal_view(p))
    def test_lru_bound_and_recent_hit_survives_eviction(self):
        k,proposals=fixture(RulesKernel,65)
        for p in proposals[:64]:k._proposal_view(p)
        first=k._proposal_view(proposals[0]);k._proposal_view(proposals[-1])
        self.assertEqual(64,len(k._entry_view_cache));self.assertIs(first,k._proposal_view(proposals[0]))
        with patch('edh_gauntlet.rules_kernel.evaluate_characteristics',wraps=evaluate_characteristics) as evaluate:
            k._proposal_view(proposals[1]);self.assertEqual(1,evaluate.call_count)
    def test_temporary_effect_creation_and_cleanup_invalidate_cache(self):
        k,proposals=fixture(RulesKernel,1);p=proposals[0];first=k._proposal_view(p)
        ref=k.state.current('board2');k.open_window_for_scenario('A')
        k.execute_for_scenario(ref,'A',(UntilEndOfTurn('source',(ModifyPT(3,3),)),))
        self.assertEqual(k._compute_proposal_view(p),k._proposal_view(p))
        epoch=k._entry_view_epoch;k._finish_cleanup_actions();self.assertEqual(first[1],k._proposal_view(p)[1]);self.assertNotEqual(epoch,k._entry_view_epoch)
    def test_real_replacement_choices_and_checkpoint_continuation_match_uncached(self):
        program=CardProgram('entry','Entry',('Creature',),power=2,toughness=2,entry_modifiers=(EntryModifier('first'),EntryModifier('second')))
        state=RulesState(('A','B'));ref=state.add_card('s','entry','A',Zone.HAND)
        pair=(RulesKernel(state,(program,)),UncachedEntryKernel(RulesState.restore(state.snapshot()),(program,)))
        for k in pair:k.open_window_for_scenario('A');k.execute_for_scenario(ref,'A',(Move('source',Zone.BATTLEFIELD),))
        restored=RulesKernel.restore(pair[0].snapshot(),(program,));self.assertFalse(hasattr(restored,'_entry_view_cache'))
        for k in (*pair,restored):
            while k.pending_choice:q=k.pending_choice;k.answer(q.request_id,q.actor,[0])
        self.assertEqual(pair[0].snapshot(),pair[1].snapshot());self.assertEqual(pair[0].snapshot(),restored.snapshot())
        self.assertTrue(state.get(state.current('s')).tapped)
    def test_benchmark_checks_material_and_bookkeeping_parity(self):
        report=measure(repeats=1,incoming=2,passes=2)
        self.assertTrue(all(row['semantic_parity'] for row in report['cases']));self.assertEqual(64,report['cache_limit'])
        with self.assertRaises(ValueError):measure(repeats=0)

if __name__=='__main__':unittest.main()
