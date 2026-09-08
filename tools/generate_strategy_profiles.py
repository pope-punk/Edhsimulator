#!/usr/bin/env python3
"""Bootstrap inert deck profiles from the current four-deck Oracle reference.

This is intentionally a conservative seed generator, not a rules parser.  It uses
unambiguous Oracle phrases plus a small reviewed card-name overlay.  Once the
gauntlet begins learning, the committed strategy JSON (and its revision history)
is authoritative; regenerating this file is not a substitute for post-game review.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from edh_gauntlet.catalog import load_catalog
from edh_gauntlet.strategy import DEFAULT_STRATEGY_FILE, canonical_card_id


CATALOG = load_catalog()
MANA_ROCKS = CATALOG.mana_source_names("mana_rock")
MANA_DORKS = CATALOG.mana_source_names("mana_dork")


DECKS = {
    "Reaminatour": (
        "reaminatour",
        "Reaminatour — Aminatou, Veil Piercer",
        "Aminatou, Veil Piercer",
    ),
    "Minsc & Boo": (
        "minsc_boo",
        "Minsc & Boo, Timeless Heroes",
        "Minsc & Boo, Timeless Heroes",
    ),
    "Omo": ("omo", "Omo, Queen of Vesuva", "Omo, Queen of Vesuva"),
    "Elenda": ("elenda", "Elenda, Saint of Dusk", "Elenda, Saint of Dusk"),
}


ROLE_DEFINITIONS = {
    "board_wipe": ("Board wipe", "Broadly removes or resets multiple opposing objects."),
    "card_advantage": ("Card advantage", "Draws or otherwise supplies repeatable access to additional cards."),
    "card_selection": ("Card selection", "Improves draw quality through scry, surveil, or top-card selection."),
    "combat_trick": ("Combat trick", "Changes combat math from hand or at instant speed."),
    "combo_piece": ("Combo piece", "Participates in a named combo or repeatable interaction package in this deck."),
    "counter_synergy": ("Counter synergy", "Creates, multiplies, moves, or rewards counters."),
    "counterspell": ("Counterspell", "Counters a spell or stack object."),
    "engine": ("Engine", "Can generate repeatable strategic value when supported."),
    "graveyard_hate": ("Graveyard hate", "Constrains, exiles, or otherwise disrupts graveyard use."),
    "land_synergy": ("Land synergy", "Enables or rewards the deck's land, land-type, Gate, Locus, or landfall plan."),
    "lifegain": ("Lifegain", "Gains life or grants a repeatable lifegain mechanism."),
    "lifegain_payoff": ("Lifegain payoff", "Rewards life gain or a high life total."),
    "protection": ("Protection", "Protects a card, board, or line from opposing interaction."),
    "ramp": ("Ramp", "Accelerates usable mana beyond ordinary one-land-per-turn development."),
    "recursion": ("Recursion", "Returns, casts, or plays cards from a graveyard."),
    "removal": ("Removal", "Answers a permanent, creature, or other opposing game object."),
    "sacrifice_outlet": ("Sacrifice outlet", "Lets its controller deliberately sacrifice another relevant permanent."),
    "token_production": ("Token production", "Creates creature or relevant resource tokens."),
    "tutor": ("Tutor", "Searches the library for one or more strategically selected cards."),
    "wincon": ("Win condition", "Represents a primary or explicit route by which this deck can end a game."),
}


CURATED: dict[str, set[str]] = {
    "board_wipe": {
        "Akroma's Vengeance", "Blasphemous Act", "Chandra's Ignition", "Doomwake Giant",
        "Evacuation", "The Meathook Massacre", "Whelming Wave",
    },
    "combat_trick": {
        "Bulk Up", "Deadly Riposte", "Devouring Light", "Fangs of Kalonia",
        "Give In to Violence", "Inspiring Call", "Invigorating Surge", "Moment of Craving",
        "Ram Through", "Return of the Wildspeaker", "Unleash Fury", "Valorous Stance",
    },
    "counterspell": {
        "Arcane Denial", "Counterspell", "Fierce Guardianship", "Glen Elendra Archmage",
        "Remand", "Summary Dismissal", "Swan Song",
    },
    "engine": {
        "Aminatou, Veil Piercer", "Aminatou, the Fateshifter", "All Will Be One",
        "Branching Evolution", "Dawn of Hope", "Entity Tracker", "Evolution Sage",
        "Forgotten Ancient", "Hardened Scales", "Innkeeper's Talent", "Mana Reflection",
        "Minsc & Boo, Timeless Heroes", "Mystic Remora", "Phyrexian Arena", "Rhystic Study",
        "Sensei's Divining Top", "Smothering Tithe", "Starfield of Nyx", "Tatyova, Benthic Druid",
        "The Ozolith", "Trading Post", "Xolatoyac, the Smiling Flood",
    },
    "graveyard_hate": {"Kunoros, Hound of Athreos", "Lion Sash", "Rest in Peace"},
    "land_synergy": {
        "Avenger of Zendikar", "Azusa, Lost but Seeking", "Baldur's Gate", "Basilisk Gate",
        "Cloudpost", "Copy Land", "Dark Depths", "Desert Warfare", "Dryad of the Ilysian Grove",
        "Glimmerpost", "Hakbal of the Surging Soul", "Horizon of Progress", "Lord of the Unreal",
        "Mana Reflection", "Maze's End", "Omo, Queen of Vesuva", "Oracle of Mul Daya",
        "Planar Nexus", "Rampaging Baloths", "Ramunap Excavator", "Sage of the Maze",
        "Scute Swarm", "Spelunking", "Tatyova, Benthic Druid", "Thespian's Stage",
        "Trenchpost", "Ulvenwald Hydra", "Urza's Mine", "Urza's Power Plant", "Urza's Tower",
        "Vesuva", "Wonderscape Sage", "Xolatoyac, the Smiling Flood",
    },
    "lifegain_payoff": {
        "Ajani's Pridemate", "Angel of Vitality", "Cosmos Elixir", "Defiant Bloodlord",
        "Elenda, Saint of Dusk", "Elenda's Hierophant", "Essence Channeler", "Exemplar of Light",
        "Fiendish Panda", "Leyline of Hope", "Marauding Blight-Priest", "Polluted Bonds",
        "Sigarda's Splendor", "Sorin of House Markov", "Twinblade Paladin",
    },
    "protection": {
        "Alseid of Life's Bounty", "Celestial Armor", "Fanatical Devotion", "Fierce Guardianship",
        "Glen Elendra Archmage", "Heroic Intervention", "Inspiring Call", "Liliana the Faultless",
        "Parallax Wave", "Swiftfoot Boots", "Valorous Stance",
    },
    "ramp": {
        "Azusa, Lost but Seeking", "Cultivate", "Dryad of the Ilysian Grove", "Elvish Rejuvenator",
        "Eureka Moment", "Farseek", "Goblin Anarchomancer", "Growth Spiral", "Hour of Promise",
        "Kodama's Reach", "Mana Reflection", "Nature's Lore", "Oracle of Mul Daya", "Rampant Growth",
        "Sakura-Tribe Elder", "Solemn Simulacrum", "The Earth Crystal", "Three Visits", "Urban Evolution",
        "Uro, Titan of Nature's Wrath", "Wayfarer's Bauble", "Xolatoyac, the Smiling Flood",
    },
    "recursion": {
        "Animate Dead", "Body Double", "Chthonian Nightmare", "Dance of the Dead", "Eternal Witness",
        "Funeral Room // Awakening Hall", "Karmic Guide", "Necromancy", "Nullpriest of Oblivion",
        "Ramunap Excavator", "Replenish", "Reveillark", "Starfield of Nyx", "Sun Titan",
        "The Cruelty of Gix", "The Restoration of Eiganjo", "Trading Post", "Vesperlark",
        "Victor, Valgavoth's Seneschal", "Zombify",
    },
    "removal": {
        "Acidic Slime", "Aggressive Biomancy", "Akroma's Vengeance", "All Will Be One", "Beast Within",
        "Blasphemous Act", "Blast Zone", "Breathe Your Last", "Changing Loyalty", "Chandra's Ignition",
        "Chaos Warp", "Curse of the Swine", "Darksteel Mutation", "Deadly Riposte", "Death Grasp",
        "Devouring Light", "Doomwake Giant", "Elspeth Conquers Death", "Evacuation", "Fling",
        "Grasp of Fate", "Hero's Downfall", "High Priest of Penance",
        "Kazuul's Fury // Kazuul's Cliffs", "Leonin Relic-Warder", "Loran of the Third Path",
        "Moment of Craving", "Murder", "Noxious Gearhulk", "Oblivion Ring", "Parallax Wave", "Pongify",
        "Prayer of Binding", "Ram Through", "Terastodon", "The Meathook Massacre",
        "Touch the Spirit Realm", "Utter End", "Valorous Stance", "Whelming Wave",
    },
    "sacrifice_outlet": {
        "Fanatical Devotion", "Fallen Ideal", "Fling", "Kazuul's Fury // Kazuul's Cliffs",
        "Lazotep Quarry", "Trading Post", "Viscera Seer",
    },
    "tutor": {
        "Crop Rotation", "Diabolic Tutor", "Dimir House Guard", "Enlightened Tutor", "Expedition Map",
        "Gifts Ungiven", "Gravebreaker Lamia", "Hour of Promise", "Invasion of Theros",
        "Rune-Scarred Demon", "Sylvan Scrying", "The Cruelty of Gix", "Ulvenwald Hydra", "Vampiric Tutor",
    },
    "token_production": {
        "Angel of Invention", "Elenda's Hierophant",
        "Minsc & Boo, Timeless Heroes",
    },
    "wincon": {
        "All Will Be One", "Chandra's Ignition", "Dark Depths", "Debt to the Deathless", "Exsanguinate",
        "Grim Guardian", "Maze's End", "Minsc & Boo, Timeless Heroes", "The Meathook Massacre",
        "Unnatural Growth",
    },
}


PACKAGES = {
    "reaminatour": [
        {
            "package_id": "lark_recursion_loop",
            "label": "Lark recursion loop",
            "description": "Reveillark/Karmic Guide recursion with a sacrifice outlet and compatible bodies.",
            "members": {
                "Reveillark": "recursion engine",
                "Karmic Guide": "reanimation link",
                "Body Double": "copy link",
                "Viscera Seer": "sacrifice outlet",
                "Fanatical Devotion": "alternate sacrifice outlet",
                "Vesperlark": "small-body recursion",
            },
        },
        {
            "package_id": "aminatou_felidar_blink",
            "label": "Aminatou/Felidar blink loop",
            "description": "Aminatou and Felidar Guardian repeatedly reset one another and reuse ETB value.",
            "members": {
                "Aminatou, the Fateshifter": "blink engine",
                "Felidar Guardian": "blink link",
            },
        },
    ],
    "minsc_boo": [
        {
            "package_id": "counter_multiplication",
            "label": "Counter multiplication package",
            "description": "Overlapping counter multipliers and counter-preservation engines for Boo and other threats.",
            "members": {
                "Branching Evolution": "counter multiplier",
                "Hardened Scales": "counter multiplier",
                "Innkeeper's Talent": "counter multiplier",
                "Vorinclex, Monstrous Raider": "counter multiplier",
                "Ozolith, the Shattered Spire": "counter multiplier",
                "The Ozolith": "counter preservation",
                "Minsc & Boo, Timeless Heroes": "counter source and payoff",
            },
        }
    ],
    "omo": [
        {
            "package_id": "dark_depths_copy",
            "label": "Dark Depths copy package",
            "description": "Copies Dark Depths without its ice counters to create Marit Lage.",
            "members": {
                "Dark Depths": "token source",
                "Thespian's Stage": "zero-counter copy",
                "Mirage Mirror": "temporary zero-counter copy",
            },
        },
        {
            "package_id": "mazes_end_gates",
            "label": "Maze's End Gate package",
            "description": "Uses Gate identities and land-copy effects to assemble Maze's End's alternate win condition.",
            "members": {
                "Maze's End": "win condition",
                "Omo, Queen of Vesuva": "land-type enabler",
                "Planar Nexus": "land-type enabler",
                "Baldur's Gate": "Gate payoff",
                "Basilisk Gate": "Gate payoff",
                "Simic Guildgate": "Gate",
                "Copy Land": "Gate copy",
                "Vesuva": "Gate copy",
                "Thespian's Stage": "Gate copy",
            },
        },
        {
            "package_id": "urzatron",
            "label": "Urza land package",
            "description": "Assembles Urza's Mine, Power-Plant, and Tower identities for large mana production.",
            "members": {
                "Urza's Mine": "Urza land",
                "Urza's Power Plant": "Urza land",
                "Urza's Tower": "Urza land",
                "Omo, Queen of Vesuva": "land-type enabler",
                "Planar Nexus": "land-type enabler",
            },
        },
    ],
    "elenda": [
        {
            "package_id": "lifegain_drain",
            "label": "Lifegain/drain package",
            "description": "Turns life gain and high life totals into counters, pressure, and table-wide life loss.",
            "members": {
                "Elenda, Saint of Dusk": "commander payoff",
                "Defiant Bloodlord": "drain payoff",
                "Marauding Blight-Priest": "drain payoff",
                "Ajani's Pridemate": "counter payoff",
                "Essence Channeler": "counter payoff",
                "Debt to the Deathless": "mass drain",
                "Exsanguinate": "mass drain",
            },
        }
    ],
}


COMBO_MEMBER_NAMES = {
    "Reveillark", "Karmic Guide", "Body Double", "Viscera Seer", "Fanatical Devotion",
    "Vesperlark", "Aminatou, the Fateshifter", "Felidar Guardian", "Dark Depths",
    "Thespian's Stage", "Mirage Mirror",
}


def inferred_roles(card: object) -> dict[str, str]:
    name = card.name
    low = card.text.lower()
    roles: dict[str, str] = {}

    def add(role: str, source: str = "seed:oracle_heuristic") -> None:
        roles.setdefault(role, source)

    for role, names in CURATED.items():
        if name in names:
            add(role, "seed:curated_baseline")

    if name in MANA_ROCKS or name in MANA_DORKS:
        add("ramp", "seed:existing_mana_classification")
    if "counter target spell" in low or "counter all other spells" in low:
        add("counterspell")
    if "search your library" in low and "shuffle" in low:
        add("tutor")
    if "draw a card" in low or "draw two cards" in low or "draw three cards" in low or "draw x cards" in low:
        add("card_advantage")
    if any(phrase in low for phrase in ("scry ", "surveil ", "look at the top three", "look at the top five", "rearrange them")):
        add("card_selection")
    if "create a" in low and "token" in low:
        add("token_production")
    if "lifelink" in low or "you gain" in low or "gain that much life" in low or "extort" in low:
        add("lifegain")
    if "whenever you gain life" in low or "if you have at least" in low and "more life" in low:
        add("lifegain_payoff")
    if "+1/+1 counter" in low or "proliferate" in low or "double the number of each kind of counter" in low:
        add("counter_synergy")
    if any(phrase in low for phrase in ("return target card from your graveyard", "return target creature card from your graveyard", "you may play lands from your graveyard", "cast target", "from your graveyard")):
        if "exile target" not in low:
            if name != "Sunken Palace":
                add("recursion")
    if any(phrase in low for phrase in ("destroy target", "exile target", "return target creature to its owner's hand")):
        add("removal")
    if any(phrase in low for phrase in ("hexproof", "gains indestructible", "gain indestructible", "protection from")):
        add("protection")
    if name in COMBO_MEMBER_NAMES:
        add("combo_piece", "seed:named_package")
    return roles


def package_payload(deck_id: str) -> list[dict[str, object]]:
    result = []
    for package in PACKAGES.get(deck_id, []):
        result.append(
            {
                "package_id": package["package_id"],
                "label": package["label"],
                "description": package["description"],
                "members": [
                    {"card_id": canonical_card_id(name), "member_role": member_role}
                    for name, member_role in sorted(package["members"].items())
                ],
                "notes": [],
                "status": "active",
                "source": "seed:curated_baseline",
                "revision": 1,
            }
        )
    return result


def cards_for_deck(source_deck: str) -> list[tuple[object, int]]:
    """Project the parent catalog's provenance into one deck profile."""

    rows: list[tuple[object, int]] = []
    for card in CATALOG.cards:
        occurrence = next((item for item in card.source_decks if item.deck == source_deck), None)
        if occurrence is not None:
            rows.append((card, occurrence.quantity))
    return rows


def build_payload() -> dict[str, object]:
    roles = [
        {
            "role_id": role_id,
            "label": label,
            "description": description,
            "aliases": [],
            "status": "active",
            "source": "seed:initial_vocabulary",
            "revision": 1,
        }
        for role_id, (label, description) in sorted(ROLE_DEFINITIONS.items())
    ]
    decks = []
    for engine_deck, (deck_id, label, commander) in DECKS.items():
        entries = []
        for card, quantity in sorted(cards_for_deck(engine_deck), key=lambda value: value[0].card_id):
            roles_for_card = inferred_roles(card)
            notes = []
            if deck_id == "reaminatour" and card.name == "Liliana the Faultless":
                notes.append(
                    {
                        "note_id": "user_liliana_hold_protection",
                        "text": (
                            "Preserve Liliana's untapped protection ability through the opposing turn cycle "
                            "when an important creature may need shielding. Do not attack merely because "
                            "protection is unnecessary at the current moment."
                        ),
                        "source": "user",
                        "locked": True,
                        "revision": 1,
                        "contexts": ["combat", "priority", "opponent_turn_cycle"],
                        "confidence": 1.0,
                    }
                )
            if deck_id == "reaminatour" and card.name == "Glen Elendra Archmage":
                notes.append(
                    {
                        "note_id": "user_glen_instant_reanimation_counter",
                        "text": (
                            "Remember the clever line of reanimating Glen Elendra Archmage at instant speed "
                            "in response to a noncreature spell. Once Glen enters and priority reaches you "
                            "again, pay {U} and sacrifice it to counter that spell."
                        ),
                        "source": "user",
                        "locked": True,
                        "revision": 1,
                        "contexts": [
                            "priority", "counterspell_response", "necromancy_target",
                            "reanimation_target", "stack",
                        ],
                        "confidence": 1.0,
                    }
                )
            entries.append(
                {
                    "card_id": canonical_card_id(card.name),
                    "card_name": card.name,
                    "quantity": quantity,
                    "roles": [
                        {"role_id": role_id, "source": source, "revision": 1}
                        for role_id, source in sorted(roles_for_card.items())
                    ],
                    "notes": notes,
                }
            )
        decks.append(
            {
                "deck_id": deck_id,
                "label": label,
                "commander_card_id": canonical_card_id(commander),
                "revision": 1,
                "cards": entries,
                "packages": package_payload(deck_id),
            }
        )
    return {"schema_version": 1, "revision": 1, "roles": roles, "decks": decks}


def render_payload() -> str:
    return json.dumps(build_payload(), ensure_ascii=False, indent=2) + "\n"


def learned_inventory_matches_seed(current: dict[str, object], seed: dict[str, object]) -> bool:
    """Validate generated deck identity without erasing post-game learning.

    Revision-one files are byte-checked below.  Later revisions are intentionally
    authoritative for notes, roles, assignments, and packages, so only their
    catalog-derived physical deck inventory may be compared with the bootstrap.
    """
    def inventory(payload: dict[str, object]) -> dict[str, tuple[str, tuple[tuple[str, int], ...]]]:
        result = {}
        for deck in payload.get("decks", []):
            result[str(deck["deck_id"])] = (
                str(deck["commander_card_id"]),
                tuple(sorted((str(card["card_id"]), int(card["quantity"])) for card in deck["cards"])),
            )
        return result
    return int(current.get("schema_version", 0)) == int(seed.get("schema_version", 0)) and inventory(current) == inventory(seed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write JSON here; otherwise print to stdout")
    parser.add_argument(
        "--check", action="store_true",
        help="byte-check revision 1, or validate generated deck inventory while preserving learned revisions",
    )
    args = parser.parse_args(argv)
    rendered = render_payload()
    output = (args.output or DEFAULT_STRATEGY_FILE).resolve()
    if args.check:
        if not output.exists():
            print(f"strategy profile is missing: {output}", file=sys.stderr)
            return 1
        current_bytes=output.read_bytes()
        try:current=json.loads(current_bytes.decode("utf-8"))
        except (UnicodeDecodeError,json.JSONDecodeError) as exc:
            print(f"strategy profile is invalid: {output}: {exc}",file=sys.stderr);return 1
        if int(current.get("revision",1))==1:
            if current_bytes != rendered.encode("utf-8"):
                print(f"strategy profile is stale: regenerate {output}", file=sys.stderr)
                return 1
        elif not learned_inventory_matches_seed(current,build_payload()):
            print(f"learned strategy profile deck inventory is stale: {output}",file=sys.stderr)
            return 1
        print(f"strategy profile is current: {output}")
        return 0
    if args.output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8", newline="\n")
        print(f"wrote {len(rendered.encode('utf-8'))} bytes to {output}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
