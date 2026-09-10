"""Land animation composes type/subtype, color and base-P/T layers."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_characteristics import evaluate,evaluate_exhaustive


class AnimatedLandTests(unittest.TestCase):
    def game(self,key='lumbering-falls',fresh=False):
        self.programs=tuple(r['program'] for r in load_reviewed().values())
        self.state=RulesState(('A','B'))
        if fresh:self.state.start_turn('A')
        self.ref=self.state.add_card('land','catalog:'+key,'A',Zone.BATTLEFIELD)
        if not fresh:self.state.start_turn('A')
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def animate(self,x=0):
        falls=self.state.get(self.ref).definition=='catalog:lumbering-falls'
        self.state.add_mana('A',('G','U','C','C') if falls else ('G',)+('C',)*x)
        payment=Payment((('G',1),('U',1),('C',2))) if falls else Payment((('G',1),('C',x)))
        self.kernel.commit_action(self.kernel.quote_activation('animate'+str(self.state.sequence),'A',self.ref,'animate',x_value=x),payment)
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)

    def test_falls_sets_types_colors_stats_and_expires_with_checkpoint(self):
        self.game();self.animate();view=self.kernel.effective(self.ref)
        self.assertEqual({'Land','Creature'},set(view.types));self.assertIn('Elemental',view.subtypes)
        self.assertEqual({'G','U'},set(view.colors));self.assertEqual((3,3),(view.power,view.toughness));self.assertIn('hexproof',view.keywords)
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        for kernel in (self.kernel,restored):kernel._finish_cleanup_actions()
        self.assertEqual(self.kernel.snapshot(),restored.snapshot());view=self.kernel.effective(self.ref)
        self.assertEqual({'Land'},set(view.types));self.assertEqual(frozenset(),view.colors);self.assertNotIn('Elemental',view.subtypes)

    def test_lair_requires_positive_x_and_later_activation_sets_new_base(self):
        self.game('lair-of-the-hydra');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('zero','A',self.ref,'animate',x_value=0)
        self.assertEqual(before,self.kernel.snapshot());self.animate(2)
        self.kernel.open_window_for_scenario('A');self.animate(4)
        view=self.kernel.effective(self.ref);self.assertEqual((4,4),(view.power,view.toughness));self.assertEqual({'G'},set(view.colors));self.assertIn('Hydra',view.subtypes)

    def test_existing_land_can_tap_as_creature_but_new_land_cannot(self):
        for fresh in (False,True):
            self.game('lair-of-the-hydra',fresh=fresh);self.animate(2);self.kernel.open_window_for_scenario('A')
            if fresh:
                with self.assertRaises(RulesViolation):self.kernel.quote_activation('mana','A',self.ref,'mana')
            else:
                self.kernel.commit_action(self.kernel.quote_activation('mana','A',self.ref,'mana'),Payment());self.assertEqual((('G',1),),self.state.mana_pool('A'))

    def test_entry_tapping_conditions_and_falls_mana_choices(self):
        for key in ('lair-of-the-hydra','lumbering-falls'):
            for count in (0,1,2):
                self.game(key)
                self.state.move((ZoneMove(self.ref,Zone.HAND),),'fixture-reset');self.ref=self.state.current('land')
                for i in range(count):self.state.add_card('other'+str(i),'catalog:forest','A',Zone.BATTLEFIELD)
                self.kernel.execute_for_scenario(self.ref,'A',(Move('source',Zone.BATTLEFIELD),));ref=self.state.current('land')
                self.assertEqual(key=='lumbering-falls' or count>=2,self.state.get(ref).tapped)
        for index,symbol in enumerate('GU'):
            self.game();request=self.kernel.commit_action(self.kernel.quote_activation('mana','A',self.ref,'mana'),Payment())
            self.kernel.answer(request.request_id,'A',[index]);self.assertEqual(((symbol,1),),self.state.mana_pool('A'))

    def test_animation_keeps_existing_subtypes_and_does_not_follow_blink(self):
        self.game('lair-of-the-hydra')
        self.kernel.execute_for_scenario(self.ref,'A',(UntilEndOfTurn('source',(AddSubtypes('Land',('Forest',)),)),))
        self.kernel.open_window_for_scenario('A');self.animate(2);self.assertTrue({'Forest','Hydra'}<=set(self.kernel.effective(self.ref).subtypes))
        self.state.move((ZoneMove(self.ref,Zone.EXILE),),'fixture-blink-out');self.state.move((ZoneMove(self.state.current('land'),Zone.BATTLEFIELD),),'fixture-blink-in')
        self.assertNotIn('Creature',self.kernel.effective(self.state.current('land')).types)

    def test_color_layer_dependencies_match_exhaustive_and_support_colorless(self):
        body=CardProgram('body','Body',('Artifact',),colors=('U',))
        green=CardProgram('green','Green',('Enchantment',),continuous=(ContinuousProgram('green',Selector(Zone.BATTLEFIELD,types=('Artifact',),any_colors=('R',)),(SetColors(('G',)),)),))
        red=CardProgram('red','Red',('Enchantment',),continuous=(ContinuousProgram('red',Selector(Zone.BATTLEFIELD,types=('Artifact',)),(SetColors(('R',)),)),))
        state=RulesState(('A','B'));ref=state.add_card('body','body','A',Zone.BATTLEFIELD);state.add_card('green','green','A',Zone.BATTLEFIELD);state.add_card('red','red','A',Zone.BATTLEFIELD)
        kernel=RulesKernel(state,(body,green,red));self.assertEqual({'G'},set(kernel.effective(ref).colors))
        self.assertEqual(evaluate(state.objects(),kernel.definitions),evaluate_exhaustive(state.objects(),kernel.definitions))
        kernel.execute_for_scenario(ref,'A',(UntilEndOfTurn('source',(SetColors(()),)),))
        self.assertEqual(frozenset(),kernel.effective(ref).colors)

    def test_color_and_minimum_x_validation(self):
        for colors in (('C',),('G','G'),('GU',),['G']):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),spell_effects=(UntilEndOfTurn('source',(SetColors(colors),)),)))
        ability=ActivatedProgram('bad',CostSpec(),(GainLife(1),),minimum_x=1)
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Artifact',),activated=(ability,)))
        good=CardProgram('good','Good',('Artifact',),activated=(replace(ability,cost=CostSpec(ManaCost(x_symbols=1))),))
        self.assertEqual(good,decode(encode(validate(good))))

    def test_copied_land_inherits_activation_and_captured_x_across_recovery(self):
        self.game('lair-of-the-hydra')
        copy=self.state.add_card('copy','catalog:forest','A',Zone.HAND)
        self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,'B',copied_definition='catalog:lair-of-the-hydra'),),'copy-fixture')
        copy=self.state.current('copy');self.kernel.open_window_for_scenario('A',priority_actor='B')
        self.state.add_mana('B',('G','C','C','C'))
        self.kernel.commit_action(self.kernel.quote_activation('copied-animation','B',copy,'animate',x_value=3),Payment((('G',1),('C',3))))
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        for kernel in (self.kernel,restored):
            while kernel.stack:kernel.pass_priority(kernel.priority)
            view=kernel.effective(copy)
            self.assertEqual({'Land','Creature'},set(view.types));self.assertEqual({'Hydra'},set(view.subtypes))
            self.assertEqual({'G'},set(view.colors));self.assertEqual((3,3),(view.power,view.toughness))
            self.assertEqual({'Land'},set(kernel.effective(self.ref).types))
            self.assertEqual((),kernel.state.mana_pool('B'))
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        restored=RulesKernel.restore(restored.snapshot(),self.programs)
        for kernel in (self.kernel,restored):kernel._finish_cleanup_actions()
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        view=restored.effective(copy)
        self.assertEqual({'Land'},set(view.types));self.assertEqual(frozenset(),view.subtypes)
        self.assertEqual('catalog:lair-of-the-hydra',restored.state.get(copy).copied_definition)

    def test_pending_animation_does_not_follow_blinked_source_after_recovery(self):
        self.game('lair-of-the-hydra');self.state.add_mana('A',('G','C','C'))
        self.kernel.commit_action(self.kernel.quote_activation('animate','A',self.ref,'animate',x_value=2),Payment((('G',1),('C',2))))
        self.state.move((ZoneMove(self.ref,Zone.EXILE),),'fixture-blink-out')
        self.state.move((ZoneMove(self.state.current('land'),Zone.BATTLEFIELD),),'fixture-blink-in')
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        for kernel in (self.kernel,restored):
            while kernel.stack:kernel.pass_priority(kernel.priority)
            self.assertEqual({'Land'},set(kernel.effective(kernel.state.current('land')).types))
            self.assertEqual([],kernel.temporary_effects)
            self.assertEqual((),kernel.state.mana_pool('A'))
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
