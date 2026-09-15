import tempfile,unittest
from pathlib import Path
from edh_gauntlet import operator_view
from edh_gauntlet.runtime_store import write

class OperatorViewTests(unittest.TestCase):
    def test_historical_checkpoint_and_publication_cannot_replace_current_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);write(root/'OPERATOR_VIEW.json',{'enabled':True});write(root/'cohort.json',{'active_game':3})
            path=operator_view.path(root,'Elenda');path.parent.mkdir()
            original='Game 03\n'+operator_view.START+'\nCurrent plan\n'+operator_view.END
            path.write_text(original)
            operator_view.checkpoint(root,{'game':2},object(),None,110,'complete')
            operator_view.refresh_plans(root,2)
            self.assertEqual(path.read_text(),original)
            self.assertTrue(operator_view.is_current(root,3))
