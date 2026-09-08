"""Post-game evidence packets for external, non-executable pilot learning.

Python records what occurred and what the pilot chose.  It does not infer strategy,
write advice, or alter role assignments.  A separate post-game pilot turn consumes
these packets and applies an auditable strategy-profile patch.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional

from .event_visibility import event_visibility, public_event_stub
from .strategy import (
    ComboPackage,
    StrategyNote,
    StrategyState,
    StrategyValidationError,
)


CARDWISE_NOTE_GUIDANCE = (
    "Write every cardwise strategy note as self-contained, reusable guidance. "
    "Do not refer to 'this game', a seed, decision ID, turn number, or an "
    "unexplained game-specific sequence in the note text. Keep provenance in "
    "source_game and the learning audit; include card interactions or exact math "
    "only when the note itself supplies enough context to apply them later."
)


class LearningPatchError(StrategyValidationError):
    """Raised when a post-game pilot patch is stale or malformed."""


_OPERATION_FIELDS = {
    "create_role": {"op", "label", "description", "aliases", "parent_role"},
    "retire_role": {"op", "role"},
    "merge_roles": {"op", "source_role", "target_role"},
    "assign_role": {"op", "deck", "card", "role"},
    "unassign_role": {"op", "deck", "card", "role"},
    "add_note": {"op", "deck", "card", "note"},
    "replace_note": {"op", "deck", "card", "note"},
    "upsert_package": {"op", "deck", "package"},
    "retire_package": {"op", "deck", "package"},
}


def _required(operation: Mapping[str, Any], *names: str) -> None:
    missing = [name for name in names if operation.get(name) in (None, "")]
    if missing:
        raise LearningPatchError(
            f"{operation.get('op', 'operation')} is missing: {', '.join(missing)}"
        )


def apply_strategy_patch(
    state: StrategyState,
    patch: Mapping[str, Any],
    *,
    source_game: int,
    source_cohort: Optional[str] = None,
) -> tuple[StrategyState, dict[str, Any]]:
    """Apply an external pilot's inert post-game learning patch.

    The patch language intentionally exposes only the strategy model's descriptive
    mutations. It cannot install rules handlers, alter the catalog, or modify a
    game. A frozen base revision prevents a late review from silently applying to
    a different memory bank than the pilot inspected.
    """

    if not isinstance(patch, Mapping):
        raise LearningPatchError("learning patch must be a JSON object")
    extras = sorted(set(patch) - {
        "schema", "base_revision", "game", "review_id", "terminal_fingerprint",
        "review", "operations",
    })
    if extras:
        raise LearningPatchError(f"unexpected learning patch fields: {', '.join(extras)}")
    if int(patch.get("schema", 1)) != 1:
        raise LearningPatchError("unsupported learning patch schema")
    if int(patch.get("game", source_game)) != source_game:
        raise LearningPatchError("learning patch game does not match the reviewed game")
    review = patch.get("review")
    if review is not None:
        if not isinstance(review, Mapping):
            raise LearningPatchError("learning patch review must be a JSON object")
        review_extras = sorted(
            set(review) - {
                "summary", "evidence_reviewed", "pilot_dispositions", "no_change_reason",
                "pilot_analyses", "rules_issue_synthesis",
            }
        )
        if review_extras:
            raise LearningPatchError(
                f"unexpected learning review fields: {', '.join(review_extras)}"
            )
        if "evidence_reviewed" in review and not isinstance(review["evidence_reviewed"], list):
            raise LearningPatchError("learning review evidence_reviewed must be a list")
        if "pilot_dispositions" in review and not isinstance(review["pilot_dispositions"], Mapping):
            raise LearningPatchError("learning review pilot_dispositions must be a JSON object")
        if "rules_issue_synthesis" in review and not isinstance(review["rules_issue_synthesis"], list):
            raise LearningPatchError("learning review rules_issue_synthesis must be a list")
    frozen_before = state.freeze()
    expected = patch.get("base_revision")
    if expected and str(expected) != frozen_before.revision_id:
        raise LearningPatchError(
            f"stale learning patch: expected {expected}, current {frozen_before.revision_id}"
        )
    operations = patch.get("operations", ())
    if not isinstance(operations, list):
        raise LearningPatchError("learning patch operations must be a list")

    current = state
    applied: list[dict[str, Any]] = []
    for index, raw in enumerate(operations, 1):
        if not isinstance(raw, Mapping):
            raise LearningPatchError(f"operation {index} must be a JSON object")
        operation = dict(raw)
        kind = str(operation.get("op", ""))
        allowed = _OPERATION_FIELDS.get(kind)
        if allowed is None:
            raise LearningPatchError(f"operation {index} has unknown op {kind!r}")
        unexpected = sorted(set(operation) - allowed)
        if unexpected:
            raise LearningPatchError(
                f"operation {index} ({kind}) has unexpected fields: {', '.join(unexpected)}"
            )

        if kind == "create_role":
            _required(operation, "label", "description")
            current = current.create_role(
                str(operation["label"]),
                str(operation["description"]),
                aliases=tuple(operation.get("aliases", ())),
                parent_role=operation.get("parent_role"),
                source="postgame_pilot",
                source_game=source_game,
            )
        elif kind == "retire_role":
            _required(operation, "role")
            current = current.retire_role(
                str(operation["role"]), source="postgame_pilot", source_game=source_game
            )
        elif kind == "merge_roles":
            _required(operation, "source_role", "target_role")
            current = current.merge_roles(
                str(operation["source_role"]),
                str(operation["target_role"]),
                source="postgame_pilot",
                source_game=source_game,
            )
        elif kind == "assign_role":
            _required(operation, "deck", "card", "role")
            current = current.assign_role(
                str(operation["deck"]), str(operation["card"]), str(operation["role"]),
                source="postgame_pilot", source_game=source_game,
            )
        elif kind == "unassign_role":
            _required(operation, "deck", "card", "role")
            current = current.unassign_role(
                str(operation["deck"]), str(operation["card"]), str(operation["role"])
            )
        elif kind in {"add_note", "replace_note"}:
            _required(operation, "deck", "card", "note")
            if not isinstance(operation["note"], Mapping):
                raise LearningPatchError(f"operation {index} note must be a JSON object")
            note_raw = dict(operation["note"])
            if note_raw.get("locked"):
                raise LearningPatchError("post-game patches cannot create or replace locked user notes")
            note_raw.update({"source": "postgame_pilot", "source_game": source_game, "locked": False})
            if source_cohort:
                note_raw.update(source_cohort=source_cohort,source_review=patch.get('review_id'))
            note = StrategyNote.from_dict(note_raw)
            if kind == "add_note":
                current = current.add_note(str(operation["deck"]), str(operation["card"]), note)
            else:
                current = current.replace_note(
                    str(operation["deck"]), str(operation["card"]), note, allow_locked=False
                )
        elif kind == "upsert_package":
            _required(operation, "deck", "package")
            if not isinstance(operation["package"], Mapping):
                raise LearningPatchError(f"operation {index} package must be a JSON object")
            package_raw = dict(operation["package"])
            package_raw.update({"source": "postgame_pilot", "source_game": source_game})
            package = ComboPackage.from_dict(package_raw)
            # Nested notes are pilot-authored too, regardless of supplied provenance.
            package = replace(
                package,
                notes=tuple(
                    replace(note, source="postgame_pilot", source_game=source_game, locked=False,
                            source_cohort=source_cohort,source_review=patch.get('review_id'))
                    for note in package.notes
                ),
            )
            current = current.upsert_package(str(operation["deck"]), package)
        else:
            _required(operation, "deck", "package")
            current = current.retire_package(
                str(operation["deck"]), str(operation["package"])
            )
        applied.append({"index": index, "op": kind, "revision": current.revision})

    frozen_after = current.freeze()
    return current, {
        "schema": 1,
        "applied_at": _now(),
        "source_game": source_game,
        "base_revision": frozen_before.to_dict(),
        "result_revision": frozen_after.to_dict(),
        "operations": applied,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _card_names_for_deck(game: Any, deck: str) -> set[str]:
    player=game.players[deck]
    names={card.d.name for card in player.library+player.hand+player.graveyard+player.exile}
    if player.commander:names.add(player.commander.d.name)
    for owner in game.players.values():
        names.update(permanent.name for permanent in owner.battlefield if permanent.owner==deck and not permanent.token)
    # A physical card may currently be represented only by its copied face/name.
    try:
        from .engine import DECKDEFS
        names.update(card.name for card in DECKDEFS[deck])
    except (ImportError, KeyError):
        pass
    return names


def _known_final_zones(game: Any, deck: str) -> dict[str, list[dict[str, Any]]]:
    player=game.players[deck];zones:dict[str,list[dict[str,Any]]]=defaultdict(list)
    for zone in ("hand","graveyard","exile"):
        for card in getattr(player,zone):zones[zone].append({"uid":card.uid,"card":card.d.name})
    if player.commander:zones["command"].append({"uid":player.commander.uid,"card":player.commander.d.name})
    for controller in game.players.values():
        for permanent in controller.battlefield:
            if permanent.owner!=deck or permanent.token:continue
            identity_visible=True
            visibility_check=getattr(game,"_battlefield_identity_visible_to",None)
            if visibility_check is not None:
                identity_visible=bool(visibility_check(deck,permanent))
            row={
                "uid":permanent.uid,
                "card":permanent.name if identity_visible else "Unknown face-down card",
                "controller":permanent.controller,
                "tapped":permanent.tapped,
            }
            if identity_visible:row["copy_of"]=permanent.copy_of
            else:row["identity_visible"]=False
            zones["battlefield"].append(row)
    # Identities are legitimate deck-accounting knowledge, but their order is not.
    zones["library"]=[{"card":name,"quantity":count} for name,count in
                      sorted(Counter(card.d.name for card in player.library).items())]
    return {zone:rows for zone,rows in sorted(zones.items())}


_EVENT_INTERNAL_FIELDS={"game","seed","state","public_view","visible_to"}
_EVENT_BASE_FIELDS=("seq","round","turn","phase","actor","type")


def _compact_event(event: Mapping[str,Any]) -> dict[str,Any]:
    return {
        key:value for key,value in event.items()
        if key not in _EVENT_INTERNAL_FIELDS
    }


def _event_view(event: Mapping[str,Any], viewer: str) -> Optional[dict[str,Any]]:
    """Project one omniscient event into exactly one pilot's knowledge view."""

    event_type=str(event.get("type", ""))
    visibility=str(event.get("visibility") or event_visibility(event_type))
    if visibility=="public":
        return _compact_event(event)
    if visibility in {"actor","actor_public"}:
        visible_to=event.get("visible_to")
        entitled=(
            viewer==event.get("actor")
            if visible_to is None
            else viewer in set(visible_to)
        )
        if entitled:return _compact_event(event)
        public_view=event.get("public_view")
        if public_view is None and visibility=="actor_public":
            public_view=public_event_stub(event_type,event.get("actor"),event)
        if isinstance(public_view,Mapping):
            projected={key:event.get(key) for key in _EVENT_BASE_FIELDS if key in event}
            projected.update(dict(public_view))
            projected["visibility"]="public_projection"
            return projected
        return None
    # Unknown event types fail closed: retain only chronology and type so the
    # release audit can see that a projection policy is missing.
    projected={key:event.get(key) for key in _EVENT_BASE_FIELDS if key in event}
    projected.update({
        "visibility":"unclassified_redacted",
        "detail":"Event payload redacted pending an explicit visibility policy.",
    })
    return projected


def _public_result(game: Any) -> dict[str,Any]:
    result=dict(game.result())
    result.pop("seed",None)
    return result


def _decision_card_mentions(decision: Mapping[str,Any], card_names: Iterable[str]) -> list[str]:
    text="\n".join([
        str(decision.get("prompt","")),str(decision.get("chosen","")),str(decision.get("rationale","")),
        *map(str,decision.get("options",[])),
    ])
    # Longest first prevents a short name from obscuring a more exact match.
    return [name for name in sorted(card_names,key=lambda value:(-len(value),value)) if name in text]


def build_pilot_evidence(game: Any, viewer: str, strategy_revision: Optional[str]=None) -> dict[str,Any]:
    """Build a knowledge-safe evidence packet for one deck's post-game pilot."""
    card_names=_card_names_for_deck(game,viewer)
    visible_events=[];card_event_counts:dict[str,Counter]=defaultdict(Counter)
    for event in game.events:
        projected=_event_view(event,viewer)
        if projected is None:continue
        visible_events.append(projected)
        name=projected.get("card")
        if event.get("actor")==viewer and name in card_names:
            card_event_counts[name][str(event.get("type"))]+=1
    decisions=[]
    for decision in game.decisions:
        if decision.get("actor")!=viewer:continue
        mentions=_decision_card_mentions(decision,card_names)
        decisions.append({
            "decision_id":decision.get("decision_id"),"round":decision.get("round"),
            "turn":decision.get("turn"),"phase":decision.get("phase"),"kind":decision.get("kind"),
            "prompt":decision.get("prompt"),"options":decision.get("options",[]),
            "chosen":decision.get("chosen"),"rationale":decision.get("rationale",""),
            "cards":mentions,"pilot_memory_ids":decision.get("pilot_memory_ids",[]),
            **({'scheduler':decision['scheduler']} if 'scheduler' in decision else {}),
        })
    return {
        "schema":2,"created_at":_now(),"game":game.game_no,"viewer":viewer,
        "information_scope":"pilot_visible_postgame_evidence",
        "strategy_revision":strategy_revision,
        "result":_public_result(game),
        "final_known_zones":_known_final_zones(game,viewer),
        "card_event_counts":{name:dict(sorted(counts.items())) for name,counts in sorted(card_event_counts.items())},
        "decisions":decisions,"visible_events":visible_events,
    }


def build_postgame_evidence(game: Any, strategy_revision: Optional[str]=None) -> dict[str,Any]:
    """Build one sealed envelope containing a separate packet for each pilot."""
    return {
        "schema":2,"created_at":_now(),"game":game.game_no,
        "strategy_revision":strategy_revision,
        "pilots":{name:build_pilot_evidence(game,name,strategy_revision) for name in game.players},
    }


__all__ = [
    "CARDWISE_NOTE_GUIDANCE",
    "LearningPatchError",
    "apply_strategy_patch",
    "build_pilot_evidence",
    "build_postgame_evidence",
]
