import tempfile, unittest
from pathlib import Path
from edh_gauntlet.dashboard import Dashboard

class DashboardTests(unittest.TestCase):
    def test_rejects_unsafe_run_id(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Dashboard(Path(directory),'secret','python')
            with self.assertRaises(ValueError):app.root('../escape')

    def test_empty_run_list(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(Dashboard(Path(directory),'secret','python').list_runs(),[])

if __name__=='__main__':unittest.main()
