from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from dataclasses import replace
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet import primitive_actions as actions,primitive_snoozes as snoozes
from edh_gauntlet.rules_state import ObjectRef,RulesViolation


class SourceSnoozeTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.game=PrimitiveCampaign._create(Path(self.tmp.name)/'game',seed=93,starting_player='Omo')
        self.addCleanup(self.game.close)
        while self.game.kernel.pending_choice:
            q=self.game.kernel.pending_choice
            self.game.submit(q.actor,'setup:'+q.request_id,{'kind':'answer','revision':self.game.kernel.revision,
                'request_id':q.request_id,'indexes':[0] if q.kind=='mulligan' else []},rationale='Synthetic setup.')

    def directive(self,refs=None):
        refs=refs if refs is not None else [row['ref'] for row in snoozes.sources(self.game,'Omo').values()]
        return snoozes.bind(self.game,'Omo',actions.normalize_scheduler({'mode':'snooze_objects','objects':refs,
             'time':'1 beginning of upkeep','wake_condition':'deadline_only'}))

    def test_only_complete_explicit_source_coverage_can_pass(self):
        full=self.directive();partial=self.directive(full['objects'][:-1])
        with self.game.transaction() as state:actions.apply_control(self.game,state,'Omo',{'scheduler':partial})
        before=self.game.store.committed_head()
        self.assertFalse(actions.automatic(self.game));self.assertEqual(before,self.game.store.committed_head())
        with self.game.transaction() as state:actions.apply_control(self.game,state,'Omo',{'scheduler':full})
        self.assertTrue(actions.automatic(self.game))
        self.assertNotEqual('Omo',self.game.next_action()['actor'])

    def test_marks_sources_without_removing_board_facts(self):
        original=self.game.store.packet('Omo');held=self.directive([original['hand'][0]['ref']])
        packet=self.game.store.packet('Omo');snoozes.annotate(self.game,'Omo',packet,held)
        self.assertTrue(packet['hand'][0]['priority_snoozed'])
        self.assertEqual(len(original['hand']),len(packet['hand']))
        self.assertEqual(original['hand'][0]['name'],packet['hand'][0]['name'])
        self.assertFalse(packet['hand'][1]['priority_snoozed'])

    def test_control_epoch_change_invalidates_exact_source_hold(self):
        held=self.directive();row=held['sources'][0]
        obj=self.game.kernel.state.get(ObjectRef.from_json(row['ref']))
        original=self.game.kernel.state.get
        with patch.object(self.game.kernel.state,'get',side_effect=lambda ref:
                replace(obj,controlled_since=obj.controlled_since+1) if ref==obj.ref else original(ref)):
            self.assertFalse(snoozes.covers(self.game,'Omo',held))

    def test_unknown_or_duplicate_reference_is_rejected(self):
        with self.assertRaisesRegex(RulesViolation,'current visible'):
            self.directive([{'card_id':'hidden-or-absent','incarnation':0}])
        ref=self.game.store.packet('Omo')['hand'][0]['ref']
        with self.assertRaisesRegex(RulesViolation,'Duplicate'):self.directive([ref,ref])

    def test_required_choice_clears_snooze_without_answering(self):
        self.game.close()
        self.game=PrimitiveCampaign._create(Path(self.tmp.name)/'opening',seed=94,starting_player='Omo')
        self.addCleanup(self.game.close)
        with self.game.transaction() as state:actions.apply_control(self.game,state,'Omo',{'scheduler':self.directive()})
        self.assertFalse(actions.automatic(self.game))
        self.assertIsNone(self.game.state()['actors']['Omo']['snooze'])
        self.assertEqual(0,self.game.store.generation)

    def advance_to(self,actor,phase):
        for index in range(150):
            k=self.game.kernel
            if k.active==actor and k.phase==phase:return
            frontier=self.game.next_action();who=frontier['actor']
            command=({'kind':'attack','attackers':[]} if frontier['decision_kind']=='declare_attackers'
                     else {'kind':'pass'})
            if frontier['decision_kind']=='choice':
                choice=k.pending_choice
                command={'kind':'answer','request_id':choice.request_id,'indexes':list(range(choice.minimum))}
            self.game.submit(who,'advance:'+str(self.game.store.generation),
                             {**command,'revision':k.revision},rationale='Offline boundary setup.')
        self.fail('Fixture did not reach boundary')

    def test_forced_empty_attack_preserves_snoozes_and_priority_window(self):
        self.advance_to('Omo','declare_attackers')
        directive=actions.normalize_scheduler({'mode':'snooze_table','time':'9 beginning of upkeep',
                                               'wake_condition':'opponent_action'})
        with self.game.transaction() as state:
            for actor in state['actors']:actions.apply_control(self.game,state,actor,{'scheduler':directive})
        before=self.game.store.generation
        self.assertTrue(actions.automatic(self.game))
        self.assertEqual(before+1,self.game.store.generation)
        self.assertEqual('priority',self.game.next_action()['decision_kind'])
        self.assertTrue(all(seat['snooze'] for seat in self.game.state()['actors'].values()))
        self.assertTrue(actions.automatic(self.game))

    def test_forced_empty_attack_does_not_authorize_new_priority_pass(self):
        self.advance_to('Omo','declare_attackers')
        self.assertTrue(actions.automatic(self.game))
        self.assertFalse(actions.automatic(self.game))

    def test_table_snooze_expires_at_own_upkeep_before_long_deadline(self):
        directive=actions.normalize_scheduler({'mode':'snooze_table','time':'9 beginning of upkeep',
                                               'wake_condition':'deadline_only'})
        with self.game.transaction() as state:actions.apply_control(self.game,state,'Elenda',{'scheduler':directive})
        self.advance_to('Elenda','upkeep')
        self.assertIsNone(self.game.state()['actors']['Elenda']['snooze'])
        self.assertFalse(actions.automatic(self.game))

    def test_possible_attacker_still_requires_pilot(self):
        self.advance_to('Omo','declare_attackers')
        with patch.object(self.game.kernel,'attack_candidates',return_value={'candidate':object()}):
            before=self.game.store.generation
            self.assertFalse(actions.automatic(self.game))
            self.assertEqual(before,self.game.store.generation)

    def test_empty_attack_resulting_opposing_trigger_still_wakes(self):
        directive=actions.normalize_scheduler({'mode':'snooze_table','time':'9 beginning of upkeep',
                                               'wake_condition':'opponent_action'})
        with self.game.transaction() as state:
            actions.apply_control(self.game,state,'Elenda',{'scheduler':directive})
            state['scheduler_event_cursor']=len(self.game.kernel.semantic_events)
            self.game.kernel.semantic_events.append({'kind':'trigger_placed','controller':'Omo'})
            try:actions.observe(self.game,state,'Omo',{'kind':'attack','attackers':[]})
            finally:self.game.kernel.semantic_events.pop()
            self.assertIsNone(state['actors']['Elenda']['snooze'])

    def test_explicit_own_main_snooze_survives_upkeep_but_not_main(self):
        directive=actions.normalize_scheduler({'mode':'snooze_until_own_main','wake_condition':'deadline_only'})
        self.assertEqual(directive,actions.normalize_scheduler(directive))
        with self.game.transaction() as state:actions.apply_control(self.game,state,'Elenda',{'scheduler':directive})
        self.advance_to('Elenda','upkeep')
        self.assertIsNotNone(self.game.state()['actors']['Elenda']['snooze'])
        self.assertTrue(actions.automatic(self.game))
        self.advance_to('Elenda','precombat_main')
        self.assertIsNone(self.game.state()['actors']['Elenda']['snooze'])
        self.assertFalse(actions.automatic(self.game))
