"""Mana choices resolve immediately, retaining exactly one paid activation."""
import unittest
from edh_gauntlet.rules_program import CardProgram, ActivatedProgram, CostSpec, ChooseMana, validate
from edh_gauntlet.rules_state import RulesState, Zone, RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment


class ManaChoiceTests(unittest.TestCase):
    def game(self, options=(('W',), ('U',), ('B',), ('R',), ('G',)), life=0):
        self.program=CardProgram('rock','Rock',('Artifact',),activated=(
            ActivatedProgram('mana',CostSpec(tap_source=True,life=life),
                             (ChooseMana(options),),mana_ability=True),))
        self.state=RulesState(('A','B'))
        self.ref=self.state.add_card('rock','rock','B',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,(self.program,))
        self.kernel.open_window_for_scenario('A',priority_actor='B')
        self.quote=self.kernel.quote_activation('one','B',self.ref,'mana')
        return self.kernel.commit_action(self.quote,Payment())

    def test_choice_is_one_paid_activation_without_stack_or_early_mana(self):
        request=self.game(life=3)
        self.assertEqual('mana_choice',request.kind)
        self.assertTrue(self.state.get(self.ref).tapped)
        self.assertEqual(37,self.state.life('B'))
        self.assertEqual((),self.state.mana_pool('B'))
        self.assertEqual([],self.kernel.stack)
        self.kernel.answer(request.request_id,'B',[4])
        self.assertEqual((('G',1),),self.state.mana_pool('B'))
        self.assertEqual('B',self.kernel.priority)
        self.assertEqual(1,len(self.kernel.action_receipts))
        self.assertEqual(1,len([e for e in self.kernel.semantic_events if e['kind']=='ability_activated']))
        self.assertEqual(37,self.state.life('B'))

    def test_invalid_answers_and_repeated_activation_are_atomic(self):
        request=self.game();before=self.kernel.snapshot()
        for actor,indexes in (('A',[0]),('B',[]),('B',[5]),('B',[0,1])):
            with self.assertRaises(RulesViolation):self.kernel.answer(request.request_id,actor,indexes)
            self.assertEqual(before,self.kernel.snapshot())
        with self.assertRaises(RulesViolation):self.kernel.commit_action(self.quote,Payment())
        self.assertEqual(before,self.kernel.snapshot())

    def test_pending_choice_checkpoint_continuation_is_exact(self):
        request=self.game(options=(('G','G'),('R','R')))
        restored=RulesKernel.restore(self.kernel.snapshot(),(self.program,))
        self.kernel.answer(request.request_id,'B',[1])
        restored.answer(request.request_id,'B',[1])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual((('R',2),),restored.state.mana_pool('B'))
        self.assertEqual('B',restored.priority)
        before=restored.snapshot()
        with self.assertRaises(RulesViolation):restored.answer(request.request_id,'B',[0])
        self.assertEqual(before,restored.snapshot())

    def test_single_alternative_is_forced_without_an_agent_choice(self):
        self.assertIsNone(self.game(options=(('G','G'),)))
        self.assertEqual((('G',2),),self.state.mana_pool('B'))
        self.assertIsNone(self.kernel.pending_choice)
        self.assertEqual('B',self.kernel.priority)

    def test_paying_last_life_resolves_mana_before_loss_check(self):
        request=self.game(life=40)
        self.assertEqual(('A','B'),self.state.live_players)
        result=self.kernel.answer(request.request_id,'B',[0])
        self.assertEqual(('A',),result.winners)
        kinds=[event['kind'] for event in self.kernel.semantic_events]
        self.assertIn('mana_added',kinds)
        self.assertEqual(('A',),self.state.live_players)

    def test_compiler_rejects_bad_options_and_wrong_classification(self):
        for options in ((), (('X',),), ((),), (('G',),('G',)), [('G',)], (['G'],)):
            with self.assertRaises(RulesViolation):
                validate(CardProgram('bad','Bad',('Artifact',),activated=(ActivatedProgram(
                    'mana',CostSpec(),(ChooseMana(options),),mana_ability=True),)))
        with self.assertRaises(RulesViolation):
            validate(CardProgram('bad','Bad',('Artifact',),activated=(ActivatedProgram(
                'mana',CostSpec(),(ChooseMana((('G',),('R',))),)),)))


class CommanderManaTests(unittest.TestCase):
    def setup_game(self,identities):
        from edh_gauntlet.rules_program import ChooseCommanderMana
        self.program=CardProgram('rock','Rock',('Artifact',),activated=(ActivatedProgram(
            'mana',CostSpec(tap_source=True),(ChooseCommanderMana(),),mana_ability=True),))
        self.state=RulesState(('A','B'),commander_identities=identities)
        self.ref=self.state.add_card('rock','rock','A',Zone.BATTLEFIELD,controller='B')
        self.kernel=RulesKernel(self.state,(self.program,))
        self.kernel.open_window_for_scenario('A',priority_actor='B')

    def activate(self):
        return self.kernel.commit_action(self.kernel.quote_activation('one','B',self.ref,'mana'),Payment())

    def test_controller_identity_and_restored_choice_are_bound(self):
        identities={'A':['R'],'B':['G','U']};self.setup_game(identities)
        identities['B'].append('B')
        request=self.activate()
        self.assertEqual(['{U}','{G}'],[o.label for o in request.options])
        restored=RulesKernel.restore(self.kernel.snapshot(),(self.program,))
        self.kernel.answer(request.request_id,'B',[1]);restored.answer(request.request_id,'B',[1])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual((('G',1),),self.state.mana_pool('B'))

    def test_colorless_identity_produces_nothing_and_single_color_is_forced(self):
        for colors,expected in (([],()),(['R'],(('R',1),))):
            self.setup_game({'A':['W'],'B':colors})
            self.assertIsNone(self.activate())
            self.assertEqual(expected,self.state.mana_pool('B'))
            self.assertTrue(self.state.get(self.ref).tapped)
            self.assertEqual('B',self.kernel.priority)

    def test_unknown_identity_rejects_before_payment(self):
        self.setup_game(None);before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.activate()
        self.assertEqual(before,self.kernel.snapshot())

    def test_malformed_identity_bindings_reject(self):
        for identities in ({'A':['R']},{'A':['C'],'B':[]},{'A':['G','G'],'B':[]}, {'A':'G','B':[]}):
            with self.assertRaises(RulesViolation):self.setup_game(identities)
        self.setup_game({'A':[],'B':[]});value=self.state.snapshot()
        value['commander_identities']['B']=['X']
        with self.assertRaises(RulesViolation):RulesState.restore(value)


class AuthoredManaTests(unittest.TestCase):
    def test_birds_readiness_flying_and_one_color_activation(self):
        from edh_gauntlet.rules_bundle import load_reviewed
        rows=load_reviewed();programs=tuple(r['program'] for r in rows.values())
        state=RulesState(('A','B'));ref=state.add_card('bird','catalog:birds-of-paradise','A',Zone.BATTLEFIELD)
        kernel=RulesKernel(state,programs);kernel.open_window_for_scenario('A')
        self.assertIn('flying',kernel.effective(ref).keywords)
        self.assertEqual((0,1),(kernel.effective(ref).power,kernel.effective(ref).toughness))
        with self.assertRaises(RulesViolation):kernel.quote_activation('early','A',ref,'mana')
        state.start_turn('A')
        request=kernel.commit_action(kernel.quote_activation('ready','A',ref,'mana'),Payment())
        self.assertEqual(5,len(request.options));kernel.answer(request.request_id,'A',[2])
        self.assertEqual((('B',1),),state.mana_pool('A'))

    def test_signet_and_tower_share_commander_mana_resolution(self):
        from edh_gauntlet.rules_bundle import load_reviewed
        programs=tuple(r['program'] for r in load_reviewed().values())
        for key in ('arcane-signet','command-tower'):
            state=RulesState(('A','B'),commander_identities={'A':['W','U','B'],'B':['R','G']})
            ref=state.add_card('mana','catalog:'+key,'A',Zone.BATTLEFIELD)
            kernel=RulesKernel(state,programs);kernel.open_window_for_scenario('A')
            request=kernel.commit_action(kernel.quote_activation('mana','A',ref,'mana'),Payment())
            self.assertEqual(['{W}','{U}','{B}'],[o.label for o in request.options])
            kernel.answer(request.request_id,'A',[0])
            self.assertEqual((('W',1),),state.mana_pool('A'))

    def test_mana_choice_keeps_nonactive_priority_over_existing_stack(self):
        from edh_gauntlet.rules_program import GainLife
        program=CardProgram('rock','Rock',('Artifact',),activated=(
            ActivatedProgram('stack',CostSpec(),(GainLife(2),)),
            ActivatedProgram('mana',CostSpec(tap_source=True),(ChooseMana((('G',),('U',))),),mana_ability=True)))
        state=RulesState(('A','B'));ref=state.add_card('rock','rock','B',Zone.BATTLEFIELD)
        kernel=RulesKernel(state,(program,));kernel.open_window_for_scenario('A',priority_actor='B')
        kernel.commit_action(kernel.quote_activation('stack','B',ref,'stack'),Payment())
        stack_ids=[f['id'] for f in kernel.stack]
        request=kernel.commit_action(kernel.quote_activation('mana','B',ref,'mana'),Payment())
        self.assertEqual(stack_ids,[f['id'] for f in kernel.stack])
        boundary=kernel.answer(request.request_id,'B',[0])
        self.assertEqual('B',boundary.actor)
        self.assertEqual(40,state.life('B'))
        kernel.pass_priority('B');kernel.pass_priority('A')
        self.assertEqual(42,state.life('B'))

    def test_copied_mana_ability_uses_copys_controller_identity(self):
        from edh_gauntlet.rules_bundle import load_reviewed
        from edh_gauntlet.rules_state import ZoneMove
        programs=tuple(r['program'] for r in load_reviewed().values())
        state=RulesState(('A','B'),commander_identities={'A':['W'],'B':['R']})
        ref=state.add_card('copy','catalog:sol-ring','A',Zone.GRAVEYARD)
        state.move((ZoneMove(ref,Zone.BATTLEFIELD,'B',copied_definition='catalog:arcane-signet'),),'copy-fixture')
        kernel=RulesKernel(state,programs);kernel.open_window_for_scenario('A',priority_actor='B')
        kernel.commit_action(kernel.quote_activation('mana','B',state.current('copy'),'mana'),Payment())
        self.assertEqual((('R',1),),state.mana_pool('B'))
        self.assertEqual((),state.mana_pool('A'))

    def test_signets_require_mana_before_producing_both_colors(self):
        from edh_gauntlet.rules_bundle import load_reviewed
        programs=tuple(r['program'] for r in load_reviewed().values())
        for key,expected in (('gruul-signet',(('G',1),('R',1))),('orzhov-signet',(('B',1),('W',1)))):
            state=RulesState(('A','B'));ref=state.add_card('signet','catalog:'+key,'A',Zone.BATTLEFIELD)
            kernel=RulesKernel(state,programs);kernel.open_window_for_scenario('A')
            quote=kernel.quote_activation('mana','A',ref,'mana');before=kernel.snapshot()
            with self.assertRaises(RulesViolation):kernel.commit_action(quote,Payment())
            self.assertEqual(before,kernel.snapshot())
            state.add_mana('A',('C',))
            kernel.commit_action(kernel.quote_activation('mana','A',ref,'mana'),Payment((('C',1),)))
            self.assertEqual(expected,state.mana_pool('A'))
            self.assertEqual([],kernel.stack);self.assertTrue(state.get(ref).tapped)
