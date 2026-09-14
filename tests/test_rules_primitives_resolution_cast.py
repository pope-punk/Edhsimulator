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

CARDS=('rishkar-s-expertise','hidden-nursery','apex-devastator','oracle-of-mul-daya')


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
        self.assertEqual(3,quote.cost.mana.generic);self.assertEqual(('B',),quote.cost.mana.symbols)
        payment=self.payment('CCCB');quote=self.kernel.quote_cast('kicked','A',card,kicker=True)
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
        self.game();self.add('catalog:simic-guildgate');self.add('catalog:simic-guildgate')
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
        self.state.add_mana('A','CCC')
        plan=Payment((('B',1),('C',3)),mana_actions=(self.mana_command(source,'mana'),{'kind':'answer','indexes':[0]}))
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

    def main(self):
        self.add('catalog:forest',zone=Zone.LIBRARY)
        self.kernel.begin_turn_for_scenario('A')
        for _ in range(30):
            if self.kernel.phase=='precombat_main':return
            self.kernel.pass_priority(self.kernel.priority)
        self.fail('No main phase')

    def land(self,ref):
        return self.kernel.play_land('land-'+str(len(self.kernel.action_receipts)),'A',ref,revision=self.kernel.revision)

    def test_oracle_additional_land_play_is_cumulative(self):
        self.game();self.add(self.cards['oracle-of-mul-daya'].definition_id)
        self.assertEqual(2,self.kernel.player_permissions()['A']['land_play_limit'])
        self.add(self.cards['oracle-of-mul-daya'].definition_id)
        self.assertEqual(3,self.kernel.player_permissions()['A']['land_play_limit'])

    def test_oracle_reveals_only_current_top_to_all_players(self):
        self.game();self.add(self.cards['oracle-of-mul-daya'].definition_id)
        hidden=self.add(zone=Zone.LIBRARY);top=self.add('catalog:forest',zone=Zone.LIBRARY);self.kernel.advance()
        for player in self.state.players:
            packet=project_actor(self.kernel,player)
            self.assertEqual(top.to_json(),packet['revealed_library_tops']['A']['ref'])
            self.assertNotIn(hidden.card_id,json.dumps(packet))
        self.assertEqual(1,len([e for e in self.events('cards_revealed') if e.get('cause')=='library_top']))

    def test_oracle_empty_library_has_no_disclosure(self):
        self.game();self.add(self.cards['oracle-of-mul-daya'].definition_id);self.kernel.advance()
        self.assertEqual({},project_actor(self.kernel,'B')['revealed_library_tops'])

    def test_oracle_top_land_uses_normal_land_budget(self):
        self.game();self.add(self.cards['oracle-of-mul-daya'].definition_id)
        first=self.add('catalog:forest',zone=Zone.LIBRARY);second=self.add('catalog:forest',zone=Zone.LIBRARY)
        third=self.add('catalog:forest',zone=Zone.HAND);self.main()
        self.land(self.current(second).ref);self.land(self.current(first).ref)
        self.assertEqual(2,self.kernel.turn_schedule['land_plays'])
        with self.assertRaises(RulesViolation):self.land(third)

    def test_oracle_land_permission_excludes_buried_land(self):
        self.game();self.add(self.cards['oracle-of-mul-daya'].definition_id)
        buried=self.add('catalog:forest',zone=Zone.LIBRARY);self.add(zone=Zone.LIBRARY);self.main()
        with self.assertRaises(RulesViolation):self.land(self.current(buried).ref)
        self.assertEqual(0,self.kernel.turn_schedule['land_plays'])

    def test_oracle_does_not_allow_top_nonland_cast(self):
        self.game();self.add(self.cards['oracle-of-mul-daya'].definition_id);top=self.add(zone=Zone.LIBRARY);self.main()
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',self.current(top).ref)

    def test_oracle_does_not_allow_top_nonland_land_play(self):
        self.game();self.add(self.cards['oracle-of-mul-daya'].definition_id);top=self.add(zone=Zone.LIBRARY);self.main()
        with self.assertRaises(RulesViolation):self.land(self.current(top).ref)

    def test_oracle_land_play_keeps_main_phase_restriction(self):
        self.game();self.add(self.cards['oracle-of-mul-daya'].definition_id);top=self.add('catalog:forest',zone=Zone.LIBRARY)
        self.kernel.begin_turn_for_scenario('A')
        with self.assertRaises(RulesViolation):self.land(self.current(top).ref)

    def test_oracle_uses_controller_library_and_permissions(self):
        self.game();oracle=self.add(self.cards['oracle-of-mul-daya'].definition_id)
        self.add(zone=Zone.LIBRARY);b=self.add(actor='B',zone=Zone.LIBRARY);self.kernel.advance()
        self.state.change_control(oracle,'B');self.kernel.advance()
        self.assertEqual(1,self.kernel.player_permissions()['A']['land_play_limit'])
        self.assertEqual(2,self.kernel.player_permissions()['B']['land_play_limit'])
        packet=project_actor(self.kernel,'C')
        self.assertEqual({'B'},set(packet['revealed_library_tops']))
        self.assertEqual(b.card_id,packet['revealed_library_tops']['B']['ref']['card_id'])

    def test_oracle_departure_revokes_top_land_permission(self):
        self.game();oracle=self.add(self.cards['oracle-of-mul-daya'].definition_id)
        top=self.add('catalog:forest',zone=Zone.LIBRARY);self.main()
        self.kernel.execute_for_scenario(oracle,'A',(Move('source',Zone.HAND),))
        with self.assertRaises(RulesViolation):self.land(self.current(top).ref)
        self.assertEqual({},project_actor(self.kernel,'B')['revealed_library_tops'])

    def test_oracle_departure_does_not_reset_used_land_budget(self):
        self.game();oracle=self.add(self.cards['oracle-of-mul-daya'].definition_id)
        self.add('catalog:forest',zone=Zone.LIBRARY);self.main()
        first=self.add('catalog:forest',zone=Zone.HAND);second=self.add('catalog:forest',zone=Zone.HAND)
        self.land(first);self.kernel.execute_for_scenario(oracle,'A',(Move('source',Zone.HAND),))
        with self.assertRaises(RulesViolation):self.land(second)
        self.kernel.enter(self.current(oracle).ref);self.land(second)
        self.assertEqual(2,self.kernel.turn_schedule['land_plays'])

    def test_oracle_phasing_disables_disclosure_and_land_bonus(self):
        self.game();oracle=self.add(self.cards['oracle-of-mul-daya'].definition_id);self.add(zone=Zone.LIBRARY);self.kernel.advance()
        self.state.phase(oracle,True);self.kernel.advance()
        self.assertEqual({},project_actor(self.kernel,'B')['revealed_library_tops'])
        self.assertEqual(1,self.kernel.player_permissions()['A']['land_play_limit'])

    def test_oracle_hidden_then_revealed_top_retires_old_identity(self):
        self.game();oracle=self.add(self.cards['oracle-of-mul-daya'].definition_id);top=self.add(zone=Zone.LIBRARY)
        self.kernel.advance();old=self.current(top).ref
        self.state.phase(oracle,True);self.kernel.advance()
        with self.assertRaises(RulesViolation):self.state.get(old)
        self.state.phase(oracle,False);self.kernel.advance()
        self.assertNotEqual(old,self.current(top).ref)
        self.assertEqual(self.current(top).ref.to_json(),project_actor(self.kernel,'B')['revealed_library_tops']['A']['ref'])

    def test_oracle_covering_revealed_top_retires_its_reference(self):
        self.game();self.add(self.cards['oracle-of-mul-daya'].definition_id);old=self.add(zone=Zone.LIBRARY)
        cover=self.add('catalog:forest',zone=Zone.GRAVEYARD);self.kernel.advance()
        self.kernel.execute_for_scenario(cover,'A',(Move('source',Zone.LIBRARY),))
        with self.assertRaises(RulesViolation):self.state.get(old)
        self.assertEqual(cover.card_id,project_actor(self.kernel,'B')['revealed_library_tops']['A']['ref']['card_id'])

    def test_oracle_records_each_top_during_multiple_draws(self):
        self.game();self.add(self.cards['oracle-of-mul-daya'].definition_id)
        refs=[self.add(zone=Zone.LIBRARY) for _ in range(3)];self.kernel.advance()
        self.kernel.execute_for_scenario(self.anchor,'A',(Draw(2),))
        revealed=[e['refs'][0]['card_id'] for e in self.events('cards_revealed') if e.get('cause')=='library_top']
        self.assertEqual([r.card_id for r in reversed(refs)],revealed)

    def test_oracle_reveal_checkpoint_and_actor_land_replay(self):
        self.game();self.add(self.cards['oracle-of-mul-daya'].definition_id)
        land=self.add('catalog:forest',zone=Zone.LIBRARY);self.main();self.restore()
        adapter=RulesActorAdapter(self.kernel);ref=self.current(land).ref
        adapter.submit('A',{'kind':'play_land','action_id':'top-land','source':ref.to_json(),'revision':self.kernel.revision})
        replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.assertEqual(adapter.kernel.snapshot(),replay.kernel.snapshot())
        self.assertEqual(Zone.BATTLEFIELD,self.current(land).zone)

    def test_oracle_visible_ref_cannot_address_buried_library_card(self):
        self.game();self.add(self.cards['oracle-of-mul-daya'].definition_id)
        hidden=self.add('catalog:forest',zone=Zone.LIBRARY);self.add('catalog:forest',zone=Zone.LIBRARY);self.main()
        adapter=RulesActorAdapter(self.kernel)
        with self.assertRaises(RulesViolation):adapter._visible_ref(self.current(hidden).ref.to_json(),'A')

    def test_oracle_new_top_waits_until_special_action_finishes(self):
        self.game();self.add(self.cards['oracle-of-mul-daya'].definition_id)
        below=self.add(zone=Zone.LIBRARY);land=self.add('catalog:forest',zone=Zone.LIBRARY);self.main()
        start=len(self.kernel.semantic_events);self.land(self.current(land).ref)
        events=self.kernel.semantic_events[start:]
        finish=next(i for i,e in enumerate(events) if e['kind']=='resolution_finished')
        reveal=next(i for i,e in enumerate(events) if e['kind']=='cards_revealed' and e.get('cause')=='library_top')
        self.assertLess(finish,reveal)
        self.assertEqual(below.card_id,events[reveal]['refs'][0]['card_id'])

    def test_oracle_new_top_waits_until_announcement_finishes(self):
        self.game();self.add(self.cards['oracle-of-mul-daya'].definition_id)
        first=self.add(zone=Zone.LIBRARY);second=self.add(zone=Zone.LIBRARY);self.kernel.advance()
        # Bind an announcement checkpoint and change the top as a cost would.
        self.kernel.announcement={'test':True}
        self.state.move((ZoneMove(second,Zone.GRAVEYARD),),'fixture-cost')
        self.kernel._sync_library_tops()
        self.assertIsNone(self.kernel._visible_library_top('A','B'))
        self.kernel.announcement=None;self.kernel._sync_library_tops()
        self.assertEqual(first.card_id,self.kernel._visible_library_top('A','B').ref.card_id)

    def test_oracle_permissions_compiler_rejects_nonboolean_flags(self):
        for permission in (TopLibraryPermissions(reveal_top=1),TopLibraryPermissions(play_top_land='yes')):
            with self.subTest(permission=permission),self.assertRaises(RulesViolation):
                validate(CardProgram('bad','Bad',('Creature',),power=2,toughness=2,player_permissions=permission))

    def test_mana_plan_total_stays_locked_when_tax_source_is_sacrificed(self):
        tax=CardProgram('tax-mana','Tax mana',('Artifact',),cost_modifiers=(CostModifier('tax',Selector(Zone.STACK),1),),
            activated=(ActivatedProgram('mana',CostSpec(zone_costs=(ZoneCost('sacrifice','sacrifice'),)),
                (AddMana(('G',)),),mana_ability=True),))
        self.game((tax,));card=self.add(zone=Zone.HAND);self.offer();source=self.add('tax-mana')
        self.free(card,payment=Payment((('G',1),),mana_actions=(self.mana_command(source,'mana'),)))
        self.assertEqual(Zone.GRAVEYARD,self.current(source).zone)
        receipt=list(self.kernel.action_receipts.values())[-1]
        self.assertEqual(1,receipt['action']['cost']['mana']['generic'])

    def test_mana_plan_accepts_bounded_outer_action_identity(self):
        tax=CardProgram('tax','Tax',('Artifact',),cost_modifiers=(CostModifier('tax',Selector(Zone.STACK),1),))
        self.game((tax,));card=self.add(zone=Zone.HAND);self.offer();self.add('tax')
        quote=self.kernel.quote_cast('x'*128,'A',card)
        self.kernel.commit_action(quote,Payment((('G',1),),mana_actions=(self.mana_command(self.anchor),)))
        self.assertIn('x'*128,self.kernel.action_receipts)

    def test_mana_plan_and_sacrifice_additional_cost_share_parent(self):
        self.game();body=self.add();card=self.add('catalog:fling',zone=Zone.HAND)
        self.add('catalog:forest',zone=Zone.LIBRARY);self.add('catalog:forest',zone=Zone.LIBRARY);self.offer()
        cost=self.kernel.definition(self.state.get(card)).cast.cost.zone_costs[0]
        plan=Payment(zone_costs=((cost.cost_id,(body,)),),mana_actions=(self.mana_command(self.anchor),))
        self.free(card,(PlayerRef('B'),),payment=plan)
        self.assertEqual(Zone.GRAVEYARD,self.current(body).zone)
        self.assertEqual(1,dict(self.state.mana_pool('A')).get('G',0))
        self.drain();self.assertEqual(38,self.state.life('B'))

    def test_free_replicate_keeps_paid_repeat_costs_and_triggers(self):
        self.game();self.add();self.add();card=self.add('catalog:changing-loyalty',zone=Zone.HAND)
        for _ in range(2):self.add('catalog:forest',zone=Zone.LIBRARY)
        self.offer();targets=tuple(obj.ref for obj in self.state.objects(Zone.BATTLEFIELD) if obj.definition=='rc-body')[:1]
        quote=self.kernel.quote_cast('replicate','A',card,targets,replicate=1)
        self.assertEqual(2,quote.cost.mana.generic);self.assertEqual((),quote.cost.mana.symbols)
        payment=self.payment('CC');quote=self.kernel.quote_cast('replicate','A',card,targets,replicate=1)
        self.kernel.commit_action(quote,payment)
        self.assertEqual(2,len(self.kernel.stack));self.assertEqual(1,self.kernel.stack[0]['replicate'])

    def test_copied_apex_spell_does_not_add_cascade_triggers(self):
        self.game();card=self.hand('apex-devastator');self.cast(card,'CCCCCCCCGG');self.answer([0,1,2,3])
        original=self.kernel.stack[0]
        self.kernel._queue_captured_copy(self.state.get(self.current(card).ref),self.kernel._copy_blueprint(original))
        self.kernel.advance();self.top()
        self.assertEqual(2,len([f for f in self.kernel.stack if f['spell']]))
        self.assertEqual(4,len([f for f in self.kernel.stack if not f['spell']]))

    def test_free_necromancy_records_non_sorcery_cast_timing(self):
        self.game();card=self.add('catalog:necromancy',zone=Zone.HAND);self.offer();self.free(card)
        self.assertEqual('other',self.kernel.stack[-1]['cast_timing'])
        self.assertEqual('WithZoneResult',self.kernel.stack[-1]['tasks'][0]['effect']['node'])

    def test_mana_plan_preserves_derived_copy_registry(self):
        self.game();card=self.add(zone=Zone.HAND)
        self.kernel.execute_for_scenario(self.anchor,'A',(CopyTokens('source'),))
        self.offer()
        self.free(card,payment=Payment(mana_actions=(self.mana_command(self.anchor),)))
        self.assertTrue(self.kernel.copy_programs);self.restore()

    def test_discover_zero_hits_zero_value_nonland(self):
        zero=CardProgram('free-zero','Free zero',('Artifact',),mana_value=0,cast=CastSpec(CostSpec()))
        self.game((zero,));card=self.add('free-zero',zone=Zone.LIBRARY)
        self.discover(0);self.free(self.hit())
        self.assertEqual(Zone.STACK,self.current(card).zone)


if __name__=='__main__':unittest.main()


