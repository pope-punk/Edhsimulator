"""Synthetic negotiations and cadence never dispatch real model/game actions."""
from pathlib import Path
from tempfile import TemporaryDirectory
from copy import deepcopy
from types import SimpleNamespace
from unittest import TestCase
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet import primitive_planning as planning,primitive_actions as actions
from edh_gauntlet import primitive_negotiation as negotiation
from edh_gauntlet.primitive_cadence import summary,relevant
from edh_gauntlet.rules_state import RulesViolation,Zone


def bounds():
    return {'objective':'Negotiate peaceful development.','disclosure_limits':'Public facts only.',
            'commitment_limits':'Temporary nonaggression only.','allowed_recipients':['Elenda'],
            'hold_authority':{'players':['Elenda'],'scopes':['attack','target_permanents'],'max_turns':2}}


def speech(key='offer',**extra):
    return {'id':key,'text':'I propose a brief truce.','to':['Elenda'],'reply_to':None,
            'urgent_material_plan_change':0,'private_assessment':{'explanation':'Discuss temporary restraint.',
            'recommended_action':'Avoid attacks while we bargain.','truthfulness':'truthful'},**extra}


class WorkflowTests(TestCase):
    def setUp(self):
        d=self.enterContext(TemporaryDirectory());self.game=PrimitiveCampaign._create(Path(d)/'game',seed=93,starting_player='Omo')
        self.addCleanup(self.game.close)
        while self.game.kernel.pending_choice:
            q=self.game.kernel.pending_choice
            self.game.submit(q.actor,'setup:'+str(self.game.store.generation),{'kind':'answer','revision':self.game.kernel.revision,'request_id':q.request_id,'indexes':[0] if q.kind=='mulligan' else []},rationale='Synthetic setup.')
        while self.game.kernel.phase!='precombat_main':
            self.game.submit(self.game.kernel.priority,'setup:'+str(self.game.store.generation),{'kind':'pass','revision':self.game.kernel.revision},rationale='Synthetic setup.')

    def goal(self):
        job=planning.claim(self.game,'Omo',planning.LONG)
        planning.publish(self.game,'Omo',planning.LONG,job['job_id'],'long_term',{'long_term_plan':'Develop resources.','diplomacy':bounds()})
        return planning.claim(self.game,'Omo',planning.DIPLOMAT)

    def post(self,job,**fields):
        return planning.publish(self.game,'Omo',planning.DIPLOMAT,job['job_id'],'message',fields)

    def test_diplomat_authors_text_and_keeps_advice_private(self):
        job=self.goal();self.assertNotIn('authorized_messages',job);self.assertEqual(bounds(),job['brief'])
        self.post(job,messages=[speech()]);state=self.game.state()
        self.assertEqual(speech()['text'],state['messages'][-1]['text'])
        self.assertNotIn('private_assessment',state['messages'][-1])
        self.assertEqual('truthful',state['actors']['Omo']['private_diplomacy'][-1]['truthfulness'])
        self.assertNotIn('private_diplomacy',state['actors']['Elenda'])

    def test_hold_conflict_override_preserves_prefix_and_deduplicates_review(self):
        job=self.goal();turn=self.game.kernel.state.turn_number
        self.post(job,messages=[speech()],holds=[{'id':'truce','player':'Elenda','scopes':['attack','target_permanents'],
            'expires_turn':turn+2,'rationale':'Pending response.','negotiation_id':'n1'}])
        target=self.game.kernel.state.add_card('fixture-target','catalog:forest','Elenda',Zone.BATTLEFIELD)
        command={'kind':'cast','targets':[target.to_json()]}
        with self.assertRaisesRegex(RulesViolation,'Diplomatic hold'):negotiation.enforce(self.game,'Omo',command)
        negotiation.enforce(self.game,'Omo',{'kind':'play_land','targets':[]})
        claim=actions.claim(self.game,'Omo');before=self.game.store.committed_head()
        result=negotiation.override(self.game,'Omo',claim['claim_id'],'override1',['truce'],'The agreement no longer serves our goal.')
        self.assertEqual(result,negotiation.override(self.game,'Omo',claim['claim_id'],'override1',['truce'],'The agreement no longer serves our goal.'))
        self.assertEqual(before,self.game.store.committed_head())
        negotiation.enforce(self.game,'Omo',command)
        reasons=self.game.state()['actors']['Omo']['jobs'][planning.LONG]['reasons']
        self.assertEqual(1,len([r for r in reasons if r.startswith('diplomatic_override:')]))
        self.assertEqual(['n1'],self.game.state()['actors']['Omo']['overridden_negotiations'])

    def test_brief_approval_releases_diplomat_before_long_term_completion(self):
        job=self.goal();self.post(job,messages=[],authorization_request='Allow another recipient.')
        long=planning.claim(self.game,'Omo',planning.LONG);new=bounds();new['allowed_recipients'].append('Reaminatour')
        decision={'approved':True,'rationale':'The broader negotiation serves the goal.','brief':new}
        planning.publish(self.game,'Omo',planning.LONG,long['job_id'],'brief_decision',decision)
        diplomat=planning.claim(self.game,'Omo',planning.DIPLOMAT)
        self.assertIsNotNone(diplomat);self.assertEqual(new,diplomat['brief'])
        self.assertFalse(diplomat['requires_public_post'])
        self.post(diplomat,messages=[speech()])
        planning.publish(self.game,'Omo',planning.LONG,long['job_id'],'long_term',{'long_term_plan':'Develop resources.','diplomacy':new})
        self.assertNotIn(planning.DIPLOMAT,self.game.state()['actors']['Omo']['jobs'])

    def test_brief_veto_retains_authority_and_does_not_force_speech(self):
        job=self.goal();self.post(job,messages=[],authorization_request='Expand authority.')
        long=planning.claim(self.game,'Omo',planning.LONG)
        planning.publish(self.game,'Omo',planning.LONG,long['job_id'],'brief_decision',{'approved':False,'rationale':'Keep the current limits.'})
        planning.publish(self.game,'Omo',planning.LONG,long['job_id'],'long_term',{'long_term_plan':'Develop resources.','diplomacy':bounds()})
        self.assertEqual(bounds(),self.game.state()['actors']['Omo']['plans']['diplomacy_brief']['value'])
        self.assertNotIn(planning.DIPLOMAT,self.game.state()['actors']['Omo']['jobs'])

    def test_opposite_gate_skips_unchanged_board_and_ignores_lands(self):
        board=self.game.store.packet('Omo');baseline=summary(board,'Omo')
        changed=deepcopy(board);changed['zones']['battlefield']['Elenda'].append({'ref':{'card_id':'land','incarnation':0},'types':['Land'],'tapped':True})
        self.assertEqual(relevant(baseline),relevant(summary(changed,'Omo')))
        changed['zones']['battlefield']['Elenda'].append({'ref':{'card_id':'rock','incarnation':0},'types':['Artifact'],'tapped':False})
        rock=summary(changed,'Omo');self.assertNotEqual(relevant(baseline),relevant(rock))
        changed['zones']['battlefield']['Elenda'][-1]['tapped']=True
        self.assertNotEqual(relevant(rock),relevant(summary(changed,'Omo')))
        changed=deepcopy(board)
        next(p for p in changed['players'] if p['seat']=='Omo')['hand_count']+=1
        self.assertNotEqual(relevant(baseline),relevant(summary(changed,'Omo')))

    def test_gate_wakes_only_two_seats_after_end_step_and_only_on_change(self):
        from unittest.mock import patch
        state=self.game.state()
        for seat in state['actors'].values():seat['jobs']={}
        players=list(self.game.kernel.state.live_players)
        event={'kind':'step_began','step':'end_step','active':players[0],'index':0}
        fake=SimpleNamespace(kernel=SimpleNamespace(semantic_events=[event],state=SimpleNamespace(live_players=players)),record=lambda *args:None)
        state['event_cursor']=0
        with patch('edh_gauntlet.primitive_cadence.changed',return_value=False):planning.observe(fake,state)
        self.assertTrue(all(not s['jobs'] for s in state['actors'].values()))
        state['event_cursor']=0
        with patch('edh_gauntlet.primitive_cadence.changed',return_value=True):planning.observe(fake,state)
        self.assertEqual([players[2]],[a for a in players if state['actors'][a]['jobs']])

    def test_tactical_request_after_prose_wakes_diplomat_without_long_review(self):
        self.post(self.goal(),messages=[speech()])
        short=planning.claim(self.game,'Omo',planning.SHORT)
        planning.publish(self.game,'Omo',planning.SHORT,short['job_id'],'short_term',{
            'short_term_plan':'Develop then bargain.','continuity':'Public truce could help.',
            'long_term_validity':'valid','long_term_invalid_reason':''})
        value={'action_sequence':[],'phase_coverage':{phase:{'status':'no_action','reason':'Synthetic request.'} for phase in planning.PHASES},
               'diplomacy_request':{'objective':'Ask Elenda to avoid attacking us this round.','player':'Elenda'}}
        planning.publish(self.game,'Omo',planning.SHORT,short['job_id'],'actions',value)
        diplomat=planning.claim(self.game,'Omo',planning.DIPLOMAT)
        self.assertEqual(value['diplomacy_request']['objective'],diplomat['requests'][0]['objective'])
        self.assertNotIn(planning.LONG,self.game.state()['actors']['Omo']['jobs'])

    def test_hold_authority_rejects_excess_scope_or_expiry_atomically(self):
        job=self.goal();before=self.game.store.committed_head()
        hold={'id':'bad','player':'Elenda','scopes':['attack'],'expires_turn':self.game.kernel.state.turn_number+9,
              'rationale':'Synthetic.','negotiation_id':'n1'}
        with self.assertRaises(RulesViolation):self.post(job,messages=[speech()],holds=[hold])
        self.assertFalse(self.game.state()['messages']);self.assertEqual(before,self.game.store.committed_head())

    def test_private_notes_roundtrip_without_repeating_prose(self):
        from edh_gauntlet.primitive_delivery import prepare,expand
        packet={'game':1,'actor':'Omo','context_handling':1,'private_diplomacy':[{'message_id':'m','explanation':'x'*600}]}
        first,cache=prepare(packet,'decider');decoded,reference=expand(first)
        second,_=prepare(packet,'decider',cache);decoded2,_=expand(second,reference)
        self.assertEqual(packet,decoded);self.assertEqual(packet,decoded2)
        self.assertEqual({},second['private_diplomacy']['new'])
        other,_=prepare({**packet,'actor':'Elenda'},'decider',cache)
        self.assertTrue(other['private_diplomacy']['new'])

    def test_brief_only_change_finishes_without_republishing_strategy(self):
        job=self.goal();self.post(job,messages=[],authorization_request='Broaden negotiation.')
        long=planning.claim(self.game,'Omo',planning.LONG);old=deepcopy(self.game.state()['actors']['Omo']['plans']['long_term'])
        new=bounds();new['allowed_recipients'].append('Reaminatour')
        result=planning.publish(self.game,'Omo',planning.LONG,long['job_id'],'brief_decision',{
            'approved':True,'rationale':'No strategic change needed.','brief':new,'update_plan':False})
        self.assertIsNone(result['next'])
        self.assertEqual(old,self.game.state()['actors']['Omo']['plans']['long_term'])
        self.assertNotIn(planning.LONG,self.game.state()['actors']['Omo']['jobs'])
        self.assertIsNotNone(planning.claim(self.game,'Omo',planning.DIPLOMAT))

    def test_expired_hold_does_not_block_actions(self):
        with self.game.transaction() as state:
            state['actors']['Omo']['diplomatic_holds']={'expired':{'id':'expired','player':'Elenda','scopes':['attack'],
                'expires_turn':self.game.kernel.state.turn_number,'negotiation_id':'old','rationale':'Old.'}}
        self.assertEqual([],negotiation.conflicts(self.game,'Omo',{'kind':'attack','attackers':[{'defender':'Elenda'}]}))

    def test_planners_cannot_publish_watches(self):
        long=planning.claim(self.game,'Omo',planning.LONG)
        with self.assertRaises(RulesViolation):
            planning.publish(self.game,'Omo',planning.LONG,long['job_id'],'long_term',{
                'long_term_plan':'Develop resources.','diplomacy':bounds(),'watches':[]})
        with self.assertRaises(RulesViolation):planning.validate_actions({'action_sequence':[],
            'phase_coverage':{p:{'status':'no_action','reason':'Fixture.'} for p in planning.PHASES},'watches':[]},{'reasons':[]})

    def test_failed_brief_request_cannot_grant_hold_authority(self):
        job=self.goal();bad=bounds();bad['hold_authority']['max_turns']=9
        with self.assertRaises(RulesViolation):negotiation.brief(bad,'Omo',self.game.state()['actors'])
        self.post(job,messages=[],authorization_request='Allow more restraint.')
        self.assertEqual(bounds(),self.game.state()['actors']['Omo']['plans']['diplomacy_brief']['value'])
        self.assertFalse(self.game.state()['actors']['Omo'].get('diplomatic_holds'))

    def test_addressed_diplomat_waits_for_initial_authority(self):
        with self.game.transaction() as state:
            planning.queue(state,'Omo',planning.DIPLOMAT,'incoming:fixture')
        self.assertIsNone(planning.claim(self.game,'Omo',planning.DIPLOMAT))
        job=self.goal()
        self.assertEqual(bounds(),job['brief'])
        self.assertIn('incoming:fixture',job['reasons'])
        self.assertTrue(job['requires_public_post'])

    def test_diplomat_receives_complete_own_plans_without_cross_seat_or_extra_summary(self):
        self.post(self.goal(),messages=[speech()])
        with self.game.transaction() as state:
            own={'id':'own-tactics','value':{'short_term_plan':'Develop resources; seek a temporary truce.',
                 'continuity':'Private tactical details retained verbatim.'}}
            state['actors']['Omo']['plans']['short_term']=deepcopy(own)
            state['actors']['Elenda']['plans']['short_term']={'id':'other','value':{'short_term_plan':'Other seat secret'}}
            planning.queue(state,'Omo',planning.DIPLOMAT,'incoming:fixture')
        job=planning.claim(self.game,'Omo',planning.DIPLOMAT)
        self.assertEqual(own,job['plans']['short_term'])
        self.assertEqual({'long_term','short_term'},set(job['plans']))
        self.assertNotIn('Other seat secret',str(job))
        self.assertNotIn('hand',job['board']);self.assertEqual([],job['rationales'])
        with self.game.transaction() as state:
            state['actors']['Omo']['plans']['short_term']['value']['short_term_plan']='New later plan.'
        self.assertEqual(job,planning.claim(self.game,'Omo',planning.DIPLOMAT))
