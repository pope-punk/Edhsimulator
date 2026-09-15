"""Static mana classification must distinguish zero formulas from zero board values."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class ConstantManaTests(unittest.TestCase):
    def game(self,amount,mana,effects=()):
        ability=ActivatedProgram('use',CostSpec(tap_source=True),(ProduceMana(amount,('G',)),)+effects,mana_ability=mana)
        self.program=validate(CardProgram('rock','Rock',('Artifact',),activated=(ability,)))
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('rock','rock','B',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,(self.program,));self.kernel.open_window_for_scenario('A',priority_actor='B')
    def activate(self):self.kernel.commit_action(self.kernel.quote_activation('use','B',self.ref,'use'),Payment())
    def drain(self,kernel):
        while kernel.stack:kernel.pass_priority(kernel.priority)

    def test_provably_zero_production_uses_stack_even_with_other_effects(self):
        count=CountObjects(Selector(Zone.BATTLEFIELD,types=('Land',)))
        for amount in (0,ScaledValue(count,0),DividedValue(1,2),DividedValue(ScaledValue(3,0),2,'up')):
            with self.assertRaises(RulesViolation):self.game(amount,True)
            self.game(amount,False,(GainLife(2),));self.activate()
            self.assertEqual(40,self.state.life('B'));self.assertEqual(1,len(self.kernel.stack));self.assertFalse(self.state.mana_pool('B'))
            self.drain(self.kernel);self.assertEqual(42,self.state.life('B'))

    def test_dynamic_zero_board_values_remain_mana_abilities(self):
        count=CountObjects(Selector(Zone.BATTLEFIELD,types=('Land',)))
        for amount in (count,ScaledValue(count,2),DividedValue(count,2)):
            self.game(amount,True,(GainLife(2),));self.activate()
            self.assertFalse(self.kernel.stack);self.assertFalse(self.state.mana_pool('B'))
            self.assertEqual(42,self.state.life('B'));self.assertEqual('B',self.kernel.priority)

    def test_constant_positive_rounding_and_scaling_produce_immediately(self):
        for amount,expected in ((DividedValue(1,2,'up'),1),(ScaledValue(DividedValue(5,2),3),6)):
            self.game(amount,True);self.activate();self.assertFalse(self.kernel.stack)
            self.assertEqual({'G':expected},dict(self.state.mana_pool('B')))

    def test_provably_zero_library_formulas_do_not_cross_library_boundary(self):
        count=CountObjects(Selector(Zone.BATTLEFIELD,types=('Land',)))
        for effect in (Draw(DividedValue(1,2)),Mill(ScaledValue(count,0)),Surveil(0)):
            self.game(1,True,(effect,));self.activate();self.assertFalse(self.kernel.stack)
            self.assertEqual({'G':1},dict(self.state.mana_pool('B')))
        for effect in (Draw(count),Mill(DividedValue(count,2)),Draw(DividedValue(1,2,'up'))):
            with self.assertRaises(RulesViolation):self.game(1,True,(effect,))

    def test_other_immediate_branches_and_delayed_bodies_are_classified_separately(self):
        zero=ProduceMana(0,('G',));positive=AddMana(('U',))
        base=ActivatedProgram('use',CostSpec(),(May((zero,),otherwise=(positive,)),),mana_ability=True)
        validate(CardProgram('rock','Rock',('Artifact',),activated=(base,)))
        delayed=DelayedTrigger(EventPattern('step_began',step='upkeep'),(positive,))
        self.assertFalse(activation_is_mana(replace(base,effects=(zero,delayed),mana_ability=False)))
        # Static folding must not hide invalid or unbound operands from validation.
        with self.assertRaises(RulesViolation):self.game(ScaledValue(EventAmount(),0),False)
        with self.assertRaises(RulesViolation):self.game(DividedValue(0,0),False)

    def test_stack_resolution_and_optional_choice_replay_preserve_classification(self):
        self.game(0,False,(May((GainLife(2),)),));self.activate()
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),(self.program,))
        for kernel in (self.kernel,replay.kernel):self.drain(kernel)
        self.assertEqual(adapter.archive(),replay.archive());q=self.kernel.pending_choice
        cmd={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[0]}
        adapter.submit('B',cmd);replay.submit('B',cmd);self.assertEqual(adapter.archive(),replay.archive())
        self.assertEqual(42,self.state.life('B'))

if __name__=='__main__':unittest.main()
