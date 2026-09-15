# Draft promotion review — 2026-09-13

The ten entry-land and evoke drafts have been reviewed against every printed
clause and characteristic in the retained catalog at
`7a9a593b998f5b8301c84fe3964b8d09cc77b227`. They now load through
`load_reviewed()` as `catalog:` definitions. The reviewed bundle contains
237 unique cards and 302 deck copies; 97 catalog cards remain unstarted.
The draft bundle was empty immediately after promotion; the subsequent
[linked-exile batch](LINKED_EXILE_CARD_DRAFTS.md) adds two separate drafts.

## Printed-face decisions

| Cards | Review result |
| --- | --- |
| Godless Shrine, Hallowed Fountain, Stomping Ground, Watery Grave | Correct paired basic land subtypes supply both intrinsic mana abilities. Optional payment is exactly two life; decline enters tapped. No duplicate mana activation or cast program. |
| Game Trail, Shineshadow Snarl, Vineglimmer Snarl | Each reveal selector matches either printed land subtype in the entering controller's hand, including nonbasics. Optional reveal and tapped fallback use EntryPayment; a tap activation uses ProduceMana for exactly one of the two printed colors. |
| Mulldrifter | Normal {4}{U}, evoke {2}{U}, flying 2/2, separate draw-two entry trigger and conditional evoke sacrifice. |
| Reveillark | Normal {4}{W}, evoke {5}{W}, flying 4/3. Any battlefield departure triggers return of zero to two own-graveyard creature targets with power at most two. |
| Vesperlark | Normal {2}{W}, evoke {1}{W}, flying 2/1. Any battlefield departure triggers return of one required own-graveyard creature target with power at most one. No optional return instruction is added. |

All ten programs retain their existing shared composition. Only their definition
identity changes from `draft:` to `catalog:`; no new interpreter behavior or
card-name dispatch is introduced. Each reviewed row includes a specific
`review_basis`, `all_printed_faces` scope and a catalog
`source_facts_sha256`. Canonical source bindings were checked against all 227
existing rows before adding the ten new bindings. The retained source facts for
all ten drafts also match the current catalog exactly.

## Interaction and evidence review

The entry-payment fixtures cover optional and exact-life payment, atomic
simultaneous budgets, pre-payment life conditions, entry copying, replacement
ordering, redirects and restoration at pending choices. Accepted payments or
reveals preserve any other tapped-entry instruction. Reveal receipts contain
only selected public names and references; unselected hand cards stay private.

The 18 evoke methods exercise normal and alternative casting costs, both entry
trigger orders, control changes, blink, countering, direct entry and copying,
signed power filters, all departure destinations, simultaneous deaths, partial
target legality and entry prohibitions. Actor archives replay accepted choices,
and spell/target checkpoints retain the same incarnation and payment facts.

The existing hosted evidence is
[run 34764423605](https://github.com/pope-punk/Edhsimulator/actions/runs/34764423605)
at `c54c116f7c087290f4c4568f0f841dd6502c37e1`: 1,231 tests passed on each
of Ubuntu and Windows while these programs were drafts. The land and evoke
fixtures now obtain these programs from the reviewed loader without opting in
draft definitions. A separate test keeps future drafts isolated and bound to
their source facts and authoring inventory. [Promotion validation run 34767022703](https://github.com/pope-punk/Edhsimulator/actions/runs/34767022703)
passed **1,232 tests on each of Ubuntu and Windows**, plus source syntax,
installation and packaged-asset checks, at `0788981d6851606eced204e7fe39b805a0a053e7`.

## Scope and compatibility

This completes card-level authored-program review within the experimental
interpreter's supported envelope. It does not certify a whole pod, introduce
future life-payment prohibitions, dynamic evoke grants, spell copying,
restricted mana, casting zone-cost transactions, or new spell-control semantics.
The production gate remains closed.

Checkpoint schema stays 110 because this change does not modify interpreter
behavior. The bundle fingerprint changes with the promoted definitions; old
checkpoints are not silently accepted or migrated. No existing game is resumed.

All project execution, imports, compilation, installation and tests remain
restricted to GitHub-hosted runners. None ran on the user's computer.

## Rules consulted

The [pinned Comprehensive Rules](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt)
supply intrinsic land mana (305.6), payments and entry replacements
(118.3, 614.1c, 614.12, 616.1), alternative-cost entry facts and evoke
(400.7d, 601.2b/f–h, 702.74a), and trigger/target handling
(603.3b, 603.4, 603.6c, 608.2b). The source baseline is unchanged.

[Edge of Eternities release notes](https://magic.wizards.com/en/news/feature/edge-of-eternities-release-notes)
clarify shock-land tapping;
[Strixhaven release notes](https://magic.wizards.com/en/news/feature/strixhaven-school-mages-and-commander-2021-edition-release-notes-2021-04-16)
clarify reveal subtypes, simultaneous entry and preserved tapped instructions.
[Commander Masters release notes](https://magic.wizards.com/en/news/feature/commander-masters-release-notes)
clarify evoke cost modifications and controller changes;
[Modern Horizons release notes](https://magic.wizards.com/en/news/feature/modern-horizons-release-notes-2019-05-31)
confirm Vesperlark's printed behavior and the response window before sacrifice.

Next implementation: linked exile and return for Oblivion Ring and Leonin
Relic-Warder, using separately triggered abilities and exact source incarnations.
