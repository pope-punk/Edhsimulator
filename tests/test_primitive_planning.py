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

    def test_kept_hand_queues_only_its_own_strategist(self):
        self.assertIsNotNone(planning.claim(self.game,'Omo',planning.LONG))
        self.assertIsNone(planning.claim(self.game,'Elenda',planning.LONG))
        self.assertIsNone(planning.claim(self.game,'Omo',planning.SHORT))

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
        self.assertEqual([],job['rationales']);self.assertNotIn('plans',job)
        for card in self.game.store.packet('Omo')['hand']:self.assertNotIn(card['ref']['card_id'],str(job))
        self.assertTrue(job['requires_public_post'])
        with self.assertRaises(RulesViolation):planning.publish(self.game,'Omo',planning.DIPLOMAT,job['job_id'],'message',{'authorized_ids':[]})
        planning.publish(self.game,'Omo',planning.DIPLOMAT,job['job_id'],'message',{'authorized_ids':['hello']})
        self.assertEqual(1,len(self.game.state()['messages']))
        self.assertIsNotNone(planning.claim(self.game,'Elenda',planning.DIPLOMAT))

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
