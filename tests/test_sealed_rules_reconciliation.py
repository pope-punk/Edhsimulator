import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from edh_gauntlet.runtime_store import read,write

spec=importlib.util.spec_from_file_location('sealed_rules',Path(__file__).parents[1]/'tools/reconcile_sealed_rules.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class SealedRulesTests(unittest.TestCase):
    def test_interrupted_install_restores_original_seal_tape_and_routing(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);transaction=root/'transaction';original=transaction/'original_game';original.mkdir(parents=True)
            write(original/'terminal_result.json',{'original':True});(original/'decisions.jsonl').write_text('original accepted choices\n')
            current=root/'game_02';current.mkdir();write(current/'terminal_result.json',{'replacement':True})
            write(transaction/'transaction.json',{'state':'prepared','game':2})
            for name in ('cohort.json','NEXT_ACTION.json'):
                write(transaction/name,{'game':3});write(root/name,{'game':2})
            write(transaction/'quarantine_registry.json',{'original':True});registry=root/'registry.json';write(registry,{'new':True})
            with patch.object(module.quarantine,'registry_path',return_value=registry):module.rollback(root,transaction)
            self.assertEqual(read(current/'terminal_result.json'),{'original':True})
            self.assertEqual((current/'decisions.jsonl').read_text(),'original accepted choices\n')
            self.assertEqual(read(root/'NEXT_ACTION.json'),{'game':3})
            self.assertEqual(read(registry),{'original':True})
            self.assertEqual(read(transaction/'transaction.json')['state'],'rolled_back')
            self.assertTrue((original/'terminal_result.json').exists())
    def test_committed_retry_returns_receipt_without_replaying_or_mutating(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);response={'game':2};tx=root/'rules_reconciliations'/module.fingerprint(response)
            write(tx/'transaction.json',{'state':'committed'});write(tx/'receipt.json',{'retained':110})
            with patch.object(module,'validate',side_effect=AssertionError('must not replay')):
                self.assertEqual(module.reconcile(root,response,True),{'retained':110})
    def test_learning_enabled_historical_correction_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);write(root/'HOST_PAUSED.json',{'reason':'rules_audit'})
            with patch.object(module.campaign,'load_manifest',return_value={'active_game':3,'learning_enabled':True}):
                with self.assertRaisesRegex(ValueError,'Published learning'):module.validate(root,{'game':2})
