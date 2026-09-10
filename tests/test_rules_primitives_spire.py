"""Shattered Spire composes counter replacement, sorcery activation and cycling."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class SpireTests(unittest.TestCase):
    def game(self,zone=Zone.BATTLEFIELD):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(CardProgram('both','Both',('Artifact','Creature'),power=2,toughness=2),)
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('spire','catalog:ozolith-the-shattered-spire','A',zone)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)

    def test_printed_cast_and_targeted_counter_includes_self(self):
        self.game(Zone.HAND);self.state.add_mana('A',('C','G'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.ref),Payment((('C',1),('G',1))));self.drain();self.ref=self.state.current('spire')
        self.kernel.open_window_for_scenario('A')
        self.state.add_mana('A',('C','G'))
        self.kernel.commit_action(self.kernel.quote_activation('counter','A',self.ref,'counter',(self.ref,)),Payment((('C',1),('G',1))));self.drain()
        self.assertEqual((('+1/+1',2),),self.state.get(self.ref).counters);self.assertTrue(self.state.get(self.ref).tapped)
        self.assertEqual((),self.state.mana_pool('A'))

    def test_replacement_union_counts_artifact_creature_once_and_excludes_lands_opponents(self):
        self.game()
        for i,(definition,owner,kind,expected) in enumerate((('both','A','+1/+1',2),('catalog:forest','A','+1/+1',1),('both','B','+1/+1',1),('both','A','charge',1))):
            ref=self.state.add_card(str(i),definition,owner,Zone.BATTLEFIELD)
            self.kernel.execute_for_scenario(ref,owner,(AddCounters('source',kind,1),))
            self.assertEqual(expected,dict(self.state.get(ref).counters)[kind])

    def test_sorcery_timing_and_target_restrictions_reject_atomically(self):
        self.game();other=self.state.add_card('other','both','B',Zone.BATTLEFIELD);land=self.state.add_card('land','catalog:forest','A',Zone.BATTLEFIELD)
        self.state.add_mana('A',('C','G'));before=self.kernel.snapshot()
        for target in (other,land):
            with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',self.ref,'counter',(target,))
            self.assertEqual(before,self.kernel.snapshot())
        self.kernel.open_window_for_scenario('B',priority_actor='A');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',self.ref,'counter',(self.ref,))
        self.assertEqual(before,self.kernel.snapshot())

    def test_cycling_discards_before_draw_and_replays(self):
        self.game(Zone.HAND);self.state.add_card('draw','catalog:forest','A',Zone.LIBRARY)
        self.kernel.open_window_for_scenario('B',priority_actor='A')
        self.state.add_mana('A',('C','C'))
        adapter=RulesActorAdapter(self.kernel)
        adapter.submit('A',{'kind':'activate','revision':self.kernel.revision,'action_id':'cycling','source':self.ref.to_json(),'ability_id':'cycling','targets':[],'x_value':0,'payment':{'mana':{'C':2},'taps':[]}})
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('spire')).zone)
        self.assertEqual(Zone.LIBRARY,self.state.get(self.state.current('draw')).zone)
        replay=RulesActorAdapter.replay(adapter.archive(),self.programs);self.drain();self.drain(replay.kernel)
        self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot());self.assertEqual(Zone.HAND,self.state.get(self.state.current('draw')).zone)
        self.assertEqual((),self.state.mana_pool('A'))

    def test_target_control_recheck_prevents_counter_after_control_changes(self):
        self.game();target=self.state.add_card('target','both','A',Zone.BATTLEFIELD);self.state.add_mana('A',('C','G'))
        self.kernel.commit_action(self.kernel.quote_activation('counter','A',self.ref,'counter',(target,)),Payment((('C',1),('G',1))))
        self.state.change_control_batch((target,),'B');self.drain();self.assertEqual((),self.state.get(target).counters)
        self.assertTrue(self.state.get(self.ref).tapped)

    def test_copied_replacement_controller_and_hand_zone_do_not_leak(self):
        self.game(Zone.HAND);target=self.state.add_card('target','both','A',Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(target,'A',(AddCounters('source','+1/+1',1),));self.assertEqual((('+1/+1',1),),self.state.get(target).counters)
        ref=self.state.add_card('copy','catalog:forest','B',Zone.HAND)
        self.state.move((ZoneMove(ref,Zone.BATTLEFIELD,'B',copied_definition='catalog:ozolith-the-shattered-spire'),),'fixture-copy')
        target=self.state.add_card('btarget','both','B',Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(target,'B',(AddCounters('source','+1/+1',1),));self.assertEqual((('+1/+1',2),),self.state.get(target).counters)
