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

CARDS=["aminatou-veil-piercer","entity-tracker","funeral-room-awakening-hall","ghostly-dancers","victor-valgavoth-s-seneschal","the-cruelty-of-gix","urza-s-saga"]


class RoomsMiracleSagasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        reviewed=load_reviewed(cls.root)
        drafts=json.loads((cls.root/'data/rules/draft_cards.json').read_text())['drafts']
        cls.rows={r['card_id']:r for r in drafts if r['card_id'] in CARDS}
        cls.cards={key:validate(decode(cls.rows[key]['program'])) for key in CARDS}
        cls.base=tuple(r['program'] for r in reviewed.values())+tuple(cls.cards.values())

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
    def ability(self,ref,name):
        return next(a.ability_id for a in self.kernel.activated_abilities(self.state.get(ref)) if a.ability_id==name or ('"'+name+'"') in a.ability_id)
    def act(self,ref,ability,targets=()):
        ability=self.ability(ref,ability)
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

    def unlocked(self,ref,door='left'):
        self.run_effect((UnlockRoom('target',door),),targets=(ref,));self.drain()
        self.kernel.open_window_for_scenario('A')
        return self.current(ref)

    def test_complete_source_binding_and_codec(self):
        catalog={c.card_id:c for c in load_catalog(self.root/'data/catalog/cards.json')}
        for key,p in self.cards.items():
            with self.subTest(card=key):
                self.assertEqual(encode(p),self.rows[key]['program'])
                self.assertEqual(digest(source_facts(catalog[key])),digest(self.rows[key]['source_facts']))
                faces=(p,p.right) if isinstance(p,RoomProgram) else (p,)
                for f,q in zip(catalog[key].faces,faces):validate_printed_face(key,f,q)
                self.assertEqual(p,decode(encode(p)))

    def test_room_combined_hand_and_graveyard(self):
        self.game();ref=self.card('funeral-room-awakening-hall')
        self.assertEqual(11,self.kernel.effective(ref).mana_value)
        self.assertEqual(3,self.kernel.effective(ref).mana_symbols.count('B'))
        self.move(ref,Zone.GRAVEYARD);self.assertEqual(11,self.kernel.effective(self.current(ref).ref).mana_value)

    def test_room_direct_entry_closed(self):
        self.game();ref=self.enter(self.card('funeral-room-awakening-hall'))
        self.assertEqual((),self.state.get(ref).unlocked)
        self.assertEqual(0,self.kernel.effective(ref).mana_value)
        self.assertEqual('',self.kernel.definition(self.state.get(ref)).name)
        self.assertEqual((),self.kernel._trigger_abilities(self.state.get(ref),'zone_changed'))
        self.restore()

    def test_left_room_cast_has_only_left_cost(self):
        self.game();ref=self.card('funeral-room-awakening-hall')
        self.cast(ref,symbols='CCB',face='left')
        self.assertEqual(3,self.kernel.effective(self.current(ref).ref).mana_value)
        self.drain();obj=self.current(ref)
        self.assertEqual(('left',),obj.unlocked);self.assertEqual('Funeral Room',self.kernel.definition(obj).name)

    def test_right_room_cast_reanimates_own_creatures(self):
        self.game();own=self.add(zone=Zone.GRAVEYARD);foreign=self.add(actor='B',zone=Zone.GRAVEYARD)
        ref=self.card('funeral-room-awakening-hall');self.cast(ref,symbols='CCCCCCBB',face='right')
        self.drain()
        self.assertEqual(('right',),self.current(ref).unlocked)
        self.assertEqual(Zone.BATTLEFIELD,self.current(own).zone);self.assertEqual(Zone.GRAVEYARD,self.current(foreign).zone)
        self.assertEqual('A',self.current(own).controller)

    def test_funeral_each_death_and_one_life_gain(self):
        self.game();ref=self.enter(self.card('funeral-room-awakening-hall'));self.unlocked(ref)
        bodies=(self.add(),self.add())
        self.run_effect((Move('target',Zone.GRAVEYARD),),targets=bodies);self.drain()
        self.assertEqual(42,self.state.life('A'));self.assertEqual([38]*3,[self.state.life(p) for p in 'BCD'])

    def test_locked_funeral_has_no_death_trigger(self):
        self.game();self.enter(self.card('funeral-room-awakening-hall'));body=self.add()
        self.move(body,Zone.GRAVEYARD);self.drain()
        self.assertEqual(40,self.state.life('A'))

    def test_room_unlock_special_action_and_full_event(self):
        self.game();tracker=self.card('entity-tracker',zone=Zone.BATTLEFIELD)
        ref=self.enter(self.card('funeral-room-awakening-hall'));self.unlocked(ref)
        hand=len(self.state.zone('A',Zone.HAND));paid=self.payment('CCCCCCBB')
        self.kernel.unlock_room('unlock','A',ref,'right',paid,revision=self.kernel.revision)
        self.drain();self.assertEqual(hand+1,len(self.state.zone('A',Zone.HAND)))
        self.assertEqual(('left','right'),self.state.get(ref).unlocked)
        self.assertEqual(11,self.kernel.effective(ref).mana_value)

    def test_unlock_bad_payment_atomic(self):
        self.game();ref=self.enter(self.card('funeral-room-awakening-hall'));self.kernel.open_window_for_scenario('A')
        paid=self.payment('B');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.unlock_room('bad','A',ref,'left',paid,revision=self.kernel.revision)
        self.assertEqual(before,self.kernel.snapshot())

    def test_unlock_wrong_actor_atomic(self):
        self.game();ref=self.enter(self.card('funeral-room-awakening-hall'));self.kernel.open_window_for_scenario('A')
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.unlock_room('bad','B',ref,'left',Payment(),revision=self.kernel.revision)
        self.assertEqual(before,self.kernel.snapshot())

    def test_relocking_allows_a_new_full_unlock(self):
        self.game();self.card('entity-tracker',zone=Zone.BATTLEFIELD);ref=self.enter(self.card('funeral-room-awakening-hall'))
        self.unlocked(ref,'both');n=len(self.state.zone('A',Zone.HAND))
        self.run_effect((LockRoom('target','left'),UnlockRoom('target','left')),targets=(ref,));self.drain()
        self.assertEqual(n+1,len(self.state.zone('A',Zone.HAND)))

    def test_unlocking_open_door_is_no_event(self):
        self.game();self.card('entity-tracker',zone=Zone.BATTLEFIELD);ref=self.enter(self.card('funeral-room-awakening-hall'));self.unlocked(ref,'both')
        n=len(self.state.zone('A',Zone.HAND));self.unlocked(ref,'both')
        self.assertEqual(n,len(self.state.zone('A',Zone.HAND)))

    def test_room_copy_enters_closed_and_retains_two_halves(self):
        self.game();ref=self.enter(self.card('funeral-room-awakening-hall'));self.unlocked(ref,'both')
        self.run_effect((CopyTokens('target',1),),targets=(ref,));self.drain()
        token=next(o for o in self.state.objects(Zone.BATTLEFIELD) if o.token)
        self.assertEqual((),token.unlocked);self.assertIsInstance(self.kernel.definitions[token.effective_definition],RoomProgram)
        self.assertEqual(0,self.kernel.effective(token.ref).mana_value);self.restore()

    def test_room_blink_resets_doors(self):
        self.game();ref=self.enter(self.card('funeral-room-awakening-hall'));self.unlocked(ref,'both')
        self.move(ref,Zone.EXILE);self.drain();ref=self.enter(self.current(ref).ref)
        self.assertEqual((),self.state.get(ref).unlocked)

    def test_entity_flash(self):
        self.game();ref=self.card('entity-tracker')
        self.kernel.open_window_for_scenario('A',phase='upkeep')
        self.cast(ref,symbols='CCU');self.drain();self.assertEqual(Zone.BATTLEFIELD,self.current(ref).zone)

    def test_ghostly_returns_enchantment_without_target(self):
        self.game();enchantment=self.card('funeral-room-awakening-hall',zone=Zone.GRAVEYARD);ref=self.card('ghostly-dancers')
        self.enter(ref);self.assertEqual(Zone.HAND,self.current(enchantment).zone)

    def test_ghostly_unlocks_and_creates_flying_spirit(self):
        self.game();room=self.enter(self.card('funeral-room-awakening-hall'));self.unlocked(room)
        self.enter(self.card('ghostly-dancers'))
        tokens=[o for o in self.state.objects(Zone.BATTLEFIELD) if o.token]
        self.assertEqual(1,len(tokens));v=self.kernel.effective(tokens[0].ref)
        self.assertEqual((3,1),(v.power,v.toughness));self.assertIn('flying',v.keywords);self.assertEqual(frozenset({'W'}),v.colors)

    def test_victor_counts_resolutions_not_triggers(self):
        self.game();ref=self.card('victor-valgavoth-s-seneschal',zone=Zone.BATTLEFIELD)
        ability=self.cards['victor-valgavoth-s-seneschal'].abilities[0]
        self.kernel._trigger(self.state.get(ref),ability);self.kernel._trigger(self.state.get(ref),ability)
        self.assertEqual({},self.kernel.resolution_counts)
        self.kernel.advance();self.drain();self.assertEqual([2],list(self.kernel.resolution_counts.values()))

    def test_victor_second_discard_uses_each_opponents_choice(self):
        self.game();ref=self.card('victor-valgavoth-s-seneschal',zone=Zone.BATTLEFIELD)
        for p in 'BCD':self.add(actor=p,zone=Zone.HAND)
        effect=self.cards['victor-valgavoth-s-seneschal'].abilities[0].effects[0]
        self.run_effect((effect,),source=ref);self.drain()
        self.run_effect((effect,),source=ref);self.restore();self.drain()
        self.assertEqual([0,0,0],[len(self.state.zone(p,Zone.HAND)) for p in 'BCD'])

    def test_victor_third_reanimates_foreign_creature(self):
        self.game();ref=self.card('victor-valgavoth-s-seneschal',zone=Zone.BATTLEFIELD);body=self.add(actor='B',zone=Zone.GRAVEYARD)
        effect=self.cards['victor-valgavoth-s-seneschal'].abilities[0].effects[0]
        for _ in range(3):self.run_effect((effect,),source=ref);self.drain()
        self.assertEqual(Zone.BATTLEFIELD,self.current(body).zone);self.assertEqual('A',self.current(body).controller)

    def test_victor_fourth_does_nothing(self):
        self.game();ref=self.card('victor-valgavoth-s-seneschal',zone=Zone.BATTLEFIELD)
        effect=self.cards['victor-valgavoth-s-seneschal'].abilities[0].effects[0]
        for _ in range(3):self.run_effect((effect,),source=ref);self.drain()
        body=self.add(zone=Zone.GRAVEYARD)
        self.run_effect((effect,),source=ref);self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.current(body).zone);self.assertEqual([4],list(self.kernel.resolution_counts.values()))

    def test_victor_new_turn_restarts(self):
        self.game();ref=self.card('victor-valgavoth-s-seneschal',zone=Zone.BATTLEFIELD)
        effect=self.cards['victor-valgavoth-s-seneschal'].abilities[0].effects[0]
        self.run_effect((effect,),source=ref);self.drain();self.state.start_turn('B')
        self.run_effect((effect,),source=ref);self.drain();self.assertEqual([1],list(self.kernel.resolution_counts.values()))

    def test_read_ahead_three_skips_earlier_chapters(self):
        self.game();body=self.add(actor='B',zone=Zone.GRAVEYARD);ref=self.card('the-cruelty-of-gix')
        self.run_effect((Move('target',Zone.BATTLEFIELD),),targets=(ref,));self.assertEqual('read_ahead',self.kernel.pending_choice.kind)
        self.restore();self.choose('3');self.drain()
        self.assertEqual(40,self.state.life('A'));self.assertEqual(Zone.BATTLEFIELD,self.current(body).zone);self.assertEqual(Zone.GRAVEYARD,self.current(ref).zone)

    def test_read_ahead_two_searches_then_loses_life(self):
        self.game();ref=self.card('the-cruelty-of-gix')
        self.run_effect((Move('target',Zone.BATTLEFIELD),),targets=(ref,));self.choose('2');self.drain()
        self.assertEqual(37,self.state.life('A'));self.assertEqual(1,len(self.state.zone('A',Zone.HAND)))
        self.assertEqual(2,dict(self.current(ref).counters)['lore'])

    def test_gix_first_reveals_and_chooses_opponents_creature(self):
        self.game();body=self.add(actor='B',zone=Zone.HAND);ref=self.card('the-cruelty-of-gix')
        self.run_effect((Move('target',Zone.BATTLEFIELD),),targets=(ref,));self.choose('1');self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.current(body).zone)
        self.assertTrue(project_actor(self.kernel,'C')['public_hand_disclosures'])

    def test_urza_is_land_and_gains_mana_from_chapter(self):
        self.game();ref=self.card('urza-s-saga')
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',ref)
        ref=self.enter(ref)
        self.assertEqual(1,dict(self.state.get(ref).counters)['lore'])
        self.assertTrue(self.ability(ref,'saga-mana'))
        self.kernel.open_window_for_scenario('A');self.act(ref,'saga-mana')
        self.assertEqual(1,dict(self.state.mana_pool('A')).get('C',0))

    def test_urza_construct_counts_itself_and_live_artifacts(self):
        self.game();ref=self.enter(self.card('urza-s-saga'));self.chapters(ref,1);self.drain()
        self.kernel.open_window_for_scenario('A');paid=self.payment('CC')
        q=self.kernel.quote_activation('construct','A',ref,self.ability(ref,'saga-construct'));self.kernel.commit_action(q,paid);self.drain()
        token=next(o for o in self.state.objects(Zone.BATTLEFIELD) if o.token)
        self.assertEqual(1,self.kernel.effective(token.ref).power)
        artifact=self.add('catalog:sol-ring')
        self.assertEqual(2,self.kernel.effective(token.ref).power);self.move(artifact,Zone.GRAVEYARD);self.drain()
        self.assertEqual(1,self.kernel.effective(token.ref).power);self.restore()

    def test_exact_cost_selector_distinguishes_absent_zero_one_and_colored(self):
        extra=tuple(CardProgram('cost-'+key,key,('Artifact',),cast=CastSpec(CostSpec(mana)) if mana is not None else None) for key,mana in (('absent',None),('zero',ManaCost()),('one',ManaCost(1)),('blue',ManaCost(0,('U',))),('x',ManaCost(x_symbols=1))))
        self.game(extra)
        refs={key:self.add('cost-'+key,zone=Zone.LIBRARY) for key in ('absent','zero','one','blue','x')}
        selector=ExactManaCostSelector(Zone.LIBRARY,types=('Artifact',),costs=(ManaCost(),ManaCost(1)))
        from edh_gauntlet.rules_characteristics import matches
        source=self.state.get(self.anchor);views=self.kernel.characteristics()
        self.assertEqual({refs['zero'],refs['one']},{o.ref for o in self.state.zone('A',Zone.LIBRARY) if matches(selector,o,views[o.ref],source)})

    def test_miracle_first_draw_reveal_is_checkpointed(self):
        self.game();self.card('aminatou-veil-piercer',zone=Zone.BATTLEFIELD);ref=self.card('funeral-room-awakening-hall',zone=Zone.LIBRARY)
        self.run_effect((Draw(2),));self.assertEqual('miracle_reveal',self.kernel.pending_choice.kind)
        self.restore();self.choose('4')
        self.assertEqual(2,len(self.state.zone('A',Zone.HAND)))
        self.assertEqual(1,len(project_actor(self.kernel,'B')['revealed_hand']))
        self.drain();self.assertEqual([],project_actor(self.kernel,'B')['revealed_hand'])

    def test_miracle_decline_keeps_identity_private(self):
        self.game();self.card('aminatou-veil-piercer',zone=Zone.BATTLEFIELD);self.card('funeral-room-awakening-hall',zone=Zone.LIBRARY)
        self.run_effect((Draw(1),));self.choose('no');self.drain()
        self.assertEqual([],project_actor(self.kernel,'B')['revealed_hand'])
        self.assertNotIn('public_hand_disclosures',project_actor(self.kernel,'B'))

    def test_miracle_room_casts_selected_half_for_reduced_cost(self):
        self.game();self.card('aminatou-veil-piercer',zone=Zone.BATTLEFIELD);ref=self.card('funeral-room-awakening-hall',zone=Zone.LIBRARY)
        self.run_effect((Draw(1),));self.choose('4');self.top()
        self.assertTrue(self.kernel._cast_waiting());self.restore()
        paid=self.payment('BBCC');q=self.kernel.quote_cast('miracle','A',self.current(ref).ref,face='right')
        self.assertEqual(ManaCost(2,('B','B')),q.cost.mana)
        self.kernel.commit_action(q,paid);self.drain();self.assertEqual(('right',),self.current(ref).unlocked)

    def test_miracle_exact_card_permission(self):
        self.game();self.card('aminatou-veil-piercer',zone=Zone.BATTLEFIELD);other=self.card('entity-tracker');ref=self.card('funeral-room-awakening-hall',zone=Zone.LIBRARY)
        self.run_effect((Draw(1),));self.choose('4');self.top()
        self.assertEqual((self.current(ref).ref,),self.kernel._resolution_cast_candidates())
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('other','A',other)

    def test_miracle_second_draw_not_revealed(self):
        self.game();self.card('aminatou-veil-piercer',zone=Zone.BATTLEFIELD)
        self.run_effect((Draw(1),));self.drain();self.card('funeral-room-awakening-hall',zone=Zone.LIBRARY)
        self.run_effect((Draw(1),));self.assertIsNone(self.kernel.pending_choice);self.assertFalse(self.kernel.stack)

    def test_put_into_hand_does_not_use_first_draw(self):
        self.game();self.card('aminatou-veil-piercer',zone=Zone.BATTLEFIELD);ref=self.card('funeral-room-awakening-hall',zone=Zone.LIBRARY)
        self.move(ref,Zone.HAND);self.assertEqual({},self.kernel.draw_counts)
        self.card('funeral-room-awakening-hall',zone=Zone.LIBRARY);self.run_effect((Draw(1),));self.assertEqual('miracle_reveal',self.kernel.pending_choice.kind)

    def test_miracle_enchantment_with_x(self):
        spell=CardProgram('miracle-x','X enchantment',('Enchantment',),cast=CastSpec(CostSpec(ManaCost(1,('W',),1))))
        self.game((spell,));self.card('aminatou-veil-piercer',zone=Zone.BATTLEFIELD);ref=self.add('miracle-x',zone=Zone.LIBRARY)
        self.run_effect((Draw(1),));self.choose('4');self.top()
        q=self.kernel.quote_cast('x','A',self.current(ref).ref,x_value=5)
        self.assertEqual(ManaCost(2,('W',)),q.cost.mana)

    def test_miracle_other_turn_and_source_leaves(self):
        self.game();aminatou=self.card('aminatou-veil-piercer',zone=Zone.BATTLEFIELD);ref=self.card('funeral-room-awakening-hall',zone=Zone.LIBRARY)
        self.state.start_turn('B');self.kernel.active='B'
        self.run_effect((Draw(1),));self.choose('4')
        self.state.move((ZoneMove(aminatou,Zone.GRAVEYARD),),'fixture')
        self.top();self.assertEqual((self.current(ref).ref,),self.kernel._resolution_cast_candidates())

    def test_actor_room_door_disclosure(self):
        self.game();ref=self.enter(self.card('funeral-room-awakening-hall'))
        row=next(r for r in project_actor(self.kernel,'B')['zones']['battlefield']['A'] if r['ref']==ref.to_json())
        self.assertEqual('room',row['layout']);self.assertEqual([],row['unlocked']);self.assertEqual(2,len(row['doors']))

    def test_discard_choices_stay_private_until_simultaneous_move(self):
        self.game()
        cards={p:self.add(actor=p,zone=Zone.HAND) for p in 'BCD'}
        self.run_effect((DiscardPlayers(),))
        self.assertEqual('B',self.kernel.pending_choice.actor);self.answer([0])
        self.assertEqual('C',self.kernel.pending_choice.actor)
        self.assertEqual(Zone.HAND,self.state.get(cards['B']).zone)
        self.assertEqual([],project_actor(self.kernel,'C')['revealed_hand'])
        self.restore();self.answer([0]);self.answer([0]);self.drain()
        events=[e for e in self.state.events if e.cause=='discard']
        self.assertEqual(3,len(events));self.assertEqual(1,len({e.batch for e in events}))

    def test_victor_copied_ability_counts_the_same_group(self):
        self.game();ref=self.card('victor-valgavoth-s-seneschal',zone=Zone.BATTLEFIELD)
        a=self.cards['victor-valgavoth-s-seneschal'].abilities[0]
        self.kernel._trigger(self.state.get(ref),a);self.kernel.advance()
        blueprint=self.kernel._copy_blueprint(self.kernel.stack[-1])
        self.kernel._materialize_copy(blueprint,'A','copy-fixture')
        self.drain();self.assertEqual([2],list(self.kernel.resolution_counts.values()))

    def test_urza_granted_mana_does_not_copy(self):
        self.game();ref=self.enter(self.card('urza-s-saga'))
        self.run_effect((CopyTokens('target',1),),targets=(ref,));self.drain()
        token=next(o for o in self.state.objects(Zone.BATTLEFIELD) if o.token)
        # The token's own chapter I grants one fresh mana ability.
        self.assertEqual(1,len(self.kernel.activated_abilities(token)))

    def test_construct_bonus_applies_after_base_setting(self):
        self.game();saga=self.enter(self.card('urza-s-saga'));self.chapters(saga,1);self.drain()
        token_program=self.cards['urza-s-saga'].abilities[1].effects[0].changes[0].ability.effects[0].token
        self.run_effect((CreateTokens(token_program,1),));self.drain()
        token=next(o for o in self.state.objects(Zone.BATTLEFIELD) if o.token)
        self.run_effect((OngoingEffect('target',(SetPT(5,5),)),),targets=(token.ref,));self.drain()
        self.assertEqual(6,self.kernel.effective(token.ref).power)

    def test_room_cost_modifiers_do_not_reduce_unlock_payment(self):
        reducer=CardProgram('room-reducer','Reducer',('Creature',),power=2,toughness=2,cost_modifiers=(CostModifier('enchantments',Selector(Zone.STACK,types=('Enchantment',),relation='controlled'),-1),))
        self.game((reducer,));ref=self.enter(self.card('funeral-room-awakening-hall'));self.add('room-reducer')
        self.kernel.open_window_for_scenario('A');paid=self.payment('CB');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.unlock_room('cheap','A',ref,'left',paid,revision=self.kernel.revision)
        self.assertEqual(before,self.kernel.snapshot())

    def test_room_unlock_replay_is_rejected(self):
        self.game();ref=self.enter(self.card('funeral-room-awakening-hall'));self.kernel.open_window_for_scenario('A')
        paid=self.payment('CCB');self.kernel.unlock_room('once','A',ref,'left',paid,revision=self.kernel.revision)
        self.kernel.open_window_for_scenario('A');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.unlock_room('once','A',ref,'right',Payment(),revision=self.kernel.revision)
        self.assertEqual(before,self.kernel.snapshot())

    def test_miracle_trigger_loses_exact_hand_incarnation(self):
        self.game();self.card('aminatou-veil-piercer',zone=Zone.BATTLEFIELD);ref=self.card('funeral-room-awakening-hall',zone=Zone.LIBRARY)
        self.run_effect((Draw(1),));self.choose('4')
        hand=self.current(ref).ref
        self.state.move((ZoneMove(hand,Zone.EXILE),),'fixture')
        self.state.move((ZoneMove(self.current(ref).ref,Zone.HAND),),'fixture')
        self.top();self.assertEqual((),self.kernel._resolution_cast_candidates())
        self.assertEqual([],project_actor(self.kernel,'B')['revealed_hand'])

    def test_corrupt_miracle_window_checkpoint_rejected(self):
        self.game();self.card('aminatou-veil-piercer',zone=Zone.BATTLEFIELD);self.card('funeral-room-awakening-hall',zone=Zone.LIBRARY)
        self.run_effect((Draw(1),));self.choose('4');self.top()
        snapshot=self.kernel.snapshot();snapshot['resolution_cast']['miracle_reduction']=-1
        with self.assertRaises(RulesViolation):RulesKernel.restore(snapshot,self.programs)

    def test_room_unknown_face_is_rejected_without_mutation(self):
        self.game();ref=self.card('funeral-room-awakening-hall');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('both','A',ref,face='both')
        self.assertEqual(before,self.kernel.snapshot())

    def test_read_ahead_doubled_lore_only_exact_chapter_triggers(self):
        doubler=CardProgram('lore-doubler','Doubler',('Enchantment',),counter_replacements=(CounterReplacement('double',Selector(Zone.BATTLEFIELD,relation='controlled'),multiplier=2),))
        self.game((doubler,));self.add('lore-doubler');ref=self.card('the-cruelty-of-gix')
        self.run_effect((Move('target',Zone.BATTLEFIELD),),targets=(ref,));self.choose('1');self.drain()
        self.assertEqual(2,dict(self.current(ref).counters)['lore'])
        self.assertEqual(37,self.state.life('A'))

    def test_read_ahead_entry_turn_proliferation_does_not_backfill(self):
        self.game();ref=self.card('the-cruelty-of-gix')
        self.run_effect((Move('target',Zone.BATTLEFIELD),),targets=(ref,));self.choose('1');self.drain()
        ref=self.current(ref).ref;life=self.state.life('A')
        self.chapters(ref,2);self.drain()
        self.assertEqual(life,self.state.life('A'))

    def test_ghostly_uses_current_room_type(self):
        blank=CardProgram('room-type-change','Room type change',('Enchantment',),continuous=(ContinuousProgram('creature-room',Selector(Zone.BATTLEFIELD,subtypes=('Room',)),(SetCardTypes(('Creature',),('Human',)),SetPT(5,5))),))
        self.game((blank,));room=self.enter(self.card('funeral-room-awakening-hall'));self.add('room-type-change')
        self.enter(self.card('ghostly-dancers'))
        self.assertEqual((),self.state.get(room).unlocked)

    def test_losing_abilities_removes_funeral_trigger(self):
        blank=CardProgram('room-blank','Room blank',('Enchantment',),continuous=(ContinuousProgram('blank-room',Selector(Zone.BATTLEFIELD,subtypes=('Room',)),(LoseAbilities(),)),))
        self.game((blank,));room=self.enter(self.card('funeral-room-awakening-hall'));self.unlocked(room)
        self.add('room-blank');body=self.add();self.move(body,Zone.GRAVEYARD);self.drain()
        self.assertEqual(40,self.state.life('A'))

    def test_room_scanning_and_indexed_collectors_agree(self):
        from edh_gauntlet.rules_trigger_benchmark import ScanningRulesKernel
        self.game();self.card('entity-tracker',zone=Zone.BATTLEFIELD);room=self.enter(self.card('funeral-room-awakening-hall'))
        state=self.kernel.snapshot()
        self.run_effect((UnlockRoom('target','both'),),targets=(room,));self.drain()
        expected=self.kernel.snapshot()
        self.kernel=ScanningRulesKernel.restore(state,self.programs);self.state=self.kernel.state
        self.run_effect((UnlockRoom('target','both'),),targets=(room,));self.drain()
        self.assertEqual(expected,self.kernel.snapshot())

    def test_counted_modifier_matches_exhaustive_layers(self):
        self.game();program=self.cards['urza-s-saga'].abilities[1].effects[0].changes[0].ability.effects[0].token
        self.run_effect((CreateTokens(program,2),));self.drain()
        self.assertEqual(evaluate(self.state.objects(),self.kernel.definitions),evaluate_exhaustive(self.state.objects(),self.kernel.definitions))

    def test_new_counter_state_rejects_negative_ordinal(self):
        self.game();ref=self.card('victor-valgavoth-s-seneschal',zone=Zone.BATTLEFIELD)
        self.run_effect(self.cards['victor-valgavoth-s-seneschal'].abilities[0].effects,source=ref);self.drain()
        state=self.kernel.snapshot();key=next(iter(state['resolution_counts']));state['resolution_counts'][key]=0
        with self.assertRaises(RulesViolation):RulesKernel.restore(state,self.programs)

    def test_urza_third_chapter_searches_then_sacrifices(self):
        self.game();artifact=self.add('catalog:sol-ring',zone=Zone.LIBRARY);ref=self.enter(self.card('urza-s-saga'))
        self.chapters(ref,1);self.drain();self.chapters(ref,1);self.top()
        self.assertEqual('library_search',self.kernel.pending_choice.kind)
        q=self.kernel.pending_choice
        self.answer([next(i for i,o in enumerate(q.options) if o.ref==artifact)])
        self.drain();self.assertEqual(Zone.BATTLEFIELD,self.current(artifact).zone)
        self.assertEqual(Zone.GRAVEYARD,self.current(ref).zone)
        self.assertTrue(any(e['kind']=='library_shuffled' for e in self.kernel.semantic_events))

    def test_urza_uses_land_play_and_ordinary_chapter_stack(self):
        self.game();ref=self.card('urza-s-saga')
        self.kernel.turn_schedule={'land_plays':0,'advance':False,'cleanup_priority':False}
        self.kernel.play_land('saga-land','A',ref,revision=self.kernel.revision)
        self.assertEqual(1,self.kernel.turn_schedule['land_plays'])
        self.assertEqual(Zone.BATTLEFIELD,self.current(ref).zone)
        self.assertEqual(1,len(self.kernel.stack));self.assertTrue(self.kernel.stack[0]['values']['saga_chapter'])
        self.restore();self.top()
        self.assertTrue(self.ability(self.current(ref).ref,'saga-mana'))

    def test_actor_adapter_unlocks_without_activated_ability(self):
        self.game();ref=self.enter(self.card('funeral-room-awakening-hall'));self.kernel.open_window_for_scenario('A')
        paid=self.payment('CCB')
        RulesActorAdapter(self.kernel)._execute('A',{'kind':'unlock_room','action_id':'actor-unlock','source':ref.to_json(),'door':'left','payment':paid.to_json(),'revision':self.kernel.revision})
        self.assertEqual(('left',),self.state.get(ref).unlocked)
        self.assertFalse(any(f.get('activated_program') for f in self.kernel.stack))


if __name__=='__main__':unittest.main()
