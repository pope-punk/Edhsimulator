# Token copies and fight: four complete cards

Base: `3c6b2b548c677bc0a0f4326b878f7f390885e63d`, branch `codex/remaining-card-programs`.
This is the second group of four in the continued eight-card batch. The four
mana/convoke cards are in the reviewed library with successful hosted draft and reviewed-loader checks.
These four token programs remain isolated drafts. No local project execution.

## Printed programs

| Card | Complete mapping |
| --- | --- |
| Scute Swarm | Own land entry trigger; test six controlled lands on resolution, creating a plain 1/1 green Insect or a copy of the source, including last known copiable values. |
| Helm of the Host | Normal {4} cast and sorcery-speed {5} equip. Each own beginning of combat creates a copy of the currently equipped creature, or its relevant last known information if Helm departed; remove Legendary in the copy values, then separately grant indefinite haste. |
| Lazotep Quarry | Base colorless mana; tap and sacrifice a controlled creature for any color; sorcery activation paying {X}{2}, tapping and sacrificing a Desert, targeting an owned graveyard creature with mana value X. Exile it and create its 4/4 black Zombie copy. |
| Aggressive Biomancy | {X}{X}{G}{U} sorcery targeting a controlled creature. Create X copies in one entry batch, each gaining a copiable optional targeted entry-fight ability. |

## Shared implementation

`CopyTokens` snapshots the source program and prior copiable type additions.
Counters, orientation, damage, controller changes, equipment grants and temporary
effects are excluded. The base mana cost, name, colors, keywords, activated
abilities, entry replacements, entry counters and entry triggers remain.
Copy exceptions replace only the named characteristic. A creature-type override
retains unrelated land and artifact subtypes; overridden characteristic-defining
power/toughness and all-creature-type definitions are removed. Added abilities
are distinct even when an already modified token is copied again.

Derived programs are content addressed and deduplicated across generations.
The immutable base library and its fingerprint remain unchanged. A separate
read-only registry view exposes derived definitions and their trigger index.
Checkpoints carry parent identifiers and exact copy exceptions; restoration
reconstructs and validates every derived identifier before reading its objects.
Token creation uses the existing atomic entry transaction and records exact
created objects for following effects. Pending replacement choices can resume.

Helm's haste is a subsequent indefinite effect, not a copiable keyword.
`Fight` requires both exact creatures still present and unphased; it snapshots
both powers, clamps negative values to zero, and sends both damage rows through
the existing simultaneous damage batch. Protection, lifelink, deathtouch and
damage observations reuse ordinary damage rules. Fight damage is noncombat;
a creature fighting itself deals twice its power to itself.

Kernel schema **123**, state schema **14**; `rules_copy.py` participates in
implementation identity. No running-game migration or production admission.

## Sources and bindings

The pinned [Comprehensive Rules](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt)
707.2, 707.5, 707.9a-d and 701.14a-d govern copied values, exceptions and fight.
[Zendikar Rising notes](https://magic.wizards.com/en/news/feature/zendikar-rising-release-notes-2020-09-10)
confirm Scute's inherited landfall and last known source.
[Dominaria notes](https://magic.wizards.com/en/news/feature/dominaria-release-notes)
distinguish the equipped creature's departure from Helm's own departure.
[Modern Horizons 3 notes](https://magic.wizards.com/en/news/feature/modern-horizons-3-release-notes)
cover Quarry's creature-type/color exceptions and both cards' retained entry behavior.

| Card ID | Source-facts SHA-256 |
| --- | --- |
| scute-swarm | `89ae041eccf2ba6740a6f1fddfd306b9bd1d2e4c4dcba92b0501265a7708d28b` |
| helm-of-the-host | `9d52634afc7db9e90e7e9ed64e565c83c6e06701bcabcad2f094979f43b009e4` |
| lazotep-quarry | `a43c091e2a528cbd047f338ac27bc14ab5388d7691eddbfbf1815a26a1dfeb8d` |
| aggressive-biomancy | `ab7aecc550843477866d39c44724d51e05835ba1bad2aba7c580e801088a36e8` |

## Hosted validation

The **64 new methods** cover source bindings, printed costs and targets, copies
of copies, changing land thresholds, source departure, phasing, copy exceptions,
entry replacements and triggers, target legality, simultaneous fight, payment
atomicity, token disappearance, public projection and checkpoint recovery.
Expected full suite: **1,917 tests on each of Ubuntu and Windows**.
Draft and required reviewed-loader checks are pending.

Initial [draft run 34837070723](https://github.com/pope-punk/Edhsimulator/actions/runs/34837070723)
ran 1,853 existing methods on Windows and found one inventory failure and one
class-setup error. The compiler now carries the action's X permission into its
target-characteristic filter, with a regression rejecting X bounds on non-X
actions. The inventory uses the established pending-review label. A fixture also
uses the existing zone-entry attributes rather than unsupported setup keywords.

[Second draft run 34837749840](https://github.com/pope-punk/Edhsimulator/actions/runs/34837749840)
ran 1,916 methods on Windows with one failure and fourteen errors. X is now
also bound during target announcement. An actor replay checks Quarry's exact
X, payment and copied result. The earlier unsupported-X expectation now permits
bound X while preserving rejection of unbound results. Remaining errors came
from fixture ability names, automatic singleton choices and explicit base P/T.
