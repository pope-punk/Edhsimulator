"""Source-bound promotion and entry-land conformance; drafts stay isolated."""
import json
import unittest
from pathlib import Path

from edh_gauntlet.catalog import load_catalog
from edh_gauntlet.rules_bundle import digest, load_reviewed, source_facts
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_program import EntryPayment, decode, encode, validate
from edh_gauntlet.rules_state import RulesState, RulesViolation, Zone


PROMOTED_CARDS = frozenset((
    'game-trail', 'shineshadow-snarl', 'vineglimmer-snarl',
    'godless-shrine', 'hallowed-fountain', 'stomping-ground', 'watery-grave',
    'mulldrifter', 'reveillark', 'vesperlark',
    'oblivion-ring', 'leonin-relic-warder', 'animate-dead',
    'crop-rotation', 'fling',
    'uro-titan-of-nature-s-wrath', 'bulk-up', 'grasp-of-fate', 'prayer-of-binding',
    'dawn-of-hope', 'rhystic-study', 'smothering-tithe', 'gleaming-splendor',
    'forgotten-ancient', 'the-ozolith', 'aven-courier', 'essence-channeler',
    'xolatoyac-the-smiling-flood', 'the-earth-crystal', 'dark-depths', 'parallax-wave',
))


class CardProgramReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.bundle = json.loads((cls.root / 'data/rules/draft_cards.json').read_text(encoding='utf-8'))
        cls.reviewed = load_reviewed(cls.root)
        cls.cards = {key: cls.reviewed[key]['program'] for key in PROMOTED_CARDS}
        cls.lands = {key: program for key, program in cls.cards.items()
                     if program.entry_modifiers and isinstance(program.entry_modifiers[0], EntryPayment)}
        cls.programs = tuple(row['program'] for row in cls.reviewed.values())

    def test_draft_bundle_stays_separate_and_source_bound(self):
        self.assertEqual('edh-card-drafts:1', self.bundle['schema'])
        self.assertEqual('unvalidated_draft', self.bundle['status'])
        self.assertFalse(self.bundle['production_ready'])
        self.assertNotIn('cards', self.bundle)
        rows = self.bundle['drafts']
        self.assertEqual(len(rows), len({row['card_id'] for row in rows}))
        catalog = {card.card_id: card for card in load_catalog(self.root / 'data/catalog/cards.json')}
        inventory = json.loads((self.root / 'reports/remaining-card-drafts.json').read_text(encoding='utf-8'))
        expected = {row['card_id'] for row in inventory['cards']
                    if row['status'] == 'draft_written_review_pending'}
        self.assertEqual(expected, {row['card_id'] for row in rows})
        for row in rows:
            key = row['card_id']
            with self.subTest(card=key):
                self.assertNotIn(key, self.reviewed)
                self.assertEqual('unvalidated_draft', row['status'])
                self.assertEqual('all_printed_faces', row['scope'])
                self.assertEqual(digest(source_facts(catalog[key])), digest(row['source_facts']))
                program = validate(decode(row['program']))
                self.assertEqual('draft:' + key, program.definition_id)
                self.assertEqual(row['program'], encode(program))

    def test_promoted_cards_load_with_complete_printed_faces_and_review_bindings(self):
        catalog = {card.card_id: card for card in load_catalog(self.root / 'data/catalog/cards.json')}
        self.assertEqual(31, len(self.cards))
        self.assertEqual(7, len(self.lands))
        for key, program in self.cards.items():
            with self.subTest(card=key):
                review = self.reviewed[key]['review']
                self.assertEqual('catalog:' + key, program.definition_id)
                self.assertEqual('all_printed_faces', review['scope'])
                self.assertTrue(review['review_basis'])
                self.assertEqual(digest(source_facts(catalog[key])), review['source_facts_sha256'])
                self.assertEqual(review['program'], encode(program))
                self.assertEqual(catalog[key].name, program.name)
                self.assertEqual(1, len(catalog[key].faces))
                face = catalog[key].faces[0]
                for field in ('types', 'subtypes', 'supertypes', 'colors'):
                    self.assertEqual(set(getattr(face, field)), set(getattr(program, field)))
                for field in ('mana_value', 'power', 'toughness'):
                    self.assertEqual(getattr(face, field), getattr(program, field))
                if 'Land' in program.types:
                    self.assertIsNone(program.cast)
                else:
                    self.assertIsNotNone(program.cast)
                    self.assertEqual('instant' if 'Instant' in face.types else 'sorcery', program.cast.timing)

    def test_shock_lands_keep_both_intrinsic_mana_abilities(self):
        symbols = {'Plains': 'W', 'Island': 'U', 'Swamp': 'B', 'Mountain': 'R', 'Forest': 'G'}
        for key in ('godless-shrine', 'hallowed-fountain', 'stomping-ground', 'watery-grave'):
            program = self.cards[key]
            self.assertEqual((), program.activated)
            for subtype in program.subtypes:
                with self.subTest(card=key, subtype=subtype):
                    state = RulesState(('A', 'B'))
                    ref = state.add_card('entry', program.definition_id, 'A', Zone.HAND)
                    kernel = RulesKernel(state, self.programs)
                    request = kernel.enter(ref)
                    index = next(i for i, option in enumerate(request.options) if option.key == 'pay')
                    kernel.answer(request.request_id, 'A', [index])
                    kernel.open_window_for_scenario('A')
                    current = state.current('entry')
                    kernel.commit_action(kernel.quote_activation(
                        'mana', 'A', current, 'intrinsic-land:' + subtype), Payment())
                    self.assertEqual(((symbols[subtype], 1),), state.mana_pool('A'))
                    self.assertEqual(38, state.life('A'))

    def test_reveal_lands_produce_exact_printed_colors_after_revealing(self):
        cases = (
            ('game-trail', 'mountain', ('R', 'G')),
            ('shineshadow-snarl', 'plains', ('W', 'B')),
            ('vineglimmer-snarl', 'island', ('G', 'U')),
        )
        for key, matching, symbols in cases:
            for symbol in symbols:
                with self.subTest(card=key, symbol=symbol):
                    state = RulesState(('A', 'B'))
                    program = self.cards[key]
                    ref = state.add_card('entry', program.definition_id, 'A', Zone.HAND)
                    reveal = state.add_card('reveal', 'catalog:' + matching, 'A', Zone.HAND)
                    kernel = RulesKernel(state, self.programs)
                    request = kernel.enter(ref)
                    index = next(i for i, option in enumerate(request.options) if option.ref == reveal)
                    kernel.answer(request.request_id, 'A', [index])
                    kernel.open_window_for_scenario('A')
                    kernel.commit_action(kernel.quote_activation(
                        'mana', 'A', state.current('entry'), 'mana'), Payment())
                    request = kernel.pending_choice
                    index = next(i for i, option in enumerate(request.options)
                                 if option.key == symbol)
                    kernel.answer(request.request_id, 'A', [index])
                    self.assertEqual(((symbol, 1),), state.mana_pool('A'))
                    self.assertEqual(40, state.life('A'))
                    self.assertEqual(Zone.HAND, state.get(reveal).zone)

    def test_play_land_choice_resumes_without_spending_a_second_land_play(self):
        matching = {'game-trail': 'mountain', 'shineshadow-snarl': 'plains', 'vineglimmer-snarl': 'island'}
        for key, program in self.lands.items():
            with self.subTest(card=key):
                state = RulesState(('A', 'B'))
                ref = state.add_card('entry', program.definition_id, 'A', Zone.HAND)
                if key in matching:
                    state.add_card('reveal', 'catalog:' + matching[key], 'A', Zone.HAND)
                state.add_card('draw', 'catalog:forest', 'A', Zone.LIBRARY)
                kernel = RulesKernel(state, self.programs)
                kernel.begin_turn_for_scenario('A')
                for _ in range(4):
                    kernel.pass_priority(kernel.priority)
                request = kernel.play_land('play', 'A', ref, revision=kernel.revision)
                self.assertEqual(1, kernel.turn_schedule['land_plays'])
                restored = RulesKernel.restore(json.loads(json.dumps(kernel.snapshot())), self.programs)
                indexes = [next(i for i, o in enumerate(request.options) if o.key == 'pay')] if program.entry_modifiers[0].life else []
                kernel.answer(request.request_id, 'A', indexes)
                restored.answer(request.request_id, 'A', indexes)
                self.assertEqual(kernel.snapshot(), restored.snapshot())
                self.assertEqual(1, kernel.turn_schedule['land_plays'])
                self.assertEqual([], kernel.stack)
                self.assertEqual(Zone.BATTLEFIELD, state.get(state.current('entry')).zone)
                with self.assertRaises(RulesViolation):
                    kernel.play_land('play', 'A', state.current('entry'), revision=kernel.revision)
                self.assertEqual(1, kernel.turn_schedule['land_plays'])

    def test_reviewed_lands_use_shared_entry_payment_nodes(self):
        for program in self.lands.values():
            self.assertEqual(1, len(program.entry_modifiers))
            self.assertIsInstance(program.entry_modifiers[0], EntryPayment)
            self.assertEqual((), program.abilities)
