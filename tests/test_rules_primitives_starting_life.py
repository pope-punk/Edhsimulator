"""Starting life is immutable game state, separate from mutable current life."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_characteristics import condition_holds,evaluate,evaluate_exhaustive
from edh_gauntlet.rules_actor import project_actor
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_casting import Payment


class StartingLifeTests(unittest.TestCase):
    def make(self,starting=40):
        self.programs=tuple(r['program'] for r in load_reviewed().values())
        self.state=RulesState(('A','B'),starting_life=starting);self.kernel=RulesKernel(self.state,self.programs)
        self.ref=self.state.add_card('elixir','catalog:cosmos-elixir','A',Zone.BATTLEFIELD)
        for i in range(4):self.state.add_card('card'+str(i),'catalog:forest','A',Zone.LIBRARY)

    def end_step(self,actor):
        self.kernel.active=actor;self.kernel._begin_phase('end_step');self.kernel.advance()

    def drain(self):
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)

    def test_starting_totals_survive_changes_restore_and_are_public(self):
        totals={'A':20,'B':40};self.make(totals);totals['A']=100
        self.state.gain_life('A',3);self.state.lose_life_batch(('B',),7)
        restored=RulesState.restore(self.state.snapshot())
        self.assertEqual((20,40),(restored.starting_life('A'),restored.starting_life('B')))
        self.assertEqual((23,33),(restored.life('A'),restored.life('B')))
        for actor in ('A','B'):
            rows=project_actor(self.kernel,actor)['players'];self.assertEqual([20,40],[r['starting_life'] for r in rows])

    def test_invalid_starting_totals_and_missing_checkpoint_field_fail(self):
        for value in (True,0,-1,20.5,{'A':20},{'A':20,'B':False},{'A':20,'B':40,'C':40}):
            with self.assertRaises(RulesViolation):RulesState(('A','B'),starting_life=value)
        self.make();snapshot=self.state.snapshot();del snapshot['starting_life']
        with self.assertRaises(RulesViolation):RulesState.restore(snapshot)

    def test_equal_or_below_gains_two_without_drawing(self):
        for starting in (20,40):
            for lost in (0,3):
                self.make(starting);self.state.lose_life_batch(('A',),lost)
                self.end_step('A');self.assertEqual(1,len(self.kernel.stack));self.drain()
                self.assertEqual(starting-lost+2,self.state.life('A'));self.assertEqual(0,len(self.state.zone('A',Zone.HAND)))

    def test_above_starting_draws_even_at_nonstandard_life(self):
        self.make(20);self.state.gain_life('A',1);self.end_step('A');self.drain()
        self.assertEqual(21,self.state.life('A'));self.assertEqual(1,len(self.state.zone('A',Zone.HAND)))
        self.end_step('B');self.assertFalse(self.kernel.stack)

    def test_condition_is_checked_at_resolution_in_both_directions(self):
        for initially_above in (False,True):
            self.make()
            if initially_above:self.state.gain_life('A',1)
            self.end_step('A');self.assertEqual(1,len(self.kernel.stack))
            if initially_above:self.state.lose_life_batch(('A',),1)
            else:self.state.gain_life('A',1)
            adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
            while self.kernel.stack:
                command={'kind':'pass','revision':self.kernel.revision};actor=self.kernel.priority
                adapter.submit(actor,command);replay.submit(actor,command)
            self.assertEqual(adapter.archive(),replay.archive())
            self.assertEqual(0 if initially_above else 1,len(self.state.zone('A',Zone.HAND)))
            self.assertEqual(42 if initially_above else 41,self.state.life('A'))

    def test_relative_condition_requires_explicit_start_and_handles_negative_offsets(self):
        self.make(20);obj=self.state.get(self.ref);condition=LifeCondition(-3,-1,True)
        self.assertTrue(condition_holds(condition,obj,(),{},life_totals={'A':18},starting_life_totals={'A':20}))
        self.assertFalse(condition_holds(condition,obj,(),{},life_totals={'A':20},starting_life_totals={'A':20}))
        with self.assertRaises(RulesViolation):condition_holds(condition,obj,(),{},life_totals={'A':18})
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Sorcery',),spell_effects=(IfCondition(LifeCondition(1,relative_to_starting=1),(Draw(),)),)))

    def test_relative_layers_follow_current_controller_and_match_exhaustive(self):
        self.make({'A':20,'B':40})
        buff=CardProgram('buff','Buff',('Creature',),power=2,toughness=2,continuous=(ContinuousProgram('boost',Selector(Zone.BATTLEFIELD,types=('Creature',)),(ModifyPT(2,2),),subject='self',condition=LifeCondition(1,relative_to_starting=True)),))
        self.kernel=RulesKernel(self.state,self.programs+(buff,));ref=self.state.add_card('buff','buff','A',Zone.BATTLEFIELD)
        self.state.gain_life('A',1);self.assertEqual(4,self.kernel.effective(ref).power)
        self.state.change_control(ref,'B');self.assertEqual(2,self.kernel.effective(ref).power)
        self.state.gain_life('B',1);self.assertEqual(4,self.kernel.effective(ref).power)
        kwargs={'life_totals':{p:self.state.life(p) for p in self.state.players},'starting_life_totals':{p:self.state.starting_life(p) for p in self.state.players}}
        self.assertEqual(evaluate(self.state.objects(),self.kernel.definitions,**kwargs),evaluate_exhaustive(self.state.objects(),self.kernel.definitions,**kwargs))

    def test_printed_cast_cost(self):
        self.make();ref=self.state.add_card('spell','catalog:cosmos-elixir','A',Zone.HAND)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('C',)*4)
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',ref),Payment((('C',4),)));self.drain()
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('spell')).zone);self.assertEqual((),self.state.mana_pool('A'))
