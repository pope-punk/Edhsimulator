"""Additive life replacements share ordinary gains and atomic lifelink damage."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class LifeReplacementTests(unittest.TestCase):
    def game(self,zone=Zone.BATTLEFIELD):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(CardProgram('link','Link',('Creature',),power=3,toughness=5,keywords=('lifelink',)),)
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('angel','catalog:angel-of-vitality','A',zone)
        self.link=self.state.add_card('link','link','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def test_printed_cast_flying_and_life_threshold_update(self):
        self.game(Zone.HAND);self.state.lose_life_batch(('A',),16);self.state.add_mana('A',('C','C','W'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.ref),Payment((('C',2),('W',1))))
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
        self.ref=self.state.current('angel');self.assertEqual(2,self.kernel.effective(self.ref).power)
        self.assertIn('flying',self.kernel.effective(self.ref).keywords)
        self.kernel.execute_for_scenario(self.ref,'A',(GainLife(1),))
        self.assertEqual(26,self.state.life('A'));self.assertEqual(4,self.kernel.effective(self.ref).power)

    def test_zero_and_opponent_gains_are_not_augmented(self):
        self.game();self.kernel.execute_for_scenario(self.ref,'A',(GainLife(0),));self.assertEqual(40,self.state.life('A'))
        self.kernel.execute_for_scenario(self.ref,'B',(GainLife(2),));self.assertEqual(42,self.state.life('B'))
        self.kernel.execute_for_scenario(self.ref,'A',(GainLife(2),));self.assertEqual(43,self.state.life('A'))

    def test_multiple_additive_sources_stack_without_an_order_choice(self):
        self.game();self.state.add_card('second','catalog:angel-of-vitality','A',Zone.BATTLEFIELD)
        self.assertIsNone(self.kernel.execute_for_scenario(self.ref,'A',(GainLife(3),)))
        self.assertEqual(45,self.state.life('A'))
        event=[e for e in self.kernel.semantic_events if e['kind']=='life_gained'][-1];self.assertEqual(5,event['amount'])

    def test_lifelink_split_damage_has_one_bonus_per_source_event(self):
        self.game();source=self.state.get(self.link)
        self.kernel._deal_damage([(source,'B',2),(source,self.ref,1)])
        self.assertEqual(44,self.state.life('A'));self.assertEqual(38,self.state.life('B'))
        events=[e for e in self.kernel.semantic_events if e['kind']=='life_gained']
        self.assertEqual([4],[e['amount'] for e in events])

    def test_two_lifelink_sources_have_separate_bonuses_and_atomic_damage(self):
        self.game();other=self.state.add_card('other','link','A',Zone.BATTLEFIELD)
        enemy=self.state.add_card('enemy','catalog:forest','B',Zone.BATTLEFIELD)
        self.state.lose_life_batch(('A',),39)
        self.kernel._deal_damage([(self.state.get(self.link),'B',1),(self.state.get(other),'B',1),(self.state.get(enemy),'A',4)])
        self.assertEqual(1,self.state.life('A'));self.assertEqual(38,self.state.life('B'))
        self.assertEqual([2,2],[e['amount'] for e in self.kernel.semantic_events if e['kind']=='life_gained'])

    def test_copy_control_and_phasing_determine_replacement_recipient(self):
        self.game(Zone.GRAVEYARD);copy=self.state.add_card('copy','catalog:forest','B',Zone.HAND)
        self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,'B',copied_definition='catalog:angel-of-vitality'),),'fixture-copy');copy=self.state.current('copy')
        self.kernel.execute_for_scenario(copy,'B',(GainLife(1),));self.assertEqual(42,self.state.life('B'))
        self.state.phase(copy,True);self.kernel.execute_for_scenario(self.link,'B',(GainLife(1),));self.assertEqual(43,self.state.life('B'))
        self.state.phase(copy,False);self.state.change_control_batch((copy,),'A')
        self.kernel.execute_for_scenario(copy,'A',(GainLife(1),));self.assertEqual(42,self.state.life('A'))

    def test_checkpoint_and_actor_replay_apply_replacement_once(self):
        self.game();q=self.kernel.execute_for_scenario(self.ref,'A',(May((GainLife(3),)),))
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        command={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[0]}
        for item in (adapter,replay):item.submit('A',command)
        self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot());self.assertEqual(44,self.state.life('A'))
        with self.assertRaises(RulesViolation):adapter.submit('A',command)

    def test_validation_and_state_lifelink_gain_reject_malformed_values_atomically(self):
        for rule in (LifeGainReplacement('',1),LifeGainReplacement('bad',0),LifeGainReplacement('bad',True),LifeGainReplacement('bad',1,'target')):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Enchantment',),life_gain_replacements=(rule,)))
        self.game();before=self.state.snapshot()
        for value in (-1,True):
            with self.assertRaises(RulesViolation):self.state.damage_batch([{'source':self.state.get(self.link),'target':'B','amount':1,'lifelink':True,'lifelink_gain':value}])
            self.assertEqual(before,self.state.snapshot())
