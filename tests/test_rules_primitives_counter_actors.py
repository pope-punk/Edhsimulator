"""Counter actor filters and rounded transforms share entry and placement paths."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_counters import commute

class CounterActorTests(unittest.TestCase):
    def game(self,zone=Zone.BATTLEFIELD):
        self.programs=tuple(r['program'] for r in load_reviewed().values())
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('vorinclex','catalog:vorinclex-monstrous-raider','A',zone)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def test_printed_cast_and_keywords(self):
        self.game(Zone.HAND);self.state.add_mana('A',('G','G')+('C',)*4)
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.ref),Payment((('G',2),('C',4))))
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
        view=self.kernel.effective(self.state.current('vorinclex'))
        self.assertEqual(6,view.power);self.assertTrue({'haste','trample'}<=view.keywords);self.assertEqual((),self.state.mana_pool('A'))

    def test_placing_actor_controls_transform_independent_of_recipient_controller(self):
        for actor in ('A','B'):
            for owner in ('A','B'):
                self.game();ref=self.state.add_card('land','catalog:forest',owner,Zone.BATTLEFIELD)
                self.kernel.execute_for_scenario(ref,actor,(AddCounters('source','charge',3),))
                self.assertEqual((('charge',6 if actor=='A' else 1),),self.state.get(ref).counters)

    def test_player_placements_round_each_kind_and_suppress_zero(self):
        self.game();self.kernel.execute_for_scenario(self.ref,'B',(AddCounters('all','energy',3),AddCounters('all','poison',1)))
        for p in ('A','B'):self.assertEqual((('energy',1),),self.state.player_counters(p))
        self.kernel.execute_for_scenario(self.ref,'A',(AddCounters('opponents','experience',2),))
        self.assertEqual((('energy',1),('experience',4)),self.state.player_counters('B'))

    def test_opposing_sources_order_is_atomic_and_checkpointed(self):
        for first,expected in (('double',1),('halve',0)):
            self.game();self.state.add_card('other','catalog:vorinclex-monstrous-raider','B',Zone.BATTLEFIELD)
            ref=self.state.add_card('land','catalog:forest','A',Zone.BATTLEFIELD);before=self.state.snapshot()
            q=self.kernel.execute_for_scenario(ref,'A',(AddCounters('source','charge',1),))
            self.assertEqual(before,self.state.snapshot());self.assertEqual('A',q.actor)
            restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
            index=next(i for i,o in enumerate(q.options) if o.label.endswith(': '+first))
            for kernel in (self.kernel,restored):kernel.answer(q.request_id,'A',[index])
            self.assertEqual(self.kernel.snapshot(),restored.snapshot())
            self.assertEqual(expected,dict(self.state.get(ref).counters).get('charge',0))

    def test_entry_counter_placer_is_entering_controller(self):
        for owner,expected in (('A',2),('B',0)):
            self.game();ref=self.state.add_card('blast','catalog:blast-zone',owner,Zone.HAND)
            self.kernel.enter(ref,owner)
            self.assertEqual(expected,dict(self.state.get(self.state.current('blast')).counters).get('charge',0))

    def test_copied_source_and_phasing_update_actor_filter(self):
        self.game(Zone.GRAVEYARD);ref=self.state.add_card('copy','catalog:forest','B',Zone.HAND)
        self.state.move((ZoneMove(ref,Zone.BATTLEFIELD,'B',copied_definition='catalog:vorinclex-monstrous-raider'),),'fixture-copy');ref=self.state.current('copy')
        self.kernel.execute_for_scenario(ref,'B',(AddCounters('source','charge',3),));self.assertEqual((('charge',6),),self.state.get(ref).counters)
        self.state.phase(ref,True);land=self.state.add_card('land','catalog:forest','B',Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(land,'A',(AddCounters('source','charge',3),));self.assertEqual((('charge',3),),self.state.get(land).counters)

    def test_rounded_commutation_is_not_inferred_from_one_even_value(self):
        double=CounterReplacement('double',Selector(Zone.BATTLEFIELD),multiplier=2)
        half=CounterReplacement('half',Selector(Zone.BATTLEFIELD),divisor=2)
        self.assertFalse(commute({'charge':2},double,half));self.assertTrue(commute({'charge':2},half,half))
        for rule in (CounterReplacement('bad',Selector(Zone.BATTLEFIELD),divisor=0),CounterReplacement('bad',Selector(Zone.BATTLEFIELD),divisor=True),CounterReplacement('bad',Selector(Zone.BATTLEFIELD),divisor=2,actor_relation='owner')):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Artifact',),counter_replacements=(rule,)))
