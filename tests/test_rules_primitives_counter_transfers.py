"""Counter snapshots, atomic authored transfers and gross life-loss history."""
import json
import unittest
from dataclasses import replace
from pathlib import Path

from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState, Zone, ZoneMove, RulesViolation, ObjectRef
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_choices import CounterAllocationRequest
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed, source_facts, digest
from edh_gauntlet.rules_characteristics import condition_holds, condition_selectors, evaluate, evaluate_exhaustive
from edh_gauntlet.catalog import load_catalog

CARDS=('forgotten-ancient','the-ozolith','aven-courier','essence-channeler')


class CounterTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        reviewed=load_reviewed(cls.root)
        cls.rows={key:reviewed[key]['review'] for key in CARDS}
        cls.cards={key:reviewed[key]['program'] for key in CARDS}
        cls.base=tuple(row['program'] for row in reviewed.values())

    def game(self,key='forgotten-ancient',*,extra=(),source_zone=Zone.BATTLEFIELD):
        body=CardProgram('transfer-body','Body',('Creature',),power=3,toughness=10)
        spell=CardProgram('transfer-spell','Spell',('Instant',),cast=CastSpec(CostSpec(),timing='instant'))
        removal=replace(spell,definition_id='transfer-remove',name='Remove',
            spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD)),spell_effects=(Move('target',Zone.GRAVEYARD),))
        control=replace(removal,definition_id='transfer-control',name='Control',spell_effects=(GainControl('target'),))
        blink=replace(removal,definition_id='transfer-blink',name='Blink',
            spell_effects=(WithMoved('target',Zone.EXILE,(Move('moved',Zone.BATTLEFIELD),)),))
        rock=CardProgram('transfer-rock','Rock',('Artifact',))
        self.programs=self.base+(body,spell,removal,control,blink,rock)+extra
        self.state=RulesState(('A','B','C','D'));self.kernel=RulesKernel(self.state,self.programs)
        self.kernel.open_window_for_scenario('A')
        self.source=self.state.add_card('source',self.cards[key].definition_id,'A',source_zone)
        self.bodies={p:self.state.add_card('body-'+p,'transfer-body',p,Zone.BATTLEFIELD) for p in self.state.players}
        for p in self.state.players:
            for n in range(8):self.state.add_card('library-'+p+'-'+str(n),'transfer-body',p,Zone.LIBRARY)
        self.number=0

    def ident(self):
        self.number+=1
        return 'transfer-action-'+str(self.number)

    def top(self):
        self.assertTrue(self.kernel.stack)
        result=None
        for _ in self.state.live_players:result=self.kernel.pass_priority(self.kernel.priority)
        return result

    def settle(self):
        for _ in range(40):
            self.assertIsNone(self.kernel.pending_choice)
            if not self.kernel.stack:return
            self.top()
        self.fail('Unexpected trigger loop')

    def choose(self,key):
        q=self.kernel.pending_choice;self.assertIsNotNone(q)
        return self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.key==key)])

    def target(self,ref):
        q=self.kernel.pending_choice;self.assertEqual('trigger_targets',q.kind)
        return self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.ref==ref)])

    def order(self):
        q=self.kernel.pending_choice
        self.assertEqual('trigger_order',q.kind)
        return self.kernel.answer(q.request_id,q.actor,list(range(len(q.options))))

    def effect(self,player,*effects):
        return self.kernel.execute_for_scenario(self.bodies[player],player,effects)

    def cast(self,player='B',definition='transfer-spell',targets=()):
        if not self.kernel.stack and self.kernel.turn_schedule is None:
            self.kernel.open_window_for_scenario('A',priority_actor=player)
        while self.kernel.priority!=player:self.kernel.pass_priority(self.kernel.priority)
        ref=self.state.add_card(self.ident(),definition,player,Zone.HAND)
        self.kernel.commit_action(self.kernel.quote_cast(self.ident(),player,ref,targets),Payment())
        return ref

    def move(self,ref,destination=Zone.GRAVEYARD):
        return self.kernel.execute_for_scenario(ref,self.state.get(ref).controller,(Move('source',destination),))

    def counts(self,ref):
        return dict(self.state.get(ref).counters)

    def allocate(self,rows,*,actor='A',request=None):
        q=self.kernel.pending_choice
        return self.kernel.allocate_counters(request or q.request_id,actor,
            [{'ref':ref.to_json(),'amount':n} for ref,n in rows])

    def upkeep(self,amount=5):
        self.state.add_counters(self.source,'+1/+1',amount)
        self.kernel.begin_step('A','upkeep')
        return self.top()

    def phase(self,name):
        self.kernel.begin_turn_for_scenario('A')
        for _ in range(40):
            if self.kernel.phase==name:return
            self.assertIsNone(self.kernel.pending_choice)
            self.assertFalse(self.kernel.stack)
            self.kernel.pass_priority(self.kernel.priority)
        self.fail('Did not reach '+name)

    def attack(self,target):
        self.phase('declare_attackers')
        self.kernel.declare_attackers('A',{self.source:'B'},revision=self.kernel.revision)
        self.target(target)

    def combat(self,target=None):
        self.phase('begin_combat')
        if target is not None:self.target(target)

    def modifier(self,multiplier=2,additional=0,divisor=1,controller='A',ident='modifier'):
        program=CardProgram(ident,ident,('Enchantment',),counter_replacements=(
            CounterReplacement('modify',Selector(Zone.BATTLEFIELD,relation='controlled'),
                multiplier=multiplier,additional=additional,divisor=divisor),))
        return program

    def add_modifier(self,program,controller='A'):
        return self.state.add_card(program.definition_id,program.definition_id,controller,Zone.BATTLEFIELD)

    def test_printed_faces_and_source_facts(self):
        catalog={c.card_id:c for c in load_catalog(self.root/'data/catalog/cards.json')}
        self.assertEqual(set(CARDS),set(self.cards))
        for key,program in self.cards.items():
            with self.subTest(card=key):
                self.assertEqual(digest(source_facts(catalog[key])),self.rows[key]['source_facts_sha256'])
                self.assertEqual(self.rows[key]['program'],encode(program))
                face=catalog[key].faces[0]
                self.assertEqual(1,len(catalog[key].faces))
                for field in ('types','subtypes','supertypes','colors'):
                    self.assertEqual(set(getattr(face,field)),set(getattr(program,field)))
                for field in ('power','toughness','mana_value'):
                    self.assertEqual(getattr(face,field),getattr(program,field))
                self.assertEqual(catalog[key].name,program.name)

    def test_corrected_essence_channeler_annotation_and_catalog_are_two_one(self):
        annotations=json.loads((self.root/'data/reference/card_catalog_annotations.json').read_text(encoding='utf-8'))
        self.assertEqual({'power':2,'toughness':1},annotations['cards']['essence-channeler']['combat'])
        self.assertEqual((2,1),(self.cards['essence-channeler'].power,self.cards['essence-channeler'].toughness))

    def test_all_four_normal_casting_costs_and_entry(self):
        for key in CARDS:
            with self.subTest(card=key):
                self.game(key,source_zone=Zone.HAND)
                cost=self.cards[key].cast.cost.mana
                self.assertEqual(cost,self.kernel.quote_cast(self.ident(),'A',self.source).cost.mana)
                symbols=cost.symbols+('C',)*cost.generic
                self.state.add_mana('A',symbols)
                self.kernel.commit_action(self.kernel.quote_cast(self.ident(),'A',self.source),
                    Payment(tuple((s,symbols.count(s)) for s in sorted(set(symbols)))))
                self.settle()
                self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('source')).zone)
                self.assertEqual((),self.state.mana_pool('A'))

    def test_ancient_may_accept_or_decline_each_players_spell(self):
        self.game()
        for player in ('A','B','C','D'):
            self.cast(player);self.assertEqual(2,len(self.kernel.stack))
            self.top();self.choose('no' if player=='A' else 'yes');self.settle()
        self.assertEqual({'+1/+1':3},self.counts(self.source))

    def test_ancient_upkeep_belongs_to_its_controller(self):
        self.game();self.state.add_counters(self.source,'+1/+1',3)
        self.kernel.begin_step('B','upkeep');self.assertFalse(self.kernel.stack)
        self.kernel.begin_step('A','upkeep');self.assertEqual(1,len(self.kernel.stack))

    def test_ancient_allocation_is_optional_and_excludes_itself(self):
        self.game();q=self.upkeep()
        self.assertIsInstance(q,CounterAllocationRequest)
        self.assertNotIn(self.source,{o.ref for o in q.options})
        self.allocate([]);self.assertEqual({'+1/+1':5},self.counts(self.source))
        self.assertFalse(any(e['kind']=='counters_removed' for e in self.kernel.semantic_events))

    def test_ancient_partial_allocation_can_include_opponents_creatures(self):
        self.game();self.upkeep(7)
        self.allocate([(self.bodies['B'],2),(self.bodies['A'],3)])
        self.assertEqual({'+1/+1':2},self.counts(self.source))
        self.assertEqual({'+1/+1':2},self.counts(self.bodies['B']))
        self.assertEqual({'+1/+1':3},self.counts(self.bodies['A']))

    def test_ancient_large_budget_does_not_enumerate_counter_combinations(self):
        self.game();q=self.upkeep(1000000)
        self.assertEqual(4,len(q.options));self.assertEqual(1000000,q.maximum)
        self.allocate([(self.bodies['D'],1000000)])
        self.assertEqual({},self.counts(self.source));self.assertEqual({'+1/+1':1000000},self.counts(self.bodies['D']))

    def test_allocation_rejects_authentication_identity_and_ordinary_answers(self):
        self.game();q=self.upkeep();before=self.kernel.snapshot()
        for action in (lambda:self.allocate([],actor='B'),lambda:self.allocate([],request='missing'),
                       lambda:self.kernel.answer(q.request_id,'A',[0])):
            with self.assertRaises(RulesViolation):action()
            self.assertEqual(before,self.kernel.snapshot())

    def test_allocation_rejects_invalid_rows_without_partial_removals(self):
        self.game();q=self.upkeep();a=self.bodies['A'].to_json();before=self.kernel.snapshot()
        cases=[None,{},[{'ref':a,'amount':0}],[{'ref':a,'amount':-1}],[{'ref':a,'amount':True}],
               [{'ref':a,'amount':6}],[{'ref':a,'amount':1},{'ref':a,'amount':1}],
               [{'ref':self.source.to_json(),'amount':1}],[{'ref':a,'amount':1,'extra':1}],
               [{'ref':{'card_id':'missing','incarnation':0},'amount':1}]]
        for rows in cases:
            with self.subTest(rows=rows),self.assertRaises(RulesViolation):
                self.kernel.allocate_counters(q.request_id,'A',rows)
            self.assertEqual(before,self.kernel.snapshot())

    def test_allocation_rejects_stale_revision(self):
        self.game();q=self.upkeep();self.state.add_counters(self.source,'+1/+1',1)
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.allocate([(self.bodies['A'],1)])
        self.assertEqual(before,self.kernel.snapshot())

    def test_allocation_checkpoint_preserves_exact_request_and_once_only_commit(self):
        self.game();q=self.upkeep();restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.assertEqual(q.to_json(),restored.pending_choice.to_json())
        rows=[{'ref':self.bodies['B'].to_json(),'amount':2}]
        self.kernel.allocate_counters(q.request_id,'A',rows);restored.allocate_counters(q.request_id,'A',rows)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.allocate_counters(q.request_id,'A',rows)
        self.assertEqual(before,self.kernel.snapshot())

    def test_allocation_actor_packet_and_journal_replay(self):
        self.game();q=self.upkeep();adapter=RulesActorAdapter(self.kernel)
        self.assertEqual('counter_allocation',adapter.packet('A')['decision']['choice']['kind'])
        self.assertEqual({'kind':'waiting','actor':'A'},adapter.packet('C')['decision'])
        self.assertNotIn('library-A-7',json.dumps(adapter.packet('C')))
        command={'kind':'allocate_counters','revision':self.kernel.revision,'request_id':q.request_id,
            'allocations':[{'ref':self.bodies['B'].to_json(),'amount':2}]}
        with self.assertRaises(RulesViolation):adapter.submit('B',command)
        self.assertEqual([],adapter.records)
        adapter.submit('A',command)
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())

    def test_transfer_doubling_changes_placement_not_number_removed(self):
        modifier=self.modifier();self.game(extra=(modifier,));self.add_modifier(modifier)
        self.upkeep(5);self.allocate([(self.bodies['A'],3)])
        self.assertEqual({'+1/+1':2},self.counts(self.source));self.assertEqual({'+1/+1':6},self.counts(self.bodies['A']))

    def test_noncommuting_replacements_wait_before_any_recipient_changes(self):
        double=self.modifier(ident='double');extra=self.modifier(multiplier=1,additional=1,ident='extra')
        self.game(extra=(double,extra));self.add_modifier(double);self.add_modifier(extra)
        self.upkeep(5);self.allocate([(self.bodies['B'],1),(self.bodies['A'],2)])
        q=self.kernel.pending_choice;self.assertEqual('counter_replacement',q.kind)
        self.assertEqual({'+1/+1':5},self.counts(self.source))
        self.assertEqual({},self.counts(self.bodies['B']));self.assertEqual({},self.counts(self.bodies['A']))
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        index=next(i for i,o in enumerate(q.options) if 'extra' in o.label)
        self.kernel.answer(q.request_id,'A',[index]);restored.answer(q.request_id,'A',[index])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual({'+1/+1':6},self.counts(self.bodies['A']))
        self.assertEqual({'+1/+1':1},self.counts(self.bodies['B']))
        self.assertEqual({'+1/+1':2},self.counts(self.source))

    def test_transfer_halving_to_zero_still_removes_the_original_counter(self):
        half=self.modifier(multiplier=1,divisor=2)
        self.game(extra=(half,));self.add_modifier(half);self.upkeep(2)
        self.allocate([(self.bodies['A'],1)])
        self.assertEqual({'+1/+1':1},self.counts(self.source));self.assertEqual({},self.counts(self.bodies['A']))

    def test_atomic_state_transfer_rejects_invalid_destination_and_excess_removal(self):
        self.game();self.state.add_counters(self.source,'+1/+1',3);before=self.state.snapshot()
        bad=ObjectRef('missing',0)
        for placements,removals in (
            (((bad,(('+1/+1',1),)),),((self.source,(('+1/+1',1),)),)),
            (((self.bodies['A'],(('+1/+1',1),)),),((self.source,(('+1/+1',4),)),)),
            (((self.bodies['A'],(('+1/+1',0),)),),((self.source,(('+1/+1',1),)),))):
            with self.assertRaises(RulesViolation):self.state.put_counters_batch(placements,removals=removals)
            self.assertEqual(before,self.state.snapshot())

    def test_ozolith_copies_all_departing_counter_kinds_without_removing_them(self):
        self.game('the-ozolith');ref=self.bodies['A']
        for kind,n in (('+1/+1',2),('flying',1),('shield',3)):self.state.add_counters(ref,kind,n)
        self.move(ref,Zone.HAND);self.settle()
        self.assertEqual({'+1/+1':2,'flying':1,'shield':3},self.counts(self.source))
        self.assertEqual({},self.counts(self.state.current(ref.card_id)))
        self.assertFalse(any(e['kind']=='counters_removed' for e in self.kernel.semantic_events))

    def test_ozolith_does_not_watch_opponents_noncreatures_or_counterless_creatures(self):
        for kind in ('opponent','artifact','empty'):
            with self.subTest(kind=kind):
                self.game('the-ozolith')
                ref=self.bodies['B'] if kind=='opponent' else self.bodies['A']
                if kind=='artifact':ref=self.state.add_card('rock','transfer-rock','A',Zone.BATTLEFIELD)
                if kind!='empty':self.state.add_counters(ref,'charge',2)
                self.move(ref);self.assertFalse(self.kernel.stack);self.assertEqual({},self.counts(self.source))

    def test_ozolith_uses_departing_controller_instead_of_owner(self):
        self.game('the-ozolith');ref=self.bodies['B']
        self.state.change_control(ref,'A');self.state.add_counters(ref,'charge',2)
        self.move(ref);self.settle();self.assertEqual({'charge':2},self.counts(self.source))

    def test_ozolith_snapshot_survives_departed_objects_new_incarnation(self):
        self.game('the-ozolith');ref=self.bodies['A'];self.state.add_counters(ref,'charge',2)
        self.move(ref,Zone.HAND)
        self.state.move((ZoneMove(self.state.current(ref.card_id),Zone.BATTLEFIELD,'A'),),'fixture-return')
        new=self.state.current(ref.card_id);self.state.add_counters(new,'charge',9)
        self.settle();self.assertEqual({'charge':2},self.counts(self.source));self.assertEqual({'charge':9},self.counts(new))

    def test_ozolith_departure_copy_does_not_follow_blinked_ozolith(self):
        self.game('the-ozolith');self.state.add_counters(self.bodies['A'],'charge',2);self.move(self.bodies['A'])
        self.cast('B','transfer-blink',(self.source,));self.top();self.settle()
        self.assertNotEqual(self.source,self.state.current('source'));self.assertEqual({},self.counts(self.state.current('source')))

    def test_ozolith_combat_moves_every_kind_to_an_opponents_creature(self):
        self.game('the-ozolith')
        for kind,n in (('+1/+1',3),('vigilance',1),('charge',2)):self.state.add_counters(self.source,kind,n)
        self.combat(self.bodies['B']);self.top();self.choose('yes')
        self.assertEqual({},self.counts(self.source))
        self.assertEqual({'+1/+1':3,'vigilance':1,'charge':2},self.counts(self.bodies['B']))

    def test_ozolith_combat_can_decline_all_counters(self):
        self.game('the-ozolith');self.state.add_counters(self.source,'charge',3)
        self.combat(self.bodies['A']);self.top();self.choose('no')
        self.assertEqual({'charge':3},self.counts(self.source));self.assertEqual({},self.counts(self.bodies['A']))

    def test_ozolith_empty_at_combat_does_not_trigger(self):
        self.game('the-ozolith');self.combat()
        self.assertFalse(self.kernel.stack);self.assertIsNone(self.kernel.pending_choice)

    def test_ozolith_intervening_condition_rechecks_counters(self):
        self.game('the-ozolith');self.state.add_counters(self.source,'charge',2)
        self.combat(self.bodies['A'])
        self.state.put_counters_batch((),removals=((self.source,(('charge',2),)),))
        self.top();self.assertIsNone(self.kernel.pending_choice);self.assertEqual({},self.counts(self.bodies['A']))

    def test_ozolith_moves_current_counters_including_newly_added_ones(self):
        self.game('the-ozolith');self.state.add_counters(self.source,'charge',2)
        self.combat(self.bodies['A']);self.state.add_counters(self.source,'flying',1)
        self.top();self.choose('yes');self.assertEqual({'charge':2,'flying':1},self.counts(self.bodies['A']))

    def test_ozolith_illegal_target_does_not_remove_any_counters(self):
        self.game('the-ozolith');self.state.add_counters(self.source,'charge',2)
        self.combat(self.bodies['A']);self.cast('B','transfer-remove',(self.bodies['A'],));self.top();self.settle()
        self.assertEqual({'charge':2},self.counts(self.source))

    def test_ozolith_departed_source_cannot_move_counters(self):
        self.game('the-ozolith');self.state.add_counters(self.source,'charge',2)
        self.combat(self.bodies['A']);self.cast('B','transfer-remove',(self.source,));self.top();self.settle()
        self.assertEqual({},self.counts(self.bodies['A']))

    def test_moving_counters_to_same_object_is_a_noop(self):
        self.game('the-ozolith');self.state.add_counters(self.source,'charge',3)
        self.kernel.execute_for_scenario(self.source,'A',(MoveCounters('source','source'),))
        self.assertEqual({'charge':3},self.counts(self.source))
        self.assertFalse(any(e['kind']=='counters_removed' for e in self.kernel.semantic_events))

    def test_aven_selects_target_before_counter_kind_at_resolution(self):
        self.game('aven-courier');self.state.add_counters(self.source,'flying',1)
        rock=self.state.add_card('rock','transfer-rock','A',Zone.BATTLEFIELD);self.state.add_counters(rock,'charge',4)
        self.attack(self.bodies['A'])
        self.assertIsNone(self.kernel.pending_choice)
        self.top();q=self.kernel.pending_choice;self.assertEqual('counter_kind',q.kind)
        index=next(i for i,o in enumerate(q.options) if o.ref==rock)
        self.kernel.answer(q.request_id,'A',[index])
        self.assertEqual({'charge':1},self.counts(self.bodies['A']));self.assertEqual({'charge':4},self.counts(rock))

    def test_aven_may_choose_kind_already_on_target_without_adding_it(self):
        self.game('aven-courier');self.state.add_counters(self.bodies['A'],'charge',2)
        self.attack(self.bodies['A']);self.top()
        if self.kernel.pending_choice:self.choose('0')
        self.assertEqual({'charge':2},self.counts(self.bodies['A']))

    def test_aven_no_counter_kinds_is_a_resolved_noop(self):
        self.game('aven-courier');self.attack(self.bodies['A']);self.top()
        self.assertIsNone(self.kernel.pending_choice);self.assertEqual({},self.counts(self.bodies['A']))

    def test_aven_counter_kind_choices_read_current_battlefield(self):
        self.game('aven-courier');self.state.add_counters(self.source,'flying',1)
        self.attack(self.bodies['A'])
        self.state.add_counters(self.bodies['C'],'opponent-only',2)
        self.state.add_counters(self.source,'charge',1)
        self.top();q=self.kernel.pending_choice
        self.assertEqual(2,len(q.options));self.assertTrue(all(o.ref==self.source for o in q.options))
        index=next(i for i,o in enumerate(q.options) if o.label.endswith(': charge'))
        self.kernel.answer(q.request_id,'A',[index]);self.assertEqual({'charge':1},self.counts(self.bodies['A']))

    def test_aven_placement_uses_shared_counter_replacements(self):
        modifier=self.modifier();self.game('aven-courier',extra=(modifier,));self.add_modifier(modifier)
        self.state.add_counters(self.source,'charge',1);self.attack(self.bodies['A']);self.top()
        if self.kernel.pending_choice:self.choose('0')
        self.assertEqual({'charge':2},self.counts(self.bodies['A']));self.assertEqual({'charge':1},self.counts(self.source))

    def test_aven_target_control_is_rechecked_on_resolution(self):
        self.game('aven-courier');self.state.add_counters(self.source,'charge',1)
        self.attack(self.bodies['A']);self.cast('B','transfer-control',(self.bodies['A'],));self.top();self.settle()
        self.assertEqual('B',self.state.get(self.bodies['A']).controller);self.assertEqual({},self.counts(self.bodies['A']))

    def test_aven_counter_choice_checkpoint_and_actor_replay(self):
        self.game('aven-courier');self.state.add_counters(self.source,'charge',1);self.state.add_counters(self.source,'flying',1)
        self.attack(self.bodies['A']);self.top();q=self.kernel.pending_choice
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs);adapter=RulesActorAdapter(self.kernel)
        command={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[0]}
        adapter.submit('A',command);restored.answer(q.request_id,'A',[0])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())

    def test_channeler_keywords_use_gross_loss_even_when_life_total_increases(self):
        self.game('essence-channeler')
        self.assertNotIn('flying',self.kernel.effective(self.source).keywords)
        self.effect('A',LoseLife('controller',2),GainLife(5));self.settle()
        self.assertEqual(43,self.state.life('A'));self.assertEqual(2,self.state.life_lost_this_turn('A'))
        self.assertTrue({'flying','vigilance'}<=set(self.kernel.effective(self.source).keywords))

    def test_channeler_life_loss_resets_at_every_players_turn(self):
        self.game('essence-channeler');self.state.lose_life_batch(('A','B'),3)
        self.state.start_turn('C')
        self.assertEqual({'A':0,'B':0,'C':0,'D':0},RulesActorAdapter(self.kernel).packet('A')['life_lost_this_turn'])
        self.assertNotIn('flying',self.kernel.effective(self.source).keywords)

    def test_channeler_sees_loss_before_it_entered_and_current_controller(self):
        self.game('essence-channeler',source_zone=Zone.HAND);self.effect('A',LoseLife('controller',1))
        self.kernel.enter(self.source);self.source=self.state.current('source')
        self.assertIn('flying',self.kernel.effective(self.source).keywords)
        self.state.change_control(self.source,'B');self.assertNotIn('flying',self.kernel.effective(self.source).keywords)
        self.state.lose_life_batch(('B',),1);self.assertIn('vigilance',self.kernel.effective(self.source).keywords)

    def test_channeler_one_counter_per_gain_event_not_per_life_or_opponents_gain(self):
        self.game('essence-channeler');self.effect('A',GainLife(7));self.settle()
        self.assertEqual({'+1/+1':1},self.counts(self.source))
        self.effect('B',GainLife(3));self.effect('A',GainLife(0))
        self.assertFalse(self.kernel.stack);self.assertEqual({'+1/+1':1},self.counts(self.source))

    def test_channeler_ordinary_cost_life_payment_counts_as_loss(self):
        rock=CardProgram('life-rock','Life Rock',('Artifact',),activated=(
            ActivatedProgram('mana',CostSpec(life=1),(AddMana(('G',)),),mana_ability=True),))
        self.game('essence-channeler',extra=(rock,));ref=self.state.add_card('rock','life-rock','A',Zone.BATTLEFIELD)
        self.kernel.commit_action(self.kernel.quote_activation(self.ident(),'A',ref,'mana'),Payment())
        self.assertEqual(1,self.state.life_lost_this_turn('A'));self.assertIn('flying',self.kernel.effective(self.source).keywords)

    def test_channeler_shock_land_entry_payment_counts_as_loss(self):
        self.game('essence-channeler');ref=self.state.add_card('shock','catalog:hallowed-fountain','A',Zone.HAND)
        self.kernel.enter(ref);q=self.kernel.pending_choice
        index=next(i for i,o in enumerate(q.options) if o.key=='pay')
        self.kernel.answer(q.request_id,'A',[index])
        self.assertEqual(2,self.state.life_lost_this_turn('A'));self.assertIn('flying',self.kernel.effective(self.source).keywords)

    def test_damage_and_simultaneous_lifelink_retain_gross_loss(self):
        self.game('essence-channeler')
        self.state.damage_batch((
            {'source':self.state.get(self.bodies['B']),'target':'A','amount':3},
            {'source':self.state.get(self.bodies['A']),'target':'B','amount':5,'lifelink':True}))
        self.assertEqual(42,self.state.life('A'));self.assertEqual(3,self.state.life_lost_this_turn('A'))
        self.assertIn('flying',self.kernel.effective(self.source).keywords)
        self.assertEqual(5,self.state.life_lost_this_turn('B'))

    def test_invalid_damage_batch_does_not_record_uncommitted_loss(self):
        self.game('essence-channeler');before=self.state.snapshot()
        with self.assertRaises(RulesViolation):
            self.state.damage_batch((
                {'source':self.state.get(self.bodies['B']),'target':'A','amount':3},
                {'source':self.state.get(self.bodies['A']),'target':'B','amount':-1}))
        self.assertEqual(before,self.state.snapshot());self.assertEqual(0,self.state.life_lost_this_turn('A'))

    def test_channeler_death_copies_every_counter_kind(self):
        self.game('essence-channeler')
        for kind,n in (('+1/+1',2),('flying',1),('charge',4)):self.state.add_counters(self.source,kind,n)
        self.move(self.source);self.target(self.bodies['A']);self.settle()
        self.assertEqual({'+1/+1':2,'flying':1,'charge':4},self.counts(self.bodies['A']))

    def test_channeler_death_target_is_controlled_and_must_stay_legal(self):
        self.game('essence-channeler');self.state.add_counters(self.source,'charge',2)
        self.move(self.source);q=self.kernel.pending_choice
        self.assertEqual({self.bodies['A']},{o.ref for o in q.options})
        self.target(self.bodies['A']);self.cast('B','transfer-control',(self.bodies['A'],));self.top();self.settle()
        self.assertEqual({},self.counts(self.bodies['A']))

    def test_channeler_leaving_without_dying_does_not_copy_counters(self):
        self.game('essence-channeler');self.state.add_counters(self.source,'charge',2)
        self.move(self.source,Zone.EXILE);self.assertFalse(self.kernel.stack);self.assertIsNone(self.kernel.pending_choice)

    def test_channeler_and_ozolith_independently_copy_the_same_departure(self):
        self.game('essence-channeler');ozolith=self.state.add_card('ozolith',self.cards['the-ozolith'].definition_id,'A',Zone.BATTLEFIELD)
        self.state.add_counters(self.source,'charge',3);self.move(self.source)
        self.order();self.target(self.bodies['A']);self.settle()
        self.assertEqual({'charge':3},self.counts(ozolith));self.assertEqual({'charge':3},self.counts(self.bodies['A']))

    def test_channeler_lethal_damage_captures_opposing_counters_before_cancellation(self):
        self.game('essence-channeler')
        self.state.put_counters_batch(((self.source,(('+1/+1',1),('-1/-1',1),('charge',2))),))
        self.state.damage_batch(({'source':self.state.get(self.bodies['B']),'target':self.source,'amount':1},))
        self.kernel.advance();self.target(self.bodies['A'])
        frame=self.kernel.stack[-1]
        self.assertEqual({'+1/+1':1,'-1/-1':1,'charge':2},frame['values']['event_counters'])
        self.settle();self.assertEqual({'charge':2},self.counts(self.bodies['A']))

    def test_life_history_checkpoint_and_legacy_schema_rejection(self):
        self.game('essence-channeler');self.state.lose_life_batch(('A',),2);self.state.gain_life('A',3)
        checkpoint=self.kernel.snapshot();restored=RulesKernel.restore(checkpoint,self.programs)
        self.assertEqual(116,checkpoint['schema']);self.assertEqual(13,checkpoint['state']['schema'])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertIn('flying',restored.effective(self.source).keywords)
        checkpoint['schema']=115
        with self.assertRaises(RulesViolation):RulesKernel.restore(checkpoint,self.programs)
        state=self.state.snapshot();state['schema']=12
        with self.assertRaises(RulesViolation):RulesState.restore(state)

    def test_condition_environment_and_layer_evaluators_agree(self):
        self.game('essence-channeler');self.state.lose_life_batch(('A',),1);obj=self.state.get(self.source)
        condition=AllConditions((LifeLostCondition(),NotCondition(SourceCountersCondition('charge'))))
        environment={'life_lost_totals':{'A':1,'B':0,'C':0,'D':0},'life_totals':{p:40 for p in self.state.players}}
        self.assertTrue(condition_holds(condition,obj,self.state.objects(),{},**environment))
        self.assertEqual((),tuple(condition_selectors(condition)))
        with self.assertRaises(RulesViolation):condition_holds(LifeLostCondition(),obj,self.state.objects(),{})
        self.assertEqual(evaluate(self.state.objects(),self.kernel.definitions,**environment),
            evaluate_exhaustive(self.state.objects(),self.kernel.definitions,**environment))

    def test_compiler_rejects_unbound_captures_bad_selectors_and_invalid_conditions(self):
        effects=(CopyEventCounters('source'),MoveCounters('missing','source'),MoveCounters('source','source',''),
                 DistributeCounters('source',Selector(Zone.HAND),'+1/+1'),
                 CopyCounterKind(Selector(Zone.GRAVEYARD),'source'),
                 CopyCounterKind(Selector(Zone.BATTLEFIELD),'source',1))
        for effect in effects:
            with self.subTest(effect=effect),self.assertRaises(RulesViolation):
                validate(CardProgram('bad','Bad',('Instant',),spell_effects=(effect,)))
        for condition in (LifeLostCondition(0),LifeLostCondition(True),SourceCountersCondition('',1),
                          SourceCountersCondition(None,0),SourceCountersCondition(None,True)):
            with self.subTest(condition=condition),self.assertRaises(RulesViolation):
                validate(CardProgram('bad','Bad',('Instant',),spell_effects=(IfCondition(condition,(GainLife(1),)),)))
        node=encode(MoveCounters('source','source'));del node['kind']
        with self.assertRaises(RulesViolation):decode(node)


if __name__=='__main__':unittest.main()
