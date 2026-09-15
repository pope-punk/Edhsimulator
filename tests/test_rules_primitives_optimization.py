"""Optimization parity is checked without using wall-clock assertions."""
import random
from dataclasses import replace
import unittest
from unittest.mock import patch
from edh_gauntlet import rules_characteristics as characteristics
from edh_gauntlet.rules_state import RulesState, Zone
from edh_gauntlet.rules_program import (CardProgram, ContinuousProgram, Selector,
    ChangeTypes, SetPT, ModifyPT, SwitchPT, CountCondition, validate)


class OptimizationTests(unittest.TestCase):
    def test_randomized_dependency_pruning_matches_exhaustive(self):
        for seed in range(80):
            rng = random.Random(seed); state = RulesState(('A', 'B'))
            definitions = {}
            for index in range(10):
                types = rng.choice((('Creature',), ('Enchantment',), ('Artifact', 'Creature')))
                changes = rng.choice(((ModifyPT(1, -1),), (SetPT(3, 4),), (SwitchPT(),),
                    (ChangeTypes(add=('Creature',)), SetPT(2, 3)),
                    (ChangeTypes(remove=('Artifact',), add=('Enchantment',)),)))
                selector = Selector(Zone.BATTLEFIELD, rng.choice(((), ('Creature',), ('Enchantment',), ('Artifact',))),
                    rng.choice(('any', 'controlled', 'opponent_controlled')), rng.choice((True, False)))
                selector=replace(selector,any_types=rng.choice(((),('Artifact','Enchantment'))),excluded_types=rng.choice(((),('Land',),('Creature',))))
                condition = CountCondition(Selector(Zone.BATTLEFIELD, ('Creature',)), rng.randrange(5)) if rng.randrange(3)==0 else None
                continuous = (ContinuousProgram('effect', selector, changes, condition=condition),) if index<6 else ()
                name = str(index)
                definitions[name] = validate(CardProgram(name, name, types, continuous=continuous,
                    power=2 if 'Creature' in types else None, toughness=3 if 'Creature' in types else None))
                ref = state.add_card(name, name, rng.choice(state.players), Zone.BATTLEFIELD)
                if rng.randrange(3)==0: state.add_counters(ref, '+1/+1', 1)
                if rng.randrange(6)==0: state.phase(ref, True)
            with self.subTest(seed=seed):
                self.assertEqual(characteristics.evaluate_exhaustive(state.objects(), definitions),
                                 characteristics.evaluate(state.objects(), definitions))

    def test_independent_modifiers_skip_hypothetical_applications(self):
        state = RulesState(('A', 'B'))
        creature = CardProgram('c', 'Creature', ('Creature',), power=2, toughness=2)
        buff = CardProgram('b', 'Buff', ('Enchantment',), continuous=(ContinuousProgram('buff',
            Selector(Zone.BATTLEFIELD, ('Creature',)), (ModifyPT(1, 1),)),))
        state.add_card('c', 'c', 'A', Zone.BATTLEFIELD)
        for index in range(8): state.add_card(str(index), 'b', 'A', Zone.BATTLEFIELD)
        definitions = {'c': creature, 'b': buff}
        with patch.object(characteristics, '_apply', wraps=characteristics._apply) as apply:
            optimized = characteristics.evaluate(state.objects(), definitions)
            optimized_calls = apply.call_count
        with patch.object(characteristics, '_apply', wraps=characteristics._apply) as apply:
            reference = characteristics.evaluate_exhaustive(state.objects(), definitions)
            reference_calls = apply.call_count
        self.assertEqual(reference, optimized)
        self.assertEqual(8, optimized_calls)
        self.assertGreater(reference_calls, optimized_calls)

    def test_unknown_changes_never_get_dependency_pruning(self):
        effect = ContinuousProgram('future', Selector(Zone.BATTLEFIELD), (ModifyPT(1, 1),))
        self.assertTrue(characteristics._may_change_recipients((object(),), effect))
