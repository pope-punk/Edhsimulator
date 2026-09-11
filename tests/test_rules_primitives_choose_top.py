"""Bounded top-card choices retain privacy, exact stages and replacement replay."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment

class ChooseTopTests(unittest.TestCase):
    def game(self,extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(CardProgram('driver','Driver',('Artifact',)),)+tuple(extra)
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('driver','driver','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def library(self,definitions,actor='A'):
        return [self.state.add_card(actor+str(i),'catalog:'+d,actor,Zone.LIBRARY) for i,d in enumerate(definitions)]

    def effect(self,amount=4,reveal=False,count=1):return ChooseFromTop(amount,Selector(Zone.LIBRARY,types=('Land',),relation='owned'),count,reveal)
    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)
    def answer(self,indexes,kernel=None):
        kernel=kernel or self.kernel;q=kernel.pending_choice
        return kernel.answer(q.request_id,q.actor,indexes)

    def test_printed_cast_reveals_exact_window_and_preserves_unseen_library(self):
        self.game();refs=self.library(['island','sol-ring','forest','sol-ring','plains','sol-ring'])
        spell=self.state.add_card('satyr','catalog:satyr-wayfinder','A',Zone.HAND)
        self.state.add_mana('A',('C','G'));self.kernel.commit_action(self.kernel.quote_cast('cast','A',spell),Payment((('C',1),('G',1))));self.drain()
        q=self.kernel.pending_choice;self.assertEqual('choose_top',q.kind);self.assertEqual([refs[4],refs[2]],[o.ref for o in q.options])
        adapter=RulesActorAdapter(self.kernel)
        for actor in ('A','B'):
            packet=adapter.packet(actor);self.assertEqual([r.to_json() for r in reversed(refs[2:])],[r['ref'] for r in packet['library_observation']['cards']])
            self.assertNotIn('library_search',packet)
        self.answer([0]);self.assertEqual([refs[0],refs[1]],[o.ref for o in self.state.zone('A',Zone.LIBRARY)])
        self.assertEqual(['A4'],[o.ref.card_id for o in self.state.zone('A',Zone.HAND)])
        deaths=[e for e in self.state.events if e.before.zone==Zone.LIBRARY and e.after.zone==Zone.GRAVEYARD]
        self.assertEqual({'A2','A3','A5'},{e.before.ref.card_id for e in deaths});self.assertEqual(1,len({e.batch for e in deaths}))
        self.assertFalse(any(e['kind']=='library_searched' for e in self.kernel.semantic_events))

    def test_private_inspection_and_optional_multi_selection_do_not_expose_unseen_cards(self):
        self.game();refs=self.library(['forest','forest','forest','forest','forest'])
        self.kernel.execute_for_scenario(self.ref,'A',(self.effect(3,count=2),));adapter=RulesActorAdapter(self.kernel)
        self.assertNotIn('library_observation',adapter.packet('B'));self.assertEqual(3,len(adapter.packet('A')['library_observation']['cards']))
        self.assertEqual('waiting',adapter.packet('B')['decision']['kind']);self.answer([0,2])
        self.assertEqual({'A4','A2'},{o.ref.card_id for o in self.state.zone('A',Zone.HAND)})
        self.assertEqual([refs[0],refs[1]],[o.ref for o in self.state.zone('A',Zone.LIBRARY)])

    def test_empty_short_no_match_and_decline_do_not_offer_pointless_choices(self):
        for defs,decline in (([],False),(['sol-ring'],False),(['forest'],True)):
            self.game();self.library(defs);self.kernel.execute_for_scenario(self.ref,'A',(self.effect(),))
            if decline:self.answer([])
            self.assertIsNone(self.kernel.pending_choice);self.assertEqual(len(defs),len(self.state.zone('A',Zone.GRAVEYARD)))
        self.game();self.library(['forest']);self.kernel.execute_for_scenario(self.ref,'A',(self.effect(0),))
        self.assertFalse(self.kernel.library_observations);self.assertEqual(1,len(self.state.zone('A',Zone.LIBRARY)))

    def test_remainder_replacement_checkpoint_does_not_repeat_reveal_or_hand_move(self):
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,from_zone=Zone.LIBRARY,optional=True),))
        self.game((redirect,));self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD);refs=self.library(['sol-ring','forest'])
        self.kernel.execute_for_scenario(self.ref,'A',(self.effect(reveal=True),));self.answer([0])
        self.assertEqual(['A1'],[o.ref.card_id for o in self.state.zone('A',Zone.HAND)])
        self.assertEqual('replacement_optional',self.kernel.pending_choice.kind)
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        q=self.kernel.pending_choice;command={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[0]}
        adapter.submit(q.actor,command);replay.submit(q.actor,command);self.assertEqual(adapter.archive(),replay.archive())
        self.assertEqual(1,sum(e.before.ref==refs[1] for e in self.state.events));self.assertEqual(1,sum(e['kind']=='cards_revealed' for e in self.kernel.semantic_events))
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('A0')).zone)
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):adapter.submit(q.actor,command)
        self.assertEqual(before,self.kernel.snapshot())

    def test_selected_hand_destination_replacement_resumes_before_remainder(self):
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.HAND,Zone.EXILE,from_zone=Zone.LIBRARY,optional=True),))
        self.game((redirect,));self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD);self.library(['sol-ring','forest'])
        self.kernel.execute_for_scenario(self.ref,'A',(self.effect(),));self.answer([0])
        self.assertEqual(2,len(self.state.zone('A',Zone.LIBRARY)));restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.answer([0]);self.answer([0],restored);self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('A1')).zone);self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('A0')).zone)

    def test_copied_entry_uses_copy_controllers_library(self):
        self.game();self.library(['forest'],'A');self.library(['plains'],'B')
        ref=self.state.add_card('copy','catalog:forest','B',Zone.HAND)
        before=self.state.objects(Zone.BATTLEFIELD);views=self.kernel.characteristics()
        events=self.state.move((ZoneMove(ref,Zone.BATTLEFIELD,'B',copied_definition='catalog:satyr-wayfinder'),),'fixture-copy')
        self.kernel._collect(events,before,self.state.objects(Zone.BATTLEFIELD),views);self.kernel.advance();self.drain()
        self.assertEqual('B',self.kernel.pending_choice.actor);self.answer([0]);self.assertEqual(1,len(self.state.zone('A',Zone.LIBRARY)))
        self.assertEqual(['B0'],[o.ref.card_id for o in self.state.zone('B',Zone.HAND)])

    def test_validation_codec_and_mana_classification(self):
        good=self.effect();base=CardProgram('test','Test',('Artifact',),spell_effects=(good,))
        self.assertEqual(validate(base),validate(decode(encode(base))))
        for bad in (replace(good,amount=-1),replace(good,amount=True),replace(good,count=-1),replace(good,count=True),replace(good,reveal=1),replace(good,selector=Selector(Zone.HAND,relation='owned')),replace(good,selector=Selector(Zone.LIBRARY,relation='any'))):
            with self.assertRaises(RulesViolation):validate(replace(base,spell_effects=(bad,)))
        ability=ActivatedProgram('mana',CostSpec(),(AddMana(('G',)),good),mana_ability=True)
        with self.assertRaises(RulesViolation):validate(replace(base,activated=(ability,)))

    def test_rejuvenator_cast_private_tapped_entry_and_random_bottom_preserve_unseen_prefix(self):
        self.game();refs=self.library(['sol-ring','sol-ring','sol-ring','forest','sol-ring','sol-ring','sol-ring'])
        spell=self.state.add_card('elf','catalog:elvish-rejuvenator','A',Zone.HAND);self.state.add_mana('A',('C','C','G'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',spell),Payment((('C',2),('G',1))));self.drain()
        self.assertNotIn('library_observation',RulesActorAdapter(self.kernel).packet('B'))
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs);self.answer([0]);self.answer([0],restored)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot());land=self.state.get(self.state.current('A3'));self.assertTrue(land.tapped);self.assertEqual(Zone.BATTLEFIELD,land.zone)
        library=self.state.zone('A',Zone.LIBRARY);self.assertEqual(refs[:2],[o.ref for o in library[-2:]])
        self.assertEqual({'A2','A4','A5','A6'},{o.ref.card_id for o in library[:-2]})
        for ref in (refs[2],refs[4],refs[5],refs[6]):
            with self.assertRaises(RulesViolation):self.state.get(ref)
        self.assertFalse(any(e['kind']=='library_shuffled' for e in self.kernel.semantic_events))

    def test_entry_replacement_boundary_precedes_subset_randomization_and_replays(self):
        replacement=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.BATTLEFIELD,Zone.EXILE,from_zone=Zone.LIBRARY,optional=True),))
        self.game((replacement,));self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD);refs=self.library(['sol-ring','forest','sol-ring'])
        effect=replace(self.effect(),destination=Zone.BATTLEFIELD,remainder='random_bottom',tapped=True)
        self.kernel.execute_for_scenario(self.ref,'A',(effect,));self.answer([0]);self.assertEqual(refs,[o.ref for o in self.state.zone('A',Zone.LIBRARY)])
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs);q=self.kernel.pending_choice
        command={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[0]}
        adapter.submit(q.actor,command);replay.submit(q.actor,command);self.assertEqual(adapter.archive(),replay.archive())
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('A1')).zone)
        self.assertEqual({'A0','A2'},{o.ref.card_id for o in self.state.zone('A',Zone.LIBRARY)})

    def test_random_bottom_subset_validation_is_atomic_and_randomness_is_replayable(self):
        orders=set()
        for seed in range(12):
            state=RulesState(('A','B'),seed=seed)
            refs=[state.add_card(str(i),'driver','A',Zone.LIBRARY) for i in range(4)]
            other=state.add_card('other','driver','B',Zone.LIBRARY)
            before=state.snapshot()
            for invalid in ((refs[0],refs[0]),(other,)):
                with self.assertRaises(RulesViolation):state.random_bottom('A',invalid)
                self.assertEqual(before,state.snapshot())
            state.random_bottom('A',refs[1:]);orders.add(tuple(o.ref.card_id for o in state.zone('A',Zone.LIBRARY)[:-1]))
            self.assertEqual(refs[0],state.zone('A',Zone.LIBRARY)[-1].ref);self.assertEqual(0,state.event_count)
        self.assertGreater(len(orders),1)

    def test_invalid_top_destinations_and_tapped_hand_are_rejected(self):
        good=self.effect();base=CardProgram('test','Test',('Artifact',))
        for bad in (replace(good,destination=Zone.EXILE),replace(good,destination='hand'),replace(good,tapped=True),replace(good,tapped=1),replace(good,remainder='shuffle')):
            with self.assertRaises(RulesViolation):validate(replace(base,spell_effects=(bad,)))
