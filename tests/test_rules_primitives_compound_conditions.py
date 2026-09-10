"""Boolean predicates preserve dependency reads and branch classification."""
import unittest
from dataclasses import replace
from unittest.mock import patch
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_characteristics import evaluate,evaluate_exhaustive,condition_holds
from edh_gauntlet.rules_adapter import RulesActorAdapter


class CompoundConditionTests(unittest.TestCase):
    def setUp(self):
        self.present=CountCondition(Selector(Zone.BATTLEFIELD,types=('Artifact',),relation='controlled'),1)
        self.absent=CountCondition(Selector(Zone.BATTLEFIELD,types=('Land',),relation='controlled'),1)
        self.program=CardProgram('source','Source',('Artifact',))
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('source','source','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,(self.program,))

    def test_boolean_truth_and_single_selected_branch(self):
        cases=[(AllConditions((self.present,NotCondition(self.absent))),True),
               (AnyConditions((self.absent,self.present)),True),
               (AllConditions((self.present,self.absent)),False),
               (NotCondition(AnyConditions((self.absent,NotCondition(self.present)))),True)]
        for condition,expected in cases:
            with self.subTest(condition=condition):
                before=self.state.life('A')
                self.kernel.execute_for_scenario(self.ref,'A',(IfCondition(condition,(GainLife(2),),(GainLife(5),)),))
                self.assertEqual(before+(2 if expected else 5),self.state.life('A'))

    def test_short_circuit_does_not_scan_unneeded_operands(self):
        source=self.state.get(self.ref);objects=self.state.objects();views=self.kernel.characteristics()
        from edh_gauntlet import rules_characteristics as module
        with patch.object(module,'matches',wraps=module.matches) as match:
            self.assertTrue(condition_holds(AnyConditions((self.present,self.absent)),source,objects,views))
            self.assertEqual(1,match.call_count)
        with patch.object(module,'matches',wraps=module.matches) as match:
            self.assertFalse(condition_holds(AllConditions((self.absent,self.present)),source,objects,views))
            self.assertEqual(1,match.call_count)

    def test_branch_is_chosen_once_before_its_effects_change_condition(self):
        self.kernel.execute_for_scenario(self.ref,'A',(IfCondition(self.present,
            (Move('source',Zone.EXILE),GainLife(2)),(GainLife(20),)),))
        self.assertEqual(42,self.state.life('A'))

    def test_else_branch_validation_and_mana_classification(self):
        bad=replace(self.program,spell_effects=(IfCondition(self.present,(),(Move('selected',Zone.EXILE),)),))
        with self.assertRaises(RulesViolation):validate(bad)
        ability=ActivatedProgram('mana',CostSpec(),(IfCondition(self.present,(),(AddMana(('C',)),)),),mana_ability=True)
        validate(replace(self.program,activated=(ability,)))
        with self.assertRaises(RulesViolation):validate(replace(self.program,activated=(replace(ability,
            effects=(IfCondition(self.present,(AddMana(('C',)),),(Draw(1),)),)),)))

    def test_invalid_and_overdeep_predicates_reject(self):
        nested=self.present
        for _ in range(18):nested=NotCondition(nested)
        for condition in [AllConditions(()),AnyConditions([self.present]),NotCondition(None),
                          AllConditions((self.present,)*33),nested,NotCondition(CountCondition(Selector(Zone.HAND),1))]:
            with self.subTest(condition=condition),self.assertRaises(RulesViolation):
                validate(replace(self.program,spell_effects=(IfCondition(condition,()),)))

    def test_compound_entry_condition_uses_preentry_battlefield(self):
        land=CardProgram('land','Land',('Land',),entry_modifiers=(EntryModifier('conditional',
            condition=AnyConditions((self.present,self.absent)),unless=True),))
        for has_artifact in (False,True):
            state=RulesState(('A','B'))
            if has_artifact:state.add_card('artifact','source','A',Zone.BATTLEFIELD)
            incoming=state.add_card('land','land','A',Zone.HAND);kernel=RulesKernel(state,(self.program,land))
            kernel.enter(incoming,'A')
            self.assertEqual(not has_artifact,state.get(state.current('land')).tapped)

    def test_fallback_choice_keeps_selected_branch_across_checkpoint(self):
        self.kernel.execute_for_scenario(self.ref,'A',(IfCondition(self.absent,(GainLife(20),),
            (May((GainLife(3),)),)),))
        snapshot=self.kernel.snapshot();restored=RulesKernel.restore(snapshot,(self.program,))
        for kernel in (self.kernel,restored):
            request=kernel.pending_choice;kernel.answer(request.request_id,'A',(0,))
        self.assertEqual(43,self.state.life('A'));self.assertEqual(self.kernel.snapshot(),restored.snapshot())

    def test_nested_predicate_reads_preserve_layer_dependencies(self):
        # The earlier effect must wait for the later effect that removes Artifact.
        condition=NotCondition(AnyConditions((self.present,self.absent)))
        early=replace(self.program,continuous=(ContinuousProgram('early',Selector(Zone.BATTLEFIELD),
            (ChangeTypes(add=('Creature',)),SetPT(3,3)),condition=condition),))
        late=CardProgram('late','Late',('Enchantment',),continuous=(ContinuousProgram('late',
            Selector(Zone.BATTLEFIELD,types=('Artifact',)),(ChangeTypes(remove=('Artifact',)),)),))
        self.state.add_card('late','late','A',Zone.BATTLEFIELD);defs={p.definition_id:p for p in (early,late)}
        optimized=evaluate(self.state.objects(),defs);exhaustive=evaluate_exhaustive(self.state.objects(),defs)
        self.assertEqual(optimized,exhaustive);self.assertIn('Creature',optimized[self.ref].types)

    def test_compound_intervening_condition_rechecks_and_replays(self):
        condition=AllConditions((self.present,NotCondition(self.absent)))
        program=replace(self.program,abilities=(AbilityProgram('upkeep',EventPattern('step_began',step='upkeep'),
            (GainLife(5),),intervening_if=condition),))
        kernel=RulesKernel(self.state,(program,));kernel.begin_step('A','upkeep')
        self.state.move((ZoneMove(self.ref,Zone.EXILE),),'scenario-response')
        adapter=RulesActorAdapter(kernel);restored=RulesActorAdapter.replay(adapter.archive(),(program,))
        while kernel.stack:
            command={'kind':'pass','revision':kernel.revision};actor=kernel.priority
            adapter.submit(actor,command);restored.submit(actor,command)
        self.assertEqual(40,kernel.state.life('A'));self.assertEqual(adapter.archive(),restored.archive())

    def test_urza_lands_missing_piece_normal_complete_set_enhanced(self):
        programs=tuple(r['program'] for r in load_reviewed().values())
        for key,amount in [('urza-s-mine',2),('urza-s-power-plant',2),('urza-s-tower',3)]:
            for complete in (False,True):
                with self.subTest(card=key,complete=complete):
                    state=RulesState(('A','B'));source=state.add_card('source','catalog:'+key,'A',Zone.BATTLEFIELD)
                    if complete:
                        for other in ('urza-s-mine','urza-s-power-plant','urza-s-tower'):
                            if other!=key:state.add_card(other,'catalog:'+other,'A',Zone.BATTLEFIELD)
                    kernel=RulesKernel(state,programs);kernel.open_window_for_scenario('A')
                    kernel.commit_action(kernel.quote_activation('mana','A',source,'mana'),Payment())
                    self.assertEqual((('C',amount if complete else 1),),state.mana_pool('A'))
                    self.assertFalse(kernel.stack);self.assertTrue(state.get(source).tapped)

    def test_urza_checks_subtypes_not_names_and_ignores_opponents_phasing(self):
        programs=tuple(r['program'] for r in load_reviewed().values())+(
            CardProgram('both','Unrelated Name',('Land',),subtypes=("Urza's",'Mine','Power-Plant')),)
        state=RulesState(('A','B'));tower=state.add_card('tower','catalog:urza-s-tower','A',Zone.BATTLEFIELD)
        both=state.add_card('both','both','B',Zone.BATTLEFIELD);kernel=RulesKernel(state,programs)
        for index,(actor,phased,expected) in enumerate([('B',False,1),('A',True,1),('A',False,3)]):
            state.phase(both,False);state.change_control(both,actor);state.phase(both,phased)
            kernel.execute_for_scenario(tower,'A',(SetTapped('source',False),));kernel.open_window_for_scenario('A')
            before=dict(state.mana_pool('A')).get('C',0)
            kernel.commit_action(kernel.quote_activation(str(index),'A',tower,'mana'),Payment())
            self.assertEqual(before+expected,dict(state.mana_pool('A'))['C'])
