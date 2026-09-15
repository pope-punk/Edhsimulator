"""Hosted conformance for modified creatures, combat milling, explore and Warp."""
import json
import unittest
from dataclasses import replace
from pathlib import Path
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,RulesViolation,Zone,ZoneMove
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_actor import project_actor
from edh_gauntlet.rules_bundle import load_reviewed,digest,source_facts
from edh_gauntlet.rules_characteristics import evaluate,evaluate_exhaustive
from edh_gauntlet.catalog import load_catalog

CARDS=('kodama-of-the-west-tree','rampant-frogantua','hakbal-of-the-surging-soul','chaos-warp')


class LibraryCreatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        reviewed=load_reviewed(cls.root)
        cls.rows={key:reviewed[key]['review'] for key in CARDS}
        cls.cards={key:reviewed[key]['program'] for key in CARDS}
        cls.base=tuple(r['program'] for r in reviewed.values())
        cls.prefix='catalog:'

    def game(self,card='kodama-of-the-west-tree',zone=Zone.BATTLEFIELD,extra=(),library=8):
        body=CardProgram('lc-body','Body',('Creature',),subtypes=('Merfolk',),colors=('G',),power=2,toughness=3)
        other=replace(body,definition_id='lc-other',name='Other',subtypes=('Elf',))
        aura=CardProgram('lc-aura','Aura',('Enchantment',),enchant=Selector(Zone.BATTLEFIELD,types=('Creature',)))
        equipment=CardProgram('lc-equipment','Equipment',('Artifact',),subtypes=('Equipment',))
        instant=CardProgram('lc-instant','Instant',('Instant',),cast=CastSpec(CostSpec(),timing='instant'))
        self.programs=self.base+(body,other,aura,equipment,instant)+extra
        self.state=RulesState(('A','B','C','D'),seed=29);self.kernel=RulesKernel(self.state,self.programs)
        self.serial=0;self.source=self.add(self.cards[card].definition_id,'A',zone)
        self.body=self.add();self.enemy=self.add(actor='B')
        for player in self.state.players:
            for _ in range(library):self.add('catalog:forest',player,Zone.LIBRARY)
        self.state.start_turn('A');self.kernel.open_window_for_scenario('A')

    def add(self,definition='lc-body',actor='A',zone=Zone.BATTLEFIELD,**kw):
        self.serial+=1
        return self.state.add_card('lc-object-'+str(self.serial),definition,actor,zone,**kw)

    def answer(self,indices):
        q=self.kernel.pending_choice
        self.assertIsNotNone(q)
        return self.kernel.answer(q.request_id,q.actor,indices)

    def until_choice(self):
        for _ in range(100):
            if self.kernel.pending_choice:return self.kernel.pending_choice
            if self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
            else:return None
        self.fail('No choice boundary')

    def drain(self):
        for _ in range(400):
            q=self.kernel.pending_choice
            if q:self.answer(list(range(len(q.options))) if q.kind=='trigger_order' else list(range(q.minimum)))
            elif self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
            else:return
        self.fail('No idle resolution boundary')

    def restore(self):
        before=self.kernel.snapshot();self.kernel=RulesKernel.restore(before,self.programs);self.state=self.kernel.state
        self.assertEqual(before,self.kernel.snapshot())

    def fx(self,*effects):
        return self.kernel.execute_for_scenario(self.source,'A',effects)

    def count(self,ref):return dict(self.state.get(ref).counters).get('+1/+1',0)
    def current(self,ref):return self.state.get(self.state.current(ref.card_id))
    def events(self,kind):return [r for r in self.kernel.semantic_events if r['kind']==kind]
    def trample(self,ref):return 'trample' in self.kernel.effective(ref).keywords
    def top(self,actor='A'):return self.state.zone(actor,Zone.LIBRARY)[-1]

    def damage(self,source=None,target='B',amount=3,combat=True):
        self.kernel._deal_damage(((self.state.get(source or self.source),target,amount),),combat=combat)
        self.kernel.advance()

    def combat(self,actor='A'):
        self.kernel.active=actor;self.kernel.phase='begin_combat'
        self.kernel._collect_step('begin_combat');self.kernel.advance()

    def attack(self):
        self.kernel._collect_announcement('creature_attacks',self.state.get(self.source),'A',values={'defending_player':'B'})
        self.kernel.advance()

    def cast(self,targets=(),mana='CCR'):
        while self.kernel.priority!='A':self.kernel.pass_priority(self.kernel.priority)
        self.state.add_mana('A',tuple(mana))
        quote=self.kernel.quote_cast('lc-cast','A',self.source,targets)
        self.kernel.commit_action(quote,Payment(tuple((s,mana.count(s)) for s in sorted(set(mana)))))

    def test_complete_faces_and_serializable_programs(self):
        catalog={c.card_id:c for c in load_catalog(self.root/'data/catalog/cards.json')}
        self.assertEqual(set(CARDS),set(self.cards))
        for key,program in self.cards.items():
            self.assertEqual(self.prefix+key,program.definition_id)
            self.assertEqual(program,validate(decode(encode(program))))
            expected=digest(source_facts(catalog[key]))
            row=self.rows[key]
            actual=row.get('source_facts_sha256') or digest(row['source_facts'])
            self.assertEqual(expected,actual)

    def test_all_four_normal_cast_costs_and_timing(self):
        for card,mana in zip(CARDS,('CCG','CCG','CCGU','CCR')):
            with self.subTest(card=card):
                self.game(card,Zone.HAND)
                self.cast((self.enemy,) if card=='chaos-warp' else (),mana)
                self.drain()
                self.assertEqual(Zone.GRAVEYARD if card=='chaos-warp' else Zone.BATTLEFIELD,self.current(self.source).zone)
                self.assertEqual((),self.state.mana_pool('A'))

    def test_kodama_reach_and_unmodified_creatures(self):
        self.game();self.assertIn('reach',self.kernel.effective(self.source).keywords)
        self.assertFalse(self.trample(self.source));self.assertFalse(self.trample(self.body))

    def test_any_counter_kind_modifies_and_last_removal_unmodifies(self):
        self.game();self.state.add_counters(self.body,'charge',1)
        self.assertTrue(self.trample(self.body))
        self.state.put_counters_batch((),removals=((self.body,(('charge',1),)),));self.assertFalse(self.trample(self.body))

    def test_opponent_equipment_modifies(self):
        self.game();equipment=self.add('lc-equipment','B');self.state.attach(equipment,self.body)
        self.assertTrue(self.trample(self.body))

    def test_only_creature_controllers_aura_modifies(self):
        self.game();aura=self.add('lc-aura','B');self.state.attach(aura,self.body)
        self.assertFalse(self.trample(self.body));self.state.change_control(aura,'A')
        self.assertTrue(self.trample(self.body));self.state.change_control(self.body,'B')
        self.assertFalse(self.kernel.effective(self.body).modified)

    def test_modified_opponents_do_not_get_kodama_trample(self):
        self.game();self.state.add_counters(self.enemy,'charge',1)
        self.assertTrue(self.kernel.effective(self.enemy).modified);self.assertFalse(self.trample(self.enemy))

    def test_noncreature_with_counters_is_not_modified(self):
        self.game();land=self.add('catalog:forest');self.state.add_counters(land,'charge',1)
        self.assertFalse(self.kernel.effective(land).modified)

    def test_phased_equipment_stops_modifying(self):
        self.game();equipment=self.add('lc-equipment');self.state.attach(equipment,self.body)
        self.state.phase(equipment,True);self.assertFalse(self.trample(self.body))
        self.state.phase(equipment,False);self.assertTrue(self.trample(self.body))

    def test_attachment_type_loss_stops_modifying_before_attachment_cleanup(self):
        self.game();equipment=self.add('lc-equipment');self.state.attach(equipment,self.body)
        effect=ContinuousProgram('remove-artifact',Selector(Zone.BATTLEFIELD),(ChangeTypes(remove=('Artifact',)),))
        kwargs={'temporary':((self.state.get(self.source),effect,(equipment,)),),
                'life_totals':{p:self.state.life(p) for p in self.state.players},'live_players':self.state.live_players}
        views=evaluate(self.state.objects(),self.kernel.definitions,**kwargs)
        self.assertFalse(views[self.body].modified);self.assertNotIn('trample',views[self.body].keywords)
        self.assertEqual(views,evaluate_exhaustive(self.state.objects(),self.kernel.definitions,**kwargs))

    def test_phased_kodama_stops_granting_trample(self):
        self.game();self.state.add_counters(self.body,'charge',1);self.state.phase(self.source,True)
        self.assertFalse(self.trample(self.body))

    def test_modified_derivation_matches_exhaustive_layers(self):
        change=CardProgram('lc-types','Types',('Enchantment',),continuous=(
            ContinuousProgram('equip',Selector(Zone.BATTLEFIELD,types=('Artifact',)),(AddSubtypes('Artifact',('Equipment',)),)),))
        self.game(extra=(change,));equipment=self.add('lc-equipment');self.state.attach(equipment,self.body);self.add('lc-types')
        kwargs={'life_totals':{p:self.state.life(p) for p in self.state.players},'live_players':self.state.live_players}
        self.assertEqual(evaluate(self.state.objects(),self.kernel.definitions,**kwargs),
                         evaluate_exhaustive(self.state.objects(),self.kernel.definitions,**kwargs))
        self.assertTrue(self.trample(self.body))

    def test_kodama_combat_search_enters_basic_tapped_and_shuffles(self):
        self.game();self.state.add_counters(self.body,'charge',1)
        self.damage(self.body);q=self.until_choice();self.assertEqual('library_search',q.kind)
        self.restore();ref=self.kernel.pending_choice.options[0].ref;self.answer([0]);self.drain()
        self.assertEqual(Zone.BATTLEFIELD,self.current(ref).zone);self.assertTrue(self.current(ref).tapped)
        self.assertEqual(1,len(self.events('library_shuffled')))

    def test_kodama_can_fail_to_find_but_still_shuffles(self):
        self.game();self.state.add_counters(self.body,'charge',1);self.damage(self.body)
        self.until_choice();self.answer([]);self.drain()
        self.assertEqual(8,len(self.state.zone('A',Zone.LIBRARY)));self.assertEqual(1,len(self.events('library_shuffled')))

    def test_kodama_ignores_noncombat_creature_damage_and_zero_damage(self):
        for target,combat,amount in (('B',False,2),('creature',True,1),('B',True,0)):
            with self.subTest(target=target,combat=combat,amount=amount):
                self.game();self.state.add_counters(self.body,'charge',1)
                self.damage(self.body,self.enemy if target=='creature' else target,amount,combat)
                self.assertFalse(self.kernel.stack);self.assertFalse(self.kernel.pending_choice)

    def test_kodama_ignores_unmodified_and_opposing_damage_sources(self):
        self.game();self.damage(self.body);self.assertFalse(self.kernel.stack)
        self.state.add_counters(self.enemy,'charge',1);self.damage(self.enemy,'A')
        self.assertFalse(self.kernel.stack)

    def test_kodama_captures_trigger_before_modification_removed(self):
        self.game();self.state.add_counters(self.body,'charge',1);self.damage(self.body)
        self.state.put_counters_batch((),removals=((self.body,(('charge',1),)),));self.until_choice()
        self.assertEqual('library_search',self.kernel.pending_choice.kind);self.drain()

    def test_kodama_simultaneous_sources_create_separate_searches(self):
        self.game();self.state.add_counters(self.body,'charge',1);self.state.add_counters(self.source,'charge',1)
        self.kernel._deal_damage(((self.state.get(self.body),'B',2),(self.state.get(self.source),'C',3)),combat=True)
        self.kernel.advance();self.drain();self.assertEqual(2,len(self.events('library_shuffled')))

    def test_frog_counts_losses_before_and_after_entry(self):
        self.game('rampant-frogantua',Zone.HAND)
        self.kernel._depart_players(('D',));self.kernel._continue_departure()
        self.kernel.enter(self.source);self.drain();self.source=self.state.current(self.source.card_id)
        self.assertEqual(13,self.kernel.effective(self.source).power)
        self.kernel._depart_players(('C',));self.kernel._continue_departure()
        self.assertEqual(23,self.kernel.effective(self.source).power);self.restore()
        self.assertEqual(23,self.kernel.effective(self.source).toughness)

    def test_frog_growth_is_not_a_counter_and_only_affects_itself(self):
        self.game('rampant-frogantua');self.kernel._depart_players(('D',));self.kernel._continue_departure()
        self.assertEqual(0,self.count(self.source));self.assertEqual(2,self.kernel.effective(self.body).power)
        self.assertEqual(13,self.kernel.effective(self.source).power)

    def test_frog_declining_mill_changes_no_cards(self):
        self.game('rampant-frogantua');self.damage();q=self.until_choice()
        self.assertEqual('optional_mill',q.kind);self.answer([1]);self.drain()
        self.assertEqual(8,len(self.state.zone('A',Zone.LIBRARY)))

    def test_frog_insufficient_library_never_offers_partial_mill(self):
        self.game('rampant-frogantua',library=2);self.damage(amount=3);self.drain()
        self.assertEqual(2,len(self.state.zone('A',Zone.LIBRARY)))
        self.assertFalse(self.state.zone('A',Zone.GRAVEYARD))

    def test_frog_exact_mill_count_and_selected_subset_enters_tapped(self):
        self.game('rampant-frogantua');old=self.add('catalog:forest','A',Zone.GRAVEYARD)
        self.damage(amount=3);self.until_choice();self.restore();self.answer([0])
        q=self.kernel.pending_choice;self.assertEqual('selection',q.kind)
        self.assertEqual(3,len(q.options));self.assertNotIn(old,[o.ref for o in q.options])
        ref=q.options[1].ref;self.restore();self.answer([1]);self.drain()
        self.assertEqual(5,len(self.state.zone('A',Zone.LIBRARY)))
        self.assertEqual(Zone.BATTLEFIELD,self.current(ref).zone);self.assertTrue(self.current(ref).tapped)
        self.assertEqual(Zone.GRAVEYARD,self.current(old).zone)

    def test_frog_milled_nonlands_cannot_be_selected(self):
        self.game('rampant-frogantua');spell=self.add('lc-instant','A',Zone.LIBRARY)
        self.damage(amount=2);self.until_choice();self.answer([0])
        self.assertEqual(1,len(self.kernel.pending_choice.options));self.answer([]);self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.current(spell).zone)

    def test_frog_replacement_arrivals_do_not_leak_into_land_choice(self):
        redirect=CardProgram('lc-replace','Redirect',('Enchantment',),replacements=(
            ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,from_zone=Zone.LIBRARY,types=('Land',)),))
        self.game('rampant-frogantua',extra=(redirect,));self.add('lc-replace');self.damage()
        self.until_choice();self.answer([0]);self.drain()
        self.assertEqual(3,len(self.state.zone('A',Zone.EXILE)));self.assertFalse(self.state.zone('A',Zone.GRAVEYARD))

    def test_frog_mills_captured_actual_damage_not_later_power(self):
        self.game('rampant-frogantua');self.damage(amount=2);self.state.add_counters(self.source,'+1/+1',9)
        q=self.until_choice();self.assertIn('2',q.prompt);self.answer([0]);self.drain()
        self.assertEqual(6,len(self.state.zone('A',Zone.LIBRARY)))

    def test_frog_ignores_noncombat_and_damage_to_creatures(self):
        self.game('rampant-frogantua');self.damage(combat=False);self.assertFalse(self.kernel.stack)
        self.damage(target=self.enemy,amount=1);self.assertFalse(self.kernel.stack)

    def test_hakbal_explore_order_precedes_any_reveal(self):
        self.game('hakbal-of-the-surging-soul');self.combat();q=self.until_choice()
        self.assertEqual('explore_order',q.kind);self.assertFalse(self.events('cards_revealed'))
        self.assertEqual({self.source,self.body},{o.ref for o in q.options})
        self.restore();self.answer([1]);self.drain()
        self.assertEqual(2,len(self.events('explored')));self.assertEqual(2,len(self.state.zone('A',Zone.HAND)))

    def test_hakbal_excludes_opponents_nonmerfolk_and_phased_creatures(self):
        self.game('hakbal-of-the-surging-soul');other=self.add('lc-other');phased=self.add();self.state.phase(phased,True)
        self.combat();self.drain()
        refs={r['source']['card_id'] for r in self.events('explored')}
        self.assertEqual({self.source.card_id,self.body.card_id},refs)

    def test_hakbal_does_not_trigger_on_opponents_combat(self):
        self.game('hakbal-of-the-surging-soul');self.combat('B')
        self.assertFalse(self.kernel.stack);self.assertFalse(self.kernel.pending_choice)

    def test_hakbal_uses_merfolk_present_when_trigger_resolves(self):
        self.game('hakbal-of-the-surging-soul');self.combat()
        late=self.add();self.drain()
        self.assertEqual(3,len(self.events('explored')));self.assertIn(late.card_id,{r['source']['card_id'] for r in self.events('explored')})

    def test_explore_nonland_adds_counter_and_may_keep_card(self):
        self.game('hakbal-of-the-surging-soul');top=self.add('lc-instant','A',Zone.LIBRARY)
        self.fx(Explore('source'));self.assertEqual('explore_card',self.kernel.pending_choice.kind)
        self.assertEqual(1,self.count(self.source));self.restore();self.answer([0]);self.drain()
        self.assertEqual(top,self.top().ref);self.assertEqual(1,self.count(self.source))

    def test_explore_nonland_can_move_to_graveyard(self):
        self.game('hakbal-of-the-surging-soul');top=self.add('lc-instant','A',Zone.LIBRARY)
        self.fx(Explore('source'));self.answer([1]);self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.current(top).zone);self.assertEqual(1,self.count(self.source))

    def test_explore_empty_library_adds_counter_without_failed_draw(self):
        self.game('hakbal-of-the-surging-soul',library=0);self.fx(Explore('source'));self.drain()
        self.assertEqual(1,self.count(self.source));self.assertEqual(('A','B','C','D'),self.state.live_players)
        self.assertEqual(1,len(self.events('explored')));self.assertFalse(self.events('cards_revealed'))

    def test_explore_repeated_nonland_reveal_can_modify_multiple_merfolk(self):
        self.game('hakbal-of-the-surging-soul');top=self.add('lc-instant','A',Zone.LIBRARY)
        self.combat();self.until_choice();self.answer([0]);self.answer([0])
        self.assertEqual('explore_card',self.kernel.pending_choice.kind);self.answer([0]);self.drain()
        self.assertEqual((1,1),(self.count(self.source),self.count(self.body)))
        self.assertEqual(top,self.top().ref);self.assertEqual(2,len(self.events('cards_revealed')))

    def test_explore_counter_replacement_is_not_repeated_after_restore(self):
        double=CardProgram('lc-double','Double',('Enchantment',),counter_replacements=(
            CounterReplacement('double',Selector(Zone.BATTLEFIELD),kind='+1/+1',multiplier=2),))
        self.game('hakbal-of-the-surging-soul',extra=(double,));self.add('lc-double');self.add('lc-instant','A',Zone.LIBRARY)
        self.fx(Explore('source'));self.assertEqual(2,self.count(self.source))
        self.restore();self.answer([0]);self.drain();self.assertEqual(2,self.count(self.source))

    def test_explore_departed_source_uses_last_controller_and_no_counter(self):
        self.game('hakbal-of-the-surging-soul');top=self.add('lc-instant','A',Zone.LIBRARY)
        self.fx(Move('source',Zone.GRAVEYARD),Explore('source'))
        self.assertEqual('A',self.kernel.pending_choice.actor);self.answer([1]);self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.current(top).zone);self.assertEqual(1,len(self.events('explored')))

    def test_hakbal_attack_can_put_land_untapped_without_using_land_play(self):
        self.game('hakbal-of-the-surging-soul');land=self.add('catalog:forest','A',Zone.HAND);self.attack();self.until_choice()
        self.assertEqual('selection',self.kernel.pending_choice.kind);self.answer([0]);self.drain()
        self.assertEqual(Zone.BATTLEFIELD,self.current(land).zone);self.assertFalse(self.current(land).tapped)
        self.assertFalse(self.events('card_drawn'))

    def test_hakbal_attack_decline_draws(self):
        self.game('hakbal-of-the-surging-soul');self.add('catalog:forest','A',Zone.HAND)
        self.attack();self.until_choice();self.answer([]);self.drain()
        self.assertEqual(2,len(self.state.zone('A',Zone.HAND)))

    def test_hakbal_attack_no_land_draws_automatically(self):
        self.game('hakbal-of-the-surging-soul');self.attack();self.drain()
        self.assertEqual(1,len(self.state.zone('A',Zone.HAND)))

    def test_warp_uses_owner_of_stolen_target(self):
        self.game('chaos-warp',Zone.HAND);target=self.add(actor='B',controller='A',token=True)
        self.cast((target,));self.drain()
        self.assertEqual(7,len(self.state.zone('B',Zone.LIBRARY)));self.assertEqual(8,len(self.state.zone('A',Zone.LIBRARY)))
        self.assertEqual('B',self.events('cards_revealed')[-1]['player'])
        self.assertEqual(1,len([o for o in self.state.objects(Zone.BATTLEFIELD,controller='B') if self.kernel.definition(o).name=='Forest']))

    def test_warp_token_never_replaces_top_card(self):
        self.game('chaos-warp',Zone.HAND,library=0);target=self.add(actor='B',token=True);top=self.add('catalog:forest','B',Zone.LIBRARY)
        self.cast((target,));self.drain()
        self.assertEqual(Zone.BATTLEFIELD,self.current(top).zone)
        self.assertNotIn(target.card_id,{o.ref.card_id for o in self.state.objects()})
        self.assertEqual(top.card_id,self.events('cards_revealed')[-1]['refs'][0]['card_id'])

    def test_warp_can_reveal_the_shuffled_target_again(self):
        self.game('chaos-warp',Zone.HAND,library=0);self.cast((self.enemy,));self.drain()
        self.assertEqual(Zone.BATTLEFIELD,self.current(self.enemy).zone)
        self.assertGreater(self.current(self.enemy).ref.incarnation,self.enemy.incarnation)

    def test_warp_nonpermanent_stays_on_top(self):
        self.game('chaos-warp',Zone.HAND,library=0);target=self.add(actor='B',token=True);top=self.add('lc-instant','B',Zone.LIBRARY)
        self.cast((target,));self.drain()
        self.assertEqual(top.card_id,self.top('B').ref.card_id);self.assertEqual(Zone.LIBRARY,self.current(top).zone)

    def test_warp_empty_library_still_shuffles(self):
        self.game('chaos-warp',Zone.HAND,library=0);target=self.add(actor='B',token=True)
        self.cast((target,));self.drain()
        self.assertEqual(1,len(self.events('library_shuffled')));self.assertFalse(self.events('cards_revealed'))

    def test_warp_illegal_target_prevents_shuffle_and_reveal(self):
        self.game('chaos-warp',Zone.HAND);self.cast((self.enemy,))
        self.state.move((ZoneMove(self.enemy,Zone.GRAVEYARD),),'scenario')
        self.drain();self.assertFalse(self.events('library_shuffled'));self.assertFalse(self.events('cards_revealed'))

    def test_warp_commander_replacement_still_shuffles_and_reveals(self):
        self.game('chaos-warp',Zone.HAND);target=self.add(actor='B',commander=True)
        self.cast((target,));q=self.until_choice();self.restore()
        index=next(i for i,o in enumerate(self.kernel.pending_choice.options) if 'command' in o.key.lower())
        self.answer([index]);self.drain()
        self.assertEqual(Zone.COMMAND,self.current(target).zone);self.assertEqual(1,len(self.events('library_shuffled')))
        self.assertEqual(1,len(self.events('cards_revealed')))

    def test_warp_unattachable_aura_remains_in_library(self):
        aura=CardProgram('lc-white-aura','White aura',('Enchantment',),enchant=Selector(Zone.BATTLEFIELD,types=('Creature',),colors=('W',)))
        self.game('chaos-warp',Zone.HAND,extra=(aura,),library=0)
        target=self.add(actor='B',token=True);top=self.add('lc-white-aura','B',Zone.LIBRARY)
        self.cast((target,));self.drain();self.assertEqual(Zone.LIBRARY,self.current(top).zone)

    def test_warp_entry_replacement_restores_without_reshuffle(self):
        self.game('chaos-warp',Zone.HAND,library=0);target=self.add(actor='B',token=True)
        top=self.add('catalog:godless-shrine','B',Zone.LIBRARY);self.cast((target,));q=self.until_choice()
        self.assertEqual('B',q.actor);self.assertEqual(1,len(self.events('library_shuffled')))
        self.restore();self.drain();self.assertEqual(Zone.BATTLEFIELD,self.current(top).zone)
        self.assertEqual(1,len(self.events('cards_revealed')));self.assertEqual(1,len(self.events('library_shuffled')))

    def test_closed_compiler_rejects_unbound_library_instructions(self):
        for effect in (Explore('missing'),ShuffleLibrary('captured_owners'),RevealTopPermanent('captured_owners'),
                       SelectBound(Selector(Zone.GRAVEYARD),0,None,(),subject='missing'),
                       MayMill(EventAmount(),effects=())):
            with self.subTest(effect=effect):
                with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',(),spell_effects=(effect,)))

    def test_closed_compiler_rejects_invalid_modified_and_damage_filters(self):
        for program in (
            CardProgram('bad','Bad',(),continuous=(ContinuousProgram('bad',ModifiedSelector(Zone.HAND),(AddKeywords(('trample',)),)),)),
            CardProgram('bad','Bad',(),abilities=(AbilityProgram('bad',CombatDamageToPlayer('life_gained'),()),)),
            CardProgram('bad','Bad',(),abilities=(AbilityProgram('bad',CombatDamageToPlayer('damage_dealt',modified=1),()),)),
        ):
            with self.subTest(program=program):
                with self.assertRaises(RulesViolation):validate(program)


    def test_explore_three_creatures_choose_again_after_first_reveal(self):
        self.game('hakbal-of-the-surging-soul');third=self.add();self.add('lc-instant','A',Zone.LIBRARY)
        self.combat();self.until_choice();self.answer([0])
        self.assertEqual('explore_card',self.kernel.pending_choice.kind);self.answer([1])
        self.assertEqual('explore_order',self.kernel.pending_choice.kind)
        self.assertEqual(1,len(self.events('cards_revealed')))
        self.assertEqual(2,len(self.kernel.pending_choice.options))
        self.restore();self.answer([1]);self.drain();self.assertEqual(3,len(self.events('explored')))

    def test_explore_multiple_controllers_choose_in_apnap_order(self):
        self.game('hakbal-of-the-surging-soul',library=0)
        self.kernel.active='B'
        self.fx(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',)),(Explore('selected'),)))
        self.drain();self.assertEqual(['B','A','A'],[r['player'] for r in self.events('explored')])

    def test_explore_reveal_is_public_but_later_library_cards_are_hidden(self):
        self.game('hakbal-of-the-surging-soul');hidden=self.top().ref;shown=self.add('lc-instant','A',Zone.LIBRARY)
        self.fx(Explore('source'))
        for actor in self.state.players:
            observation=project_actor(self.kernel,actor)['library_observation']
            self.assertEqual([shown.to_json()],[r['ref'] for r in observation['cards']])
            self.assertNotIn(hidden.card_id,json.dumps(observation))
        self.restore();self.answer([0]);self.drain()

    def test_explore_counter_replacement_choice_preserves_top_and_replay(self):
        double=CardProgram('lc-double','Double',('Enchantment',),counter_replacements=(
            CounterReplacement('double',Selector(Zone.BATTLEFIELD),kind='+1/+1',multiplier=2),))
        extra=CardProgram('lc-extra','Extra',('Enchantment',),counter_replacements=(
            CounterReplacement('extra',Selector(Zone.BATTLEFIELD),kind='+1/+1',additional=1),))
        self.game('hakbal-of-the-surging-soul',extra=(double,extra));self.add('lc-double');self.add('lc-extra')
        top=self.add('lc-instant','A',Zone.LIBRARY);self.fx(Explore('source'))
        self.assertEqual(0,self.count(self.source));self.assertEqual(1,len(self.events('cards_revealed')))
        self.restore();self.drain();self.assertIn(self.count(self.source),(3,4))
        self.assertEqual(top,self.top().ref);self.assertEqual(1,len(self.events('cards_revealed')))

    def test_frog_source_departure_does_not_cancel_captured_mill(self):
        self.game('rampant-frogantua');self.damage(amount=2)
        self.state.move((ZoneMove(self.source,Zone.GRAVEYARD),),'scenario')
        self.until_choice();self.answer([0]);self.drain()
        self.assertEqual(6,len(self.state.zone('A',Zone.LIBRARY)))

    def test_warp_legal_aura_attachment_is_chosen_by_owner(self):
        self.game('chaos-warp',Zone.HAND,library=0);target=self.add(actor='B',token=True)
        aura=self.add('lc-aura','B',Zone.LIBRARY);self.cast((target,));q=self.until_choice()
        self.assertEqual('B',q.actor);self.assertGreaterEqual(len(q.options),2)
        self.restore();self.answer([0]);self.drain()
        self.assertEqual(Zone.BATTLEFIELD,self.current(aura).zone);self.assertIsNotNone(self.current(aura).attached_to)
        self.assertEqual(1,len(self.events('library_shuffled')));self.assertEqual(1,len(self.events('cards_revealed')))

    def test_lost_player_modifier_requires_player_history_and_static_context(self):
        self.game('rampant-frogantua')
        with self.assertRaises(RulesViolation):evaluate(self.state.objects(),self.kernel.definitions)
        with self.assertRaises(RulesViolation):
            validate(CardProgram('bad','Bad',(),spell_effects=(UntilEndOfTurn('source',(LostPlayerPT(1,1),)),)))


if __name__=='__main__':unittest.main()
