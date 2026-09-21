"""Frozen role jobs, stage ownership and public-only diplomacy."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet import primitive_planning as planning
from edh_gauntlet.rules_state import RulesViolation


class PrimitivePlanningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.game=PrimitiveCampaign._create(Path(self.tmp.name)/'game',seed=93,starting_player='Omo')
        self.addCleanup(self.game.close)
        q=self.game.kernel.pending_choice
        self.game.submit('Omo','keep',{'kind':'answer','revision':self.game.kernel.revision,'request_id':q.request_id,'indexes':[0]},rationale='Synthetic keep for planning validation.')

    def goal(self):
        return {'long_term_plan':'Develop resources for this offline fixture.',
                'diplomacy':[{'id':'hello','text':'A synthetic authorized message.','expires_turn':20}]}

    def publish_goal(self):
        job=planning.claim(self.game,'Omo',planning.LONG)
        planning.publish(self.game,'Omo',planning.LONG,job['job_id'],'long_term',self.goal())
        return job

    def test_kept_hand_queues_both_own_planners(self):
        self.assertIsNotNone(planning.claim(self.game,'Omo',planning.LONG))
        self.assertIsNone(planning.claim(self.game,'Elenda',planning.LONG))
        self.assertIsNotNone(planning.claim(self.game,'Omo',planning.SHORT))

    def test_frozen_claim_and_queued_wakeup_survive_publication(self):
        job=planning.claim(self.game,'Omo',planning.LONG)
        with self.game.transaction() as state:planning.queue(state,'Omo',planning.LONG,'later_alarm')
        self.assertEqual(job,planning.claim(self.game,'Omo',planning.LONG))
        planning.publish(self.game,'Omo',planning.LONG,job['job_id'],'long_term',self.goal())
        replacement=planning.claim(self.game,'Omo',planning.LONG)
        self.assertNotEqual(job['job_id'],replacement['job_id'])
        self.assertEqual(['later_alarm'],replacement['reasons'])

    def test_accepted_stage_is_idempotent_and_cannot_be_replaced(self):
        job=planning.claim(self.game,'Omo',planning.LONG);value=self.goal()
        first=planning.publish(self.game,'Omo',planning.LONG,job['job_id'],'long_term',value)
        self.assertEqual(first,planning.publish(self.game,'Omo',planning.LONG,job['job_id'],'long_term',value))
        with self.assertRaises(RulesViolation):planning.publish(self.game,'Omo',planning.LONG,job['job_id'],'long_term',{**value,'long_term_plan':'Changed'})
        self.assertIsNotNone(planning.claim(self.game,'Omo',planning.SHORT))
        self.assertIsNotNone(planning.claim(self.game,'Omo',planning.DIPLOMAT))

    def test_tactical_stages_cannot_be_skipped_and_invalid_goal_does_not_block_actions(self):
        self.publish_goal();job=planning.claim(self.game,'Omo',planning.SHORT)
        actions={'action_sequence':[],'phase_coverage':{p:{'status':'reassess','reason':'Offline test boundary'} for p in planning.PHASES}}
        with self.assertRaises(RulesViolation):planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'actions',actions)
        value={'short_term_plan':'Retain this fixture hand.','continuity':'The fixture hand was kept.',
               'long_term_validity':'invalid','long_term_invalid_reason':'Test explicit strategic reconsideration.'}
        result=planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'short_term',value)
        self.assertEqual('actions',result['next'])
        self.assertIsNotNone(planning.claim(self.game,'Omo',planning.LONG))
        result=planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'actions',actions)
        self.assertIsNone(result['next'])

    def test_diplomat_never_receives_private_hand_seed_or_rationales(self):
        self.publish_goal();job=planning.claim(self.game,'Omo',planning.DIPLOMAT)
        self.assertNotIn('hand',job['board']);self.assertNotIn('seed',job)
        self.assertEqual([],job['rationales']);self.assertEqual({'long_term'},set(job['plans']))
        for card in self.game.store.packet('Omo')['hand']:self.assertNotIn(card['ref']['card_id'],str(job))
        self.assertTrue(job['requires_public_post'])
        with self.assertRaises(RulesViolation):planning.publish(self.game,'Omo',planning.DIPLOMAT,job['job_id'],'message',{'authorized_ids':[],'urgent_material_plan_change':{},'private_assessments':{}})
        planning.publish(self.game,'Omo',planning.DIPLOMAT,job['job_id'],'message',{'authorized_ids':['hello'],'urgent_material_plan_change':{'hello':0},'private_assessments':{'hello':{'explanation':'Routine fixture speech.','recommended_action':'Continue the current plan.','truthfulness':'truthful'}}})
        self.assertEqual(1,len(self.game.state()['messages']))
        self.assertIsNone(planning.claim(self.game,'Elenda',planning.DIPLOMAT)) # Generic talk creates no reply inference.

    def test_pause_blocks_new_jobs_and_publications(self):
        job=planning.claim(self.game,'Omo',planning.LONG);self.game.pause('operator')
        with self.assertRaises(RulesViolation):planning.claim(self.game,'Omo',planning.LONG)
        with self.assertRaises(RulesViolation):planning.publish(self.game,'Omo',planning.LONG,job['job_id'],'long_term',self.goal())

    def test_equivalent_goal_retains_version_and_renews_diplomatic_obligation(self):
        first=self.publish_goal();before=self.game.state()['actors']['Omo']['plans']['long_term']['id']
        with self.game.transaction() as state:planning.queue(state,'Omo',planning.LONG,'review_keep')
        job=planning.claim(self.game,'Omo',planning.LONG)
        value=self.goal();value['diplomacy'][0]['text']='Renewed synthetic public authorization.'
        planning.publish(self.game,'Omo',planning.LONG,job['job_id'],'long_term',value)
        seat=self.game.state()['actors']['Omo']
        self.assertEqual(before,seat['plans']['long_term']['id'])
        self.assertIn('strategic_publication:'+job['job_id'],seat['jobs'][planning.DIPLOMAT]['reasons'])

    def test_late_invalid_assessment_cannot_invalidate_a_replacement_goal(self):
        self.publish_goal();tactical=planning.claim(self.game,'Omo',planning.SHORT)
        with self.game.transaction() as state:planning.queue(state,'Omo',planning.LONG,'independent_review')
        strategic=planning.claim(self.game,'Omo',planning.LONG)
        planning.publish(self.game,'Omo',planning.LONG,strategic['job_id'],'long_term',
                         {**self.goal(),'long_term_plan':'A replacement fixture goal.'})
        planning.publish(self.game,'Omo',planning.SHORT,tactical['job_id'],'short_term',
            {'short_term_plan':'Interim fixture line.','continuity':'Reviewed the original goal.',
             'long_term_validity':'invalid','long_term_invalid_reason':'The original goal is obsolete.'})
        seat=self.game.state()['actors']['Omo']
        self.assertIsNone(seat.get('invalid_goal'));self.assertNotIn(planning.LONG,seat['jobs'])
        self.assertNotEqual(seat['plans']['long_term']['id'],seat['plans']['short_term']['assessed_goal'])

    def test_invalid_current_goal_cannot_be_cleared_by_identical_prose(self):
        self.publish_goal();job=planning.claim(self.game,'Omo',planning.SHORT)
        planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'short_term',
            {'short_term_plan':'Interim fixture line.','continuity':'Reviewed the current goal.',
             'long_term_validity':'invalid','long_term_invalid_reason':'The goal is obsolete.'})
        revision=planning.claim(self.game,'Omo',planning.LONG)
        with self.assertRaisesRegex(RulesViolation,'requires revised'):
            planning.publish(self.game,'Omo',planning.LONG,revision['job_id'],'long_term',self.goal())
        self.assertIsNotNone(self.game.state()['actors']['Omo']['invalid_goal'])

    def test_initial_tactical_job_does_not_wait_for_opening_goal(self):
        with self.game.transaction() as state:planning.queue(state,'Omo',planning.SHORT,'pre_turn:fixture')
        self.assertIsNotNone(planning.claim(self.game,'Omo',planning.SHORT))
        self.publish_goal()
        self.assertIsNotNone(planning.claim(self.game,'Omo',planning.SHORT))

    def test_own_maintenance_waits_until_cleanup_has_finished(self):
        from types import SimpleNamespace
        state={'actors':{'A':{'jobs':{},'next_job':0},'B':{'jobs':{},'next_job':0}}}
        events=[{'index':1,'kind':'step_began','step':'cleanup','active':'A'}]
        campaign=SimpleNamespace(kernel=SimpleNamespace(semantic_events=events))
        planning.observe(campaign,state)
        self.assertFalse(state['actors']['A']['jobs'])
        events.append({'index':2,'kind':'turn_began','active':'B'})
        planning.observe(campaign,state)
        self.assertEqual(['own_turn_complete:2'],state['actors']['A']['jobs'][planning.SHORT]['reasons'])

    def test_invalidation_after_strategic_claim_is_carried_into_a_fresh_review(self):
        self.publish_goal()
        with self.game.transaction() as state:planning.queue(state,'Omo',planning.LONG,'independent_review')
        older=planning.claim(self.game,'Omo',planning.LONG)
        tactical=planning.claim(self.game,'Omo',planning.SHORT)
        planning.publish(self.game,'Omo',planning.SHORT,tactical['job_id'],'short_term',
            {'short_term_plan':'Interim fixture.','continuity':'New facts appeared after the strategic claim.',
             'long_term_validity':'invalid','long_term_invalid_reason':'A milestone is already complete.'})
        planning.publish(self.game,'Omo',planning.LONG,older['job_id'],'long_term',self.goal())
        next_review=planning.claim(self.game,'Omo',planning.LONG)
        self.assertIsNotNone(next_review['invalid_goal'])
        self.assertEqual('A milestone is already complete.',next_review['invalid_goal']['reason'])

    def test_repeated_invalidation_already_covered_by_a_claim_does_not_queue_another(self):
        self.publish_goal();goal_id=self.game.state()['actors']['Omo']['plans']['long_term']['id']
        with self.game.transaction() as state:
            state['actors']['Omo']['invalid_goal']={'goal_id':goal_id,'reason':'Fixture invalidation.'}
            planning.queue(state,'Omo',planning.LONG,'invalid_goal:'+goal_id)
        planning.claim(self.game,'Omo',planning.LONG)
        with self.game.transaction() as state:planning.queue(state,'Omo',planning.LONG,'invalid_goal:'+goal_id)
        self.assertEqual([],self.game.state()['actors']['Omo']['jobs'][planning.LONG]['queued'])

    def test_planner_history_keeps_nonpass_prose_and_excludes_passes(self):
        with self.game.transaction():
            self.game.record('Omo','rationale',{'rationale':'Routine pass omitted.','command':{'kind':'pass'}})
            self.game.record('Omo','rationale',{'rationale':'Complete resource-development reason.','command':{'kind':'activate'}})
        job=planning.claim(self.game,'Omo',planning.LONG)
        self.assertNotIn('Routine pass omitted.',str(job['rationales']))
        self.assertIn('Complete resource-development reason.',str(job['rationales']))
        self.assertIn('Routine pass omitted.',str(self.game.evidence('Omo',kinds=('rationale',))))

    def test_combined_publication_commits_both_stages_and_retries_idempotently(self):
        self.publish_goal();job=planning.claim(self.game,'Omo',planning.SHORT)
        value={'short_term':{'short_term_plan':'Keep the fixture line.','continuity':'Known fixture state.',
                            'long_term_validity':'valid','long_term_invalid_reason':''},
               'actions':{'action_sequence':[],'phase_coverage':{p:{'status':'reassess','reason':'Fixture.'} for p in planning.PHASES}}}
        result=planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'short_term_and_actions',value)
        self.assertIsNone(result['next']);self.assertEqual({'short_term','actions'},set(result['components']))
        count=self.game.store.connection.execute('select count(*) from host_publications').fetchone()[0]
        self.assertEqual(result,planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'short_term_and_actions',value))
        self.assertEqual(count,self.game.store.connection.execute('select count(*) from host_publications').fetchone()[0])
        self.assertEqual(self.game.state()['actors']['Omo']['plans']['short_term']['id'],
                         self.game.state()['actors']['Omo']['plans']['actions']['short_term_id'])

    def test_invalid_combined_actions_roll_back_prose_and_strategic_alarm(self):
        self.publish_goal();job=planning.claim(self.game,'Omo',planning.SHORT);before=self.game.state()
        value={'short_term':{'short_term_plan':'Changed fixture.','continuity':'Fixture.',
                            'long_term_validity':'invalid','long_term_invalid_reason':'Fixture test.'},'actions':{}}
        with self.assertRaises(RulesViolation):planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'short_term_and_actions',value)
        self.assertEqual(before,self.game.state())

    def test_opening_tactics_publish_before_goal_and_receive_followup(self):
        short=planning.claim(self.game,'Omo',planning.SHORT)
        self.assertIsNotNone(short)
        self.assertNotIn('long_term',short['plans'])
        self.assertIn('standing',short)
        planning.publish(self.game,'Omo',planning.SHORT,short['job_id'],'short_term',{
            'short_term_plan':'Develop the kept hand.','continuity':'Opening plan from standing strategy.',
            'long_term_validity':'pending','long_term_invalid_reason':''})
        long=planning.claim(self.game,'Omo',planning.LONG)
        planning.publish(self.game,'Omo',planning.LONG,long['job_id'],'long_term',self.goal())
        state=self.game.state()
        self.assertIn('short_term',state['actors']['Omo']['plans'])
        self.assertTrue(any(r.startswith('strategic_publication:') for r in state['actors']['Omo']['jobs'][planning.SHORT]['queued']))

    def test_opposite_gate_actions_first_prose_keeps_proposal_identity(self):
        with self.game.transaction() as state:planning.queue(state,'Omo',planning.SHORT,'pre_turn:fixture')
        job=planning.claim(self.game,'Omo',planning.SHORT)
        self.assertEqual(['actions','short_term'],job['publication_order'])
        prose={'short_term_plan':'Develop from standing.','continuity':'Fixture.',
               'long_term_validity':'pending','long_term_invalid_reason':''}
        proposed={'action_sequence':[],'phase_coverage':{p:{'status':'reassess','reason':'Fixture.'} for p in planning.PHASES}}
        with self.assertRaises(RulesViolation):planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'short_term',prose)
        first=planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'actions',proposed)
        self.assertEqual('short_term',first['next'])
        action=self.game.state()['actors']['Omo']['plans']['actions']
        self.assertIsNone(action['short_term_id'])
        with self.game.transaction() as state:planning.queue(state,'Omo',planning.SHORT,'own_turn_complete:later')
        self.assertEqual('short_term',planning.claim(self.game,'Omo',planning.SHORT)['stage'])
        last=planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'short_term',prose)
        self.assertIsNone(last['next'])
        self.assertEqual(action,self.game.state()['actors']['Omo']['plans']['actions'])
        self.assertEqual(first,planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'actions',proposed))
        self.assertEqual(['short_term','actions'],planning.claim(self.game,'Omo',planning.SHORT)['publication_order'])

    def test_queued_opposite_gate_cannot_reorder_started_own_end_job(self):
        with self.game.transaction() as state:planning.queue(state,'Omo',planning.SHORT,'own_turn_complete:fixture')
        job=planning.claim(self.game,'Omo',planning.SHORT)
        with self.game.transaction() as state:planning.queue(state,'Omo',planning.SHORT,'pre_turn:later')
        self.assertEqual(job,planning.claim(self.game,'Omo',planning.SHORT))
        self.assertEqual(['short_term','actions'],job['publication_order'])

    def test_combined_opposite_publication_is_atomic_and_retry_safe(self):
        with self.game.transaction() as state:planning.queue(state,'Omo',planning.SHORT,'pre_turn:fixture')
        job=planning.claim(self.game,'Omo',planning.SHORT);before=self.game.state()
        proposed={'action_sequence':[],'phase_coverage':{p:{'status':'reassess','reason':'Fixture.'} for p in planning.PHASES}}
        with self.assertRaises(RulesViolation):planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'short_term_and_actions',{'actions':proposed,'short_term':{}})
        self.assertEqual(before,self.game.state())
        value={'actions':proposed,'short_term':{'short_term_plan':'Develop from standing.','continuity':'Fixture.',
               'long_term_validity':'pending','long_term_invalid_reason':''}}
        receipt=planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'short_term_and_actions',value)
        self.assertEqual(receipt,planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'short_term_and_actions',value))
        self.assertEqual(receipt['components']['actions'],self.game.state()['actors']['Omo']['plans']['actions']['id'])
        self.assertNotIn(planning.SHORT,self.game.state()['actors']['Omo']['jobs'])

class StrategicReviewTests(PrimitivePlanningTests):
    def review(self,job):
        return planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'short_term',
            {'short_term_plan':'Continue the independently selected fixture line.','continuity':'A named strategic piece changed.',
             'long_term_validity':'review','long_term_invalid_reason':'Named engine piece became available; reassess the preferred route.'})

    def test_review_queues_goal_with_reason_without_blocking_actions(self):
        self.publish_goal();job=planning.claim(self.game,'Omo',planning.SHORT)
        with self.assertRaises(RulesViolation):
            planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'short_term',
                {'short_term_plan':'Interim plan.','continuity':'Fixture.',
                 'long_term_validity':'review','long_term_invalid_reason':''})
        result=self.review(job);self.assertEqual('actions',result['next'])
        strategic=planning.claim(self.game,'Omo',planning.LONG)
        self.assertIn('engine piece',strategic['review_goal']['reason'])
        with self.game.transaction() as state:planning.queue(state,'Omo',planning.LONG,'review_goal:'+strategic['review_goal']['goal_id'])
        self.assertEqual([],self.game.state()['actors']['Omo']['jobs'][planning.LONG]['queued'])
        self.assertIsNone(self.game.state()['actors']['Omo'].get('invalid_goal'))
        planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'actions',
            {'action_sequence':[],'phase_coverage':{p:{'status':'reassess','reason':'Offline boundary'} for p in planning.PHASES}})
        planning.publish(self.game,'Omo',planning.LONG,strategic['job_id'],'long_term',self.goal())
        self.assertIsNone(self.game.state()['actors']['Omo'].get('review_goal'))

    def test_late_review_does_not_wake_for_replaced_goal(self):
        self.publish_goal();job=planning.claim(self.game,'Omo',planning.SHORT)
        with self.game.transaction() as state:planning.queue(state,'Omo',planning.LONG,'independent')
        newer=planning.claim(self.game,'Omo',planning.LONG)
        planning.publish(self.game,'Omo',planning.LONG,newer['job_id'],'long_term',{**self.goal(),'long_term_plan':'Updated route.'})
        self.review(job)
        self.assertNotIn(planning.LONG,self.game.state()['actors']['Omo']['jobs'])
        self.assertIsNone(self.game.state()['actors']['Omo'].get('review_goal'))

    def test_review_requires_reason_and_fresh_contract(self):
        self.publish_goal();job=planning.claim(self.game,'Omo',planning.SHORT)
        self.game.config.pop('strategic_review')
        with self.assertRaisesRegex(RulesViolation,'strategic assessment'):self.review(job)

    def test_review_and_invalid_do_not_enable_watches(self):
        job=planning.claim(self.game,'Omo',planning.LONG)
        with self.assertRaises(RulesViolation):planning.publish(self.game,'Omo',planning.LONG,job['job_id'],'long_term',{**self.goal(),'watches':[]})

class PlanProseMarginTests(unittest.TestCase):
    setUp=PrimitivePlanningTests.setUp
    goal=PrimitivePlanningTests.goal

    def test_current_publication_preserves_small_prose_overflow_but_rejects_hard_cap(self):
        self.game.config['coordination_document']=1
        job=planning.claim(self.game,'Omo',planning.SHORT)
        value={'short_term_plan':'x'*661,'continuity':'Fixture history.',
               'long_term_validity':'pending','long_term_invalid_reason':''}
        head=self.game.store.committed_head()
        with self.assertRaisesRegex(RulesViolation,'received 661 characters'):
            planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'short_term',value)
        self.assertEqual(0,self.game.state()['actors']['Omo']['jobs'][planning.SHORT]['stage'])
        value['short_term_plan']='x'*601
        planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'short_term',value)
        self.assertEqual(value['short_term_plan'],self.game.state()['actors']['Omo']['plans']['short_term']['value']['short_term_plan'])
        long_job=planning.claim(self.game,'Omo',planning.LONG)
        goal={**self.goal(),'long_term_plan':'y'*1310}
        planning.publish(self.game,'Omo',planning.LONG,long_job['job_id'],'long_term',goal)
        self.assertEqual(goal['long_term_plan'],self.game.state()['actors']['Omo']['plans']['long_term']['value']['long_term_plan'])
        self.assertEqual(head,self.game.store.committed_head())

    def test_legacy_publication_keeps_its_original_strict_bound(self):
        self.game.config.pop('coordination_document',None)
        job=planning.claim(self.game,'Omo',planning.SHORT)
        value={'short_term_plan':'x'*601,'continuity':'Fixture history.',
               'long_term_validity':'pending','long_term_invalid_reason':''}
        with self.assertRaisesRegex(RulesViolation,'at most 600'):
            planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'short_term',value)
