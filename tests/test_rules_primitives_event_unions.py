"""Other-object zone triggers use one type union, including copied abilities."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState, Zone, ZoneMove, RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter


class EventUnionTests(unittest.TestCase):
    def game(self, zone=Zone.BATTLEFIELD):
        both=CardProgram('both','Both',('Creature','Planeswalker'),power=2,toughness=2)
        walker=CardProgram('walker','Walker',('Planeswalker',))
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(both,walker)
        self.state=RulesState(('A','B'))
        self.ref=self.state.add_card('liliana','catalog:liliana-the-faultless','A',zone)
        self.state.start_turn('A')
        self.kernel=RulesKernel(self.state,self.programs)
        self.kernel.open_window_for_scenario('A')

    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack or kernel.pending_choice:
            if kernel.pending_choice:
                q=kernel.pending_choice;self.assertEqual('trigger_order',q.kind)
                kernel.answer(q.request_id,q.actor,list(range(len(q.options))))
            else:kernel.pass_priority(kernel.priority)

    def test_printed_cast_excludes_self_then_union_triggers_once_per_entry(self):
        self.game(Zone.HAND);self.state.add_mana('A',('W',))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.ref),Payment((('W',1),)));self.drain()
        self.assertEqual(40,self.state.life('A'))
        for i,(definition,owner,expected) in enumerate((('both','A',41),('walker','A',42),('catalog:llanowar-elves','A',43),('both','B',43),('catalog:forest','A',43))):
            ref=self.state.add_card(str(i),definition,owner,Zone.HAND)
            self.kernel.enter(ref);self.drain();self.assertEqual(expected,self.state.life('A'))

    def test_simultaneous_entries_see_other_objects_without_double_counting(self):
        self.game(Zone.HAND)
        self.state.add_card('both','both','A',Zone.HAND)
        self.state.add_card('walker','walker','A',Zone.HAND)
        self.kernel.execute_for_scenario(self.ref,'A',(SelectAll(Selector(Zone.HAND,relation='owned'),(Move('selected',Zone.BATTLEFIELD),)),))
        self.drain();self.assertEqual(42,self.state.life('A'))

    def test_copied_trigger_uses_current_controller_and_excludes_its_own_entry(self):
        self.game(Zone.GRAVEYARD)
        ref=self.state.add_card('copy','catalog:forest','B',Zone.HAND)
        before=self.state.objects(Zone.BATTLEFIELD);views=self.kernel.characteristics()
        events=self.state.move((ZoneMove(ref,Zone.BATTLEFIELD,'B',copied_definition='catalog:liliana-the-faultless'),),'fixture-copy')
        self.kernel._collect(events,before,self.state.objects(Zone.BATTLEFIELD),views);self.kernel.advance();self.drain()
        self.assertEqual(40,self.state.life('B'))
        ref=self.state.add_card('both','both','B',Zone.HAND);self.kernel.enter(ref);self.drain()
        self.assertEqual(41,self.state.life('B'));self.assertEqual(40,self.state.life('A'))

    def activation(self,target):
        self.state.add_mana('A',('C',))
        discard=self.state.add_card('discard','catalog:forest','A',Zone.HAND)
        quote=self.kernel.quote_activation('protect','A',self.ref,'protect',(target,))
        self.kernel.commit_action(quote,Payment((('C',1),),zone_costs=(('discard',(discard,)),)))

    def test_activation_pays_before_resolving_and_hexproof_expires_after_recovery(self):
        self.game();target=self.state.add_card('target','both','A',Zone.BATTLEFIELD)
        self.state.add_counters(target,'loyalty',3)
        self.activation(target)
        self.assertTrue(self.state.get(self.ref).tapped)
        self.assertEqual((),self.state.mana_pool('A'))
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('discard')).zone)
        self.assertNotIn('hexproof',self.kernel.effective(target).keywords)
        replay=RulesActorAdapter.replay(RulesActorAdapter(self.kernel).archive(),self.programs)
        for kernel in (self.kernel,replay.kernel):self.drain(kernel)
        self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot())
        self.assertIn('hexproof',self.kernel.effective(target).keywords)
        self.kernel._finish_cleanup_actions();self.assertNotIn('hexproof',self.kernel.effective(target).keywords)

    def test_activation_rejects_self_opponents_and_nonmatching_types_atomically(self):
        self.game();self.state.add_mana('A',('C',))
        refs=(self.ref,self.state.add_card('other','both','B',Zone.BATTLEFIELD),self.state.add_card('land','catalog:forest','A',Zone.BATTLEFIELD))
        before=self.kernel.snapshot()
        for target in refs:
            with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',self.ref,'protect',(target,))
            self.assertEqual(before,self.kernel.snapshot())

    def test_blinked_target_does_not_receive_hexproof_on_its_new_incarnation(self):
        self.game();target=self.state.add_card('target','walker','A',Zone.BATTLEFIELD);self.state.add_counters(target,'loyalty',3);self.activation(target)
        self.state.move((ZoneMove(target,Zone.EXILE),),'fixture-blink')
        self.state.move((ZoneMove(self.state.current('target'),Zone.BATTLEFIELD),),'fixture-return')
        self.drain();self.assertNotIn('hexproof',self.kernel.effective(self.state.current('target')).keywords)
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('discard')).zone)

    def test_union_validation_and_codec_fail_closed_for_other_event_kinds(self):
        for event in (EventPattern('step_began',step='upkeep',any_types=('Creature',)),EventPattern('spell_cast',exclude_source=True),EventPattern('zone_changed',subject='self',exclude_source=True),EventPattern('zone_changed',any_types='Creature'),EventPattern('zone_changed',exclude_source=1)):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Enchantment',),abilities=(AbilityProgram('bad',event,()),)))
        event=EventPattern('zone_changed',any_types=('Creature','Planeswalker'),exclude_source=True)
        self.assertEqual(event,decode(encode(event)))
