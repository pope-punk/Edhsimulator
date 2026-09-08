"""Static release gates for the rebuilt four-deck runtime.

These checks validate the seams between the parent card catalog, deck-specific
strategy profiles, and the legacy-compatible rules adapter. They do not attempt
to replace behavioral tests; a green report means the generated hierarchy is
internally coherent and the official pilot layer remains strategy-free.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Mapping

from . import engine
from .ability_registry import CARD_ABILITIES
from .catalog import load_catalog
from .event_visibility import EVENT_VISIBILITY_POLICY
from .strategy import load_strategy_state


from .paths import PROJECT_ROOT
DECK_PROFILE_IDS = {
    "Reaminatour": "reaminatour",
    "Minsc & Boo": "minsc_boo",
    "Omo": "omo",
    "Elenda": "elenda",
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


def _catalog_deck_rows(catalog: Any, deck: str) -> list[tuple[str, int]]:
    return [(card.name, occurrence.quantity) for card, occurrence in catalog.deck_entries(deck)]


def _runtime_deck_rows(deck: str) -> list[tuple[str, int]]:
    return [(card.name, card.quantity) for card in engine.DECKDEFS[deck]]


def _literal_event_types(*sources: str) -> set[str]:
    logged: set[str] = set()
    for source in sources:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "log" or not node.args:
                continue
            event_type = node.args[0]
            if isinstance(event_type, ast.Constant) and isinstance(event_type.value, str):
                logged.add(event_type.value)
    return logged


def release_report(project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    catalog = load_catalog()
    catalog_report = catalog.validation_report()
    strategy = load_strategy_state()
    strategy_errors = strategy.validation_errors(catalog_card_ids=catalog.by_id)
    source_directory=project_root/'src/edh_gauntlet'
    if not source_directory.is_dir():source_directory=Path(__file__).resolve().parent
    engine_source = (source_directory / "engine.py").read_text(
        encoding="utf-8"
    )
    referee_source = (source_directory / "referee.py").read_text(
        encoding="utf-8"
    )
    scheduler_source = (source_directory / 'scheduler.py').read_text(encoding='utf-8')
    literal_event_types = _literal_event_types(engine_source, referee_source, scheduler_source)
    visibility_event_types = set(EVENT_VISIBILITY_POLICY)
    missing_event_visibility = sorted(literal_event_types - visibility_event_types)
    unused_event_visibility = sorted(visibility_event_types - literal_event_types)

    catalog_decks = {
        deck: _catalog_deck_rows(catalog, deck) for deck in DECK_PROFILE_IDS
    }
    runtime_decks = {deck: _runtime_deck_rows(deck) for deck in DECK_PROFILE_IDS}
    catalog_counts = {
        deck: sum(quantity for _, quantity in rows) for deck, rows in catalog_decks.items()
    }
    runtime_counts = {
        deck: sum(quantity for _, quantity in rows) for deck, rows in runtime_decks.items()
    }
    strategy_counts = {
        deck: strategy.deck(profile_id).card_count
        for deck, profile_id in DECK_PROFILE_IDS.items()
    }
    profile_parity: dict[str, bool] = {}
    for deck, profile_id in DECK_PROFILE_IDS.items():
        catalog_quantities = dict(catalog_decks[deck])
        profile = strategy.deck(profile_id)
        profile_quantities = {entry.card_name: entry.quantity for entry in profile.cards}
        profile_parity[deck] = profile_quantities == catalog_quantities

    missing_creature_stats = sorted(
        f"{card.name} / {face.name}"
        for card in catalog.cards
        for face in card.faces
        if face.has_type("Creature") and (face.power is None or face.toughness is None)
    )
    missing_planeswalker_loyalty = sorted(
        f"{card.name} / {face.name}"
        for card in catalog.cards
        for face in card.faces
        if face.has_type("Planeswalker")
        and face.loyalty is None
        and face.loyalty_variable is None
    )
    catalog_registered = {
        card.name: len(catalog.registered_abilities(card.name))
        for card in catalog.cards
        if catalog.registered_abilities(card.name)
    }
    runtime_registered = {name: len(rows) for name, rows in CARD_ABILITIES.items()}
    matrix = strategy.role_presence_matrix()
    matrix_columns = {profile_id for profile_id in DECK_PROFILE_IDS.values()}
    role_matrix_valid = bool(matrix) and all(
        set(row) == matrix_columns and set(row.values()) <= {0, 1}
        for row in matrix.values()
    )

    normalized_engine = "".join(engine_source.split())
    forbidden_pilot_tokens = [
        token
        for token in ("StrategicReferee", "def choose(", ".choose(", "STRATEGIC_FALLBACK")
        if token in referee_source
    ]
    retired_literal_markers = [
        marker
        for marker in ("PT={", "KEYWORDS={", "LAND_COLOR_HINTS={", "FETCHES={", "MANA_ROCKS={")
        if marker in normalized_engine
    ]
    baseline = {name for name, _ in catalog_decks["Reaminatour"]}

    checks = {
        "catalog_valid": catalog_report.ok,
        "four_100_card_decks": (
            len(catalog_counts) == 4
            and all(count == 100 for count in catalog_counts.values())
            and runtime_counts == catalog_counts
            and strategy_counts == catalog_counts
        ),
        "runtime_deck_order_matches_catalog": runtime_decks == catalog_decks,
        "strategy_profiles_match_catalog": all(profile_parity.values()) and not strategy_errors,
        "role_presence_matrix_generated": role_matrix_valid,
        "registered_actions_catalog_backed": runtime_registered == catalog_registered,
        "printed_creature_stats_complete": not missing_creature_stats,
        "printed_planeswalker_loyalty_complete": not missing_planeswalker_loyalty,
        "runtime_uses_catalog_deck_source": "DECKDEFS=parse_reference" not in normalized_engine,
        "duplicated_runtime_classification_literals_retired": not retired_literal_markers,
        "latest_reaminatour_baseline": {
            "Liliana the Faultless", "Vesperlark", "The Meathook Massacre"
        } <= baseline,
        "official_layer_has_no_action_chooser": not forbidden_pilot_tokens,
        "death_grasp_is_not_grouped_with_multiplayer_drains": (
            "{'Exsanguinate','Debt to the Deathless','Death Grasp'}" not in engine_source
        ),
        "event_visibility_policy_complete": (
            not missing_event_visibility and not unused_event_visibility
        ),
    }
    return {
        "schema": 2,
        **checks,
        "catalog_counts": catalog_counts,
        "runtime_counts": runtime_counts,
        "strategy_counts": strategy_counts,
        "catalog_audit": _jsonable(catalog.audit),
        "strategy_revision": strategy.freeze().to_dict(),
        "strategy_errors": list(strategy_errors),
        "profile_parity": profile_parity,
        "missing_creature_stats": missing_creature_stats,
        "missing_planeswalker_loyalty": missing_planeswalker_loyalty,
        "forbidden_hits": forbidden_pilot_tokens,
        "retired_literal_hits": retired_literal_markers,
        "missing_event_visibility": missing_event_visibility,
        "unused_event_visibility": unused_event_visibility,
        "ok": all(checks.values()),
    }


__all__ = ["DECK_PROFILE_IDS", "release_report"]
