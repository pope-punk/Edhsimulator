import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from edh_gauntlet import engine,referee,component_store,pilot_handoff,planner_runtime
from edh_gauntlet.continuous import read_only_views
from edh_gauntlet.runtime_store import put,write


class QueryCacheTests(unittest.TestCase):
    def setUp(self):
        self.game=referee.ManualGame.__new__(referee.ManualGame)
        self.player=engine.PlayerState('Elenda');self.game.players={'Elenda':self.player};self.game.turn_number=1
        self.creature=engine.Perm('creature','Boo','Elenda','Elenda',token=True,base_power=1,base_toughness=1)
        self.player.battlefield=[self.creature]

    @staticmethod
    @read_only_views
    def query(game,creature):
        return game.power(creature),game.toughness(creature),game.is_creature_perm(creature)

    def test_reuses_views_but_refreshes_after_counters_and_attachments_change(self):
        with patch('edh_gauntlet.referee.evaluate_continuous',wraps=referee.evaluate_continuous) as evaluate:
            self.assertEqual(self.query(self.game,self.creature),(1,1,True));self.assertEqual(evaluate.call_count,1)
            self.assertFalse(hasattr(self.game,'_continuous_view_cache'))
            self.creature.counters['+1/+1']=3
            self.assertEqual(self.query(self.game,self.creature),(4,4,True));self.assertEqual(evaluate.call_count,2)
            self.player.battlefield.append(engine.Perm('aura','Angelic Destiny','Elenda','Elenda',attached_to='creature'))
            self.assertEqual(self.query(self.game,self.creature),(8,8,True))

    def test_nested_queries_share_cache_and_exception_discards_it(self):
        @read_only_views
        def outer(game):
            self.query(game,self.creature);self.query(game,self.creature)
            raise ValueError('aborted query')
        with patch('edh_gauntlet.referee.evaluate_continuous',wraps=referee.evaluate_continuous) as evaluate:
            with self.assertRaises(ValueError):outer(self.game)
            self.assertEqual(evaluate.call_count,1)
        self.assertFalse(hasattr(self.game,'_continuous_view_cache'))

    def test_mana_menu_refreshes_after_land_taps(self):
        self.player.battlefield=[engine.Perm('land','Swamp','Elenda','Elenda')]
        self.player.hand=[engine.CardObj('spell',engine.CARDDEF['Moment of Craving'])]
        # Two sources pay the two-mana spell before one source becomes tapped.
        self.player.battlefield.append(engine.Perm('land2','Swamp','Elenda','Elenda'))
        actions=self.game.legal_main_actions(self.player)
        self.assertTrue(any(a[0]=='cast' for a in actions))
        self.player.battlefield[0].tapped=True
        self.assertFalse(any(a[0]=='cast' for a in self.game.legal_main_actions(self.player)))

    def test_source_cache_tracks_convoke_taps_and_restoration(self):
        creature=engine.Perm('dork','Elvish Mystic','Elenda','Elenda',summoning_sick=False)
        self.player.battlefield=[creature]
        @read_only_views
        def preview(game):
            before=game.available_sources(self.player)
            creature.tapped=True
            tapped=game.available_sources(self.player)
            creature.tapped=False
            restored=game.available_sources(self.player)
            return before,tapped,restored
        before,tapped,restored=preview(self.game)
        self.assertEqual(len(before),1);self.assertEqual(tapped,[])
        self.assertEqual(restored,before)
        self.assertFalse(hasattr(self.game,'_query_source_cache'))

    def test_source_cache_copies_options_and_tracks_virtual_mana(self):
        self.player.battlefield=[engine.Perm('land','Swamp','Elenda','Elenda')]
        @read_only_views
        def preview(game):
            first=game.available_sources(self.player)
            first[0][1].clear();first.clear()
            second=game.available_sources(self.player)
            self.player.treasures=1
            third=game.available_sources(self.player)
            self.player.dungeon['floating_mana']=['test-U']
            fourth=game.available_sources(self.player)
            return second,third,fourth
        second,third,fourth=preview(self.game)
        self.assertEqual(second[0][1],{'B'})
        self.assertEqual(len(second),1);self.assertEqual(len(third),2);self.assertEqual(len(fourth),3)


class ComponentReadTests(unittest.TestCase):
    def test_one_tape_read_and_changed_branch_revalidated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);directory=root/'game_01';directory.mkdir()
            tape=directory/'decisions.jsonl';rows=[{'decision_id':'D1','choice':1}];tape.write_text(json.dumps(rows[0])+'\n')
            session=pilot_handoff.session_descriptor(root,1,'Elenda',rows);d=directory/'continuity';pointers={}
            for kind in ['standing','long_term']:
                pointers[kind]=put(d/'plan_components',{'actor':'Elenda','game':1,'kind':kind,'source_session':session})
            write(component_store.index_path(d,'Elenda'),pointers)
            with patch('edh_gauntlet.planner_runtime._rows',wraps=planner_runtime._rows) as reads:
                self.assertEqual(set(component_store.current(root,1,'Elenda')),set(pointers));reads.assert_called_once()
            tape.write_text(json.dumps({'decision_id':'D1','choice':2})+'\n')
            self.assertEqual(component_store.current(root,1,'Elenda'),{})

    def test_atomic_write_keeps_prior_file_when_flush_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'record.json';write(path,{'before':'é'})
            with patch('edh_gauntlet.runtime_store.os.fsync',side_effect=OSError('disk error')):
                with self.assertRaises(OSError):write(path,{'after':list(range(100))})
            self.assertEqual(json.loads(path.read_text()),{'before':'é'})


class TimingTests(unittest.TestCase):
    def test_fast_writes_preserve_event_count_order_and_retention(self):
        from edh_gauntlet.host_telemetry import Timing
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'timing.json';timing=Timing(path,limit=3,flush_interval=60)
            self.addCleanup(timing.close)
            for index in range(5):timing.record('test',index=index)
            timing.flush()
            value=json.loads(path.read_text())
            self.assertEqual(value['total_events'],5)
            self.assertEqual([e['index'] for e in value['retained_events']],[2,3,4])

    def test_phase_logs_duration_without_swallowing_failure(self):
        from edh_gauntlet.host_telemetry import Timing
        with tempfile.TemporaryDirectory() as tmp:
            timing=Timing(Path(tmp)/'timing.json',flush_interval=60)
            self.addCleanup(timing.close)
            with patch('edh_gauntlet.host_telemetry.time.monotonic',side_effect=[10,12]):
                with self.assertRaisesRegex(ValueError,'failure'):
                    with timing.measure('submission'):raise ValueError('failure')
            timing.flush()
            value=json.loads((Path(tmp)/'timing.json').read_text())['retained_events'][0]
            self.assertEqual(value['seconds'],2);self.assertEqual(value['phase'],'submission')


class TelemetryBatchTests(unittest.TestCase):
    def test_batch_and_close_preserve_all_retained_events(self):
        from edh_gauntlet.host_telemetry import Timing
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'timing.json';timing=Timing(path,limit=128,flush_interval=60)
            with patch('edh_gauntlet.host_telemetry.write',wraps=write) as writes:
                for i in range(100):timing.record('test',index=i)
                self.assertEqual(writes.call_count,0)
                timing.flush();self.assertEqual(writes.call_count,1)
                timing.flush();self.assertEqual(writes.call_count,1)
                timing.record('last');timing.close()
                self.assertEqual(writes.call_count,2)
            value=json.loads(path.read_text())
            self.assertEqual(value['total_events'],101)
            self.assertEqual([x['index'] for x in value['retained_events'][:-1]],list(range(100)))
            self.assertFalse(timing.worker.is_alive())

    def test_slow_flush_does_not_hold_up_event_receipt(self):
        import threading
        from edh_gauntlet.host_telemetry import Timing
        with tempfile.TemporaryDirectory() as tmp:
            timing=Timing(Path(tmp)/'timing.json',flush_interval=60)
            timing.record('first');entered=threading.Event();release=threading.Event()
            def slow_write(path,value):
                entered.set();release.wait(2);write(path,value)
            with patch('edh_gauntlet.host_telemetry.write',side_effect=slow_write):
                worker=threading.Thread(target=timing.flush);worker.start()
                self.assertTrue(entered.wait(1))
                receipt=threading.Thread(target=lambda:timing.record('second'));receipt.start();receipt.join(.5)
                try:self.assertFalse(receipt.is_alive())
                finally:release.set();worker.join();receipt.join()
            timing.close()
            self.assertEqual(json.loads(timing.path.read_text())['total_events'],2)


class ReservationReplayTests(unittest.TestCase):
    def test_shared_replay_projects_each_actor_and_invalidates_changed_prefix(self):
        from contextlib import ExitStack
        from unittest.mock import Mock
        from edh_gauntlet import campaign
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root=Path(tmp);state={'jobs':{}};cache={};runtime=object()
            stack.enter_context(patch.object(campaign,'load_manifest',return_value={}))
            config=stack.enter_context(patch.object(campaign,'_game_config_with_bound_surface',return_value={'game':1}))
            replay=stack.enter_context(patch.object(campaign,'_run',return_value={'state':'need_decision','game':runtime}))
            snapshot=stack.enter_context(patch.object(planner_runtime,'_snapshot',side_effect=lambda r,g,a,*args:a))
            stack.enter_context(patch.object(pilot_handoff,'session_descriptor',side_effect=lambda r,g,a,rows:{'actor':a,'rows':rows}))
            stack.enter_context(patch.object(planner_runtime,'get',return_value={}))
            stack.enter_context(patch.object(planner_runtime,'_compatible',return_value=True))
            rows=[{'choice':1}]
            first=planner_runtime._refresh_reservation(root,1,state,'A',rows,cache)
            second=planner_runtime._refresh_reservation(root,1,state,'B',rows,cache)
            self.assertTrue(first['replayed']);self.assertTrue(second['shared_replay'])
            self.assertEqual(replay.call_count,1)
            self.assertEqual([call.args[2] for call in snapshot.call_args_list],['A','B'])
            planner_runtime._refresh_reservation(root,1,state,'C',[{'choice':2}],cache)
            self.assertEqual(replay.call_count,2)
            config.return_value={'game':1,'changed':True}
            planner_runtime._refresh_reservation(root,1,state,'D',[{'choice':2}],cache)
            self.assertEqual(replay.call_count,3)
            self.assertEqual(len(cache),1)


class TelemetryWorkerTests(unittest.TestCase):
    def test_periodic_flush_and_failure_are_observable(self):
        import threading
        from edh_gauntlet.host_telemetry import Timing
        with tempfile.TemporaryDirectory() as tmp:
            published=threading.Event()
            def publish(path,value):write(path,value);published.set()
            with patch('edh_gauntlet.host_telemetry.write',side_effect=publish):
                timing=Timing(Path(tmp)/'timing.json',flush_interval=.01)
                try:
                    timing.record('test')
                    self.assertTrue(published.wait(2))
                    self.assertEqual(json.loads(timing.path.read_text())['total_events'],1)
                finally:timing.close()
            with patch('edh_gauntlet.host_telemetry.write',side_effect=OSError('disk error')):
                timing=Timing(Path(tmp)/'failure.json',flush_interval=.01)
                timing.record('test');timing.worker.join(2)
                self.assertFalse(timing.worker.is_alive())
                with self.assertRaisesRegex(OSError,'disk error'):timing.record('next')
                with self.assertRaisesRegex(OSError,'disk error'):timing.close()
