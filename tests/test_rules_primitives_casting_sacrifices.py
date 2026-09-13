"""Source-bound Crop Rotation/Fling and accepted sacrifice-cost transactions."""
import json
import unittest
from dataclasses import replace
from pathlib import Path

from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState, Zone, ZoneMove, PlayerRef, RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment, PreparedAction
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed, digest, source_facts
from edh_gauntlet.catalog import load_catalog


class CastingSacrificeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        cls.reviewed=load_reviewed(cls.root)
        cls.cards={key:cls.reviewed[key]['program'] for key in ('crop-rotation','fling')}
        cls.rows={key:cls.reviewed[key]['review'] for key in cls.cards}
        cls.base=tuple(r['program'] for r in cls.reviewed.values())

    def game(self,key='fling',*,body=None,extra=(),owner='A',token=False,spell=None):
        self.card=spell or self.cards[key];self.key=key
        body=body or CardProgram('cost-body','Cost body',('Creature',),power=4,toughness=5)
        self.programs=self.base+(body,)+tuple(extra)+((spell,) if spell else ())
        self.state=RulesState(('A','B'))
        self.source=self.state.add_card('spell',self.card.definition_id,'A',Zone.HAND)
        self.body=self.state.add_card('paid','catalog:forest' if key=='crop-rotation' else body.definition_id,owner,Zone.BATTLEFIELD,controller='A',token=token)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
        self.state.add_mana('A',('G',) if key=='crop-rotation' else ('C','R'))
        self.cost_id=self.card.cast.cost.zone_costs[0].cost_id

    def quote(self,targets=None,action_id='cast',**kwargs):
        if targets is None:targets=() if self.key=='crop-rotation' else (PlayerRef('B'),)
        return self.kernel.quote_cast(action_id,'A',self.source,targets,**kwargs)

    def payment(self,refs=None,mana=None):
        return Payment(tuple(mana) if mana is not None else (('G',1),) if self.key=='crop-rotation' else (('C',1),('R',1)),
            zone_costs=((self.cost_id,(self.body,) if refs is None else refs),))

    def cast(self,targets=None,payment=None,**kwargs):
        return self.kernel.commit_action(self.quote(targets,**kwargs),payment or self.payment())

    def resolve(self):
        self.kernel.pass_priority(self.kernel.priority)
        return self.kernel.pass_priority(self.kernel.priority)

    def drain(self):
        for _ in range(40):
            if self.kernel.pending_choice:self.fail('Unexpected unresolved choice')
            if not self.kernel.stack and self.kernel.resolving is None:return
            self.kernel.pass_priority(self.kernel.priority)
        self.fail('Fixture did not settle')

    def counter(self):
        counter=self.state.add_card('counter','catalog:counterspell','B',Zone.HAND)
        self.state.add_mana('B',('U','U'));self.kernel.pass_priority('A')
        self.kernel.commit_action(self.kernel.quote_cast('counter','B',counter,(self.state.current('spell'),)),Payment((('U',2),)))
        self.drain()

    def test_reviewed_programs_match_complete_printed_faces_and_source_bindings(self):
        catalog={c.card_id:c for c in load_catalog(self.root/'data/catalog/cards.json')}
        self.assertEqual({'crop-rotation','fling'},set(self.cards))
        for key,p in self.cards.items():
            with self.subTest(card=key):
                self.assertEqual('catalog:'+key,p.definition_id)
                self.assertEqual('all_printed_faces',self.rows[key]['scope']);self.assertTrue(self.rows[key]['review_basis'])
                self.assertEqual(self.rows[key]['program'],encode(p))
                self.assertEqual(digest(source_facts(catalog[key])),self.rows[key]['source_facts_sha256'])
                f=catalog[key].faces[0]
                for field in ('types','subtypes','supertypes','colors'):
                    self.assertEqual(set(getattr(f,field)),set(getattr(p,field)))
                for field in ('name','mana_value','power','toughness'):
                    self.assertEqual(getattr(f,field),getattr(p,field))
                self.assertEqual('instant',p.cast.timing)
                self.assertEqual(1,len(p.cast.cost.zone_costs));self.assertEqual(1,p.cast.cost.zone_costs[0].count)

    def test_crop_rotation_searches_any_land_and_preserves_its_entry_behavior(self):
        self.game('crop-rotation')
        for key in ('island','cinder-glade'):
            self.state.add_card(key,'catalog:'+key,'A',Zone.LIBRARY)
        self.state.add_card('not-land','catalog:counterspell','A',Zone.LIBRARY)
        self.cast();self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('paid')).zone)
        self.assertEqual(40,self.state.life('A'));self.assertEqual((),self.state.mana_pool('A'))
        request=self.resolve();self.assertEqual({'island','cinder-glade'},{o.ref.card_id for o in request.options})
        self.kernel.answer(request.request_id,'A',[next(i for i,o in enumerate(request.options) if o.ref.card_id=='cinder-glade')])
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('cinder-glade')).zone)
        self.assertTrue(self.state.get(self.state.current('cinder-glade')).tapped)
        self.assertEqual(1,self.state.snapshot()['shuffle_nonce'])

    def test_crop_rotation_can_fail_to_find_and_still_shuffles_without_disclosing_library(self):
        self.game('crop-rotation');self.state.add_card('private-land','catalog:island','A',Zone.LIBRARY)
        adapter=RulesActorAdapter(self.kernel)
        adapter.submit('A',{'kind':'cast','revision':self.kernel.revision,'action_id':'cast','source':self.source.to_json(),
            'targets':[],'x_value':0,'payment':{'mana':{'G':1},'taps':[],'zone_costs':{'land':[self.body.to_json()]}}})
        adapter.submit('A',{'kind':'pass','revision':self.kernel.revision})
        own=adapter.submit('B',{'kind':'pass','revision':self.kernel.revision})
        self.assertNotIn('private-land',json.dumps(own))
        request=self.kernel.pending_choice;self.assertEqual(0,request.minimum)
        adapter.submit('A',{'kind':'answer','revision':self.kernel.revision,'request_id':request.request_id,'indexes':[]})
        self.assertEqual(1,self.state.snapshot()['shuffle_nonce'])
        self.assertEqual(Zone.LIBRARY,self.state.get(self.state.current('private-land')).zone)
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())

    def test_crop_rotation_can_sacrifice_the_land_that_previously_produced_its_mana(self):
        self.game('crop-rotation');self.state.empty_mana_pools()
        self.kernel.commit_action(self.kernel.quote_activation('mana','A',self.body,'intrinsic-land:Forest'),Payment())
        self.assertTrue(self.state.get(self.body).tapped);self.assertEqual((('G',1),),self.state.mana_pool('A'))
        self.cast();self.assertEqual((),self.state.mana_pool('A'));self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('paid')).zone)
        self.assertEqual(1,self.state.snapshot()['shuffle_nonce'])

    def test_wrong_missing_extra_or_phased_sacrifices_and_bad_mana_are_atomic(self):
        for key in ('crop-rotation','fling'):
            with self.subTest(card=key):
                self.game(key)
                foreign=self.state.add_card('foreign','catalog:forest' if key=='crop-rotation' else 'cost-body','B',Zone.BATTLEFIELD)
                wrong=self.state.add_card('wrong','cost-body' if key=='crop-rotation' else 'catalog:forest','A',Zone.BATTLEFIELD)
                phased=self.state.add_card('phased','catalog:forest' if key=='crop-rotation' else 'cost-body','A',Zone.BATTLEFIELD)
                self.state.phase(phased,True)
                quote=self.quote();before=self.kernel.snapshot()
                for refs in ((),(self.body,self.body),(self.body,foreign),(foreign,),(wrong,),(phased,)):
                    with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,self.payment(refs))
                    self.assertEqual(before,self.kernel.snapshot())
                with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,Payment(self.payment().mana))
                with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,self.payment(mana=()))
                self.assertEqual(before,self.kernel.snapshot())

    def test_quote_is_pure_and_stale_payment_is_rejected_before_announcement(self):
        self.game();before=self.kernel.snapshot();quote=self.quote()
        self.assertEqual(before,self.kernel.snapshot())
        self.assertEqual(quote,PreparedAction.from_json(quote.to_json()))
        self.state.add_counters(self.body,'+1/+1',1);before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,self.payment())
        self.assertEqual(before,self.kernel.snapshot())

    def test_both_countered_spells_keep_their_sacrifice_and_mana_paid(self):
        for key in ('crop-rotation','fling'):
            with self.subTest(card=key):
                self.game(key);self.state.add_card('land','catalog:island','A',Zone.LIBRARY)
                self.cast();self.counter()
                self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('paid')).zone)
                self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('spell')).zone)
                self.assertEqual((),self.state.mana_pool('A'));self.assertEqual(40,self.state.life('B'))
                self.assertEqual(0,self.state.snapshot()['shuffle_nonce'])

    def test_fling_targets_players_creatures_planeswalkers_and_battles(self):
        for kind in ('opponent','self','Creature','Planeswalker','Battle'):
            with self.subTest(target=kind):
                recipient=CardProgram('recipient','Recipient',(kind,) if kind[0].isupper() else ('Artifact',),
                    power=9 if kind=='Creature' else None,toughness=9 if kind=='Creature' else None)
                self.game(extra=(recipient,))
                if kind in ('opponent','self'):target=PlayerRef('B' if kind=='opponent' else 'A')
                else:
                    target=self.state.add_card('recipient','recipient','B',Zone.BATTLEFIELD)
                    if kind in ('Planeswalker','Battle'):self.state.add_counters(target,'loyalty' if kind=='Planeswalker' else 'defense',9)
                self.cast((target,));self.drain()
                if isinstance(target,PlayerRef):self.assertEqual(36,self.state.life(target.player))
                elif kind=='Creature':self.assertEqual(4,self.state.get(target).damage_marked)
                else:self.assertEqual(5,dict(self.state.get(target).counters)['loyalty' if kind=='Planeswalker' else 'defense'])
                dealt=[e for e in self.kernel.semantic_events if e['kind']=='damage_dealt']
                self.assertEqual(1,len(dealt));self.assertEqual('spell',dealt[0]['source']['card_id'])

    def test_fling_uses_counters_and_continuous_power_before_sacrifice(self):
        anthem=CardProgram('anthem','Anthem',('Enchantment',),continuous=(ContinuousProgram('pump',
            Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled'),(ModifyPT(3,0),)),))
        self.game(extra=(anthem,));self.state.add_card('anthem','anthem','A',Zone.BATTLEFIELD)
        self.state.add_counters(self.body,'+1/+1',2);self.assertEqual(9,self.kernel.effective(self.body).power)
        self.cast()
        self.assertEqual(4,self.kernel.effective(self.state.current('paid')).power)
        self.assertEqual(9,self.kernel.stack[0]['values']['paid_cost_stats']['creature']['power'])
        self.drain();self.assertEqual(31,self.state.life('B'))

    def test_fling_retains_pre_departure_power_after_creature_reenters(self):
        self.game();self.state.add_counters(self.body,'+1/+1',2);self.cast()
        grave=self.state.current('paid')
        self.state.move((ZoneMove(grave,Zone.BATTLEFIELD,'B'),),'fixture-blink')
        self.state.add_counters(self.state.current('paid'),'+1/+1',20)
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.drain()
        for _ in range(2):restored.pass_priority(restored.priority)
        self.assertEqual(34,self.state.life('B'));self.assertEqual(self.kernel.snapshot(),restored.snapshot())

    def test_fling_retains_token_power_after_token_ceases_to_exist(self):
        self.game(token=True);self.state.add_counters(self.body,'+1/+1',3);self.cast()
        self.assertNotIn('paid',{obj.ref.card_id for obj in self.state.objects()})
        self.drain();self.assertEqual(33,self.state.life('B'))

    def test_fling_with_negative_power_deals_no_damage(self):
        self.game(body=CardProgram('negative','Negative',('Creature',),power=-3,toughness=5))
        self.cast();self.drain();self.assertEqual(40,self.state.life('B'))
        self.assertFalse(any(e['kind']=='damage_dealt' for e in self.kernel.semantic_events))

    def test_fling_does_not_inherit_sacrificed_creatures_damage_keywords(self):
        body=CardProgram('linked','Linked',('Creature',),power=4,toughness=5,keywords=('lifelink','deathtouch'))
        recipient=CardProgram('recipient','Recipient',('Creature',),power=8,toughness=8)
        self.game(body=body,extra=(recipient,));target=self.state.add_card('target','recipient','B',Zone.BATTLEFIELD)
        self.cast((target,));self.drain();self.assertEqual(40,self.state.life('A'))
        self.assertEqual(4,self.state.get(target).damage_marked);self.assertFalse(self.state.get(target).deathtouch_hit)

    def test_sacrifice_is_nontargeting_and_uses_controller_not_owner(self):
        for keyword in ('shroud','hexproof'):
            with self.subTest(keyword=keyword):
                body=CardProgram('protected','Protected',('Creature',),power=4,toughness=5,keywords=(keyword,))
                self.game(body=body,owner='B');self.cast();self.drain()
                self.assertEqual(['paid'],[o.ref.card_id for o in self.state.zone('B',Zone.GRAVEYARD)])
                self.assertEqual(36,self.state.life('B'))

    def test_sacrificing_fling_target_makes_it_illegal_without_refunding_costs(self):
        self.game();self.cast((self.body,));self.drain()
        self.assertEqual((),self.state.mana_pool('A'));self.assertEqual(40,self.state.life('B'))
        self.assertTrue(any(e['kind']=='all_targets_illegal' for e in self.kernel.semantic_events))
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('paid')).zone)

    def test_illegal_fling_target_rejects_before_sacrifice(self):
        recipient=CardProgram('protected','Protected',('Creature',),power=4,toughness=5,keywords=('hexproof',))
        self.game(extra=(recipient,));target=self.state.add_card('target','protected','B',Zone.BATTLEFIELD);before=self.kernel.snapshot()
        for targets in ((),(target,),(PlayerRef('A'),PlayerRef('B')),(self.source,)):
            with self.assertRaises(RulesViolation):self.cast(targets)
            self.assertEqual(before,self.kernel.snapshot())

    def test_pending_payment_exposes_spell_but_no_cast_event_or_priority(self):
        replacement=CardProgram('replacement','Replacement',('Enchantment',),
            replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,from_zone=Zone.BATTLEFIELD,optional=True),))
        self.game(extra=(replacement,));self.state.add_card('replacement','replacement','B',Zone.BATTLEFIELD)
        self.state.add_card('secret-hand','catalog:island','A',Zone.HAND)
        request=self.cast();self.assertIsNotNone(self.kernel.announcement)
        self.assertEqual(Zone.STACK,self.state.get(self.state.current('spell')).zone)
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.body).zone)
        self.assertEqual((('C',1),('R',1)),self.state.mana_pool('A'))
        self.assertFalse(self.kernel.action_receipts)
        self.assertFalse(any(e['kind']=='spell_cast' for e in self.kernel.semantic_events))
        before=self.kernel.snapshot()
        for actor in ('A','B'):
            with self.assertRaises(RulesViolation):self.kernel.pass_priority(actor)
        self.assertEqual(before,self.kernel.snapshot())
        packet=RulesActorAdapter(self.kernel).packet('B')
        self.assertEqual('Fling',packet['stack'][0]['name'])
        self.assertNotIn('secret-hand',json.dumps(packet));self.assertNotIn('payment',packet['announcement'])
        self.assertEqual('A',request.actor)

    def test_replacement_payment_restore_and_adapter_replay_commit_once(self):
        replacement=CardProgram('replacement','Replacement',('Enchantment',),
            replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,from_zone=Zone.BATTLEFIELD,optional=True),))
        self.game(extra=(replacement,),owner='B');self.state.add_card('replacement','replacement','B',Zone.BATTLEFIELD)
        self.state.add_counters(self.body,'+1/+1',2)
        adapter=RulesActorAdapter(self.kernel)
        adapter.submit('A',{'kind':'cast','revision':self.kernel.revision,'action_id':'cast','source':self.source.to_json(),
            'targets':[PlayerRef('B').to_json()],'x_value':0,
            'payment':{'mana':{'C':1,'R':1},'taps':[],'zone_costs':{'creature':[self.body.to_json()]}}})
        request=self.kernel.pending_choice;self.assertEqual('A',request.actor)
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())
        # The affected permanent's controller chooses; exile still pays sacrifice.
        restored.answer(request.request_id,'A',[0])
        adapter.submit('A',{'kind':'answer','revision':self.kernel.revision,'request_id':request.request_id,'indexes':[0]})
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('paid')).zone)
        self.assertEqual('B',self.state.get(self.state.current('paid')).owner)
        self.assertEqual(1,len(self.kernel.action_receipts))
        paid=adapter.packet('B')['stack'][0]['paid_cost_stats'];self.assertEqual(6,paid['creature']['power'])
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.answer(request.request_id,'A',[0])
        with self.assertRaises(RulesViolation):self.kernel.commit_action(PreparedAction.from_json(self.kernel.action_receipts['cast']['action']),self.payment())
        self.assertEqual(before,self.kernel.snapshot())
        for actor in ('A','B'):adapter.submit(actor,{'kind':'pass','revision':self.kernel.revision})
        self.assertEqual(34,self.state.life('B'))
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())

    def test_cost_reduction_stays_locked_when_reducer_is_sacrificed(self):
        reducer=CardProgram('reducer','Reducer',('Creature',),power=4,toughness=5,
            cost_modifiers=(CostModifier('discount',Selector(Zone.STACK,relation='controlled'),-1),))
        self.game(body=reducer);quote=self.quote();self.assertEqual(0,quote.cost.mana.generic)
        self.kernel.commit_action(quote,self.payment(mana=(('R',1),)))
        self.drain();self.assertEqual(36,self.state.life('B'));self.assertEqual((('C',1),),self.state.mana_pool('A'))

    def test_death_triggers_stack_above_completed_spell_and_cast_watchers_see_payment(self):
        death=CardProgram('death','Death',('Creature',),power=4,toughness=5,abilities=(
            AbilityProgram('death',EventPattern('zone_changed',from_zone=Zone.BATTLEFIELD,to_zone=Zone.GRAVEYARD,subject='self'),(GainLife(1),)),
            AbilityProgram('cast',EventPattern('spell_cast'),(GainLife(10),)),))
        self.game(body=death);self.cast()
        self.assertEqual(2,len(self.kernel.stack));self.assertEqual('death',self.kernel.stack[-1]['ability_id'])
        self.assertFalse(any(f.get('ability_id')=='cast' for f in self.kernel.stack))
        self.resolve();self.assertEqual(41,self.state.life('A'));self.assertEqual(40,self.state.life('B'))
        self.resolve();self.assertEqual(36,self.state.life('B'))

    def test_nonactive_caster_and_commander_tax_are_retained_through_pending_payment(self):
        replacement=CardProgram('replacement','Replacement',('Enchantment',),
            replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,from_zone=Zone.BATTLEFIELD,optional=True),))
        self.game(extra=(replacement,))
        self.source=self.state.add_card('commander',self.card.definition_id,'A',Zone.COMMAND,commander=True)
        self.state.record_command_cast('A','commander');self.state.add_card('replacement','replacement','B',Zone.BATTLEFIELD)
        self.kernel.open_window_for_scenario('B',priority_actor='A');self.state.add_mana('A',('C','C','C','R'))
        request=self.cast(payment=self.payment(mana=(('C',3),('R',1))))
        self.assertEqual(1,self.state.commander_casts('commander'))
        self.kernel.answer(request.request_id,'A',[1])
        self.assertEqual(2,self.state.commander_casts('commander'));self.assertEqual('A',self.kernel.priority)
        request=self.resolve();self.assertEqual('commander_sba',request.kind)
        self.assertEqual(36,self.state.life('B'))
        self.kernel.answer(request.request_id,'A',[0])
        self.assertEqual(Zone.COMMAND,self.state.get(self.state.current('commander')).zone)
        self.assertEqual(2,self.state.commander_casts('commander'))

    def test_modal_and_x_spell_keep_paid_statistics_in_the_selected_effect(self):
        cost=replace(self.cards['fling'].cast.cost,mana=ManaCost(0,('R',),1))
        spell=replace(self.cards['fling'],definition_id='modal-cost',name='Modal cost',spell_effects=(),spell_targets=None,
            cast=CastSpec(cost,'instant'),modal=ModalSpec((SpellMode('damage',(Damage('target',PaidCostStat('creature')),),self.cards['fling'].spell_targets),
                SpellMode('life',(GainLife(ChosenX()),))),1,1))
        self.game(spell=spell)
        self.cast(targets=(),x_value=1,mode_choices=(('damage',(PlayerRef('B'),)),))
        self.assertEqual(1,self.kernel.stack[0]['chosen_x']);self.drain();self.assertEqual(36,self.state.life('B'))

    def test_compiler_rejects_unbound_statistics_and_unimplemented_cost_combinations(self):
        fling=self.cards['fling'];cost=fling.cast.cost
        bad_costs=(replace(cost,zone_costs=(ZoneCost('creature','sacrifice'),)),
            replace(cost,zone_costs=(ZoneCost('creature','discard',Selector(Zone.HAND,relation='owned')),)),
            replace(cost,zone_costs=cost.zone_costs*2),replace(cost,life=1),
            replace(cost,tap_selector=Selector(Zone.BATTLEFIELD,relation='controlled'),tap_count=1))
        for bad in bad_costs:
            with self.assertRaises(RulesViolation):validate(replace(fling,cast=replace(fling.cast,cost=bad)))
        for stat in (PaidCostStat('missing'),PaidCostStat('creature','colors'),PaidCostStat(True)):
            with self.assertRaises(RulesViolation):validate(replace(fling,spell_effects=(Damage('target',stat),)))
        with self.assertRaises(RulesViolation):validate(replace(fling,cast=replace(fling.cast,alternatives=(AlternativeCost('free',CostSpec()),))))
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Artifact',),activated=(
            ActivatedProgram('use',cost,(GainLife(PaidCostStat('creature')),)),)))
        with self.assertRaises(RulesViolation):validate(replace(fling,cast=replace(fling.cast,generic_reduction=PaidCostStat('creature'))))

    def test_new_checkpoint_schema_rejects_prior_announcement_layout(self):
        self.game();checkpoint=self.kernel.snapshot();self.assertEqual(113,checkpoint['schema'])
        checkpoint['schema']=112
        with self.assertRaises(RulesViolation):RulesKernel.restore(checkpoint,self.programs)
