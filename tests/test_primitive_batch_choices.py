"""A real two-land sequence, including persisted choice continuation and interruption."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet import primitive_actions as actions
from edh_gauntlet.rules_state import Zone


class ManaBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'game'
        self.game=PrimitiveCampaign._create(self.path,seed=93,starting_player='Omo')
        self.addCleanup(lambda:self.game.close())
        while self.game.kernel.pending_choice:
            q=self.game.kernel.pending_choice
            self.send(q.actor,{'kind':'answer','request_id':q.request_id,'indexes':[0] if q.kind=='mulligan' else []})
        self.main()
        self.island=self.land('catalog:island');self.send('Omo',{'kind':'play_land','source':self.island.to_json()})
        # A real accepted first turn, with no test-only state mutation.
        self.send('Omo',{'kind':'pass'})
        self.main(next_turn=True)
        self.grove=self.land('catalog:flooded-grove');self.send('Omo',{'kind':'play_land','source':self.grove.to_json()})
        self.island=self.game.kernel.state.current(self.island.card_id)
        self.grove=self.game.kernel.state.current(self.grove.card_id)

    def send(self,actor,command):
        return self.game.submit(actor,'fixture:'+str(self.game.store.generation),
            {**command,'revision':self.game.kernel.revision,**({'action_id':'fixture:'+str(self.game.store.generation)} if command['kind'] in {'activate','play_land'} else {})},
            rationale='Offline mana-batch fixture.')

    def main(self,next_turn=False):
        for _ in range(150):
            if (self.game.kernel.active=='Omo' and self.game.kernel.phase=='precombat_main'
                    and self.game.kernel.priority=='Omo' and (not next_turn or self.game.state()['actors']['Omo']['turns']>=2)):return
            a=self.game.next_action()
            if a.get('decision_kind')=='choice':
                q=self.game.kernel.pending_choice
                self.send(a['actor'],{'kind':'answer','request_id':q.request_id,'indexes':list(range(q.minimum))})
            elif a.get('decision_kind')=='declare_attackers':self.send(a['actor'],{'kind':'attack','attackers':[]})
            else:
                self.assertEqual('priority',a.get('decision_kind'))
                self.send(a['actor'],{'kind':'pass'})
        self.fail('Fixture did not reach own main phase')

    def land(self,name):
        return next(o.ref for o in self.game.kernel.state.objects(Zone.HAND) if o.owner=='Omo' and o.definition==name)

    def approve(self,labels=None):
        kernel=self.game.kernel
        island_ability=kernel.activated_abilities(kernel.state.get(self.island))[0].ability_id
        grove_abilities=kernel.activated_abilities(kernel.state.get(self.grove))
        # The printed filter ability accepts a U payment and offers UU, UG, GG.
        filter_ability=next(a.ability_id for a in grove_abilities if a.cost.mana.symbols)
        def step(key,command):return {'id':key,'seat_turn':2,'phase':'precombat_main','command':command,'rationale':'Produce the explicitly approved mana.','scheduler':{'mode':'hold_full_control'}}
        steps=[step('island',{'kind':'activate','source':self.island.to_json(),'ability_id':island_ability,'targets':[],'x_value':0,'payment':{'mana':{},'taps':[]}}),
               step('grove',{'kind':'activate','source':self.grove.to_json(),'ability_id':filter_ability,'targets':[],'x_value':0,'payment':{'mana':{'U':1},'taps':[]}}),
               step('colors',{'kind':'answer','choice_from':{'step_id':'grove','option_labels':labels or ['{G}{G}','{G}{U}','{U}{U}']},'indexes':[1]}),
               step('done',{'kind':'pass'})]
        frozen=actions.claim(self.game,'Omo')
        actions.approve(self.game,'Omo',frozen['claim_id'],approve_ids=[],reject_ids=[],added=steps,pass_priority=False)

    def test_one_approval_runs_activations_and_choice_across_reopen_without_replay(self):
        self.approve();before=self.game.store.generation
        self.assertTrue(actions.automatic(self.game));self.assertTrue(actions.automatic(self.game))
        self.assertEqual('mana_choice',self.game.kernel.pending_choice.kind)
        prefix=self.game.store.committed_head();self.game.close()
        self.game=PrimitiveCampaign.open(self.path,recover=False)
        self.assertEqual(prefix,self.game.store.committed_head())
        self.assertTrue(actions.automatic(self.game));self.assertIsNone(self.game.kernel.pending_choice)
        self.assertTrue(actions.automatic(self.game));self.assertEqual(before+4,self.game.store.generation)
        self.assertFalse(actions.automatic(self.game))

    def test_changed_color_menu_stops_at_accepted_prefix(self):
        self.approve(labels=['{U}{U}','{G}{U}','{G}{G}'])
        self.assertTrue(actions.automatic(self.game));self.assertTrue(actions.automatic(self.game))
        before=self.game.store.committed_head();choice=self.game.kernel.pending_choice
        self.assertFalse(actions.automatic(self.game));self.assertEqual(before,self.game.store.committed_head())
        self.assertEqual(choice,self.game.kernel.pending_choice)
        self.assertIsNone(self.game.state()['actors']['Omo']['approved'])
        self.assertIn('exact options',self.game.state()['actors']['Omo']['last_rejection'])


class ManaGuardTests(unittest.TestCase):
    def test_long_sequences_still_have_step_and_byte_limits(self):
        from edh_gauntlet.primitive_planning import validate_actions,PHASES
        from edh_gauntlet.rules_state import RulesViolation
        def proposal(count):
            steps=[{'id':str(i),'seat_turn':1,'phase':'precombat_main','command':{'kind':'pass'},
                    'rationale':'Approved.','scheduler':{'mode':'hold_full_control'}} for i in range(count)]
            return {'action_sequence':steps,'phase_coverage':{p:({'status':'planned'} if p=='precombat_main'
                else {'status':'no_action','reason':'No action.'}) for p in PHASES}}
        validate_actions(proposal(64),{'reasons':[]})
        with self.assertRaises(RulesViolation):validate_actions(proposal(65),{'reasons':[]})
        large=proposal(64)
        for step in large['action_sequence']:step['rationale']='x'*300
        with self.assertRaises(RulesViolation):validate_actions(large,{'reasons':[]})

    def test_guard_requires_immediate_same_window_predecessor_and_explicit_index(self):
        from copy import deepcopy
        from edh_gauntlet.primitive_batch_choices import validate
        from edh_gauntlet.rules_state import RulesViolation
        steps=[{'id':'tap','seat_turn':1,'phase':'precombat_main','command':{'kind':'activate'}},
               {'id':'color','seat_turn':1,'phase':'precombat_main','command':{'kind':'answer','choice_from':{'step_id':'tap','option_labels':['{U}','{G}']},'indexes':[1]}}]
        validate(steps,1)
        for field,value in [('choice_from',None),('indexes',[True]),('indexes',[2]),('request_id','stale')]:
            bad=deepcopy(steps);bad[1]['command'][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(RulesViolation):validate(bad,1)
        for field,value in [('seat_turn',2),('phase','combat')]:
            bad=deepcopy(steps);bad[1][field]=value
            with self.subTest(field=field),self.assertRaises(RulesViolation):validate(bad,1)
        bad=deepcopy(steps);bad[1]['command']['choice_from']['step_id']='unrelated'
        with self.assertRaises(RulesViolation):validate(bad,1)

    def test_exact_menu_never_authorizes_another_frame_actor_or_choice_kind(self):
        from types import SimpleNamespace
        from dataclasses import replace
        from edh_gauntlet.primitive_batch_choices import bind
        from edh_gauntlet.rules_choices import ChoiceRequest,Option
        from edh_gauntlet.rules_state import RulesViolation
        request=ChoiceRequest('fresh','A','mana_choice','Choose mana',(Option('0','{U}'),Option('1','{G}')),1,1,False,False,'rev')
        step={'command':{'kind':'answer','choice_from':{'step_id':'tap','option_labels':['{U}','{G}']},'indexes':[1]}}
        approved={'cursor':1,'steps':[{'id':'tap'},step],'continuation_frame':'accepted-mana-frame'}
        frame={'id':'accepted-mana-frame','controller':'A','mana_ability':True}
        campaign=SimpleNamespace(kernel=SimpleNamespace(pending_choice=request,resolving=frame))
        self.assertEqual({'kind':'answer','request_id':'fresh','indexes':[1]},bind(campaign,'A',approved,step))
        for altered in [dict(frame,id='another-frame'),dict(frame,controller='B'),dict(frame,mana_ability=False)]:
            campaign.kernel.resolving=altered
            with self.assertRaises(RulesViolation):bind(campaign,'A',approved,step)
        campaign.kernel.resolving=frame
        for altered in [replace(request,actor='B'),replace(request,kind='protection_color'),replace(request,minimum=0),replace(request,options=tuple(reversed(request.options)))]:
            campaign.kernel.pending_choice=altered
            with self.assertRaises(RulesViolation):bind(campaign,'A',approved,step)
