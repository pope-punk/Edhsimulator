"""Checkpoint/replay shell for the four-player manual EDH ledger.

The decision tape is the source of truth. Every checkpoint is rebuilt from the game
seed and accepted decisions, so Python reconciles state but never chooses strategy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, Optional

from . import engine
from .runtime_store import serialized,locked
from . import pilot_handoff
from . import review_contract
from . import quarantine
from .scheduler import directive_from_flags, SURFACE_REVISION as SCHEDULER_DECISION_SURFACE_REVISION
from .active_plan import (
    DEFAULT_PLAN_SCOPE,
    OPENING_OPPONENT_KNOWLEDGE_QUALIFIER,
    delivery_telemetry,
    is_strategic_request,
    normalize_plan_delta,
    normalize_plan_scope,
    planning_checkpoint_help,
    project_active_plan,
)
from .inspection import InspectionError, InspectionService
from .combo_adjudication import (
    ComboAdjudicationValidationError,
    validate_combo_adjudication_response,
)
from .learning import (
    CARDWISE_NOTE_GUIDANCE,
    LearningPatchError,
    apply_strategy_patch,
    build_pilot_evidence,
)
from .referee import (
    DecisionTape,
    ManualGame,
    NeedComboAdjudication,
    NeedDecision,
    PASS_ON_MANAGEMENT_CHOICE,
    UnrefereedDecisionError,
    decision_request_fingerprint,
    normalize_messageboard_text,
    parse_pass_on_batch_entry,
    parse_pass_on_schedule,
    validate_pass_on_control,
)
from .release import release_report
from .strategy import (
    DEFAULT_STRATEGY_FILE,
    StrategyState,
    StrategyValidationError,
    load_strategy_state,
)

from .paths import PROJECT_ROOT
DEFAULT_COHORT = PROJECT_ROOT / "runs" / "fresh20"
SCHEMA = 1
COHORT_SCHEMA = 2
LEGACY_DECISION_SURFACE_REVISION = 1
ACTIVE_PLAN_DECISION_SURFACE_REVISION = 2
DRAW_PLANNING_DECISION_SURFACE_REVISION = 3
OPENING_REGIME_DECISION_SURFACE_REVISION = 4
PASSING_ACCELERATION_DECISION_SURFACE_REVISION = 5
CURRENT_DECISION_SURFACE_REVISION = SCHEDULER_DECISION_SURFACE_REVISION
STRATEGY_SNAPSHOT_FILE = "strategy_snapshot.json"
GAME_CONFIG_FILE = "game_config.json"
TERMINAL_SEAL_FILE = "terminal_result.json"
POSTGAME_EVIDENCE_DIR = "postgame_evidence"
POSTGAME_REVIEW_DIR = "postgame_review"
POSTGAME_LEARNING_DIR = "postgame_learning"
REVIEW_REQUEST_FILE = "review_request.json"
LEARNING_PATCH_FILE = "learning_patch.json"
REVIEW_INSTRUCTIONS_FILE = "REVIEW.md"
GAME_SUMMARY_FILE = "game_summary.txt"
NEXT_ACTION_FILE = "NEXT_ACTION.json"
CANCELLATION_FILE = "CANCELLATION.json"
REINITIALIZATION_JOURNAL_FILE = "reinitializations.jsonl"
REINITIALIZATION_RELEASE_GATE_PREFIX = "reinitialization_release_gate_"
MESSAGEBOARD_FILE = "MESSAGEBOARD.md"
LEARNING_TRANSACTION_FILE = "transaction.json"
PRIVATE_GAMEPLAN_DIR = "private_gameplans"
PRIVATE_GAMEPLAN_TELEMETRY_DIR = "telemetry"
GAMEPLAN_SEED_SNAPSHOT_FILE = "gameplan_seed_snapshot.json"
SEED_GAMEPLAN_SOURCE_DIR = PROJECT_ROOT / "data" / "strategy" / "gameplan_seeds"
MESSAGING_PERSONALITY_SNAPSHOT_FILE = "messaging_personality_snapshot.json"
MESSAGING_PERSONALITY_SOURCE_DIR = PROJECT_ROOT / "data" / "strategy" / "messaging_personalities"
# Compatibility alias for callers that read the older noun order.
GAMEPLAN_SEED_SOURCE_DIR = SEED_GAMEPLAN_SOURCE_DIR
COMBO_ADJUDICATION_JOURNAL = "combo_adjudications.jsonl"
COMBO_ADJUDICATION_REQUEST = "combo_adjudication_request.json"
COMBO_ADJUDICATION_RESPONSE = "combo_adjudication_response.json"
INSPECTION_AUDIT_FILE = "inspections.jsonl"
INSPECTION_EVIDENCE_DIR = "inspection_evidence"
INSPECTION_CACHE_DIR = "inspection_cache"
INSPECTION_CACHE_SCHEMA = 2
REVIEW_EVIDENCE_MIGRATION_FILE = "review_evidence_migrations.jsonl"
ANSWER_TRANSACTION_FILE = ".answer_transaction.json"
ANSWER_TRANSACTION_SCHEMA = 1
ANSWER_TRANSACTION_STATES = {"prepared", "committing", "applied"}
ANSWER_TRANSACTION_SCRATCH_FILES = (
    ".candidate_decisions.jsonl",
    ".candidate_request.json",
    ".candidate_rebase_combo_adjudications.jsonl",
)
GAMEPLAN_CHOICE = "GAMEPLAN"
MAIN_PHASES = {"precombat_main", "postcombat_main"}
MAIN_PHASE_REVIEW_FIELD = "main_phase_seed_review"
MANDATORY_LONG_TERM_UPDATE_FIELD = "mandatory_long_term_plan_update"
PLANNING_CHECKPOINT_FIELD = "planning_checkpoint"
DRAW_PLANNING_REVIEW_FIELD = "draw_planning_review"
PASS_ON_MANAGEMENT_ALIASES = {
    "manage pass-ons","manage pass ons","pass-ons","pass ons","snoozes",
}
GAMEPLAN_PRIORITY_KINDS = {
    "main_action",
    "upkeep_action",
    "priority_action",
    "counterspell_response",
    "summary_dismissal_abilities",
    "heroic_intervention",
    "evacuation_response",
    "combo_response",
    "combo_consent",
    "pass_on_schedule",
}

PILOT_GAMEPLAN_FILES = {
    "Reaminatour": "reaminatour.jsonl",
    "Minsc & Boo": "minsc_and_boo.jsonl",
    "Omo": "omo.jsonl",
    "Elenda": "elenda.jsonl",
}

PILOT_SEED_GAMEPLAN_FILES = {
    "Reaminatour": "reaminatour.md",
    "Minsc & Boo": "minsc_and_boo.md",
    "Omo": "omo.md",
    "Elenda": "elenda.md",
}
PILOT_MESSAGING_PERSONALITY_FILES = {
    "Reaminatour": "reaminatour.md",
    "Minsc & Boo": "minsc_and_boo.md",
    "Omo": "omo.md",
    "Elenda": "elenda.md",
}
# Compatibility alias; seed plans and dynamic journals remain distinct artifacts.
PILOT_GAMEPLAN_SEED_FILES = PILOT_SEED_GAMEPLAN_FILES


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_text(path: Path, text: str) -> None:
    _atomic_text_chunks(path, (text,))


def _atomic_text_chunks(path: Path, chunks: Iterable[str]) -> None:
    """Publish only after every chunk is written; avoid joining large journals."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            stream.writelines(chunks)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    from .atomic_files import replace
    replace(temporary,path)


def write_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _jsonl_text(rows: Iterable[Dict[str, Any]]) -> str:
    return "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in rows
    )


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    _atomic_text_chunks(path, (
        json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n'
        for row in rows
    ))


def _transaction_text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _answer_transaction_path(directory: Path) -> Path:
    return directory / ANSWER_TRANSACTION_FILE


def _answer_transaction_relative_path(directory: Path, path: Path) -> str:
    resolved_directory = directory.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(resolved_directory)
    except ValueError as exc:
        raise SystemExit("Answer transaction target escapes the game directory.") from exc
    value = relative.as_posix()
    allowed_journals = {
        "decisions.jsonl", COMBO_ADJUDICATION_JOURNAL, "rejections.jsonl",
    }
    allowed_gameplans = {
        f"{PRIVATE_GAMEPLAN_DIR}/{filename}"
        for filename in PILOT_GAMEPLAN_FILES.values()
    }
    checkpoint = (
        len(relative.parts) == 2
        and relative.parts[0] == "checkpoints"
        and relative.suffix == ".json"
    )
    if value not in allowed_journals | allowed_gameplans and not checkpoint:
        raise SystemExit(f"Unsupported answer transaction target {value!r}.")
    return value


def _answer_transaction_image(*, exists: bool, text: Optional[str]) -> Dict[str, Any]:
    if not exists:
        return {"exists": False, "sha256": None, "text": None}
    if text is None:
        raise SystemExit("An existing answer transaction image must contain text.")
    return {
        "exists": True,
        "sha256": _transaction_text_sha256(text),
        "text": text,
    }


def _answer_transaction_target(
    directory: Path,
    path: Path,
    after_text: Optional[str],
) -> Dict[str, Any]:
    before_exists = path.exists()
    before_text = path.read_text(encoding="utf-8") if before_exists else None
    return {
        "path": _answer_transaction_relative_path(directory, path),
        "before": _answer_transaction_image(exists=before_exists, text=before_text),
        "after": _answer_transaction_image(
            exists=after_text is not None,
            text=after_text,
        ),
    }


def _answer_transaction_fingerprint(transaction: Dict[str, Any]) -> str:
    payload = {
        key: value
        for key, value in transaction.items()
        if key not in {"state", "transaction_id", "transaction_sha256"}
    }
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def _validate_answer_transaction_image(
    image: Any,
    *,
    transaction_path: Path,
) -> Dict[str, Any]:
    if not isinstance(image, dict) or set(image) != {"exists", "sha256", "text"}:
        raise SystemExit(f"Invalid answer transaction image in {transaction_path}.")
    exists = image.get("exists")
    text = image.get("text")
    digest = image.get("sha256")
    if not isinstance(exists, bool):
        raise SystemExit(f"Invalid answer transaction image state in {transaction_path}.")
    if exists:
        if not isinstance(text, str) or digest != _transaction_text_sha256(text):
            raise SystemExit(f"Answer transaction image hash mismatch in {transaction_path}.")
    elif text is not None or digest is not None:
        raise SystemExit(f"Invalid absent answer transaction image in {transaction_path}.")
    return image


def _validate_answer_transaction(
    directory: Path,
    transaction: Any,
    *,
    transaction_path: Optional[Path] = None,
) -> Dict[str, Any]:
    path = transaction_path or _answer_transaction_path(directory)
    required = {
        "schema", "kind", "state", "transaction_id", "transaction_sha256",
        "prepared_at", "decision_id", "request_sha256", "rebase_cut",
        "privacy", "targets",
    }
    if not isinstance(transaction, dict) or set(transaction) != required:
        raise SystemExit(f"Invalid answer transaction envelope in {path}.")
    if (
        transaction.get("schema") != ANSWER_TRANSACTION_SCHEMA
        or transaction.get("kind") != "answer_commit"
        or transaction.get("state") not in ANSWER_TRANSACTION_STATES
        or transaction.get("privacy") != "game_local_private_strategy_may_be_present"
        or not isinstance(transaction.get("decision_id"), str)
        or not transaction.get("decision_id")
        or not isinstance(transaction.get("request_sha256"), str)
    ):
        raise SystemExit(f"Invalid answer transaction metadata in {path}.")
    rebase_cut = transaction.get("rebase_cut")
    if rebase_cut is not None and (
        isinstance(rebase_cut, bool) or not isinstance(rebase_cut, int) or rebase_cut < 0
    ):
        raise SystemExit(f"Invalid answer transaction rebase cut in {path}.")
    targets = transaction.get("targets")
    if not isinstance(targets, list) or not targets:
        raise SystemExit(f"Answer transaction has no targets in {path}.")
    seen = set()
    for target in targets:
        if not isinstance(target, dict) or set(target) != {"path", "before", "after"}:
            raise SystemExit(f"Invalid answer transaction target in {path}.")
        relative = str(target.get("path", ""))
        resolved = (directory / relative).resolve()
        validated_relative = _answer_transaction_relative_path(directory, resolved)
        if relative != validated_relative or relative in seen:
            raise SystemExit(f"Invalid or duplicate answer transaction target in {path}.")
        seen.add(relative)
        _validate_answer_transaction_image(target.get("before"), transaction_path=path)
        _validate_answer_transaction_image(target.get("after"), transaction_path=path)
    fingerprint = _answer_transaction_fingerprint(transaction)
    if (
        transaction.get("transaction_sha256") != fingerprint
        or transaction.get("transaction_id") != f"answer-{fingerprint[:20]}"
    ):
        raise SystemExit(f"Answer transaction fingerprint mismatch in {path}.")
    return transaction


def _read_answer_transaction_candidate(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        value = read_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _load_answer_transaction(directory: Path) -> Optional[Dict[str, Any]]:
    """Load the newest durable protocol state, including an interrupted atomic rename."""

    path = _answer_transaction_path(directory)
    temporary = path.with_suffix(path.suffix + ".tmp")
    primary = _read_answer_transaction_candidate(path)
    staged = _read_answer_transaction_candidate(temporary)
    if path.exists() and primary is None:
        raise SystemExit(f"Could not read prepared answer transaction {path}.")
    valid = []
    for candidate_path, candidate in ((path, primary), (temporary, staged)):
        if candidate is None:
            continue
        try:
            valid.append(
                (candidate_path, _validate_answer_transaction(
                    directory, candidate, transaction_path=candidate_path
                ))
            )
        except SystemExit:
            if candidate_path == path:
                raise
            # A truncated temporary beside a valid primary is merely an
            # interrupted attempt to advance the protocol state.
            if primary is None:
                temporary.unlink(missing_ok=True)
            continue
    if not valid:
        temporary.unlink(missing_ok=True)
        return None
    identities = {item[1]["transaction_id"] for item in valid}
    if len(identities) != 1:
        raise SystemExit(f"Conflicting answer transaction states in {directory}.")
    rank = {"prepared": 0, "committing": 1, "applied": 2}
    _, selected = max(valid, key=lambda item: rank[item[1]["state"]])
    if primary != selected:
        write_json(path, selected)
    temporary.unlink(missing_ok=True)
    return selected


def _prepare_answer_transaction(
    directory: Path,
    *,
    decision_id: str,
    request_sha256: str,
    rebase_cut: Optional[int],
    after_images: Dict[Path, Optional[str]],
) -> Dict[str, Any]:
    existing = _load_answer_transaction(directory)
    if existing is not None:
        raise SystemExit(
            "A prior answer transaction must be recovered before preparing another answer."
        )
    targets = [
        _answer_transaction_target(directory, path, after_images[path])
        for path in sorted(after_images, key=lambda value: value.as_posix())
    ]
    transaction: Dict[str, Any] = {
        "schema": ANSWER_TRANSACTION_SCHEMA,
        "kind": "answer_commit",
        "state": "prepared",
        "transaction_id": "",
        "transaction_sha256": "",
        "prepared_at": now(),
        "decision_id": decision_id,
        "request_sha256": request_sha256,
        "rebase_cut": rebase_cut,
        "privacy": "game_local_private_strategy_may_be_present",
        "targets": targets,
    }
    fingerprint = _answer_transaction_fingerprint(transaction)
    transaction["transaction_id"] = f"answer-{fingerprint[:20]}"
    transaction["transaction_sha256"] = fingerprint
    _validate_answer_transaction(directory, transaction)
    write_json(_answer_transaction_path(directory), transaction)
    return transaction


def _set_answer_transaction_state(
    directory: Path,
    transaction: Dict[str, Any],
    state: str,
) -> Dict[str, Any]:
    if state not in ANSWER_TRANSACTION_STATES:
        raise SystemExit(f"Unknown answer transaction state {state!r}.")
    updated = dict(transaction)
    updated["state"] = state
    _validate_answer_transaction(directory, updated)
    write_json(_answer_transaction_path(directory), updated)
    return updated


def _answer_transaction_image_matches(path: Path, image: Dict[str, Any]) -> bool:
    if not image["exists"]:
        return not path.exists()
    if not path.exists():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    return _transaction_text_sha256(text) == image["sha256"]


def _write_answer_transaction_target(path: Path, image: Dict[str, Any]) -> None:
    """One narrow write seam, intentionally patchable by recovery tests."""

    if image["exists"]:
        atomic_text(path, image["text"])
    else:
        path.unlink(missing_ok=True)


def _answer_transaction_targets_in_order(
    directory: Path,
    transaction: Dict[str, Any],
    *,
    image_name: str,
) -> list[Dict[str, Any]]:
    # On commit, prune private branch state before exposing the new tape. On
    # rollback, restore the old tape before restoring its private branch state.
    tape_last = image_name == "after"
    return sorted(
        transaction["targets"],
        key=lambda target: (
            (target["path"] == "decisions.jsonl") if tape_last
            else (target["path"] != "decisions.jsonl"),
            target["path"],
        ),
    )


def _apply_answer_transaction_images(
    directory: Path,
    transaction: Dict[str, Any],
    *,
    image_name: str,
) -> None:
    if image_name not in {"before", "after"}:
        raise SystemExit(f"Unknown answer transaction image {image_name!r}.")
    transaction = _validate_answer_transaction(directory, transaction)
    for target in transaction["targets"]:
        path = directory / target["path"]
        if not (
            _answer_transaction_image_matches(path, target["before"])
            or _answer_transaction_image_matches(path, target["after"])
        ):
            raise SystemExit(
                "Cannot recover answer transaction because target changed outside the "
                f"transaction: {target['path']}"
            )
    for target in _answer_transaction_targets_in_order(
        directory, transaction, image_name=image_name
    ):
        path = directory / target["path"]
        desired = target[image_name]
        if not _answer_transaction_image_matches(path, desired):
            _write_answer_transaction_target(path, desired)
    for target in transaction["targets"]:
        if not _answer_transaction_image_matches(
            directory / target["path"], target[image_name]
        ):
            raise SystemExit(
                f"Answer transaction target did not reach its {image_name} image: "
                f"{target['path']}"
            )


def _cleanup_answer_transaction_scratch(directory: Path) -> None:
    for name in ANSWER_TRANSACTION_SCRATCH_FILES:
        (directory / name).unlink(missing_ok=True)


def _recover_answer_transaction(directory: Path) -> Optional[Dict[str, Any]]:
    """Restore an uncommitted prepare or finish a durably committed answer."""

    transaction = _load_answer_transaction(directory)
    if transaction is None:
        return None
    if transaction["state"] == "prepared":
        _apply_answer_transaction_images(directory, transaction, image_name="before")
        _answer_transaction_path(directory).unlink(missing_ok=True)
        _cleanup_answer_transaction_scratch(directory)
        return {"outcome": "rolled_back", "transaction": transaction}
    if transaction["state"] == "committing":
        _apply_answer_transaction_images(directory, transaction, image_name="after")
        transaction = _set_answer_transaction_state(directory, transaction, "applied")
    else:
        _apply_answer_transaction_images(directory, transaction, image_name="after")
    _cleanup_answer_transaction_scratch(directory)
    return {"outcome": "applied", "transaction": transaction}


def _commit_answer_transaction(
    directory: Path,
    transaction: Dict[str, Any],
) -> Dict[str, Any]:
    committing = _set_answer_transaction_state(directory, transaction, "committing")
    _apply_answer_transaction_images(directory, committing, image_name="after")
    return _set_answer_transaction_state(directory, committing, "applied")


def _finalize_answer_transaction(
    directory: Path,
    transaction_id: Optional[str] = None,
) -> None:
    transaction = _load_answer_transaction(directory)
    if transaction is None:
        return
    if transaction["state"] != "applied":
        raise SystemExit("Cannot finalize an answer transaction that is not applied.")
    if transaction_id is not None and transaction["transaction_id"] != transaction_id:
        raise SystemExit("Answer transaction identity changed before finalization.")
    # ``advance`` may already have written a fresh replacement-branch checkpoint
    # using the filename of a checkpoint this transaction deleted. Checkpoints
    # are derived replay products; authoritative journals must still match their
    # committed images exactly before the durable receipt can be removed.
    for target in transaction["targets"]:
        if target["path"].startswith("checkpoints/") and not target["after"]["exists"]:
            continue
        if not _answer_transaction_image_matches(
            directory / target["path"], target["after"]
        ):
            raise SystemExit(
                "Cannot finalize answer transaction because a committed target changed: "
                f"{target['path']}"
            )
    _answer_transaction_path(directory).unlink(missing_ok=True)
    _cleanup_answer_transaction_scratch(directory)


def _normalized_seed_gameplan_text(text: str) -> str:
    """Use stable newlines without otherwise rewriting pilot-authored Markdown."""

    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")
    return "" if not normalized.strip() else normalized


def _seed_gameplan_text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _seed_gameplan_source_file(pilot: str) -> str:
    return str(
        (SEED_GAMEPLAN_SOURCE_DIR / PILOT_SEED_GAMEPLAN_FILES[pilot]).relative_to(PROJECT_ROOT)
    ).replace("\\", "/")


def _seed_gameplan_fingerprint(snapshot: Dict[str, Any]) -> str:
    core = {
        "schema": snapshot.get("schema"),
        "effective_from_game": snapshot.get("effective_from_game"),
        "pilots": snapshot.get("pilots"),
    }
    digest = hashlib.sha256(
        json.dumps(
            core, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    return digest


def _validate_seed_gameplan_snapshot(
    snapshot: Any,
    *,
    path: Path,
    expected_fingerprint: Optional[str] = None,
    expected_effective_from_game: Optional[int] = None,
) -> Dict[str, Any]:
    """Validate immutable seed text and its cohort/game bindings."""

    if not isinstance(snapshot, dict) or set(snapshot) != {
        "schema", "created_at", "effective_from_game", "pilots", "fingerprint"
    }:
        raise SystemExit(f"Invalid seed gameplan snapshot shape: {path}")
    effective = snapshot.get("effective_from_game")
    if (
        snapshot.get("schema") != 1
        or isinstance(effective, bool)
        or not isinstance(effective, int)
        or effective < 1
        or not isinstance(snapshot.get("created_at"), str)
    ):
        raise SystemExit(f"Invalid seed gameplan snapshot metadata: {path}")
    pilots = snapshot.get("pilots")
    if not isinstance(pilots, dict) or set(pilots) != set(PILOT_SEED_GAMEPLAN_FILES):
        raise SystemExit(f"Seed gameplan snapshot has the wrong pilot set: {path}")
    for pilot, filename in PILOT_SEED_GAMEPLAN_FILES.items():
        entry = pilots.get(pilot)
        if not isinstance(entry, dict) or set(entry) != {"source_file", "text", "sha256"}:
            raise SystemExit(f"Invalid seed gameplan entry for {pilot}: {path}")
        text = entry.get("text")
        source_file = entry.get("source_file")
        source_path = Path(str(source_file))
        if (
            not isinstance(text, str)
            or not isinstance(source_file, str)
            or not source_file
            or source_path.is_absolute()
            or ".." in source_path.parts
            or entry.get("sha256") != _seed_gameplan_text_sha256(text)
            or source_path.name != filename
        ):
            raise SystemExit(f"Seed gameplan entry for {pilot} failed validation: {path}")
    fingerprint = _seed_gameplan_fingerprint(snapshot)
    if snapshot.get("fingerprint") != fingerprint:
        raise SystemExit(f"Seed gameplan snapshot fingerprint does not match its contents: {path}")
    if expected_fingerprint is not None and fingerprint != expected_fingerprint:
        raise SystemExit(f"Seed gameplan snapshot fingerprint does not match its binding: {path}")
    if (
        expected_effective_from_game is not None
        and effective != expected_effective_from_game
    ):
        raise SystemExit(f"Seed gameplan snapshot activation game does not match its binding: {path}")
    return snapshot


def _read_seed_gameplan_snapshot(
    path: Path,
    *,
    expected_fingerprint: Optional[str] = None,
    expected_effective_from_game: Optional[int] = None,
) -> Dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Seed gameplan snapshot is missing: {path}")
    try:
        snapshot = read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read seed gameplan snapshot {path}: {exc}") from exc
    return _validate_seed_gameplan_snapshot(
        snapshot,
        path=path,
        expected_fingerprint=expected_fingerprint,
        expected_effective_from_game=expected_effective_from_game,
    )


def _new_seed_gameplan_snapshot(effective_from_game: int) -> Dict[str, Any]:
    pilots: Dict[str, Any] = {}
    for pilot, filename in PILOT_SEED_GAMEPLAN_FILES.items():
        path = SEED_GAMEPLAN_SOURCE_DIR / filename
        if not path.exists():
            raise SystemExit(f"Seed gameplan source is missing: {path}")
        try:
            text = _normalized_seed_gameplan_text(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise SystemExit(f"Could not read seed gameplan source {path}: {exc}") from exc
        pilots[pilot] = {
            "source_file": _seed_gameplan_source_file(pilot),
            "text": text,
            "sha256": _seed_gameplan_text_sha256(text),
        }
    snapshot: Dict[str, Any] = {
        "schema": 1,
        "created_at": now(),
        "effective_from_game": effective_from_game,
        "pilots": pilots,
    }
    snapshot["fingerprint"] = _seed_gameplan_fingerprint(snapshot)
    return snapshot


def _seed_gameplan_binding(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema": 1,
        "snapshot": GAMEPLAN_SEED_SNAPSHOT_FILE,
        "fingerprint": snapshot["fingerprint"],
        "effective_from_game": snapshot["effective_from_game"],
    }


def _validated_seed_gameplan_binding(manifest: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    binding = manifest.get("gameplan_seed_snapshot")
    if binding is None:
        return None
    if not isinstance(binding, dict) or set(binding) != {
        "schema", "snapshot", "fingerprint", "effective_from_game"
    }:
        raise SystemExit("Seed gameplan snapshot binding has an invalid shape.")
    effective = binding.get("effective_from_game")
    if (
        binding.get("schema") != 1
        or binding.get("snapshot") != GAMEPLAN_SEED_SNAPSHOT_FILE
        or not isinstance(binding.get("fingerprint"), str)
        or not binding.get("fingerprint")
        or isinstance(effective, bool)
        or not isinstance(effective, int)
        or effective < 1
    ):
        raise SystemExit("Seed gameplan snapshot binding is invalid.")
    return binding


def _ensure_cohort_seed_gameplan_snapshot(
    root: Path,
    manifest: Dict[str, Any],
    *,
    effective_from_game: int,
) -> Dict[str, Any]:
    """Create/adopt one immutable cohort seed snapshot at a game boundary."""

    if (
        isinstance(effective_from_game, bool)
        or not isinstance(effective_from_game, int)
        or effective_from_game < 1
    ):
        raise SystemExit("Seed gameplan activation game must be a positive integer.")
    binding = _validated_seed_gameplan_binding(manifest)
    path = root / GAMEPLAN_SEED_SNAPSHOT_FILE
    if binding is not None:
        return _read_seed_gameplan_snapshot(
            path,
            expected_fingerprint=binding["fingerprint"],
            expected_effective_from_game=binding["effective_from_game"],
        )
    if path.exists():
        snapshot = _read_seed_gameplan_snapshot(
            path, expected_effective_from_game=effective_from_game
        )
        current_sources = _new_seed_gameplan_snapshot(effective_from_game)
        if snapshot["fingerprint"] != current_sources["fingerprint"]:
            raise SystemExit(
                "Unbound cohort seed gameplan snapshot does not match the current editable sources."
            )
    else:
        snapshot = _new_seed_gameplan_snapshot(effective_from_game)
        write_json(path, snapshot)
    manifest["gameplan_seed_snapshot"] = _seed_gameplan_binding(snapshot)
    manifest["updated_at"] = now()
    write_json(root / "cohort.json", manifest)
    return snapshot


def _messaging_personality_text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _messaging_personality_source_file(pilot: str) -> str:
    return str(
        (MESSAGING_PERSONALITY_SOURCE_DIR / PILOT_MESSAGING_PERSONALITY_FILES[pilot])
        .relative_to(PROJECT_ROOT)
    ).replace("\\", "/")


def _messaging_personality_fingerprint(snapshot: Dict[str, Any]) -> str:
    core = {
        "schema": snapshot.get("schema"),
        "effective_from_game": snapshot.get("effective_from_game"),
        "pilots": snapshot.get("pilots"),
    }
    return hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        .encode("utf-8")
    ).hexdigest()


def _validate_messaging_personality_snapshot(
    snapshot: Any,
    *,
    path: Path,
    expected_fingerprint: Optional[str] = None,
    expected_effective_from_game: Optional[int] = None,
) -> Dict[str, Any]:
    if not isinstance(snapshot, dict) or set(snapshot) != {
        "schema", "created_at", "effective_from_game", "pilots", "fingerprint"
    }:
        raise SystemExit(f"Invalid messaging personality snapshot shape: {path}")
    effective = snapshot.get("effective_from_game")
    if (
        snapshot.get("schema") != 1
        or isinstance(effective, bool)
        or not isinstance(effective, int)
        or effective < 1
        or not isinstance(snapshot.get("created_at"), str)
    ):
        raise SystemExit(f"Invalid messaging personality snapshot metadata: {path}")
    pilots = snapshot.get("pilots")
    if not isinstance(pilots, dict) or set(pilots) != set(PILOT_MESSAGING_PERSONALITY_FILES):
        raise SystemExit(f"Messaging personality snapshot has the wrong pilot set: {path}")
    for pilot, filename in PILOT_MESSAGING_PERSONALITY_FILES.items():
        entry = pilots.get(pilot)
        if not isinstance(entry, dict) or set(entry) != {"source_file", "text", "sha256"}:
            raise SystemExit(f"Invalid messaging personality entry for {pilot}: {path}")
        text = entry.get("text"); source_file = entry.get("source_file")
        source_path = Path(str(source_file))
        if (
            not isinstance(text, str)
            or not isinstance(source_file, str)
            or not source_file
            or source_path.is_absolute()
            or ".." in source_path.parts
            or entry.get("sha256") != _messaging_personality_text_sha256(text)
            or source_path.name != filename
        ):
            raise SystemExit(f"Messaging personality entry for {pilot} failed validation: {path}")
    fingerprint = _messaging_personality_fingerprint(snapshot)
    if snapshot.get("fingerprint") != fingerprint:
        raise SystemExit(f"Messaging personality snapshot fingerprint does not match its contents: {path}")
    if expected_fingerprint is not None and fingerprint != expected_fingerprint:
        raise SystemExit(f"Messaging personality snapshot fingerprint does not match its binding: {path}")
    if expected_effective_from_game is not None and effective != expected_effective_from_game:
        raise SystemExit(f"Messaging personality activation game does not match its binding: {path}")
    return snapshot


def _read_messaging_personality_snapshot(
    path: Path,
    *,
    expected_fingerprint: Optional[str] = None,
    expected_effective_from_game: Optional[int] = None,
) -> Dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Messaging personality snapshot is missing: {path}")
    try:snapshot = read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read messaging personality snapshot {path}: {exc}") from exc
    return _validate_messaging_personality_snapshot(
        snapshot,path=path,expected_fingerprint=expected_fingerprint,
        expected_effective_from_game=expected_effective_from_game)


def _new_messaging_personality_snapshot(effective_from_game: int) -> Dict[str, Any]:
    pilots: Dict[str, Any] = {}
    for pilot, filename in PILOT_MESSAGING_PERSONALITY_FILES.items():
        path = MESSAGING_PERSONALITY_SOURCE_DIR / filename
        if not path.exists():raise SystemExit(f"Messaging personality source is missing: {path}")
        try:text = _normalized_seed_gameplan_text(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise SystemExit(f"Could not read messaging personality source {path}: {exc}") from exc
        pilots[pilot] = {
            "source_file": _messaging_personality_source_file(pilot),
            "text": text,
            "sha256": _messaging_personality_text_sha256(text),
        }
    snapshot: Dict[str, Any] = {
        "schema":1,"created_at":now(),"effective_from_game":effective_from_game,
        "pilots":pilots,
    }
    snapshot["fingerprint"] = _messaging_personality_fingerprint(snapshot)
    return snapshot


def _messaging_personality_binding(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema":1,"snapshot":MESSAGING_PERSONALITY_SNAPSHOT_FILE,
        "fingerprint":snapshot["fingerprint"],
        "effective_from_game":snapshot["effective_from_game"],
    }


def _validated_messaging_personality_binding(
    manifest: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    binding = manifest.get("messaging_personality_snapshot")
    if binding is None:return None
    if not isinstance(binding, dict) or set(binding) != {
        "schema", "snapshot", "fingerprint", "effective_from_game"
    }:
        raise SystemExit("Messaging personality snapshot binding has an invalid shape.")
    effective = binding.get("effective_from_game")
    if (
        binding.get("schema") != 1
        or binding.get("snapshot") != MESSAGING_PERSONALITY_SNAPSHOT_FILE
        or not isinstance(binding.get("fingerprint"), str)
        or not binding.get("fingerprint")
        or isinstance(effective, bool)
        or not isinstance(effective, int)
        or effective < 1
    ):
        raise SystemExit("Messaging personality snapshot binding is invalid.")
    return binding


def _ensure_cohort_messaging_personality_snapshot(
    root: Path,
    manifest: Dict[str, Any],
    *,
    effective_from_game: int,
) -> Dict[str, Any]:
    if (
        isinstance(effective_from_game, bool)
        or not isinstance(effective_from_game, int)
        or effective_from_game < 1
    ):
        raise SystemExit("Messaging personality activation game must be a positive integer.")
    binding = _validated_messaging_personality_binding(manifest)
    path = root / MESSAGING_PERSONALITY_SNAPSHOT_FILE
    if binding is not None:
        return _read_messaging_personality_snapshot(
            path,expected_fingerprint=binding["fingerprint"],
            expected_effective_from_game=binding["effective_from_game"])
    if path.exists():
        snapshot = _read_messaging_personality_snapshot(
            path,expected_effective_from_game=effective_from_game)
        current_sources = _new_messaging_personality_snapshot(effective_from_game)
        if snapshot["fingerprint"] != current_sources["fingerprint"]:
            raise SystemExit(
                "Unbound cohort messaging personality snapshot does not match the current editable sources.")
    else:
        snapshot = _new_messaging_personality_snapshot(effective_from_game)
        write_json(path, snapshot)
    manifest["messaging_personality_snapshot"] = _messaging_personality_binding(snapshot)
    manifest["updated_at"] = now()
    write_json(root / "cohort.json", manifest)
    return snapshot


def _game_has_started(directory: Path) -> bool:
    return any(
        (directory / name).exists()
        for name in (
            "status.json", "decisions.jsonl", GAME_CONFIG_FILE,
            STRATEGY_SNAPSHOT_FILE, GAMEPLAN_SEED_SNAPSHOT_FILE,
            MESSAGING_PERSONALITY_SNAPSHOT_FILE, TERMINAL_SEAL_FILE,
        )
    )


def _gameplan_path(directory: Path, pilot: str) -> Path:
    try:
        filename=PILOT_GAMEPLAN_FILES[pilot]
    except KeyError as exc:
        raise SystemExit(f"Unknown pilot {pilot!r}.") from exc
    return directory/PRIVATE_GAMEPLAN_DIR/filename


def _gameplan_telemetry_path(directory: Path, pilot: str) -> Path:
    try:
        filename=PILOT_GAMEPLAN_FILES[pilot]
    except KeyError as exc:
        raise SystemExit(f"Unknown pilot {pilot!r}.") from exc
    return directory/PRIVATE_GAMEPLAN_DIR/PRIVATE_GAMEPLAN_TELEMETRY_DIR/filename


def _read_gameplan(directory: Path, pilot: str) -> list[Dict[str, Any]]:
    path=_gameplan_path(directory,pilot)
    rows=read_jsonl(path)
    if any(row.get("pilot")!=pilot for row in rows):
        raise SystemExit(f"Private gameplan journal for {pilot} contains an invalid pilot entry.")
    return rows


def _read_gameplan_telemetry(directory: Path, pilot: str) -> list[Dict[str, Any]]:
    """Read one pilot's body-free private GAMEPLAN access audit."""

    rows=read_jsonl(_gameplan_telemetry_path(directory,pilot))
    for row in rows:
        if row.get("pilot")!=pilot or row.get("private") is not True:
            raise SystemExit(f"Private GAMEPLAN telemetry for {pilot} contains an invalid entry.")
        if any(key in row for key in ("text","body","note","rationale")):
            raise SystemExit(f"Private GAMEPLAN telemetry for {pilot} contains strategy text.")
    return rows


def _record_gameplan_telemetry(
    directory: Path,
    actor: str,
    request: Dict[str, Any],
    *,
    dynamic_entry_count: int,
    seed_sha256: Optional[str],
    entry: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Durably record a private full-context query or idempotent write.

    The event deliberately stores only bindings, counts, lengths, and hashes.
    A deterministic event ID means retrying an interrupted write does not add a
    second audit row; an explicit review is similarly recorded once per decision.
    """

    event="gameplan_write" if entry is not None else "gameplan_query"
    identity={
        "event":event,
        "pilot":actor,
        "decision_id":request.get("decision_id"),
        "request_sha256":_request_fingerprint(request),
        "entry_id":entry.get("entry_id") if entry else None,
    }
    event_id="GPT-"+hashlib.sha256(
        json.dumps(identity,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:20]
    path=_gameplan_telemetry_path(directory,actor)
    rows=_read_gameplan_telemetry(directory,actor)
    matches=[row for row in rows if row.get("event_id")==event_id]
    if len(matches)>1:
        raise SystemExit(f"Private GAMEPLAN telemetry for {actor} contains duplicate event IDs.")
    if matches:return matches[0]
    row={
        "schema":1,"private":True,"event_id":event_id,"event":event,
        "recorded_at":now(),"pilot":actor,
        "decision_id":request.get("decision_id"),
        "request_sha256":identity["request_sha256"],
        "accepted_decision_count":_request_accepted_prefix_count(directory,request),
        "returned_full_context":True,
        "visible_dynamic_entry_count":int(dynamic_entry_count),
        "seed_sha256":seed_sha256,
    }
    if entry is not None:
        body=str(entry.get("text") or "")
        row.update({
            "entry_id":entry.get("entry_id"),
            "entry_source":entry.get("source"),
            "entry_scope":normalize_plan_scope(entry.get("scope")),
            "character_count":len(body),
            "content_sha256":hashlib.sha256(body.encode("utf-8")).hexdigest(),
        })
    rows.append(row);write_jsonl(path,rows)
    return row


def _ensure_gameplan_journals(directory: Path) -> None:
    for pilot in PILOT_GAMEPLAN_FILES:
        path=_gameplan_path(directory,pilot)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.touch(exist_ok=True)
        telemetry_path=_gameplan_telemetry_path(directory,pilot)
        telemetry_path.parent.mkdir(parents=True,exist_ok=True)
        telemetry_path.touch(exist_ok=True)


def _request_fingerprint(request: Dict[str, Any]) -> str:
    return decision_request_fingerprint(request)


def _request_pass_on_controls(request: Dict[str, Any]) -> list[Dict[str, Any]]:
    raw=request.get("pass_on_controls",[])
    if not isinstance(raw,list):raise SystemExit("Pending PASS ON controls must be a list.")
    try:controls=[validate_pass_on_control(value) for value in raw]
    except ValueError as exc:raise SystemExit(f"Invalid pending PASS ON control: {exc}") from exc
    identifiers=[control["control_id"] for control in controls]
    if len(identifiers)!=len(set(identifiers)):
        raise SystemExit("Pending PASS ON controls contain duplicate IDs.")
    for control in controls:
        if (control["actor"]!=request.get("actor") or
                control["decision_id"]!=request.get("decision_id")):
            raise SystemExit("Pending PASS ON control binding disagrees with the current decision.")
    return controls


def _request_accepted_prefix_count(directory: Path, request: Dict[str, Any]) -> int:
    rows=read_jsonl(directory/"decisions.jsonl")
    if not request.get("rebase_existing_decision"):return len(rows)
    try:return next(
        index for index,row in enumerate(rows)
        if row.get("decision_id")==request.get("decision_id")
    )
    except StopIteration as exc:
        raise SystemExit(
            "Cannot project the private gameplan: the rebased decision is absent from the accepted tape."
        ) from exc


def _visible_gameplan(directory: Path, pilot: str,
                      request: Dict[str, Any]) -> list[Dict[str, Any]]:
    prefix_count=_request_accepted_prefix_count(directory,request)
    visible=[]
    for row in _read_gameplan(directory,pilot):
        try:anchor=int(row.get("accepted_decision_count",10**18))
        except (TypeError,ValueError):continue
        if anchor<=prefix_count:visible.append(row)
    return visible


def _next_gameplan_entry_id(rows: Iterable[Dict[str, Any]]) -> str:
    ordinals=[]
    for row in rows:
        value=str(row.get("entry_id") or "")
        if value.startswith("GP") and value[2:].isdigit():ordinals.append(int(value[2:]))
    return f"GP{(max(ordinals,default=0)+1):04d}"


def _new_gameplan_entry(
    directory: Path,
    actor: str,
    request: Dict[str, Any],
    text: str,
    *,
    accepted_decision_count: int,
    source: str,
    scope: str = DEFAULT_PLAN_SCOPE,
    rows: Optional[list[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    existing=list(rows if rows is not None else _read_gameplan(directory,actor))
    entry = {
        "schema":1,
        "entry_id":_next_gameplan_entry_id(existing),
        "pilot":actor,
        "written_at":now(),
        "decision_id":request["decision_id"],
        "accepted_decision_count":accepted_decision_count,
        "request_sha256":_request_fingerprint(request),
        "round":request.get("round"),
        "turn":request.get("turn"),
        "phase":request.get("phase"),
        "source":source,
        "scope":normalize_plan_scope(scope),
        "text":text,
    }
    requirement = request.get(MANDATORY_LONG_TERM_UPDATE_FIELD) or {}
    if (
        entry["scope"] == "long_term"
        and isinstance(requirement, dict)
        and requirement.get("required") is True
        and requirement.get("cadence_id")
    ):
        entry[MAIN_PHASE_REVIEW_FIELD] = {
            "schema": 1,
            "cadence": "once_per_own_main_phase",
            "cadence_id": str(requirement["cadence_id"]),
            "seed_sha256": requirement.get("seed_sha256"),
            "full_seed_delivered": requirement.get("seed_inspection") == "full",
        }
    return entry


def _main_phase_review_cadence_id(request: Dict[str, Any]) -> Optional[str]:
    """Name one actor-private main-phase planning checkpoint."""

    if (
        request.get("kind") != "main_action"
        or request.get("phase") not in MAIN_PHASES
        or request.get("rebase_existing_decision")
    ):
        return None
    turn = request.get("turn")
    if isinstance(turn, bool) or not isinstance(turn, int) or turn < 1:
        return None
    actor = str(request.get("actor") or "")
    if not actor:
        return None
    return f"{actor}|turn:{turn}|phase:{request['phase']}"


def _pending_main_phase_review(
    request: Dict[str, Any], entries: Iterable[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Return the declarative review gate when this phase has no completion entry."""

    cadence_id = _main_phase_review_cadence_id(request)
    if cadence_id is None:
        return None
    for entry in entries:
        review = entry.get(MAIN_PHASE_REVIEW_FIELD) or {}
        if (
            normalize_plan_scope(entry.get("scope")) == "long_term"
            and isinstance(review, dict)
            and review.get("cadence_id") == cadence_id
            and review.get("full_seed_delivered") is True
        ):
            return None
    return {
        "schema": 1,
        "private": True,
        "required": True,
        "cadence": "once_per_own_main_phase",
        "cadence_id": cadence_id,
        "phase": request.get("phase"),
        "turn": request.get("turn"),
        "seed_inspection": "full",
        "completion": "append_one_long_term_dynamic_entry",
        "help": (
            "Before this main-phase gameplay decision can be accepted, review the complete "
            "seed plan supplied privately and either write a long-term GAMEPLAN entry or "
            "attach --plan-delta with --plan-scope long-term to the gameplay answer."
        ),
    }


def _gameplan_discard_summary(discarded: list[Dict[str, Any]]) -> Dict[str, Any]:
    if not discarded:return {"count":0,"sha256":None}
    digest=hashlib.sha256(
        json.dumps(
            discarded,sort_keys=True,separators=(",",":"),ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    return {"count":len(discarded),"sha256":digest}


def _prepare_inline_gameplan_entry(
    directory: Path,
    request: Dict[str, Any],
    text: str,
    *,
    accepted_decision_count: int,
    rebase_cut: Optional[int],
    scope: str = DEFAULT_PLAN_SCOPE,
) -> tuple[list[Dict[str, Any]],Dict[str, Any]]:
    """Prepare an idempotent future-anchored journal commit.

    The returned entry is invisible while the accepted tape is still shorter
    than its anchor.  This permits writing the journal immediately before the
    tape rename without exposing a failed candidate branch.
    """
    actor=str(request["actor"]);stored=_read_gameplan(directory,actor)
    scope=normalize_plan_scope(scope)
    kept=[];discarded=[]
    for row in stored:
        try:anchor=int(row.get("accepted_decision_count",10**18))
        except (TypeError,ValueError):anchor=10**18
        if rebase_cut is not None and anchor>rebase_cut:discarded.append(row)
        else:kept.append(row)
    matches=[
        row for row in kept
        if row.get("source")=="inline_plan_delta"
        and row.get("decision_id")==request.get("decision_id")
    ]
    expected_hash=_request_fingerprint(request)
    if len(matches)>1:
        raise SystemExit("The private gameplan has duplicate inline updates for this decision.")
    if matches:
        entry=matches[0]
        if (
            entry.get("pilot")!=actor or entry.get("text")!=text
            or normalize_plan_scope(entry.get("scope"))!=scope
            or entry.get("accepted_decision_count")!=accepted_decision_count
            or entry.get("request_sha256")!=expected_hash
        ):
            raise SystemExit(
                "A different private plan delta is already staged for this decision; "
                "retry the same answer and delta or reconcile the interrupted commit."
            )
    else:
        entry=_new_gameplan_entry(
            directory,actor,request,text,
            accepted_decision_count=accepted_decision_count,
            source="inline_plan_delta",scope=scope,rows=kept)
        kept.append(entry)
    return kept,entry


def _prepare_draw_planning_entries(
    directory: Path,
    request: Dict[str, Any],
    *,
    short_term_plan: str,
    long_term_action: str,
    long_term_rationale: str,
    long_term_plan: Optional[str],
    accepted_decision_count: int,
    rebase_cut: Optional[int],
) -> tuple[list[Dict[str, Any]],list[Dict[str, Any]]]:
    """Prepare one atomic first-draw plan replacement and review."""
    actor=str(request["actor"]);stored=_read_gameplan(directory,actor)
    kept=[]
    for row in stored:
        try:anchor=int(row.get("accepted_decision_count",10**18))
        except (TypeError,ValueError):anchor=10**18
        if rebase_cut is None or anchor<=rebase_cut:kept.append(row)
    matches=[
        row for row in kept
        if row.get("source")=="draw_planning_checkpoint"
        and row.get("decision_id")==request.get("decision_id")
    ]
    if matches:
        raise SystemExit(
            "This decision already has a committed draw-planning batch; retry the "
            "same interrupted answer or reconcile the decision tape."
        )
    checkpoint=request.get(PLANNING_CHECKPOINT_FIELD) or {}
    review={
        "schema":1,"cadence":"first_draw_each_turn",
        "cadence_id":checkpoint.get("cadence_id"),
        "seed_sha256":checkpoint.get("seed_sha256"),
        "full_seed_delivered":checkpoint.get("seed_inspection")=="full",
        "long_term_action":long_term_action,
        "long_term_rationale":long_term_rationale,
    }
    short_entry=_new_gameplan_entry(
        directory,actor,request,short_term_plan,
        accepted_decision_count=accepted_decision_count,
        source="draw_planning_checkpoint",scope="short_term",rows=kept)
    short_entry["mode"]="replace"
    short_entry[DRAW_PLANNING_REVIEW_FIELD]=review
    entries=[short_entry];kept.append(short_entry)
    if long_term_action=="revise":
        long_entry=_new_gameplan_entry(
            directory,actor,request,str(long_term_plan),
            accepted_decision_count=accepted_decision_count,
            source="draw_planning_checkpoint",scope="long_term",rows=kept)
        long_entry["mode"]="replace"
        long_entry[DRAW_PLANNING_REVIEW_FIELD]={
            key:value for key,value in review.items()
            if key!="long_term_rationale"
        }
        entries.append(long_entry);kept.append(long_entry)
    return kept,entries


def _load_game_seed_gameplan_snapshot(directory: Path) -> Optional[Dict[str, Any]]:
    path = directory / GAMEPLAN_SEED_SNAPSHOT_FILE
    config_path = directory / GAME_CONFIG_FILE
    config = read_json(config_path) if config_path.exists() else {}
    binding = _validated_seed_gameplan_binding(config)
    if binding is not None and not path.exists():
        raise SystemExit(f"Game seed gameplan snapshot is missing: {path}")
    if binding is None and path.exists():
        raise SystemExit(f"Game seed gameplan snapshot is not bound by {config_path}: {path}")
    if not path.exists():
        return None
    return _read_seed_gameplan_snapshot(
        path,
        expected_fingerprint=(binding or {}).get("fingerprint"),
        expected_effective_from_game=(binding or {}).get("effective_from_game"),
    )


def _load_game_messaging_personality_snapshot(
    directory: Path,
) -> Optional[Dict[str, Any]]:
    path = directory / MESSAGING_PERSONALITY_SNAPSHOT_FILE
    config_path = directory / GAME_CONFIG_FILE
    config = read_json(config_path) if config_path.exists() else {}
    binding = _validated_messaging_personality_binding(config)
    if binding is not None and not path.exists():
        raise SystemExit(f"Game messaging personality snapshot is missing: {path}")
    if binding is None and path.exists():
        raise SystemExit(f"Game messaging personality snapshot is not bound by {config_path}: {path}")
    if not path.exists():return None
    return _read_messaging_personality_snapshot(
        path,expected_fingerprint=(binding or {}).get("fingerprint"),
        expected_effective_from_game=(binding or {}).get("effective_from_game"))


def _private_gameplan_context(
    directory: Path,
    request: Dict[str, Any],
    seed_snapshot: Optional[Dict[str, Any]] = None,
    *,
    automatic: bool = False,
) -> Dict[str, Any]:
    actor = str(request.get("actor", ""))
    if actor not in PILOT_SEED_GAMEPLAN_FILES:
        raise SystemExit(f"Cannot build private gameplan context for unknown pilot {actor!r}.")
    if seed_snapshot is None:
        seed_snapshot = _load_game_seed_gameplan_snapshot(directory)
    entries = _visible_gameplan(directory, actor, request)
    if seed_snapshot is None:
        seed = {
            "text": "",
            "sha256": _seed_gameplan_text_sha256(""),
            "snapshot_fingerprint": None,
            "source_file": None,
            "legacy_empty": True,
        }
    else:
        validated = _validate_seed_gameplan_snapshot(
            seed_snapshot,
            path=directory / GAMEPLAN_SEED_SNAPSHOT_FILE,
        )
        stored = validated["pilots"][actor]
        seed = {
            "text": stored["text"],
            "sha256": stored["sha256"],
            "snapshot_fingerprint": validated["fingerprint"],
            "source_file": stored["source_file"],
            "legacy_empty": False,
        }
    projected = [
        {
            key: entry.get(key)
            for key in (
                "entry_id", "written_at", "decision_id", "round", "turn", "phase",
                "scope", "text", "mode", DRAW_PLANNING_REVIEW_FIELD,
            )
        } | {"scope": normalize_plan_scope(entry.get("scope"))}
        for entry in entries
    ]
    return {
        "schema": 1,
        "private": True,
        "read_is_automatic": bool(automatic),
        "delivery": "opening" if automatic else "query",
        "seed": seed,
        "dynamic_notes": projected,
        "dynamic_entry_count": len(projected),
    }


def _with_gameplan_action(
    directory: Path,
    request: Optional[Dict[str, Any]],
    seed_snapshot: Optional[Dict[str, Any]] = None,
    *,
    reveal_context: bool = False,
    decision_surface_revision: int = LEGACY_DECISION_SURFACE_REVISION,
) -> Optional[Dict[str, Any]]:
    """Attach private strategy context without changing the decision surface."""
    if request is None:return None
    revision=_validate_decision_surface_revision(decision_surface_revision)
    result=dict(request);actor=str(result.get("actor",""))
    result.pop("gameplan",None)
    result.pop("private_gameplan_context",None)
    result.pop("private_active_plan",None)
    result.pop("active_plan_delivery",None)
    result.pop(MANDATORY_LONG_TERM_UPDATE_FIELD,None)
    if result.get('planning_contract',1)>=2:
        result.pop(PLANNING_CHECKPOINT_FIELD,None)
        result['gameplan_access']=result.get('kind') in GAMEPLAN_PRIORITY_KINDS
        result['gameplan']={
            'schema':2,'private':True,'can_append':False,'inline_update':False,
            'help':'The background planner maintains written continuity. Use the current facts and '
                   'delivered plan to reason about this action. No plan adoption, KEEP/REVISE, '
                   'written fallback or plan-validation response is required. At an eligible '
                   'strategic answer, planner_update may request short_term or long_term maintenance.'}
        if result.get('planning_contract',1)>=3:
            result['gameplan']['help']='The planner maintains continuity and written plans. The latest completed version arrives on the next unclaimed decision, in any phase. Use Python-reported changes to reason about this action; no plan-writing or validation turn. Planner alarms are available at priority; see planner_control.'
        if result.get('planning_contract',1)>=4:
            result['gameplan']['help']+=' During an ordinary own main-phase action, you may approve/reject the proposed sequence by step ID in one batch; order approved IDs, override choices/rationales/snoozes, or add full steps for newly available cards with their own rationale and scheduler. Python executes only the exact legal prefix and returns the stopping reason. Ordinary answers remain available.'
        return result
    automatic_opening = bool(result.get("opening_gameplan_context"))
    if "opening_gameplan_context" not in result and result.get("kind") == "mulligan":
        # Cohorts with a pending mulligan created before this marker existed still
        # receive their opening delivery. Newly generated follow-up mulligans carry
        # an explicit false marker and therefore do not repeat the full plan.
        automatic_opening = True
    if "gameplan_access" not in result:
        result["gameplan_access"]=result.get("kind") in GAMEPLAN_PRIORITY_KINDS
    planning_due=bool((result.get(PLANNING_CHECKPOINT_FIELD) or {}).get("required"))
    strategic=(
        revision>=ACTIVE_PLAN_DECISION_SURFACE_REVISION
        and (revision>=SCHEDULER_DECISION_SURFACE_REVISION or is_strategic_request(result) or planning_due)
    )
    entries=_visible_gameplan(directory,actor,result)
    mandatory_review=(
        _pending_main_phase_review(result,entries)
        if strategic and revision==ACTIVE_PLAN_DECISION_SURFACE_REVISION else None
    )
    planning_checkpoint=(result.get(PLANNING_CHECKPOINT_FIELD) or {})
    planning_due=(
        revision>=DRAW_PLANNING_DECISION_SURFACE_REVISION
        and isinstance(planning_checkpoint,dict)
        and planning_checkpoint.get("required") is True
    )
    private_context=None
    if automatic_opening or reveal_context or strategic:
        private_context=_private_gameplan_context(
            directory,result,seed_snapshot,automatic=automatic_opening)
    if mandatory_review:
        private_context=dict(private_context or {})
        private_context["read_is_automatic"]=True
        private_context["delivery"]="mandatory_main_phase_review"
        mandatory_review["seed_sha256"]=(private_context.get("seed") or {}).get("sha256")
        result[MANDATORY_LONG_TERM_UPDATE_FIELD]=mandatory_review
    if planning_due:
        private_context=dict(private_context or {})
        private_context["read_is_automatic"]=True
        private_context["delivery"]="draw_planning_checkpoint"
        planning_checkpoint=dict(planning_checkpoint)
        planning_checkpoint["seed_inspection"]="full"
        planning_checkpoint["seed_sha256"]=(private_context.get("seed") or {}).get("sha256")
        result[PLANNING_CHECKPOINT_FIELD]=planning_checkpoint
    if automatic_opening or reveal_context or mandatory_review or planning_due:
        result["private_gameplan_context"]=private_context
    active=None
    if strategic:
        active=project_active_plan(
            actor=actor,
            seed=(private_context or {}).get("seed") or {},
            dynamic_entries=(private_context or {}).get("dynamic_notes") or [],
            request=result,
        )
        result["private_active_plan"]=active
        result["active_plan_delivery"]=delivery_telemetry(active,result)
    # Full-query writes retain the legacy eligibility boundary; revised games
    # gain the independent inline-update path on any strategic answer.
    can_append=bool(result.get("gameplan_access"))
    if automatic_opening:
        lead=(
            "The seed plan and currently visible dynamic notes are loaded for this "
            "pilot's one-time opening delivery. Choose GAMEPLAN to reprint them privately. "
        )
    else:
        lead=(
            "Choose GAMEPLAN with no rationale to privately load the seed plan and currently "
            "visible dynamic notes without consuming this decision. "
        )
    if revision>=ACTIVE_PLAN_DECISION_SURFACE_REVISION:
        if planning_due:
            help_text=planning_checkpoint_help(
                opening_long_term_required=bool(
                    planning_checkpoint.get("opening_long_term_plan_required")
                )
            )
        elif mandatory_review:
            help_text=str(mandatory_review["help"])
        else:
            help_text=(
                "GAMEPLAN privately opens the complete frozen seed and branch-visible journal "
                "without consuming this decision. Add --plan-delta to an ordinary answer when "
                "your immediate line changes; add --plan-scope long-term for durable objectives."
            )
    elif can_append:
        help_text=(
            lead+
            "If strategy changes, use answer GAMEPLAN --rationale \"...\" (equivalently, "
            "gameplan --write \"...\") to append a private dynamic note. The pending gameplay "
            "decision remains unchanged."
        )
    else:
        help_text=(
            lead+
            "This decision permits review only; dynamic updates become available at an eligible "
            "main-action, upkeep-action, priority, or specialized response window. The pending "
            "gameplay decision remains unchanged."
        )
    result["gameplan"]={
        "schema":1,
        "private":True,
        "entry_count":len(entries),
        "choice":GAMEPLAN_CHOICE,
        "consumes_decision":False,
        "can_append":can_append,
        "inline_update":strategic,
        "update_recommended":bool(active and active.get("update_recommended")),
        "mandatory_long_term_update":bool(mandatory_review),
        "planning_checkpoint_due":planning_due,
        "help":help_text,
    }
    return result


def _with_messaging_personality(
    directory: Path,
    request: Optional[Dict[str, Any]],
    personality_snapshot: Optional[Dict[str, Any]] = None,
    *,
    decision_surface_revision: int = LEGACY_DECISION_SURFACE_REVISION,
) -> Optional[Dict[str, Any]]:
    """Attach private characterization whenever planning or politics needs it."""
    if request is None:return None
    result=dict(request);result.pop("private_messaging_personality",None)
    revision=_validate_decision_surface_revision(decision_surface_revision)
    kind=result.get("kind")
    reasons=[]
    if revision==LEGACY_DECISION_SURFACE_REVISION and kind in {
        "main_action","messageboard_compose","messageboard_response"
    }:
        reasons.append("messageboard")
    elif revision==ACTIVE_PLAN_DECISION_SURFACE_REVISION and kind in {
        "messageboard_compose","messageboard_response"
    }:
        reasons.append("messageboard")
    elif revision>=DRAW_PLANNING_DECISION_SURFACE_REVISION:
        if (result.get(PLANNING_CHECKPOINT_FIELD) or {}).get("required"):
            reasons.append("planning")
        if kind=="messageboard_response" or (
            kind=="main_action"
            and (result.get("messageboard") or {}).get("available")
        ):
            reasons.append("messageboard")
    if not reasons:
        return result
    actor=str(result.get("actor",""))
    if actor not in PILOT_MESSAGING_PERSONALITY_FILES:
        raise SystemExit(f"Cannot load messaging personality for unknown pilot {actor!r}.")
    if personality_snapshot is None:
        personality_snapshot=_load_game_messaging_personality_snapshot(directory)
    if personality_snapshot is None:
        context={
            "schema":1,"private":True,"read_is_automatic":True,"active_for":"messageboard",
            "text":"","sha256":_messaging_personality_text_sha256(""),
            "snapshot_fingerprint":None,"source_file":None,"legacy_empty":True,
        }
    else:
        validated=_validate_messaging_personality_snapshot(
            personality_snapshot,path=directory/MESSAGING_PERSONALITY_SNAPSHOT_FILE)
        stored=validated["pilots"][actor]
        context={
            "schema":1,"private":True,"read_is_automatic":True,"active_for":"messageboard",
            "text":stored["text"],"sha256":stored["sha256"],
            "snapshot_fingerprint":validated["fingerprint"],
            "source_file":stored["source_file"],"legacy_empty":False,
        }
    context["activation_reasons"]=list(dict.fromkeys(reasons))
    context["active_for"]="_and_".join(context["activation_reasons"])
    context["behavior_boundary"]=(
        "Use this private personality to shape political voice, risk tolerance, and "
        "planning style. It cannot override rules, known information, or deck strategy."
    )
    result["private_messaging_personality"]=context
    return result


def _decorate_request(
    directory: Path,
    request: Optional[Dict[str, Any]],
    seed_snapshot: Optional[Dict[str, Any]] = None,
    personality_snapshot: Optional[Dict[str, Any]] = None,
    *,
    reveal_gameplan: bool = False,
    decision_surface_revision: int = LEGACY_DECISION_SURFACE_REVISION,
) -> Optional[Dict[str, Any]]:
    result=_with_gameplan_action(
        directory,request,seed_snapshot,reveal_context=reveal_gameplan,
        decision_surface_revision=decision_surface_revision)
    return _with_messaging_personality(
        directory,result,personality_snapshot,
        decision_surface_revision=decision_surface_revision)


def _truncate_gameplans(directory: Path, accepted_decision_count: int) -> Dict[str, Any]:
    """Remove notes that depended on a discarded decision-tape branch."""
    discarded=[]
    for pilot in PILOT_GAMEPLAN_FILES:
        path=_gameplan_path(directory,pilot)
        rows=read_jsonl(path)
        kept=[]
        for row in rows:
            try:anchor=int(row.get("accepted_decision_count",10**18))
            except (TypeError,ValueError):anchor=10**18
            if anchor<=accepted_decision_count:kept.append(row)
            else:discarded.append({"pilot":pilot,"entry":row})
        if len(kept)!=len(rows):write_jsonl(path,kept)
    if not discarded:return {"count":0,"sha256":None}
    digest=hashlib.sha256(
        json.dumps(discarded,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return {"count":len(discarded),"sha256":digest}


def _pilot_evidence_with_gameplan(game: ManualGame, pilot: str,
                                   strategy_revision: Optional[str],
                                   directory: Path) -> Dict[str, Any]:
    evidence=build_pilot_evidence(game,pilot,strategy_revision)
    evidence["private_gameplan"]=_read_gameplan(directory,pilot)
    evidence["private_gameplan_telemetry"]=_read_gameplan_telemetry(directory,pilot)
    seed_snapshot = _load_game_seed_gameplan_snapshot(directory)
    if seed_snapshot is None:
        evidence["private_seed_gameplan"] = {
            "text": "",
            "sha256": _seed_gameplan_text_sha256(""),
            "snapshot_fingerprint": None,
            "source_file": None,
            "legacy_empty": True,
        }
    else:
        stored = seed_snapshot["pilots"][pilot]
        evidence["private_seed_gameplan"] = {
            "text": stored["text"],
            "sha256": stored["sha256"],
            "snapshot_fingerprint": seed_snapshot["fingerprint"],
            "source_file": stored["source_file"],
            "legacy_empty": False,
        }
    personality_snapshot = _load_game_messaging_personality_snapshot(directory)
    if personality_snapshot is None:
        evidence["private_messaging_personality"] = {
            "text":"","sha256":_messaging_personality_text_sha256(""),
            "snapshot_fingerprint":None,"source_file":None,"legacy_empty":True,
        }
    else:
        stored = personality_snapshot["pilots"][pilot]
        evidence["private_messaging_personality"] = {
            "text":stored["text"],"sha256":stored["sha256"],
            "snapshot_fingerprint":personality_snapshot["fingerprint"],
            "source_file":stored["source_file"],"legacy_empty":False,
        }
    rules_tag=quarantine.rules_integrity_tag(directory.parent,int(evidence['game']))
    if rules_tag is not None:evidence['rules_integrity']=rules_tag
    if getattr(game,'decision_surface_revision',1)>=SCHEDULER_DECISION_SURFACE_REVISION:
        evidence['schema']=3
        evidence['decision_contexts']=pilot_handoff.accepted_contexts(
            directory,read_jsonl(directory/'decisions.jsonl'),pilot)
        inspection_rows,inspection_payloads=_inspection_review_records(directory,pilot)
        evidence['inspections']=inspection_rows
        evidence['inspection_evidence']=inspection_payloads
        evidence['rejected_answers']=[row for row in read_jsonl(directory/'rejections.jsonl') if row.get('actor')==pilot]
        evidence['review_requirements']=review_contract.review_requirements(evidence)
        evidence=review_contract.compact_evidence(evidence)
    if getattr(game,'planning_contract',1)>=2:
        from . import planner_runtime, handoff_runtime
        evidence['private_continuity']=planner_runtime.evidence(directory.parent,game.game_no,pilot)
        receipts={}
        for row in read_jsonl(directory/'decisions.jsonl'):
            binding=row.get('auxiliary_payload',{}).get('runtime')
            if getattr(game,'planning_contract',1)<4 and row.get('actor')==pilot and binding:
                from .runtime_store import get
                receipt=get(handoff_runtime.directory_for(directory.parent,game.game_no)/'attachments',binding['attachment_id'])
                receipts[row['decision_id']]=receipt
        if getattr(game,'planning_contract',1)>=4:
            from . import sequence_runtime
            evidence['private_continuity']['accepted_deliveries']=sequence_runtime.review_deliveries(
                directory.parent,game.game_no,pilot,read_jsonl(directory/'decisions.jsonl'))
        else:evidence['private_continuity']['accepted_deliveries']=receipts
    return evidence


def _combo_adjudication_responses(path: Path) -> list[Dict[str, Any]]:
    responses=[];seen=set()
    for row in read_jsonl(path):
        if not isinstance(row,dict) or set(row)!={
            "schema","accepted_at","proposal_decision_id","accepted_decision_count","response"
        }:
            raise SystemExit(f"Invalid combo adjudication journal envelope in {path}.")
        accepted_count=row.get("accepted_decision_count")
        proposal_decision_id=row.get("proposal_decision_id")
        if (row.get("schema")!=1 or isinstance(accepted_count,bool) or
                not isinstance(accepted_count,int) or accepted_count<1 or
                not isinstance(proposal_decision_id,str) or not proposal_decision_id):
            raise SystemExit(f"Invalid combo adjudication journal metadata in {path}.")
        try:
            response=validate_combo_adjudication_response(row.get("response"),known_pilots=tuple(PILOT_GAMEPLAN_FILES))
        except ComboAdjudicationValidationError as exc:
            raise SystemExit(f"Invalid combo adjudication journal response in {path}: {exc}") from exc
        if f"-P-{proposal_decision_id}-" not in response["proposal_id"]:
            raise SystemExit(
                f"Combo adjudication journal proposal binding disagrees in {path}.")
        if response["proposal_id"] in seen:
            raise SystemExit(f"Duplicate combo proposal {response['proposal_id']} in {path}.")
        seen.add(response["proposal_id"]);responses.append(response)
    return responses


def _partition_combo_adjudications(
    directory: Path,
    kept_decision_ids: set[str],
    accepted_decision_count: Optional[int] = None,
) -> tuple[list[Dict[str, Any]],list[Dict[str, Any]]]:
    path=directory/COMBO_ADJUDICATION_JOURNAL
    rows=read_jsonl(path);kept=[];discarded=[]
    for row in rows:
        anchored=row.get("proposal_decision_id") in kept_decision_ids
        accepted_before_cut=(
            accepted_decision_count is None or
            row.get("accepted_decision_count",10**18)<=accepted_decision_count
        )
        if anchored and accepted_before_cut:kept.append(row)
        else:discarded.append(row)
    return kept,discarded


def _truncate_combo_adjudications(
    directory: Path,
    kept_decision_ids: set[str],
    accepted_decision_count: Optional[int] = None,
) -> Dict[str, Any]:
    path=directory/COMBO_ADJUDICATION_JOURNAL
    kept,discarded=_partition_combo_adjudications(
        directory,kept_decision_ids,accepted_decision_count)
    if discarded:write_jsonl(path,kept)
    if not discarded:return {"count":0,"sha256":None}
    return {
        "count":len(discarded),
        "sha256":hashlib.sha256(
            json.dumps(discarded,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
    }


REVIEW_RESOLVED_STATES = {"applied", "no_changes", "legacy_waived", "skipped_by_configuration"}
REVIEW_LOCKED_STATES = {"pending", "rules_blocker"}


def _review_applications(directory: Path) -> list[Path]:
    audit_dir = directory / POSTGAME_LEARNING_DIR
    if not audit_dir.exists():
        return []
    valid=[]
    for path in sorted(audit_dir.glob("application_*.json")):
        try:
            audit=read_json(path)
            transaction_path=audit_dir/LEARNING_TRANSACTION_FILE
            transaction=read_json(transaction_path)
            transaction_payload={
                key:value for key,value in transaction.items()
                if key!="transaction_fingerprint"
            }
            transaction_fingerprint=hashlib.sha256(
                json.dumps(transaction_payload,sort_keys=True,separators=(",",":")).encode("utf-8")
            ).hexdigest()
            source_game=int(audit.get("source_game",-1))
            expected_game=int(directory.name.rsplit("_",1)[-1])
            patch_digest=str(audit.get("patch_sha256",""))
            patch_document_digest=hashlib.sha256(
                json.dumps(
                    audit.get("patch"),sort_keys=True,separators=(",",":"),ensure_ascii=False
                ).encode("utf-8")
            ).hexdigest()
            disposition=str(audit.get("review_disposition",""))
            base=audit.get("base_revision")
            result=audit.get("result_revision")
            request=read_json(directory/POSTGAME_REVIEW_DIR/REVIEW_REQUEST_FILE)
            response=read_json(directory/POSTGAME_REVIEW_DIR/"response.json")
            seal=read_json(directory/TERMINAL_SEAL_FILE)
            transaction_audit=transaction.get("audit")
            updated=StrategyState.from_dict(transaction["updated_strategy"])
            sealed_payload={key:value for key,value in seal.items() if key!="terminal_fingerprint"}
            sealed_fingerprint="terminal-"+hashlib.sha256(
                json.dumps(sealed_payload,sort_keys=True,separators=(",",":")).encode("utf-8")
            ).hexdigest()
        except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError,StrategyValidationError):
            continue
        if (
            source_game==expected_game
            and len(patch_digest)==64
            and all(char in "0123456789abcdefABCDEF" for char in patch_digest)
            and disposition in {"applied","no_changes"}
            and isinstance(base,dict)
            and isinstance(result,dict)
            and transaction.get("state")=="committed"
            and transaction.get("transaction_fingerprint")==transaction_fingerprint
            and isinstance(transaction_audit,dict)
            and transaction.get("source_game")==source_game
            and transaction.get("patch_sha256")==patch_digest
            and transaction.get("base_revision_id")==base.get("revision_id")
            and transaction.get("result_revision_id")==result.get("revision_id")
            and updated.freeze().revision_id==result.get("revision_id")
            and transaction_audit.get("patch_sha256")==patch_digest
            and transaction_audit.get("patch_document_sha256")==patch_document_digest
            and audit.get("patch_document_sha256")==patch_document_digest
            and audit.get("review_id")==request.get("review_id")
            and audit.get("terminal_fingerprint")==request.get("terminal_fingerprint")
            and seal.get("terminal_fingerprint")==sealed_fingerprint
            and request.get("terminal_fingerprint")==sealed_fingerprint
            and response.get("patch_sha256")==patch_digest
            and response.get("disposition")==disposition
            and Path(str(audit.get("audit_path",""))).name==path.name
        ):
            valid.append(path)
    return valid


def _migrate_cohort_manifest(root: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Upgrade pre-review-gate cohorts without retroactively blocking them.

    Games completed before the gate existed are explicitly marked
    ``legacy_waived`` unless a learning application proves that their review was
    applied. The existing active game is preserved, so historical cohorts never
    jump backwards merely because newer workflow code reads them.
    """

    if int(manifest.get("schema", 1)) >= COHORT_SCHEMA:
        return manifest
    migrated = dict(manifest)
    games = {str(key): dict(value) for key, value in manifest.get("games", {}).items()}
    for game_key, entry in games.items():
        if entry.get("state") == "complete":
            applications = _review_applications(root / f"game_{int(game_key):02d}")
            entry["postgame_review"] = {
                "state": "applied" if applications else "legacy_waived",
                "migrated_at": now(),
                **({
                    "audit_path": str(applications[-1].relative_to(root)).replace("\\", "/")
                } if applications else {}),
            }
        else:
            entry.setdefault("postgame_review", {"state": "not_ready"})
    migrated["schema"] = COHORT_SCHEMA
    migrated["games"] = games
    target = int(migrated.get("target_games", 0))
    all_resolved = bool(target) and all(
        games.get(str(number), {}).get("state") == "complete"
        and games.get(str(number), {}).get("postgame_review", {}).get("state")
        in REVIEW_RESOLVED_STATES
        for number in range(1, target + 1)
    )
    migrated["cohort_state"] = "complete" if all_resolved else "active"
    migrated["updated_at"] = now()
    write_json(root / "cohort.json", migrated)
    return migrated


def load_manifest(root: Path) -> Dict[str, Any]:
    path = root / "cohort.json"
    if not path.exists():
        raise SystemExit(f"No cohort at {root}. Run init first.")
    return _migrate_cohort_manifest(root, read_json(path))


def _require_cohort_not_cancelled(manifest: Dict[str, Any], action: str) -> None:
    if manifest.get("cohort_state") == "cancelled":
        raise SystemExit(
            f"Cannot {action}: this cohort was cancelled. Start a new cohort instead."
        )


def game_dir(root: Path, game_number: int) -> Path:
    return root / f"game_{game_number:02d}"


def game_config(manifest: Dict[str, Any], game_number: int) -> Dict[str, Any]:
    if not 1 <= game_number <= manifest["target_games"]:
        raise SystemExit(f"game must be between 1 and {manifest['target_games']}")
    config = {
        "game": game_number,
        "seed": manifest["seed_start"] + game_number - 1,
        "max_rounds": manifest["max_rounds"],
        "decision_surface_revision": _validate_decision_surface_revision(
            manifest.get(
                "decision_surface_revision", LEGACY_DECISION_SURFACE_REVISION
            )
        ),
    }
    planning=manifest.get('planning_runtime') or {}
    if 'learning_enabled' in manifest:
        from .learning_policy import enabled
        config['learning_enabled']=enabled(manifest)
    config['planning_contract']=planning.get('contract',1) if game_number>=planning.get('effective_from_game',1) else 1
    config['planner_stages']=bool(planning.get('stages',False) and config['planning_contract']==4)
    config['plan_tiers']=bool(planning.get('tiers',False) and config['planner_stages'])
    config['context_handling']=planning.get('context_handling',0) if config['planning_contract']==4 else 0
    if 'selection_batch_after' in manifest:config['selection_batch_after']=manifest['selection_batch_after']
    if 'proliferate_batch_after' in manifest:config['proliferate_batch_after']=manifest['proliferate_batch_after']
    if 'combat_blocker_batch' in manifest:
        from .block_declaration import version
        config['combat_blocker_batch']=version(manifest['combat_blocker_batch'])
    if 'combat_damage_batch' in manifest:
        from .combat_damage import version as damage_version
        config['combat_damage_batch']=damage_version(manifest['combat_damage_batch'])
    for field in ('agent_architecture','async_diplomacy','decision_roles','static_standing','combat_proposals','turn_batches','short_term_sol_fast'):
        if planning.get(field) and game_number>=planning.get('effective_from_game',1):config[field]=planning[field]
    from .agent_architecture import validate_binding
    validate_binding(config)
    if config['planning_contract'] not in {1,2,3,4} or isinstance(config['planning_contract'],bool):
        raise SystemExit('Unsupported planning contract.')
    if config['planning_contract']>=2 and config['decision_surface_revision']!=6:
        raise SystemExit('Split planning requires decision surface 6.')
    binding = _validated_seed_gameplan_binding(manifest)
    if binding is not None and game_number >= binding["effective_from_game"]:
        config["gameplan_seed_snapshot"] = dict(binding)
    personality_binding = _validated_messaging_personality_binding(manifest)
    if (
        personality_binding is not None
        and game_number >= personality_binding["effective_from_game"]
    ):
        config["messaging_personality_snapshot"] = dict(personality_binding)
    return config


def _validate_decision_surface_revision(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in {
        LEGACY_DECISION_SURFACE_REVISION,
        ACTIVE_PLAN_DECISION_SURFACE_REVISION,
        DRAW_PLANNING_DECISION_SURFACE_REVISION,
        OPENING_REGIME_DECISION_SURFACE_REVISION,
        PASSING_ACCELERATION_DECISION_SURFACE_REVISION,
        CURRENT_DECISION_SURFACE_REVISION,
    }:
        raise SystemExit(
            "decision_surface_revision must name a supported integer revision "
            f"({LEGACY_DECISION_SURFACE_REVISION}, "
            f"{ACTIVE_PLAN_DECISION_SURFACE_REVISION}, "
            f"{DRAW_PLANNING_DECISION_SURFACE_REVISION}, "
            f"{OPENING_REGIME_DECISION_SURFACE_REVISION}, "
            f"{PASSING_ACCELERATION_DECISION_SURFACE_REVISION}, or "
            f"{CURRENT_DECISION_SURFACE_REVISION})."
        )
    return value


def _game_config_with_bound_surface(
    root: Path, manifest: Dict[str, Any], game_number: int
) -> Dict[str, Any]:
    """Return config with an existing game's immutable surface binding.

    A game_config written before this field existed is revision 1 forever. This
    prevents a status/answer/replay command from retrofitting active context or
    changed decision topology into a started cohort.
    """

    config = game_config(manifest, game_number)
    path = game_dir(root, game_number) / GAME_CONFIG_FILE
    if not path.exists():
        return config
    persisted = read_json(path)
    config.pop('learning_enabled',None)
    if 'learning_enabled' in persisted:
        from .learning_policy import enabled
        config['learning_enabled']=enabled(persisted)
    revision = _validate_decision_surface_revision(
        persisted.get("decision_surface_revision", LEGACY_DECISION_SURFACE_REVISION)
    )
    config["decision_surface_revision"] = revision
    config['planning_contract']=persisted.get('planning_contract',1)
    config['planner_stages']=persisted.get('planner_stages',False)
    config['plan_tiers']=persisted.get('plan_tiers',False)
    config['context_handling']=persisted.get('context_handling',0)
    config.pop('selection_batch_after',None)
    if 'selection_batch_after' in persisted:config['selection_batch_after']=persisted['selection_batch_after']
    config.pop('proliferate_batch_after',None)
    if 'proliferate_batch_after' in persisted:config['proliferate_batch_after']=persisted['proliferate_batch_after']
    config.pop('combat_blocker_batch',None)
    if 'combat_blocker_batch' in persisted:
        from .block_declaration import version
        config['combat_blocker_batch']=version(persisted['combat_blocker_batch'])
    config.pop('combat_damage_batch',None)
    if 'combat_damage_batch' in persisted:
        from .combat_damage import version as damage_version
        config['combat_damage_batch']=damage_version(persisted['combat_damage_batch'])
    for field in ('agent_architecture','async_diplomacy','decision_roles','static_standing','combat_proposals','turn_batches','short_term_sol_fast'):
        config.pop(field,None)
        if field in persisted:config[field]=persisted[field]
    from .agent_architecture import validate_binding
    validate_binding(config)
    return config


def _game_config_for_run(
    root: Path, manifest: Dict[str, Any], game_number: int
) -> Dict[str, Any]:
    """Adopt editable pilot context only at an untouched-game boundary."""

    # Validate before creating either a cohort snapshot or a game directory.
    try:quarantine.require_clean(DEFAULT_STRATEGY_FILE,root,game_number)
    except ValueError as exc:raise SystemExit(str(exc)) from exc
    game_config(manifest, game_number)
    directory = game_dir(root, game_number)
    if (
        _validated_seed_gameplan_binding(manifest) is None
        and not _game_has_started(directory)
    ):
        _ensure_cohort_seed_gameplan_snapshot(
            root, manifest, effective_from_game=game_number
        )
    if (
        _validated_messaging_personality_binding(manifest) is None
        and not _game_has_started(directory)
    ):
        _ensure_cohort_messaging_personality_snapshot(
            root, manifest, effective_from_game=game_number
        )
    return _game_config_with_bound_surface(root, manifest, game_number)


def _require_not_future_game(
    manifest: Dict[str, Any], game_number: int, action: str
) -> None:
    active = int(manifest["active_game"])
    if game_number > active:
        raise SystemExit(
            f"Cannot {action} game {game_number:02d} while game {active:02d} owns the "
            "campaign lifecycle gate. Follow NEXT_ACTION.json first."
        )


def _relative_path(path: Path, root: Path) -> str:
    try:
        value = path.resolve().relative_to(root.resolve())
    except ValueError:
        value = path.resolve()
    return str(value).replace("\\", "/")


def _powershell_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _prepared_learning_transaction(root: Path) -> Optional[tuple[Path, Dict[str, Any]]]:
    """Return the one unfinished learning journal, failing closed on ambiguity."""

    pending: list[tuple[Path, Dict[str, Any]]] = []
    for path in sorted(root.glob(f"game_*/{POSTGAME_LEARNING_DIR}/{LEARNING_TRANSACTION_FILE}")):
        try:
            transaction = read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Could not read learning transaction {path}: {exc}") from exc
        if transaction.get("state") != "committed":
            pending.append((path, transaction))
    if len(pending) > 1:
        names = ", ".join(_relative_path(path, root) for path, _ in pending)
        raise SystemExit(f"Multiple prepared learning transactions require manual repair: {names}")
    return pending[0] if pending else None


def _learning_recovery_action(root: Path, path: Path, transaction: Dict[str, Any]) -> Dict[str, Any]:
    audit = transaction.get("audit") if isinstance(transaction.get("audit"), dict) else {}
    game_number = int(transaction.get("source_game", audit.get("source_game", 0)))
    patch_path = str(audit.get("patch_path") or (
        f"game_{game_number:02d}/{POSTGAME_REVIEW_DIR}/{LEARNING_PATCH_FILE}"
    ))
    patch_value=Path(patch_path)
    patch_for_command=(
        patch_value.resolve()
        if patch_value.is_absolute()
        else (root/patch_value).resolve()
    )
    command = (
        f".\\gauntlet.cmd --cohort {_powershell_quote(_relative_path(root, PROJECT_ROOT))} "
        f"learn --game {game_number} --patch "
        f"{_powershell_quote(_relative_path(patch_for_command, PROJECT_ROOT))}"
    )
    return {
        "kind": "retry_learning_transaction",
        "game": game_number,
        "transaction": _relative_path(path, root),
        "patch": patch_path,
        "command": command,
    }


def _require_no_prepared_learning_transaction(root: Path, action: str) -> None:
    prepared = _prepared_learning_transaction(root)
    if prepared is None:
        return
    path, transaction = prepared
    recovery = _learning_recovery_action(root, path, transaction)
    raise SystemExit(
        f"Cannot {action} while game {recovery['game']:02d} has a prepared learning "
        f"transaction. Retry the exact learn command first: {recovery['command']}"
    )


def _review_markdown(request: Dict[str, Any]) -> str:
    inputs = request["inputs"]
    outputs = request["required_outputs"]
    lines = [
        f"# Game {request['game']:02d} post-game review",
        "",
        "Gameplay is terminal, but the gauntlet is intentionally blocked here until this review is resolved.",
        "The authoritative lifecycle is `docs/GAUNTLET_WORKFLOW.md`.",
        "",
        "## Review inputs",
        "",
        f"- Frozen strategy: `{inputs['strategy_snapshot']}`",
    ]
    for pilot, path in inputs["evidence"].items():
        lines.append(f"- {pilot} private evidence: `{path}`")
    rules_integrity=request.get('rules_integrity') or {}
    if rules_integrity:
        lines += [
            "",
            "# RULES-AFFECTED GAME — SKEPTICAL REVIEW REQUIRED",
            "",
            rules_integrity.get('learning_instruction',''),
        ]
        for issue in rules_integrity.get('issues',[]):
            lines.append(
                f"- `{issue.get('issue_id')}` [{issue.get('severity')}]: {issue.get('reason')}"
            )
    lines += [
        "",
        "Review each pilot packet independently before combining conclusions. Compare any lesson with the current",
        "card notes, role vocabulary, role assignments, and packages. Do not turn rules facts into strategy memory",
        "and restrict rules-affected learning to conclusions supported independently of the defect.",
        "Raw decision tapes and omniscient game narratives are sealed only for rules/integrity audit. They are not",
        "strategy-review inputs: do not read them during this learning pass or use hidden facts from them in notes.",
        "",
        "## Required response",
        "",
        f"Edit `{outputs['learning_patch']}`. Supply a concise narrative summary and one disposition for every pilot:",
        "`changes`, `no_change`, or `rules_blocker`, each with a rationale. Add only reusable, evidence-supported",
        "strategy operations. If no durable lesson is warranted, leave `operations` empty and explain why in",
        "`no_change_reason`. Every tagged rules issue needs a skeptical per-seat review and consolidated synthesis.",
        "",
        CARDWISE_NOTE_GUIDANCE,
        "",
        "Then apply the reviewed response with:",
        "",
        "```powershell",
        request["apply_command"],
        "```",
        "",
        "The next game cannot start until that command records an applied or explicit no-change review.",
    ]
    return "\n".join(lines) + "\n"


def _ensure_terminal_seal(
    directory: Path,
    config: Dict[str, Any],
    result: Dict[str, Any],
    decision_count: int,
) -> Dict[str, Any]:
    """Write the non-self-referential terminal record bound by every review."""

    decisions_path=directory/"decisions.jsonl"
    snapshot_path=directory/STRATEGY_SNAPSHOT_FILE
    payload={
        "schema":1,
        "game":config["game"],
        "seed":config["seed"],
        "result":result,
        "decision_count":decision_count,
        "decisions_sha256":_sha256_file(decisions_path),
        "decision_surface_revision":config.get(
            "decision_surface_revision",LEGACY_DECISION_SURFACE_REVISION),
        "strategy_revision":config.get("strategy_revision"),
        "strategy_snapshot_sha256":_sha256_file(snapshot_path),
    }
    seed_binding = _validated_seed_gameplan_binding(config)
    if seed_binding is not None:
        seed_path = directory / GAMEPLAN_SEED_SNAPSHOT_FILE
        _read_seed_gameplan_snapshot(
            seed_path,
            expected_fingerprint=seed_binding["fingerprint"],
            expected_effective_from_game=seed_binding["effective_from_game"],
        )
        payload["gameplan_seed_revision"] = dict(seed_binding)
        payload["gameplan_seed_snapshot_sha256"] = _sha256_file(seed_path)
    personality_binding = _validated_messaging_personality_binding(config)
    if personality_binding is not None:
        personality_path = directory / MESSAGING_PERSONALITY_SNAPSHOT_FILE
        _read_messaging_personality_snapshot(
            personality_path,
            expected_fingerprint=personality_binding["fingerprint"],
            expected_effective_from_game=personality_binding["effective_from_game"],
        )
        payload["messaging_personality_revision"] = dict(personality_binding)
        payload["messaging_personality_snapshot_sha256"] = _sha256_file(personality_path)
    adjudications_path=directory/COMBO_ADJUDICATION_JOURNAL
    if adjudications_path.exists():
        adjudications=read_jsonl(adjudications_path)
        payload["combo_adjudication_count"]=len(adjudications)
        payload["combo_adjudications_sha256"]=_sha256_file(adjudications_path)
    payload["terminal_fingerprint"]="terminal-"+hashlib.sha256(
        json.dumps(payload,sort_keys=True,separators=(",",":")).encode("utf-8")
    ).hexdigest()
    path=directory/TERMINAL_SEAL_FILE
    if path.exists():
        existing=read_json(path)
        if existing!=payload:
            raise SystemExit(
                "Terminal result changed after it was sealed. Invalidate the pending review "
                "and replay before producing learning evidence."
            )
    else:write_json(path,payload)
    return payload


def _postgame_binding_paths(directory: Path, evidence_by_viewer: Dict[str, Path]) -> list[Path]:
    paths = [
        directory / "decisions.jsonl",
        directory / COMBO_ADJUDICATION_JOURNAL,
        directory / STRATEGY_SNAPSHOT_FILE,
        directory / GAME_CONFIG_FILE,
        directory / TERMINAL_SEAL_FILE,
        directory / GAMEPLAN_SEED_SNAPSHOT_FILE,
        directory / MESSAGING_PERSONALITY_SNAPSHOT_FILE,
        *evidence_by_viewer.values(),
    ]
    games_dir = directory / "games"
    if games_dir.exists():
        paths.extend(path for path in games_dir.rglob("*") if path.is_file())
    inspection_dir=directory/INSPECTION_EVIDENCE_DIR
    if inspection_dir.exists():
        paths.extend(path for path in inspection_dir.rglob("*") if path.is_file())
    return sorted({path.resolve() for path in paths if path.exists()}, key=str)


def _ensure_postgame_review_bundle(
    root: Path,
    config: Dict[str, Any],
    result: Dict[str, Any],
    evidence_by_viewer: Dict[str, Path],
) -> Dict[str, Any]:
    """Emit the immutable review request and an editable response skeleton once."""

    directory = game_dir(root, config["game"])
    review_dir = directory / POSTGAME_REVIEW_DIR
    review_dir.mkdir(exist_ok=True)
    request_path = review_dir / REVIEW_REQUEST_FILE
    patch_path = review_dir / LEARNING_PATCH_FILE
    instructions_path = review_dir / REVIEW_INSTRUCTIONS_FILE
    bindings = {
        _relative_path(path, directory): _sha256_file(path)
        for path in _postgame_binding_paths(directory, evidence_by_viewer)
    }
    terminal_seal=read_json(directory/TERMINAL_SEAL_FILE)
    terminal_fingerprint=str(terminal_seal["terminal_fingerprint"])
    identity_payload = {
        "game": config["game"],
        "terminal_fingerprint": terminal_fingerprint,
        "bindings": bindings,
    }
    review_id = "review-" + hashlib.sha256(
        json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    current_strategy = load_strategy_state(DEFAULT_STRATEGY_FILE)
    current_revision = current_strategy.freeze().revision_id
    evidence_paths = {
        pilot: _relative_path(path, root)
        for pilot, path in sorted(evidence_by_viewer.items())
    }
    rules_integrity=None
    for path in evidence_by_viewer.values():
        candidate=read_json(path).get('rules_integrity')
        if candidate is None:continue
        if rules_integrity is not None and candidate!=rules_integrity:
            raise SystemExit('Rules-integrity tag differs between private evidence packets.')
        rules_integrity=candidate
    request = {
        "schema": 1,
        "review_id": review_id,
        "state": "pending",
        "created_at": now(),
        "game": config["game"],
        "terminal_fingerprint": terminal_fingerprint,
        "game_strategy_revision": config.get("strategy_revision"),
        "current_global_base_revision": current_revision,
        "bindings": bindings,
        "inputs": {
            "strategy_snapshot": _relative_path(directory / STRATEGY_SNAPSHOT_FILE, root),
            "evidence": evidence_paths,
        },
        "sealed_rules_artifacts": {
            "terminal_record": _relative_path(directory / TERMINAL_SEAL_FILE, root),
            "binding_count": len(bindings),
            "strategy_review_must_not_consume_raw_audit": True,
        },
        "required_outputs": {
            "learning_patch": _relative_path(patch_path, root),
            "game_summary": _relative_path(directory / GAME_SUMMARY_FILE, root),
            "application_audit_directory": _relative_path(directory / POSTGAME_LEARNING_DIR, root),
        },
        "apply_command": (
            f".\\gauntlet.cmd --cohort "
            f"{_powershell_quote(_relative_path(root, PROJECT_ROOT))} "
            f"learn --game {config['game']} --patch "
            f"{_powershell_quote(_relative_path(patch_path, PROJECT_ROOT))}"
        ),
    }
    if rules_integrity is not None:request['rules_integrity']=rules_integrity
    if not request_path.exists():
        if config.get('decision_surface_revision',1)>=SCHEDULER_DECISION_SURFACE_REVISION:
            request['review_contract']=2
        write_json(request_path, request)
    else:
        request = read_json(request_path)
        if (
            request.get("review_id")!=review_id
            or request.get("terminal_fingerprint")!=terminal_fingerprint
        ):
            raise SystemExit(
                "Existing post-game review request does not match the sealed terminal result. "
                "Invalidate and replay this game before review."
            )
    if not patch_path.exists():
        write_json(patch_path, {
            "schema": 1,
            "game": config["game"],
            "base_revision": current_revision,
            "review_id": review_id,
            "terminal_fingerprint": terminal_fingerprint,
            "review": {
                "summary": "",
                "pilot_dispositions": {
                    pilot: {"disposition": "", "rationale": ""}
                    for pilot in engine.DECKDEFS
                },
                "no_change_reason": "",
                "rules_issue_synthesis": [
                    {
                        "issue_id":issue['issue_id'],
                        "impact":"",
                        "analysis":"",
                        "learning_treatment":"",
                    }
                    for issue in (rules_integrity or {}).get('issues',[])
                ],
            },
            "operations": [],
        })
    if request.get('review_contract')==2:
        template=read_json(patch_path)
        changed=False
        if 'pilot_analyses' not in template['review']:
            template['review']['pilot_analyses']={
                pilot:review_contract.review_template(read_json(path)) for pilot,path in evidence_by_viewer.items()}
            changed=True
        if 'rules_issue_synthesis' not in template['review']:
            template['review']['rules_issue_synthesis']=[
                {'issue_id':issue['issue_id'],'impact':'','analysis':'','learning_treatment':''}
                for issue in (request.get('rules_integrity') or {}).get('issues',[])]
            changed=True
        if changed:write_json(patch_path,template)
    if not instructions_path.exists():
        atomic_text(instructions_path, _review_markdown(request)+
                    (review_contract.INSTRUCTIONS if request.get('review_contract')==2 else ''))
    return {
        "state": "pending",
        "review_id": request["review_id"],
        "request": _relative_path(request_path, root),
        "instructions": _relative_path(instructions_path, root),
        "learning_patch": _relative_path(patch_path, root),
    }


def _write_next_action(root: Path, manifest: Dict[str, Any], status: Dict[str, Any]) -> Dict[str, Any]:
    """Publish the one machine-readable action an external workflow must take next."""

    game_number = int(status["game"])
    review = status.get("postgame_review") or {}
    prepared = _prepared_learning_transaction(root)
    quarantine_entries=quarantine.read_registry(DEFAULT_STRATEGY_FILE)['games']
    quarantine_pending=next(
        (entry for entry in quarantine_entries if entry['learning_state']=='pending'),None)
    quarantine_repairs=[]
    if (quarantine_pending is not None and quarantine_pending.get('work_items_path') and
            Path(quarantine_pending['work_items_path']).exists()):
        quarantine_repairs=quarantine.pending_repairs(
            quarantine_pending['cohort'],quarantine_pending['game'])
    rules_integrity=quarantine.rules_integrity_tag(root,game_number)
    pending_repairs=quarantine.pending_repairs(root,game_number)
    if prepared is not None:
        cohort_state = "learning_recovery"
        action = _learning_recovery_action(root, *prepared)
    elif quarantine_pending is not None and quarantine_repairs:
        cohort_state='rules_repair'
        affected_root=Path(quarantine_pending['cohort'])
        action={
            'kind':'repair_rules_work_items','game':quarantine_pending['game'],
            'cohort':str(affected_root),
            'issues':[row['issue_id'] for row in quarantine_repairs],
            'work_items':quarantine_pending['work_items_path'],
            'command':(
                f".\\gauntlet.cmd --cohort {_powershell_quote(_relative_path(affected_root,PROJECT_ROOT))} "
                f"repair-rules --game {quarantine_pending['game']} --summary 'REPAIR AND REGRESSION SUMMARY'"
            ),
        }
    elif quarantine_pending is not None:
        cohort_state='blocked'
        action={'kind':'review_quarantined_learning','game':game_number,
                'registry':str(quarantine.registry_path(DEFAULT_STRATEGY_FILE))}
    elif manifest.get("cohort_state") == "cancelled":
        cohort_state = "cancelled"
        action = {
            "kind": "none",
            "reason": "cohort_cancelled",
            "cancellation": CANCELLATION_FILE,
        }
    elif status.get('state')=='complete' and pending_repairs:
        cohort_state='rules_repair'
        action={
            'kind':'repair_rules_work_items','game':game_number,
            'issues':[row['issue_id'] for row in pending_repairs],
            'work_items':str(quarantine.work_items_path(root,game_number).resolve()),
        }
    elif status.get("state") == "complete" and review.get("state") == "rules_blocker":
        cohort_state = "blocked"
        action = {
            "kind": "fix_release_blocker",
            "game": game_number,
            "error": review.get("blocker_summary")
            or "Post-game review identified a rules blocker; record its repair and regenerate the tagged draw review.",
            "review_response": review.get("response"),
        }
    elif status.get("state") == "complete" and review.get("state") == "pending":
        cohort_state = "awaiting_review"
        action = {
            "kind": "postgame_review",
            "game": game_number,
            "request": review.get("request"),
            "instructions": review.get("instructions"),
            "learning_patch": review.get("learning_patch"),
        }
    elif status.get("state")=="awaiting_combo_adjudication":
        adjudication=status.get("combo_adjudication") or {}
        directory=game_dir(root,game_number)
        response_path=directory/COMBO_ADJUDICATION_RESPONSE
        cohort_state="awaiting_combo_adjudication"
        action={
            "kind":"adjudicate_combo","game":game_number,
            "proposal_id":adjudication.get("proposal_id"),
            "request":_relative_path(directory/COMBO_ADJUDICATION_REQUEST,root),
            "response":_relative_path(response_path,root),
            "command":(
                f".\\gauntlet.cmd --cohort {_powershell_quote(_relative_path(root,PROJECT_ROOT))} "
                f"adjudicate-combo --game {game_number} --response "
                f"{_powershell_quote(_relative_path(response_path,PROJECT_ROOT))}"
            ),
        }
    elif status.get("state") == "need_decision":
        request = status.get("request") or {}
        cohort_state = "playing"
        action = {
            "kind": "answer_decision",
            "game": game_number,
            "decision_id": request.get("decision_id"),
            "actor": request.get("actor"),
            "request": _relative_path(game_dir(root, game_number) / "request.json", root),
        }
        if request.get('pilot_handoff'):
            action.pop('request',None)
            action.update({'kind':'dispatch_pilot','pilot_context_id':request['pilot_context_id'],
                           **request['pilot_handoff']})
    elif status.get("state") == "release_blocker":
        cohort_state = "blocked"
        action = {"kind": "fix_release_blocker", "game": game_number, "error": status.get("error")}
    elif status.get("state") == "horizon_stop":
        cohort_state = "blocked"
        action = {"kind": "resolve_horizon_stop", "game": game_number}
    elif manifest.get("cohort_state") == "complete":
        cohort_state = "complete"
        action = {"kind": "none", "reason": "cohort_complete"}
    else:
        cohort_state = "ready_next"
        action = {"kind": "advance_game", "game": int(manifest["active_game"])}
    if action['kind']=='dispatch_pilot':
        from . import pilot_dispatch
        action['dispatch']=pilot_dispatch.build_route(root,action)
    if rules_integrity is not None:
        action['rules_integrity']=rules_integrity
    payload = {
        "schema": 1,
        "updated_at": now(),
        "cohort_state": cohort_state,
        "active_game": int(manifest["active_game"]),
        "next_action": action,
    }
    from . import planner_runtime
    if planner_runtime.enabled(game_dir(root,game_number)):
        board=planner_runtime.workboard(root,game_number,action=action)
        payload['planning']={'contract':read_json(game_dir(root,game_number)/'game_config.json')['planning_contract'],'policy':str((PROJECT_ROOT/'docs/SPLIT_RUNTIME_POLICY.md').resolve()),
            'coordinator_instruction':'Read the split runtime policy once on entering this contract. '
                'Schedule one persistent seat planner through the metadata CLI at existing coordinator opportunities.',
            'status_command':f'python -m edh_gauntlet.planner_runtime --cohort "{Path(root).resolve()}" --game {game_number} status',
            'next_actor':board['next_actor'],'active_batch':(board['active'] or {}).get('batch_id'),
            'stop_required':board['stop_required']}
    write_json(root / NEXT_ACTION_FILE, payload)
    return payload


def bind_game_seed_gameplan_snapshot(
    root: Path, config: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Copy the cohort seed snapshot into an applicable game exactly once."""

    directory = game_dir(root, config["game"])
    directory.mkdir(parents=True, exist_ok=True)
    local_path = directory / GAMEPLAN_SEED_SNAPSHOT_FILE
    config_path = directory / GAME_CONFIG_FILE
    persisted = read_json(config_path) if config_path.exists() else {}
    expected = _validated_seed_gameplan_binding(config)
    prior = _validated_seed_gameplan_binding(persisted)

    if expected is None:
        if prior is not None or local_path.exists():
            raise SystemExit(
                f"Game {config['game']:02d} has a seed gameplan snapshot not bound by its cohort."
            )
        return None
    if config["game"] < expected["effective_from_game"]:
        raise SystemExit(
            f"Game {config['game']:02d} precedes its seed gameplan activation boundary."
        )
    if prior is not None and prior != expected:
        raise SystemExit(
            f"Game {config['game']:02d} seed gameplan snapshot binding changed after creation."
        )
    if prior is not None and not local_path.exists():
        raise SystemExit(
            f"Game {config['game']:02d} seed gameplan snapshot is missing: {local_path}"
        )

    cohort_path = root / GAMEPLAN_SEED_SNAPSHOT_FILE
    cohort_snapshot = _read_seed_gameplan_snapshot(
        cohort_path,
        expected_fingerprint=expected["fingerprint"],
        expected_effective_from_game=expected["effective_from_game"],
    )
    if local_path.exists():
        _read_seed_gameplan_snapshot(
            local_path,
            expected_fingerprint=expected["fingerprint"],
            expected_effective_from_game=expected["effective_from_game"],
        )
        if local_path.read_bytes() != cohort_path.read_bytes():
            raise SystemExit(
                f"Game {config['game']:02d} seed gameplan snapshot does not match the cohort copy."
            )
    else:
        # The cohort artifact is already validated and immutable. Copy its exact
        # bytes so file-level review bindings agree as well as semantic hashes.
        shutil.copyfile(cohort_path, local_path)

    desired = {
        **persisted,
        "schema": SCHEMA,
        "game": config["game"],
        "seed": config["seed"],
        "max_rounds": config["max_rounds"],
        **({'planning_contract':config['planning_contract']} if config.get('planning_contract',1)>=2 else {}),
        **({'planner_stages':True} if config.get('planner_stages',False) else {}),
        **({'plan_tiers':True} if config.get('plan_tiers',False) else {}),
        **({'context_handling':1} if config.get('context_handling')==1 else {}),
        **{key:config[key] for key in ('agent_architecture','async_diplomacy','decision_roles','static_standing','combat_proposals','turn_batches','short_term_sol_fast','combat_blocker_batch','combat_damage_batch','proliferate_batch_after','selection_batch_after','learning_enabled') if key in config},
        "decision_surface_revision": _validate_decision_surface_revision(
            config.get("decision_surface_revision", LEGACY_DECISION_SURFACE_REVISION)
        ),
        "gameplan_seed_snapshot": dict(expected),
    }
    if desired != persisted:
        write_json(config_path, desired)
    config["gameplan_seed_snapshot"] = dict(expected)
    return cohort_snapshot


def bind_game_messaging_personality_snapshot(
    root: Path, config: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Copy the applicable cohort personality snapshot into one game exactly once."""
    directory = game_dir(root, config["game"])
    directory.mkdir(parents=True, exist_ok=True)
    local_path = directory / MESSAGING_PERSONALITY_SNAPSHOT_FILE
    config_path = directory / GAME_CONFIG_FILE
    persisted = read_json(config_path) if config_path.exists() else {}
    expected = _validated_messaging_personality_binding(config)
    prior = _validated_messaging_personality_binding(persisted)
    if expected is None:
        if prior is not None or local_path.exists():
            raise SystemExit(
                f"Game {config['game']:02d} has a messaging personality snapshot not bound by its cohort.")
        return None
    if config["game"] < expected["effective_from_game"]:
        raise SystemExit(
            f"Game {config['game']:02d} precedes its messaging personality activation boundary.")
    if prior is not None and prior != expected:
        raise SystemExit(
            f"Game {config['game']:02d} messaging personality binding changed after creation.")
    if prior is not None and not local_path.exists():
        raise SystemExit(
            f"Game {config['game']:02d} messaging personality snapshot is missing: {local_path}")
    cohort_path = root / MESSAGING_PERSONALITY_SNAPSHOT_FILE
    cohort_snapshot = _read_messaging_personality_snapshot(
        cohort_path,expected_fingerprint=expected["fingerprint"],
        expected_effective_from_game=expected["effective_from_game"])
    if local_path.exists():
        _read_messaging_personality_snapshot(
            local_path,expected_fingerprint=expected["fingerprint"],
            expected_effective_from_game=expected["effective_from_game"])
        if local_path.read_bytes() != cohort_path.read_bytes():
            raise SystemExit(
                f"Game {config['game']:02d} messaging personality snapshot does not match the cohort copy.")
    else:
        shutil.copyfile(cohort_path, local_path)
    desired = {
        **persisted,"schema":SCHEMA,"game":config["game"],"seed":config["seed"],
        "max_rounds":config["max_rounds"],
        **({'planning_contract':config['planning_contract']} if config.get('planning_contract',1)>=2 else {}),
        **({'planner_stages':True} if config.get('planner_stages',False) else {}),
        **({'plan_tiers':True} if config.get('plan_tiers',False) else {}),
        **({'context_handling':1} if config.get('context_handling')==1 else {}),
        **{key:config[key] for key in ('agent_architecture','async_diplomacy','decision_roles','static_standing','combat_proposals','turn_batches','short_term_sol_fast','combat_blocker_batch','combat_damage_batch','proliferate_batch_after','selection_batch_after','learning_enabled') if key in config},
        "decision_surface_revision":_validate_decision_surface_revision(
            config.get("decision_surface_revision",LEGACY_DECISION_SURFACE_REVISION)),
        "messaging_personality_snapshot":dict(expected),
    }
    if desired != persisted:write_json(config_path,desired)
    config["messaging_personality_snapshot"] = dict(expected)
    return cohort_snapshot


def bind_game_strategy_snapshot(root: Path, config: Dict[str, Any]) -> StrategyState:
    """Load the immutable strategy revision for one game, creating it once.

    Older cohorts have neither artifact.  Their next replay adopts the current
    strategy state exactly once and thereafter follows the same snapshot path as
    a newly initialized game.  A config that already names a missing snapshot is
    treated as corruption rather than silently changing pilot memory.
    """

    directory = game_dir(root, config["game"])
    directory.mkdir(parents=True, exist_ok=True)
    snapshot_path = directory / STRATEGY_SNAPSHOT_FILE
    config_path = directory / GAME_CONFIG_FILE
    persisted = read_json(config_path) if config_path.exists() else {}
    named_snapshot = persisted.get("strategy_snapshot")
    if named_snapshot and str(named_snapshot) != STRATEGY_SNAPSHOT_FILE:
        raise SystemExit(
            f"Game {config['game']:02d} names unsupported strategy snapshot {named_snapshot!r}."
        )
    if named_snapshot and not snapshot_path.exists():
        raise SystemExit(
            f"Game {config['game']:02d} strategy snapshot is missing: {snapshot_path}"
        )

    if snapshot_path.exists():
        strategy = load_strategy_state(snapshot_path)
    else:
        strategy = load_strategy_state()
        # Persist the complete, Oracle-free profile rather than a pointer to the
        # mutable project default.  Replays therefore survive later learning.
        write_json(snapshot_path, strategy.to_dict())

    try:quarantine.require_snapshot_clean(DEFAULT_STRATEGY_FILE,strategy)
    except ValueError as exc:raise SystemExit(str(exc)) from exc
    frozen = strategy.freeze().to_dict()
    prior_frozen = persisted.get("strategy_revision")
    if prior_frozen and prior_frozen.get("fingerprint") != frozen["fingerprint"]:
        raise SystemExit(
            f"Game {config['game']:02d} strategy snapshot fingerprint does not match game_config.json."
        )

    config["strategy_snapshot"] = STRATEGY_SNAPSHOT_FILE
    config["strategy_revision"] = frozen
    desired = {
        **persisted,
        "schema": SCHEMA,
        "game": config["game"],
        "seed": config["seed"],
        "max_rounds": config["max_rounds"],
        "decision_surface_revision": _validate_decision_surface_revision(
            config.get("decision_surface_revision", LEGACY_DECISION_SURFACE_REVISION)
        ),
        "strategy_snapshot": STRATEGY_SNAPSHOT_FILE,
        **({'planning_contract':config['planning_contract']} if config.get('planning_contract',1)>=2 else {}),
        **({'planner_stages':True} if config.get('planner_stages',False) else {}),
        **({'plan_tiers':True} if config.get('plan_tiers',False) else {}),
        **({'context_handling':1} if config.get('context_handling')==1 else {}),
        **{key:config[key] for key in ('agent_architecture','async_diplomacy','decision_roles','static_standing','combat_proposals','turn_batches','short_term_sol_fast','combat_blocker_batch','combat_damage_batch','proliferate_batch_after','selection_batch_after','learning_enabled') if key in config},
        "strategy_revision": frozen,
    }
    if desired != persisted:
        write_json(config_path, desired)
    return strategy


def _run(root: Path, config: Dict[str, Any], tape_path: Path, request_path: Path,
         combo_adjudication_path: Optional[Path] = None,
         retain_suspended_game: bool = False, *, sequence_execution=None):
    seed_gameplans = bind_game_seed_gameplan_snapshot(root, config)
    messaging_personalities = bind_game_messaging_personality_snapshot(root, config)
    strategy = bind_game_strategy_snapshot(root, config)
    from . import static_standing
    static_standing.bind(root,config,seed_gameplans)
    tape = DecisionTape(tape_path, request_path)
    if sequence_execution is not None:
        from .sequence_runtime import SequenceTape
        tape=SequenceTape(tape_path,request_path,sequence_execution)
        sequence_execution['tape']=tape
    adjudication_path=(combo_adjudication_path or
                       (game_dir(root,config["game"])/COMBO_ADJUDICATION_JOURNAL))
    combo_adjudications=_combo_adjudication_responses(adjudication_path)
    from .diplomacy import committed_posts
    from .decision_roles import deliveries
    game: Optional[ManualGame] = None
    construction_complete=False
    try:
        # Setup itself contains mulligan decisions and may suspend ``__init__``.
        # Retain the allocated instance before entering the constructor so
        # read-only helpers (notably inspection) can use that deterministic
        # partial setup state when the first unanswered mulligan raises.
        game = ManualGame.__new__(ManualGame)
        if sequence_execution is not None:tape.runtime=game
        ManualGame.__init__(
            game,
            config["seed"], config["game"], game_dir(root, config["game"]),
            max_turns=config["max_rounds"], decision_tape=tape,
            inspection_service=InspectionService(strategy=strategy),
            combo_adjudications=combo_adjudications,
            planning_contract=config.get('planning_contract',1),
            async_diplomacy=config.get('async_diplomacy')==1,
            decision_roles=config.get('decision_roles')==1,
            combo_deliveries=deliveries(root,config['game']) if config.get('decision_roles')==1 else [],
            combat_blocker_batch=config.get('combat_blocker_batch',0),
            combat_damage_batch=config.get('combat_damage_batch',0),
            proliferate_batch_after=config.get('proliferate_batch_after'),
            selection_batch_after=config.get('selection_batch_after'),
            turn_batches=config.get('turn_batches',0),
            diplomacy_posts=committed_posts(root,config['game']) if config.get('async_diplomacy')==1 else None,
            decision_surface_revision=_validate_decision_surface_revision(
                config.get(
                    "decision_surface_revision", LEGACY_DECISION_SURFACE_REVISION
                )
            ),
            # Campaign replay persists neither per-event full states nor the
            # decision-local state_before payload.  Public checkpoints and
            # terminal evidence are projected separately at the frontier.
            capture_event_state=False,
            capture_decision_state=False,
        )
        construction_complete=True
        result = game.run()
        state = "complete" if result["winner"] or result.get('terminal')=='reaminatour_eliminated' else "horizon_stop"
        return {"state": state, "result": result, "game": game}
    except NeedDecision as exc:
        request=_decorate_request(
            game_dir(root,config["game"]),exc.request,seed_gameplans,
            messaging_personalities,
            decision_surface_revision=config.get(
                "decision_surface_revision", LEGACY_DECISION_SURFACE_REVISION
            ),
        )
        if config.get("decision_roles")==1:request.pop("private_messaging_personality",None)
        return {
            "state": "need_decision", "request": request,
            # Historically setup-time decisions exposed no game to checkpoint
            # writers. Keep that behavior everywhere except an explicitly
            # read-only reconstruction for inspection.
            "game": game if construction_complete or retain_suspended_game else None,
            "pilot_game": game,
        }
    except NeedComboAdjudication as exc:
        return {"state":"awaiting_combo_adjudication","combo_adjudication":exc.request,"game":game}
    except UnrefereedDecisionError as exc:
        return {"state": "release_blocker", "error": str(exc), "game": game}


def _public_state(game: Optional[ManualGame], request: Optional[Dict[str, Any]],
                  adjudication: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if request is None:return (adjudication or {}).get("public_state")
    if game is None:return request.get("public_state")
    return game.redacted_snapshot(request["actor"])


def _pending_pass_on_replay_tape(directory: Path, tape_path: Path) -> Optional[Path]:
    """Materialize controls for an unanswered decision without accepting that answer."""
    status_path=directory/"status.json"
    if not status_path.exists():return None
    status=read_json(status_path);request=status.get("request") or {}
    if status.get("state")!="need_decision" or not request:return None
    controls=_request_pass_on_controls(request)
    if not controls:return None
    rows=read_jsonl(tape_path);did=request.get("decision_id")
    if did in {row.get("decision_id") for row in rows}:return None
    candidate=directory/".pending_pass_on_controls.jsonl"
    write_jsonl(candidate,[*rows,{
        "decision_id":did,"pass_on_controls":controls,"choice_pending":True,
    }])
    return candidate


def _markdown_private_text(text: Any, empty_label: str) -> list[str]:
    value = str(text or "")
    if not value:
        return [f"    ({empty_label})"]
    # An indented Markdown code block keeps pilot-authored headings and fences
    # from changing the structure of STATUS.md.
    return ["    " + line for line in value.split("\n")]


def _gameplan_context_markdown(context: Dict[str, Any]) -> list[str]:
    seed = context.get("seed") or {}
    notes = context.get("dynamic_notes") or []
    source = seed.get("source_file") or "legacy game without a seed snapshot"
    delivery=str(context.get("delivery") or "query")
    automatic=bool(context.get("read_is_automatic"))
    mandatory=delivery=="mandatory_main_phase_review"
    draw_checkpoint=delivery=="draw_planning_checkpoint"
    lines = [
        (
            "## Private gameplan context (first-draw planning checkpoint)"
            if draw_checkpoint else
            "## Private gameplan context (mandatory main-phase seed review)"
            if mandatory else
            "## Private gameplan context (opening delivery)"
            if automatic else
            "## Private gameplan context (private query)"
        ),
        "",
        (
            "This belongs only to the named pilot. The complete frozen seed is supplied "
            "for the required batched short-term update and long-term KEEP/REVISE review."
            if draw_checkpoint else
            "This belongs only to the named pilot. The complete frozen seed is supplied "
            "automatically for the required main-phase long-term-plan review."
            if mandatory else
            "This belongs only to the named pilot and is automatically supplied once at "
            "the start of its mulligan sequence."
            if automatic else
            "This belongs only to the named pilot and is returned only for this explicit "
            "GAMEPLAN query."
        ),
        "The pending gameplay decision remains unchanged.",
        "",
        f"Seed plan: `{source}`  ",
        f"Seed SHA-256: `{seed.get('sha256')}`",
        "",
    ]
    lines.extend(_markdown_private_text(seed.get("text"), "empty seed plan"))
    lines += ["", f"Dynamic notes visible on this branch: `{len(notes)}`"]
    for scope, heading in (
        ("long_term", "Long-term objectives"),
        ("short_term", "Short-term line"),
    ):
        scoped=[entry for entry in notes if normalize_plan_scope(entry.get("scope"))==scope]
        lines += ["", f"### {heading} (`{len(scoped)}`)"]
        for entry in scoped:
            label = entry.get("entry_id") or "dynamic note"
            anchor = "/".join(
                str(value) for value in (
                    entry.get("decision_id"), entry.get("phase")
                ) if value is not None
            )
            lines += ["", f"#### {label}" + (f" — `{anchor}`" if anchor else ""), ""]
            lines.extend(_markdown_private_text(entry.get("text"), "empty note"))
            review=entry.get(DRAW_PLANNING_REVIEW_FIELD) or {}
            if review and scope=="short_term":
                lines += [
                    "",
                    f"Long-term review: `{str(review.get('long_term_action','')).upper()}`",
                    "Review rationale: "+str(review.get("long_term_rationale") or "(none)"),
                ]
    return lines


def _previous_pilot_decision_markdown(
    previous: Dict[str, Any], *, heading: str = "Private pilot continuity"
) -> list[str]:
    chosen=previous.get("chosen")
    if "choice_value" in previous:chosen=previous.get("choice_value")
    rendered=json.dumps(chosen,ensure_ascii=False) if not isinstance(chosen,str) else chosen
    lines=[
        f"## {heading}","",
        "Full accepted decision item for this same pilot on the current replay branch:","",
        f"- Decision: `{previous.get('decision_id')}` / `{previous.get('kind')}`",
        f"- Turn/phase: `{previous.get('turn')}` / `{previous.get('phase')}`",
        f"- Request: {previous.get('prompt') or '(not recorded)'}",
        f"- Chosen: {rendered or 'PASS'}",
        f"- Rationale: {previous.get('rationale') or '(none recorded)'}",
    ]
    options=previous.get("options") or []
    if options:
        lines += ["- Options presented:"]
        lines.extend(f"  {index}. {label}" for index,label in enumerate(options,1))
    return lines


def _active_plan_markdown(context: Dict[str, Any]) -> list[str]:
    sources=context.get("sources") or {}
    lines=[
        "## Private active plan (automatically loaded)","",
        "This bounded decision brief belongs only to the acting pilot. It is regenerated ",
        "from the frozen seed and branch-visible dynamic journal; it is not a third store.","",
    ]
    lines.extend(_markdown_private_text(context.get("text"),"empty active plan"))
    if context.get("update_recommended") and context.get("update_guidance"):
        lines += ["", "Plan checkpoint: " + str(context["update_guidance"])]
    lines += [
        "",
        f"Delivery reason: `{context.get('delivery_reason','material_decision')}`  ",
        f"Projection SHA-256: `{context.get('projection_sha256')}`  ",
        f"Dynamic notes included/visible: `"
        f"{len(sources.get('included_dynamic_entry_ids') or [])}/"
        f"{sources.get('visible_dynamic_entry_count',0)}`",
    ]
    return lines


def _pilot_memory_markdown(notes: list[Dict[str,Any]]) -> list[str]:
    lines=["## Private relevant strategy notes",""]
    current=None
    for note in notes:
        name=str(note.get("card_name") or "Card")
        if name!=current:
            if current is not None:lines.append("")
            lines.append(f"### {name}");lines.append("");current=name
        provenance=str(note.get("source") or "unknown")
        if note.get("source_game") is not None:provenance+=f", game {note['source_game']}"
        if note.get("locked"):provenance+=", locked"
        lines.append(f"- {note.get('text','')} [{provenance}]")
    return lines


def _messaging_personality_markdown(context: Dict[str, Any]) -> list[str]:
    source=context.get("source_file") or "legacy game without a personality snapshot"
    lines=[
        "## Private messaging personality (automatically loaded)","",
        "Use this to shape political voice, risk tolerance, planning style, and any public ",
        "table-talk message or response. It cannot override rules, known information, or ",
        "the deck's strategic doctrine.","",
        f"Source: `{source}`  ",f"SHA-256: `{context.get('sha256')}`","",
    ]
    lines.extend(_markdown_private_text(context.get("text"),"empty messaging personality"))
    return lines


def _decision_context(status: Dict[str, Any]) -> Dict[str, Any]:
    """Derive the actor-visible timing and stack view for one pending decision.

    The referee already records this information in the request and its redacted
    public snapshot. Keep this as a presentation projection rather than copying
    the stack into another persisted request field.
    """
    request=status.get("request") or {}
    public_state=(status.get("public_state") or request.get("public_state") or {})
    raw_stack=public_state.get("stack") or []
    return {
        "round":public_state.get("round",request.get("round")),
        "turn":public_state.get("turn_number",request.get("turn")),
        "active_player":public_state.get("active"),
        "acting_pilot":request.get("actor"),
        "phase":public_state.get("phase",request.get("phase")),
        "window":request.get("prompt"),
        # The engine appends new objects and resolves from the end of the list.
        "stack_top_first":list(reversed(raw_stack)),
    }


def _stack_object_summary(value: Any) -> str:
    """Render one already-redacted public stack object without exposing internals."""
    if not isinstance(value,dict):return str(value)
    card=(value.get("card") or value.get("name") or value.get("label")
          or "Unnamed stack object")
    actor=value.get("actor") or value.get("controller")
    detail=(value.get("trigger_label") or value.get("ability_label")
            or value.get("effect") or value.get("description"))
    summary=str(card)
    if detail and str(detail)!=summary:summary+=f" — {detail}"
    if actor:summary+=f" (controlled by {actor})"
    targets=value.get("target_names") or value.get("targets")
    if targets:
        if not isinstance(targets,(list,tuple)):targets=[targets]
        summary+="; targets: "+", ".join(str(target) for target in targets)
    return summary


def _decision_context_markdown(status: Dict[str, Any]) -> list[str]:
    context=_decision_context(status)
    active=context.get("active_player") or "unknown"
    actor=context.get("acting_pilot") or "unknown"
    active_note=" (active player)" if active==actor else ""
    round_value=context.get("round")
    turn_value=context.get("turn")
    timing=(f"Round **{round_value}**, turn **{turn_value}**"
            if round_value is not None else f"Turn **{turn_value}**")
    lines=[
        "### Decision timing and stack","",
        f"- {timing}",
        f"- Whose turn: **{active}**",
        f"- Pilot making this decision: **{actor}**{active_note}",
        f"- Phase/step: `{context.get('phase') or 'unknown'}`",
        f"- Window/transition: {context.get('window') or 'unspecified'}",
    ]
    order=(status.get('request') or {}).get('turn_order')
    if order:
        lines += ['- Turn order: '+' → '.join(order['seating'])+' → repeat.',
                  '- Living seats: '+', '.join(order['living']),
                  '- Next turn: '+str(order['next_player'])]
    stack=context["stack_top_first"]
    if not stack:
        lines.append("- Stack: **empty**")
        return lines
    lines.append(f"- Stack: **{len(stack)} object(s)**; top object is listed first")
    for index,value in enumerate(stack,1):
        marker="TOP — " if index==1 else ""
        lines.append(f"  {index}. {marker}{_stack_object_summary(value)}")
    return lines


def _status_markdown(status: Dict[str, Any]) -> str:
    if (status.get('decision_surface_revision',1)>=SCHEDULER_DECISION_SURFACE_REVISION
            and status.get('request')):
        return pilot_handoff.brief(status['request'])
    lines = [
        f"# Game {status['game']:02d} checkpoint",
        "",
        f"Status: **{status['state']}**  ",
        f"Seed: `{status['seed']}`  ",
        f"Accepted decisions: `{status['decision_count']}`",
    ]
    rules_integrity=status.get('rules_integrity') or {}
    if rules_integrity:
        lines += ['', '# RULES-AFFECTED GAME — SKEPTICAL REVIEW REQUIRED', '']
        lines += [
            f"- `{row.get('issue_id')}` [{row.get('severity')}]: {row.get('reason')}"
            for row in rules_integrity.get('issues',[])]
    request = status.get("request")
    if request:
        lines += [
            "",
            f"## {request['decision_id']} — {request['actor']} / {request['kind']}",
            "",
        ]
        lines.extend(_decision_context_markdown(status))
        lines += [
            "",
            "### Decision prompt",
            "",
            request["prompt"],
            "",
            "```text",
            request["seat_view"],
            "```",
            "",
        ]
        private_gameplan = request.get("private_gameplan_context") or {}
        if private_gameplan:
            lines.extend(_gameplan_context_markdown(private_gameplan))
            lines.append("")
        previous=request.get("previous_pilot_decision") or {}
        if previous:
            lines.extend(_previous_pilot_decision_markdown(previous))
            lines.append("")
        rationalized=request.get("previous_rationalized_decision") or {}
        if rationalized and rationalized.get("decision_id")!=previous.get("decision_id"):
            lines.extend(_previous_pilot_decision_markdown(
                rationalized,heading="Private prior rationalized decision"))
            lines.append("")
        private_active_plan=request.get("private_active_plan") or {}
        if private_active_plan:
            lines.extend(_active_plan_markdown(private_active_plan))
            lines.append("")
        pilot_memory=request.get("pilot_memory") or []
        if pilot_memory:
            lines.extend(_pilot_memory_markdown(pilot_memory))
            lines.append("")
        private_personality=request.get("private_messaging_personality") or {}
        if private_personality:
            lines.extend(_messaging_personality_markdown(private_personality))
            lines.append("")
        if request.get("planner_combo"):
            from .decision_roles import presentation
            lines += [presentation(request), ""]
        if request.get("response_type"):
            lines += ["Required response:","",request.get("response_help","")]
            if request['response_type'] in {'block_declaration','combat_damage'}:
                lines += [json.dumps(request[request['response_type']],ensure_ascii=False,separators=(',',':')),
                          *[f'{index}. {label}' for index,label in enumerate(request['options'],1)]]
        else:
            lines += ["Options:",""]
            lines.extend(f"{index}. {label}" for index, label in enumerate(request["options"], 1))
            if request["allow_pass"]:
                lines.append("0. PASS")
            if request.get('multi_select'):
                lines.append("Choose option numbers in one comma-separated answer."+
                             (" Order matters: follow the direction in the prompt." if request.get("ordered_selection") else ""))
        rationale_policy=request.get("rationale_policy") or {}
        if rationale_policy:
            lines += [
                "",
                "Gameplay rationale policy:",
                "",
                f"`{rationale_policy.get('mode','optional')}` — "
                f"{rationale_policy.get('help','A rationale is optional.')}",
            ]
        planning=request.get(PLANNING_CHECKPOINT_FIELD) or {}
        if planning.get("required"):
            opening_required=bool(planning.get("opening_long_term_plan_required"))
            lines += [
                "",
                "Required batched planning fields:",
                "",
                (
                    "`--short-term-plan`, `--long-term-action revise`, "
                    "`--long-term-rationale`, and `--long-term-plan`."
                    if opening_required else
                    "`--short-term-plan`, `--long-term-action keep|revise`, and "
                    "`--long-term-rationale`; also supply `--long-term-plan` when revising."
                ),
                "These private fields commit atomically with the gameplay answer.",
                str(planning.get("help") or ""),
            ]
        messageboard=request.get("messageboard") or {}
        if messageboard.get("available") and request.get("kind")=="main_action":
            recipients=", ".join(messageboard.get("valid_recipients") or [])
            lines += [
                "",
                "Batched TABLE TALK syntax:",
                "",
                "Choose the TABLE TALK option and include `--message-address generic|all|pilot` "
                "plus `--message-text`; `pilot` also requires `--message-recipient`.",
                f"Current legal named recipients: {recipients or '(none)' }.",
            ]
            if messageboard.get("opening_salutation_required"):
                lines += [
                    "",
                    "Opening TABLE TALK is required before play or pass. Use `generic` and "
                    "write a characteristic but strategically unrevealing salutation; it "
                    "prompts no response.",
                    str(messageboard.get("salutation_guidance") or ""),
                ]
        if request.get("kind")=="messageboard_response":
            lines += [
                "",
                "To respond, choose the response option and include `--message-text`; PASS "
                "declines. Responses are generically addressed and cannot recurse.",
            ]
        batch=request.get('pass_on_batch') or {}
        if batch.get('schema')==1:
            lines += [
                "",
                "Batched PASS ON syntax:",
                "",
                'Choose the PASS ON OBJECTS option and repeat `--pass-on "UID=SCHEDULE"` '
                "for every object to schedule in this answer.",
            ]
            for source in batch.get('sources',[]):
                lines.append(
                    f"- {source.get('name')} `{source.get('uid')}` in {source.get('zone')}"
                )
        autoresolve=request.get('autoresolve') or {}
        if autoresolve.get('schema')==1:
            lines += [
                "",
                "Spell shortcut:",
                "",
                "An eligible spellcasting choice may include `--autoresolve`; it passes "
                "your priority only if the spell was cast onto an empty stack and wakes "
                "you if another spell is cast.",
            ]
        seat_snooze=request.get('seat_snooze') or {}
        if seat_snooze.get('available'):
            lines += [
                "",
                "Postcombat pass shortcut:",
                "",
                "Use `answer 0 --snooze-all [--until \"SCHEDULE\"]` to pass this main "
                "phase and later optional prompts. An attack or mandatory choice wakes you.",
            ]
        inspection_help=request.get("inspection_help")
        if inspection_help:
            lines += [
                "",
                "Auxiliary inspection:",
                "",
                inspection_help,
            ]
        gameplan_meta=request.get("gameplan") or {}
        if gameplan_meta:
            lines += [
                "",
                "Private auxiliary option:",
                "",
                f"`{gameplan_meta.get('choice',GAMEPLAN_CHOICE)}` — private gameplan "
                f"({gameplan_meta.get('entry_count',0)} entries). "
                f"{gameplan_meta.get('help','Review or update the private gameplan without consuming this decision.')}",
            ]
        pass_on_meta=request.get("pass_on_management") or {}
        if pass_on_meta:
            lines += [
                "",
                "Private auxiliary option:",
                "",
                f"`{pass_on_meta.get('choice',PASS_ON_MANAGEMENT_CHOICE)}` — review or manage "
                f"the active pilot's {pass_on_meta.get('entry_count',0)} passed-on object(s). "
                "Use `pass-ons`, `pass-ons --unsnooze UID`, `pass-ons --unsnooze-all`, or "
                "`pass-ons --reschedule UID --wake \"2 end of combat\"`. The gameplay decision "
                "remains open.",
                "",
            ]
            for entry in pass_on_meta.get("entries",[]):
                lines.append(
                    f"- {entry.get('source_name')} `{entry.get('source_uid')}` in "
                    f"{entry.get('source_zone')}: {entry.get('wake_description')}"
                )
    adjudication=status.get("combo_adjudication") or {}
    if adjudication:
        lines += [
            "",
            f"## Combo adjudication — {adjudication.get('proposal_id')}",
            "",
            f"Proposer: **{adjudication.get('actor')}**  ",
            f"Proposal: {adjudication.get('proposal')}",
            "",
            "Every other live pilot consented that they have no disruption capable of stopping the demonstrated loop.",
            "The rules adjudicator must now approve, reject, or request a better demonstration using the generated response file.",
        ]
    if status.get("error"):
        lines += ["", "## Release blocker", "", status["error"]]
    if status.get("result") and status['result'].get('winner'):
        result = status["result"]
        lines += ["", f"Winner: **{result['winner']}** — {result['reason']}"]
    elif status.get('result'):
        lines += ['',f"Outcome: **{status['result']['reason']}**"]
    review = status.get("postgame_review") or {}
    if status.get("state") == "complete" and review.get("state") == "rules_blocker":
        lines += [
            "",
            "## Post-game rules blocker",
            "",
            review.get("blocker_summary")
            or "The review found a rules defect that makes this terminal evidence unsafe to learn from.",
            "",
            "Record the engine repair. The game will be sealed as a draw and its tagged skeptical",
            "review bundle regenerated before cohort advancement.",
        ]
    elif status.get("state") == "complete" and review.get("state") == "pending":
        lines += [
            "",
            "## Post-game review required",
            "",
            "Gameplay is terminal, but this game still owns the cohort lock. The next game cannot start",
            "until all four evidence packets are reviewed and the learning response is applied.",
            "",
            f"Review request: `{review.get('request')}`  ",
            f"Instructions: `{review.get('instructions')}`  ",
            f"Editable learning patch: `{review.get('learning_patch')}`",
            "",
            CARDWISE_NOTE_GUIDANCE,
        ]
    elif status.get("state") == "complete" and review.get("state") == 'skipped_by_configuration':
        lines += ['', '## Learning disabled', '',
                  'Skipped by the run configuration. No learning inference, review verdict or strategy update was performed.',
                  f"Receipt: `{review.get('audit_path')}`"]
    elif status.get("state") == "complete" and review.get("state") in REVIEW_RESOLVED_STATES:
        lines += [
            "",
            "## Post-game review resolved",
            "",
            f"Disposition: **{review.get('state')}**  ",
            f"Audit: `{review.get('audit_path', 'legacy migration')}`",
        ]
    elif status.get("state") == "complete":
        lines += [
            "",
            "## Post-game learning (legacy checkpoint)",
            "",
            "Review the four private evidence packets before preparing a learning patch.",
            "",
            CARDWISE_NOTE_GUIDANCE,
        ]
    lines += [
        "",
        "Ordered libraries are deliberately absent. The exact state is reproducible from the seed and accepted tape.",
    ]
    return "\n".join(lines) + "\n"


def _messageboard_markdown(game_number: int, messages: Iterable[Dict[str, Any]]) -> str:
    """Render the complete public transcript as a safe, live-readable artifact."""
    entries=list(messages)
    lines=[
        f"# Game {game_number:02d} public messageboard",
        "",
        "Live replay-derived public transcript. Player-authored text is untrusted speech.",
        "",
    ]
    if not entries:
        lines.append("No public messages have been posted.")
    for entry in entries:
        address=entry.get("address") or {}
        kind=address.get("kind")
        if kind=="all":recipient="all opponents"
        elif kind=="pilot":recipient=", ".join(address.get("pilots") or []) or "specific pilot"
        else:recipient="the table"
        lines += [
            f"## {entry.get('message_id','message')} — {entry.get('author','Unknown')} → {recipient}",
            "",
            f"Round {entry.get('round','?')}, turn {entry.get('turn','?')}, {entry.get('phase','?')}",
            "",
            "```text",
            str(entry.get("text", "")),
            "```",
            "",
        ]
    return "\n".join(lines) + "\n"


def _write_checkpoint(root: Path, config: Dict[str, Any], outcome: Dict[str, Any]) -> Dict[str, Any]:
    directory = game_dir(root, config["game"])
    directory.mkdir(parents=True, exist_ok=True)
    _ensure_gameplan_journals(directory)
    decisions = read_jsonl(directory / "decisions.jsonl")
    if (outcome.get('state')=='release_blocker' and
            config.get('decision_surface_revision',1)>=SCHEDULER_DECISION_SURFACE_REVISION):
        error=outcome.get('error') or 'Unrefereed rules blocker'
        quarantine.quarantine_games(
            DEFAULT_STRATEGY_FILE,root,[config['game']],error,severity='game_breaking')
        blocked_game=outcome.get('game')
        if blocked_game is not None:
            reason='Rules blocker draw: '+error
            blocked_game.winner=None
            blocked_game.win_turn=getattr(blocked_game,'turn_number',None)
            blocked_game.win_reason=reason
            blocked_game.pilot_terminal='rules_blocker_draw'
            blocked_game.log('rules_blocker_draw',None,None,reason)
            outcome={**outcome,'state':'complete','result':blocked_game.result(),
                     'rules_blocker_draw':True}
    request = outcome.get("request")
    combo_adjudication=outcome.get("combo_adjudication")
    game = outcome.get("game") or outcome.get('pilot_game')
    if request and request.get('rebase_existing_decision') and config.get('decision_surface_revision',1)>=SCHEDULER_DECISION_SURFACE_REVISION:
        pilot_handoff.invalidate_sessions(root,config['game'],'rebase',cause=pilot_handoff.fingerprint(
            {'decision':request['decision_id'],'options':request['options'],'tape':decisions}))
    if config.get('planning_contract',1)>=2:
        from . import planner_runtime
        planner_runtime.checkpoint(root,config,game,outcome['state'],request)
    rules_integrity=quarantine.rules_integrity_tag(root,config['game'])
    if request is not None and rules_integrity is not None:
        request={**request,'rules_integrity':rules_integrity}
    if request and config.get('decision_surface_revision',1)>=SCHEDULER_DECISION_SURFACE_REVISION:
        full_plan=_private_gameplan_context(directory,request,
            _load_game_seed_gameplan_snapshot(directory),automatic=False)
        packet=pilot_handoff.build_packet(request,outcome.get('pilot_game') or game,full_plan)
        context_id=pilot_handoff.fingerprint(packet)
        path=pilot_handoff.packet_path(directory,request['actor'],context_id)
        current_request=pilot_handoff.packet_request(packet)
        request={**current_request,'pilot_context_id':context_id,
                 'pilot_handoff':{'context':str(path.resolve()),
                                  'brief':str((path.parent/'brief.md').resolve()),
                                  'fresh_context_required':False,
                                  'context_policy':'persistent_isolated_seat',
                                  'seat_session':pilot_handoff.session_descriptor(
                                      root,config['game'],request['actor'],decisions)}}
        # Machine-only context packets are compact. Pretty-printing the repeated
        # frontier snapshots previously accounted for roughly a third of their
        # on-disk size without improving auditability.
        atomic_text(
            path,
            json.dumps(packet,ensure_ascii=False,separators=(',',':'))+'\n',
        )
        atomic_text(path.parent/'brief.md',pilot_handoff.brief(request))
    postgame_review = {"state": "not_ready"}
    if game is not None:
        from . import operator_view
        operator_view.checkpoint(root,config,game,request,len(decisions),outcome['state'])
        game.write_game()
        atomic_text(directory / MESSAGEBOARD_FILE,
                    _messageboard_markdown(config["game"], getattr(game,"public_messageboard",[])))
        if outcome["state"] == "complete":
            _ensure_terminal_seal(
                directory,
                config,
                outcome.get("result") or {},
                len(decisions),
            )
            evidence_dir = directory / POSTGAME_EVIDENCE_DIR
            from .learning_policy import enabled as learning_enabled, skip as skip_learning
            if learning_enabled(config):evidence_dir.mkdir(exist_ok=True)
            evidence_by_viewer: dict[str, Path] = {}
            for pilot in (game.players if learning_enabled(config) else ()):
                evidence_path = evidence_dir / (
                    pilot.lower().replace(" ", "_").replace("&", "and") + ".json"
                )
                if not evidence_path.exists():
                    evidence=_pilot_evidence_with_gameplan(
                        game,pilot,config.get("strategy_revision"),directory)
                    atomic_text(evidence_path,json.dumps(
                        evidence,ensure_ascii=False,separators=(',',':'))+'\n')
                    # Do not retain the previous seat's packet while constructing
                    # the next seat's much larger intermediate review evidence.
                    del evidence
                evidence_by_viewer[pilot] = evidence_path
            applications = _review_applications(directory)
            if applications:
                latest = read_json(applications[-1])
                postgame_review = {
                    "state": latest.get("review_disposition", "applied"),
                    "review_id": latest.get("review_id"),
                    "resolved_at": latest.get("applied_at"),
                    "audit_path": _relative_path(applications[-1], root),
                }
            elif not learning_enabled(config):
                postgame_review=skip_learning(directory)
            else:
                postgame_review = _ensure_postgame_review_bundle(
                    root, config, outcome.get("result") or {}, evidence_by_viewer
                )
    status = {
        "schema": SCHEMA,
        "created_at": now(),
        "game": config["game"],
        "seed": config["seed"],
        "state": outcome["state"],
        "decision_count": len(decisions),
        "request": request,
        "combo_adjudication":combo_adjudication,
        "public_state": _public_state(outcome.get("game"), request,combo_adjudication),
        "result": outcome.get("result"),
        "error": outcome.get("error"),
        "rules_blocker_draw":bool(outcome.get('rules_blocker_draw')),
        "strategy_revision": config.get("strategy_revision"),
        "decision_surface_revision": config.get(
            "decision_surface_revision", LEGACY_DECISION_SURFACE_REVISION
        ),
        "gameplan_seed_snapshot": config.get("gameplan_seed_snapshot"),
        "messaging_personality_snapshot": config.get("messaging_personality_snapshot"),
        "postgame_review": postgame_review,
        "rules_integrity":rules_integrity,
    }
    write_json(directory / "status.json", status)
    atomic_text(directory / "STATUS.md", _status_markdown(status))
    if request:
        write_json(directory / "request.json", request)
    elif (directory / "request.json").exists():
        (directory / "request.json").unlink()
    combo_request_path=directory/COMBO_ADJUDICATION_REQUEST
    combo_response_path=directory/COMBO_ADJUDICATION_RESPONSE
    if combo_adjudication:
        write_json(combo_request_path,combo_adjudication)
        template={
            "schema":1,
            "proposal_id":combo_adjudication["proposal_id"],
            "request_sha256":combo_adjudication["request_sha256"],
            "verdict":"needs_demonstration",
            "rules_basis":"",
            "public_summary":"",
            "operations":[],
        }
        if not combo_response_path.exists():write_json(combo_response_path,template)
        else:
            existing=read_json(combo_response_path)
            if (existing.get("proposal_id")!=combo_adjudication["proposal_id"] or
                    existing.get("request_sha256")!=combo_adjudication["request_sha256"]):
                write_json(combo_response_path,template)
    else:
        combo_request_path.unlink(missing_ok=True)
        combo_response_path.unlink(missing_ok=True)
    checkpoints = directory / "checkpoints"
    checkpoints.mkdir(exist_ok=True)
    existing = sorted(checkpoints.glob("*.json"))
    prior = read_json(existing[-1]) if existing else None
    same = prior and prior["decision_count"] == status["decision_count"] and (
        (prior.get("request") or {}).get("decision_id") == (request or {}).get("decision_id")
    ) and (
        (prior.get("combo_adjudication") or {}).get("proposal_id") ==
        (combo_adjudication or {}).get("proposal_id")
    ) and prior["state"] == status["state"]
    if not same:
        write_json(checkpoints / f"{len(existing):04d}.json", status)
    return status


def _recover_answer_transaction_before_operation(
    root: Path,
    game_number: int,
) -> Optional[Dict[str, Any]]:
    """Recover a game-local answer commit before any consumer reads its branch."""

    directory = game_dir(root, game_number)
    if not directory.exists():
        return None
    recovery = _recover_answer_transaction(directory)
    if recovery and recovery["outcome"] == "applied":
        # Advance rebuilds status/request from the now-consistent authoritative
        # files and removes the applied receipt only after that succeeds.
        return advance(root, game_number)
    return None


def _commit_checkpoint_outcome(
    root: Path,
    manifest: Dict[str, Any],
    config: Dict[str, Any],
    outcome: Dict[str, Any],
    *,
    applied_transaction_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist an already-validated replay frontier without replaying it again."""
    number=int(config["game"]);directory=game_dir(root,number)
    status = _write_checkpoint(root, config, outcome)
    manifest["games"][str(number)] = {
        "state": status["state"],
        "decision_count": status["decision_count"],
        "postgame_review": status.get("postgame_review", {"state": "not_ready"}),
    }
    if status.get("result"):
        manifest["games"][str(number)]["result"] = status["result"]
        review_state = status.get("postgame_review", {}).get("state")
        if (
            status["state"] == "complete"
            and review_state in REVIEW_RESOLVED_STATES
            and number == manifest["active_game"]
            and number < manifest["target_games"]
        ):
            manifest["active_game"] = number + 1
        elif (
            status["state"] == "complete"
            and review_state in REVIEW_RESOLVED_STATES
            and number == manifest["target_games"]
        ):
            manifest["cohort_state"] = "complete"
    if status["state"] == "complete" and status.get("postgame_review", {}).get("state") == "pending":
        manifest["cohort_state"] = "awaiting_review"
    elif manifest.get("cohort_state") != "complete":
        manifest["cohort_state"] = "active"
    manifest["updated_at"] = now()
    write_json(root / "cohort.json", manifest)
    _write_next_action(root, manifest, status)
    if applied_transaction_id is not None:
        _finalize_answer_transaction(directory, applied_transaction_id)
    return status


@serialized
def advance(root: Path, game_number: Optional[int] = None) -> Dict[str, Any]:
    _require_no_prepared_learning_transaction(root, "advance gameplay")
    manifest = load_manifest(root)
    _require_cohort_not_cancelled(manifest,"advance gameplay")
    number = game_number or manifest["active_game"]
    _require_not_future_game(manifest, number, "advance")
    directory = game_dir(root, number)
    # Preserve validation-before-creation for an unstarted game. Merely probing
    # for recovery must not materialize game_XX ahead of snapshot validation.
    config = _game_config_for_run(root, manifest, number)
    recovery = _recover_answer_transaction(directory) if directory.exists() else None
    applied_transaction_id = (
        recovery["transaction"]["transaction_id"]
        if recovery and recovery["outcome"] == "applied"
        else None
    )
    directory.mkdir(parents=True, exist_ok=True)
    status_path = directory / "status.json"
    if status_path.exists():
        existing_status = read_json(status_path)
        manifest_review = (
            manifest.get("games", {}).get(str(number), {}).get("postgame_review") or {}
        )
        status_review = existing_status.get("postgame_review") or manifest_review
        if existing_status.get("state") == "complete" and (
            status_review.get("state") in REVIEW_LOCKED_STATES
            or status_review.get("state") in REVIEW_RESOLVED_STATES
        ):
            existing_status["postgame_review"] = status_review
            write_json(status_path, existing_status)
            atomic_text(directory / "STATUS.md", _status_markdown(existing_status))
            _write_next_action(root, manifest, existing_status)
            if applied_transaction_id is not None:
                _finalize_answer_transaction(directory, applied_transaction_id)
            return existing_status
    tape = directory / "decisions.jsonl"
    tape.touch(exist_ok=True)
    scratch = directory / ".replay_request.json"
    pending_tape=_pending_pass_on_replay_tape(directory,tape)
    try:outcome = _run(root, config, pending_tape or tape, scratch)
    finally:
        scratch.unlink(missing_ok=True)
        if pending_tape is not None:pending_tape.unlink(missing_ok=True)
    return _commit_checkpoint_outcome(
        root,manifest,config,outcome,
        applied_transaction_id=applied_transaction_id)


@serialized
def refresh_messaging_personalities(
    root: Path, game_number: Optional[int] = None
) -> Dict[str, Any]:
    """Refresh table-talk profiles for the active unfinished game on request.

    This is an explicit operator exception to the ordinary snapshot boundary.
    It changes only future private messageboard context and leaves completed
    games' local snapshots intact.
    """

    _require_no_prepared_learning_transaction(root, "refresh messaging personalities")
    manifest = load_manifest(root)
    number = game_number or int(manifest["active_game"])
    _require_not_future_game(manifest, number, "refresh messaging personalities")
    if number != int(manifest["active_game"]):
        raise SystemExit("Messaging personalities may be refreshed only for the active game.")

    directory = game_dir(root, number)
    status = reconcile_status(root, number)
    if status.get("state") == "complete":
        raise SystemExit("Messaging personalities cannot be refreshed after a game is terminal.")

    previous = _validated_messaging_personality_binding(manifest)
    if previous is None:
        raise SystemExit("This cohort has no messaging personality snapshot to refresh.")

    snapshot = _new_messaging_personality_snapshot(number)
    binding = _messaging_personality_binding(snapshot)
    write_json(root / MESSAGING_PERSONALITY_SNAPSHOT_FILE, snapshot)
    manifest["messaging_personality_snapshot"] = binding
    manifest["updated_at"] = now()
    write_json(root / "cohort.json", manifest)

    write_json(directory / MESSAGING_PERSONALITY_SNAPSHOT_FILE, snapshot)
    config_path = directory / GAME_CONFIG_FILE
    config = read_json(config_path)
    config["messaging_personality_snapshot"] = binding
    write_json(config_path, config)

    audit_path = directory / "messaging_personality_refreshes.jsonl"
    refreshes = read_jsonl(audit_path)
    refreshes.append({
        "schema": 1,
        "refreshed_at": now(),
        "game": number,
        "decision_count": status["decision_count"],
        "previous_binding": previous,
        "refreshed_binding": binding,
        "reason": "explicit operator-requested personality refresh",
    })
    write_jsonl(audit_path, refreshes)

    refreshed = reconcile_status(root, number)
    refreshed["messaging_personality_refresh"] = {
        "previous_binding": previous,
        "binding": binding,
        "audit": _relative_path(audit_path, root),
    }
    return refreshed


@serialized
def adjudicate_draw(root: Path, game_number: Optional[int] = None,
                    reason: str = "User adjudicated the game a draw", *,
                    _rules_blocker: bool = False) -> Dict[str, Any]:
    """Seal the current accepted branch as an externally adjudicated draw."""

    _require_no_prepared_learning_transaction(root, "adjudicate a draw")
    manifest = load_manifest(root)
    number = game_number or int(manifest["active_game"])
    _require_not_future_game(manifest, number, "adjudicate")
    if number != int(manifest["active_game"]):
        raise SystemExit("Only the active game may be adjudicated a draw.")
    directory = game_dir(root, number)
    recovered = _recover_answer_transaction_before_operation(root, number)
    if recovered is not None:
        manifest = load_manifest(root)
    existing_path = directory / "status.json"
    if existing_path.exists() and read_json(existing_path).get("state") == "complete":
        raise SystemExit(f"Game {number:02d} is already complete.")
    reason = reason.strip()
    if not reason:
        raise SystemExit("Draw adjudication requires a non-empty reason.")

    if not _game_has_started(directory):
        raise SystemExit(
            f"Game {number:02d} has not started; run advance before adjudicating a draw."
        )
    config = _game_config_with_bound_surface(root, manifest, number)
    tape = directory / "decisions.jsonl"
    tape.touch(exist_ok=True)
    scratch = directory / ".draw_adjudication_request.json"
    try:
        outcome = _run(root, config, tape, scratch)
    finally:
        scratch.unlink(missing_ok=True)
    allowed_states={"need_decision","horizon_stop"}
    if _rules_blocker:allowed_states.update({'complete','release_blocker'})
    if outcome.get("state") not in allowed_states:
        raise SystemExit(
            f"Game {number:02d} cannot be draw-adjudicated from state {outcome.get('state')}."
        )
    game = outcome.get("game") or outcome.get('pilot_game')
    if game is None:
        raise SystemExit("The current game state could not be reconstructed.")
    game.winner = None
    game.win_turn = game.turn_number
    game.win_reason = reason
    game.pilot_terminal = "adjudicated_draw"
    game.log("draw_adjudication", None, None, reason)
    result = game.result()
    return _commit_checkpoint_outcome(
        root,manifest,config,{"state":"complete","result":result,"game":game})


def _adjudicate_rules_blocker_draw(root: Path, game_number: int, error: str) -> Dict[str, Any]:
    """End the accepted prefix as a draw and attach a game-breaking work item."""

    quarantine.quarantine_games(
        DEFAULT_STRATEGY_FILE,root,[game_number],error,severity='game_breaking')
    return adjudicate_draw(
        root,game_number,'Rules blocker draw: '+str(error),_rules_blocker=True)


@serialized
def repair_rules_work_items(root: Path, summary: str,
                            game_number: Optional[int] = None,
                            issue_id: Optional[str] = None) -> Dict[str, Any]:
    """Record an engine repair and return the affected game to its lifecycle."""

    _require_no_prepared_learning_transaction(root,'record a rules repair')
    manifest=load_manifest(root);number=game_number or int(manifest['active_game'])
    _require_not_future_game(manifest,number,'repair rules for')
    try:
        work=quarantine.repair_work_items(
            DEFAULT_STRATEGY_FILE,root,number,summary,issue_id)
    except ValueError as exc:raise SystemExit(str(exc)) from exc
    directory=game_dir(root,number);status_path=directory/'status.json'
    status=read_json(status_path) if status_path.exists() else {
        'game':number,'state':'not_started','postgame_review':{'state':'not_ready'}}
    if status.get('state')=='complete' and (status.get('postgame_review') or {}).get('state')=='rules_blocker':
        blocker_summary=(status.get('postgame_review') or {}).get('blocker_summary') or summary
        _invalidate_unresolved_terminal_review(root,manifest,directory,number)
        for checkpoint in (directory/'checkpoints').glob('*.json'):
            if read_json(checkpoint).get('state')=='complete':checkpoint.unlink()
        manifest['cohort_state']='active';manifest['active_game']=number;manifest['updated_at']=now()
        write_json(root/'cohort.json',manifest)
        status=_adjudicate_rules_blocker_draw(root,number,blocker_summary)
    else:
        manifest['updated_at']=now();write_json(root/'cohort.json',manifest)
        _write_next_action(root,manifest,status)
    result=dict(status)
    result['rules_repair_activity']={
        'game':number,'issue_id':issue_id,'summary':summary,
        'work_items':_relative_path(quarantine.work_items_path(root,number),root),
        'remaining_repairs':[row['issue_id'] for row in quarantine.pending_repairs(root,number)],
    }
    return result


@serialized
def reconcile_status(root: Path, game_number: Optional[int] = None) -> Dict[str, Any]:
    """Reconcile a cached checkpoint with manifest review state without replaying it."""

    manifest=load_manifest(root);number=game_number or int(manifest["active_game"])
    _require_not_future_game(manifest,number,"show status for")
    directory=game_dir(root,number)
    recovered=_recover_answer_transaction_before_operation(root,number)
    if recovered is not None:return recovered
    path=directory/"status.json"
    if not path.exists():
        if not _game_has_started(directory):
            raise SystemExit(f"Game {number:02d} has not started; run advance first.")
        return advance(root,number)
    _ensure_gameplan_journals(directory)
    status=read_json(path)
    manifest_review=(manifest.get("games",{}).get(str(number),{}).get("postgame_review") or {})
    status_review=status.get("postgame_review") or {}
    if (
        manifest_review.get("state")
        and status_review.get("state") in (None,"not_ready")
        and manifest_review.get("state")!="not_ready"
    ):
        status["postgame_review"]=manifest_review
    request=status.get("request")
    if request:
        context_config=_game_config_with_bound_surface(root,manifest,number)
        seed_snapshot=bind_game_seed_gameplan_snapshot(root,context_config)
        personality_snapshot=bind_game_messaging_personality_snapshot(root,context_config)
        status["request"]=_decorate_request(
            directory,request,seed_snapshot,personality_snapshot,
            decision_surface_revision=context_config["decision_surface_revision"])
        status=_refresh_pending_pilot_context(
            root,manifest,number,status,context_config=context_config)
        write_json(directory/"request.json",status["request"])
    write_json(path,status);atomic_text(directory/"STATUS.md",_status_markdown(status))
    _write_next_action(root,manifest,status)
    return status


def _refresh_pending_pilot_context(
    root: Path, manifest: Dict[str, Any], number: int, status: Dict[str, Any],
    *, context_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Rebind a revision-6 packet after an out-of-band request decoration.

    Private GAMEPLAN writes change the active-plan projection without consuming
    the gameplay decision.  The pending request and its content-addressed packet
    must therefore move together; otherwise a correct answer is rejected because
    the packet reconstructs the pre-write plan while request.json holds the new
    one.  Reconciliation uses the literal cached board and accepted-tape count,
    and never replays or chooses gameplay.
    """
    request=status.get('request')
    context_config=context_config or _game_config_with_bound_surface(root,manifest,number)
    if (status.get('state')!='need_decision' or not request or
            context_config.get('decision_surface_revision',1)<SCHEDULER_DECISION_SURFACE_REVISION):
        return status
    directory=game_dir(root,number);decisions=read_jsonl(directory/'decisions.jsonl')
    request={
        key:value for key,value in request.items()
        if key not in {'pilot_context_id','pilot_handoff','private_gameplan_context'}
    }
    rules_integrity=quarantine.rules_integrity_tag(root,number)
    if rules_integrity is not None:request['rules_integrity']=rules_integrity
    full_plan=_private_gameplan_context(
        directory,request,_load_game_seed_gameplan_snapshot(directory),automatic=False)
    packet=pilot_handoff.build_packet(
        request,SimpleNamespace(decisions=decisions),full_plan)
    context_id=pilot_handoff.fingerprint(packet)
    path=pilot_handoff.packet_path(directory,request['actor'],context_id)
    current_request=pilot_handoff.packet_request(packet)
    current_request={
        **current_request,'pilot_context_id':context_id,
        'pilot_handoff':{
            'context':str(path.resolve()),
            'brief':str((path.parent/'brief.md').resolve()),
            'fresh_context_required':False,
            'context_policy':'persistent_isolated_seat',
            'seat_session':pilot_handoff.session_descriptor(
                root,number,request['actor'],decisions),
        },
    }
    atomic_text(path,json.dumps(packet,ensure_ascii=False,separators=(',',':'))+'\n')
    atomic_text(path.parent/'brief.md',pilot_handoff.brief(current_request))
    result=dict(status);result['request']=current_request
    return result


@serialized
def gameplan(root: Path, note: Optional[str] = None,
             game_number: Optional[int] = None,
             scope: str = DEFAULT_PLAN_SCOPE) -> Dict[str, Any]:
    """Review or append the pending pilot's private out-of-band gameplan."""
    _require_no_prepared_learning_transaction(root,"review or update a private gameplan")
    manifest=load_manifest(root);number=game_number or int(manifest["active_game"])
    _require_not_future_game(manifest,number,"use a gameplan for")
    directory=game_dir(root,number)
    if _recover_answer_transaction_before_operation(root,number) is not None:
        manifest=load_manifest(root)
    status_path=directory/"status.json"
    if not status_path.exists():
        raise SystemExit(
            "A private gameplan cannot create a decision; advance gameplay through NEXT_ACTION.json first."
        )
    status=read_json(status_path)
    request=status.get("request")
    if status.get("state")!="need_decision" or not request:
        raise SystemExit(
            "A private gameplan can be reviewed or updated only while its pilot has a pending decision."
        )
    request_path=directory/"request.json"
    if not request_path.exists():
        raise SystemExit("The pending priority request is missing; GAMEPLAN cannot reconstruct it.")
    live_request=read_json(request_path)
    if (
        live_request.get("decision_id")!=request.get("decision_id") or
        live_request.get("actor")!=request.get("actor")
    ):
        raise SystemExit("The status and pending request disagree; reconcile gameplay before using GAMEPLAN.")
    context_config=_game_config_with_bound_surface(root,manifest,number)
    if note is not None and context_config.get('planning_contract',1)>=2:
        raise SystemExit('Written plan updates belong to the background planner; use an optional planner_update on an eligible answer.')
    seed_snapshot=bind_game_seed_gameplan_snapshot(root,context_config)
    personality_snapshot=bind_game_messaging_personality_snapshot(root,context_config)
    request=_decorate_request(
        directory,live_request,seed_snapshot,personality_snapshot,
        decision_surface_revision=context_config["decision_surface_revision"])
    mandatory_review=request.get(MANDATORY_LONG_TERM_UPDATE_FIELD) or {}
    if note is not None and mandatory_review.get("required"):
        try:mandatory_scope=normalize_plan_scope(scope)
        except ValueError as exc:raise SystemExit(str(exc)) from exc
        if mandatory_scope!="long_term":
            raise SystemExit(
                "This main-phase seed review requires a long-term update; use "
                "--scope long-term."
            )
    if note is not None and not (request.get("gameplan") or {}).get("can_append"):
        raise SystemExit(
            "The pending decision permits private GAMEPLAN review but not a dynamic update. "
            "Wait for an eligible main-action, upkeep-action, priority, or specialized response window."
        )
    if note is not None and request.get("rebase_existing_decision"):
        raise SystemExit(
            "Cannot append a gameplan note while rebasing a displaced decision; answer the replacement "
            "first so discarded-branch information cannot enter the new journal."
        )
    actor=str(request["actor"])
    stored_entries=_read_gameplan(directory,actor)
    entries=_visible_gameplan(directory,actor,request)
    status=dict(status);status["request"]=request
    mode="review";entry=None;idempotent_retry=False
    if note is not None:
        try:scope=normalize_plan_scope(scope)
        except ValueError as exc:raise SystemExit(str(exc)) from exc
        try:text=normalize_plan_delta(note)
        except ValueError as exc:raise SystemExit(str(exc).replace("plan delta","gameplan entry")) from exc
        accepted_count=_request_accepted_prefix_count(directory,request)
        request_sha256=_request_fingerprint(request)
        matches=[
            row for row in stored_entries
            if row.get("source")=="gameplan_query"
            and row.get("decision_id")==request.get("decision_id")
            and row.get("accepted_decision_count")==accepted_count
            and row.get("request_sha256")==request_sha256
            and row.get("text")==text
            and normalize_plan_scope(row.get("scope"))==scope
        ]
        if len(matches)>1:
            raise SystemExit("The private gameplan has duplicate writes for this decision and text.")
        if matches:
            entry=matches[0];idempotent_retry=True
        else:
            entry=_new_gameplan_entry(
                directory,actor,request,text,
                accepted_decision_count=accepted_count,
                source="gameplan_query",scope=scope,rows=stored_entries)
            stored_entries=[*stored_entries,entry]
            write_jsonl(_gameplan_path(directory,actor),stored_entries)
        entries=_visible_gameplan(directory,actor,request)
        mode="append"
        request=_decorate_request(
            directory,request,seed_snapshot,personality_snapshot,
            decision_surface_revision=context_config["decision_surface_revision"])
        status["request"]=request
        status=_refresh_pending_pilot_context(
            root,manifest,number,status,context_config=context_config)
        request=status['request']
        write_json(request_path,request)
        write_json(status_path,status)
        atomic_text(directory/"STATUS.md",_status_markdown(status))
        if context_config.get('decision_surface_revision',1)>=SCHEDULER_DECISION_SURFACE_REVISION:
            _write_next_action(root,manifest,status)
    display_request=_decorate_request(
        directory,request,seed_snapshot,personality_snapshot,reveal_gameplan=True,
        decision_surface_revision=context_config["decision_surface_revision"])
    private_context=display_request.get("private_gameplan_context") or {}
    seed=private_context.get("seed") or {}
    telemetry=_record_gameplan_telemetry(
        directory,actor,display_request,
        dynamic_entry_count=len(entries),seed_sha256=seed.get("sha256"),entry=entry)
    result=dict(status);result["request"]=display_request
    result["gameplan_activity"]={
        "mode":mode,"pilot":actor,"entries":entries,
        "idempotent_retry":idempotent_retry,"telemetry":telemetry,
    }
    return result


@serialized
def pass_ons(
    root: Path,
    *,
    unsnooze: Optional[str] = None,
    unsnooze_all: bool = False,
    reschedule: Optional[str] = None,
    wake: Optional[str] = None,
    game_number: Optional[int] = None,
) -> Dict[str, Any]:
    """Review or replayably modify the pending pilot's private PASS ON entries."""
    _require_no_prepared_learning_transaction(root,"manage PASS ON entries")
    selected=sum(bool(value) for value in (unsnooze,unsnooze_all,reschedule))
    if selected>1:raise SystemExit("Choose only one of --unsnooze, --unsnooze-all, or --reschedule.")
    if reschedule and not wake:raise SystemExit("--reschedule requires --wake.")
    if wake and not reschedule:raise SystemExit("--wake is valid only with --reschedule.")
    manifest=load_manifest(root);number=game_number or int(manifest["active_game"])
    _require_not_future_game(manifest,number,"manage PASS ON entries for")
    directory=game_dir(root,number)
    if _recover_answer_transaction_before_operation(root,number) is not None:
        manifest=load_manifest(root)
    status_path=directory/"status.json"
    if not status_path.exists():
        raise SystemExit(
            "PASS ON management cannot create a decision; advance gameplay through NEXT_ACTION.json first.")
    status=read_json(status_path);request=status.get("request")
    if status.get("state")!="need_decision" or not request:
        raise SystemExit("PASS ON entries can be managed only while that pilot has a pending decision.")
    request_path=directory/"request.json"
    if not request_path.exists():
        raise SystemExit("The pending request is missing; PASS ON management cannot reconstruct it.")
    live_request=read_json(request_path)
    if (live_request.get("decision_id")!=request.get("decision_id") or
            live_request.get("actor")!=request.get("actor") or
            _request_fingerprint(live_request)!=_request_fingerprint(request)):
        raise SystemExit("The status and pending request disagree; reconcile gameplay first.")
    config=_game_config_with_bound_surface(root,manifest,number)
    seed_snapshot=bind_game_seed_gameplan_snapshot(root,config)
    personality_snapshot=bind_game_messaging_personality_snapshot(root,config)
    request=_decorate_request(
        directory,live_request,seed_snapshot,personality_snapshot,
        decision_surface_revision=config["decision_surface_revision"])
    controls=_request_pass_on_controls(request)
    management=request.get("pass_on_management") or {}
    entries=list(management.get("entries") or [])
    actor=str(request["actor"])
    if not selected:
        result=dict(status);result["request"]=request
        result["pass_on_activity"]={
            "mode":"review","pilot":actor,"changed_source_uids":[],"entries":entries,
            "decision_id":request["decision_id"],
        }
        return result
    if request.get("rebase_existing_decision"):
        raise SystemExit(
            "Cannot modify PASS ON entries while rebasing a displaced decision; answer the "
            "replacement decision first. Review remains available.")
    by_uid={str(entry.get("source_uid")):entry for entry in entries}
    if not by_uid:raise SystemExit("The pending pilot has no live PASS ON entries to manage.")
    mode="unsnooze";schedule=None
    if unsnooze_all:
        source_uids=sorted(by_uid)
        mode="unsnooze_all"
    else:
        requested_uid=str(reschedule or unsnooze or "").strip()
        if requested_uid not in by_uid:
            raise SystemExit(f"No live actor-owned PASS ON entry has UID {requested_uid!r}.")
        source_uids=[requested_uid]
        if reschedule:
            mode="reschedule"
            try:schedule=parse_pass_on_schedule(wake)
            except ValueError as exc:raise SystemExit(str(exc)) from exc
    existing_ids={control["control_id"] for control in controls};ordinal=len(controls)+1
    control_id=f'{request["decision_id"]}-POM-{ordinal:04d}'
    while control_id in existing_ids:
        ordinal+=1;control_id=f'{request["decision_id"]}-POM-{ordinal:04d}'
    control={
        "schema":1,"control_id":control_id,"actor":actor,
        "decision_id":request["decision_id"],"request_sha256":_request_fingerprint(request),
        "action":"reschedule" if reschedule else "unsnooze","source_uids":source_uids,
    }
    if schedule is not None:control["schedule"]=schedule
    try:control=validate_pass_on_control(control)
    except ValueError as exc:raise SystemExit(f"Invalid PASS ON control: {exc}") from exc
    next_controls=[*controls,control]
    tape_path=directory/"decisions.jsonl";rows=read_jsonl(tape_path)
    if request["decision_id"] in {row.get("decision_id") for row in rows}:
        raise SystemExit("The pending decision is already accepted; reconcile before managing PASS ON entries.")
    candidate=directory/".candidate_pass_on_controls.jsonl"
    candidate_request=directory/".candidate_pass_on_request.json"
    write_jsonl(candidate,[*rows,{
        "decision_id":request["decision_id"],"pass_on_controls":next_controls,
        "choice_pending":True,
    }])
    try:
        outcome=_run(root,config,candidate,candidate_request)
        if outcome["state"]=="release_blocker":
            return _adjudicate_rules_blocker_draw(root,number,outcome['error'])
        refreshed=outcome.get("request") or {}
        if (outcome.get("state")!="need_decision" or
                refreshed.get("decision_id")!=request["decision_id"] or
                _request_pass_on_controls(refreshed)!=next_controls):
            raise SystemExit(
                "PASS ON change not committed because replay did not return to the same pending decision.")
        game=outcome.get("game")
        if control_id not in getattr(game,"consumed_pass_on_controls",set()):
            raise SystemExit(
                "PASS ON change not committed because replay did not consume that exact control.")
    except BaseException:
        candidate.unlink(missing_ok=True);candidate_request.unlink(missing_ok=True)
        raise
    finally:
        candidate.unlink(missing_ok=True);candidate_request.unlink(missing_ok=True)
    committed=_write_checkpoint(root,config,outcome)
    _write_next_action(root,manifest,committed)
    refreshed_management=(committed.get("request") or {}).get("pass_on_management") or {}
    result=dict(committed);result["pass_on_activity"]={
        "mode":mode,"pilot":actor,"changed_source_uids":source_uids,
        "entries":list(refreshed_management.get("entries") or []),
        "decision_id":request["decision_id"],
    }
    return result


def _safe_cohort_artifact(root: Path, relative: str, expected: Optional[Path] = None) -> Path:
    value=Path(str(relative))
    if value.is_absolute():
        raise SystemExit("Cohort artifact path must be relative to the cohort root.")
    candidate=(root/value).resolve()
    try:candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise SystemExit("Cohort artifact path escapes the cohort root.") from exc
    if expected is not None and candidate!=expected.resolve():
        raise SystemExit("Cohort artifact path does not name the expected generated file.")
    return candidate


@serialized
def answer(
    root: Path,
    choice: str | int,
    rationale: str = '',
    game_number: Optional[int] = None,
    plan_delta: Optional[str] = None,
    plan_scope: str = DEFAULT_PLAN_SCOPE,
    short_term_plan: Optional[str] = None,
    long_term_action: Optional[str] = None,
    long_term_rationale: Optional[str] = None,
    long_term_plan: Optional[str] = None,
    message_address: Optional[str] = None,
    message_recipient: Optional[str] = None,
    message_text: Optional[str] = None,
    pass_on_entries: Optional[Iterable[str]] = None,
    autoresolve: bool = False,
    snooze_all: bool = False,
    snooze_until: Optional[str] = None,
    hold_full_control: bool = False,
    snooze_stack: bool = False,
    resolve_my_sequence: bool = False,
    snooze_table: Optional[str] = None,
    snooze_objects: Optional[str] = None,
    pilot_context: Optional[str] = None,
    planner_update: Optional[str] = None,
    planner_alarm: Optional[dict] = None,
    runtime_receipt: Optional[Dict[str,Any]] = None,
) -> Dict[str, Any]:
    submitted_arguments={key:value for key,value in locals().items() if key not in {'root','pilot_context','runtime_receipt'}}
    _require_no_prepared_learning_transaction(root, "answer a gameplay decision")
    manifest = load_manifest(root)
    _require_cohort_not_cancelled(manifest,"answer a gameplay decision")
    number = game_number or manifest["active_game"]
    _require_not_future_game(manifest, number, "answer")
    directory = game_dir(root, number)
    recovery = _recover_answer_transaction(directory)
    if recovery and recovery["outcome"] == "applied":
        # The previous invocation crossed its durable commit point. Finishing
        # checkpoint reconciliation is the idempotent result of this retry.
        return advance(root, number)
    config = _game_config_with_bound_surface(root, manifest, number)
    raw=json.dumps(choice,separators=(',',':')) if isinstance(choice,dict) else str(choice).strip()
    if config.get('planning_contract',1)>=2 and any(value is not None for value in (
            plan_delta,short_term_plan,long_term_action,long_term_rationale,long_term_plan)):
        raise SystemExit('The planner owns written plans in this game. Submit only your gameplay decision.')
    try:quarantine.require_clean(DEFAULT_STRATEGY_FILE,root,number)
    except ValueError as exc:raise SystemExit(str(exc)) from exc
    if raw.casefold() in {"g","gameplan"}:
        if any(value is not None for value in (
            plan_delta,short_term_plan,long_term_action,long_term_rationale,
            long_term_plan,message_address,message_recipient,message_text,
        )) or list(pass_on_entries or []) or autoresolve or snooze_all or snooze_until is not None:
            raise SystemExit(
                "Planning and table-message fields accompany an ordinary gameplay answer; "
                "use the gameplan command for a plan-only query or update."
            )
        return gameplan(
            root,rationale if str(rationale).strip() else None,number,scope=plan_scope)
    if raw.casefold() in PASS_ON_MANAGEMENT_ALIASES:
        if str(rationale).strip():
            raise SystemExit(
                "MANAGE PASS-ONS opens the private review. Use the pass-ons command to "
                "unsnooze or reschedule an entry.")
        return pass_ons(root,game_number=number)
    request_path = directory / "request.json"
    if not request_path.exists():
        status = advance(root, number)
        # A legacy cohort may have adopted its seed snapshot during that first
        # advance, so discard the pre-advance config before candidate replay.
        manifest = load_manifest(root)
        config = _game_config_with_bound_surface(root, manifest, number)
        review_state = status.get("postgame_review", {}).get("state")
        if status.get("state") == "complete" and review_state in REVIEW_LOCKED_STATES:
            detail = (
                "has a post-game rules blocker"
                if review_state == "rules_blocker"
                else "is awaiting post-game review"
            )
            raise SystemExit(
                f"Game {number:02d} {detail}; answer is unavailable. "
                "Follow NEXT_ACTION.json."
            )
        if not request_path.exists():
            raise SystemExit(f"Game {number:02d} has no pending decision to answer.")
    request = read_json(request_path)
    revision=config.get("decision_surface_revision",LEGACY_DECISION_SURFACE_REVISION)
    if config.get('planning_contract',1)>=2:
        from . import handoff_runtime
        handoff_runtime.validate_answer(root,request,runtime_receipt,submitted_arguments)
        if config.get('planning_contract',1)>=3 and planner_update is not None:
            raise SystemExit('Contract 3 uses planner_alarm at priority instead of scheduled plan-update turns.')
        if planner_alarm is not None:
            from . import planning_contract
            try:planner_alarm=planning_contract.alarm(planner_alarm,request['actor'],request)
            except ValueError as exc:raise SystemExit(str(exc)) from exc
        if planner_update is not None:
            if not is_strategic_request(request):
                raise SystemExit('Optional planner updates require an existing strategic answer boundary.')
            if planner_update not in {'short_term','long_term'}:
                raise SystemExit('planner_update must be short_term or long_term.')
    elif planner_update is not None or runtime_receipt is not None or planner_alarm is not None:
        raise SystemExit('Background planning and runtime claims require planning contract 2.')
    planning_requirement=request.get(PLANNING_CHECKPOINT_FIELD) or {}
    planning_due=(
        revision>=DRAW_PLANNING_DECISION_SURFACE_REVISION
        and isinstance(planning_requirement,dict)
        and planning_requirement.get("required") is True
    )
    planning_values=(
        short_term_plan,long_term_action,long_term_rationale,long_term_plan,
    )
    normalized_short_plan=None
    normalized_long_action=None
    normalized_long_rationale=None
    normalized_long_plan=None
    if planning_due:
        if plan_delta is not None:
            raise SystemExit(
                "A first-draw planning checkpoint uses the batched planning fields, not "
                "--plan-delta."
            )
        missing=[]
        if short_term_plan is None:missing.append("--short-term-plan")
        if long_term_action is None:missing.append("--long-term-action")
        if long_term_rationale is None:missing.append("--long-term-rationale")
        if missing:
            raise SystemExit(
                "This first-draw planning checkpoint must be answered atomically; missing "
                +", ".join(missing)+"."
            )
        try:
            normalized_short_plan=normalize_plan_delta(short_term_plan)
            normalized_long_rationale=normalize_plan_delta(long_term_rationale)
        except ValueError as exc:raise SystemExit(str(exc)) from exc
        normalized_long_action=str(long_term_action).strip().casefold()
        if normalized_long_action not in {"keep","revise"}:
            raise SystemExit("--long-term-action must be keep or revise.")
        opening_long_term_required=bool(
            revision>=OPENING_REGIME_DECISION_SURFACE_REVISION
            and planning_requirement.get("opening_long_term_plan_required")
        )
        if opening_long_term_required and normalized_long_action!="revise":
            raise SystemExit(
                "This first-own-turn checkpoint requires --long-term-action revise and a "
                "new match-specific Long-Term Plan."
            )
        if normalized_long_action=="revise":
            if long_term_plan is None:
                raise SystemExit(
                    "--long-term-plan is required when --long-term-action is revise."
                )
            try:normalized_long_plan=normalize_plan_delta(long_term_plan)
            except ValueError as exc:raise SystemExit(str(exc)) from exc
            if opening_long_term_required:
                required_opponents=list(
                    planning_requirement.get("required_opponent_postures") or []
                )
                missing_opponents=[
                    opponent for opponent in required_opponents
                    if opponent.casefold() not in normalized_long_plan.casefold()
                ]
                if missing_opponents:
                    raise SystemExit(
                        "The first-own-turn Long-Term Plan must state a posture toward each "
                        "living opponent; missing: "+", ".join(missing_opponents)+"."
                    )
                required_clauses=list(
                    (planning_requirement.get("opening_information_boundary") or {}).get(
                        "required_clauses"
                    ) or [
                        f"{opponent}: {OPENING_OPPONENT_KNOWLEDGE_QUALIFIER}"
                        for opponent in required_opponents
                    ]
                )
                missing_boundaries=[
                    clause for clause in required_clauses
                    if clause.casefold() not in normalized_long_plan.casefold()
                ]
                if missing_boundaries:
                    raise SystemExit(
                        "The first-own-turn Long-Term Plan must preserve opponent information "
                        "boundaries with these exact clauses: "+
                        "; ".join(missing_boundaries)+"."
                    )
        elif long_term_plan is not None:
            raise SystemExit(
                "--long-term-plan is only valid when --long-term-action is revise."
            )
    elif any(value is not None for value in planning_values):
        raise SystemExit(
            "Batched planning fields are accepted only when this request carries a "
            "first-draw planning checkpoint."
        )
    inline_plan_text=None
    if plan_delta is not None:
        if config.get("decision_surface_revision",LEGACY_DECISION_SURFACE_REVISION)<ACTIVE_PLAN_DECISION_SURFACE_REVISION:
            raise SystemExit(
                "Inline plan deltas are unavailable in this legacy started game. "
                "Use GAMEPLAN at an eligible decision instead."
            )
        if not is_strategic_request(request):
            raise SystemExit("This mechanical decision does not accept an inline plan delta.")
        try:inline_plan_text=normalize_plan_delta(plan_delta)
        except ValueError as exc:raise SystemExit(str(exc)) from exc
        try:plan_scope=normalize_plan_scope(plan_scope)
        except ValueError as exc:raise SystemExit(str(exc)) from exc
    elif normalize_plan_scope(plan_scope)!=DEFAULT_PLAN_SCOPE:
        raise SystemExit("--plan-scope requires --plan-delta or a GAMEPLAN write.")
    mandatory_review=request.get(MANDATORY_LONG_TERM_UPDATE_FIELD) or {}
    if mandatory_review.get("required"):
        if inline_plan_text is None:
            raise SystemExit(
                "This main-phase decision is waiting for its mandatory long-term plan update. "
                "Review the complete private seed and either use gameplan --write with "
                "--scope long-term first, or attach --plan-delta with --plan-scope long-term."
            )
        if plan_scope!="long_term":
            raise SystemExit(
                "This main-phase seed review requires --plan-scope long-term."
            )
    pass_on_controls=_request_pass_on_controls(request)
    if request.get('response_type') in {'block_declaration','combat_damage'}:
        from .structured_choice import validate
        try:value=validate(request,raw)
        except ValueError as exc:raise SystemExit(str(exc)) from exc
        decision_fields={'choice_value':value}
    elif request.get("response_type")=="pass_on_schedule":
        try:value=parse_pass_on_schedule(raw)
        except ValueError as exc:raise SystemExit(str(exc)) from exc
        decision_fields={"choice_value":value}
    elif request.get('multi_select'):
        if raw=='0':indexes=[]
        else:
            try:indexes=[int(value.strip())-1 for value in raw.split(',')]
            except ValueError:raise SystemExit('choice must be comma-separated option numbers, or 0 to choose none')
        if len(indexes)!=len(set(indexes)) or any(not 0<=index<len(request['options']) for index in indexes):
            raise SystemExit(f"each choice must be a distinct number from 1..{len(request['options'])}")
        if not indexes and not request['allow_pass']:
            raise SystemExit('This decision cannot be empty.')
        required=set(request.get('required_indexes',[]))
        from .decision_selection import validate_count
        try:validate_count(request,indexes)
        except ValueError as exc:raise SystemExit(str(exc)) from exc
        if not required.issubset(indexes):
            missing=', '.join(str(index+1) for index in sorted(required-set(indexes)))
            raise SystemExit('Required option(s) omitted: '+missing)
        labels=[request['options'][index] for index in indexes]
        decision_fields={'choice_indexes':indexes,'chosen_labels':labels}
    else:
        try:single=int(raw)
        except ValueError:raise SystemExit('choice must be one option number, or 0 to pass')
        if single == 0:
            if not request["allow_pass"]:
                raise SystemExit("This decision cannot be passed.")
            index = None;label = None
        else:
            index = single - 1
            if not 0 <= index < len(request["options"]):
                raise SystemExit(f"choice must be 1..{len(request['options'])}" + (" or 0" if request["allow_pass"] else ""))
            label = request["options"][index]
        decision_fields={'choice_index':index,'chosen_label':label}

    rationale_policy=request.get("rationale_policy") or {}
    rationale_required=rationale_policy.get("mode")=="required"
    if rationale_policy.get("mode")=="required_for_choices":
        selected=set(decision_fields.get("choice_indexes") or [])
        if decision_fields.get("choice_index") is not None:
            selected.add(decision_fields["choice_index"])
        rationale_required=bool(
            selected & set(rationale_policy.get("choice_indexes") or [])
        )
    if rationale_required and not str(rationale).strip():
        reason=str(rationale_policy.get("reason") or "this decision").replace("_"," ")
        raise SystemExit(f"A gameplay rationale is required for {reason}.")

    auxiliary_payload: Dict[str, Any] = {}
    try:
        scheduler_directive=directive_from_flags(hold_full_control=hold_full_control,
            snooze_stack=snooze_stack,resolve_my_sequence=resolve_my_sequence,
            snooze_table=snooze_table,snooze_objects=snooze_objects)
    except ValueError as exc:raise SystemExit(str(exc)) from exc
    if revision>=SCHEDULER_DECISION_SURFACE_REVISION:
        if scheduler_directive is None:
            raise SystemExit('Exactly one scheduler directive is required with every gameplay answer.')
        if list(pass_on_entries or []) or autoresolve or snooze_all or snooze_until is not None:
            raise SystemExit('Use the appended scheduler directive for this game.')
        if pilot_context!=request.get('pilot_context_id') or not pilot_context:
            raise SystemExit('Answer requires --pilot-context from the current seat-specific handoff.')
        context_path=pilot_handoff.packet_path(directory,request['actor'],pilot_context)
        packet=read_json(context_path)
        clean={k:v for k,v in request.items() if k not in {'pilot_context_id','pilot_handoff'}}
        # A GAMEPLAN query may temporarily reattach the full standing-plan view
        # to request.json. It is presentation-only and intentionally absent from
        # the bounded decision packet.
        clean.pop('private_gameplan_context',None)
        if (pilot_handoff.fingerprint(packet)!=pilot_context or
                pilot_handoff.packet_request(packet)!=clean):
            raise SystemExit('Pilot handoff changed; regenerate the current seat packet before answering.')
        auxiliary_payload['scheduler']=scheduler_directive
        auxiliary_payload['pilot_context_id']=pilot_context
    elif scheduler_directive is not None:
        raise SystemExit('Appended scheduler directives require a revision-6 game; legacy tapes retain their controls.')
    pass_on_values=list(pass_on_entries or [])
    acceleration_requested=bool(
        pass_on_values or autoresolve or snooze_all or snooze_until is not None)
    if (
        acceleration_requested
        and revision<PASSING_ACCELERATION_DECISION_SURFACE_REVISION
    ):
        raise SystemExit(
            'Batched PASS ON, spell autoresolve, and SNOOZE ALL are unavailable '
            'in this older started game.')
    if revision>=PASSING_ACCELERATION_DECISION_SURFACE_REVISION:
        pass_on_meta=request.get('pass_on_batch') or {}
        chose_pass_on=(
            pass_on_meta.get('schema')==1
            and decision_fields.get('choice_index')==pass_on_meta.get('option_index')
        )
        if chose_pass_on:
            if not pass_on_values:
                raise SystemExit(
                    'PASS ON OBJECTS requires at least one --pass-on '
                    '"OBJECT_UID=1 beginning of upkeep" field.')
            try:
                normalized_pass_ons=[
                    parse_pass_on_batch_entry(value) for value in pass_on_values]
            except ValueError as exc:raise SystemExit(str(exc)) from exc
            uids=[entry['source_uid'] for entry in normalized_pass_ons]
            if len(uids)!=len(set(uids)):
                raise SystemExit('Each object UID may appear only once in a batched PASS ON.')
            allowed={str(row.get('uid')) for row in pass_on_meta.get('sources',[])}
            unavailable=[uid for uid in uids if uid not in allowed]
            if unavailable:
                raise SystemExit(
                    'Batched PASS ON names unavailable object UID(s): '+', '.join(unavailable))
            auxiliary_payload['pass_on_batch']={
                'schema':1,'entries':normalized_pass_ons,
            }
        elif pass_on_values:
            raise SystemExit(
                '--pass-on fields require choosing the PASS ON OBJECTS option.')

        autoresolve_meta=request.get('autoresolve') or {}
        selected_indexes=set(decision_fields.get('choice_indexes') or [])
        if decision_fields.get('choice_index') is not None:
            selected_indexes.add(decision_fields['choice_index'])
        autoresolve_eligible=set(autoresolve_meta.get('eligible_choice_indexes') or [])
        if autoresolve:
            if not (selected_indexes & autoresolve_eligible):
                raise SystemExit('--autoresolve requires selecting an eligible spellcasting option.')
            auxiliary_payload['cast_control']={'schema':1,'autoresolve':True}

        seat_meta=request.get('seat_snooze') or {}
        if snooze_until is not None and not snooze_all:
            raise SystemExit('--until is valid only with --snooze-all.')
        if snooze_all:
            if not (
                request.get('kind')=='main_action'
                and request.get('phase')=='postcombat_main'
                and decision_fields.get('choice_index') is None
                and seat_meta.get('available') is True
            ):
                raise SystemExit(
                    '--snooze-all is valid only when passing a postcombat main-phase action.')
            try:
                normalized_until=(
                    parse_pass_on_schedule(snooze_until)
                    if snooze_until is not None else None)
            except ValueError as exc:raise SystemExit(str(exc)) from exc
            auxiliary_payload['seat_snooze']={
                'schema':1,'schedule':normalized_until,
            }

    message_values=(message_address,message_recipient,message_text)
    if revision>=DRAW_PLANNING_DECISION_SURFACE_REVISION:
        message_meta=request.get("messageboard") or {}
        message_option=message_meta.get("option_index")
        chose_message=(
            request.get("kind")=="main_action"
            and decision_fields.get("choice_index")==message_option
            and message_meta.get("available") is True
        )
        chose_response=(
            request.get("kind")=="messageboard_response"
            and decision_fields.get("choice_index") is not None
        )
        opening_salutation_required=bool(
            revision>=OPENING_REGIME_DECISION_SURFACE_REVISION
            and message_meta.get("opening_salutation_required")
        )
        if opening_salutation_required and not chose_message:
            raise SystemExit(
                "This first-own-turn main phase requires TABLE TALK before a material "
                "action or pass: post a characteristic but strategically unrevealing "
                "generic salutation."
            )
        if chose_message:
            if message_address is None or message_text is None:
                raise SystemExit(
                    "TABLE TALK requires --message-address and --message-text in this "
                    "same answer."
                )
            address_kind=str(message_address).strip().casefold().replace("-","_")
            if address_kind not in {"generic","all","pilot"}:
                raise SystemExit("--message-address must be generic, all, or pilot.")
            if opening_salutation_required and address_kind!="generic":
                raise SystemExit(
                    "The required first-own-turn salutation must use --message-address "
                    "generic so it prompts no responses."
                )
            recipients=list(message_meta.get("valid_recipients") or [])
            if address_kind=="pilot":
                if message_recipient not in recipients:
                    raise SystemExit(
                        "--message-recipient must name one living opponent: "
                        +", ".join(recipients)
                    )
                pilots=[str(message_recipient)]
            else:
                if message_recipient is not None:
                    raise SystemExit(
                        "--message-recipient is valid only with --message-address pilot."
                    )
                pilots=recipients if address_kind=="all" else []
            try:normalized_message=normalize_messageboard_text(message_text)
            except ValueError as exc:raise SystemExit(str(exc)) from exc
            auxiliary_payload["messageboard"]={
                "schema":2,"text":normalized_message,
                "address":{"kind":address_kind,"pilots":pilots},
            }
        elif chose_response:
            if message_text is None:
                raise SystemExit(
                    "A public table-talk response requires --message-text."
                )
            if message_address is not None or message_recipient is not None:
                raise SystemExit(
                    "Messageboard responses are always generically addressed; do not "
                    "supply an address or recipient."
                )
            try:normalized_message=normalize_messageboard_text(message_text)
            except ValueError as exc:raise SystemExit(str(exc)) from exc
            auxiliary_payload["messageboard"]={
                "schema":2,"text":normalized_message,
                "address":{"kind":"generic","pilots":[]},
            }
        elif any(value is not None for value in message_values):
            raise SystemExit(
                "Table-message fields require choosing TABLE TALK or accepting a prompted "
                "messageboard response."
            )
    elif any(value is not None for value in message_values):
        raise SystemExit(
            "Batched table-message fields are unavailable in this older started game."
        )

    if (
        revision<DRAW_PLANNING_DECISION_SURFACE_REVISION
        and request.get("kind") in {"messageboard_compose","messageboard_response"}
        and decision_fields.get("choice_index") is not None
    ):
        try:rationale=normalize_messageboard_text(rationale)
        except ValueError as exc:raise SystemExit(str(exc)) from exc

    tape_path = directory / "decisions.jsonl"
    rows = read_jsonl(tape_path)
    accepted_prefix=rows;rebase_cut=None;rebase_discarded=None
    if request.get('rebase_existing_decision'):
        try:
            insert_at=next(index for index,row in enumerate(rows) if row['decision_id']==request['decision_id'])
        except StopIteration:
            raise SystemExit('Cannot rebase: the displaced decision is absent from the accepted tape.')
        # A semantic-label mismatch means this request replaces the accepted
        # choice at the same decision ID.  Every later row was authored using
        # knowledge from the displaced branch and must be discarded, not shifted.
        accepted_prefix=rows[:insert_at];rebase_cut=len(accepted_prefix)
        rebase_discarded=rows[insert_at:]
    inline_gameplan_rows=None;inline_gameplan_entry=None
    planning_gameplan_rows=None;planning_gameplan_entries=[]
    if inline_plan_text is not None:
        inline_gameplan_rows,inline_gameplan_entry=(
            _prepare_inline_gameplan_entry(
                directory,request,inline_plan_text,
                accepted_decision_count=len(accepted_prefix)+1,
                rebase_cut=rebase_cut,
                scope=plan_scope,
            )
        )
    if planning_due:
        planning_gameplan_rows,planning_gameplan_entries=(
            _prepare_draw_planning_entries(
                directory,request,
                short_term_plan=str(normalized_short_plan),
                long_term_action=str(normalized_long_action),
                long_term_rationale=str(normalized_long_rationale),
                long_term_plan=normalized_long_plan,
                accepted_decision_count=len(accepted_prefix)+1,
                rebase_cut=rebase_cut,
            )
        )
    record = {
        "decision_id": request["decision_id"],
        **decision_fields,
        "rationale": rationale,
        "accepted_at": now(),
        "chunk": (accepted_prefix[-1].get("chunk", 0) + 1) if accepted_prefix else 1,
    }
    if runtime_receipt is not None:auxiliary_payload['runtime']=runtime_receipt
    if planner_update is not None:auxiliary_payload['planner_update']=planner_update
    if planner_alarm is not None:auxiliary_payload['planner_alarm']=planner_alarm
    if auxiliary_payload:record["auxiliary_payload"]=auxiliary_payload
    if revision>=SCHEDULER_DECISION_SURFACE_REVISION:record['actor']=request['actor']
    if pass_on_controls:record["pass_on_controls"]=pass_on_controls
    if inline_gameplan_entry is not None:
        delta_text=str(inline_gameplan_entry["text"])
        record["private_plan_update"]={
            "schema":1,
            "pilot":request["actor"],
            "entry_id":inline_gameplan_entry["entry_id"],
            "decision_id":request["decision_id"],
            "scope":inline_gameplan_entry["scope"],
            "character_count":len(delta_text),
            "sha256":hashlib.sha256(delta_text.encode("utf-8")).hexdigest(),
        }
        review_completion=inline_gameplan_entry.get(MAIN_PHASE_REVIEW_FIELD)
        if review_completion:
            record["private_plan_update"][MAIN_PHASE_REVIEW_FIELD]=review_completion
    if planning_gameplan_entries:
        review=planning_gameplan_entries[0][DRAW_PLANNING_REVIEW_FIELD]
        record["private_planning_update"]={
            "schema":1,"pilot":request["actor"],
            "decision_id":request["decision_id"],
            "cadence_id":review["cadence_id"],
            "short_term_entry_id":planning_gameplan_entries[0]["entry_id"],
            "long_term_action":review["long_term_action"],
            "long_term_entry_id":(
                planning_gameplan_entries[1]["entry_id"]
                if len(planning_gameplan_entries)>1 else None
            ),
            "long_term_rationale_sha256":hashlib.sha256(
                str(review["long_term_rationale"]).encode("utf-8")
            ).hexdigest(),
        }
    candidate_rows=[*accepted_prefix,record]
    candidate = directory / ".candidate_decisions.jsonl"
    candidate_request = directory / ".candidate_request.json"
    candidate_adjudications = directory / ".candidate_rebase_combo_adjudications.jsonl"
    write_jsonl(candidate,candidate_rows)
    replay_adjudications=None
    kept_adjudications: Optional[list[Dict[str, Any]]] = None
    discarded_adjudication_rows: list[Dict[str, Any]] = []
    if rebase_cut is not None:
        kept_adjudications,discarded_adjudication_rows=_partition_combo_adjudications(
            directory,{row["decision_id"] for row in accepted_prefix},rebase_cut)
        write_jsonl(candidate_adjudications,kept_adjudications)
        replay_adjudications=candidate_adjudications
    try:
        outcome = _run(root, config, candidate, candidate_request,replay_adjudications)
        if outcome["state"] == "release_blocker":
            if revision>=SCHEDULER_DECISION_SURFACE_REVISION:
                error=outcome['error']
                audit_path=directory/'rejections.jsonl';audit=read_jsonl(audit_path)
                audit.append({'rejected_at':now(),'actor':request['actor'],
                    'decision_id':request['decision_id'],'pilot_context_id':pilot_context,
                    'proposed_answer':record,'error':error,'kind':'rules_blocker_draw'})
                write_jsonl(audit_path,audit)
                candidate.unlink(missing_ok=True)
                candidate_request.unlink(missing_ok=True)
                candidate_adjudications.unlink(missing_ok=True)
                return _adjudicate_rules_blocker_draw(root,number,error)
            raise SystemExit("Decision not committed; replay reached release blocker: " + outcome["error"])
    except BaseException as exc:
        if revision>=SCHEDULER_DECISION_SURFACE_REVISION and isinstance(exc,(ValueError,SystemExit)):
            audit_path=directory/'rejections.jsonl'
            audit=read_jsonl(audit_path)
            audit.append({'rejected_at':now(),'actor':request['actor'],
                'decision_id':request['decision_id'],'pilot_context_id':pilot_context,
                'proposed_answer':record,'error':str(exc),'kind':'candidate_rejected'})
            write_jsonl(audit_path,audit)
        candidate.unlink(missing_ok=True)
        candidate_request.unlink(missing_ok=True)
        candidate_adjudications.unlink(missing_ok=True)
        raise
    transactional = (
        rebase_cut is not None
        or inline_gameplan_rows is not None
        or planning_gameplan_rows is not None
    )
    applied_transaction_id=None
    if transactional:
        after_images: Dict[Path, Optional[str]] = {
            tape_path: _jsonl_text(candidate_rows),
        }
        discarded_gameplans = {"count": 0, "sha256": None}
        if rebase_cut is not None:
            discarded_gameplan_rows=[]
            actor=str(request["actor"])
            for pilot in PILOT_GAMEPLAN_FILES:
                original=_read_gameplan(directory,pilot)
                desired=[]
                for row in original:
                    try:anchor=int(row.get("accepted_decision_count",10**18))
                    except (TypeError,ValueError):anchor=10**18
                    if anchor<=rebase_cut:desired.append(row)
                    else:discarded_gameplan_rows.append({"pilot":pilot,"entry":row})
                if pilot==actor and planning_gameplan_rows is not None:
                    desired=planning_gameplan_rows
                elif pilot==actor and inline_gameplan_rows is not None:
                    desired=inline_gameplan_rows
                if desired!=original:
                    after_images[_gameplan_path(directory,pilot)]=_jsonl_text(desired)
            discarded_gameplans=_gameplan_discard_summary(discarded_gameplan_rows)
        elif planning_gameplan_rows is not None:
            after_images[_gameplan_path(
                directory,str(request["actor"])
            )]=_jsonl_text(planning_gameplan_rows)
        elif inline_gameplan_rows is not None:
            after_images[_gameplan_path(
                directory,str(request["actor"])
            )]=_jsonl_text(inline_gameplan_rows)

        if discarded_adjudication_rows:
            after_images[directory/COMBO_ADJUDICATION_JOURNAL]=_jsonl_text(
                kept_adjudications or []
            )
        discarded_adjudications = (
            {
                "count":len(discarded_adjudication_rows),
                "sha256":hashlib.sha256(
                    json.dumps(
                        discarded_adjudication_rows,sort_keys=True,
                        separators=(",",":"),ensure_ascii=False,
                    ).encode("utf-8")
                ).hexdigest(),
            }
            if discarded_adjudication_rows else
            {"count":0,"sha256":None}
        )
        discarded_checkpoint_count=0
        if rebase_cut is not None:
            for checkpoint in (directory/"checkpoints").glob("*.json"):
                if read_json(checkpoint).get("decision_count",0)>rebase_cut:
                    after_images[checkpoint]=None
                    discarded_checkpoint_count+=1
            discarded_digest=hashlib.sha256(
                json.dumps(rebase_discarded,sort_keys=True).encode("utf-8")
            ).hexdigest()
            audit_path=directory/"rejections.jsonl";audit=read_jsonl(audit_path)
            audit.append({
                "rejected_at":now(),"kind":"successful_rebase",
                "from_decision":request["decision_id"],
                "discarded_count":len(rebase_discarded),
                "discarded_sha256":discarded_digest,
                "discarded_gameplan_entry_count":discarded_gameplans["count"],
                "discarded_gameplan_sha256":discarded_gameplans["sha256"],
                "discarded_combo_adjudication_count":discarded_adjudications["count"],
                "discarded_combo_adjudication_sha256":discarded_adjudications["sha256"],
                "discarded_checkpoint_count":discarded_checkpoint_count,
                "reason":"A changed legal-option surface displaced this decision and its future branch.",
            })
            after_images[audit_path]=_jsonl_text(audit)
        transaction=_prepare_answer_transaction(
            directory,
            decision_id=str(request["decision_id"]),
            request_sha256=_request_fingerprint(request),
            rebase_cut=rebase_cut,
            after_images=after_images,
        )
        try:
            _commit_answer_transaction(directory,transaction)
            applied_transaction_id=transaction["transaction_id"]
        finally:
            candidate.unlink(missing_ok=True)
            candidate_request.unlink(missing_ok=True)
            candidate_adjudications.unlink(missing_ok=True)
    else:
        try:
            candidate.replace(tape_path)
        finally:
            candidate_request.unlink(missing_ok=True)
            candidate_adjudications.unlink(missing_ok=True)
    if transactional and outcome.get("request"):
        # Candidate replay necessarily projected the frontier before the
        # transaction made inline notes or rebase pruning visible. Refresh only
        # actor-private presentation from the now-committed sources; rules state
        # and the validated frontier are already final and need no second replay.
        outcome=dict(outcome)
        outcome["request"]=_decorate_request(
            directory,outcome["request"],
            _load_game_seed_gameplan_snapshot(directory),
            _load_game_messaging_personality_snapshot(directory),
            decision_surface_revision=config.get(
                "decision_surface_revision",LEGACY_DECISION_SURFACE_REVISION),
        )
    # Candidate replay has already produced the exact frontier for the tape that
    # was just committed.  Persist it directly; replaying the same growing tape
    # a second time made every ordinary answer roughly twice as expensive.
    return _commit_checkpoint_outcome(
        root,manifest,config,outcome,
        applied_transaction_id=applied_transaction_id)


@serialized
def adjudicate_combo(root: Path, response_path: Path,
                      game_number: Optional[int] = None) -> Dict[str, Any]:
    """Validate and atomically bind one rules-agent response to a consented loop."""
    _require_no_prepared_learning_transaction(root,"adjudicate a combo loop")
    manifest=load_manifest(root);number=game_number or int(manifest["active_game"])
    _require_not_future_game(manifest,number,"adjudicate a combo for")
    directory=game_dir(root,number)
    if _recover_answer_transaction_before_operation(root,number) is not None:
        manifest=load_manifest(root)
    config=_game_config_with_bound_surface(root,manifest,number)
    status_path=directory/"status.json"
    if not status_path.exists():raise SystemExit(f"Game {number:02d} has no combo proposal to adjudicate.")
    status=read_json(status_path);request=status.get("combo_adjudication") or {}
    if status.get("state")!="awaiting_combo_adjudication" or not request:
        raise SystemExit(f"Game {number:02d} is not awaiting combo adjudication.")
    response_path=Path(response_path).resolve()
    if not response_path.exists():raise SystemExit(f"Combo adjudication response does not exist: {response_path}")
    try:raw=read_json(response_path)
    except (OSError,json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read combo adjudication response {response_path}: {exc}") from exc
    try:
        response=validate_combo_adjudication_response(
            raw,expected_proposal_id=request["proposal_id"],
            expected_request_sha256=request["request_sha256"],
            known_pilots=tuple(PILOT_GAMEPLAN_FILES))
    except ComboAdjudicationValidationError as exc:
        raise SystemExit(f"Invalid combo adjudication response: {exc}") from exc
    journal=directory/COMBO_ADJUDICATION_JOURNAL;rows=read_jsonl(journal)
    existing=next((row for row in rows if (row.get("response") or {}).get("proposal_id")==response["proposal_id"]),None)
    if existing:
        if existing.get("response")!=response:
            raise SystemExit("This combo proposal already has a different immutable adjudication.")
        return advance(root,number)
    decisions=read_jsonl(directory/"decisions.jsonl")
    proposal_decision_id=str(request.get("proposal_decision_id",""))
    if proposal_decision_id not in {row.get("decision_id") for row in decisions}:
        raise SystemExit("The combo proposal decision is not present in the accepted decision tape.")
    envelope={
        "schema":1,"accepted_at":now(),"proposal_decision_id":proposal_decision_id,
        "accepted_decision_count":len(decisions),"response":response,
    }
    candidate=directory/".candidate_combo_adjudications.jsonl"
    candidate_request=directory/".candidate_combo_request.json"
    write_jsonl(candidate,[*rows,envelope])
    try:
        outcome=_run(root,config,directory/"decisions.jsonl",candidate_request,candidate)
        if outcome["state"]=="release_blocker":
            candidate.unlink(missing_ok=True)
            return _adjudicate_rules_blocker_draw(root,number,outcome['error'])
        candidate_game=outcome.get("game")
        consumed=getattr(candidate_game,"consumed_combo_adjudications",set())
        if request["proposal_id"] not in consumed:
            raise SystemExit(
                "Combo adjudication not committed because candidate replay did not consume "
                "that exact proposal.")
        candidate.replace(journal)
    except BaseException:
        candidate.unlink(missing_ok=True)
        raise
    finally:
        candidate_request.unlink(missing_ok=True)
    return advance(root,number)


def _invalidate_unresolved_terminal_review(
    root: Path,
    manifest: Dict[str, Any],
    directory: Path,
    game_number: int,
) -> None:
    for artifact in (directory/POSTGAME_EVIDENCE_DIR,directory/POSTGAME_REVIEW_DIR):
        if artifact.exists():shutil.rmtree(artifact)
    for artifact in (
        directory/GAME_SUMMARY_FILE,
        directory/TERMINAL_SEAL_FILE,
        directory/"status.json",
        directory/"STATUS.md",
        directory/"request.json",
    ):
        artifact.unlink(missing_ok=True)
    manifest.setdefault("games",{}).setdefault(str(game_number),{})["postgame_review"]={
        "state":"not_ready"
    }
    manifest["cohort_state"]="active";manifest["active_game"]=game_number
    manifest["updated_at"]=now();write_json(root/"cohort.json",manifest)


def _retained_public_history(root, game, rows):
    """Keep committed public inputs, independently of discarded model contexts."""
    directory=game_dir(root,game)/'continuity';retained={}
    for name,actor_key in [('diplomacy_posts.json','author'),('combo_deliveries.json','actor')]:
        values=read_json(directory/name) if (directory/name).exists() else []
        retained[name]=[row for row in values if pilot_handoff.can_resume_session(
            row['source_session'],root,game,row[actor_key],rows)]
    return retained


def _rebind_public_history(root, game, rows, retained):
    """Called only after epoch invalidation, with history validated before it."""
    directory=game_dir(root,game)/'continuity'
    for name,actor_key in [('diplomacy_posts.json','author'),('combo_deliveries.json','actor')]:
        values=[]
        for row in retained[name]:
            count=row['source_session']['accepted_prefix_count']
            if count>len(rows) or row['source_session']['accepted_prefix_sha256']!=pilot_handoff.fingerprint(rows[:count]):
                raise SystemExit('Public rewind history no longer matches the retained tape.')
            values.append({**row,'source_session':pilot_handoff.session_descriptor(root,game,row[actor_key],rows[:count])})
        write_json(directory/name,values)


@serialized
def rewind(root: Path, decision_id: str, reason: str, game_number: Optional[int] = None) -> Dict[str, Any]:
    _require_no_prepared_learning_transaction(root, "rewind gameplay")
    manifest = load_manifest(root)
    number = game_number or manifest["active_game"]
    _require_not_future_game(manifest, number, "rewind")
    directory = game_dir(root, number)
    if _recover_answer_transaction_before_operation(root,number) is not None:
        manifest=load_manifest(root)
    status_path = directory / "status.json"
    status = read_json(status_path) if status_path.exists() else {}
    review = status.get("postgame_review") or (
        manifest.get("games", {}).get(str(number), {}).get("postgame_review") or {}
    )
    transaction_path=directory/POSTGAME_LEARNING_DIR/LEARNING_TRANSACTION_FILE
    if transaction_path.exists() and read_json(transaction_path).get("state")!="committed":
        raise SystemExit(
            f"Game {number:02d} has a prepared learning transaction. Retry the exact "
            "learn command to reconcile it before any other operation."
        )
    if review.get("state") in REVIEW_RESOLVED_STATES or _review_applications(directory):
        raise SystemExit(
            f"Game {number:02d} has a resolved post-game review and is sealed; "
            "fork a new cohort instead of rewinding learned evidence."
        )
    tape_path = directory / "decisions.jsonl"
    rows = read_jsonl(tape_path)
    try:
        cut = next(index for index, row in enumerate(rows) if row["decision_id"] == decision_id)
    except StopIteration:
        raise SystemExit(f"Decision {decision_id} is not in the accepted tape.")
    if review.get("state") in REVIEW_LOCKED_STATES:
        _invalidate_unresolved_terminal_review(root,manifest,directory,number)
    discarded = rows[cut:]
    digest = hashlib.sha256(json.dumps(discarded, sort_keys=True).encode("utf-8")).hexdigest()
    retained_public=_retained_public_history(root,number,rows[:cut])
    write_jsonl(tape_path, rows[:cut])
    pilot_handoff.invalidate_sessions(root,number,'rewind')
    _rebind_public_history(root,number,rows[:cut],retained_public)
    # Epoch fencing makes all prior contexts incompatible.  Remove their
    # routing identities as well so a new software host can safely create
    # isolated contexts on the retained accepted prefix.
    from . import pilot_dispatch, planner_runtime
    pilot_dispatch.invalidate_registry(root,number)
    planner_runtime.invalidate_contexts(root,number)
    (root/'host_runtime'/'sessions.json').unlink(missing_ok=True)
    discarded_gameplans=_truncate_gameplans(directory,cut)
    discarded_adjudications=_truncate_combo_adjudications(
        directory,{row["decision_id"] for row in rows[:cut]},cut)
    audit_path = directory / "rejections.jsonl"
    audit = read_jsonl(audit_path)
    audit.append({
        "rejected_at": now(), "from_decision": decision_id,
        "discarded_count": len(discarded), "discarded_sha256": digest,
        "discarded_gameplan_entry_count":discarded_gameplans["count"],
        "discarded_gameplan_sha256":discarded_gameplans["sha256"],
        "discarded_combo_adjudication_count":discarded_adjudications["count"],
        "discarded_combo_adjudication_sha256":discarded_adjudications["sha256"],
        "reason": reason,
    })
    write_jsonl(audit_path, audit)
    for checkpoint in (directory / "checkpoints").glob("*.json"):
        if read_json(checkpoint)["decision_count"] > cut:
            checkpoint.unlink()
    return advance(root, number)


@serialized
def migrate_legacy_attack_batches(root: Path, game_number: Optional[int] = None) -> Dict[str, Any]:
    """Collapse legacy one-creature-at-a-time tape rows into atomic attack batches."""
    _require_no_prepared_learning_transaction(root, "migrate gameplay decisions")
    manifest=load_manifest(root);number=game_number or manifest['active_game']
    _require_not_future_game(manifest,number,'migrate decisions for')
    directory=game_dir(root,number)
    if _recover_answer_transaction_before_operation(root,number) is not None:
        manifest=load_manifest(root)
    tape_path=directory/'decisions.jsonl';rows=read_jsonl(tape_path)
    requests={}
    for checkpoint in sorted((directory/'checkpoints').glob('*.json')):
        request=read_json(checkpoint).get('request')
        if request:requests[request['decision_id']]=request
    if not any((requests.get(row['decision_id']) or {}).get('kind')=='declare_attacker' for row in rows):
        return advance(root,number)
    if any(_read_gameplan(directory,pilot) for pilot in PILOT_GAMEPLAN_FILES):
        raise SystemExit(
            'Cannot migrate legacy attack decisions while private gameplan journals exist; '
            'their decision anchors would become ambiguous.'
        )
    if read_jsonl(directory/COMBO_ADJUDICATION_JOURNAL):
        raise SystemExit(
            'Cannot migrate legacy attack decisions while combo adjudications exist; '
            'their proposal decision anchors would become ambiguous.')
    status_path=directory/'status.json';status=read_json(status_path) if status_path.exists() else {}
    review=status.get('postgame_review') or (
        manifest.get('games',{}).get(str(number),{}).get('postgame_review') or {}
    )
    transaction=directory/POSTGAME_LEARNING_DIR/LEARNING_TRANSACTION_FILE
    if transaction.exists() and read_json(transaction).get('state')!='committed':
        raise SystemExit('Cannot migrate decisions while a learning transaction is prepared; retry learn first.')
    if review.get('state') in REVIEW_RESOLVED_STATES or _review_applications(directory):
        raise SystemExit('Cannot migrate decisions for a game with a resolved post-game review.')
    if review.get('state') in REVIEW_LOCKED_STATES:
        _invalidate_unresolved_terminal_review(root,manifest,directory,number)
    before=hashlib.sha256(tape_path.read_bytes()).hexdigest();migrated=[];index=0;collapsed=0
    while index<len(rows):
        row=rows[index];request=requests.get(row['decision_id']) or {}
        if request.get('kind')!='declare_attacker':
            copy=dict(row);copy['decision_id']=f'G{number:02d}-D{len(migrated)+1:04d}';migrated.append(copy);index+=1;continue
        group=[]
        while index<len(rows) and (requests.get(rows[index]['decision_id']) or {}).get('kind')=='declare_attacker':
            group.append(rows[index]);index+=1
        selected=[entry['chosen_label'] for entry in group if entry.get('choice_index') is not None]
        rationales=[entry.get('rationale','') for entry in group if entry.get('rationale')]
        migrated.append({
            'decision_id':f'G{number:02d}-D{len(migrated)+1:04d}',
            'choice_indexes':list(range(len(selected))),'chosen_labels':selected,
            'rationale':' / '.join(rationales),'accepted_at':group[-1].get('accepted_at',now()),
            'chunk':group[-1].get('chunk',1),
        })
        collapsed+=len(group)-1
    write_jsonl(tape_path,migrated)
    pilot_handoff.invalidate_sessions(root,number,'decision migration')
    from . import pilot_dispatch, planner_runtime
    pilot_dispatch.invalidate_registry(root,number)
    planner_runtime.invalidate_contexts(root,number)
    (root/'host_runtime'/'sessions.json').unlink(missing_ok=True)
    audit_path=directory/'migrations.jsonl';audit=read_jsonl(audit_path)
    audit.append({'migrated_at':now(),'kind':'atomic_attacker_batches','old_rows':len(rows),
                  'new_rows':len(migrated),'collapsed_rows':collapsed,'source_sha256':before})
    write_jsonl(audit_path,audit)
    for checkpoint in (directory/'checkpoints').glob('*.json'):checkpoint.unlink()
    return advance(root,number)


def inspect_current(root: Path, query: str, game_number: Optional[int] = None,
                    actor: Optional[str] = None) -> Dict[str, Any]:
    """Replay read-only state and inspect it without consuming a game decision."""
    directory,config,request,game,viewer,service=_inspection_context(root,game_number,actor)
    try:
        result=_execute_inspection_query(
            directory,config,request,game,viewer,service,query,retain_error=False)
    except InspectionError as exc:raise SystemExit(str(exc)) from exc
    reconcile_status(root,config['game'])
    return result


@serialized
def inspect_many_current(root: Path, queries, game_number: Optional[int] = None,
                         actor: Optional[str] = None, *, pilot_context=None):
    """Inspect explicit queries with one replay, retaining successes and failures."""
    if not isinstance(queries,(list,tuple)) or not 1<=len(queries)<=32 or any(
        not isinstance(query,str) or not query.strip() for query in queries
    ):raise SystemExit('Supply 1..32 nonempty inspection queries.')
    directory,config,request,game,viewer,service=_inspection_context(root,game_number,actor)
    if pilot_context is not None and pilot_context!=(request or {}).get('pilot_context_id'):
        raise SystemExit('Inspection context is stale; obtain the current own-seat packet.')
    results=[]
    for query in queries:
        result=_execute_inspection_query(
            directory,config,request,game,viewer,service,query,retain_error=True)
        results.append((query,result))
    reconcile_status(root,config['game'])
    return [{'query':query,'result':result} for query,result in results]


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    """Append one compact record without rereading or replacing prior rows."""
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8',newline='') as handle:
        handle.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
        handle.flush()


def _inspection_branch_sha256(directory: Path) -> str:
    tape=directory/'decisions.jsonl'
    return hashlib.sha256(tape.read_bytes() if tape.exists() else b'').hexdigest()


def _inspection_cache_identity(directory: Path, request: Optional[Dict[str, Any]],
                               viewer: str, normalized_query: str) -> tuple[str,str]:
    branch=_inspection_branch_sha256(directory)
    decision_surface={key:(request or {}).get(key) for key in (
        'actor','decision_id','kind','phase','options','allow_pass')}
    identity={
        'schema':INSPECTION_CACHE_SCHEMA,
        'actor':viewer,'decision_id':(request or {}).get('decision_id'),
        'accepted_branch_sha256':branch,'normalized_query':normalized_query,
        'decision_surface_sha256':pilot_handoff.fingerprint(decision_surface),
    }
    deployment=directory.parent/'runtime_deployment.json'
    if deployment.exists():identity['runtime_deployment_sha256']=_sha256_file(deployment)
    return pilot_handoff.fingerprint(identity),branch


def _inspection_result_sha256(result: Dict[str, Any]) -> str:
    return pilot_handoff.fingerprint(result)


def _inspection_evidence_path(directory: Path, result_sha256: str) -> Path:
    return directory/INSPECTION_EVIDENCE_DIR/f'{result_sha256}.json'


def _load_cached_inspection(directory: Path, cache_key: str) -> Optional[Dict[str, Any]]:
    pointer_path=directory/INSPECTION_CACHE_DIR/f'{cache_key}.json'
    if not pointer_path.exists():return None
    try:
        pointer=read_json(pointer_path)
        result_sha256=str(pointer['result_sha256'])
        evidence_path=_inspection_evidence_path(directory,result_sha256)
        result=read_json(evidence_path)
    except (OSError,ValueError,KeyError,json.JSONDecodeError):
        return None
    if _inspection_result_sha256(result)!=result_sha256:return None
    return result


def _inspection_snapshot_provenance(directory: Path, config: Dict[str, Any]) -> Dict[str, Any]:
    snapshot_name=config.get('strategy_snapshot') or STRATEGY_SNAPSHOT_FILE
    snapshot_path=Path(str(snapshot_name))
    if not snapshot_path.is_absolute():snapshot_path=directory/snapshot_path
    provenance={
        'frozen':True,'live_updates':False,
        'file':_relative_path(snapshot_path,directory),
    }
    if snapshot_path.exists():provenance['sha256']=_sha256_file(snapshot_path)
    return provenance


def _store_inspection_result(directory: Path, cache_key: Optional[str],
                             result: Dict[str, Any]) -> tuple[str,str]:
    result_sha256=_inspection_result_sha256(result)
    evidence_path=_inspection_evidence_path(directory,result_sha256)
    if not evidence_path.exists():write_json(evidence_path,result)
    evidence_reference=_relative_path(evidence_path,directory)
    if cache_key:
        pointer_path=directory/INSPECTION_CACHE_DIR/f'{cache_key}.json'
        if not pointer_path.exists():
            write_json(pointer_path,{
                'schema':INSPECTION_CACHE_SCHEMA,'cache_key':cache_key,'result_sha256':result_sha256,
                'evidence_reference':evidence_reference,
            })
    return result_sha256,evidence_reference


def _record_inspection(directory: Path, request: Optional[Dict[str, Any]], viewer: str,
                       query: str, normalized_query: str, result: Dict[str, Any], *,
                       cache_key: Optional[str], branch_sha256: str,
                       cache_hit: bool) -> None:
    result_sha256,evidence_reference=_store_inspection_result(directory,cache_key,result)
    catalog_refs=sorted(set((result.get('catalog_identities') or result.get('catalog_records') or {}).keys()))
    memory_refs=sorted({
        str(note.get('note_id')) for note in result.get('pilot_memory',[])
        if isinstance(note,dict) and note.get('note_id')
    })
    _append_jsonl(directory/INSPECTION_AUDIT_FILE,{
        'schema':2,'inspected_at':now(),
        'decision_id':(request or {}).get('decision_id'),'actor':viewer,
        'query':query,'normalized_query':normalized_query,
        'result_kind':result.get('kind'),'result_sha256':result_sha256,
        'evidence_reference':evidence_reference,
        'accepted_branch_sha256':branch_sha256,
        'pilot_context_id':(request or {}).get('pilot_context_id'),
        'cache_hit':cache_hit,
        'catalog_references':catalog_refs,'memory_references':memory_refs,
    })


def _execute_inspection_query(directory: Path, config: Dict[str, Any],
                              request: Optional[Dict[str, Any]], game: Any,
                              viewer: str, service: InspectionService, query: str, *,
                              retain_error: bool) -> Dict[str, Any]:
    normalized=' '.join(query.split())
    cache_key=None
    branch_sha256=_inspection_branch_sha256(directory)
    cache_hit=False
    try:
        normalized=service.normalize_query(viewer,query)
        cache_key,branch_sha256=_inspection_cache_identity(
            directory,request,viewer,normalized)
        result=_load_cached_inspection(directory,cache_key)
        if result is None:
            result=service.query(game,viewer,query,decision_request=request)
            snapshot=dict(result.get('strategy_snapshot') or {})
            snapshot.update(_inspection_snapshot_provenance(directory,config))
            result['strategy_snapshot']=snapshot
        else:cache_hit=True
    except (InspectionError,ValueError) as exc:
        if not retain_error:raise
        result={
            'kind':'error','actor':viewer,'error_type':type(exc).__name__,
            'error':str(exc),'normalized_query':normalized,
        }
    _record_inspection(
        directory,request,viewer,query,normalized,result,
        cache_key=cache_key,branch_sha256=branch_sha256,cache_hit=cache_hit)
    return result


def _inspection_review_records(directory: Path, pilot: str) -> tuple[list[Dict[str,Any]],Dict[str,Any]]:
    """Resolve actor-private content-addressed inspection evidence for review."""
    compact=[];payloads={}
    for stored in read_jsonl(directory/INSPECTION_AUDIT_FILE):
        if stored.get('actor')!=pilot:continue
        row=dict(stored)
        legacy_result=row.pop('result',None)
        result_sha256=str(row.get('result_sha256') or '')
        if legacy_result is not None:
            result_sha256=result_sha256 or _inspection_result_sha256(legacy_result)
            row['result_sha256']=result_sha256
            payloads.setdefault(result_sha256,legacy_result)
        elif result_sha256:
            evidence_path=_inspection_evidence_path(directory,result_sha256)
            if evidence_path.exists():
                result=read_json(evidence_path)
                if _inspection_result_sha256(result)!=result_sha256:
                    raise SystemExit(f'Inspection evidence hash mismatch: {result_sha256}')
                payloads.setdefault(result_sha256,result)
        compact.append(row)
    return compact,payloads


def _inspection_context(root,game_number,actor):
    """Build one actor-scoped read-only inspection state."""
    _require_no_prepared_learning_transaction(root, "inspect gameplay")
    manifest=load_manifest(root);number=game_number or manifest['active_game']
    _require_not_future_game(manifest,number,'inspect')
    directory=game_dir(root,number)
    if _recover_answer_transaction_before_operation(root,number) is not None:
        manifest=load_manifest(root)
    if not _game_has_started(directory):
        raise SystemExit(f"Game {number:02d} has not started; run advance before inspection.")
    config=_game_config_with_bound_surface(root,manifest,number)
    tape=directory/'decisions.jsonl';tape.touch(exist_ok=True)
    scratch=directory/'.inspection_request.json'
    outcome=_run(root,config,tape,scratch,retain_suspended_game=True)
    scratch.unlink(missing_ok=True)
    game=outcome.get('game')
    if game is None:raise SystemExit('The game could not be reconstructed for inspection.')
    request=outcome.get('request');pending_actor=(request or {}).get('actor')
    if pending_actor:
        if actor is not None and actor!=pending_actor:
            raise SystemExit(
                f'Inspection is private to pending pilot {pending_actor!r}; '
                '--actor cannot switch viewers while a gameplay decision is open.')
        viewer=pending_actor
    else:viewer=actor
    if not viewer:
        raise SystemExit('A completed game has no pending actor; pass --actor with one of the four deck names.')
    if viewer not in game.players:raise SystemExit(f'Unknown pilot {viewer!r}.')
    service=getattr(game,'inspection_service',None)
    if service is None:raise SystemExit('The game has no inspection service for its frozen strategy revision.')
    published=read_json(directory/'status.json').get('request') or {}
    if request and published.get('decision_id')==request.get('decision_id') and published.get('actor')==viewer:
        request={**request,'pilot_context_id':published.get('pilot_context_id')}
    return directory,config,request,game,viewer,service


def _revision_id(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        revision_id = value.get("revision_id")
        return str(revision_id) if revision_id else None
    return str(value) if value else None


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_review_bindings(directory: Path, request: Dict[str, Any]) -> None:
    for relative, expected in request.get("bindings", {}).items():
        candidate = (directory / str(relative)).resolve()
        try:
            candidate.relative_to(directory.resolve())
        except ValueError as exc:
            raise SystemExit(f"Post-game review binding escapes the game directory: {relative}") from exc
        if not candidate.exists():
            raise SystemExit(f"Post-game review input is missing: {relative}")
        actual = _sha256_file(candidate)
        if actual != str(expected):
            raise SystemExit(
                f"Post-game review input changed after the request was sealed: {relative}"
            )


def _validate_pending_review_response(
    directory: Path,
    status: Dict[str, Any],
    patch: Dict[str, Any],
    manifest: Optional[Dict[str, Any]] = None,
) -> tuple[Dict[str, Any], str, str]:
    review_state = status.get("postgame_review") or {}
    request_path = directory / POSTGAME_REVIEW_DIR / REVIEW_REQUEST_FILE
    if not request_path.exists():
        raise SystemExit("Pending post-game review is missing its immutable review request.")
    request = read_json(request_path)
    current_rules_tag=quarantine.rules_integrity_tag(directory.parent,int(status['game']))
    if request.get('rules_integrity')!=current_rules_tag:
        raise SystemExit(
            'Rules work items changed after the review bundle was sealed; regenerate the terminal review.')
    if request.get("review_id") != review_state.get("review_id"):
        raise SystemExit("Post-game review ID does not match the terminal checkpoint.")
    if patch.get("review_id") != request.get("review_id"):
        raise SystemExit(
            "Learning response review_id does not match this terminal review request."
        )
    if patch.get("terminal_fingerprint") != request.get("terminal_fingerprint"):
        raise SystemExit(
            "Learning response terminal_fingerprint does not match this sealed game."
        )
    identity_payload = {
        "game": request.get("game"),
        "terminal_fingerprint": request.get("terminal_fingerprint"),
        "bindings": request.get("bindings", {}),
    }
    expected_review_id = "review-" + hashlib.sha256(
        json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    if request.get("review_id") != expected_review_id:
        raise SystemExit("Post-game review request identity hash is invalid.")
    _validate_review_bindings(directory, request)
    seal_path=directory/TERMINAL_SEAL_FILE
    if not seal_path.exists():
        raise SystemExit("Pending review is missing its immutable terminal result record.")
    seal=read_json(seal_path)
    fingerprint_payload={key:value for key,value in seal.items() if key!="terminal_fingerprint"}
    expected_terminal="terminal-"+hashlib.sha256(
        json.dumps(fingerprint_payload,sort_keys=True,separators=(",",":")).encode("utf-8")
    ).hexdigest()
    if (
        seal.get("terminal_fingerprint")!=expected_terminal
        or request.get("terminal_fingerprint")!=expected_terminal
    ):
        raise SystemExit("Terminal result fingerprint is invalid or stale.")
    config=read_json(directory/GAME_CONFIG_FILE)
    comparisons=(
        ("game",seal.get("game"),status.get("game")),
        ("seed",seal.get("seed"),status.get("seed")),
        ("result",seal.get("result"),status.get("result")),
        ("decision_count",seal.get("decision_count"),status.get("decision_count")),
        ("config game",seal.get("game"),config.get("game")),
        ("config seed",seal.get("seed"),config.get("seed")),
        ("strategy revision",seal.get("strategy_revision"),config.get("strategy_revision")),
    )
    for label,sealed_value,live_value in comparisons:
        if sealed_value!=live_value:
            raise SystemExit(f"Terminal {label} no longer matches the sealed review input.")
    if manifest is not None:
        entry=manifest.get("games",{}).get(str(seal["game"]),{})
        if entry.get("result") is not None and entry.get("result")!=seal.get("result"):
            raise SystemExit("Cohort manifest result no longer matches the terminal seal.")
    review = patch.get("review")
    if not isinstance(review, dict):
        raise SystemExit("Pending post-game review requires a review object in the learning patch.")
    if config.get('decision_surface_revision',1)>=SCHEDULER_DECISION_SURFACE_REVISION:
        if request.get('review_contract')!=2:raise SystemExit('Missing evidence review contract')
        packets={}
        for path in (directory/POSTGAME_EVIDENCE_DIR).glob('*.json'):
            packet=read_json(path);packets[packet['viewer']]=packet
        try:review_contract.validate_analyses(review,packets)
        except ValueError as exc:raise SystemExit(str(exc)) from exc
    tagged_issues=(request.get('rules_integrity') or {}).get('issues',[])
    syntheses=review.get('rules_issue_synthesis',[])
    if not isinstance(syntheses,list) or any(not isinstance(row,dict) for row in syntheses):
        raise SystemExit('Rules issue synthesis must be a list.')
    synthesis_ids=[row.get('issue_id') for row in syntheses]
    expected_issue_ids=[row.get('issue_id') for row in tagged_issues]
    if len(synthesis_ids)!=len(set(synthesis_ids)) or set(synthesis_ids)!=set(expected_issue_ids):
        raise SystemExit('Consolidated learning must synthesize every tagged rules issue exactly once.')
    for row in syntheses:
        if (row.get('impact') not in {'unaffected','evidence_limited','invalidated','uncertain'} or
                not str(row.get('analysis','')).strip() or
                not str(row.get('learning_treatment','')).strip()):
            raise SystemExit(
                'Each rules issue synthesis needs an impact, skeptical analysis, and learning treatment.')
    summary = str(review.get("summary", "")).strip()
    if not summary:
        raise SystemExit("Post-game review requires a nonempty narrative summary.")
    dispositions = review.get("pilot_dispositions")
    if not isinstance(dispositions, dict):
        raise SystemExit("Post-game review requires one pilot_dispositions entry per deck.")
    expected_pilots = set(engine.DECKDEFS)
    if set(dispositions) != expected_pilots:
        missing = sorted(expected_pilots - set(dispositions))
        extras = sorted(set(dispositions) - expected_pilots)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extras:
            detail.append("unexpected " + ", ".join(extras))
        raise SystemExit("Pilot dispositions must cover exactly the four decks: " + "; ".join(detail))
    allowed = {"changes", "no_change", "rules_blocker"}
    disposition_values: list[str] = []
    for pilot, raw in dispositions.items():
        if not isinstance(raw, dict):
            raise SystemExit(f"Pilot disposition for {pilot} must be a JSON object.")
        extras = sorted(set(raw) - {"disposition", "rationale"})
        if extras:
            raise SystemExit(
                f"Pilot disposition for {pilot} has unexpected fields: {', '.join(extras)}"
            )
        disposition = str(raw.get("disposition", ""))
        rationale = str(raw.get("rationale", "")).strip()
        if disposition not in allowed or not rationale:
            raise SystemExit(
                f"Pilot disposition for {pilot} requires changes, no_change, or rules_blocker "
                "and a nonempty rationale."
            )
        disposition_values.append(disposition)
    operations = patch.get("operations", [])
    if not isinstance(operations, list):
        raise SystemExit("Learning patch operations must be a list.")
    if "rules_blocker" in disposition_values:
        if operations:
            raise SystemExit(
                "A rules-blocker review cannot also apply strategy operations. "
                "Remove the operations; the blocker becomes a draw and a repair work item."
            )
        return request, "rules_blocker", summary
    if operations and "changes" not in disposition_values:
        raise SystemExit("A nonempty learning patch requires at least one pilot disposition of changes.")
    if not operations and not str(review.get("no_change_reason", "")).strip():
        raise SystemExit("An empty learning patch requires a nonempty no_change_reason.")
    disposition = "applied" if operations else "no_changes"
    return request, disposition, summary


def _record_review_rules_blocker(
    root: Path,
    manifest: Dict[str, Any],
    directory: Path,
    status: Dict[str, Any],
    game_number: int,
    request: Dict[str, Any],
    patch: Dict[str, Any],
    patch_sha256: str,
    summary: str,
) -> Dict[str, Any]:
    """Turn a review-discovered game-breaking defect into a tagged draw."""
    quarantine.quarantine_games(
        DEFAULT_STRATEGY_FILE,root,[game_number],summary,severity='game_breaking')
    reports_path=directory/'rules_blocker_reports.jsonl'
    reports=read_jsonl(reports_path)
    existing=next((row for row in reports if row.get('patch_sha256')==patch_sha256),None)
    recorded_at=(existing or {}).get('recorded_at') or now()
    record=existing or {
        "schema":1,
        "review_id":request.get("review_id"),
        "recorded_at":recorded_at,
        "review_disposition":"rules_blocker",
        "patch_sha256":patch_sha256,
        "patch":patch,
        "summary":summary,
        "outcome":"rules_blocker_draw",
    }
    if existing is None:
        reports.append(record);write_jsonl(reports_path,reports)
    _invalidate_unresolved_terminal_review(root,manifest,directory,game_number)
    for checkpoint in (directory/'checkpoints').glob('*.json'):
        candidate=read_json(checkpoint)
        if candidate.get('state')=='complete':checkpoint.unlink()
    manifest['active_game']=game_number;manifest['cohort_state']='active';manifest['updated_at']=now()
    write_json(root/'cohort.json',manifest)
    _adjudicate_rules_blocker_draw(root,game_number,summary)
    return record


def _finalize_resolved_review(
    root: Path,
    manifest: Dict[str, Any],
    directory: Path,
    status: Dict[str, Any],
    game_number: int,
    audit: Dict[str, Any],
    audit_path: Path,
) -> Dict[str, Any]:
    """Idempotently finish status/manifest/NEXT_ACTION after a durable audit."""

    disposition=str(audit["review_disposition"])
    patch=audit.get("patch") or {}
    review=patch.get("review") if isinstance(patch,dict) else {}
    summary=str((review or {}).get("summary","")).strip()
    if summary:atomic_text(directory/GAME_SUMMARY_FILE,summary+"\n")
    resolved_at=(status.get("postgame_review") or {}).get("resolved_at") or now()
    previous_review=status.get("postgame_review") or {}
    status["postgame_review"]={
        **previous_review,
        "state":disposition,
        "resolved_at":resolved_at,
        "audit_path":_relative_path(audit_path,root),
    }
    config=read_json(directory/GAME_CONFIG_FILE)
    status.setdefault("seed",config.get("seed"))
    status.setdefault("decision_count",len(read_jsonl(directory/"decisions.jsonl")))
    status.setdefault("request",None);status.setdefault("result",None);status.setdefault("error",None)
    write_json(directory/"status.json",status)
    atomic_text(directory/"STATUS.md",_status_markdown(status))
    response_path=directory/POSTGAME_REVIEW_DIR/"response.json"
    if response_path.parent.exists():
        write_json(response_path,{
            "schema":1,
            "review_id":audit.get("review_id"),
            "resolved_at":resolved_at,
            "disposition":disposition,
            "patch_sha256":audit["patch_sha256"],
            "audit_path":_relative_path(audit_path,root),
        })

    game_entry=manifest.setdefault("games",{}).setdefault(str(game_number),{})
    game_entry.update({
        "state":"complete",
        "decision_count":status.get("decision_count",game_entry.get("decision_count",0)),
        "postgame_review":status["postgame_review"],
    })
    if status.get("result"):game_entry["result"]=status["result"]
    if int(manifest.get("active_game",game_number))==game_number:
        if game_number<int(manifest["target_games"]):
            manifest["active_game"]=game_number+1;manifest["cohort_state"]="active"
        else:manifest["cohort_state"]="complete"
    manifest["updated_at"]=now();write_json(root/"cohort.json",manifest)
    if quarantine.rules_integrity_tag(root,game_number) is not None:
        try:quarantine.complete_critical_review(
            DEFAULT_STRATEGY_FILE,root,game_number,audit.get('review_id'),
            audit.get('patch_sha256'))
        except ValueError as exc:raise SystemExit(str(exc)) from exc
    active_number=int(manifest["active_game"])
    next_status=status
    if active_number!=game_number:
        active_status_path=game_dir(root,active_number)/"status.json"
        next_status=(
            read_json(active_status_path)
            if active_status_path.exists()
            else {"game":active_number,"state":"not_started","postgame_review":{"state":"not_ready"}}
        )
    _write_next_action(root,manifest,next_status)
    audit["workflow_transition"]={
        "postgame_review":disposition,
        "active_game":manifest["active_game"],
        "cohort_state":manifest["cohort_state"],
    }
    write_json(audit_path,audit)
    return audit


def _transaction_fingerprint(transaction: Dict[str, Any]) -> str:
    payload={key:value for key,value in transaction.items() if key!="transaction_fingerprint"}
    return hashlib.sha256(
        json.dumps(payload,sort_keys=True,separators=(",",":")).encode("utf-8")
    ).hexdigest()


def _resume_learning_transaction(
    root: Path,
    manifest: Dict[str, Any],
    directory: Path,
    status: Dict[str, Any],
    strategy_path: Path,
    snapshot_path: Path,
    snapshot_bytes_before: bytes,
    transaction_path: Path,
    transaction: Dict[str, Any],
) -> Dict[str, Any]:
    """Complete a prepared learning commit after any interrupted write boundary."""

    if transaction.get("transaction_fingerprint")!=_transaction_fingerprint(transaction):
        raise SystemExit("Post-game learning transaction fingerprint is invalid.")
    updated=StrategyState.from_dict(transaction["updated_strategy"])
    updated.validate(catalog_card_ids=engine.CATALOG.by_id)
    current=load_strategy_state(strategy_path)
    current_id=current.freeze().revision_id
    base_id=str(transaction["base_revision_id"]);result_id=str(transaction["result_revision_id"])
    if current_id==base_id and result_id!=base_id:
        atomic_text(strategy_path,json.dumps(updated.to_dict(),ensure_ascii=False,indent=2)+"\n")
    elif current_id!=result_id:
        raise SystemExit(
            "Global strategy changed while a prepared learning transaction was pending; "
            "manual reconciliation is required."
        )
    persisted=load_strategy_state(strategy_path)
    if persisted.freeze().revision_id!=result_id:
        raise SystemExit("Global strategy verification failed while resuming learning.")
    if snapshot_path.read_bytes()!=snapshot_bytes_before:
        raise SystemExit("Reviewed game's frozen strategy snapshot changed during learning.")
    audit_dir=directory/POSTGAME_LEARNING_DIR;audit_dir.mkdir(exist_ok=True)
    audit_path=audit_dir/"application_0001.json"
    audit=dict(transaction["audit"])
    if audit_path.exists():
        existing=read_json(audit_path)
        if existing.get("patch_sha256")!=audit.get("patch_sha256"):
            raise SystemExit("A different learning application audit already exists.")
        audit=existing
    else:write_json(audit_path,audit)
    audit=_finalize_resolved_review(root,manifest,directory,status,int(audit["source_game"]),audit,audit_path)
    transaction["state"]="committed";transaction["committed_at"]=now()
    transaction["transaction_fingerprint"]=_transaction_fingerprint(transaction)
    write_json(transaction_path,transaction)
    active_number=int(manifest["active_game"])
    active_status_path=game_dir(root,active_number)/"status.json"
    next_status=(
        read_json(active_status_path)
        if active_status_path.exists()
        else {"game":active_number,"state":"not_started","postgame_review":{"state":"not_ready"}}
    )
    _write_next_action(root,manifest,next_status)
    return audit


@serialized
def learn(root: Path, game_number: int, patch_path: Path) -> Dict[str, Any]:
    """Commit one externally reviewed post-game strategy patch.

    The completed game's evidence and strategy snapshot are immutable review
    inputs.  Only the current global strategy profile is replaced, and only when
    the patch names that profile's exact frozen base revision.
    """

    manifest = load_manifest(root)
    _require_cohort_not_cancelled(manifest,"run post-game learning")
    _require_not_future_game(manifest, game_number, "review")
    game_config(manifest, game_number)  # validates the requested game number
    directory = game_dir(root, game_number)
    from .learning_policy import enabled as learning_enabled
    if not learning_enabled(read_json(directory/GAME_CONFIG_FILE)):
        raise SystemExit('Learning was disabled at run initialization; no post-game learning is permitted.')
    if _recover_answer_transaction_before_operation(root,game_number) is not None:
        manifest=load_manifest(root)
    status_path = directory / "status.json"
    if not status_path.exists():
        raise SystemExit(f"Game {game_number:02d} has no status checkpoint.")
    status = read_json(status_path)
    if status.get("state") != "complete":
        raise SystemExit(f"Game {game_number:02d} is not complete; post-game learning is unavailable.")

    snapshot_path = directory / STRATEGY_SNAPSHOT_FILE
    config_path = directory / GAME_CONFIG_FILE
    if not snapshot_path.exists() or not config_path.exists():
        raise SystemExit(
            f"Game {game_number:02d} requires both {STRATEGY_SNAPSHOT_FILE} and {GAME_CONFIG_FILE}."
        )
    snapshot_bytes_before = snapshot_path.read_bytes()
    snapshot = load_strategy_state(snapshot_path)
    try:quarantine.require_snapshot_clean(DEFAULT_STRATEGY_FILE,snapshot)
    except ValueError as exc:raise SystemExit(str(exc)) from exc
    snapshot_revision = snapshot.freeze().to_dict()
    persisted_config = read_json(config_path)
    if _revision_id(persisted_config.get("strategy_revision")) != snapshot_revision["revision_id"]:
        raise SystemExit(f"Game {game_number:02d} strategy snapshot does not match its frozen config revision.")
    if _revision_id(status.get("strategy_revision")) != snapshot_revision["revision_id"]:
        raise SystemExit(f"Game {game_number:02d} status does not match its frozen strategy revision.")

    evidence_dir = directory / POSTGAME_EVIDENCE_DIR
    evidence_paths = sorted(evidence_dir.glob("*.json")) if evidence_dir.exists() else []
    evidence_by_viewer: dict[str, Path] = {}
    for evidence_path in evidence_paths:
        evidence = read_json(evidence_path)
        if int(evidence.get("game", -1)) != game_number:
            raise SystemExit(f"Evidence {evidence_path.name} belongs to a different game.")
        if _revision_id(evidence.get("strategy_revision")) != snapshot_revision["revision_id"]:
            raise SystemExit(f"Evidence {evidence_path.name} does not match the game's strategy snapshot.")
        viewer = str(evidence.get("viewer", ""))
        if viewer:
            evidence_by_viewer[viewer] = evidence_path
    missing_viewers = sorted(set(engine.DECKDEFS) - set(evidence_by_viewer))
    if missing_viewers:
        raise SystemExit(
            f"Game {game_number:02d} is missing post-game evidence for: {', '.join(missing_viewers)}"
        )
    if quarantine.rules_integrity_tag(root,game_number) is not None:
        try:quarantine.require_repairs_complete(root,game_number)
        except ValueError as exc:raise SystemExit(str(exc)) from exc

    patch_path = Path(patch_path).resolve()
    if not patch_path.exists():
        raise SystemExit(f"Learning patch does not exist: {patch_path}")
    try:
        patch = read_json(patch_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read learning patch {patch_path}: {exc}") from exc
    if not isinstance(patch, dict) or not patch.get("base_revision"):
        raise SystemExit("Learning patch must name the current global base_revision.")

    patch_sha256 = _sha256_file(patch_path)
    status_review = status.get("postgame_review") or {}
    manifest_review = (
        manifest.get("games", {}).get(str(game_number), {}).get("postgame_review") or {}
    )
    if status_review.get("state") in (None, "not_ready") and manifest_review.get("state"):
        status_review = manifest_review
        status["postgame_review"] = status_review

    review_request: Optional[Dict[str, Any]] = None
    review_disposition = "applied" if patch.get("operations") else "no_changes"
    review_summary = ""
    response_path=directory/POSTGAME_REVIEW_DIR/"response.json"
    if status_review.get("state")=="rules_blocker":
        if not response_path.exists():
            raise SystemExit(
                "Recorded post-game rules blocker is missing its response artifact; "
                "repair the artifact, record the engine fix, and regenerate the skeptical review."
            )
        recorded=read_json(response_path)
        if recorded.get("patch_sha256")!=patch_sha256:
            raise SystemExit(
                "A recorded post-game rules blocker cannot be replaced by another response. "
                "Fix the rules defect and use repair-rules to regenerate the skeptical review."
            )
    if status_review.get("state") in REVIEW_LOCKED_STATES:
        review_request, review_disposition, review_summary = _validate_pending_review_response(
            directory, status, patch, manifest
        )
        if review_disposition=="rules_blocker" and response_path.exists():
            recorded=read_json(response_path)
            if recorded.get("patch_sha256")!=patch_sha256:
                raise SystemExit("A different post-game rules blocker is already recorded.")
            return _record_review_rules_blocker(
                root,manifest,directory,status,game_number,review_request,patch,
                patch_sha256,review_summary,
            )

    strategy_path=Path(DEFAULT_STRATEGY_FILE).resolve()
    if strategy_path==snapshot_path.resolve():
        raise SystemExit("Global strategy path must not be the reviewed game's frozen snapshot.")
    transaction_path=directory/POSTGAME_LEARNING_DIR/LEARNING_TRANSACTION_FILE
    if transaction_path.exists():
        transaction=read_json(transaction_path)
        if transaction.get("patch_sha256")!=patch_sha256:
            raise SystemExit("A different prepared learning transaction already exists for this game.")
        if transaction.get("state")!="committed":
            return _resume_learning_transaction(
                root,manifest,directory,status,strategy_path,snapshot_path,
                snapshot_bytes_before,transaction_path,transaction,
            )

    existing_applications=_review_applications(directory)
    if existing_applications:
        audit_path=existing_applications[-1];latest=read_json(audit_path)
        if latest.get("patch_sha256")!=patch_sha256:
            raise SystemExit(
                f"Game {game_number:02d} already has a resolved post-game review; "
                "a different second learning patch is not allowed."
            )
        return _finalize_resolved_review(
            root,manifest,directory,status,game_number,latest,audit_path
        )
    review_state=str(status_review.get("state") or "not_ready")
    if review_state in REVIEW_RESOLVED_STATES:
        raise SystemExit(
            f"Game {game_number:02d} post-game review is sealed as {review_state}; "
            "no new learning response is allowed."
        )
    if review_state not in REVIEW_LOCKED_STATES:
        raise SystemExit(
            f"Game {game_number:02d} has no sealed pending review request. "
            "Unbound post-game learning is not allowed."
        )

    current = load_strategy_state(strategy_path)
    current.validate(catalog_card_ids=engine.CATALOG.by_id)
    if str(patch["base_revision"]) != current.freeze().revision_id:
        raise SystemExit(
            f"Stale learning patch: expected {patch['base_revision']}, current {current.freeze().revision_id}."
        )
    try:
        quarantine.require_clean(DEFAULT_STRATEGY_FILE,root,game_number)
        updated, patch_audit = apply_strategy_patch(current, patch, source_game=game_number,
                                                   source_cohort=str(root.resolve()))
    except (LearningPatchError, StrategyValidationError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    updated.validate(catalog_card_ids=engine.CATALOG.by_id)
    if review_disposition=="rules_blocker":
        if updated.freeze()!=current.freeze():
            raise SystemExit("A rules-blocker response must not mutate strategy memory.")
        return _record_review_rules_blocker(
            root,manifest,directory,status,game_number,review_request or {},patch,
            patch_sha256,review_summary,
        )

    audit_dir=directory/POSTGAME_LEARNING_DIR;audit_dir.mkdir(exist_ok=True)
    audit_path=audit_dir/"application_0001.json"
    audit = {
        **patch_audit,
        "review_id": (review_request or {}).get("review_id"),
        "terminal_fingerprint": (review_request or {}).get("terminal_fingerprint"),
        "review_disposition": review_disposition,
        "game_snapshot_revision": snapshot_revision,
        "game_snapshot_sha256": hashlib.sha256(snapshot_bytes_before).hexdigest(),
        "patch_path": _relative_path(patch_path,root),
        "patch_sha256": patch_sha256,
        "patch_document_sha256": hashlib.sha256(
            json.dumps(patch,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
        "patch": patch,
        "evidence": {
            viewer: {"path": _relative_path(path,root), "sha256": _sha256_file(path)}
            for viewer, path in sorted(evidence_by_viewer.items())
        },
        "global_strategy_path": _relative_path(strategy_path,PROJECT_ROOT),
        "audit_path": _relative_path(audit_path,root),
    }
    transaction={
        "schema":1,"state":"prepared","prepared_at":now(),"source_game":game_number,
        "patch_sha256":patch_sha256,
        "base_revision_id":current.freeze().revision_id,
        "result_revision_id":updated.freeze().revision_id,
        "updated_strategy":updated.to_dict(),
        "audit":audit,
    }
    transaction["transaction_fingerprint"]=_transaction_fingerprint(transaction)
    write_json(transaction_path,transaction)
    return _resume_learning_transaction(
        root,manifest,directory,status,strategy_path,snapshot_path,
        snapshot_bytes_before,transaction_path,transaction,
    )


def review_current(root: Path, game_number: Optional[int] = None) -> str:
    """Return the generated post-game review turn without advancing the cohort."""

    manifest = load_manifest(root)
    number = game_number or manifest["active_game"]
    _require_not_future_game(manifest,number,"review")
    directory = game_dir(root, number)
    status = reconcile_status(root,number)
    review = status.get("postgame_review") or {}
    if status.get("state") != "complete":
        raise SystemExit(f"Game {number:02d} is not terminal; post-game review is not ready.")
    instructions = review.get("instructions")
    if not instructions:
        if review.get("state") in REVIEW_RESOLVED_STATES:
            return _status_markdown(status)
        raise SystemExit(f"Game {number:02d} has no generated post-game review instructions.")
    path = _safe_cohort_artifact(
        root,str(instructions),directory/POSTGAME_REVIEW_DIR/REVIEW_INSTRUCTIONS_FILE
    )
    if not path.exists():
        raise SystemExit(f"Post-game review instructions are missing: {path}")
    return path.read_text(encoding="utf-8")


@serialized
def refresh_review_evidence(
    root: Path, reason: str, game_number: Optional[int] = None
) -> Dict[str, Any]:
    """Migrate one unresolved review bundle to the bounded cardwise schema."""

    _require_no_prepared_learning_transaction(root,"refresh post-game review evidence")
    manifest=load_manifest(root)
    _require_cohort_not_cancelled(manifest,"refresh post-game review evidence")
    reason=str(reason or '').strip()
    if not reason:raise SystemExit('Review-evidence refresh requires a non-empty reason.')
    number=game_number or int(manifest['active_game'])
    _require_not_future_game(manifest,number,'refresh review evidence for')
    directory=game_dir(root,number);status_path=directory/'status.json'
    if not status_path.exists():raise SystemExit(f'Game {number:02d} has no checkpoint.')
    status=read_json(status_path);review=status.get('postgame_review') or {}
    if status.get('state')!='complete' or review.get('state')!='pending':
        raise SystemExit('Review evidence can be refreshed only for a terminal pending review.')
    if _review_applications(directory):
        raise SystemExit('Resolved review evidence is immutable; start a new cohort instead.')
    evidence_dir=directory/POSTGAME_EVIDENCE_DIR
    paths=sorted(evidence_dir.glob('*.json'))
    if len(paths)!=len(engine.DECKDEFS):
        raise SystemExit('Pending review does not contain exactly four evidence packets.')
    prepared=[];viewers=set();total_before=0;total_after=0
    for path in paths:
        before=path.read_bytes();packet=read_json(path)
        viewer=packet.get('viewer')
        if viewer not in engine.DECKDEFS or viewer in viewers:
            raise SystemExit('Pending review evidence has an invalid or duplicate viewer.')
        viewers.add(viewer)
        compact=review_contract.compact_evidence(packet)
        after=(json.dumps(compact,ensure_ascii=False,separators=(',',':'))+'\n').encode('utf-8')
        prepared.append((path,viewer,before,after,compact))
        total_before+=len(before);total_after+=len(after)
    if all(packet.get('schema')==5 and before==after
           for _,_,before,after,packet in prepared):
        raise SystemExit('Pending review evidence already uses the bounded cardwise schema.')
    review_dir=directory/POSTGAME_REVIEW_DIR
    old_review_id=str(review.get('review_id') or 'unidentified-review')
    archive_root=directory/'postgame_review_archive';archive_root.mkdir(exist_ok=True)
    archive=archive_root/old_review_id
    if archive.exists():raise SystemExit(f'Review archive already exists: {archive}')
    if review_dir.exists():review_dir.replace(archive)
    for path,_,_,after,_ in prepared:atomic_text(path,after.decode('utf-8'))
    evidence_by_viewer={viewer:path for path,viewer,_,_,_ in prepared}
    config=read_json(directory/GAME_CONFIG_FILE)
    new_review=_ensure_postgame_review_bundle(
        root,config,status.get('result') or {},evidence_by_viewer)
    status['postgame_review']=new_review
    write_json(status_path,status);atomic_text(directory/'STATUS.md',_status_markdown(status))
    game_entry=manifest.setdefault('games',{}).setdefault(str(number),{})
    game_entry['postgame_review']=new_review
    manifest['cohort_state']='awaiting_review';manifest['updated_at']=now()
    write_json(root/'cohort.json',manifest)
    migration_rows=read_jsonl(directory/REVIEW_EVIDENCE_MIGRATION_FILE)
    migration={
        'schema':1,'migrated_at':now(),'reason':reason,'game':number,
        'old_review_id':old_review_id,'new_review_id':new_review.get('review_id'),
        'archived_review':_relative_path(archive,root),
        'before_bytes':total_before,'after_bytes':total_after,
        'reduction_percent':round((1-total_after/total_before)*100,2) if total_before else 0,
        'packets':[
            {
                'viewer':viewer,'path':_relative_path(path,root),
                'before_sha256':hashlib.sha256(before).hexdigest(),
                'after_sha256':hashlib.sha256(after).hexdigest(),
                'before_bytes':len(before),'after_bytes':len(after),
                'review_anchor_count':len(packet['review_requirements']['critical_decisions']),
                'card_review_count':len(packet['review_requirements']['card_review_cards']),
            }
            for path,viewer,before,after,packet in prepared
        ],
    }
    migration_rows.append(migration)
    write_jsonl(directory/REVIEW_EVIDENCE_MIGRATION_FILE,migration_rows)
    _write_next_action(root,manifest,status)
    result=dict(status);result['review_evidence_refresh']=migration
    return result


@serialized
def next_action(root: Path) -> Dict[str, Any]:
    """Return the cohort's authoritative next action without starting a game."""

    manifest = load_manifest(root);number=int(manifest["active_game"])
    if manifest.get("cohort_state")=="cancelled":
        status_path=game_dir(root,number)/"status.json"
        status=(read_json(status_path) if status_path.exists() else
                {"game":number,"state":"cancelled"})
        return _write_next_action(root,manifest,status)
    status_path=game_dir(root,number)/"status.json"
    if status_path.exists():
        reconcile_status(root,number)
        return read_json(root/NEXT_ACTION_FILE)
    return _write_next_action(root,manifest,{"game":number,"state":"not_started"})


def verify() -> Dict[str, Any]:
    """Validate catalog, deck, strategy, action, and official-pilot seams."""

    return release_report(PROJECT_ROOT)


@serialized
def cancel(root: Path, reason: str) -> Dict[str, Any]:
    """Terminate an unfinished cohort without sealing or deleting its games."""

    manifest=load_manifest(root)
    reason=str(reason or "").strip()
    if not reason:
        raise SystemExit("Cohort cancellation requires a non-empty reason.")
    if manifest.get("cohort_state")=="cancelled":
        cancellation=read_json(root/CANCELLATION_FILE)
    else:
        prepared=_prepared_learning_transaction(root)
        if prepared is not None:
            raise SystemExit(
                "A prepared learning transaction must be reconciled before the cohort can be cancelled."
            )
        number=int(manifest["active_game"]);directory=game_dir(root,number)
        status_path=directory/"status.json"
        status=read_json(status_path) if status_path.exists() else {
            "game":number,"state":"not_started","decision_count":0,"request":None,
        }
        request=status.get("request") or {}
        cancellation={
            "schema":1,
            "cancelled_at":now(),
            "reason":reason,
            "active_game":number,
            "active_game_state":status.get("state"),
            "accepted_decision_count":status.get("decision_count",0),
            "pending_decision_id":request.get("decision_id"),
            "pending_actor":request.get("actor"),
            "cancelled_unstarted_games":[
                game for game in range(number+1,int(manifest["target_games"])+1)
                if not game_dir(root,game).exists()
            ],
            "postgame_learning_cancelled_for_games":list(
                range(number,int(manifest["target_games"])+1)
            ),
            "artifacts_preserved":True,
        }
        write_json(root/CANCELLATION_FILE,cancellation)
        manifest["cohort_state"]="cancelled"
        manifest["cancelled_at"]=cancellation["cancelled_at"]
        manifest["cancellation"]={
            "path":CANCELLATION_FILE,
            "reason":reason,
            "active_game":number,
        }
        manifest["updated_at"]=now()
        write_json(root/"cohort.json",manifest)
    number=int(manifest["active_game"]);status_path=game_dir(root,number)/"status.json"
    prior=read_json(status_path) if status_path.exists() else {
        "schema":SCHEMA,"game":number,"seed":manifest["seed_start"]+number-1,
        "decision_count":0,
    }
    result={
        **prior,
        "state":"cancelled",
        "request":None,
        "combo_adjudication":None,
        "result":{"reason":"cohort cancelled","cancellation":CANCELLATION_FILE},
        "error":None,
        "cancellation":cancellation,
    }
    _write_next_action(root,manifest,result)
    return result


@serialized
def reinitialize(root: Path, reason: str) -> Dict[str, Any]:
    """Resume an explicitly cancelled cohort from its preserved lifecycle boundary.

    Cancellation remains the default terminal behavior.  This operation is the
    sole recovery path: it reruns the release gate and proves that the active
    checkpoint still matches the cancellation audit before making the cohort
    live again.  It never edits a decision tape, game result, or review state.
    """

    manifest=load_manifest(root)
    reason=str(reason or "").strip()
    if not reason:
        raise SystemExit("Cohort reinitialization requires a non-empty reason.")
    if manifest.get("cohort_state")!="cancelled":
        raise SystemExit("Only an explicitly cancelled cohort can be reinitialized.")
    _require_no_prepared_learning_transaction(root,"reinitialize a cancelled cohort")
    cancellation_path=root/CANCELLATION_FILE
    if not cancellation_path.exists():
        raise SystemExit("Cancelled cohort is missing its cancellation audit.")
    cancellation=read_json(cancellation_path)
    number=int(manifest["active_game"])
    if int(cancellation.get("active_game",-1))!=number:
        raise SystemExit("Cancellation audit does not match the active game.")
    status_path=game_dir(root,number)/"status.json"
    if not status_path.exists():
        raise SystemExit("Cancelled cohort is missing its preserved active checkpoint.")
    status=read_json(status_path)
    request=status.get("request") or {}
    expected={
        "active_game_state":status.get("state"),
        "accepted_decision_count":status.get("decision_count",0),
        "pending_decision_id":request.get("decision_id"),
        "pending_actor":request.get("actor"),
    }
    mismatches=[
        key for key,value in expected.items()
        if cancellation.get(key)!=value
    ]
    if mismatches:
        raise SystemExit(
            "Preserved checkpoint no longer matches the cancellation audit: "
            +", ".join(mismatches)
        )
    checks=verify()
    if not checks["ok"]:
        raise SystemExit("Release gate failed:\n"+json.dumps(checks,indent=2))
    journal_path=root/REINITIALIZATION_JOURNAL_FILE
    journal=read_jsonl(journal_path)
    ordinal=len(journal)+1
    gate_name=f"{REINITIALIZATION_RELEASE_GATE_PREFIX}{ordinal:04d}.json"
    write_json(root/gate_name,checks)
    reinitialized_at=now()
    entry={
        "schema":1,
        "ordinal":ordinal,
        "reinitialized_at":reinitialized_at,
        "reason":reason,
        "cancellation":CANCELLATION_FILE,
        "cancelled_at":cancellation.get("cancelled_at"),
        "active_game":number,
        "active_game_state":status.get("state"),
        "accepted_decision_count":status.get("decision_count",0),
        "release_gate":gate_name,
        "artifacts_preserved":True,
    }
    journal.append(entry);write_jsonl(journal_path,journal)
    review=(status.get("postgame_review") or {})
    if status.get("state")=="complete" and review.get("state") in REVIEW_LOCKED_STATES:
        resumed_state="awaiting_review"
    elif (status.get("state")=="complete" and
          review.get("state") in REVIEW_RESOLVED_STATES and
          number>=int(manifest["target_games"])):
        resumed_state="complete"
    else:
        resumed_state="active"
    manifest.pop("cancelled_at",None)
    prior_cancellation=manifest.pop("cancellation",None)
    history=manifest.setdefault("cancellation_history",[])
    history.append({
        **(prior_cancellation or {"path":CANCELLATION_FILE}),
        "cancelled_at":cancellation.get("cancelled_at"),
        "reinitialized_at":reinitialized_at,
        "reinitialization":REINITIALIZATION_JOURNAL_FILE,
    })
    manifest["cohort_state"]=resumed_state
    manifest["updated_at"]=reinitialized_at
    write_json(root/"cohort.json",manifest)
    next_state=_write_next_action(root,manifest,status)
    result=dict(status)
    result["reinitialization"]={
        **entry,
        "journal":REINITIALIZATION_JOURNAL_FILE,
        "next_action":next_state["next_action"],
    }
    return result


@serialized
def init(root: Path, games: int, seed_start: int, max_rounds: int, *, decision_surface_revision: int = CURRENT_DECISION_SURFACE_REVISION, planning_contract: int = 1, planner_stages: bool = False, plan_tiers: bool = True, agent_architecture: bool = False, async_diplomacy: bool = False, learning_enabled: bool = True) -> Dict[str, Any]:
    try:quarantine.require_clean(DEFAULT_STRATEGY_FILE)
    except ValueError as exc:raise SystemExit(str(exc)) from exc
    if games<1:raise SystemExit("games must be at least 1")
    if type(learning_enabled) is not bool:raise SystemExit('learning_enabled must be boolean.')
    from .agent_architecture import validate_binding
    architecture_flags={k:1 for k,v in [('agent_architecture',agent_architecture),('async_diplomacy',async_diplomacy),('decision_roles',async_diplomacy),('static_standing',agent_architecture),('combat_proposals',agent_architecture),('turn_batches',agent_architecture),('short_term_sol_fast',agent_architecture)] if v}
    validate_binding({**architecture_flags,'planning_contract':planning_contract,'planner_stages':planner_stages,'plan_tiers':plan_tiers,'context_handling':1})
    if max_rounds<1:raise SystemExit("max-rounds must be at least 1")
    if not isinstance(plan_tiers,bool):raise SystemExit('plan_tiers must be boolean.')
    if not isinstance(planner_stages,bool) or (planner_stages and planning_contract!=4):
        raise SystemExit('Staged publication requires planning contract 4.')
    if isinstance(planning_contract,bool) or planning_contract not in {1,2,3,4}:
        raise SystemExit('planning_contract must be 1, 2, 3 or 4.')
    if planning_contract>=2 and decision_surface_revision!=6:
        raise SystemExit('Split planning requires decision surface 6.')
    if (root / "cohort.json").exists():
        raise SystemExit(f"Cohort already exists at {root}")
    checks = verify()
    if not checks["ok"]:
        raise SystemExit("Release gate failed:\n" + json.dumps(checks, indent=2))
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": COHORT_SCHEMA, "created_at": now(), "updated_at": now(),
        "target_games": games, "seed_start": seed_start, "max_rounds": max_rounds,
        "learning_enabled":learning_enabled,
        "active_game": 1, "baseline": "data/decks/reaminatour.txt",
        **({'combat_blocker_batch':2,'combat_damage_batch':1,'proliferate_batch_after':0,'selection_batch_after':0} if decision_surface_revision>=6 else {}),
        "decision_surface_revision": _validate_decision_surface_revision(decision_surface_revision),
        "cohort_state": "active",
        "planning_runtime":{"contract":planning_contract,"effective_from_game":1,"stages":planner_stages,"tiers":bool(planner_stages and plan_tiers),"context_handling":1 if planning_contract==4 else 0,**architecture_flags},
        "method": "external pilot -> deterministic replay/referee -> redacted checkpoint -> continue",
        "games": {},
    }
    _ensure_cohort_seed_gameplan_snapshot(root, manifest, effective_from_game=1)
    _ensure_cohort_messaging_personality_snapshot(root, manifest, effective_from_game=1)
    write_json(root / "release_gate.json", checks)
    return advance(root, 1)


def print_status(status: Dict[str, Any]) -> None:
    handoff=(status.get('request') or {}).get('pilot_handoff')
    if handoff and not status.get('gameplan_activity'):
        request=status['request']
        print(f"Game {status['game']:02d} | {status['state']} | {request['decision_id']} | dispatch {request['actor']}")
        print('Isolated seat pilot brief: '+handoff['brief'])
        print('Follow NEXT_ACTION.json; private gameplay content is in the seat handoff.')
        return
    personality_refresh = status.get("messaging_personality_refresh") or {}
    if personality_refresh:
        print("Refreshed messaging personalities for future table-talk decisions.")
        print("Audit:", personality_refresh.get("audit"))
    activity=status.get("gameplan_activity") or {}
    if activity:
        if handoff:print('Current seat handoff: '+handoff['brief'])
        verb="Updated" if activity.get("mode")=="append" else "Reviewed"
        print(f"{verb} private gameplan for {activity.get('pilot')}:")
        entries=activity.get("entries") or []
        if entries:
            for entry in entries:
                scope=normalize_plan_scope(entry.get("scope")).replace('_','-')
                print(f"  {entry.get('entry_id')} [{scope}]: {entry.get('text','')}")
                review=entry.get(DRAW_PLANNING_REVIEW_FIELD) or {}
                if review and scope=="short-term":
                    print(
                        f"    Long-term {str(review.get('long_term_action','')).upper()}: "
                        f"{review.get('long_term_rationale') or '(no rationale recorded)'}"
                    )
        else:print("  (no entries)")
        print("Returning to the unchanged pending decision.")
    pass_on_activity=status.get("pass_on_activity") or {}
    if pass_on_activity:
        verb={
            "review":"Reviewed","unsnooze":"Unsnoozed",
            "unsnooze_all":"Unsnoozed all","reschedule":"Rescheduled",
        }.get(pass_on_activity.get("mode"),"Managed")
        print(f"{verb} private PASS ON entries for {pass_on_activity.get('pilot')}:")
        entries=pass_on_activity.get("entries") or []
        if entries:
            for entry in entries:
                print(
                    f"  {entry.get('source_name')} [{entry.get('source_uid')}] "
                    f"({entry.get('source_zone')}): {entry.get('wake_description')}"
                )
        else:print("  (no live PASS ON entries)")
        print("Returning to the unchanged pending gameplay decision.")
    request = status.get("request")
    print(f"Game {status['game']:02d} | seed {status['seed']} | {status['state']} | accepted decisions {status['decision_count']}")
    if request:
        print(f"{request['decision_id']} | {request['actor']} | {request['kind']}")
        context=_decision_context(status)
        active=context.get("active_player") or "unknown"
        actor=context.get("acting_pilot") or "unknown"
        active_note=" (active player)" if active==actor else ""
        print(
            f"TIMING | round {context.get('round')} | turn {context.get('turn')} | "
            f"whose turn: {active} | acting pilot: {actor}{active_note} | "
            f"phase/step: {context.get('phase') or 'unknown'}"
        )
        print("WINDOW / TRANSITION | "+str(context.get("window") or "unspecified"))
        if request.get('turn_order'):
            order=request['turn_order']
            print('TURN ORDER | '+' → '.join(order['seating'])+' → repeat | next turn: '+str(order['next_player']))
        stack=context["stack_top_first"]
        if stack:
            print(f"STACK | {len(stack)} object(s), top first")
            for index,value in enumerate(stack,1):
                marker="TOP — " if index==1 else ""
                print(f"  {index}. {marker}{_stack_object_summary(value)}")
        else:
            print("STACK | empty")
        print(request["prompt"])
        if request.get("response_type"):
            print("  " + request.get("response_help", "Enter the requested value."))
            if request['response_type'] in {'block_declaration','combat_damage'}:
                print(json.dumps(request[request['response_type']],ensure_ascii=False,separators=(',',':')))
                for label in request['options']:print('  '+label)
        else:
            for index, label in enumerate(request["options"], 1):
                print(f"  {index}. {label}")
            if request["allow_pass"]:
                print("  0. PASS")
        if request.get('multi_select'):
            print("  Select option numbers in one comma-separated answer (for example: 1,3,4); preserve the requested order.")
        batch=request.get('pass_on_batch') or {}
        if batch.get('schema')==1:
            print('  PASS ON BATCH. Choose its option and repeat --pass-on "UID=SCHEDULE".')
            for source in batch.get('sources',[]):
                print(f"    {source.get('name')} [{source.get('uid')}] ({source.get('zone')})")
        if (request.get('autoresolve') or {}).get('schema')==1:
            print('  AUTORESOLVE. An eligible spell choice may include --autoresolve.')
        if (request.get('seat_snooze') or {}).get('available'):
            print('  SNOOZE ALL. With PASS, use --snooze-all [--until "SCHEDULE"].')
        inspection_help=request.get("inspection_help")
        if inspection_help:
            print("  INSPECT. "+str(inspection_help))
        private_gameplan=request.get("private_gameplan_context") or {}
        if private_gameplan:
            seed=private_gameplan.get("seed") or {}
            if private_gameplan.get("delivery")=="mandatory_main_phase_review":
                print("PRIVATE GAMEPLAN CONTEXT (mandatory main-phase seed review)")
            elif private_gameplan.get("delivery")=="draw_planning_checkpoint":
                print("PRIVATE GAMEPLAN CONTEXT (first-draw planning checkpoint)")
            elif private_gameplan.get("read_is_automatic"):
                print("PRIVATE GAMEPLAN CONTEXT (one-time opening delivery)")
            else:
                print("PRIVATE GAMEPLAN CONTEXT (returned for this private query only)")
            print("  Seed:")
            seed_text=str(seed.get("text") or "")
            if seed_text:
                for line in seed_text.split("\n"):print("    "+line)
            else:print("    (empty seed plan)")
            notes=private_gameplan.get("dynamic_notes") or []
            print(f"  Dynamic notes visible on this branch: {len(notes)}")
            for entry in notes:
                scope=normalize_plan_scope(entry.get("scope")).replace('_','-')
                print(f"    {entry.get('entry_id','note')} [{scope}]: {entry.get('text','')}")
                review=entry.get(DRAW_PLANNING_REVIEW_FIELD) or {}
                if review and scope=="short-term":
                    print(
                        f"      Long-term {str(review.get('long_term_action','')).upper()}: "
                        f"{review.get('long_term_rationale') or '(no rationale recorded)'}"
                    )
        previous=request.get("previous_pilot_decision") or {}
        if previous:
            print("PRIVATE PILOT CONTINUITY (full latest accepted decision item)")
            for line in _previous_pilot_decision_markdown(previous)[4:]:print("  "+line)
        rationalized=request.get("previous_rationalized_decision") or {}
        if rationalized and rationalized.get("decision_id")!=previous.get("decision_id"):
            print("PRIVATE PRIOR RATIONALIZED DECISION (full accepted item)")
            for line in _previous_pilot_decision_markdown(rationalized)[4:]:print("  "+line)
        private_active_plan=request.get("private_active_plan") or {}
        if private_active_plan:
            print("PRIVATE ACTIVE PLAN (automatically loaded; derived, bounded)")
            for line in str(private_active_plan.get("text") or "").split("\n"):
                print("  "+line)
            if (private_active_plan.get("update_recommended") and
                    private_active_plan.get("update_guidance")):
                print("  PLAN CHECKPOINT. "+str(private_active_plan["update_guidance"]))
        pilot_memory=request.get("pilot_memory") or []
        if pilot_memory:
            print("PRIVATE RELEVANT STRATEGY NOTES")
            for note in pilot_memory:
                print(f"  {note.get('card_name','Card')}: {note.get('text','')}")
        private_personality=request.get("private_messaging_personality") or {}
        if private_personality:
            reasons=", ".join(private_personality.get("activation_reasons") or ["messageboard"])
            print(f"PRIVATE PILOT PERSONALITY (automatically loaded for {reasons})")
            personality_text=str(private_personality.get("text") or "")
            if personality_text:
                for line in personality_text.split("\n"):print("  "+line)
            else:print("  (empty messaging personality)")
        gameplan_meta=request.get("gameplan") or {}
        if gameplan_meta:
            print(
                f"  {gameplan_meta.get('choice',GAMEPLAN_CHOICE)}. Private gameplan "
                f"({gameplan_meta.get('entry_count',0)} entries). "
                f"{gameplan_meta.get('help','Review or update the private gameplan without consuming this decision.')}"
            )
        rationale_policy=request.get("rationale_policy") or {}
        if rationale_policy:
            print(
                f"  RATIONALE {str(rationale_policy.get('mode','optional')).upper()}: "
                f"{rationale_policy.get('help','')}"
            )
        planning=request.get(PLANNING_CHECKPOINT_FIELD) or {}
        if planning.get("required"):
            if planning.get("opening_long_term_plan_required"):
                print(
                    "  FIRST-OWN-TURN PLANNING REQUIRED: --short-term-plan, "
                    "--long-term-action revise, --long-term-rationale, and "
                    "--long-term-plan naming a posture toward every opponent."
                )
            else:
                print(
                    "  PLANNING REQUIRED IN THIS ANSWER: --short-term-plan, "
                    "--long-term-action keep|revise, --long-term-rationale, and when "
                    "revising --long-term-plan."
                )
        messageboard=request.get("messageboard") or {}
        if messageboard.get("available") and request.get("kind")=="main_action":
            if messageboard.get("opening_salutation_required"):
                print(
                    "  OPENING TABLE TALK REQUIRED: choose TABLE TALK, use "
                    "--message-address generic, and supply a characteristic but "
                    "strategically unrevealing --message-text."
                )
            else:
                print(
                    "  TABLE TALK BATCH: choose TABLE TALK and supply --message-address "
                    "generic|all|pilot plus --message-text; pilot also needs --message-recipient."
                )
        if request.get("kind")=="messageboard_response":
            print("  MESSAGE RESPONSE: choose RESPOND with --message-text, or PASS.")
        pass_on_meta=request.get("pass_on_management") or {}
        if pass_on_meta:
            print(
                f"  {pass_on_meta.get('choice',PASS_ON_MANAGEMENT_CHOICE)}. Private PASS ON manager "
                f"({pass_on_meta.get('entry_count',0)} entries); use pass-ons to review, "
                "--unsnooze UID, --unsnooze-all, or --reschedule UID --wake SCHEDULE. "
                "The gameplay decision remains open."
            )
    adjudication=status.get("combo_adjudication") or {}
    if adjudication:
        print(f"Combo proposal {adjudication.get('proposal_id')} awaits rules adjudication.")
        print(adjudication.get("proposal", ""))
        print("Edit combo_adjudication_response.json, then run adjudicate-combo --response with that path.")
    if status.get("error"):
        print("RELEASE BLOCKER:", status["error"])
    if status.get("result"):
        print(json.dumps(status["result"], indent=2))
    review = status.get("postgame_review") or {}
    if status.get("state") == "complete" and review.get("state") == "rules_blocker":
        print("POST-GAME RULES BLOCKER; record the repair and regenerate the tagged draw review.")
        print(review.get("blocker_summary", "Follow NEXT_ACTION.json."))
    elif status.get("state") == "complete" and review.get("state") == "pending":
        print("POST-GAME REVIEW REQUIRED; cohort advancement is blocked.")
        print("Review instructions:", review.get("instructions"))
        print("Learning patch:", review.get("learning_patch"))
    elif status.get("state") == "complete" and review.get("state") in REVIEW_RESOLVED_STATES:
        print("Post-game review:", review.get("state"))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Manual-pilot EDH gauntlet checkpoint runner")
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    sub = parser.add_subparsers(dest="command", required=True)
    init_parser = sub.add_parser("init", help="create and release-gate a fresh cohort")
    init_parser.add_argument("--games", type=int, default=20)
    init_parser.add_argument("--seed-start", type=int, default=2026090101)
    init_parser.add_argument("--max-rounds", type=int, default=16)
    init_parser.add_argument('--learning',choices=['enabled','disabled'],default='enabled',help='Bind post-game learning at run initialization; disabled runs preserve results without review inference or strategy writes.')
    init_parser.add_argument('--planner-publication',choices=['staged','single'],default='staged')
    init_parser.add_argument('--agent-architecture',action='store_true',help='Bind split long/short planners to this fresh cohort.')
    init_parser.add_argument('--async-diplomacy',action='store_true',help='Bind authorized background diplomacy; requires --agent-architecture.')
    init_parser.add_argument('--planning-contract',type=int,choices=[1,2,3,4],default=4,
                             help='4: approved sequences with event-driven planners; 3: event-driven planners; 2: draw-cadence planners; 1: legacy pilot planning')
    advance_parser = sub.add_parser("advance", help="deterministically replay to the next decision")
    advance_parser.add_argument("--game", type=int)
    draw_parser = sub.add_parser("adjudicate-draw", help="seal the active game as an externally adjudicated draw")
    draw_parser.add_argument("--game", type=int)
    draw_parser.add_argument("--reason", required=True)
    answer_parser = sub.add_parser("answer", help="atomically accept one external decision and reconcile")
    answer_parser.add_argument("choice", help="one-based option; comma-separated for multi-select; 0 passes; PASS ON schedules also accept e.g. '2 end of combat'; GAMEPLAN and MANAGE PASS-ONS are auxiliary")
    answer_parser.add_argument("--rationale", default="")
    scheduler_flags=answer_parser.add_mutually_exclusive_group()
    scheduler_flags.add_argument('--hold_full_control',action='store_true')
    scheduler_flags.add_argument('--snooze_stack','-snooze_stack',action='store_true',help=argparse.SUPPRESS)
    scheduler_flags.add_argument('--resolve_my_sequence',action='store_true')
    scheduler_flags.add_argument('--snooze_table',metavar='JSON')
    scheduler_flags.add_argument('--snooze_objects',metavar='JSON')
    answer_parser.add_argument('--pilot-context',help='current seat-specific handoff identity')
    answer_parser.add_argument(
        "--plan-delta",
        help="optional private strategy update committed with a successful gameplay answer",
    )
    answer_parser.add_argument(
        "--plan-scope", choices=("short-term", "long-term"), default="short-term",
        help="scope for --plan-delta (default: short-term)",
    )
    answer_parser.add_argument(
        "--short-term-plan",
        help="complete short-term replacement required by a first-draw planning checkpoint",
    )
    answer_parser.add_argument(
        "--long-term-action", choices=("keep","revise"),
        help="long-term KEEP/REVISE decision required by a planning checkpoint",
    )
    answer_parser.add_argument(
        "--long-term-rationale",
        help="private rationale for the planning checkpoint's long-term decision",
    )
    answer_parser.add_argument(
        "--long-term-plan",
        help="complete replacement required when --long-term-action revise is chosen",
    )
    answer_parser.add_argument(
        "--message-address", choices=("generic","all","pilot"),
        help="batched TABLE TALK address mode",
    )
    answer_parser.add_argument(
        "--message-recipient",
        help="living opponent required only for --message-address pilot",
    )
    answer_parser.add_argument(
        "--message-text",
        help="public TABLE TALK post or prompted response (maximum 300 characters)",
    )
    answer_parser.add_argument(
        "--pass-on", action="append", default=[], metavar="UID=SCHEDULE",
        help=(
            "schedule one eligible object in a PASS ON OBJECTS answer; repeat for "
            "multiple objects, e.g. --pass-on \"UID=2 end of combat\""
        ),
    )
    answer_parser.add_argument(
        "--autoresolve", action="store_true",
        help="autopass the selected spell's stack when it was cast onto an empty stack",
    )
    answer_parser.add_argument(
        "--snooze-all", action="store_true",
        help="with postcombat-main PASS, skip optional prompts until the selected deadline",
    )
    answer_parser.add_argument(
        "--until", dest="snooze_until",
        help="SNOOZE ALL wake boundary, e.g. \"2 beginning of upkeep\"",
    )
    answer_parser.add_argument("--game", type=int)
    gameplan_parser=sub.add_parser('gameplan',help='review or append the pending pilot\'s private gameplan without consuming its decision')
    gameplan_parser.add_argument('--write',help='append one private note; omit to review')
    gameplan_parser.add_argument(
        '--scope',choices=('short-term','long-term'),default='short-term',
        help='scope for --write (default: short-term)')
    gameplan_parser.add_argument('--game',type=int)
    personality_parser = sub.add_parser(
        'refresh-messaging-personalities',
        help='explicitly refresh table-talk profiles for the active unfinished game',
    )
    personality_parser.add_argument('--game', type=int)
    pass_ons_parser=sub.add_parser(
        'pass-ons',help='review or replayably manage the pending pilot\'s private PASS ON entries')
    pass_ons_group=pass_ons_parser.add_mutually_exclusive_group()
    pass_ons_group.add_argument('--unsnooze',metavar='UID',help='unsnooze one exact live object')
    pass_ons_group.add_argument('--unsnooze-all',action='store_true',help='unsnooze every listed object')
    pass_ons_group.add_argument('--reschedule',metavar='UID',help='replace one object\'s wake boundary')
    pass_ons_parser.add_argument('--wake',help='new schedule, for example "2 end of combat"')
    pass_ons_parser.add_argument('--game',type=int)
    combo_parser=sub.add_parser('adjudicate-combo',help='validate and atomically apply a rules-agent combo verdict')
    combo_parser.add_argument('--response',type=Path,required=True)
    combo_parser.add_argument('--game',type=int)
    rewind_parser = sub.add_parser("rewind", help="reject a decision and discard it plus all later choices")
    rewind_parser.add_argument("decision_id")
    rewind_parser.add_argument("--reason", required=True)
    rewind_parser.add_argument("--game", type=int)
    migrate_parser=sub.add_parser('migrate-attacks',help='collapse legacy sequential attacker tape rows into atomic batches')
    migrate_parser.add_argument('--game',type=int)
    status_parser = sub.add_parser("status", help="show the current redacted checkpoint")
    status_parser.add_argument("--game", type=int)
    inspect_parser=sub.add_parser('inspect',help='inspect a visible object or the active pilot\'s known deck without advancing')
    inspect_parser.add_argument('query',nargs='+',help='for example: object UID; deck; roles; role removal; package NAME')
    inspect_parser.add_argument('--game',type=int)
    inspect_parser.add_argument('--actor',help='required only when inspecting a completed game')
    learn_parser=sub.add_parser('learn',help='apply a reviewed post-game strategy patch to the global profile')
    learn_parser.add_argument('--game',type=int,required=True)
    learn_parser.add_argument('--patch',type=Path,required=True)
    review_parser=sub.add_parser('review',help='show the blocking post-game review turn')
    review_parser.add_argument('--game',type=int)
    refresh_review_parser=sub.add_parser(
        'refresh-review-evidence',
        help='migrate a terminal pending review to bounded cardwise evidence')
    refresh_review_parser.add_argument('--game',type=int)
    refresh_review_parser.add_argument('--reason',required=True)
    cancel_parser=sub.add_parser(
        'cancel',help='terminate the cohort without deleting its preserved artifacts')
    cancel_parser.add_argument('--reason',required=True)
    reinitialize_parser=sub.add_parser(
        'reinitialize',
        help='release-gate and resume an explicitly cancelled cohort from its preserved boundary')
    reinitialize_parser.add_argument('--reason',required=True)
    quarantine_parser=sub.add_parser(
        'quarantine',help='tag rules-affected games and create repair work items')
    quarantine_parser.add_argument('--games',required=True,help='comma-separated game numbers')
    quarantine_parser.add_argument('--reason',required=True)
    quarantine_parser.add_argument(
        '--severity',choices=sorted(quarantine.SEVERITIES),default='recoverable')
    repair_rules_parser=sub.add_parser(
        'repair-rules',help='record the engine repair for tagged rules work items')
    repair_rules_parser.add_argument('--game',type=int)
    repair_rules_parser.add_argument('--issue')
    repair_rules_parser.add_argument('--summary',required=True)
    rules_review_parser=sub.add_parser('review-quarantine',help='apply an independent rules audit of quarantined learning')
    rules_review_parser.add_argument('--response',required=True,type=Path)
    sub.add_parser('recover-quarantine',help='finish an interrupted quarantine bank transaction')
    sub.add_parser('next',help='show the cohort\'s one authoritative next action')
    sub.add_parser("verify", help="run static release gates")
    args = parser.parse_args(argv)
    root = args.cohort.resolve()
    with locked(root):
        return _dispatch_cli(root,args)


def _dispatch_cli(root,args):
    if args.command == "init":
        status = init(root, args.games, args.seed_start, args.max_rounds,planning_contract=args.planning_contract,planner_stages=args.planning_contract==4 and args.planner_publication=='staged',agent_architecture=args.agent_architecture,async_diplomacy=args.async_diplomacy,learning_enabled=args.learning=='enabled')
    elif args.command == "advance":
        status = advance(root, args.game)
    elif args.command == "adjudicate-draw":
        status = adjudicate_draw(root, args.game, args.reason)
    elif args.command == "answer":
        status = answer(
            root,args.choice,args.rationale,args.game,plan_delta=args.plan_delta,
            plan_scope=args.plan_scope,short_term_plan=args.short_term_plan,
            long_term_action=args.long_term_action,
            long_term_rationale=args.long_term_rationale,
            long_term_plan=args.long_term_plan,
            message_address=args.message_address,
            message_recipient=args.message_recipient,
            message_text=args.message_text,
            pass_on_entries=args.pass_on,
            autoresolve=args.autoresolve,
            hold_full_control=args.hold_full_control,snooze_stack=args.snooze_stack,
            resolve_my_sequence=args.resolve_my_sequence,
            snooze_table=args.snooze_table,snooze_objects=args.snooze_objects,
            pilot_context=args.pilot_context,
            snooze_all=args.snooze_all,
            snooze_until=args.snooze_until)
    elif args.command == 'gameplan':
        status=gameplan(root,args.write,args.game,scope=args.scope)
    elif args.command == 'refresh-messaging-personalities':
        status=refresh_messaging_personalities(root,args.game)
    elif args.command == 'pass-ons':
        status=pass_ons(
            root,unsnooze=args.unsnooze,unsnooze_all=args.unsnooze_all,
            reschedule=args.reschedule,wake=args.wake,game_number=args.game)
    elif args.command == 'adjudicate-combo':
        status=adjudicate_combo(root,args.response,args.game)
    elif args.command == "rewind":
        status = rewind(root, args.decision_id, args.reason, args.game)
    elif args.command == 'migrate-attacks':
        status=migrate_legacy_attack_batches(root,args.game)
    elif args.command == "status":
        status = reconcile_status(root,args.game)
    elif args.command == 'inspect':
        result=inspect_current(root,'inspect '+' '.join(args.query),args.game,args.actor)
        print(result['text'])
        return 0
    elif args.command == 'learn':
        audit=learn(root,args.game,args.patch)
        print(json.dumps(audit,indent=2,ensure_ascii=False))
        return 0
    elif args.command == 'review':
        print(review_current(root,args.game),end='')
        return 0
    elif args.command == 'refresh-review-evidence':
        status=refresh_review_evidence(root,args.reason,args.game)
    elif args.command == 'cancel':
        status=cancel(root,args.reason)
    elif args.command == 'reinitialize':
        status=reinitialize(root,args.reason)
    elif args.command == 'quarantine':
        _require_no_prepared_learning_transaction(root,'quarantine learning')
        try:
            numbers=[int(value) for value in args.games.split(',')]
            entries=quarantine.quarantine_games(
                DEFAULT_STRATEGY_FILE,root,numbers,args.reason,args.severity)
        except ValueError as exc:raise SystemExit(str(exc)) from exc
        manifest=load_manifest(root);number=int(manifest['active_game'])
        status_path=game_dir(root,number)/'status.json'
        status=read_json(status_path) if status_path.exists() else {'game':number,'state':'not_started'}
        if (number in numbers and status.get('state')=='complete' and
                (status.get('postgame_review') or {}).get('state') in REVIEW_LOCKED_STATES):
            directory=game_dir(root,number)
            _invalidate_unresolved_terminal_review(root,manifest,directory,number)
            for checkpoint in (directory/'checkpoints').glob('*.json'):
                if read_json(checkpoint).get('state')=='complete':checkpoint.unlink()
            manifest['cohort_state']='active';manifest['updated_at']=now()
            write_json(root/'cohort.json',manifest)
            if args.severity=='game_breaking':
                status=_adjudicate_rules_blocker_draw(root,number,args.reason)
            else:status=advance(root,number)
        elif number in numbers and status.get('state') not in {'complete','cancelled'}:
            if args.severity=='game_breaking':
                status=_adjudicate_rules_blocker_draw(root,number,args.reason)
            else:
                status=advance(root,number)
        else:_write_next_action(root,manifest,status)
        print(json.dumps(entries,indent=2));return 0
    elif args.command == 'repair-rules':
        status=repair_rules_work_items(root,args.summary,args.game,args.issue)
    elif args.command == 'review-quarantine':
        _require_no_prepared_learning_transaction(root,'review quarantined learning')
        try:result=quarantine.resolve_learning(DEFAULT_STRATEGY_FILE,read_json(args.response))
        except ValueError as exc:raise SystemExit(str(exc)) from exc
        print(json.dumps(result,indent=2));return 0
    elif args.command == 'recover-quarantine':
        quarantine.recover(DEFAULT_STRATEGY_FILE)
        return 0
    elif args.command == 'next':
        print(json.dumps(next_action(root),indent=2,ensure_ascii=False))
        return 0
    else:
        checks = verify()
        print(json.dumps(checks, indent=2))
        return 0 if checks["ok"] else 1
    print_status(status)
    return 0
