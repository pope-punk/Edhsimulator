"""Counter placer attribution and per-recipient counts drive All Will Be One."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,PlayerRef
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class AllOneTests(unittest.TestCase):
    def game(self,zone=Zone.BATTLEFIELD):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(CardProgram('body','Body',('Creature',),power=2,toughness=10),CardProgram('walker','Walker',('Planeswalker',)),)
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('one','catalog:all-will-be-one','A',zone)
        self.body=self.state.add_card('body','body','B',Zone.BATTLEFIELD)
        self.own=self.state.add_card('own','body','A',Zone.BATTLEFIELD)
        self.walker=self.state.add_card('walker','walker','B',Zone.BATTLEFIELD);self.state.add_counters(self.walker,'loyalty',8)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def drain(self,kernel=None,player='B'):
        kernel=kernel or self.kernel
        while kernel.stack or kernel.pending_choice:
            if kernel.pending_choice:
                q=kernel.pending_choice
                if q.kind=='trigger_order':indexes=list(range(len(q.options)))
                else:
                    self.assertEqual('trigger_targets',q.kind)
                    indexes=[next(i for i,o in enumerate(q.options) if o.player==player)]
                kernel.answer(q.request_id,q.actor,indexes)
            else:kernel.pass_priority(kernel.priority)

    def test_printed_cast_and_counter_placer_not_recipient_controller(self):
        self.game(Zone.HAND);self.state.add_mana('A',('C','C','C','R','R'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.ref),Payment((('C',3),('R',2))));self.drain();self.ref=self.state.current('one')
        self.kernel.execute_for_scenario(self.body,'A',(AddCounters('source','charge',3),));self.drain()
        self.assertEqual(37,self.state.life('B'))
        self.kernel.execute_for_scenario(self.own,'B',(AddCounters('source','charge',4),));self.drain()
        self.assertEqual(37,self.state.life('B'))

    def test_player_counters_and_zero_placements(self):
        self.game();self.kernel.execute_for_scenario(self.ref,'A',(AddCounters('opponents','energy',2),));self.drain()
        self.assertEqual(38,self.state.life('B'))
        self.kernel.execute_for_scenario(self.ref,'A',(AddCounters('controller','energy',0),));self.drain()
        self.assertEqual(38,self.state.life('B'))

    def test_target_union_excludes_own_objects_and_can_damage_planeswalker(self):
        self.game();q=self.kernel.execute_for_scenario(self.own,'A',(AddCounters('source','charge',3),))
        self.assertEqual({self.body,self.walker},{o.ref for o in q.options if o.ref})
        self.assertEqual({'B'},{o.player for o in q.options if o.player})
        self.kernel.answer(q.request_id,'A',[next(i for i,o in enumerate(q.options) if o.ref==self.walker)]);self.drain()
        self.assertEqual(5,dict(self.state.get(self.walker).counters)['loyalty']);self.assertEqual(40,self.state.life('B'))

    def test_multikind_proliferate_aggregates_each_recipient_and_replays(self):
        self.game();self.state.add_counters(self.own,'charge',1);self.state.add_counters(self.own,'+1/+1',1)
        self.state.add_player_counters('B','energy',1)
        q=self.kernel.execute_for_scenario(self.ref,'A',(Proliferate(),))
        self.assertEqual('proliferate',q.kind)
        indexes=[i for i,o in enumerate(q.options) if o.ref==self.own or o.player=='B']
        adapter=RulesActorAdapter(self.kernel)
        adapter.submit('A',{'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':indexes})
        replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.drain();self.drain(replay.kernel)
        self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot());self.assertEqual(37,self.state.life('B'))
        self.assertEqual(2,sum(e['kind']=='trigger_created' for e in self.kernel.semantic_events))

    def test_entry_counters_and_replacement_amounts_are_observed(self):
        self.game();self.state.add_card('kami','catalog:kami-of-whispered-hopes','A',Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(self.own,'A',(AddCounters('source','+1/+1',1),));self.drain();self.assertEqual(38,self.state.life('B'))
        land=self.state.add_card('blast','catalog:blast-zone','A',Zone.HAND)
        self.kernel.enter(land,'A');self.drain();self.assertEqual(37,self.state.life('B'))

    def test_copy_uses_its_controller_and_damage_survives_source_departure(self):
        self.game(Zone.GRAVEYARD);copy=self.state.add_card('copy','catalog:forest','B',Zone.HAND)
        self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,'B',copied_definition='catalog:all-will-be-one'),),'fixture-copy')
        q=self.kernel.execute_for_scenario(self.body,'B',(AddCounters('source','charge',4),))
        self.assertEqual('B',q.actor);self.kernel.answer(q.request_id,'B',[next(i for i,o in enumerate(q.options) if o.player=='A')])
        self.state.move((ZoneMove(self.state.current('copy'),Zone.GRAVEYARD),),'fixture-response')
        self.drain(player='A');self.assertEqual(36,self.state.life('A'));self.assertEqual(40,self.state.life('B'))

    def test_target_control_change_invalidates_damage(self):
        self.game();q=self.kernel.execute_for_scenario(self.own,'A',(AddCounters('source','charge',2),))
        self.kernel.answer(q.request_id,'A',[next(i for i,o in enumerate(q.options) if o.ref==self.body)])
        self.state.change_control_batch((self.body,),'A');self.drain()
        self.assertEqual(0,self.state.get(self.body).damage_marked)
