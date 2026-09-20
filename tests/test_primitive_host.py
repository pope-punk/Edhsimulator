"""Transport fixtures never invoke a model or make choices in a real game."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet.primitive_host import PrimitiveRunner
from edh_gauntlet import primitive_planning as planning
from edh_gauntlet.runtime_store import read
from edh_gauntlet.rules_state import RulesViolation


class FakeServer:
    def __init__(self):
        self.calls=[];self.replies=[];self.usage={};self.closed=False
    def call(self,method,params):
        self.calls.append((method,params))
        if method=='thread/start':return {'thread':{'id':f'thread-{len(self.calls)}'}}
        if method=='turn/start':return {'turn':{'id':f'turn-{len(self.calls)}'}}
        return {}
    def send(self,value):self.calls.append((value['method'],value['params']))
    def respond(self,request,value,success=True):self.replies.append((request,value,success))
    def respond_text(self,request,text,success=True):self.replies.append((request,{'pilot_document':text},success))
    def close(self):self.closed=True


class PrimitiveHostTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.game=PrimitiveCampaign._create(Path(self.temp.name)/'game',seed=93,starting_player='Omo')
        self.game.config.pop('coordination_document',None)
        self.game.config.pop('pilot_document',None)  # Legacy packet delivery remains supported.
        self.addCleanup(self.game.close)
        self.server=FakeServer();self.runner=PrimitiveRunner(self.game,self.server)
        self.addCleanup(self.runner.timing.close)

    def tool(self,thread,name,args,request='call-1'):
        return {'id':request,'method':'item/tool/call','params':{'threadId':thread,
            'turnId':self.runner.running[thread],'callId':request,'tool':name,'arguments':args}}

    def test_batch_wrapper_rejection_explains_correction_without_acceptance(self):
        self.runner.pump(); thread=self.runner.lanes[('Omo','decider')]
        before=self.game.store.committed_head()
        self.runner.handle(self.tool(thread,'edh_act',{
            'batch':{'approve_ids':[],'reject_ids':[]},'rationale':'Extra wrapper field'}))
        value=self.server.replies[-1][1]
        self.assertTrue(value['rejected'])
        self.assertIn('Remove top-level rationale',value['reason'])
        self.assertEqual(before,self.game.store.committed_head())

    def test_role_contexts_have_independent_lanes_and_fast_tactical_model(self):
        threads=set()
        for actor in self.game.kernel.state.players:
            for role in ('decider',planning.LONG,planning.SHORT,planning.DIPLOMAT):
                threads.add(self.runner.context(actor,role))
        self.assertEqual(16,len(threads))
        starts=[p for m,p in self.server.calls if m=='thread/start']
        self.assertTrue(all(p['approvalPolicy']=='never' and not p['selectedCapabilityRoots'] for p in starts))
        fast=[p for p in starts if p.get('serviceTier')=='fast']
        self.assertEqual(4,len(fast));self.assertTrue(all(p['model']=='gpt-5.6-sol' for p in fast))
        self.assertTrue(all(not p['config']['features']['shell_tool'] for p in starts))

    def test_waiting_tool_returns_durable_receipt_and_does_not_block_next_seat(self):
        self.runner.pump();thread=self.runner.lanes[('Omo','decider')]
        q=self.game.kernel.pending_choice
        self.runner.handle(self.tool(thread,'edh_act',{'command':{'kind':'answer','request_id':q.request_id,'indexes':[0]},
            'rationale':'Keep this synthetic hand.','scheduler':{'mode':'hold_full_control'}}))
        self.assertEqual(1,self.game.store.generation)
        self.assertIn(thread,self.runner.waiting)
        self.runner.pump()
        self.assertEqual(4,len(self.runner.running)) # Both deciders and both opening planners.
        self.assertEqual(1,len(self.runner.waiting))
        self.runner.warm_seconds=0;self.runner.pump()
        parked=[v for _,v,_ in self.server.replies if v.get('state')=='parked']
        self.assertEqual(1,len(parked));self.assertIn('commit',parked[0]['previous_receipt'])

    def test_automatic_chunk_boundary_does_not_claim_a_decider_input(self):
        with patch('edh_gauntlet.primitive_host.actions.automatic',return_value=True) as automatic:
            self.runner.pump()
        self.assertEqual(16,automatic.call_count)
        self.assertFalse(self.runner.done)
        self.assertIsNone(self.game.state()['claim'])
        self.assertNotIn(('Omo','decider'),self.runner.lanes)
        with patch('edh_gauntlet.primitive_host.actions.automatic',return_value=False):
            self.runner.pump()
        self.assertIn(('Omo','decider'),self.runner.lanes)

    def test_automatic_limit_prevents_further_model_dispatch(self):
        self.runner.max_decisions=1
        def automatic(game):
            q=game.kernel.pending_choice
            game.submit(q.actor,'fixture',{'kind':'answer','revision':game.kernel.revision,
                'request_id':q.request_id,'indexes':[0]},rationale='Synthetic fixture.')
            return True
        with patch('edh_gauntlet.primitive_host.actions.automatic',side_effect=automatic):self.runner.pump()
        self.assertTrue(self.runner.done);self.assertFalse(self.server.calls)

    def test_shutdown_preserves_user_pause_and_seals_reported_blocker(self):
        self.game.rules_blocker('Omo','Synthetic unsupported interaction.')
        self.game.pause('user pause')
        before=self.game.store.committed_head();self.runner.run()
        self.assertEqual('user pause',self.game.state()['paused']['reason'])
        self.assertEqual(before,self.game.store.committed_head())
        terminal=read(self.game.root/'game_01/terminal_result.json')
        self.assertEqual('rules_review',terminal['tag'])
        self.assertEqual('skipped_by_configuration',read(self.game.root/'game_01/postgame_learning/skipped.json')['status'])
        self.assertFalse(read(self.runner.directory/'process.json')['active'])

    def test_duplicate_transport_call_stops_without_replaying(self):
        self.runner.pump();thread=self.runner.lanes[('Omo','decider')]
        message=self.tool(thread,'edh_inspect',{'queries':[{'kind':'state'}]})
        self.runner.handle(message)
        with self.assertRaisesRegex(RuntimeError,'Repeated transport'):self.runner.handle(message)
        self.assertEqual(0,self.game.store.generation)

    def test_shutdown_does_not_claim_unloaded_when_a_transport_child_survives(self):
        self.runner.done=True
        self.runner.process_evidence={'host_identity':None,
            'transport_identity':{'pid':123,'boot_id':'fixture','start_ticks':1},'transport_session':123}
        with patch('edh_gauntlet.primitive_recovery.verify_exited',side_effect=RulesViolation('child survives')):
            with self.assertRaisesRegex(RulesViolation,'child survives'):self.runner.run()
        marker=read(self.runner.directory/'process.json')
        self.assertTrue(marker['active']);self.assertFalse(marker['contexts_unloaded'])
        self.assertEqual(0,self.game.store.generation)

    def test_unexpected_approval_request_stops(self):
        with self.assertRaisesRegex(RuntimeError,'Unexpected approval'):
            self.runner.handle({'id':99,'method':'item/commandExecution/requestApproval','params':{}})

    def test_unchanged_status_is_not_rewritten(self):
        self.runner.pump()
        with patch('edh_gauntlet.primitive_host.write',wraps=__import__('edh_gauntlet.runtime_store',fromlist=['write']).write) as writer:
            self.runner.pump();self.runner.pump()
        self.assertFalse(writer.called)

    def failed_turn(self,thread):
        return {'method':'turn/completed','params':{'threadId':thread,'turn':{
            'id':self.runner.running[thread],'status':'failed','error':{'codexErrorInfo':'ServerOverloaded'}}}}

    def test_capacity_retry_cools_down_the_model_that_actually_failed(self):
        self.runner.pump();thread=self.runner.lanes[('Omo','decider')]
        used=self.runner.turn_models[thread]
        self.runner.handle(self.failed_turn(thread))
        self.assertGreater(self.runner.routing.delay(used),0)
        self.assertEqual(1,self.runner.retries[thread])
        self.assertEqual(0,self.game.store.generation)

    def test_capacity_failure_after_any_tool_is_not_retried(self):
        self.runner.pump();thread=self.runner.lanes[('Omo','decider')]
        self.runner.handle(self.tool(thread,'edh_inspect',{'queries':[{'kind':'state'}]}))
        with self.assertRaisesRegex(RuntimeError,'non-retryable'):
            self.runner.handle(self.failed_turn(thread))
        self.assertNotIn(thread,self.runner.retries)

    def test_fenced_restart_preserves_logical_identity_and_exact_prefix(self):
        self.runner.pump();identities=self.game.state()['registrations']
        before=self.game.store.committed_head();self.runner.done=True;self.runner.run()
        replacement=PrimitiveRunner(self.game,FakeServer(),resume_fenced=True)
        self.addCleanup(replacement.timing.close)
        self.assertEqual(before,self.game.store.committed_head())
        self.assertIsNone(self.game.state()['paused'])
        replacement.context('Omo','decider')
        self.assertEqual(identities['Omo::decider']['logical_id'],self.game.state()['registrations']['Omo::decider']['logical_id'])

    def test_fenced_restart_rejects_changed_prefix_or_operator_pause(self):
        self.runner.pump();self.runner.done=True;self.runner.run()
        self.game.pause('operator requested pause')
        with self.assertRaisesRegex(RulesViolation,'operator pause'):
            PrimitiveRunner(self.game,FakeServer(),resume_fenced=True)

    def test_fresh_memory_does_not_repeat_rationales_already_in_the_packet(self):
        with self.game.transaction():
            self.game.record('Omo','rationale',{'rationale':'Retain this complete fixture explanation.','command':{'kind':'cast'}})
            self.game.record('Omo','rationale',{'rationale':'Do not restore this pass.','command':{'kind':'pass'}})
            self.game.record('Elenda','rationale',{'rationale':'Another seat private reason.','command':{'kind':'pass'}})
        rows=self.game.evidence('Omo',kinds=('rationale',))
        self.assertEqual({},self.runner.memory('Omo',planning.LONG,{'rationales':rows}))
        restored=self.runner.memory('Omo',planning.LONG,{'rationales':[]})
        self.assertIn('Retain this complete fixture explanation.',str(restored))
        self.assertNotIn('Another seat private reason.',str(restored))
        self.assertNotIn('Do not restore this pass.',str(restored))
        self.assertEqual({},self.runner.memory('Omo','decider',{}))

    def test_waiting_context_parks_at_checkpoint_threshold_before_another_input(self):
        self.runner.pump();thread=self.runner.lanes[('Omo','decider')]
        q=self.game.kernel.pending_choice
        self.runner.handle(self.tool(thread,'edh_act',{'command':{'kind':'answer','request_id':q.request_id,'indexes':[0]},
            'rationale':'Keep this synthetic hand.','scheduler':{'mode':'hold_full_control'}}))
        self.server.usage[thread]={'last':{'inputTokens':64000},'first':{'inputTokens':100}}
        self.runner.pump()
        self.assertNotIn(thread,self.runner.waiting)
        self.assertTrue(any(value.get('state')=='parked' for _,value,_ in self.server.replies))

    def test_large_next_decision_parks_before_full_delivery_without_replaying(self):
        import json
        self.runner.pump();thread=self.runner.lanes[('Omo','decider')]
        previous=self.runner.inputs[thread];baseline=self.runner.deliveries[thread]
        q=self.game.kernel.pending_choice
        self.runner.handle(self.tool(thread,'edh_act',{'command':{'kind':'answer','request_id':q.request_id,'indexes':[1]},
            'rationale':'Synthetic mulligan to test a consecutive same-seat choice.','scheduler':{'mode':'hold_full_control'}}))
        while self.game.next_action()['actor']!='Omo':
            q=self.game.kernel.pending_choice
            self.game.submit(q.actor,'fixture-keep:'+q.request_id,{'kind':'answer',
                'revision':self.game.kernel.revision,'request_id':q.request_id,'indexes':[0]},rationale='Synthetic opposing keep.')
        committed=self.game.store.committed_head()
        with self.game.transaction() as state:state['actors']['Omo']['plans']['large']={'id':'fixture','value':'x'*100000}
        self.runner.pump()
        self.assertEqual('parked',self.server.replies[-1][1]['state'])
        self.assertEqual(previous,self.runner.inputs[thread]);self.assertEqual(baseline,self.runner.deliveries[thread])
        self.assertEqual(committed,self.game.store.committed_head())
        self.runner.handle({'method':'turn/completed','params':{'threadId':thread,
            'turn':{'id':self.runner.running[thread],'status':'completed'}}})
        self.runner.pump()
        turns=[p for m,p in self.server.calls if m=='turn/start' and p['threadId']==thread]
        packet=json.loads(turns[-1]['input'][0]['text'])
        self.assertEqual('x'*100000,packet['plans']['large']['value'])
        self.assertEqual(self.game.kernel.pending_choice.request_id,packet['current_decision']['choice']['request_id'])
        self.assertEqual(committed,self.game.store.committed_head());self.assertFalse(self.runner.unanswered)

    def test_inspection_is_exposed_only_to_planners_and_denied_to_other_roles(self):
        from edh_gauntlet.primitive_host import schemas,instructions
        for role in ('decider',planning.DIPLOMAT,planning.LONG,planning.SHORT):
            names={t['name'] for t in schemas(role)}
            self.assertEqual(role in (planning.LONG,planning.SHORT),'edh_inspect' in names)
            if role in ('decider',planning.DIPLOMAT):self.assertNotIn('edh_inspect',instructions('Omo',role))
        self.runner.pump();thread=self.runner.lanes[('Omo','decider')]
        before=self.game.store.committed_head()
        with patch('edh_gauntlet.primitive_host.inspect') as inspect:
            self.runner.handle(self.tool(thread,'edh_inspect',{'queries':[{'kind':'state'}]},request='forbidden-inspection'))
            inspect.assert_not_called()
        self.assertFalse(self.server.replies[-1][2]);self.assertEqual(before,self.game.store.committed_head())

    def test_decider_receives_current_visible_rules_without_an_inspection_call(self):
        from edh_gauntlet.primitive_inspection import action_facts
        self.runner.pump();thread=self.runner.lanes[('Omo','decider')];frozen=self.runner.inputs[thread]
        facts=action_facts(frozen);refs={tuple(sorted(o['source'].items())) for o in facts['objects']}
        own=frozen['board']['hand'][0]['ref'];hidden=self.game.store.packet('Elenda')['hand'][0]['ref']
        self.assertIn(tuple(sorted(own.items())),refs)
        self.assertNotIn(tuple(sorted(hidden.items())),refs)
        self.assertTrue(facts['rules'])
        for obj in facts['objects']:self.assertIn(obj['rules_id'],facts['rules'])
        import json
        sent=[p for m,p in self.server.calls if m=='turn/start'][-1]
        self.assertIn('action_facts',json.dumps(sent))

    def test_planner_scalar_inspections_do_not_crash_telemetry(self):
        thread=self.runner.context('Omo',planning.SHORT)
        self.runner.running[thread]='fixture-turn'
        self.runner.inputs[thread]={}
        values=['precombat_main',3,True,None,[],{'rejected':True}, {'phase':'main'}]
        with patch('edh_gauntlet.primitive_host.inspect',return_value={'results':values}):
            self.runner.handle(self.tool(thread,'edh_inspect',{'queries':[{'kind':'state'}]}))
        self.assertEqual({'results':values},self.server.replies[-1][1])
        self.assertTrue(self.server.replies[-1][2])
        self.assertIsNone(self.game.state()['paused'])

    def test_unfinished_publication_continues_only_current_stage_with_bound(self):
        thread='publication-test';self.runner.threads[thread]=('Omo',planning.SHORT)
        self.runner.inputs[thread]={'job_id':'test-job','stage':'short_term'}
        with self.game.transaction() as state:
            state['actors']['Omo']['jobs'][planning.SHORT]={'id':'test-job','stage':1}
        head=self.game.store.committed_head()
        event={'method':'turn/completed','params':{'threadId':thread,'turn':{'id':'turn','status':'completed'}}}
        for expected in (1,2):
            self.runner.running[thread]='turn';self.runner.handle(event)
            self.assertEqual(expected,self.runner.unfinished_publications[('Omo',planning.SHORT,'test-job',1)])
            self.assertEqual(1,self.game.state()['actors']['Omo']['jobs'][planning.SHORT]['stage'])
            self.assertEqual(head,self.game.store.committed_head())
        self.runner.running[thread]='turn'
        with self.assertRaisesRegex(RuntimeError,'publication stages'):self.runner.handle(event)

    def test_completed_publication_is_not_restarted(self):
        thread='publication-test';self.runner.threads[thread]=('Omo',planning.DIPLOMAT)
        self.runner.inputs[thread]={'job_id':'completed-job','stage':'message'}
        self.runner.running[thread]='turn'
        self.runner.handle({'method':'turn/completed','params':{'threadId':thread,'turn':{'id':'turn','status':'completed'}}})
        self.assertFalse(self.runner.unfinished_publications)
