# Resolution payments and draw-trigger enchantments

Branch: `codex/remaining-card-programs`. Source catalog unchanged from
`1d25cf3ff93762b3326190ae7c55486bb1509259`. Review date: 2026-09-13.

## Printed-face review

| Card | Complete mapping |
| --- | --- |
| Dawn of Hope | {1}{W}, white enchantment. Each controller life-gain event creates one optional {2} payment, then one draw if paid. Opponent and zero life gains do not trigger it. {3}{W} creates a white 1/1 Soldier creature token with lifelink. |
| Rhystic Study | {2}{U}, blue enchantment. Each opponent spell cast captures that caster. The caster may pay {1}; nonpayment offers the original trigger controller a separate optional draw. The spell remains below the trigger. |
| Smothering Tithe | {3}{W}, white enchantment. Each actual opponent draw captures that player for an optional {2} payment. Nonpayment creates one Treasure under the trigger controller. Each card in a multiple-card draw triggers separately. |
| Gleaming Splendor | {1}{W}, white enchantment. Each opponent's second actual draw of each turn creates one Treasure. Draw history includes earlier draws before entry. {2}{W} targets exactly two distinct players; surviving legal targets draw individually in APNAP order. |

All four are single-faced. Colors, types, subtypes, supertypes, mana values,
power/toughness and casting costs were checked against the pinned catalog.
Source-fact digests bind the complete printed facts; they are checked again by the
hosted fixtures before promotion.

Treasure is a shared colorless Artifact—Treasure definition with a tap and
self-sacrifice cost followed by one choice among the five colors. Both cards embed
the identical definition, deduplicated by the kernel. Soldier uses the existing
combat lifelink primitive.

## Shared implementation

`PayMana` is a fixed-cost instruction with paid and unpaid branches. The payer is
the controller or the captured event player. The authenticated `pay_mana` command
accepts an exact mana packet or an explicit decline. Insufficient, excessive,
wrong-colored, stale, duplicated or unauthorized submissions fail before mutation.
Hybrid and colorless requirements reuse the shared mana matcher.

A payment suspends its parent's current instruction. The payer can activate
eligible mana abilities without ordinary priority. Immediate mana, color choices,
and mana-source sacrifice costs use the existing casting transaction. A child
mana frame resolves completely before restoring the parent; generated ordinary
triggers and state-based actions wait until parent resolution finishes. Snapshots
and accepted-command replay retain the payment, child choices and exact continuation.
The parent remains available to Flashback's exact-stack-incarnation replacement.

`DrawEventPattern` selects a positive ordinal actual draw. The kernel records
individual successful draws per player and turn even when no ordinal observer is
present. Ordinary hand additions and empty-library failures do not increment it.
Public packets contain only the payer/cost/parent identifier and public draw counts;
they do not serialize the private suspended frame or another player's hand.

Checkpoint schema 115 binds the new payment continuation and turn draw counters.
Old layouts are rejected. Existing production admission remains closed.

## Rules authority and bounds

The pinned [Wizards Comprehensive Rules](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt)
are effective August 7, 2026. Relevant rules are 118.12a (unless), 118.13b (hybrid
payment), 121.1–2c and 121.4 (individual draws, APNAP and failures), 605.3a–c and
608.2g (mana abilities during resolution), 111.10a (Treasure), and 800.4f (departed
payer does not pay). Source identity is recorded in
`data/reference/rules_primitives_sources.json`.

This slice accepts fixed unrestricted mana during a resolution payment. Restricted
mana, mana abilities during spell announcement, nested payment requests inside a
mana ability, and concessions during suspended choices retain their existing
unsupported boundaries. These are not silently approximated by banked-only
resolution payments. Unsupported node shapes fail compilation.

## Validation

[Draft run 34776935566](https://github.com/pope-punk/Edhsimulator/actions/runs/34776935566) passed **1,384 tests on both
Ubuntu and Windows** at `1d434de1fcabaf4d82d06baf17608df2fa76614f`, together with source syntax,
installation and packaged-asset checks. The same 46 new methods now load the four
source-bound reviewed programs. [Reviewed-loader run 34777218224](https://github.com/pope-punk/Edhsimulator/actions/runs/34777218224)
also passed **1,384 tests on both platforms** at `648829318cdfc1f6ebd73ff9a4354db55d00a337`.
The result-recording commit changes documentation/inventory only, with no runtime,
program or test changes after validation.

The first draft run `f94894b36674f0be871abb333c2385baf84b210b` / 34776728530 exposed two
fixture setup mistakes: a stale moved source reference and a prompt assertion for
an automatically selected sole option. The corrected fixtures preserve the intended
checks and exercise both payment branches. No runtime fix was needed.

The 46 new methods cover all printed clauses,
normal casting, paid/unpaid outcomes, correct actor capture, repeated events,
payer departure, source control changes, mana-source readiness, mana choices and
sacrifice, rejection atomicity, lexical bindings, suspended parent restore,
authenticated replay, hidden-state projection, draw ordinals, entry timing,
two-player targeting, partial target legality and strict codec/checkpoint gates.
No local Python, imports, installation, compilation, tests or games were run.
