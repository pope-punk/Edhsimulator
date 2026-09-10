"""Color predicates compose with costs, public targets and private searches."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_adapter import RulesActorAdapter


class ColorSelectorTests(unittest.TestCase):
    def game(self,colors=('R','G'),generic=3,symbols=None):
        spell=CardProgram('spell','Spell',('Sorcery',),colors=colors,cast=CastSpec(CostSpec(ManaCost(generic,colors if symbols is None else symbols))),spell_effects=(GainLife(1),))
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(spell,)
        self.state=RulesState(('A','B'));self.goblin=self.state.add_card('goblin','catalog:goblin-anarchomancer','A',Zone.BATTLEFIELD)
        self.spell=self.state.add_card('spell','spell','A',Zone.HAND)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def test_red_green_or_both_receive_one_reduction(self):
        for colors,expected in ((('R',),2),(('G',),2),(('R','G'),2),(('B',),3),((),3)):
            self.game(colors);quote=self.kernel.quote_cast('cast','A',self.spell)
            self.assertEqual(expected,quote.cost.mana.generic);self.assertEqual(colors,quote.cost.mana.symbols)

    def test_modifiers_stack_floor_at_zero_and_follow_controller(self):
        self.game(generic=1);self.state.add_card('second','catalog:goblin-anarchomancer','A',Zone.BATTLEFIELD)
        quote=self.kernel.quote_cast('cast','A',self.spell);self.assertEqual(0,quote.cost.mana.generic);self.assertEqual(('R','G'),quote.cost.mana.symbols)
        self.state.change_control_batch((self.goblin,self.state.current('second')),'B')
        self.assertEqual(1,self.kernel.quote_cast('cast','A',self.spell).cost.mana.generic)

    def test_hybrid_spell_color_does_not_depend_on_payment_color(self):
        self.game(('G','U'),1,('G/U',));self.state.add_mana('A',('U',))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.spell),Payment((('U',1),)))
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual(41,self.state.life('A'));self.assertEqual((),self.state.mana_pool('A'))

    def test_color_predicates_support_all_any_and_exclusions(self):
        self.game();frame={'source':self.state.get(self.goblin).to_json(),'controller':'A'}
        self.assertEqual((self.state.get(self.goblin),),self.kernel._query(Selector(Zone.BATTLEFIELD,colors=('R','G')),frame))
        self.assertEqual((),self.kernel._query(Selector(Zone.BATTLEFIELD,any_colors=('B','U')),frame))
        self.assertEqual((),self.kernel._query(Selector(Zone.BATTLEFIELD,excluded_colors=('R',)),frame))
        for colors in (('C',),('RG',),('g',),('G','G')):
            bad=CardProgram('bad','Bad',('Instant',),spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD,any_colors=colors)),spell_effects=(Destroy('target'),))
            with self.assertRaises(RulesViolation):validate(bad)

    def test_color_quality_search_can_fail_to_find_and_preserves_private_menu(self):
        self.game();ref=self.state.add_card('hidden','spell','A',Zone.LIBRARY)
        request=self.kernel.execute_for_scenario(self.goblin,'A',(SearchLibrary(Selector(Zone.LIBRARY,relation='owned',any_colors=('G',)),Zone.HAND),))
        self.assertEqual(0,request.minimum);self.assertEqual([ref],[o.ref for o in request.options])
        self.kernel.answer(request.request_id,'A',[]);self.assertEqual(Zone.LIBRARY,self.state.get(self.state.current(ref.card_id)).zone)
        self.assertEqual(1,self.state.snapshot()['shuffle_nonce'])

    def test_printed_goblin_cost_and_reduced_spell_actor_replay(self):
        self.game();another=self.state.add_card('cast-goblin','catalog:goblin-anarchomancer','A',Zone.HAND)
        self.state.add_mana('A',('R','G'));self.kernel.commit_action(self.kernel.quote_cast('goblin','A',another),Payment((('R',1),('G',1))))
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('cast-goblin')).zone)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('R','G','C'));adapter=RulesActorAdapter(self.kernel)
        adapter.submit('A',{'kind':'cast','revision':self.kernel.revision,'action_id':'spell','source':self.spell.to_json(),'targets':[],'x_value':0,'payment':{'mana':{'R':1,'G':1,'C':1},'taps':[]}})
        while self.kernel.stack:adapter.submit(self.kernel.priority,{'kind':'pass','revision':self.kernel.revision})
        restored=RulesActorAdapter.replay(adapter.archive(),self.programs)
        for actor in ('A','B'):self.assertEqual(adapter.packet(actor),restored.packet(actor))
