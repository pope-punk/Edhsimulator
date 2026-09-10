import queue
import unittest
from unittest.mock import patch, Mock
from contextlib import ExitStack, nullcontext
from pathlib import Path
from edh_gauntlet import background_slots as slots, planner_runtime
from edh_gauntlet.host_runtime import Runner
from edh_gauntlet.agent_architecture import SHORT, LONG, DIPLOMACY

SEATS = ('A', 'B', 'C', 'D')
ROLES = ('decider', SHORT, LONG, DIPLOMACY)


def job(actor, role):
    return dict(actor=actor, role=role, batch_id=actor+role, id=actor+role,
                status='pending', mandatory=True)


class InferenceLaneTests(unittest.TestCase):
    def test_twelve_background_reservations_coexist(self):
        state={'role_slots':2}
        jobs=[job(actor,role) for actor in SEATS for role in ROLES[1:]]
        for value in jobs:
            self.assertIn(value, slots.available(state,jobs))
            slots.assign(state,value)
        self.assertEqual(len(slots.reservations(state)),12)
        self.assertEqual(slots.available(state,jobs),[])
        for value in jobs:
            self.assertIs(slots.reservation(state,value['batch_id']),value)
        slots.release(state,jobs[0])
        self.assertEqual(slots.available(state,jobs),[jobs[0]])
        self.assertEqual(len(slots.reservations(state)),11)

    def test_duplicate_seat_role_rejected(self):
        state={'role_slots':2}
        slots.assign(state,job('A',SHORT))
        with self.assertRaises(SystemExit):slots.assign(state,job('A',SHORT))
        slots.assign(state,job('B',SHORT))

    def test_old_role_lanes_stay_shared(self):
        state={'role_slots':1}
        slots.assign(state,job('A',SHORT))
        self.assertEqual(slots.available(state,[job('B',SHORT)]),[])
        with self.assertRaises(SystemExit):slots.assign(state,job('B',SHORT))
        slots.assign(state,job('B',LONG))
        self.assertEqual(set(state['active_by_role']),{SHORT,LONG})

    def test_legacy_serial_admission(self):
        state={}
        slots.assign(state,job('A',SHORT))
        self.assertEqual(slots.available(state,[job('B',LONG)]),[])
        slots.release(state,job('A',SHORT))
        self.assertEqual(len(slots.available(state,[job('B',LONG)])),1)

    def runner(self,version=2):
        runner=Runner.__new__(Runner)
        runner.concurrent_roles=True;runner.role_slots=version
        runner.active=set();runner.pending={};runner.parking=set()
        runner.threads={actor+role:(actor,role) for actor in SEATS for role in ROLES}
        return runner

    def test_all_sixteen_host_lanes_admitted(self):
        runner=self.runner()
        for thread in runner.threads:
            self.assertTrue(runner.slot_available(thread))
            runner.active.add(thread)
        self.assertEqual(runner.inference_count(),16)
        runner.threads['duplicate']=('A',SHORT)
        self.assertFalse(runner.slot_available('duplicate'))

    def test_same_seat_role_excluded_below_capacity(self):
        runner=self.runner();runner.active.add('A'+SHORT)
        runner.threads['duplicate']=('A',SHORT)
        self.assertFalse(runner.slot_available('duplicate'))
        self.assertTrue(runner.slot_available('B'+SHORT))
        self.assertTrue(runner.slot_available('A'+LONG))

    def test_waiting_and_parking_do_not_consume_inference(self):
        runner=self.runner();runner.active={'Adecider','Bdecider'}
        runner.pending={'Adecider':object()};runner.parking={'Bdecider'}
        self.assertEqual(runner.inference_count(),0)
        self.assertTrue(runner.slot_available('Cdecider'))

    def test_old_host_role_lane_still_excludes_other_seats(self):
        runner=self.runner(1);runner.active.add('A'+SHORT)
        self.assertFalse(runner.slot_available('B'+SHORT))
        self.assertTrue(runner.slot_available('A'+LONG))

    def test_pump_dispatches_twelve_backgrounds_without_waiting_for_completion(self):
        runner=self.runner()
        runner.root=Path('/unused');runner.game=1;runner.max_decisions=None
        runner.done=False;runner.backgrounds={};runner.metrics={}
        runner.check_pause=Mock();runner.rows=Mock(return_value=[])
        runner.action=Mock(return_value={'kind':'dispatch_pilot','game':1,'actor':'A'})
        runner.context=Mock(side_effect=lambda actor,role:actor+role)
        runner.agent=Mock(side_effect=lambda thread:'/app-server/'+thread)
        runner.routing=Mock();runner.routing.delay.return_value=0
        runner.timing=Mock();runner.timing.measure.side_effect=lambda *a,**k:nullcontext();runner.active.add('Adecider')
        runner.server=Mock();runner.server.events=queue.Queue()
        def deliver(thread,packet):runner.active.add(thread)
        runner.deliver=Mock(side_effect=deliver)
        def board(root,game,*,role,actor):
            return {'next_actor':actor,'next_role':role}
        def reserve(root,game,**kwargs):
            self.assertEqual(kwargs['host_capacity'],16)
            actor,role=kwargs['expected_identity']
            return {**job(actor,role),'generation':1,'source_session':{'accepted_prefix_count':0}}
        with ExitStack() as stack:
            stack.enter_context(patch('edh_gauntlet.host_runtime.campaign.PILOT_GAMEPLAN_FILES',dict.fromkeys(SEATS)))
            stack.enter_context(patch('edh_gauntlet.diplomacy.flush',return_value=False))
            stack.enter_context(patch('edh_gauntlet.decision_roles.flush',return_value=False))
            stack.enter_context(patch('edh_gauntlet.sequence_runtime.continue_pending',return_value={'state':'idle'}))
            stack.enter_context(patch.object(planner_runtime,'workboard',side_effect=board))
            stack.enter_context(patch.object(planner_runtime,'reserve',side_effect=reserve))
            stack.enter_context(patch.object(planner_runtime,'dispatched'))
            stack.enter_context(patch.object(planner_runtime,'read_job',return_value={}))
            runner.server.events.put({'method':'item/tool/call'})
            runner._pump()
            self.assertEqual(runner.deliver.call_count,0)
            runner.server.events.get_nowait()
            # A tool arriving during the first admission yields before the second.
            def first_delivery(thread,packet):
                deliver(thread,packet)
                runner.server.events.put({'method':'item/tool/call'})
            runner.deliver.side_effect=first_delivery
            runner._pump()
            self.assertEqual(runner.deliver.call_count,1)
            runner.server.events.get_nowait()
            runner.deliver.side_effect=deliver
            runner._pump()
        self.assertEqual(runner.deliver.call_count,12)
        self.assertEqual(len(runner.backgrounds),12)
        self.assertEqual(runner.inference_count(),13)
        self.assertEqual({runner.threads[t] for t in runner.backgrounds},
                         {(actor,role) for actor in SEATS for role in ROLES[1:]})

    def test_workboard_preserves_all_reservations_and_filters_seat(self):
        state={'role_slots':2,'jobs':{},'planners':{}}
        for actor in SEATS:slots.assign(state,job(actor,SHORT))
        for actor in SEATS:
            value=job(actor,LONG);state['jobs'][value['id']]=value
        with patch.object(planner_runtime,'_state',return_value=state), \
             patch('edh_gauntlet.split_planning.eligible',side_effect=lambda r,g,s,p:p), \
             patch('edh_gauntlet.split_planning.sort_pending'):
            board=planner_runtime.workboard(Path('/unused'),1,
                action={'kind':'dispatch_pilot','game':1},role=LONG,actor='D')
        self.assertEqual(board['next_actor'],'D')
        self.assertEqual(len(board['active_by_role']),4)
        self.assertEqual(board['planner_concurrency'],12)
        self.assertEqual(board['reserved_decision_slots'],4)

if __name__=='__main__':unittest.main()
