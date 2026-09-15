"""Fixed recipients, captured numbers, layer-six grants and cleanup lifetime."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation,ZoneMove
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_characteristics import evaluate_exhaustive


class TemporaryEffectTests(unittest.TestCase):
    def game(self,extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(CardProgram('driver','Driver',('Artifact',)),)+tuple(extra)
        self.state=RulesState(('A','B'));self.kernel=RulesKernel(self.state,self.programs)
        self.ref=self.state.add_card('driver','driver','A',Zone.BATTLEFIELD)
    def elf(self,name='elf',owner='A'):return self.state.add_card(name,'catalog:llanowar-elves',owner,Zone.BATTLEFIELD)
    def drain(self):
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)
    def cast(self,key,mana,payment,targets=()):
        ref=self.state.add_card('spell','catalog:'+key,'A',Zone.HAND);self.kernel.open_window_for_scenario('A');self.state.add_mana('A',mana)
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',ref,targets),Payment(payment));self.drain()

    def test_recipient_set_is_fixed_and_source_departure_does_not_end_effect(self):
        self.game();old=self.elf()
        self.kernel.execute_for_scenario(self.ref,'A',(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled'),(UntilEndOfTurn('selected',(ModifyPT(2,2),)),)),Move('source',Zone.GRAVEYARD)))
        new=self.elf('new');self.assertEqual(3,self.kernel.effective(old).power);self.assertEqual(1,self.kernel.effective(new).power)
        self.kernel._finish_cleanup_actions();self.assertEqual(1,self.kernel.effective(old).power)

    def test_blink_does_not_transfer_effect_to_new_incarnation(self):
        self.game();elf=self.elf();self.kernel.execute_for_scenario(elf,'A',(UntilEndOfTurn('source',(ModifyPT(3,3),)),WithMoved('source',Zone.EXILE,(Move('moved',Zone.BATTLEFIELD),))))
        self.assertEqual(1,self.kernel.effective(self.state.current('elf')).power)
        self.assertEqual(4,self.kernel.last_known[elf][1].power)

    def test_layer_grants_and_animation_match_exhaustive_evaluation(self):
        self.game();self.kernel.execute_for_scenario(self.ref,'A',(UntilEndOfTurn('source',(ChangeTypes(add=('Creature',)),SetPT(3,4),AddKeywords(('flying','haste')))),))
        view=self.kernel.effective(self.ref);self.assertEqual((3,4),(view.power,view.toughness));self.assertIn('haste',view.keywords)
        self.assertEqual(self.kernel.characteristics(),evaluate_exhaustive(self.state.objects(),self.kernel.definitions,temporary=self.kernel._temporary_rows()))
        self.kernel._finish_cleanup_actions();self.assertNotIn('Creature',self.kernel.effective(self.ref).types)

    def test_timestamps_order_temporary_and_later_static_setters(self):
        setter=CardProgram('setter','Setter',('Enchantment',),continuous=(ContinuousProgram('set',Selector(Zone.BATTLEFIELD,types=('Creature',)),(SetPT(5,5),)),))
        self.game((setter,));elf=self.elf();self.kernel.execute_for_scenario(elf,'A',(UntilEndOfTurn('source',(SetPT(2,2),)),))
        self.state.add_card('setter','setter','B',Zone.BATTLEFIELD);self.assertEqual(5,self.kernel.effective(elf).power)
        self.kernel.execute_for_scenario(elf,'A',(UntilEndOfTurn('source',(SetPT(7,7),)),));self.assertEqual(7,self.kernel.effective(elf).power)

    def test_cleanup_removes_damage_and_toughness_bonus_before_state_actions(self):
        self.game();elf=self.elf();self.kernel.execute_for_scenario(elf,'A',(UntilEndOfTurn('source',(ModifyPT(2,2),)),Damage('source',2)))
        self.assertEqual(2,self.state.get(elf).damage_marked)
        self.kernel._finish_cleanup_actions();self.kernel.advance()
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(elf).zone);self.assertEqual(0,self.state.get(elf).damage_marked)

    def test_static_keyword_grants_follow_current_selector_membership(self):
        anthem=CardProgram('anthem','Anthem',('Enchantment',),continuous=(ContinuousProgram('grant',Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled'),(AddKeywords(('trample',)),)),))
        self.game((anthem,));self.state.add_card('anthem','anthem','A',Zone.BATTLEFIELD);elf=self.elf();other=self.elf('other','B')
        self.assertIn('trample',self.kernel.effective(elf).keywords);self.assertNotIn('trample',self.kernel.effective(other).keywords)

    def test_heroic_intervention_protects_current_permanents_and_expires(self):
        self.game();elf=self.elf();self.cast('heroic-intervention',('G','C'),(('G',1),('C',1)))
        late=self.elf('late');frame=self.kernel._frame(self.state.get(self.ref),'B',())
        self.assertNotIn(elf,{o.ref for o in self.kernel._target_query(Selector(Zone.BATTLEFIELD),frame)})
        self.assertIn(late,{o.ref for o in self.kernel._target_query(Selector(Zone.BATTLEFIELD),frame)})
        self.kernel.execute_for_scenario(elf,'A',(Destroy('source'),));self.assertEqual(Zone.BATTLEFIELD,self.state.get(elf).zone)
        self.kernel._finish_cleanup_actions();self.assertNotIn('hexproof',self.kernel.effective(elf).keywords)

    def test_give_in_to_violence_grants_lifelink_and_bonus(self):
        self.game();elf=self.elf();self.cast('give-in-to-violence',('B','C'),(('B',1),('C',1)),(elf,))
        self.assertEqual(3,self.kernel.effective(elf).power);self.assertIn('lifelink',self.kernel.effective(elf).keywords)

    def test_moment_of_craving_kills_small_creature_and_gains_life(self):
        self.game();elf=self.elf('victim','B');self.cast('moment-of-craving',('B','C'),(('B',1),('C',1)),(elf,))
        self.assertEqual(42,self.state.life('A'));self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('victim')).zone)

    def test_doomwake_entry_affects_opponents_existing_creatures(self):
        self.game();own=self.elf();victim=self.elf('victim','B');giant=self.state.add_card('giant','catalog:doomwake-giant','A',Zone.HAND)
        self.kernel.enter(giant,'A');self.drain();self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('victim')).zone)
        late=self.elf('late','B');self.assertEqual(1,self.kernel.effective(late).power);self.assertEqual(1,self.kernel.effective(own).power)

    def test_halana_uses_source_power_and_grants_haste_at_combat(self):
        self.game();elf=self.elf();self.state.add_card('partners','catalog:halana-and-alena-partners','A',Zone.BATTLEFIELD)
        self.kernel._collect_step('begin_combat');self.kernel.advance();r=self.kernel.pending_choice
        self.kernel.answer(r.request_id,'A',(next(i for i,o in enumerate(r.options) if o.ref==elf),));self.drain()
        self.assertEqual(3,self.kernel.effective(elf).power);self.assertIn('haste',self.kernel.effective(elf).keywords)

    def test_kessig_paid_x_freezes_bonus_and_replays(self):
        self.game();elf=self.elf();land=self.state.add_card('land','catalog:kessig-wolf-run','A',Zone.BATTLEFIELD)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('R','G','C','C','C'))
        self.kernel.commit_action(self.kernel.quote_activation('boost','A',land,'boost',(elf,),x_value=3),Payment((('R',1),('G',1),('C',3))))
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        while self.kernel.stack:
            actor=self.kernel.priority;command={'kind':'pass','revision':self.kernel.revision};adapter.submit(actor,command);replay.submit(actor,command)
        self.assertEqual(adapter.archive(),replay.archive());self.assertEqual(4,self.kernel.effective(elf).power);self.assertIn('trample',self.kernel.effective(elf).keywords)

    def test_basilisk_freezes_gate_count_and_enforces_sorcery_timing(self):
        self.game();elf=self.elf();gate=self.state.add_card('gate','catalog:basilisk-gate','A',Zone.BATTLEFIELD)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('C','C'))
        self.kernel.phase='upkeep'
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',gate,'boost',(elf,))
        self.kernel.phase='precombat_main';self.kernel.commit_action(self.kernel.quote_activation('boost','A',gate,'boost',(elf,)),Payment((('C',2),)));self.drain()
        self.state.add_card('second','catalog:basilisk-gate','A',Zone.BATTLEFIELD);self.assertEqual(2,self.kernel.effective(elf).power)

    def test_hashep_can_pay_by_sacrificing_its_own_tapped_source(self):
        self.game();elf=self.elf();land=self.state.add_card('oasis','catalog:hashep-oasis','A',Zone.BATTLEFIELD)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('G','G','C'))
        self.kernel.commit_action(self.kernel.quote_activation('boost','A',land,'boost',(elf,)),Payment((('G',2),('C',1)),zone_costs=(('desert',(land,)),)));self.drain()
        self.assertEqual(4,self.kernel.effective(elf).power);self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('oasis')).zone)

    def test_previous_instant_cards_are_legal_in_opponent_response_window(self):
        for key,mana in [('consider',('U',)),('growth-spiral',('G','U'))]:
            self.game();ref=self.state.add_card('spell','catalog:'+key,'A',Zone.HAND)
            self.kernel.open_window_for_scenario('B',priority_actor='A');self.state.add_mana('A',mana)
            self.kernel.quote_cast('response','A',ref)

    def test_control_change_and_phasing_preserve_the_exact_recipient(self):
        self.game();elf=self.elf();self.kernel.execute_for_scenario(elf,'A',(UntilEndOfTurn('source',(ModifyPT(2,2),)),))
        self.state.change_control(elf,'B');self.assertEqual(3,self.kernel.effective(elf).power)
        self.state.phase(elf,True);self.assertEqual(1,self.kernel.effective(elf).power)
        self.state.phase(elf,False);self.assertEqual(3,self.kernel.effective(elf).power)

    def test_bundle_rejects_printed_instant_with_sorcery_timing(self):
        import json,shutil,tempfile
        from pathlib import Path
        from edh_gauntlet.paths import PROJECT_ROOT
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'data/catalog').mkdir(parents=True);(root/'data/rules').mkdir()
            shutil.copy(PROJECT_ROOT/'data/catalog/cards.json',root/'data/catalog/cards.json')
            rows=json.loads((PROJECT_ROOT/'data/rules/primitive_cards.json').read_text())
            next(r for r in rows['cards'] if r['card_id']=='consider')['program']['cast']['timing']='sorcery'
            (root/'data/rules/primitive_cards.json').write_text(json.dumps(rows))
            with self.assertRaisesRegex(RulesViolation,'Printed instant'):load_reviewed(root)

    def test_repeated_numeric_expressions_are_captured_once(self):
        from unittest.mock import patch
        self.game();elf=self.elf();amount=CountObjects(Selector(Zone.BATTLEFIELD,types=('Creature',)))
        with patch.object(self.kernel,'_quantity',wraps=self.kernel._quantity) as quantity:
            self.kernel.execute_for_scenario(elf,'A',(UntilEndOfTurn('source',(ModifyPT(amount,amount),)),))
        self.assertEqual(1,quantity.call_count);self.assertEqual(2,self.kernel.effective(elf).power)

    def test_invalid_keywords_unbound_values_and_player_recipients_reject(self):
        base=CardProgram('test','Test',('Artifact',))
        for effect in (UntilEndOfTurn('missing',(ModifyPT(1,1),)),UntilEndOfTurn('source',(AddKeywords(('made_up',)),)),UntilEndOfTurn('source',(ModifyPT(ChosenX(),0),))):
            with self.assertRaises(RulesViolation):validate(replace(base,spell_effects=(effect,)))
        with self.assertRaises(RulesViolation):validate(replace(base,spell_targets=TargetSpec(players='opponents'),spell_effects=(UntilEndOfTurn('target',(AddKeywords(('haste',)),)),)))
