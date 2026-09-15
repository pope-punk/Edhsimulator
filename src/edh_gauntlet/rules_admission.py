"""Production readiness audit for the experimental rules kernel.

A passing interaction fixture is not a whole-card certificate. This module
provides an explicit rejecting production entrypoint while migration is partial;
it never interprets legacy catalog support labels as primitive coverage.
"""
import argparse
import hashlib
import json
from pathlib import Path
from .catalog import load_catalog
from .paths import PROJECT_ROOT
from .rules_program import encode
from .rules_identity import IMPLEMENTATION_ID
from .rules_kernel import RulesKernel
from .rules_durable import DurableRulesAdapter
from .rules_scenarios import fixture_programs
from .rules_state import RulesState, RulesViolation
from .rules_bundle import load_reviewed, deck_coverage


# These identify authored fixture definitions, not named runtime execution paths.
FIXTURE_BINDINGS = {
    'animate-dead': 'animate',
    'body-double': 'body-double',
    'evolution-sage': 'sage',
    'felidar-guardian': 'felidar',
    'remand': 'remand',
    'starfield-of-nyx': 'starfield',
    'uro-titan-of-nature-s-wrath': 'uro',
}

PRODUCTION_BLOCKERS = (
    'No complete reviewed executable bundle for every face and clause in the fixed decks',
    'Casting and activation still lack the full cost/announcement vocabulary and restricted mana; concessions, loss/win exceptions and planeswalker/battle combat are incomplete',
    'Ability/control/color layers, prevention, full replacement semantics and state-based actions are incomplete',
    'Hidden-information projections and production action routing are not bound to this kernel',
    'Historical runtime selection, production replay parity and deployment gates are incomplete',
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def readiness(root=PROJECT_ROOT):
    root = Path(root)
    catalog_path = root / 'data/catalog/cards.json'
    catalog = tuple(load_catalog(catalog_path))
    programs = {program.definition_id: program for program in fixture_programs()}
    reviewed = load_reviewed(root)
    cards = []
    for card in catalog:
        program_id = FIXTURE_BINDINGS.get(card.card_id)
        facts = [{'face_id': face.face_id, 'oracle_text': face.oracle_text,
                  'type_line': face.type_line, 'mana_cost': face.mana_cost,
                  'power': face.power, 'toughness': face.toughness,
                  'loyalty': face.loyalty, 'loyalty_variable': face.loyalty_variable}
                 for face in card.faces]
        cards.append({'card_id': card.card_id, 'name': card.name,
            'source_facts_sha256': digest(facts), 'face_count': len(facts),
            'status': 'program_authored' if card.card_id in reviewed else 'fixture_only' if program_id else 'unmapped',
            'authored_program': reviewed[card.card_id]['program'].definition_id if card.card_id in reviewed else None,
            'authored_program_sha256': digest(encode(reviewed[card.card_id]['program'])) if card.card_id in reviewed else None,
            'fixture_program': program_id,
            'fixture_sha256': digest(encode(programs[program_id])) if program_id else None,
            'production_certified': False})
    return {'schema': 1, 'production_ready': False, 'implementation_sha256': IMPLEMENTATION_ID,
        'kernel_checkpoint_schema': RulesKernel.CHECKPOINT_SCHEMA, 'state_checkpoint_schema': RulesState.CHECKPOINT_SCHEMA,
        'actor_packet_schema':1,'adapter_replay_schema':1,'durable_journal_schema':DurableRulesAdapter.SCHEMA,'production_host_bound':False,
        'catalog_sha256': hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        'fixture_bundle_sha256': digest([encode(p) for p in sorted(programs.values(), key=lambda p: p.definition_id)]),
        'card_count': len(cards), 'fixture_card_count': sum(row['status'] == 'fixture_only' for row in cards),
        'authored_card_count':len(reviewed),'unreviewed_program_count':len(cards)-len(reviewed),
        'certified_card_count': 0, 'blockers': list(PRODUCTION_BLOCKERS), 'cards': cards}


def require_production_ready(root=PROJECT_ROOT):
    report = readiness(root)
    raise RulesViolation('Experimental kernel is not admitted for production: ' + '; '.join(report['blockers']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=PROJECT_ROOT)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--deck-coverage-output', type=Path)
    args = parser.parse_args()
    report = readiness(args.root)
    if args.deck_coverage_output:
        args.deck_coverage_output.parent.mkdir(parents=True,exist_ok=True)
        args.deck_coverage_output.write_text(json.dumps(deck_coverage(args.root),indent=2)+'\n')
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'cards'}, indent=2))


if __name__ == '__main__':
    main()
