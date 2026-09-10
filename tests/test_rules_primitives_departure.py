"""Departure transactions distinguish ownership, default control and later effects."""
import unittest
from edh_gauntlet.rules_departure import plan_departure
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation


class DepartureTests(unittest.TestCase):
    def setUp(self):self.state=RulesState(('A','B','C','D'))

    def creature(self,owner='A',controller=None,key='creature'):
        return self.state.add_card(key,'creature',owner,Zone.BATTLEFIELD,controller=controller)

    def test_temporary_theft_returns_to_default_controller(self):
        ref=self.creature();key=self.state.change_control(ref,'B',duration='until_end_of_turn')
        before=self.state.snapshot();plan=plan_departure(self.state,('B',))
        self.assertEqual(((ref,'A'),),plan.control_changes)
        self.assertEqual((key,),plan.ended_control_effects)
        self.assertEqual((),plan.exile_objects)
        self.assertEqual(before,self.state.snapshot())

    def test_reanimated_opponents_card_is_exiled_when_entry_controller_leaves(self):
        ref=self.creature(owner='A',controller='B')
        plan=plan_departure(self.state,('B',))
        self.assertEqual((ref,),plan.exile_objects)
        self.assertEqual((),plan.owned_objects)

    def test_earlier_surviving_control_effect_is_revealed(self):
        ref=self.creature();self.state.change_control(ref,'C');self.state.change_control(ref,'B')
        plan=plan_departure(self.state,('B',))
        self.assertEqual(((ref,'C'),),plan.control_changes)
        self.assertEqual((),plan.exile_objects)

    def test_removing_buried_effect_does_not_change_current_controller(self):
        ref=self.creature();key=self.state.change_control(ref,'B');self.state.change_control(ref,'C')
        plan=plan_departure(self.state,('B',))
        self.assertEqual((key,),plan.ended_control_effects)
        self.assertEqual((),plan.control_changes)
        self.assertEqual((),plan.exile_objects)

    def test_owned_phased_objects_leave_even_under_another_players_control(self):
        ref=self.creature();self.state.change_control(ref,'B');self.state.phase(ref,True)
        hand=self.state.add_card('hand','creature','A',Zone.HAND)
        plan=plan_departure(self.state,('A',))
        self.assertEqual({ref,hand},set(plan.owned_objects))
        self.assertEqual((),plan.exile_objects)
        self.assertEqual((),plan.control_changes)

    def test_simultaneous_departure_filters_all_departing_control_effects(self):
        ref=self.creature(owner='D',controller='B')
        self.state.change_control(ref,'C');self.state.change_control(ref,'A')
        plan=plan_departure(self.state,('A','C','B'))
        self.assertEqual(('A','B','C'),plan.players)
        self.assertEqual((ref,),plan.exile_objects)

    def test_surviving_controller_keeps_foreign_owned_permanent_when_default_controller_leaves(self):
        ref=self.creature(owner='D',controller='B');self.state.change_control(ref,'C')
        plan=plan_departure(self.state,('B',))
        self.assertEqual((),plan.exile_objects)
        self.assertEqual((),plan.control_changes)

    def test_stale_departure_plan_is_rejected(self):
        self.creature();plan=plan_departure(self.state,('B',));plan.validate_state(self.state)
        self.state.add_mana('A',('G',))
        with self.assertRaises(RulesViolation):plan.validate_state(self.state)
        with self.assertRaises(RulesViolation):plan_departure(self.state,('B','B'))
