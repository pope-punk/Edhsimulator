"""Canonical, card-first data model for the fixed four-deck EDH pod.

The catalog is deliberately independent of the runtime game engine.  It stores
printed facts and references to rules handlers; it never stores mutable game
state or pilot strategy.  Consumers may therefore import it from the referee,
inspection tools, or reporting code without creating a rules dependency cycle.

``data/catalog/cards.json`` is generated deterministically by
``tools/generate_card_catalog.py``.  JSON arrays are converted to tuples and
parameter dictionaries to read-only mappings when loaded, so catalog objects
cannot be mutated accidentally during a game.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Optional
import unicodedata


from .paths import PROJECT_ROOT
DEFAULT_CATALOG_PATH = PROJECT_ROOT / "data" / "catalog" / "cards.json"
CATALOG_SCHEMA_VERSION = 1
EXPECTED_DECK_SLOTS: Mapping[str, int] = MappingProxyType(
    {"Reaminatour": 100, "Minsc & Boo": 100, "Omo": 100, "Elenda": 100}
)


def canonical_card_id(name: str) -> str:
    """Return the stable, human-readable identifier used across catalog files."""

    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


def mana_value(mana_cost: str) -> int:
    """Return the printed mana value for one face's mana-cost string."""

    if not mana_cost or mana_cost in {"—", "-"}:
        return 0
    total = 0
    for symbol in re.findall(r"\{([^}]+)\}", mana_cost):
        if symbol.isdigit():
            total += int(symbol)
        elif symbol.upper() in {"X", "Y", "Z"}:
            continue
        else:
            # Colored, colorless, Phyrexian, hybrid, and snow symbols each
            # contribute one to mana value unless a numeric hybrid component
            # explicitly supplies the larger value.
            hybrid_numbers = [int(part) for part in symbol.split("/") if part.isdigit()]
            total += max(hybrid_numbers, default=1)
    return total


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


@dataclass(frozen=True)
class DeckOccurrence:
    deck: str
    quantity: int
    ordinal: int


@dataclass(frozen=True)
class CardFace:
    face_id: str
    name: str
    mana_cost: str
    mana_value: int
    type_line: str
    supertypes: tuple[str, ...]
    types: tuple[str, ...]
    subtypes: tuple[str, ...]
    oracle_text: str
    colors: tuple[str, ...] = ()
    power: Optional[int] = None
    toughness: Optional[int] = None
    loyalty: Optional[int] = None
    loyalty_variable: Optional[str] = None
    keywords: tuple[str, ...] = ()

    def starting_loyalty(self, *, x_value: Optional[int] = None) -> Optional[int]:
        if self.loyalty is not None:
            return self.loyalty
        if self.loyalty_variable == "X":
            return x_value
        return None

    def has_type(self, card_type: str) -> bool:
        return card_type.casefold() in {item.casefold() for item in self.types}


@dataclass(frozen=True)
class AbilitySpec:
    """One discoverable rules clause or executable registered ability.

    ``origin='oracle'`` rows are the complete human-auditable inventory parsed
    from the stored Oracle reference.  A row becomes executable only when its
    ``support_status`` and ``handler`` identify a rules implementation.
    """

    ability_id: str
    face_id: str
    origin: str
    kind: str
    zone: str
    timing: str
    rules_text: str
    event: Optional[str] = None
    optional: bool = False
    mana_ability: bool = False
    uses_stack: bool = True
    cost_text: Optional[str] = None
    handler: Optional[str] = None
    support_status: str = "oracle_only"

    @property
    def speed(self) -> str:
        return self.timing

    @property
    def handler_ref(self) -> Optional[str]:
        return self.handler


@dataclass(frozen=True)
class EntryReplacementSpec:
    replacement_id: str
    face_id: str
    kind: str
    event: str
    rules_text: str
    optional: bool = False
    parameters: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    handler: Optional[str] = None
    support_status: str = "catalogued"

    def parameter(self, name: str, default: Any = None) -> Any:
        return self.parameters.get(name, default)


@dataclass(frozen=True)
class ManaMetadata:
    is_mana_source: bool = False
    colors: tuple[str, ...] = ()
    source_kinds: tuple[str, ...] = ()
    production_rule: str = "none"
    base_amount: Optional[int] = None
    variable_output: bool = False


@dataclass(frozen=True)
class LandMetadata:
    classifications: tuple[str, ...] = ()
    fetch_types: tuple[str, ...] = ()

    def has_classification(self, value: str) -> bool:
        return value in self.classifications


@dataclass(frozen=True)
class CardDefinition:
    card_id: str
    name: str
    oracle_text: str
    color_identity: tuple[str, ...]
    faces: tuple[CardFace, ...]
    abilities: tuple[AbilitySpec, ...]
    entry_replacements: tuple[EntryReplacementSpec, ...]
    mana: ManaMetadata
    land: Optional[LandMetadata]
    source_decks: tuple[DeckOccurrence, ...]

    @property
    def front(self) -> CardFace:
        return self.faces[0]

    def face(self, face_id_or_name: str) -> CardFace:
        folded = face_id_or_name.casefold()
        for face in self.faces:
            if face.face_id == face_id_or_name or face.name.casefold() == folded:
                return face
        raise KeyError(f"{self.name!r} has no face {face_id_or_name!r}")

    def has_face_type(self, card_type: str) -> bool:
        return any(face.has_type(card_type) for face in self.faces)

    # Compatibility conveniences for the legacy CardDef interface.  These
    # intentionally describe the front face, matching the old split-on-// code.
    @property
    def mana_cost(self) -> str:
        return " // ".join(face.mana_cost for face in self.faces)

    @property
    def type_line(self) -> str:
        return " // ".join(face.type_line for face in self.faces)

    @property
    def text(self) -> str:
        return self.oracle_text

    @property
    def mv(self) -> int:
        return self.front.mana_value

    @property
    def is_land(self) -> bool:
        return self.front.has_type("Land")

    @property
    def is_creature(self) -> bool:
        return self.front.has_type("Creature")

    @property
    def is_enchantment(self) -> bool:
        return self.front.has_type("Enchantment")

    @property
    def is_artifact(self) -> bool:
        return self.front.has_type("Artifact")

    @property
    def is_planeswalker(self) -> bool:
        return self.front.has_type("Planeswalker")

    @property
    def is_instant(self) -> bool:
        return self.front.has_type("Instant")

    @property
    def is_sorcery(self) -> bool:
        return self.front.has_type("Sorcery")

    @property
    def is_permanent(self) -> bool:
        return not (self.is_instant or self.is_sorcery)


@dataclass(frozen=True)
class CatalogValidationReport:
    card_count: int
    face_count: int
    ability_count: int
    oracle_ability_count: int
    deck_slot_counts: Mapping[str, int]
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


class CatalogValidationError(ValueError):
    def __init__(self, errors: tuple[str, ...]):
        self.errors = errors
        super().__init__("Invalid card catalog:\n- " + "\n- ".join(errors))


@dataclass(frozen=True)
class CardCatalog:
    schema_version: int
    cards: tuple[CardDefinition, ...]
    source: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    audit: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    _by_id: Mapping[str, CardDefinition] = field(init=False, repr=False, compare=False)
    _by_name: Mapping[str, CardDefinition] = field(init=False, repr=False, compare=False)
    _by_face_id: Mapping[str, CardDefinition] = field(init=False, repr=False, compare=False)
    _by_face_name: Mapping[str, CardDefinition] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_by_id", MappingProxyType({card.card_id: card for card in self.cards}))
        object.__setattr__(self, "_by_name", MappingProxyType({card.name: card for card in self.cards}))
        object.__setattr__(
            self,
            "_by_face_id",
            MappingProxyType({face.face_id: card for card in self.cards for face in card.faces}),
        )
        object.__setattr__(
            self,
            "_by_face_name",
            MappingProxyType({face.name: card for card in self.cards for face in card.faces}),
        )

    def __len__(self) -> int:
        return len(self.cards)

    def __iter__(self) -> Iterator[CardDefinition]:
        return iter(self.cards)

    @property
    def by_id(self) -> Mapping[str, CardDefinition]:
        return self._by_id

    @property
    def by_name(self) -> Mapping[str, CardDefinition]:
        return self._by_name

    @property
    def by_face_name(self) -> Mapping[str, CardDefinition]:
        """Face-name aliases mapped to their parent definitions."""

        return self._by_face_name

    def get(self, name_or_id: str, default: Optional[CardDefinition] = None) -> Optional[CardDefinition]:
        return self._by_id.get(
            name_or_id,
            self._by_name.get(
                name_or_id,
                self._by_face_id.get(name_or_id, self._by_face_name.get(name_or_id, default)),
            ),
        )

    def require(self, name_or_id: str) -> CardDefinition:
        card = self.get(name_or_id)
        if card is None:
            raise KeyError(f"No catalog card named or identified by {name_or_id!r}")
        return card

    def resolve_face(self, face_name_or_id: str) -> tuple[CardDefinition, CardFace]:
        """Resolve either a parent/front alias or an individual face alias."""

        card = self.require(face_name_or_id)
        folded = face_name_or_id.casefold()
        face = next(
            (
                item
                for item in card.faces
                if item.face_id == face_name_or_id or item.name.casefold() == folded
            ),
            card.front,
        )
        return card, face

    def cards_for_deck(self, deck: str) -> tuple[CardDefinition, ...]:
        return tuple(card for card, _ in self.deck_entries(deck))

    def deck_entries(self, deck: str) -> tuple[tuple[CardDefinition, DeckOccurrence], ...]:
        """Return definitions in the exact source decklist order used by RNG setup."""

        rows = [
            (card, occurrence)
            for card in self.cards
            for occurrence in card.source_decks
            if occurrence.deck == deck and occurrence.quantity > 0
        ]
        return tuple(sorted(rows, key=lambda row: row[1].ordinal))

    def abilities_for_event(
        self,
        card_name: str,
        event: str,
        zone: str = "battlefield",
        *,
        executable_only: bool = True,
    ) -> tuple[AbilitySpec, ...]:
        """Return card-owned abilities subscribed to a normalized rules event.

        Event inventory rows may name more than one event with commas.  The
        default executable filter is important during incremental migration: raw
        Oracle audit clauses must not become stack objects until a handler exists.
        Callers building coverage reports can pass ``executable_only=False``.
        """

        card = self.require(card_name)
        result: list[AbilitySpec] = []
        for ability in card.abilities:
            events = {item.strip() for item in (ability.event or "").split(",") if item.strip()}
            if event not in events or ability.zone != zone:
                continue
            if executable_only and (
                not ability.handler
                or ability.support_status not in {"registered", "generic", "custom"}
            ):
                continue
            result.append(ability)
        return tuple(result)

    def registered_abilities(
        self,
        card_name: str,
        *,
        zone: Optional[str] = None,
        timing: Optional[str] = None,
    ) -> tuple[AbilitySpec, ...]:
        """Return executable action registrations for decision discovery."""

        card = self.require(card_name)
        return tuple(
            ability
            for ability in card.abilities
            if ability.origin == "registry"
            and (zone is None or ability.zone == zone)
            and (timing is None or ability.timing == timing)
        )

    def entry_replacements_for(
        self, card_name: str, *, face_id: Optional[str] = None
    ) -> tuple[EntryReplacementSpec, ...]:
        card = self.require(card_name)
        return tuple(
            replacement
            for replacement in card.entry_replacements
            if face_id is None or replacement.face_id == face_id
        )

    def combat_stats(self) -> Mapping[str, tuple[int, int]]:
        """Compatibility projection for the legacy ``PT`` annotation map."""

        return MappingProxyType(
            {
                card.name: (card.front.power, card.front.toughness)
                for card in self.cards
                if card.front.power is not None and card.front.toughness is not None
            }
        )

    def keyword_projection(self) -> Mapping[str, frozenset[str]]:
        """Compatibility projection for printed front-face combat keywords."""

        return MappingProxyType(
            {card.name: frozenset(card.front.keywords) for card in self.cards if card.front.keywords}
        )

    def land_color_projection(self) -> Mapping[str, frozenset[str]]:
        rows: dict[str, frozenset[str]] = {}
        for card in self.cards:
            if card.land is None or not card.mana.colors:
                continue
            colors = frozenset(card.mana.colors)
            rows[card.name] = colors
            for face in card.faces:
                if face.has_type("Land"):
                    rows[face.name] = colors
        return MappingProxyType(rows)

    def names_with_land_classification(self, classification: str) -> frozenset[str]:
        names: set[str] = set()
        for card in self.cards:
            if card.land is None or not card.land.has_classification(classification):
                continue
            names.add(card.name)
            names.update(face.name for face in card.faces if face.has_type("Land"))
        return frozenset(names)

    def fetch_type_projection(self) -> Mapping[str, frozenset[str]]:
        return MappingProxyType(
            {
                card.name: frozenset(card.land.fetch_types)
                for card in self.cards
                if card.land is not None and card.land.fetch_types
            }
        )

    def mana_source_names(self, source_kind: str) -> frozenset[str]:
        return frozenset(card.name for card in self.cards if source_kind in card.mana.source_kinds)

    def legacy_projections(self) -> Mapping[str, Any]:
        """Expose generated, read-only views during the engine cutover.

        These are compatibility products, never independent sources of truth.
        Their uppercase keys intentionally match the structures being retired.
        """

        return MappingProxyType(
            {
                "CARDDEF": self.by_name,
                "PT": self.combat_stats(),
                "KEYWORDS": self.keyword_projection(),
                "LAND_COLOR_HINTS": self.land_color_projection(),
                "FETCHES": self.names_with_land_classification("fetch"),
                "FETCH_TYPES": self.fetch_type_projection(),
                "BOUNCE_LANDS": self.names_with_land_classification("bounce"),
                "TAPPED_LANDS": self.names_with_land_classification("enters_tapped"),
                "SHOCK_LANDS": self.names_with_land_classification("shock"),
                "SLOW_LANDS": self.names_with_land_classification("slow"),
                "MANA_ROCKS": self.mana_source_names("mana_rock"),
                "MANA_DORKS": self.mana_source_names("mana_dork"),
            }
        )

    def validation_report(
        self,
        expected_unique: Optional[int] = 334,
        expected_slots: Optional[Mapping[str, int]] = EXPECTED_DECK_SLOTS,
    ) -> CatalogValidationReport:
        errors: list[str] = []
        if self.schema_version != CATALOG_SCHEMA_VERSION:
            errors.append(
                f"schema_version {self.schema_version} != supported {CATALOG_SCHEMA_VERSION}"
            )
        ids = [card.card_id for card in self.cards]
        names = [card.name for card in self.cards]
        if len(ids) != len(set(ids)):
            errors.append("duplicate card_id values")
        if len(names) != len(set(names)):
            errors.append("duplicate card names")
        if ids != sorted(ids):
            errors.append("cards are not in deterministic card_id order")
        if expected_unique is not None and len(self.cards) != expected_unique:
            errors.append(f"unique card count {len(self.cards)} != {expected_unique}")

        deck_slots: dict[str, int] = {}
        deck_ordinals: dict[str, list[int]] = {}
        face_count = 0
        ability_count = 0
        oracle_ability_count = 0
        allowed_statuses = {"oracle_only", "registered", "generic", "custom", "unsupported"}
        for card in self.cards:
            if card.card_id != canonical_card_id(card.name):
                errors.append(f"{card.name}: noncanonical card_id {card.card_id!r}")
            if not card.faces:
                errors.append(f"{card.name}: has no faces")
                continue
            if not card.oracle_text.strip():
                errors.append(f"{card.name}: empty Oracle text")
            face_ids = {face.face_id for face in card.faces}
            if len(face_ids) != len(card.faces):
                errors.append(f"{card.name}: duplicate face IDs")
            face_count += len(card.faces)
            for face in card.faces:
                if not face.name or not face.type_line:
                    errors.append(f"{card.name}/{face.face_id}: incomplete face identity")
                if face.mana_value != mana_value(face.mana_cost):
                    errors.append(
                        f"{card.name}/{face.face_id}: mana value {face.mana_value} does not match {face.mana_cost}"
                    )
                if bool(face.power is None) != bool(face.toughness is None):
                    errors.append(f"{card.name}/{face.face_id}: only one P/T component is present")
                if face.loyalty is not None and face.loyalty_variable is not None:
                    errors.append(f"{card.name}/{face.face_id}: fixed and variable loyalty both present")
                if face.loyalty_variable not in {None, "X"}:
                    errors.append(
                        f"{card.name}/{face.face_id}: unsupported loyalty variable {face.loyalty_variable}"
                    )
            ability_ids: set[str] = set()
            for ability in card.abilities:
                ability_count += 1
                oracle_ability_count += ability.origin == "oracle"
                if ability.ability_id in ability_ids:
                    errors.append(f"{card.name}: duplicate ability ID {ability.ability_id}")
                ability_ids.add(ability.ability_id)
                if ability.face_id not in face_ids:
                    errors.append(f"{card.name}/{ability.ability_id}: unknown face {ability.face_id}")
                if ability.support_status not in allowed_statuses:
                    errors.append(
                        f"{card.name}/{ability.ability_id}: invalid support status {ability.support_status}"
                    )
                if ability.support_status in {"registered", "generic", "custom"} and not ability.handler:
                    errors.append(f"{card.name}/{ability.ability_id}: supported ability has no handler")
            replacement_ids: set[str] = set()
            for replacement in card.entry_replacements:
                if replacement.replacement_id in replacement_ids:
                    errors.append(f"{card.name}: duplicate replacement ID {replacement.replacement_id}")
                replacement_ids.add(replacement.replacement_id)
                if replacement.face_id not in face_ids:
                    errors.append(
                        f"{card.name}/{replacement.replacement_id}: unknown face {replacement.face_id}"
                    )
            for occurrence in card.source_decks:
                if occurrence.quantity <= 0:
                    errors.append(f"{card.name}/{occurrence.deck}: nonpositive quantity")
                if occurrence.ordinal < 0:
                    errors.append(f"{card.name}/{occurrence.deck}: negative source ordinal")
                deck_slots[occurrence.deck] = deck_slots.get(occurrence.deck, 0) + occurrence.quantity
                deck_ordinals.setdefault(occurrence.deck, []).append(occurrence.ordinal)

        if expected_slots is not None:
            for deck, expected in expected_slots.items():
                actual = deck_slots.get(deck, 0)
                if actual != expected:
                    errors.append(f"{deck} deck slots {actual} != {expected}")
            extras = sorted(set(deck_slots) - set(expected_slots))
            if extras:
                errors.append(f"unexpected source decks: {', '.join(extras)}")
        for deck, ordinals in deck_ordinals.items():
            # Schema-v1 catalogs emitted before ordinal preservation are still
            # readable so the deterministic generator can bootstrap their
            # replacement.  Once any row supplies ordinals, the deck must supply
            # every ordinal and they must form one contiguous sequence.
            if ordinals and all(ordinal == 0 for ordinal in ordinals):
                continue
            expected_ordinals = list(range(1, len(ordinals) + 1))
            if sorted(ordinals) != expected_ordinals:
                errors.append(f"{deck}: source ordinals are not contiguous and unique")

        return CatalogValidationReport(
            card_count=len(self.cards),
            face_count=face_count,
            ability_count=ability_count,
            oracle_ability_count=oracle_ability_count,
            deck_slot_counts=MappingProxyType(dict(sorted(deck_slots.items()))),
            errors=tuple(errors),
        )

    def validate(
        self,
        expected_unique: Optional[int] = 334,
        expected_slots: Optional[Mapping[str, int]] = EXPECTED_DECK_SLOTS,
    ) -> CatalogValidationReport:
        report = self.validation_report(expected_unique=expected_unique, expected_slots=expected_slots)
        if not report.ok:
            raise CatalogValidationError(report.errors)
        return report


def _face_from_json(row: Mapping[str, Any]) -> CardFace:
    return CardFace(
        face_id=str(row["face_id"]),
        name=str(row["name"]),
        mana_cost=str(row.get("mana_cost", "—")),
        mana_value=int(row.get("mana_value", 0)),
        type_line=str(row["type_line"]),
        supertypes=tuple(str(item) for item in row.get("supertypes", ())),
        types=tuple(str(item) for item in row.get("types", ())),
        subtypes=tuple(str(item) for item in row.get("subtypes", ())),
        oracle_text=str(row.get("oracle_text", "")),
        colors=tuple(str(item) for item in row.get("colors", ())),
        power=None if row.get("power") is None else int(row["power"]),
        toughness=None if row.get("toughness") is None else int(row["toughness"]),
        loyalty=None if row.get("loyalty") is None else int(row["loyalty"]),
        loyalty_variable=None
        if row.get("loyalty_variable") is None
        else str(row["loyalty_variable"]),
        keywords=tuple(str(item) for item in row.get("keywords", ())),
    )


def _ability_from_json(row: Mapping[str, Any]) -> AbilitySpec:
    return AbilitySpec(
        ability_id=str(row["ability_id"]),
        face_id=str(row["face_id"]),
        origin=str(row["origin"]),
        kind=str(row["kind"]),
        zone=str(row["zone"]),
        timing=str(row["timing"]),
        rules_text=str(row.get("rules_text", "")),
        event=None if row.get("event") is None else str(row["event"]),
        optional=bool(row.get("optional", False)),
        mana_ability=bool(row.get("mana_ability", False)),
        uses_stack=bool(row.get("uses_stack", True)),
        cost_text=None if row.get("cost_text") is None else str(row["cost_text"]),
        handler=None if row.get("handler") is None else str(row["handler"]),
        support_status=str(row.get("support_status", "oracle_only")),
    )


def _replacement_from_json(row: Mapping[str, Any]) -> EntryReplacementSpec:
    parameters = row.get("parameters", {})
    if not isinstance(parameters, Mapping):
        raise TypeError(f"replacement parameters must be an object, got {type(parameters).__name__}")
    return EntryReplacementSpec(
        replacement_id=str(row["replacement_id"]),
        face_id=str(row["face_id"]),
        kind=str(row["kind"]),
        event=str(row.get("event", "enter_battlefield")),
        rules_text=str(row.get("rules_text", "")),
        optional=bool(row.get("optional", False)),
        parameters=_freeze_json(dict(parameters)),
        handler=None if row.get("handler") is None else str(row["handler"]),
        support_status=str(row.get("support_status", "catalogued")),
    )


def _card_from_json(row: Mapping[str, Any]) -> CardDefinition:
    mana_row = row.get("mana", {})
    land_row = row.get("land")
    return CardDefinition(
        card_id=str(row["card_id"]),
        name=str(row["name"]),
        oracle_text=str(row.get("oracle_text", "")),
        color_identity=tuple(str(item) for item in row.get("color_identity", ())),
        faces=tuple(_face_from_json(item) for item in row.get("faces", ())),
        abilities=tuple(_ability_from_json(item) for item in row.get("abilities", ())),
        entry_replacements=tuple(
            _replacement_from_json(item) for item in row.get("entry_replacements", ())
        ),
        mana=ManaMetadata(
            is_mana_source=bool(mana_row.get("is_mana_source", False)),
            colors=tuple(str(item) for item in mana_row.get("colors", ())),
            source_kinds=tuple(str(item) for item in mana_row.get("source_kinds", ())),
            production_rule=str(mana_row.get("production_rule", "none")),
            base_amount=None if mana_row.get("base_amount") is None else int(mana_row["base_amount"]),
            variable_output=bool(mana_row.get("variable_output", False)),
        ),
        land=None
        if land_row is None
        else LandMetadata(
            classifications=tuple(str(item) for item in land_row.get("classifications", ())),
            fetch_types=tuple(str(item) for item in land_row.get("fetch_types", ())),
        ),
        source_decks=tuple(
            DeckOccurrence(
                deck=str(item["deck"]),
                quantity=int(item["quantity"]),
                ordinal=int(item.get("ordinal", 0)),
            )
            for item in row.get("source_decks", ())
        ),
    )


def catalog_from_payload(payload: Mapping[str, Any], *, validate: bool = True) -> CardCatalog:
    catalog = CardCatalog(
        schema_version=int(payload.get("schema_version", 0)),
        cards=tuple(_card_from_json(row) for row in payload.get("cards", ())),
        source=_freeze_json(dict(payload.get("source", {}))),
        audit=_freeze_json(dict(payload.get("audit", {}))),
    )
    if validate:
        catalog.validate()
    return catalog


@lru_cache(maxsize=8)
def _load_catalog_cached(path_text: str, validate: bool) -> CardCatalog:
    path = Path(path_text)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise TypeError(f"catalog root must be an object, got {type(payload).__name__}")
    return catalog_from_payload(payload, validate=validate)


def load_catalog(path: Optional[Path | str] = None, *, validate: bool = True) -> CardCatalog:
    """Load and cache an immutable catalog from disk."""

    resolved = Path(path or DEFAULT_CATALOG_PATH).resolve()
    return _load_catalog_cached(str(resolved), validate)


def clear_catalog_cache() -> None:
    """Clear loader state for generator and test processes that replace a file."""

    _load_catalog_cached.cache_clear()


__all__ = [
    "AbilitySpec",
    "CATALOG_SCHEMA_VERSION",
    "CardCatalog",
    "CardDefinition",
    "CardFace",
    "CatalogValidationError",
    "CatalogValidationReport",
    "DEFAULT_CATALOG_PATH",
    "DeckOccurrence",
    "EntryReplacementSpec",
    "EXPECTED_DECK_SLOTS",
    "LandMetadata",
    "ManaMetadata",
    "canonical_card_id",
    "catalog_from_payload",
    "clear_catalog_cache",
    "load_catalog",
    "mana_value",
]
