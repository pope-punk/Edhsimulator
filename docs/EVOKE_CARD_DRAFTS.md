# Evoke card authoring — 2026-09-13

This batch adds complete printed programs for Mulldrifter, Reveillark and
Vesperlark to the isolated draft bundle on `codex/remaining-card-programs`.
They are authored drafts awaiting hosted validation and card-level review.
The reviewed bundle remains at 227 unique cards. The outstanding inventory now
contains ten written drafts and 97 unstarted cards, still 107 outside that bundle.

## Card compositions

| Card | Normal cost | Evoke cost | Other printed behavior |
| --- | --- | --- | --- |
| Mulldrifter | {4}{U} | {2}{U} | Flying, 2/2; draw two on entry |
| Reveillark | {4}{W} | {5}{W} | Flying, 4/3; on leaving the battlefield return up to two own graveyard creature cards with power at most 2 |
| Vesperlark | {2}{W} | {1}{W} | Flying, 2/1; on leaving the battlefield return one target own graveyard creature card with power at most 1 |

Reveillark's evoke cost is higher than its normal cost. Both larks use
battlefield-departure events with no destination restriction. Their target
selectors read the creature cards' current graveyard characteristics.

## Shared implementation

`EntryAlternativeCost` extends the existing fixed alternative-cost declaration
with immutable entry flags. Normal quote validation and atomic payment determine
the selected alternative. Only after the cast is accepted does its spell frame
carry those facts into successful battlefield entry. This uses the existing
noncopiable `entry_flags` field, rather than a new counter or a card-name handler.

`EntryFlagCondition` exposes those retained facts to the shared condition
evaluator, including compound conditions and its selector-dependency walker.
Each evoke program has an ordinary self-entry trigger with this intervening
condition. Its `Sacrifice` operation instructs the permanent's current controller
to sacrifice it, even after a controller change.

The entry trigger and a separate printed entry ability receive ordinary ordering
and priority boundaries. Blink creates a new incarnation with no evoke fact; an
old trigger cannot sacrifice the returned object. Countering the evoke trigger
leaves the creature, whereas countering the spell prevents its entry. Direct entry
and copying a creature's definition do not copy payment history.

Fixed costs, reductions and commander tax continue through the existing casting
transaction. Alternative tap-selection costs are explicitly rejected alongside
unsupported casting zone costs. This does not implement restricted mana, casting
zone-cost transactions, dynamic keyword grants, spell copying, or new spell-control
semantics.

## Conformance work

Eighteen new methods in
[test_rules_primitives_evoke.py](../tests/test_rules_primitives_evoke.py) cover:

- Normal and evoke costs, printed mana value, and both Mulldrifter trigger orders.
- Blink, countering, direct entry, Body Double copying, and control changes.
- Lark departure destinations, signed power filters, opposing graveyards,
  required versus optional targets, simultaneous deaths, partial target legality,
  and graveyard-entry prohibitions.
- Cost reduction, commander tax, rejected payments and duplicate actions.
- Actor archive replay, spell and target-choice checkpoints, old-schema rejection,
  condition composition, malformed nodes, and redirected entry.

The existing draft inventory test now validates all ten source-bound programs.
Land-play and entry-payment cases explicitly select only the seven land drafts.

GitHub-hosted validation is pending. No project code, Python, imports, compilation,
package installation, tests, or games ran on the user's computer.

## Compatibility and remaining review

The experimental checkpoint schema advances from 109 to 110; implementation
fingerprints bind the modified program, casting, condition and kernel modules.
The state schema and reviewed card definitions are unchanged. No migration of
an existing checkpoint or started game is provided.

The next review pass should promote only drafts whose complete printed clauses,
source facts, interaction evidence and hosted results satisfy the reviewed-bundle
process. Keep that decision separate from whole-pod or production admission.
After that, the next implementation family is linked exile/return for Oblivion
Ring and Leonin Relic-Warder, followed by casting zone costs for Crop Rotation
and Fling.

## Rules references

The retained catalog facts bind each card's text and printed characteristics.
The existing [Comprehensive Rules baseline](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt),
effective August 7, 2026, supplies evoke (702.74a), entry information (400.7d),
alternative-cost calculation (601.2b/f–h), triggers (603.3b/603.4) and target
revalidation (608.2b).

[Commander Masters release notes](https://magic.wizards.com/en/news/feature/commander-masters-release-notes)
clarify evoke's timing, cost modifications, and controller changes.
[Modern Horizons release notes](https://magic.wizards.com/en/news/feature/modern-horizons-release-notes-2019-05-31)
cover Vesperlark and the response window before sacrifice.
[Lorwyn Eclipsed release notes](https://magic.wizards.com/en/news/feature/lorwyn-eclipsed-release-notes)
confirm ordering the creature's other entry triggers relative to evoke.
These references do not change the pinned rules baseline.
