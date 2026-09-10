"""Player life is explicit input to shared conditions and layer evaluation."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_characteristics import condition_holds,evaluate,evaluate_exhaustive,condition_selectors
from edh_gauntlet.rules_casting import Payment


class LifeConditionTests(unittest.TestCase):
    def setUp(self):
        self.programs=tuple(r['program'] for r in load_reviewed().values())
        self.state=RulesState(('A','B'));self.kernel=RulesKernel(self.state,self.programs)
        self.ref=self.state.add_card('paladin','catalog:twinblade-paladin','A',Zone.BATTLEFIELD)

    def drain(self):
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)

    def test_threshold_and_cache_follow_life_changes(self):
        self.assertIn('double_strike',self.kernel.effective(self.ref).keywords)
        self.state.lose_life_batch(('A',),15);self.assertIn('double_strike',self.kernel.effective(self.ref).keywords)
        self.state.lose_life_batch(('A',),1);self.assertNotIn('double_strike',self.kernel.effective(self.ref).keywords)
        self.state.gain_life('A',1);self.assertIn('double_strike',self.kernel.effective(self.ref).keywords)

    def test_current_controller_determines_life_and_source_is_only_recipient(self):
        other=self.state.add_card('other','catalog:llanowar-elves','A',Zone.BATTLEFIELD)
        self.state.lose_life_batch(('B',),20);self.state.change_control(self.ref,'B')
        self.assertNotIn('double_strike',self.kernel.effective(self.ref).keywords)
        self.assertNotIn('double_strike',self.kernel.effective(other).keywords)
        self.state.gain_life('B',5);self.assertIn('double_strike',self.kernel.effective(self.ref).keywords)

    def test_gain_event_places_one_counter_not_one_per_life(self):
        self.state.lose_life_batch(('A',),16)
        self.kernel.execute_for_scenario(self.ref,'A',(GainLife(3),));self.drain()
        self.assertEqual(4,self.kernel.effective(self.ref).power)
        self.assertIn('double_strike',self.kernel.effective(self.ref).keywords)
        self.kernel.execute_for_scenario(self.ref,'B',(GainLife(3),));self.drain()
        self.assertEqual(4,self.kernel.effective(self.ref).power)

    def test_compound_bounds_signed_values_and_missing_environment(self):
        obj=self.state.get(self.ref)
        condition=AllConditions((LifeCondition(-5,25),NotCondition(LifeCondition(26))))
        self.assertTrue(condition_holds(condition,obj,(),{},life_totals={'A':-3}))
        self.assertFalse(condition_holds(condition,obj,(),{},life_totals={'A':26}))
        self.assertEqual((),tuple(condition_selectors(condition)))
        with self.assertRaises(RulesViolation):condition_holds(condition,obj,(),{})
        with self.assertRaises(RulesViolation):evaluate(self.state.objects(),self.kernel.definitions)

    def test_layers_match_exhaustive_evaluation_with_nested_conditions(self):
        condition=AnyConditions((LifeCondition(maximum=24),CountCondition(Selector(Zone.BATTLEFIELD,types=('Land',)),1)))
        program=CardProgram('buff','Buff',('Enchantment',),continuous=(ContinuousProgram('boost',Selector(Zone.BATTLEFIELD,types=('Creature',)),(ModifyPT(2,2),),condition=condition),))
        self.kernel=RulesKernel(self.state,self.programs+(program,));self.state.add_card('buff','buff','A',Zone.BATTLEFIELD)
        for life in (40,24,25):
            totals={'A':life,'B':40};objects=self.state.objects()
            self.assertEqual(evaluate(objects,self.kernel.definitions,life_totals=totals),evaluate_exhaustive(objects,self.kernel.definitions,life_totals=totals))

    def test_resolution_condition_chooses_once_and_checkpoint_preserves_life(self):
        self.state.lose_life_batch(('A',),16)
        condition=LifeCondition(minimum=25)
        self.kernel.execute_for_scenario(self.ref,'A',(IfCondition(condition,(GainLife(10),),(GainLife(1),)),));self.drain()
        self.assertEqual(25,self.state.life('A'))
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertIn('double_strike',restored.effective(self.ref).keywords)

    def test_intervening_condition_rechecks_on_resolution(self):
        program=CardProgram('watcher','Watcher',('Enchantment',),abilities=(AbilityProgram('upkeep',EventPattern('step_began',step='upkeep',controller_only=True),(GainLife(9),),intervening_if=LifeCondition(25)),))
        self.kernel=RulesKernel(self.state,self.programs+(program,));self.state.add_card('watcher','watcher','A',Zone.BATTLEFIELD)
        self.kernel._collect_step('upkeep');self.kernel.advance();self.assertEqual(1,len(self.kernel.stack))
        self.state.lose_life_batch(('A',),16);self.drain();self.assertEqual(24,self.state.life('A'))

    def test_validation_roundtrip_and_printed_cast_cost(self):
        for c in (LifeCondition(),LifeCondition(True),LifeCondition(3,2),LifeCondition(maximum=1.5)):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Sorcery',),spell_effects=(IfCondition(c,(GainLife(1),)),)))
        self.assertEqual(LifeCondition(25),decode(encode(LifeCondition(25))))
        ref=self.state.add_card('spell','catalog:twinblade-paladin','A',Zone.HAND)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('W','C','C','C'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',ref),Payment((('W',1),('C',3))));self.drain()
        self.assertEqual((),self.state.mana_pool('A'));self.assertIn('double_strike',self.kernel.effective(self.state.current('spell')).keywords)

    def test_sacrifice_with_life_payment_uses_pre_event_life_for_leaves_trigger(self):
        program=CardProgram('relic','Relic',('Artifact',),
            activated=(ActivatedProgram('sac',CostSpec(life=1,zone_costs=(ZoneCost('sac','sacrifice'),)),(GainLife(0),)),),
            abilities=(AbilityProgram('leaves',EventPattern('zone_changed',from_zone=Zone.BATTLEFIELD,subject='self'),
                (GainLife(9),),occurrence_condition=LifeCondition(25)),))
        self.kernel=RulesKernel(self.state,self.programs+(program,))
        relic=self.state.add_card('relic','relic','A',Zone.BATTLEFIELD)
        self.state.lose_life_batch(('A',),15);self.kernel.open_window_for_scenario('A')
        self.kernel.commit_action(self.kernel.quote_activation('sac','A',relic,'sac'),Payment())
        self.assertEqual(24,self.state.life('A'));self.assertEqual(2,len(self.kernel.stack))
        self.drain();self.assertEqual(33,self.state.life('A'))
