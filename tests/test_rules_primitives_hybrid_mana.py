"""Hybrid pips match paid colors without greedy assignment or card branches."""
import itertools
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment,_mana_symbols_satisfied
from edh_gauntlet.rules_bundle import load_reviewed


class HybridManaTests(unittest.TestCase):
    def test_matching_agrees_with_exhaustive_small_payment_assignments(self):
        def oracle(symbols,paid):
            if not symbols:return True
            for color in symbols[0].split('/'):
                if paid.get(color,0):
                    rest=dict(paid);rest[color]-=1
                    if oracle(symbols[1:],rest):return True
            return False
        pips=('W','U','B','W/U','U/B','W/B')
        for size in (1,2,3):
            for symbols in itertools.combinations_with_replacement(pips,size):
                for counts in itertools.product(range(4),repeat=3):
                    paid=dict(zip('WUB',counts))
                    self.assertEqual(oracle(symbols,paid),_mana_symbols_satisfied(symbols,paid),(symbols,paid))

    def game(self):
        self.programs=tuple(r['program'] for r in load_reviewed().values())
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('grove','catalog:flooded-grove','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def test_all_six_filter_combinations_pay_once_and_checkpoint(self):
        for paid in 'GU':
            for index,expected in enumerate(((('G',2),),(('G',1),('U',1)),(('U',2),))):
                self.game();self.state.add_mana('A',(paid,))
                request=self.kernel.commit_action(self.kernel.quote_activation('filter','A',self.ref,'filter'),Payment(((paid,1),)))
                self.assertEqual((),self.state.mana_pool('A'));self.assertTrue(self.state.get(self.ref).tapped);self.assertFalse(self.kernel.stack)
                restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
                for k in (self.kernel,restored):k.answer(request.request_id,'A',[index])
                self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertEqual(expected,self.state.mana_pool('A'))

    def test_colorless_ability_and_wrong_hybrid_payment(self):
        self.game();self.kernel.commit_action(self.kernel.quote_activation('mana','A',self.ref,'colorless'),Payment())
        self.assertEqual((('C',1),),self.state.mana_pool('A'))
        self.state.set_tapped_batch((self.ref,),False);before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(self.kernel.quote_activation('bad','A',self.ref,'filter'),Payment((('C',1),)))
        self.assertEqual(before,self.kernel.snapshot())

    def test_shared_cast_cost_handles_overlapping_hybrids_fixed_and_generic(self):
        program=CardProgram('spell','Spell',('Sorcery',),cast=CastSpec(CostSpec(ManaCost(1,('W','W/U','U/B')))),spell_effects=(GainLife(1),))
        state=RulesState(('A','B'));ref=state.add_card('spell','spell','A',Zone.HAND)
        kernel=RulesKernel(state,(program,));kernel.open_window_for_scenario('A');state.add_mana('A',('W','U','B','C'))
        kernel.commit_action(kernel.quote_cast('cast','A',ref),Payment((('W',1),('U',1),('B',1),('C',1))))
        while kernel.stack:kernel.pass_priority(kernel.priority)
        self.assertEqual(41,state.life('A'));self.assertEqual((),state.mana_pool('A'))

    def test_large_repeated_pip_groups_do_not_expand_combinations(self):
        self.assertTrue(_mana_symbols_satisfied(('W/U',)*100+('U/B',)*100,{'W':100,'B':100}))
        self.assertFalse(_mana_symbols_satisfied(('W/U',)*100+('U/B',)*100,{'W':99,'B':101}))
        self.assertTrue(_mana_symbols_satisfied(('W/U','U/B'),{'U':1,'W':1}))

    def test_unsupported_symbols_reject_and_hybrid_codec_roundtrips(self):
        for symbol in ('2/W','W/P','W/W','C/W','W/U/B','w/u','W//U',None):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),cast=CastSpec(CostSpec(ManaCost(0,(symbol,))),timing='instant')))
        program=CardProgram('good','Good',('Instant',),cast=CastSpec(CostSpec(ManaCost(0,('G/U',))),timing='instant'))
        self.assertEqual(program,decode(encode(validate(program))))
