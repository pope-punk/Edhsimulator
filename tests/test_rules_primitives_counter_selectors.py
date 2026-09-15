"""Shared counter predicates support counted, retained creature groups."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_characteristics import evaluate,evaluate_exhaustive
from edh_gauntlet.rules_adapter import RulesActorAdapter


class CounterSelectorTests(unittest.TestCase):
    def game(self):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(CardProgram('body','Body',('Creature',),power=2,toughness=2),CardProgram('rock','Rock',('Artifact',)))
        self.state=RulesState(('A','B'));self.kernel=RulesKernel(self.state,self.programs)
        self.spell=self.state.add_card('spell','catalog:inspiring-call','A',Zone.HAND)
        self.bodies=[self.state.add_card(str(i),'body','A' if i<3 else 'B',Zone.BATTLEFIELD) for i in range(4)]
        for ref,n in zip(self.bodies,(1,5,0,2)):
            self.state.add_counters(ref,'+1/+1',n)
        self.rock=self.state.add_card('rock','rock','A',Zone.BATTLEFIELD);self.state.add_counters(self.rock,'+1/+1',1)
        for i in range(4):self.state.add_card('draw'+str(i),'catalog:forest','A',Zone.LIBRARY)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('G','C','C'))

    def cast(self):
        self.kernel.commit_action(self.kernel.quote_cast('call','A',self.spell),Payment((('G',1),('C',2))))

    def drain(self):
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)

    def test_draws_per_creature_and_buffs_only_qualifying_controlled_creatures(self):
        self.game();self.cast();self.drain()
        self.assertEqual(2,len(self.state.zone('A',Zone.HAND)));self.assertEqual((),self.state.mana_pool('A'))
        for ref,expected in zip(self.bodies,(True,True,False,False)):
            self.assertEqual(expected,'indestructible' in self.kernel.effective(ref).keywords)
        self.assertNotIn('indestructible',self.kernel.effective(self.rock).keywords)

    def test_resolution_uses_current_counts_then_retains_group_when_counters_change(self):
        self.game();self.cast();self.state.add_counters(self.bodies[2],'+1/+1',1);self.drain()
        self.assertEqual(3,len(self.state.zone('A',Zone.HAND)))
        self.state.add_counters(self.bodies[0],'-1/-1',1);self.state.cancel_opposing_counters(self.bodies[0])
        self.assertIn('indestructible',self.kernel.effective(self.bodies[0]).keywords)
        self.state.add_counters(self.bodies[3],'+1/+1',1)
        self.assertNotIn('indestructible',self.kernel.effective(self.bodies[3]).keywords)
        self.kernel._finish_cleanup_actions()
        self.assertNotIn('indestructible',self.kernel.effective(self.bodies[0]).keywords)

    def test_empty_group_draws_nothing_and_phased_creatures_do_not_count(self):
        self.game()
        for ref in self.bodies[:2]:self.state.phase(ref,True)
        self.cast();self.drain();self.assertEqual(0,len(self.state.zone('A',Zone.HAND)))
        self.assertEqual(4,len(self.state.zone('A',Zone.LIBRARY)))

    def test_actor_cast_and_replay_preserve_draws_and_temporary_group(self):
        self.game();adapter=RulesActorAdapter(self.kernel)
        adapter.submit('A',{'kind':'cast','revision':self.kernel.revision,'action_id':'call','source':self.spell.to_json(),'targets':[],'x_value':0,'payment':{'mana':{'G':1,'C':2},'taps':[]}})
        while self.kernel.stack:adapter.submit(self.kernel.priority,{'kind':'pass','revision':self.kernel.revision})
        restored=RulesActorAdapter.replay(adapter.archive(),self.programs)
        for actor in ('A','B'):self.assertEqual(adapter.packet(actor),restored.packet(actor))

    def test_counter_predicate_static_layers_update_and_match_exhaustive(self):
        sel=Selector(Zone.BATTLEFIELD,types=('Creature',),counters=(CounterRange('charge',2,3),))
        buff=CardProgram('buff','Buff',('Enchantment',),continuous=(ContinuousProgram('boost',sel,(ModifyPT(3,3),)),))
        state=RulesState(('A','B'));ref=state.add_card('body','body','A',Zone.BATTLEFIELD);state.add_card('buff','buff','A',Zone.BATTLEFIELD)
        programs=(CardProgram('body','Body',('Creature',),power=2,toughness=2),buff);kernel=RulesKernel(state,programs)
        for count,expected in ((0,2),(1,2),(2,5),(3,5),(4,2)):
            if count:state.add_counters(ref,'charge',1)
            self.assertEqual(expected,kernel.effective(ref).power)
            self.assertEqual(evaluate(state.objects(),kernel.definitions),evaluate_exhaustive(state.objects(),kernel.definitions))

    def test_range_validation_and_zero_counter_absence(self):
        self.game();source=self.state.get(self.spell)
        zero=Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled',counters=(CounterRange('+1/+1',0,0),))
        self.assertEqual([self.bodies[2]],[o.ref for o in self.kernel._query(zero,{'source':source.to_json(),'controller':'A'})])
        for ranges in ((CounterRange('',1),),(CounterRange('charge',True),),(CounterRange('charge',-1),),(CounterRange('charge',3,2),),(CounterRange('charge',None,None),),(CounterRange('charge'),CounterRange('charge'))):
            program=CardProgram('bad','Bad',('Instant',),spell_targets=TargetSpec(replace(zero,counters=ranges)),spell_effects=(Damage('target',1),))
            with self.assertRaises(RulesViolation):validate(program)
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),spell_targets=TargetSpec(replace(zero,zone=Zone.HAND)),spell_effects=(Damage('target',1),)))
        self.assertEqual(zero,decode(encode(zero)))
