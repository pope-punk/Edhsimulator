"""Authored modal spells use paid shared choices and mode-specific targeting."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,PlayerRef,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed


class ModalCardTests(unittest.TestCase):
    def setUp(self):
        programs=tuple(r['program'] for r in load_reviewed().values())+(CardProgram('beast','Beast',('Creature',),power=2,toughness=2),CardProgram('human','Human',('Creature',),subtypes=('Human',),power=15,toughness=15))
        self.state=RulesState(('A','B'));self.kernel=RulesKernel(self.state,programs)
        self.beast=self.state.add_card('beast','beast','A',Zone.BATTLEFIELD)
        self.human=self.state.add_card('human','human','A',Zone.BATTLEFIELD)
        for actor in ('A','B'):
            for i in range(10):self.state.add_card(actor+str(i),'catalog:forest',actor,Zone.LIBRARY)

    def cast(self,key,modes,symbol,generic,x=0):
        source=self.state.add_card('spell','catalog:'+key,'A',Zone.HAND)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',(symbol,)+('C',)*generic)
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',source,mode_choices=modes,x_value=x),Payment(((symbol,1),('C',generic))))

    def drain(self):
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)

    def test_valorous_stance_protect_and_cleanup(self):
        self.cast('valorous-stance',(('protect',(self.beast,)),),'W',1);self.drain()
        self.assertIn('indestructible',self.kernel.effective(self.beast).keywords)
        self.kernel._finish_cleanup_actions();self.assertNotIn('indestructible',self.kernel.effective(self.beast).keywords)

    def test_valorous_stance_destroys_eligible_target(self):
        self.cast('valorous-stance',(('destroy',(self.human,)),),'W',1);self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('human')).zone)
        self.assertEqual((),self.state.mana_pool('A'))

    def test_valorous_stance_invalid_destroy_target_rejected_before_payment(self):
        source=self.state.add_card('spell','catalog:valorous-stance','A',Zone.HAND);self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('W','C'));before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',source,mode_choices=(('destroy',(self.beast,)),))
        self.assertEqual(before,self.kernel.snapshot())

    def test_wildspeaker_draw_ignores_humans_and_opponents(self):
        self.state.add_card('enemy','human','B',Zone.BATTLEFIELD)
        self.cast('return-of-the-wildspeaker',(('draw',()),),'G',4);self.drain()
        self.assertEqual(2,len(self.state.zone('A',Zone.HAND)))
        self.assertEqual(2,self.kernel.effective(self.beast).power)

    def test_wildspeaker_boost_ignores_humans_and_does_not_draw(self):
        self.cast('return-of-the-wildspeaker',(('boost',()),),'G',4);self.drain()
        self.assertEqual(5,self.kernel.effective(self.beast).power);self.assertEqual(15,self.kernel.effective(self.human).power)
        self.assertFalse(self.state.zone('A',Zone.HAND))

    def test_drown_both_modes_same_player_printed_order_and_no_commander_recheck(self):
        commander=self.state.add_card('commander','beast','A',Zone.BATTLEFIELD,commander=True)
        self.cast('drown-in-dreams',(('mill',(PlayerRef('B'),)),('draw',(PlayerRef('B'),))),'U',4,x=2)
        self.state.move((ZoneMove(commander,Zone.COMMAND),),'scenario_response');self.drain()
        self.assertEqual({'B8','B9'},{o.ref.card_id for o in self.state.zone('B',Zone.HAND)})
        self.assertEqual({'B4','B5','B6','B7'},{o.ref.card_id for o in self.state.zone('B',Zone.GRAVEYARD)})
        self.assertEqual((),self.state.mana_pool('A'))

    def test_drown_without_controlled_commander_cannot_choose_both(self):
        self.state.add_card('commander','beast','B',Zone.BATTLEFIELD,commander=True)
        self.state.add_card('own-command','beast','A',Zone.COMMAND,commander=True)
        source=self.state.add_card('spell','catalog:drown-in-dreams','A',Zone.HAND);self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('U','C','C'))
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',source,mode_choices=(('draw',(PlayerRef('A'),)),('mill',(PlayerRef('B'),))))
        self.assertEqual(before,self.kernel.snapshot())
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',source,mode_choices=(('mill',(PlayerRef('B'),)),)),Payment((('U',1),('C',2))))
        self.drain();self.assertEqual(10,len(self.state.zone('B',Zone.LIBRARY)))
