"""Optional turn allowances are consumed by acceptance, not trigger creation."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_casting import Payment

class OptionalLimitTests(unittest.TestCase):
    def game(self):
        self.programs=tuple(r['program'] for r in load_reviewed().values())
        self.state=RulesState(('A','B'));self.source=self.state.add_card('terra','catalog:terrasymbiosis','A',Zone.BATTLEFIELD)
        self.body=self.state.add_card('body','catalog:elvish-mystic','A',Zone.BATTLEFIELD)
        for actor in ('A','B'):
            for i in range(15):self.state.add_card(actor+str(i),'catalog:forest',actor,Zone.LIBRARY)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
    def counters(self,n=1,actor='A',ref=None,kind='+1/+1'):
        self.kernel.execute_for_scenario(ref or self.body,actor,(AddCounters('source',kind,n),))
    def reach_choice(self,k=None):
        k=k or self.kernel
        while k.stack and not k.pending_choice:k.pass_priority(k.priority)
        return k.pending_choice
    def answer(self,yes=True,k=None):
        k=k or self.kernel;q=self.reach_choice(k);self.assertEqual('may',q.kind)
        k.answer(q.request_id,q.actor,[0 if yes else 1]);self.reach_choice(k)
    def hand(self,actor='A'):return len(self.state.zone(actor,Zone.HAND))
    def test_decline_preserves_allowance_later_acceptance_suppresses_triggers(self):
        self.game();self.counters(1);self.answer(False);self.assertEqual(0,self.hand())
        self.counters(3);self.answer();self.assertEqual(3,self.hand())
        before=len(self.kernel.semantic_events);self.counters(2);self.assertIsNone(self.reach_choice());self.assertEqual(3,self.hand())
        self.assertFalse(any(e['kind']=='trigger_created' for e in self.kernel.semantic_events[before:]))
    def test_simultaneous_recipients_create_separate_triggers_but_only_one_use(self):
        self.game();other=self.state.add_card('other','catalog:elvish-mystic','A',Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(self.source,'A',(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled'),(AddCounters('selected','+1/+1',2),)),))
        q=self.kernel.pending_choice;self.assertEqual('trigger_order',q.kind);self.kernel.answer(q.request_id,q.actor,list(range(len(q.options))))
        self.answer();self.assertIsNone(self.reach_choice());self.assertEqual(2,self.hand())
        self.assertEqual(2,len([e for e in self.kernel.semantic_events if e['kind']=='trigger_created']))
        self.assertEqual(1,len([e for e in self.kernel.semantic_events if e['kind']=='optional_turn_use_consumed']))
    def test_countered_trigger_does_not_consume_allowance(self):
        self.game();self.counters(2)
        counter=self.state.add_card('dismiss','catalog:summary-dismissal','A',Zone.HAND);self.state.add_mana('A',('C','C','U','U'))
        self.kernel.commit_action(self.kernel.quote_cast('dismiss','A',counter),Payment((('C',2),('U',2))));self.assertIsNone(self.reach_choice())
        self.counters(1);self.answer();self.assertEqual(1,self.hand())
    def test_new_turn_and_new_incarnation_get_fresh_allowances(self):
        self.game();self.counters();self.answer();self.state.start_turn('B');self.counters(2);self.answer();self.assertEqual(3,self.hand())
        self.state.move((ZoneMove(self.source,Zone.HAND),),'scenario_blink')
        self.state.move((ZoneMove(self.state.current('terra'),Zone.BATTLEFIELD,'A'),),'scenario_return');self.source=self.state.current('terra')
        self.counters();self.answer();self.assertEqual(4,self.hand())
    def test_actor_and_recipient_filters_ignore_foreign_and_other_counter_events(self):
        self.game();self.counters(actor='B');self.assertIsNone(self.reach_choice())
        self.counters(kind='shield');self.assertIsNone(self.reach_choice())
        enemy=self.state.add_card('enemy','catalog:elvish-mystic','B',Zone.BATTLEFIELD);self.counters(ref=enemy);self.assertIsNone(self.reach_choice())
        self.counters();self.answer();self.assertEqual(1,self.hand())
    def test_control_change_tracks_each_controller_and_retains_previous_use(self):
        self.game();self.counters();self.answer()
        self.state.change_control(self.source,'B');self.state.change_control(self.body,'B')
        self.counters(actor='B');self.answer();self.assertEqual(1,self.hand('B'))
        self.state.change_control(self.source,'A');self.state.change_control(self.body,'A')
        self.counters();self.assertIsNone(self.reach_choice());self.assertEqual(1,self.hand())
    def test_pending_and_consumed_states_replay_exactly(self):
        self.game();self.counters(2);self.reach_choice();a=RulesActorAdapter(self.kernel);b=RulesActorAdapter.replay(a.archive(),self.programs)
        q=self.kernel.pending_choice;cmd={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[0]}
        a.submit('A',cmd);b.submit('A',cmd);self.reach_choice();self.reach_choice(b.kernel);self.assertEqual(a.archive(),b.archive())
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        for k in (self.kernel,restored):k.execute_for_scenario(self.body,'A',(AddCounters('source','+1/+1',1),));self.reach_choice(k)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertEqual(2,self.hand())
    def test_closed_validation_and_nested_optional_effect_not_limited_again(self):
        self.game();base=load_reviewed()['terrasymbiosis']['program'];ability=base.abilities[0]
        for bad in (replace(ability,optional_once_per_turn=1),replace(ability,trigger_limit=1),replace(ability,effects=(Draw(1),)),replace(ability,effects=(May((Draw(1),),otherwise=(GainLife(1),)),))):
            with self.assertRaises(RulesViolation):validate(replace(base,abilities=(bad,)))
        custom=replace(base,abilities=(replace(ability,effects=(May((May((GainLife(1),)),)),)),))
        state=RulesState(('A','B'));source=state.add_card('terra',custom.definition_id,'A',Zone.BATTLEFIELD);body=state.add_card('body','catalog:elvish-mystic','A',Zone.BATTLEFIELD)
        programs=tuple(p for p in self.programs if p.definition_id!=custom.definition_id)+(custom,);k=RulesKernel(state,programs);k.open_window_for_scenario('A')
        k.execute_for_scenario(body,'A',(AddCounters('source','+1/+1',1),));self.answer(k=k);self.answer(k=k);self.assertEqual(41,state.life('A'))

if __name__=='__main__':unittest.main()
