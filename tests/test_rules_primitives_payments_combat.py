"""Hosted conformance for all seven cards in the first four-pass batch."""
import itertools
import json
import unittest
from collections import Counter as Counts
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,RulesViolation,Zone,ZoneMove,ObjectRef,PlayerRef,ResourcePayment
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment,PreparedAction
from edh_gauntlet.rules_actor import project_actor
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed,digest,source_facts
from edh_gauntlet.rules_characteristics import evaluate,evaluate_exhaustive
from edh_gauntlet.catalog import load_catalog

CARDS=('chthonian-nightmare','maze-s-end','rhythm-of-the-wild','parasitic-impetus',
       'propaganda','defiler-of-vigor','darksteel-mutation')


class PaymentsCombatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        reviewed=load_reviewed(cls.root)
        draft=json.loads((cls.root/'data/rules/draft_cards.json').read_text(encoding='utf-8'))
        cls.rows={row['card_id']:row for row in draft['drafts'] if row['card_id'] in CARDS}
        cls.cards={key:validate(decode(row['program'])) for key,row in cls.rows.items()}
        cls.base=tuple(row['program'] for row in reviewed.values())+tuple(cls.cards.values())
        cls.prefix='draft:'

    def game(self,extra=(),players=('A','B','C','D')):
        body=CardProgram('pc-body','Body',('Creature',),power=2,toughness=3,mana_value=2,colors=('G',),
            cast=CastSpec(CostSpec(ManaCost(1,('G',)))))
        zero=CardProgram('pc-zero','Zero',('Creature',),power=1,toughness=1,cast=CastSpec(CostSpec()))
        counter=CardProgram('pc-counter','Counter',('Instant',),mana_value=2,colors=('U',),
            cast=CastSpec(CostSpec(ManaCost(1,('U',))),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.STACK)),spell_effects=(Counter('target'),))
        self.programs=self.base+(body,zero,counter)+extra
        self.state=RulesState(players,seed=59);self.kernel=RulesKernel(self.state,self.programs);self.serial=0
        self.anchor=self.add('catalog:forest')
        self.state.start_turn('A');self.kernel.open_window_for_scenario('A')

    def add(self,definition='pc-body',actor='A',zone=Zone.BATTLEFIELD,**kw):
        self.serial+=1
        return self.state.add_card('pc-object-'+str(self.serial),definition,actor,zone,**kw)

    def card(self,key,actor='A',zone=Zone.BATTLEFIELD,**kw):
        return self.add(self.cards[key].definition_id,actor,zone,**kw)

    def current(self,ref):return self.state.get(self.state.current(ref.card_id))
    def events(self,kind):return [r for r in self.kernel.semantic_events if r['kind']==kind]

    def payment(self,symbols='',actor='A',**kw):
        self.state.add_mana(actor,symbols)
        return Payment(tuple(sorted(Counts(symbols).items())),**kw)

    def cast(self,ref,symbols='',targets=(),actor='A',payment=None,**kw):
        if self.kernel.priority is None and not self.kernel.stack:self.kernel.open_window_for_scenario(actor)
        payment=payment or self.payment(symbols,actor)
        q=self.kernel.quote_cast('pc-cast-'+str(len(self.kernel.action_receipts)),actor,ref,targets,**kw)
        return self.kernel.commit_action(q,payment)

    def answer(self,indexes):
        r=self.kernel.pending_choice
        return self.kernel.answer(r.request_id,r.actor,indexes)

    def top(self):
        fid=self.kernel.stack[-1]['id']
        for _ in range(100):
            if self.kernel.pending_choice or self.kernel._cast_waiting() or not any(f['id']==fid for f in self.kernel.stack):return
            self.kernel.pass_priority(self.kernel.priority)
        self.fail('No resolution boundary')

    def drain(self):
        for _ in range(300):
            if self.kernel.pending_choice:self.answer(list(range(self.kernel.pending_choice.minimum)))
            elif self.kernel._cast_waiting():
                self.kernel.decline_resolution_cast('pc-decline-'+str(len(self.kernel.action_receipts)),
                    self.kernel.resolution_cast['actor'],self.kernel.resolution_cast['id'],revision=self.kernel.revision)
            elif self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
            else:return
        self.fail('No final boundary')

    def effect(self,effects):
        self.kernel.execute_for_scenario(self.anchor,'A',effects)
        return self.kernel.advance()

    def aura(self,key,ref,actor='A'):
        aura=self.card(key,actor);self.state.attach(aura,ref);return aura

    def combat(self,actor='A'):
        self.state.start_turn(actor)
        self.kernel.active=actor;self.kernel.phase='declare_attackers';self.kernel.priority=None
        self.kernel.passes=[];self.kernel.turn_schedule={'land_plays':0,'advance':False,'cleanup_priority':False}

    def attack(self,rows,payment=None):
        return self.kernel.declare_attackers(self.kernel.active,rows,revision=self.kernel.revision,payment=payment)

    def restore(self):
        snap=self.kernel.snapshot();self.kernel=RulesKernel.restore(snap,self.programs);self.state=self.kernel.state
        self.assertEqual(snap,self.kernel.snapshot())

    def energy(self,amount=3):
        self.state.put_counters_batch(((PlayerRef('A'),(('energy',amount),)),))

    def nightmare(self,x=2,order=('player:energy','zone:creature','zone:return')):
        source=self.card('chthonian-nightmare');sac=self.add();target=self.add('pc-zero' if x==0 else 'pc-body',zone=Zone.GRAVEYARD)
        if x:self.energy(x)
        q=self.kernel.quote_activation('nightmare','A',source,'reanimate',(target,),x_value=x)
        p=Payment(zone_costs=(('creature',(sac,)),),cost_order=order)
        return source,sac,target,q,p

    def modifier_keys(self,ref):
        return tuple(self.kernel._life_cost_options(self.state.get(ref),'A'))

    def mana_command(self,ref,ability='intrinsic-land:Forest',payment=None):
        return {'kind':'activate','source':ref.to_json(),'targets':[],'x_value':0,
            'ability_id':ability,'payment':(payment or Payment()).to_json()}

    def test_complete_printed_programs_and_bindings(self):
        catalog={c.card_id:c for c in load_catalog(self.root/'data/catalog/cards.json')}
        self.assertEqual(set(CARDS),set(self.cards))
        for key,p in self.cards.items():
            self.assertEqual(self.prefix+key,p.definition_id)
            self.assertEqual(p,validate(decode(encode(p))))
            row=self.rows[key]
            self.assertEqual(digest(source_facts(catalog[key])),row.get('source_facts_sha256') or digest(row['source_facts']))

    def test_nightmare_entry_gains_player_energy(self):
        self.game();card=self.card('chthonian-nightmare',zone=Zone.HAND);self.cast(card,'CB');self.drain()
        self.assertEqual({'energy':3},dict(self.state.player_counters('A')))
        self.assertEqual((),self.current(card).counters)

    def test_energy_uses_player_counter_replacements(self):
        doubler=CardProgram('pc-double','Double',('Enchantment',),
            counter_replacements=(CounterReplacement('double',players='controller',multiplier=2),))
        self.game((doubler,));self.add('pc-double')
        card=self.card('chthonian-nightmare',zone=Zone.HAND);self.cast(card,'CB');self.drain()
        self.assertEqual({'energy':6},dict(self.state.player_counters('A')))

    def test_nightmare_all_six_authored_payment_orders(self):
        for order in itertools.permutations(('player:energy','zone:creature','zone:return')):
            with self.subTest(order=order):
                self.game();source,sac,target,q,p=self.nightmare(order=order)
                self.kernel.commit_action(q,p)
                self.assertEqual(Zone.HAND,self.current(source).zone)
                self.assertEqual(Zone.GRAVEYARD,self.current(sac).zone)
                self.assertEqual((),self.state.player_counters('A'))
                moves=[e.before.ref for e in self.state.events_since(0) if e.cause in {'sacrifice','return'}]
                expected=[sac if c=='zone:creature' else source for c in order if c.startswith('zone:')]
                self.assertEqual(expected,moves)
                self.drain();self.assertEqual(Zone.BATTLEFIELD,self.current(target).zone)

    def test_nightmare_zero_energy_still_pays_zone_costs(self):
        self.game();source,sac,target,q,p=self.nightmare(0);self.kernel.commit_action(q,p);self.drain()
        self.assertEqual(Zone.BATTLEFIELD,self.current(target).zone)
        self.assertEqual(Zone.HAND,self.current(source).zone)
        self.assertEqual(Zone.GRAVEYARD,self.current(sac).zone)

    def test_nightmare_requires_target_before_sacrificing(self):
        self.game();source=self.card('chthonian-nightmare');sac=self.add();self.energy(2)
        before=self.kernel.snapshot()
        for targets in ((),(sac,)):
            with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',source,'reanimate',targets,x_value=2)
        self.assertEqual(before,self.kernel.snapshot())

    def test_nightmare_rejects_insufficient_energy_and_wrong_x(self):
        self.game();source=self.card('chthonian-nightmare');target=self.add(zone=Zone.GRAVEYARD)
        before=self.kernel.snapshot()
        for x in (1,2,-1,True):
            with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',source,'reanimate',(target,),x_value=x)
        self.assertEqual(before,self.kernel.snapshot())

    def test_nightmare_rejects_missing_duplicate_and_unknown_order(self):
        self.game();source,sac,target,q,p=self.nightmare();before=self.kernel.snapshot()
        for order in ((),('zone:creature','zone:return'),('player:energy','zone:creature','zone:creature'),('player:poison','zone:creature','zone:return')):
            with self.assertRaises(RulesViolation):self.kernel.commit_action(q,replace(p,cost_order=order))
            self.assertEqual(before,self.kernel.snapshot())

    def test_nightmare_rejects_opponent_sacrifice_atomically(self):
        self.game();source,sac,target,q,p=self.nightmare();other=self.add(actor='B')
        q=self.kernel.quote_activation('nightmare','A',source,'reanimate',(target,),x_value=2)
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(q,replace(p,zone_costs=(('creature',(other,)),)))
        self.assertEqual(before,self.kernel.snapshot())

    def test_nightmare_only_sorcery_timing(self):
        self.game();source,sac,target,q,p=self.nightmare()
        self.kernel.phase='upkeep'
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',source,'reanimate',(target,),x_value=2)

    def test_nightmare_payment_checkpoint_at_commander_replacement(self):
        self.game();source=self.card('chthonian-nightmare',commander=True);sac=self.add();target=self.add(zone=Zone.GRAVEYARD);self.energy(2)
        q=self.kernel.quote_activation('nightmare','A',source,'reanimate',(target,),x_value=2)
        self.kernel.commit_action(q,Payment(zone_costs=(('creature',(sac,)),),cost_order=('player:energy','zone:return','zone:creature')))
        self.assertEqual('commander_destination',self.kernel.pending_choice.kind)
        self.assertEqual((),self.state.player_counters('A'));self.assertEqual(Zone.BATTLEFIELD,self.current(sac).zone)
        self.restore();self.answer([0]);self.drain()
        self.assertEqual(Zone.COMMAND,self.current(source).zone);self.assertEqual(Zone.BATTLEFIELD,self.current(target).zone)
        self.assertEqual(1,len(self.events('player_counters_paid')))

    def test_nightmare_replacement_can_exile_sacrifice(self):
        replacement=CardProgram('pc-exile','Exile',('Enchantment',),
            replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,from_zone=Zone.BATTLEFIELD,types=('Creature',)),))
        self.game((replacement,));self.add('pc-exile');source,sac,target,q,p=self.nightmare()
        self.kernel.commit_action(q,p);self.drain()
        self.assertEqual(Zone.EXILE,self.current(sac).zone);self.assertEqual(Zone.BATTLEFIELD,self.current(target).zone)

    def test_energy_is_not_mana_and_does_not_empty_at_step(self):
        self.game();self.energy(3);self.state.add_mana('A','G');self.state.empty_mana_pools()
        self.assertEqual({'energy':3},dict(self.state.player_counters('A')))

    def test_defiler_optional_cost_reduces_green_only(self):
        self.game();self.card('defiler-of-vigor');ref=self.add(zone=Zone.HAND);keys=self.modifier_keys(ref)
        q=self.kernel.quote_cast('defile','A',ref,life_costs=keys)
        self.assertEqual(ManaCost(1),q.cost.mana);self.assertEqual(2,q.cost.life)
        payment=self.payment('C');q=replace(q,revision=self.kernel.revision)
        self.kernel.commit_action(q,payment);self.drain()
        self.assertEqual(38,self.state.life('A'));self.assertEqual(Zone.BATTLEFIELD,self.current(ref).zone)

    def test_defiler_payment_is_optional(self):
        self.game();self.card('defiler-of-vigor');ref=self.add(zone=Zone.HAND)
        self.cast(ref,'CG');self.drain();self.assertEqual(40,self.state.life('A'))

    def test_defiler_trigger_includes_source_and_excludes_uncast_entrant(self):
        self.game();source=self.card('defiler-of-vigor');other=self.add();ref=self.add(zone=Zone.HAND)
        self.cast(ref,'CG');self.drain()
        self.assertEqual({'+1/+1':1},dict(self.current(source).counters))
        self.assertEqual({'+1/+1':1},dict(self.current(other).counters))
        self.assertEqual((),self.current(ref).counters)

    def test_defiler_does_not_trigger_for_itself_being_cast(self):
        self.game();other=self.add();ref=self.card('defiler-of-vigor',zone=Zone.HAND);self.cast(ref,'CCCGG');self.drain()
        self.assertEqual((),self.current(other).counters);self.assertEqual((),self.current(ref).counters)

    def test_defiler_stacks_once_per_source(self):
        self.game();self.card('defiler-of-vigor');self.card('defiler-of-vigor')
        ref=self.card('defiler-of-vigor',zone=Zone.HAND);keys=self.modifier_keys(ref)
        q=self.kernel.quote_cast('two','A',ref,life_costs=keys)
        self.assertEqual(4,q.cost.life);self.assertEqual(ManaCost(3),q.cost.mana)

    def test_defiler_duplicate_or_forged_life_selection_rejected(self):
        self.game();self.card('defiler-of-vigor');ref=self.add(zone=Zone.HAND);key=self.modifier_keys(ref)[0]
        for keys in ((key,key),('forged',)):
            with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',ref,life_costs=keys)

    def test_defiler_excludes_green_instant_and_opponent_source(self):
        instant=CardProgram('pc-green-instant','Green instant',('Instant',),colors=('G',),mana_value=1,
            cast=CastSpec(CostSpec(ManaCost(symbols=('G',))),timing='instant'))
        self.game((instant,));self.card('defiler-of-vigor');ref=self.add('pc-green-instant',zone=Zone.HAND)
        self.assertEqual((),self.modifier_keys(ref))
        self.game();self.card('defiler-of-vigor','B');ref=self.add(zone=Zone.HAND);self.assertEqual((),self.modifier_keys(ref))

    def test_defiler_hybrid_choice_precedes_reduction(self):
        self.game();self.card('defiler-of-vigor');ref=self.add('catalog:omo-queen-of-vesuva',zone=Zone.HAND);keys=self.modifier_keys(ref)
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('hybrid','A',ref,life_costs=keys)
        green=self.kernel.quote_cast('green','A',ref,life_costs=keys,hybrid_choices=('G',))
        blue=self.kernel.quote_cast('blue','A',ref,life_costs=keys,hybrid_choices=('U',))
        self.assertEqual(ManaCost(2),green.cost.mana);self.assertEqual(ManaCost(2,('U',)),blue.cost.mana)
        self.assertEqual(2,blue.cost.life)

    def test_defiler_pay_life_without_green_cost_reduction(self):
        alt=CardProgram('pc-green-free','Green free',('Creature',),colors=('G',),power=1,toughness=1,
            cast=CastSpec(CostSpec(ManaCost(2))))
        self.game((alt,));self.card('defiler-of-vigor');ref=self.add('pc-green-free',zone=Zone.HAND)
        q=self.kernel.quote_cast('life','A',ref,life_costs=self.modifier_keys(ref))
        self.assertEqual(ManaCost(2),q.cost.mana);self.assertEqual(2,q.cost.life)

    def test_defiler_insufficient_life_rejected(self):
        self.game();self.card('defiler-of-vigor');ref=self.add(zone=Zone.HAND);self.state.lose_life_batch(('A',),39)
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',ref,life_costs=self.modifier_keys(ref))

    def test_defiler_quote_serializes_declarations(self):
        self.game();self.card('defiler-of-vigor');ref=self.add('catalog:omo-queen-of-vesuva',zone=Zone.HAND)
        q=self.kernel.quote_cast('hybrid','A',ref,life_costs=self.modifier_keys(ref),hybrid_choices=('G',))
        self.assertEqual(q,PreparedAction.from_json(q.to_json()))

    def test_rhythm_cannot_counter_current_creature_spell(self):
        self.game();self.card('rhythm-of-the-wild');ref=self.add(zone=Zone.HAND);self.cast(ref,'CG')
        self.assertTrue(self.kernel._spell_uncounterable(self.current(ref).ref))
        current=self.current(ref).ref
        self.kernel.priority='B';counter=self.add('pc-counter','B',Zone.HAND);self.cast(counter,'CU',(current,),actor='B');self.top()
        self.assertEqual(Zone.STACK,self.current(ref).zone)

    def test_rhythm_protection_ends_when_source_leaves(self):
        self.game();rhythm=self.card('rhythm-of-the-wild');ref=self.add(zone=Zone.HAND);self.cast(ref,'CG')
        self.state.move((ZoneMove(rhythm,Zone.GRAVEYARD),),'fixture')
        self.assertFalse(self.kernel._spell_uncounterable(self.current(ref).ref))

    def test_rhythm_ignores_opponent_and_noncreature_spells(self):
        self.game();self.card('rhythm-of-the-wild','B');ref=self.add(zone=Zone.HAND);self.cast(ref,'CG')
        self.assertFalse(self.kernel._spell_uncounterable(self.current(ref).ref))

    def test_riot_counter_choice_is_on_entry(self):
        self.game();self.card('rhythm-of-the-wild');ref=self.add(zone=Zone.HAND);self.cast(ref,'CG');self.top()
        self.assertEqual('riot',self.kernel.pending_choice.kind)
        self.assertEqual(Zone.STACK,self.current(ref).zone)
        self.answer([0]);self.drain();self.assertEqual({'+1/+1':1},dict(self.current(ref).counters))

    def test_riot_haste_survives_turn_and_source_departure(self):
        self.game();rhythm=self.card('rhythm-of-the-wild');ref=self.add(zone=Zone.HAND);self.cast(ref,'CG');self.top();self.answer([1]);self.drain()
        self.state.move((ZoneMove(rhythm,Zone.GRAVEYARD),),'fixture');self.state.start_turn('B')
        self.assertIn('haste',self.kernel.effective(self.current(ref).ref).keywords)

    def test_riot_multiple_instances_choose_independently(self):
        self.game();self.card('rhythm-of-the-wild');self.card('rhythm-of-the-wild')
        ref=self.add(zone=Zone.HAND);self.cast(ref,'CG');self.top()
        self.assertEqual('replacement_order',self.kernel.pending_choice.kind)
        self.answer([0]);self.answer([0]);self.answer([1]);self.drain()
        self.assertEqual({'+1/+1':1},dict(self.current(ref).counters))
        self.assertIn('haste',self.kernel.effective(self.current(ref).ref).keywords)

    def test_riot_skips_tokens(self):
        token=CardProgram('pc-token','Token',('Creature',),power=1,toughness=1)
        self.game((token,));self.card('rhythm-of-the-wild')
        self.effect((CreateTokens(token,1),));self.drain()
        obj=next(o for o in self.state.objects(Zone.BATTLEFIELD) if o.token)
        self.assertEqual((),obj.counters);self.assertNotIn('haste',self.kernel.effective(obj.ref).keywords)

    def test_riot_checkpoint_keeps_the_exact_choice(self):
        self.game();self.card('rhythm-of-the-wild');ref=self.add(zone=Zone.HAND);self.cast(ref,'CG');self.top()
        request=self.kernel.pending_choice.to_json();self.restore()
        self.assertEqual(request,self.kernel.pending_choice.to_json());self.answer([1]);self.drain()
        self.assertIn('haste',self.kernel.effective(self.current(ref).ref).keywords)

    def test_riot_applies_to_reanimation(self):
        self.game();self.card('rhythm-of-the-wild');ref=self.add(zone=Zone.GRAVEYARD)
        self.effect((SelectAll(Selector(Zone.GRAVEYARD,types=('Creature',),relation='owned'),(Move('selected',Zone.BATTLEFIELD),)),))
        self.assertEqual('riot',self.kernel.pending_choice.kind);self.answer([0])
        self.assertEqual({'+1/+1':1},dict(self.current(ref).counters))

    def test_riot_counter_uses_entry_counter_replacement(self):
        self.game();self.card('rhythm-of-the-wild');self.add('catalog:the-earth-crystal');ref=self.add(zone=Zone.HAND)
        self.cast(ref,'G');self.top();self.answer([0]);self.drain()
        self.assertEqual({'+1/+1':2},dict(self.current(ref).counters))

    def test_maze_enters_tapped_and_has_colorless_mana(self):
        self.game();ref=self.card('maze-s-end',zone=Zone.HAND)
        self.kernel.turn_schedule={'land_plays':0,'advance':False,'cleanup_priority':False}
        self.kernel.play_land('maze','A',ref,revision=self.kernel.revision)
        self.assertTrue(self.current(ref).tapped)
        self.state.start_turn('A');self.kernel.priority='A'
        q=self.kernel.quote_activation('mana','A',self.current(ref).ref,'mana')
        self.kernel.commit_action(q,Payment());self.assertEqual({'C':1},dict(self.state.mana_pool('A')))

    def maze_search(self,gates=0,duplicate=False,library=True):
        self.game()
        # Fixture definitions distinguish names; actual selection still uses Gate type.
        extras=tuple(CardProgram('pc-gate-'+str(i),'Gate '+str(0 if duplicate else i),('Land',),subtypes=('Gate',)) for i in range(max(gates,1)+1))
        self.game(extras)
        for i in range(gates):self.add('pc-gate-'+str(i))
        found=self.add('pc-gate-'+str(gates),zone=Zone.LIBRARY) if library else None
        maze=self.card('maze-s-end');payment=self.payment('CCC')
        q=self.kernel.quote_activation('maze-search','A',maze,'gate-search')
        self.kernel.commit_action(q,payment);self.top()
        return maze,found

    def test_maze_search_then_ten_distinct_names_wins(self):
        maze,found=self.maze_search(9);self.assertEqual(Zone.HAND,self.current(maze).zone)
        self.answer([0]);self.assertEqual(['A'],self.kernel.outcome['winners'])
        self.assertEqual(Zone.BATTLEFIELD,self.current(found).zone)

    def test_maze_can_win_without_finding_a_gate(self):
        maze,found=self.maze_search(10,library=False);self.drain()
        self.assertEqual(['A'],self.kernel.outcome['winners'])

    def test_maze_duplicate_gate_names_do_not_win(self):
        maze,found=self.maze_search(10,duplicate=True);self.answer([0]);self.drain()
        self.assertIsNone(self.kernel.outcome)

    def test_maze_nine_gates_do_not_win(self):
        maze,found=self.maze_search(8);self.answer([0]);self.drain();self.assertIsNone(self.kernel.outcome)

    def test_maze_opponent_gates_do_not_count(self):
        self.game();source=self.card('maze-s-end')
        for _ in range(12):self.add('catalog:simic-guildgate','B')
        payment=self.payment('CCC');q=self.kernel.quote_activation('maze-search','A',source,'gate-search');self.kernel.commit_action(q,payment);self.drain()
        self.assertIsNone(self.kernel.outcome)

    def test_maze_win_ends_resolution_immediately(self):
        self.game();self.effect((WinGame(),GainLife(10)))
        self.assertEqual(40,self.state.life('A'));self.assertEqual(['A'],self.kernel.outcome['winners'])

    def test_goad_requires_attacking_another_player(self):
        self.game();ref=self.add();self.aura('parasitic-impetus',ref,'B');self.combat()
        before=self.kernel.snapshot()
        for rows in ({},{ref:'B'}):
            with self.assertRaises(RulesViolation):self.attack(rows)
            self.assertEqual(before,self.kernel.snapshot())
        self.attack({ref:'C'});self.drain()
        self.assertEqual(38,self.state.life('A'));self.assertEqual(42,self.state.life('B'))

    def test_goad_two_player_game_attacks_goading_player(self):
        self.game(players=('A','B'));ref=self.add();self.aura('parasitic-impetus',ref,'B');self.combat()
        self.attack({ref:'B'});self.assertEqual('B',self.kernel.combat['attackers'][0]['defender'])

    def test_goad_multiple_players_maximizes_requirements(self):
        self.game();ref=self.add();self.aura('parasitic-impetus',ref,'B');self.aura('parasitic-impetus',ref,'C');self.combat()
        with self.assertRaises(RulesViolation):self.attack({ref:'B'})
        self.attack({ref:'D'});self.assertEqual({'B','C'},set(self.kernel.effective(ref).goaded_by))

    def test_repeated_goad_from_one_player_adds_no_requirements(self):
        self.game();ref=self.add();self.aura('parasitic-impetus',ref,'B');self.aura('parasitic-impetus',ref,'B');self.combat()
        self.assertEqual(frozenset({'B'}),self.kernel.effective(ref).goaded_by)
        self.attack({ref:'C'});self.assertEqual(2,len(self.kernel.stack))

    def test_goad_all_other_players_ties_are_legal(self):
        self.game();ref=self.add()
        for player in ('B','C','D'):self.aura('parasitic-impetus',ref,player)
        self.combat();self.attack({ref:'B'})
        self.assertEqual('B',self.kernel.combat['attackers'][0]['defender'])

    def test_goad_does_not_force_tapped_or_summoning_sick(self):
        self.game();self.combat();ref=self.add();self.aura('parasitic-impetus',ref,'B')
        self.attack({});self.assertEqual([],self.kernel.combat['attackers'])

    def test_goad_does_not_override_defender(self):
        wall=CardProgram('pc-wall','Wall',('Creature',),power=0,toughness=4,keywords=('defender',))
        self.game((wall,));ref=self.add('pc-wall');self.aura('parasitic-impetus',ref,'B');self.combat();self.attack({})
        self.assertEqual([],self.kernel.combat['attackers'])

    def test_impetus_only_triggers_for_attached_attacker(self):
        self.game();ref=self.add();other=self.add();self.aura('parasitic-impetus',ref,'B')
        self.combat();self.state.set_tapped_batch((ref,),True);self.attack({other:'C'})
        self.assertEqual([],self.kernel.stack)

    def test_impetus_captures_attacking_controller(self):
        self.game();ref=self.add();self.aura('parasitic-impetus',ref,'B');self.combat();self.attack({ref:'C'})
        self.kernel.turn_schedule=None
        self.state.change_control(ref,'D')
        self.drain();self.assertEqual(38,self.state.life('A'));self.assertEqual(40,self.state.life('D'))
        self.assertEqual(42,self.state.life('B'))

    def test_impetus_same_controller_loses_then_gains_without_sba(self):
        self.game();ref=self.add();self.aura('parasitic-impetus',ref);self.state.lose_life_batch(('A',),38)
        self.combat();self.attack({ref:'B'});self.kernel.turn_schedule=None;self.drain()
        self.assertEqual(2,self.state.life('A'));self.assertIn('A',self.state.live_players)

    def test_impetus_trigger_survives_aura_departure(self):
        self.game();ref=self.add();aura=self.aura('parasitic-impetus',ref,'B');self.combat();self.attack({ref:'C'})
        self.state.move((ZoneMove(aura,Zone.GRAVEYARD),),'fixture');self.kernel.turn_schedule=None;self.drain()
        self.assertEqual(38,self.state.life('A'));self.assertEqual(42,self.state.life('B'))

    def test_propaganda_exact_payment_and_failed_payment_atomic(self):
        self.game();ref=self.add();self.card('propaganda','B');self.combat()
        payment=self.payment('CC');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.attack({ref:'B'})
        self.assertEqual(before,self.kernel.snapshot())
        self.attack({ref:'B'},payment);self.assertEqual((),self.state.mana_pool('A'));self.assertTrue(self.current(ref).tapped)

    def test_propaganda_stacks_per_attacker(self):
        self.game();a=self.add();b=self.add();self.card('propaganda','B');self.card('propaganda','B');self.combat()
        self.attack({a:'B',b:'B'},self.payment('CCCCCCCC'))
        self.assertEqual(8,self.events('attackers_declared')[-1]['attack_cost'])

    def test_propaganda_only_taxes_its_controller(self):
        self.game();ref=self.add();self.card('propaganda','B');self.combat();self.attack({ref:'C'})
        self.assertEqual(0,self.events('attackers_declared')[-1]['attack_cost'])

    def test_propaganda_goad_can_decline_paid_destination(self):
        self.game();ref=self.add();self.aura('parasitic-impetus',ref,'B')
        self.card('propaganda','C');self.card('propaganda','D');self.combat()
        self.attack({ref:'B'});self.assertEqual('B',self.kernel.combat['attackers'][0]['defender'])

    def test_propaganda_goad_free_other_destination_required(self):
        self.game();ref=self.add();self.aura('parasitic-impetus',ref,'B');self.card('propaganda','C');self.combat()
        with self.assertRaises(RulesViolation):self.attack({ref:'B'})
        self.attack({ref:'D'})

    def test_propaganda_all_destinations_taxed_can_omit_goaded_attacker(self):
        self.game();ref=self.add();self.aura('parasitic-impetus',ref,'B')
        for player in ('B','C','D'):self.card('propaganda',player)
        self.combat();self.attack({});self.assertEqual([],self.kernel.combat['attackers'])

    def test_propaganda_authored_mana_abilities_during_declaration(self):
        self.game();ref=self.add();forest=self.add('catalog:forest');self.card('propaganda','B');self.combat()
        payment=Payment((('G',2),),mana_actions=(self.mana_command(self.anchor),self.mana_command(forest)))
        self.attack({ref:'B'},payment);self.assertTrue(self.current(forest).tapped)
        self.assertEqual((),self.state.mana_pool('A'));self.assertIsNone(self.kernel.declaration_mana)

    def test_propaganda_nonmana_action_cannot_hide_in_plan(self):
        self.game();ref=self.add();nightmare=self.card('chthonian-nightmare');self.card('propaganda','B');self.combat()
        before=self.kernel.snapshot()
        for commands in (({'kind':'pass'},),(self.mana_command(nightmare,'reanimate'),)):
            with self.assertRaises(RulesViolation):self.attack({ref:'B'},Payment((('G',2),),mana_actions=commands))
            self.assertEqual(before,self.kernel.snapshot())

    def test_propaganda_failed_mana_plan_rolls_back_every_action(self):
        self.game();ref=self.add();self.card('propaganda','B');self.combat();before=self.kernel.snapshot()
        payment=Payment((('G',2),),mana_actions=(self.mana_command(self.anchor),self.mana_command(self.anchor)))
        with self.assertRaises(RulesViolation):self.attack({ref:'B'},payment)
        self.assertEqual(before,self.kernel.snapshot())

    def test_propaganda_actor_command_replay(self):
        self.game();ref=self.add();forest=self.add('catalog:forest');self.card('propaganda','B');self.combat()
        adapter=RulesActorAdapter(self.kernel)
        payment=Payment((('G',2),),mana_actions=(self.mana_command(self.anchor),self.mana_command(forest)))
        adapter.submit('A',{'kind':'attack','revision':self.kernel.revision,
            'attackers':[{'source':ref.to_json(),'defender':'B'}],'payment':payment.to_json()})
        self.assertEqual(adapter.archive(),RulesActorAdapter.replay(adapter.archive(),self.programs).archive())

    def test_darksteel_preserves_color_supertype_and_commander(self):
        legend=CardProgram('pc-legend','Legend',('Enchantment','Creature'),subtypes=('God',),supertypes=('Legendary',),
            power=7,toughness=7,colors=('G',),keywords=('trample','haste'))
        self.game((legend,));ref=self.add('pc-legend',commander=True);self.aura('darksteel-mutation',ref)
        v=self.kernel.effective(ref)
        self.assertEqual(frozenset({'Artifact','Creature'}),v.types);self.assertEqual(frozenset({'Insect'}),v.subtypes)
        self.assertEqual((0,1),(v.power,v.toughness));self.assertEqual(frozenset({'indestructible'}),v.keywords)
        self.assertEqual(frozenset({'G'}),v.colors);self.assertIn('Legendary',v.supertypes);self.assertTrue(self.current(ref).commander)

    def test_darksteel_preserves_artifact_subtypes_only(self):
        weird=CardProgram('pc-weird','Weird',('Artifact','Enchantment','Creature'),subtypes=('Equipment','Shrine','Cat'),power=2,toughness=2)
        self.game((weird,));ref=self.add('pc-weird');self.aura('darksteel-mutation',ref)
        self.assertEqual(frozenset({'Equipment','Insect'}),self.kernel.effective(ref).subtypes)

    def test_darksteel_preserves_pt_counters_and_anthem(self):
        anthem=CardProgram('pc-anthem','Anthem',('Enchantment',),continuous=(ContinuousProgram('boost',
            Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled'),(ModifyPT(2,2),)),))
        self.game((anthem,));ref=self.add();self.state.add_counters(ref,'+1/+1',3);self.add('pc-anthem');self.aura('darksteel-mutation',ref)
        self.assertEqual((5,6),(self.kernel.effective(ref).power,self.kernel.effective(ref).toughness))

    def test_darksteel_suppresses_printed_activated_abilities(self):
        self.game();ref=self.add('catalog:fanatic-of-rhonas');self.aura('darksteel-mutation',ref)
        self.assertEqual((),self.kernel.activated_abilities(self.current(ref)))

    def test_darksteel_suppresses_defiler_cost_and_trigger(self):
        self.game();ref=self.card('defiler-of-vigor');self.aura('darksteel-mutation',ref);hand=self.add(zone=Zone.HAND)
        self.assertEqual((),self.modifier_keys(hand));self.cast(hand,'CG');self.drain()
        self.assertEqual((),self.current(ref).counters)

    def test_darksteel_suppresses_leaves_trigger_using_lookback(self):
        self.game();ref=self.add('catalog:vesperlark');self.aura('darksteel-mutation',ref)
        target=self.add('pc-zero',zone=Zone.GRAVEYARD)
        self.effect((SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled'),(Sacrifice('selected'),)),));self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.current(target).zone)
        self.assertEqual([],self.kernel.pending_triggers)

    def test_darksteel_allows_later_keyword_grant(self):
        self.game();ref=self.add();self.aura('darksteel-mutation',ref)
        self.effect((SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled'),
            (UntilEndOfTurn('selected',(AddKeywords(('flying',)),)),)),))
        self.assertEqual(frozenset({'indestructible','flying'}),self.kernel.effective(ref).keywords)

    def test_darksteel_removes_earlier_keyword_grant(self):
        self.game();ref=self.add()
        self.effect((SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled'),
            (UntilEndOfTurn('selected',(AddKeywords(('flying',)),)),)),))
        self.aura('darksteel-mutation',ref)
        self.assertEqual(frozenset({'indestructible'}),self.kernel.effective(ref).keywords)

    def test_darksteel_restores_abilities_when_aura_leaves(self):
        self.game();ref=self.card('defiler-of-vigor');aura=self.aura('darksteel-mutation',ref)
        self.state.move((ZoneMove(aura,Zone.GRAVEYARD),),'fixture')
        self.assertIn('trample',self.kernel.effective(ref).keywords);hand=self.add(zone=Zone.HAND)
        self.assertTrue(self.modifier_keys(hand))

    def test_darksteel_does_not_remove_goad_designation(self):
        self.game();ref=self.add();self.aura('parasitic-impetus',ref,'B');self.aura('darksteel-mutation',ref)
        self.assertEqual(frozenset({'B'}),self.kernel.effective(ref).goaded_by)
        self.combat()
        with self.assertRaises(RulesViolation):self.attack({})
        self.attack({ref:'C'})

    def test_darksteel_suppresses_later_layer_static_pt_source(self):
        self.game();ref=self.add('catalog:rampant-frogantua');self.aura('darksteel-mutation',ref)
        self.state.mark_departed(('D',))
        self.assertEqual((0,1),(self.kernel.effective(ref).power,self.kernel.effective(ref).toughness))

    def test_darksteel_multi_layer_effect_continues_after_ability_removed(self):
        source=CardProgram('pc-self','Self',('Creature',),power=1,toughness=1,
            continuous=(ContinuousProgram('already-started',Selector(Zone.BATTLEFIELD,types=('Creature',)),
                (ChangeTypes(add=('Artifact',)),ModifyPT(3,3))),))
        self.game((source,));ref=self.add('pc-self');other=self.add();self.aura('darksteel-mutation',ref)
        self.assertEqual((3,4),(self.kernel.effective(ref).power,self.kernel.effective(ref).toughness))
        self.assertEqual((5,6),(self.kernel.effective(other).power,self.kernel.effective(other).toughness))

    def test_derived_history_checkpoint_round_trip(self):
        self.game();ref=self.add();self.aura('parasitic-impetus',ref,'B');self.aura('darksteel-mutation',ref)
        self.effect((SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled'),(Sacrifice('selected'),)),))
        self.drain();self.restore()

    def test_actor_projection_exposes_current_goad_and_tax(self):
        self.game();ref=self.add();self.aura('parasitic-impetus',ref,'B');self.card('propaganda','C')
        packet=project_actor(self.kernel,'A')
        self.assertEqual(2,packet['attack_taxes']['C'])
        self.assertIn('goaded_by',json.dumps(packet))

    def test_invalid_player_counter_cost_rejected(self):
        for cost in (OrderedCostSpec(player_counter_costs=(PlayerCounterCost('energy',-1),)),
                     OrderedCostSpec(player_counter_costs=(PlayerCounterCost('energy',True),)),
                     OrderedCostSpec(player_counter_costs=(PlayerCounterCost('energy',1),PlayerCounterCost('energy',2)))):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Enchantment',),activated=(ActivatedProgram('a',cost,()),)))

    def test_invalid_rule_permissions_and_type_changes_rejected(self):
        for permissions in (RulePermissions(attack_tax=-1),RulePermissions(creature_spells_uncounterable=1)):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Enchantment',),player_permissions=permissions))
        with self.assertRaises(RulesViolation):
            validate(CardProgram('bad','Bad',('Enchantment',),continuous=(ContinuousProgram('bad',
                Selector(Zone.BATTLEFIELD),(SetCardTypes(('Sorcery',),('Insect',)),)),)))

    def test_invalid_life_modifier_rejected(self):
        for rule in (LifeCostModifier('bad',Selector(Zone.STACK),0,color='C'),LifeCostModifier('bad',Selector(Zone.STACK),0,life=-1)):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Creature',),cost_modifiers=(rule,)))

    def test_payment_round_trip_preserves_order_and_authored_mana(self):
        p=Payment(cost_order=('player:energy','zone:creature','zone:return'))
        self.assertEqual(p,Payment.from_json(p.to_json()))
        with self.assertRaises(RulesViolation):Payment.from_json({'mana':{},'taps':[],'cost_order':[1]})
