"""Death Grasp composes shared X costs, any-target damage and independent life gain."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,PlayerRef,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_adapter import RulesActorAdapter


class DeathGraspTests(unittest.TestCase):
    def game(self,x=3,types=('Creature',)):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(CardProgram('body','Body',types,power=4 if 'Creature' in types else None,toughness=4 if 'Creature' in types else None),)
        self.state=RulesState(('A','B'));self.spell=self.state.add_card('spell','catalog:death-grasp','A',Zone.HAND)
        self.body=self.state.add_card('body','body','B',Zone.BATTLEFIELD)
        if 'Planeswalker' in types:self.state.add_counters(self.body,'loyalty',5)
        if 'Battle' in types:self.state.add_counters(self.body,'defense',5)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
        self.state.add_mana('A',('W','B')+('C',)*x);self.x=x
        self.payment=Payment((('W',1),('B',1))+((('C',x),) if x else ()))

    def cast(self,target):
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.spell,(target,),x_value=self.x),self.payment)

    def drain(self):
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)

    def test_player_target_and_self_target_use_announced_x(self):
        for player,expected in (('B',(43,37)),('A',(40,40))):
            self.game();self.cast(PlayerRef(player));self.drain()
            self.assertEqual(expected,tuple(self.state.life(p) for p in self.state.players));self.assertEqual((),self.state.mana_pool('A'))

    def test_each_permanent_target_type_uses_shared_damage_result(self):
        for types,counter in ((('Creature',),None),(('Planeswalker',),'loyalty'),(('Battle',),'defense')):
            self.game(types=types);self.cast(self.body);self.drain();obj=self.state.get(self.body)
            self.assertEqual(43,self.state.life('A'))
            if counter:self.assertEqual(((counter,2),),obj.counters);self.assertEqual(0,obj.damage_marked)
            else:self.assertEqual(3,obj.damage_marked)

    def test_zero_x_pays_colored_cost_without_damage_or_life_events(self):
        self.game(0);self.cast(PlayerRef('B'));self.drain()
        self.assertEqual((40,40),tuple(self.state.life(p) for p in self.state.players));self.assertEqual((),self.state.mana_pool('A'))
        self.assertFalse(any(e['kind'] in ('damage_dealt','life_gained') for e in self.kernel.semantic_events))

    def test_target_leaves_before_resolution_so_no_life_is_gained(self):
        self.game();self.cast(self.body);self.state.move((ZoneMove(self.body,Zone.EXILE),),'fixture-response');self.drain()
        self.assertEqual(40,self.state.life('A'));self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('spell')).zone)

    def test_illegal_target_and_incorrect_payment_leave_state_unchanged(self):
        self.game(types=('Artifact',));before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',self.spell,(self.body,),x_value=3)
        self.assertEqual(before,self.kernel.snapshot())
        quote=self.kernel.quote_cast('bad','A',self.spell,(PlayerRef('B'),),x_value=3)
        with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,Payment((('W',1),('B',1),('C',2))))
        self.assertEqual(before,self.kernel.snapshot())
        self.kernel.open_window_for_scenario('B','upkeep',priority_actor='A');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad-time','A',self.spell,(PlayerRef('B'),),x_value=3)
        self.assertEqual(before,self.kernel.snapshot())

    def test_actor_replay_preserves_x_and_stack_checkpoint(self):
        self.game();adapter=RulesActorAdapter(self.kernel)
        adapter.submit('A',{'kind':'cast','revision':self.kernel.revision,'action_id':'cast','source':self.spell.to_json(),'targets':[{'player':'B'}],'x_value':3,'payment':{'mana':{'W':1,'B':1,'C':3},'taps':[]}})
        self.assertEqual(3,adapter.packet('B')['stack'][0]['chosen_x'])
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        while self.kernel.stack:adapter.submit(self.kernel.priority,{'kind':'pass','revision':self.kernel.revision})
        while restored.stack:restored.pass_priority(restored.priority)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        for actor in self.state.players:self.assertEqual(adapter.packet(actor),replay.packet(actor))
