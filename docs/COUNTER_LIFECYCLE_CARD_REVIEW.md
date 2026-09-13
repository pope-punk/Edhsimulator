# Counter lifecycle card review

Source branch: `codex/remaining-card-programs`.
Cycle base: `2cbc5f63a54aa67ae71cddbce5219da350aeec5a`.
Status: all four printed programs are authored in the isolated draft bundle.
Hosted draft validation and reviewed-bundle promotion are pending.
No project code or Python was executed on the user's computer.

## Printed-face mapping

| Card | Printed characteristics | Complete program mapping |
| --- | --- | --- |
| Xolatoyac, the Smiling Flood | {4}{G}{U}; legendary blue/green Salamander Serpent creature; 6/6 | Independent entry and attack triggers target any land, put one flood counter on it, then create an exact-recipient Island addition while it retains a flood counter. Own end step untaps every controlled permanent with any kind of counter. |
| The Earth Crystal | {2}{G}{G}; legendary green artifact | Controlled green spells receive one generic reduction. Controlled creatures receive twice the +1/+1 counters, including as they enter. {4}{G}{G} and tap activate a two-counter placement divided positively among one or two controlled creature targets during announcement. |
| Dark Depths | Legendary snow land; colorless; no mana cost or mana ability | Enters with ten ice counters. The {3} activation removes one ice counter on resolution, as much as possible. A no-ice state trigger sacrifices its exact source and creates the legendary 20/20 black Avatar Marit Lage with flying and indestructible only after a successful sacrifice. |
| Parallax Wave | {2}{W}{W}; white enchantment | Five entry fade counters plus the controller's upkeep remove-or-sacrifice implement Fading 5. Removing a fade counter is the activation cost to exile any creature target. Its independent departure trigger returns all cards still in its linked exile incarnations, simultaneously under their owners' control. |

Ordinary casting/land play, colors, supertypes, subtypes, costs, body statistics,
entry counters and every printed clause are included. Existing catalog facts are
unchanged. Fading is expanded into its two rules abilities; it is not an inert keyword.

## Shared implementation and timing

`RemoveCounters` removes up to the specified amount from exact battlefield
references using the shared atomic counter transaction. It never spends counters
at announcement. Parallax Wave instead retains the existing `CounterCost` for
its activated ability. Its upkeep condition is checked on resolution: removing
the final counter leaves the enchantment in play until a later upkeep at which
no fade counter can be removed.

`WhileCounter` reuses resolved continuous-layer changes with a separate duration
ledger. The recipient set and creator characteristics are captured at resolution.
The effect persists across creator departure, control changes and cleanup.
Losing the last matching counter, leaving the battlefield or phasing out ends
that recipient's duration permanently; a later counter cannot revive it.
A new resolving ability can create a new duration. Untargeted lands with flood
counters receive no grant. Existing land types and abilities remain, and Island
adds its intrinsic blue mana ability. The duration can remain when the creator
is hidden; public packets expose the visible recipient and change, not a hidden
source reference.

`counter_state` scans after atomic interpreter steps, including between
instructions during resolution. Each source incarnation/ability has at most one
pending, stacked or resolving state trigger. Its occupied identity is derived
from those actual frames, retained by checkpoints, and released when that trigger
finishes or leaves the stack. Countering the trigger allows a fresh occurrence
when the condition still holds. Adding ice after occurrence does not undo the
existing trigger. A stolen source cannot be sacrificed by the previous
controller's trigger, and a new incarnation cannot be sacrificed through an old
reference. A replacement that changes a successful sacrifice's destination
still permits token creation.

`PlaceDividedCounters` is restricted to one unconditional, fixed-total division
in an ordinary targeted cast or activation. Announcement supplies a positive
integer share for every target, with the exact total and no duplicate targets.
Malformed, stale or forged proposals fail before payment or mutation. Prepared
quotes, accepted action records, public stack projection, snapshots and replay
retain the division. Resolution rechecks target legality and loses each illegal
target's original share. The shared counter placement planner applies replacement
choices before any recipient receives counters. Unsupported modal, nested,
player or triggered divisions remain rejected.

Parallax Wave reuses `ExileLinked`/`WithLinkedExile`; its return is a separate
trigger. Departure before a pending exile resolves returns the earlier linked
cards first; a subsequent exile is not returned by a future Wave incarnation.
No new card-name dispatch is introduced.

## Sources and exact bindings

The pinned [Comprehensive Rules](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt)
remain unchanged (effective 2026-08-07, SHA-256
`4381ad1b39ab2c05f7d03633a20f711ed37277074d3266dcba5f38cbb527423f`).
Relevant rules are 601.2d/602.2b (announced division), 603.8 (state triggers),
608.2b (target legality), 611.2b/611.2c (durations and fixed recipients),
702.26f (phasing ends tracked durations), 702.32a (Fading), 122.6
(counter placement), 607 (linked abilities) and 118.12 (successful payment).

- [Lost Caverns of Ixalan release notes](https://magic.wizards.com/en/news/feature/the-lost-caverns-of-ixalan-release-notes) support Xolatoyac's printed face and persistent Island grant.
- [Foundations update bulletin](https://magic.wizards.com/en/news/announcements/foundations-update-bulletin) clarifies a newly resolving flood-counter duration after a previous condition ended.
- [Final Fantasy release notes](https://magic.wizards.com/en/news/feature/final-fantasy-release-notes) support The Earth Crystal's reduction, counter replacements and announced division.
- [Dominaria Remastered release notes](https://magic.wizards.com/en/news/feature/dominaria-remastered-release-notes) support Dark Depths' state-trigger lifecycle, no mana ability and successful sacrifice requirement.

The complete catalog source facts are retained with each draft. Promotion binds
those exact facts using the normal reviewed loader:

| Card ID | Source-facts SHA-256 |
| --- | --- |
| xolatoyac-the-smiling-flood | `dec7453e5735bac0ef01878b37a2ce0fae130d6081c9f8e1edffb15eba183b45` |
| the-earth-crystal | `0cabcb8c3fc889dfaedf0d74e1fef0e44797fddbafac8f398d34be5ac513faaa` |
| dark-depths | `f21ac0e6360b17a10ecf19314864436a4b2b4776a69e0111728cef923a8c9c5d` |
| parallax-wave | `fa1e1c46b9e526bfbdc1eb978118fb9ac8ef435c93c72388b8b1c18a3bf2a398` |

## Conformance and compatibility

The 62 new methods in
`tests/test_rules_primitives_counter_lifecycles.py` cover normal casts and land
play, target legality, announcement and paid resources, replacement order,
brief state conditions, countered triggers, control/departure/blink, phasing,
Fading upkeep timing, exact exile links, simultaneous returns, public projections,
compiler rejection, authenticated adapter replay and checkpoint restoration.
The historical counter-transfer schema assertion now accepts its schema or a
newer layout while still rejecting its prior layout.

Kernel checkpoint schema is **117**; state schema remains **13**.
Previous kernel layouts are rejected. No existing game or checkpoint is migrated.
Draft isolation, source-bound review, hosted conformance and production admission
remain distinct; production admission stays closed. General unsupported rules,
including counter-removal prohibitions, are not silently admitted.

Validation is pending. Do not treat the authored scenarios as execution evidence.

## Initial hosted findings

[Run 34782111960](https://github.com/pope-punk/Edhsimulator/actions/runs/34782111960)
ran 1,498 tests on Ubuntu at `f20404e234e443c6951141d429f015f6c4ef7307`;
one new fixture failed because it reused a stale exile reference after returning
a land. Windows was cancelled by matrix fail-fast. The fixture now captures the
returned incarnation explicitly. Independent static review also retained the
suspended resolution-payment parent in state-trigger occupancy, with a new
regression while a mana ability runs. The corrected suite has 62 new methods;
its execution is pending.
