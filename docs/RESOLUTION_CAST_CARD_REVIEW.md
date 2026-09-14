# Casting during resolution: source and implementation review

Status: source-bound reviewed programs; required reviewed-loader validation pending.
Base: `8f2c947759f204e42014edfe1a654d0832d6ce46`. Kernel/state schemas: **128/17**.
No local project execution. Production admission remains closed.

## Printed scope

- Rishkar's Expertise: draw the current greatest controlled-creature power,
  then offer one hand spell with mana value at most five without its mana cost.
- Hidden Nursery: tapped Cave entry, green mana, and sorcery-only five-mana,
  tap-and-sacrifice activation that discovers four.
- Apex Devastator: ten-mana 10/10 Chimera Hydra with four independent cascade
  cast triggers. Correct the catalog's omitted Hydra subtype.

- Oracle of Mul Daya: cumulative additional land play, current top-card reveal,
  and exact top-land permission under normal land-play timing and budgets.

## Primary rules reviewed

[Aether Revolt release notes](https://magic.wizards.com/en/news/feature/aether-revolt-release-notes-2017-01-06)
confirm the Expertise timing, draw calculation, zero-power case and ability to
cast a newly drawn card. [Ixalan release notes](https://magic.wizards.com/en/news/feature/the-lost-caverns-of-ixalan-release-notes)
confirm discover's hand fallback and additional-cost rules.
[Commander Legends release notes](https://magic.wizards.com/en/news/feature/commander-legends-release-notes-2020-11-06)
confirm Apex's printed types and four separate triggers.
[Current Comprehensive Rules](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt)
608.2g, 701.57 and 702.85 govern the exact continuation and current cascade limits.
The retained CR text hash is
`4381ad1b39ab2c05f7d03633a20f711ed37277074d3266dcba5f38cbb527423f`.

## Shared implementation

An actor-bound resolution-cast window retains its parent and grants no priority.
The ordinary cast quote retains targets, modes, kicker, replicate, taxes and
nonmana additional costs; free casting fixes X at zero and excludes alternatives.
An optional authored mana plan announces the spell and locks its cost before
immediate mana abilities. Every choice must be supplied by the actor; incomplete
or invalid plans leave no accepted state. No command in a mana plan gains priority.
Successful casts resume their parents before state-based actions or trigger placement.

Discover and cascade exile from the top one card at a time. Only exact exiled
incarnations belong to the result. Discover moves an uncast hit to hand; cascade
includes it in the random-bottom subset. The untouched library stays ordered.
The random generator and suspended choices survive checkpoints and actor replay.

Oracle composes the existing land-play budget with top-only permissions. Its
reveals track current source control, phasing, each individual draw and CR 401.5
announcement/special-action deferral. CR 401.6 retires old revealed references
when disclosure ends while the card remains in a library. Actor packets carry
only the current authorized top and historical disclosures, never the rest of
the library. [Double Masters 2022 release notes](https://magic.wizards.com/en/news/feature/double-masters-2022-release-notes-2022-06-24)
confirm Oracle's three clauses, cumulative land plays and ordinary timing.

The **85-method draft** passed **2,245 tests on each of Ubuntu and Windows**,
plus syntax, installation and assets, at
`c168dae7c628cde1f37e0381a21a609fe720f088` ([run 34876806875](https://github.com/pope-punk/Edhsimulator/actions/runs/34876806875)).
The **94-method required reviewed-loader run** is pending. The initial
three-card run executed 2,217 tests on Ubuntu with two failures and two errors:
incorrect kicker and Gate fixtures, plus a missing canonical-reference update.
These are corrected before the expanded run. Existing limitations
for unreviewed split/Room/transform programs remain gated by the reviewed loader.
Chthonian Nightmare remains queued for complete energy and ordered costs.

## Promotion review corrections

The required reviewed-loader run includes nine additional regressions and three
focused corrections: library-moving effects follow CR 605.1a's mana-ability
classification; bottom/top placement and surveil finish before top disclosure;
and face-up resolution exiles remain available as historical public evidence even
without a hit. Other regressions cover uninterrupted sequential offers, copied
Oracle permissions and failed-draw state-based actions. These corrections are
not attributed to the earlier 85-method draft proof.

## Source bindings

- `rishkar-s-expertise`: `3f66d02ca36446abfcbad7b739341b71b50cf716bbe14ccff06773e861ebdcb7`
- `hidden-nursery`: `eb589611b11ef161411131bf93fc2de2b25fec7a1dda8a8f44c96d23ae43ad7a`
- `apex-devastator`: `77af1405ee0efd9ebb3f5dc4d00dfeca21c23d976984ccf0e942e9c611e3ac4d`
- `oracle-of-mul-daya`: `1d68df5207da1f689698ffb09a39673c0660e5cfbf61922d2bd242cb07a2b549`
