"""Selection counts are retained numeric values, not repeated board queries."""
import unittest
from unittest.mock import patch
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment


class SelectedCountTests(unittest.TestCase):
    def game(self):
        self.programs=(CardProgram('source','Source',('Artifact',)),CardProgram('body','Body',('Creature',),power=2,toughness=2))
        self.state=RulesState(('A','B'));self.source=self.state.add_card('source','source','A',Zone.BATTLEFIELD)
        self.bodies=tuple(self.state.add_card(str(i),'body','A',Zone.BATTLEFIELD) for i in range(3))
        self.kernel=RulesKernel(self.state,self.programs)
        self.sel=Selector(Zone.BATTLEFIELD,types=('Creature',))

    def test_count_survives_movement_and_numeric_composition(self):
        self.game();self.kernel.execute_for_scenario(self.source,'A',(SelectAll(self.sel,(Move('selected',Zone.EXILE),GainLife(ScaledValue(SelectedCount(),2)))),))
        self.assertEqual(46,self.state.life('A'));self.assertEqual(0,len(self.state.objects(Zone.BATTLEFIELD))-1)

    def test_optional_selection_counts_actual_choices_and_checkpoint_retains_it(self):
        self.game();request=self.kernel.execute_for_scenario(self.source,'A',(Select(self.sel,0,3,(May((GainLife(SelectedCount()),)),)),))
        self.kernel.answer(request.request_id,'A',[0,2]);request=self.kernel.pending_choice
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        for k in (self.kernel,restored):k.answer(request.request_id,'A',[0])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertEqual(42,self.state.life('A'))

    def test_nested_selection_restores_outer_count_for_later_sibling(self):
        self.game();empty=Selector(Zone.BATTLEFIELD,types=('Enchantment',))
        self.kernel.execute_for_scenario(self.source,'A',(SelectAll(self.sel,(SelectAll(empty,(GainLife(SelectedCount()),)),GainLife(SelectedCount()))),))
        self.assertEqual(43,self.state.life('A'))

    def test_unbound_count_is_rejected_and_codec_roundtrips(self):
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),spell_effects=(Draw(SelectedCount()),)))
        self.game();program=CardProgram('good','Good',('Instant',),spell_effects=(SelectAll(self.sel,(Draw(SelectedCount()),)),))
        self.assertEqual(program,decode(encode(validate(program))))

    def test_inspiring_call_queries_its_creature_group_only_once(self):
        programs=tuple(r['program'] for r in load_reviewed().values())
        state=RulesState(('A','B'));spell=state.add_card('spell','catalog:inspiring-call','A',Zone.HAND)
        creature=state.add_card('creature','catalog:spirited-companion','A',Zone.BATTLEFIELD);state.add_counters(creature,'+1/+1',1)
        state.add_card('draw','catalog:forest','A',Zone.LIBRARY)
        kernel=RulesKernel(state,programs);kernel.open_window_for_scenario('A');state.add_mana('A',('G','C','C'))
        kernel.commit_action(kernel.quote_cast('cast','A',spell),Payment((('G',1),('C',2))))
        selector=next(p for p in programs if p.definition_id=='catalog:inspiring-call').spell_effects[0].selector
        with patch.object(kernel,'_query',wraps=kernel._query) as query:
            while kernel.stack:kernel.pass_priority(kernel.priority)
        self.assertEqual(1,sum(call.args[0]==selector for call in query.call_args_list))
        self.assertEqual(1,len(state.zone('A',Zone.HAND)));self.assertIn('indestructible',kernel.effective(creature).keywords)
