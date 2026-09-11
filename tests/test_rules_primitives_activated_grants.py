"""Layer-six grants use recipient costs, identities and inherited runtime behavior."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed

class ActivatedGrantsTests(unittest.TestCase):
    def game(self,zone=Zone.BATTLEFIELD,extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+tuple(extra)
        self.state=RulesState(('A','B'));self.lantern=self.state.add_card('lantern','catalog:chromatic-lantern','A',zone)
        self.land=self.state.add_card('land','catalog:forest','A',Zone.BATTLEFIELD);self.other=self.state.add_card('other','catalog:forest','B',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
    def grants(self,ref=None):return tuple(a for a in self.kernel.activated_abilities(self.state.get(ref or self.land)) if a.ability_id.startswith('granted:'))
    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)

    def test_printed_cast_grants_own_lands_and_keeps_intrinsic_mana(self):
        self.game(Zone.HAND);self.state.add_mana('A',('C','C','C'));self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.lantern),Payment((('C',3),)));self.drain();self.lantern=self.state.current('lantern')
        self.assertEqual(1,len(self.grants()));self.assertFalse(self.grants(self.other));self.assertTrue(any(a.ability_id=='intrinsic-land:Forest' for a in self.kernel.activated_abilities(self.state.get(self.land))))
        self.kernel.open_window_for_scenario('A');q=self.kernel.commit_action(self.kernel.quote_activation('mana','A',self.land,self.grants()[0].ability_id),Payment())
        self.assertFalse(self.kernel.stack);self.assertTrue(self.state.get(self.land).tapped);self.assertFalse(self.state.get(self.lantern).tapped)
        self.kernel.answer(q.request_id,'A',[1]);self.assertEqual((('U',1),),self.state.mana_pool('A'))

    def test_copy_phasing_control_and_multiple_sources_have_distinct_grants(self):
        self.game();second=self.state.add_card('second','catalog:forest','A',Zone.HAND)
        self.state.move((ZoneMove(second,Zone.BATTLEFIELD,'A',copied_definition='catalog:chromatic-lantern'),),'fixture-copy');second=self.state.current('second')
        self.assertEqual(2,len({a.ability_id for a in self.grants()}))
        self.state.phase(self.lantern,True);self.assertEqual(1,len(self.grants()))
        self.state.change_control(second,'B');self.assertFalse(self.grants());self.assertEqual(1,len(self.grants(self.other)))

    def test_granted_nonmana_activation_survives_granter_departure_and_replays(self):
        ability=ActivatedProgram('gain',CostSpec(tap_source=True),(GainLife(2),))
        grant=CardProgram('grant','Grant',('Enchantment',),continuous=(ContinuousProgram('give',Selector(Zone.BATTLEFIELD,types=('Land',),relation='controlled'),(AddActivated(ability),)),))
        self.game(Zone.GRAVEYARD,(grant,));giver=self.state.add_card('grant','grant','A',Zone.BATTLEFIELD)
        self.kernel.commit_action(self.kernel.quote_activation('gain','A',self.land,self.grants()[0].ability_id),Payment())
        self.state.move((ZoneMove(giver,Zone.EXILE),),'response');self.assertFalse(self.grants())
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs);self.drain();self.drain(replay.kernel)
        self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot());self.assertEqual(42,self.state.life('A'))

    def test_granted_abilities_are_not_copiable_values_and_public_packet_exposes_ids(self):
        self.game();packet=RulesActorAdapter(self.kernel).packet('A');row=next(r for r in packet['zones']['battlefield']['A'] if r['ref']==self.land.to_json())
        self.assertEqual(self.grants()[0].ability_id,row['granted_abilities'][0]['ability_id'])
        copy=self.state.add_card('copy','catalog:forest','B',Zone.HAND)
        self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,'B',copied_definition=self.state.get(self.land).effective_definition),),'fixture-copy')
        self.assertFalse(self.grants(self.state.current('copy')))

    def test_departed_recipient_last_known_grants_serialize(self):
        self.game();self.kernel.execute_for_scenario(self.land,'A',(Move('source',Zone.EXILE),))
        self.assertTrue(self.kernel.last_known[self.land][1].granted_abilities)
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs);self.assertEqual(self.kernel.snapshot(),restored.snapshot())

    def test_granted_tap_ability_obeys_summoning_sickness_and_compiler_guards(self):
        self.game();self.kernel.execute_for_scenario(self.land,'A',(UntilEndOfTurn('source',(ChangeTypes(add=('Creature',)),SetPT(2,2))),))
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',self.land,self.grants()[0].ability_id)
        ability=ActivatedProgram('mana',CostSpec(tap_source=True),(AddMana(('G',)),),mana_ability=True)
        for bad in (replace(ability,zone=Zone.HAND),replace(ability,ability_id='granted:collision'),replace(ability,mana_ability=False)):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Artifact',),continuous=(ContinuousProgram('grant',Selector(Zone.BATTLEFIELD),(AddActivated(bad),)),)))

    def test_optimized_and_exhaustive_layers_agree_on_source_scoped_grants(self):
        from edh_gauntlet.rules_characteristics import evaluate,evaluate_exhaustive
        self.game();self.state.add_card('second','catalog:chromatic-lantern','A',Zone.BATTLEFIELD)
        kwargs={'life_totals':{p:self.state.life(p) for p in self.state.players},'starting_life_totals':{p:self.state.starting_life(p) for p in self.state.players},'live_players':self.state.live_players}
        fast=evaluate(self.state.objects(),self.kernel.definitions,**kwargs)
        slow=evaluate_exhaustive(self.state.objects(),self.kernel.definitions,**kwargs)
        self.assertEqual(fast,slow);self.assertEqual(2,len({a.ability_id for a in fast[self.land].granted_abilities}))
