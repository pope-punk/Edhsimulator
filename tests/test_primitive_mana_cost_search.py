import unittest
from edh_gauntlet.rules_program import (CardProgram,ActivatedProgram,CostSpec,ManaCost,AddMana,ChooseMana,GainLife,CounterCost,ZoneCost,Selector)
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.primitive_autotap import payment

class ManaCostSearchTests(unittest.TestCase):
    def game(self,costs,life=40,amount=1):
        self.state=RulesState(('A','B'),starting_life=life)
        programs=[CardProgram('goal','Goal',('Artifact',),activated=(ActivatedProgram('use',CostSpec(mana=ManaCost(generic=amount)),(GainLife(1),)),))]
        self.goal=self.state.add_card('goal','goal','A',Zone.BATTLEFIELD);self.refs=[]
        for i,cost in enumerate(costs):
            name='mana'+str(i)
            programs.append(CardProgram(name,name,('Artifact',),activated=(ActivatedProgram('mana',cost,(ChooseMana((('W',),('B',))),),mana_ability=True),)))
            self.refs.append(self.state.add_card(name,name,'A',Zone.BATTLEFIELD))
        self.kernel=RulesKernel(self.state,programs);self.kernel.open_window_for_scenario('A')
        self.command={'kind':'activate','source':self.goal.to_json(),'ability_id':'use','targets':[],'x_value':0,'action_id':'goal-use','autotap':{}}

    def pay(self):
        command=dict(self.command);command['payment']=payment(self.kernel,'A',command);command.pop('autotap');command['revision']=self.kernel.revision
        RulesActorAdapter(self.kernel)._execute('A',command)
        return command

    def test_cumulative_life_cost_cannot_exceed_available_life(self):
        self.game([CostSpec(tap_source=True,life=1)]*2,life=1,amount=2)
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.pay()
        self.assertEqual(before,self.kernel.snapshot())

    def test_counter_removal_cost_is_paid_once(self):
        self.game([CostSpec(tap_source=True,counter_costs=(CounterCost('charge',1),))])
        self.state.add_counters(self.refs[0],'charge',1)
        self.pay();self.assertFalse(dict(self.state.get(self.refs[0]).counters).get('charge',0))

    def test_other_permanent_sacrifice_is_bound_to_the_payment(self):
        self.game([CostSpec(tap_source=True,zone_costs=(ZoneCost('food','sacrifice',Selector(Zone.BATTLEFIELD,types=('Artifact',),relation='controlled',exclude_source=True)),))])
        # Goal cannot be sacrificed: that would invalidate the announced action.
        food=self.state.add_card('food','mana0','A',Zone.BATTLEFIELD)
        self.state.set_tapped_batch((food,),True)
        self.pay()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current(food.card_id)).zone)
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.goal).zone)

    def test_invalid_final_payment_is_atomic_after_life_cost(self):
        self.game([CostSpec(tap_source=True,life=1)])
        command=dict(self.command);command['payment']=payment(self.kernel,'A',command);command.pop('autotap');command['revision']=self.kernel.revision
        command['payment']['mana']={};before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):RulesActorAdapter(self.kernel)._execute('A',command)
        self.assertEqual(before,self.kernel.snapshot())

    def test_resolution_window_can_use_life_paying_mana(self):
        from edh_gauntlet.rules_program import PayMana
        self.game([CostSpec(tap_source=True,life=1)])
        self.kernel.execute_for_scenario(self.goal,'A',(PayMana(ManaCost(generic=1),(GainLife(2),)),))
        command={'kind':'pay_mana','request_id':self.kernel.mana_payment['id'],'action_id':'resolve-pay','autotap':{},'revision':self.kernel.revision}
        command['payment']=payment(self.kernel,'A',command);command.pop('autotap')
        RulesActorAdapter(self.kernel)._execute('A',command)
        self.assertIsNone(self.kernel.mana_payment)
        self.assertEqual(41,self.state.life('A'))

    def test_tapping_trigger_is_placed_after_the_paid_action(self):
        from edh_gauntlet.rules_program import AbilityProgram,EventPattern,LoseLife
        from dataclasses import replace
        self.game([CostSpec(tap_source=True)])
        programs=tuple(replace(p,abilities=(AbilityProgram('hurt',EventPattern('becomes_tapped',subject='self'),(LoseLife("controller",1),)),)) if p.definition_id=='mana0' else p for p in self.kernel._base_definitions.values())
        self.kernel=RulesKernel(self.state,programs);self.kernel.open_window_for_scenario('A')
        self.pay()
        self.assertEqual(2,len(self.kernel.stack))
        self.assertEqual('use',self.kernel.stack[0]['ability_id'])
        self.assertEqual('hurt',self.kernel.stack[1]['ability_id'])
