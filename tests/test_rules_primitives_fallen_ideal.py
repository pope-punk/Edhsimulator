"""Granted sacrifice abilities and exact public successor bindings compose."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed

class FallenIdealTests(unittest.TestCase):
    def game(self,host_actor='A'):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(CardProgram('body','Body',('Creature',),power=2,toughness=3),)
        self.state=RulesState(('A','B'));self.host=self.state.add_card('host','body',host_actor,Zone.BATTLEFIELD)
        self.food=self.state.add_card('food','body',host_actor,Zone.BATTLEFIELD);self.aura=self.state.add_card('aura','catalog:fallen-ideal','A',Zone.HAND)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)
    def cast(self):
        self.state.add_mana('A',('C','C','B'));self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.aura,(self.host,)),Payment((('C',2),('B',1))));self.drain();self.aura=self.state.current('aura')
    def pump(self,actor='A',food=None):
        self.kernel.open_window_for_scenario(actor);ability=self.kernel.activated_abilities(self.state.get(self.host))[0]
        return self.kernel.commit_action(self.kernel.quote_activation('pump',actor,self.host,ability.ability_id),Payment(zone_costs=(('sac',(food or self.food,)),)))

    def test_printed_cast_grants_flying_sacrifice_cost_and_temporary_recipient_pump(self):
        self.game();self.cast();self.assertEqual(self.host,self.state.get(self.aura).attached_to);self.assertIn('flying',self.kernel.effective(self.host).keywords)
        self.pump();self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('food')).zone);self.assertEqual(2,self.kernel.effective(self.host).power)
        self.drain();self.assertEqual((4,4),(self.kernel.effective(self.host).power,self.kernel.effective(self.host).toughness))
        self.kernel._finish_cleanup_actions();self.assertEqual(2,self.kernel.effective(self.host).power);self.assertIn('flying',self.kernel.effective(self.host).keywords)

    def test_host_controller_owns_granted_ability_and_cost_even_when_aura_has_other_controller(self):
        self.game('B');self.cast();self.pump('B');self.drain();self.assertEqual(4,self.kernel.effective(self.host).power)
        self.assertEqual('A',self.state.get(self.aura).controller);self.assertEqual('B',self.state.get(self.state.current('food')).owner)

    def test_sacrificing_host_returns_aura_and_does_not_pump_new_objects(self):
        self.game();self.cast();self.pump(food=self.host);self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('host')).zone);self.assertEqual(Zone.HAND,self.state.get(self.state.current('aura')).zone)
        self.assertEqual(2,self.kernel.effective(self.food).power)

    def test_aura_return_tracks_exact_successor_and_replays(self):
        self.game();self.cast();self.kernel.execute_for_scenario(self.aura,'A',(Destroy('source'),))
        successor=self.state.current('aura');self.assertEqual(Zone.GRAVEYARD,self.state.get(successor).zone)
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs);self.drain();self.drain(replay.kernel)
        self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot());self.assertEqual(Zone.HAND,self.state.get(self.state.current('aura')).zone)

    def test_old_trigger_does_not_follow_later_graveyard_incarnation(self):
        self.game();self.cast();self.kernel.execute_for_scenario(self.aura,'A',(Destroy('source'),))
        grave=self.state.current('aura');self.state.move((ZoneMove(grave,Zone.EXILE),),'response');exile=self.state.current('aura')
        self.state.move((ZoneMove(exile,Zone.GRAVEYARD),),'response');later=self.state.current('aura');self.drain()
        self.assertEqual(later,self.state.current('aura'));self.assertEqual(Zone.GRAVEYARD,self.state.get(later).zone)

    def test_stolen_aura_returns_to_owner_and_hidden_successor_binding_is_rejected(self):
        self.game();self.cast();self.state.change_control(self.aura,'B');self.kernel.execute_for_scenario(self.aura,'B',(Destroy('source'),));self.drain()
        self.assertEqual(['aura'],[o.ref.card_id for o in self.state.zone('A',Zone.HAND)]);self.assertFalse(self.state.zone('B',Zone.HAND))
        for event in (EventPattern('zone_changed',from_zone=Zone.BATTLEFIELD,to_zone=Zone.HAND,subject='self'),EventPattern('zone_changed',from_zone=Zone.BATTLEFIELD,to_zone=Zone.GRAVEYARD),EventPattern('zone_changed',to_zone=Zone.BATTLEFIELD,subject='self')):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Artifact',),abilities=(AbilityProgram('bad',event,(Move('source_successor',Zone.HAND),)),)))

    def test_copied_aura_inherits_return_and_returns_underlying_card_to_its_owner(self):
        self.game();copy=self.state.add_card('copy','catalog:forest','B',Zone.HAND)
        self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,'B',copied_definition='catalog:fallen-ideal',attached_to=self.host),),'fixture-copy')
        copy=self.state.current('copy');self.assertIn('flying',self.kernel.effective(self.host).keywords)
        self.kernel.execute_for_scenario(copy,'B',(Destroy('source'),));self.drain()
        returned=self.state.get(self.state.current('copy'));self.assertEqual(Zone.HAND,returned.zone);self.assertEqual('B',returned.owner)
        self.assertEqual('catalog:forest',returned.effective_definition);self.assertNotIn('flying',self.kernel.effective(self.host).keywords)
