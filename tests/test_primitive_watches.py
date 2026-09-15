"""Planner watch facts use real primitive casts and zone/life transitions."""
from copy import deepcopy
from types import SimpleNamespace
from unittest import TestCase
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_program import CardProgram,CostSpec,ManaCost,CastSpec
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.primitive_planning import LONG,SHORT
from edh_gauntlet import primitive_watches as watches


class PrimitiveWatchTests(TestCase):
    def setUp(self):
        self.state=RulesState(('A','B'))
        self.spell=self.state.add_card('spell','spell','B',Zone.HAND)
        self.object=self.state.add_card('object','object','B',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,(CardProgram('spell','Known spell',('Instant',),
            cast=CastSpec(CostSpec(ManaCost()),'instant')),CardProgram('object','Known object',('Artifact',))))
        self.kernel.open_window_for_scenario('B')
        self.adapter=RulesActorAdapter(self.kernel);self.records=[]
        self.campaign=SimpleNamespace(kernel=self.kernel,store=SimpleNamespace(committed_head=lambda:{'sequence':1,'sha256':'fixture'}),
            record=lambda actor,kind,value:self.records.append((actor,kind,value)))
        self.host={'actors':{'A':{'jobs':{},'next_job':0},'B':{'jobs':{},'next_job':0}}}

    def job(self):
        return {'input':{'board':self.adapter.packet('A'),'_event_cursor':len(self.kernel.semantic_events),
                         '_zone_cursor':self.state.event_count}}

    def install(self,condition,role=LONG,watch_id='watch',job=None):
        watches.install(self.campaign,self.host,'A',role,job or self.job(),[{'watch_id':watch_id,'condition':condition}])

    def cast(self):
        self.adapter.submit('B',{'kind':'cast','revision':self.kernel.revision,'action_id':'fixture-cast',
            'source':self.spell.to_json(),'targets':[],'x_value':0,'payment':{'mana':{},'taps':[]}})

    def test_cast_watch_fires_once_without_disclosing_the_prior_hidden_hand(self):
        self.install({'kind':'card_cast','seat':'B','card':'Known spell'})
        self.assertNotIn('spell',str(self.job()['input']['board']['hand']))
        self.cast();watches.observe(self.campaign,self.host);watches.observe(self.campaign,self.host)
        self.assertEqual(1,len(self.records))
        self.assertIn(LONG,self.host['actors']['A']['jobs'])
        self.assertNotIn(SHORT,self.host['actors']['A']['jobs'])

    def test_cast_between_claim_and_publication_is_not_missed(self):
        frozen=self.job();self.cast()
        self.install({'kind':'card_cast','seat':'B','card':'Known spell'},job=frozen)
        self.assertEqual(1,len(self.records))

    def test_hidden_object_watch_rejects_and_visible_departure_fires(self):
        with self.assertRaisesRegex(RulesViolation,'visible battlefield'):
            self.install({'kind':'object_left','source':self.spell.to_json()})
        self.install({'kind':'object_left','source':self.object.to_json()},role=SHORT)
        self.state.move((ZoneMove(self.object,Zone.GRAVEYARD),),'fixture-removal')
        watches.observe(self.campaign,self.host)
        self.assertIn(SHORT,self.host['actors']['A']['jobs'])
        self.assertEqual(1,len(self.records))

    def test_identical_watch_is_not_rearmed_by_another_plan_publication(self):
        condition={'kind':'life_at_most','seat':'B','value':20}
        self.install(condition);self.state.lose_life_batch(('B',),21)
        watches.observe(self.campaign,self.host)
        self.state.gain_life('B',10);watches.observe(self.campaign,self.host)
        self.install(condition);self.state.lose_life_batch(('B',),10)
        watches.observe(self.campaign,self.host)
        self.assertEqual(1,len(self.records))

    def test_explicit_new_watch_id_rearms_after_replacement(self):
        condition={'kind':'life_at_most','seat':'B','value':20}
        self.install(condition);self.state.lose_life_batch(('B',),21);watches.observe(self.campaign,self.host)
        self.state.gain_life('B',10);watches.observe(self.campaign,self.host)
        self.install(condition,watch_id='rearmed');self.state.lose_life_batch(('B',),10)
        watches.observe(self.campaign,self.host)
        self.assertEqual(2,len(self.records))
