"""Read-only pilot inspection and context rendering.

The referee owns rules truth and runtime mutation.  This module deliberately does
neither: it reads visible runtime objects, crosswalks them to the canonical card
catalog and the active pilot's deck profile, and returns JSON-serializable views.

Inspection is out-of-band.  None of the APIs below consume priority, allocate a
decision id, advance RNG, or write to the game, catalog, or strategy state.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, fields, is_dataclass
from difflib import get_close_matches
import json
import re
import shlex
import unicodedata
from typing import Any, Iterable, Mapping, Optional


class InspectionError(ValueError):
    """Base class for a malformed or unavailable inspection."""


class ObjectNotVisible(InspectionError):
    """The requested uid is absent or not visible to the acting pilot."""


class UnknownDeckCard(InspectionError):
    """The requested card is not part of the acting pilot's deck profile."""


class UnknownRole(InspectionError):
    """The requested strategic role is not represented in the pilot's deck."""


class UnknownPackage(InspectionError):
    """The requested strategic package is not present in the pilot's deck."""


PUBLIC_METADATA_KEYS = frozenset({
    "additional_enchantment", "battle_defense", "devotion_on", "door",
    "doors_unlocked", "eot_pt_penalty", "everything_types", "face",
    "fading", "is_land", "land_face", "land_types", "level",
    "lore", "march_animated", "march_power", "march_toughness",
    "mutated", "noncreature_token", "phased_out", "room_doors",
    "saga_chapter", "sage_animated", "transformed", "unlocked_rooms",
    "urza_mana",
})

ZONE_ORDER = (
    "command", "stack", "battlefield", "hand", "graveyard", "exile",
    "library",
)

ACTIONABLE_ZONES = frozenset({"command", "stack", "battlefield", "hand", "graveyard", "exile"})
CASTABLE_ZONES = frozenset({"command", "hand", "graveyard", "exile"})
ROLE_RESULT_GUIDANCE_LIMIT = 8
ROLE_RESULT_CATALOG_LIMIT = 12

# This exact grammar is delivered once per compatible pilot session and on changes. Query
# strings are passed as individual ``pilot_session --inspect`` arguments; the
# optional leading word ``inspect`` remains accepted for interactive use.
INSPECTION_GRAMMAR = (
    'object UID',
    'card "NAME"',
    'deck [zone=ZONE]',
    'roles',
    'role "ROLE NAME" [zone=ZONE] [mv<=N] [castable_now=true]',
    'package "PACKAGE NAME" [zone=ZONE]',
    'messageboard',
)

INSPECTION_LEGEND = (
    "Inspection grammar (batch multiple --inspect queries; inspection does not pass priority or consume a decision):\n"
    + "\n".join(INSPECTION_GRAMMAR)
    + "\nLibrary results are unordered and never expose future draw order. "
      "For an explicitly scoped role/package query, append detail=full for fuller records."
)


@dataclass(frozen=True)
class _ParsedQuery:
    kind: str
    value: str = ""
    zone: Optional[str] = None
    max_mana_value: Optional[int] = None
    castable_now: bool = False
    full_detail: bool = False
    normalized: str = ""


@dataclass(frozen=True)
class _VisibleRef:
    uid: str
    zone: str
    owner: str
    controller: str
    obj: Any
    name: Optional[str]
    identity_visible: bool
    stack_position: Optional[int] = None


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return list(value.values())
    if isinstance(value, (str, bytes)):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]


def _json_value(value: Any, _seen: Optional[set[int]] = None) -> Any:
    """Convert catalog/profile dataclasses to plain JSON values.

    Callable resolver objects are intentionally represented by their stable name;
    inspection never invokes them.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if callable(value):
        return getattr(value, "__name__", type(value).__name__)
    if _seen is None:
        _seen = set()
    ident = id(value)
    if ident in _seen:
        return "<recursive>"
    if isinstance(value, Mapping):
        _seen.add(ident)
        result = {str(key): _json_value(item, _seen) for key, item in value.items()
                  if not str(key).startswith("_")}
        _seen.remove(ident)
        return result
    if isinstance(value, (set, frozenset)):
        return sorted((_json_value(item, _seen) for item in value), key=str)
    if isinstance(value, (list, tuple)):
        _seen.add(ident)
        result = [_json_value(item, _seen) for item in value]
        _seen.remove(ident)
        return result
    if is_dataclass(value):
        _seen.add(ident)
        result = {
            item.name: _json_value(getattr(value, item.name), _seen)
            for item in fields(value) if not item.name.startswith("_")
        }
        _seen.remove(ident)
        return result
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_value(value.to_dict(), _seen)
    if hasattr(value, "__dict__"):
        _seen.add(ident)
        result = {
            key: _json_value(item, _seen)
            for key, item in vars(value).items()
            if not key.startswith("_") and not callable(item)
        }
        _seen.remove(ident)
        return result
    return str(value)


def _slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", plain.casefold()).strip("-")


def _object_metadata(obj: Any) -> Mapping[str, Any]:
    metadata = _field(obj, "metadata", {})
    return metadata if isinstance(metadata, Mapping) else {}


def _object_uid(obj: Any, fallback: str = "") -> str:
    return str(_field(obj, "uid", fallback))


def _object_name(obj: Any) -> Optional[str]:
    name = _field(obj, "name")
    if name:
        return str(name)
    definition = _field(obj, "d")
    name = _field(definition, "name")
    if name:
        return str(name)
    card = _field(obj, "card")
    return str(card) if card else None


def _identity_is_visible(obj: Any, actor: str, owner: str, controller: str,
                         zone: str) -> bool:
    metadata = _object_metadata(obj)
    known_to = metadata.get("known_to", _field(obj, "known_to"))
    visible_to = metadata.get("visible_to", _field(obj, "visible_to"))
    if known_to is not None:
        return actor in set(_items(known_to))
    if visible_to is not None:
        return actor in set(_items(visible_to))
    hidden = bool(
        metadata.get("identity_hidden") or metadata.get("hidden_identity") or
        metadata.get("hidden") or _field(obj, "identity_hidden", False) or
        _field(obj, "hidden_identity", False)
    )
    face_down = bool(metadata.get("face_down") or _field(obj, "face_down", False))
    if hidden:
        return False
    if not face_down:
        return True
    # A player can normally inspect a face-down permanent they control.  A
    # face-down card in exile needs an explicit known_to/visible_to grant.
    return zone == "battlefield" and actor == controller


def _player(game: Any, actor: str) -> Any:
    players = _field(game, "players", {})
    if not isinstance(players, Mapping) or actor not in players:
        raise InspectionError(f"Unknown pilot/deck {actor!r}")
    return players[actor]


def _player_name(player: Any, fallback: str = "") -> str:
    return str(_field(player, "name", fallback))


def _load_default_catalog() -> Any:
    try:
        from .catalog import load_catalog
        return load_catalog()
    except (ImportError, FileNotFoundError, ValueError):
        return None


def _load_default_strategy() -> Any:
    try:
        from .strategy import load_strategy_state
        return load_strategy_state()
    except (ImportError, FileNotFoundError, ValueError):
        return None


class InspectionService:
    """Pure read adapter over a game, a catalog, and strategy profiles.

    Catalog and strategy values use structural/duck typing so the service can be
    constructed with the project's frozen models, plain mappings, or test fakes.
    """

    def __init__(self, catalog: Any = None, strategy: Any = None,
                 *, load_defaults: bool = True,
                 public_metadata_keys: Iterable[str] = PUBLIC_METADATA_KEYS):
        self.catalog = catalog if catalog is not None else (_load_default_catalog() if load_defaults else None)
        self.strategy = strategy if strategy is not None else (_load_default_strategy() if load_defaults else None)
        self.public_metadata_keys = frozenset(public_metadata_keys)

    # ------------------------------------------------------------------
    # Catalog/profile adapters
    # ------------------------------------------------------------------
    def canonical_card_id(self, name: str) -> str:
        try:
            from .catalog import canonical_card_id
            return canonical_card_id(name)
        except ImportError:
            try:
                from .strategy import canonical_card_id
                return canonical_card_id(name)
            except ImportError:
                return _slug(name)

    def _catalog_get(self, name_or_id: str) -> Any:
        if not name_or_id:
            return None
        catalog = self.catalog
        if catalog is not None:
            getter = getattr(catalog, "get", None)
            if callable(getter):
                found = getter(name_or_id)
                if found is not None:
                    return found
            if isinstance(catalog, Mapping):
                if name_or_id in catalog:
                    return catalog[name_or_id]
                target = str(name_or_id).casefold()
                for key, value in catalog.items():
                    if str(key).casefold() == target or str(_field(value, "name", "")).casefold() == target:
                        return value
            for attr in ("by_id", "by_name", "cards"):
                values = getattr(catalog, attr, None)
                if isinstance(values, Mapping):
                    found = values.get(name_or_id)
                    if found is None:
                        found = next((value for key, value in values.items()
                                      if str(key).casefold() == str(name_or_id).casefold()), None)
                    if found is not None:
                        return found
        # Compatibility fallback while the canonical catalog is being installed.
        try:
            from .engine import CARDDEF
            if name_or_id in CARDDEF:
                return CARDDEF[name_or_id]
            target = str(name_or_id).casefold()
            return next((card for name, card in CARDDEF.items()
                         if name.casefold() == target or self.canonical_card_id(name) == name_or_id), None)
        except ImportError:
            return None

    def _catalog_record(self, name_or_id: str) -> Optional[dict[str, Any]]:
        definition = self._catalog_get(name_or_id)
        if definition is None:
            return None
        record = _json_value(definition)
        if not isinstance(record, dict):
            record = {"value": record}
        name = str(_field(definition, "name", record.get("name", name_or_id)))
        record.setdefault("card_id", str(_field(definition, "card_id", self.canonical_card_id(name))))
        record.setdefault("name", name)
        # Legacy CardDef calls this field `text`; expose the canonical spelling
        # without deleting the compatibility field.
        oracle = _field(definition, "oracle_text", _field(definition, "text"))
        if oracle is not None:
            record.setdefault("oracle_text", str(oracle))
        for source_name, output_name in (
            ("mana_cost", "mana_cost"), ("type_line", "type_line"),
            ("mana_value", "mana_value"), ("mv", "mana_value"),
        ):
            value = _field(definition, source_name)
            if value is not None:
                record.setdefault(output_name, _json_value(value))
        return record

    def _profile(self, actor: str) -> Any:
        state = self.strategy
        if state is None:
            return None
        deck_method = getattr(state, "deck", None)
        if callable(deck_method):
            for key in (actor, _slug(actor)):
                try:
                    profile = deck_method(key)
                except (KeyError, ValueError):
                    profile = None
                if profile is not None:
                    return profile
        decks = _field(state, "decks", {})
        for profile in _items(decks):
            identifiers = {
                str(_field(profile, "deck_id", "")).casefold(),
                str(_field(profile, "label", "")).casefold(),
            }
            if actor.casefold() in identifiers or _slug(actor) in {_slug(value) for value in identifiers}:
                return profile
        return None

    @staticmethod
    def _profile_entries(profile: Any) -> list[Any]:
        return _items(_field(profile, "cards", ()))

    def _entry(self, profile: Any, card_ref: str) -> Any:
        if profile is None:
            return None
        for method_name in ("card_by_id", "card_by_name"):
            method = getattr(profile, method_name, None)
            if callable(method):
                try:
                    found = method(card_ref)
                except (KeyError, ValueError):
                    found = None
                if found is not None:
                    return found
        wanted = str(card_ref).casefold()
        wanted_slug = _slug(card_ref)
        for entry in self._profile_entries(profile):
            if (
                str(_field(entry, "card_id", "")).casefold() == wanted or
                str(_field(entry, "card_name", "")).casefold() == wanted or
                _slug(str(_field(entry, "card_name", ""))) == wanted_slug
            ):
                return entry
        return None

    @staticmethod
    def _entry_role_ids(entry: Any) -> tuple[str, ...]:
        result = []
        for assignment in _items(_field(entry, "roles", ())):
            role_id = assignment if isinstance(assignment, str) else _field(assignment, "role_id")
            if role_id:
                result.append(str(role_id))
        return tuple(dict.fromkeys(result))

    @staticmethod
    def _entry_role_assignments(entry: Any) -> list[dict[str, Any]]:
        assignments = []
        for value in _items(_field(entry, "roles", ())):
            if isinstance(value, str):
                assignments.append({"role_id": value, "source": "seed", "revision": 1})
                continue
            role_id = _field(value, "role_id")
            if not role_id:
                continue
            row = {
                "role_id": str(role_id),
                "source": str(_field(value, "source", "seed")),
                "revision": _field(value, "revision", 1),
            }
            source_game = _field(value, "source_game")
            if source_game is not None:
                row["source_game"] = source_game
            confidence = _field(value, "confidence")
            if confidence is not None:
                row["confidence"] = confidence
            assignments.append(row)
        return assignments

    def _role_definitions(self) -> list[Any]:
        return _items(_field(self.strategy, "roles", ())) if self.strategy is not None else []

    def _role_definition(self, role_ref: str) -> Any:
        wanted = str(role_ref).casefold()
        wanted_slug = _slug(role_ref)
        matches = []
        for role in self._role_definitions():
            identifiers = {
                str(_field(role, "role_id", "")),
                str(_field(role, "label", "")),
                *[str(alias) for alias in _items(_field(role, "aliases", ()))],
            }
            if wanted in {value.casefold() for value in identifiers} or wanted_slug in {_slug(value) for value in identifiers}:
                matches.append(role)
        if not matches:
            return None
        # A merged role keeps its old ID/label as aliases on the active target.
        # Prefer that active target over the retired vocabulary tombstone.
        return sorted(matches,key=lambda role:(
            0 if str(_field(role,"status","active"))=="active" else 1,
            str(_field(role,"role_id","")),
        ))[0]

    def _resolve_role_id(self, profile: Any, role_ref: str) -> str:
        definition = self._role_definition(role_ref)
        candidate = str(_field(definition, "role_id", role_ref))
        represented = {role_id for entry in self._profile_entries(profile)
                       for role_id in self._entry_role_ids(entry)}
        if candidate in represented:
            return candidate
        wanted = _slug(role_ref)
        match = next((role_id for role_id in represented if _slug(role_id) == wanted), None)
        if match:
            return match
        available = []
        for role_id in sorted(represented):
            role = self._role_definition(role_id)
            available.append((role_id, str(_field(role, "label", role_id))))
        choices = [label for _, label in available]
        close = get_close_matches(str(role_ref), choices, n=3, cutoff=0.3)
        suggested = close or choices[:3]
        commands = "; ".join(f'role {json.dumps(label, ensure_ascii=False)}' for label in suggested)
        suffix = f" Try: {commands}" if commands else " Try: roles"
        raise UnknownRole(
            f"Role {role_ref!r} is not represented in {_field(profile, 'label', 'this deck')}." + suffix
        )

    def _package(self, profile: Any, package_ref: str) -> Any:
        wanted = str(package_ref).casefold()
        wanted_slug = _slug(package_ref)
        for package in _items(_field(profile, "packages", ())):
            identifiers = {
                str(_field(package, "package_id", "")),
                str(_field(package, "label", "")),
            }
            if wanted in {value.casefold() for value in identifiers} or wanted_slug in {_slug(value) for value in identifiers}:
                return package
        packages = sorted(
            (str(_field(value, "label", _field(value, "package_id", "")))
             for value in _items(_field(profile, "packages", ()))),
            key=str.casefold,
        )
        close = get_close_matches(str(package_ref), packages, n=3, cutoff=0.3) or packages[:3]
        commands = "; ".join(f'package {json.dumps(label, ensure_ascii=False)}' for label in close)
        suffix = f" Try: {commands}" if commands else ""
        raise UnknownPackage(
            f"Package {package_ref!r} is not present in {_field(profile, 'label', 'this deck')}." + suffix
        )

    # ------------------------------------------------------------------
    # Runtime visibility
    # ------------------------------------------------------------------
    def _public_refs(self, game: Any, actor: str) -> list[_VisibleRef]:
        _player(game, actor)
        players = _field(game, "players", {})
        refs: list[_VisibleRef] = []
        for fallback_name, player in players.items():
            owner_name = _player_name(player, str(fallback_name))
            for permanent in list(_field(player, "battlefield", ()) or ()):
                owner = str(_field(permanent, "owner", owner_name))
                controller = str(_field(permanent, "controller", owner_name))
                refs.append(_VisibleRef(
                    _object_uid(permanent), "battlefield", owner, controller,
                    permanent, _object_name(permanent),
                    _identity_is_visible(permanent, actor, owner, controller, "battlefield"),
                ))
            for zone in ("graveyard", "exile"):
                for card in list(_field(player, zone, ()) or ()):
                    owner = str(_field(card, "owner", owner_name))
                    refs.append(_VisibleRef(
                        _object_uid(card), zone, owner, owner_name, card,
                        _object_name(card),
                        _identity_is_visible(card, actor, owner, owner_name, zone),
                    ))
            commander = _field(player, "commander")
            if commander is not None:
                owner = str(_field(commander, "owner", owner_name))
                refs.append(_VisibleRef(
                    _object_uid(commander), "command", owner, owner_name,
                    commander, _object_name(commander),
                    _identity_is_visible(commander, actor, owner, owner_name, "command"),
                ))
            if owner_name == actor:
                for card in list(_field(player, "hand", ()) or ()):
                    owner = str(_field(card, "owner", owner_name))
                    refs.append(_VisibleRef(
                        _object_uid(card), "hand", owner, actor, card,
                        _object_name(card),
                        _identity_is_visible(card, actor, owner, actor, "hand"),
                    ))
        for position, item in enumerate(list(_field(game, "stack", ()) or ())):
            owner = str(_field(item, "owner", _field(item, "actor", "")))
            controller = str(_field(item, "controller", _field(item, "actor", owner)))
            fallback_uid = f"stack:{position}"
            refs.append(_VisibleRef(
                _object_uid(item, fallback_uid), "stack", owner, controller,
                item, _object_name(item),
                _identity_is_visible(item, actor, owner, controller, "stack"),
                position,
            ))
        return refs

    def inspectable_object_index(self, game: Any, actor: str) -> list[dict[str, Any]]:
        """Compact index of public objects plus the actor's hand.

        Libraries and opposing hands never appear here.  The actor's decklist is
        browsed through :meth:`inspect_deck`, which exposes no physical library uid.
        """
        indexed = []
        for ref in self._public_refs(game, actor):
            display_name = ref.name if ref.identity_visible else "Unknown face-down card"
            catalog_id = None
            if ref.identity_visible and ref.name:
                definition = self._catalog_get(ref.name)
                catalog_id = str(_field(definition, "card_id", self.canonical_card_id(ref.name)))
            row = {
                "uid": ref.uid,
                "name": display_name,
                "zone": ref.zone,
                "owner": ref.owner,
                "controller": ref.controller,
                "catalog_id": catalog_id,
                "identity_visible": ref.identity_visible,
            }
            if ref.stack_position is not None:
                row["stack_position_from_bottom"] = ref.stack_position
            indexed.append(row)
        order = {zone: index for index, zone in enumerate(ZONE_ORDER)}
        return sorted(indexed, key=lambda row: (
            order.get(row["zone"], 99),
            row.get("stack_position_from_bottom", -1),
            row["controller"], row["name"], row["uid"],
        ))

    def _public_metadata(self, obj: Any) -> dict[str, Any]:
        metadata = _object_metadata(obj)
        return {
            key: _json_value(metadata[key])
            for key in sorted(self.public_metadata_keys)
            if key in metadata
        }

    def _live_state(self, ref: _VisibleRef) -> dict[str, Any]:
        obj = ref.obj
        state: dict[str, Any] = {
            "uid": ref.uid,
            "name": ref.name if ref.identity_visible else "Unknown face-down card",
            "zone": ref.zone,
            "owner": ref.owner,
            "controller": ref.controller,
            "identity_visible": ref.identity_visible,
        }
        if ref.zone == "battlefield":
            for attr in (
                "tapped", "summoning_sick", "attached_to", "token",
                "entered_turn",
            ):
                value = _field(obj, attr)
                if value is not None:
                    state[attr] = _json_value(value)
            state["counters"] = _json_value(_field(obj, "counters", {}))
            if not ref.identity_visible:
                # Engine permanents retain their real printed/runtime fields
                # while face down.  Those fields are referee truth, not public
                # information: base P/T, keywords, copy identity, and metadata
                # such as a selected face can all fingerprint the hidden card.
                # Keep only state that is observable on the physical object.
                state["face_down"] = True
                if bool(_object_metadata(obj).get("phased_out")):
                    state["phased_out"] = True
                return state
            for attr in ("base_power", "base_toughness"):
                value = _field(obj, attr)
                if value is not None:
                    state[attr] = _json_value(value)
            state["keywords"] = sorted(str(keyword) for keyword in _items(_field(obj, "keywords", ())))
            copy_of = _field(obj, "copy_of")
            if copy_of:
                state["copy_of"] = str(copy_of)
            metadata = self._public_metadata(obj)
            if metadata:
                state["public_metadata"] = metadata
        elif ref.zone == "stack":
            state["stack_position_from_bottom"] = ref.stack_position
            if ref.identity_visible:
                for attr in (
                    "ability_kind", "ability_label", "trigger_event",
                    "trigger_label", "target_uids",
                ):
                    value = _field(obj, attr)
                    if value is not None:
                        state[attr] = _json_value(value)
        return state

    def inspect_object(self, game: Any, actor: str, object_uid: str) -> dict[str, Any]:
        ref = next((item for item in self._public_refs(game, actor)
                    if item.uid == str(object_uid)), None)
        if ref is None:
            # Do not distinguish an invalid uid from an opponent's hidden object.
            visible_uids = sorted(item.uid for item in self._public_refs(game, actor))
            close = get_close_matches(str(object_uid), visible_uids, n=3, cutoff=0.25) or visible_uids[:3]
            suggestions = "; ".join(f"object {uid}" for uid in close)
            suffix = f" Try: {suggestions}" if suggestions else " Try: object UID"
            raise ObjectNotVisible(
                f"Object {object_uid!r} was not found or is not visible to {actor}." + suffix
            )
        result: dict[str, Any] = {
            "kind": "object",
            "actor": actor,
            "object": self._live_state(ref),
            "parent_card": None,
            "effective_parent_card": None,
            "pilot_memory": [],
        }
        if ref.identity_visible and ref.name:
            result["parent_card"] = self._catalog_record(ref.name)
            copy_of = _field(ref.obj, "copy_of")
            if copy_of and str(copy_of) != ref.name:
                result["effective_parent_card"] = self._catalog_record(str(copy_of))
            result["pilot_memory"] = self.pilot_memory(actor, [ref.name])
        return self._finish(result)

    # ------------------------------------------------------------------
    # Strategy memory -- text only, never executable
    # ------------------------------------------------------------------
    def pilot_memory(self, actor: str, card_refs: Iterable[str],
                     contexts: Iterable[str] = ()) -> list[dict[str, Any]]:
        profile = self._profile(actor)
        if profile is None:
            return []
        requested_contexts = {str(context).casefold() for context in contexts}
        result = []
        seen = set()
        for card_ref in card_refs:
            entry = self._entry(profile, str(card_ref))
            if entry is None:
                continue
            card_id = str(_field(entry, "card_id", self.canonical_card_id(str(card_ref))))
            card_name = str(_field(entry, "card_name", card_ref))
            for note in _items(_field(entry, "notes", ())):
                note_contexts = tuple(str(value) for value in _items(_field(note, "contexts", ())))
                if requested_contexts and note_contexts and not requested_contexts.intersection(
                    value.casefold() for value in note_contexts
                ):
                    continue
                note_id = str(_field(note, "note_id", f"{card_id}:{len(result) + 1}"))
                key = (card_id, note_id)
                if key in seen:
                    continue
                seen.add(key)
                result.append({
                    "note_id": note_id,
                    "card_id": card_id,
                    "card_name": card_name,
                    "text": str(_field(note, "text", "")),
                    "source": str(_field(note, "source", "unknown")),
                    "locked": bool(_field(note, "locked", False)),
                    "revision": _field(note, "revision"),
                    "source_game": _field(note, "source_game"),
                    "contexts": list(note_contexts),
                    "confidence": _field(note, "confidence"),
                    "source_cohort": _field(note, "source_cohort"),
                    "source_review": _field(note, "source_review"),
                })
        return result

    def decision_memory(self, actor: str, card_refs: Iterable[str],
                        contexts: Iterable[str] = (), *,
                        hand_card_refs: Iterable[str] = ()) -> list[dict[str, Any]]:
        """Return deterministic card and applicable package notes for a decision.

        ``pilot_memory`` remains the narrow card-query API used by explicit
        inspection.  Decision context has a slightly wider job: a yes/no choice
        can still benefit from a note about a card in hand, and a package note is
        useful when the current options or hand expose that package.  This method
        only assembles inert private text; the referee owns relevance ranking and
        the delivery cap.
        """
        profile = self._profile(actor)
        if profile is None:
            return []

        requested_contexts = {str(context).casefold() for context in contexts}

        def entries_for(refs: Iterable[str]) -> dict[str, Any]:
            entries: dict[str, Any] = {}
            for ref in refs:
                entry = self._entry(profile, str(ref))
                if entry is None:
                    continue
                card_id = str(_field(
                    entry, "card_id", self.canonical_card_id(str(ref))))
                entries[card_id] = entry
            return entries

        current_entries = entries_for(card_refs)
        hand_entries = entries_for(hand_card_refs)
        all_entries = {**hand_entries, **current_entries}
        ordered_refs = [
            str(_field(entry, "card_name", card_id))
            for card_id, entry in sorted(all_entries.items())
        ]
        result = self.pilot_memory(actor, ordered_refs, contexts)
        for note in result:
            note["memory_kind"] = "card"

        visible_ids = set(current_entries) | set(hand_entries)
        for package in sorted(
            _items(_field(profile, "packages", ())),
            key=lambda value: str(_field(value, "package_id", "")),
        ):
            if str(_field(package, "status", "active")) != "active":
                continue
            package_id = str(_field(package, "package_id", ""))
            label = str(_field(package, "label", package_id))
            member_ids = {
                str(_field(member, "card_id", member))
                for member in _items(_field(package, "members", ()))
                if _field(member, "card_id", member)
            }
            current_overlap = member_ids.intersection(current_entries)
            hand_overlap = member_ids.intersection(hand_entries)
            # A package is actionable when a current option is one of its
            # members, or when at least two pieces are already visible in hand.
            if not current_overlap and len(hand_overlap) < 2:
                continue
            applicable_ids = sorted(member_ids.intersection(visible_ids))
            applicable_names = [
                str(_field(all_entries[card_id], "card_name", card_id))
                for card_id in applicable_ids if card_id in all_entries
            ]
            for index, note in enumerate(_items(_field(package, "notes", ())), 1):
                if isinstance(note, str):
                    text = note
                    note_contexts: tuple[str, ...] = ()
                    note_id = f"package:{package_id}:{index}"
                    source = str(_field(package, "source", "unknown"))
                    locked = False
                    revision = _field(package, "revision")
                    source_game = _field(package, "source_game")
                    confidence = None
                else:
                    text = str(_field(note, "text", ""))
                    note_contexts = tuple(
                        str(value) for value in _items(_field(note, "contexts", ())))
                    note_id = str(_field(note, "note_id", f"package:{package_id}:{index}"))
                    source = str(_field(note, "source", _field(package, "source", "unknown")))
                    locked = bool(_field(note, "locked", False))
                    revision = _field(note, "revision", _field(package, "revision"))
                    source_game = _field(note, "source_game", _field(package, "source_game"))
                    confidence = _field(note, "confidence")
                    source_cohort = _field(note, "source_cohort")
                    source_review = _field(note, "source_review")
                if requested_contexts and note_contexts and not requested_contexts.intersection(
                    value.casefold() for value in note_contexts
                ):
                    continue
                if not text:
                    continue
                result.append({
                    "note_id": note_id,
                    "card_id": f"package:{package_id}",
                    "card_name": f"Package: {label}",
                    "text": text,
                    "source": source,
                    "locked": locked,
                    "revision": revision,
                    "source_game": source_game,
                    "contexts": list(note_contexts),
                    "confidence": confidence,
                    "source_cohort": source_cohort if not isinstance(note, str) else None,
                    "source_review": source_review if not isinstance(note, str) else None,
                    "memory_kind": "package",
                    "package_id": package_id,
                    "package_label": label,
                    "applicable_card_ids": applicable_ids,
                    "applicable_card_names": applicable_names,
                    "current_card_ids": sorted(current_overlap),
                })

        # Candidate order must not depend on option order.  The referee applies
        # semantic relevance ranking after this stable assembly.
        return sorted(result, key=lambda note: (
            str(note.get("memory_kind", "card")),
            str(note.get("card_id", "")),
            str(note.get("note_id", "")),
        ))

    def render_pilot_memory(self, actor: str, card_refs: Iterable[str],
                            contexts: Iterable[str] = ()) -> str:
        notes = self.pilot_memory(actor, card_refs, contexts)
        if not notes:
            return ""
        lines = [f"PILOT MEMORY — {actor}"]
        current = None
        for note in notes:
            if note["card_name"] != current:
                current = note["card_name"]
                lines.append(f"\n{current}")
            provenance = note["source"]
            if note["source_game"] is not None:
                provenance += f", game {note['source_game']}"
            if note["locked"]:
                provenance += ", locked"
            lines.append(f"- {note['text']} [{provenance}]")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Runtime deck view
    # ------------------------------------------------------------------
    def _owned_runtime_refs(self, game: Any, actor: str) -> list[_VisibleRef]:
        player = _player(game, actor)
        refs: list[_VisibleRef] = []
        for zone in ("library", "hand", "graveyard", "exile"):
            for card in list(_field(player, zone, ()) or ()):
                owner = str(_field(card, "owner", actor))
                refs.append(_VisibleRef(
                    _object_uid(card), zone, owner, actor, card,
                    _object_name(card),
                    _identity_is_visible(card, actor, owner, actor, zone),
                ))
        commander = _field(player, "commander")
        if commander is not None:
            refs.append(_VisibleRef(
                _object_uid(commander), "command", actor, actor, commander,
                _object_name(commander), True,
            ))
        players = _field(game, "players", {})
        for fallback_name, controller_state in players.items():
            controller = _player_name(controller_state, str(fallback_name))
            for permanent in list(_field(controller_state, "battlefield", ()) or ()):
                if bool(_field(permanent, "token", False)):
                    continue
                owner = str(_field(permanent, "owner", controller))
                if owner != actor:
                    continue
                refs.append(_VisibleRef(
                    _object_uid(permanent), "battlefield", owner, controller,
                    permanent, _object_name(permanent),
                    _identity_is_visible(permanent, actor, owner, controller, "battlefield"),
                ))
        existing_uids = {ref.uid for ref in refs}
        for position, item in enumerate(list(_field(game, "stack", ()) or ())):
            raw_uid = _field(item, "uid")
            # Trigger/ability markers are inspectable public stack objects, but
            # they are not additional physical cards in the owner's 100.  Spell
            # copies likewise do not belong in a runtime deck view.
            if not raw_uid or bool(_field(item, "spell_copy", False)):
                continue
            uid = str(raw_uid)
            if uid in existing_uids:
                continue
            owner = str(_field(item, "owner", _field(item, "actor", "")))
            if owner != actor:
                continue
            controller = str(_field(item, "controller", _field(item, "actor", actor)))
            refs.append(_VisibleRef(
                uid, "stack", owner, controller, item, _object_name(item),
                _identity_is_visible(item, actor, owner, controller, "stack"),
                position,
            ))
        return refs

    def _deck_expected_counts(self, profile: Any) -> Counter[str]:
        counts: Counter[str] = Counter()
        for entry in self._profile_entries(profile):
            card_id = str(_field(entry, "card_id", ""))
            if card_id:
                counts[card_id] += int(_field(entry, "quantity", 1) or 1)
        return counts

    def _ref_card_id(self, ref: _VisibleRef) -> Optional[str]:
        if not ref.identity_visible or not ref.name:
            return None
        definition = self._catalog_get(ref.name)
        return str(_field(definition, "card_id", self.canonical_card_id(ref.name)))

    def _entry_by_id(self, profile: Any) -> dict[str, Any]:
        return {str(_field(entry, "card_id", "")): entry for entry in self._profile_entries(profile)
                if _field(entry, "card_id")}

    def _card_summary(self, card_id: str, name: str, entry: Any,
                      *, quantity: int = 1, controllers: Iterable[str] = (),
                      inspectable_uids: Iterable[str] = (), zone: Optional[str] = None,
                      castable_ids: Iterable[str] = (),
                      playable_ids: Iterable[str] = ()) -> dict[str, Any]:
        record = self._catalog_record(card_id) or self._catalog_record(name) or {}
        mana_value = record.get("mana_value")
        try:
            mana_value = int(mana_value) if mana_value is not None else None
        except (TypeError, ValueError):
            mana_value = None
        castable = zone in CASTABLE_ZONES and card_id in set(castable_ids)
        playable = zone in {"hand", "graveyard"} and card_id in set(playable_ids)
        if castable:
            usability = "castable_now"
        elif playable:
            usability = "playable_now"
        elif zone == "library":
            usability = "unordered_future_resource"
        elif zone == "battlefield":
            usability = "in_play"
        elif zone == "stack":
            usability = "on_stack"
        elif zone in ACTIONABLE_ZONES:
            usability = "not_currently_castable"
        else:
            usability = "not_actionable"
        return {
            "card_id": card_id,
            "name": name,
            "quantity": quantity,
            "roles": list(self._entry_role_ids(entry)) if entry is not None else [],
            "role_assignments": self._entry_role_assignments(entry) if entry is not None else [],
            "mana_value": mana_value,
            "castable_now": castable,
            "playable_now": playable,
            "current_usability": usability,
            "controllers": sorted(set(str(value) for value in controllers if value)),
            "inspectable_uids": sorted(set(str(value) for value in inspectable_uids if value)),
        }

    def _current_castable_ids(self, game: Any, actor: str,
                              decision_request: Optional[Mapping[str, Any]]) -> set[str]:
        """Read the referee's already-derived decision surface for castability.

        The pilot never estimates mana.  The request options were built by the
        referee from exact timing, targets, payment plans, and current state, so
        matching those options back to the frozen deck profile is both read-only
        and stricter than recomputing from printed mana cost.
        """
        if not decision_request or str(decision_request.get("actor", "")) != actor:
            return set()
        options = [" ".join(str(value).split()).casefold()
                   for value in _items(decision_request.get("options", ())) ]
        profile = self._profile(actor)
        result = set()
        for entry in self._profile_entries(profile):
            card_id = str(_field(entry, "card_id", ""))
            name = " ".join(str(_field(entry, "card_name", card_id)).split()).casefold()
            markers = (
                f"cast {name}", f"cast commander {name}", f"escape {name}",
                f"transmute {name}",
            )
            if any(any(option == marker or option.startswith(marker + " ")
                       for marker in markers) for option in options):
                result.add(card_id)
        return result

    def _current_playable_ids(self, actor: str,
                              decision_request: Optional[Mapping[str, Any]]) -> set[str]:
        if not decision_request or str(decision_request.get("actor", "")) != actor:
            return set()
        if str(decision_request.get("kind", "")) not in {"land_play", "effect_land"}:
            return set()
        options = [" ".join(str(value).split()).casefold()
                   for value in _items(decision_request.get("options", ()))]
        result = set()
        for entry in self._profile_entries(self._profile(actor)):
            card_id = str(_field(entry, "card_id", ""))
            name = " ".join(str(_field(entry, "card_name", card_id)).split()).casefold()
            if any(option == name or option.startswith(name + " |") for option in options):
                result.add(card_id)
        return result

    def _mana_value_for_id(self, profile: Any, card_id: str) -> Optional[int]:
        entry = self._entry_by_id(profile).get(card_id)
        record = self._catalog_record(card_id)
        if record is None and entry is not None:
            record = self._catalog_record(str(_field(entry, "card_name", card_id)))
        value = (record or {}).get("mana_value")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _mana_band(value: Optional[int]) -> str:
        if value is None:
            return "unknown"
        if value <= 2:
            return "0-2"
        if value <= 4:
            return "3-4"
        return "5+"

    def _zone_groups(self, game: Any, actor: str, profile: Any,
                     selected_ids: Optional[set[str]] = None, *,
                     castable_ids: Iterable[str] = (),
                     playable_ids: Iterable[str] = ()) -> tuple[dict[str, Any], dict[str, Any]]:
        refs = self._owned_runtime_refs(game, actor)
        entry_by_id = self._entry_by_id(profile)
        hidden_nonlibrary = [ref for ref in refs if ref.zone != "library" and not ref.identity_visible]
        known_nonlibrary = [ref for ref in refs if ref.zone != "library" and ref.identity_visible]
        library_refs = [ref for ref in refs if ref.zone == "library"]
        uncertainty: dict[str, Any] = {
            "has_hidden_identity_uncertainty": bool(hidden_nonlibrary),
            "hidden_objects": [],
            "unresolved_identity_pool": [],
        }
        hidden_by_zone = Counter(ref.zone for ref in hidden_nonlibrary)
        uncertainty["hidden_objects"] = [
            {"zone": zone, "count": count} for zone, count in sorted(hidden_by_zone.items())
        ]

        visible_by_zone: dict[str, list[_VisibleRef]] = defaultdict(list)
        for ref in known_nonlibrary:
            card_id = self._ref_card_id(ref)
            if selected_ids is None or card_id in selected_ids:
                visible_by_zone[ref.zone].append(ref)

        # With no external hidden object, the owner can derive the unordered
        # identities remaining in their library from their registered decklist.
        # Once a face-down object is unknown, using the engine's actual library
        # identities would leak which card was hidden; derive only certainties.
        derived_library: Counter[str] = Counter()
        if hidden_nonlibrary and profile is not None:
            unresolved = self._deck_expected_counts(profile)
            for ref in known_nonlibrary:
                card_id = self._ref_card_id(ref)
                if card_id:
                    unresolved[card_id] -= 1
                    if unresolved[card_id] <= 0:
                        unresolved.pop(card_id, None)
            uncertainty["unresolved_identity_pool"] = [
                {"card_id": card_id,
                 "name": str(_field(entry_by_id.get(card_id), "card_name", card_id)),
                 "quantity": count}
                for card_id, count in sorted(unresolved.items()) if count > 0
            ]
            hidden_count = len(hidden_nonlibrary)
            for card_id, count in unresolved.items():
                definite = max(0, count - hidden_count)
                if definite and (selected_ids is None or card_id in selected_ids):
                    derived_library[card_id] = definite
        elif not hidden_nonlibrary:
            for ref in library_refs:
                card_id = self._ref_card_id(ref)
                if card_id and (selected_ids is None or card_id in selected_ids):
                    derived_library[card_id] += 1

        zones: dict[str, Any] = {}
        for zone in ZONE_ORDER:
            grouped: dict[str, list[_VisibleRef]] = defaultdict(list)
            for ref in visible_by_zone.get(zone, []):
                card_id = self._ref_card_id(ref)
                if card_id:
                    grouped[card_id].append(ref)
            cards = []
            for card_id, group in sorted(grouped.items(), key=lambda item: (
                str(_field(entry_by_id.get(item[0]), "card_name", item[0])).casefold(), item[0]
            )):
                entry = entry_by_id.get(card_id)
                name = str(_field(entry, "card_name", group[0].name or card_id))
                cards.append(self._card_summary(
                    card_id, name, entry, quantity=len(group),
                    controllers=(ref.controller for ref in group),
                    inspectable_uids=(ref.uid for ref in group if ref.zone != "library"),
                    zone=zone, castable_ids=castable_ids, playable_ids=playable_ids,
                ))
            if zone == "library":
                cards = []
                for card_id, count in sorted(derived_library.items(), key=lambda item: (
                    str(_field(entry_by_id.get(item[0]), "card_name", item[0])).casefold(), item[0]
                )):
                    entry = entry_by_id.get(card_id)
                    name = str(_field(entry, "card_name", card_id))
                    cards.append(self._card_summary(
                        card_id, name, entry, quantity=count, zone=zone,
                        castable_ids=castable_ids, playable_ids=playable_ids,
                    ))
            unknown_count = hidden_by_zone.get(zone, 0)
            actual_zone_count = sum(1 for ref in refs if ref.zone == zone)
            matching_count = sum(card["quantity"] for card in cards)
            zones[zone] = {
                "ordered": False if zone == "library" else None,
                "count": actual_zone_count if selected_ids is None else matching_count,
                "zone_total_count": actual_zone_count,
                "matching_known_count": matching_count,
                "unknown_count": unknown_count,
                "cards": cards,
            }
        return zones, uncertainty

    def _catalog_records_for_ids(self, profile: Any, card_ids: Iterable[str]) -> dict[str, Any]:
        entry_by_id = self._entry_by_id(profile)
        records = {}
        for card_id in sorted(set(card_ids)):
            entry = entry_by_id.get(card_id)
            record = self._catalog_record(card_id)
            if record is None and entry is not None:
                record = self._catalog_record(str(_field(entry, "card_name", card_id)))
            if record is not None:
                records[card_id] = record
        return records

    def _notes_for_ids(self, actor: str, profile: Any, card_ids: Iterable[str]) -> list[dict[str, Any]]:
        entry_by_id = self._entry_by_id(profile)
        refs = [str(_field(entry_by_id[card_id], "card_name", card_id))
                for card_id in card_ids if card_id in entry_by_id]
        return self.pilot_memory(actor, refs)

    def _catalog_identities_for_ids(self, profile: Any,
                                    card_ids: Iterable[str]) -> dict[str, Any]:
        entry_by_id = self._entry_by_id(profile)
        identities = {}
        for card_id in sorted(set(card_ids)):
            entry = entry_by_id.get(card_id)
            name = str(_field(entry, "card_name", card_id))
            record = self._catalog_record(card_id) or self._catalog_record(name) or {}
            identities[card_id] = {
                "card_id": card_id,
                "name": str(record.get("name", name)),
                "mana_cost": record.get("mana_cost"),
                "mana_value": record.get("mana_value"),
                "type_line": record.get("type_line"),
            }
        return identities

    def _package_relationships(self, profile: Any, card_ids: Iterable[str],
                               zones: Mapping[str, Any]) -> list[dict[str, Any]]:
        selected = set(card_ids)
        if not selected:
            return []
        locations: dict[str, list[str]] = defaultdict(list)
        for zone, group in zones.items():
            for card in group.get("cards", []):
                locations[str(card["card_id"])].append(zone)
        entry_by_id = self._entry_by_id(profile)
        relationships = []
        for package in sorted(_items(_field(profile, "packages", ())),
                              key=lambda value: str(_field(value, "package_id", ""))):
            if str(_field(package, "status", "active")) != "active":
                continue
            members = []
            for member in _items(_field(package, "members", ())):
                card_id = str(_field(member, "card_id", member))
                if card_id not in selected:
                    continue
                entry = entry_by_id.get(card_id)
                members.append({
                    "card_id": card_id,
                    "name": str(_field(entry, "card_name", card_id)),
                    "member_role": str(_field(member, "member_role", "piece")),
                    "zones": sorted(locations.get(card_id, ())),
                })
            if not members:
                continue
            relationship = {
                "package_id": str(_field(package, "package_id", "")),
                "label": str(_field(package, "label", _field(package, "package_id", ""))),
                "description": str(_field(package, "description", "")),
                "matched_member_count": len(members),
                "package_member_count": len(_items(_field(package, "members", ()))),
                "members": members,
                "source": str(_field(package, "source", "seed")),
                "revision": _field(package, "revision", 1),
                "source_game": _field(package, "source_game"),
            }
            relationships.append(relationship)
        return relationships

    def _package_guidance(self, profile: Any,
                          relationships: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        wanted = {str(row.get("package_id", "")) for row in relationships}
        result = []
        for package in _items(_field(profile, "packages", ())):
            package_id = str(_field(package, "package_id", ""))
            if package_id not in wanted:
                continue
            label = str(_field(package, "label", package_id))
            for index, note in enumerate(_items(_field(package, "notes", ())), 1):
                if isinstance(note, str):
                    row = {
                        "note_id": f"package:{package_id}:{index}", "text": note,
                        "source": str(_field(package, "source", "seed")),
                        "revision": _field(package, "revision", 1),
                        "source_game": _field(package, "source_game"),
                        "confidence": None,
                    }
                else:
                    row = {
                        "note_id": str(_field(note, "note_id", f"package:{package_id}:{index}")),
                        "text": str(_field(note, "text", "")),
                        "source": str(_field(note, "source", _field(package, "source", "seed"))),
                        "revision": _field(note, "revision", _field(package, "revision", 1)),
                        "source_game": _field(note, "source_game", _field(package, "source_game")),
                        "confidence": _field(note, "confidence"),
                        "source_cohort": _field(note, "source_cohort"),
                        "source_review": _field(note, "source_review"),
                    }
                row.update({
                    "memory_kind": "package", "package_id": package_id,
                    "package_label": label, "card_id": f"package:{package_id}",
                    "card_name": f"Package: {label}",
                })
                if row["text"]:
                    result.append(row)
        return result

    @staticmethod
    def _guidance_priority(note: Mapping[str, Any], actionable_ids: set[str]) -> tuple[Any, ...]:
        return (
            0 if str(note.get("card_id", "")) in actionable_ids else 1,
            0 if note.get("locked") else 1,
            0 if note.get("source_game") is not None else 1,
            -(float(note.get("confidence")) if note.get("confidence") is not None else -1.0),
            str(note.get("card_name", "")).casefold(),
            str(note.get("note_id", "")),
        )

    def _planning_views(self, zones: Mapping[str, Any], profile: Any,
                        relationships: list[dict[str, Any]],
                        guidance: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
        available_cards = []
        actionable_ids = set()
        for zone, group in zones.items():
            if zone not in ACTIONABLE_ZONES:
                continue
            for card in group.get("cards", []):
                row = dict(card)
                row["zone"] = zone
                available_cards.append(row)
                actionable_ids.add(str(card["card_id"]))
        available_cards.sort(key=lambda row: (
            0 if row.get("castable_now") else 1,
            ZONE_ORDER.index(str(row.get("zone"))), str(row.get("name", "")).casefold(),
        ))

        library = zones.get("library", {"cards": [], "count": 0, "unknown_count": 0})
        library_cards = [dict(card) for card in library.get("cards", [])]
        mana_bands: Counter[str] = Counter()
        for card in library_cards:
            mana_bands[self._mana_band(card.get("mana_value"))] += int(card.get("quantity", 1))
        library_ids = {str(card["card_id"]) for card in library_cards}
        route_rows = []
        for relationship in relationships:
            library_members = [member["name"] for member in relationship["members"]
                               if member["card_id"] in library_ids]
            if library_members:
                route_rows.append({
                    "package_id": relationship["package_id"],
                    "label": relationship["label"],
                    "library_members": library_members,
                })
        relevant_guidance = [
            note for note in guidance
            if (str(note.get("card_id", "")) in library_ids or note.get("memory_kind") == "package")
        ]
        return (
            {"cards": available_cards, "card_count": sum(int(row.get("quantity", 1)) for row in available_cards)},
            {
                "ordered": False,
                "warning": "Library identities are an unordered deck-composition view; future draw order is never exposed.",
                "known_member_count": sum(int(row.get("quantity", 1)) for row in library_cards),
                "unknown_identity_count": int(library.get("unknown_count", 0)),
                "members": library_cards,
                "mana_bands": dict(sorted(mana_bands.items())),
                "package_routes": route_rows,
                "learned_guidance": relevant_guidance[:ROLE_RESULT_GUIDANCE_LIMIT],
            },
        )

    def inspect_deck(self, game: Any, actor: str, *, card: Optional[str] = None,
                     zone: Optional[str] = None, role: Optional[str] = None,
                     package: Optional[str] = None,
                     max_mana_value: Optional[int] = None,
                     castable_now: bool = False,
                     full_detail: bool = False,
                     decision_request: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        """Inspect the actor's deck composition joined to known runtime zones.

        At most one of ``card``, ``role``, and ``package`` may be supplied.  A
        zone is an additional presentation filter and never changes visibility.
        """
        _player(game, actor)
        selectors = [value is not None for value in (card, role, package)]
        if sum(selectors) > 1:
            raise InspectionError("Choose only one of card, role, or package")
        if zone is not None:
            zone = zone.casefold().replace("command_zone", "command")
            if zone not in ZONE_ORDER:
                raise InspectionError(
                    f"Unknown deck-view zone {zone!r}. Try: deck zone=library; role \"Protection\" zone=hand"
                )
        if max_mana_value is not None and max_mana_value < 0:
            raise InspectionError('Mana value must be nonnegative. Try: role "Protection" mv<=3')
        if (max_mana_value is not None or castable_now) and role is None:
            raise InspectionError(
                'Mana/castability filters apply to role queries. Try: role "Protection" mv<=3 castable_now=true'
            )
        profile = self._profile(actor)
        selected_ids: Optional[set[str]] = None
        selection: Optional[dict[str, Any]] = None
        detailed = False
        package_value = None
        if card is not None:
            entry = self._entry(profile, card)
            if profile is not None and entry is None:
                names = sorted(
                    (str(_field(value, "card_name", "")) for value in self._profile_entries(profile)),
                    key=str.casefold,
                )
                close = get_close_matches(str(card), names, n=3, cutoff=0.3) or names[:3]
                suggestions = "; ".join(
                    f"card {json.dumps(name, ensure_ascii=False)}" for name in close
                )
                raise UnknownDeckCard(
                    f"{card!r} is not in {actor}'s deck profile. Try: {suggestions}"
                )
            if entry is not None:
                card_id = str(_field(entry, "card_id", self.canonical_card_id(card)))
                name = str(_field(entry, "card_name", card))
            else:
                definition = self._catalog_get(card)
                if definition is None:
                    raise UnknownDeckCard(f"Unknown card {card!r}. Try: deck zone=library")
                card_id = str(_field(definition, "card_id", self.canonical_card_id(card)))
                name = str(_field(definition, "name", card))
                # Without a profile, confirm the runtime deck owns this card.
                if not any(self._ref_card_id(ref) == card_id for ref in self._owned_runtime_refs(game, actor)):
                    raise UnknownDeckCard(
                        f"{card!r} is not in {actor}'s runtime deck. Try: deck zone=library"
                    )
            selected_ids = {card_id}
            selection = {"kind": "card", "card_id": card_id, "name": name}
            detailed = True
        elif role is not None:
            if profile is None:
                raise UnknownRole("Role inspection requires a strategy deck profile")
            role_id = self._resolve_role_id(profile, role)
            selected_ids = {
                str(_field(entry, "card_id", "")) for entry in self._profile_entries(profile)
                if role_id in self._entry_role_ids(entry)
            }
            definition = self._role_definition(role_id)
            selection = {
                "kind": "role", "role_id": role_id,
                "label": str(_field(definition, "label", role_id)),
                "description": str(_field(definition, "description", "")),
                "source": str(_field(definition, "source", "seed")),
                "revision": _field(definition, "revision", 1),
                "source_game": _field(definition, "source_game"),
            }
            detailed = True
        elif package is not None:
            if profile is None:
                raise UnknownPackage("Package inspection requires a strategy deck profile")
            package_value = self._package(profile, package)
            selected_ids = {
                str(_field(member, "card_id", ""))
                for member in _items(_field(package_value, "members", ()))
                if _field(member, "card_id")
            }
            selection = {
                "kind": "package",
                "package_id": str(_field(package_value, "package_id", package)),
                "label": str(_field(package_value, "label", package)),
                "description": str(_field(package_value, "description", "")),
                "source": str(_field(package_value, "source", "seed")),
                "revision": _field(package_value, "revision", 1),
                "source_game": _field(package_value, "source_game"),
            }
            detailed = True
        castable_ids = self._current_castable_ids(game, actor, decision_request)
        playable_ids = self._current_playable_ids(actor, decision_request)
        original_selected_ids = set(selected_ids or ())
        if selected_ids is not None and max_mana_value is not None:
            selected_ids = {
                card_id for card_id in selected_ids
                if (self._mana_value_for_id(profile, card_id) is not None and
                    self._mana_value_for_id(profile, card_id) <= max_mana_value)
            }
        if selected_ids is not None and castable_now:
            selected_ids &= castable_ids
        zones, uncertainty = self._zone_groups(
            game, actor, profile, selected_ids, castable_ids=castable_ids,
            playable_ids=playable_ids,
        )
        if castable_now:
            for group in zones.values():
                group["cards"] = [card for card in group["cards"] if card.get("castable_now")]
                group["matching_known_count"] = sum(
                    int(card.get("quantity", 1)) for card in group["cards"])
                group["count"] = group["matching_known_count"]
        if zone is not None:
            zones = {zone: zones[zone]}
        effective_ids = set(selected_ids or ())
        relationships = self._package_relationships(profile, effective_ids, zones)
        guidance = self._notes_for_ids(actor, profile, effective_ids)
        guidance.extend(self._package_guidance(profile, relationships))
        actionable_ids = {
            str(card["card_id"])
            for zone_name, group in zones.items() if zone_name in ACTIONABLE_ZONES
            for card in group.get("cards", ())
        }
        guidance.sort(key=lambda note: self._guidance_priority(note, actionable_ids))
        if not full_detail:
            guidance = guidance[:ROLE_RESULT_GUIDANCE_LIMIT]
        result: dict[str, Any] = {
            "kind": selection["kind"] if selection else "deck",
            "actor": actor,
            "deck": {
                "deck_id": str(_field(profile, "deck_id", _slug(actor))),
                "label": str(_field(profile, "label", actor)),
                "revision": _field(profile, "revision"),
                "registered_cards": sum(self._deck_expected_counts(profile).values()) if profile is not None else None,
            },
            "selection": selection,
            "zone_filter": zone,
            "filters": {
                "mv_lte": max_mana_value,
                "castable_now": bool(castable_now),
                "castability_source": "authoritative_current_decision_surface",
                "matched_card_count": len(effective_ids),
                "unfiltered_card_count": len(original_selected_ids),
            },
            "zones": zones,
            "uncertainty": uncertainty,
            "catalog_records": {},
            "catalog_identities": self._catalog_identities_for_ids(profile, effective_ids),
            "pilot_memory": guidance,
            "package_relationships": relationships,
            "strategy_snapshot": {
                "frozen": True,
                "live_updates": False,
                "strategy_revision": _field(self.strategy, "revision"),
                "deck_revision": _field(profile, "revision"),
            },
        }
        if detailed and selected_ids:
            if card is not None or full_detail:
                record_ids = effective_ids
            else:
                record_ids = set(sorted(actionable_ids)[:ROLE_RESULT_CATALOG_LIMIT])
            result["catalog_records"] = self._catalog_records_for_ids(profile, record_ids)
        if role is not None and zone is None:
            available_now, library_outlook = self._planning_views(
                zones, profile, relationships, guidance,
            )
            result["available_now"] = available_now
            result["library_outlook"] = library_outlook
        elif role is not None and zone == "library":
            _, result["library_outlook"] = self._planning_views(
                zones, profile, relationships, guidance,
            )
        if role is not None:
            label = str(selection.get("label", role))
            quoted = json.dumps(label, ensure_ascii=False)
            result["refinement_commands"] = [
                f"role {quoted} zone=library",
                f"role {quoted} zone=hand",
                f"role {quoted} mv<=3",
                f"role {quoted} castable_now=true",
                f"role {quoted} zone={zone or 'library'} detail=full",
            ]
        elif package is not None:
            quoted = json.dumps(str(selection.get("label", package)), ensure_ascii=False)
            result["refinement_commands"] = [
                f"package {quoted} zone=library",
                f"package {quoted} zone=hand",
                f"package {quoted} zone={zone or 'library'} detail=full",
            ]
        return self._finish(result)

    def inspect_card(self, game: Any, actor: str, card: str,
                     *, zone: Optional[str] = None) -> dict[str, Any]:
        return self.inspect_deck(game, actor, card=card, zone=zone)

    def inspect_roles(self, game: Any, actor: str) -> dict[str, Any]:
        profile = self._profile(actor)
        if profile is None:
            raise UnknownRole("Role inspection requires a strategy deck profile")
        zones, uncertainty = self._zone_groups(game, actor, profile)
        counts_by_id: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for zone_name, group in zones.items():
            for card in group["cards"]:
                for role_id in card["roles"]:
                    counts_by_id[role_id][zone_name] += int(card["quantity"])
        represented = {
            role_id for entry in self._profile_entries(profile)
            for role_id in self._entry_role_ids(entry)
        }
        roles = []
        for role_id in sorted(represented):
            definition = self._role_definition(role_id)
            if definition is not None and str(_field(definition, "status", "active")) != "active":
                continue
            entries = [entry for entry in self._profile_entries(profile)
                       if role_id in self._entry_role_ids(entry)]
            unresolved_count = sum(
                int(row["quantity"])
                for row in uncertainty.get("unresolved_identity_pool", [])
                if role_id in self._entry_role_ids(self._entry(profile, str(row["card_id"])))
            )
            roles.append({
                "role_id": role_id,
                "label": str(_field(definition, "label", role_id)),
                "description": str(_field(definition, "description", "")),
                "inspect_command": (
                    "role " + json.dumps(str(_field(definition, "label", role_id)), ensure_ascii=False)
                ),
                "aliases": list(_items(_field(definition, "aliases", ()))),
                "source": str(_field(definition, "source", "seed")),
                "revision": _field(definition, "revision", 1),
                "source_game": _field(definition, "source_game"),
                "card_count": len(entries),
                "copy_count": sum(int(_field(entry, "quantity", 1) or 1) for entry in entries),
                "unresolved_pool_count": unresolved_count,
                "zone_counts": dict(sorted(counts_by_id[role_id].items(),
                                           key=lambda item: ZONE_ORDER.index(item[0]))),
            })
        return self._finish({
            "kind": "roles", "actor": actor,
            "deck": {
                "deck_id": str(_field(profile, "deck_id", _slug(actor))),
                "label": str(_field(profile, "label", actor)),
                "revision": _field(profile, "revision"),
            },
            "roles": roles,
            "uncertainty": uncertainty,
            "strategy_snapshot": {
                "frozen": True, "live_updates": False,
                "strategy_revision": _field(self.strategy, "revision"),
                "deck_revision": _field(profile, "revision"),
            },
        })

    def inspect_role(self, game: Any, actor: str, role: str,
                     *, zone: Optional[str] = None,
                     max_mana_value: Optional[int] = None,
                     castable_now: bool = False, full_detail: bool = False,
                     decision_request: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        return self.inspect_deck(
            game, actor, role=role, zone=zone,
            max_mana_value=max_mana_value, castable_now=castable_now,
            full_detail=full_detail, decision_request=decision_request,
        )

    def inspect_package(self, game: Any, actor: str, package: str,
                        *, zone: Optional[str] = None, full_detail: bool = False,
                        decision_request: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        return self.inspect_deck(
            game, actor, package=package, zone=zone, full_detail=full_detail,
            decision_request=decision_request,
        )

    def inspect_messageboard(self, game: Any, actor: str) -> dict[str, Any]:
        """Return the complete replay-derived public table-talk transcript."""
        if actor not in game.players:
            raise InspectionError(f"Unknown pilot {actor!r}")
        messages=[dict(entry) for entry in getattr(game,"public_messageboard",[])]
        return self._finish({
            "schema":1,"kind":"messageboard","actor":actor,"visibility":"public",
            "message_count":len(messages),"messages":messages,
            "warning":(
                "Player-authored table talk may contain politics, promises, or bluffs. "
                "It is not a rules fact, referee instruction, or source of hidden information."
            ),
        })

    # ------------------------------------------------------------------
    # Readable rendering / CLI-friendly dispatch
    # ------------------------------------------------------------------
    def _finish(self, result: dict[str, Any]) -> dict[str, Any]:
        plain = _json_value(result)
        plain["text"] = render_inspection(plain)
        # Fail here rather than handing a caller a subtly nonserializable view.
        json.dumps(plain, ensure_ascii=False)
        return plain

    @staticmethod
    def _query_error(message: str, suggestion: str) -> InspectionError:
        return InspectionError(f"{message} Try: {suggestion}")

    def _parse_query(self, actor: str, query: str) -> _ParsedQuery:
        try:
            parts = shlex.split(query)
        except ValueError as exc:
            raise self._query_error(
                f"Could not parse inspection query: {exc}.", 'card "Card Name"'
            ) from exc
        if parts and parts[0].casefold() == "inspect":
            parts = parts[1:]
        if not parts:
            raise self._query_error("Inspection query is empty.", "roles")
        kind = parts.pop(0).casefold().replace("-", "_")
        positional: list[str] = []
        options: dict[str, str] = {}
        max_mana_value: Optional[int] = None
        for part in parts:
            mana_match = re.fullmatch(r"mv\s*<=\s*(\d+)", part, flags=re.IGNORECASE)
            if mana_match:
                max_mana_value = int(mana_match.group(1))
                continue
            if "=" in part:
                key, option_value = part.split("=", 1)
                options[key.casefold().replace("-", "_")] = option_value
            else:
                positional.append(part)
        value = " ".join(positional).strip()

        # A common natural shorthand is safe and unambiguous.
        if kind == "roles" and value:
            kind = "role"
        allowed = {
            "object": set(), "card": {"zone"}, "deck": {"zone"},
            "roles": set(),
            "role": {"zone", "castable_now", "detail"},
            "package": {"zone", "detail"}, "messageboard": set(),
        }
        if kind not in allowed:
            raise self._query_error(
                f"Unknown inspection kind {kind!r}.", "roles"
            )
        unknown = sorted(set(options) - allowed[kind])
        if unknown:
            exemplar = ('role "Protection" zone=hand mv<=3 castable_now=true'
                        if kind == "role" else INSPECTION_GRAMMAR[0])
            raise self._query_error(
                f"Unsupported option(s) for {kind}: {', '.join(unknown)}.", exemplar
            )
        if max_mana_value is not None and kind != "role":
            raise self._query_error(
                "mv<=N is available on role inspections.", 'role "Protection" mv<=3'
            )
        zone = options.get("zone")
        if zone is not None:
            zone = zone.casefold().replace("command_zone", "command").replace("command-zone", "command")
            if zone not in ZONE_ORDER:
                raise self._query_error(
                    f"Unknown zone {zone!r}.", f"{kind} " + (json.dumps(value) + " " if value else "") + "zone=library"
                )
        castable_value = options.get("castable_now")
        if castable_value is None:
            castable_now = False
        elif castable_value.casefold() == "true":
            castable_now = True
        else:
            raise self._query_error(
                "castable_now accepts true.", 'role "Protection" castable_now=true'
            )
        detail_value = options.get("detail")
        if detail_value is None:
            full_detail = False
        elif detail_value.casefold() == "full":
            full_detail = True
        else:
            raise self._query_error(
                "detail accepts full.", f'{kind} {json.dumps(value)} zone={zone or "library"} detail=full'
            )

        requires_value = kind in {"object", "card", "role", "package"}
        if requires_value and not value:
            exemplar = {
                "object": "object UID", "card": 'card "Card Name"',
                "role": 'role "Protection"', "package": 'package "Package Name"',
            }[kind]
            raise self._query_error(f"{kind} requires a value.", exemplar)
        if kind in {"deck", "roles", "messageboard"} and value:
            raise self._query_error(
                f"{kind} does not accept a positional value.",
                "roles" if kind == "roles" else kind,
            )

        canonical_value = value
        if kind == "role":
            profile = self._profile(actor)
            if profile is None:
                raise UnknownRole("Role inspection requires a strategy deck profile. Try: roles")
            role_id = self._resolve_role_id(profile, value)
            definition = self._role_definition(role_id)
            canonical_value = str(_field(definition, "label", role_id))
        elif kind == "package":
            profile = self._profile(actor)
            if profile is None:
                raise UnknownPackage("Package inspection requires a strategy deck profile")
            package = self._package(profile, value)
            canonical_value = str(_field(package, "label", _field(package, "package_id", value)))
        elif kind == "card":
            profile = self._profile(actor)
            entry = self._entry(profile, value)
            if entry is not None:
                canonical_value = str(_field(entry, "card_name", value))

        if kind in {"object", "deck", "roles", "messageboard"}:
            normalized = kind + ((" " + canonical_value) if canonical_value else "")
        else:
            normalized = f"{kind} {json.dumps(canonical_value, ensure_ascii=False)}"
        if zone is not None:
            normalized += f" zone={zone}"
        if max_mana_value is not None:
            normalized += f" mv<={max_mana_value}"
        if castable_now:
            normalized += " castable_now=true"
        if full_detail:
            normalized += " detail=full"
        return _ParsedQuery(
            kind=kind, value=canonical_value, zone=zone,
            max_mana_value=max_mana_value, castable_now=castable_now,
            full_detail=full_detail, normalized=normalized,
        )

    def normalize_query(self, actor: str, query: str) -> str:
        """Return the canonical, cacheable spelling of a valid query."""
        return self._parse_query(actor, query).normalized

    def query(self, game: Any, actor: str, query: str, *,
              decision_request: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        """Dispatch one shell-friendly, actor-private inspection command."""
        parsed = self._parse_query(actor, query)
        if parsed.kind == "object":
            result = self.inspect_object(game, actor, parsed.value)
        elif parsed.kind == "card":
            result = self.inspect_deck(
                game, actor, card=parsed.value, zone=parsed.zone,
                decision_request=decision_request,
            )
        elif parsed.kind == "deck":
            result = self.inspect_deck(game, actor, zone=parsed.zone)
        elif parsed.kind == "roles":
            result = self.inspect_roles(game, actor)
        elif parsed.kind == "role":
            result = self.inspect_role(
                game, actor, parsed.value, zone=parsed.zone,
                max_mana_value=parsed.max_mana_value,
                castable_now=parsed.castable_now,
                full_detail=parsed.full_detail,
                decision_request=decision_request,
            )
        elif parsed.kind == "package":
            result = self.inspect_package(
                game, actor, parsed.value, zone=parsed.zone,
                full_detail=parsed.full_detail,
                decision_request=decision_request,
            )
        else:
            result = self.inspect_messageboard(game, actor)
        result["normalized_query"] = parsed.normalized
        return result


def _catalog_brief(record: Optional[Mapping[str, Any]]) -> list[str]:
    if not record:
        return ["No canonical parent record is available."]
    lines = [str(record.get("name", record.get("card_id", "Unknown card")))]
    cost = record.get("mana_cost")
    type_line = record.get("type_line")
    oracle = record.get("oracle_text", record.get("text"))
    if cost:
        lines.append(f"Mana cost: {cost}")
    if type_line:
        lines.append(f"Type: {type_line}")
    if oracle:
        lines.append("Oracle: " + " ".join(str(oracle).split()))
    return lines


def render_inspection(result: Mapping[str, Any]) -> str:
    """Render any structured inspection result without changing it."""
    kind = str(result.get("kind", "inspection"))
    actor = str(result.get("actor", ""))
    if kind == "object":
        obj = result.get("object", {})
        lines = [
            f"OBJECT — {obj.get('name', 'Unknown')} [{obj.get('uid', '?')}]",
            f"Zone: {obj.get('zone', '?')}; owner: {obj.get('owner', '?')}; controller: {obj.get('controller', '?')}",
        ]
        flags = []
        for label in ("tapped", "summoning_sick", "token", "phased_out"):
            if obj.get(label):
                flags.append(label.replace("_", " "))
        if flags:
            lines.append("State: " + ", ".join(flags))
        if obj.get("counters"):
            lines.append("Counters: " + json.dumps(obj["counters"], sort_keys=True))
        lines.append("\nPARENT CARD")
        lines.extend(_catalog_brief(result.get("parent_card")))
        effective = result.get("effective_parent_card")
        if effective:
            lines.append("\nEFFECTIVE COPY RECORD")
            lines.extend(_catalog_brief(effective))
        memory = result.get("pilot_memory", [])
        if memory:
            lines.append(f"\nPILOT MEMORY — {actor}")
            lines.extend(f"- {note['text']} [{note['source']}]" for note in memory)
        return "\n".join(lines)
    if kind == "roles":
        deck = result.get("deck", {})
        lines = [f"ROLES — {deck.get('label', actor)}"]
        for role in result.get("roles", []):
            locations = ", ".join(f"{zone} {count}" for zone, count in role.get("zone_counts", {}).items())
            lines.append(
                f"- {role['label']}: {role['card_count']} cards" +
                (f" ({locations})" if locations else "") +
                f" — inspect with: {role['inspect_command']}"
            )
        return "\n".join(lines)
    if kind == "messageboard":
        lines=[f"PUBLIC MESSAGEBOARD — {result.get('message_count',0)} message(s)"]
        lines.append(str(result.get("warning","")))
        for message in result.get("messages",[]):
            address=message.get("address") or {};address_kind=address.get("kind","generic")
            target=(", ".join(address.get("pilots") or [])
                    if address_kind=="pilot" else
                    ("all opponents" if address_kind=="all" else "the table (generic)"))
            reply=f"; reply to {message.get('reply_to')}" if message.get("reply_to") else ""
            lines.append(
                f"- [{message.get('message_id','?')}] {message.get('author','?')} -> "
                f"{target}{reply}: {json.dumps(message.get('text',''),ensure_ascii=False)}")
        return "\n".join(lines)
    if kind in {"deck", "card", "role", "package"}:
        deck = result.get("deck", {})
        selection = result.get("selection") or {}
        heading = kind.upper()
        if selection:
            heading += " — " + str(selection.get("label", selection.get("name", "")))
        lines = [f"{heading} — {deck.get('label', actor)}"]
        if kind == "role" and result.get("available_now") is not None:
            lines.append("\nAVAILABLE NOW")
            available = result.get("available_now", {}).get("cards", [])
            if not available:
                lines.append("- No known role members in actionable zones.")
            for card in available:
                quantity = f" x{card['quantity']}" if card.get("quantity", 1) != 1 else ""
                lines.append(
                    f"- {card['name']}{quantity} — {card.get('zone')}; "
                    f"{card.get('current_usability', 'unknown usability')}"
                )
            outlook = result.get("library_outlook", {})
            lines.append("\nLIBRARY OUTLOOK (UNORDERED)")
            lines.append(str(outlook.get("warning", "Future draw order is not exposed.")))
            members = outlook.get("members", [])
            lines.append(
                "Remaining: " + (", ".join(
                    f"{card['name']}" + (f" x{card['quantity']}" if card.get("quantity", 1) != 1 else "")
                    for card in members
                ) or "no known members")
            )
            if outlook.get("mana_bands"):
                lines.append("Mana bands: " + ", ".join(
                    f"{band}: {count}" for band, count in outlook["mana_bands"].items()
                ))
            for route in outlook.get("package_routes", []):
                lines.append(
                    f"- Route {route['label']}: " + ", ".join(route.get("library_members", []))
                )
        else:
            for zone, group in result.get("zones", {}).items():
                suffix = " (unordered)" if group.get("ordered") is False else ""
                lines.append(f"\n{zone.upper()}{suffix} — {group.get('count', 0)} total")
                for card in group.get("cards", []):
                    quantity = f" x{card['quantity']}" if card.get("quantity", 1) != 1 else ""
                    role_text = f" [{', '.join(card['roles'])}]" if card.get("roles") else ""
                    usability = f" — {card['current_usability']}" if card.get("current_usability") else ""
                    lines.append(f"- {card['name']}{quantity}{role_text}{usability}")
                if group.get("unknown_count"):
                    lines.append(f"- {group['unknown_count']} card(s) with hidden identity")
        uncertainty = result.get("uncertainty", {})
        if uncertainty.get("has_hidden_identity_uncertainty"):
            lines.append("\nIDENTITY UNCERTAINTY")
            lines.append("A face-down object prevents exact library/hidden-zone attribution; no omniscient identity was used.")
            pool = uncertainty.get("unresolved_identity_pool", [])
            if pool:
                lines.append("Unresolved pool: " + ", ".join(
                    f"{row['name']} x{row['quantity']}" for row in pool
                ))
        memory = result.get("pilot_memory", [])
        if memory:
            lines.append(f"\nRELEVANT LEARNED GUIDANCE — {actor}")
            for note in memory:
                provenance = str(note.get("source", "unknown"))
                if note.get("source_game") is not None:
                    provenance += f", game {note['source_game']}"
                if note.get("revision") is not None:
                    provenance += f", rev {note['revision']}"
                if note.get("confidence") is not None:
                    provenance += f", confidence {note['confidence']}"
                lines.append(f"- {note['card_name']}: {note['text']} [{provenance}]")
        refinements = result.get("refinement_commands", [])
        if refinements:
            lines.append("\nREFINE")
            lines.extend(f"- {command}" for command in refinements)
        return "\n".join(lines)
    return json.dumps(_json_value(result), indent=2, ensure_ascii=False)


# Functional wrappers make embedding in a CLI/decision handler straightforward.
def inspectable_object_index(game: Any, actor: str, *, catalog: Any = None,
                             strategy: Any = None) -> list[dict[str, Any]]:
    return InspectionService(catalog, strategy).inspectable_object_index(game, actor)


def inspect_object(game: Any, actor: str, object_uid: str, *, catalog: Any = None,
                   strategy: Any = None) -> dict[str, Any]:
    return InspectionService(catalog, strategy).inspect_object(game, actor, object_uid)


def inspect_card(game: Any, actor: str, card: str, *, zone: Optional[str] = None,
                 catalog: Any = None, strategy: Any = None) -> dict[str, Any]:
    return InspectionService(catalog, strategy).inspect_card(game, actor, card, zone=zone)


def inspect_deck(game: Any, actor: str, *, zone: Optional[str] = None,
                 catalog: Any = None, strategy: Any = None) -> dict[str, Any]:
    return InspectionService(catalog, strategy).inspect_deck(game, actor, zone=zone)


def inspect_roles(game: Any, actor: str, *, catalog: Any = None,
                  strategy: Any = None) -> dict[str, Any]:
    return InspectionService(catalog, strategy).inspect_roles(game, actor)


def inspect_role(game: Any, actor: str, role: str, *, zone: Optional[str] = None,
                 max_mana_value: Optional[int] = None, castable_now: bool = False,
                 full_detail: bool = False, catalog: Any = None,
                 strategy: Any = None) -> dict[str, Any]:
    return InspectionService(catalog, strategy).inspect_role(
        game, actor, role, zone=zone, max_mana_value=max_mana_value,
        castable_now=castable_now, full_detail=full_detail,
    )


def inspect_package(game: Any, actor: str, package: str, *, zone: Optional[str] = None,
                    full_detail: bool = False, catalog: Any = None,
                    strategy: Any = None) -> dict[str, Any]:
    return InspectionService(catalog, strategy).inspect_package(
        game, actor, package, zone=zone, full_detail=full_detail,
    )


def query_inspection(game: Any, actor: str, query: str, *, catalog: Any = None,
                     strategy: Any = None) -> dict[str, Any]:
    return InspectionService(catalog, strategy).query(game, actor, query)


__all__ = [
    "INSPECTION_GRAMMAR", "INSPECTION_LEGEND", "InspectionError",
    "InspectionService", "ObjectNotVisible",
    "UnknownDeckCard", "UnknownPackage", "UnknownRole",
    "inspect_card", "inspect_deck", "inspect_object", "inspect_package",
    "inspect_role", "inspect_roles", "inspectable_object_index",
    "query_inspection", "render_inspection",
]
