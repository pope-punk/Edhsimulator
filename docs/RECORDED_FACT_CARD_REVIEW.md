# Recorded casting, entry and payment facts

Cycle base: `ce0631cfcf0171463dfc58d7f11718b5230a0001` on `codex/remaining-card-programs`.
Four complete printed programs are source-bound and promoted after hosted draft checks.
The required reviewed-loader check remains pending.
No project code, Python, imports, installation, compilation, tests or games ran locally.

## Printed-face mapping

| Card | Complete behavior |
| --- | --- |
| Necromancy | Normal {2}{B} enchantment with instant permission. Capture sorcery eligibility before its cast joins the stack. A non-sorcery cast resolving into a permanent schedules its exact next-cleanup sacrifice by its current controller. Entry targets a creature card in any graveyard and requires Necromancy to remain. Ongoing Aura subtype, exact enchant rule, return, attachment and delayed leaves sacrifice compose existing interpreters. Failed returns leave an unattached Aura for normal state-based removal. |
| Nullpriest of Oblivion | Normal {1}{B} 2/1 with menace and lifelink. Kicker adds {3}{B} to the chosen normal or alternative cost before reductions. Its authenticated declaration becomes a noncopiable entry fact. Only kicked entry targets and returns a creature card from its controller's graveyard. |
| Sigarda's Splendor | Normal {2}{W}{W} enchantment. Entry replacement notes its controller's life without using the stack. Own upkeep compares current life with this incarnation's last note, draws if at least as high, then notes current life whether or not it drew. Each actual own white spell cast gains one life. |
| Wonderscape Sage | Normal {1}{U} 1/3 flyer. Tap and return one controlled land before responses. Draw, then discard unless the paid land had a nonbasic land subtype. Capture derived battlefield subtypes before payment, including copies and everything counters. Use the pinned nonbasic-land subtype set; Basic supertype is irrelevant. |

Karmic Guide remains unstarted for full protection and echo. Sage shares existing
cost transactions and subtype vocabulary.

## Shared semantics

Kicker is an additional cost, not an alternative total. It combines with an
alternative and precedes reductions; command tax retains its existing order.
Malformed, stale or forged quotes and insufficient payments fail before mutation.
Actor records show kicker and Necromancy's captured cast-timing fact.

Cleanup sacrifice is created by resolving the spell, not by an entry trigger.
It survives entry-trigger counters and control changes and cannot follow a new
incarnation. Existing cleanup processing handles discards, expiring turn effects,
delayed triggers, priority and repeated cleanup. Phased objects cannot be
sacrificed; a one-shot delay is still consumed. Noncopiable Aura conversion shares
the same ongoing characteristic effects used for token grants. Quantity
comparisons guard continuations requiring an actual movement result.

Life notes use exact object keys and remain available to abilities already on
the stack after their source leaves. New incarnations get independent notes.
Control changes preserve notes while abilities use their captured controllers.
Phasing preserves notes. Entry-copy replacement precedes the copied noting
ability. Replacement proposals capture life after earlier reserved payments and
commit notes only for accepted battlefield entries. Public packets show current
battlefield notes without following later hidden incarnations.

Paid-subtype observations are restricted to public battlefield payments and use
derived characteristics before cards move or lose copy/counter effects. Suspended replacement choices rebuild pure observations;
no payment is repeated. Public summaries do not disclose unrelated hands.

## Bound sources

Catalog facts supply every printed face. The pinned
[Comprehensive Rules](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt)
retain SHA-256 `4381ad1b39ab2c05f7d03633a20f711ed37277074d3266dcba5f38cbb527423f`.
Review includes 307.5a, 514.1-3a, 601.2b/f-h, 603.7, 614.1c, 614.12,
608.2h, 702.33 and existing Aura/identity rules.
[Midnight Hunt release notes](https://magic.wizards.com/en/news/feature/innistrad-midnight-hunt-release-notes)
confirm Sigarda updates its note even when no card is drawn.
[Modern Horizons 3 release notes](https://magic.wizards.com/en/news/feature/modern-horizons-3-release-notes)
confirm Sage uses former subtypes, including copies and Omo's everything counters.
Nullpriest's kicker follows CR 702.33; Zendikar's release notes contain no
card-specific entry for it.

| Card ID | Exact source-facts SHA-256 |
| --- | --- |
| necromancy | `c4554821addaf30621d06969189768655c9c2ddaca978644a18947a6926bfeca` |
| nullpriest-of-oblivion | `6b42815f3e64ee0ba89e951d5301ff822305782d6d98e0e92da4895fbb8609cf` |
| sigarda-s-splendor | `361531c0139fbe7ab320f3725346f3c87a59c04635651f7e93d88f27bbe72008` |
| wonderscape-sage | `bbc98a6da6e605773cc013aef7c4f39e0bff8f0cb593c619cf5f8f67233e0438` |

## Conformance and compatibility

The **63 new methods** in `tests/test_rules_primitives_recorded_facts.py`
cover full printed facts and costs; kicker composition/reductions/atomicity;
cast timing and actual cleanup; Aura legality and copying; counter/removal/
replacement cases; exact notes and control; phasing; paid subtypes; privacy;
checkpoint restoration and authenticated actor replay.

Kernel schema is **120**; state schema remains **13**. The historical
schema-119 test accepts its layout or newer and still rejects 118.
No started game or checkpoint is migrated. Production admission remains closed.
The corrected draft check passed. The required reviewed-loader check is pending.

## Initial hosted attempt

Run `34796156600` passed syntax, installation and packaged assets.
Windows ran 1,609 existing tests with one failure and two errors; Ubuntu was
cancelled by matrix fail-fast. An extra GainLife JSON field rejected Sigarda's
draft and prevented the 63 new methods from loading. The compiler also exposed
an existing intentionally fenced activation-statistic path. The correction
removes that field and restricts new subtype bindings to public battlefield
payments, preserving the old statistic gate and hidden-cost privacy. A corrected
hosted run passed before promotion.

Run `34796570052` loaded all drafts and ran 1,672 tests. The 1,609
existing methods passed; 61 new methods stopped in a shared fixture that omitted
LoseLife's required player domain. The corrected helper supplies that domain.
Waiting ability packets also retain their exact source life note after source
departure, so public decision context remains self-contained. Both changes
are covered by the next required hosted run.

Run `34796928484` ran 1,672 tests on Ubuntu with seven fixture errors
and no assertion failures. Those Necromancy cases requested an unsupported
end-step scenario window. They now use an opponent's supported main-phase
window, which still cannot satisfy the caster's sorcery timing. The actual
turn/cleanup integration passed and is unchanged; the runtime fixture gate
remains intact. The corrected draft validation below passed on both required platforms.


[Corrected draft validation 34797317071](https://github.com/pope-punk/Edhsimulator/actions/runs/34797317071) passed
**1,672 tests on each of Ubuntu and Windows**, plus syntax, installation and
packaged assets, at `825827f67c5d3f4fc8397b6cede516d1d1b0862c`.
All four programs now load through source-bound reviewed metadata. Coverage is
**270 unique cards / 335 deck copies**, with **64 unstarted / 65 copies**.
All 266 prior reviewed rows are unchanged. The required reviewed-loader run
is pending; production and gameplay admission remain separate.

## Reviewed-loader correction

Run `34797724871` ran 1,672 tests on Windows with one inventory-count
assertion failure; Ubuntu was cancelled by matrix fail-fast. The shared
promotion audit still expected 39 cards after its explicit set grew to 43.
The correction updates that count and also recognizes `CleanupCast`'s printed
instant permission in the following generic timing assertion. Source, printed
face and codec checks remain intact. The corrected reviewed-loader run is pending.
