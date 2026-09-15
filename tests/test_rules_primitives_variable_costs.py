"""Casting discounts read shared numeric expressions at the quote boundary."""
import unittest
from dataclasses import replace
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment,PreparedAction
from edh_gauntlet.rules_bundle import load_reviewed


class VariableCostTests(unittest.TestCase):
    def setUp(self):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(
            CardProgram('small','Small',('Creature',),power=3,toughness=3),
            CardProgram('negative','Negative',('Creature',),power=-2,toughness=3),
            CardProgram('huge','Huge',('Creature',),power=20,toughness=20),
            CardProgram('tax','Tax',('Enchantment',),cost_modifiers=(CostModifier('tax',Selector(Zone.STACK),5),)),)
        self.state=RulesState(('A','B'));self.kernel=RulesKernel(self.state,self.programs)
        self.ghalta=self.state.add_card('ghalta','catalog:ghalta-primal-hunger','A',Zone.HAND)
        self.act=self.state.add_card('act','catalog:blasphemous-act','A',Zone.HAND)
        self.kernel.open_window_for_scenario('A')

    def add(self,key,definition='small',actor='A'):
        return self.state.add_card(key,definition,actor,Zone.BATTLEFIELD)

    def quote(self,ref=None):return self.kernel.quote_cast('cast','A',ref or self.ghalta)

    def test_ghalta_uses_total_signed_power_of_controlled_unphased_creatures(self):
        self.add('own');self.add('negative','negative');self.add('enemy','huge','B')
        phased=self.add('phased','huge');self.state.phase(phased,True)
        self.assertEqual(9,self.quote().cost.mana.generic)
        self.assertEqual(('G','G'),self.quote().cost.mana.symbols)

    def test_negative_total_does_not_increase_cost(self):
        self.add('negative','negative');self.assertEqual(10,self.quote().cost.mana.generic)

    def test_derived_counters_change_discount(self):
        creature=self.add('own');self.state.add_counters(creature,'+1/+1',2)
        self.assertEqual(5,self.quote().cost.mana.generic)

    def test_generic_floor_applies_after_increases_and_preserves_colored_cost(self):
        self.add('huge','huge');self.add('tax','tax')
        self.state.add_mana('A',('G','G'));quote=self.quote();self.assertEqual(0,quote.cost.mana.generic)
        self.kernel.commit_action(quote,Payment((('G',2),)))
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
        ref=self.state.current('ghalta');self.assertEqual(Zone.BATTLEFIELD,self.state.get(ref).zone)
        self.assertEqual(12,self.kernel.effective(ref).mana_value);self.assertIn('trample',self.kernel.effective(ref).keywords)

    def test_stale_battlefield_quote_rejects_without_payment(self):
        creature=self.add('own');self.state.add_mana('A',('G','G')+('C',)*7)
        quote=self.quote();self.state.add_counters(creature,'+1/+1',1);before=self.state.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,Payment((('G',2),('C',7))))
        self.assertEqual(before,self.state.snapshot());self.assertEqual(6,self.quote().cost.mana.generic)

    def test_quote_is_pure_and_checkpoint_commit_matches(self):
        self.add('own');self.state.add_mana('A',('G','G')+('C',)*7);before=self.kernel.snapshot();quote=self.quote()
        self.assertEqual(before,self.kernel.snapshot())
        restored=RulesKernel.restore(before,self.programs);payment=Payment((('G',2),('C',7)))
        restored.commit_action(PreparedAction.from_json(quote.to_json()),payment);self.kernel.commit_action(quote,payment)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())

    def test_act_counts_opponents_and_damages_all_creatures(self):
        own=self.add('own');enemy=self.add('enemy',actor='B');huge=self.add('huge','huge')
        self.state.add_mana('A',('R',)+('C',)*5);quote=self.quote(self.act);self.assertEqual(5,quote.cost.mana.generic)
        self.kernel.commit_action(quote,Payment((('R',1),('C',5))))
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
        for ref in (own,enemy):self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current(ref.card_id)).zone)
        self.assertEqual(13,self.state.get(huge).damage_marked)
        self.assertEqual(40,self.state.life('A'));self.assertEqual(40,self.state.life('B'))

    def test_act_never_reduces_red_symbol_or_uses_phased_creatures(self):
        for i in range(10):self.add(str(i))
        self.assertEqual(ManaCost(0,('R',)),self.quote(self.act).cost.mana)
        for i in range(10):self.state.phase(self.state.current(str(i)),True)
        self.assertEqual(8,self.quote(self.act).cost.mana.generic)

    def test_variable_discount_combines_with_per_card_commander_tax(self):
        commander=self.state.add_card('commander','catalog:ghalta-primal-hunger','A',Zone.COMMAND,commander=True)
        self.add('small');self.state.record_command_cast('A','commander')
        self.assertEqual(9,self.quote(commander).cost.mana.generic)
        self.assertEqual(7,self.quote().cost.mana.generic)

    def test_cost_expression_rejects_runtime_or_unannounced_values(self):
        base=load_reviewed()['ghalta-primal-hunger']['program']
        for value in [True,-1,ChosenX(),EventAmount(),SourceStat(),ScaledValue(SourceStat(),2),
                      CountObjects(Selector(Zone.LIBRARY))]:
            with self.subTest(value=value),self.assertRaises(RulesViolation):
                validate(replace(base,cast=replace(base.cast,generic_reduction=value)))
