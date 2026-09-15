"""Losses, departed control and continuing multiplayer rules boundaries."""
import unittest
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_program import CardProgram,AbilityProgram,EventPattern,GainLife,Draw,GainControl,ZoneReplacement
from edh_gauntlet.rules_departure import GameResult


class EliminationTests(unittest.TestCase):
    def setUp(self):
        self.state=RulesState(('A','B','C','D'))
        self.creature=CardProgram('creature','Creature',('Creature',),power=2,toughness=2)
        self.programs=[self.creature,CardProgram('land','Land',('Land',))]
        self.source=self.state.add_card('source','creature','D',Zone.BATTLEFIELD)

    def kernel(self):return RulesKernel(self.state,self.programs)

    def poison(self,player):self.state.add_player_counters(player,'poison',10)

    def drain(self,kernel):
        for _ in range(50):
            if not kernel.stack:return
            kernel.pass_priority(kernel.priority)
        self.fail('Stack did not drain')

    def test_simultaneous_losses_and_terminal_checkpoint(self):
        kernel=self.kernel()
        for p in ('A','B','C'):self.poison(p)
        result=kernel.advance()
        self.assertEqual(GameResult('win',('D',),('A','B','C')),result)
        restored=RulesKernel.restore(kernel.snapshot(),self.programs)
        self.assertEqual(result,restored.advance())
        with self.assertRaises(RulesViolation):kernel.pass_priority('D')
        with self.assertRaises(RulesViolation):kernel.execute_for_scenario(self.source,'D',(GainLife(1),))

    def test_every_player_losing_simultaneously_is_a_draw(self):
        kernel=self.kernel()
        for p in self.state.players:self.poison(p)
        self.assertEqual('draw',kernel.advance().kind)
        self.assertEqual((),self.state.live_players)

    def test_lethal_damage_waits_until_resolution_has_finished(self):
        # Paying life down to zero is legal; subsequent resolution can gain life
        # before the next state-action boundary. Damage uses the same loss ledger.
        self.state.damage_batch(({'source':self.state.get(self.source),'target':'A','amount':40},))
        kernel=self.kernel();kernel.execute_for_scenario(self.source,'A',(GainLife(1),))
        self.assertIn('A',self.state.live_players);self.assertEqual(1,self.state.life('A'))

    def test_failed_draw_does_not_end_resolution_early(self):
        kernel=self.kernel();kernel.execute_for_scenario(self.source,'A',(Draw(),GainLife(5)))
        self.assertEqual(45,self.state.life('A'))
        self.assertNotIn('A',self.state.live_players)
        self.assertEqual(('B','C','D'),self.state.live_players)

    def test_departure_reveals_earlier_control_effect(self):
        ref=self.state.add_card('borrowed','creature','A',Zone.BATTLEFIELD)
        self.state.change_control(ref,'C');self.state.change_control(ref,'B')
        kernel=self.kernel();self.poison('B');kernel.advance()
        self.assertEqual('C',self.state.get(ref).controller)
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(ref).zone)

    def test_foreign_owned_reanimation_exiles_instead_of_returning_to_owner(self):
        ref=self.state.add_card('borrowed','creature','A',Zone.BATTLEFIELD,controller='B')
        kernel=self.kernel();self.poison('B');kernel.advance()
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current(ref.card_id)).zone)

    def test_phased_foreign_owned_reanimation_also_exiles(self):
        ref=self.state.add_card('borrowed','creature','A',Zone.BATTLEFIELD,controller='B')
        self.state.phase(ref,True)
        kernel=self.kernel();self.poison('B');kernel.advance()
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current(ref.card_id)).zone)

    def test_expiring_control_over_a_departed_default_controller_exiles(self):
        ref=self.state.add_card('borrowed','creature','A',Zone.BATTLEFIELD,controller='B')
        self.state.change_control(ref,'C',duration='until_end_of_turn')
        kernel=self.kernel();self.poison('B');kernel.advance()
        self.assertEqual('C',self.state.get(ref).controller)
        kernel._finish_cleanup_actions();kernel.advance()
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current(ref.card_id)).zone)

    def test_leaves_triggers_survive_for_live_controller_but_not_departed_controller(self):
        watcher=CardProgram('watcher','Watcher',('Enchantment',),abilities=(AbilityProgram('leaves',
            EventPattern('zone_changed',from_zone=Zone.BATTLEFIELD,types=('Creature',)),(GainLife(1),)),))
        self.programs.append(watcher)
        self.state.add_card('watchC','watcher','C',Zone.BATTLEFIELD)
        self.state.add_card('watchB','watcher','B',Zone.BATTLEFIELD)
        self.state.add_card('ownedB','creature','B',Zone.BATTLEFIELD)
        kernel=self.kernel();self.poison('B');kernel.advance();self.drain(kernel)
        self.assertEqual(41,self.state.life('C'));self.assertEqual(40,self.state.life('B'))

    def test_phased_owned_objects_do_not_generate_leaves_triggers(self):
        watcher=CardProgram('watcher','Watcher',('Enchantment',),abilities=(AbilityProgram('leaves',
            EventPattern('zone_changed',from_zone=Zone.BATTLEFIELD,types=('Creature',)),(GainLife(1),)),))
        self.programs.append(watcher);self.state.add_card('watch','watcher','C',Zone.BATTLEFIELD)
        ref=self.state.add_card('ownedB','creature','B',Zone.BATTLEFIELD);self.state.phase(ref,True)
        kernel=self.kernel();self.poison('B');kernel.advance()
        self.assertEqual(40,self.state.life('C'));self.assertFalse(kernel.stack)
        self.assertEqual(Zone.OUTSIDE,self.state.get(self.state.current(ref.card_id)).zone)

    def test_active_player_departure_continues_turn_then_skips_departed_seat(self):
        for p in self.state.players:self.state.add_card('draw'+p,'land',p,Zone.LIBRARY)
        kernel=self.kernel();kernel.begin_turn_for_scenario('A')
        self.poison('A');kernel.advance()
        self.assertEqual('A',kernel.active);self.assertEqual('B',kernel.priority)
        for _ in range(50):
            if self.state.turn_active=='B':break
            kernel.pass_priority(kernel.priority)
        self.assertEqual('B',self.state.turn_active)
        self.assertEqual(0,len(self.state.zone('A',Zone.HAND)))
        self.assertEqual(('B','C','D'),self.state.live_players)

    def test_commander_damage_is_per_physical_card_not_combined_across_commanders(self):
        first=self.state.add_card('cmd1','creature','D',Zone.BATTLEFIELD,commander=True)
        second=self.state.add_card('cmd2','creature','D',Zone.BATTLEFIELD,commander=True)
        kernel=self.kernel()
        for ref in (first,second):self.state.damage_batch(({'source':self.state.get(ref),'target':'A','amount':11,'combat':True},))
        kernel.advance();self.assertIn('A',self.state.live_players)
        self.state.damage_batch(({'source':self.state.get(first),'target':'A','amount':10,'combat':True},))
        kernel.advance();self.assertNotIn('A',self.state.live_players)

    def test_departure_exile_replacement_choice_resumes_without_repeating_removal(self):
        ref=self.state.add_card('borrowed','creature','A',Zone.BATTLEFIELD,controller='B')
        for key,destination in (('hand',Zone.HAND),('grave',Zone.GRAVEYARD)):
            self.programs.append(CardProgram(key,key,('Enchantment',),replacements=(ZoneReplacement(key,Zone.EXILE,destination),)))
            self.state.add_card(key,key,'D',Zone.BATTLEFIELD)
        kernel=self.kernel();self.poison('B');request=kernel.advance()
        self.assertEqual('replacement_order',request.kind)
        self.assertEqual('C',request.actor) # CR 800.4h: next live seat makes a rule choice.
        restored=RulesKernel.restore(kernel.snapshot(),self.programs)
        for k in (kernel,restored):k.answer(request.request_id,request.actor,[0])
        self.assertEqual(kernel.snapshot(),restored.snapshot())
        self.assertEqual(1,len([e for e in kernel.semantic_events if e['kind']=='players_departed']))
        self.assertIn(self.state.get(self.state.current(ref.card_id)).zone,(Zone.HAND,Zone.GRAVEYARD))

    def test_foreign_owned_commander_gets_its_surviving_owners_zone_choice(self):
        ref=self.state.add_card('commander','creature','A',Zone.BATTLEFIELD,controller='B',commander=True)
        kernel=self.kernel();self.poison('B');request=kernel.advance()
        self.assertEqual('commander_sba',request.kind);self.assertEqual('A',request.actor)
        kernel.answer(request.request_id,'A',[0])
        self.assertEqual(Zone.COMMAND,self.state.get(self.state.current(ref.card_id)).zone)

    def test_stack_removes_departed_players_abilities_but_preserves_other_controllers_lki(self):
        ref=self.state.add_card('ownedB','creature','B',Zone.BATTLEFIELD)
        kernel=self.kernel()
        kernel.stack=[kernel._frame(self.state.get(ref),'B',(GainLife(9),)),
                      kernel._frame(self.state.get(ref),'C',(GainLife(2),))]
        self.poison('B');kernel.advance();self.drain(kernel)
        self.assertEqual(40,self.state.life('B'));self.assertEqual(42,self.state.life('C'))

    def test_simultaneous_lethal_creature_damage_and_player_loss_keeps_surviving_dies_trigger(self):
        watcher=CardProgram('watcher','Watcher',('Enchantment',),abilities=(AbilityProgram('dies',
            EventPattern('zone_changed',from_zone=Zone.BATTLEFIELD,to_zone=Zone.GRAVEYARD,types=('Creature',)),(GainLife(1),)),))
        self.programs.append(watcher);self.state.add_card('watch','watcher','C',Zone.BATTLEFIELD)
        ref=self.state.add_card('ownedB','creature','B',Zone.BATTLEFIELD)
        self.state.damage_batch(({'source':self.state.get(self.source),'target':ref,'amount':2},
                                 {'source':self.state.get(self.source),'target':'B','amount':40}))
        kernel=self.kernel();kernel.advance();self.drain(kernel)
        self.assertEqual(41,self.state.life('C'))
        self.assertEqual(Zone.OUTSIDE,self.state.get(self.state.current(ref.card_id)).zone)
