"""Upkeep payments, attachment untap rules and exact delayed returns."""
import json
import unittest
from dataclasses import replace
from pathlib import Path
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState, RulesViolation, Zone, ZoneMove
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed, digest, source_facts
from edh_gauntlet.catalog import load_catalog
from edh_gauntlet.rules_characteristics import evaluate_exhaustive

CARDS=('dance-of-the-dead','mystic-remora','touch-the-spirit-realm','arcane-denial')


class UpkeepDelayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        reviewed=load_reviewed(cls.root)
        cls.rows={key:reviewed[key] for key in CARDS}
        cls.cards={key:row['program'] for key,row in cls.rows.items()}
        cls.base=tuple(row['program'] for row in reviewed.values())

    def game(self,key='mystic-remora',*,zone=Zone.BATTLEFIELD,extra=()):
        body=CardProgram('u-body','Body',('Creature',),power=2,toughness=4)
        land=CardProgram('u-land','Land',('Land',),subtypes=('Swamp',))
        spell=CardProgram('u-spell','Spell',('Instant',),cast=CastSpec(CostSpec(),timing='instant'))
        remove=replace(spell,definition_id='u-remove',name='Remove',
            spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD)),spell_effects=(Move('target',Zone.GRAVEYARD),))
        stifle=replace(spell,definition_id='u-stifle',name='Counter ability',spell_effects=(CounterAbilities(),))
        self.programs=self.base+(body,land,spell,remove,stifle)+extra
        self.state=RulesState(('A','B','C','D'));self.kernel=RulesKernel(self.state,self.programs)
        self.kernel.open_window_for_scenario('A');self.number=0
        self.source=self.state.add_card('source',self.cards[key].definition_id,'A',zone)
        self.body=self.state.add_card('body','u-body','B',Zone.BATTLEFIELD)
        self.other=self.state.add_card('other','u-body','A',Zone.BATTLEFIELD)
        self.lands={p:self.state.add_card('land-'+p,'u-land',p,Zone.BATTLEFIELD) for p in self.state.players}
        for p in self.state.players:
            for n in range(12):self.state.add_card('library-'+p+'-'+str(n),'u-body',p,Zone.LIBRARY)

    def ident(self):
        self.number+=1
        return 'u-action-'+str(self.number)

    def window(self,actor='A'):
        if not self.kernel.stack and self.kernel.turn_schedule is None:
            self.kernel.open_window_for_scenario('A',priority_actor=actor)
        while self.kernel.priority!=actor:self.kernel.pass_priority(self.kernel.priority)

    def top(self):
        self.assertTrue(self.kernel.stack)
        result=None
        for _ in self.state.live_players:result=self.kernel.pass_priority(self.kernel.priority)
        return result

    def choose(self,key):
        q=self.kernel.pending_choice;self.assertIsNotNone(q)
        return self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.key==key)])

    def targets(self,refs=()):
        q=self.kernel.pending_choice;self.assertEqual('trigger_targets',q.kind)
        return self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.ref==ref) for ref in refs])

    def order(self):
        q=self.kernel.pending_choice;self.assertEqual('trigger_order',q.kind)
        return self.kernel.answer(q.request_id,q.actor,list(range(len(q.options))))

    def settle(self):
        for _ in range(30):
            self.assertIsNone(self.kernel.pending_choice);self.assertIsNone(self.kernel.mana_payment)
            if not self.kernel.stack:return
            self.top()
        self.fail('Unbounded stack')

    def effect(self,ref,*effects,actor='A'):
        return self.kernel.execute_for_scenario(ref,actor,effects)

    def pay(self,mana=None):
        w=self.kernel.mana_payment
        return self.kernel.pay_resolution_mana(self.ident(),w['actor'],w['id'],
            None if mana is None else Payment(tuple(sorted(mana.items()))),revision=self.kernel.revision)

    def cast(self,ref,actor='A',targets=(),mana=()):
        self.window(actor);symbols=tuple(mana)
        if symbols:self.state.add_mana(actor,symbols)
        quote=self.kernel.quote_cast(self.ident(),actor,ref,targets)
        return self.kernel.commit_action(quote,Payment(tuple((s,symbols.count(s)) for s in sorted(set(symbols)))))

    def response(self,definition='u-remove',targets=(),actor='B'):
        ref=self.state.add_card(self.ident(),definition,actor,Zone.HAND)
        return self.cast(ref,actor,targets)

    def channel(self,target=None):
        self.window();self.state.add_mana('A',('C','W'))
        quote=self.kernel.quote_activation(self.ident(),'A',self.source,'channel',(target or self.body,))
        return self.kernel.commit_action(quote,Payment((('C',1),('W',1))))

    def reanimate(self):
        self.game('dance-of-the-dead',zone=Zone.HAND)
        grave=self.state.add_card('grave','u-body','B',Zone.GRAVEYARD)
        self.cast(self.source,targets=(grave,),mana='CB');self.top();self.top()
        self.source=self.state.current('source');self.returned=self.state.current('grave')

    def counts(self,ref=None):return dict(self.state.get(ref or self.source).counters)
    def hand(self,actor):return len(self.state.zone(actor,Zone.HAND))

    def next_upkeep(self,active='B'):
        # Begin an actual next turn; an injected upkeep alone is still this turn.
        self.kernel.begin_turn_for_scenario(active)
        if self.kernel.pending_choice:self.order()

    def advance_to(self,phase):
        for _ in range(100):
            if self.kernel.phase==phase:return
            self.assertIsNone(self.kernel.pending_choice);self.assertFalse(self.kernel.stack)
            if self.kernel.phase=='declare_attackers' and self.kernel.priority is None:
                self.kernel.declare_attackers(self.kernel.active,{},revision=self.kernel.revision)
            else:self.kernel.pass_priority(self.kernel.priority)
        self.fail('Did not reach phase')

    def denial(self,target_actor='B'):
        self.game('arcane-denial',zone=Zone.HAND)
        target=self.state.add_card('target','u-spell',target_actor,Zone.HAND)
        self.cast(target,target_actor);self.cast(self.source,targets=(self.state.current('target'),),mana='CU')
        self.top()
        return self.state.current('target')

    def test_full_printed_faces_source_facts_and_codec(self):
        catalog={c.card_id:c for c in load_catalog(self.root/'data/catalog/cards.json')}
        self.assertEqual(set(CARDS),set(self.cards))
        for key,program in self.cards.items():
            with self.subTest(card=key):
                self.assertEqual(digest(source_facts(catalog[key])),self.rows[key]['source_facts_sha256'])
                self.assertEqual(program,decode(encode(program)))
                face=catalog[key].faces[0]
                for field in ('types','subtypes','supertypes','colors'):
                    self.assertEqual(set(getattr(face,field)),set(getattr(program,field)))
                for field in ('mana_value','power','toughness'):
                    self.assertEqual(getattr(face,field),getattr(program,field))
                self.assertEqual(catalog[key].name,program.name)

    def test_normal_enchantment_cast_costs_and_touch_optional_entry(self):
        for key,symbols in (('mystic-remora','U'),('touch-the-spirit-realm','CCW')):
            with self.subTest(card=key):
                self.game(key,zone=Zone.HAND);self.cast(self.source,mana=symbols);self.top()
                self.source=self.state.current('source')
                if key=='touch-the-spirit-realm':self.targets();self.top()
                self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.source).zone)
                self.assertEqual((),self.state.mana_pool('A'))

    def test_dance_normal_cast_returns_tapped_attaches_and_adds_one_one(self):
        self.reanimate();obj=self.state.get(self.returned);view=self.kernel.effective(self.returned)
        self.assertTrue(obj.tapped);self.assertEqual('A',obj.controller)
        self.assertEqual((3,5),(view.power,view.toughness));self.assertTrue(view.untap_blocked)
        self.assertEqual(self.returned,self.state.get(self.source).attached_to)
        self.assertEqual((),self.state.mana_pool('A'))

    def test_dance_untap_step_skips_creature_and_upkeep_payment_untaps_it(self):
        self.reanimate();self.next_upkeep('A')
        self.assertTrue(self.state.get(self.returned).tapped);self.top()
        self.assertEqual('A',self.kernel.mana_payment['actor'])
        self.state.add_mana('A',('C','B'));self.pay({'C':1,'B':1})
        self.assertFalse(self.state.get(self.returned).tapped);self.assertEqual((),self.state.mana_pool('A'))

    def test_dance_decline_and_ordinary_untap_effect(self):
        self.reanimate();self.next_upkeep('A');self.top();self.pay()
        self.assertTrue(self.state.get(self.returned).tapped)
        self.effect(self.returned,SetTapped('source',False))
        self.assertFalse(self.state.get(self.returned).tapped)

    def test_dance_uses_enchanted_creature_controller_for_upkeep_and_payment(self):
        self.reanimate();self.state.change_control(self.returned,'B');self.next_upkeep('B');self.top()
        self.assertEqual('B',self.kernel.mana_payment['actor'])
        self.assertEqual('A',self.kernel.resolving['controller'])
        self.state.add_mana('B',('C','B'));self.pay({'C':1,'B':1})
        self.assertFalse(self.state.get(self.returned).tapped)

    def test_dance_does_not_trigger_on_aura_controllers_unrelated_upkeep(self):
        self.reanimate();self.state.change_control(self.returned,'B')
        self.kernel.begin_step('A','upkeep');self.assertFalse(self.kernel.stack)

    def test_dance_departure_sacrifices_current_creature_controller(self):
        self.reanimate();self.state.change_control(self.returned,'B')
        self.effect(self.source,Move('source',Zone.GRAVEYARD));self.top()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('grave')).zone)
        self.assertEqual('B',self.state.get(self.state.current('grave')).owner)

    def test_dance_cannot_attach_to_a_different_creature(self):
        self.reanimate();self.effect(self.source,Attach('source','source'))
        self.assertEqual(self.returned,self.state.get(self.source).attached_to)
        self.assertFalse(self.kernel._attachment_legal(self.state.get(self.source),self.other))

    def test_dance_early_departure_does_not_return_the_graveyard_card(self):
        self.game('dance-of-the-dead',zone=Zone.HAND)
        grave=self.state.add_card('grave','u-body','B',Zone.GRAVEYARD)
        self.cast(self.source,targets=(grave,),mana='CB');self.top()
        self.response(targets=(self.state.current('source'),));self.top();self.top()
        self.assertEqual(grave,self.state.current('grave'));self.assertEqual(Zone.GRAVEYARD,self.state.get(grave).zone)

    def test_dance_replacement_prevents_return_without_leaving_an_illegal_aura(self):
        redirect=CardProgram('redirect','Redirect',('Artifact',),replacements=(
            ZoneReplacement('redirect',Zone.BATTLEFIELD,Zone.EXILE,from_zone=Zone.GRAVEYARD,types=('Creature',)),))
        self.game('dance-of-the-dead',zone=Zone.HAND,extra=(redirect,))
        self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD)
        grave=self.state.add_card('grave','u-body','B',Zone.GRAVEYARD)
        self.cast(self.source,targets=(grave,),mana='CB');self.top();self.top()
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('grave')).zone)
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('source')).zone)

    def test_dance_public_untap_rule_and_layer_evaluator_agree(self):
        self.reanimate()
        packet=RulesActorAdapter(self.kernel).packet('C')
        row=next(row for rows in packet['zones']['battlefield'].values() for row in rows if row['ref']==self.returned.to_json())
        self.assertTrue(row['untap_blocked'])
        expected=evaluate_exhaustive(self.state.objects(),self.kernel.definitions,
            life_totals={p:self.state.life(p) for p in self.state.players},
            starting_life_totals={p:self.state.starting_life(p) for p in self.state.players},
            live_players=self.state.live_players,life_lost_totals={p:0 for p in self.state.players})
        self.assertEqual(expected,self.kernel.characteristics())

    def test_dance_payment_checkpoint_and_actor_replay(self):
        self.reanimate();self.next_upkeep('A');self.top();self.state.add_mana('A',('C','B'))
        adapter=RulesActorAdapter(self.kernel);w=self.kernel.mana_payment
        adapter.submit('A',{'kind':'pay_mana','action_id':'pay','revision':self.kernel.revision,
            'request_id':w['id'],'payment':{'mana':{'C':1,'B':1},'taps':[]}})
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())

    def test_remora_cumulative_upkeep_adds_age_before_all_or_nothing_payment(self):
        self.game();self.state.add_counters(self.source,'age',2)
        self.kernel.begin_step('A','upkeep');self.top()
        self.assertEqual({'age':3},self.counts());self.assertEqual(3,self.kernel.mana_payment['mana']['generic'])
        self.state.add_mana('A',('C','C','C'));before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.pay({'C':2})
        self.assertEqual(before,self.kernel.snapshot());self.pay({'C':3})
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.source).zone)

    def test_remora_declined_cumulative_upkeep_sacrifices_source(self):
        self.game();self.kernel.begin_step('A','upkeep');self.top();self.pay()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('source')).zone)

    def test_remora_no_cumulative_upkeep_on_opponents_turn(self):
        self.game();self.kernel.begin_step('B','upkeep');self.assertFalse(self.kernel.stack)

    def test_remora_source_departure_before_cumulative_resolution_prevents_age_and_payment(self):
        self.game();self.kernel.begin_step('A','upkeep')
        self.response(targets=(self.source,));self.top()
        # The cast trigger resolves above removal, then the upkeep sees no source.
        self.pay();self.choose('no');self.top();self.top()
        self.assertIsNone(self.kernel.mana_payment)

    def test_remora_age_counter_replacement_sets_actual_cost(self):
        extra=CardProgram('double','Double',('Artifact',),counter_replacements=(
            CounterReplacement('double',Selector(Zone.BATTLEFIELD),kind='age',multiplier=2),))
        self.game(extra=(extra,));self.state.add_card('double','double','A',Zone.BATTLEFIELD)
        self.kernel.begin_step('A','upkeep');self.top()
        self.assertEqual({'age':2},self.counts());self.assertEqual(2,self.kernel.mana_payment['mana']['generic'])

    def test_remora_zero_age_after_prevention_still_offers_zero_payment(self):
        extra=CardProgram('prevent','Prevent',('Artifact',),counter_replacements=(
            CounterReplacement('prevent',Selector(Zone.BATTLEFIELD),kind='age',multiplier=0),))
        self.game(extra=(extra,));self.state.add_card('prevent','prevent','A',Zone.BATTLEFIELD)
        self.kernel.begin_step('A','upkeep');self.top();self.assertEqual(0,self.kernel.mana_payment['mana']['generic'])
        self.pay({});self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.source).zone)

    def test_remora_payment_is_frozen_while_mana_ability_changes_age_count(self):
        ability=ActivatedProgram('mana',CostSpec(),(AddMana(('C','C','C')),
            SelectAll(Selector(Zone.BATTLEFIELD,types=('Enchantment',)),(RemoveCounters('selected','age',10),))),mana_ability=True)
        extra=CardProgram('rock','Rock',('Artifact',),activated=(ability,))
        self.game(extra=(extra,));rock=self.state.add_card('rock','rock','A',Zone.BATTLEFIELD)
        self.state.add_counters(self.source,'age',2);self.kernel.begin_step('A','upkeep');self.top()
        self.kernel.commit_action(self.kernel.quote_activation(self.ident(),'A',rock,'mana'),Payment())
        self.assertEqual({},self.counts());self.assertEqual(3,self.kernel.mana_payment['mana']['generic'])
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs);w=restored.mana_payment
        self.pay({'C':3})
        restored.pay_resolution_mana('u-action-'+str(self.number),'A',w['id'],Payment((('C',3),)),revision=restored.revision)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())

    def test_remora_opponent_can_pay_four_to_prevent_draw(self):
        self.game();self.response('u-spell');self.top()
        self.assertEqual('B',self.kernel.mana_payment['actor'])
        self.state.add_mana('B',tuple('CCCC'));self.pay({'C':4})
        self.assertEqual(0,self.hand('A'));self.assertIsNone(self.kernel.pending_choice)

    def test_remora_unpaid_trigger_gives_controller_optional_draw(self):
        for take in ('yes','no'):
            with self.subTest(take=take):
                self.game();self.response('u-spell');self.top();self.pay();self.choose(take)
                self.assertEqual(1 if take=='yes' else 0,self.hand('A'))

    def test_remora_excludes_creature_and_artifact_creature_spells(self):
        for types in (('Creature',),('Artifact','Creature')):
            with self.subTest(types=types):
                extra=CardProgram('flash-body','Flash body',types,power=1,toughness=1,keywords=('flash',),cast=CastSpec(CostSpec()))
                self.game(extra=(extra,));self.response('flash-body')
                self.assertEqual(1,len(self.kernel.stack));self.assertFalse(self.kernel.pending_triggers)

    def test_remora_does_not_trigger_for_controllers_spell(self):
        self.game();ref=self.state.add_card('spell','u-spell','A',Zone.HAND);self.cast(ref)
        self.assertEqual(1,len(self.kernel.stack))

    def test_touch_entry_exile_is_optional_and_returns_immediately_on_departure(self):
        self.game('touch-the-spirit-realm',zone=Zone.HAND);self.kernel.enter(self.source)
        self.source=self.state.current('source');self.targets((self.body,));self.top()
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('body')).zone)
        self.effect(self.source,Move('source',Zone.GRAVEYARD))
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('body')).zone);self.assertFalse(self.kernel.stack)

    def test_touch_entry_early_departure_does_not_exile(self):
        self.game('touch-the-spirit-realm',zone=Zone.HAND);self.kernel.enter(self.source)
        self.source=self.state.current('source');self.targets((self.body,))
        self.response(targets=(self.source,));self.top();self.top()
        self.assertEqual(self.body,self.state.current('body'))

    def test_touch_channel_discards_as_cost_and_returns_to_owner_next_end_step(self):
        self.game('touch-the-spirit-realm',zone=Zone.HAND);self.state.change_control(self.body,'A')
        self.channel();self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('source')).zone)
        self.assertEqual((),self.state.mana_pool('A'));self.top()
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('body')).zone)
        self.next_upkeep('A');self.advance_to('end_step');self.top()
        obj=self.state.get(self.state.current('body'))
        self.assertEqual(Zone.BATTLEFIELD,obj.zone);self.assertEqual('B',obj.controller)

    def test_touch_channel_created_during_end_step_waits_until_a_later_end_step(self):
        self.game('touch-the-spirit-realm',zone=Zone.HAND);self.next_upkeep('A');self.advance_to('end_step')
        self.channel();self.top();self.assertEqual(1,len(self.kernel.delayed_triggers))
        for _ in range(4):self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual('B',self.kernel.active)
        self.advance_to('end_step');self.top()
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('body')).zone)

    def test_touch_channel_illegal_target_spends_cost_without_delayed_return(self):
        self.game('touch-the-spirit-realm',zone=Zone.HAND);self.channel()
        self.response(targets=(self.body,));self.top();self.top()
        self.assertFalse(self.kernel.delayed_triggers);self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('source')).zone)

    def test_touch_channel_countered_ability_keeps_discard_paid(self):
        self.game('touch-the-spirit-realm',zone=Zone.HAND);self.channel()
        self.response('u-stifle');self.top()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('source')).zone)
        self.assertEqual(self.body,self.state.current('body'));self.assertFalse(self.kernel.delayed_triggers)

    def test_touch_delayed_return_does_not_follow_a_changed_exile_incarnation(self):
        self.game('touch-the-spirit-realm',zone=Zone.HAND);self.channel();self.top()
        ref=self.state.current('body');self.state.move((ZoneMove(ref,Zone.GRAVEYARD,'B'),),'fixture')
        self.state.move((ZoneMove(self.state.current('body'),Zone.EXILE,'B'),),'fixture')
        current=self.state.current('body');self.next_upkeep('A');self.advance_to('end_step');self.top()
        self.assertEqual(current,self.state.current('body'));self.assertEqual(Zone.EXILE,self.state.get(current).zone)

    def test_touch_delayed_return_checkpoint_and_public_channel_replay(self):
        self.game('touch-the-spirit-realm',zone=Zone.HAND);self.channel()
        packet=RulesActorAdapter(self.kernel).packet('B')
        self.assertEqual('channel',packet['stack'][0]['ability_id']);self.assertEqual('Touch the Spirit Realm',packet['stack'][0]['name'])
        self.assertEqual([],packet['revealed_hand']);self.assertNotIn('library-A-11',json.dumps(packet))
        adapter=RulesActorAdapter(self.kernel)
        for _ in self.state.live_players:adapter.submit(self.kernel.priority,{'kind':'pass','revision':self.kernel.revision})
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs);self.assertEqual(1,len(restored.delayed_triggers))

    def test_hidden_activation_reveal_lasts_only_for_exact_live_ability(self):
        card=CardProgram('hand-ability','Hand ability',('Artifact',),activated=(
            ActivatedProgram('wait',CostSpec(),(),zone=Zone.HAND),))
        self.game('arcane-denial',extra=(card,));ref=self.state.add_card('revealed','hand-ability','A',Zone.HAND)
        hidden=self.state.add_card('hidden','u-body','A',Zone.HAND);adapter=RulesActorAdapter(self.kernel)
        self.kernel.commit_action(self.kernel.quote_activation(self.ident(),'A',ref,'wait'),Payment())
        packet=adapter.packet('B');self.assertEqual([ref.to_json()],[r['ref'] for r in packet['revealed_hand']])
        self.assertEqual(ref,adapter._visible_ref(ref.to_json(),'B'))
        with self.assertRaises(RulesViolation):adapter._visible_ref(hidden.to_json(),'B')
        self.top();self.assertEqual([],adapter.packet('B')['revealed_hand'])
        with self.assertRaises(RulesViolation):adapter._visible_ref(ref.to_json(),'B')

    def test_denial_normal_cost_counters_then_defers_both_draws(self):
        ref=self.denial();self.assertEqual(Zone.GRAVEYARD,self.state.get(ref).zone)
        self.assertEqual(0,self.hand('A'));self.assertEqual(0,self.hand('B'))
        self.assertEqual(2,len(self.kernel.delayed_triggers));self.assertEqual((),self.state.mana_pool('A'))
        self.kernel.begin_step('A','upkeep')
        self.assertFalse(self.kernel.stack);self.assertEqual(2,len(self.kernel.delayed_triggers))

    def test_denial_next_turn_has_two_independent_delayed_triggers(self):
        self.denial();self.next_upkeep('B');self.assertEqual(2,len(self.kernel.stack))
        self.top();self.assertEqual(1,self.hand('A'));self.top()
        self.assertEqual('B',self.kernel.pending_choice.actor);self.choose('2')
        self.assertEqual(2,self.hand('B'));self.assertFalse(self.kernel.delayed_triggers)

    def test_denial_target_controller_can_choose_zero_one_or_two_before_drawing(self):
        for amount in range(3):
            with self.subTest(amount=amount):
                self.denial();self.next_upkeep('C');self.top();self.top()
                self.assertEqual(0,self.hand('B'));self.choose(str(amount));self.assertEqual(amount,self.hand('B'))

    def test_denial_can_target_own_spell_and_keep_both_benefits(self):
        self.denial('A');self.next_upkeep('B');self.top();self.top();self.choose('2')
        self.assertEqual(3,self.hand('A'));self.assertEqual(0,self.hand('B'))

    def test_denial_illegal_target_creates_neither_delayed_trigger(self):
        self.game('arcane-denial',zone=Zone.HAND);target=self.state.add_card('target','u-spell','B',Zone.HAND)
        self.cast(target,'B');self.cast(self.source,targets=(self.state.current('target'),),mana='CU')
        self.state.move((ZoneMove(self.state.current('target'),Zone.GRAVEYARD,'B'),),'fixture')
        self.top();self.assertFalse(self.kernel.delayed_triggers)

    def test_denial_delayed_draw_uses_captured_controller_after_source_moves(self):
        self.denial()
        source=self.state.current('source')
        self.state.move((ZoneMove(source,Zone.HAND,'A'),),'fixture')
        self.next_upkeep('D');self.top();self.top();self.choose('1')
        self.assertEqual(1,self.hand('B'));self.assertEqual(2,self.hand('A'))

    def test_denial_delay_and_draw_choice_restore_and_actor_replay(self):
        self.denial();restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.next_upkeep('B');self.top();self.top();adapter=RulesActorAdapter(self.kernel);q=self.kernel.pending_choice
        adapter.submit('B',{'kind':'answer','request_id':q.request_id,'revision':self.kernel.revision,'indexes':[2]})
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())

    def test_repeated_payment_and_delay_codec_reject_unsupported_shapes(self):
        invalid=(PayRepeatedMana(ManaCost(1),(),repetitions=-1),
                 PayRepeatedMana(ManaCost(1),(),repetitions=True),
                 PayRepeatedMana(ManaCost(1),(),repetitions=ChosenX()),
                 DelayedNextStep(EventPattern('step_began',step='draw'),()),
                 DelayedNextStep(EventPattern('step_began',step='upkeep'),(),next_turn=1),
                 DrawUpTo(101),DrawUpTo(True),DrawUpTo(2,players='opponents'))
        for effect in invalid:
            with self.subTest(effect=effect),self.assertRaises(RulesViolation):
                validate(CardProgram('bad','Bad',('Instant',),spell_effects=(effect,)))

    def test_spell_exclusion_and_attached_upkeep_filters_are_strict(self):
        for event in (SpellEventPattern('zone_changed',excluded_types=('Creature',)),
                      EventPattern('step_began',step='end_step',subject='attached'),
                      EventPattern('step_began',step='upkeep',subject='attached',controller_only=True)):
            with self.subTest(event=event),self.assertRaises(RulesViolation):
                validate(CardProgram('bad','Bad',('Enchantment',),abilities=(AbilityProgram('bad',event,()),)))

    def test_touch_countered_delayed_return_is_consumed_once(self):
        self.game('touch-the-spirit-realm',zone=Zone.HAND);self.channel();self.top()
        self.next_upkeep('A');self.advance_to('end_step')
        self.response('u-stifle');self.top()
        self.assertFalse(self.kernel.delayed_triggers);self.assertFalse(self.kernel.stack)
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('body')).zone)

    def test_hidden_reveal_does_not_follow_card_into_new_hand_incarnation(self):
        card=CardProgram('hand-ability','Hand ability',('Artifact',),activated=(
            ActivatedProgram('wait',CostSpec(),(),zone=Zone.HAND),))
        self.game('arcane-denial',extra=(card,));ref=self.state.add_card('revealed','hand-ability','A',Zone.HAND)
        self.kernel.commit_action(self.kernel.quote_activation(self.ident(),'A',ref,'wait'),Payment())
        self.state.move((ZoneMove(ref,Zone.GRAVEYARD,'A'),),'fixture')
        self.state.move((ZoneMove(self.state.current('revealed'),Zone.HAND,'A'),),'fixture')
        adapter=RulesActorAdapter(self.kernel)
        self.assertEqual([],adapter.packet('B')['revealed_hand'])
        with self.assertRaises(RulesViolation):adapter._visible_ref(self.state.current('revealed').to_json(),'B')
        self.assertEqual(self.kernel.snapshot(),RulesKernel.restore(self.kernel.snapshot(),self.programs).snapshot())

    def test_touch_token_exile_does_not_recreate_it_at_end_step(self):
        token=CardProgram('u-token','Token',('Creature',),power=1,toughness=1)
        maker=CardProgram('u-maker','Maker',('Sorcery',),spell_effects=(CreateTokens(token),))
        self.game('touch-the-spirit-realm',zone=Zone.HAND,extra=(maker,))
        self.effect(self.other,CreateTokens(token))
        ref=next(obj.ref for obj in self.state.objects(Zone.BATTLEFIELD) if obj.token)
        self.channel(ref);self.top();self.next_upkeep('A');self.advance_to('end_step');self.top()
        self.assertFalse(any(obj.token for obj in self.state.objects()))

    def test_delayed_step_requires_explicit_capture_instead_of_parent_targets_or_x(self):
        for effect in (Move('target',Zone.HAND),Draw(ChosenX())):
            with self.subTest(effect=effect),self.assertRaises(RulesViolation):
                validate(CardProgram('bad','Bad',('Instant',),cast=CastSpec(CostSpec(ManaCost(x_symbols=1)),timing='instant'),
                    spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD)),
                    spell_effects=(DelayedNextStep(EventPattern('step_began',step='end_step'),(effect,)),)))

        with self.assertRaises(RulesViolation):
            validate(CardProgram('bad-player','Bad player',('Instant',),
                spell_targets=TargetSpec(players='any'),
                spell_effects=(DelayedNextStep(EventPattern('step_began',step='upkeep'),
                    (Draw(1,players='target'),)),)))

    def test_new_kernel_layout_rejects_previous_checkpoint_without_state_migration(self):
        self.game();checkpoint=self.kernel.snapshot()
        self.assertEqual(118,checkpoint['schema']);self.assertEqual(13,checkpoint['state']['schema'])
        restored=RulesKernel.restore(checkpoint,self.programs);self.assertEqual(checkpoint,restored.snapshot())
        checkpoint['schema']=117
        with self.assertRaises(RulesViolation):RulesKernel.restore(checkpoint,self.programs)


if __name__=='__main__':unittest.main()
