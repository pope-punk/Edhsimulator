"""Damage applies every relevant recipient-type result in one state transaction."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel


class DamageCounterTests(unittest.TestCase):
    def game(self,types=('Planeswalker',),keywords=()):
        self.programs=(CardProgram('source','Source',('Creature',),power=2,toughness=2,keywords=('lifelink','deathtouch')),
            CardProgram('target','Target',types,power=8 if 'Creature' in types else None,toughness=8 if 'Creature' in types else None,keywords=keywords))
        self.state=RulesState(('A','B'));self.source=self.state.add_card('source','source','A',Zone.BATTLEFIELD)
        self.target=self.state.add_card('target','target','B',Zone.BATTLEFIELD)
        for kind in ('loyalty','defense'):self.state.add_counters(self.target,kind,5)
        self.kernel=RulesKernel(self.state,self.programs)

    def test_planeswalker_damage_removes_loyalty_and_lifelink_uses_full_damage(self):
        self.game();self.kernel._deal_damage(((self.state.get(self.source),self.target,3),))
        obj=self.state.get(self.target);self.assertEqual({'loyalty':2,'defense':5},dict(obj.counters))
        self.assertEqual(0,obj.damage_marked);self.assertFalse(obj.deathtouch_hit);self.assertEqual(43,self.state.life('A'))
        self.kernel.advance();self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.target).zone)
        self.kernel._deal_damage(((self.state.get(self.source),self.target,9),));self.kernel.advance()
        self.assertEqual(52,self.state.life('A'));self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('target')).zone)

    def test_animated_planeswalker_applies_both_results_and_zero_loyalty_ignores_indestructible(self):
        self.game(('Creature','Planeswalker'),('indestructible',))
        self.kernel._deal_damage(((self.state.get(self.source),self.target,5),));obj=self.state.get(self.target)
        self.assertEqual(5,obj.damage_marked);self.assertTrue(obj.deathtouch_hit);self.assertNotIn('loyalty',dict(obj.counters))
        self.kernel.advance();self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('target')).zone)

    def test_battle_damage_removes_defense_without_marking_creature_damage(self):
        self.game(('Battle',));self.kernel._deal_damage(((self.state.get(self.source),self.target,2),))
        self.assertEqual({'loyalty':5,'defense':3},dict(self.state.get(self.target).counters))
        self.assertEqual(0,self.state.get(self.target).damage_marked)
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())

    def test_multiple_assignments_share_remaining_counters_and_one_revision(self):
        self.game(('Creature','Planeswalker','Battle'))
        before=self.state.sequence
        self.kernel._deal_damage(((self.state.get(self.source),self.target,2),(self.state.get(self.source),self.target,2)))
        obj=self.state.get(self.target);self.assertEqual({'loyalty':1,'defense':1},dict(obj.counters))
        self.assertEqual(4,obj.damage_marked);self.assertEqual(before+1,self.state.sequence)
        self.assertEqual(44,self.state.life('A'))

    def test_invalid_later_recipient_leaves_whole_damage_batch_unpaid(self):
        self.game();before=self.state.snapshot();source=self.state.get(self.source)
        with self.assertRaises(RulesViolation):self.state.damage_batch((
            {'source':source,'target':self.target,'amount':3,'recipient_types':('Planeswalker',),'lifelink':True},
            {'source':source,'target':self.target,'amount':1,'recipient_types':('Land',)}))
        self.assertEqual(before,self.state.snapshot())

    def test_zero_damage_does_not_remove_counters_or_gain_life(self):
        self.game();before=self.state.snapshot();self.kernel._deal_damage(((self.state.get(self.source),self.target,0),))
        self.assertEqual(before,self.state.snapshot())
