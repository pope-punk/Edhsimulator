import hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from edh_gauntlet.cardwise_report import report,deck_rows,eligible_game,observations
from edh_gauntlet.cardwise_replay import ZoneObserver
from edh_gauntlet.runtime_store import write


class ZoneObserverTests(unittest.TestCase):
    def test_hand_battlefield_graveyard_from_anywhere(self):
        observer=ZoneObserver({'a':'Tutor target','b':'Milled card','c':'Reanimated card'})
        players={'seat':SimpleNamespace(hand=[SimpleNamespace(uid='a')],graveyard=[SimpleNamespace(uid='b')],battlefield=[]),
                 'opponent':SimpleNamespace(hand=[],graveyard=[],battlefield=[SimpleNamespace(uid='c')])}
        observer.observe(players);observer.observe(players)
        self.assertEqual(observer.seen,{'Tutor target','Milled card','Reanimated card'})
        self.assertEqual(observer.cast,{'Reanimated card'})

    def test_scry_command_exile_and_tokens_do_not_count(self):
        observer=ZoneObserver({'a':'Commander','b':'Scry card','c':'Exiled card','d':'Clone original'})
        player=SimpleNamespace(hand=[],graveyard=[],battlefield=[SimpleNamespace(uid='TOK-copy',name='Clone original',token=True)],
                               library=[SimpleNamespace(uid='b')],commander=SimpleNamespace(uid='a'),exile=[SimpleNamespace(uid='c')])
        observer.observe({'seat':player});self.assertEqual(observer.seen,set())
        observer.event('cast','seat','Copy',{'uid':'COPY-a'});self.assertEqual(observer.cast,set())

    def test_original_identity_survives_copy_and_control_change(self):
        observer=ZoneObserver({'a':'Body Double'})
        player=SimpleNamespace(hand=[],graveyard=[],battlefield=[SimpleNamespace(uid='a',name='Copied creature',token=False)])
        observer.observe({'opponent':player})
        self.assertEqual(observer.seen,{'Body Double'});self.assertEqual(observer.cast,{'Body Double'})

    def test_cast_counts_even_without_resolution(self):
        observer=ZoneObserver({'a':'Countered spell'})
        observer.event('cast','seat','Countered spell',{'uid':'a'})
        self.assertEqual(observer.cast,{'Countered spell'});self.assertEqual(observer.seen,set())
        observer.observe({'seat':SimpleNamespace(hand=[],graveyard=[SimpleNamespace(uid='a')],battlefield=[])})
        self.assertEqual(observer.seen,{'Countered spell'})


class ReportTests(unittest.TestCase):
    def fixture(self,root,number,winner='Reaminatour',complete=True):
        directory=root/f'game_{number:02d}';directory.mkdir()
        cards=[{'card_id':'commander','card_name':'Commander','quantity':1},
               {'card_id':'land','card_name':'Land','quantity':99}]
        write(directory/'strategy_snapshot.json',{'decks':[{'deck_id':'reaminatour','commander_card_id':'commander','cards':cards}]})
        write(directory/'game_config.json',{'game':number,'seed':number,'learning_enabled':False})
        write(directory/'status.json',{'state':'complete' if complete else 'need_decision'})
        (directory/'decisions.jsonl').write_text('{}\n')
        if not complete:return directory
        seal={'game':number,'seed':number,'result':{'winner':winner,'events':1,'terminal':'rules_winner' if winner else 'draw'},
              'decision_count':1,'decisions_sha256':hashlib.sha256((directory/'decisions.jsonl').read_bytes()).hexdigest(),
              'strategy_snapshot_sha256':hashlib.sha256((directory/'strategy_snapshot.json').read_bytes()).hexdigest()}
        seal['terminal_fingerprint']='terminal-'+hashlib.sha256(json.dumps(seal,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        write(directory/'terminal_result.json',seal)
        write(directory/'postgame_learning/skipped.json',{'state':'skipped_by_configuration','terminal_fingerprint':seal['terminal_fingerprint']})
        return directory

    def test_rates_use_per_game_union_and_draws_in_denominator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for n,winner in enumerate(('Reaminatour','Omo',None),1):self.fixture(root,n,winner)
            self.fixture(root,4,complete=False)
            def sets(directory,seal):
                return ({'Commander','Land'},{'Commander','Land'}) if seal['game']==1 else ({'Land'},set())
            with patch('edh_gauntlet.cardwise_report.observations',side_effect=sets):value=report(root)
            rows={r['card']:r for r in value['rows']}
            self.assertEqual(value['completed_games'],3);self.assertEqual(value['pending_games'],1)
            self.assertEqual(value['deck_size'],100);self.assertTrue(rows['Commander']['commander'])
            self.assertEqual(rows['Land']['games_seen'],3);self.assertAlmostEqual(rows['Land']['won_if_seen'],100/3)
            self.assertEqual(rows['Land']['games_etb_cast'],1);self.assertEqual(rows['Land']['won_if_cast'],100)

    def test_no_completed_games_has_full_list_and_blank_rates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root,1,complete=False)
            with patch('edh_gauntlet.cardwise_report.observations') as replay:
                value=report(root);replay.assert_not_called()
            self.assertEqual(value['deck_size'],100)
            self.assertTrue(all(r['won_if_seen'] is None and r['won_if_cast'] is None for r in value['rows']))

    def test_bad_prefix_or_missing_learning_receipt_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=self.fixture(root,1);b=self.fixture(root,2)
            (a/'decisions.jsonl').write_text('changed\n');(b/'postgame_learning/skipped.json').unlink()
            with patch('edh_gauntlet.cardwise_report.observations') as replay:
                value=report(root);replay.assert_not_called()
            self.assertEqual(value['completed_games'],0);self.assertEqual(len(value['excluded_games']),2)

    def test_real_catalog_includes_all_100_cards_and_commander(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows=deck_rows(Path(tmp))
            self.assertEqual(sum(r['quantity'] for r in rows),100)
            self.assertEqual(rows[0]['card'],'Aminatou, Veil Piercer');self.assertTrue(rows[0]['commander'])

    def test_replay_result_must_match_sealed_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=self.fixture(Path(tmp),1);seal=eligible_game(directory)
            output={'decisions_sha256':seal['decisions_sha256'],'accepted':1,'state':'terminal','result':{'winner':'Omo'},'seen':[],'cast':[]}
            with patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(output))):
                with self.assertRaisesRegex(ValueError,'terminal result'):observations(directory,seal)
            self.assertFalse((Path(tmp)/'dashboard/cardwise/game_01.json').exists())

    def test_adjudicated_draw_requires_bound_receipt_and_replayed_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=self.fixture(Path(tmp),1);seal=eligible_game(directory)
            seal['result']={'winner':None,'terminal':'adjudicated_draw','events':5,'rules_reconciliation_id':'audit'}
            output={'decisions_sha256':seal['decisions_sha256'],'accepted':1,'state':'unanswered','events':4,'seen':['Land'],'cast':[]}
            receipt={'terminal_fingerprint':seal['terminal_fingerprint'],'response_sha256':'audit','retained':1,'verdict':'rules_draw'}
            write(directory/'rules_reconciliation.json',receipt)
            with patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(output))):
                self.assertEqual(observations(directory,seal),({'Land'},set()))
                # Invalidate cache as a source change would, then reject a stale adjudication.
                write(directory/'rules_reconciliation.json',{**receipt,'response_sha256':'wrong'})
                with patch('edh_gauntlet.cardwise_report.rules_signature',return_value='new rules'):
                    with self.assertRaisesRegex(ValueError,'adjudicated rules draw'):observations(directory,seal)

if __name__=='__main__':unittest.main()
