import json,tempfile,unittest
from pathlib import Path
from edh_gauntlet.dashboard_presenter import decisions,decision_markdown,published_short_term

class PresenterTests(unittest.TestCase):
    def test_labels_reasons_pass_and_structured_choices(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);rows=[{'decision_id':'D1','actor':'A','chosen_label':'CAST Body Double','rationale':'Keep the engine running.'},{'decision_id':'D2','actor':'B','chosen_label':None},{'decision_id':'D3','actor':'B','choice_value':{'a':['b'],'c':[]}}, {'decision_id':'D4','actor':'B','chosen_labels':['Draw a card','Gain life']}]
            (p/'decisions.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
            result=decisions(p)
            self.assertEqual([r['action'] for r in result],['Cast Body Double','Pass','Declare blocks for 2 attackers','Draw a card; Gain life'])
            text=decision_markdown(result,2)
            self.assertIn('## D1 — A',text);self.assertIn('Reason: Keep the engine running.',text)
            rows.pop();(p/'decisions.jsonl').write_text(json.dumps(rows[0]))
            self.assertEqual(len(decisions(p)),1)
    def test_only_deciding_seats_short_term_prose_is_selected(self):
        value={'minsc_and_boo':'**Short-term plan**\nsource metadata\n\n> Attack after protection.\n> Keep removal.\n\n**Long-term plan**\n> Long term secret\n'}
        self.assertEqual(published_short_term(value,'Minsc & Boo'),'Attack after protection.\nKeep removal.')
        self.assertEqual(published_short_term(value,'Omo'),'')
