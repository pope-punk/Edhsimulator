import unittest
from edh_gauntlet.rules_program import CardProgram,Selector
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove
from edh_gauntlet.rules_kernel import RulesKernel


class LegendTests(unittest.TestCase):
    def setup_game(self, second_owner='A'):
        self.state=RulesState(('A','B'))
        self.program=CardProgram('legend','Legend fixture',('Creature',),power=2,toughness=2,supertypes=('Legendary',))
        self.first=self.state.add_card('one','legend','A',Zone.BATTLEFIELD)
        self.second=self.state.add_card('two','legend',second_owner,Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,(self.program,))

    def test_legend_rule_is_a_choice_and_not_sacrifice(self):
        self.setup_game();boundary=self.kernel.advance()
        self.assertEqual('legend_rule',boundary.kind)
        self.kernel.answer(boundary.request_id,'A',[1])
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('one')).zone)
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.second).zone)
        self.assertNotEqual('sacrifice',self.state.events[-1].cause)

    def test_different_controllers_keep_matching_legends(self):
        self.setup_game('B');self.assertIsNone(self.kernel.advance())
        self.assertEqual(2,len(self.state.objects(Zone.BATTLEFIELD)))

    def test_copy_inherits_name_and_legendary_supertype(self):
        self.setup_game('B')
        plain=CardProgram('plain','Plain fixture',('Creature',),power=2,toughness=2)
        source=self.state.add_card('copy','plain','A',Zone.HAND)
        self.state.move((ZoneMove(source,Zone.BATTLEFIELD,'A',copied_definition='legend'),),'copy')
        self.kernel=RulesKernel(self.state,(self.program,plain));boundary=self.kernel.advance()
        self.assertEqual('legend_rule',boundary.kind);self.assertEqual(2,len(boundary.options))
        restored=RulesKernel.restore(self.kernel.snapshot(),(self.program,plain))
        self.kernel.answer(boundary.request_id,'A',[0]);restored.answer(boundary.request_id,'A',[0])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())

    def test_zero_toughness_and_legend_choices_share_the_same_batch(self):
        self.setup_game();self.state.add_counters(self.first,'-1/-1',2)
        boundary=self.kernel.advance();self.kernel.answer(boundary.request_id,'A',[0])
        self.assertEqual(0,len(self.state.objects(Zone.BATTLEFIELD)))
        self.assertEqual(1,len({event.batch for event in self.state.events}))
