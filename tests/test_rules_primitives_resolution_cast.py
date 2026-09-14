"""Hosted conformance for complete Expertise, discover and four cascade programs."""
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
from edh_gauntlet.rules_choices import ResolutionCastBoundary
from edh_gauntlet.rules_actor import project_actor
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed,digest,source_facts
from edh_gauntlet.catalog import load_catalog

CARDS=('rishkar-s-expertise','hidden-nursery','apex-devastator')


class ResolutionCastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        reviewed=load_reviewed(cls.root)
        drafts=json.loads((cls.root/'data/rules/draft_cards.json').read_text(encoding='utf-8'))['drafts']
        cls.rows={row['card_id']:row for row in drafts if row['card_id'] in CARDS}
        cls.cards={key:validate(decode(row['program'])) for key,row in cls.rows.items()}
        cls.base=tuple(row['program'] for row in reviewed.values())+tuple(cls.cards.values())
        cls.prefix='draft:'

    def game(self,extra=()):
        body=CardProgram('rc-body','Body',('Creature',),power=2,toughness=3,mana_value=2,
            cast=CastSpec(CostSpec(ManaCost(1,('G',)))))
        counter=CardProgram('rc-counter','Counter',('Instant',),mana_value=2,
            cast=CastSpec(CostSpec(ManaCost(1,('U',))),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.STACK)),spell_effects=(Counter('target'),))
        self.programs=self.base+(body,counter)+extra
        self.state=RulesState(('A','B','C','D'),seed=31);self.kernel=RulesKernel(self.state,self.programs);self.serial=0
        self.anchor=self.add('catalog:forest')
        self.state.start_turn('A');self.kernel.open_window_for_scenario('A')

    def add(self,definition='rc-body',actor='A',zone=Zone.BATTLEFIELD,**kw):
        self.serial+=1
        return self.state.add_card('rc-object-'+str(self.serial),definition,actor,zone,**kw)

    def hand(self,key):return self.add(self.cards[key].definition_id,zone=Zone.HAND)
    def current(self,ref):return self.state.get(self.state.current(ref.card_id))
    def events(self,kind):return [row for row in self.kernel.semantic_events if row['kind']==kind]
    def payment(self,symbols='',**kw):
        self.state.add_mana('A',symbols)
        return Payment(tuple(sorted(Counts(symbols).items())),**kw)

    def cast(self,ref,symbols='',targets=(),**kw):
        if not self.kernel._cast_waiting() and self.kernel.priority is None and not self.kernel.stack:
            self.kernel.open_window_for_scenario('A')
        payment=self.payment(symbols)
        quote=self.kernel.quote_cast('rc-cast-'+str(len(self.kernel.action_receipts)),'A',ref,targets,**kw)
        return self.kernel.commit_action(quote,payment)

    def free(self,ref,targets=(),payment=None,**kw):
        quote=self.kernel.quote_cast('rc-free-'+str(len(self.kernel.action_receipts)),'A',ref,targets,**kw)
        return self.kernel.commit_action(quote,payment or Payment())

    def decline(self):
        window=self.kernel.resolution_cast
        return self.kernel.decline_resolution_cast('rc-decline-'+str(len(self.kernel.action_receipts)),
            'A',window['id'],revision=self.kernel.revision)

    def answer(self,indexes):
        request=self.kernel.pending_choice
        return self.kernel.answer(request.request_id,request.actor,indexes)

    def top(self):
        frame=self.kernel.stack[-1]['id']
        for _ in range(60):
            if self.kernel.pending_choice or self.kernel._cast_waiting() or not any(f['id']==frame for f in self.kernel.stack):return
            self.kernel.pass_priority(self.kernel.priority)
        self.fail('No top-frame boundary')

    def drain(self):
        for _ in range(300):
            if self.kernel.pending_choice:self.answer(list(range(self.kernel.pending_choice.minimum)))
            elif self.kernel._cast_waiting():self.decline()
            elif self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
            else:return
        self.fail('No final boundary')

    def offer(self):
        card=self.hand('rishkar-s-expertise');self.cast(card,'CCCCGG');self.top()
        self.assertTrue(self.kernel._cast_waiting())
        return card

    def discover(self,amount=4):
        self.kernel.execute_for_scenario(self.anchor,'A',(Discover(amount),))
        return self.kernel.advance()

    def hit(self):return ObjectRef.from_json(self.kernel.resolution_cast['refs'][0])

    def restore(self):
        value=self.kernel.snapshot();self.kernel=RulesKernel.restore(value,self.programs);self.state=self.kernel.state
        self.assertEqual(value,self.kernel.snapshot())

    def mana_command(self,source,ability='intrinsic-land:Forest',payment=None):
        return {'kind':'activate','source':source.to_json(),'targets':[],'x_value':0,'ability_id':ability,
            'payment':(payment or Payment()).to_json()}

    def test_complete_printed_programs_and_source_binding(self):
        catalog={c.card_id:c for c in load_catalog(self.root/'data/catalog/cards.json')}
        self.assertEqual(set(CARDS),set(self.cards))
        for key,program in self.cards.items():
            self.assertEqual(self.prefix+key,program.definition_id)
            self.assertEqual(program,validate(decode(encode(program))))
            row=self.rows[key];actual=row.get('source_facts_sha256') or digest(row['source_facts'])
            self.assertEqual(digest(source_facts(catalog[key])),actual)
        self.assertEqual(('Chimera','Hydra'),self.cards['apex-devastator'].subtypes)

    def test_compiler_rejects_invalid_limits_and_unbound_cascade(self):
        for effect in (Discover(-1),Discover(True),CastDuringResolution(-1),CastDuringResolution('5'),Cascade()):
            with self.subTest(effect=effect),self.assertRaises(RulesViolation):
                validate(CardProgram('bad','Bad',('Sorcery',),spell_effects=(effect,)))

    def test_expertise_draws_current_greatest_power_then_offers(self):
        self.game();body=self.add();self.state.add_counters(body,'+1/+1',2)
        for _ in range(5):self.add(zone=Zone.LIBRARY)
        card=self.offer()
        self.assertEqual(4,len(self.state.zone('A',Zone.HAND)))
        self.assertEqual(Zone.STACK,self.current(card).zone)
        self.assertIsNone(self.kernel.priority)

    def test_expertise_ignores_opponent_power(self):
        self.game();self.add(actor='B');self.offer()
        self.assertEqual(0,len(self.events('card_drawn')))

    def test_expertise_zero_power_still_offers(self):
        self.game((CardProgram('zero','Zero',('Creature',),power=0,toughness=4),));self.add('zero')
        self.offer();self.assertTrue(self.kernel._cast_waiting())

    def test_expertise_negative_power_still_offers(self):
        self.game((CardProgram('negative','Negative',('Creature',),power=-2,toughness=4),));self.add('negative')
        self.offer();self.assertEqual(0,len(self.events('card_drawn')))

    def test_expertise_can_cast_newly_drawn_card(self):
        self.game();self.add();drawn=self.add(zone=Zone.LIBRARY);self.add('catalog:forest',zone=Zone.LIBRARY)
        self.offer();ref=self.current(drawn).ref;self.free(ref)
        self.assertEqual(Zone.STACK,self.current(drawn).zone)
        self.drain();self.assertEqual(Zone.BATTLEFIELD,self.current(drawn).zone)

    def test_expertise_decline_leaves_hand_and_finishes_parent(self):
        self.game();other=self.add(zone=Zone.HAND);parent=self.offer();self.decline()
        self.assertEqual(Zone.HAND,self.current(other).zone)
        self.assertEqual(Zone.GRAVEYARD,self.current(parent).zone)
        self.assertIsNone(self.kernel.resolution_cast)

    def test_free_cast_has_no_priority_until_parent_finishes(self):
        self.game();other=self.add(zone=Zone.HAND);parent=self.offer();self.free(other)
        kinds=[e['kind'] for e in self.kernel.semantic_events]
        last_cast=max(i for i,x in enumerate(kinds) if x=='spell_cast')
        finish=max(i for i,x in enumerate(kinds) if x=='resolution_finished')
        self.assertLess(last_cast,finish);self.assertNotIn('priority_pass',kinds[last_cast:finish])
        self.assertEqual(Zone.GRAVEYARD,self.current(parent).zone);self.assertEqual('A',self.kernel.priority)

    def test_free_sorcery_works_during_opponents_upkeep(self):
        self.game();other=self.add(zone=Zone.HAND);self.kernel.open_window_for_scenario('B','upkeep','B')
        self.kernel.execute_for_scenario(self.anchor,'A',(CastDuringResolution(5),))
        self.free(other);self.assertEqual(Zone.STACK,self.current(other).zone)

    def test_offer_rejects_other_actor_without_mutation(self):
        self.game();other=self.add(zone=Zone.HAND);self.offer();before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('wrong','B',other)
        self.assertEqual(before,self.kernel.snapshot())

    def test_offer_rejects_land_and_wrong_origin(self):
        self.game();land=self.add('catalog:forest',zone=Zone.HAND);grave=self.add(zone=Zone.GRAVEYARD)
        self.offer()
        for ref in (land,grave):
            with self.subTest(ref=ref),self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',ref)

    def test_offer_rejects_mana_value_above_five_even_with_reducer(self):
        large=CardProgram('large','Large',('Sorcery',),mana_value=6,cast=CastSpec(CostSpec(ManaCost(6)),generic_reduction=6))
        self.game((large,));ref=self.add('large',zone=Zone.HAND);self.offer()
        with self.assertRaises(RulesViolation):self.free(ref)

    def test_free_x_is_zero(self):
        self.game();x=self.add('catalog:finale-of-revelation',zone=Zone.HAND);self.offer()
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad-x','A',x,x_value=3)
        self.free(x);self.assertEqual(0,self.kernel.stack[-1]['chosen_x'])

    def test_free_cast_rejects_alternative_cost(self):
        self.game();card=self.add('catalog:mulldrifter',zone=Zone.HAND);self.offer()
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad-alt','A',card,alternative_id='evoke')

    def test_free_cast_can_pay_kicker(self):
        self.game();card=self.add('catalog:nullpriest-of-oblivion',zone=Zone.HAND);self.offer()
        quote=self.kernel.quote_cast('kicked','A',card,kicker=True)
        self.assertEqual(4,quote.cost.mana.generic);self.assertEqual(('B',),quote.cost.mana.symbols)
        payment=self.payment('CCCCB');quote=self.kernel.quote_cast('kicked','A',card,kicker=True)
        self.kernel.commit_action(quote,payment)
        self.assertTrue(self.kernel.stack[-1]['kicker'])

    def test_free_cast_keeps_sacrifice_additional_cost(self):
        self.game();body=self.add();card=self.add('catalog:fling',zone=Zone.HAND)
        for _ in range(2):self.add('catalog:forest',zone=Zone.LIBRARY)
        self.offer()
        cost=self.kernel.definition(self.state.get(card)).cast.cost.zone_costs[0]
        self.free(card,(PlayerRef('B'),),Payment(zone_costs=((cost.cost_id,(body,)),)))
        self.assertEqual(Zone.GRAVEYARD,self.current(body).zone)
        self.drain();self.assertEqual(38,self.state.life('B'))

    def test_free_cast_requires_actual_legal_targets(self):
        self.game();card=self.add('catalog:zombify',zone=Zone.HAND);self.offer()
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.free(card)
        self.assertEqual(before,self.kernel.snapshot())

    def test_free_counter_can_target_resolving_parent(self):
        self.game();card=self.add('rc-counter',zone=Zone.HAND);parent=self.offer()
        self.free(card,(self.current(parent).ref,))
        self.assertEqual(Zone.GRAVEYARD,self.current(parent).zone)
        self.drain();self.assertTrue(self.events('all_targets_illegal'))

    def test_pending_draw_triggers_wait_for_free_cast(self):
        watch=CardProgram('watch','Watch',('Artifact',),abilities=(AbilityProgram('draw-watch',
            EventPattern('card_drawn',controller_only=True),(GainLife(1),)),))
        self.game((watch,));self.add('watch');self.add();self.add(zone=Zone.LIBRARY);self.add(zone=Zone.LIBRARY)
        self.offer();self.assertEqual(2,len(self.kernel.pending_triggers));self.assertFalse(self.kernel.stack)
        self.decline();self.assertEqual('trigger_order',self.kernel.pending_choice.kind)

    def test_offer_checkpoint_retains_parent_and_draw_count(self):
        self.game();self.add();self.add(zone=Zone.LIBRARY);self.add(zone=Zone.LIBRARY)
        self.offer();self.restore();self.decline()
        self.assertEqual(2,len(self.events('card_drawn')))

    def test_stale_decline_is_rejected(self):
        self.game();self.offer();w=self.kernel.resolution_cast
        with self.assertRaises(RulesViolation):
            self.kernel.decline_resolution_cast('decline','A',w['id'],revision='stale')
        self.assertTrue(self.kernel._cast_waiting())

    def test_no_regular_activation_or_priority_during_offer(self):
        self.game();self.offer()
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('mana','A',self.anchor,'intrinsic-land:Forest')
        with self.assertRaises(RulesViolation):self.kernel.pass_priority('A')

    def test_discover_exiles_face_up_until_inclusive_hit(self):
        self.game();hit=self.add('catalog:zombify',zone=Zone.LIBRARY)
        high=self.add(self.cards['apex-devastator'].definition_id,zone=Zone.LIBRARY);land=self.add('catalog:forest',zone=Zone.LIBRARY)
        self.discover();self.assertEqual(hit.card_id,self.hit().card_id)
        self.assertEqual({hit.card_id,high.card_id,land.card_id},{o.ref.card_id for o in self.state.zone('A',Zone.EXILE)})
        public=project_actor(self.kernel,'B')
        self.assertEqual(3,len(public['zones']['exile']['A']))
        self.assertEqual('waiting',public['decision']['kind'])

    def test_discover_decline_puts_hit_in_hand_and_rest_bottom(self):
        self.game();untouched=self.add(zone=Zone.LIBRARY);hit=self.add(zone=Zone.LIBRARY);land=self.add('catalog:forest',zone=Zone.LIBRARY)
        self.discover();self.decline()
        self.assertEqual(Zone.HAND,self.current(hit).zone)
        self.assertEqual([land.card_id,untouched.card_id],[o.ref.card_id for o in self.state.zone('A',Zone.LIBRARY)])
        self.assertEqual(1,len(self.events('discovered')))

    def test_discover_casts_from_exact_exiled_incarnation(self):
        self.game();hit=self.add(zone=Zone.LIBRARY);other=self.add(zone=Zone.EXILE)
        self.discover()
        with self.assertRaises(RulesViolation):self.free(other)
        self.free(self.hit());self.assertEqual(Zone.STACK,self.current(hit).zone)
        self.assertEqual(Zone.EXILE,self.current(other).zone)

    def test_discover_unpayable_targeted_hit_can_go_to_hand(self):
        self.game();hit=self.add('catalog:zombify',zone=Zone.LIBRARY);self.discover()
        with self.assertRaises(RulesViolation):self.free(self.hit())
        self.decline();self.assertEqual(Zone.HAND,self.current(hit).zone)

    def test_discover_empty_library_still_completes(self):
        self.game();self.discover();self.assertIsNone(self.kernel.resolution_cast)
        self.assertEqual(1,len(self.events('discovered')))

    def test_discover_no_hit_returns_every_card_and_preserves_count(self):
        self.game();refs=[self.add('catalog:forest',zone=Zone.LIBRARY) for _ in range(4)]
        self.discover();self.assertEqual(4,len(self.state.zone('A',Zone.LIBRARY)))
        self.assertFalse(self.state.zone('A',Zone.EXILE))
        self.assertEqual({r.card_id for r in refs},{o.ref.card_id for o in self.state.zone('A',Zone.LIBRARY)})

    def test_discover_zero_can_hit_zero_value_spell(self):
        self.game();hit=self.add('catalog:sol-ring',zone=Zone.LIBRARY)
        self.discover(0);self.assertIsNone(self.kernel.resolution_cast)
        self.assertEqual(Zone.LIBRARY,self.current(hit).zone)

    def test_discover_checkpoint_does_not_exile_twice(self):
        self.game();self.add(zone=Zone.LIBRARY);self.add('catalog:forest',zone=Zone.LIBRARY)
        self.discover();count=self.state.event_count;self.restore();self.kernel.advance()
        self.assertEqual(count,self.state.event_count);self.decline()
        self.assertEqual(1,len(self.events('discovered')))

    def test_discover_random_bottom_is_replay_deterministic(self):
        self.game();self.add(zone=Zone.LIBRARY)
        for _ in range(5):self.add('catalog:forest',zone=Zone.LIBRARY)
        self.discover();snapshot=self.kernel.snapshot();self.decline();expected=self.kernel.snapshot()
        self.kernel=RulesKernel.restore(snapshot,self.programs);self.state=self.kernel.state;self.decline()
        self.assertEqual(expected,self.kernel.snapshot())

    def test_discover_keeps_unrelated_exile(self):
        self.game();old=self.add(zone=Zone.EXILE);self.add(zone=Zone.LIBRARY)
        self.discover();self.decline();self.assertEqual(Zone.EXILE,self.current(old).zone)

    def test_nursery_enters_tapped_even_with_two_gates(self):
        self.game();self.add('catalog:simic-guildgate');self.add('catalog:gruul-guildgate')
        ref=self.add(self.cards['hidden-nursery'].definition_id,zone=Zone.HAND)
        self.kernel.enter(ref);self.drain();self.assertTrue(self.current(ref).tapped)

    def test_nursery_taps_for_green(self):
        self.game();ref=self.add(self.cards['hidden-nursery'].definition_id)
        quote=self.kernel.quote_activation('green','A',ref,'green');self.kernel.commit_action(quote,Payment())
        self.assertEqual(1,dict(self.state.mana_pool('A'))['G']);self.assertTrue(self.state.get(ref).tapped)

    def test_nursery_sacrifices_and_pays_five_for_discover(self):
        self.game();ref=self.add(self.cards['hidden-nursery'].definition_id);self.add(zone=Zone.LIBRARY)
        payment=self.payment('CCCCG');quote=self.kernel.quote_activation('discover','A',ref,'discover-four')
        self.kernel.commit_action(quote,payment)
        self.assertEqual(Zone.GRAVEYARD,self.current(ref).zone);self.top();self.assertTrue(self.kernel._cast_waiting())
        self.decline()

    def test_nursery_discover_requires_sorcery_timing(self):
        self.game();ref=self.add(self.cards['hidden-nursery'].definition_id)
        self.kernel.open_window_for_scenario('A','upkeep')
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',ref,'discover-four')

    def test_nursery_payment_failure_is_atomic(self):
        self.game();ref=self.add(self.cards['hidden-nursery'].definition_id)
        quote=self.kernel.quote_activation('bad','A',ref,'discover-four');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,Payment())
        self.assertEqual(before,self.kernel.snapshot())

    def test_apex_cast_creates_four_distinct_cascade_triggers(self):
        self.game();card=self.hand('apex-devastator');self.cast(card,'CCCCCCCCGG')
        self.assertEqual('trigger_order',self.kernel.pending_choice.kind);self.assertEqual(4,len(self.kernel.pending_triggers))
        self.answer([0,1,2,3]);self.assertEqual(5,len(self.kernel.stack))
        self.assertEqual(4,len({f.get('ability_id') for f in self.kernel.stack if not f['spell']}))

    def test_apex_cascade_hits_strictly_less_than_ten(self):
        self.game();hit=self.add(zone=Zone.LIBRARY);equal=self.add(self.cards['apex-devastator'].definition_id,zone=Zone.LIBRARY)
        self.cast(self.hand('apex-devastator'),'CCCCCCCCGG');self.answer([0,1,2,3]);self.top()
        self.assertEqual(hit.card_id,self.hit().card_id);self.assertEqual(9,self.kernel.resolution_cast['maximum'])
        self.assertEqual(Zone.EXILE,self.current(equal).zone)

    def test_cascade_decline_bottoms_hit_instead_of_hand(self):
        self.game();hit=self.add(zone=Zone.LIBRARY)
        self.cast(self.hand('apex-devastator'),'CCCCCCCCGG');self.answer([0,1,2,3]);self.top();self.decline()
        self.assertEqual(Zone.LIBRARY,self.current(hit).zone);self.assertFalse(self.state.zone('A',Zone.HAND))

    def test_cascaded_spell_resolves_before_next_cascade(self):
        self.game();hit=self.add(zone=Zone.LIBRARY)
        self.cast(self.hand('apex-devastator'),'CCCCCCCCGG');self.answer([0,1,2,3]);self.top()
        self.free(self.hit());self.assertTrue(self.kernel.stack[-1]['spell']);self.top()
        self.assertEqual(Zone.BATTLEFIELD,self.current(hit).zone);self.assertEqual(4,len(self.kernel.stack))

    def test_countered_apex_still_has_four_cascades(self):
        self.game();card=self.hand('apex-devastator');self.cast(card,'CCCCCCCCGG');self.answer([0,1,2,3])
        counter=self.add('rc-counter',zone=Zone.HAND);self.cast(counter,'CU',(self.current(card).ref,));self.top()
        self.assertEqual(Zone.GRAVEYARD,self.current(card).zone)
        self.drain();self.assertEqual(4,len(self.events('cascade_finished')))

    def test_apex_put_onto_battlefield_does_not_cascade(self):
        self.game();card=self.hand('apex-devastator');self.kernel.enter(card);self.drain()
        self.assertFalse(self.events('cascade_finished'));self.assertFalse(self.events('spell_cast'))

    def test_cascade_empty_library_four_independent_completions(self):
        self.game();card=self.hand('apex-devastator');self.cast(card,'CCCCCCCCGG');self.drain()
        self.assertEqual(4,len(self.events('cascade_finished')))
        self.assertEqual(Zone.BATTLEFIELD,self.current(card).zone)

    def test_free_spell_cannot_bypass_casting_restriction(self):
        blocker=CardProgram('blocker','Blocker',('Artifact',),casting_restrictions=(
            CastRestriction(Selector(Zone.STACK,types=('Creature',)),(Zone.EXILE,)),))
        self.game((blocker,));self.add('blocker');hit=self.add(zone=Zone.LIBRARY);self.discover()
        with self.assertRaises(RulesViolation):self.free(self.hit())
        self.decline();self.assertEqual(Zone.HAND,self.current(hit).zone)

    def test_resolution_actor_packet_does_not_reveal_other_hands(self):
        self.game();self.add(zone=Zone.HAND);self.offer()
        own=project_actor(self.kernel,'A');other=project_actor(self.kernel,'B')
        self.assertEqual('resolution_cast',own['decision']['kind']);self.assertEqual(1,len(own['decision']['candidates']))
        self.assertEqual('waiting',other['decision']['kind']);self.assertNotIn('candidates',other['decision'])

    def test_actor_decline_and_replay(self):
        self.game();self.offer();adapter=RulesActorAdapter(self.kernel);request=self.kernel.resolution_cast['id']
        adapter.submit('A',{'kind':'decline_cast','action_id':'decline','request_id':request,'revision':self.kernel.revision})
        replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.assertEqual(adapter.kernel.snapshot(),replay.kernel.snapshot())

    def test_actor_free_cast_and_replay(self):
        self.game();card=self.add(zone=Zone.HAND);self.offer();adapter=RulesActorAdapter(self.kernel)
        adapter.submit('A',{'kind':'cast','action_id':'free','revision':self.kernel.revision,'source':card.to_json(),
            'targets':[],'x_value':0,'payment':Payment().to_json()})
        replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.assertEqual(adapter.kernel.snapshot(),replay.kernel.snapshot())

    def test_taxed_free_cast_requires_payment(self):
        tax=CardProgram('tax','Tax',('Artifact',),cost_modifiers=(CostModifier('tax',Selector(Zone.STACK),1),))
        self.game((tax,));card=self.add(zone=Zone.HAND);self.offer();self.add('tax')
        quote=self.kernel.quote_cast('taxed','A',card);self.assertEqual(1,quote.cost.mana.generic)
        with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,Payment())
        payment=self.payment('C');quote=self.kernel.quote_cast('taxed','A',card)
        self.kernel.commit_action(quote,payment);self.assertEqual(Zone.STACK,self.current(card).zone)

    def test_authored_mana_ability_pays_locked_free_cast_tax(self):
        tax=CardProgram('tax','Tax',('Artifact',),cost_modifiers=(CostModifier('tax',Selector(Zone.STACK),1),))
        self.game((tax,));card=self.add(zone=Zone.HAND);self.offer();self.add('tax')
        plan=Payment((('G',1),),mana_actions=(self.mana_command(self.anchor),))
        self.free(card,payment=plan)
        self.assertTrue(self.state.get(self.anchor).tapped);self.assertEqual(Zone.STACK,self.current(card).zone)
        self.assertEqual(0,dict(self.state.mana_pool('A')).get('G',0))

    def test_mana_plan_failure_leaves_no_payment_or_spell_announcement(self):
        tax=CardProgram('tax','Tax',('Artifact',),cost_modifiers=(CostModifier('tax',Selector(Zone.STACK),2),))
        self.game((tax,));card=self.add(zone=Zone.HAND);self.offer();self.add('tax');before=self.kernel.snapshot()
        plan=Payment((('G',1),),mana_actions=(self.mana_command(self.anchor),))
        with self.assertRaises(RulesViolation):self.free(card,payment=plan)
        self.assertEqual(before,self.kernel.snapshot())

    def test_mana_plan_rejects_nonmana_activation(self):
        machine=CardProgram('machine','Machine',('Artifact',),activated=(ActivatedProgram('draw',CostSpec(),(Draw(1),)),))
        self.game((machine,));machine=self.add('machine');card=self.add(zone=Zone.HAND);self.offer();before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):
            self.free(card,payment=Payment(mana_actions=(self.mana_command(machine,'draw'),)))
        self.assertEqual(before,self.kernel.snapshot())

    def test_mana_plan_rejects_other_commands(self):
        self.game();card=self.add(zone=Zone.HAND);self.offer();before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.free(card,payment=Payment(mana_actions=({'kind':'pass'},)))
        self.assertEqual(before,self.kernel.snapshot())

    def test_mana_plan_can_answer_owned_color_choice(self):
        # A fixture source with reviewed fixed options avoids inferred commander identity.
        choice=CardProgram('choice','Choice',('Artifact',),activated=(ActivatedProgram('mana',CostSpec(tap_source=True),
            (ChooseMana((('B',),('G',))),),mana_ability=True),))
        # Definition sets are immutable; construct this case independently.
        self.game((choice,));card=self.add('catalog:nullpriest-of-oblivion',zone=Zone.HAND);source=self.add('choice');self.offer()
        self.state.add_mana('A','CCCC')
        plan=Payment((('B',1),('C',4)),mana_actions=(self.mana_command(source,'mana'),{'kind':'answer','indexes':[0]}))
        self.free(card,payment=plan,kicker=True)
        self.assertTrue(self.kernel.stack[-1]['kicker']);self.assertTrue(self.state.get(source).tapped)

    def test_mana_plan_must_complete_color_choice(self):
        choice=CardProgram('choice','Choice',('Artifact',),activated=(ActivatedProgram('mana',CostSpec(tap_source=True),
            (ChooseMana((('B',),('G',))),),mana_ability=True),))
        self.game((choice,));card=self.add(zone=Zone.HAND);source=self.add('choice');self.offer();before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.free(card,payment=Payment(mana_actions=(self.mana_command(source,'mana'),)))
        self.assertEqual(before,self.kernel.snapshot())

    def test_actor_mana_plan_replay(self):
        tax=CardProgram('tax','Tax',('Artifact',),cost_modifiers=(CostModifier('tax',Selector(Zone.STACK),1),))
        self.game((tax,));card=self.add(zone=Zone.HAND);self.offer();self.add('tax');adapter=RulesActorAdapter(self.kernel)
        payment=Payment((('G',1),),mana_actions=(self.mana_command(self.anchor),))
        adapter.submit('A',{'kind':'cast','action_id':'with-mana','source':card.to_json(),'targets':[],
            'x_value':0,'payment':payment.to_json(),'revision':self.kernel.revision})
        replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.assertEqual(adapter.kernel.snapshot(),replay.kernel.snapshot())


if __name__=='__main__':unittest.main()
