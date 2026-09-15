"""Whole-game advancement and dashboard reports over real durable fixtures."""
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet.primitive_multigame import advance
from edh_gauntlet.primitive_reports import cardwise,snapshot,verified_result
from edh_gauntlet.rules_state import RulesViolation
from edh_gauntlet.runtime_store import read,write


def finish(game):
    for index in range(32):
        if game.state()['terminal']:return
        action=game.next_action();actor=action['actor'];choice=game.kernel.pending_choice
        command=({'kind':'answer','request_id':choice.request_id,'indexes':[0]} if choice else {'kind':'concede'})
        command['revision']=game.kernel.revision
        game.submit(actor,f'fixture-{index}',command,rationale='Deterministic conformance fixture, not a live pilot.')
    raise AssertionError('Fixture did not terminate')


class MultiGameTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'run'
        self.game=PrimitiveCampaign._create(self.root,seed=93,starting_player='Omo',games=2)
        self.addCleanup(lambda:self.game.close())

    def test_complete_two_games_preserving_first_prefix_and_isolated_roles(self):
        finish(self.game)
        self.assertEqual('advance_game',self.game.next_action()['kind'])
        self.game.close()
        before=hashlib.sha256((self.root/'game_01/rules.sqlite').read_bytes()).hexdigest()
        self.game=PrimitiveCampaign.open(self.root,recover=False)
        old=self.game;self.game=advance(old,2);old.close()
        self.assertEqual(before,hashlib.sha256((self.root/'game_01/rules.sqlite').read_bytes()).hexdigest())
        self.assertEqual(0,self.game.store.generation);self.assertEqual({},self.game.state()['registrations'])
        self.assertEqual(94,self.game.config['seed']);self.assertNotEqual('Omo',self.game.config['starting_player'])
        self.assertEqual(2,self.game.next_action()['game'])
        finish(self.game)
        self.assertEqual('cohort_complete',self.game.next_action()['reason'])
        report=cardwise(self.root)
        self.assertEqual(2,report['completed_games']);self.assertEqual([],report['excluded_games'])
        self.assertEqual(100,sum(row['quantity'] for row in report['rows']))
        self.assertTrue(all(row['games_seen']<=2 for row in report['rows']))
        value=snapshot(self.root)
        self.assertEqual(2,value['game']);self.assertEqual(4,len(value['operator']))
        self.assertEqual(2,len(value['game_results']));self.assertTrue(value['all_decisions'])

    def test_blocker_pause_and_unfinished_game_cannot_advance(self):
        with self.assertRaises(RulesViolation):advance(self.game,2)
        self.game.rules_blocker('Omo','Synthetic unsupported-rule fixture.')
        with self.assertRaises(RulesViolation):advance(self.game,2)
        report=cardwise(self.root)
        self.assertEqual(0,report['completed_games']);self.assertEqual(1,len(report['excluded_games']))
        self.assertFalse((self.root/'game_02').exists())

    def test_terminal_seal_tamper_is_excluded(self):
        finish(self.game)
        seal=read(self.root/'game_01/terminal_result.json');seal['winners']=['Omo']
        write(self.root/'game_01/terminal_result.json',seal)
        with self.assertRaises(RulesViolation):verified_result(self.root/'game_01')
        self.assertEqual(0,cardwise(self.root)['completed_games'])

    def test_campaign_schedule_and_frozen_deck_cannot_change(self):
        manifest=read(self.root/'cohort.json');manifest['target_games']=3
        write(self.root/'cohort.json',manifest)
        with self.assertRaisesRegex(RulesViolation,'schedule'):PrimitiveCampaign.open(self.root)

    def test_live_reporting_does_not_accept_or_recover_pending_input(self):
        q=self.game.kernel.pending_choice
        self.game.prepare(q.actor,'pending',{'kind':'answer','request_id':q.request_id,'indexes':[0],
                          'revision':self.game.kernel.revision},rationale='Pending synthetic input.')
        value=snapshot(self.root)
        self.assertEqual(0,value['status']['decision_count']);self.assertEqual('pending',self.game.state()['pending'])
        self.assertNotIn('library_order',str(value));self.assertNotIn('operator_statistics',str(value))

    def test_operator_pause_blocks_terminal_advancement(self):
        finish(self.game);write(self.root/'HOST_PAUSED.json',{'reason':'user_stop'})
        with self.assertRaisesRegex(RulesViolation,'pause'):advance(self.game,2)

    def test_interrupted_publication_reuses_the_prepared_next_game(self):
        finish(self.game)
        from edh_gauntlet import primitive_multigame as module
        original=module.write
        def fail_manifest(path,value):
            if path==self.root/'cohort.json':raise OSError('Synthetic interruption before manifest publication')
            return original(path,value)
        with patch.object(module,'write',side_effect=fail_manifest):
            with self.assertRaises(OSError):advance(self.game,2)
        intent=read(self.root/'ADVANCE.json')
        self.assertEqual(1,read(self.root/'cohort.json')['active_game'])
        old=self.game;self.game=advance(old,2);old.close()
        self.assertEqual(intent['binding'],self.game.binding)
        self.assertEqual(0,self.game.store.generation)
        self.assertFalse((self.root/'ADVANCE.json').exists())

    def test_statistics_include_transient_entry_and_keep_printed_copy_identity(self):
        from edh_gauntlet.rules_state import Zone,ZoneMove
        from edh_gauntlet.primitive_reports import capture_statistics
        kernel=self.game.kernel
        card=next(o for o in kernel.state.objects(Zone.LIBRARY,owner='Reaminatour')
                  if 'Creature' in kernel.definitions[o.definition].types)
        original_name=self.game._report_card_names[card.definition]
        copied=next(o.definition for o in kernel.state.objects(Zone.COMMAND) if o.definition!=card.definition)
        kernel.state.move((ZoneMove(card.ref,Zone.BATTLEFIELD,copied_definition=copied),),'fixture reanimation')
        kernel.state.move((ZoneMove(kernel.state.current(card.ref.card_id),Zone.GRAVEYARD),),'fixture departure')
        state=self.game.state();capture_statistics(self.game,state)
        self.assertIn(original_name,state['operator_statistics']['seen'])
        self.assertIn(original_name,state['operator_statistics']['cast'])
