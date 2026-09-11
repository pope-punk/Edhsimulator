"""August 2026 mana classification distinguishes zone movement from rearrangement."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class LibraryManaClassificationTests(unittest.TestCase):
    def game(self,effect,mana,count=2,extra=()):
        self.program=CardProgram('source','Source',('Artifact',),activated=(ActivatedProgram('use',CostSpec(tap_source=True),(AddMana(('G',)),effect),mana_ability=mana),))
        self.programs=(self.program,CardProgram('land','Synthetic land',('Land',)))+tuple(extra)
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('source','source','B',Zone.BATTLEFIELD)
        for i in range(count):self.state.add_card(str(i),'land','B',Zone.LIBRARY)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A',priority_actor='B')
    def activate(self):return self.kernel.commit_action(self.kernel.quote_activation('use','B',self.ref,'use'),Payment())
    def drain(self):
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)
    def ability(self,effect):return ActivatedProgram('use',CostSpec(),(AddMana(('G',)),effect))

    def test_positive_surveil_uses_stack_and_resolves_private_choice(self):
        self.game(Surveil(1),False);self.activate();self.assertEqual(1,len(self.kernel.stack));self.assertFalse(self.state.mana_pool('B'))
        self.drain();q=self.kernel.pending_choice;self.assertEqual('surveil',q.kind)
        self.assertEqual((('G',1),),self.state.mana_pool('B'));self.assertEqual('waiting',RulesActorAdapter(self.kernel).packet('A')['decision']['kind'])
        self.kernel.answer(q.request_id,'B',[1,0]);self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('1')).zone)
        with self.assertRaises(RulesViolation):self.game(Surveil(1),True)

    def test_empty_library_does_not_change_static_classification(self):
        self.game(Surveil(1),False,count=0);self.activate();self.assertEqual(1,len(self.kernel.stack));self.drain()
        self.assertEqual((('G',1),),self.state.mana_pool('B'));self.assertFalse(self.kernel.pending_choice)
        self.assertFalse(activation_is_mana(self.program.activated[0]))

    def test_zero_card_instructions_and_reordering_only_are_not_zone_movement(self):
        selector=Selector(Zone.LIBRARY,relation='owned')
        effects=(Draw(0),Mill(0),Surveil(0),Scry(2),LookTop(2),SearchLibrary(selector,Zone.LIBRARY),
            ChooseFromTop(0,selector),ChooseFromTop(2,selector,count=0,remainder='random_bottom'))
        for effect in effects:
            with self.subTest(effect=effect):
                ability=replace(self.ability(effect),mana_ability=True)
                self.assertTrue(activation_is_mana(ability));validate(CardProgram('test','Test',('Artifact',),activated=(ability,)))

    def test_scry_and_look_are_immediate_private_and_replayable(self):
        self.game(May((Scry(1),LookTop(2))),True);self.activate();q=self.kernel.pending_choice
        self.kernel.answer(q.request_id,'B',[0]);self.assertEqual('scry',self.kernel.pending_choice.kind);self.assertFalse(self.kernel.stack)
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        while self.kernel.pending_choice:
            q=self.kernel.pending_choice
            self.assertNotIn('library_observation',adapter.packet('A'))
            cmd={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':list(range(len(q.options)))}
            adapter.submit('B',cmd);replay.submit('B',cmd);self.assertEqual(adapter.archive(),replay.archive())
        self.assertEqual('B',self.kernel.priority);self.assertEqual(0,self.state.event_count);self.assertFalse(self.kernel.stack)

    def test_search_to_top_is_immediate_but_search_out_of_library_is_not(self):
        selector=Selector(Zone.LIBRARY,relation='owned');self.game(SearchLibrary(selector,Zone.LIBRARY),True)
        q=self.activate();self.assertEqual('library_search',q.kind);self.assertFalse(self.kernel.stack)
        self.kernel.answer(q.request_id,'B',[0]);self.assertEqual(0,self.state.event_count);self.assertEqual('0',self.state.zone('B',Zone.LIBRARY)[-1].ref.card_id)
        self.game(SearchLibrary(selector,Zone.HAND),False);self.activate();self.assertEqual(1,len(self.kernel.stack));self.assertFalse(self.state.mana_pool('B'))

    def test_random_bottom_without_selection_preserves_zone_and_uses_no_stack(self):
        effect=ChooseFromTop(2,Selector(Zone.LIBRARY,relation='owned'),count=0,remainder='random_bottom')
        self.game(effect,True);self.activate();self.assertFalse(self.kernel.stack);self.assertFalse(self.kernel.pending_choice)
        self.assertEqual(2,len(self.state.zone('B',Zone.LIBRARY)));self.assertEqual(0,self.state.event_count)
        self.assertFalse(activation_is_mana(self.ability(replace(effect,count=1))))
        self.assertFalse(activation_is_mana(self.ability(replace(effect,remainder='graveyard'))))

    def test_fallback_movement_counts_but_future_trigger_body_does_not(self):
        effect=May((GainLife(1),),otherwise=(Surveil(1),))
        self.assertFalse(activation_is_mana(self.ability(effect)))
        future=DelayedTrigger(EventPattern('zone_changed',from_zone=Zone.BATTLEFIELD,subject='self'),(Surveil(1),))
        self.assertTrue(activation_is_mana(self.ability(future)))

    def test_ordinary_replacement_does_not_reclassify_the_activation(self):
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,from_zone=Zone.LIBRARY),))
        self.game(Surveil(1),False,extra=(redirect,));self.state.add_card('redirect','redirect','A',Zone.BATTLEFIELD)
        self.activate();self.assertEqual(1,len(self.kernel.stack));self.drain();q=self.kernel.pending_choice;self.kernel.answer(q.request_id,'B',[1,0])
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('1')).zone);self.assertFalse(activation_is_mana(self.program.activated[0]))
