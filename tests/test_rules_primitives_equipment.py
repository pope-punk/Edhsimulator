"""Equip uses ordinary costs/targets; attachment legality is independent of control."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter


class EquipmentTests(unittest.TestCase):
    def game(self):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(CardProgram('driver','Driver',('Artifact',)),)
        self.state=RulesState(('A','B'));self.kernel=RulesKernel(self.state,self.programs)
        self.elf=self.state.add_card('elf','catalog:llanowar-elves','A',Zone.BATTLEFIELD)
        self.other=self.state.add_card('other','catalog:llanowar-elves','B',Zone.BATTLEFIELD)
        self.boots=self.state.add_card('boots','catalog:swiftfoot-boots','A',Zone.BATTLEFIELD)
    def drain(self):
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)
    def equip(self,ref=None,target=None,action='equip'):
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('C',))
        self.kernel.commit_action(self.kernel.quote_activation(action,'A',ref or self.boots,'equip',(target or self.elf,)),Payment((('C',1),)));self.drain()
    def armor_entry(self):
        armor=self.state.add_card('armor','catalog:celestial-armor','A',Zone.HAND);self.kernel.enter(armor,'A')
        r=self.kernel.pending_choice;self.kernel.answer(r.request_id,'A',(next(i for i,o in enumerate(r.options) if o.ref==self.elf),))
        return self.state.current('armor')

    def test_equipment_enters_unattached_without_aura_choice(self):
        self.game();ref=self.state.add_card('new','catalog:swiftfoot-boots','A',Zone.HAND);self.kernel.enter(ref,'A')
        self.assertIsNone(self.kernel.pending_choice);self.assertIsNone(self.state.get(self.state.current('new')).attached_to)

    def test_equip_pays_targets_own_creature_and_grants_keywords(self):
        self.game();self.equip();self.assertEqual(self.elf,self.state.get(self.boots).attached_to)
        self.assertTrue({'hexproof','haste'}<=self.kernel.effective(self.elf).keywords);self.assertEqual((),self.state.mana_pool('A'))

    def test_equip_rejects_opponent_and_nonsorcery_window_before_payment(self):
        self.game();self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('C',));before=self.state.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',self.boots,'equip',(self.other,))
        self.assertEqual(before,self.state.snapshot());self.kernel.phase='upkeep'
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',self.boots,'equip',(self.elf,))

    def test_equip_target_control_change_fizzles_without_moving_old_attachment(self):
        self.game();self.equip();second=self.state.add_card('second','catalog:llanowar-elves','A',Zone.BATTLEFIELD)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('C',))
        self.kernel.commit_action(self.kernel.quote_activation('second','A',self.boots,'equip',(second,)),Payment((('C',1),)))
        self.state.change_control(second,'B');self.drain();self.assertEqual(self.elf,self.state.get(self.boots).attached_to)

    def test_existing_attachment_survives_creature_control_change(self):
        self.game();self.equip();self.state.change_control(self.elf,'B');self.kernel.advance()
        self.assertEqual(self.elf,self.state.get(self.boots).attached_to);self.assertIn('hexproof',self.kernel.effective(self.elf).keywords)
        self.assertEqual('A',self.state.get(self.boots).controller)

    def test_host_departure_detaches_equipment_without_destroying_it(self):
        self.game();self.equip();self.kernel.execute_for_scenario(self.elf,'A',(Move('source',Zone.GRAVEYARD),))
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.boots).zone);self.assertIsNone(self.state.get(self.boots).attached_to)

    def test_host_losing_creature_type_detaches_equipment(self):
        self.game();self.equip();self.kernel.execute_for_scenario(self.elf,'A',(UntilEndOfTurn('source',(ChangeTypes(remove=('Creature',)),)),))
        self.assertIsNone(self.state.get(self.boots).attached_to);self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.boots).zone)

    def test_animated_equipment_detaches_and_cannot_attach_as_creature(self):
        self.game();self.equip();self.kernel.execute_for_scenario(self.boots,'A',(UntilEndOfTurn('source',(ChangeTypes(add=('Creature',)),SetPT(2,2))),))
        self.assertIsNone(self.state.get(self.boots).attached_to);self.assertNotIn('haste',self.kernel.effective(self.elf).keywords)
        self.equip(action='animated');self.assertIsNone(self.state.get(self.boots).attached_to)

    def test_non_attachment_permanent_cannot_attach_and_illegal_state_is_detached(self):
        self.game();ref=self.state.add_card('driver','driver','A',Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(ref,'A',(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled'),(Attach('source','selected'),)),))
        self.assertIsNone(self.state.get(ref).attached_to)
        self.state.attach(ref,self.elf);self.kernel.advance();self.assertIsNone(self.state.get(ref).attached_to)

    def test_same_host_equip_pays_but_does_not_change_timestamp_or_attach_again(self):
        self.game();self.equip();stamp=self.state.get(self.boots).timestamp
        self.equip(action='again');self.assertEqual(stamp,self.state.get(self.boots).timestamp)
        self.assertEqual(1,sum(e['kind']=='attached' for e in self.kernel.semantic_events));self.assertEqual((),self.state.mana_pool('A'))

    def test_switching_host_moves_continuous_grants_and_replays(self):
        self.game();self.equip();second=self.state.add_card('second','catalog:llanowar-elves','A',Zone.BATTLEFIELD)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('C',));self.kernel.commit_action(self.kernel.quote_activation('switch','A',self.boots,'equip',(second,)),Payment((('C',1),)))
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        while self.kernel.stack:
            actor=self.kernel.priority;command={'kind':'pass','revision':self.kernel.revision};adapter.submit(actor,command);replay.submit(actor,command)
        self.assertEqual(adapter.archive(),replay.archive());self.assertNotIn('haste',self.kernel.effective(self.elf).keywords);self.assertIn('haste',self.kernel.effective(second).keywords)

    def test_celestial_armor_entry_and_independent_temporary_protection(self):
        self.game();armor=self.armor_entry();self.drain();self.assertEqual(self.elf,self.state.get(armor).attached_to)
        view=self.kernel.effective(self.elf);self.assertEqual(3,view.power);self.assertTrue({'flying','hexproof','indestructible'}<=view.keywords)
        self.kernel._finish_cleanup_actions();view=self.kernel.effective(self.elf);self.assertIn('flying',view.keywords);self.assertNotIn('indestructible',view.keywords)

    def test_armor_departure_before_entry_trigger_still_grants_protection(self):
        self.game();armor=self.armor_entry()
        removal=self.state.add_card('removal','catalog:utter-end','A',Zone.HAND);self.state.add_mana('A',('W','B','C','C'))
        self.kernel.commit_action(self.kernel.quote_cast('remove','A',removal,(armor,)),Payment((('W',1),('B',1),('C',2))));self.drain()
        view=self.kernel.effective(self.elf);self.assertEqual(1,view.power);self.assertTrue({'hexproof','indestructible'}<=view.keywords);self.assertNotIn('flying',view.keywords)

    def test_phased_equipment_cannot_be_attached_by_resolving_ability(self):
        self.game();self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('C',));self.kernel.commit_action(self.kernel.quote_activation('equip','A',self.boots,'equip',(self.elf,)),Payment((('C',1),)))
        self.state.phase(self.boots,True);self.drain();self.assertIsNone(self.state.get(self.boots).attached_to)

    def test_armor_flash_quote_on_opponent_turn(self):
        self.game();armor=self.state.add_card('armor','catalog:celestial-armor','A',Zone.HAND);self.kernel.open_window_for_scenario('B',priority_actor='A');self.state.add_mana('A',('W','C','C'))
        self.kernel.quote_cast('flash','A',armor)

    def test_authored_bundle_checks_characteristics_and_casting_cost(self):
        import json,tempfile,shutil
        from pathlib import Path
        from edh_gauntlet.paths import PROJECT_ROOT
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'data/catalog').mkdir(parents=True);(root/'data/rules').mkdir()
            shutil.copy(PROJECT_ROOT/'data/catalog/cards.json',root/'data/catalog/cards.json')
            original=json.loads((PROJECT_ROOT/'data/rules/primitive_cards.json').read_text())
            for field in ('power','colors','mana'):
                rows=json.loads(json.dumps(original));row=next(r for r in rows['cards'] if r['card_id']=='healer-s-hawk')['program']
                if field=='power':row['power']=2
                elif field=='colors':row['colors']=['B']
                else:row['cast']['cost']['mana']['generic']=1
                (root/'data/rules/primitive_cards.json').write_text(json.dumps(rows))
                with self.assertRaisesRegex(RulesViolation,'Printed'):load_reviewed(root)

    def test_known_attachment_legality_does_not_scan_the_battlefield(self):
        from unittest.mock import patch
        self.game();self.equip()
        with patch.object(self.kernel,'_query',side_effect=AssertionError('Unnecessary battlefield scan')):
            self.assertTrue(self.kernel._attachment_legal(self.state.get(self.boots),self.elf))
            self.assertFalse(self.kernel._attachment_legal(self.state.get(self.boots),self.boots))
