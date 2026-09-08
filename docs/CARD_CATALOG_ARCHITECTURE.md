# Card-first catalog and pilot memory

The gauntlet has three deliberately separate kinds of knowledge. Keeping these
separate is the central rule of the rebuild.

## 1. Canonical printed-card catalog

`data/catalog/cards.json` is the single runtime catalog for the fixed 400-card
pod. Its 334 parent records are generated deterministically from the frozen
four-deck Oracle reference and curated migration annotations.

Each `CardDefinition` owns:

- stable card identity and literal Oracle text;
- one or more `CardFace` records with cost, mana value, type hierarchy, color,
  printed power/toughness, loyalty, and keywords;
- `AbilitySpec` children describing zone, timing, event, stack/mana status, and
  an optional executable handler reference;
- `EntryReplacementSpec` children for entry behavior;
- structured mana and land metadata; and
- `DeckOccurrence` children recording quantity and exact source-list order.

Reverse indexes such as “all fetchlands,” “all mana dorks,” or “all cards with a
spell-cast trigger” are generated views over those card-owned records. They are
not separately maintained card-name lists.

Regenerate and validate the catalog with:

```powershell
$env:PYTHONPATH = "src"
python tools\generate_card_catalog.py --check
```

## 2. Deck-specific strategy profiles

`data/strategy/deck_profiles.json` contains non-executable pilot memory. It does
not duplicate Oracle text and rules code must never consult it to decide what is
legal or resolve an effect.

Each `DeckProfile` owns its 100 `DeckCardEntry` records. An entry crosswalks to a
catalog card and may have:

- zero or more strategic role assignments;
- plain-language strategy notes with provenance and useful decision contexts;
  and
- membership in named combo or synergy packages.

The role vocabulary is a separate child collection. The requested role-by-deck
0/1 table is generated from card assignments by
`StrategyState.role_presence_matrix()`. A pilot can first inspect the roles
represented in its deck, then inspect any role to see its options grouped by
current zone.

Strategy notes are advisory text only. Their schema rejects resolver, trigger,
effect, and other executable fields. Locked user guidance cannot be changed by
the post-game learning patch path.

## 3. Mutable game objects and zones

The engine owns runtime `CardObj` and `Perm` instances, unique object IDs, and
player zones. Zone is therefore never stored in the parent catalog or strategy
profile. The inspection service crosswalks a visible runtime object to both its
parent catalog record and that pilot's deck-specific notes.

Out-of-band inspection does not pass priority, advance the RNG, consume a
decision ID, or reveal ordered libraries. Supported queries include:

```powershell
.\gauntlet.cmd inspect object R-42
.\gauntlet.cmd inspect card "Parallax Wave"
.\gauntlet.cmd inspect deck
.\gauntlet.cmd inspect roles
.\gauntlet.cmd inspect role removal
.\gauntlet.cmd inspect role ramp zone=library
.\gauntlet.cmd inspect package "named package"
```

The deck view may identify the remaining cards in its own library because a
Commander pilot knows its submitted list, but it reports that library as an
unordered multiset. Hidden face-down identities produce an explicit uncertainty
pool rather than leaking the referee's omniscient state.

## Game and learning lifecycle

The normative play, terminal-review, learning, and advancement state machine is
defined in `docs/GAUNTLET_WORKFLOW.md`. Its review gate freezes each game's exact
strategy revision, seals all four private evidence packets, and prevents the next
game from starting until a validated learning patch or explicit reviewed
no-change response is recorded.

Strategy operations remain limited to `create_role`, `retire_role`,
`merge_roles`, `assign_role`, `unassign_role`, `add_note`, `replace_note`,
`upsert_package`, and `retire_package`. They are declarative, checked against the
reviewed revision, applied only to future games, and cannot alter the catalog,
rules handlers, completed snapshot, or game state. Python validates and audits
the response; the external reviewer supplies every strategic conclusion.

This yields the intended hierarchy:

```text
Card catalog (printed identity and rules metadata)
  -> faces / abilities / entry replacements / mana / land facts
  -> deck occurrences

Strategy state (inert, learnable pilot knowledge)
  -> role vocabulary and generated per-deck presence matrix
  -> deck profiles
       -> card roles and notes
       -> combo/synergy packages

Game state (mutable objects)
  -> public and private zones
  -> visible object -> catalog + deck-profile crosswalk at inspection time
```
