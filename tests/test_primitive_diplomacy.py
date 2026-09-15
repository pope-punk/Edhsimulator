"""Public egress preserves frozen claims and prevents unsolicited reply cascades."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet import primitive_planning as planning,primitive_actions as actions
from edh_gauntlet.primitive_diplomacy import flush


class PrimitiveDiplomacyTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.game=PrimitiveCampaign._create(Path(self.tmp.name)/'game',seed=93,starting_player='Omo')
        self.addCleanup(lambda:self.game.close())
        q=self.game.kernel.pending_choice
        self.game.submit('Omo','keep',{'kind':'answer','revision':self.game.kernel.revision,
            'request_id':q.request_id,'indexes':[0]},rationale='Synthetic setup keep.')

    def goal(self,**fields):
        job=planning.claim(self.game,'Omo',planning.LONG)
        if job is None:
            with self.game.transaction() as state:planning.queue(state,'Omo',planning.LONG,'fixture_review')
            job=planning.claim(self.game,'Omo',planning.LONG)
        planning.publish(self.game,'Omo',planning.LONG,job['job_id'],'long_term',{
            'long_term_plan':'Keep the fixture strategy.','diplomacy':[
                {'id':'fixture-message','text':'A fixture public message.','expires_turn':20,**fields}]})
        return planning.claim(self.game,'Omo',planning.DIPLOMAT)

    def publish(self,job,urgent=0):
        return planning.publish(self.game,'Omo',planning.DIPLOMAT,job['job_id'],'message',
                                {'authorized_ids':['fixture-message'],'urgent_material_plan_change':{'fixture-message':urgent},'private_assessments':{'fixture-message':{'explanation':'Routine fixture speech.','recommended_action':'Continue the current plan.','truthfulness':'truthful'}}})

    def test_post_waits_for_unclaimed_boundary_without_changing_claim(self):
        job=self.goal();actor=self.game.next_action()['actor'];frozen=actions.claim(self.game,actor)
        self.publish(job)
        self.assertEqual([],self.game.state()['messages'])
        self.assertEqual(frozen,actions.claim(self.game,actor))
        self.assertFalse(flush(self.game))
        q=self.game.kernel.pending_choice
        actions.submit(self.game,actor,frozen['claim_id'],'next-keep',
            {'kind':'answer','request_id':q.request_id,'indexes':[0]},'Synthetic next keep.',{'mode':'hold_full_control'})
        self.assertEqual(1,len(self.game.state()['messages']))
        self.assertFalse(flush(self.game))
        self.assertEqual({},self.game.state()['public_outbox'])

    def test_only_addressed_root_message_wakes_a_diplomat(self):
        job=self.goal(to=['Elenda']);self.publish(job)
        state=self.game.state()
        self.assertIn(planning.DIPLOMAT,state['actors']['Elenda']['jobs'])
        for actor in state['actors']:
            if actor not in {'Omo','Elenda'}:self.assertNotIn(planning.DIPLOMAT,state['actors'][actor]['jobs'])
        first=state['messages'][0]['id']
        with self.game.transaction() as state:state['actors']['Elenda']['jobs'].pop(planning.DIPLOMAT)
        job=self.goal(to=['Elenda'],reply_to=first,text='A fixture reply.')
        self.publish(job)
        self.assertNotIn(planning.DIPLOMAT,self.game.state()['actors']['Elenda']['jobs'])

    def test_superseded_frozen_brief_cannot_post_old_text(self):
        old=self.goal()
        with self.game.transaction() as state:planning.queue(state,'Omo',planning.LONG,'fixture_revision')
        current=planning.claim(self.game,'Omo',planning.LONG)
        planning.publish(self.game,'Omo',planning.LONG,current['job_id'],'long_term',{
            'long_term_plan':'Keep the fixture strategy.','diplomacy':[
                {'id':'new','text':'Replacement authorization.','expires_turn':20}]})
        self.publish(old)
        self.assertEqual([],self.game.state()['messages'])
        replacement=planning.claim(self.game,'Omo',planning.DIPLOMAT)
        self.assertEqual('new',replacement['authorized_messages'][0]['id'])

    def test_repeated_text_is_suppressed_and_mandatory_debt_goes_to_renewal(self):
        job=self.goal();self.publish(job)
        job=self.goal();self.publish(job)
        state=self.game.state()
        self.assertEqual(1,len(state['messages']))
        self.assertTrue(any(r.startswith('renew_unposted_diplomacy:') for r in state['actors']['Omo']['jobs'][planning.LONG]['reasons']))

    def test_outbox_survives_paused_restart_without_posting(self):
        job=self.goal();actions.claim(self.game,self.game.next_action()['actor']);self.publish(job)
        self.game.pause('operator pause');path=self.game.root;self.game.close()
        self.game=PrimitiveCampaign.open(path)
        self.assertIn('Omo',self.game.state()['public_outbox'])
        self.assertFalse(flush(self.game));self.assertEqual([],self.game.state()['messages'])

    def test_authorization_expiring_while_a_claim_is_held_cannot_post(self):
        from unittest.mock import patch
        job=self.goal();actions.claim(self.game,self.game.next_action()['actor']);self.publish(job)
        with self.game.transaction() as state:state['claim']=None
        with patch.object(self.game.kernel.state,'_turn_number',21):self.assertFalse(flush(self.game))
        self.assertEqual([],self.game.state()['messages'])
        self.assertIn(planning.LONG,self.game.state()['actors']['Omo']['jobs'])

    def test_private_authorization_request_cannot_publish_or_start_an_unsettled_goal(self):
        job=self.goal(to=['Elenda']);self.publish(job)
        reply=planning.claim(self.game,'Elenda',planning.DIPLOMAT)
        planning.publish(self.game,'Elenda',planning.DIPLOMAT,reply['job_id'],'message',
                         {'authorized_ids':[],'urgent_material_plan_change':{},'private_assessments':{},'authorization_request':'May I offer a fixture agreement?'})
        self.assertEqual(1,len(self.game.state()['messages']))
        self.assertIn(planning.LONG,self.game.state()['actors']['Elenda']['jobs'])
        self.assertIsNone(planning.claim(self.game,'Elenda',planning.LONG))

    def test_routine_message_preserves_approved_batch_and_snooze(self):
        job=self.goal()
        with self.game.transaction() as state:
            state['actors']['Elenda']['approved']={'id':'approved-line','cursor':2}
            state['actors']['Elenda']['snooze']={'mode':'snooze_table'}
        self.publish(job,0)
        seat=self.game.state()['actors']['Elenda']
        self.assertEqual({'id':'approved-line','cursor':2},seat['approved'])
        self.assertEqual({'mode':'snooze_table'},seat['snooze'])
        self.assertNotIn('batch_interruption',seat)
        self.assertNotIn('urgent_material_plan_change',self.game.state()['messages'][-1])

    def test_urgent_message_cancels_remaining_batch_with_explicit_notice(self):
        job=self.goal()
        actor=self.game.next_action()['actor']
        with self.game.transaction() as state:
            state['actors'][actor]['approved']={'id':'approved-line','cursor':2}
            state['actors'][actor]['snooze']={'mode':'snooze_table'}
        self.publish(job,1)
        seat=self.game.state()['actors'][actor]
        self.assertIsNone(seat['approved']);self.assertIsNone(seat['snooze'])
        packet=actions.claim(self.game,actor)
        self.assertEqual('approved-line',packet['batch_interruption']['approval_id'])
        self.assertEqual(2,packet['batch_interruption']['executed_step_count'])
        self.assertEqual(packet,actions.claim(self.game,actor))
        self.assertNotIn('batch_interruption',self.game.state()['actors'][actor])
        self.assertNotIn('urgent_material_plan_change',self.game.state()['messages'][-1])

    def test_explicit_binary_tag_required_for_every_selected_message(self):
        from edh_gauntlet.rules_state import RulesViolation
        job=self.goal()
        for tags in [None,{}, {'fixture-message':True},{'fixture-message':2},{'fixture-message':0,'extra':1}]:
            with self.assertRaises(RulesViolation):
                planning.publish(self.game,'Omo',planning.DIPLOMAT,job['job_id'],'message',
                    {'authorized_ids':['fixture-message'],'urgent_material_plan_change':tags})
        self.assertFalse(self.game.state()['messages'])

    def test_duplicate_urgent_message_does_not_interrupt(self):
        self.publish(self.goal(),0)
        job=self.goal()
        with self.game.transaction() as state:state['actors']['Elenda']['approved']={'id':'still-approved','cursor':0}
        self.publish(job,1)
        self.assertEqual('still-approved',self.game.state()['actors']['Elenda']['approved']['id'])

    def test_secret_assessment_is_delivered_only_to_own_decider(self):
        self.publish(self.goal(),0)
        state=self.game.state()
        note=state['actors']['Omo']['private_diplomacy'][0]
        self.assertEqual('truthful',note['truthfulness'])
        self.assertEqual('Continue the current plan.',note['recommended_action'])
        for actor,seat in state['actors'].items():
            if actor!='Omo':self.assertNotIn('private_diplomacy',seat)
        self.assertNotIn('private_assessment',state['messages'][0])
        self.assertNotIn('truthfulness',state['messages'][0])

    def test_private_assessment_requires_all_fields(self):
        from edh_gauntlet.rules_state import RulesViolation
        job=self.goal()
        for assessment in [{},{'explanation':'x','recommended_action':'x','truthfulness':'yes'},
                           {'explanation':'','recommended_action':'x','truthfulness':'truthful'}]:
            with self.assertRaises(RulesViolation):
                planning.publish(self.game,'Omo',planning.DIPLOMAT,job['job_id'],'message',{
                    'authorized_ids':['fixture-message'],'urgent_material_plan_change':{'fixture-message':0},
                    'private_assessments':{'fixture-message':assessment}})
