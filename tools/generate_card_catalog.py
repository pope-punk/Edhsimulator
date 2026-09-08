#!/usr/bin/env python3
"""Generate the canonical card-first catalog from the frozen pod reference.

This is intentionally a migration/generation tool, not a runtime Oracle parser.
It consumes the full four-deck reference plus the frozen card-first combat,
keyword, mana, land, and activated-ability annotations. The resulting JSON is
the runtime source of truth and is byte-for-byte deterministic.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from edh_gauntlet.catalog import (  # noqa: E402
    CATALOG_SCHEMA_VERSION,
    canonical_card_id,
    catalog_from_payload,
    mana_value,
)


DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "catalog" / "cards.json"
DEFAULT_REFERENCE = PROJECT_ROOT / "data" / "reference" / "four_deck_oracle.txt"
DEFAULT_ANNOTATIONS = PROJECT_ROOT / "data" / "reference" / "card_catalog_annotations.json"
COLOR_ORDER = "WUBRGC"
SUPERTYPES = {"Basic", "Legendary", "Ongoing", "Snow", "World"}
CARD_TYPES = {
    "Artifact",
    "Battle",
    "Creature",
    "Enchantment",
    "Instant",
    "Kindred",
    "Land",
    "Planeswalker",
    "Sorcery",
    "Tribal",
}
DECK_HEADINGS = {
    "Reaminatour": "REAMINATOUR — AMINATOU, VEIL PIERCER",
    "Minsc & Boo": "MINSC & BOO, TIMELESS HEROES",
    "Omo": "OMO, QUEEN OF VESUVA",
    "Elenda": "ELENDA, SAINT OF DUSK",
}
DECK_ORDER = tuple(DECK_HEADINGS)


@dataclass(frozen=True)
class ReferenceCard:
    name: str
    mana_cost: str
    type_line: str
    text: str
    quantity: int
    deck: str


def parse_reference(path: Path) -> dict[str, list[ReferenceCard]]:
    """Parse the frozen Oracle reference without importing the runtime engine."""

    text = path.read_text(encoding="utf-8")
    decks: dict[str, list[ReferenceCard]] = {}
    pattern = re.compile(
        r"^\[(\d+)\]\s+(\d+)x\s+(.+?)\n-+\n"
        r"Mana cost:\s*(.*?)\nType line:\s*(.*?)\nRules text:\n"
        r"(.*?)(?=\n\[\d+\]|\n\n={20,}|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    for deck, heading in DECK_HEADINGS.items():
        start = text.index(heading)
        later = [
            location
            for other in DECK_HEADINGS.values()
            if (location := text.find(other, start + len(heading))) != -1
        ]
        section = text[start : min(later) if later else len(text)]
        cards = [
            ReferenceCard(
                name=match.group(3).strip(),
                mana_cost=match.group(4).strip(),
                type_line=match.group(5).strip(),
                text=match.group(6).strip(),
                quantity=int(match.group(2)),
                deck=deck,
            )
            for match in pattern.finditer(section)
        ]
        slots = sum(card.quantity for card in cards)
        if slots != 100:
            raise ValueError(f"{deck} parsed {slots} physical cards, expected 100")
        decks[deck] = cards
    return decks


def load_annotations(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("cards"), dict):
        raise ValueError(f"unsupported catalog annotations: {path}")
    return {str(card_id): dict(row) for card_id, row in payload["cards"].items()}


def _ordered_colors(colors: Iterable[str]) -> list[str]:
    values = set(colors)
    return [color for color in COLOR_ORDER if color in values]


def _mana_symbols(text: str) -> set[str]:
    colors: set[str] = set()
    for symbol in re.findall(r"\{([^}]+)\}", text):
        for part in symbol.upper().split("/"):
            if part in "WUBRGC":
                colors.add(part)
    return colors


def _type_parts(type_line: str) -> tuple[list[str], list[str], list[str]]:
    if " — " in type_line:
        left, right = type_line.split(" — ", 1)
    else:
        left, right = type_line, ""
    supertypes: list[str] = []
    types: list[str] = []
    for word in left.split():
        if word in SUPERTYPES:
            supertypes.append(word)
        elif word in CARD_TYPES:
            types.append(word)
        else:
            # A future card type should remain visible instead of being silently
            # dropped merely because this migration tool predates it.
            types.append(word)
    return supertypes, types, right.split() if right else []


def _clean_oracle(text: str) -> str:
    lines = [line.strip() for line in text.strip().splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _display_face_name(marker_name: str) -> str:
    """Turn all-caps reference headings into conventional display casing."""

    words = marker_name.lower().split()
    minor = {"a", "an", "and", "at", "for", "from", "in", "of", "on", "or", "the", "to"}
    rendered: list[str] = []
    for index, word in enumerate(words):
        titled = "-".join(part[:1].upper() + part[1:] for part in word.split("-"))
        if index and word in minor:
            titled = word
        rendered.append(titled)
    return " ".join(rendered)


def _face_names(card_name: str, oracle_text: str, face_count: int) -> list[str]:
    if " // " in card_name:
        names = card_name.split(" // ")
    else:
        names = []
        for line in oracle_text.splitlines():
            match = re.match(r"^(?:FRONT|BACK)\s+—\s+(.+)$", line.strip(), re.IGNORECASE)
            if match:
                names.append(_display_face_name(match.group(1).strip()))
        if names:
            # The deck entry is the canonical spelling of the front face.
            names[0] = card_name
    if not names:
        names = [card_name]
    if len(names) < face_count:
        names.extend(f"{card_name} face {index + 1}" for index in range(len(names), face_count))
    return names[:face_count]


def _face_oracle_texts(oracle_text: str, face_names: list[str]) -> list[str]:
    if len(face_names) == 1:
        return [_clean_oracle(oracle_text)]

    lines = oracle_text.splitlines()
    markers: list[tuple[int, str]] = []
    by_folded_name = {name.casefold(): name for name in face_names}
    for index, line in enumerate(lines):
        stripped = line.strip()
        match = re.match(r"^(?:FRONT|BACK)\s+—\s+(.+)$", stripped, re.IGNORECASE)
        if match:
            marker_name = _display_face_name(match.group(1).strip())
            markers.append((index, marker_name))
        elif stripped.casefold() in by_folded_name:
            markers.append((index, by_folded_name[stripped.casefold()]))

    if len(markers) < len(face_names):
        # Preserve all information on the front rather than inventing a split.
        return [_clean_oracle(oracle_text), *["" for _ in face_names[1:]]]

    result: list[str] = []
    marker_by_name = {name.casefold(): pos for pos, name in markers}
    sorted_markers = sorted(markers)
    for face_name in face_names:
        start = marker_by_name.get(face_name.casefold())
        if start is None:
            result.append("")
            continue
        end = next((pos for pos, _ in sorted_markers if pos > start), len(lines))
        result.append(_clean_oracle("\n".join(lines[start + 1 : end])))
    return result


def _build_faces(card: ReferenceCard, annotation: dict[str, Any]) -> list[dict[str, Any]]:
    costs = [part.strip() for part in card.mana_cost.split(" // ")]
    type_lines = [part.strip() for part in card.type_line.split(" // ")]
    face_count = max(len(costs), len(type_lines), 1)
    costs.extend("—" for _ in range(face_count - len(costs)))
    type_lines.extend(type_lines[-1] for _ in range(face_count - len(type_lines)))
    names = _face_names(card.name, card.text, face_count)
    texts = _face_oracle_texts(card.text, names)
    combat = annotation.get("combat") or {}
    stats = (
        (int(combat["power"]), int(combat["toughness"]))
        if combat.get("power") is not None and combat.get("toughness") is not None
        else None
    )
    engine_keywords = sorted(str(item) for item in annotation.get("keywords", ()))
    face_annotations = annotation.get("faces") or {}
    faces: list[dict[str, Any]] = []
    used_ids: Counter[str] = Counter()
    for index, (name, cost, type_line, oracle) in enumerate(zip(names, costs, type_lines, texts)):
        base_face_id = canonical_card_id(name)
        used_ids[base_face_id] += 1
        face_id = base_face_id if used_ids[base_face_id] == 1 else f"{base_face_id}-{used_ids[base_face_id]}"
        supertypes, types, subtypes = _type_parts(type_line)
        face_annotation = face_annotations.get(face_id, {})
        default_power = stats[0] if index == 0 and stats is not None else None
        default_toughness = stats[1] if index == 0 and stats is not None else None
        faces.append(
            {
                "face_id": face_id,
                "name": name,
                "mana_cost": cost,
                "mana_value": mana_value(cost),
                "type_line": type_line,
                "supertypes": supertypes,
                "types": types,
                "subtypes": subtypes,
                "oracle_text": oracle,
                "colors": _ordered_colors(_mana_symbols(cost) - {"C"}),
                "power": face_annotation.get("power", default_power),
                "toughness": face_annotation.get("toughness", default_toughness),
                "loyalty": face_annotation.get("loyalty"),
                "loyalty_variable": face_annotation.get("loyalty_variable"),
                "keywords": engine_keywords if index == 0 else [],
            }
        )
    return faces


def _infer_events(text: str, kind: str) -> Optional[str]:
    """Infer subscriptions from trigger conditions, never from their effects."""

    lower = text.casefold()
    if kind == "replacement":
        return "permanent_entered" if _is_entry_replacement(text) else None
    if kind != "triggered":
        return None
    if re.match(r"^(?:i|ii|iii|iv|v|vi)\s+—", lower):
        return "counters_added"

    # A stored paragraph can contain more than one trigger (Animate Dead is a
    # notable example).  For each trigger introducer, only inspect its condition
    # up to the next comma; otherwise words such as "draw" in the effect would
    # incorrectly subscribe the ability to CARD_DRAWN.
    starts = list(re.finditer(r"\b(?:when|whenever|at the beginning)\b", lower))
    conditions: list[str] = []
    for start in starts:
        end = lower.find(",", start.start())
        conditions.append(lower[start.start() : end if end >= 0 else len(lower)])
    condition_text = "\n".join(conditions) if conditions else lower
    events: list[str] = []

    def add(event: str) -> None:
        if event not in events:
            events.append(event)

    if ("enchantment" in condition_text and "enter" in condition_text) or (
        "unlock" in condition_text and "room" in condition_text
    ):
        add("enchantment_entered_or_room_unlocked")
    elif "land" in condition_text and "enter" in condition_text:
        add("land_entered")
    elif re.search(r"\benter(?:s|ed)?\b", condition_text):
        add("permanent_entered")
    if re.search(r"\bleav(?:e|es)\b", condition_text):
        add("permanent_left")
    if re.search(r"\bdi(?:e|es)\b", condition_text):
        add("permanent_died")
    if "at the beginning" in condition_text or "postcombat main phase" in condition_text:
        add("phase_began")
    if re.search(r"\battacks?\b", condition_text):
        add("attackers_declared")
    if re.search(r"\bblocks?\b", condition_text):
        add("blockers_declared")
    if re.search(r"\bcast\b", condition_text):
        add("spell_cast")
    if re.search(r"\bdraws?\b", condition_text):
        add("card_drawn")
    if re.search(r"\bgain(?:ed|s)? (?:\d+ or more )?life\b", condition_text):
        add("life_gained")
    if re.search(r"\bloses? life\b", condition_text):
        add("life_lost")
    if re.search(r"\bcounters? (?:is|are|was|were|would be )?(?:put|placed|added)\b", condition_text):
        add("counters_added")
    if "deals" in condition_text and "damage" in condition_text:
        add("damage_dealt")
    return ",".join(events) if events else None


def _is_entry_replacement(text: str) -> bool:
    lower = text.casefold()
    return bool(
        re.search(r"\bas .+ enters\b", lower)
        or re.search(r"\benter(?:s)? (?:the battlefield )?(?:tapped|untapped|with|as a copy)\b", lower)
        or "would enter" in lower
    )


def _ability_kind(text: str, face: dict[str, Any]) -> str:
    lower = text.casefold()
    if "Instant" in face["types"] or "Sorcery" in face["types"]:
        return "spell"
    if re.search(r"(?:\[?[+−-]\d+\]?|\[?0\]?)\s*:", text) or ":" in text:
        return "activated"
    if re.search(r"\b(?:when|whenever|at the beginning)\b", lower) or re.match(
        r"^(?:i|ii|iii|iv|v|vi)\s+—", lower
    ):
        return "triggered"
    if _is_entry_replacement(text) or " instead" in lower or "would " in lower:
        return "replacement"
    return "static"


def _ability_zone(text: str, kind: str) -> str:
    lower = text.casefold()
    if kind == "spell":
        return "stack"
    if lower.startswith("channel ") or lower.startswith("cycling ") or "discard this card:" in lower:
        return "hand"
    if lower.startswith(("flashback", "escape", "unearth", "embalm", "eternalize")):
        return "graveyard"
    if "from your graveyard" in lower and kind == "activated":
        return "graveyard"
    return "battlefield"


def _ability_timing(text: str, kind: str, face: dict[str, Any]) -> str:
    lower = text.casefold()
    if kind == "triggered":
        return "triggered"
    if kind == "replacement":
        return "replacement"
    if kind == "static":
        return "static"
    if kind == "spell":
        return "priority" if "Instant" in face["types"] or "flash" in lower else "sorcery"
    if re.search(r"\[?(?:[+−-]\d+|0)\]?\s*:", text):
        return "sorcery"
    return "priority"


def _is_mana_ability(text: str, kind: str) -> bool:
    if kind != "activated" or ":" not in text:
        return False
    effect = text.split(":", 1)[1]
    return bool(re.search(r"\badd\b", effect, re.IGNORECASE) and "target" not in effect.casefold())


def _oracle_abilities(card_id: str, faces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sequence = 0
    for face in faces:
        for line in face["oracle_text"].splitlines():
            clause = line.strip()
            if not clause:
                continue
            sequence += 1
            kind = _ability_kind(clause, face)
            mana_ability = _is_mana_ability(clause, kind)
            cost_text = clause.split(":", 1)[0].strip() if kind == "activated" and ":" in clause else None
            if mana_ability:
                handler = "primitive:mana"
                support_status = "generic"
            else:
                handler = None
                support_status = "oracle_only"
            rows.append(
                {
                    "ability_id": f"{card_id}:oracle:{sequence:03d}",
                    "face_id": face["face_id"],
                    "origin": "oracle",
                    "kind": kind,
                    "zone": _ability_zone(clause, kind),
                    "timing": _ability_timing(clause, kind, face),
                    "rules_text": clause,
                    "event": _infer_events(clause, kind),
                    "optional": bool(re.search(r"\bmay\b|\bup to\b", clause, re.IGNORECASE)),
                    "mana_ability": mana_ability,
                    "uses_stack": not mana_ability,
                    "cost_text": cost_text,
                    "handler": handler,
                    "support_status": support_status,
                }
            )
    return rows


def _registered_abilities(annotation: dict[str, Any]) -> list[dict[str, Any]]:
    """Copy frozen executable registrations from the card-first annotation input."""

    return [dict(row) for row in annotation.get("registered_abilities", ())]


def _entry_spec_for_clause(
    card_id: str, face: dict[str, Any], clause: str, sequence: int
) -> Optional[dict[str, Any]]:
    lower = clause.casefold()
    if not _is_entry_replacement(clause):
        return None
    kind = "entry_replacement"
    optional = "may" in lower
    parameters: dict[str, Any] = {}
    handler: Optional[str] = None

    if re.fullmatch(r"this (?:land|artifact|permanent) enters (?:the battlefield )?tapped\.?", lower):
        kind = "unconditional_tapped"
        handler = "primitive:enter_tapped"
    elif "pay 2 life" in lower and "enters tapped" in lower:
        kind = "pay_life_or_tapped"
        parameters = {"life": 2}
        optional = True
        handler = "primitive:pay_life_or_tapped"
    elif "enters tapped unless" in lower:
        kind = "tapped_unless"
        condition = lower.split("unless", 1)[1].rstrip(".")
        parameters = {"condition_text": condition}
        handler = "primitive:conditional_entry_tapped"
    elif lower.startswith("if ") and "enters tapped" in lower:
        kind = "tapped_if"
        parameters = {"condition_text": lower.split(",", 1)[0][3:]}
        handler = "primitive:conditional_entry_tapped"
    elif "reveal" in lower and "enters tapped" in lower:
        kind = "reveal_land_type_or_tapped"
        revealed = re.search(r"reveal (?:a |an )?(.+?) card from your hand", lower)
        parameters = {"reveal_text": revealed.group(1) if revealed else "qualifying card"}
        optional = True
        handler = "primitive:reveal_or_enter_tapped"
    elif "enter tapped as a copy" in lower:
        kind = "optional_tapped_copy"
        optional = True
        handler = "primitive:copy_entry"
    elif "enter as a copy" in lower:
        kind = "optional_copy"
        optional = True
        handler = "primitive:copy_entry"
    elif "enters with" in lower or "enter with" in lower:
        kind = "enters_with"
        parameters = {"value_text": clause}
        handler = "primitive:entry_modification"
    elif "enter untapped" in lower:
        kind = "enter_untapped_modifier"
        handler = "primitive:entry_untapped"

    return {
        "replacement_id": f"{card_id}:entry:{sequence:02d}",
        "face_id": face["face_id"],
        "kind": kind,
        "event": "enter_battlefield",
        "rules_text": clause,
        "optional": optional,
        "parameters": parameters,
        "handler": handler,
        "support_status": "catalogued",
    }


def _entry_replacements(card_id: str, faces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for face in faces:
        for line in face["oracle_text"].splitlines():
            clause = line.strip()
            row = _entry_spec_for_clause(card_id, face, clause, len(rows) + 1)
            if row is not None:
                rows.append(row)

    return rows


def _land_metadata(
    faces: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    annotation: dict[str, Any],
) -> Optional[dict[str, Any]]:
    land_faces = [face for face in faces if "Land" in face["types"]]
    if not land_faces:
        return None
    if annotation.get("land") is not None:
        return dict(annotation["land"])
    classes: set[str] = set()
    if any(row["kind"] == "unconditional_tapped" for row in entries):
        classes.add("enters_tapped")
    if len(faces) > 1:
        classes.add("modal_or_transform_face")
    for face in land_faces:
        if "Basic" in face["supertypes"]:
            classes.add("basic")
        for subtype in ("Gate", "Desert", "Locus", "Cave"):
            if subtype in face["subtypes"]:
                classes.add(subtype.casefold())
    return {
        "classifications": sorted(classes),
        "fetch_types": [],
    }


def _mana_metadata(card_name: str, faces: list[dict[str, Any]], annotation: dict[str, Any]) -> dict[str, Any]:
    if annotation.get("mana") is not None:
        return dict(annotation["mana"])
    oracle = "\n".join(face["oracle_text"] for face in faces)
    colors: set[str] = set()
    for line in oracle.splitlines():
        if re.search(r"\badd\b", line, re.IGNORECASE):
            colors.update(_mana_symbols(line))
    for face in faces:
        if "Land" not in face["types"]:
            continue
        for basic, color in (
            ("Plains", "W"),
            ("Island", "U"),
            ("Swamp", "B"),
            ("Mountain", "R"),
            ("Forest", "G"),
        ):
            if basic in face["subtypes"]:
                colors.add(color)
    lower = oracle.casefold()
    if "mana of any color" in lower or "one mana of any color" in lower:
        colors.update("WUBRG")
        production_rule = "any_color"
    elif card_name == "Arcane Signet":
        production_rule = "controller_color_identity"
    elif card_name == "Fellwar Stone":
        production_rule = "opponents_land_colors"
    elif card_name in {"Priest of Titania", "Kami of Whispered Hopes", "Fanatic of Rhonas", "Cloudpost"}:
        production_rule = "dynamic"
    elif colors:
        production_rule = "printed"
    else:
        production_rule = "none"
    source_kinds: list[str] = []
    if any("Land" in face["types"] for face in faces):
        source_kinds.append("land")
    is_source = bool(source_kinds or any(_is_mana_ability(line, _ability_kind(line, face)) for face in faces for line in face["oracle_text"].splitlines()))
    fixed_outputs = re.findall(r"^\{T\}: Add ((?:\{[WUBRGC]\})+)\.$", oracle, re.MULTILINE)
    base_amount: Optional[int] = max((len(re.findall(r"\{[WUBRGC]\}", output)) for output in fixed_outputs),
                                     default=(1 if is_source else 0)) or None
    variable = production_rule in {"dynamic", "opponents_land_colors", "controller_color_identity"} or bool(
        re.search(r"for each|equal to|any (?:type|color)", lower)
    )
    return {
        "is_mana_source": is_source,
        "colors": _ordered_colors(colors),
        "source_kinds": source_kinds,
        "production_rule": production_rule,
        "base_amount": base_amount,
        "variable_output": variable,
    }


def _definition_signature(card: ReferenceCard) -> tuple[str, str, str]:
    return card.mana_cost, card.type_line, card.text


def build_payload(
    reference_path: Path = DEFAULT_REFERENCE,
    annotations_path: Path = DEFAULT_ANNOTATIONS,
) -> dict[str, Any]:
    decks = parse_reference(reference_path)
    annotations = load_annotations(annotations_path)
    grouped: dict[str, list[ReferenceCard]] = defaultdict(list)
    deck_ordinals: dict[tuple[str, str], int] = {}
    for deck in DECK_ORDER:
        for ordinal, card in enumerate(decks[deck], start=1):
            grouped[card.name].append(card)
            deck_ordinals[(deck, card.name)] = ordinal

    cards: list[dict[str, Any]] = []
    for card_name, copies in grouped.items():
        signatures = {_definition_signature(card) for card in copies}
        if len(signatures) != 1:
            raise ValueError(f"conflicting reference definitions for {card_name}: {len(signatures)}")
        card = copies[0]
        card_id = canonical_card_id(card_name)
        annotation = annotations.get(card_id, {})
        faces = _build_faces(card, annotation)
        abilities = _oracle_abilities(card_id, faces)
        abilities.extend(_registered_abilities(annotation))
        entries = _entry_replacements(card_id, faces)
        occurrences = [
            {
                "deck": deck,
                "quantity": sum(row.quantity for row in copies if row.deck == deck),
                "ordinal": deck_ordinals[(deck, card_name)],
            }
            for deck in DECK_ORDER
            if any(row.deck == deck for row in copies)
        ]
        colors = set()
        for face in faces:
            colors.update(_mana_symbols(face["mana_cost"]))
            colors.update(_mana_symbols(face["oracle_text"]))
        cards.append(
            {
                "card_id": card_id,
                "name": card_name,
                "oracle_text": _clean_oracle(card.text),
                "color_identity": _ordered_colors(colors - {"C"}),
                "faces": faces,
                "abilities": abilities,
                "entry_replacements": entries,
                "mana": _mana_metadata(card_name, faces, annotation),
                "land": _land_metadata(faces, entries, annotation),
                "source_decks": occurrences,
            }
        )

    cards.sort(key=lambda row: row["card_id"])
    status_counts: Counter[str] = Counter()
    origin_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    for card in cards:
        for ability in card["abilities"]:
            status_counts[ability["support_status"]] += 1
            origin_counts[ability["origin"]] += 1
            kind_counts[ability["kind"]] += 1
    payload = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "source": {
            "reference": "data/reference/four_deck_oracle.txt",
            "annotations": "data/reference/card_catalog_annotations.json",
            "generator": "tools/generate_card_catalog.py",
            "reference_version": "four-deck-v3-2026-09-01",
        },
        "audit": {
            "unique_cards": len(cards),
            "physical_deck_slots": sum(
                occurrence["quantity"] for card in cards for occurrence in card["source_decks"]
            ),
            "faces": sum(len(card["faces"]) for card in cards),
            "abilities": sum(len(card["abilities"]) for card in cards),
            "oracle_ability_clauses": origin_counts["oracle"],
            "registered_actions": origin_counts["registry"],
            "ability_origins": dict(sorted(origin_counts.items())),
            "ability_kinds": dict(sorted(kind_counts.items())),
            "support_statuses": dict(sorted(status_counts.items())),
            "entry_replacements": sum(len(card["entry_replacements"]) for card in cards),
        },
        "cards": cards,
    }
    # Run the same strict validator used by runtime consumers before emitting.
    catalog_from_payload(payload, validate=True)
    return payload


def render_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--annotations", type=Path, default=DEFAULT_ANNOTATIONS)
    parser.add_argument("--check", action="store_true", help="fail if the generated bytes differ from --output")
    parser.add_argument("--stdout", action="store_true", help="write JSON to stdout instead of a file")
    args = parser.parse_args(argv)
    rendered = render_payload(build_payload(args.reference.resolve(), args.annotations.resolve()))
    if args.stdout:
        sys.stdout.write(rendered)
        return 0
    output = args.output.resolve()
    if args.check:
        if not output.exists():
            print(f"catalog is missing: {output}", file=sys.stderr)
            return 1
        if output.read_text(encoding="utf-8") != rendered:
            print(f"catalog is stale: regenerate {output}", file=sys.stderr)
            return 1
        print(f"catalog is current: {output}")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {len(rendered.encode('utf-8'))} bytes to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
