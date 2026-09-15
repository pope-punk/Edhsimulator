"""Numeric filters use derived views; occurrence and intervening checks differ."""
import unittest
from dataclasses import replace
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_characteristics import evaluate,evaluate_exhaustive,characteristics_match
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_casting import Payment


class CharacteristicRangeTests(unittest.TestCase):
    def setUp(self):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(
            CardProgram('small','Small',('Creature',),power=3,toughness=3),
            CardProgram('big','Big',('Creature',),power=4,toughness=4),
            CardProgram('buff','Buff',('Enchantment',),continuous=(ContinuousProgram('buff',
                Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled'),(ModifyPT(1,1),)),)),)
        self.state=RulesState(('A','B'));self.kernel=RulesKernel(self.state,self.programs)
        for i in range(8):self.state.add_card('draw'+str(i),'catalog:forest','A',Zone.LIBRARY)

    def add(self,key,definition,actor='A',zone=Zone.BATTLEFIELD):
        return self.state.add_card(key,definition,actor,zone)

    def drain(self):
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)

    def answer(self,card=None,index=0):
        request=self.kernel.pending_choice
        if card is not None:index=next(i for i,o in enumerate(request.options) if o.ref and o.ref.card_id==card)
        self.kernel.answer(request.request_id,request.actor,(index,))

    def attack(self,ref):
        self.kernel.begin_turn_for_scenario('A')
        for _ in range(8):self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual('declare_attackers',self.kernel.phase)
        self.kernel.declare_attackers('A',{ref:'B'},revision=self.kernel.revision)

    def test_range_validation_rejects_malformed_or_unsupported_event_filters(self):
        for ranges in [(CharacteristicRange('power'),),(CharacteristicRange('power',True),),
                       (CharacteristicRange('toughness',3,2),),(CharacteristicRange([],1),),
                       (CharacteristicRange('colors',1),),[CharacteristicRange('power',1)]]:
            with self.subTest(ranges=ranges),self.assertRaises(RulesViolation):
                validate(CardProgram('bad','Bad',('Artifact',),spell_effects=(SelectAll(
                    Selector(Zone.BATTLEFIELD,characteristics=ranges),(GainLife(1),)),)))
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Artifact',),abilities=(
            AbilityProgram('bad',EventPattern('creature_attacks',characteristics=(CharacteristicRange('power',1),)),()),)))

    def test_missing_power_is_not_zero_and_negative_bounds_are_signed(self):
        land=self.add('land','catalog:forest');creature=self.add('small','small')
        bound=(CharacteristicRange('power',maximum=0),)
        self.assertFalse(characteristics_match(bound,self.kernel.effective(land)))
        self.kernel.execute_for_scenario(creature,'A',(UntilEndOfTurn('source',(ModifyPT(-5,0),)),))
        self.assertTrue(characteristics_match((CharacteristicRange('power',-3,-1),),self.kernel.effective(creature)))

    def test_numeric_selector_dependency_matches_exhaustive_evaluator(self):
        early=CardProgram('early','Early',('Enchantment',),continuous=(ContinuousProgram('conditional',
            Selector(Zone.BATTLEFIELD,types=('Creature',),characteristics=(CharacteristicRange('power',minimum=4),)),(ModifyPT(2,0),)),))
        late=CardProgram('late','Late',('Enchantment',),continuous=(ContinuousProgram('raise',
            Selector(Zone.BATTLEFIELD,types=('Creature',)),(ModifyPT(1,0),)),))
        self.add('early','early');self.add('late','late');small=self.add('small','small')
        defs={p.definition_id:p for p in self.programs+(early,late)}
        fast=evaluate(self.state.objects(),defs);slow=evaluate_exhaustive(self.state.objects(),defs)
        self.assertEqual(slow,fast);self.assertEqual(6,fast[small].power)

    def test_uprising_entry_intervening_condition_rechecks(self):
        big=self.add('big','big');uprising=self.add('up','catalog:garruk-s-uprising',zone=Zone.HAND)
        self.kernel.enter(uprising,'A');self.assertTrue(self.kernel.stack)
        self.state.move((ZoneMove(big,Zone.EXILE),),'scenario-response');self.drain()
        self.assertEqual(0,len(self.state.zone('A',Zone.HAND)))

    def test_uprising_creature_entry_checks_derived_power_only_at_occurrence(self):
        self.add('up','catalog:garruk-s-uprising');buff=self.add('buff','buff')
        creature=self.add('small','small',zone=Zone.HAND);self.kernel.enter(creature,'A')
        self.assertEqual('creature-entry-draw',self.kernel.stack[-1]['ability_id'])
        self.state.move((ZoneMove(buff,Zone.EXILE),),'scenario-response');self.drain()
        self.assertEqual(1,len(self.state.zone('A',Zone.HAND)))
        self.assertIn('trample',self.kernel.effective(self.state.current('small')).keywords)

    def test_small_or_enemy_entry_does_not_trigger_uprising(self):
        self.add('up','catalog:garruk-s-uprising')
        for key,definition,actor in [('small','small','A'),('enemy','big','B')]:
            self.kernel.enter(self.add(key,definition,actor,Zone.HAND),actor);self.assertFalse(self.kernel.stack)
        self.assertNotIn('trample',self.kernel.effective(self.state.current('enemy')).keywords)

    def test_leaves_range_uses_predeparture_modified_power(self):
        observer=CardProgram('observer','Observer',('Enchantment',),abilities=(AbilityProgram('death',
            EventPattern('zone_changed',from_zone=Zone.BATTLEFIELD,to_zone=Zone.GRAVEYARD,
                types=('Creature',),characteristics=(CharacteristicRange('power',minimum=4),)),(GainLife(2),)),))
        self.add('observer','observer');self.add('buff','buff');small=self.add('small','small')
        self.kernel=RulesKernel(self.state,self.programs+(observer,))
        self.kernel.execute_for_scenario(small,'A',(SelectAll(Selector(Zone.BATTLEFIELD,any_types=('Creature','Enchantment')),(Move('selected',Zone.GRAVEYARD),)),))
        self.drain();self.assertEqual(42,self.state.life('A'))

    def test_ruby_occurrence_condition_survives_loss_of_big_creature_and_replays(self):
        ruby=self.add('ruby','catalog:ruby-daring-tracker');big=self.add('big','big');self.attack(ruby)
        self.assertEqual('attack-bonus',self.kernel.stack[-1]['ability_id'])
        self.state.move((ZoneMove(big,Zone.EXILE),),'scenario-response')
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        while self.kernel.stack:
            command={'kind':'pass','revision':self.kernel.revision};actor=self.kernel.priority
            adapter.submit(actor,command);replay.submit(actor,command)
        self.assertEqual(3,self.kernel.effective(ruby).power);self.assertEqual(adapter.archive(),replay.archive())
        self.kernel._finish_cleanup_actions();self.assertEqual(1,self.kernel.effective(ruby).power)

    def test_ruby_does_not_trigger_if_power_threshold_missing_at_attack(self):
        ruby=self.add('ruby','catalog:ruby-daring-tracker');self.attack(ruby)
        self.assertFalse(self.kernel.stack);self.add('late','big');self.assertEqual(1,self.kernel.effective(ruby).power)

    def test_sun_titan_target_menu_filters_value_type_and_ownership(self):
        self.add('legal','catalog:sol-ring',zone=Zone.GRAVEYARD)
        self.add('expensive','catalog:solemn-simulacrum',zone=Zone.GRAVEYARD)
        self.add('spell','catalog:counterspell',zone=Zone.GRAVEYARD)
        self.add('enemy','catalog:sol-ring','B',Zone.GRAVEYARD)
        titan=self.add('titan','catalog:sun-titan',zone=Zone.HAND);self.kernel.enter(titan,'A')
        self.assertEqual({'legal'},{o.ref.card_id for o in self.kernel.pending_choice.options if o.ref})
        self.answer('legal');self.drain();self.answer();self.drain()
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('legal')).zone)

    def test_sun_titan_attack_can_return_zero_value_land_and_decline(self):
        titan=self.add('titan','catalog:sun-titan');land=self.add('land','catalog:forest',zone=Zone.GRAVEYARD)
        self.attack(titan);self.assertFalse(self.state.get(titan).tapped)
        self.answer('land');self.drain();self.answer(index=1);self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(land).zone)

    def test_numeric_quality_search_allows_failure_to_find(self):
        source=self.add('source','catalog:sol-ring')
        self.kernel.execute_for_scenario(source,'A',(SearchLibrary(Selector(Zone.LIBRARY,relation='owned',
            characteristics=(CharacteristicRange('mana_value',maximum=1),)),Zone.HAND),))
        request=self.kernel.pending_choice;self.assertEqual(0,request.minimum)
        self.kernel.answer(request.request_id,'A',());self.assertEqual(0,len(self.state.zone('A',Zone.HAND)))

    def test_target_range_rechecks_current_toughness_on_resolution(self):
        spell=CardProgram('removal','Removal',('Instant',),cast=CastSpec(CostSpec(),'instant'),
            spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',),
                characteristics=(CharacteristicRange('toughness',minimum=4),))),spell_effects=(Destroy('target'),))
        big=self.add('big','big');small=self.add('small','small');card=self.add('spell','removal',zone=Zone.HAND)
        self.kernel=RulesKernel(self.state,self.programs+(spell,));self.kernel.open_window_for_scenario('A')
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',card,(small,))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',card,(big,)),Payment())
        self.state.add_counters(big,'-1/-1',1);self.drain()
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(big).zone)
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('spell')).zone)

    def test_ruby_haste_allows_immediate_mana_choice(self):
        ruby=self.add('ruby','catalog:ruby-daring-tracker',zone=Zone.HAND);self.kernel.enter(ruby,'A')
        ruby=self.state.current('ruby');self.kernel.open_window_for_scenario('A')
        self.kernel.commit_action(self.kernel.quote_activation('mana','A',ruby,'mana'),Payment())
        self.answer(index=1);self.assertEqual((('G',1),),self.state.mana_pool('A'))
        self.assertTrue(self.state.get(ruby).tapped);self.assertFalse(self.kernel.stack)

    def test_three_authored_cards_pay_printed_casting_costs(self):
        for key,mana,payment in [('garruk-s-uprising',('G','C','C'),(('G',1),('C',2))),
                                ('ruby-daring-tracker',('R','G'),(('R',1),('G',1))),
                                ('sun-titan',('W','W','C','C','C','C'),(('W',2),('C',4)))]:
            with self.subTest(card=key):
                state=RulesState(('A','B'));ref=state.add_card('spell','catalog:'+key,'A',Zone.HAND)
                kernel=RulesKernel(state,self.programs);kernel.open_window_for_scenario('A');state.add_mana('A',mana)
                kernel.commit_action(kernel.quote_cast('cast','A',ref),Payment(payment))
                while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)
                self.assertEqual(Zone.BATTLEFIELD,state.get(state.current('spell')).zone);self.assertEqual((),state.mana_pool('A'))
