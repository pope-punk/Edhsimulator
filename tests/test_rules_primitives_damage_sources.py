"""Bound damage sources retain their own characteristics and batch recipients."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed

class DamageSourcesTests(unittest.TestCase):
    def game(self,keywords=(),power=3):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(CardProgram('dealer','Dealer',('Creature',),power=power,toughness=8,keywords=keywords),CardProgram('body','Body',('Creature',),power=1,toughness=8))
        self.state=RulesState(('A','B','C'));self.spell=self.state.add_card('spell','catalog:chandra-s-ignition','A',Zone.HAND)
        self.dealer=self.state.add_card('dealer','dealer','A',Zone.BATTLEFIELD)
        self.own=self.state.add_card('own','body','A',Zone.BATTLEFIELD);self.enemy=self.state.add_card('enemy','body','B',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
    def cast(self):
        self.state.add_mana('A',('C','C','C','R','R'));self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.spell,(self.dealer,)),Payment((('C',3),('R',2))))
    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)

    def test_ignition_printed_cast_attributes_all_damage_to_creature_and_excludes_it(self):
        self.game(('lifelink',));self.cast();self.drain()
        self.assertEqual(0,self.state.get(self.dealer).damage_marked)
        self.assertEqual(3,self.state.get(self.own).damage_marked);self.assertEqual(3,self.state.get(self.enemy).damage_marked)
        self.assertEqual((52,37,37),tuple(self.state.life(p) for p in self.state.players))
        rows=[e for e in self.kernel.semantic_events if e['kind']=='damage_dealt'];self.assertEqual(4,len(rows));self.assertTrue(all(e['source']==self.dealer.to_json() for e in rows))

    def test_deathtouch_and_lifelink_replacement_apply_to_one_simultaneous_source_event(self):
        self.game(('deathtouch','lifelink'));self.state.add_card('angel','catalog:angel-of-vitality','A',Zone.BATTLEFIELD)
        self.cast();self.drain();self.assertEqual(56,self.state.life('A'))
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('own')).zone);self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('enemy')).zone)
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.dealer).zone)

    def test_current_power_at_resolution_and_actor_replay(self):
        self.game();self.cast();self.state.add_counters(self.dealer,'+1/+1',2)
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.drain();self.drain(replay.kernel);self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot());self.assertEqual(35,self.state.life('B'))

    def test_target_leaving_or_changing_controller_prevents_damage(self):
        for leave in (False,True):
            self.game();self.cast()
            if leave:self.state.move((ZoneMove(self.dealer,Zone.EXILE),),'response')
            else:self.state.change_control(self.dealer,'B')
            self.drain();self.assertEqual((40,40,40),tuple(self.state.life(p) for p in self.state.players));self.assertFalse(any(e['kind']=='damage_dealt' for e in self.kernel.semantic_events))

    def test_general_bound_source_can_deal_damage_after_leaving_using_last_known_keywords(self):
        self.game(('lifelink',));effects=(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled',exclude_source=True),(Move('selected',Zone.EXILE),Damage('controller',2,source_subject='selected'))),)
        self.kernel.execute_for_scenario(self.dealer,'A',effects)
        # Only the other own creature was selected; its lack of lifelink is retained.
        self.assertEqual(38,self.state.life('A'));rows=[e for e in self.kernel.semantic_events if e['kind']=='damage_dealt'];self.assertEqual(self.own.to_json(),rows[-1]['source'])

    def test_zero_negative_power_and_invalid_bindings(self):
        for power in (0,-2):
            self.game(power=power);self.cast();self.drain();self.assertEqual(40,self.state.life('B'))
        base=CardProgram('test','Test',('Sorcery',))
        for effect in (Damage('controller',1,source_subject='target'),Damage('controller',1,players=[]),Damage('controller',1,exclude_damage_source=1)):
            with self.assertRaises(RulesViolation):validate(replace(base,spell_effects=(effect,)))
