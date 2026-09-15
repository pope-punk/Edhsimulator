"""Offline accepted-prefix cases for staged combat proposals."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet import primitive_actions as actions
from edh_gauntlet.rules_setup import fresh_pod
from edh_gauntlet.rules_state import Zone, RulesViolation, ObjectRef


class CombatStageTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        k=fresh_pod(seed=93,starting_player='Omo')
        program=next(p for p in k.definitions.values() if p.name=='Omo, Queen of Vesuva')
        self.attacker=k.state.add_card('fixture-attacker',program.definition_id,'Omo',Zone.BATTLEFIELD)
        k.pending_choice=replace(k.pending_choice,revision=k.revision)
        with patch('edh_gauntlet.primitive_campaign.fresh_pod',return_value=k):
            self.game=PrimitiveCampaign._create(Path(self.tmp.name)/'game',seed=93,starting_player='Omo')
        self.addCleanup(self.game.close)
        while self.game.kernel.pending_choice:
            q=self.game.kernel.pending_choice
            self.game.submit(q.actor,'setup:'+q.request_id,{'kind':'answer','revision':self.game.kernel.revision,
                'request_id':q.request_id,'indexes':[0] if q.kind=='mulligan' else []},rationale='Offline setup')
        self.game.config.pop('mana_only_priority',None)
        self.advance('begin_combat','priority')

    def advance(self,phase,kind):
        for _ in range(40):
            n=self.game.next_action()
            if self.game.kernel.phase==phase and n.get('decision_kind')==kind:return
            self.assertEqual('priority',n['decision_kind'])
            self.game.submit(n['actor'],'fixture-pass:'+str(self.game.store.generation),
                {'kind':'pass','revision':self.game.kernel.revision},rationale='Offline advancement')
        self.fail('No expected boundary')

    def approve_attack(self,pass_priority=True,source=None):
        claim=actions.claim(self.game,'Omo')
        turn=self.game.state()['actors']['Omo']['turns']
        step={'id':'attack','seat_turn':turn,'phase':'combat','command':{'kind':'attack',
            'attackers':[{'source':(source or self.attacker).to_json(),'defender':'Elenda'}]},
            'rationale':'Synthetic approved attack','scheduler':{'mode':'hold_full_control'}}
        actions.approve(self.game,'Omo',claim['claim_id'],approve_ids=[],reject_ids=[],added=[step],pass_priority=pass_priority)

    def test_waits_through_priority_then_executes_approved_attack_once(self):
        self.approve_attack(); before=self.game.store.generation
        self.assertTrue(actions.automatic(self.game))
        self.assertEqual(before+1,self.game.store.generation)
        self.assertEqual(0,self.game.state()['actors']['Omo']['approved']['cursor'])
        self.advance('declare_attackers','declare_attackers')
        self.assertTrue(actions.automatic(self.game))
        self.assertEqual(1,self.game.state()['actors']['Omo']['approved']['cursor'])
        self.assertEqual(1,len(self.game.kernel.combat['attackers']))
        self.assertEqual('Elenda',self.game.kernel.combat['attackers'][0]['defender'])
        events=[e for e in self.game.kernel.semantic_events if e['kind']=='attackers_declared']
        self.assertEqual(1,len(events))

    def test_pass_opt_out_preserves_control_and_pending_attack(self):
        self.approve_attack(False); before=self.game.store.committed_head()
        self.assertFalse(actions.automatic(self.game))
        self.assertEqual(before,self.game.store.committed_head())
        self.assertEqual(0,self.game.state()['actors']['Omo']['approved']['cursor'])

    def test_frozen_claim_is_not_advanced(self):
        self.approve_attack(False); actions.claim(self.game,'Omo')
        before=self.game.store.committed_head();self.assertFalse(actions.automatic(self.game))
        self.assertEqual(before,self.game.store.committed_head())

    def test_unapproved_declaration_still_requires_pilot(self):
        self.advance('declare_attackers','declare_attackers')
        before=self.game.store.committed_head();self.assertFalse(actions.automatic(self.game))
        self.assertEqual(before,self.game.store.committed_head())

    def test_ordinary_mistimed_combat_commands_explain_required_stage(self):
        for kind,required in [('attack','declare_attackers'),('block','declare_blockers'),('damage','combat_damage')]:
            before=self.game.store.committed_head()
            with self.assertRaisesRegex(RulesViolation,required):
                actions.bind_command(self.game,'Omo',{'kind':kind},'bad-stage')
            self.assertEqual(before,self.game.store.committed_head())

    def test_old_binding_does_not_execute_attack_declaration(self):
        self.approve_attack();self.game.config.pop('combat_stage_batches')
        self.advance('declare_attackers','declare_attackers')
        before=self.game.store.committed_head();self.assertFalse(actions.automatic(self.game))
        self.assertEqual(before,self.game.store.committed_head())

    def test_missed_declaration_cancels_instead_of_replaying(self):
        self.approve_attack()
        self.advance('declare_attackers','declare_attackers')
        self.game.submit('Omo','fixture-empty-attack',{'kind':'attack','attackers':[],
            'revision':self.game.kernel.revision},rationale='Offline alternate declaration')
        before=self.game.store.committed_head()
        self.assertFalse(actions.automatic(self.game))
        self.assertEqual(before,self.game.store.committed_head())
        seat=self.game.state()['actors']['Omo']
        self.assertIsNone(seat['approved'])
        self.assertIn('already passed',seat['last_rejection'])

    def test_invalid_approved_attacker_returns_control_without_acceptance(self):
        self.approve_attack(source=ObjectRef('missing-fixture-source',0))
        self.advance('declare_attackers','declare_attackers')
        before=self.game.store.committed_head()
        self.assertFalse(actions.automatic(self.game))
        self.assertEqual(before,self.game.store.committed_head())
        self.assertIsNone(self.game.state()['actors']['Omo']['approved'])

    def test_forced_empty_declaration_cancels_current_attack_preserving_snooze(self):
        self.approve_attack()
        self.advance('declare_attackers','declare_attackers')
        with self.game.transaction() as state:
            state['actors']['Omo']['snooze']={'mode':'snooze_table','remaining':1,
                'time':{'occurrences':1,'edge':'beginning','phase':'upkeep'},'wake_condition':'deadline_only'}
        with patch.object(self.game.kernel,'attack_candidates',return_value={}):
            self.assertTrue(actions.automatic(self.game))
        seat=self.game.state()['actors']['Omo']
        self.assertIsNone(seat['approved']); self.assertIsNotNone(seat['snooze'])
        self.assertIn('No eligible attackers',seat['last_rejection'])
        self.assertEqual([],self.game.kernel.combat['attackers'])
