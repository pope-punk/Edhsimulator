"""Rogue's Passage composes existing temporary combat restrictions."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_combat import uid
from edh_gauntlet.rules_adapter import RulesActorAdapter


class PassageTests(unittest.TestCase):
    def setUp(self):
        self.programs=tuple(r['program'] for r in load_reviewed().values())
        self.state=RulesState(('A','B'));self.kernel=RulesKernel(self.state,self.programs)
        self.land=self.state.add_card('passage','catalog:rogue-s-passage','A',Zone.BATTLEFIELD)
        self.elf=self.state.add_card('elf','catalog:llanowar-elves','A',Zone.BATTLEFIELD)
        self.blocker=self.state.add_card('blocker','catalog:llanowar-elves','B',Zone.BATTLEFIELD)
        for actor in ('A','B'):self.state.add_card('draw'+actor,'catalog:forest',actor,Zone.LIBRARY)

    def activate(self,target=None):
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('C',)*4)
        self.kernel.commit_action(self.kernel.quote_activation('passage','A',self.land,'passage',(target or self.elf,)),Payment((('C',4),)))

    def drain(self):
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)

    def test_cost_target_and_source_departure_with_checkpoint(self):
        self.activate(self.blocker)
        self.assertEqual((),self.state.mana_pool('A'));self.assertTrue(self.state.get(self.land).tapped)
        self.state.move((ZoneMove(self.land,Zone.GRAVEYARD),),'scenario_source_departure')
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        for kernel in (self.kernel,replay.kernel):
            while kernel.stack:kernel.pass_priority(kernel.priority)
        self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot())
        self.assertIn('unblockable',self.kernel.effective(self.blocker).keywords)
        self.kernel._finish_cleanup_actions();self.assertNotIn('unblockable',self.kernel.effective(self.blocker).keywords)

    def test_blinked_target_is_illegal_on_resolution(self):
        self.activate();self.state.move((ZoneMove(self.elf,Zone.EXILE),),'scenario_blink')
        self.state.move((ZoneMove(self.state.current('elf'),Zone.BATTLEFIELD),),'scenario_return');self.drain()
        self.assertNotIn('unblockable',self.kernel.effective(self.state.current('elf')).keywords)
        self.assertEqual((),self.state.mana_pool('A'))

    def test_actual_block_declaration_rejects_a_block(self):
        self.kernel.begin_turn_for_scenario('A')
        while self.kernel.phase!='precombat_main':self.kernel.pass_priority(self.kernel.priority)
        self.state.add_mana('A',('C',)*4)
        self.kernel.commit_action(self.kernel.quote_activation('passage','A',self.land,'passage',(self.elf,)),Payment((('C',4),)))
        self.drain()
        while self.kernel.phase!='declare_attackers':self.kernel.pass_priority(self.kernel.priority)
        self.kernel.declare_attackers('A',{self.elf:'B'},revision=self.kernel.revision)
        while self.kernel.phase!='declare_blockers':self.kernel.pass_priority(self.kernel.priority)
        with self.assertRaises(RulesViolation):self.kernel.declare_blockers('B',{uid(self.elf):[uid(self.blocker)]},revision=self.kernel.revision)
        self.kernel.declare_blockers('B',{uid(self.elf):[]},revision=self.kernel.revision)

    def test_mana_activation_and_noncreature_target_rejection(self):
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('C',)*4)
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',self.land,'passage',(self.land,))
        self.kernel.commit_action(self.kernel.quote_activation('mana','A',self.land,'mana'),Payment())
        self.assertEqual((('C',5),),self.state.mana_pool('A'));self.assertFalse(self.kernel.stack)
