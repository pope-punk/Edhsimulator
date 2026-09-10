import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from edh_gauntlet import static_standing as standing,component_store as components
from edh_gauntlet.runtime_store import write,read,put

class StandingEpochTests(unittest.TestCase):
    def test_same_doctrine_installs_again_after_branch_invalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);d=components.directory(root,1);target=components.index_path(d,'A')
            write(root/'game_01/standing_plan_snapshot.json',{'pilots':{'A':{'standing_plan':'Frozen doctrine'}}})
            with patch.object(components,'current',return_value={}),patch('edh_gauntlet.planner_runtime._compatible',return_value=True),patch.object(components,'prepare') as prepare:
                for epoch in ('old','new','new'):
                    snapshot=put(d/'snapshots',{'source_session':{'key':epoch},'event_seq':1})
                    prepare.return_value=({'standing':epoch},['standing'])
                    standing.install(root,1,'A',snapshot)
                    self.assertEqual(read(target),{'standing':epoch})
            self.assertEqual(len(list((d/'component_publications').glob('*.json'))),2)
