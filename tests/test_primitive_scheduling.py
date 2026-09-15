"""Alarm deadlines are seat-specific, one-shot and durable across retries."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet.primitive_actions import claim
from edh_gauntlet.primitive_scheduling import control,advance,normalize
from edh_gauntlet.primitive_planning import SHORT,LONG
from edh_gauntlet.rules_state import RulesViolation


class AlarmClockTests(TestCase):
    def test_only_named_seat_boundaries_count_and_final_alarm_fires_once(self):
        state={'actors':{'Omo':{'jobs':{},'next_job':0,'alarm':{
            'id':'fixture','seat':'Elenda','armed_after':0,'long_term':False,
            'remaining':2,'time':{'occurrences':2,'edge':'beginning','phase':'combat'}}}}}
        def event(i,seat,step):return {'index':i,'kind':'step_began','active':seat,'step':step}
        advance(state,[event(1,'Omo','begin_combat'),event(2,'Elenda','begin_combat'),
                       event(3,'Elenda','declare_attackers'),event(4,'Elenda','postcombat_main')])
        self.assertEqual(1,state['actors']['Omo']['alarm']['remaining'])
        self.assertFalse(state['actors']['Omo']['jobs'])
        advance(state,[event(5,'Elenda','begin_combat'),event(6,'Elenda','declare_attackers')])
        self.assertIsNone(state['actors']['Omo']['alarm'])
        self.assertEqual(['pilot_alarm:fixture'],state['actors']['Omo']['jobs'][SHORT]['reasons'])

    def test_end_boundary_belongs_to_previous_active_seat(self):
        state={'alarm_boundary':{'seat':'Elenda','phase':'cleanup'},'actors':{'Omo':{
            'jobs':{},'next_job':0,'alarm':{'id':'end','seat':'Elenda','armed_after':0,
            'long_term':True,'remaining':1,'time':{'occurrences':1,'edge':'end','phase':'cleanup'}}}}}
        advance(state,[{'index':1,'kind':'step_began','active':'Omo','step':'untap'}])
        self.assertIn(LONG,state['actors']['Omo']['jobs'])

    def test_invalid_or_duplicate_mandatory_boundary_rejects(self):
        for value in ({'mode':'schedule','seat':'Unknown','time':'1 beginning of upkeep'},
                      {'mode':'cancel','long_term':True},
                      {'mode':'schedule','seat':'Omo','time':'1 end of end_step'}):
            with self.assertRaises((RulesViolation,ValueError)):normalize(value,'Omo',['Omo','Elenda'])


class AlarmControlTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.game=PrimitiveCampaign._create(Path(self.tmp.name)/'game',seed=93,starting_player='Omo')
        self.addCleanup(self.game.close)

    def keep_fixture_hands(self):
        while self.game.kernel.pending_choice:
            q=self.game.kernel.pending_choice
            self.game.submit(q.actor,'fixture:'+q.request_id,{'kind':'answer','revision':self.game.kernel.revision,
                'request_id':q.request_id,'indexes':[0]},rationale='Synthetic setup keep.')

    def test_required_choice_cannot_control_alarm(self):
        frozen=claim(self.game,'Omo')
        with self.assertRaisesRegex(RulesViolation,'priority'):
            control(self.game,'Omo',frozen['claim_id'],'first',{'mode':'now'})
        self.assertEqual(0,self.game.store.generation)

    def test_schedule_retry_does_not_rearm_and_cancel_preserves_decision(self):
        self.keep_fixture_hands();frozen=claim(self.game,'Omo');head=self.game.store.committed_head()
        value={'mode':'schedule','seat':'Elenda','time':'2 beginning of upkeep'}
        receipt=control(self.game,'Omo',frozen['claim_id'],'first',value)
        with self.game.transaction() as state:state['actors']['Omo']['alarm']['remaining']=1
        self.assertEqual(receipt,control(self.game,'Omo',frozen['claim_id'],'first',value))
        self.assertEqual(1,self.game.state()['actors']['Omo']['alarm']['remaining'])
        control(self.game,'Omo',frozen['claim_id'],'cancel',{'mode':'cancel'})
        self.assertIsNone(self.game.state()['actors']['Omo']['alarm'])
        self.assertEqual(head,self.game.store.committed_head())
        self.assertEqual(frozen,claim(self.game,'Omo'))
        with self.assertRaises(RulesViolation):control(self.game,'Omo',frozen['claim_id'],'first',{'mode':'now'})
