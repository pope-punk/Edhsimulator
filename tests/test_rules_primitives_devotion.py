"""Devotion counts copied mana symbols, with once-per-symbol hybrid counting."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_characteristics import condition_holds,evaluate,evaluate_exhaustive
from edh_gauntlet.rules_replacements import ZoneProposal
from edh_gauntlet.rules_adapter import RulesActorAdapter

class DevotionTests(unittest.TestCase):
    def game(self,zone=Zone.BATTLEFIELD):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(
            CardProgram('hybrid','Hybrid',('Enchantment',),cast=CastSpec(CostSpec(ManaCost(1,('R/G',)*3)))),
            CardProgram('pair','Pair',('Enchantment',),cast=CastSpec(CostSpec(ManaCost(2,('R','G'))))),
            CardProgram('body','Body',('Creature',),power=3,toughness=5),
            CardProgram('negative','Negative',('Creature',),power=-2,toughness=5))
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('x','catalog:xenagos-god-of-revels','A',zone)
        self.body=self.state.add_card('body','body','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
    def devotion(self,colors,minimum):
        return condition_holds(DevotionCondition(colors,minimum),self.state.get(self.ref),self.state.objects(),self.kernel.characteristics())
    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)
    def combat(self,target):
        self.kernel._begin_phase('begin_combat');self.kernel.advance();q=self.kernel.pending_choice
        self.assertNotIn(self.ref,{o.ref for o in q.options})
        self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.ref==target)])
    def test_hybrid_symbols_count_once_for_combined_devotion(self):
        self.game();self.state.add_card('h','hybrid','A',Zone.BATTLEFIELD)
        self.assertTrue(self.devotion(('R','G'),5));self.assertFalse(self.devotion(('R','G'),6))
        self.assertTrue(self.devotion(('R',),4));self.assertTrue(self.devotion(('G',),4))
        self.assertNotIn('Creature',self.kernel.effective(self.ref).types)
        self.state.add_card('p','pair','A',Zone.BATTLEFIELD)
        self.assertIn('Creature',self.kernel.effective(self.ref).types);self.assertEqual(6,self.kernel.effective(self.ref).power)
    def test_control_phasing_and_off_battlefield_symbols(self):
        self.game();hybrid=self.state.add_card('h','hybrid','A',Zone.BATTLEFIELD);pair=self.state.add_card('p','pair','A',Zone.BATTLEFIELD)
        self.state.add_card('hand','hybrid','A',Zone.HAND);self.state.add_card('enemy','hybrid','B',Zone.BATTLEFIELD)
        self.assertTrue(self.devotion(('R','G'),7));self.assertFalse(self.devotion(('R','G'),8))
        self.state.phase(pair,True);self.assertFalse(self.devotion(('R','G'),7))
        self.state.phase(pair,False);self.state.change_control(hybrid,'B');self.assertFalse(self.devotion(('R','G'),7))
        self.state.change_control(self.ref,'B');self.assertTrue(self.devotion(('R','G'),8))
    def test_copied_costs_count_but_color_changes_do_not(self):
        self.game();copy=self.state.add_card('copy','body','A',Zone.HAND)
        self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,'A',copied_definition='hybrid'),),'scenario_copy')
        self.assertTrue(self.devotion(('R','G'),5))
        self.kernel.execute_for_scenario(self.state.current('copy'),'A',(UntilEndOfTurn('source',(SetColors(('U',)),)),))
        self.assertTrue(self.devotion(('R','G'),5));self.assertFalse(self.devotion(('U',),1))
        self.assertEqual(evaluate(self.state.objects(),self.kernel.definitions),evaluate_exhaustive(self.state.objects(),self.kernel.definitions))
    def test_entry_lookahead_excludes_incoming_symbols_post_entry_includes_them(self):
        self.game(Zone.HAND);self.state.add_card('h','hybrid','A',Zone.BATTLEFIELD);self.state.add_card('p','pair','A',Zone.BATTLEFIELD)
        proposal=ZoneProposal(self.state.get(self.ref),Zone.BATTLEFIELD,'A')
        self.assertNotIn('Creature',self.kernel._proposal_view(proposal)[1].types)
        self.assertIn('Creature',self.kernel.effective(self.ref).types)
        self.state.add_mana('A',('C','C','C','R','G'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.ref),Payment((('C',3),('R',1),('G',1))))
        self.drain();self.ref=self.state.current('x');self.assertIn('Creature',self.kernel.effective(self.ref).types)
        self.assertIn('God',self.kernel.effective(self.ref).subtypes)
    def test_combat_bonus_freezes_at_resolution_then_expires(self):
        self.game();self.combat(self.body);self.state.add_counters(self.body,'+1/+1',2)
        self.drain();view=self.kernel.effective(self.body);self.assertEqual((10,12),(view.power,view.toughness));self.assertIn('haste',view.keywords)
        self.state.add_counters(self.body,'+1/+1',1);self.assertEqual(11,self.kernel.effective(self.body).power)
        self.kernel._finish_cleanup_actions();self.assertEqual(6,self.kernel.effective(self.body).power);self.assertNotIn('haste',self.kernel.effective(self.body).keywords)
    def test_negative_power_produces_zero_bonus_and_source_may_depart(self):
        self.game();negative=self.state.add_card('n','negative','A',Zone.BATTLEFIELD);self.combat(negative)
        self.state.move((ZoneMove(self.ref,Zone.HAND),),'scenario_response');self.drain()
        view=self.kernel.effective(negative);self.assertEqual((-2,5),(view.power,view.toughness));self.assertIn('haste',view.keywords)
    def test_pending_combat_choice_replays_and_opponents_combat_does_not_trigger(self):
        self.game();self.kernel._begin_phase('begin_combat');self.kernel.advance();a=RulesActorAdapter(self.kernel);b=RulesActorAdapter.replay(a.archive(),self.programs)
        q=self.kernel.pending_choice;cmd={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[0]}
        a.submit('A',cmd);b.submit('A',cmd);self.drain();self.drain(b.kernel);self.assertEqual(a.archive(),b.archive())
        self.game();self.kernel.open_window_for_scenario('B');self.kernel._begin_phase('begin_combat');self.kernel.advance();self.assertIsNone(self.kernel.pending_choice);self.assertFalse(self.kernel.stack)
    def test_last_known_mana_symbols_restore_as_immutable_values(self):
        self.game();self.kernel.execute_for_scenario(self.ref,'A',(Move('source',Zone.GRAVEYARD),))
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.assertEqual(self.kernel.last_known,restored.last_known)
        self.assertEqual(('R','G'),restored.last_known[self.ref][1].mana_symbols)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())

    def test_closed_predicate_validation_and_serialization(self):
        self.game();condition=DevotionCondition(('R','G'),7);self.assertEqual(condition,decode(encode(condition)))
        for bad in (DevotionCondition((),1),DevotionCondition(('C',),1),DevotionCondition(('R','R'),1),DevotionCondition(['R'],1),DevotionCondition(('R',),True),DevotionCondition(('R',),-1)):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Enchantment',),continuous=(ContinuousProgram('bad',Selector(Zone.BATTLEFIELD),(AddKeywords(('haste',)),),condition=bad),)))

if __name__=='__main__':unittest.main()
