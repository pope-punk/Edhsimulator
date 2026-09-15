"""Explicit activation origins reuse the ordinary cost, stack and replay pipeline."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_adapter import RulesActorAdapter


class ActivationZoneTests(unittest.TestCase):
    def game(self,key='akroma-s-vengeance',zone=Zone.HAND,extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+extra
        self.state=RulesState(('A','B'))
        self.ref=self.state.add_card('source','catalog:'+key,'A',zone)
        self.draw=self.state.add_card('draw','catalog:forest','A',Zone.LIBRARY)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
        self.state.add_mana('A',('C','C','C'))

    def cycle(self):
        return self.kernel.commit_action(self.kernel.quote_activation('cycle','A',self.ref,'cycling'),Payment((('C',3),)))

    def drain(self):
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)

    def test_both_cards_discard_as_cost_draw_only_after_priority_and_restore(self):
        for key in ('akroma-s-vengeance','raffine-s-tower'):
            with self.subTest(card=key):
                self.game(key);self.cycle()
                self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('source')).zone)
                self.assertEqual((),self.state.mana_pool('A'))
                self.assertEqual(Zone.LIBRARY,self.state.get(self.draw).zone)
                self.assertFalse(self.kernel.stack[-1]['spell'])
                restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
                self.drain()
                while restored.stack:restored.pass_priority(restored.priority)
                self.assertEqual(self.kernel.snapshot(),restored.snapshot())
                self.assertEqual(Zone.HAND,self.state.get(self.state.current('draw')).zone)

    def test_wrong_origin_owner_or_intrinsic_land_ability_reject_without_mutation(self):
        for zone in (Zone.BATTLEFIELD,Zone.GRAVEYARD,Zone.EXILE):
            self.game(zone=zone);before=self.kernel.snapshot()
            with self.assertRaises(RulesViolation):self.cycle()
            self.assertEqual(before,self.kernel.snapshot())
        self.game('raffine-s-tower');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('mana','A',self.ref,'intrinsic-land:Plains')
        self.assertEqual(before,self.kernel.snapshot())
        other=self.state.add_card('other','catalog:raffine-s-tower','B',Zone.HAND);before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('steal','A',other,'cycling')
        self.assertEqual(before,self.kernel.snapshot())

    def test_cycling_uses_instant_timing_and_cannot_discard_a_substitute(self):
        self.game();other=self.state.add_card('other','catalog:forest','A',Zone.HAND)
        # An opponent's upkeep still permits an instant-speed hand activation.
        self.kernel.open_window_for_scenario('B','upkeep',priority_actor='A');self.state.add_mana('A',('C','C','C'))
        quote=self.kernel.quote_activation('cycle','A',self.ref,'cycling');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,Payment((('C',3),),zone_costs=(('discard-source',(other,)),)))
        self.assertEqual(before,self.kernel.snapshot())
        self.kernel.commit_action(quote,Payment((('C',3),)))
        self.assertEqual(Zone.HAND,self.state.get(other).zone)

    def test_replaced_discard_pays_once_across_choice_checkpoint(self):
        replacement=CardProgram('replacement','Replacement',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,optional=True),))
        self.game(extra=(replacement,));self.state.add_card('replacement','replacement','B',Zone.BATTLEFIELD)
        before=self.state.snapshot();request=self.cycle();self.assertEqual(before,self.state.snapshot())
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        for k in (self.kernel,restored):k.answer(request.request_id,'A',[0])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('source')).zone)
        self.assertEqual((),self.state.mana_pool('A'));self.drain()
        self.assertEqual(Zone.HAND,self.state.get(self.state.current('draw')).zone)

    def test_actor_command_replays_and_opponent_hidden_source_is_rejected(self):
        self.game();other=self.state.add_card('other','catalog:raffine-s-tower','B',Zone.HAND)
        adapter=RulesActorAdapter(self.kernel)
        command={'kind':'activate','revision':self.kernel.revision,'action_id':'cycle','source':other.to_json(),'targets':[], 'x_value':0,'payment':{'mana':{'C':3},'taps':[]},'ability_id':'cycling'}
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):adapter.submit('A',command)
        self.assertEqual(before,self.kernel.snapshot())
        command['source']=self.ref.to_json();adapter.submit('A',command)
        while self.kernel.stack:adapter.submit(self.kernel.priority,{'kind':'pass','revision':self.kernel.revision})
        replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        for actor in ('A','B'):self.assertEqual(adapter.packet(actor),replay.packet(actor))

    def test_vengeance_spell_destroys_union_simultaneously_and_spares_lands(self):
        self.game();self.state.add_mana('A',('C','W','W'))
        refs=[self.state.add_card(key,'catalog:'+key,'B',Zone.BATTLEFIELD) for key in ('sol-ring','baleful-strix','cosmos-elixir','spirited-companion','forest')]
        enchant=self.state.add_card('enchant','catalog:acidic-slime','B',Zone.HAND)
        # A plain enchantment fixture separates the union from artifacts/creatures.
        program=CardProgram('enchantment','Enchantment',('Enchantment',));self.programs+=(program,)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('C','C','C','C','W','W'))
        e=self.state.add_card('e','enchantment','B',Zone.BATTLEFIELD)
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.ref),Payment((('C',4),('W',2))));self.drain()
        destroyed=[event for event in self.state.events if event.before.ref in refs[:-1]+[e]]
        self.assertEqual(5,len(destroyed));self.assertEqual(1,len({event.batch for event in destroyed}))
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(refs[-1]).zone);self.assertEqual(Zone.HAND,self.state.get(enchant).zone)

    def test_tower_enters_tapped_and_each_intrinsic_mana_color_works(self):
        for subtype,symbol in (('Plains','W'),('Island','U'),('Swamp','B')):
            self.game('raffine-s-tower');self.kernel.execute_for_scenario(self.ref,'A',(Move('source',Zone.BATTLEFIELD),))
            self.kernel.open_window_for_scenario('A')
            ref=self.state.current('source');self.assertTrue(self.state.get(ref).tapped)
            self.state.set_tapped_batch((ref,),False);self.state.empty_mana_pools()
            self.kernel.commit_action(self.kernel.quote_activation('mana','A',ref,'intrinsic-land:'+subtype),Payment())
            self.assertEqual(((symbol,1),),self.state.mana_pool('A'))

    def test_generic_graveyard_activation_and_invalid_zone_cost_combinations(self):
        ability=ActivatedProgram('return',CostSpec(zone_costs=(ZoneCost('exile','exile'),)),(GainLife(2),),zone=Zone.GRAVEYARD)
        program=CardProgram('grave','Grave',('Creature',),power=1,toughness=1,activated=(ability,))
        self.game(extra=(program,));ref=self.state.add_card('grave','grave','A',Zone.GRAVEYARD)
        self.kernel.commit_action(self.kernel.quote_activation('grave','A',ref,'return'),Payment());self.drain()
        self.assertEqual(42,self.state.life('A'));self.assertEqual(Zone.EXILE,self.state.get(self.state.current('grave')).zone)
        for bad in (replace(ability,zone='hand'),replace(ability,zone=Zone.LIBRARY),replace(ability,cost=CostSpec(tap_source=True)),replace(ability,cost=CostSpec(zone_costs=(ZoneCost('sac','sacrifice'),)))):
            with self.assertRaises(RulesViolation):validate(replace(program,activated=(bad,)))
        self.assertEqual(program,decode(encode(program)))
