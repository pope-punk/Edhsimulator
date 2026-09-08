"""Catalog-driven event and trigger discovery primitives.

This module deliberately stops before resolution.  A rules event is an immutable
description of something that happened; catalog ability specifications subscribe to
event kinds; registered Python builders turn matching specifications into the trigger
records already understood by :class:`ManualGame`.  Strategy notes and roles are not
accepted by any API in this module.

The split permits the existing exact handlers to migrate incrementally without
changing APNAP ordering, priority, or stack resolution.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable, Mapping, Optional, Protocol, Sequence


class EventKind(str, Enum):
    PERMANENT_ENTERED = "permanent_entered"
    PERMANENT_LEFT = "permanent_left"
    PERMANENT_DIED = "permanent_died"
    ENCHANTMENT_EVENT = "enchantment_entered_or_room_unlocked"
    LAND_ENTERED = "land_entered"
    CARD_DRAWN = "card_drawn"
    LIFE_GAINED = "life_gained"
    LIFE_LOST = "life_lost"
    COUNTERS_ADDED = "counters_added"
    SPELL_CAST = "spell_cast"
    PHASE_BEGAN = "phase_began"
    ATTACKERS_DECLARED = "attackers_declared"
    BLOCKERS_DECLARED = "blockers_declared"
    DAMAGE_DEALT = "damage_dealt"


@dataclass(frozen=True)
class RuleEvent:
    kind: EventKind
    active_player: str
    affected_player: Optional[str] = None
    source_uid: Optional[str] = None
    source_name: Optional[str] = None
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EventSource:
    """One visible rules object whose abilities may observe an event."""

    controller: str
    card_name: str
    uid: Optional[str] = None
    zone: str = "battlefield"


@dataclass(frozen=True)
class CatalogAbilityMatch:
    """One card-owned ability whose subscription matches a rules event.

    A match is discovery metadata, not a stack object.  In particular, audit
    callers may request Oracle-only rows while live resolution continues through
    the existing exact handlers during the incremental migration.
    """

    event: RuleEvent
    source: EventSource
    spec: Any


@dataclass(frozen=True)
class TriggerCandidate:
    controller: str
    source: str
    ability_id: str
    label: str
    handler: str
    source_uid: Optional[str] = None
    targets: tuple[Any, ...] = ()
    payload: Mapping[str, Any] = field(default_factory=dict)
    optional: bool = False

    def as_referee_trigger(self, resolver: Callable[[], Any]) -> dict[str, Any]:
        return {
            "controller": self.controller,
            "source": self.source,
            "label": self.label,
            "targets": list(self.targets),
            "resolve": resolver,
            "ability_id": self.ability_id,
            "source_uid": self.source_uid,
        }


class EventCatalog(Protocol):
    def abilities_for_event(
        self,
        card_name: str,
        event: str,
        zone: str = "battlefield",
        *,
        executable_only: bool = True,
    ) -> Sequence[Any]: ...


TriggerBuilder = Callable[[Any, RuleEvent, EventSource, Any], Optional[TriggerCandidate | Iterable[TriggerCandidate]]]


class TriggerBuilderRegistry:
    """Named executable boundary for catalog ability handler references."""

    def __init__(self) -> None:
        self._builders: dict[str, TriggerBuilder] = {}

    def register(self, name: str, builder: TriggerBuilder) -> None:
        if not name or name in self._builders:
            raise ValueError(f"duplicate or empty trigger builder: {name!r}")
        self._builders[name] = builder

    def decorator(self, name: str):
        def wrap(builder: TriggerBuilder) -> TriggerBuilder:
            self.register(name, builder)
            return builder
        return wrap

    def get(self, name: str) -> Optional[TriggerBuilder]:
        return self._builders.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._builders))


class CatalogEventDispatcher:
    """Discover candidates from card-owned subscriptions; never resolve them."""

    def __init__(self, catalog: EventCatalog, builders: TriggerBuilderRegistry) -> None:
        self.catalog = catalog
        self.builders = builders
        self.unhandled: list[dict[str, str]] = []

    @staticmethod
    def _field(spec: Any, name: str, default: Any = None) -> Any:
        if isinstance(spec, Mapping):
            return spec.get(name, default)
        return getattr(spec, name, default)

    def discover(
        self,
        event: RuleEvent,
        sources: Iterable[EventSource],
        *,
        executable_only: bool = True,
    ) -> list[CatalogAbilityMatch]:
        """Return catalog subscriptions without constructing or resolving triggers.

        ``executable_only=False`` is the safe migration/audit path: it proves that
        an exact legacy trigger corresponds to card-owned catalog metadata without
        accidentally making an Oracle-only clause executable.
        """

        matches: list[CatalogAbilityMatch] = []
        for source in sources:
            try:
                specs = self.catalog.abilities_for_event(
                    source.card_name,
                    event.kind.value,
                    source.zone,
                    executable_only=executable_only,
                )
            except KeyError:
                # Tokens and copied names need not have a parent catalog record.
                continue
            matches.extend(CatalogAbilityMatch(event, source, spec) for spec in specs)
        return matches

    def collect(self, game: Any, event: RuleEvent, sources: Iterable[EventSource]) -> list[TriggerCandidate]:
        candidates: list[TriggerCandidate] = []
        for match in self.discover(event, sources):
            source, spec = match.source, match.spec
            handler = str(self._field(spec, "handler", ""))
            ability_id = str(self._field(spec, "ability_id", self._field(spec, "id", "")))
            builder = self.builders.get(handler)
            if builder is None:
                self.unhandled.append({
                    "card": source.card_name,
                    "ability_id": ability_id,
                    "event": event.kind.value,
                    "handler": handler,
                })
                continue
            built = builder(game, event, source, spec)
            if built is None:
                continue
            if isinstance(built, TriggerCandidate):
                candidates.append(built)
            else:
                candidates.extend(built)
        return candidates


def group_candidates_by_controller(candidates: Iterable[TriggerCandidate]) -> dict[str, list[TriggerCandidate]]:
    """Small audit helper; referee APNAP code still owns ordering decisions."""
    grouped: dict[str, list[TriggerCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.controller].append(candidate)
    return dict(grouped)
