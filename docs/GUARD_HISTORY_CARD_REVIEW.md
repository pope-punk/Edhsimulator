# Eight cards: guards, replacement effects and history

Cycle base: `cecda2894b3afb4f67aacd1656acdaff7096fe04`, branch `codex/remaining-card-programs`.
All eight complete printed programs are source-bound in the reviewed bundle.
Corrected draft checks passed; required reviewed-loader validation is pending. No project code, Python, imports, installation,
compilation, tests or games ran on the user's computer.

## Complete printed-face mapping

| Card | Implementation |
| --- | --- |
| Karmic Guide | {3}{W}{W} 2/2 Angel Spirit; flying, protection from black; own-graveyard creature return; echo {3}{W}{W}. Echo uses real acquisition timestamps against the prior own upkeep and an independent optional mana payment with controller-limited sacrifice. |
| Alseid of Life's Bounty | {W} 1/1 enchantment creature Nymph with lifelink. Pay {1} and sacrifice the source, target a controlled creature or enchantment, choose a color at resolution and grant protection through cleanup. The target relation is control, not ownership. |
| Fanatical Devotion | {2}{W} enchantment. Sacrifice a controlled creature as an authenticated cost, then regenerate any legal target creature. Sacrificing the target pays the cost but leaves no recipient. |
| Pongify | {U} instant. Destroy a creature without regeneration; its resolution-time controller creates a 3/3 green Ape even if destruction fails or changes destination. All-illegal-target resolution creates nothing. |
| Dimir House Guard | {3}{B} 2/3 Skeleton with fear. Sacrifice a creature to regenerate itself. Transmute {1}{B}{B} is a sorcery-timed hand activation with source discard, mana-value-bound search, reveal, optional failure to find and shuffle. |
| Midnight Snack | {2}{B} enchantment. Own end-step raid creates a complete Food token. Pay {2}{B} and sacrifice the source to make a targeted opponent lose the controller's actual life gained this turn, read at resolution. |
| Restart Sequence | {3}{B} sorcery returning an own-graveyard creature. Freerunning {1}{B} reuses alternative-cost selection with an authenticated qualifying combat-damage fact. Ordinary timing remains required. |
| Jyoti, Moag Ancient | {2}{G}{U} legendary 2/4 Elemental. Entry creates complete 1/1 green Forest Dryad land creatures for all own command-zone casts. Each combat grants current own land creatures a frozen modifier equal to current or last-known source power, through cleanup; a negative source power yields a zero bonus (CR 107.1b). |

## Shared implementation and review

Color protection uses one derived-characteristic predicate in target queries,
combat blocking, pre-damage prevention, attachment legality and nontargeting
Aura entry. Prevented damage does not generate damage events or lifelink gains.
Source colors use current information or the existing last-known-information
path. Previously legal blocks retain their blocked status after protection is
gained. Only the five color qualities required by this batch are admitted;
unimplemented protection variants remain rejected.

Regeneration is part of the pure zone-proposal replacement pipeline. Competing
effects are selected by the affected player before any state mutation. The
accepted batch commits regeneration with simultaneous moves, counter cancellation
and detachment. A shield has an exact recipient, is consumed once, clears damage,
taps that recipient and removes it from combat. Creating the shield does none of
those actions. Cleanup expires unused shields, including those on phased objects.
Indestructible, sacrifice, zero toughness, legend losses and illegal Auras retain
their distinct behavior. Pongify uses an explicit destruction subtype.

Echo uses existing continuous-control timestamps and a separate upkeep ledger.
Its creation condition records a historical occurrence that later source
departure or control changes cannot undo. Its payment remains independent of
the source, while sacrifice retains the usual controller and incarnation checks.
Phased sources do not trigger; the player's upkeep boundary still advances.

Public turn history records accepted declarations and actual positive combat
damage. Freerunning captures source type, commander identity and controller
before damage consequences; lifelink-created type changes cannot retroactively
qualify the event. State life-gain totals include ordinary and replacement-adjusted
lifelink gains independently of life loss and reset on every turn.

Resolving player statistics reuse the effect quantity interpreter. Dynamic
selector bounds now share one helper between ordinary queries and authorized
library searches, preserving the search visibility protocol. Temporary power/toughness grants reuse the existing frozen nonnegative source
statistic. Signed comparison and explicit doubling paths retain their existing semantics. The kernel
implementation manifest includes both the new guard module and the previously
omitted phasing module.

Kernel schema is **121** and state schema **14**. Old checkpoints are rejected;
started games are not migrated. Public packets expose only public history and
current shield recipients. Production and gameplay admission remain separate.

## Sources and exact bindings

The pinned [Comprehensive Rules](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt)
retain SHA-256 `4381ad1b39ab2c05f7d03633a20f711ed37277074d3266dcba5f38cbb527423f`.
Relevant rules include color protection 702.16b-f, echo 702.30a, fear 702.36b,
transmute 702.53a, freerunning 702.173a, regeneration 701.19a-c and 614.8,
combat removal 506.4/506.4a, and negative calculated amounts 107.1b.
[Modern Horizons 3 release notes](https://magic.wizards.com/en/news/feature/modern-horizons-3-release-notes)
support Jyoti's commander count and power snapshot.
[Foundations release notes](https://magic.wizards.com/en/news/feature/foundations-release-notes)
support Midnight Snack's attack history and resolution-time life-gain amount.
Every printed face is mapped from the repository's source catalog.

| Card ID | Source-facts SHA-256 |
| --- | --- |
| karmic-guide | `d81e7f6361414795c44c79d16030b188b1e401c21230cc20929a650c03923a1a` |
| alseid-of-life-s-bounty | `72aafe6173c47fe7afdb2abee41877c7e4efa16850be102e2ad0c4cf797eceea` |
| fanatical-devotion | `f7be0201def2cf6165473864aa34fcd7442fde842128f6515a10a4622a3620b2` |
| pongify | `59a5d0c1e859a1c3ed9aa299e6fe9786660dddd0e679631871283f73f923c979` |
| dimir-house-guard | `1380ec20199b20420b44470b2877490acbfd4cc904a786bcc914d29b9e003c45` |
| midnight-snack | `5a86c7ac0130d6285a5c7e85bcdfc96046e48f68243b99c6c13457f21cbafd9d` |
| restart-sequence | `4fa4d35aedf7420ba12a2f72b63bf96344e3d8d74a8ca3e8f9f7d0bc8966e5d5` |
| jyoti-moag-ancient | `947c188cbc40a24a9eb49679457dad9b862694006026980f4f69e8877dc16bd9` |

## Required hosted evidence

The **107 new methods** in
`tests/test_rules_primitives_guard_history.py` cover all eight programs and their
shared semantics, including actual casts and payments, real combat declarations,
replacement ordering, privacy, checkpoint rejection/restoration and actor replay.
Existing historical schema tests keep their minimum-layout assertions; the new
tests require schema 121/14 and reject the immediately prior versions.

Initial draft run [34800692440](https://github.com/pope-punk/Edhsimulator/actions/runs/34800692440)
completed 1779 tests on Ubuntu with two historical state-schema assertion failures
and one incomplete replay-command fixture. These are corrected while preserving
legacy checkpoint rejection and the actor command's strict field validation.
Windows was cancelled by matrix fail-fast. No runtime defect was reported by this run.
Source review then caught an incorrect signed quantity in Jyoti's program.
CR 107.1b requires zero for a negative calculated +X/+X bonus. The program now
uses the existing clamped source statistic. The regression checks both a present
source and last-known negative power after departure; the unnecessary compiler
permission for signed temporary source modifiers is removed. This source-review
correction supersedes [fixture-only validation 34801536529](https://github.com/pope-punk/Edhsimulator/actions/runs/34801536529),
which passed 1779 tests on both platforms at `4c8e634887275bb68bde64186e858995281d16b3`.
Passing that run did not validate the incorrect negative-power expectation.
[Corrected draft validation 34801795555](https://github.com/pope-punk/Edhsimulator/actions/runs/34801795555)
passed **1779 tests on each of Ubuntu and Windows**, plus syntax, installation
and packaged-asset verification, at `f7aa71651971da75381805bbbb30a04b59226bd5`.
All eight source bindings are promoted; the 107 new methods now use the reviewed
loader. Required reviewed-loader validation is pending.

