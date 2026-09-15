"""Escape/flashback declarations, exact payments, stack departures and printed cards."""
import json
import unittest
from dataclasses import replace
from pathlib import Path

from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState, Zone, ZoneMove, RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment, PreparedAction
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed, source_facts, digest
from edh_gauntlet.catalog import load_catalog


class GraveyardCastingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        cls.reviewed=load_reviewed(cls.root)
        cls.rows={key:cls.reviewed[key]['review'] for key in ('uro-titan-of-nature-s-wrath','bulk-up')}
        cls.cards={key:cls.reviewed[key]['program'] for key in cls.rows}
        cls.base=tuple(r['program'] for r in cls.reviewed.values())

    def game(self,key='bulk-up',zone=Zone.GRAVEYARD,*,power=3,extra=(),players=('A','B')):
        self.key=key;self.program=self.cards[key]
        body=CardProgram('body','Body',('Creature',),power=power,toughness=5)
        self.programs=self.base+(body,)+extra
        self.state=RulesState(players)
        self.source=self.state.add_card('spell',self.program.definition_id,'A',zone)
        self.body=self.state.add_card('body','body','A',Zone.BATTLEFIELD)
        self.fuel=tuple(self.state.add_card('fuel-'+str(i),'catalog:forest','A',Zone.GRAVEYARD) for i in range(5))
        for i in range(6):self.state.add_card('draw-'+str(i),'catalog:island','A',Zone.LIBRARY)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def pay(self,alternative=True):
        if self.key=='bulk-up':return Payment((('C',4),('R',2)) if alternative else (('C',1),('R',1)))
        return Payment((('G',2),('U',2)),zone_costs=(('escape',self.fuel),)) if alternative else Payment((('C',1),('G',1),('U',1)))

    def cast(self,alternative=True,action_id='cast'):
        payment=self.pay(alternative)
        for symbol,count in payment.mana:self.state.add_mana('A',(symbol,)*count)
        quote=self.kernel.quote_cast(action_id,'A',self.state.current('spell'),
            (self.body,) if self.key=='bulk-up' else (),
            alternative_id=('flashback' if self.key=='bulk-up' else 'escape') if alternative else None)
        return self.kernel.commit_action(quote,payment)

    def settle(self,land=None):
        for _ in range(100):
            request=self.kernel.pending_choice
            if request:
                if request.kind=='trigger_order':indexes=list(range(len(request.options)))
                elif request.kind=='selection':indexes=[] if land is None else [next(i for i,o in enumerate(request.options) if o.ref.card_id==land)]
                else:self.fail('Unexpected choice '+request.kind)
                self.kernel.answer(request.request_id,request.actor,indexes)
            elif self.kernel.stack or self.kernel.resolving is not None:self.kernel.pass_priority(self.kernel.priority)
            else:return
        self.fail('Fixture did not settle')

    def current(self,key='spell'):return self.state.get(self.state.current(key))

    def test_complete_source_facts_and_codec(self):
        catalog={c.card_id:c for c in load_catalog(self.root/'data/catalog/cards.json')}
        for key,p in self.cards.items():
            self.assertEqual(digest(source_facts(catalog[key])),self.rows[key]['source_facts_sha256'])
            self.assertEqual(p,validate(decode(encode(p))))
            self.assertEqual((Zone.HAND,Zone.COMMAND),p.cast.origin_zones)
            self.assertIsInstance(p.cast.alternatives[0],GraveyardAlternativeCost)

    def test_escape_pays_five_other_cards_and_retains_normal_mana_value(self):
        self.game('uro-titan-of-nature-s-wrath');self.cast()
        self.assertEqual((),self.state.mana_pool('A'));self.assertEqual(Zone.STACK,self.current().zone)
        self.assertEqual(3,self.kernel.effective(self.current().ref).mana_value)
        self.assertTrue(all(self.state.get(self.state.current(r.card_id)).zone==Zone.EXILE for r in self.fuel))
        self.settle();self.assertEqual(Zone.BATTLEFIELD,self.current().zone)
        self.assertEqual(frozenset({'escaped'}),self.current().entry_flags)
        self.assertEqual(43,self.state.life('A'));self.assertEqual(1,len(self.state.objects(Zone.HAND,owner='A')))

    def test_normal_uro_sacrifices_but_still_gains_draws_and_may_put_land(self):
        self.game('uro-titan-of-nature-s-wrath',Zone.HAND)
        self.state.add_card('land','catalog:island','A',Zone.HAND)
        self.cast(False);self.settle('land')
        self.assertEqual(Zone.GRAVEYARD,self.current().zone);self.assertEqual(43,self.state.life('A'))
        self.assertEqual(Zone.BATTLEFIELD,self.current('land').zone)
        self.assertTrue(all(self.state.get(r).zone==Zone.GRAVEYARD for r in self.fuel))

    def test_escape_and_flashback_do_not_grant_normal_graveyard_casting(self):
        for key in self.cards:
            self.game(key)
            before=self.kernel.snapshot()
            with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',self.source,(self.body,) if key=='bulk-up' else ())
            self.assertEqual(before,self.kernel.snapshot())

    def test_graveyard_alternatives_are_unavailable_from_hand_exile_and_command(self):
        for key in self.cards:
            for zone in (Zone.HAND,Zone.EXILE,Zone.COMMAND):
                self.game(key,zone);before=self.kernel.snapshot()
                with self.assertRaises(RulesViolation):
                    self.kernel.quote_cast('bad','A',self.source,(self.body,) if key=='bulk-up' else (),
                        alternative_id='flashback' if key=='bulk-up' else 'escape')
                self.assertEqual(before,self.kernel.snapshot())

    def test_escape_preserves_timing_and_ownership_restrictions(self):
        self.game('uro-titan-of-nature-s-wrath')
        self.kernel.open_window_for_scenario('B',priority_actor='A')
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('wrong-turn','A',self.source,alternative_id='escape')
        self.kernel.open_window_for_scenario('A',priority_actor='B')
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('wrong-owner','B',self.source,alternative_id='escape')

    def test_escape_selection_and_mana_errors_are_atomic(self):
        self.game('uro-titan-of-nature-s-wrath');self.state.add_mana('A',('G','G','U','U'))
        foreign=self.state.add_card('foreign','catalog:island','B',Zone.GRAVEYARD)
        hand=self.state.add_card('hand','catalog:island','A',Zone.HAND)
        quote=self.kernel.quote_cast('cast','A',self.source,alternative_id='escape');before=self.kernel.snapshot()
        for refs in (self.fuel[:4],self.fuel+(foreign,),self.fuel[:4]+(self.fuel[0],),
                     self.fuel[:4]+(self.source,),self.fuel[:4]+(foreign,),self.fuel[:4]+(hand,)):
            with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,Payment(self.pay().mana,zone_costs=(('escape',refs),)))
            self.assertEqual(before,self.kernel.snapshot())
        for payment in (Payment(self.pay().mana),Payment(zone_costs=(('escape',self.fuel),)),Payment((('G',4),),zone_costs=(('escape',self.fuel),))):
            with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,payment)
            self.assertEqual(before,self.kernel.snapshot())

    def test_quote_roundtrip_and_stale_graveyard_selection(self):
        self.game('uro-titan-of-nature-s-wrath');self.state.add_mana('A',('G','G','U','U'))
        before=self.kernel.snapshot();quote=self.kernel.quote_cast('cast','A',self.source,alternative_id='escape')
        self.assertEqual(before,self.kernel.snapshot());self.assertEqual(quote,PreparedAction.from_json(quote.to_json()))
        self.state.move((ZoneMove(self.fuel[0],Zone.HAND,'A'),),'fixture')
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,self.pay())
        self.assertEqual(before,self.kernel.snapshot())

    def test_escape_replacement_choices_checkpoint_and_actor_replay_pay_once(self):
        redirect=CardProgram('redirect','Optional exile redirect',('Enchantment',),replacements=(
            ZoneReplacement('redirect',Zone.EXILE,Zone.HAND,from_zone=Zone.GRAVEYARD,optional=True),))
        self.game('uro-titan-of-nature-s-wrath',extra=(redirect,))
        self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD);self.state.add_mana('A',('G','G','U','U'))
        self.state.add_card('private','catalog:counterspell','A',Zone.HAND)
        adapter=RulesActorAdapter(self.kernel)
        adapter.submit('A',{'kind':'cast','revision':self.kernel.revision,'action_id':'escape','source':self.source.to_json(),
            'targets':[],'x_value':0,'alternative_id':'escape','payment':{'mana':{'G':2,'U':2},'taps':[],'zone_costs':{'escape':[r.to_json() for r in self.fuel]}}})
        self.assertIsNotNone(self.kernel.announcement);self.assertEqual(Zone.STACK,self.current().zone)
        public=adapter.packet('B')
        self.assertNotIn('private',json.dumps(public))
        self.assertNotIn('payment',public['announcement'])
        self.assertEqual((('G',2),('U',2)),self.state.mana_pool('A'))
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        while self.kernel.pending_choice:
            q=self.kernel.pending_choice
            self.assertEqual('replacement_optional',q.kind)
            indexes=[next(i for i,o in enumerate(q.options) if o.key=='no')]
            adapter.submit(q.actor,{'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':indexes})
            restored.answer(restored.pending_choice.request_id,q.actor,indexes)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())
        self.assertEqual(1,len([e for e in self.kernel.semantic_events if e['kind']=='spell_cast']))
        self.assertEqual(1,len([e for e in self.kernel.semantic_events if e['kind']=='costs_paid']))
        self.assertEqual((),self.state.mana_pool('A'))

    def test_countered_escape_keeps_payment_and_goes_to_graveyard(self):
        self.game('uro-titan-of-nature-s-wrath');self.cast()
        counter=self.state.add_card('counter','catalog:counterspell','B',Zone.HAND);self.state.add_mana('B',('U','U'))
        self.kernel.pass_priority('A')
        self.kernel.commit_action(self.kernel.quote_cast('counter','B',counter,(self.current().ref,)),Payment((('U',2),)))
        self.settle();self.assertEqual(Zone.GRAVEYARD,self.current().zone);self.assertEqual(40,self.state.life('A'))
        self.assertTrue(all(self.current(r.card_id).zone==Zone.EXILE for r in self.fuel))

    def test_blink_resets_escaped_entry_fact_and_new_uro_is_sacrificed(self):
        blink=CardProgram('blink','Blink',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD,('Creature',))),
            spell_effects=(WithMoved('target',Zone.EXILE,(Move('moved',Zone.BATTLEFIELD,controller='owner'),)),))
        self.game('uro-titan-of-nature-s-wrath',extra=(blink,));self.cast();self.settle()
        old=self.current().ref;self.kernel.open_window_for_scenario('A')
        ref=self.state.add_card('blink','blink','A',Zone.HAND)
        self.kernel.commit_action(self.kernel.quote_cast('blink','A',ref,(old,)),Payment());self.settle()
        self.assertEqual(Zone.GRAVEYARD,self.current().zone);self.assertEqual(46,self.state.life('A'))

    def test_uro_attack_trigger_uses_real_declaration_and_does_not_sacrifice(self):
        self.game('uro-titan-of-nature-s-wrath');self.cast();self.settle()
        self.kernel.begin_turn_for_scenario('A')
        for _ in range(30):
            if self.kernel.phase=='declare_attackers' and self.kernel.priority is None:break
            self.kernel.pass_priority(self.kernel.priority)
        else:self.fail('No attacker boundary')
        before=len(self.state.objects(Zone.HAND,owner='A'))
        self.kernel.declare_attackers('A',{self.current().ref:'B'},revision=self.kernel.revision)
        while self.kernel.stack or self.kernel.resolving or self.kernel.pending_choice:
            q=self.kernel.pending_choice
            if q:self.kernel.answer(q.request_id,q.actor,[])
            else:self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual(46,self.state.life('A'));self.assertEqual(before+1,len(self.state.objects(Zone.HAND,owner='A')))
        self.assertEqual(Zone.BATTLEFIELD,self.current().zone)

    def test_bulk_up_normal_and_flashback_resolve_to_different_zones(self):
        for alternative in (False,True):
            self.game(zone=Zone.GRAVEYARD if alternative else Zone.HAND);self.cast(alternative);self.settle()
            self.assertEqual(6,self.kernel.effective(self.body).power);self.assertEqual(5,self.kernel.effective(self.body).toughness)
            self.assertEqual(Zone.EXILE if alternative else Zone.GRAVEYARD,self.current().zone)

    def test_bulk_up_uses_power_at_resolution_including_negative_and_zero(self):
        for power in (-3,0,5):
            self.game(power=power);self.cast();self.state.add_counters(self.body,'+1/+1',1);self.settle()
            self.assertEqual((power+1)*2,self.kernel.effective(self.body).power)

    def test_bulk_up_modifier_is_frozen_and_expires_at_cleanup(self):
        self.game();self.cast();self.settle();self.state.add_counters(self.body,'+1/+1',2)
        self.assertEqual(8,self.kernel.effective(self.body).power)
        self.kernel._finish_cleanup_actions()
        self.assertEqual(5,self.kernel.effective(self.body).power)

    def test_flashback_illegal_target_is_exiled_without_effect(self):
        self.game();self.cast()
        self.state.move((ZoneMove(self.body,Zone.HAND,'A'),),'fixture')
        self.settle();self.assertEqual(Zone.EXILE,self.current().zone)
        self.assertTrue(any(e['kind']=='all_targets_illegal' for e in self.kernel.semantic_events))

    def test_flashback_counter_and_return_to_hand_both_exile_exact_spell(self):
        for operation in (Counter(),Counter(destination=Zone.HAND),Move('target',Zone.HAND),Move('target',Zone.LIBRARY,library_position='top')):
            answer=CardProgram('answer','Stack interaction',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
                spell_targets=TargetSpec(Selector(Zone.STACK)),spell_effects=(operation,))
            self.game(extra=(answer,));self.cast()
            self.kernel.pass_priority('A');ref=self.state.add_card('answer','answer','B',Zone.HAND)
            self.kernel.commit_action(self.kernel.quote_cast('answer','B',ref,(self.current().ref,)),Payment())
            self.settle();self.assertEqual(Zone.EXILE,self.current().zone);self.assertEqual(3,self.kernel.effective(self.body).power)

    def test_flashback_checkpoint_preserves_stack_departure_replacement(self):
        self.game();self.cast();restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.settle()
        for _ in range(2):restored.pass_priority(restored.priority)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())

    def test_graveyard_costs_obey_global_prohibitions_and_cost_modifiers(self):
        for key in self.cards:
            modifier=CardProgram('tax','Tax',('Enchantment',),cost_modifiers=(CostModifier('tax',Selector(Zone.STACK),2),))
            self.game(key,extra=(modifier,));self.state.add_card('tax','tax','B',Zone.BATTLEFIELD)
            alt='flashback' if key=='bulk-up' else 'escape'
            q=self.kernel.quote_cast('cast','A',self.source,(self.body,) if key=='bulk-up' else (),alternative_id=alt)
            self.assertEqual((4 if key=='bulk-up' else 0)+2,q.cost.mana.generic)
            cage=CardProgram('cage','Cage',('Artifact',),casting_restrictions=(CastRestriction(Selector(Zone.STACK),(Zone.GRAVEYARD,)),))
            self.game(key,extra=(cage,));self.state.add_card('cage','cage','B',Zone.BATTLEFIELD)
            with self.assertRaises(RulesViolation):self.kernel.quote_cast('cast','A',self.source,(self.body,) if key=='bulk-up' else (),alternative_id=alt)

    def test_compiler_rejects_unsupported_graveyard_cost_shapes_and_facts(self):
        uro=self.cards['uro-titan-of-nature-s-wrath'];alt=uro.cast.alternatives[0];zc=alt.cost.zone_costs[0]
        invalid=(replace(alt,cost=replace(alt.cost,zone_costs=(replace(zc,selector=None),))),
            replace(alt,cost=replace(alt.cost,zone_costs=(replace(zc,selector=replace(zc.selector,exclude_source=False)),))),
            replace(alt,cost=replace(alt.cost,zone_costs=(replace(zc,kind='sacrifice'),))),
            replace(alt,exile_on_stack_exit=True),replace(alt,entry_flags=('escaped','escaped')),
            replace(alt,entry_flags='escaped'),replace(alt,exile_on_stack_exit=1))
        for bad in invalid:
            with self.assertRaises(RulesViolation):validate(replace(uro,cast=replace(uro.cast,alternatives=(bad,))))
        bulk=self.cards['bulk-up']
        with self.assertRaises(RulesViolation):
            validate(replace(bulk,cast=replace(bulk.cast,alternatives=(replace(bulk.cast.alternatives[0],entry_flags=('escaped',)),))))

    def test_actor_projection_marks_flashback_only_on_the_paid_stack_incarnation(self):
        self.game();self.cast();packet=RulesActorAdapter(self.kernel).packet('B')
        self.assertTrue(packet['stack'][0]['exile_on_stack_exit'])
        self.game(zone=Zone.HAND);self.cast(False);packet=RulesActorAdapter(self.kernel).packet('B')
        self.assertNotIn('exile_on_stack_exit',packet['stack'][0])

    def test_uro_trigger_controller_cannot_sacrifice_uro_after_an_opponent_gains_it(self):
        self.game('uro-titan-of-nature-s-wrath',Zone.HAND);self.cast(False)
        self.kernel.pass_priority(self.kernel.priority);self.kernel.pass_priority(self.kernel.priority)
        q=self.kernel.pending_choice;self.assertEqual('trigger_order',q.kind)
        self.kernel.answer(q.request_id,q.actor,list(range(len(q.options))))
        self.state.change_control(self.current().ref,'B');self.settle()
        self.assertEqual(Zone.BATTLEFIELD,self.current().zone);self.assertEqual('B',self.current().controller)
        self.assertEqual(43,self.state.life('A'));self.assertEqual(40,self.state.life('B'))

    def test_flashback_fact_does_not_follow_the_card_into_a_later_normal_cast(self):
        self.game();self.cast();self.settle()
        self.state.move((ZoneMove(self.current().ref,Zone.HAND,'A'),),'fixture-return')
        self.kernel.open_window_for_scenario('A');self.cast(False,action_id='normal');self.settle()
        self.assertEqual(Zone.GRAVEYARD,self.current().zone);self.assertEqual(12,self.kernel.effective(self.body).power)
