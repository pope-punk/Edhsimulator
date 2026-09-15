"""Cast event numbers survive source removal and remain distinct from action X."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState, Zone, RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed


class EventXTests(unittest.TestCase):
    def game(self, x, extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+tuple(extra)
        self.state=RulesState(('A','B'));self.kernel=RulesKernel(self.state,self.programs)
        self.ref=self.state.add_card('krasis','catalog:hydroid-krasis','A',Zone.HAND)
        for i in range(8):self.state.add_card('library'+str(i),'catalog:forest','A',Zone.LIBRARY)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('G','U')+('C',)*x)
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.ref,x_value=x),Payment((('G',1),('U',1))+((('C',x),) if x else ())))

    def drain(self):
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)

    def test_odd_x_rounds_each_benefit_down_and_enters_with_full_x(self):
        self.game(5)
        packet=RulesActorAdapter(self.kernel).packet('B')
        self.assertEqual([5],[f['event_x'] for f in packet['stack'] if 'event_x' in f])
        self.drain()
        self.assertEqual(42,self.state.life('A'));self.assertEqual(2,len(self.state.objects(Zone.HAND)))
        obj=self.state.get(self.state.current('krasis'))
        self.assertEqual(5,dict(obj.counters)['+1/+1']);self.assertEqual(Zone.BATTLEFIELD,obj.zone)

    def test_zero_x_gains_and_draws_zero_then_dies(self):
        self.game(0);self.drain()
        self.assertEqual(40,self.state.life('A'));self.assertEqual(0,len(self.state.objects(Zone.HAND)))
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('krasis')).zone)

    def test_countered_spell_keeps_cast_benefit_and_checkpoint_value(self):
        self.game(5)
        counter=self.state.add_card('counter','catalog:counterspell','A',Zone.HAND)
        self.state.add_mana('A',('U','U'))
        self.kernel.commit_action(self.kernel.quote_cast('counter','A',counter,(self.state.current('krasis'),)),Payment((('U',2),)))
        replay=RulesActorAdapter.replay(RulesActorAdapter(self.kernel).archive(),self.programs)
        while self.kernel.stack:
            actor=self.kernel.priority
            self.kernel.pass_priority(actor);replay.kernel.pass_priority(actor)
        self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot())
        self.assertEqual(42,self.state.life('A'));self.assertEqual(2,len(self.state.objects(Zone.HAND)))
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('krasis')).zone)

    def test_observer_uses_announced_spell_x_not_its_own(self):
        observer=CardProgram('observer','Observer',('Enchantment',),abilities=(AbilityProgram('watch',EventPattern('spell_cast'),(GainLife(EventX()),)),))
        self.game(3,(observer,));self.drain()
        self.state.add_card('observer','observer','B',Zone.BATTLEFIELD)
        self.kernel.open_window_for_scenario('A')
        second=self.state.add_card('second','catalog:hydroid-krasis','A',Zone.HAND)
        self.state.add_mana('A',('G','U')+('C',)*7)
        self.kernel.commit_action(self.kernel.quote_cast('second','A',second,x_value=7),Payment((('G',1),('U',1),('C',7))))
        self.drain();self.assertEqual(47,self.state.life('B'))

    def test_division_rounding_and_nested_values(self):
        self.game(2);self.drain();ref=self.state.current('krasis')
        self.kernel.execute_for_scenario(ref,'A',(GainLife(DividedValue(5,2,'up')),GainLife(DividedValue(ScaledValue(5,3),2))))
        self.assertEqual(51,self.state.life('A'))

    def test_compiler_rejects_unbound_values_and_invalid_division(self):
        base=CardProgram('test','Test',('Sorcery',))
        for value in (EventX(),DividedValue(1,0),DividedValue(1,True),DividedValue(1,2,'nearest')):
            with self.assertRaises(RulesViolation):validate(replace(base,spell_effects=(GainLife(value),)))
        validate(replace(base,abilities=(AbilityProgram('entry',EventPattern('zone_changed',to_zone=Zone.BATTLEFIELD),(GainLife(EventX()),)),)))
        with self.assertRaises(RulesViolation):validate(replace(base,abilities=(AbilityProgram('cast',EventPattern('spell_cast'),(GainLife(ChosenX()),)),)))
