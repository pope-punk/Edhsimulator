"""Counter durations, state triggers, Fading and announcement-bound divisions."""
import json
import unittest
from dataclasses import replace
from pathlib import Path

from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState, RulesViolation, Zone, ZoneMove, ObjectRef, PlayerRef
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment, PreparedAction
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed, source_facts, digest
from edh_gauntlet.catalog import load_catalog

CARDS=('xolatoyac-the-smiling-flood','the-earth-crystal','dark-depths','parallax-wave')


class CounterLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        reviewed=load_reviewed(cls.root)
        drafts=json.loads((cls.root/'data/rules/draft_cards.json').read_text(encoding='utf-8'))['drafts']
        cls.rows={row['card_id']:row for row in drafts if row['card_id'] in CARDS}
        cls.cards={key:validate(decode(row['program'])) for key,row in cls.rows.items()}
        cls.base=tuple(row['program'] for row in reviewed.values())+tuple(cls.cards.values())

    def game(self,key='dark-depths',*,extra=(),source_zone=Zone.BATTLEFIELD,counters=None):
        body=CardProgram('cycle-body','Body',('Creature',),power=3,toughness=10)
        land=CardProgram('cycle-land','Land',('Land',),subtypes=('Forest',),supertypes=('Basic',))
        rock=CardProgram('cycle-rock','Rock',('Artifact',))
        spell=CardProgram('cycle-spell','Spell',('Instant',),cast=CastSpec(CostSpec(),timing='instant'))
        removal=replace(spell,definition_id='cycle-remove',name='Remove',spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD)),
            spell_effects=(Move('target',Zone.GRAVEYARD),))
        control=replace(removal,definition_id='cycle-control',name='Control',spell_effects=(GainControl('target'),))
        blink=replace(removal,definition_id='cycle-blink',name='Blink',
            spell_effects=(WithMoved('target',Zone.EXILE,(Move('moved',Zone.BATTLEFIELD),)),))
        counter=replace(spell,definition_id='cycle-stifle',name='Counter abilities',spell_effects=(CounterAbilities(),))
        self.programs=self.base+(body,land,rock,spell,removal,control,blink,counter)+extra
        self.state=RulesState(('A','B','C','D'));self.kernel=RulesKernel(self.state,self.programs)
        self.kernel.open_window_for_scenario('A');self.key=key;self.number=0
        self.source=self.state.add_card('source',self.cards[key].definition_id,'A',source_zone)
        self.bodies={p:self.state.add_card('body-'+p,'cycle-body',p,Zone.BATTLEFIELD) for p in self.state.players}
        self.other=self.state.add_card('other','cycle-body','A',Zone.BATTLEFIELD)
        self.lands={p:self.state.add_card('land-'+p,'cycle-land',p,Zone.BATTLEFIELD) for p in self.state.players}
        if source_zone==Zone.BATTLEFIELD:
            initial={'dark-depths':('ice',10),'parallax-wave':('fade',5)}.get(key)
            if initial:self.state.add_counters(self.source,initial[0],initial[1] if counters is None else counters)
        for p in self.state.players:
            for n in range(8):self.state.add_card('library-'+p+'-'+str(n),'cycle-body',p,Zone.LIBRARY)

    def ident(self):
        self.number+=1
        return 'cycle-action-'+str(self.number)

    def top(self):
        self.assertTrue(self.kernel.stack)
        result=None
        for _ in self.state.live_players:result=self.kernel.pass_priority(self.kernel.priority)
        return result

    def settle(self):
        for _ in range(60):
            self.assertIsNone(self.kernel.pending_choice)
            if not self.kernel.stack:return
            self.top()
        self.fail('Unexpected trigger loop')

    def target(self,ref):
        q=self.kernel.pending_choice;self.assertEqual('trigger_targets',q.kind)
        return self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.ref==ref)])

    def order(self):
        q=self.kernel.pending_choice;self.assertEqual('trigger_order',q.kind)
        return self.kernel.answer(q.request_id,q.actor,list(range(len(q.options))))

    def choose(self,key):
        q=self.kernel.pending_choice
        return self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.key==key)])

    def counts(self,ref):return dict(self.state.get(ref).counters)

    def tokens(self):return tuple(obj for obj in self.state.objects(Zone.BATTLEFIELD) if obj.token)

    def effect(self,ref,*effects,actor='A'):
        return self.kernel.execute_for_scenario(ref,actor,effects)

    def window(self,actor='A'):
        if not self.kernel.stack and self.kernel.turn_schedule is None:
            self.kernel.open_window_for_scenario('A',priority_actor=actor)
        while self.kernel.priority!=actor:self.kernel.pass_priority(self.kernel.priority)

    def activate(self,ability,targets=(),*,mana=(),division=(),actor='A',source=None):
        self.window(actor)
        symbols=tuple(mana)
        if symbols:self.state.add_mana(actor,symbols)
        quote=self.kernel.quote_activation(self.ident(),actor,source or self.source,ability,targets,counter_division=division)
        return self.kernel.commit_action(quote,Payment(tuple((s,symbols.count(s)) for s in sorted(set(symbols)))))

    def cast_response(self,definition,targets=(),actor='B'):
        self.window(actor);ref=self.state.add_card(self.ident(),definition,actor,Zone.HAND)
        self.kernel.commit_action(self.kernel.quote_cast(self.ident(),actor,ref,targets),Payment())
        return ref

    def phase(self,name):
        if self.kernel.turn_schedule is None:self.kernel.begin_turn_for_scenario('A')
        for _ in range(100):
            if self.kernel.phase==name:return
            self.assertIsNone(self.kernel.pending_choice)
            self.assertFalse(self.kernel.stack)
            if self.kernel.phase=='declare_attackers' and self.kernel.priority is None:
                self.kernel.declare_attackers(self.kernel.active,{},revision=self.kernel.revision)
            else:self.kernel.pass_priority(self.kernel.priority)
        self.fail('Did not reach '+name)

    def flood(self,ref=None):
        self.kernel.enter(self.source);self.source=self.state.current('source')
        self.target(ref or self.lands['A']);self.settle()

    def depth_trigger(self):
        self.effect(self.source,RemoveCounters('source','ice',10))
        self.assertEqual(1,len(self.kernel.stack))
        return self.kernel.stack[-1]

    def crystal_activation(self,targets=None,division=None):
        targets=targets or (self.bodies['A'],self.other)
        division=division if division is not None else tuple((ref,1) for ref in targets)
        return self.activate('distribute',targets,mana='CCCCGG',division=division)

    def test_full_printed_faces_and_source_facts(self):
        catalog={card.card_id:card for card in load_catalog(self.root/'data/catalog/cards.json')}
        self.assertEqual(set(CARDS),set(self.cards))
        for key,program in self.cards.items():
            with self.subTest(card=key):
                self.assertEqual(digest(source_facts(catalog[key])),digest(self.rows[key]['source_facts']))
                self.assertEqual(self.rows[key]['program'],encode(program))
                self.assertEqual(catalog[key].name,program.name)
                face=catalog[key].faces[0]
                self.assertEqual(1,len(catalog[key].faces))
                for field in ('types','subtypes','supertypes','colors'):
                    self.assertEqual(set(getattr(face,field)),set(getattr(program,field)))
                for field in ('power','toughness','mana_value'):
                    self.assertEqual(getattr(face,field),getattr(program,field))

    def test_three_normal_spell_costs_and_complete_battlefield_entry(self):
        for key in ('xolatoyac-the-smiling-flood','the-earth-crystal','parallax-wave'):
            with self.subTest(card=key):
                self.game(key,source_zone=Zone.HAND)
                cost=self.cards[key].cast.cost.mana;symbols=cost.symbols+('C',)*cost.generic
                self.state.add_mana('A',symbols)
                quote=self.kernel.quote_cast(self.ident(),'A',self.source)
                self.assertEqual(cost,quote.cost.mana)
                self.kernel.commit_action(quote,Payment(tuple((s,symbols.count(s)) for s in sorted(set(symbols)))))
                self.top();self.source=self.state.current('source')
                if key=='xolatoyac-the-smiling-flood':self.target(self.lands['A']);self.settle()
                self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.source).zone)
                self.assertEqual((),self.state.mana_pool('A'))
                if key=='parallax-wave':self.assertEqual({'fade':5},self.counts(self.source))

    def test_dark_depths_normal_land_play_has_ten_ice_counters_and_no_mana(self):
        self.game(source_zone=Zone.HAND);self.phase('precombat_main')
        self.kernel.play_land(self.ident(),'A',self.source,revision=self.kernel.revision)
        self.source=self.state.current('source')
        self.assertEqual({'ice':10},self.counts(self.source))
        self.assertEqual(('remove-ice',),tuple(a.ability_id for a in self.kernel.activated_abilities(self.state.get(self.source))))
        self.assertEqual({'Legendary','Snow'},set(self.kernel.effective(self.source).supertypes))
        self.assertFalse(self.kernel.stack);self.assertEqual(1,self.kernel.turn_schedule['land_plays'])
        with self.assertRaises(RulesViolation):self.kernel.quote_cast(self.ident(),'A',self.source)

    def test_depths_removal_is_an_effect_paid_with_three_mana(self):
        self.game();self.activate('remove-ice',mana='CCC')
        self.assertEqual({'ice':10},self.counts(self.source));self.assertFalse(self.state.get(self.source).tapped)
        self.top();self.assertEqual({'ice':9},self.counts(self.source));self.assertFalse(self.tokens())

    def test_depths_zero_counter_activation_is_legal_but_does_not_duplicate_state_trigger(self):
        self.game(counters=0);self.kernel.advance();self.assertEqual(1,len(self.kernel.stack))
        self.activate('remove-ice',mana='CCC');self.assertEqual(2,len(self.kernel.stack))
        self.top();self.assertEqual(1,len(self.kernel.stack));self.top()
        self.assertEqual(1,len(self.tokens()))

    def test_depths_creates_exact_marit_lage_only_after_successful_sacrifice(self):
        self.game();self.depth_trigger();self.assertFalse(self.tokens())
        self.top();token,=self.tokens()
        view=self.kernel.effective(token.ref)
        self.assertEqual('Marit Lage',self.kernel.definition(token).name)
        self.assertEqual((20,20),(view.power,view.toughness))
        self.assertEqual({'B'},set(view.colors));self.assertEqual({'Avatar'},set(view.subtypes))
        self.assertEqual({'Legendary'},set(view.supertypes))
        self.assertTrue({'flying','indestructible'}<=set(view.keywords))
        self.assertEqual('A',token.controller)
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('source')).zone)

    def test_depths_state_trigger_is_single_while_pending_and_on_stack(self):
        self.game();first=self.depth_trigger()['id']
        for _ in range(3):self.kernel.advance()
        self.assertEqual([first],[frame['id'] for frame in self.kernel.stack])
        self.assertEqual(1,sum(e['kind']=='trigger_created' and e['ability']=='no-ice' for e in self.kernel.semantic_events))

    def test_depths_state_condition_can_be_briefly_true_during_resolution(self):
        self.game()
        self.effect(self.source,RemoveCounters('source','ice',10),AddCounters('source','ice',3))
        self.assertEqual({'ice':3},self.counts(self.source));self.assertEqual(1,len(self.kernel.stack))
        self.top();self.assertEqual(1,len(self.tokens()))

    def test_depths_readding_ice_does_not_cancel_an_existing_trigger(self):
        self.game();self.depth_trigger();self.state.add_counters(self.source,'ice',1)
        self.top();self.assertEqual(1,len(self.tokens()))

    def test_depths_countered_state_trigger_retriggers_with_fresh_identity(self):
        self.game();old=self.depth_trigger()['id']
        self.cast_response('cycle-stifle');self.top()
        self.assertEqual(1,len(self.kernel.stack));self.assertNotEqual(old,self.kernel.stack[-1]['id'])
        self.top();self.assertEqual(1,len(self.tokens()))

    def test_depths_departure_in_response_prevents_token_creation(self):
        self.game();self.depth_trigger()
        self.cast_response('cycle-remove',(self.source,));self.top();self.settle()
        self.assertFalse(self.tokens())

    def test_depths_blink_in_response_does_not_sacrifice_the_new_incarnation(self):
        self.game();self.depth_trigger()
        self.cast_response('cycle-blink',(self.source,));self.top();self.settle()
        new=self.state.current('source')
        self.assertNotEqual(new,self.source);self.assertEqual({'ice':10},self.counts(new));self.assertFalse(self.tokens())

    def test_depths_stolen_source_cannot_be_sacrificed_by_original_trigger_controller(self):
        self.game();self.depth_trigger()
        self.cast_response('cycle-control',(self.source,));self.top()
        self.assertEqual('B',self.state.get(self.source).controller)
        self.top();self.assertFalse(self.tokens())
        self.assertEqual('B',self.kernel.stack[-1]['controller'])
        self.top();self.assertEqual('B',self.tokens()[0].controller)

    def test_depths_replaced_sacrifice_still_counts_as_success(self):
        replacement=CardProgram('redirect','Redirect',('Enchantment',),replacements=(
            ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,from_zone=Zone.BATTLEFIELD,types=('Land',)),))
        self.game(extra=(replacement,));self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD)
        self.depth_trigger();self.top()
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('source')).zone);self.assertEqual(1,len(self.tokens()))

    def test_depths_replacement_choice_retains_occupied_state_trigger(self):
        replacement=CardProgram('redirect','Redirect',('Enchantment',),replacements=(
            ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,from_zone=Zone.BATTLEFIELD,types=('Land',),optional=True),))
        self.game(extra=(replacement,));self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD)
        self.depth_trigger();self.top();q=self.kernel.pending_choice
        self.assertEqual('replacement_optional',q.kind)
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.kernel.answer(q.request_id,q.actor,[0]);restored.answer(q.request_id,q.actor,[0])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertEqual(1,len(self.tokens()))
        self.assertEqual(1,sum(e['kind']=='trigger_created' and e['ability']=='no-ice' for e in self.kernel.semantic_events))

    def test_state_trigger_stays_occupied_while_resolution_mana_ability_runs(self):
        program=CardProgram('paid-state','Paid state',('Artifact',),abilities=(AbilityProgram(
            'state-payment',EventPattern('counter_state',subject='self',counters=(CounterRange('charge',0,0),)),
            (PayMana(ManaCost(1),(Sacrifice('source'),)),)),))
        self.game(extra=(program,))
        source=self.state.add_card('paid-state','paid-state','A',Zone.BATTLEFIELD)
        self.kernel.advance();self.top()
        quote=self.kernel.quote_activation(self.ident(),'A',self.lands['A'],'intrinsic-land:Forest')
        self.kernel.commit_action(quote,Payment())
        self.assertEqual([],self.kernel.pending_triggers);self.assertEqual([],self.kernel.stack)
        self.assertEqual(1,sum(e['kind']=='trigger_created' and e['ability']=='state-payment'
                               for e in self.kernel.semantic_events))
        window=self.kernel.mana_payment
        self.kernel.pay_resolution_mana(self.ident(),'A',window['id'],Payment((('G',1),)),revision=self.kernel.revision)
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('paid-state')).zone)
        self.assertFalse(self.kernel.stack);self.assertIsNone(self.kernel.mana_payment)

    def test_depths_state_trigger_checkpoint_and_actor_replay(self):
        self.game();self.depth_trigger();adapter=RulesActorAdapter(self.kernel)
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        for _ in self.state.live_players:
            actor=self.kernel.priority
            adapter.submit(actor,{'kind':'pass','revision':self.kernel.revision})
            restored.pass_priority(restored.priority)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())

    def test_counter_removal_does_as_much_as_possible_and_ignores_other_kinds(self):
        self.game('the-earth-crystal');self.state.add_counters(self.bodies['A'],'charge',2)
        self.state.add_counters(self.bodies['A'],'flood',3)
        self.effect(self.bodies['A'],RemoveCounters('source','charge',7))
        self.assertEqual({'flood':3},self.counts(self.bodies['A']))
        events=[e for e in self.kernel.semantic_events if e['kind']=='counters_removed']
        self.assertEqual({'charge':2},events[-1]['counters'])
        self.effect(self.bodies['A'],RemoveCounters('source','charge',1))
        self.assertEqual(len(events),len([e for e in self.kernel.semantic_events if e['kind']=='counters_removed']))

    def test_wave_entry_fading_removes_last_counter_then_sacrifices_next_upkeep(self):
        self.game('parallax-wave',counters=1)
        self.kernel.begin_step('A','upkeep');self.top()
        self.assertEqual({},self.counts(self.source));self.assertFalse(self.kernel.stack)
        self.kernel.begin_step('A','upkeep');self.settle()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('source')).zone)

    def test_wave_fading_ignores_another_players_upkeep(self):
        self.game('parallax-wave');self.kernel.begin_step('B','upkeep')
        self.assertFalse(self.kernel.stack);self.assertEqual({'fade':5},self.counts(self.source))

    def test_wave_cost_removes_counter_at_activation_before_responses(self):
        self.game('parallax-wave');self.activate('exile-creature',(self.bodies['B'],))
        self.assertEqual({'fade':4},self.counts(self.source))
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.bodies['B']).zone)
        self.assertEqual((),self.state.mana_pool('A'));self.assertFalse(self.state.get(self.source).tapped)
        self.top();self.assertEqual(Zone.EXILE,self.state.get(self.state.current('body-B')).zone)

    def test_wave_zero_counters_rejects_activation_without_side_effects(self):
        self.game('parallax-wave',counters=0);before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_activation(self.ident(),'A',self.source,'exile-creature',(self.bodies['B'],))
        self.assertEqual(before,self.kernel.snapshot())

    def test_wave_illegal_target_still_consumes_paid_fade_counter(self):
        self.game('parallax-wave');self.activate('exile-creature',(self.bodies['B'],))
        self.cast_response('cycle-remove',(self.bodies['B'],));self.top();self.settle()
        self.assertEqual({'fade':4},self.counts(self.source))
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('body-B')).zone)
        self.assertEqual({},self.kernel.linked_exile)

    def test_wave_returns_all_actual_exiles_simultaneously_to_their_owners(self):
        self.game('parallax-wave')
        self.state.change_control(self.bodies['B'],'A')
        for ref in (self.bodies['A'],self.bodies['B']):
            self.activate('exile-creature',(ref,));self.top()
        self.effect(self.source,Move('source',Zone.GRAVEYARD));self.settle()
        current=[self.state.get(self.state.current('body-'+p)) for p in ('A','B')]
        self.assertEqual(['A','B'],[obj.controller for obj in current])
        self.assertTrue(all(obj.zone==Zone.BATTLEFIELD for obj in current))
        events=[e for e in self.state.events if e.before.zone==Zone.EXILE and e.after.ref.card_id.startswith('body-')]
        self.assertEqual(2,len(events));self.assertEqual(events[0].batch,events[1].batch)

    def test_wave_departure_before_exile_resolution_leaves_that_creature_exiled(self):
        self.game('parallax-wave');self.activate('exile-creature',(self.bodies['B'],))
        self.cast_response('cycle-remove',(self.source,));self.top()
        self.top();self.top()
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('body-B')).zone)
        self.assertFalse(self.kernel.stack)

    def test_wave_new_incarnation_cannot_return_the_old_linked_cards(self):
        self.game('parallax-wave');self.activate('exile-creature',(self.bodies['B'],))
        self.cast_response('cycle-blink',(self.source,));self.top();self.top();self.top()
        new=self.state.current('source');self.assertNotEqual(new,self.source)
        self.effect(new,Move('source',Zone.GRAVEYARD));self.settle()
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('body-B')).zone)

    def test_wave_returns_only_cards_still_in_its_recorded_exile_incarnations(self):
        self.game('parallax-wave');self.activate('exile-creature',(self.bodies['B'],));self.top()
        ref=self.state.current('body-B')
        self.state.move((ZoneMove(ref,Zone.GRAVEYARD,'B'),),'fixture-exile-departure')
        self.state.move((ZoneMove(self.state.current('body-B'),Zone.EXILE,'B'),),'fixture-new-exile')
        self.effect(self.source,Move('source',Zone.GRAVEYARD));self.settle()
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('body-B')).zone)

    def test_wave_last_counter_can_be_spent_in_response_to_fading_then_creature_returns(self):
        self.game('parallax-wave',counters=1);self.kernel.begin_step('A','upkeep')
        self.activate('exile-creature',(self.bodies['B'],));self.top();self.top();self.settle()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('source')).zone)
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('body-B')).zone)

    def test_wave_return_trigger_checkpoint_and_replay(self):
        self.game('parallax-wave');self.activate('exile-creature',(self.bodies['B'],));self.top()
        self.effect(self.source,Move('source',Zone.GRAVEYARD));adapter=RulesActorAdapter(self.kernel)
        for _ in self.state.live_players:adapter.submit(self.kernel.priority,{'kind':'pass','revision':self.kernel.revision})
        replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot())
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('body-B')).zone)

    def test_wave_counter_replacement_changes_entry_amount_but_not_activation_cost(self):
        double=CardProgram('double','Double',('Artifact',),counter_replacements=(
            CounterReplacement('double',Selector(Zone.BATTLEFIELD),kind='fade',multiplier=2),))
        self.game('parallax-wave',source_zone=Zone.HAND,extra=(double,))
        self.state.add_card('double','double','A',Zone.BATTLEFIELD);self.kernel.enter(self.source);self.source=self.state.current('source')
        self.assertEqual({'fade':10},self.counts(self.source))
        self.activate('exile-creature',(self.bodies['B'],));self.assertEqual({'fade':9},self.counts(self.source))

    def test_xolatoyac_entry_adds_flood_and_island_without_losing_forest_or_abilities(self):
        self.game('xolatoyac-the-smiling-flood',source_zone=Zone.HAND);self.flood(self.lands['B'])
        view=self.kernel.effective(self.lands['B'])
        self.assertEqual({'Forest','Island'},set(view.subtypes));self.assertIn('Basic',view.supertypes)
        self.assertEqual({'flood':1},self.counts(self.lands['B']))
        self.window('B')
        self.kernel.commit_action(self.kernel.quote_activation(self.ident(),'B',self.lands['B'],'intrinsic-land:Island'),Payment())
        self.assertEqual((('U',1),),self.state.mana_pool('B'))

    def test_xolatoyac_actual_attack_has_the_same_targeted_flood_effect(self):
        self.game('xolatoyac-the-smiling-flood');self.phase('declare_attackers')
        self.kernel.declare_attackers('A',{self.source:'B'},revision=self.kernel.revision)
        self.target(self.lands['B']);self.top()
        self.assertEqual({'flood':1},self.counts(self.lands['B']));self.assertIn('Island',self.kernel.effective(self.lands['B']).subtypes)

    def test_xolatoyac_duration_survives_its_source_departure_and_control_changes(self):
        self.game('xolatoyac-the-smiling-flood',source_zone=Zone.HAND);self.flood()
        self.effect(self.source,Move('source',Zone.GRAVEYARD))
        self.state.change_control(self.lands['A'],'B')
        self.assertIn('Island',self.kernel.effective(self.lands['A']).subtypes)
        self.assertEqual(1,len(self.kernel.counter_effects))

    def test_xolatoyac_flood_counters_on_untargeted_lands_do_not_grant_island(self):
        self.game('xolatoyac-the-smiling-flood',source_zone=Zone.HAND)
        self.state.add_counters(self.lands['B'],'flood',3);self.flood()
        self.assertNotIn('Island',self.kernel.effective(self.lands['B']).subtypes)
        self.assertIn('Island',self.kernel.effective(self.lands['A']).subtypes)

    def test_xolatoyac_duration_expires_permanently_before_a_later_counter_is_added(self):
        self.game('xolatoyac-the-smiling-flood',source_zone=Zone.HAND);self.flood()
        self.effect(self.lands['A'],RemoveCounters('source','flood'),AddCounters('source','flood',1))
        self.assertEqual({'flood':1},self.counts(self.lands['A']))
        self.assertNotIn('Island',self.kernel.effective(self.lands['A']).subtypes);self.assertFalse(self.kernel.counter_effects)

    def test_xolatoyac_removing_only_one_of_multiple_flood_counters_preserves_duration(self):
        self.game('xolatoyac-the-smiling-flood',source_zone=Zone.HAND);self.flood()
        self.state.add_counters(self.lands['A'],'flood',1)
        self.effect(self.lands['A'],RemoveCounters('source','flood'))
        self.assertIn('Island',self.kernel.effective(self.lands['A']).subtypes);self.assertEqual({'flood':1},self.counts(self.lands['A']))

    def test_xolatoyac_new_resolution_can_start_after_a_previous_duration_ended(self):
        self.game('xolatoyac-the-smiling-flood',source_zone=Zone.HAND);self.flood()
        self.effect(self.lands['A'],RemoveCounters('source','flood'))
        self.phase('declare_attackers');self.kernel.declare_attackers('A',{self.source:'B'},revision=self.kernel.revision)
        self.target(self.lands['A']);self.top()
        self.assertIn('Island',self.kernel.effective(self.lands['A']).subtypes);self.assertEqual(1,len(self.kernel.counter_effects))

    def test_xolatoyac_new_land_incarnation_does_not_retain_old_duration(self):
        self.game('xolatoyac-the-smiling-flood',source_zone=Zone.HAND);self.flood()
        self.effect(self.lands['A'],WithMoved('source',Zone.EXILE,(WithMoved('moved',Zone.BATTLEFIELD,(AddCounters('moved','flood',1),)),)))
        ref=self.state.current('land-A')
        self.assertNotEqual(ref,self.lands['A']);self.assertEqual({'flood':1},self.counts(ref))
        self.assertNotIn('Island',self.kernel.effective(ref).subtypes)

    def test_xolatoyac_phasing_ends_tracked_duration_without_removing_counter(self):
        self.game('xolatoyac-the-smiling-flood',source_zone=Zone.HAND);self.flood()
        self.state.phase(self.lands['A'],True);self.kernel.advance()
        self.state.phase(self.lands['A'],False);self.kernel.advance()
        self.assertEqual({'flood':1},self.counts(self.lands['A']))
        self.assertNotIn('Island',self.kernel.effective(self.lands['A']).subtypes);self.assertFalse(self.kernel.counter_effects)

    def test_xolatoyac_prevented_counter_does_not_begin_new_duration(self):
        cancel=CardProgram('cancel','Cancel',('Enchantment',),counter_replacements=(
            CounterReplacement('cancel',Selector(Zone.BATTLEFIELD),kind='flood',multiplier=0),))
        self.game('xolatoyac-the-smiling-flood',source_zone=Zone.HAND,extra=(cancel,))
        self.state.add_card('cancel','cancel','B',Zone.BATTLEFIELD);self.flood()
        self.assertEqual({},self.counts(self.lands['A']));self.assertNotIn('Island',self.kernel.effective(self.lands['A']).subtypes)
        self.assertFalse(self.kernel.counter_effects)

    def test_xolatoyac_illegal_entry_target_has_neither_counter_nor_duration(self):
        self.game('xolatoyac-the-smiling-flood',source_zone=Zone.HAND)
        self.kernel.enter(self.source);self.source=self.state.current('source');self.target(self.lands['A'])
        self.cast_response('cycle-remove',(self.lands['A'],));self.top();self.settle()
        self.assertFalse(self.kernel.counter_effects)

    def test_xolatoyac_end_step_untaps_own_permanents_with_any_kind_of_counter(self):
        self.game('xolatoyac-the-smiling-flood');rock=self.state.add_card('rock','cycle-rock','A',Zone.BATTLEFIELD)
        for ref,kind in ((self.bodies['A'],'+1/+1'),(rock,'charge'),(self.lands['B'],'flood')):
            self.state.add_counters(ref,kind,1)
        self.phase('precombat_main')
        self.state.set_tapped_batch((self.bodies['A'],rock,self.other,self.lands['B']),True)
        self.phase('end_step');self.top()
        self.assertFalse(self.state.get(self.bodies['A']).tapped);self.assertFalse(self.state.get(rock).tapped)
        self.assertTrue(self.state.get(self.other).tapped);self.assertTrue(self.state.get(self.lands['B']).tapped)

    def test_xolatoyac_duration_survives_cleanup_and_next_turn(self):
        self.game('xolatoyac-the-smiling-flood',source_zone=Zone.HAND);self.flood()
        self.phase('end_step');self.top()
        while self.kernel.active=='A':self.kernel.pass_priority(self.kernel.priority)
        self.assertIn('Island',self.kernel.effective(self.lands['A']).subtypes);self.assertEqual(1,len(self.kernel.counter_effects))

    def test_xolatoyac_public_duration_and_checkpoint_do_not_disclose_hidden_source(self):
        self.game('xolatoyac-the-smiling-flood',source_zone=Zone.HAND);self.flood()
        self.effect(self.source,Move('source',Zone.HAND))
        packet=RulesActorAdapter(self.kernel).packet('B')
        duration,=packet['counter_durations'];self.assertEqual('flood',duration['counter_kind'])
        self.assertEqual([self.lands['A'].to_json()],duration['recipients']);self.assertNotIn('source',duration)
        self.assertNotIn('library-A-7',json.dumps(packet))
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertIn('Island',restored.effective(self.lands['A']).subtypes)

    def test_crystal_division_is_announced_before_payment_and_uses_doubled_placements(self):
        self.game('the-earth-crystal');self.crystal_activation()
        frame=self.kernel.stack[-1]
        self.assertEqual([{'ref':self.bodies['A'].to_json(),'amount':1},{'ref':self.other.to_json(),'amount':1}],frame['values']['counter_division'])
        self.assertTrue(self.state.get(self.source).tapped);self.assertEqual((),self.state.mana_pool('A'))
        self.assertEqual({},self.counts(self.bodies['A']));self.top()
        self.assertEqual({'+1/+1':2},self.counts(self.bodies['A']));self.assertEqual({'+1/+1':2},self.counts(self.other))
        self.assertIsNone(self.kernel.pending_choice)

    def test_crystal_single_target_receives_all_two_counters_then_doubles(self):
        self.game('the-earth-crystal')
        self.crystal_activation((self.bodies['A'],),((self.bodies['A'],2),));self.top()
        self.assertEqual({'+1/+1':4},self.counts(self.bodies['A']))

    def test_crystal_partial_illegality_loses_that_share_without_redistribution(self):
        self.game('the-earth-crystal');self.crystal_activation()
        self.cast_response('cycle-remove',(self.other,));self.top();self.top()
        self.assertEqual({'+1/+1':2},self.counts(self.bodies['A']))

    def test_crystal_all_illegal_targets_do_not_place_counters(self):
        self.game('the-earth-crystal');self.crystal_activation((self.other,),((self.other,2),))
        self.cast_response('cycle-remove',(self.other,));self.top();self.top()
        self.assertFalse(any(e['kind']=='counters_added' for e in self.kernel.semantic_events))

    def test_crystal_departure_preserves_original_division_without_its_doubler(self):
        self.game('the-earth-crystal');self.crystal_activation()
        self.cast_response('cycle-remove',(self.source,));self.top();self.top()
        self.assertEqual({'+1/+1':1},self.counts(self.bodies['A']));self.assertEqual({'+1/+1':1},self.counts(self.other))

    def test_crystal_target_control_is_rechecked_before_placing_its_share(self):
        self.game('the-earth-crystal');self.crystal_activation()
        self.cast_response('cycle-control',(self.other,));self.top();self.top()
        self.assertEqual({'+1/+1':2},self.counts(self.bodies['A']));self.assertEqual({},self.counts(self.other))

    def test_crystal_rejects_missing_zero_negative_duplicate_and_excess_divisions_atomically(self):
        self.game('the-earth-crystal');self.state.add_mana('A',tuple('CCCCGG'));before=self.kernel.snapshot()
        targets=(self.bodies['A'],self.other)
        cases=((),((targets[0],2),(targets[1],0)),((targets[0],3),(targets[1],-1)),
               ((targets[0],True),(targets[1],1)),((targets[0],1),(targets[0],1)),
               ((targets[0],2),(targets[1],1)),((targets[0],1),(self.bodies['B'],1)))
        for division in cases:
            with self.subTest(division=division),self.assertRaises(RulesViolation):
                self.kernel.quote_activation(self.ident(),'A',self.source,'distribute',targets,counter_division=division)
            self.assertEqual(before,self.kernel.snapshot())
        with self.assertRaises(RulesViolation):
            self.kernel.quote_activation(self.ident(),'A',self.source,'distribute',targets,counter_division=[])
        self.assertEqual(before,self.kernel.snapshot())

    def test_crystal_quote_roundtrip_binds_division_and_rejects_tampering_or_staleness(self):
        self.game('the-earth-crystal');self.state.add_mana('A',tuple('CCCCGG'))
        refs=(self.bodies['A'],self.other)
        quote=self.kernel.quote_activation(self.ident(),'A',self.source,'distribute',refs,
            counter_division=((self.other,1),(self.bodies['A'],1)))
        self.assertEqual(quote,PreparedAction.from_json(quote.to_json()))
        self.assertEqual(tuple((ref,1) for ref in refs),quote.counter_division)
        before=self.kernel.snapshot();payment=Payment((('C',4),('G',2)))
        with self.assertRaises(RulesViolation):self.kernel.commit_action(replace(quote,counter_division=((refs[0],2),)),payment)
        self.assertEqual(before,self.kernel.snapshot())
        self.state.add_counters(self.bodies['B'],'charge',1);before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,payment)
        self.assertEqual(before,self.kernel.snapshot())

    def test_crystal_actor_command_and_public_stack_division_replay(self):
        self.game('the-earth-crystal');self.state.add_mana('A',tuple('CCCCGG'));adapter=RulesActorAdapter(self.kernel)
        division=[{'ref':self.bodies['A'].to_json(),'amount':1},{'ref':self.other.to_json(),'amount':1}]
        command={'kind':'activate','revision':self.kernel.revision,'action_id':'divide','source':self.source.to_json(),
            'ability_id':'distribute','targets':[self.bodies['A'].to_json(),self.other.to_json()],'x_value':0,
            'counter_division':division,'payment':{'mana':{'C':4,'G':2},'taps':[]}}
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):adapter.submit('B',command)
        self.assertEqual(before,self.kernel.snapshot());self.assertEqual([],adapter.records)
        adapter.submit('A',command)
        shown=adapter.packet('B')['stack'][0]['counter_division']
        self.assertEqual([{'target':row['ref'],'amount':row['amount']} for row in division],shown)
        for _ in self.state.live_players:adapter.submit(self.kernel.priority,{'kind':'pass','revision':self.kernel.revision})
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())

    def test_crystal_division_checkpoint_preserves_resolution_and_payer_cost(self):
        self.game('the-earth-crystal');self.crystal_activation()
        checkpoint=self.kernel.snapshot();restored=RulesKernel.restore(checkpoint,self.programs)
        self.top()
        for _ in restored.state.live_players:restored.pass_priority(restored.priority)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertEqual(117,checkpoint['schema'])
        checkpoint['schema']=116
        with self.assertRaises(RulesViolation):RulesKernel.restore(checkpoint,self.programs)

    def test_crystal_replacement_order_waits_before_any_divided_placement(self):
        extra=CardProgram('extra','Extra',('Enchantment',),counter_replacements=(
            CounterReplacement('extra',Selector(Zone.BATTLEFIELD,relation='controlled'),kind='+1/+1',additional=1),))
        self.game('the-earth-crystal',extra=(extra,));self.state.add_card('extra','extra','A',Zone.BATTLEFIELD)
        self.crystal_activation();self.top();q=self.kernel.pending_choice
        self.assertEqual('counter_replacement',q.kind);self.assertEqual({},self.counts(self.bodies['A']));self.assertEqual({},self.counts(self.other))
        self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if 'Extra' in o.label)])
        self.assertEqual({},self.counts(self.bodies['A']));self.assertEqual({},self.counts(self.other))
        q=self.kernel.pending_choice;self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if 'Extra' in o.label)])
        self.assertEqual({'+1/+1':4},self.counts(self.bodies['A']));self.assertEqual({'+1/+1':4},self.counts(self.other))

    def test_crystal_reduces_only_generic_cost_of_controllers_green_spells(self):
        green=CardProgram('green','Green',('Instant',),colors=('G',),cast=CastSpec(CostSpec(ManaCost(3,('G',))),timing='instant'))
        blue=replace(green,definition_id='blue',name='Blue',colors=('U',),cast=CastSpec(CostSpec(ManaCost(3,('U',))),timing='instant'))
        pip=replace(green,definition_id='pip',name='Pip',cast=CastSpec(CostSpec(ManaCost(0,('G',))),timing='instant'))
        self.game('the-earth-crystal',extra=(green,blue,pip))
        for player,definition,expected in (('A','green',ManaCost(2,('G',))),('A','blue',ManaCost(3,('U',))),
                                            ('A','pip',ManaCost(0,('G',))),('B','green',ManaCost(3,('G',)))):
            with self.subTest(player=player,definition=definition):
                self.window(player);ref=self.state.add_card(self.ident(),definition,player,Zone.HAND)
                self.assertEqual(expected,self.kernel.quote_cast(self.ident(),player,ref).cost.mana)

    def test_crystal_doubles_only_plus_one_counters_on_controlled_creatures(self):
        self.game('the-earth-crystal')
        self.effect(self.bodies['A'],SelectAll(Selector(Zone.BATTLEFIELD),(AddCounters('selected','+1/+1',1),AddCounters('selected','charge',1))))
        self.assertEqual({'+1/+1':2,'charge':1},self.counts(self.bodies['A']))
        self.assertEqual({'+1/+1':1,'charge':1},self.counts(self.bodies['B']))
        self.assertEqual({'+1/+1':1,'charge':1},self.counts(self.source))

    def test_crystal_doubles_creature_entry_counters(self):
        creature=CardProgram('entry','Entry',('Creature',),power=1,toughness=1,
            entry_counters=(EntryCounters('entry','+1/+1',3),))
        self.game('the-earth-crystal',extra=(creature,))
        ref=self.state.add_card('entry','entry','A',Zone.HAND);self.kernel.enter(ref)
        self.assertEqual({'+1/+1':6},self.counts(self.state.current('entry')))

    def test_generic_divided_spell_requires_authored_cast_and_preserves_two_three_split(self):
        spell=CardProgram('divided','Divided',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',)),1,2),
            spell_effects=(PlaceDividedCounters('charge',5),))
        self.game('parallax-wave',extra=(spell,));ref=self.state.add_card('divided','divided','A',Zone.HAND)
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.stage_spell_for_scenario(ref,'A',(self.bodies['A'],self.other))
        self.assertEqual(before,self.kernel.snapshot())
        quote=self.kernel.quote_cast(self.ident(),'A',ref,(self.bodies['A'],self.other),
            counter_division=((self.bodies['A'],2),(self.other,3)))
        self.kernel.commit_action(quote,Payment());self.top()
        self.assertEqual({'charge':2},self.counts(self.bodies['A']));self.assertEqual({'charge':3},self.counts(self.other))

    def test_compiler_rejects_unbound_removal_and_invalid_counter_duration(self):
        for effect in (RemoveCounters('missing','ice'),RemoveCounters('source',''),RemoveCounters('source','ice',True),
                       RemoveCounters('source','ice',-1),WhileCounter('source',(AddSubtypes('Land',('Island',)),),''),
                       WhileCounter('missing',(AddSubtypes('Land',('Island',)),),'flood')):
            with self.subTest(effect=effect),self.assertRaises(RulesViolation):
                validate(CardProgram('bad','Bad',('Instant',),spell_effects=(effect,)))
        node=encode(WhileCounter('source',(AddSubtypes('Land',('Island',)),),'flood'));del node['counter_kind']
        with self.assertRaises(RulesViolation):decode(node)

    def test_compiler_rejects_ambiguous_division_timing_and_target_shapes(self):
        spec=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',)),1,2)
        card=CardProgram('bad','Bad',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_targets=spec,spell_effects=(PlaceDividedCounters('charge',2),))
        invalid=(replace(card,spell_effects=(May((PlaceDividedCounters('charge',2),)),)),
                 replace(card,spell_effects=(PlaceDividedCounters('charge',2),PlaceDividedCounters('charge',2))),
                 replace(card,spell_targets=replace(spec,maximum=3)),
                 replace(card,spell_targets=TargetSpec(players='all')),
                 replace(card,spell_effects=(PlaceDividedCounters('charge',True),)),
                 replace(card,cast=None))
        for program in invalid:
            with self.subTest(program=program),self.assertRaises(RulesViolation):validate(program)
        with self.assertRaises(RulesViolation):
            validate(CardProgram('trigger','Trigger',('Enchantment',),abilities=(AbilityProgram('bad',
                EventPattern('step_began',step='upkeep'),(PlaceDividedCounters('charge',2),),targets=spec),)))

    def test_compiler_rejects_ambiguous_counter_state_filters(self):
        ability=self.cards['dark-depths'].abilities[0]
        for event in (replace(ability.event,subject='any'),replace(ability.event,counters=()),
                      replace(ability.event,types=('Land',)),replace(ability.event,from_zone=Zone.BATTLEFIELD)):
            with self.subTest(event=event),self.assertRaises(RulesViolation):
                validate(replace(self.cards['dark-depths'],abilities=(replace(ability,event=event),)))
        with self.assertRaises(RulesViolation):
            validate(replace(self.cards['dark-depths'],abilities=(replace(ability,intervening_if=SourceCountersCondition('ice')),)))


if __name__=='__main__':unittest.main()
