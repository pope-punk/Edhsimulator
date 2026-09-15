"""Ownership does not make a hand/graveyard card controlled by a player."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_characteristics import matches


class ControllerDomainTests(unittest.TestCase):
    def game(self,event=None):
        abilities=() if event is None else (AbilityProgram('watch',event,(GainLife(1),)),)
        self.programs=(CardProgram('observer','Observer',('Enchantment',),abilities=abilities),CardProgram('card','Card',('Artifact',)))
        self.state=RulesState(('A','B'));self.source=self.state.add_card('observer','observer','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs)

    def test_hidden_and_graveyard_cards_are_owned_but_not_controlled(self):
        self.game();frame={'source':self.state.get(self.source).to_json(),'controller':'A'}
        def query(selector):
            if selector.zone!=Zone.LIBRARY:return self.kernel._query(selector,frame)
            return tuple(obj for obj in self.state.objects(Zone.LIBRARY) if matches(selector,obj,self.kernel.effective(obj.ref),self.state.get(self.source)))
        for zone in (Zone.HAND,Zone.GRAVEYARD,Zone.EXILE,Zone.LIBRARY):
            mine=self.state.add_card('mine-'+zone.value,'card','A',zone)
            self.state.add_card('other-'+zone.value,'card','B',zone)
            self.assertEqual([mine],[o.ref for o in query(Selector(zone,relation='owned'))])
            for relation in ('controlled','opponent_controlled'):
                self.assertEqual((),query(Selector(zone,relation=relation)))

    def test_hand_entry_controller_filters_do_not_match_owner(self):
        for controller_only,relation in ((True,'any'),(False,'controlled'),(False,'opponent_controlled')):
            self.game(EventPattern('zone_changed',to_zone=Zone.HAND,controller_only=controller_only,recipient_relation=relation))
            for actor in ('A','B'):
                ref=self.state.add_card('card-'+actor,'card',actor,Zone.LIBRARY)
                self.kernel.execute_for_scenario(ref,actor,(Move('source',Zone.HAND),))
                self.assertFalse(self.kernel.stack);self.assertFalse(self.kernel.pending_triggers)

    def test_leaves_event_uses_predeparture_controller_not_owner(self):
        event=EventPattern('zone_changed',from_zone=Zone.BATTLEFIELD,types=('Artifact',),recipient_relation='controlled')
        self.game(event);ref=self.state.add_card('card','card','B',Zone.BATTLEFIELD)
        self.state.change_control_batch((ref,),'A')
        self.kernel.execute_for_scenario(ref,'A',(Move('source',Zone.GRAVEYARD,controller='owner'),))
        self.assertEqual(1,len(self.kernel.stack));self.assertEqual(['A'],self.kernel.stack[0]['values']['event_controllers'])
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual(41,self.state.life('A'))

    def test_unfiltered_hand_event_has_subject_but_no_controller(self):
        self.game(EventPattern('zone_changed',to_zone=Zone.HAND))
        ref=self.state.add_card('card','card','B',Zone.LIBRARY)
        self.kernel.execute_for_scenario(ref,'B',(Move('source',Zone.HAND),))
        self.assertEqual([],self.kernel.stack[0]['values']['event_controllers'])
        self.assertEqual([self.state.current('card').to_json()],self.kernel.stack[0]['bindings']['event_subject'])
