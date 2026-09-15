"""Validate a proposed fresh primitive-engine launch without creating a cohort.

There is deliberately no fallback to the legacy campaign initializer. Once the
rules and host-adapter gates exist, a launch must consume this exact bound intent.
"""
import argparse
import hashlib
import json
from pathlib import Path
from .paths import PROJECT_ROOT
from .rules_admission import readiness
from .rules_bundle import deck_coverage
from .rules_state import RulesViolation


def preflight(destination, *, root=PROJECT_ROOT, games=20, seed_start=2026090901,
              max_rounds=16, learning='disabled'):
    root=Path(root);destination=Path(destination).resolve()
    if destination.exists():raise RulesViolation('Fresh launch destination already exists; never overwrite a cohort')
    if any(type(value) is not int or value<1 for value in (games,seed_start,max_rounds)):
        raise RulesViolation('Game count, seed and round limit must be positive integers')
    if learning not in {'enabled','disabled'}:raise RulesViolation('Choose an explicit learning policy')
    report=readiness(root);coverage=deck_coverage(root)
    unmapped=sorted({row['card_id'] for deck in coverage['decks'] for row in deck['entries'] if not row['program_definition']})
    requested={'cohort':str(destination),'rules_engine':'primitives-v1','games':games,
        'seed_start':seed_start,'max_rounds':max_rounds,'learning_enabled':learning=='enabled',
        'planning_contract':4,'agent_architecture':1,'async_diplomacy':1,'short_term_sol_fast':1,
        'rules_implementation_sha256':report['implementation_sha256'],
        'catalog_sha256':report['catalog_sha256'],'decks_sha256':coverage['decks_sha256'],
        'authored_bundle_sha256':hashlib.sha256((root/'data/rules/primitive_cards.json').read_bytes()).hexdigest()}
    intent_hash=hashlib.sha256(json.dumps(requested,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'schema':1,'status':'blocked_rules_migration','initialized':False,'intent_sha256':intent_hash,
        'requested':requested,'authored_unique_cards':coverage['authored_unique_cards'],
        'unreviewed_program_count':len(unmapped),'unreviewed_programs':unmapped,
        'blockers':report['blockers'],
        'launch_command':None,'adapter_status':'No production primitive-engine campaign/host adapter is registered'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort',type=Path,required=True)
    parser.add_argument('--root',type=Path,default=PROJECT_ROOT)
    parser.add_argument('--games',type=int,default=20);parser.add_argument('--seed-start',type=int,default=2026090901)
    parser.add_argument('--max-rounds',type=int,default=16)
    parser.add_argument('--learning',choices=['enabled','disabled'],required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=preflight(args.cohort,root=args.root,games=args.games,seed_start=args.seed_start,
                     max_rounds=args.max_rounds,learning=args.learning)
    if args.output.resolve()==args.cohort.resolve() or args.cohort.resolve() in args.output.resolve().parents:
        raise RulesViolation('Store the blocked preflight outside the proposed cohort')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ('status','initialized','authored_unique_cards','unreviewed_program_count','intent_sha256')},indent=2))


if __name__=='__main__':main()
