"""Strict schema boundary for externally authored combo adjudications.

The rules adjudicator is intentionally more privileged than a pilot decision,
but its response is not an arbitrary state patch.  This module accepts only the
small, auditable operation vocabulary understood by the referee and binds the
response to the exact proposal request that was reviewed.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


SCHEMA_VERSION = 1
MAX_INTEGER = 10**18
INFINITE = "infinite"
VERDICTS = frozenset({"approved", "rejected", "needs_demonstration"})
KNOWN_PILOTS = (
    "Reaminatour",
    "Minsc & Boo",
    "Omo",
    "Elenda",
)
OPERATION_FIELDS = {
    "damage_player": frozenset({"op", "player", "amount"}),
    "set_life": frozenset({"op", "player", "value"}),
    "bounce_permanents": frozenset({"op", "players", "uids"}),
}

_TOP_LEVEL_FIELDS = frozenset({
    "schema",
    "proposal_id",
    "request_sha256",
    "verdict",
    "rules_basis",
    "public_summary",
    "operations",
})
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class ComboAdjudicationValidationError(ValueError):
    """Raised when an adjudication response is malformed or stale."""


def _error(message: str) -> ComboAdjudicationValidationError:
    return ComboAdjudicationValidationError(message)


def _strict_string(value: Any, field: str, *, strip_text: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(f"{field} must be a nonempty string")
    if strip_text:
        return value.strip()
    if value != value.strip():
        raise _error(f"{field} must not have leading or trailing whitespace")
    return value


def _bounded_integer_or_infinite(
    value: Any,
    field: str,
    *,
    minimum: int,
) -> int | str:
    if value == INFINITE and isinstance(value, str):
        return INFINITE
    # bool is an int subclass and must never be accepted as a game quantity.
    if isinstance(value, bool) or not isinstance(value, int):
        raise _error(f"{field} must be an integer or {INFINITE!r}")
    if value < minimum:
        comparison = "positive" if minimum == 1 else "nonnegative"
        raise _error(f"{field} must be {comparison}")
    if value > MAX_INTEGER:
        raise _error(f"{field} exceeds the maximum supported integer {MAX_INTEGER}")
    return value


def _known_player(value: Any, field: str, pilots: frozenset[str]) -> str:
    player = _strict_string(value, field)
    if player not in pilots:
        raise _error(f"{field} names unknown pilot {player!r}")
    return player


def _validate_operation(
    raw: Any,
    index: int,
    pilots: frozenset[str],
) -> dict[str, Any]:
    prefix = f"operation {index}"
    if not isinstance(raw, Mapping):
        raise _error(f"{prefix} must be an object")
    operation = dict(raw)
    if any(not isinstance(field, str) for field in operation):
        raise _error(f"{prefix} field names must be strings")
    kind = operation.get("op")
    if not isinstance(kind, str) or kind not in OPERATION_FIELDS:
        raise _error(f"{prefix} has unknown op {kind!r}")

    allowed = OPERATION_FIELDS[kind]
    required = allowed if kind != "bounce_permanents" else allowed - {"uids"}
    missing = sorted(required - set(operation))
    unexpected = sorted(set(operation) - allowed)
    if missing:
        raise _error(f"{prefix} ({kind}) is missing fields: {', '.join(missing)}")
    if unexpected:
        raise _error(f"{prefix} ({kind}) has unexpected fields: {', '.join(unexpected)}")

    if kind == "damage_player":
        return {
            "op": kind,
            "player": _known_player(operation["player"], f"{prefix}.player", pilots),
            "amount": _bounded_integer_or_infinite(
                operation["amount"], f"{prefix}.amount", minimum=1
            ),
        }

    if kind == "set_life":
        return {
            "op": kind,
            "player": _known_player(operation["player"], f"{prefix}.player", pilots),
            "value": _bounded_integer_or_infinite(
                operation["value"], f"{prefix}.value", minimum=0
            ),
        }

    players_raw = operation["players"]
    if isinstance(players_raw, str):
        if players_raw not in {"all", "opponents"}:
            raise _error(
                f"{prefix}.players must be 'all', 'opponents', or a nonempty list of known pilots"
            )
        players: str | list[str] = players_raw
    else:
        if (
            not isinstance(players_raw, list)
            or not players_raw
        ):
            raise _error(
                f"{prefix}.players must be 'all', 'opponents', or a nonempty list of known pilots"
            )
        players = [
            _known_player(value, f"{prefix}.players[{position}]", pilots)
            for position, value in enumerate(players_raw)
        ]
        if len(players) != len(set(players)):
            raise _error(f"{prefix}.players contains a duplicate pilot")

    result: dict[str, Any] = {"op": kind, "players": players}
    if "uids" in operation:
        uids_raw = operation["uids"]
        if not isinstance(uids_raw, list):
            raise _error(f"{prefix}.uids must be a list of unique strings")
        uids = [
            _strict_string(value, f"{prefix}.uids[{position}]")
            for position, value in enumerate(uids_raw)
        ]
        if len(uids) != len(set(uids)):
            raise _error(f"{prefix}.uids contains a duplicate UID")
        result["uids"] = uids
    return result


def validate_combo_adjudication_response(
    response: Mapping[str, Any],
    *,
    expected_proposal_id: str | None = None,
    expected_request_sha256: str | None = None,
    known_pilots: Sequence[str] = KNOWN_PILOTS,
) -> dict[str, Any]:
    """Validate and normalize one request-bound combo adjudication response.

    The returned dictionary is a new JSON-compatible value.  ``response`` is
    never mutated.  Optional expected identifiers let the campaign reject a
    syntactically valid response prepared for a different proposal or state.
    """

    if not isinstance(response, Mapping):
        raise _error("combo adjudication response must be an object")
    value = dict(response)
    if any(not isinstance(field, str) for field in value):
        raise _error("combo adjudication response field names must be strings")
    missing = sorted(_TOP_LEVEL_FIELDS - set(value))
    unexpected = sorted(set(value) - _TOP_LEVEL_FIELDS)
    if missing:
        raise _error(f"combo adjudication response is missing fields: {', '.join(missing)}")
    if unexpected:
        raise _error(
            f"combo adjudication response has unexpected fields: {', '.join(unexpected)}"
        )

    schema = value["schema"]
    if isinstance(schema, bool) or not isinstance(schema, int) or schema != SCHEMA_VERSION:
        raise _error(f"unsupported combo adjudication schema {schema!r}")

    proposal_id = _strict_string(value["proposal_id"], "proposal_id")
    request_sha256 = _strict_string(value["request_sha256"], "request_sha256")
    if not _SHA256_RE.fullmatch(request_sha256):
        raise _error("request_sha256 must be exactly 64 hexadecimal characters")
    request_sha256 = request_sha256.lower()

    if expected_proposal_id is not None and proposal_id != expected_proposal_id:
        raise _error(
            f"proposal_id does not match the pending proposal {expected_proposal_id!r}"
        )
    if expected_request_sha256 is not None:
        expected_hash = _strict_string(
            expected_request_sha256, "expected_request_sha256"
        ).lower()
        if not _SHA256_RE.fullmatch(expected_hash):
            raise _error("expected_request_sha256 must be exactly 64 hexadecimal characters")
        if request_sha256 != expected_hash:
            raise _error("request_sha256 does not match the pending adjudication request")

    verdict = value["verdict"]
    if not isinstance(verdict, str) or verdict not in VERDICTS:
        raise _error(f"verdict must be one of: {', '.join(sorted(VERDICTS))}")
    rules_basis = _strict_string(value["rules_basis"], "rules_basis", strip_text=True)
    public_summary = _strict_string(
        value["public_summary"], "public_summary", strip_text=True
    )
    operations_raw = value["operations"]
    if not isinstance(operations_raw, list):
        raise _error("operations must be a list")

    pilots = frozenset(known_pilots)
    if not pilots or any(not isinstance(pilot, str) or not pilot for pilot in pilots):
        raise _error("known_pilots must contain nonempty pilot names")
    operations = [
        _validate_operation(operation, index, pilots)
        for index, operation in enumerate(operations_raw, 1)
    ]
    fingerprints: set[str] = set()
    bounced_uids: set[str] = set()
    for index, operation in enumerate(operations, 1):
        fingerprint = json.dumps(
            operation, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        if fingerprint in fingerprints:
            raise _error(f"operation {index} duplicates an earlier operation")
        fingerprints.add(fingerprint)
        if operation["op"] == "bounce_permanents":
            for uid in operation.get("uids", ()):
                if uid in bounced_uids:
                    raise _error(
                        f"operation {index}.uids repeats UID {uid!r} from an earlier operation"
                    )
                bounced_uids.add(uid)

    if verdict == "approved" and not operations:
        raise _error("approved combo adjudication requires at least one operation")
    if verdict != "approved" and operations:
        raise _error(f"{verdict} combo adjudication must not contain operations")

    return {
        "schema": SCHEMA_VERSION,
        "proposal_id": proposal_id,
        "request_sha256": request_sha256,
        "verdict": verdict,
        "rules_basis": rules_basis,
        "public_summary": public_summary,
        "operations": operations,
    }


__all__ = [
    "ComboAdjudicationValidationError",
    "INFINITE",
    "KNOWN_PILOTS",
    "MAX_INTEGER",
    "OPERATION_FIELDS",
    "SCHEMA_VERSION",
    "VERDICTS",
    "validate_combo_adjudication_response",
]
