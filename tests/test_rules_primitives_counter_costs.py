"""Counter costs are exact, atomic resources, independent of counter additions."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import (CardProgram,CostSpec,CounterCost,ZoneCost,ManaCost,ActivatedProgram,
    GainLife,AddMana,CastSpec,CounterReplacement,Selector,validate)
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation,ResourcePayment,ZoneMove
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter


class CounterCostTests(unittest.TestCase):
    def game(self,cost=None,*,creature=False,extra=(),effects=(GainLife(2),),mana=False):
        cost=cost or CostSpec(counter_costs=(CounterCost('+1/+1',1),))
        self.program=CardProgram('source','Source',('Creature',) if creature else ('Artifact',),
            power=0 if creature else None,toughness=0 if creature else None,
            activated=(ActivatedProgram('use',cost,effects,mana_ability=mana),))
        self.programs=(self.program,*extra);self.state=RulesState(('A','B'))
        self.ref=self.state.add_card('source','source','A',Zone.BATTLEFIELD)
        self.state.add_counters(self.ref,'+1/+1',2)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def activate(self,payment=Payment()):
        return self.kernel.commit_action(self.kernel.quote_activation('use','A',self.ref,'use'),payment)

    def test_counters_mana_life_and_tap_commit_once_and_rejection_changes_nothing(self):
        self.game(CostSpec(ManaCost(1),life=3,tap_source=True,counter_costs=(CounterCost('+1/+1',2),)))
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.activate()
        self.assertEqual(before,self.kernel.snapshot())
        self.state.add_mana('A',('C',));self.activate(Payment((('C',1),)))
        self.assertEqual(37,self.state.life('A'));self.assertEqual((),self.state.mana_pool('A'))
        self.assertTrue(self.state.get(self.ref).tapped);self.assertEqual((),self.state.get(self.ref).counters)
        self.assertEqual((),self.kernel.stack[-1]['source']['counters'])
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.activate(Payment((('C',1),)))
        self.assertEqual(before,self.kernel.snapshot())
        self.kernel.pass_priority('A');self.kernel.pass_priority('B');self.assertEqual(39,self.state.life('A'))

    def test_unpayable_counter_cost_rejects_quote_before_other_resources(self):
        self.game(CostSpec(life=4,tap_source=True,counter_costs=(CounterCost('+1/+1',3),)))
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.activate()
        self.assertEqual(before,self.kernel.snapshot())

    def test_last_toughness_counter_cost_kills_source_but_ability_still_resolves(self):
        self.game(CostSpec(counter_costs=(CounterCost('+1/+1',2),)),creature=True)
        self.activate();self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('source')).zone)
        self.assertEqual(1,len(self.kernel.stack));self.assertEqual((),self.state.events[-1].before.counters)
        self.kernel.pass_priority('A');self.kernel.pass_priority('B');self.assertEqual(42,self.state.life('A'))

    def test_multiple_counter_kinds_pay_exactly_without_replacement_or_added_event(self):
        mod=CardProgram('double','Double',('Enchantment',),counter_replacements=(CounterReplacement('double',Selector(Zone.BATTLEFIELD),multiplier=2),))
        self.game(CostSpec(counter_costs=(CounterCost('+1/+1',1),CounterCost('charge',2))),extra=(mod,))
        self.state.add_card('double','double','A',Zone.BATTLEFIELD);self.state.add_counters(self.ref,'charge',3)
        self.activate();self.assertEqual((('+1/+1',1),('charge',1)),self.state.get(self.ref).counters)
        self.assertIsNone(self.kernel.pending_choice)
        self.assertFalse(any(e['kind'] in {'counters_added','counter_replacement_applied'} for e in self.kernel.semantic_events))

    def test_counter_paid_mana_ability_needs_no_stack_or_order_prompt(self):
        self.game(effects=(AddMana(('G',)),),mana=True);self.activate()
        self.assertEqual((),tuple(self.kernel.stack));self.assertEqual((('G',1),),self.state.mana_pool('A'))
        self.assertEqual((('+1/+1',1),),self.state.get(self.ref).counters)

    def test_adapter_archive_replays_payment_once_and_restored_resolution(self):
        self.game();adapter=RulesActorAdapter(self.kernel)
        command={'kind':'activate','revision':self.kernel.revision,'action_id':'use','source':self.ref.to_json(),
            'targets':[],'x_value':0,'payment':{'mana':{},'taps':[]},'ability_id':'use'}
        adapter.submit('A',command)
        replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.assertEqual(adapter.archive(),replay.archive())
        for actor in ('A','B'):
            command={'kind':'pass','revision':self.kernel.revision};adapter.submit(actor,command);replay.submit(actor,command)
        self.assertEqual(adapter.archive(),replay.archive());self.assertEqual(42,self.state.life('A'))

    def test_low_level_invalid_and_mixed_payments_are_atomic(self):
        self.game();before=self.state.snapshot()
        for rows in (((self.ref,'+1/+1',3),),((self.ref,'+1/+1',True),),((self.ref,'+1/+1',1),)*2):
            with self.assertRaises(RulesViolation):self.state.move((),'pay',payment=ResourcePayment('A',life=2,counters=rows))
            self.assertEqual(before,self.state.snapshot())
        with self.assertRaises(RulesViolation):self.state.move((ZoneMove(self.ref,Zone.GRAVEYARD),),'pay',payment=ResourcePayment('A',counters=((self.ref,'+1/+1',1),)))
        self.assertEqual(before,self.state.snapshot())

    def test_compiler_rejects_unrepresented_counter_costs(self):
        self.game()
        for costs in ([CounterCost('x',1)],(CounterCost('x',0),),(CounterCost('x',True),),(CounterCost('x',1),)*2):
            ability=replace(self.program.activated[0],cost=CostSpec(counter_costs=costs))
            with self.assertRaises(RulesViolation):validate(replace(self.program,activated=(ability,)))
        cost=CostSpec(counter_costs=(CounterCost('x',1),))
        with self.assertRaises(RulesViolation):validate(replace(self.program,cast=CastSpec(cost)))
        ability=replace(self.program.activated[0],cost=replace(cost,zone_costs=(ZoneCost('sac','sacrifice'),)))
        with self.assertRaises(RulesViolation):validate(replace(self.program,activated=(ability,)))

class MikaeusTests(unittest.TestCase):
    def game(self):
        from edh_gauntlet.rules_bundle import load_reviewed
        self.programs=tuple(r['program'] for r in load_reviewed().values())
        self.state=RulesState(('A','B'));self.kernel=RulesKernel(self.state,self.programs)

    def test_cast_x_and_summoning_readiness_share_normal_actions(self):
        self.game();ref=self.state.add_card('mikaeus','catalog:mikaeus-the-lunarch','A',Zone.HAND)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('W','C','C','C'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',ref,x_value=3),Payment((('C',3),('W',1))))
        self.kernel.pass_priority('A');self.kernel.pass_priority('B')
        ref=self.state.current('mikaeus');self.assertEqual((('+1/+1',3),),self.state.get(ref).counters)
        self.kernel.open_window_for_scenario('A')
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('grow','A',ref,'grow')
        self.state.add_card('draw','catalog:forest','A',Zone.LIBRARY);self.kernel.begin_turn_for_scenario('A')
        self.kernel.commit_action(self.kernel.quote_activation('grow','A',ref,'grow'),Payment())
        self.kernel.pass_priority('A');self.kernel.pass_priority('B')
        self.assertEqual((('+1/+1',4),),self.state.get(ref).counters)

    def test_last_counter_distributes_after_mikaeus_dies_with_scales(self):
        self.game();ref=self.state.add_card('mikaeus','catalog:mikaeus-the-lunarch','A',Zone.BATTLEFIELD)
        self.state.add_counters(ref,'+1/+1',1)
        mine=self.state.add_card('mine','catalog:llanowar-elves','A',Zone.BATTLEFIELD)
        theirs=self.state.add_card('theirs','catalog:llanowar-elves','B',Zone.BATTLEFIELD)
        self.state.add_card('scales','catalog:hardened-scales','A',Zone.BATTLEFIELD)
        self.state.add_card('draw','catalog:forest','A',Zone.LIBRARY);self.kernel.begin_turn_for_scenario('A')
        self.kernel.commit_action(self.kernel.quote_activation('distribute','A',ref,'distribute'),Payment())
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('mikaeus')).zone)
        self.assertEqual((),self.state.get(mine).counters)
        self.kernel.pass_priority('A');self.kernel.pass_priority('B')
        self.assertEqual((('+1/+1',2),),self.state.get(mine).counters)
        self.assertEqual((),self.state.get(theirs).counters)

if __name__=='__main__':unittest.main()

