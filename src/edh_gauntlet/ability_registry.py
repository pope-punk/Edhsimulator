"""Catalog-backed action inventory for the exact four-deck manual pod.

The registry answers *when* and *from which zone* an ability must be exposed.  The
referee owns legality, announcement-time choices, costs, stack placement, and exact
resolution.  The canonical card catalog now owns the registrations themselves;
this module is the stable compatibility API consumed by the referee and reports.
"""
from __future__ import annotations

from dataclasses import dataclass

from .catalog import AbilitySpec, load_catalog


@dataclass(frozen=True)
class AbilityRegistration:
    kind: str
    zone: str                 # battlefield, hand, graveyard
    timing: str               # priority, sorcery, land_play
    label: str


def reg(kind, zone, timing, label):
    """Construct a legacy-shaped registration.

    ``reg`` remains public for compatibility, but the runtime inventory below is
    projected from :class:`~edh_gauntlet.catalog.AbilitySpec` rows rather than
    being authored independently in this module.
    """

    return AbilityRegistration(kind, zone, timing, label)


_LEGACY_HANDLER_PREFIX = "legacy:"


def _registration_from_spec(spec: AbilitySpec) -> AbilityRegistration:
    """Project one canonical registry ability onto the stable referee API."""

    handler = spec.handler or ""
    if not handler.startswith(_LEGACY_HANDLER_PREFIX):
        raise ValueError(
            f"Catalog registry ability {spec.ability_id!r} has no legacy handler reference"
        )
    kind = handler.removeprefix(_LEGACY_HANDLER_PREFIX)
    if not kind:
        raise ValueError(f"Catalog registry ability {spec.ability_id!r} has an empty handler kind")
    return reg(kind, spec.zone, spec.timing, spec.rules_text)


def _catalog_ability_projection() -> dict[str, tuple[AbilityRegistration, ...]]:
    """Generate card registrations from ``origin='registry'`` catalog rows."""

    catalog = load_catalog()
    result: dict[str, tuple[AbilityRegistration, ...]] = {}
    for card in catalog:
        specs = tuple(ability for ability in card.abilities if ability.origin == "registry")
        if specs:
            result[card.name] = tuple(_registration_from_spec(spec) for spec in specs)
    return result


# Public compatibility projection.  This is deliberately a normal dictionary:
# callers historically use membership, ``get``, ``values``, and per-card tuple
# ordering.  Its contents have one source of truth: data/catalog/cards.json.
CARD_ABILITIES = _catalog_ability_projection()


def registrations_for(card_name, zone, include_sorcery=True, include_priority=True, include_land_play=True):
    allowed = set()
    if include_sorcery:
        allowed.add("sorcery")
    if include_priority:
        allowed.add("priority")
    if include_land_play:
        allowed.add("land_play")
    return tuple(
        row
        for row in CARD_ABILITIES.get(card_name, ())
        if row.zone == zone and row.timing in allowed
    )
