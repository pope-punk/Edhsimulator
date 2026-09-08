"""Bounded private projections of frozen and branch-visible pilot strategy.

The active plan is deliberately not a third strategy store.  It is rebuilt for
each eligible request from the immutable seed snapshot plus the dynamic journal
entries visible on that decision-tape branch.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any, Dict, Iterable, Mapping


ACTIVE_PLAN_SCHEMA = 2
ACTIVE_PLAN_MAX_CHARS = 3700
PLAN_DELTA_MAX_CHARS = 1200
# Leave enough room for the longest valid update plus its generated entry label.
# A smaller cap made a perfectly legal newest delta impossible to deliver while
# allowing an older, shorter note to masquerade as the current adjustment.
ACTIVE_PLAN_SCOPE_MAX_CHARS = PLAN_DELTA_MAX_CHARS + 100
ACTIVE_PLAN_DYNAMIC_MAX_CHARS = ACTIVE_PLAN_SCOPE_MAX_CHARS * 2
PLAN_SCOPES = {"short_term", "long_term"}
DEFAULT_PLAN_SCOPE = "short_term"
OPENING_OPPONENT_KNOWLEDGE_QUALIFIER = "strategy unknown beyond public information"

PLAN_ROLE_GUIDANCE = {
    "standing": (
        "Standing Plan is immutable, reusable doctrine for how to pilot this deck. "
        "It supplies deck knowledge and decision principles, not the objective for this match."
    ),
    "long_term": (
        "Long-Term Plan is the current match-specific goal: name the primary win route or "
        "development objective, the posture toward each opponent, plausible future branches, "
        "and observable cues that would cause a pivot."
    ),
    "short_term": (
        "Short-Term Plan is the executable bridge to the Long-Term Plan. Synthesize current "
        "game status, relevant inspections, and recent rationale into direct next-step "
        "instructions, including sequencing, priority and trigger timing, attacks, blocks, "
        "targets, held interaction, and hazards that matter now."
    ),
}


def planning_checkpoint_help(*, opening_long_term_required: bool = False) -> str:
    """Return the canonical pilot-facing contract for a batched plan review."""
    action=(
        "This is your first own turn: REVISE is mandatory and the replacement Long-Term "
        "Plan must identify every opponent's current posture. For each opponent, use the "
        f"exact qualifier '{OPENING_OPPONENT_KNOWLEDGE_QUALIFIER}' and base any added "
        "posture only on this pilot's actor-visible request and public game history. Other "
        "pilots' private seeds, hands, inspections, gameplans, and decklists are forbidden."
        if opening_long_term_required else
        "KEEP the Long-Term Plan only if its match goal, political posture, alternatives, "
        "and pivot cues remain accurate; otherwise REVISE it completely."
    )
    return (
        PLAN_ROLE_GUIDANCE["standing"]+" "+PLAN_ROLE_GUIDANCE["long_term"]+" "+
        PLAN_ROLE_GUIDANCE["short_term"]+" "+action+" Submit the complete Short-Term "
        "replacement, the Long-Term KEEP/REVISE decision and private rationale, and—when "
        "revising—the complete replacement Long-Term Plan with the gameplay answer."
    )

_COMPACT_STANDING_PLAN_HEADING = re.compile(
    r"(?im)^\s*(?:current\s+game\s+plan|standing\s+plan\s+summary)"
    r"(?:\s*\([^\n]*\))?\s*:\s*$"
)
_STANDING_PLAN_HEADING = re.compile(
    r"(?im)^\s*standing\s+plan\s+[—-]\s+how\s+to\s+play\s+this\s+deck\s*:\s*$"
)
_DECK_OVERVIEW_HEADING = re.compile(r"(?im)^\s*deck\s+overview\s*:\s*$")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_WORDS = re.compile(r"[a-z0-9][a-z0-9'’+-]{2,}", re.IGNORECASE)
_STOP_WORDS = {
    "about", "after", "again", "against", "also", "another", "before",
    "being", "between", "card", "cards", "choose", "could", "from",
    "have", "into", "only", "other", "player", "should", "that", "their",
    "there", "these", "this", "those", "through", "turn", "using", "with",
    "your",
}


def normalize_plan_delta(value: Any) -> str:
    """Validate a private inline strategy update without silently truncating it."""

    text = unicodedata.normalize(
        "NFC", str(value).replace("\r\n", "\n").replace("\r", "\n")
    ).strip()
    if not text:
        raise ValueError("A plan delta cannot be empty")
    if any(
        unicodedata.category(character) == "Cc" and character not in "\n\t"
        for character in text
    ):
        raise ValueError("A plan delta cannot contain control characters")
    if len(text) > PLAN_DELTA_MAX_CHARS:
        raise ValueError(
            f"A plan delta may not exceed {PLAN_DELTA_MAX_CHARS} characters "
            f"(received {len(text)})"
        )
    return text


def normalize_plan_scope(value: Any) -> str:
    """Return the canonical scope for a private dynamic strategy update."""

    scope = str(value or DEFAULT_PLAN_SCOPE).strip().casefold().replace("-", "_")
    if scope not in PLAN_SCOPES:
        raise ValueError("Plan scope must be short-term or long-term")
    return scope


def is_strategic_request(request: Mapping[str, Any]) -> bool:
    """Return whether a request merits automatic private strategic context.

    Typed scheduling input is mechanical.  Other requests are strategic when
    they expose a choice, permit declining, or are one of the broad decisions
    where a single currently-legal option can still carry strategic meaning.
    """

    kind = str(request.get("kind") or "")
    if not kind or kind == "pass_on_schedule":
        return False
    options = request.get("options")
    option_count = len(options) if isinstance(options, list) else 0
    return bool(
        option_count > 1
        or request.get("allow_pass")
        or request.get("gameplan_access")
        or kind in {
            "mulligan", "london_bottom", "main_action", "priority_action",
            "messageboard_compose", "messageboard_response", "combo_attempt",
            "combo_consent", "combo_response", "attack_batch", "combat_target",
            "block_decision", "cleanup_discard", "land_play", "tutor",
        }
    )


def delivery_reason(request: Mapping[str, Any]) -> str:
    """Classify why private strategy is being delivered.

    These values are deliberately declarative.  A future scheduler can decide
    when they become due without coupling the projector to today's turn loop.
    """

    kind = str(request.get("kind") or "")
    planning = request.get("planning_checkpoint") or {}
    if isinstance(planning, Mapping) and planning.get("required"):
        return "first_draw_planning_checkpoint"
    mandatory_review = request.get("mandatory_long_term_plan_update") or {}
    if isinstance(mandatory_review, Mapping) and mandatory_review.get("required"):
        return "main_phase_seed_review"
    if kind in {"mulligan", "london_bottom"} or request.get(
        "opening_gameplan_context"
    ):
        return "opening"
    if kind == "main_action":
        messageboard = request.get("messageboard") or {}
        return "turn_anchor" if messageboard.get("available") else "main_action"
    if kind in {"messageboard_compose", "messageboard_response"}:
        return "politics"
    if kind.startswith("combo_") or kind == "combo_attempt":
        return "combo"
    if "priority" in kind or kind.endswith("_response"):
        return "priority_response"
    if kind in {"attack_batch", "combat_target", "block_decision"}:
        return "combat"
    return "material_decision"


def _terms(value: Any) -> set[str]:
    return {
        word.casefold().replace("’", "'")
        for word in _WORDS.findall(str(value or ""))
        if word.casefold() not in _STOP_WORDS
    }


def _seed_sentences(text: str) -> list[str]:
    parts = _COMPACT_STANDING_PLAN_HEADING.split(str(text or ""), maxsplit=1)
    # Seed authors may provide a deliberately compact always-on section after
    # the marker.  Prefer it; otherwise extract deterministically from the full
    # standing plan for legacy/current seeds whose section is empty.
    compact = parts[1].strip() if len(parts) == 2 and parts[1].strip() else ""
    standing_parts=_STANDING_PLAN_HEADING.split(parts[0],maxsplit=1)
    authored=""
    if len(standing_parts)==2:
        authored=_DECK_OVERVIEW_HEADING.split(standing_parts[1],maxsplit=1)[0].strip()
    standing="\n".join(value for value in (authored,compact) if value).strip() or parts[0]
    lines = []
    for line in standing.splitlines():
        stripped = line.strip()
        if not stripped or stripped.casefold() == "deck overview:":
            continue
        lines.append(stripped)
    units = []
    for line in lines:
        # Authored compact sections use one Markdown bullet per standing rule.
        # Keep those boundaries readable; prose-only legacy seeds still split
        # deterministically at sentence boundaries for relevance scoring.
        if line.startswith(("- ", "* ")):
            units.append(line)
        else:
            units.extend(
                part.strip()
                for part in _SENTENCE_BOUNDARY.split(line)
                if part.strip()
            )
    return units


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 1:
        return "…"[:limit]
    return value[: limit - 1].rstrip() + "…"


def _request_terms(request: Mapping[str, Any]) -> set[str]:
    values = [request.get("kind"), request.get("phase"), request.get("prompt")]
    options = request.get("options")
    if isinstance(options, list):
        values.extend(options)
    # The acting pilot's redacted seat view is safe input to its own private
    # projection.  Cap it so scoring work cannot grow with a long transcript.
    values.append(str(request.get("seat_view") or "")[:6000])
    for field in ("previous_pilot_decision","previous_rationalized_decision"):
        continuity = request.get(field) or {}
        if isinstance(continuity, Mapping):
            values.extend((
                continuity.get("kind"),continuity.get("prompt"),
                continuity.get("options"),continuity.get("chosen"),
                continuity.get("choice_value"),continuity.get("rationale"),
            ))
    return _terms(" ".join(str(value or "") for value in values))


def _select_seed_text(seed_text: str, request: Mapping[str, Any], budget: int) -> str:
    sentences = _seed_sentences(seed_text)
    if not sentences or budget <= 0:
        return ""
    request_terms = _request_terms(request)
    ranked = []
    for index, sentence in enumerate(sentences):
        overlap = len(_terms(sentence) & request_terms)
        # Preserve deck identity/opening posture while favoring material that
        # names cards and concepts in the current decision.
        score = overlap * 20 + (8 if index == 0 else 0) + max(0, 4 - index)
        ranked.append((-score, index, sentence))
    chosen = []
    used = 0
    for _negative_score, index, sentence in sorted(ranked):
        separator = 1 if chosen else 0
        if used + separator + len(sentence) <= budget:
            chosen.append((index, sentence));used += separator + len(sentence)
        elif not chosen:
            chosen.append((index, _truncate(sentence, budget)));used = budget
        if used >= budget:
            break
    ordered = [sentence for _index, sentence in sorted(chosen)]
    separator = "\n" if any(
        sentence.startswith(("- ", "* ")) for sentence in ordered
    ) else " "
    return separator.join(ordered)


def _select_dynamic_notes(
    entries: Iterable[Mapping[str, Any]], budget: int
) -> tuple[list[Dict[str, str]], int]:
    visible = list(entries)
    selected: list[Dict[str, str]] = []
    used = 0
    # Latest first is intentional: a newer delta may supersede an older plan.
    for entry in reversed(visible):
        entry_id = str(entry.get("entry_id") or "note")
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        prefix = f"{entry_id}: "
        remaining = budget - used - (1 if selected else 0)
        if remaining <= len(prefix):
            break
        if len(prefix) + len(text) > remaining:
            # A partial update can reverse or obscure its meaning. Report it as
            # omitted and leave the complete entry available through GAMEPLAN.
            # Do not then surface an older note as though it were the latest
            # adjustment; a too-small custom projection fails closed.
            break
        rendered = prefix + text
        selected.append({"entry_id": entry_id, "text": rendered})
        used += len(rendered) + (1 if len(selected) > 1 else 0)
        if entry.get("mode") == "replace":
            break
        if used >= budget:
            break
    return selected, len(visible)


def _scoped_dynamic_notes(
    entries: Iterable[Mapping[str, Any]], budget: int
) -> tuple[Dict[str, list[Dict[str, str]]], Dict[str, int]]:
    grouped = {scope: [] for scope in PLAN_SCOPES}
    for entry in entries:
        scope = normalize_plan_scope(entry.get("scope"))
        grouped[scope].append(entry)
    selected: Dict[str, list[Dict[str, str]]] = {}
    visible_counts: Dict[str, int] = {}
    for scope in ("long_term", "short_term"):
        selected[scope], visible_counts[scope] = _select_dynamic_notes(
            grouped[scope], min(ACTIVE_PLAN_SCOPE_MAX_CHARS, budget)
        )
    return selected, visible_counts


def project_active_plan(
    *,
    actor: str,
    seed: Mapping[str, Any],
    dynamic_entries: Iterable[Mapping[str, Any]],
    request: Mapping[str, Any],
    max_chars: int = ACTIVE_PLAN_MAX_CHARS,
) -> Dict[str, Any]:
    """Build a deterministic, bounded, actor-private decision brief."""

    if max_chars < 400:
        raise ValueError("Active-plan projection budget must be at least 400 characters")
    # The default projection must fit one maximum-size valid update in full.
    # Custom smaller projections remain valid, but fail closed rather than
    # showing stale entries when their newest note does not fit.
    dynamic_budget = min(ACTIVE_PLAN_DYNAMIC_MAX_CHARS, max_chars - 500)
    selected, visible_counts = _scoped_dynamic_notes(dynamic_entries, dynamic_budget)
    long_text = "\n".join(row["text"] for row in selected["long_term"])
    short_text = "\n".join(row["text"] for row in selected["short_term"])
    headings = (
        "Standing Plan — reusable deck-piloting doctrine:\n\n"
        "Long-Term Plan — current match goal (latest first):\n\n"
        "Short-Term Plan — execution instructions (latest first):\n"
    )
    seed_budget = max_chars - len(headings) - len(long_text) - len(short_text)
    standing = _select_seed_text(str(seed.get("text") or ""), request, seed_budget)
    sections = [
        "Standing Plan — reusable deck-piloting doctrine:",
        standing or "(No frozen seed guidance.)",
    ]
    sections += [
        "",
        "Long-Term Plan — current match goal (latest first):",
        long_text or "(No branch-visible Long-Term Plan yet.)",
        "",
        "Short-Term Plan — execution instructions (latest first):",
        short_text or "(No branch-visible Short-Term Plan yet.)",
    ]
    text = _truncate("\n".join(sections), max_chars)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    included_by_scope = {
        scope: [row["entry_id"] for row in selected[scope]]
        for scope in ("long_term", "short_term")
    }
    included_ids = included_by_scope["long_term"] + included_by_scope["short_term"]
    visible_count = sum(visible_counts.values())
    reason = delivery_reason(request)
    update_recommended = reason in {
        "opening", "turn_anchor", "combo", "politics", "main_phase_seed_review",
        "first_draw_planning_checkpoint",
    }
    return {
        "schema": ACTIVE_PLAN_SCHEMA,
        "private": True,
        "derived": True,
        "source_of_truth": "frozen_seed_plus_branch_visible_dynamic_journal",
        "actor": actor,
        "text": text,
        "character_count": len(text),
        "max_characters": max_chars,
        "projection_sha256": digest,
        "delivery_reason": reason,
        "update_recommended": update_recommended,
        "update_guidance": (
            planning_checkpoint_help(opening_long_term_required=bool(
                (request.get("planning_checkpoint") or {}).get(
                    "opening_long_term_plan_required"
                )
            ))
            if reason == "first_draw_planning_checkpoint" else
            "Review the complete seed plan supplied with this request and add a private "
            "long-term --plan-delta before resolving this main-phase decision."
            if reason == "main_phase_seed_review" else
            "If this decision changes your objectives, sequencing, threat assessment, "
            "or political commitments, add a private --plan-delta to the gameplay answer."
            if update_recommended else None
        ),
        "sources": {
            "seed_sha256": seed.get("sha256"),
            "seed_snapshot_fingerprint": seed.get("snapshot_fingerprint"),
            "visible_dynamic_entry_count": visible_count,
            "included_dynamic_entry_ids": included_ids,
            "omitted_dynamic_entry_count": max(0, visible_count - len(included_ids)),
            "visible_dynamic_entry_count_by_scope": visible_counts,
            "included_dynamic_entry_ids_by_scope": included_by_scope,
        },
    }


def delivery_telemetry(
    projection: Mapping[str, Any], request: Mapping[str, Any]
) -> Dict[str, Any]:
    """Return body-free delivery telemetry safe for audits and aggregation."""

    sources = projection.get("sources") or {}
    return {
        "schema": 1,
        "event": "active_plan_delivered",
        "actor": projection.get("actor"),
        "decision_id": request.get("decision_id"),
        "request_kind": request.get("kind"),
        "projection_sha256": projection.get("projection_sha256"),
        "character_count": projection.get("character_count"),
        "seed_sha256": sources.get("seed_sha256"),
        "visible_dynamic_entry_count": sources.get("visible_dynamic_entry_count", 0),
        "included_dynamic_entry_ids": list(sources.get("included_dynamic_entry_ids") or []),
        "omitted_dynamic_entry_count": sources.get("omitted_dynamic_entry_count", 0),
        "delivery_reason": projection.get("delivery_reason"),
        "update_recommended": bool(projection.get("update_recommended")),
        "mandatory_long_term_update": bool(
            (request.get("mandatory_long_term_plan_update") or {}).get("required")
        ),
        "planning_checkpoint_due": bool(
            (request.get("planning_checkpoint") or {}).get("required")
        ),
        "full_seed_delivered": (
            (request.get("mandatory_long_term_plan_update") or {}).get("seed_inspection")
            == "full"
            or (request.get("planning_checkpoint") or {}).get("seed_inspection")=="full"
        ),
    }
