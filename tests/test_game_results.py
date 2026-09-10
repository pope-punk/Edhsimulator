import tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from edh_gauntlet.runtime_store import read,write,identity
from edh_gauntlet.game_results import evidence,rows,narrate_pending

class ResultsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.d=self.root/'game_01'
        write(self.d/'status.json',{'state':'complete'})
        write(self.d/'terminal_result.json',{'game':1,'terminal_fingerprint':'seal','decision_count':20,'result':{'winner':'A','seating':['A','B'],'reason':'Recorded finish'}})
    def test_outcome_and_stale_narrative(self):
        facts=evidence(self.d);write(self.d/'supervisor_recap.json',{'state':'complete','evidence_id':identity(facts),'narrative':'A won.'})
        result=rows(self.root)[0];self.assertEqual(result['losers'],['B']);self.assertEqual(result['narrative'],'A won.')
        write(self.d/'rules_work_items.json',{'issues':[{'reason':'Needs review'}]})
        self.assertIsNone(rows(self.root)[0]['narrative']);self.assertTrue(rows(self.root)[0]['rules_review_pending'])
    def test_supervisor_writes_once_per_evidence(self):
        worker=Mock();worker.root=self.root;worker.directory=self.root/'supervisor';worker.config.return_value={'recaps':True}
        def command(args,*unused,**kwargs):
            self.assertIn('read-only',args);self.assertIn('no tools',kwargs['prompt']);write(Path(args[args.index('-o')+1]),{'narrative':'A won by the recorded finish.'})
        worker.command.side_effect=command
        narrate_pending(worker);narrate_pending(worker);worker.command.assert_called_once()
        self.assertEqual(rows(self.root)[0]['author'],'Supervisor agent')
    def test_failed_authoring_is_not_fabricated_or_retried(self):
        worker=Mock();worker.root=self.root;worker.directory=self.root/'supervisor';worker.config.return_value={'recaps':True};worker.command.side_effect=RuntimeError('offline')
        narrate_pending(worker);narrate_pending(worker);worker.command.assert_called_once();self.assertIsNone(rows(self.root)[0]['narrative'])
