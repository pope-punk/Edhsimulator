"""Top-card arrangements preserve privacy and survive movement replacements."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment


class LibraryArrangementTests(unittest.TestCase):
    def game(self,count=5,extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(CardProgram('driver','Driver',('Artifact',)),)+tuple(extra)
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('driver','driver','A',Zone.BATTLEFIELD)
        for i in range(count):self.state.add_card(str(i),'catalog:forest','A',Zone.LIBRARY)
        self.kernel=RulesKernel(self.state,self.programs)

    def order(self):return [o.ref.card_id for o in reversed(self.state.zone('A',Zone.LIBRARY))]
    def drain(self):
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)
    def answer(self,key):
        r=self.kernel.pending_choice;self.kernel.answer(r.request_id,r.actor,(next(i for i,o in enumerate(r.options) if o.key==key),))

    def test_surveil_partitions_once_moves_simultaneously_and_preserves_unseen_order(self):
        self.game();r=self.kernel.execute_for_scenario(self.ref,'A',(Surveil(3),))
        self.assertEqual('surveil',r.kind);self.assertEqual(['4','3','2'],[o.ref.card_id for o in r.options if o.ref])
        self.kernel.answer(r.request_id,'A',(1,3,2,0))
        self.assertEqual(['3','1','0'],self.order());self.assertEqual({'2','4'},{o.ref.card_id for o in self.state.objects(Zone.GRAVEYARD)})
        self.assertEqual(1,len({e.batch for e in self.state.events}))
        self.assertEqual(1,sum(e['kind']=='surveilled' for e in self.kernel.semantic_events))

    def test_pending_replacement_keeps_partition_private_and_replays_once(self):
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,from_zone=Zone.LIBRARY,optional=True),))
        self.game(extra=(redirect,));self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD)
        r=self.kernel.execute_for_scenario(self.ref,'A',(Surveil(2),Draw(1)))
        adapter=RulesActorAdapter(self.kernel)
        self.assertEqual('waiting',adapter.packet('B')['decision']['kind'])
        self.kernel.answer(r.request_id,'A',(1,2,0));r=self.kernel.pending_choice
        self.assertIsNotNone(r);self.assertEqual(['4','3','2','1','0'],self.order())
        self.assertEqual(0,self.state.event_count)
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        command={'kind':'answer','revision':self.kernel.revision,'request_id':r.request_id,'indexes':[next(i for i,o in enumerate(r.options) if o.key=='yes')]}
        adapter.submit(r.actor,command);replay.submit(r.actor,command)
        self.assertEqual(1,sum(e['kind']=='library_cards_looked' for e in self.kernel.semantic_events))
        self.assertEqual(adapter.archive(),replay.archive());self.assertEqual(Zone.EXILE,self.state.get(self.state.current('4')).zone)
        self.assertEqual(['3'],[o.ref.card_id for o in self.state.objects(Zone.HAND)])
        self.assertEqual(1,sum(e['kind']=='surveilled' for e in self.kernel.semantic_events))

    def test_empty_library_still_surveils_but_zero_does_not(self):
        observer=CardProgram('observer','Observer',('Enchantment',),abilities=(AbilityProgram('watch',EventPattern('surveilled',controller_only=True),(GainLife(1),)),))
        self.game(0,(observer,));self.state.add_card('observer','observer','A',Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(self.ref,'A',(Surveil(0),Surveil(3)));self.drain()
        self.assertEqual(41,self.state.life('A'));self.assertEqual(1,sum(e['kind']=='surveilled' for e in self.kernel.semantic_events))

    def test_look_top_only_reorders_authorized_prefix_without_movement(self):
        self.game();r=self.kernel.execute_for_scenario(self.ref,'A',(LookTop(3),))
        self.assertEqual(3,len(r.options));self.kernel.answer(r.request_id,'A',(2,0,1))
        self.assertEqual(['2','4','3','1','0'],self.order());self.assertEqual(0,self.state.event_count)
        self.assertFalse(any(e['kind'] in {'scried','surveilled'} for e in self.kernel.semantic_events))

    def test_short_look_needs_no_pointless_order_choice(self):
        for n in (0,1):
            self.game(n);self.kernel.execute_for_scenario(self.ref,'A',(LookTop(3),))
            self.assertIsNone(self.kernel.pending_choice);self.assertEqual(n,len(self.order()))
            adapter=RulesActorAdapter(self.kernel)
            self.assertEqual(n,len(adapter.packet('A')['library_observation']['cards']))
            self.assertNotIn('library_observation',adapter.packet('B'))

    def test_observation_is_historical_detached_and_grants_no_hidden_action_permission(self):
        self.game(1);self.kernel.execute_for_scenario(self.ref,'A',(LookTop(3),))
        adapter=RulesActorAdapter(self.kernel);packet=adapter.packet('A');observation=packet['library_observation']
        observed=observation['cards'][0]['ref'];stamp=observation['observed_revision']
        with self.assertRaises(RulesViolation):adapter._visible_ref(observed,'A')
        observation['cards'].clear()
        self.assertEqual(1,len(adapter.packet('A')['library_observation']['cards']))
        self.state.shuffle_library('A')
        self.assertEqual(stamp,adapter.packet('A')['library_observation']['observed_revision'])
        self.assertNotEqual(observed,self.state.zone('A',Zone.LIBRARY)[-1].ref.to_json())
        replay=RulesActorAdapter.replay(RulesActorAdapter(self.kernel).archive(),self.programs)
        self.assertEqual(adapter.packet('A'),replay.packet('A'))

    def test_consider_draws_after_surveillance(self):
        self.game(2);ref=self.state.add_card('consider','catalog:consider','A',Zone.HAND)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('U',))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',ref),Payment((('U',1),)));self.drain()
        r=self.kernel.pending_choice;self.kernel.answer(r.request_id,'A',(1,0))
        self.assertEqual(['0'],[o.ref.card_id for o in self.state.objects(Zone.HAND)])
        self.assertEqual({'consider','1'},{o.ref.card_id for o in self.state.objects(Zone.GRAVEYARD)})

    def test_top_activated_order_and_draw_then_source_on_library_top(self):
        self.game(4);top=self.state.add_card('top','catalog:sensei-s-divining-top','A',Zone.BATTLEFIELD)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('C',))
        self.kernel.commit_action(self.kernel.quote_activation('look','A',top,'look'),Payment((('C',1),)));self.drain()
        r=self.kernel.pending_choice;self.kernel.answer(r.request_id,'A',(2,0,1));self.assertEqual(['1','3','2','0'],self.order())
        self.kernel.open_window_for_scenario('A');self.kernel.commit_action(self.kernel.quote_activation('draw','A',top,'draw'),Payment());self.drain()
        self.assertEqual(['1'],[o.ref.card_id for o in self.state.objects(Zone.HAND)]);self.assertEqual(['top','3','2','0'],self.order())

    def test_top_departing_before_resolution_does_not_return_old_source(self):
        self.game(2);top=self.state.add_card('top','catalog:sensei-s-divining-top','A',Zone.BATTLEFIELD)
        self.kernel.open_window_for_scenario('A');self.kernel.commit_action(self.kernel.quote_activation('draw','A',top,'draw'),Payment())
        # Scenario movement keeps the accepted ability on the stack.
        from edh_gauntlet.rules_state import ZoneMove
        self.state.move((ZoneMove(top,Zone.GRAVEYARD),),'scenario_departure');self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('top')).zone);self.assertEqual(['0'],self.order())

    def test_growth_spiral_can_place_the_just_drawn_land_without_land_play(self):
        self.game(1);spell=self.state.add_card('growth','catalog:growth-spiral','A',Zone.HAND)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('G','U'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',spell),Payment((('G',1),('U',1))));self.drain()
        r=self.kernel.pending_choice;self.kernel.answer(r.request_id,'A',(0,))
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('0')).zone)

    def test_overseer_gains_life_and_draws_on_entry(self):
        self.game(1);ref=self.state.add_card('overseer','catalog:inspiring-overseer','A',Zone.HAND)
        self.kernel.enter(ref,'A');self.drain();self.assertEqual(41,self.state.life('A'));self.assertEqual(1,len(self.state.objects(Zone.HAND)))

    def test_harmonize_draws_three(self):
        self.game();ref=self.state.add_card('harmonize','catalog:harmonize','A',Zone.HAND)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('G','G','C','C'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',ref),Payment((('G',2),('C',2))));self.drain()
        self.assertEqual({'4','3','2'},{o.ref.card_id for o in self.state.objects(Zone.HAND)})

    def test_solemn_searches_basic_tapped_then_offers_death_draw(self):
        self.game(2);ref=self.state.add_card('solemn','catalog:solemn-simulacrum','A',Zone.HAND)
        self.kernel.enter(ref,'A');self.drain();self.answer('yes')
        r=self.kernel.pending_choice;chosen=r.options[0].ref;self.kernel.answer(r.request_id,'A',(0,))
        self.assertTrue(self.state.get(self.state.current(chosen.card_id)).tapped)
        self.kernel.execute_for_scenario(self.state.current('solemn'),'A',(Destroy('source'),));self.drain();self.answer('yes')
        self.assertEqual(1,len(self.state.objects(Zone.HAND)))

    def test_compiler_rejects_invalid_amounts_and_object_filtered_surveil_events(self):
        base=CardProgram('test','Test',('Artifact',))
        for effect in (Surveil(-1),Surveil(True),LookTop(-1),LookTop(ChosenX())):
            with self.assertRaises(RulesViolation):validate(replace(base,spell_effects=(effect,)))
        with self.assertRaises(RulesViolation):validate(replace(base,abilities=(AbilityProgram('bad',EventPattern('surveilled',subject='self'),()),)))
