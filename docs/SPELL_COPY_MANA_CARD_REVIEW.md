# Spell-copy and special-mana card review

Status: complete source-bound reviewed programs; draft and required reviewed-loader
validation passed on both hosted platforms.
Branch: `codex/remaining-card-programs`.
Baseline: `8527eb661827e231b36f429c6efb9f981050df11`.
Kernel/state checkpoint schemas: **127/17**.
Local project execution: **none**. Production admission remains separate.

## Printed programs

| Card | Complete behavior |
|---|---|
| Replication Technique | Demonstrate cast trigger; optional own copy, opponent choice, independently authored targets; token copy of a controlled permanent. |
| Changing Loyalty | Flash, fixed {2} replicate payments, Aura targets and entry, enchanted-creature death successor returned under the Aura controller. |
| Sunken Palace | Cave; tapped entry; ordinary blue; {1}{U}, tap and exactly seven owned graveyard cards exiled for tracked blue mana with a delayed copy rider. |
| Delighted Halfling | {G}, 1/2 Halfling Citizen; ordinary colorless or one of five colors restricted to casting legendary spells, which cannot be countered. |

## Shared boundaries

A spell copy is an independently identified noncard on the stack. A resolving
permanent copy becomes a token through ordinary replacement-aware entry without
a token-created event. Copies outside the stack cease at the next state-action
boundary. Copies do not cast spells or activate abilities.

Copy triggers retain announcement instructions, X, selected modes, targets,
counter divisions and paid additional/alternative-cost decisions even after the
original leaves the stack. Each target clause chooses one retained or legal
new target per original slot simultaneously, preserving arity and permitting
swaps. New targets must obey uniqueness and controller constraints. Demonstrate
finishes the caster's target choices before choosing an opponent, who sees
that copy and copies the original announcement.

Actual casting history is separate from copied cost decisions. Copies did not
escape from a graveyard (CR 702.138b), were not cast outside sorcery timing for
Necromancy, and do not inherit flashback's stack-exit replacement. Evoke and
kicker paid-cost consequences do carry over. Three cross-library regressions
exercise these distinctions without changing the existing reviewed programs.

Mana pools retain total color counts plus individual tagged units. Payments
explicitly identify tagged units; ordinary same-color mana cannot silently
consume them. Restrictions are checked before atomic payment. Legendary mana
may pay any portion of an eligible spell's cost, but cannot pay an activation or
a resolution cost. Counter immunity belongs to the paid frame and is not copied.
Each Palace production instruction has one delayed trigger, including when a
mana replacement multiplies its output. Remaining units retain their type after
that rider is spent. Mana abilities cannot be copied.

## Source evidence

- [Commander 2021 release notes: demonstrate](https://magic.wizards.com/en/news/feature/strixhaven-school-mages-and-commander-2021-edition-release-notes-2021-04-16).
- [Modern Horizons 3 release notes: Sunken Palace](https://magic.wizards.com/en/news/feature/modern-horizons-3-release-notes).
- [Secrets of Strixhaven release notes: Changing Loyalty](https://magic.wizards.com/en/news/feature/secrets-of-strixhaven-release-notes).
- [Tales of Middle-earth release notes: Delighted Halfling](https://magic.wizards.com/en/news/feature/the-lord-of-the-rings-tales-of-middle-earth-release-notes).
- Pinned [Comprehensive Rules](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt), effective August 7, 2026, SHA-256 `4381ad1b39ab2c05f7d03633a20f711ed37277074d3266dcba5f38cbb527423f`: copies, permanent-copy entry, delayed triggers, replicate and demonstrate.

## Validation

65 new hosted methods cover complete source faces and serialization, compiler
rejections, ordinary cast and activation payments, opponent target visibility,
checkpoint continuation, countered originals, copied Aura entry/death/exile,
exact seven-card payment, special-mana identity, doubled and separate riders,
legendary-only payment, counter immunity, resolution payments, target swaps,
X, modes, divided counters, Necromancy, escaped Uro and evoked Mulldrifter.
Draft validation passed **2,159 tests per platform** plus syntax, installation
and packaged assets on Ubuntu and Windows at `5f13db33ccca589d11e1d6c4feae1785ade8d13a`
([run 34868673387](https://github.com/pope-punk/Edhsimulator/actions/runs/34868673387)). Required reviewed-loader validation passed **2,160 tests per platform**,
including **all 65 new methods**, plus syntax, installation and packaged assets,
at `8d29e0e7cf916860c0004605b052b8d3ebd03903` ([run 34869674458](https://github.com/pope-punk/Edhsimulator/actions/runs/34869674458)).

The passing draft run covers 64 new methods. Promotion adds a visibility
correction for copied hand abilities and a 65th regression: retain their
already-public announced source in opponent packets and replay. The successful
reviewed-loader run validates that final code and all 65 methods.

## Following work

Rishkar's Expertise and Hidden Nursery need casting during resolution.
Apex Devastator shares ordered library exile and free casting through four
separate cascade triggers. Chthonian Nightmare needs energy and ordered costs.
Entity Tracker still needs Room-unlock events before its whole printed text can
be claimed complete. Review current source texts before selecting the next batch.

The final result-recording commit changes only this review, the work order and
the inventory. Runtime, card programs, source facts and tests are unchanged
after required reviewed-loader validation. Coverage is **302/334 unique cards
and 368/400 deck copies**, with **32 unique cards / 32 copies remaining**.
