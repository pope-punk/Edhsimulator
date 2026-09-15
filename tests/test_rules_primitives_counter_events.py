"""Counter effects and proliferate share atomic replacements and trigger events."""
import unittest
from edh_gauntlet.rules_program import (CardProgram,CounterReplacement,Selector,AddCounters,MultiplyCounters,
    Proliferate,SelectAll,AbilityProgram,EventPattern,GainLife,EventAmount,TargetSpec,CastSpec,CostSpec,validate)
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,ObjectRef,PlayerRef,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed


class CounterEventTests(unittest.TestCase):
    def setup_game(self,extra=()):
        self.program=CardProgram('creature','Creature',('Creature',),power=2,toughness=4)
        self.programs=(self.program,*extra);self.state=RulesState(('A','B','C'))
        self.source=self.state.add_card('source','creature','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs)

    def modifier(self,key,multiplier=1,additional=0,*,players=None,kind='+1/+1'):
        return CardProgram(key,key,('Enchantment',),counter_replacements=(CounterReplacement(key,
            Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled') if players is None else None,
            players=players,kind=kind,multiplier=multiplier,additional=additional),))

    def drain(self):
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)
        return self.kernel.pending_choice

    def answer(self,indexes):
        r=self.kernel.pending_choice;self.kernel.answer(r.request_id,r.actor,indexes);return self.drain()

    def test_noncommuting_orders_produce_three_or_four_counters_and_restore(self):
        for first,expected in (('plus',4),('double',3)):
            self.setup_game((self.modifier('plus',additional=1),self.modifier('double',multiplier=2)))
            for key in ('plus','double'):self.state.add_card(key,key,'A',Zone.BATTLEFIELD)
            before=self.state.snapshot();r=self.kernel.execute_for_scenario(self.source,'A',(AddCounters('source','+1/+1',1),))
            self.assertEqual(before,self.state.snapshot());self.assertEqual('counter_replacement',r.kind)
            index=next(i for i,o in enumerate(r.options) if first in o.label)
            restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
            self.kernel.answer(r.request_id,'A',[index]);restored.answer(r.request_id,'A',[index])
            self.assertEqual(self.kernel.snapshot(),restored.snapshot())
            self.assertEqual((('+1/+1',expected),),self.state.get(self.source).counters)
            self.assertEqual(2,sum(e['kind']=='counter_replacement_applied' for e in self.kernel.semantic_events))

    def test_commuting_doublers_are_forced_and_apply_only_to_new_counters(self):
        self.setup_game((self.modifier('double',multiplier=2),))
        for i in range(2):self.state.add_card(str(i),'double','A',Zone.BATTLEFIELD)
        self.state.add_counters(self.source,'+1/+1',2)
        result=self.kernel.execute_for_scenario(self.source,'A',(AddCounters('source','+1/+1',1),))
        self.assertIsNone(result);self.assertEqual((('+1/+1',6),),self.state.get(self.source).counters)
        self.assertEqual([],self.kernel.accepted)

    def test_zero_additions_do_not_become_one_and_cancellation_has_no_added_event(self):
        self.setup_game((self.modifier('plus',additional=1),self.modifier('cancel',multiplier=0)))
        self.state.add_card('plus','plus','A',Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(self.source,'A',(AddCounters('source','+1/+1',0),))
        self.assertEqual((),self.state.get(self.source).counters)
        self.state.add_card('cancel','cancel','A',Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(self.source,'A',(AddCounters('source','+1/+1',1),))
        self.assertEqual((),self.state.get(self.source).counters)
        self.assertFalse(any(e['kind']=='counters_added' for e in self.kernel.semantic_events))

    def test_replacements_follow_recipient_controller_and_phasing(self):
        self.setup_game((self.modifier('plus',additional=1),))
        modifier=self.state.add_card('plus','plus','B',Zone.BATTLEFIELD)
        other=self.state.add_card('other','creature','B',Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(self.source,'A',(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',)),(AddCounters('selected','+1/+1',1),)),))
        self.assertEqual((('+1/+1',1),),self.state.get(self.source).counters)
        self.assertEqual((('+1/+1',2),),self.state.get(other).counters)
        self.state.phase(modifier,True)
        self.kernel.execute_for_scenario(other,'B',(AddCounters('source','+1/+1',1),))
        self.assertEqual((('+1/+1',3),),self.state.get(other).counters)

    def test_multi_recipient_replacement_choices_follow_apnap_without_partial_commit(self):
        self.setup_game((self.modifier('plus',additional=1),self.modifier('double',multiplier=2)))
        for player in ('A','B'):
            for key in ('plus','double'):self.state.add_card(player+key,key,player,Zone.BATTLEFIELD)
        other=self.state.add_card('other','creature','B',Zone.BATTLEFIELD)
        self.kernel.active='B';before=self.state.snapshot()
        self.kernel.execute_for_scenario(self.source,'A',(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',)),(AddCounters('selected','+1/+1',1),)),))
        r=self.kernel.pending_choice;self.assertEqual('B',r.actor)
        self.answer([0]);self.assertEqual(before,self.state.snapshot());self.assertEqual('A',self.kernel.pending_choice.actor)
        self.answer([0]);self.assertEqual(before['sequence']+1,self.state.sequence)
        self.assertEqual((('+1/+1',3),),self.state.get(other).counters)

    def test_proliferate_emits_one_event_per_recipient_with_all_counter_kinds(self):
        observer=CardProgram('observer','Observer',('Enchantment',),abilities=(AbilityProgram('count',EventPattern('counters_added',controller_only=True),(GainLife(EventAmount()),)),))
        self.setup_game((observer,));self.state.add_card('observer','observer','A',Zone.BATTLEFIELD)
        self.state.add_counters(self.source,'+1/+1',1);self.state.add_counters(self.source,'charge',2)
        self.state.add_player_counters('A','energy',1)
        self.kernel.execute_for_scenario(self.source,'A',(Proliferate(),));self.answer([0,1])
        while self.kernel.pending_choice:self.answer(list(range(len(self.kernel.pending_choice.options))))
        self.drain();events=[e for e in self.kernel.semantic_events if e['kind']=='counters_added']
        self.assertEqual([2,1],[e['amount'] for e in events]);self.assertEqual(43,self.state.life('A'))
        self.assertEqual({'+1/+1':1,'charge':1},events[0]['counters'])

    def test_player_replacements_and_counter_kind_filters_share_the_batch(self):
        rule=self.modifier('player-plus',additional=1,players='controller',kind=None)
        observer=CardProgram('observer','Observer',('Enchantment',),abilities=(AbilityProgram('poison',EventPattern('counters_added',counter_kind='poison'),(GainLife(EventAmount()),)),))
        self.setup_game((rule,observer));self.state.add_card('rule','player-plus','B',Zone.BATTLEFIELD);self.state.add_card('observer','observer','A',Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(self.source,'A',(AddCounters('opponents','poison',1),));self.drain()
        while self.kernel.pending_choice:self.answer(list(range(len(self.kernel.pending_choice.options))))
        self.assertEqual((('poison',2),),self.state.player_counters('B'));self.assertEqual((('poison',1),),self.state.player_counters('C'))
        self.assertEqual(43,self.state.life('A'))

    def test_invalid_batch_cannot_partly_mutate_state(self):
        self.setup_game();before=self.state.snapshot()
        invalid=ObjectRef('missing',0)
        for placements in (((self.source,(('charge',1),)),(invalid,(('charge',1),))),
                ((self.source,(('charge',1),)),(PlayerRef('unknown'),(('poison',1),))),
                ((self.source,(('charge',1),('charge',2))),),((self.source,(('charge',0),)),)):
            with self.assertRaises(RulesViolation):self.state.put_counters_batch(placements)
            self.assertEqual(before,self.state.snapshot())

    def test_player_counter_target_runs_through_authenticated_adapter(self):
        spell=CardProgram('spell','Spell',('Sorcery',),cast=CastSpec(CostSpec()),spell_targets=TargetSpec(players='opponents'),spell_effects=(AddCounters('target','poison',2),))
        self.setup_game((spell,));ref=self.state.add_card('spell','spell','A',Zone.HAND);self.kernel.open_window_for_scenario('A');adapter=RulesActorAdapter(self.kernel)
        adapter.submit('A',{'kind':'cast','revision':self.kernel.revision,'action_id':'cast','source':ref.to_json(),'targets':[{'player':'B'}],'x_value':0,'payment':{'mana':{},'taps':[]}})
        for actor in ('A','B','C'):adapter.submit(actor,{'kind':'pass','revision':self.kernel.revision})
        restored=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.assertEqual((('poison',2),),self.state.player_counters('B'));self.assertEqual(adapter.archive(),restored.archive())

    def test_compiler_rejects_ambiguous_limits_and_invalid_modifiers(self):
        for kwargs in ({'multiplier':-1},{'multiplier':True},{'additional':-1},{'selector':Selector(Zone.HAND)},{'kind':''}):
            rule=CounterReplacement('bad',Selector(Zone.BATTLEFIELD),additional=1)
            from dataclasses import replace
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Enchantment',),counter_replacements=(replace(rule,**kwargs),)))
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Enchantment',),abilities=(AbilityProgram('limit',EventPattern('counters_added'),(GainLife(1),),trigger_limit=1),)))
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),spell_effects=(MultiplyCounters('missing','charge'),)))


class AuthoredCounterTests(unittest.TestCase):
    def setUp(self):
        self.programs=tuple(r['program'] for r in load_reviewed().values());self.state=RulesState(('A','B','C'));self.kernel=RulesKernel(self.state,self.programs)

    def add(self,key,zone=Zone.BATTLEFIELD,actor='A',name=None):return self.state.add_card(name or key,'catalog:'+key,actor,zone)

    def drain(self):
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)
        return self.kernel.pending_choice

    def answer(self,indexes):
        r=self.kernel.pending_choice;self.kernel.answer(r.request_id,r.actor,indexes);return self.drain()

    def test_scales_and_branching_modify_proliferate_without_separate_card_handlers(self):
        self.add('hardened-scales');self.add('branching-evolution');ref=self.add('llanowar-elves');self.state.add_counters(ref,'+1/+1',1)
        self.kernel.execute_for_scenario(ref,'A',(Proliferate(),));self.answer([0])
        r=self.kernel.pending_choice;self.assertEqual('counter_replacement',r.kind)
        self.answer([next(i for i,o in enumerate(r.options) if 'Hardened Scales' in o.label)])
        self.assertEqual((('+1/+1',5),),self.state.get(ref).counters)

    def test_surge_adds_then_doubles_current_counters_with_replacements_twice(self):
        self.add('hardened-scales');ref=self.add('llanowar-elves');self.state.add_counters(ref,'+1/+1',1)
        spell=self.add('invigorating-surge',Zone.HAND);self.kernel.stage_spell_for_scenario(spell,'A',(ref,));self.drain()
        self.assertEqual((('+1/+1',7),),self.state.get(ref).counters)
        self.assertEqual([2,4],[e['amount'] for e in self.kernel.semantic_events if e['kind']=='counters_added'])

    def test_bill_landfall_can_target_opponent_but_activation_doubles_only_own(self):
        bill=self.add('bristly-bill-spine-sower');own=self.add('llanowar-elves');enemy=self.add('llanowar-elves',actor='B',name='enemy')
        self.state.add_counters(own,'+1/+1',2);land=self.add('forest',Zone.HAND);self.kernel.enter(land)
        r=self.kernel.pending_choice;self.answer([next(i for i,o in enumerate(r.options) if o.ref==enemy)])
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',tuple('CCCGG'))
        self.kernel.commit_action(self.kernel.quote_activation('double','A',bill,'double'),Payment((('C',3),('G',2))));self.drain()
        self.assertEqual((('+1/+1',4),),self.state.get(own).counters);self.assertEqual((('+1/+1',1),),self.state.get(enemy).counters)
        self.assertEqual((),self.state.get(bill).counters)

    def test_exemplar_draw_limit_is_trigger_time_per_turn_and_restores(self):
        ref=self.add('exemplar-of-light')
        for i in range(3):self.add('forest',Zone.LIBRARY,name=str(i))
        for _ in range(2):self.kernel.execute_for_scenario(ref,'A',(GainLife(1),));self.drain()
        self.assertEqual(1,len(self.state.zone('A',Zone.HAND)));self.assertEqual((('+1/+1',2),),self.state.get(ref).counters)
        shown=RulesActorAdapter(self.kernel).packet('B')['zones']['battlefield']['A'][0]
        self.assertEqual([{'ability_id':'counter-draw','remaining':0}],shown['limited_triggers'])
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        for kernel in (self.kernel,restored):
            kernel.state.start_turn('B');kernel.execute_for_scenario(ref,'A',(GainLife(1),))
            while kernel.stack:kernel.pass_priority(kernel.priority)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertEqual(2,len(self.state.zone('A',Zone.HAND)))

    def test_other_players_proliferate_does_not_consume_exemplars_own_placement_limit(self):
        ref=self.add('exemplar-of-light');self.add('forest',Zone.LIBRARY);self.state.add_counters(ref,'+1/+1',1)
        self.kernel.execute_for_scenario(ref,'B',(Proliferate(),));self.answer([0])
        self.assertEqual(0,len(self.state.zone('A',Zone.HAND)));self.assertEqual({},self.kernel.trigger_limits)
        self.kernel.execute_for_scenario(ref,'A',(Proliferate(),));self.answer([0]);self.drain()
        self.assertEqual(1,len(self.state.zone('A',Zone.HAND)))

    def test_managorger_counts_opponent_spells_through_shared_counter_event(self):
        ref=self.add('managorger-hydra');spell=self.add('sol-ring',Zone.HAND,'B')
        self.kernel.stage_spell_for_scenario(spell,'B');self.drain()
        self.assertEqual((('+1/+1',1),),self.state.get(ref).counters)
        self.assertEqual(1,sum(e['kind']=='counters_added' for e in self.kernel.semantic_events))
