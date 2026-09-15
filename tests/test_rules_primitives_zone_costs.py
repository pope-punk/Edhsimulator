"""Activation zone costs bind exact objects and pay once after replacement choices."""
import unittest
from edh_gauntlet.rules_program import (CardProgram,CostSpec,ZoneCost,ManaCost,ActivatedProgram,GainLife,
    AddMana,Draw,Selector,ZoneReplacement,AbilityProgram,EventPattern,CastSpec,validate)
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter


class ZoneCostTests(unittest.TestCase):
    def game(self,zone_cost,cost=None,effects=(GainLife(2),),mana=False,extra=()):
        cost=cost or CostSpec(zone_costs=(zone_cost,))
        self.program=CardProgram('source','Source',('Artifact',),activated=(ActivatedProgram('use',cost,effects,mana_ability=mana),))
        self.programs=(self.program,CardProgram('creature','Creature',('Creature',),power=1,toughness=1),*extra)
        self.state=RulesState(('A','B'));self.source=self.state.add_card('source','source','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def activate(self,payment=Payment()):
        return self.kernel.commit_action(self.kernel.quote_activation('one','A',self.source,'use'),payment)

    def test_source_taps_and_sacrifices_in_one_payment_with_tapped_lki(self):
        zone_cost=ZoneCost('sac','sacrifice');cost=CostSpec(ManaCost(1),tap_source=True,zone_costs=(zone_cost,))
        self.game(zone_cost,cost);self.state.add_mana('A',('C',));self.activate(Payment((('C',1),)))
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('source')).zone)
        event=self.state.events[-1];self.assertTrue(event.before.tapped);self.assertFalse(event.after.tapped)
        self.assertEqual((),self.state.mana_pool('A'));self.assertEqual(40,self.state.life('A'))
        self.assertTrue(self.kernel.stack[-1]['source']['tapped'])
        self.kernel.pass_priority('A');self.kernel.pass_priority('B');self.assertEqual(42,self.state.life('A'))

    def test_exact_selected_cost_group_commits_simultaneously(self):
        cost=ZoneCost('sac','sacrifice',Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled'),2)
        self.game(cost);refs=tuple(self.state.add_card(str(i),'creature','A',Zone.BATTLEFIELD) for i in range(2))
        before=self.kernel.snapshot()
        for chosen in ((refs[0],),(refs[0],refs[0])):
            with self.assertRaises(RulesViolation):self.activate(Payment(zone_costs=(('sac',chosen),)))
            self.assertEqual(before,self.kernel.snapshot())
        self.activate(Payment(zone_costs=(('sac',refs),)))
        self.assertEqual(2,len(self.state.events));self.assertEqual(1,len({e.batch for e in self.state.events}))

    def test_wrong_controller_is_rejected_before_any_cost(self):
        cost=ZoneCost('sac','sacrifice',Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled'))
        self.game(cost);ref=self.state.add_card('other','creature','B',Zone.BATTLEFIELD);before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.activate(Payment(zone_costs=(('sac',(ref,)),)))
        self.assertEqual(before,self.kernel.snapshot())

    def test_replacement_choice_keeps_resources_unpaid_and_checkpoint_continues_once(self):
        replacer=CardProgram('replacement','Replacement',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,optional=True),))
        cost=ZoneCost('sac','sacrifice');self.game(cost,CostSpec(ManaCost(1),tap_source=True,zone_costs=(cost,)),extra=(replacer,))
        self.state.add_card('replacement','replacement','B',Zone.BATTLEFIELD);self.state.add_mana('A',('C',))
        before=self.state.snapshot();request=self.activate(Payment((('C',1),)))
        self.assertEqual(before,self.state.snapshot());self.assertEqual(1,len(self.kernel.stack))
        with self.assertRaises(RulesViolation):self.kernel.pass_priority('A')
        self.assertIsNotNone(self.kernel.announcement)
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.kernel.answer(request.request_id,'A',[0]);restored.answer(request.request_id,'A',[0])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('source')).zone)
        self.assertEqual((),self.state.mana_pool('A'));self.assertEqual(1,len(self.kernel.action_receipts))
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.answer(request.request_id,'A',[0])
        self.assertEqual(before,self.kernel.snapshot())

    def test_sacrifice_mana_ability_and_death_trigger_have_correct_stack_order(self):
        observer=CardProgram('observer','Observer',('Enchantment',),abilities=(AbilityProgram('death',
            EventPattern('zone_changed',from_zone=Zone.BATTLEFIELD,to_zone=Zone.GRAVEYARD),(GainLife(1),)),))
        self.game(ZoneCost('sac','sacrifice'),effects=(AddMana(('C','C')),),mana=True,extra=(observer,))
        self.state.add_card('observer','observer','A',Zone.BATTLEFIELD);self.activate()
        self.assertEqual((('C',2),),self.state.mana_pool('A'))
        self.assertEqual(1,len(self.kernel.stack));self.assertEqual('death',self.kernel.stack[-1]['ability_id'])
        self.assertEqual(40,self.state.life('A'));self.kernel.pass_priority('A');self.kernel.pass_priority('B')
        self.assertEqual(41,self.state.life('A'))

    def test_discard_exile_and_return_costs_use_correct_origins_and_owners(self):
        for kind,zone,destination in (('discard',Zone.HAND,Zone.GRAVEYARD),('exile',Zone.GRAVEYARD,Zone.EXILE),('return',Zone.BATTLEFIELD,Zone.HAND)):
            relation='controlled' if kind=='return' else 'owned'
            self.game(ZoneCost('cost',kind,Selector(zone,relation=relation)))
            owner='B' if kind=='return' else 'A'
            ref=self.state.add_card('paid','creature',owner,zone,controller='A')
            self.activate(Payment(zone_costs=(('cost',(ref,)),)))
            self.assertEqual(['paid'],[o.ref.card_id for o in self.state.zone(owner,destination)])

    def test_adapter_replays_pending_payment_then_activation(self):
        replacer=CardProgram('replacement','Replacement',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,optional=True),))
        self.game(ZoneCost('sac','sacrifice'),extra=(replacer,));self.state.add_card('replacement','replacement','B',Zone.BATTLEFIELD)
        adapter=RulesActorAdapter(self.kernel)
        packet=adapter.submit('A',{'kind':'activate','revision':self.kernel.revision,'action_id':'sac','source':self.source.to_json(),
            'ability_id':'use','targets':[],'x_value':0,'payment':{'mana':{},'taps':[]}})
        request=packet['decision']['choice']
        adapter.submit('A',{'kind':'answer','revision':self.kernel.revision,'request_id':request['request_id'],'indexes':[1]})
        restored=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.assertEqual(self.kernel.snapshot(),restored.kernel.snapshot())

    def test_compiler_rejects_unimplemented_payment_shapes(self):
        for costs in ((ZoneCost('bad','discard'),),(ZoneCost('a','sacrifice'),ZoneCost('b','sacrifice'))):
            with self.assertRaises(RulesViolation):self.game(costs[0],CostSpec(zone_costs=costs))
        with self.assertRaises(RulesViolation):validate(CardProgram('spell','Spell',('Instant',),cast=CastSpec(CostSpec(zone_costs=(ZoneCost('sac','sacrifice'),)))))

    def test_pending_discard_payment_is_visible_only_to_its_actor(self):
        replacer=CardProgram('replacement','Replacement',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,optional=True),))
        self.game(ZoneCost('discard','discard',Selector(Zone.HAND,relation='owned')),extra=(replacer,))
        self.state.add_card('replacement','replacement','B',Zone.BATTLEFIELD)
        ref=self.state.add_card('private-card','creature','A',Zone.HAND)
        adapter=RulesActorAdapter(self.kernel)
        adapter.submit('A',{'kind':'activate','revision':self.kernel.revision,'action_id':'discard','source':self.source.to_json(),
            'ability_id':'use','targets':[],'x_value':0,'payment':{'mana':{},'taps':[],'zone_costs':{'discard':[ref.to_json()]}}})
        import json
        own=adapter.packet('A');other=adapter.packet('B')
        self.assertIn('private-card',json.dumps(own['announcement']))
        self.assertNotIn('private-card',json.dumps(other));self.assertNotIn('payment',other['announcement'])
        self.assertEqual('Source',other['announcement']['name'])

    def test_copied_source_ability_survives_sacrificing_the_copy(self):
        from edh_gauntlet.rules_state import ZoneMove
        self.game(ZoneCost('sac','sacrifice'))
        ref=self.state.add_card('copy','creature','A',Zone.GRAVEYARD)
        self.state.move((ZoneMove(ref,Zone.BATTLEFIELD,'A',copied_definition='source'),),'copy-fixture')
        self.source=self.state.current('copy');self.activate()
        self.assertEqual('source',self.kernel.stack[-1]['source']['copied_definition'])
        self.kernel.pass_priority('A');self.kernel.pass_priority('B');self.assertEqual(42,self.state.life('A'))

    def test_activation_watchers_use_departed_sources_last_known_types(self):
        from edh_gauntlet.rules_program import ContinuousProgram,ChangeTypes,SetPT
        watcher=CardProgram('watcher','Watcher',('Enchantment',),abilities=(AbilityProgram('creature-activation',
            EventPattern('ability_activated',types=('Creature',)),(GainLife(1),)),),continuous=(
                ContinuousProgram('animate',Selector(Zone.BATTLEFIELD,types=('Artifact',)),(ChangeTypes(add=('Creature',)),SetPT(1,1))),))
        self.game(ZoneCost('sac','sacrifice'),extra=(watcher,));self.state.add_card('watcher','watcher','A',Zone.BATTLEFIELD)
        self.activate();self.assertEqual(2,len(self.kernel.stack))
        self.assertEqual('creature-activation',self.kernel.stack[-1]['ability_id'])
        for _ in range(4):self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual(43,self.state.life('A'))


class AuthoredZoneCostTests(unittest.TestCase):
    def game(self,key):
        from edh_gauntlet.rules_bundle import load_reviewed
        self.programs=tuple(r['program'] for r in load_reviewed().values())
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('source','catalog:'+key,'A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
        self.adapter=RulesActorAdapter(self.kernel)

    def submit(self,actor,kind,**fields):return self.adapter.submit(actor,{'kind':kind,'revision':self.kernel.revision,**fields})

    def activate(self,ability,mana=None,zones=None):
        payment={'mana':mana or {},'taps':[]}
        if zones is not None:payment['zone_costs']=zones
        return self.submit('A','activate',action_id='activate',source=self.ref.to_json(),ability_id=ability,targets=[],x_value=0,payment=payment)

    def resolve(self):
        self.submit('A','pass');self.submit('B','pass')
        return self.kernel.pending_choice

    def test_fetch_subtype_union_includes_duals_and_rejects_nonmatching_lands(self):
        self.game('arid-mesa')
        for key in ('plains','forest','island','mountain','cinder-glade'):
            self.state.add_card(key,'catalog:'+key,'A',Zone.LIBRARY)
        # Rebind after fixture setup so replay has the same initial state.
        self.adapter=RulesActorAdapter(self.kernel)
        self.activate('fetch');self.assertEqual(39,self.state.life('A'))
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('source')).zone)
        request=self.resolve();self.assertEqual({'plains','mountain','cinder-glade'},{o.ref.card_id for o in request.options})
        selected=next(i for i,o in enumerate(request.options) if o.ref.card_id=='cinder-glade')
        self.submit('A','answer',request_id=request.request_id,indexes=[selected])
        land=self.state.get(self.state.current('cinder-glade'))
        self.assertEqual(Zone.BATTLEFIELD,land.zone);self.assertTrue(land.tapped) # Its own entry replacement.
        self.assertEqual(1,self.state.snapshot()['shuffle_nonce'])
        replayed=RulesActorAdapter.replay(self.adapter.archive(),self.programs)
        self.assertEqual(self.kernel.snapshot(),replayed.kernel.snapshot())

    def test_fetch_paid_with_last_life_loses_before_search_resolution(self):
        from edh_gauntlet.rules_program import Damage
        self.game('flooded-strand');self.kernel.execute_for_scenario(self.ref,'A',(Damage('controller',39),))
        self.kernel.open_window_for_scenario('A');self.adapter=RulesActorAdapter(self.kernel)
        self.activate('fetch');self.assertEqual(['B'],self.kernel.outcome['winners'])
        self.assertFalse(any(e['kind']=='library_searched' for e in self.kernel.semantic_events))

    def test_basic_search_places_land_tapped_and_rejects_nonbasic_types(self):
        for key,amount in (('sakura-tribe-elder',0),('wayfarer-s-bauble',2),('urza-s-cave',3)):
            self.game(key)
            self.state.add_card('basic','catalog:forest','A',Zone.LIBRARY)
            self.state.add_card('nonbasic','catalog:cinder-glade','A',Zone.LIBRARY)
            if amount:self.state.add_mana('A',('C',)*amount)
            self.activate('search',{'C':amount} if amount else {})
            request=self.resolve()
            expected={'basic','nonbasic'} if key=='urza-s-cave' else {'basic'}
            self.assertEqual(expected,{o.ref.card_id for o in request.options})
            index=next(i for i,o in enumerate(request.options) if o.ref.card_id=='basic')
            self.submit('A','answer',request_id=request.request_id,indexes=[index])
            self.assertTrue(self.state.get(self.state.current('basic')).tapped)
            entry=next(e for e in self.state.events if e.after.ref.card_id=='basic')
            self.assertTrue(entry.after.tapped)

    def test_mind_stone_sacrifices_before_draw_and_viscera_can_sacrifice_itself(self):
        for key,ability,amount in (('mind-stone','draw',1),('viscera-seer','scry',0)):
            self.game(key);self.state.add_card('look','catalog:forest','A',Zone.LIBRARY)
            if amount:self.state.add_mana('A',('C',))
            zones={'creature':[self.ref.to_json()]} if key=='viscera-seer' else None
            self.activate(ability,{'C':amount} if amount else {},zones)
            self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('source')).zone)
            request=self.resolve()
            if request:self.submit('A','answer',request_id=request.request_id,indexes=[0,1])
            self.assertEqual(Zone.HAND if key=='mind-stone' else Zone.LIBRARY,self.state.get(self.state.current('look')).zone)

    def test_omen_flash_cast_and_later_sacrifice_both_use_shared_scry(self):
        self.game('omen-of-the-sea')
        from edh_gauntlet.rules_state import ZoneMove
        self.state.move((ZoneMove(self.ref,Zone.HAND),),'fixture');self.ref=self.state.current('source')
        self.state.add_card('bottom','catalog:forest','A',Zone.LIBRARY);self.state.add_card('top','catalog:island','A',Zone.LIBRARY)
        self.kernel.open_window_for_scenario('B',priority_actor='A');self.state.add_mana('A',('C','U'))
        self.submit('A','cast',action_id='flash',source=self.ref.to_json(),targets=[],x_value=0,payment={'mana':{'C':1,'U':1},'taps':[]})
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)
        request=self.kernel.pending_choice;self.assertEqual('scry',request.kind)
        self.kernel.answer(request.request_id,'A',[0,1,2])
        self.assertEqual(['top'],[o.ref.card_id for o in self.state.zone('A',Zone.HAND)])
        self.kernel.open_window_for_scenario('A');self.ref=self.state.current('source');self.state.add_mana('A',('C','C','U'))
        self.activate('scry',{'C':2,'U':1});request=self.resolve()
        self.assertEqual('scry',request.kind);self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('source')).zone)

    def test_silent_clearing_pays_life_instead_of_dealing_damage(self):
        self.game('silent-clearing');packet=self.activate('mana')
        self.assertEqual(39,self.state.life('A'))
        request=packet['decision']['choice'];self.submit('A','answer',request_id=request['request_id'],indexes=[1])
        self.assertEqual((('B',1),),self.state.mana_pool('A'))
        self.assertFalse(any(e['kind']=='damage_dealt' for e in self.kernel.semantic_events))

    def test_expedition_map_reveals_the_selected_land_before_putting_it_in_hand(self):
        self.game('expedition-map');self.state.add_card('land','catalog:forest','A',Zone.LIBRARY);self.state.add_mana('A',('C','C'))
        self.activate('search',{'C':2});request=self.resolve()
        self.submit('A','answer',request_id=request.request_id,indexes=[0])
        self.assertEqual(Zone.HAND,self.state.get(self.state.current('land')).zone)
        revealed=[e for e in self.kernel.semantic_events if e['kind']=='cards_revealed']
        self.assertEqual(['Forest'],revealed[0]['names']);self.assertEqual(1,self.state.snapshot()['shuffle_nonce'])
