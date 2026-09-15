from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from edh_gauntlet import primitive_dependencies as dependencies,primitive_planning as planning
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet.rules_state import RulesViolation


class DependencyFactsTests(TestCase):
    def test_changed_removed_and_unchanged_facts(self):
        board={'players':[{'life':40}],'hand':[]}
        frozen=dependencies.freeze(board,['/players/0/life','/hand'])
        self.assertFalse(dependencies.changed(deepcopy(board),frozen))
        self.assertEqual(['/players/0/life'],dependencies.changed({'players':[],'hand':[]},frozen))
        self.assertEqual(['/hand'],dependencies.changed({**board,'hand':[{'name':'new'}]},frozen))

    def test_nonfacts_missing_paths_aliases_and_duplicates_rejected(self):
        board={'players':[{'life':40}],'revision':1,'hand':[]}
        for paths in [['/revision'],['/players/01/life'],['/players/0/missing'],['/hand','/hand'],['/hand/~2'],[4]]:
            with self.assertRaises(RulesViolation):dependencies.freeze(board,paths)


class TacticalDependencyTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.game=PrimitiveCampaign._create(Path(self.tmp.name)/'game',seed=93,starting_player='Omo')
        self.addCleanup(self.game.close)
        q=self.game.kernel.pending_choice
        self.game.submit('Omo','keep',{'kind':'answer','revision':self.game.kernel.revision,
            'request_id':q.request_id,'indexes':[0]},rationale='Synthetic keep.')
        self.goal('Opening goal.')

    def goal(self,text):
        with self.game.transaction() as state:planning.queue(state,'Omo',planning.LONG,'fixture_review')
        job=planning.claim(self.game,'Omo',planning.LONG)
        planning.publish(self.game,'Omo',planning.LONG,job['job_id'],'long_term',
            {'long_term_plan':text,'diplomacy':[{'id':'hello','text':'Synthetic public text.','expires_turn':20}]})

    def tactical(self,job=None):
        job=job or planning.claim(self.game,'Omo',planning.SHORT)
        planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'short_term',
            {'short_term_plan':'Keep resources available.','continuity':'Opening fixture.',
             'long_term_validity':'valid','long_term_invalid_reason':'','dependencies':['/hand']})
        planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'actions',
            {'action_sequence':[],'phase_coverage':{p:{'status':'reassess','reason':'Synthetic fixture.'} for p in planning.PHASES}})

    def test_goal_change_without_factual_change_does_not_queue_tactics(self):
        self.tactical();self.goal('Revised goal.')
        self.assertNotIn(planning.SHORT,self.game.state()['actors']['Omo']['jobs'])

    def test_revised_goal_with_changed_dependency_queues_tactics(self):
        self.tactical()
        board=self.game.store.packet('Omo');board['hand']=[]
        with patch.object(self.game.store,'packet',return_value=board):self.goal('Revised goal.')
        job=self.game.state()['actors']['Omo']['jobs'][planning.SHORT]
        self.assertTrue(any(r.startswith('changed_dependencies:') for r in job['reasons']))
        self.assertEqual(['/hand'],self.game.evidence('Omo',kinds=('dependency_review',))[0]['value']['paths'])

    def test_late_tactical_publication_retains_frozen_baseline_and_queues_followup(self):
        job=planning.claim(self.game,'Omo',planning.SHORT)
        self.goal('Revised goal while tactics are running.')
        board=self.game.store.packet('Omo');board['hand']=[]
        with patch.object(self.game.store,'packet',return_value=board):self.tactical(job)
        seat=self.game.state()['actors']['Omo']
        self.assertNotEqual(seat['plans']['long_term']['id'],seat['tactical_dependencies']['goal_id'])
        self.assertIn(planning.SHORT,seat['jobs'])
