"""Shared blocking comparisons use current characteristics and copied rules."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_combat import CombatView,uid
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed

class BlockRestrictionTests(unittest.TestCase):
    def game(self,zone=Zone.BATTLEFIELD):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(CardProgram('body','Body',('Creature',),power=1,toughness=4),)
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('champion','catalog:champion-of-lambholt','A',zone)
        self.ally=self.state.add_card('ally','body','A',Zone.BATTLEFIELD);self.blocker=self.state.add_card('blocker','body','B',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
    def can(self,attacker=None,blocker=None,kernel=None):
        view=CombatView(kernel or self.kernel);return view.can_block(view.card(blocker or self.blocker),view.card(attacker or self.ally))
    def drain(self):
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)

    def test_printed_cast_excludes_self_entry_and_grows_on_other_own_creature(self):
        self.game(Zone.HAND);self.state.add_mana('A',('C','G','G'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.ref),Payment((('C',1),('G',2))));self.drain();self.ref=self.state.current('champion')
        self.assertEqual(1,self.kernel.effective(self.ref).power);self.assertTrue(self.can())
        entrant=self.state.add_card('new','body','A',Zone.HAND);self.kernel.enter(entrant);self.drain();self.assertEqual(2,self.kernel.effective(self.ref).power);self.assertFalse(self.can())
        other=self.state.add_card('other','body','B',Zone.HAND);self.kernel.enter(other,'B');self.drain();self.assertEqual(2,self.kernel.effective(self.ref).power)

    def test_strict_power_comparison_current_counters_and_negative_values(self):
        self.game();self.assertTrue(self.can());self.state.add_counters(self.ref,'+1/+1',1);self.assertFalse(self.can());self.assertFalse(self.can(self.ref))
        self.state.add_counters(self.blocker,'+1/+1',1);self.assertTrue(self.can())
        self.kernel.execute_for_scenario(self.ref,'A',(UntilEndOfTurn('source',(SetPT(-3,4),)),))
        self.assertTrue(self.can());self.kernel.execute_for_scenario(self.blocker,'B',(UntilEndOfTurn('source',(SetPT(-2,4),)),))
        self.assertTrue(self.can())
        self.kernel.execute_for_scenario(self.blocker,'B',(UntilEndOfTurn('source',(SetPT(-5,4),)),))
        self.assertFalse(self.can())

    def test_phasing_and_control_changes_change_restriction_domain(self):
        self.game();self.state.add_counters(self.ref,'+1/+1',2);self.assertFalse(self.can())
        self.state.phase(self.ref,True);self.assertTrue(self.can());self.state.phase(self.ref,False);self.assertFalse(self.can())
        self.state.change_control(self.ref,'B');self.assertTrue(self.can());self.assertFalse(self.can(self.blocker,self.ally))

    def test_copied_rule_uses_copy_controller_and_power_with_actor_replay(self):
        self.game(Zone.GRAVEYARD);copy=self.state.add_card('copy','body','B',Zone.HAND)
        self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,'B',copied_definition='catalog:champion-of-lambholt'),),'fixture-copy');copy=self.state.current('copy');self.state.add_counters(copy,'+1/+1',2)
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.assertTrue(self.can());self.assertFalse(self.can(self.blocker,self.ally));self.assertFalse(self.can(self.blocker,self.ally,replay.kernel))

    def test_combat_menu_and_declaration_share_prohibition_and_reject_atomically(self):
        self.game();self.state.add_counters(self.ref,'+1/+1',1)
        for actor in ('A','B'):self.state.add_card('draw'+actor,'catalog:forest',actor,Zone.LIBRARY)
        self.kernel.begin_turn_for_scenario('A')
        for _ in range(4):
            for actor in ('A','B'):self.kernel.pass_priority(actor)
        self.kernel.declare_attackers('A',{self.ally:'B'},revision=self.kernel.revision)
        for actor in ('A','B'):self.kernel.pass_priority(actor)
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.declare_blockers('B',{uid(self.ally):[uid(self.blocker)]},revision=self.kernel.revision)
        self.assertEqual(before,self.kernel.snapshot());self.kernel.declare_blockers('B',{uid(self.ally):[]},revision=self.kernel.revision)

    def test_validation_rejects_unbound_values_and_invalid_comparisons(self):
        rule=BlockRestriction(Selector(Zone.BATTLEFIELD),Selector(Zone.BATTLEFIELD),'power','lt',1);base=CardProgram('test','Test',('Enchantment',),block_restrictions=(rule,))
        self.assertEqual(base,validate(decode(encode(base))))
        for bad in (replace(rule,comparison='neq'),replace(rule,statistic='loyalty'),replace(rule,value=ChosenX()),replace(rule,value=True),replace(rule,blockers=Selector(Zone.HAND))):
            with self.assertRaises(RulesViolation):validate(replace(base,block_restrictions=(bad,)))

    def test_restrictions_do_not_remove_an_already_declared_legal_block(self):
        self.game()
        for actor in ('A','B'):self.state.add_card('draw'+actor,'catalog:forest',actor,Zone.LIBRARY)
        self.kernel.begin_turn_for_scenario('A')
        for _ in range(4):
            for actor in ('A','B'):self.kernel.pass_priority(actor)
        self.kernel.declare_attackers('A',{self.ally:'B'},revision=self.kernel.revision)
        for actor in ('A','B'):self.kernel.pass_priority(actor)
        self.kernel.declare_blockers('B',{uid(self.ally):[uid(self.blocker)]},revision=self.kernel.revision)
        self.state.add_counters(self.ref,'+1/+1',3)
        self.assertFalse(self.can());self.kernel._combat_prune()
        self.assertEqual([self.blocker.to_json()],[row['ref'] for row in self.kernel.combat['blocks'][uid(self.ally)]])
        self.assertIn(uid(self.ally),self.kernel.combat['blocked'])

    def test_multiple_restrictions_combine_with_flying_and_reach_without_overrides(self):
        self.game();self.state.add_counters(self.ref,'+1/+1',2)
        self.kernel.execute_for_scenario(self.ally,'A',(UntilEndOfTurn('source',(AddKeywords(('flying',)),)),))
        self.kernel.execute_for_scenario(self.blocker,'B',(UntilEndOfTurn('source',(AddKeywords(('reach',)),)),))
        self.assertFalse(self.can())
        self.state.add_counters(self.blocker,'+1/+1',2);self.assertTrue(self.can())
        second=self.state.add_card('second','catalog:champion-of-lambholt','A',Zone.BATTLEFIELD)
        self.state.add_counters(second,'+1/+1',4);self.assertFalse(self.can())
        self.state.phase(second,True);self.assertTrue(self.can())
        self.kernel._finish_cleanup_actions()
        self.kernel.execute_for_scenario(self.ally,'A',(UntilEndOfTurn('source',(AddKeywords(('flying',)),)),))
        self.assertFalse(self.can())

    def test_blocker_selector_and_non_power_statistics_remain_general(self):
        self.game(Zone.GRAVEYARD)
        rule=BlockRestriction(Selector(Zone.BATTLEFIELD,relation='controlled'),Selector(Zone.BATTLEFIELD,colors=('G',)),'toughness','ge',4)
        restriction=CardProgram('restriction','Restriction',('Enchantment',),block_restrictions=(rule,))
        self.programs+=(restriction,);self.state.add_card('restriction','restriction','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs)
        self.assertTrue(self.can())
        self.kernel.execute_for_scenario(self.blocker,'B',(UntilEndOfTurn('source',(SetColors(('G',)),)),))
        self.assertFalse(self.can());self.assertTrue(self.can(self.blocker,self.ally))
        self.kernel.execute_for_scenario(self.blocker,'B',(UntilEndOfTurn('source',(ModifyPT(0,-1),)),))
        self.assertTrue(self.can())

    def test_view_prepares_source_threshold_once_for_multiple_block_pairs(self):
        from unittest.mock import patch
        self.game();self.state.add_counters(self.ref,'+1/+1',2)
        second=self.state.add_card('other-blocker','body','B',Zone.BATTLEFIELD)
        view=CombatView(self.kernel)
        with patch.object(self.kernel,'_quantity',wraps=self.kernel._quantity) as quantity:
            for attacker in (self.ref,self.ally):
                for blocker in (self.blocker,second):self.assertFalse(view.can_block(view.card(blocker),view.card(attacker)))
            self.assertEqual(1,quantity.call_count)
