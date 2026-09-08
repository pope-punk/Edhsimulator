"""Inert pilot strategy metadata for the EDH gauntlet.

This module deliberately has no dependency on the rules engine.  It describes why
cards are in a particular deck (roles, packages, and notes), never what those cards
are legally allowed to do.  Rules code must not use this data to construct actions,
resolve effects, or mutate game state.

The data model is immutable.  Post-game learning operations return a new
``StrategyState`` with an incremented revision; ``freeze`` supplies a deterministic
fingerprint that a game can retain alongside its seed and decision tape.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterable, Mapping, Sequence

from .catalog import canonical_card_id


from .paths import PROJECT_ROOT
DEFAULT_STRATEGY_FILE = PROJECT_ROOT / "data" / "strategy" / "deck_profiles.json"


class StrategyValidationError(ValueError):
    """Raised when strategy data is internally inconsistent."""


def canonical_role_id(value: str) -> str:
    """Return a stable snake-case role identifier."""

    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_value.lower()).strip("_")


def _nonempty(value: str, field_name: str) -> str:
    value = str(value).strip()
    if not value:
        raise StrategyValidationError(f"{field_name} must not be empty")
    return value


def _tuple_strings(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in values if str(value).strip())


@dataclass(frozen=True, slots=True)
class StrategyNote:
    """Plain-language pilot memory with provenance; it has no executable fields."""

    note_id: str
    text: str
    source: str
    locked: bool = False
    revision: int = 1
    source_game: int | None = None
    contexts: tuple[str, ...] = ()
    confidence: float | None = None
    source_cohort: str | None = None
    source_review: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.note_id, "note_id")
        _nonempty(self.text, "note text")
        _nonempty(self.source, "note source")
        if self.revision < 1:
            raise StrategyValidationError("note revision must be positive")
        if self.source_game is not None and self.source_game < 1:
            raise StrategyValidationError("source_game must be positive")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise StrategyValidationError("note confidence must be between 0 and 1")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "StrategyNote":
        allowed = {
            "note_id", "text", "source", "locked", "revision",
            "source_game", "contexts", "confidence", "source_cohort", "source_review",
        }
        extras = sorted(set(raw) - allowed)
        if extras:
            raise StrategyValidationError(
                "strategy notes accept descriptive/provenance fields only; "
                f"unexpected fields: {', '.join(extras)}"
            )
        return cls(
            note_id=str(raw["note_id"]),
            text=str(raw["text"]),
            source=str(raw["source"]),
            locked=bool(raw.get("locked", False)),
            revision=int(raw.get("revision", 1)),
            source_game=(int(raw["source_game"]) if raw.get("source_game") is not None else None),
            contexts=_tuple_strings(raw.get("contexts", ())),
            confidence=(float(raw["confidence"]) if raw.get("confidence") is not None else None),
            source_cohort=raw.get('source_cohort'),source_review=raw.get('source_review'),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "note_id": self.note_id,
            "text": self.text,
            "source": self.source,
            "locked": self.locked,
            "revision": self.revision,
            "contexts": list(self.contexts),
        }
        if self.source_game is not None:
            result["source_game"] = self.source_game
        if self.confidence is not None:
            result["confidence"] = self.confidence
        if self.source_cohort is not None:result['source_cohort']=self.source_cohort
        if self.source_review is not None:result['source_review']=self.source_review
        return result


@dataclass(frozen=True, slots=True)
class RoleDefinition:
    """A human-facing strategic classification, never a rules classification."""

    role_id: str
    label: str
    description: str
    aliases: tuple[str, ...] = ()
    parent_role: str | None = None
    status: str = "active"
    source: str = "seed"
    source_game: int | None = None
    revision: int = 1

    def __post_init__(self) -> None:
        if canonical_role_id(self.role_id) != self.role_id:
            raise StrategyValidationError(f"role_id is not canonical: {self.role_id!r}")
        _nonempty(self.label, "role label")
        _nonempty(self.description, "role description")
        _nonempty(self.source, "role source")
        if self.status not in {"active", "retired"}:
            raise StrategyValidationError(f"invalid role status: {self.status!r}")
        if self.revision < 1:
            raise StrategyValidationError("role revision must be positive")
        if self.source_game is not None and self.source_game < 1:
            raise StrategyValidationError("source_game must be positive")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "RoleDefinition":
        return cls(
            role_id=str(raw["role_id"]),
            label=str(raw["label"]),
            description=str(raw["description"]),
            aliases=_tuple_strings(raw.get("aliases", ())),
            parent_role=(str(raw["parent_role"]) if raw.get("parent_role") else None),
            status=str(raw.get("status", "active")),
            source=str(raw.get("source", "seed")),
            source_game=(int(raw["source_game"]) if raw.get("source_game") is not None else None),
            revision=int(raw.get("revision", 1)),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "role_id": self.role_id,
            "label": self.label,
            "description": self.description,
            "aliases": list(self.aliases),
            "status": self.status,
            "source": self.source,
            "revision": self.revision,
        }
        if self.parent_role is not None:
            result["parent_role"] = self.parent_role
        if self.source_game is not None:
            result["source_game"] = self.source_game
        return result


@dataclass(frozen=True, slots=True)
class RoleAssignment:
    """A deck-specific assertion that one card serves one strategic role."""

    role_id: str
    source: str = "seed"
    source_game: int | None = None
    revision: int = 1

    def __post_init__(self) -> None:
        if canonical_role_id(self.role_id) != self.role_id:
            raise StrategyValidationError(f"role assignment is not canonical: {self.role_id!r}")
        _nonempty(self.source, "role-assignment source")
        if self.source_game is not None and self.source_game < 1:
            raise StrategyValidationError("source_game must be positive")
        if self.revision < 1:
            raise StrategyValidationError("role-assignment revision must be positive")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | str) -> "RoleAssignment":
        if isinstance(raw, str):
            return cls(role_id=raw)
        return cls(
            role_id=str(raw["role_id"]),
            source=str(raw.get("source", "seed")),
            source_game=(int(raw["source_game"]) if raw.get("source_game") is not None else None),
            revision=int(raw.get("revision", 1)),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "role_id": self.role_id,
            "source": self.source,
            "revision": self.revision,
        }
        if self.source_game is not None:
            result["source_game"] = self.source_game
        return result


@dataclass(frozen=True, slots=True)
class DeckCardEntry:
    """One canonical card's membership and strategic annotations in one deck."""

    card_id: str
    card_name: str
    quantity: int
    roles: tuple[RoleAssignment, ...] = ()
    notes: tuple[StrategyNote, ...] = ()

    def __post_init__(self) -> None:
        if canonical_card_id(self.card_name) != self.card_id:
            raise StrategyValidationError(
                f"card_id {self.card_id!r} does not match card name {self.card_name!r}"
            )
        if self.quantity < 1:
            raise StrategyValidationError(f"quantity must be positive for {self.card_name}")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DeckCardEntry":
        return cls(
            card_id=str(raw["card_id"]),
            card_name=str(raw["card_name"]),
            quantity=int(raw["quantity"]),
            roles=tuple(RoleAssignment.from_dict(value) for value in raw.get("roles", ())),
            notes=tuple(StrategyNote.from_dict(value) for value in raw.get("notes", ())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "card_name": self.card_name,
            "quantity": self.quantity,
            "roles": [role.to_dict() for role in sorted(self.roles, key=lambda item: item.role_id)],
            "notes": [note.to_dict() for note in sorted(self.notes, key=lambda item: item.note_id)],
        }

    @property
    def role_ids(self) -> tuple[str, ...]:
        return tuple(sorted(assignment.role_id for assignment in self.roles))


@dataclass(frozen=True, slots=True)
class ComboPackageMember:
    card_id: str
    member_role: str = "piece"

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | str) -> "ComboPackageMember":
        if isinstance(raw, str):
            return cls(card_id=raw)
        return cls(card_id=str(raw["card_id"]), member_role=str(raw.get("member_role", "piece")))

    def to_dict(self) -> dict[str, str]:
        return {"card_id": self.card_id, "member_role": self.member_role}


@dataclass(frozen=True, slots=True)
class ComboPackage:
    """A named, inspectable group of strategically related cards in one deck."""

    package_id: str
    label: str
    description: str
    members: tuple[ComboPackageMember, ...]
    notes: tuple[StrategyNote, ...] = ()
    status: str = "active"
    source: str = "seed"
    source_game: int | None = None
    revision: int = 1

    def __post_init__(self) -> None:
        if canonical_role_id(self.package_id) != self.package_id:
            raise StrategyValidationError(f"package_id is not canonical: {self.package_id!r}")
        _nonempty(self.label, "package label")
        _nonempty(self.description, "package description")
        if not self.members:
            raise StrategyValidationError(f"package {self.package_id} must have at least one member")
        if self.status not in {"active", "retired"}:
            raise StrategyValidationError(f"invalid package status: {self.status!r}")
        if self.source_game is not None and self.source_game < 1:
            raise StrategyValidationError("source_game must be positive")
        if self.revision < 1:
            raise StrategyValidationError("package revision must be positive")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ComboPackage":
        return cls(
            package_id=str(raw["package_id"]),
            label=str(raw["label"]),
            description=str(raw["description"]),
            members=tuple(ComboPackageMember.from_dict(value) for value in raw["members"]),
            notes=tuple(StrategyNote.from_dict(value) for value in raw.get("notes", ())),
            status=str(raw.get("status", "active")),
            source=str(raw.get("source", "seed")),
            source_game=(int(raw["source_game"]) if raw.get("source_game") is not None else None),
            revision=int(raw.get("revision", 1)),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "package_id": self.package_id,
            "label": self.label,
            "description": self.description,
            "members": [member.to_dict() for member in sorted(self.members, key=lambda item: item.card_id)],
            "notes": [note.to_dict() for note in sorted(self.notes, key=lambda item: item.note_id)],
            "status": self.status,
            "source": self.source,
            "revision": self.revision,
        }
        if self.source_game is not None:
            result["source_game"] = self.source_game
        return result


@dataclass(frozen=True, slots=True)
class DeckProfile:
    """Deck membership plus deck-specific, non-executable pilot knowledge."""

    deck_id: str
    label: str
    commander_card_id: str
    cards: tuple[DeckCardEntry, ...]
    packages: tuple[ComboPackage, ...] = ()
    revision: int = 1

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DeckProfile":
        return cls(
            deck_id=str(raw["deck_id"]),
            label=str(raw["label"]),
            commander_card_id=str(raw["commander_card_id"]),
            cards=tuple(DeckCardEntry.from_dict(value) for value in raw["cards"]),
            packages=tuple(ComboPackage.from_dict(value) for value in raw.get("packages", ())),
            revision=int(raw.get("revision", 1)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "deck_id": self.deck_id,
            "label": self.label,
            "commander_card_id": self.commander_card_id,
            "revision": self.revision,
            "cards": [card.to_dict() for card in sorted(self.cards, key=lambda item: item.card_id)],
            "packages": [package.to_dict() for package in sorted(self.packages, key=lambda item: item.package_id)],
        }

    @property
    def card_count(self) -> int:
        return sum(card.quantity for card in self.cards)

    def card_by_id(self, card_id: str) -> DeckCardEntry | None:
        return next((card for card in self.cards if card.card_id == card_id), None)

    def card_by_name(self, card_name: str) -> DeckCardEntry | None:
        return self.card_by_id(canonical_card_id(card_name))

    def package(self, package_id: str) -> ComboPackage | None:
        package_id = canonical_role_id(package_id)
        return next((item for item in self.packages if item.package_id == package_id), None)


@dataclass(frozen=True, slots=True)
class FrozenStrategyRevision:
    """A deterministic reference to the exact pilot-memory revision used by a game."""

    revision: int
    fingerprint: str

    @property
    def revision_id(self) -> str:
        return f"strategy-r{self.revision}-{self.fingerprint[:16]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "fingerprint": self.fingerprint,
            "revision_id": self.revision_id,
        }


@dataclass(frozen=True, slots=True)
class StrategyState:
    """The complete, immutable role vocabulary and four deck profiles."""

    schema_version: int
    revision: int
    roles: tuple[RoleDefinition, ...]
    decks: tuple[DeckProfile, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], *, validate: bool = True) -> "StrategyState":
        forbidden = _find_forbidden_oracle_fields(raw)
        if forbidden:
            raise StrategyValidationError(
                "Oracle text belongs in the parent card catalog, not strategy data: "
                + ", ".join(forbidden)
            )
        state = cls(
            schema_version=int(raw.get("schema_version", 1)),
            revision=int(raw.get("revision", 1)),
            roles=tuple(RoleDefinition.from_dict(value) for value in raw["roles"]),
            decks=tuple(DeckProfile.from_dict(value) for value in raw["decks"]),
        )
        if validate:
            state.validate()
        return state

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "revision": self.revision,
            "roles": [role.to_dict() for role in sorted(self.roles, key=lambda item: item.role_id)],
            "decks": [deck.to_dict() for deck in sorted(self.decks, key=lambda item: item.deck_id)],
        }

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def freeze(self) -> FrozenStrategyRevision:
        return FrozenStrategyRevision(self.revision, sha256(self.canonical_json().encode("utf-8")).hexdigest())

    def role(self, role_id_or_alias: str) -> RoleDefinition | None:
        wanted = canonical_role_id(role_id_or_alias)
        # Active aliases win over the preserved identity of a retired role.  This
        # lets ``merge_roles`` keep an auditable tombstone while old vocabulary
        # transparently resolves to the surviving active role.
        for status in ("active", "retired"):
            for role in self.roles:
                if role.status != status:
                    continue
                aliases = {canonical_role_id(value) for value in role.aliases}
                if role.role_id == wanted or wanted in aliases:
                    return role
        return None

    def deck(self, deck_id: str) -> DeckProfile | None:
        wanted = canonical_role_id(deck_id)
        return next((deck for deck in self.decks if deck.deck_id == wanted), None)

    def roles_for_deck(self, deck_id: str, *, include_retired: bool = False) -> tuple[RoleDefinition, ...]:
        deck = self._require_deck(deck_id)
        used = {assignment.role_id for card in deck.cards for assignment in card.roles}
        return tuple(
            sorted(
                (
                    role
                    for role in self.roles
                    if role.role_id in used and (include_retired or role.status == "active")
                ),
                key=lambda role: role.role_id,
            )
        )

    def cards_for_role(self, deck_id: str, role_id_or_alias: str) -> tuple[DeckCardEntry, ...]:
        deck = self._require_deck(deck_id)
        role = self._require_role(role_id_or_alias)
        return tuple(card for card in deck.cards if role.role_id in card.role_ids)

    def role_presence_matrix(self, *, include_retired: bool = False) -> dict[str, dict[str, int]]:
        """Generate the requested role-by-deck 0/1 table from card assignments."""

        decks = sorted(self.decks, key=lambda deck: deck.deck_id)
        roles = sorted(
            (role for role in self.roles if include_retired or role.status == "active"),
            key=lambda role: role.role_id,
        )
        deck_role_sets = {
            deck.deck_id: {assignment.role_id for card in deck.cards for assignment in card.roles}
            for deck in decks
        }
        return {
            role.role_id: {
                deck.deck_id: int(role.role_id in deck_role_sets[deck.deck_id]) for deck in decks
            }
            for role in roles
        }

    def validate(
        self,
        *,
        catalog_card_ids: Iterable[str] | None = None,
        expected_deck_size: int | None = 100,
    ) -> None:
        errors = self.validation_errors(
            catalog_card_ids=catalog_card_ids,
            expected_deck_size=expected_deck_size,
        )
        if errors:
            raise StrategyValidationError("Invalid strategy data:\n- " + "\n- ".join(errors))

    def validation_errors(
        self,
        *,
        catalog_card_ids: Iterable[str] | None = None,
        expected_deck_size: int | None = 100,
    ) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version < 1:
            errors.append("schema_version must be positive")
        if self.revision < 1:
            errors.append("revision must be positive")
        role_by_id = {role.role_id: role for role in self.roles}
        if len(role_by_id) != len(self.roles):
            errors.append("duplicate role_id")
        deck_by_id = {deck.deck_id: deck for deck in self.decks}
        if len(deck_by_id) != len(self.decks):
            errors.append("duplicate deck_id")

        alias_owner: dict[str, str] = {}
        for role in self.roles:
            if role.parent_role and role.parent_role not in role_by_id:
                errors.append(f"role {role.role_id} has missing parent {role.parent_role}")
            # Retired definitions are historical tombstones.  Their former name
            # may intentionally be an alias of the active role they merged into.
            if role.status == "retired":
                continue
            for name in (role.role_id, role.label, *role.aliases):
                alias = canonical_role_id(name)
                previous = alias_owner.get(alias)
                if previous and previous != role.role_id:
                    errors.append(f"role alias {name!r} is shared by {previous} and {role.role_id}")
                alias_owner[alias] = role.role_id
        errors.extend(_role_cycle_errors(role_by_id))

        catalog_ids = set(catalog_card_ids) if catalog_card_ids is not None else None
        for deck in self.decks:
            if canonical_role_id(deck.deck_id) != deck.deck_id:
                errors.append(f"deck_id is not canonical: {deck.deck_id}")
            if deck.revision < 1:
                errors.append(f"deck {deck.deck_id} revision must be positive")
            card_ids = [card.card_id for card in deck.cards]
            if len(set(card_ids)) != len(card_ids):
                errors.append(f"deck {deck.deck_id} has duplicate card entries")
            if expected_deck_size is not None and deck.card_count != expected_deck_size:
                errors.append(
                    f"deck {deck.deck_id} contains {deck.card_count} cards, expected {expected_deck_size}"
                )
            if deck.commander_card_id not in set(card_ids):
                errors.append(f"deck {deck.deck_id} commander is not in its card list")
            if catalog_ids is not None:
                missing = sorted(set(card_ids) - catalog_ids)
                if missing:
                    errors.append(f"deck {deck.deck_id} has catalog-missing cards: {', '.join(missing)}")
            note_ids: set[str] = set()
            for card in deck.cards:
                assignment_ids = [assignment.role_id for assignment in card.roles]
                if len(set(assignment_ids)) != len(assignment_ids):
                    errors.append(f"{deck.deck_id}/{card.card_id} has duplicate role assignments")
                for assignment in card.roles:
                    if assignment.role_id not in role_by_id:
                        errors.append(
                            f"{deck.deck_id}/{card.card_id} uses unknown role {assignment.role_id}"
                        )
                for note in card.notes:
                    qualified = f"card:{card.card_id}:{note.note_id}"
                    if qualified in note_ids:
                        errors.append(f"deck {deck.deck_id} has duplicate note {qualified}")
                    note_ids.add(qualified)
            package_ids = [package.package_id for package in deck.packages]
            if len(set(package_ids)) != len(package_ids):
                errors.append(f"deck {deck.deck_id} has duplicate package IDs")
            for package in deck.packages:
                member_ids = [member.card_id for member in package.members]
                if len(set(member_ids)) != len(member_ids):
                    errors.append(f"package {deck.deck_id}/{package.package_id} has duplicate members")
                for member_id in member_ids:
                    if member_id not in set(card_ids):
                        errors.append(
                            f"package {deck.deck_id}/{package.package_id} references absent card {member_id}"
                        )
                for note in package.notes:
                    qualified = f"package:{package.package_id}:{note.note_id}"
                    if qualified in note_ids:
                        errors.append(f"deck {deck.deck_id} has duplicate note {qualified}")
                    note_ids.add(qualified)
        return tuple(sorted(set(errors)))

    # --- Post-game learning operations.  Every operation returns a new revision. ---

    def create_role(
        self,
        label: str,
        description: str,
        *,
        aliases: Sequence[str] = (),
        parent_role: str | None = None,
        source: str = "pilot_review",
        source_game: int | None = None,
    ) -> "StrategyState":
        role_id = canonical_role_id(label)
        if self.role(role_id) is not None:
            raise StrategyValidationError(f"role or alias already exists: {role_id}")
        parent_id = self._require_role(parent_role).role_id if parent_role else None
        next_revision = self.revision + 1
        role = RoleDefinition(
            role_id=role_id,
            label=label,
            description=description,
            aliases=_tuple_strings(aliases),
            parent_role=parent_id,
            source=source,
            source_game=source_game,
            revision=next_revision,
        )
        result = replace(self, revision=next_revision, roles=(*self.roles, role))
        result.validate()
        return result

    def retire_role(
        self,
        role_id_or_alias: str,
        *,
        source: str = "pilot_review",
        source_game: int | None = None,
    ) -> "StrategyState":
        role = self._require_role(role_id_or_alias)
        next_revision = self.revision + 1
        updated = replace(
            role,
            status="retired",
            source=source,
            source_game=source_game,
            revision=next_revision,
        )
        result = replace(
            self,
            revision=next_revision,
            roles=tuple(updated if item.role_id == role.role_id else item for item in self.roles),
        )
        result.validate()
        return result

    def merge_roles(
        self,
        source_role: str,
        target_role: str,
        *,
        source: str = "pilot_review",
        source_game: int | None = None,
    ) -> "StrategyState":
        old = self._require_role(source_role)
        target = self._require_role(target_role)
        if old.role_id == target.role_id:
            raise StrategyValidationError("cannot merge a role into itself")
        next_revision = self.revision + 1
        aliases = tuple(dict.fromkeys((*target.aliases, old.role_id, old.label, *old.aliases)))
        updated_target = replace(
            target,
            aliases=aliases,
            source=source,
            source_game=source_game,
            revision=next_revision,
        )
        updated_old = replace(
            old,
            status="retired",
            aliases=(),
            source=source,
            source_game=source_game,
            revision=next_revision,
        )
        roles = tuple(
            updated_target
            if role.role_id == target.role_id
            else updated_old
            if role.role_id == old.role_id
            else replace(role, parent_role=target.role_id)
            if role.parent_role == old.role_id
            else role
            for role in self.roles
        )
        decks: list[DeckProfile] = []
        for deck in self.decks:
            cards: list[DeckCardEntry] = []
            for card in deck.cards:
                assignments: dict[str, RoleAssignment] = {}
                for assignment in card.roles:
                    assignment = (
                        RoleAssignment(target.role_id, source, source_game, next_revision)
                        if assignment.role_id == old.role_id
                        else assignment
                    )
                    assignments[assignment.role_id] = assignment
                cards.append(replace(card, roles=tuple(assignments.values())))
            decks.append(replace(deck, cards=tuple(cards), revision=next_revision))
        result = replace(self, revision=next_revision, roles=roles, decks=tuple(decks))
        result.validate()
        return result

    def assign_role(
        self,
        deck_id: str,
        card_id_or_name: str,
        role_id_or_alias: str,
        *,
        source: str = "pilot_review",
        source_game: int | None = None,
    ) -> "StrategyState":
        deck = self._require_deck(deck_id)
        card = self._require_card(deck, card_id_or_name)
        role = self._require_role(role_id_or_alias)
        if role.role_id in card.role_ids:
            return self
        next_revision = self.revision + 1
        assignment = RoleAssignment(role.role_id, source, source_game, next_revision)
        updated_card = replace(card, roles=(*card.roles, assignment))
        return self._replace_card(deck, updated_card, next_revision)

    def unassign_role(self, deck_id: str, card_id_or_name: str, role_id_or_alias: str) -> "StrategyState":
        deck = self._require_deck(deck_id)
        card = self._require_card(deck, card_id_or_name)
        role = self._require_role(role_id_or_alias)
        if role.role_id not in card.role_ids:
            return self
        next_revision = self.revision + 1
        updated_card = replace(
            card,
            roles=tuple(item for item in card.roles if item.role_id != role.role_id),
        )
        return self._replace_card(deck, updated_card, next_revision)

    def add_note(self, deck_id: str, card_id_or_name: str, note: StrategyNote) -> "StrategyState":
        deck = self._require_deck(deck_id)
        card = self._require_card(deck, card_id_or_name)
        if any(item.note_id == note.note_id for item in card.notes):
            raise StrategyValidationError(f"note already exists: {note.note_id}")
        next_revision = self.revision + 1
        note = replace(note, revision=next_revision)
        return self._replace_card(deck, replace(card, notes=(*card.notes, note)), next_revision)

    def replace_note(
        self,
        deck_id: str,
        card_id_or_name: str,
        note: StrategyNote,
        *,
        allow_locked: bool = False,
    ) -> "StrategyState":
        deck = self._require_deck(deck_id)
        card = self._require_card(deck, card_id_or_name)
        previous = next((item for item in card.notes if item.note_id == note.note_id), None)
        if previous is None:
            raise StrategyValidationError(f"unknown note: {note.note_id}")
        if previous.locked and not allow_locked:
            raise StrategyValidationError(f"note is locked: {note.note_id}")
        next_revision = self.revision + 1
        note = replace(note, revision=next_revision)
        notes = tuple(note if item.note_id == note.note_id else item for item in card.notes)
        return self._replace_card(deck, replace(card, notes=notes), next_revision)

    def upsert_package(self, deck_id: str, package: ComboPackage) -> "StrategyState":
        """Create or revise a named strategic package during post-game learning."""

        deck = self._require_deck(deck_id)
        next_revision = self.revision + 1
        package = replace(package, revision=next_revision)
        previous = deck.package(package.package_id)
        packages = (
            tuple(package if item.package_id == package.package_id else item for item in deck.packages)
            if previous
            else (*deck.packages, package)
        )
        updated_deck = replace(deck, packages=packages, revision=next_revision)
        decks = tuple(updated_deck if item.deck_id == deck.deck_id else item for item in self.decks)
        result = replace(self, revision=next_revision, decks=decks)
        result.validate()
        return result

    def retire_package(self, deck_id: str, package_id: str) -> "StrategyState":
        deck = self._require_deck(deck_id)
        package = deck.package(package_id)
        if package is None:
            raise StrategyValidationError(f"unknown package in {deck.deck_id}: {package_id}")
        if package.status == "retired":
            return self
        next_revision = self.revision + 1
        updated_package = replace(package, status="retired", revision=next_revision)
        packages = tuple(
            updated_package if item.package_id == package.package_id else item for item in deck.packages
        )
        updated_deck = replace(deck, packages=packages, revision=next_revision)
        decks = tuple(updated_deck if item.deck_id == deck.deck_id else item for item in self.decks)
        result = replace(self, revision=next_revision, decks=decks)
        result.validate()
        return result

    def _replace_card(self, deck: DeckProfile, card: DeckCardEntry, next_revision: int) -> "StrategyState":
        cards = tuple(card if item.card_id == card.card_id else item for item in deck.cards)
        updated_deck = replace(deck, cards=cards, revision=next_revision)
        decks = tuple(updated_deck if item.deck_id == deck.deck_id else item for item in self.decks)
        result = replace(self, revision=next_revision, decks=decks)
        result.validate()
        return result

    def _require_role(self, role_id_or_alias: str | None) -> RoleDefinition:
        if role_id_or_alias is None:
            raise StrategyValidationError("role is required")
        role = self.role(role_id_or_alias)
        if role is None:
            raise StrategyValidationError(f"unknown role: {role_id_or_alias}")
        return role

    def _require_deck(self, deck_id: str) -> DeckProfile:
        deck = self.deck(deck_id)
        if deck is None:
            raise StrategyValidationError(f"unknown deck: {deck_id}")
        return deck

    @staticmethod
    def _require_card(deck: DeckProfile, card_id_or_name: str) -> DeckCardEntry:
        card = deck.card_by_id(card_id_or_name) or deck.card_by_name(card_id_or_name)
        if card is None:
            raise StrategyValidationError(f"card is not in {deck.deck_id}: {card_id_or_name}")
        return card


def _find_forbidden_oracle_fields(value: Any, path: str = "$") -> tuple[str, ...]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).lower() in {"oracle", "oracle_text", "rules_text", "printed_text"}:
                found.append(child_path)
            found.extend(_find_forbidden_oracle_fields(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_find_forbidden_oracle_fields(child, f"{path}[{index}]"))
    return tuple(found)


def _role_cycle_errors(role_by_id: Mapping[str, RoleDefinition]) -> list[str]:
    errors: list[str] = []
    for role_id in sorted(role_by_id):
        seen: set[str] = set()
        current: str | None = role_id
        while current is not None and current in role_by_id:
            if current in seen:
                errors.append(f"role parent cycle contains {current}")
                break
            seen.add(current)
            current = role_by_id[current].parent_role
    return errors


def load_strategy_state(path: str | Path = DEFAULT_STRATEGY_FILE) -> StrategyState:
    """Load and validate the strategy model from a JSON file."""

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return StrategyState.from_dict(raw)


def save_strategy_state(state: StrategyState, path: str | Path) -> None:
    """Persist a canonical, reproducible strategy revision."""

    state.validate()
    Path(path).write_text(
        json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


__all__ = [
    "ComboPackage",
    "ComboPackageMember",
    "DEFAULT_STRATEGY_FILE",
    "DeckCardEntry",
    "DeckProfile",
    "FrozenStrategyRevision",
    "RoleAssignment",
    "RoleDefinition",
    "StrategyNote",
    "StrategyState",
    "StrategyValidationError",
    "canonical_card_id",
    "canonical_role_id",
    "load_strategy_state",
    "save_strategy_state",
]
