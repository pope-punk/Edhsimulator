"""Whole-card Starfield behavior uses shared return, copy and continuous layers."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class StarfieldTests(unittest.TestCase):
    def game(self,zone=Zone.BATTLEFIELD):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(
            CardProgram('enchantment','Enchantment',('Enchantment',),mana_value=2),
            CardProgram('aura','Aura',('Enchantment',),mana_value=3,enchant=Selector(Zone.BATTLEFIELD,types=('Creature',))),
            CardProgram('host','Host',('Creature',),power=4,toughness=4,keywords=('hexproof',)))
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('starfield','catalog:starfield-of-nyx','A',zone)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def add(self,key,definition='enchantment',actor='A',zone=Zone.BATTLEFIELD):
        return self.state.add_card(key,definition,actor,zone)

    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)

    def answer(self,index=0,kernel=None):
        kernel=kernel or self.kernel;q=kernel.pending_choice
        return kernel.answer(q.request_id,q.actor,[index])

    def test_printed_cast_and_dynamic_threshold_controller_phasing_and_counters(self):
        self.game(Zone.HAND);refs=[self.add(str(i)) for i in range(3)]
        self.state.add_mana('A',('C','C','C','C','W'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.ref),Payment((('C',4),('W',1))));self.drain()
        self.ref=self.state.current('starfield');self.assertNotIn('Creature',self.kernel.effective(refs[0]).types)
        self.add('opponent',actor='B');self.assertNotIn('Creature',self.kernel.effective(refs[0]).types)
        fifth=self.add('fifth');self.state.add_counters(refs[0],'+1/+1',2)
        self.assertEqual(4,self.kernel.effective(refs[0]).power);self.assertNotIn('Creature',self.kernel.effective(self.ref).types)
        self.state.phase(fifth,True);self.assertIsNone(self.kernel.effective(refs[0]).power)
        self.state.phase(fifth,False);self.assertEqual(4,self.kernel.effective(refs[0]).power)

    def test_upkeep_targets_only_own_enchantment_then_optional_return_and_replay(self):
        self.game();target=self.add('target',zone=Zone.GRAVEYARD)
        self.add('enemy',actor='B',zone=Zone.GRAVEYARD);self.add('land','catalog:forest',zone=Zone.GRAVEYARD)
        self.kernel.begin_step('B','upkeep');self.assertFalse(self.kernel.stack)
        q=self.kernel.begin_step('A','upkeep');self.assertEqual([target],[o.ref for o in q.options])
        self.answer();self.drain();self.assertEqual('may',self.kernel.pending_choice.kind)
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        command={'kind':'answer','revision':self.kernel.revision,'request_id':self.kernel.pending_choice.request_id,'indexes':[0]}
        adapter.submit('A',command);replay.submit('A',command)
        self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot());self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('target')).zone)
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):adapter.submit('A',command)
        self.assertEqual(before,self.kernel.snapshot())

    def test_declining_return_and_target_leaving_do_not_reanimate(self):
        for leave in (False,True):
            self.game();target=self.add('target',zone=Zone.GRAVEYARD)
            self.kernel.begin_step('A','upkeep');self.answer()
            if leave:self.state.move((ZoneMove(target,Zone.EXILE),),'response')
            self.drain()
            if not leave:self.answer(1)
            self.assertIsNone(self.kernel.pending_choice)
            self.assertEqual(Zone.EXILE if leave else Zone.GRAVEYARD,self.state.get(self.state.current('target')).zone)

    def test_returned_aura_chooses_attachment_without_targeting_hexproof_creature(self):
        self.game();host=self.add('host','host','B');aura=self.add('aura','aura',zone=Zone.GRAVEYARD)
        self.kernel.begin_step('A','upkeep');self.answer();self.drain();self.answer()
        self.assertEqual('aura_attachment',self.kernel.pending_choice.kind);self.assertEqual(host,self.kernel.pending_choice.options[0].ref)
        self.answer();self.assertEqual(host,self.state.get(self.state.current('aura')).attached_to)

    def test_aura_counts_but_is_not_animated_and_two_starfields_animate_each_other(self):
        self.game();host=self.add('host','host');aura=self.add('aura','aura',zone=Zone.HAND)
        self.kernel.enter(aura);self.answer();aura=self.state.current('aura')
        self.add('one');self.add('two');second=self.add('second','catalog:starfield-of-nyx')
        self.assertEqual(5,self.kernel.effective(self.ref).power);self.assertEqual(5,self.kernel.effective(second).power)
        self.assertNotIn('Creature',self.kernel.effective(aura).types)
        self.state.phase(second,True);self.assertIsNone(self.kernel.effective(self.ref).power)

    def test_copied_program_uses_copy_controller_for_upkeep_and_animation(self):
        self.game(Zone.GRAVEYARD);ref=self.add('copy','catalog:forest','B',Zone.HAND)
        self.state.move((ZoneMove(ref,Zone.BATTLEFIELD,'B',copied_definition='catalog:starfield-of-nyx'),),'fixture-copy')
        for i in range(4):self.add(str(i),actor='B')
        self.assertEqual(2,self.kernel.effective(self.state.current('0')).power)
        self.kernel.begin_step('A','upkeep');self.assertFalse(self.kernel.stack)
        target=self.add('return',actor='B',zone=Zone.GRAVEYARD)
        q=self.kernel.begin_step('B','upkeep');self.assertEqual('B',q.actor);self.assertEqual([target],[o.ref for o in q.options])
        self.answer();self.drain();self.answer();self.assertEqual('B',self.state.get(self.state.current('return')).controller)
