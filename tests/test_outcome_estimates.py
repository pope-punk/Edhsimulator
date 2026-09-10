from test_game_results import ResultsTests
from edh_gauntlet.outcome_estimates import binding,publish,current
from edh_gauntlet.runtime_store import write,read

class EstimateTests(ResultsTests):
    def test_estimate_is_separate_and_invalidates_on_changed_evidence(self):
        write(self.d/'rules_work_items.json',{'issues':[{'reason':'defect'}]})
        before=(self.d/'terminal_result.json').read_bytes()
        value={**binding(self.d),'estimated_winner':'B','confidence':'low','rationale':'Possible advantage','uncertainty':'Counterfactual play is unknown'}
        publish(self.d,value,'Test reviewer')
        self.assertEqual(current(self.d)['estimated_winner'],'B')
        self.assertEqual((self.d/'terminal_result.json').read_bytes(),before)
        self.assertFalse(current(self.d)['included_in_verified_win_rates'])
        write(self.d/'rules_work_items.json',{'issues':[{'reason':'changed'}]})
        self.assertIsNone(current(self.d))
    def test_unknown_winner_rejected(self):
        write(self.d/'rules_work_items.json',{'issues':[{'reason':'defect'}]})
        with self.assertRaises(ValueError):publish(self.d,{**binding(self.d),'estimated_winner':'not a seat'},'reviewer')
