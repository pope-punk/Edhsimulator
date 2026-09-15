"""Entry X survives spell movement and signed temporary P/T uses shared quantities."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class EntryXTests(unittest.TestCase):
    def game(self,zone=Zone.HAND,extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(CardProgram('small','Small',('Creature',),power=2,toughness=2),CardProgram('large','Large',('Creature',),power=5,toughness=5),)+tuple(extra)
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('hook','catalog:the-meathook-massacre','A',zone)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack or kernel.pending_choice:
            if kernel.pending_choice:
                q=kernel.pending_choice;self.assertEqual('trigger_order',q.kind);kernel.answer(q.request_id,q.actor,list(range(len(q.options))))
            else:kernel.pass_priority(kernel.priority)

    def cast_to_entry_trigger(self,x):
        self.state.add_mana('A',('B','B')+('C',)*x)
        payment=(('B',2),)+((('C',x),) if x else ())
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.ref,x_value=x),Payment(payment))
        while self.kernel.stack[-1]['spell']:self.kernel.pass_priority(self.kernel.priority)
        self.ref=self.state.current('hook')

    def test_printed_x_cost_simultaneous_deaths_life_triggers_and_cleanup(self):
        self.game();self.state.add_card('own','small','A',Zone.BATTLEFIELD);self.state.add_card('opponent','small','B',Zone.BATTLEFIELD)
        large=self.state.add_card('large','large','B',Zone.BATTLEFIELD)
        self.cast_to_entry_trigger(2);self.assertEqual(0,self.state.get(self.ref).cast_x);self.drain()
        self.assertEqual(41,self.state.life('A'));self.assertEqual(39,self.state.life('B'))
        self.assertEqual(3,self.kernel.effective(large).power)
        deaths=[e for e in self.state.events if e.before.ref.card_id in ('own','opponent')]
        self.assertEqual(1,len({e.batch for e in deaths}));self.assertEqual((),self.state.mana_pool('A'))
        self.kernel._finish_cleanup_actions();self.assertEqual(5,self.kernel.effective(large).power)

    def test_source_departure_keeps_entry_x_through_replay(self):
        self.game();large=self.state.add_card('large','large','B',Zone.BATTLEFIELD);self.cast_to_entry_trigger(3)
        self.state.move((ZoneMove(self.ref,Zone.GRAVEYARD),),'fixture-response')
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.drain();self.drain(replay.kernel);self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot())
        self.assertEqual(2,self.kernel.effective(large).power)

    def test_reanimation_does_not_reuse_old_spell_x(self):
        self.game();self.cast_to_entry_trigger(4);self.drain()
        self.kernel.execute_for_scenario(self.ref,'A',(Destroy('source'),))
        large=self.state.add_card('large','large','B',Zone.BATTLEFIELD)
        self.kernel.enter(self.state.current('hook'),'A');self.drain()
        self.assertEqual(5,self.kernel.effective(large).power)

    def test_simultaneous_source_death_observes_its_last_creature_type(self):
        self.game(Zone.BATTLEFIELD);self.state.add_card('own','small','A',Zone.BATTLEFIELD);self.state.add_card('opponent','small','B',Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(self.ref,'A',(UntilEndOfTurn('source',(ChangeTypes(add=('Creature',)),SetPT(2,2))),SelectAll(Selector(Zone.BATTLEFIELD),(Destroy('selected'),))))
        self.drain();self.assertEqual(41,self.state.life('A'));self.assertEqual(38,self.state.life('B'))

    def test_external_entry_observer_receives_entering_spells_x(self):
        observer=CardProgram('observer','Observer',('Artifact',),abilities=(AbilityProgram('entry-x',EventPattern('zone_changed',to_zone=Zone.BATTLEFIELD,types=('Enchantment',)),(GainLife(EventX()),)),))
        self.game(extra=(observer,));self.state.add_card('observer','observer','B',Zone.BATTLEFIELD)
        self.cast_to_entry_trigger(3);self.drain();self.assertEqual(43,self.state.life('B'))

    def test_signed_scaling_and_entry_x_validation_are_scoped(self):
        for effect in (GainLife(ScaledValue(2,-1)),Damage('controller',ScaledValue(2,-1))):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),spell_effects=(effect,)))
        for event in (EventPattern('step_began',step='upkeep'),EventPattern('zone_changed',from_zone=Zone.BATTLEFIELD,to_zone=Zone.GRAVEYARD)):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Enchantment',),abilities=(AbilityProgram('bad',event,(GainLife(EventX()),)),)))
        validate(CardProgram('good','Good',('Instant',),spell_effects=(UntilEndOfTurn('source',(ModifyPT(ScaledValue(2,-1),0),)),)))

    def test_nonstack_copy_inherits_zero_x_entry_and_its_own_controller_death_triggers(self):
        self.game(Zone.GRAVEYARD);large=self.state.add_card('large','large','A',Zone.BATTLEFIELD)
        copy=self.state.add_card('copy','small','B',Zone.HAND)
        before=self.state.objects(Zone.BATTLEFIELD);views=self.kernel.characteristics()
        events=self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,'B',copied_definition='catalog:the-meathook-massacre'),),'fixture-copy')
        self.kernel._collect(events,before,self.state.objects(Zone.BATTLEFIELD),views);self.kernel.advance();self.drain()
        self.assertEqual(5,self.kernel.effective(large).power)
        self.kernel.execute_for_scenario(large,'A',(Destroy('source'),));self.drain()
        self.assertEqual(41,self.state.life('B'));self.assertEqual(40,self.state.life('A'))
