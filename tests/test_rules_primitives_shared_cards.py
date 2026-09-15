"""Reviewed cards composed from shared operations exercise actual bundle programs."""
import unittest
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment


class SharedCardTests(unittest.TestCase):
    def setUp(self):
        self.rows=load_reviewed();self.programs=tuple(r['program'] for r in self.rows.values())
        self.state=RulesState(('A','B'));self.kernel=RulesKernel(self.state,self.programs)

    def add(self,key,zone=Zone.BATTLEFIELD,owner='A',name=None,controller=None):
        return self.state.add_card(name or key,'catalog:'+key,owner,zone,controller=controller)

    def drain(self):
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)
        return self.kernel.pending_choice

    def answer(self,indexes):
        req=self.kernel.pending_choice
        self.kernel.answer(req.request_id,req.actor,indexes)
        return self.drain()

    def enter(self,key):
        ref=self.add(key,Zone.HAND);self.kernel.enter(ref);return self.drain()

    def spell(self,key,targets=()):
        ref=self.add(key,Zone.HAND);self.kernel.stage_spell_for_scenario(ref,'A',targets);return self.drain()

    def test_murder_and_utter_end_share_target_validation_and_destination(self):
        for key,destination in (('murder',Zone.GRAVEYARD),('utter-end',Zone.EXILE)):
            self.setUp();victim=self.add('llanowar-elves',owner='B');land=self.add('forest',owner='B')
            spell=self.add(key,Zone.HAND);self.kernel.open_window_for_scenario('A')
            with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',spell,(land,))
            self.kernel.stage_spell_for_scenario(spell,'A',(victim,));self.drain()
            self.assertEqual(destination,self.state.get(self.state.current(victim.card_id)).zone)

    def test_evacuation_returns_stolen_creatures_to_owners_in_one_batch(self):
        a=self.add('llanowar-elves',owner='B',controller='A');b=self.add('baleful-strix');land=self.add('forest')
        self.spell('evacuation')
        events=[e for e in self.state.events if e.before.ref in (a,b)]
        self.assertEqual(2,len(events));self.assertEqual(1,len({e.batch for e in events}))
        self.assertEqual('B',self.state.get(self.state.current(a.card_id)).controller)
        self.assertEqual(Zone.HAND,self.state.get(self.state.current(b.card_id)).zone)
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(land).zone)

    def test_farseek_and_rampant_growth_search_different_land_sets(self):
        for key,expected in (('farseek',{'island','cinder-glade'}),('rampant-growth',{'island','forest'})):
            self.setUp()
            for land in ('island','forest','cinder-glade'):self.add(land,Zone.LIBRARY)
            request=self.spell(key);self.assertEqual(expected,{o.ref.card_id for o in request.options})
            chosen=next(i for i,o in enumerate(request.options) if o.ref.card_id=='island');self.answer([chosen])
            self.assertTrue(self.state.get(self.state.current('island')).tapped)
            self.assertEqual(1,self.state.snapshot()['shuffle_nonce'])

    def test_eureka_draws_before_optional_land_selection(self):
        self.add('forest',Zone.LIBRARY);self.add('island',Zone.LIBRARY)
        request=self.spell('eureka-moment');self.assertEqual(2,len(self.state.zone('A',Zone.HAND)))
        self.assertEqual({'forest','island'},{o.ref.card_id for o in request.options});self.answer([0])
        self.assertEqual(1,len(self.state.zone('A',Zone.HAND)));self.assertEqual(1,len(self.state.objects(Zone.BATTLEFIELD)))

    def test_witness_targets_own_graveyard_then_optional_return(self):
        own=self.add('forest',Zone.GRAVEYARD);self.add('island',Zone.GRAVEYARD,owner='B')
        request=self.enter('eternal-witness');self.assertEqual([own],[o.ref for o in request.options]);self.answer([0]);self.answer([0])
        self.assertEqual(Zone.HAND,self.state.get(self.state.current('forest')).zone)
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('island')).zone)

    def test_felidar_blinks_another_permanent_and_returns_it_to_owner(self):
        original=self.add('sol-ring',owner='B',controller='A')
        request=self.enter('felidar-guardian');self.assertEqual([original],[o.ref for o in request.options])
        self.answer([0]);self.answer([0]);current=self.state.get(self.state.current('sol-ring'))
        self.assertEqual(original.incarnation+2,current.ref.incarnation);self.assertEqual('B',current.controller)
        self.assertEqual(Zone.BATTLEFIELD,current.zone)

    def test_body_double_inherits_the_copied_entry_trigger(self):
        self.add('oasis-gardener',Zone.GRAVEYARD,owner='B')
        request=self.enter('body-double')
        index=next(i for i,o in enumerate(request.options) if o.ref and o.ref.card_id=='oasis-gardener')
        self.answer([index]);self.assertEqual(42,self.state.life('A'))
        ref=self.state.current('body-double');self.assertEqual('catalog:oasis-gardener',self.state.get(ref).effective_definition)
        self.state.start_turn('A');self.kernel.open_window_for_scenario('A')
        request=self.kernel.commit_action(self.kernel.quote_activation('mana','A',ref,'mana'),Payment())
        self.kernel.answer(request.request_id,'A',[2]);self.assertEqual((('B',1),),self.state.mana_pool('A'))

    def test_arvad_anthem_excludes_self_nonlegendary_and_opponents(self):
        arvad=self.add('arvad-the-cursed');own=self.add('tatyova-benthic-druid');other=self.add('llanowar-elves')
        enemy=self.add('tatyova-benthic-druid',owner='B',name='enemy')
        self.assertEqual(3,self.kernel.effective(arvad).power);self.assertEqual(5,self.kernel.effective(own).power)
        self.assertEqual(1,self.kernel.effective(other).power);self.assertEqual(3,self.kernel.effective(enemy).power)
        self.state.move((ZoneMove(arvad,Zone.GRAVEYARD),),'fixture');self.assertEqual(3,self.kernel.effective(own).power)

    def test_rune_scarred_demon_searches_without_type_restriction(self):
        self.add('murder',Zone.LIBRARY);self.add('forest',Zone.LIBRARY)
        request=self.enter('rune-scarred-demon');self.assertEqual({'forest','murder'},{o.ref.card_id for o in request.options})
        self.answer([next(i for i,o in enumerate(request.options) if o.ref.card_id=='murder')])
        self.assertEqual(Zone.HAND,self.state.get(self.state.current('murder')).zone)
        self.assertEqual(1,self.state.snapshot()['shuffle_nonce'])

    def test_tatyova_and_sage_landfall_use_controller_and_batch_proliferation(self):
        self.add('tatyova-benthic-druid');sage=self.add('evolution-sage');self.state.add_counters(sage,'+1/+1',1)
        self.add('island',Zone.LIBRARY);enemy=self.add('forest',Zone.HAND,owner='B',name='enemy')
        self.kernel.enter(enemy);self.assertFalse(self.kernel.stack);self.assertEqual(40,self.state.life('A'))
        land=self.add('forest',Zone.HAND);self.kernel.enter(land)
        # Both triggers are independently placed; choose an APNAP order when asked.
        request=self.drain()
        while request:
            indexes=list(range(len(request.options))) if request.kind!='proliferate' else [next(i for i,o in enumerate(request.options) if o.ref==sage)]
            request=self.answer(indexes)
        self.assertEqual(41,self.state.life('A'));self.assertEqual(Zone.HAND,self.state.get(self.state.current('island')).zone)
        self.assertEqual((('+1/+1',2),),self.state.get(sage).counters)

    def test_filter_lands_pay_generic_and_produce_the_printed_pair(self):
        for key,expected in (('mossfire-valley',(('G',1),('R',1))),('overflowing-basin',(('G',1),('U',1)))):
            self.setUp();ref=self.add(key);self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('C',))
            self.kernel.commit_action(self.kernel.quote_activation('one','A',ref,'mana'),Payment((('C',1),)))
            self.assertEqual(expected,self.state.mana_pool('A'));self.assertEqual([],self.kernel.stack)

    def test_rootbound_crag_checks_either_subtype_before_entry(self):
        for land,tapped in (('forest',False),('mountain',False),('island',True)):
            self.setUp();self.add(land);self.enter('rootbound-crag');ref=self.state.current('rootbound-crag')
            self.assertEqual(tapped,self.state.get(ref).tapped)
            self.state.start_turn('A');self.kernel.open_window_for_scenario('A')
            req=self.kernel.commit_action(self.kernel.quote_activation('mana','A',ref,'mana'),Payment())
            self.kernel.answer(req.request_id,'A',[1]);self.assertEqual((('G',1),),self.state.mana_pool('A'))

    def test_remand_returns_real_stack_spell_and_draws(self):
        victim=self.add('sol-ring',Zone.HAND,owner='B');self.add('forest',Zone.LIBRARY)
        self.kernel.stage_spell_for_scenario(victim,'B');self.kernel.pass_priority('B')
        counter=self.add('remand',Zone.HAND);self.state.add_mana('A',('C','U'))
        self.kernel.commit_action(self.kernel.quote_cast('counter','A',counter,(self.state.current(victim.card_id),)),Payment((('C',1),('U',1))))
        self.drain();self.assertEqual(Zone.HAND,self.state.get(self.state.current('sol-ring')).zone)
        self.assertEqual(Zone.HAND,self.state.get(self.state.current('forest')).zone)
