"""Zone-trigger subjects and controllers are captured when the event occurs."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_adapter import RulesActorAdapter


class EventSubjectTests(unittest.TestCase):
    def game(self,extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+extra
        self.state=RulesState(('A','B','C'));self.bonds=self.state.add_card('bonds','catalog:polluted-bonds','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs)

    def enter(self,owner,definition='catalog:forest'):
        ref=self.state.add_card('enter'+str(self.state.sequence),definition,owner,Zone.HAND)
        self.kernel.execute_for_scenario(ref,owner,(Move('source',Zone.BATTLEFIELD),))
        return self.state.current(ref.card_id)

    def drain(self):
        while self.kernel.stack or self.kernel.pending_choice:
            if self.kernel.pending_choice:
                request=self.kernel.pending_choice;self.assertEqual('trigger_order',request.kind)
                self.kernel.answer(request.request_id,request.actor,list(range(len(request.options))))
            else:self.kernel.pass_priority(self.kernel.priority)

    def test_only_opponent_land_entries_trigger_without_target_choices(self):
        self.game();self.enter('A');self.assertFalse(self.kernel.stack)
        self.enter('B','catalog:sol-ring');self.assertFalse(self.kernel.stack)
        self.enter('B');self.assertIsNone(self.kernel.pending_choice);self.drain()
        self.assertEqual((42,38,40),tuple(self.state.life(p) for p in self.state.players))

    def test_land_and_enchantment_departure_do_not_erase_captured_players(self):
        self.game();land=self.enter('B')
        self.state.move((ZoneMove(land,Zone.EXILE),ZoneMove(self.bonds,Zone.GRAVEYARD)),'fixture-response')
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs);self.drain()
        while restored.stack:restored.pass_priority(restored.priority)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertEqual(42,self.state.life('A'));self.assertEqual(38,self.state.life('B'))

    def test_control_changes_after_occurrence_do_not_redirect_either_life_effect(self):
        self.game();land=self.enter('B');self.state.change_control_batch((land,self.bonds),'C');self.drain()
        self.assertEqual((42,38,40),tuple(self.state.life(p) for p in self.state.players))

    def test_simultaneous_entries_capture_each_controller(self):
        self.game();refs=tuple(self.state.add_card('land'+p,'catalog:forest',p,Zone.HAND) for p in ('B','C'))
        self.kernel.execute_for_scenario(self.bonds,'A',(SelectAll(Selector(Zone.HAND,types=('Land',)),(Move('selected',Zone.BATTLEFIELD,controller='owner'),)),))
        self.drain();self.assertEqual((44,38,38),tuple(self.state.life(p) for p in self.state.players))

    def test_event_subject_binding_and_controller_filter_are_generic(self):
        observer=CardProgram('observer','Observer',('Enchantment',),abilities=(AbilityProgram('bounce',EventPattern('zone_changed',to_zone=Zone.BATTLEFIELD,types=('Artifact',),recipient_relation='controlled'),(Move('event_subject',Zone.HAND),)),))
        self.game((observer,));self.state.add_card('observer','observer','A',Zone.BATTLEFIELD)
        mine=self.enter('A','catalog:sol-ring');self.drain();self.assertEqual(Zone.HAND,self.state.get(self.state.current(mine.card_id)).zone)
        other=self.enter('B','catalog:sol-ring');self.assertFalse(self.kernel.stack);self.assertEqual(Zone.BATTLEFIELD,self.state.get(other).zone)

    def test_paid_cast_and_captured_trigger_replay(self):
        self.game();spell=self.state.add_card('spell','catalog:polluted-bonds','A',Zone.HAND)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('B','B','C','C','C'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',spell),Payment((('B',2),('C',3))))
        self.drain();self.assertEqual((),self.state.mana_pool('A'))
        self.enter('B');self.drain()
        # A fresh single-trigger checkpoint exercises ordinary actor pass replay.
        self.state.move((ZoneMove(self.state.current('spell'),Zone.GRAVEYARD),),'fixture-remove-second')
        self.enter('C');adapter=RulesActorAdapter(self.kernel)
        while self.kernel.stack:adapter.submit(self.kernel.priority,{'kind':'pass','revision':self.kernel.revision})
        restored=RulesActorAdapter.replay(adapter.archive(),self.programs)
        for actor in self.state.players:self.assertEqual(adapter.packet(actor),restored.packet(actor))

    def test_unbound_event_values_and_contradictory_filters_are_rejected(self):
        for effects in ((LoseLife('event_controllers',1),),(Move('event_subject',Zone.HAND),)):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),spell_effects=effects))
        event=EventPattern('zone_changed',to_zone=Zone.BATTLEFIELD,controller_only=True,recipient_relation='opponent_controlled')
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Enchantment',),abilities=(AbilityProgram('bad',event,(GainLife(1),)),)))

    def test_actor_summary_shows_captured_players_and_masks_hidden_event_subjects(self):
        self.game();land=self.enter('B');packet=RulesActorAdapter(self.kernel).packet('C')
        self.assertEqual(['B'],packet['stack'][0]['event_controllers'])
        self.assertEqual([land.to_json()],packet['stack'][0]['event_subjects'])
        self.drain()
        observer=CardProgram('observer','Observer',('Enchantment',),abilities=(AbilityProgram('hand-entry',EventPattern('zone_changed',to_zone=Zone.HAND),(GainLife(1),)),))
        self.game((observer,));self.state.add_card('observer','observer','A',Zone.BATTLEFIELD)
        secret=self.state.add_card('secret','catalog:forest','B',Zone.LIBRARY)
        self.kernel.execute_for_scenario(secret,'B',(Move('source',Zone.HAND),))
        adapter=RulesActorAdapter(self.kernel)
        self.assertEqual([{'hidden':True,'zone':'hand','owner':'B'}],adapter.packet('A')['stack'][0]['event_subjects'])
        self.assertEqual([self.state.current('secret').to_json()],adapter.packet('B')['stack'][0]['event_subjects'])
