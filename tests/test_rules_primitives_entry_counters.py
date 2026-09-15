"""Entry counters belong to the replaced zone event, before triggers and SBAs."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import (CardProgram,EntryCounters,CounterReplacement,Selector,Move,SelectAll,
    AbilityProgram,EventPattern,GainLife,EventAmount,ChosenX,CastSpec,CostSpec,ManaCost,ZoneReplacement,validate)
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel


class EntryCounterTests(unittest.TestCase):
    def game(self,extras=(),own=(EntryCounters('base','+1/+1',4),),**kwargs):
        self.body=CardProgram('body','Body',('Creature',),power=0,toughness=0,entry_counters=own,**kwargs)
        self.programs=(self.body,*extras)
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('body','body','A',Zone.HAND)
        self.kernel=RulesKernel(self.state,self.programs)

    def modifier(self,key,*,additional=0,multiplier=1):
        return CardProgram(key,key,('Enchantment',),counter_replacements=(CounterReplacement(key,
            Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled'),None,'+1/+1',multiplier,additional),))

    def enter(self):return self.kernel.execute_for_scenario(self.ref,'A',(Move('source',Zone.BATTLEFIELD),))

    def answer_label(self,text):
        r=self.kernel.pending_choice
        return self.kernel.answer(r.request_id,r.actor,[next(i for i,o in enumerate(r.options) if text in o.label)])

    def test_counter_event_and_entry_lki_already_have_counters_before_sba(self):
        ability=AbilityProgram('counter',EventPattern('counters_added',subject='self'),(GainLife(EventAmount()),))
        self.game(abilities=(ability,));self.enter()
        event=self.state.events[0]
        self.assertEqual((('+1/+1',4),),event.after.counters)
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('body')).zone)
        self.assertEqual(4,self.kernel.stack[-1]['values']['event_amount'])
        self.kernel.pass_priority('A');self.kernel.pass_priority('B')
        self.assertEqual(44,self.state.life('A'))
        self.assertEqual(1,sum(e['kind']=='counters_added' for e in self.kernel.semantic_events))

    def test_additions_and_multipliers_interleave_once_with_exact_restore(self):
        global_entry=CardProgram('global','Global',('Enchantment',),entry_counters=(EntryCounters('extra','+1/+1',2,
            Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled')),))
        for second,expected in (('double',10),('Global',12)):
            self.game((global_entry,self.modifier('double',multiplier=2)))
            for key in ('global','double'):self.state.add_card(key,key,'A',Zone.BATTLEFIELD)
            before=self.state.snapshot();self.enter();self.answer_label('base')
            self.assertEqual(before,self.state.snapshot())
            restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
            request=self.kernel.pending_choice
            indexes=[next(i for i,o in enumerate(request.options) if second in o.label)]
            self.kernel.answer(request.request_id,request.actor,indexes)
            restored.answer(request.request_id,request.actor,indexes)
            self.assertEqual(self.kernel.snapshot(),restored.snapshot())
            self.assertEqual((('+1/+1',expected),),self.state.get(self.state.current('body')).counters)

    def test_scales_applies_once_for_two_entry_additions(self):
        self.game((self.modifier('plus',additional=1),),own=(EntryCounters('first','+1/+1',4),EntryCounters('second','+1/+1',2)))
        self.state.add_card('plus','plus','A',Zone.BATTLEFIELD)
        self.enter();self.answer_label('first');self.answer_label('plus')
        self.assertEqual((('+1/+1',7),),self.state.get(self.state.current('body')).counters)

    def test_entry_copy_inherits_counters_and_not_copied_cast_x(self):
        target=CardProgram('target','Target',('Creature',),power=0,toughness=0,
            entry_counters=(EntryCounters('base','+1/+1',4),))
        self.game((target,),own=(),entry_copy=Selector(Zone.GRAVEYARD))
        self.state.add_card('model','target','A',Zone.GRAVEYARD)
        request=self.enter();self.assertEqual('entry_copy',request.kind)
        self.kernel.answer(request.request_id,'A',[0])
        self.assertEqual((('+1/+1',4),),self.state.events[0].after.counters)
        self.assertEqual('target',self.state.events[0].after.copied_definition)

    def test_incoming_broad_modifier_is_inactive_but_self_modifier_applies(self):
        for subject,expected in (('any',4),('self',8)):
            self.game(counter_replacements=(CounterReplacement('double',Selector(Zone.BATTLEFIELD),None,'+1/+1',2,0,subject),))
            self.enter();self.assertEqual((('+1/+1',expected),),self.state.events[0].after.counters)

    def test_simultaneous_incoming_global_modifiers_do_not_affect_coentrants(self):
        global_entry=CardProgram('global','Global',('Creature',),power=1,toughness=1,
            entry_counters=(EntryCounters('extra','+1/+1',2,Selector(Zone.BATTLEFIELD,types=('Creature',))),))
        self.game((global_entry,));self.state.add_card('global','global','A',Zone.HAND)
        self.kernel.execute_for_scenario(self.ref,'A',(SelectAll(Selector(Zone.HAND),(Move('selected',Zone.BATTLEFIELD),)),))
        self.assertEqual((('+1/+1',4),),self.state.get(self.state.current('body')).counters)
        self.assertEqual((),self.state.get(self.state.current('global')).counters)
        self.assertEqual(1,len({e.batch for e in self.state.events}))

    def test_redirect_discards_proposed_counters_without_counter_event(self):
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.BATTLEFIELD,Zone.EXILE),))
        self.game((redirect,));self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD)
        self.enter();self.answer_label('base')
        self.assertEqual(Zone.EXILE,self.state.events[0].after.zone)
        self.assertEqual((),self.state.events[0].after.counters)
        self.assertFalse(any(e['kind']=='counters_added' for e in self.kernel.semantic_events))

    def test_entry_x_uses_entering_stack_object_and_is_zero_elsewhere(self):
        for zone,x,expected in ((Zone.STACK,5,5),(Zone.HAND,0,0)):
            self.game(own=(EntryCounters('x','+1/+1',ChosenX()),),cast=CastSpec(CostSpec(ManaCost(x_symbols=1))))
            if zone==Zone.STACK:
                self.state.move((ZoneMove(self.ref,Zone.STACK,cast_x=x),),'cast');self.ref=self.state.current('body')
            self.enter()
            entry=next(e.after for e in self.state.events if e.after.zone==Zone.BATTLEFIELD)
            self.assertEqual((('+1/+1',expected),) if expected else (),entry.counters)

    def test_low_level_counter_entry_validation_is_atomic(self):
        self.game();before=self.state.snapshot()
        for destination,counters in ((Zone.GRAVEYARD,(('x',1),)),(Zone.BATTLEFIELD,(('x',0),)),
                (Zone.BATTLEFIELD,(('x',True),)),(Zone.BATTLEFIELD,(('x',1),('x',2)))):
            with self.assertRaises(RulesViolation):self.state.move((ZoneMove(self.ref,destination,counters=counters),),'invalid')
            self.assertEqual(before,self.state.snapshot())

    def test_invalid_entry_programs_rejected(self):
        self.game()
        for rules in ([EntryCounters('x','x',1)],(EntryCounters('x','x',-1),),
                (EntryCounters('x','x',ChosenX()),),(EntryCounters('x','x',1),)*2,
                (EntryCounters('x','x',1,Selector(Zone.HAND)),)):
            with self.assertRaises(RulesViolation):validate(replace(self.body,entry_counters=rules))

class AuthoredEntryCounterTests(unittest.TestCase):
    def setup_game(self):
        from edh_gauntlet.rules_bundle import load_reviewed
        self.programs=tuple(r['program'] for r in load_reviewed().values())
        self.state=RulesState(('A','B'))
        self.kernel=RulesKernel(self.state,self.programs)

    def test_kalonian_enters_then_attack_doubles_via_normal_stack(self):
        self.setup_game()
        ref=self.state.add_card('hydra','catalog:kalonian-hydra','A',Zone.HAND)
        self.kernel.execute_for_scenario(ref,'A',(Move('source',Zone.BATTLEFIELD),))
        ref=self.state.current('hydra')
        self.assertEqual(4,dict(self.state.get(ref).counters)['+1/+1'])
        self.state.add_card('draw','catalog:forest','A',Zone.LIBRARY)
        self.kernel.begin_turn_for_scenario('A')
        for _ in range(8):self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual('declare_attackers',self.kernel.phase)
        self.kernel.declare_attackers('A',{ref:'B'},revision=self.kernel.revision)
        self.assertEqual('attack-double',self.kernel.stack[-1]['ability_id'])
        self.kernel.pass_priority('A');self.kernel.pass_priority('B')
        self.assertEqual(8,dict(self.state.get(ref).counters)['+1/+1'])

    def test_grumgully_nonhuman_control_and_phasing_filters(self):
        from edh_gauntlet.rules_bundle import load_reviewed
        for key,actor,phased,expected in (('kalonian-hydra','A',False,5),('kalonian-hydra','B',False,4),
                ('kalonian-hydra','A',True,4),('eternal-witness','A',False,0)):
            self.setup_game()
            global_ref=self.state.add_card('grumgully','catalog:grumgully-the-generous','A',Zone.BATTLEFIELD)
            if phased:self.state.phase(global_ref,True)
            ref=self.state.add_card('entry','catalog:'+key,actor,Zone.HAND)
            self.kernel.execute_for_scenario(ref,actor,(Move('source',Zone.BATTLEFIELD),))
            while self.kernel.pending_choice:
                r=self.kernel.pending_choice;self.kernel.answer(r.request_id,r.actor,[0])
            self.assertEqual(expected,dict(self.state.get(self.state.current('entry')).counters).get('+1/+1',0))

if __name__=='__main__':unittest.main()

