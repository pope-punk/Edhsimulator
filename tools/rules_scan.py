#!/usr/bin/env python3
"""Generate a conservative static rules-coverage inventory for the four-deck pod.

This is a triage tool, not a proof of rules correctness.  A named code path means
only that the card is mentioned by behavioral code; it does not certify that every
mode, target, trigger, replacement effect, or interaction is implemented exactly.
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from edh_gauntlet import engine
from edh_gauntlet.ability_registry import CARD_ABILITIES


PROJECT = Path(__file__).resolve().parents[1]
BEHAVIOR_SOURCES = (
    PROJECT / "src/edh_gauntlet/engine.py",
    PROJECT / "src/edh_gauntlet/referee.py",
    PROJECT / "src/edh_gauntlet/ability_registry.py",
    PROJECT / "src/edh_gauntlet/continuous.py",
)
TEST_SOURCES = tuple(sorted((PROJECT / "tests").glob("test_*.py")))

NON_BEHAVIOR_FUNCTIONS = {
    "ream_card_score", "generic_card_score", "perm_threat", "action_score",
    "cards_to_cast", "check_ream_combo", "mark_appearance", "aggregate_cardwise",
    "run_gauntlet", "write_outputs", "strategic_state_summary", "note_timing_affordance",
}

PATTERNS = {
    "triggered": r"\b(when|whenever|at the beginning|at the end)\b",
    "activated": r"(^|\n)\s*[^\n]+:",
    "targeting": r"\btarget\b",
    "replacement": r"\b(instead|as [^\n]+ enters|would)\b",
    "choice_optional": r"\b(choose|may|unless|up to)\b",
    "zones_hidden_info": r"\b(graveyard|exile|library|hand|command zone|reveal|look at)\b",
    "counters": r"\bcounter",
    "copy": r"\bcopy",
    "control_change": r"\b(gain control|exchange control|controls? it|under your control)\b",
    "multiplayer": r"\b(each opponent|each player|target opponent|two target players|for each opponent)\b",
    "variable_cost": r"\{X\}|\bwhere X\b",
    "transform_mdfc": r"\b(transform|transformed|back face|converted)\b|//",
    "room": r"\b(Room|door|unlock)\b",
    "linked_delayed": r"\b(for as long as|until|at the beginning of the next|return that card|exiled with)\b",
    "replacement_cost": r"\b(additional cost|rather than pay|without paying|alternative cost|miracle|evoke|kicker|escape|transmute)\b",
}

HIGH_RISK_TAGS = {
    "replacement", "copy", "control_change", "variable_cost", "transform_mdfc",
    "room", "linked_delayed", "replacement_cost", "multiplayer",
}


class StringUseVisitor(ast.NodeVisitor):
    def __init__(self, card_names: set[str]):
        self.card_names = card_names
        self.stack: list[str] = []
        self.uses: dict[str, set[str]] = defaultdict(set)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Constant(self, node: ast.Constant):
        if self.stack and isinstance(node.value, str) and node.value in self.card_names:
            self.uses[node.value].add(self.stack[-1])


def function_string_uses(path: Path, card_names: set[str]) -> dict[str, set[str]]:
    visitor = StringUseVisitor(card_names)
    visitor.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    return visitor.uses


def tags_for(text: str) -> list[str]:
    return [name for name, pattern in PATTERNS.items() if re.search(pattern, text, re.I | re.M)]


def primitive_evidence(name: str) -> list[str]:
    evidence = []
    mappings = {
        "keyword metadata": engine.KEYWORDS,
        "land color mapping": engine.LAND_COLOR_HINTS,
        "fetch primitive": engine.FETCHES,
        "bounce-land primitive": engine.BOUNCE_LANDS,
        "enters-tapped primitive": engine.TAPPED_LANDS,
        "shock-land primitive": engine.SHOCK_LANDS,
        "slow-land primitive": engine.SLOW_LANDS,
        "mana-rock primitive": engine.MANA_ROCKS,
        "mana-dork primitive": engine.MANA_DORKS,
    }
    for label, values in mappings.items():
        if name in values:
            evidence.append(label)
    return evidence


def is_mana_only_land(card) -> bool:
    if not card.is_land:
        return False
    normalized = " ".join(card.text.replace("\n", " ").split())
    clauses = [part.strip() for part in normalized.split(".") if part.strip()]
    return bool(clauses) and all("Add " in clause and "{T}" in clause for clause in clauses)


def complexity(tags: list[str], text: str) -> int:
    weights = {
        "triggered": 2, "activated": 2, "targeting": 2, "replacement": 4,
        "choice_optional": 2, "zones_hidden_info": 3, "counters": 2, "copy": 5,
        "control_change": 5, "multiplayer": 3, "variable_cost": 3,
        "transform_mdfc": 4, "room": 5, "linked_delayed": 4, "replacement_cost": 4,
    }
    return sum(weights[tag] for tag in tags) + min(5, text.count("\n"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=PROJECT / "reports/rules_scan_400")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    entries = [card for deck in engine.DECKDEFS.values() for card in deck]
    names = {card.name for card in entries}
    by_name = {}
    decks_by_name: dict[str, list[str]] = defaultdict(list)
    slots_by_name = Counter()
    for card in entries:
        by_name.setdefault(card.name, card)
        decks_by_name[card.name].append(card.deck)
        slots_by_name[card.name] += card.quantity

    behavior_uses: dict[str, set[str]] = defaultdict(set)
    for path in BEHAVIOR_SOURCES:
        for name, funcs in function_string_uses(path, names).items():
            behavior_uses[name].update(func for func in funcs if func not in NON_BEHAVIOR_FUNCTIONS)
    for name in CARD_ABILITIES:
        if name in names:behavior_uses[name].add('ability_registry')
    test_uses: dict[str, set[str]] = defaultdict(set)
    for path in TEST_SOURCES:
        for name, funcs in function_string_uses(path, names).items():test_uses[name].update(funcs)

    rows = []
    for name, card in by_name.items():
        tags = tags_for(card.text)
        handlers = sorted(behavior_uses.get(name, set()))
        tests = sorted(func for func in test_uses.get(name, set()) if func.startswith("test_"))
        primitives = primitive_evidence(name)
        score = complexity(tags, card.text)
        if is_mana_only_land(card) and primitives:
            status = "primitive"
        elif handlers and tests:
            status = "named_path_with_test"
        elif handlers:
            status = "named_path_unverified"
        elif primitives and not (set(tags) & HIGH_RISK_TAGS):
            status = "primitive_or_generic"
        elif primitives:
            status = "primitive_plus_unmapped_text"
        else:
            status = "unmapped_or_generic_only"

        if status == "unmapped_or_generic_only" and score >= 8:
            priority = "P0"
        elif status in {"unmapped_or_generic_only", "primitive_plus_unmapped_text"} or score >= 15:
            priority = "P1"
        elif status == "named_path_unverified" or score >= 8:
            priority = "P2"
        else:
            priority = "P3"

        rows.append({
            "card": name,
            "decks": "; ".join(sorted(set(decks_by_name[name]))),
            "physical_slots": slots_by_name[name],
            "mana_cost": card.mana_cost,
            "type_line": card.type_line,
            "complexity": score,
            "risk_tags": "; ".join(tags),
            "static_status": status,
            "priority": priority,
            "behavior_functions": "; ".join(handlers),
            "primitive_evidence": "; ".join(primitives),
            "test_functions": "; ".join(tests),
            "oracle_text": " ".join(card.text.split()),
        })

    deck_order = {name: index for index, name in enumerate(engine.DECKDEFS)}
    rows.sort(key=lambda row: (min(deck_order[d] for d in row["decks"].split("; ")), row["card"]))
    fields = list(rows[0])
    with (args.out / "card_inventory.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
    (args.out / "card_inventory.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    framework_by_tag = {
        "triggered":"APNAP trigger batching and post-resolution generated-trigger queue",
        "activated":"declarative/legacy-migrated activated-ability stack path",
        "targeting":"announcement-time target lock, ward, protection, and resolution legality",
        "replacement":"affected-player ordered replacement pipeline",
        "counters":"counter replacement and counter-event trigger pipeline",
        "copy":"copiable-value/continuous-view and Sunken copy path",
        "control_change":"controller/owner-aware permanent state",
        "multiplayer":"four-seat APNAP and per-opponent iteration",
        "variable_cost":"announced X and exact payment path",
        "transform_mdfc":"face/copy metadata and zone-transition path",
        "room":"unlock special action plus eerie/full-unlock trigger path",
        "linked_delayed":"object-UID linked exile and delayed-return path",
        "replacement_cost":"alternate/additional cost path before stack placement",
        "zones_hidden_info":"decision-tape zone choice and deterministic hidden-zone reconciliation",
        "choice_optional":"explicit decision point with pass/decline support",
    }
    manifest=[]
    for row in rows:
        tags=[tag for tag in row["risk_tags"].split("; ") if tag]
        blocked=row["static_status"] in {"unmapped_or_generic_only","primitive_plus_unmapped_text"}
        manifest.append({
            "card":row["card"],"decks":row["decks"].split("; "),"physical_slots":row["physical_slots"],
            "oracle_snapshot":"data/reference/four_deck_oracle.txt",
            "support_status":"blocked_unmapped" if blocked else ("executable_with_named_regression" if row["test_functions"] else "executable_framework_path"),
            "action_policy":"fail_closed_before_selection_when_unrepresented",
            "behavior_functions":[item for item in row["behavior_functions"].split("; ") if item],
            "primitive_evidence":[item for item in row["primitive_evidence"].split("; ") if item],
            "regression_tests":[item for item in row["test_functions"].split("; ") if item],
            "framework_families":[framework_by_tag[tag] for tag in tags if tag in framework_by_tag],
            "risk_priority":row["priority"],
            "certification_scope":"fixed four-deck Oracle snapshot; static evidence plus executable framework regressions",
        })
    (args.out / "support_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    manifest_fields=["card","decks","physical_slots","support_status","action_policy","behavior_functions","primitive_evidence","regression_tests","framework_families","risk_priority","certification_scope"]
    with (args.out / "support_manifest.csv").open("w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=manifest_fields);writer.writeheader()
        for item in manifest:
            writer.writerow({key:("; ".join(str(value) for value in item[key]) if isinstance(item[key],list) else item[key]) for key in manifest_fields})

    status_counts = Counter(row["static_status"] for row in rows)
    priority_counts = Counter(row["priority"] for row in rows)
    tag_counts = Counter(tag for row in rows for tag in row["risk_tags"].split("; ") if tag)
    slot_status = Counter()
    for row in rows:
        slot_status[row["static_status"]] += row["physical_slots"]

    summary = {
        "physical_slots": sum(row["physical_slots"] for row in rows),
        "deck_entries": len(entries),
        "unique_cards": len(rows),
        "status_unique": dict(status_counts),
        "status_slots": dict(slot_status),
        "priority_unique": dict(priority_counts),
        "risk_tags_unique": dict(tag_counts),
        "methodology": "Conservative static triage; named paths and tests are evidence, not certification.",
        "manifest_blocked_unmapped":sum(item["support_status"]=="blocked_unmapped" for item in manifest),
        "manifest_executable":sum(item["support_status"]!="blocked_unmapped" for item in manifest),
    }
    if summary["physical_slots"] != 400:
        raise RuntimeError(f"Expected four 100-card decks, found {summary['physical_slots']} physical slots")
    if summary["unique_cards"] != 334:
        raise RuntimeError(f"Expected the audited 334 unique names, found {summary['unique_cards']}")
    if summary["manifest_blocked_unmapped"]:
        raise RuntimeError(f"Support manifest still has {summary['manifest_blocked_unmapped']} unmapped card(s)")
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "# Automated 400-slot static rules inventory", "",
        "> This inventory is conservative triage, not a proof of Magic rules correctness.", "",
        f"- Physical deck slots: **{summary['physical_slots']}**",
        f"- Deck entries: **{summary['deck_entries']}**",
        f"- Unique cards: **{summary['unique_cards']}**", "",
        "## Static status (unique cards)", "",
    ]
    for key, value in status_counts.most_common():
        lines.append(f"- `{key}`: {value} unique / {slot_status[key]} physical slots")
    lines.extend(["", "## Priority triage", ""])
    for key in ("P0", "P1", "P2", "P3"):
        lines.append(f"- `{key}`: {priority_counts[key]} unique cards")
    lines.extend(["", "## Highest-complexity P0/P1 candidates", "",
                  "| Card | Deck | Priority | Score | Status | Risk tags |", "|---|---|---:|---:|---|---|"])
    candidates = sorted((row for row in rows if row["priority"] in {"P0", "P1"}), key=lambda row: (-row["complexity"], row["card"]))
    for row in candidates[:100]:
        lines.append(f"| {row['card']} | {row['decks']} | {row['priority']} | {row['complexity']} | {row['static_status']} | {row['risk_tags']} |")
    lines.extend(["", "The complete card-by-card inventory is in `card_inventory.csv` and `card_inventory.json`.", ""])
    (args.out / "AUTOMATED_INVENTORY.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
