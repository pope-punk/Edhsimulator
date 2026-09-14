# Casting during resolution: source and implementation review

Status: drafted; hosted validation and source-bound promotion pending.
Base: `8f2c947759f204e42014edfe1a654d0832d6ce46`. Kernel/state schemas: **128/17**.
No local project execution. Production admission remains closed.

## Printed scope

- Rishkar's Expertise: draw the current greatest controlled-creature power,
  then offer one hand spell with mana value at most five without its mana cost.
- Hidden Nursery: tapped Cave entry, green mana, and sorcery-only five-mana,
  tap-and-sacrifice activation that discovers four.
- Apex Devastator: ten-mana 10/10 Chimera Hydra with four independent cascade
  cast triggers. Correct the catalog's omitted Hydra subtype.

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

Current tests: **57 new methods**; draft results pending. Existing limitations
for unreviewed split/Room/transform programs remain gated by the reviewed loader.
Chthonian Nightmare remains queued for complete energy and ordered costs.
