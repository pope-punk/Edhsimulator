"""Hosted conformance for the second seven-card completion pass."""
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
from edh_gauntlet.rules_actor import project_actor
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed,digest,source_facts
from edh_gauntlet.rules_characteristics import evaluate,evaluate_exhaustive
from edh_gauntlet.rules_combat import uid
from edh_gauntlet.catalog import load_catalog

CARDS=('aminatou-the-fateshifter','domri-anarch-of-bolas','minsc-boo-timeless-heroes',
       'nissa-steward-of-elements','sorin-vengeful-bloodlord','innkeeper-s-talent','leyline-of-hope')


class WalkersClassOpeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        reviewed=load_reviewed(cls.root)
        cls.rows={key:reviewed[key]['review'] for key in CARDS}
        cls.cards={key:reviewed[key]['program'] for key in CARDS}
        cls.base=tuple(r['program'] for r in reviewed.values())
        cls.prefix='catalog:'

    def game(self,extra=(),players=('A','B','C','D'),started=True):
        body=CardProgram('wc-body','Body',('Creature',),power=2,toughness=3,mana_value=2,
            cast=CastSpec(CostSpec(ManaCost(2))))
        hamster=replace(body,definition_id='wc-hamster',name='Hamster',subtypes=('Hamster',),power=4,toughness=5,keywords=('haste',))
        zero=replace(body,definition_id='wc-zero',name='Zero',power=1,toughness=1,mana_value=0,cast=CastSpec(CostSpec()))
        bolt=CardProgram('wc-bolt','Bolt',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD,any_types=('Creature','Planeswalker')),players='all'),
            spell_effects=(Damage('target',1),))
        counter=CardProgram('wc-counter','Counter',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.STACK)),spell_effects=(Counter('target'),GainLife(2)))
        self.programs=self.base+(body,hamster,zero,bolt,counter)+extra
        self.state=RulesState(players,seed=91);self.kernel=RulesKernel(self.state,self.programs);self.serial=0
        self.anchor=self.add('catalog:forest')
        for actor in players:
            for _ in range(12):self.add('wc-body',actor,Zone.LIBRARY)
        if started:self.state.start_turn('A');self.kernel.open_window_for_scenario('A')

    def add(self,definition='wc-body',actor='A',zone=Zone.BATTLEFIELD,**kw):
        self.serial+=1
        return self.state.add_card('wc-'+str(self.serial),definition,actor,zone,**kw)

    def card(self,key,actor='A',zone=Zone.BATTLEFIELD,loyalty=None,**kw):
        ref=self.add(self.cards[key].definition_id,actor,zone,**kw)
        if zone==Zone.BATTLEFIELD and 'Planeswalker' in self.cards[key].types:
            amount=loyalty if loyalty is not None else 4 if key=='sorin-vengeful-bloodlord' else 3
            self.state.add_counters(ref,'loyalty',amount)
        return ref

    def current(self,ref):return self.state.get(self.state.current(ref.card_id))
    def loyalty(self,ref):return dict(self.state.get(ref).counters).get('loyalty',0)
    def events(self,kind):return [e for e in self.kernel.semantic_events if e['kind']==kind]
    def payment(self,symbols='',actor='A'):
        self.state.add_mana(actor,symbols)
        return Payment(tuple(sorted(Counts(symbols).items())))
    def act(self,ref,ability,targets=(),x=0,actor='A',symbols=''):
        if self.kernel.priority is None and not self.kernel.stack:self.kernel.open_window_for_scenario(actor)
        payment=self.payment(symbols,actor)
        quote=self.kernel.quote_activation('wc-act-'+str(len(self.kernel.action_receipts)),actor,ref,ability,targets,x_value=x)
        return self.kernel.commit_action(quote,payment)
    def cast(self,ref,targets=(),actor='A',symbols='',x=0):
        payment=self.payment(symbols,actor)
        return self.kernel.commit_action(self.kernel.quote_cast('wc-cast-'+str(len(self.kernel.action_receipts)),actor,ref,targets,x_value=x),payment)
    def answer(self,indexes):
        q=self.kernel.pending_choice
        return self.kernel.answer(q.request_id,q.actor,indexes)
    def choose(self,key):
        q=self.kernel.pending_choice
        return self.answer([next(i for i,o in enumerate(q.options) if o.key==key)])
    def top(self):
        fid=self.kernel.stack[-1]['id']
        for _ in range(40):
            if self.kernel.pending_choice or self.kernel._payment_waiting() or not any(f['id']==fid for f in self.kernel.stack):return
            self.kernel.pass_priority(self.kernel.priority)
        self.fail('Top stack object did not start resolution')
    def drain(self):
        for _ in range(250):
            if self.kernel.pending_choice:self.answer(list(range(self.kernel.pending_choice.minimum)))
            elif self.kernel._payment_waiting():
                w=self.kernel.mana_payment
                self.kernel.pay_resolution_mana('decline-'+str(len(self.kernel.action_receipts)),w['actor'],w['id'],None,revision=self.kernel.revision)
            elif self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
            else:return
        self.fail('Rules did not reach a stable boundary')
    def restore(self):
        before=self.kernel.snapshot();self.kernel=RulesKernel.restore(before,self.programs);self.state=self.kernel.state
        self.assertEqual(before,self.kernel.snapshot())
    def move(self,ref,destination):
        frame={'source':self.state.get(self.anchor).to_json(),'controller':'A','bindings':{},'values':{}}
        result=self.kernel._move((ref,),destination,frame,'fixture-move-'+str(self.state.sequence))
        self.kernel.advance();return result
    def level(self,ref,level):
        for n in range(2,level+1):self.state.set_class_level(ref,n)
    def combat(self,attackers):
        self.state.start_turn('A');self.kernel.active='A';self.kernel.phase='declare_attackers';self.kernel.priority=None
        self.kernel.turn_schedule={'land_plays':0,'advance':False,'cleanup_priority':False}
        return self.kernel.declare_attackers('A',attackers,revision=self.kernel.revision)
    def finish_combat(self,blocks=None):
        for _ in range(100):
            if self.kernel.phase=='end_combat':return
            if self.kernel.priority:self.kernel.pass_priority(self.kernel.priority)
            elif self.kernel.phase=='declare_blockers':
                actor=self.kernel._defenders()[self.kernel.combat['defender_index']]
                rows=self.kernel._block_specification(actor)['attackers']
                self.kernel.declare_blockers(actor,{r['uid']:[] for r in rows} if blocks is None else blocks,revision=self.kernel.revision)
            else:self.kernel.advance()
        self.fail('Combat did not finish')

    def test_complete_source_binding_and_serialization(self):
        catalog={c.card_id:c for c in load_catalog(self.root/'data/catalog/cards.json')}
        self.assertEqual(set(CARDS),set(self.cards))
        for key,p in self.cards.items():
            with self.subTest(card=key):
                self.assertEqual(self.rows[key]['source_facts_sha256'],digest(source_facts(catalog[key])))
                self.assertEqual(encode(p),self.rows[key]['program'])
                self.assertEqual(p,decode(encode(p)))

    def test_commander_permissions_are_printed_program_values(self):
        for key in ('aminatou-the-fateshifter','minsc-boo-timeless-heroes'):
            self.assertTrue(self.cards[key].can_be_commander)
        self.assertNotIsInstance(self.cards['domri-anarch-of-bolas'],CommanderProgram)

    def test_fixed_loyalty_entry(self):
        for key,n in (('aminatou-the-fateshifter',3),('domri-anarch-of-bolas',3),('sorin-vengeful-bloodlord',4)):
            with self.subTest(card=key):
                self.game();ref=self.card(key,zone=Zone.HAND);self.kernel.enter(ref);self.drain()
                self.assertEqual(n,self.loyalty(self.current(ref).ref))

    def test_nissa_x_cast_enters_with_x_loyalty(self):
        self.game();ref=self.card('nissa-steward-of-elements',zone=Zone.HAND)
        self.cast(ref,symbols='CCCGU',x=3);self.drain()
        self.assertEqual(3,self.loyalty(self.current(ref).ref));self.assertEqual(2,self.kernel.effective(self.current(ref).ref).mana_value)

    def test_nissa_zero_cast_dies_before_priority(self):
        self.game();ref=self.card('nissa-steward-of-elements',zone=Zone.HAND)
        self.cast(ref,symbols='GU');self.drain();self.assertEqual(Zone.GRAVEYARD,self.current(ref).zone)

    def test_loyalty_is_paid_before_resolution(self):
        self.game();ref=self.card('aminatou-the-fateshifter');hands=len(self.state.zone('A',Zone.HAND))
        self.act(ref,'draw-and-top');self.assertEqual(4,self.loyalty(ref));self.assertEqual(hands,len(self.state.zone('A',Zone.HAND)))
        self.assertTrue(self.kernel.stack)

    def test_loyalty_once_per_turn_survives_control_change(self):
        self.game();ref=self.card('nissa-steward-of-elements');self.act(ref,'scry-two');self.drain()
        self.state.change_control(ref,'B');self.kernel.open_window_for_scenario('B')
        with self.assertRaisesRegex(RulesViolation,'already activated'):self.kernel.quote_activation('again','B',ref,'scry-two')

    def test_loyalty_reset_after_blink(self):
        self.game();ref=self.card('nissa-steward-of-elements');self.act(ref,'scry-two');self.drain()
        self.move(ref,Zone.EXILE);self.kernel.enter(self.current(ref).ref);self.drain()
        # Noncast Nissa enters with zero and leaves; a fixed-loyalty copy provides a fresh activation.
        self.assertEqual(Zone.GRAVEYARD,self.current(ref).zone)
        other=self.card('domri-anarch-of-bolas');self.act(other,'mana-and-counter-immunity');self.drain()
        self.move(other,Zone.EXILE);self.kernel.enter(self.current(other).ref);self.drain()
        self.kernel.open_window_for_scenario('A');self.act(self.current(other).ref,'mana-and-counter-immunity')

    def test_loyalty_resets_next_turn(self):
        self.game();ref=self.card('nissa-steward-of-elements');self.act(ref,'scry-two');self.drain()
        self.state.start_turn('A');self.kernel.open_window_for_scenario('A');self.act(ref,'scry-two')
        self.assertEqual(7,self.loyalty(ref))

    def test_zero_loyalty_symbol_also_uses_the_turn(self):
        self.game();ref=self.card('nissa-steward-of-elements');self.act(ref,'look-and-put');self.drain()
        self.kernel.open_window_for_scenario('A')
        with self.assertRaisesRegex(RulesViolation,'already activated'):self.act(ref,'scry-two')

    def test_loyalty_rejects_insufficient_negative_payment_atomically(self):
        self.game();ref=self.card('aminatou-the-fateshifter');snap=self.kernel.snapshot()
        with self.assertRaisesRegex(RulesViolation,'Insufficient loyalty'):self.kernel.quote_activation('bad','A',ref,'rotate-control')
        self.assertEqual(snap,self.kernel.snapshot())

    def test_loyalty_rejects_other_turn_and_nonmain_window(self):
        self.game();ref=self.card('nissa-steward-of-elements')
        for active,phase in (('B','precombat_main'),('A','upkeep')):
            self.kernel.open_window_for_scenario(active,phase,priority_actor='A')
            with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',ref,'scry-two')

    def test_loyalty_rejects_stack_and_forged_cost(self):
        self.game();ref=self.card('nissa-steward-of-elements')
        q=self.kernel.quote_activation('activate','A',ref,'scry-two');snap=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(replace(q,cost=replace(q.cost,loyalty=10)),Payment())
        self.assertEqual(snap,self.kernel.snapshot());self.kernel.commit_action(q,Payment())
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('again','A',ref,'look-and-put')

    def test_loyalty_extra_payment_is_rejected_before_mutation(self):
        self.game();ref=self.card('nissa-steward-of-elements');q=self.kernel.quote_activation('activate','A',ref,'scry-two')
        snap=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(q,Payment(cost_order=('mana',)))
        self.assertEqual(snap,self.kernel.snapshot())

    def test_positive_loyalty_uses_putting_player_replacement(self):
        self.game();talent=self.card('innkeeper-s-talent');self.level(talent,3)
        ref=self.card('nissa-steward-of-elements');self.act(ref,'scry-two');self.assertEqual(7,self.loyalty(ref))

    def test_negative_loyalty_is_not_doubled(self):
        self.game();talent=self.card('innkeeper-s-talent');self.level(talent,3)
        ref=self.card('aminatou-the-fateshifter');target=self.add()
        self.act(ref,'blink-owned',(target,));self.assertEqual(2,self.loyalty(ref))

    def test_loyalty_checkpoint_retains_usage(self):
        self.game();ref=self.card('nissa-steward-of-elements');self.act(ref,'scry-two');self.restore();self.drain()
        self.assertTrue(self.kernel.loyalty_used(ref));self.assertEqual(5,self.loyalty(ref))

    def test_loyalty_mana_production_still_uses_stack(self):
        self.game();ref=self.card('domri-anarch-of-bolas');self.act(ref,'mana-and-counter-immunity')
        self.assertEqual((),self.state.mana_pool('A'));self.assertTrue(self.kernel.stack);self.top();self.choose('0')
        self.assertEqual((('R',1),),self.state.mana_pool('A'))

    def test_loyalty_compiler_rejects_mana_flag_and_extra_cost(self):
        p=self.cards['domri-anarch-of-bolas'];a=p.activated[0]
        for bad in (replace(a,mana_ability=True),replace(a,timing='instant'),replace(a,cost=replace(a.cost,life=1))):
            with self.assertRaises(RulesViolation):validate(replace(p,activated=(bad,)))

    def test_aminatou_draw_and_top_is_one_resolution(self):
        self.game();ref=self.card('aminatou-the-fateshifter');hand=self.add(zone=Zone.HAND)
        self.act(ref,'draw-and-top');self.top();self.assertEqual('selection',self.kernel.pending_choice.kind)
        self.assertEqual(2,len(self.state.zone('A',Zone.HAND)));self.restore()
        q=self.kernel.pending_choice;self.answer([next(i for i,o in enumerate(q.options) if o.ref==hand)])
        self.assertEqual(hand.card_id,self.state.zone('A',Zone.LIBRARY)[-1].ref.card_id)

    def test_aminatou_blinks_owned_opponent_controlled_permanent(self):
        self.game();ref=self.card('aminatou-the-fateshifter');target=self.add(controller='B')
        self.act(ref,'blink-owned',(target,));self.drain()
        self.assertEqual('A',self.current(target).controller);self.assertEqual(target.incarnation+2,self.current(target).ref.incarnation)

    def test_aminatou_cannot_blink_self_or_an_opponents_card(self):
        self.game();ref=self.card('aminatou-the-fateshifter');other=self.add(actor='B',controller='A')
        for target in (ref,other):
            with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',ref,'blink-owned',(target,))

    def test_aminatou_blinked_token_does_not_return(self):
        self.game();ref=self.card('aminatou-the-fateshifter');target=self.add(token=True)
        self.act(ref,'blink-owned',(target,));self.drain();self.assertFalse(any(o.ref.card_id==target.card_id for o in self.state.objects()))

    def test_aminatou_rotation_left_and_right_are_simultaneous(self):
        for direction in ('left','right'):
            with self.subTest(direction=direction):
                self.game();ref=self.card('aminatou-the-fateshifter',loyalty=7);bodies={p:self.add(actor=p) for p in self.state.players}
                self.act(ref,'rotate-control');self.top();self.restore();self.choose(direction)
                offset=1 if direction=='left' else -1
                for i,actor in enumerate(self.state.players):self.assertEqual(actor,self.state.get(bodies[self.state.players[(i+offset)%4]]).controller)
                self.assertEqual('A',self.state.get(ref).controller);self.assertEqual('A',self.state.get(self.anchor).controller)

    def test_aminatou_rotation_survives_source_departure(self):
        self.game();ref=self.card('aminatou-the-fateshifter',loyalty=6);other=self.add(actor='B')
        self.act(ref,'rotate-control');self.assertEqual(Zone.GRAVEYARD,self.current(ref).zone)
        self.top();self.choose('left');self.assertEqual('A',self.state.get(other).controller)

    def test_domri_fight_uses_two_independent_target_groups(self):
        self.game();ref=self.card('domri-anarch-of-bolas');own=self.add();other=self.add(actor='B')
        self.act(ref,'fight',(own,other));self.drain()
        self.assertEqual(2,self.state.get(own).damage_marked);self.assertEqual(Zone.GRAVEYARD,self.current(other).zone)

    def test_domri_lethal_cost_removes_anthem_before_fight(self):
        self.game();ref=self.card('domri-anarch-of-bolas',loyalty=2);own=self.add();other=self.add(actor='B')
        self.act(ref,'fight',(own,other));self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.current(ref).zone);self.assertEqual(2,self.state.get(other).damage_marked)

    def test_domri_fight_does_nothing_if_either_target_is_illegal(self):
        self.game();ref=self.card('domri-anarch-of-bolas');own=self.add();other=self.add(actor='B')
        self.act(ref,'fight',(own,other));self.move(other,Zone.HAND);self.drain()
        self.assertEqual(0,self.state.get(own).damage_marked)

    def test_domri_immunity_does_not_require_spending_his_mana(self):
        self.game();ref=self.card('domri-anarch-of-bolas');self.act(ref,'mana-and-counter-immunity');self.drain()
        spell=self.add('wc-zero',zone=Zone.HAND);self.kernel.open_window_for_scenario('A');self.cast(spell)
        self.kernel.pass_priority('A');answer=self.add('wc-counter','B',Zone.HAND);self.cast(answer,(self.current(spell).ref,),actor='B')
        self.drain();self.assertEqual(Zone.BATTLEFIELD,self.current(spell).zone);self.assertEqual(42,self.state.life('B'))

    def test_domri_immunity_expires_with_turn_permissions(self):
        self.game();ref=self.card('domri-anarch-of-bolas');self.act(ref,'mana-and-counter-immunity');self.drain()
        self.kernel.player_effects=[];spell=self.add('wc-zero',zone=Zone.HAND);self.kernel.open_window_for_scenario('A');self.cast(spell)
        self.assertFalse(self.kernel._spell_uncounterable(self.current(spell).ref))

    def test_minsc_entry_offers_legendary_boo(self):
        self.game();ref=self.card('minsc-boo-timeless-heroes',zone=Zone.HAND);self.kernel.enter(ref);self.drain()
        boos=[o for o in self.state.objects(Zone.BATTLEFIELD) if o.effective_definition=='token:boo']
        self.assertEqual(1,len(boos));v=self.kernel.effective(boos[0].ref)
        self.assertEqual((1,1),(v.power,v.toughness));self.assertTrue({'trample','haste'}<=v.keywords);self.assertIn('Legendary',v.supertypes)

    def test_minsc_upkeep_offer_can_be_declined(self):
        self.game();ref=self.card('minsc-boo-timeless-heroes');self.kernel.begin_step('A','upkeep');self.top();self.choose('no')
        self.assertFalse([o for o in self.state.objects() if o.token])

    def test_minsc_plus_accepts_either_keyword_and_zero_targets(self):
        for keywords in (('trample',),('haste',)):
            body=CardProgram('kw','Keyword body',('Creature',),power=2,toughness=2,keywords=keywords)
            self.game((body,));ref=self.card('minsc-boo-timeless-heroes');target=self.add('kw','B')
            self.act(ref,'grow-hasty-or-trampling',(target,));self.drain()
            self.assertEqual(3,dict(self.state.get(target).counters)['+1/+1'])
        self.game();ref=self.card('minsc-boo-timeless-heroes');self.act(ref,'grow-hasty-or-trampling');self.drain()
        self.assertEqual(4,self.loyalty(ref))

    def test_minsc_plus_rejects_creature_without_either_keyword(self):
        self.game();ref=self.card('minsc-boo-timeless-heroes');body=self.add()
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',ref,'grow-hasty-or-trampling',(body,))

    def test_minsc_sacrifice_happens_at_resolution_before_target_choice(self):
        self.game();ref=self.card('minsc-boo-timeless-heroes');hamster=self.add('wc-hamster')
        self.act(ref,'sacrifice-and-fling');self.assertEqual(Zone.BATTLEFIELD,self.state.get(hamster).zone)
        self.top();self.assertEqual(Zone.GRAVEYARD,self.current(hamster).zone)
        self.assertEqual('trigger_targets',self.kernel.pending_choice.kind);self.restore()

    def test_minsc_hamster_damage_and_draw_use_captured_power(self):
        self.game();ref=self.card('minsc-boo-timeless-heroes');hamster=self.add('wc-hamster')
        self.state.add_counters(hamster,'+1/+1',2);self.act(ref,'sacrifice-and-fling');self.top()
        self.choose('player:B');self.drain()
        self.assertEqual(34,self.state.life('B'));self.assertEqual(6,len(self.state.zone('A',Zone.HAND)))

    def test_minsc_nonhamster_deals_damage_without_draw(self):
        self.game();ref=self.card('minsc-boo-timeless-heroes');self.add()
        self.act(ref,'sacrifice-and-fling');self.top();self.choose('player:B');self.drain()
        self.assertEqual(38,self.state.life('B'));self.assertEqual(0,len(self.state.zone('A',Zone.HAND)))

    def test_minsc_illegal_reflexive_target_prevents_draw(self):
        self.game();ref=self.card('minsc-boo-timeless-heroes');self.add('wc-hamster');target=self.add(actor='B')
        self.act(ref,'sacrifice-and-fling');self.top()
        q=self.kernel.pending_choice;self.answer([next(i for i,o in enumerate(q.options) if o.ref==target)])
        self.move(target,Zone.HAND);self.drain();self.assertEqual(0,len(self.state.zone('A',Zone.HAND)))

    def test_minsc_no_creature_creates_no_reflexive_trigger(self):
        self.game();ref=self.card('minsc-boo-timeless-heroes');self.act(ref,'sacrifice-and-fling');self.drain()
        self.assertFalse([e for e in self.events('trigger_created') if e['ability'].startswith('reflexive:')])

    def test_nissa_top_offer_is_private_and_decline_keeps_card(self):
        self.game();ref=self.card('nissa-steward-of-elements');top=self.state.zone('A',Zone.LIBRARY)[-1].ref
        self.act(ref,'look-and-put');self.top()
        self.assertIn('library_observation',project_actor(self.kernel,'A'));self.assertNotIn('library_observation',project_actor(self.kernel,'B'))
        self.restore();self.choose('leave');self.assertEqual(top,self.state.zone('A',Zone.LIBRARY)[-1].ref)

    def test_nissa_land_ignores_mana_value_bound(self):
        land=CardProgram('odd-land','Unusual land',('Land',),mana_value=20)
        self.game((land,));ref=self.card('nissa-steward-of-elements',loyalty=1);top=self.add('odd-land',zone=Zone.LIBRARY)
        self.act(ref,'look-and-put');self.top();self.choose('put');self.assertEqual(Zone.BATTLEFIELD,self.current(top).zone)

    def test_nissa_creature_uses_current_loyalty_when_resolving(self):
        self.game();ref=self.card('nissa-steward-of-elements',loyalty=1);self.act(ref,'look-and-put')
        self.state.add_counters(ref,'loyalty',1);self.top();self.choose('put')
        self.assertTrue(self.events('zone_changed'))

    def test_nissa_uses_departed_sources_last_known_loyalty(self):
        self.game();ref=self.card('nissa-steward-of-elements',loyalty=2);self.act(ref,'look-and-put')
        self.move(ref,Zone.GRAVEYARD);self.top();self.choose('put');self.assertEqual(Zone.GRAVEYARD,self.current(ref).zone)

    def test_nissa_ineligible_top_cannot_be_forged_into_play(self):
        self.game();ref=self.card('nissa-steward-of-elements',loyalty=1);top=self.state.zone('A',Zone.LIBRARY)[-1].ref
        self.act(ref,'look-and-put');self.top();self.assertEqual(['leave'],[o.key for o in self.kernel.pending_choice.options])
        snap=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.answer([1])
        self.assertEqual(snap,self.kernel.snapshot());self.choose('leave');self.assertEqual(top,self.state.zone('A',Zone.LIBRARY)[-1].ref)

    def test_nissa_animate_retains_lands_and_counters(self):
        self.game();ref=self.card('nissa-steward-of-elements',loyalty=6);land=self.add('catalog:forest')
        self.state.set_tapped_batch((land,),True);self.state.add_counters(land,'+1/+1',2)
        self.act(ref,'animate-lands',(land,));self.drain();view=self.kernel.effective(land)
        self.assertEqual((7,7),(view.power,view.toughness));self.assertFalse(self.state.get(land).tapped)
        self.assertTrue({'Land','Creature'}<=view.types);self.assertTrue({'Forest','Elemental'}<=view.subtypes);self.assertTrue({'flying','haste'}<=view.keywords)

    def test_nissa_animate_can_target_zero_or_two_lands(self):
        for count in (0,2):
            self.game();ref=self.card('nissa-steward-of-elements',loyalty=7);lands=tuple(self.add('catalog:forest') for _ in range(count))
            self.act(ref,'animate-lands',lands);self.drain();self.assertEqual(1,self.loyalty(ref))
            for land in lands:self.assertEqual(5,self.kernel.effective(land).power)

    def test_sorin_turn_lifelink_covers_walkers_and_creatures(self):
        self.game();ref=self.card('sorin-vengeful-bloodlord');body=self.add();walker=self.card('nissa-steward-of-elements')
        for obj in (ref,body,walker):self.assertIn('lifelink',self.kernel.effective(obj).keywords)
        self.kernel.open_window_for_scenario('B')
        for obj in (ref,body,walker):self.assertNotIn('lifelink',self.kernel.effective(obj).keywords)

    def test_sorin_plus_damages_player_and_gains_life(self):
        self.game();ref=self.card('sorin-vengeful-bloodlord');self.act(ref,'drain-player-or-walker',(PlayerRef('B'),));self.drain()
        self.assertEqual((41,39),(self.state.life('A'),self.state.life('B')))

    def test_sorin_plus_damages_planeswalker_loyalty(self):
        self.game();ref=self.card('sorin-vengeful-bloodlord');target=self.card('nissa-steward-of-elements','B')
        self.act(ref,'drain-player-or-walker',(target,));self.drain();self.assertEqual(2,self.loyalty(target));self.assertEqual(41,self.state.life('A'))

    def test_sorin_plus_rejects_creature_target(self):
        self.game();ref=self.card('sorin-vengeful-bloodlord');target=self.add(actor='B')
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',ref,'drain-player-or-walker',(target,))

    def test_sorin_departed_source_keeps_lifelink_information(self):
        self.game();ref=self.card('sorin-vengeful-bloodlord');self.act(ref,'drain-player-or-walker',(PlayerRef('B'),))
        self.move(ref,Zone.GRAVEYARD);self.drain();self.assertEqual(41,self.state.life('A'))

    def test_sorin_x_exact_value_and_zero_cost(self):
        for x,definition in ((0,'wc-zero'),(2,'wc-body')):
            self.game();ref=self.card('sorin-vengeful-bloodlord');target=self.add(definition,zone=Zone.GRAVEYARD)
            self.act(ref,'return-vampire',(target,),x=x);self.drain()
            self.assertEqual(4-x,self.loyalty(ref));self.assertIn('Vampire',self.kernel.effective(self.current(target).ref).subtypes)

    def test_sorin_wrong_x_and_opponents_graveyard_are_rejected(self):
        self.game();ref=self.card('sorin-vengeful-bloodlord');target=self.add(zone=Zone.GRAVEYARD);other=self.add(actor='B',zone=Zone.GRAVEYARD)
        for obj,x in ((target,1),(other,2)):
            with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',ref,'return-vampire',(obj,),x_value=x)

    def test_sorin_vampire_is_visible_to_entry_replacements(self):
        watcher=CardProgram('vampire-watch','Vampire watcher',('Enchantment',),
            entry_counters=(EntryCounters('vampire-entry','+1/+1',2,Selector(Zone.BATTLEFIELD,types=('Creature',),subtypes=('Vampire',))),))
        self.game((watcher,));self.add('vampire-watch');ref=self.card('sorin-vengeful-bloodlord');target=self.add(zone=Zone.GRAVEYARD)
        self.act(ref,'return-vampire',(target,),x=2);self.drain()
        self.assertEqual(2,dict(self.current(target).counters)['+1/+1']);self.restore()

    def test_sorin_added_type_is_not_copied_or_retained_after_blink(self):
        self.game();ref=self.card('sorin-vengeful-bloodlord');target=self.add(zone=Zone.GRAVEYARD)
        self.act(ref,'return-vampire',(target,),x=2);self.drain();arrived=self.current(target).ref
        copy=self.add('wc-body');self.state.apply_copy((copy,),self.current(target).effective_definition)
        self.assertNotIn('Vampire',self.kernel.effective(copy).subtypes)
        self.move(arrived,Zone.EXILE);self.kernel.enter(self.current(target).ref);self.drain()
        self.assertNotIn('Vampire',self.kernel.effective(self.current(target).ref).subtypes)

    def test_class_activations_require_exact_preceding_level(self):
        self.game();ref=self.card('innkeeper-s-talent')
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('skip','A',ref,'level-3')
        self.act(ref,'level-2',symbols='G');self.assertEqual(1,self.state.get(ref).class_level);self.drain()
        self.assertEqual(2,self.state.get(ref).class_level)
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('repeat','A',ref,'level-2')
        self.act(ref,'level-3',symbols='CCCG');self.drain();self.assertEqual(3,self.state.get(ref).class_level);self.assertEqual((),self.state.get(ref).counters)

    def test_class_levels_are_sorcery_activations(self):
        self.game();ref=self.card('innkeeper-s-talent');self.kernel.open_window_for_scenario('A','upkeep')
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',ref,'level-2')

    def test_class_level_survives_copy_and_type_loss_but_not_blink(self):
        self.game();ref=self.card('innkeeper-s-talent');self.level(ref,3)
        self.state.apply_copy((ref,),'wc-body');self.assertEqual(3,self.state.get(ref).class_level)
        self.restore();self.move(ref,Zone.EXILE);self.kernel.enter(self.current(ref).ref);self.drain()
        self.assertEqual(1,self.current(ref).class_level)

    def test_class_counter_replacement_uses_actor_not_recipient(self):
        self.game();ref=self.card('innkeeper-s-talent');self.level(ref,3);opponent=self.add(actor='B')
        self.kernel.execute_for_scenario(opponent,'A',(AddCounters('source','charge',2),))
        self.assertEqual(4,dict(self.state.get(opponent).counters)['charge'])
        self.kernel.execute_for_scenario(ref,'B',(AddCounters('source','charge',2),))
        self.assertEqual(2,dict(self.state.get(ref).counters)['charge'])

    def test_class_doubles_player_counters_and_entry_counters(self):
        self.game();talent=self.card('innkeeper-s-talent');self.level(talent,3)
        self.kernel.execute_for_scenario(talent,'A',(AddCounters('opponents','energy',2),))
        self.assertEqual(4,dict(self.state.player_counters('B'))['energy'])
        source=self.card('domri-anarch-of-bolas',zone=Zone.HAND);self.kernel.enter(source);self.drain()
        self.assertEqual(6,self.loyalty(self.current(source).ref))

    def test_class_level_one_and_two_do_not_double_counters(self):
        for level in (1,2):
            self.game();talent=self.card('innkeeper-s-talent');self.level(talent,level)
            self.kernel.execute_for_scenario(talent,'A',(AddCounters('source','charge',1),))
            self.assertEqual(1,dict(self.state.get(talent).counters)['charge'])

    def test_class_combat_counter_trigger_remains_at_level_three(self):
        self.game();talent=self.card('innkeeper-s-talent');self.level(talent,3);body=self.add()
        self.kernel._begin_phase('begin_combat');self.kernel.advance();self.drain()
        self.assertEqual(2,dict(self.state.get(body).counters)['+1/+1'])

    def test_ward_requires_level_two_and_any_counter_kind(self):
        self.game();talent=self.card('innkeeper-s-talent');self.state.add_counters(self.anchor,'charge',1)
        self.assertEqual((),self.kernel.effective(self.anchor).wards);self.level(talent,2)
        self.assertEqual(1,len(self.kernel.effective(self.anchor).wards));self.assertEqual((),self.kernel.effective(talent).wards)

    def ward_spell(self):
        self.game();talent=self.card('innkeeper-s-talent');self.level(talent,2);body=self.add();self.state.add_counters(body,'charge',1)
        bolt=self.add('wc-bolt','B',Zone.HAND);self.kernel.open_window_for_scenario('A',priority_actor='B');self.cast(bolt,(body,),actor='B')
        return talent,body,bolt

    def test_ward_decline_counters_the_bound_spell(self):
        _,body,bolt=self.ward_spell();self.drain()
        self.assertEqual(0,self.state.get(body).damage_marked);self.assertEqual(Zone.GRAVEYARD,self.current(bolt).zone)

    def test_ward_payment_allows_spell_and_checkpoint(self):
        _,body,bolt=self.ward_spell();self.top();self.assertTrue(self.kernel._payment_waiting());self.restore()
        w=self.kernel.mana_payment
        self.kernel.pay_resolution_mana('pay','B',w['id'],self.payment('C','B'),revision=self.kernel.revision);self.drain()
        self.assertEqual(1,self.state.get(body).damage_marked)

    def test_ward_trigger_survives_grant_source_departure(self):
        talent,body,bolt=self.ward_spell();self.move(talent,Zone.GRAVEYARD);self.drain()
        self.assertEqual(0,self.state.get(body).damage_marked)

    def test_ward_does_not_trigger_for_controller_targeting_own_permanent(self):
        self.game();talent=self.card('innkeeper-s-talent');self.level(talent,2);body=self.add();self.state.add_counters(body,'charge',1)
        bolt=self.add('wc-bolt',zone=Zone.HAND);self.cast(bolt,(body,));self.drain()
        self.assertFalse([e for e in self.events('trigger_created') if e['ability'].startswith('ward:')])

    def test_leyline_gain_bonus_applies_once_per_event_and_per_copy(self):
        self.game();a=self.card('leyline-of-hope');self.card('leyline-of-hope')
        self.kernel.execute_for_scenario(a,'A',(GainLife(3),GainLife(0),GainLife(2)))
        self.assertEqual(49,self.state.life('A'));self.assertEqual(40,self.state.life('B'))

    def test_leyline_anthem_uses_starting_life_plus_seven(self):
        self.game();ref=self.card('leyline-of-hope');body=self.add()
        self.state.gain_life('A',6);self.assertEqual(2,self.kernel.effective(body).power)
        self.state.gain_life('A',1);self.assertEqual(4,self.kernel.effective(body).power)
        self.state.lose_life_batch(('A',),1);self.assertEqual(2,self.kernel.effective(body).power)

    def test_leyline_lifelink_sources_are_distinct_gain_events(self):
        self.game();self.card('leyline-of-hope');self.card('sorin-vengeful-bloodlord');a=self.add();b=self.add()
        self.kernel._deal_damage(((self.state.get(a),'B',2),(self.state.get(a),'C',2),(self.state.get(b),'D',2)))
        self.assertEqual(48,self.state.life('A'))

    def test_opening_actions_are_optional_and_start_in_starting_player_order(self):
        self.game(started=False);a=self.card('leyline-of-hope','A',Zone.HAND);b=self.card('leyline-of-hope','B',Zone.HAND)
        self.kernel.begin_opening_hand_actions('B');self.assertEqual('B',self.kernel.pending_choice.actor)
        self.answer([]);self.assertEqual('A',self.kernel.pending_choice.actor);self.restore();self.answer([0])
        self.assertEqual(Zone.BATTLEFIELD,self.current(a).zone);self.assertEqual(Zone.HAND,self.current(b).zone)
        self.assertEqual('B',self.kernel.active);self.assertEqual(1,self.state.turn_number)

    def test_opening_choice_is_private_and_rejects_another_actor(self):
        self.game(started=False);self.card('leyline-of-hope','A',Zone.HAND);hidden=self.add(zone=Zone.HAND)
        self.kernel.begin_opening_hand_actions('A');request=self.kernel.pending_choice
        self.assertNotIn(hidden.ref.card_id if hasattr(hidden,'ref') else hidden.card_id,json.dumps(project_actor(self.kernel,'B')))
        snap=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.answer(request.request_id,'B',[0])
        self.assertEqual(snap,self.kernel.snapshot())

    def test_opening_actions_cannot_replace_a_started_game(self):
        self.game();snap=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.begin_opening_hand_actions('A')
        self.assertEqual(snap,self.kernel.snapshot())

    def test_opening_choice_rejects_card_without_permission(self):
        self.game(started=False);self.card('leyline-of-hope',zone=Zone.HAND);self.add(zone=Zone.HAND)
        self.kernel.begin_opening_hand_actions('A');self.assertEqual(1,len(self.kernel.pending_choice.options))
        with self.assertRaises(RulesViolation):self.answer([1])

    def test_planeswalker_combat_removes_loyalty_without_player_damage(self):
        self.game();attacker=self.add();walker=self.card('nissa-steward-of-elements','B')
        self.combat({attacker:walker});self.finish_combat()
        self.assertEqual(1,self.loyalty(walker));self.assertEqual(40,self.state.life('B'))

    def test_planeswalker_controller_can_block_for_it(self):
        self.game();attacker=self.add();walker=self.card('nissa-steward-of-elements','B');blocker=self.add(actor='B')
        self.combat({attacker:walker});self.finish_combat({uid(attacker):[uid(blocker)]})
        self.assertEqual(3,self.loyalty(walker));self.assertEqual(2,self.state.get(attacker).damage_marked)

    def test_planeswalker_attack_avoids_player_only_propaganda_tax(self):
        self.game();attacker=self.add();walker=self.card('nissa-steward-of-elements','B');self.add('catalog:propaganda','B')
        self.combat({attacker:walker});self.assertEqual(0,self.events('attackers_declared')[-1]['attack_cost'])

    def test_walker_combat_rejects_own_and_stale_defenders(self):
        self.game();attacker=self.add();walker=self.card('nissa-steward-of-elements')
        with self.assertRaises(RulesViolation):self.combat({attacker:walker})
        self.state.change_control(walker,'B');self.state.move((ZoneMove(walker,Zone.HAND),),'fixture')
        with self.assertRaises(RulesViolation):self.kernel.declare_attackers('A',{attacker:walker},revision=self.kernel.revision)

    def test_departed_defending_walker_does_not_redirect_damage(self):
        self.game();attacker=self.add();walker=self.card('nissa-steward-of-elements','B')
        self.combat({attacker:walker});self.move(walker,Zone.GRAVEYARD);self.finish_combat()
        self.assertEqual(40,self.state.life('B'))

    def test_goad_prefers_an_available_other_player_over_planeswalker(self):
        self.game();attacker=self.add();walker=self.card('nissa-steward-of-elements','B')
        aura=self.add('catalog:parasitic-impetus','B');self.state.attach(aura,attacker)
        with self.assertRaisesRegex(RulesViolation,'goad'):self.combat({attacker:walker})

    def test_walker_combat_actor_packet_and_adapter_are_exact(self):
        self.game();attacker=self.add();walker=self.card('nissa-steward-of-elements','B')
        self.state.start_turn('A');self.kernel.phase='declare_attackers';self.kernel.priority=None
        self.kernel.turn_schedule={'land_plays':0,'advance':False,'cleanup_priority':False}
        packet=project_actor(self.kernel,'A');self.assertIn({'ref':walker.to_json(),'defending_player':'B'},packet['attack_destinations'])
        RulesActorAdapter(self.kernel).submit('A',{'kind':'attack','revision':self.kernel.revision,
            'attackers':[{'source':attacker.to_json(),'defender':walker.to_json()}]})
        self.restore();self.assertEqual(walker.to_json(),self.kernel.combat['attackers'][0]['defender_object']['ref'])

    def test_positive_loyalty_replacement_choice_replays_without_double_payment(self):
        plus=CardProgram('loyalty-plus','Extra loyalty',('Enchantment',),
            counter_replacements=(CounterReplacement('plus',Selector(Zone.BATTLEFIELD),kind='loyalty',additional=1),))
        self.game((plus,));talent=self.card('innkeeper-s-talent');self.level(talent,3);self.add('loyalty-plus')
        ref=self.card('nissa-steward-of-elements');self.act(ref,'scry-two')
        self.assertEqual('counter_replacement',self.kernel.pending_choice.kind);self.assertEqual(3,self.loyalty(ref));self.restore()
        q=self.kernel.pending_choice;self.answer([next(i for i,o in enumerate(q.options) if 'double-counters-you-put' in o.label)])
        self.assertEqual(8,self.loyalty(ref));self.drain();self.assertEqual(1,len(self.events('loyalty_cost_paid')))

    def test_minsc_any_target_includes_battles(self):
        battle=CardProgram('wc-battle','Battle',('Battle',))
        self.game((battle,));ref=self.card('minsc-boo-timeless-heroes');self.add('wc-hamster');target=self.add('wc-battle','B')
        self.state.add_counters(target,'defense',7);self.state.set_protector(target,'B');self.act(ref,'sacrifice-and-fling');self.top()
        q=self.kernel.pending_choice;self.answer([next(i for i,o in enumerate(q.options) if o.ref==target)]);self.drain()
        self.assertEqual(3,dict(self.state.get(target).counters)['defense']);self.assertEqual(4,len(self.state.zone('A',Zone.HAND)))

    def test_minsc_multiple_sacrifices_require_an_authored_selection(self):
        self.game();ref=self.card('minsc-boo-timeless-heroes');one=self.add();two=self.add('wc-hamster')
        self.act(ref,'sacrifice-and-fling');self.top();self.assertEqual('reflexive_sacrifice',self.kernel.pending_choice.kind)
        self.restore();q=self.kernel.pending_choice;self.answer([next(i for i,o in enumerate(q.options) if o.ref==two)])
        self.choose('player:B');self.drain();self.assertEqual(Zone.BATTLEFIELD,self.state.get(one).zone);self.assertEqual(36,self.state.life('B'))

    def test_minsc_reflexive_trigger_retains_lki_after_source_leaves(self):
        self.game();ref=self.card('minsc-boo-timeless-heroes',loyalty=2);self.add('wc-hamster')
        self.act(ref,'sacrifice-and-fling');self.assertEqual(Zone.GRAVEYARD,self.current(ref).zone)
        self.top();self.choose('player:B');self.drain();self.assertEqual(36,self.state.life('B'))

    def test_minsc_reflexive_damage_can_be_responded_to(self):
        self.game();ref=self.card('minsc-boo-timeless-heroes');self.add('wc-hamster')
        self.act(ref,'sacrifice-and-fling');self.top();self.choose('player:B')
        self.assertEqual(40,self.state.life('B'));self.assertIsNone(self.kernel.resolving);self.assertIsNotNone(self.kernel.priority)

    def test_minsc_second_boo_uses_legend_state_action(self):
        self.game();ref=self.card('minsc-boo-timeless-heroes',zone=Zone.HAND);self.kernel.enter(ref);self.drain()
        self.kernel.begin_step('A','upkeep');self.drain()
        self.assertEqual(1,len([o for o in self.state.objects(Zone.BATTLEFIELD) if o.effective_definition=='token:boo']))

    def test_nissa_loyalty_zero_lki_does_not_put_a_two_mana_creature(self):
        self.game();ref=self.card('nissa-steward-of-elements',loyalty=2);self.act(ref,'look-and-put')
        self.kernel._deal_damage(((self.state.get(self.add()),ref,2),));self.kernel.advance()
        self.assertEqual(Zone.GRAVEYARD,self.current(ref).zone);self.top()
        self.assertEqual(['leave'],[o.key for o in self.kernel.pending_choice.options])

    def test_nissa_animation_expires_on_cleanup(self):
        self.game();ref=self.card('nissa-steward-of-elements',loyalty=7);land=self.add('catalog:forest')
        self.act(ref,'animate-lands',(land,));self.drain()
        self.kernel.turn_schedule={'land_plays':0,'advance':False,'cleanup_priority':False};self.kernel._begin_cleanup();self.drain()
        self.assertNotIn('Creature',self.kernel.effective(land).types)

    def test_sorin_entry_type_continuous_layers_match_exhaustive(self):
        self.game();ref=self.card('sorin-vengeful-bloodlord');target=self.add(zone=Zone.GRAVEYARD)
        self.act(ref,'return-vampire',(target,),x=2);self.drain()
        args={'active_player':'A','life_totals':{p:self.state.life(p) for p in self.state.players},
              'starting_life_totals':{p:40 for p in self.state.players},'live_players':self.state.live_players}
        self.assertEqual(evaluate(self.state.objects(),self.kernel.definitions,**args),evaluate_exhaustive(self.state.objects(),self.kernel.definitions,**args))

    def test_sorin_copied_entry_retains_added_vampire(self):
        copier=CardProgram('wc-copy','Copy',('Creature',),power=0,toughness=0,
            entry_copy=Selector(Zone.BATTLEFIELD,types=('Creature',)))
        self.game((copier,));ref=self.card('sorin-vengeful-bloodlord');body=self.add();target=self.add('wc-copy',zone=Zone.GRAVEYARD)
        self.act(ref,'return-vampire',(target,),x=0);self.top()
        q=self.kernel.pending_choice;self.answer([next(i for i,o in enumerate(q.options) if o.ref==body)]);self.drain()
        self.assertIn('Vampire',self.kernel.effective(self.current(target).ref).subtypes)

    def test_ward_multiple_instances_trigger_independently(self):
        talent,body,bolt=self.ward_spell()
        # A second source present before a fresh targeting event adds a second ward.
        self.drain();second=self.card('innkeeper-s-talent');self.level(second,2)
        bolt2=self.add('wc-bolt','B',Zone.HAND);self.kernel.open_window_for_scenario('A',priority_actor='B');self.cast(bolt2,(body,),actor='B')
        created=[e for e in self.events('trigger_created') if e['ability'].startswith('ward:')]
        self.assertEqual(3,len(created));self.drain();self.assertEqual(0,self.state.get(body).damage_marked)

    def test_ward_counters_activated_ability_not_its_source(self):
        ability=ActivatedProgram('ping',CostSpec(),(Damage('target',1),),TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',))))
        p=CardProgram('wc-pinger','Pinger',('Artifact',),activated=(ability,))
        self.game((p,));talent=self.card('innkeeper-s-talent');self.level(talent,2);body=self.add();self.state.add_counters(body,'charge',1)
        source=self.add('wc-pinger','B');self.kernel.open_window_for_scenario('A',priority_actor='B');self.act(source,'ping',(body,),actor='B');self.drain()
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(source).zone);self.assertEqual(0,self.state.get(body).damage_marked)

    def test_ward_trigger_survives_last_counter_removal(self):
        _,body,_=self.ward_spell();self.state.put_counters_batch((),removals=((body,(('charge',1),)),))
        self.drain();self.assertEqual(0,self.state.get(body).damage_marked)

    def test_class_granted_ward_is_removed_with_source_abilities(self):
        self.game();talent=self.card('innkeeper-s-talent');self.level(talent,2);body=self.add();self.state.add_counters(body,'charge',1)
        self.state.apply_copy((talent,),'wc-body')
        self.assertEqual((),self.kernel.effective(body).wards)

    def test_leyline_anthem_loss_runs_state_based_actions(self):
        self.game();ref=self.card('leyline-of-hope');body=self.add();self.state.gain_life('A',7)
        self.kernel._deal_damage(((self.state.get(self.add(actor='B')),body,4),));self.kernel.advance()
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(body).zone)
        self.state.lose_life_batch(('A',),1);self.kernel.advance();self.assertEqual(Zone.GRAVEYARD,self.current(body).zone)

    def test_multiple_opening_leylines_can_be_ordered_and_all_enter(self):
        self.game(started=False);a=self.card('leyline-of-hope',zone=Zone.HAND);b=self.card('leyline-of-hope',zone=Zone.HAND)
        self.kernel.begin_opening_hand_actions('A');self.answer([1,0])
        self.assertEqual(Zone.BATTLEFIELD,self.current(a).zone);self.assertEqual(Zone.BATTLEFIELD,self.current(b).zone)
        entries=[e['event']['before']['ref']['card_id'] for e in self.events('zone_changed')]
        self.assertEqual([b.card_id,a.card_id],entries[:2])

    def test_trample_excess_goes_to_walker_not_controller(self):
        trampler=CardProgram('wc-trampler','Trampler',('Creature',),power=8,toughness=8,keywords=('trample',))
        self.game((trampler,),players=('A','B'));a=self.add('wc-trampler');walker=self.card('nissa-steward-of-elements','B',loyalty=10);blocker=self.add('wc-zero','B')
        self.combat({a:walker})
        while self.kernel.priority:self.kernel.pass_priority(self.kernel.priority)
        self.kernel.declare_blockers('B',{uid(a):[uid(blocker)]},revision=self.kernel.revision)
        for _ in range(30):
            if self.kernel.combat['damage_pending'] and self.kernel.priority is None:break
            self.kernel.pass_priority(self.kernel.priority)
        self.kernel.assign_combat_damage('A',{uid(a):{'blockers':{uid(blocker):1},'defender':7}},revision=self.kernel.revision)
        self.assertEqual(3,self.loyalty(walker));self.assertEqual(40,self.state.life('B'))

    def test_defending_walker_control_change_removes_damage_destination(self):
        self.game();attacker=self.add();walker=self.card('nissa-steward-of-elements','B')
        self.combat({attacker:walker});self.state.change_control(walker,'C');self.kernel.advance();self.finish_combat()
        self.assertEqual(3,self.loyalty(walker));self.assertEqual(40,self.state.life('B'));self.assertEqual(40,self.state.life('C'))

    def test_class_resolution_sets_its_level_without_rechecking_activation_condition(self):
        self.game();talent=self.card('innkeeper-s-talent');self.level(talent,3)
        self.kernel.execute_for_scenario(talent,'A',(SetClassLevel(2),))
        self.assertEqual(2,self.state.get(talent).class_level)
