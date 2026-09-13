"""Regressions from the printed-text and shared-primitive library audit."""
from collections import Counter
import json
import unittest

from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_program import CardProgram, ChangeTypes, ContinuousProgram, Damage, Selector
from edh_gauntlet.rules_state import RulesState, RulesViolation, Zone, ZoneMove


class LibraryAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_reviewed()
        cls.reviewed = tuple(row['program'] for row in cls.rows.values())

    def game(self, *extra):
        self.programs = self.reviewed + extra
        self.state = RulesState(('A', 'B'))
        self.kernel = RulesKernel(self.state, self.programs)

    def add(self, key, name=None, owner='A', zone=Zone.BATTLEFIELD):
        return self.state.add_card(name or key, 'catalog:' + key, owner, zone)

    def drain(self):
        while self.kernel.stack and not self.kernel.pending_choice:
            self.kernel.pass_priority(self.kernel.priority)
        return self.kernel.pending_choice

    def answer(self, key):
        request = self.kernel.pending_choice
        index = next(i for i, option in enumerate(request.options) if option.key == key)
        self.kernel.answer(request.request_id, request.actor, [index])
        return self.drain()

    def test_avenger_landfall_selects_only_controlled_plant_creatures(self):
        plant = CardProgram('plant', 'Plant', ('Creature',), subtypes=('Plant',), power=0, toughness=1)
        kindred = CardProgram('kindred', 'Kindred Plant', ('Kindred', 'Enchantment'), subtypes=('Plant',))
        changeling = CardProgram('changeling', 'Kindred Changeling', ('Kindred', 'Enchantment'),
                                 all_subtype_sets=('creature',))
        self.game(plant, kindred, changeling)
        self.add('avenger-of-zendikar')
        own = self.state.add_card('own', 'plant', 'A', Zone.BATTLEFIELD)
        enemy = self.state.add_card('enemy', 'plant', 'B', Zone.BATTLEFIELD)
        noncreature = self.state.add_card('noncreature', 'kindred', 'A', Zone.BATTLEFIELD)
        all_types = self.state.add_card('all-types', 'changeling', 'A', Zone.BATTLEFIELD)
        creature_changeling = self.add('taurean-mauler')
        other = self.add('llanowar-elves')
        enemy_land = self.add('forest', 'enemy-land', 'B', Zone.HAND)
        self.kernel.enter(enemy_land)
        self.assertIsNone(self.drain())
        self.assertFalse(self.kernel.stack)
        land = self.add('forest', 'own-land', zone=Zone.HAND)
        self.kernel.enter(land)
        self.assertEqual('may', self.drain().kind)
        self.answer('yes')
        for ref in (own, creature_changeling):
            self.assertEqual({'+1/+1': 1}, dict(self.state.get(ref).counters))
        for ref in (enemy, noncreature, all_types, other):
            self.assertEqual((), self.state.get(ref).counters)

    def test_lyra_grants_lifelink_to_kindred_angels_without_noncreature_power(self):
        angel = CardProgram('angel', 'Angel', ('Creature',), subtypes=('Angel',), power=2, toughness=2)
        kindred = CardProgram('kindred', 'Kindred Angel', ('Kindred', 'Enchantment'), subtypes=('Angel',))
        self.game(angel, kindred)
        lyra = self.add('lyra-dawnbringer')
        creature = self.state.add_card('creature', 'angel', 'A', Zone.BATTLEFIELD)
        own = self.state.add_card('own', 'kindred', 'A', Zone.BATTLEFIELD)
        enemy = self.state.add_card('enemy', 'kindred', 'B', Zone.BATTLEFIELD)
        unrelated = self.add('llanowar-elves')
        self.assertEqual((5, 5), (self.kernel.effective(lyra).power, self.kernel.effective(lyra).toughness))
        self.assertEqual((3, 3), (self.kernel.effective(creature).power, self.kernel.effective(creature).toughness))
        view = self.kernel.effective(own)
        self.assertIn('lifelink', view.keywords)
        self.assertEqual((None, None), (view.power, view.toughness))
        self.assertNotIn('lifelink', self.kernel.effective(enemy).keywords)
        self.assertNotIn('lifelink', self.kernel.effective(unrelated).keywords)
        # Lifelink matters on noncreature damage sources, without animating them.
        self.kernel.execute_for_scenario(own, 'A', (Damage('source', 2, players='opponents', exclude_damage_source=True),))
        self.assertEqual((42, 38), (self.state.life('A'), self.state.life('B')))
        self.state.move((ZoneMove(lyra, Zone.GRAVEYARD),), 'fixture')
        self.assertNotIn('lifelink', self.kernel.effective(own).keywords)
        self.assertEqual(2, self.kernel.effective(creature).power)

    def test_priest_counts_elves_including_opposing_kindreds_but_not_hand_cards(self):
        kindred = CardProgram('kindred', 'Kindred Elf', ('Kindred', 'Enchantment'), subtypes=('Elf',))
        self.game(kindred)
        priest = self.add('priest-of-titania')
        self.add('llanowar-elves')
        self.state.add_card('own', 'kindred', 'A', Zone.BATTLEFIELD)
        self.state.add_card('enemy', 'kindred', 'B', Zone.BATTLEFIELD)
        self.state.add_card('hand', 'kindred', 'A', Zone.HAND)
        self.add('forest')
        self.state.start_turn('A')
        self.kernel.open_window_for_scenario('A')
        self.kernel.commit_action(self.kernel.quote_activation('mana', 'A', priest, 'mana'), Payment())
        self.assertEqual({'G': 4}, dict(self.state.mana_pool('A')))
        self.assertFalse(self.kernel.stack)

    def test_fabricate_creates_two_servos_with_the_rules_defined_token_name(self):
        self.game()
        angel = self.add('angel-of-invention', zone=Zone.HAND)
        self.kernel.enter(angel)
        self.assertEqual('may', self.drain().kind)
        self.answer('no')
        tokens = [obj for obj in self.state.objects(Zone.BATTLEFIELD) if obj.token]
        self.assertEqual(2, len(tokens))
        for token in tokens:
            definition = self.kernel.definition(token)
            self.assertEqual('Servo Token', definition.name)
            self.assertEqual(('Servo',), definition.subtypes)
            self.assertEqual({'Artifact', 'Creature'}, set(definition.types))
            self.assertEqual((1, 1, ()), (definition.power, definition.toughness, definition.colors))
            self.assertEqual((2, 2), (self.kernel.effective(token.ref).power,
                                     self.kernel.effective(token.ref).toughness))
        entries = [event for event in self.state.events if event.after.ref in {obj.ref for obj in tokens}]
        self.assertEqual(1, len({event.batch for event in entries}))

    def test_normalized_mana_choices_produce_each_printed_color_and_keep_pain(self):
        cases = {
            'adarkar-wastes': 'WU', 'birds-of-paradise': 'WUBRG', 'caves-of-koilos': 'WB',
            'deserted-beach': 'WU', 'dreamroot-cascade': 'GU', 'karplusan-forest': 'RG',
            'lumbering-falls': 'GU', 'mana-confluence': 'WUBRG', 'morphic-pool': 'UB',
            'restless-fortress': 'WB', 'rockfall-vale': 'RG', 'ruby-daring-tracker': 'RG',
            'scoured-barrens': 'WB', 'sea-of-clouds': 'WU', 'shattered-sanctum': 'WB',
            'shipwreck-marsh': 'UB', 'silent-clearing': 'WB', 'simic-guildgate': 'GU',
            'spire-garden': 'RG', 'talisman-of-dominance': 'UB', 'talisman-of-hierarchy': 'WB',
            'talisman-of-progress': 'WU', 'temple-of-mystery': 'GU',
            'temple-of-silence': 'WB', 'vault-of-champions': 'WB', 'yavimaya-coast': 'GU',
        }
        pain = {'adarkar-wastes', 'caves-of-koilos', 'karplusan-forest', 'yavimaya-coast',
                'talisman-of-dominance', 'talisman-of-hierarchy', 'talisman-of-progress'}
        life_costs = {'mana-confluence', 'silent-clearing'}
        for key, colors in cases.items():
            ability = next(ability for ability in self.rows[key]['program'].activated
                           if ability.mana_ability and getattr(ability.effects[0], 'options', None))
            for color in colors:
                with self.subTest(card=key, color=color):
                    self.game()
                    ref = self.add(key)
                    self.state.start_turn('A')
                    self.kernel.open_window_for_scenario('A')
                    request = self.kernel.commit_action(
                        self.kernel.quote_activation('mana', 'A', ref, ability.ability_id), Payment())
                    self.assertEqual(list(colors), [option.key for option in request.options])
                    self.assertEqual((), self.state.mana_pool('A'))
                    self.assertEqual(39 if key in life_costs else 40, self.state.life('A'))
                    self.assertTrue(self.state.get(ref).tapped)
                    self.answer(color)
                    self.assertEqual({color: 1}, dict(self.state.mana_pool('A')))
                    self.assertEqual(39 if key in pain | life_costs else 40, self.state.life('A'))
                    damage = [event for event in self.kernel.semantic_events if event['kind'] == 'damage_dealt']
                    self.assertEqual(1 if key in pain else 0, len(damage))
                    self.assertFalse(self.kernel.stack)
                    self.assertEqual(1, len(self.kernel.action_receipts))

    def test_changed_mana_choices_restore_without_repaying_or_doubling_damage(self):
        for key in ('mana-confluence', 'adarkar-wastes'):
            with self.subTest(card=key):
                self.game()
                ref = self.add(key)
                self.add('mana-reflection')
                self.kernel.open_window_for_scenario('A')
                ability = next(ability for ability in self.rows[key]['program'].activated
                               if ability.mana_ability and getattr(ability.effects[0], 'options', None))
                request = self.kernel.commit_action(
                    self.kernel.quote_activation('mana', 'A', ref, ability.ability_id), Payment())
                restored = RulesKernel.restore(json.loads(json.dumps(self.kernel.snapshot())), self.programs)
                for kernel in (self.kernel, restored):
                    before = kernel.snapshot()
                    with self.assertRaises(RulesViolation):
                        kernel.answer(request.request_id, 'B', [0])
                    self.assertEqual(before, kernel.snapshot())
                    kernel.answer(request.request_id, 'A', [0])
                self.assertEqual(self.kernel.snapshot(), restored.snapshot())
                self.assertEqual({'W': 2}, dict(self.state.mana_pool('A')))
                self.assertEqual(39, self.state.life('A'))
                self.assertEqual(1, len(self.kernel.action_receipts))
                self.assertFalse(self.kernel.stack)

    def test_filter_and_any_combination_mana_keep_mixed_color_bundles(self):
        cases = (
            ('flooded-grove', 'filter', ('GG', 'GU', 'UU'), ('G',), Payment((('G', 1),))),
            ('sage-of-the-maze', 'mana',
             ('WW', 'WU', 'WB', 'WR', 'WG', 'UU', 'UB', 'UR', 'UG', 'BB', 'BR', 'BG', 'RR', 'RG', 'GG'),
             (), Payment()),
        )
        for key, ability_id, bundles, pool, payment in cases:
            for index, bundle in enumerate(bundles):
                with self.subTest(card=key, bundle=bundle):
                    self.game()
                    ref = self.add(key)
                    self.state.start_turn('A')
                    self.state.add_mana('A', pool)
                    self.kernel.open_window_for_scenario('A')
                    request = self.kernel.commit_action(
                        self.kernel.quote_activation('mana', 'A', ref, ability_id), payment)
                    self.assertEqual(len(bundles), len(request.options))
                    self.kernel.answer(request.request_id, 'A', [index])
                    self.assertEqual(dict(Counter(bundle)), dict(self.state.mana_pool('A')))
                    self.assertFalse(self.kernel.stack)

    def test_constellation_self_entry_survives_type_change_and_never_triggers_twice(self):
        strip = CardProgram('strip', 'Remove Enchantment', ('Artifact',), continuous=(
            ContinuousProgram('strip', Selector(Zone.BATTLEFIELD, types=('Creature', 'Enchantment')),
                              (ChangeTypes(remove=('Enchantment',)),)),))
        enchantment = CardProgram('enchantment', 'Enchantment', ('Enchantment',))
        creature = CardProgram('creature', 'Creature', ('Creature',), power=8, toughness=8)
        for key in ('doomwake-giant', 'grim-guardian', 'underworld-coinsmith'):
            for remove_type in (False, True):
                with self.subTest(card=key, remove_type=remove_type):
                    self.game(strip, enchantment, creature)
                    if remove_type:
                        self.state.add_card('strip', 'strip', 'A', Zone.BATTLEFIELD)
                    victim = self.state.add_card('victim', 'creature', 'B', Zone.BATTLEFIELD)
                    source = self.add(key, zone=Zone.HAND)
                    self.kernel.enter(source)
                    self.assertIsNone(self.drain())
                    self.assertEqual(not remove_type,
                                     'Enchantment' in self.kernel.effective(self.state.current(key)).types)
                    self.assertEqual(41 if key == 'underworld-coinsmith' else 40, self.state.life('A'))
                    self.assertEqual(39 if key == 'grim-guardian' else 40, self.state.life('B'))
                    self.assertEqual(7 if key == 'doomwake-giant' else 8, self.kernel.effective(victim).power)
                    # Another controlled enchantment still triggers the other branch.
                    other = self.state.add_card('other', 'enchantment', 'A', Zone.HAND)
                    self.kernel.enter(other)
                    self.assertIsNone(self.drain())
                    self.assertEqual(42 if key == 'underworld-coinsmith' else 40, self.state.life('A'))
                    self.assertEqual(38 if key == 'grim-guardian' else 40, self.state.life('B'))
                    self.assertEqual(6 if key == 'doomwake-giant' else 8, self.kernel.effective(victim).power)
                    # An opposing enchantment and an ordinary own creature do not.
                    for name, definition, owner in (('enemy', 'enchantment', 'B'), ('own', 'creature', 'A')):
                        ref = self.state.add_card(name, definition, owner, Zone.HAND)
                        self.kernel.enter(ref)
                        self.assertIsNone(self.drain())
                    self.assertEqual(42 if key == 'underworld-coinsmith' else 40, self.state.life('A'))
                    self.assertEqual(38 if key == 'grim-guardian' else 40, self.state.life('B'))
                    self.assertEqual(6 if key == 'doomwake-giant' else 8, self.kernel.effective(victim).power)
