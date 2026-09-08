"""Read one completed game's actor-projected review, without repeated catalogs."""
import argparse
import json
from read_review_packet import view

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('evidence')
args = parser.parse_args()
from pathlib import Path
v = view(Path(args.evidence))
req = v['requirements']
out = {
    'viewer': v['viewer'], 'critical': req['critical_decisions'],
    'rules_issues': req['rules_issue_ids'],
    'plans': [{k: value for k, value in p.items() if k != 'standing_plan'}
              for p in v['plans'].values()],
    'decisions': [{k: d.get(k) for k in
                   ('decision_id', 'kind', 'phase', 'chosen', 'rationale', 'scheduler')}
                  for d in v['decisions']],
    'notes': v['notes'],
    'cards': {k: v['cards'][k] for k in req['card_review_cards']},
    'rejections': v['rejected_answers'],
}
print(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
