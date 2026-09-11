"""Optional branches preserve exact availability and batch their fallback effects."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class OptionalBranchTests(unittest.TestCase):
    def game(self,extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+tuple(extra)
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('angel','catalog:angel-of-invention','A',Zone.HAND)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)
    def enter(self):
        self.kernel.enter(self.ref);self.ref=self.state.current('angel')
    def answer(self,index,kernel=None):
        kernel=kernel or self.kernel;q=kernel.pending_choice;return kernel.answer(q.request_id,q.actor,[index])
    def tokens(self):return tuple(o for o in self.state.objects(Zone.BATTLEFIELD) if o.token)

    def test_printed_cast_counters_are_chosen_on_resolution_and_anthem_excludes_self(self):
        self.game();other=self.state.add_card('other','catalog:elvish-mystic','A',Zone.BATTLEFIELD)
        self.state.add_mana('A',('C','C','C','W','W'));self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.ref),Payment((('C',3),('W',2))))
        self.drain();self.ref=self.state.current('angel');self.assertEqual('may',self.kernel.pending_choice.kind)
        self.assertFalse(self.state.get(self.ref).counters);self.assertEqual(2,self.kernel.effective(other).power)
        self.answer(0);self.assertEqual({'+1/+1':2},dict(self.state.get(self.ref).counters));self.assertFalse(self.tokens())
        view=self.kernel.effective(self.ref);self.assertEqual((4,3),(view.power,view.toughness));self.assertTrue({'flying','vigilance','lifelink'}<=view.keywords)

    def test_declining_creates_two_colorless_servos_in_one_batch(self):
        self.game();self.enter();self.drain();self.answer(1);tokens=self.tokens();self.assertEqual(2,len(tokens))
        for obj in tokens:
            view=self.kernel.effective(obj.ref);self.assertEqual({'Artifact','Creature'},set(view.types));self.assertEqual({'Servo'},set(view.subtypes));self.assertFalse(view.colors)
            self.assertEqual((2,2),(view.power,view.toughness))
        events=[e for e in self.state.events if e.cause=='token_created'];self.assertEqual(1,len({e.batch for e in events}))
        self.assertFalse(self.state.get(self.ref).counters)

    def test_departed_or_phased_source_automatically_takes_fallback(self):
        for phased in (False,True):
            self.game();self.enter()
            if phased:self.state.phase(self.ref,True)
            else:self.state.move((ZoneMove(self.ref,Zone.GRAVEYARD),),'response')
            self.drain();self.assertIsNone(self.kernel.pending_choice);self.assertEqual(2,len(self.tokens()))
            self.assertTrue(all(self.kernel.effective(o.ref).power==1 for o in self.tokens()))

    def test_old_source_reference_does_not_offer_counters_on_reentered_card(self):
        self.game();self.enter();old=self.ref
        self.state.move((ZoneMove(old,Zone.HAND),),'response');hand=self.state.current('angel')
        # Isolate the old accepted trigger while supplying a new incarnation.
        self.state.move((ZoneMove(hand,Zone.BATTLEFIELD),),'scenario_new_incarnation')
        self.drain();self.assertIsNone(self.kernel.pending_choice);self.assertEqual(2,len(self.tokens()))
        self.assertFalse(self.state.get(self.state.current('angel')).counters)

    def test_copied_ability_and_changed_control_keep_trigger_controller(self):
        self.game();copy=self.state.add_card('copy','catalog:forest','B',Zone.HAND)
        before=self.state.objects(Zone.BATTLEFIELD);views=self.kernel.characteristics()
        events=self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,'B',copied_definition='catalog:angel-of-invention'),),'copy')
        self.kernel._collect(events,before,self.state.objects(Zone.BATTLEFIELD),views);self.kernel.advance()
        self.state.change_control(self.state.current('copy'),'A');self.drain()
        self.assertEqual('B',self.kernel.pending_choice.actor);self.answer(1)
        self.assertTrue(all(o.controller=='B' for o in self.tokens()));self.assertEqual(2,len(self.tokens()))
        self.assertTrue(all(self.kernel.effective(o.ref).power==1 for o in self.tokens()))

    def test_counter_replacement_uses_selected_branch_without_fallback(self):
        self.game();self.state.add_card('vorinclex','catalog:vorinclex-monstrous-raider','A',Zone.BATTLEFIELD)
        self.enter();self.drain();self.answer(0)
        self.assertEqual({'+1/+1':4},dict(self.state.get(self.ref).counters));self.assertFalse(self.tokens())

    def test_fallback_token_replacement_recovery_and_duplicate_rejection(self):
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.BATTLEFIELD,Zone.EXILE,types=('Artifact',),optional=True),))
        self.game((redirect,));self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD);self.enter();self.drain();self.answer(1)
        self.assertFalse(self.tokens());adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        while self.kernel.pending_choice:
            q=self.kernel.pending_choice;cmd={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[1]}
            adapter.submit(q.actor,cmd);replay.submit(q.actor,cmd);self.assertEqual(adapter.archive(),replay.archive())
        self.assertEqual(2,len(self.tokens()));before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):adapter.submit(q.actor,cmd)
        self.assertEqual(before,self.kernel.snapshot())

    def test_fallback_is_validated_for_bindings_and_mana_classification(self):
        base=CardProgram('test','Test',('Sorcery',));good=May((GainLife(1),),otherwise=(GainLife(2),))
        self.assertEqual(good,decode(encode(good)))
        for bad in (replace(good,subject='missing'),replace(good,available=Selector(Zone.LIBRARY)),replace(good,otherwise=(Move('missing',Zone.HAND),))):
            with self.assertRaises(RulesViolation):validate(replace(base,spell_effects=(bad,)))
        ability=ActivatedProgram('mana',CostSpec(),(May((AddMana(('G',)),),otherwise=(Draw(1),)),),mana_ability=True)
        with self.assertRaises(RulesViolation):validate(CardProgram('test','Test',('Artifact',),activated=(ability,)))
        spec=TargetSpec(players='all');bad=May((GainLife(1),),available=Selector(Zone.BATTLEFIELD),subject='target')
        with self.assertRaises(RulesViolation):validate(replace(base,spell_targets=spec,spell_effects=(bad,)))
