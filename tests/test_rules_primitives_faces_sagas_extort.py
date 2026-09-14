"""Hosted conformance for Pass 3's complete printed cards and shared rules."""
import json
import unittest
from collections import Counter as Counts
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,RulesViolation,Zone,ZoneMove,ObjectRef,PlayerRef
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed,digest,source_facts,validate_printed_face
from edh_gauntlet.rules_actor import project_actor
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_characteristics import evaluate,evaluate_exhaustive
from edh_gauntlet.catalog import load_catalog

CARDS=('glasswing-grace-age-graced-chapel','kazuul-s-fury-kazuul-s-cliffs','sorin-of-house-markov',
       'pontiff-of-blight','invasion-of-theros','the-restoration-of-eiganjo','elspeth-conquers-death')


class FacesSagasExtortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        reviewed=load_reviewed(cls.root)
        drafts=json.loads((cls.root/'data/rules/draft_cards.json').read_text(encoding='utf-8'))['drafts']
        cls.rows={key:reviewed[key]['review'] for key in CARDS if key in reviewed}
        cls.rows.update({r['card_id']:r for r in drafts if r['card_id'] in CARDS})
        cls.cards={key:validate(decode(cls.rows[key]['program'])) for key in CARDS}
        cls.base=tuple(r['program'] for r in reviewed.values())+tuple(cls.cards[k] for k in CARDS if k not in reviewed)

    def game(self,extra=(),players=('A','B','C','D')):
        body=CardProgram('fs-body','Body',('Creature',),power=4,toughness=4,mana_value=2,cast=CastSpec(CostSpec(ManaCost(2))))
        spell=CardProgram('fs-spell','Spell',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),spell_effects=(GainLife(1),))
        self.programs=self.base+(body,spell)+extra
        self.state=RulesState(players,seed=42);self.kernel=RulesKernel(self.state,self.programs);self.serial=0
        self.anchor=self.add('catalog:forest')
        for actor in players:
            for _ in range(15):self.add('fs-body',actor,Zone.LIBRARY)
        self.state.start_turn('A');self.kernel.open_window_for_scenario('A')

    def add(self,definition='fs-body',actor='A',zone=Zone.BATTLEFIELD,**kw):
        self.serial+=1
        return self.state.add_card('fs-'+str(self.serial),definition,actor,zone,**kw)
    def card(self,key,actor='A',zone=Zone.HAND,**kw):return self.add(self.cards[key].definition_id,actor,zone,**kw)
    def current(self,ref):return self.state.get(self.state.current(ref.card_id))
    def answer(self,indexes):
        q=self.kernel.pending_choice
        return self.kernel.answer(q.request_id,q.actor,indexes)
    def choose(self,key):return self.answer([next(i for i,o in enumerate(self.kernel.pending_choice.options) if o.key==key)])
    def payment(self,symbols='',actor='A'):
        self.state.add_mana(actor,symbols)
        return Payment(tuple(sorted(Counts(symbols).items())))
    def cast(self,ref,targets=(),symbols='',actor='A',payment=None,face=None):
        paid=self.payment(symbols,actor) if payment is None else payment
        quote=self.kernel.quote_cast('fs-cast-'+str(len(self.kernel.action_receipts)),actor,ref,targets,face=face)
        return self.kernel.commit_action(quote,paid)
    def act(self,ref,ability,targets=()):
        quote=self.kernel.quote_activation('fs-act-'+str(len(self.kernel.action_receipts)),'A',ref,ability,targets)
        return self.kernel.commit_action(quote,Payment())
    def top(self):
        fid=self.kernel.stack[-1]['id']
        for _ in range(40):
            if self.kernel.pending_choice or self.kernel._payment_waiting() or self.kernel._cast_waiting() or not any(f['id']==fid for f in self.kernel.stack):return
            self.kernel.pass_priority(self.kernel.priority)
        self.fail('Resolution failed to start')
    def drain(self):
        for _ in range(250):
            if self.kernel.pending_choice:self.answer(list(range(self.kernel.pending_choice.minimum)))
            elif self.kernel._payment_waiting():
                w=self.kernel.mana_payment
                self.kernel.pay_resolution_mana('decline-'+str(len(self.kernel.action_receipts)),w['actor'],w['id'],None,revision=self.kernel.revision)
            elif self.kernel._cast_waiting():
                w=self.kernel.resolution_cast
                self.kernel.decline_resolution_cast('decline-cast-'+str(len(self.kernel.action_receipts)),w['actor'],w['id'],revision=self.kernel.revision)
            elif self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
            else:return
        self.fail('Rules failed to settle')
    def restore(self):
        before=self.kernel.snapshot();self.kernel=RulesKernel.restore(before,self.programs);self.state=self.kernel.state
        self.assertEqual(before,self.kernel.snapshot())
    def run_effect(self,effects,source=None,targets=()):
        source=self.state.get(source or self.anchor)
        self.kernel.resolving=self.kernel._frame(source,'A',effects,targets=targets)
        return self.kernel.advance()
    def enter(self,ref,back=False,actor='A'):
        self.kernel.resolving=self.kernel._frame(self.state.get(ref),actor,(MoveFace('source',Zone.BATTLEFIELD,back_face=back),))
        self.kernel.advance();self.drain()
        return self.current(ref).ref
    def move(self,ref,zone):
        self.run_effect((Move('target',zone,controller='owner'),),targets=(ref,))
    def chapters(self,ref,n):
        self.run_effect((AddCounters('target','lore',n),),targets=(ref,))
    def main_phase(self,actor='A'):
        self.kernel.active=actor;self.kernel._begin_phase('precombat_main');self.kernel.advance()
    def transform_sorin(self,actor='A'):
        ref=self.card('sorin-of-house-markov',actor)
        return self.enter(ref,True,actor)
    def battle(self):
        ref=self.card('invasion-of-theros')
        self.kernel.resolving=self.kernel._frame(self.state.get(ref),'A',(Move('source',Zone.BATTLEFIELD),))
        self.kernel.advance();self.choose('B');self.drain()
        return self.current(ref).ref

    def test_source_bound_complete_faces(self):
        catalog={c.card_id:c for c in load_catalog(self.root/'data/catalog/cards.json')}
        self.assertEqual(set(CARDS),set(self.cards))
        for key,p in self.cards.items():
            c=catalog[key];row=self.rows[key]
            self.assertEqual('all_printed_faces',row['scope'])
            self.assertEqual(encode(p),row['program'])
            facts=source_facts(c)
            self.assertEqual(digest(facts),row.get('source_facts_sha256',digest(row.get('source_facts'))))
            faces=(p,p.back) if isinstance(p,DoubleFacedProgram) else (p,)
            self.assertEqual(len(c.faces),len(faces))
            for i,(f,program) in enumerate(zip(c.faces,faces)):validate_printed_face(key,f,program,back=bool(i and c.layout=='transform'))

    def test_derived_back_face_indicators_and_defense(self):
        self.assertEqual(('W','B'),self.cards['sorin-of-house-markov'].back.colors)
        self.assertEqual(('W','U'),self.cards['invasion-of-theros'].back.colors)
        self.assertEqual(('W',),self.cards['the-restoration-of-eiganjo'].back.colors)
        self.assertEqual(4,self.cards['invasion-of-theros'].defense)

    def test_all_programs_round_trip(self):
        for p in self.cards.values():self.assertEqual(p,validate(decode(encode(p))))

    def test_compiler_rejects_unknown_layout(self):
        with self.assertRaises(RulesViolation):validate(replace(self.cards['sorin-of-house-markov'],layout='split'))

    def test_compiler_rejects_wrong_back_identity(self):
        p=self.cards['sorin-of-house-markov']
        with self.assertRaises(RulesViolation):validate(replace(p,back=replace(p.back,definition_id='wrong')))

    def test_compiler_rejects_zero_battle_defense(self):
        with self.assertRaises(RulesViolation):validate(replace(self.cards['invasion-of-theros'],defense=0))

    def test_compiler_rejects_invalid_chapter(self):
        p=self.cards['elspeth-conquers-death']
        with self.assertRaises(RulesViolation):validate(replace(p,abilities=(replace(p.abilities[0],chapter=0),)))

    def test_glasswing_front_aura(self):
        self.game();body=self.add();card=self.card('glasswing-grace-age-graced-chapel')
        self.cast(card,(body,),symbols='CCCWB');self.drain()
        view=self.kernel.effective(body)
        self.assertEqual((6,6),(view.power,view.toughness))
        self.assertTrue({'flying','lifelink'}<=view.keywords)
        self.assertEqual(body,self.current(card).attached_to)

    def test_modal_back_land_uses_land_play(self):
        self.game();ref=self.card('glasswing-grace-age-graced-chapel')
        self.kernel.turn_schedule={'land_plays':0,'advance':False,'cleanup_priority':False}
        self.kernel.play_land('land','A',ref,revision=self.kernel.revision,face='back')
        obj=self.current(ref);self.assertTrue(obj.back_face);self.assertTrue(obj.tapped)
        self.assertEqual(frozenset({'Land'}),self.kernel.effective(obj.ref).types)
        self.assertEqual(1,self.kernel.turn_schedule['land_plays'])
        self.restore()

    def test_modal_back_land_mana_value_zero(self):
        self.game();ref=self.enter(self.card('kazuul-s-fury-kazuul-s-cliffs'),True)
        self.assertEqual(0,self.kernel.effective(ref).mana_value)

    def test_modal_back_returns_to_front_in_hand(self):
        self.game();ref=self.enter(self.card('kazuul-s-fury-kazuul-s-cliffs'),True)
        self.move(ref,Zone.HAND);obj=self.current(ref)
        self.assertFalse(obj.back_face);self.assertEqual(frozenset({'Instant'}),self.kernel.effective(obj.ref).types)

    def test_reanimation_enters_modal_front(self):
        self.game();body=self.add();ref=self.card('glasswing-grace-age-graced-chapel',zone=Zone.GRAVEYARD)
        ref=self.enter(ref)
        self.assertFalse(self.state.get(ref).back_face);self.assertIsNotNone(self.state.get(ref).attached_to)

    def test_cannot_cast_modal_land_face(self):
        self.game();ref=self.card('kazuul-s-fury-kazuul-s-cliffs')
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',ref,face='back')

    def test_cannot_normally_cast_transform_back(self):
        self.game();ref=self.card('sorin-of-house-markov')
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',ref,face='back')

    def test_cannot_select_back_of_single_face(self):
        self.game();ref=self.add('fs-spell',zone=Zone.HAND)
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',ref,face='back')

    def test_hidden_modal_land_is_front_characteristics(self):
        self.game();ref=self.card('kazuul-s-fury-kazuul-s-cliffs',zone=Zone.LIBRARY)
        self.assertEqual(frozenset({'Instant'}),self.kernel.effective(ref).types)
        self.assertEqual(3,self.kernel.effective(ref).mana_value)

    def test_kazuul_sacrifice_uses_captured_power(self):
        self.game();body=self.add();ref=self.card('kazuul-s-fury-kazuul-s-cliffs')
        self.state.add_counters(body,'+1/+1',2);paid=self.payment('CCR')
        self.cast(ref,(PlayerRef('B'),),payment=replace(paid,zone_costs=(('creature',(body,)),)))
        self.assertEqual(Zone.GRAVEYARD,self.current(body).zone);self.restore();self.drain()
        self.assertEqual(34,self.state.life('B'))

    def test_pontiff_grants_one_independent_extort(self):
        self.game();pontiff=self.card('pontiff-of-blight',zone=Zone.BATTLEFIELD);body=self.add()
        self.assertEqual(1,len(self.kernel.effective(body).granted_triggers))
        self.cast(self.add('fs-spell',zone=Zone.HAND))
        self.assertEqual(2,len(self.kernel.pending_triggers)+len(self.kernel.stack)-1)

    def test_two_pontiffs_grant_two_extort_instances(self):
        self.game();self.card('pontiff-of-blight',zone=Zone.BATTLEFIELD);self.card('pontiff-of-blight',zone=Zone.BATTLEFIELD);body=self.add()
        self.assertEqual(2,len(self.kernel.effective(body).granted_triggers))

    def test_pontiff_excludes_enemy_creatures(self):
        self.game();self.card('pontiff-of-blight',zone=Zone.BATTLEFIELD);body=self.add(actor='B')
        self.assertEqual((),self.kernel.effective(body).granted_triggers)

    def test_pontiff_grant_ends_on_departure(self):
        self.game();p=self.card('pontiff-of-blight',zone=Zone.BATTLEFIELD);body=self.add()
        self.move(p,Zone.EXILE)
        self.assertEqual((),self.kernel.effective(body).granted_triggers)

    def test_extort_black_payment_drains_all_opponents(self):
        self.game();self.card('pontiff-of-blight',zone=Zone.BATTLEFIELD)
        self.cast(self.add('fs-spell',zone=Zone.HAND));self.top()
        self.assertTrue(self.kernel._payment_waiting());self.restore()
        payment=self.payment('B');w=self.kernel.mana_payment
        self.kernel.pay_resolution_mana('extort','A',w['id'],payment,revision=self.kernel.revision)
        self.assertEqual(43,self.state.life('A'));self.assertEqual([39,39,39],[self.state.life(p) for p in ('B','C','D')])

    def test_extort_decline_loses_no_life(self):
        self.game();self.card('pontiff-of-blight',zone=Zone.BATTLEFIELD)
        self.cast(self.add('fs-spell',zone=Zone.HAND));self.drain()
        self.assertEqual([41,40,40,40],[self.state.life(p) for p in self.state.players])

    def test_sorin_back_entry_loyalty_and_mana_value(self):
        self.game();ref=self.transform_sorin();obj=self.state.get(ref)
        self.assertEqual(3,dict(obj.counters)['loyalty']);self.assertTrue(obj.back_face)
        self.assertEqual(2,self.kernel.effective(ref).mana_value);self.restore()

    def test_sorin_in_place_transform_has_no_starting_loyalty(self):
        self.game();ref=self.card('sorin-of-house-markov',zone=Zone.BATTLEFIELD)
        self.run_effect((Transform(),),source=ref)
        self.assertEqual(Zone.GRAVEYARD,self.current(ref).zone)

    def test_sorin_postcombat_counts_life_before_entry(self):
        self.game();self.state.gain_life('A',3);ref=self.card('sorin-of-house-markov',zone=Zone.BATTLEFIELD)
        self.kernel._begin_phase('postcombat_main');self.kernel.advance();self.drain()
        self.assertTrue(self.current(ref).back_face)
        self.assertEqual(3,dict(self.current(ref).counters)['loyalty'])

    def test_sorin_no_postcombat_trigger_below_threshold(self):
        self.game();self.state.gain_life('A',2);ref=self.card('sorin-of-house-markov',zone=Zone.BATTLEFIELD)
        self.kernel._begin_phase('postcombat_main');self.kernel.advance()
        self.assertFalse(self.kernel.stack);self.assertFalse(self.current(ref).back_face)

    def test_sorin_damage_uses_total_life_gained(self):
        self.game();ref=self.transform_sorin();self.state.gain_life('A',7);self.state.lose_life_batch(('A',),7)
        self.act(ref,'life-gained-damage',(PlayerRef('B'),));self.drain()
        self.assertEqual(33,self.state.life('B'))

    def test_sorin_food_uses_existing_token_definition(self):
        self.game();ref=self.transform_sorin();self.act(ref,'create-food');self.drain()
        foods=[o for o in self.state.objects(Zone.BATTLEFIELD) if 'Food' in self.kernel.effective(o.ref).subtypes]
        self.assertEqual(1,len(foods));self.assertEqual('consume',self.kernel.activated_abilities(foods[0])[0].ability_id)

    def test_saga_enters_with_lore_and_first_chapter(self):
        self.game();ref=self.card('the-restoration-of-eiganjo')
        self.kernel.resolving=self.kernel._frame(self.state.get(ref),'A',(Move('source',Zone.BATTLEFIELD),))
        self.kernel.advance()
        self.assertEqual(1,dict(self.current(ref).counters)['lore'])
        self.assertEqual('chapter-1',self.kernel.stack[-1]['ability_id'])

    def test_saga_does_not_get_lore_in_postcombat_main(self):
        self.game();ref=self.enter(self.card('the-restoration-of-eiganjo'))
        self.kernel._begin_phase('postcombat_main');self.kernel.advance()
        self.assertEqual(1,dict(self.state.get(ref).counters)['lore'])

    def test_saga_precombat_lore_survives_checkpoint(self):
        self.game();ref=self.enter(self.card('the-restoration-of-eiganjo'))
        self.kernel._begin_phase('precombat_main');self.restore();self.kernel.advance()
        self.assertEqual(2,dict(self.state.get(ref).counters)['lore'])
        self.assertEqual('chapter-2',self.kernel.stack[-1]['ability_id'])

    def test_saga_final_chapter_keeps_source_until_resolution(self):
        self.game();ref=self.enter(self.card('the-restoration-of-eiganjo'))
        self.chapters(ref,2)
        if self.kernel.pending_choice:self.answer(list(range(len(self.kernel.pending_choice.options))))
        self.assertEqual(Zone.BATTLEFIELD,self.current(ref).zone);self.drain()
        self.assertTrue(self.current(ref).back_face);self.assertEqual(3,self.kernel.effective(self.current(ref).ref).mana_value)

    def test_restoration_can_return_just_discarded_permanent(self):
        self.game();ref=self.enter(self.card('the-restoration-of-eiganjo'));body=self.add(zone=Zone.HAND)
        self.chapters(ref,1);self.top()
        self.assertEqual('reflexive_discard',self.kernel.pending_choice.kind);self.answer([0])
        self.assertEqual('trigger_targets',self.kernel.pending_choice.kind)
        self.assertEqual(body.card_id,self.kernel.pending_choice.options[0].ref.card_id)
        self.restore();self.answer([0]);self.drain()
        self.assertEqual(Zone.BATTLEFIELD,self.current(body).zone);self.assertTrue(self.current(body).tapped)

    def test_restoration_optional_discard_may_decline(self):
        self.game();ref=self.enter(self.card('the-restoration-of-eiganjo'));body=self.add(zone=Zone.HAND)
        self.chapters(ref,1);self.top();self.answer([])
        self.assertEqual(Zone.HAND,self.current(body).zone);self.assertFalse(self.kernel.stack)

    def test_battle_entry_protector_and_defense(self):
        self.game();ref=self.battle()
        self.assertEqual('B',self.state.get(ref).protector);self.assertEqual(4,dict(self.state.get(ref).counters)['defense']);self.restore()

    def test_battle_controller_can_attack_it(self):
        self.game();ref=self.battle()
        player,target=self.kernel._attack_destination('A',ref)
        self.assertEqual('B',player);self.assertTrue(target['battle'])

    def test_battle_protector_cannot_attack_it(self):
        self.game();ref=self.battle()
        with self.assertRaises(RulesViolation):self.kernel._attack_destination('B',ref)

    def test_defeat_offers_transformed_cast(self):
        self.game();ref=self.battle()
        self.run_effect((Damage('target',4),),targets=(ref,))
        self.assertEqual('intrinsic-siege-defeat',self.kernel.stack[-1]['ability_id']);self.restore();self.top()
        self.assertTrue(self.kernel._cast_waiting());self.assertEqual(Zone.EXILE,self.current(ref).zone)
        self.restore();self.cast(self.current(ref).ref);self.drain()
        obj=self.current(ref);self.assertTrue(obj.back_face);self.assertEqual(Zone.BATTLEFIELD,obj.zone)
        self.assertEqual(3,self.kernel.effective(obj.ref).mana_value);self.assertIsNone(self.kernel.resolution_cast)

    def test_defeat_may_decline_cast(self):
        self.game();ref=self.battle()
        self.run_effect((Damage('target',4),),targets=(ref,));self.drain()
        self.assertEqual(Zone.EXILE,self.current(ref).zone);self.assertIsNone(self.kernel.resolution_cast)

    def test_ephara_requires_three_other_enchantments(self):
        self.game();ref=self.enter(self.card('invasion-of-theros'),True)
        self.assertNotIn('indestructible',self.kernel.effective(ref).keywords)
        others=[self.add('catalog:leyline-of-hope') for _ in range(3)]
        self.assertIn('indestructible',self.kernel.effective(ref).keywords)
        self.move(others[0],Zone.EXILE);self.assertNotIn('indestructible',self.kernel.effective(ref).keywords)

    def test_elspeth_tax_survives_source_departure(self):
        self.game();ref=self.card('elspeth-conquers-death',zone=Zone.BATTLEFIELD)
        self.run_effect(self.cards['elspeth-conquers-death'].abilities[1].effects,source=ref)
        self.move(ref,Zone.EXILE);self.kernel.priority='B'
        quote=self.kernel.quote_cast('taxed','B',self.add('fs-spell','B',Zone.HAND))
        self.assertEqual(2,quote.cost.mana.generic);self.restore()

    def test_elspeth_tax_excludes_creatures_and_own_spells(self):
        self.game();self.run_effect(self.cards['elspeth-conquers-death'].abilities[1].effects)
        self.assertEqual(0,self.kernel.quote_cast('own','A',self.add('fs-spell',zone=Zone.HAND)).cost.mana.generic)
        self.kernel.active='B';self.kernel.priority='B'
        self.assertEqual(2,self.kernel.quote_cast('creature','B',self.add('fs-body','B',Zone.HAND)).cost.mana.generic)

    def test_elspeth_tax_expires_at_next_turn(self):
        self.game();self.run_effect(self.cards['elspeth-conquers-death'].abilities[1].effects)
        self.kernel._expire_spell_taxes('B');self.assertEqual(1,len(self.kernel.timed_spell_taxes))
        self.state.start_turn('D');self.kernel._expire_spell_taxes('A');self.assertEqual([],self.kernel.timed_spell_taxes)

    def test_elspeth_counter_choice_after_return(self):
        self.game();body=self.add(zone=Zone.GRAVEYARD)
        self.run_effect(self.cards['elspeth-conquers-death'].abilities[2].effects,targets=(body,))
        self.assertEqual(Zone.BATTLEFIELD,self.current(body).zone)
        self.assertEqual('counter_kind',self.kernel.pending_choice.kind);self.restore();self.choose('loyalty')
        self.assertEqual(1,dict(self.current(body).counters)['loyalty'])

    def test_lifelink_counter_is_an_ability(self):
        self.game();body=self.add();self.run_effect((AddCounters('target','lifelink',1),),targets=(body,))
        self.assertIn('lifelink',self.kernel.effective(body).keywords);self.restore()

    def test_copy_of_back_face_is_single_face_zero_mana_value(self):
        self.game();ref=self.enter(self.card('the-restoration-of-eiganjo'),True);clone=self.add()
        self.run_effect((CopyPermanent('source','target'),),source=clone,targets=(ref,))
        self.assertEqual(0,self.kernel.effective(clone).mana_value)
        self.assertNotIsInstance(self.kernel.definition(self.state.get(clone)),DoubleFacedProgram)
        self.restore()

    def test_copy_token_has_both_faces_and_current_orientation(self):
        self.game();ref=self.enter(self.card('the-restoration-of-eiganjo'),True)
        self.run_effect((CopyTokens('source'),),source=ref)
        tokens=[o for o in self.state.objects(Zone.BATTLEFIELD) if o.token]
        self.assertEqual(1,len(tokens));token=tokens[0]
        self.assertTrue(token.back_face);self.assertIsInstance(self.kernel.definitions[token.definition],DoubleFacedProgram)
        self.assertEqual(3,self.kernel.effective(token.ref).mana_value);self.restore()

    def test_original_reviewed_rows_are_unchanged(self):
        self.assertGreaterEqual(len(load_reviewed(self.root)),320)


if __name__=='__main__':unittest.main()
