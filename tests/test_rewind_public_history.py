import tempfile,unittest
from pathlib import Path
from edh_gauntlet import campaign,pilot_handoff


class PublicHistoryRewindTests(unittest.TestCase):
    def test_retained_public_inputs_survive_but_old_contexts_and_future_posts_do_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);d=root/'game_01/continuity';d.mkdir(parents=True)
            rows=[{'decision_id':'D1'},{'decision_id':'D2'}]
            old=pilot_handoff.session_descriptor(root,1,'A',rows[:1])
            future=pilot_handoff.session_descriptor(root,1,'A',rows)
            campaign.write_json(d/'diplomacy_posts.json',[
                {'author':'A','text':'retained','source_session':old},
                {'author':'A','text':'future','source_session':future}])
            campaign.write_json(d/'combo_deliveries.json',[{'actor':'A','proposal':{'proof':'retained'},'source_session':old}])
            retained=campaign._retained_public_history(root,1,rows[:1])
            pilot_handoff.invalidate_sessions(root,1,'rewind')
            campaign._rebind_public_history(root,1,rows[:1],retained)
            self.assertFalse(pilot_handoff.can_resume_session(old,root,1,'A',rows[:1]))
            posts=campaign.read_json(d/'diplomacy_posts.json')
            self.assertEqual([v['text'] for v in posts],['retained'])
            self.assertTrue(pilot_handoff.can_resume_session(posts[0]['source_session'],root,1,'A',rows[:1]))
            self.assertEqual(campaign.read_json(d/'combo_deliveries.json')[0]['proposal'],{'proof':'retained'})
            with self.assertRaises(SystemExit):campaign._rebind_public_history(root,1,[{'decision_id':'changed'}],retained)
