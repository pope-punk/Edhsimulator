"""Authored executable coverage never masquerades as production certification."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from edh_gauntlet.paths import PROJECT_ROOT
from edh_gauntlet.rules_bundle import load_reviewed,deck_coverage
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_casting import Payment


class BundleTests(unittest.TestCase):
    def drain_stack(self,kernel):
        while kernel.stack:
            kernel.pass_priority(kernel.priority)

    def test_authored_entry_draw_creatures_use_shared_etb_resolution(self):
        rows=load_reviewed();programs=tuple(row['program'] for row in rows.values())
        for key,symbols,payment in (('baleful-strix',('U','B'),(('U',1),('B',1))),
                                    ('spirited-companion',('W','C'),(('W',1),('C',1)))):
            state=RulesState(('A','B'));program=rows[key]['program']
            ref=state.add_card('creature',program.definition_id,'A',Zone.HAND)
            draw=state.add_card('draw',rows['forest']['program'].definition_id,'A',Zone.LIBRARY)
            kernel=RulesKernel(state,programs);kernel.open_window_for_scenario('A');state.add_mana('A',symbols)
            kernel.commit_action(kernel.quote_cast('cast','A',ref),Payment(payment))
            self.drain_stack(kernel)
            self.assertEqual(Zone.HAND,state.get(state.current(draw.card_id)).zone)
            current=state.current('creature');self.assertEqual(Zone.BATTLEFIELD,state.get(current).zone)
            self.assertEqual(set(program.keywords),set(kernel.effective(current).keywords))
            self.assertEqual((),state.mana_pool('A'))

    def test_authored_counterspell_counters_a_real_stack_spell(self):
        rows=load_reviewed();programs=tuple(row['program'] for row in rows.values())
        state=RulesState(('A','B'))
        victim=state.add_card('victim',rows['sol-ring']['program'].definition_id,'B',Zone.HAND)
        counter=state.add_card('counter',rows['counterspell']['program'].definition_id,'A',Zone.HAND)
        kernel=RulesKernel(state,programs);kernel.stage_spell_for_scenario(victim,'B');kernel.pass_priority('B')
        state.add_mana('A',('U','U'))
        kernel.commit_action(kernel.quote_cast('counter','A',counter,(state.current('victim'),)),Payment((('U',2),)))
        self.drain_stack(kernel)
        self.assertEqual(Zone.GRAVEYARD,state.get(state.current('victim')).zone)
        self.assertEqual(Zone.GRAVEYARD,state.get(state.current('counter')).zone)

    def test_authored_zombify_restricts_ownership_and_preserves_entry_triggers(self):
        rows=load_reviewed();programs=tuple(row['program'] for row in rows.values())
        state=RulesState(('A','B'))
        creature=state.add_card('creature',rows['baleful-strix']['program'].definition_id,'A',Zone.GRAVEYARD)
        other=state.add_card('other',rows['baleful-strix']['program'].definition_id,'B',Zone.GRAVEYARD)
        spell=state.add_card('spell',rows['zombify']['program'].definition_id,'A',Zone.HAND)
        state.add_card('draw',rows['forest']['program'].definition_id,'A',Zone.LIBRARY)
        kernel=RulesKernel(state,programs);kernel.open_window_for_scenario('A');state.add_mana('A',('B','C','C','C'))
        with self.assertRaises(RulesViolation):kernel.quote_cast('bad','A',spell,(other,))
        kernel.commit_action(kernel.quote_cast('cast','A',spell,(creature,)),Payment((('B',1),('C',3))))
        self.drain_stack(kernel)
        self.assertEqual(Zone.BATTLEFIELD,state.get(state.current('creature')).zone)
        self.assertEqual(Zone.HAND,state.get(state.current('draw')).zone)
        self.assertEqual(Zone.GRAVEYARD,state.get(other).zone)

    def test_exact_pod_counts_and_unmapped_cards_remain_visible(self):
        coverage=deck_coverage()
        self.assertEqual(199,coverage['authored_unique_cards'])
        self.assertEqual(400,sum(deck['cards'] for deck in coverage['decks']))
        self.assertEqual(4,len(coverage['decks']));self.assertFalse(coverage['production_ready'])
        for deck in coverage['decks']:
            self.assertEqual(deck['cards'],deck['authored_copies']+deck['unmapped_copies'])
            self.assertGreater(deck['unmapped_copies'],0)
            self.assertTrue(all(not row['production_certified'] for row in deck['entries']))

    def test_reviewed_sol_ring_uses_shared_casting_and_mana(self):
        rows=load_reviewed();programs=tuple(row['program'] for row in rows.values())
        ring=rows['sol-ring']['program'];state=RulesState(('A','B'))
        source=state.add_card('ring',ring.definition_id,'A',Zone.HAND)
        kernel=RulesKernel(state,programs);kernel.open_window_for_scenario('A');state.add_mana('A',('G',))
        kernel.commit_action(kernel.quote_cast('cast','A',source),Payment((('G',1),)))
        kernel.pass_priority('A');kernel.pass_priority('B')
        kernel.open_window_for_scenario('A')
        kernel.commit_action(kernel.quote_activation('mana','A',state.current('ring'),'produce-mana'),Payment())
        self.assertEqual((('C',2),),state.mana_pool('A'))

    def test_basic_land_types_confer_mana_without_printed_abilities(self):
        rows=load_reviewed();forest=rows['forest']['program']
        self.assertEqual((),forest.activated);self.assertEqual(('Basic',),forest.supertypes)
        state=RulesState(('A','B'));source=state.add_card('forest',forest.definition_id,'A',Zone.BATTLEFIELD)
        kernel=RulesKernel(state,[forest]);kernel.open_window_for_scenario('A')
        kernel.commit_action(kernel.quote_activation('mana','A',source,'intrinsic-land:Forest'),Payment())
        self.assertEqual((('G',1),),state.mana_pool('A'))

    def test_catalog_change_invalidates_authored_source_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for folder,file in (('catalog','cards.json'),('rules','primitive_cards.json')):
                (root/'data'/folder).mkdir(parents=True)
                shutil.copyfile(PROJECT_ROOT/'data'/folder/file,root/'data'/folder/file)
            path=root/'data/rules/primitive_cards.json';value=json.loads(path.read_text())
            value['cards'][0]['source_facts_sha256']='changed';path.write_text(json.dumps(value))
            with self.assertRaisesRegex(RulesViolation,'source facts changed'):load_reviewed(root)
