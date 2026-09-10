"""Kami composes existing counter replacements and power-based mana production."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class KamiTests(unittest.TestCase):
    def game(self,zone=Zone.BATTLEFIELD,extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+tuple(extra)
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('kami','catalog:kami-of-whispered-hopes','A',zone)
        self.state.start_turn('A');self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def activate(self,actor='A'):
        self.kernel.open_window_for_scenario(actor)
        return self.kernel.commit_action(self.kernel.quote_activation('mana',actor,self.ref,'mana'),Payment())

    def test_printed_cast_and_newly_entered_tap_restriction(self):
        self.game(Zone.HAND);self.state.add_mana('A',('C','C','G'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.ref),Payment((('C',2),('G',1))))
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
        self.ref=self.state.current('kami');self.assertEqual(1,self.kernel.effective(self.ref).power)
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('mana','A',self.ref,'mana')
        self.assertEqual(before,self.kernel.snapshot());self.assertEqual((),self.state.mana_pool('A'))

    def test_replacement_includes_self_and_noncreatures_but_not_other_kinds_or_opponents(self):
        self.game()
        for i,(owner,kind,amount,expected) in enumerate((('A','+1/+1',1,2),('B','+1/+1',1,1),('A','charge',1,1),('A','+1/+1',0,0))):
            ref=self.state.add_card(str(i),'catalog:forest',owner,Zone.BATTLEFIELD)
            self.kernel.execute_for_scenario(ref,owner,(AddCounters('source',kind,amount),))
            self.assertEqual(expected,dict(self.state.get(ref).counters).get(kind,0))
        self.kernel.execute_for_scenario(self.ref,'A',(AddCounters('source','+1/+1',1),))
        self.assertEqual(3,self.kernel.effective(self.ref).power)

    def test_mana_uses_derived_power_one_color_and_resumes_exactly_once(self):
        self.game();self.kernel.execute_for_scenario(self.ref,'A',(AddCounters('source','+1/+1',1),UntilEndOfTurn('source',(ModifyPT(2,0),))))
        q=self.activate();self.assertEqual('mana_choice',q.kind);self.assertEqual({'W','U','B','R','G'},{o.key for o in q.options})
        self.assertFalse(self.kernel.stack);self.assertTrue(self.state.get(self.ref).tapped)
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        command={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[1]}
        adapter.submit('A',command);replay.submit('A',command)
        self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot());self.assertEqual((('U',5),),self.state.mana_pool('A'))
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):adapter.submit('A',command)
        self.assertEqual(before,self.kernel.snapshot())

    def test_zero_and_negative_power_produce_no_mana_or_choice(self):
        for power in (0,-2):
            self.game();self.kernel.execute_for_scenario(self.ref,'A',(UntilEndOfTurn('source',(SetPT(power,2),)),))
            self.assertIsNone(self.activate());self.assertEqual((),self.state.mana_pool('A'));self.assertTrue(self.state.get(self.ref).tapped)

    def test_noncommuting_replacements_preserve_chosen_order_across_checkpoint(self):
        double=CardProgram('double','Double',('Enchantment',),counter_replacements=(CounterReplacement('double',Selector(Zone.BATTLEFIELD),kind='+1/+1',multiplier=2),))
        for first,expected in (('Kami',4),('Double',3)):
            self.game(extra=(double,));self.state.add_card('double','double','A',Zone.BATTLEFIELD)
            before=self.state.snapshot();q=self.kernel.execute_for_scenario(self.ref,'A',(AddCounters('source','+1/+1',1),))
            self.assertEqual(before,self.state.snapshot());self.assertEqual('counter_replacement',q.kind)
            restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
            index=next(i for i,o in enumerate(q.options) if first in o.label)
            for kernel in (self.kernel,restored):kernel.answer(q.request_id,'A',[index])
            self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertEqual(expected,dict(self.state.get(self.ref).counters)['+1/+1'])

    def test_copy_uses_copy_power_and_controller(self):
        self.game(Zone.GRAVEYARD);ref=self.state.add_card('copy','catalog:forest','B',Zone.HAND)
        self.state.move((ZoneMove(ref,Zone.BATTLEFIELD,'B',copied_definition='catalog:kami-of-whispered-hopes'),),'fixture-copy')
        self.ref=self.state.current('copy');self.state.start_turn('B')
        self.kernel.execute_for_scenario(self.ref,'B',(AddCounters('source','+1/+1',1),))
        q=self.activate('B');self.kernel.answer(q.request_id,'B',[4])
        self.assertEqual((('G',3),),self.state.mana_pool('B'));self.assertEqual((),self.state.mana_pool('A'))

    def test_phased_source_does_not_replace_counters(self):
        self.game();land=self.state.add_card('land','catalog:forest','A',Zone.BATTLEFIELD)
        self.state.phase(self.ref,True)
        self.kernel.execute_for_scenario(land,'A',(AddCounters('source','+1/+1',1),))
        self.assertEqual((('+1/+1',1),),self.state.get(land).counters)
        self.state.phase(self.ref,False)
        self.kernel.execute_for_scenario(land,'A',(AddCounters('source','+1/+1',1),))
        self.assertEqual((('+1/+1',3),),self.state.get(land).counters)
