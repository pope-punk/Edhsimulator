# Animate Dead and linked-exile review — 2026-09-13

This cycle starts at `c1f5e17d0fbfee7a5dfe147e086243025797e319` on
`codex/remaining-card-programs`. It promotes Oblivion Ring and Leonin
Relic-Warder after full printed-face review, and authors and reviews Animate Dead using
existing shared attachment primitives.

## Linked-exile promotion

Both cards match every retained printed clause, casting cost and characteristic.
Oblivion Ring has a required other nonland permanent target and required exile;
Relic-Warder has one required artifact-or-enchantment target and a resolution-time
choice to exile it. Each has a separately triggered return on any battlefield
departure. Their one link identity is scoped to the source incarnation and
effective printed definition; current exile objects return under their owners'
control through ordinary Move.

The review checked early departure, source reentry, changed controller/owner,
multiple exiles, redirected movement, Aura return, target illegality, copying,
nested bindings and actor privacy against the 18 existing conformance methods.
Their prior [hosted run 34767597799](https://github.com/pope-punk/Edhsimulator/actions/runs/34767597799)
passed 1,250 tests on Ubuntu and Windows at
`2617d40e0a55f40892cd1a3f43d37558c12b5a4e`.
They now have `catalog:` identities, exact source-fact hashes and specific
`review_basis` records. Their fixtures load the promoted definitions directly.

## Animate Dead composition

Animate Dead is a black {1}{B} Enchantment — Aura with mana value two. The program
retains all printed source facts and uses the existing attachment fixture's
composition, adding complete catalog identity, color and subtype declarations.

| Printed clause | Existing composition |
| --- | --- |
| Enchant creature card in a graveyard | Graveyard Creature enchant selector and required Aura spell target; either player's graveyard |
| Entry trigger requires the Aura to remain | Self-entry event with source_must_remain=BATTLEFIELD |
| Change the enchant ability | SetAttachmentRule changes its zone/domain, then binds the exact returned creature reference |
| Return and attach | WithAttached and WithMoved move the actual attached card under the trigger controller's control; Attach uses the resulting incarnation |
| Sacrifice when the Aura leaves | DelayedTrigger captures the Aura and creature references; Sacrifice instructs the creature's current controller |
| Enchanted creature gets -1/-0 | Attached ContinuousProgram with ModifyPT(-1, 0) |

No new instruction node, card-name branch or duplicate reanimation handler is
introduced. The historical fixture remains a separate scenario definition.
Ordinary Aura entry supplies a non-targeted attachment choice when this card
returns through Starfield of Nyx or a linked-exile ability.

## Shared targeting correction

Review found that the target filter consulted printed shroud and hexproof in
every zone. Printed keywords remain useful characteristics of graveyard cards
and spells, but these targeting restrictions protect battlefield permanents.
The filter now applies that restriction only in BATTLEFIELD. Existing
quality-based TargetRestriction characteristics already had the correct zone
scope and are unchanged.

The new cases cast Animate Dead targeting shroud/hexproof creature cards in an
opposing graveyard and attach it as those creatures enter. They also counter
creature spells with those printed keywords, while preserving shroud and
opposing-hexproof restrictions on battlefield targets. No printed keyword is
removed from a graveyard or spell characteristic view.

## Authored conformance and validation

Nineteen methods in
[test_rules_primitives_animate_dead.py](../tests/test_rules_primitives_animate_dead.py)
cover printed casting/target domains, graveyard and stack keyword scope,
battlefield target protection, countered spells and entry triggers, premature
Aura removal, trigger-controller and current-controller distinctions, blink,
noncreature Gods, prohibited/replaced reanimation, exact enchant restrictions,
Starfield and Oblivion Ring return, three optional Relic-Warder cycles with
explicit decline, actor replay and checkpoint restoration.

[Hosted run 34769235605](https://github.com/pope-punk/Edhsimulator/actions/runs/34769235605)
passed **1,269 tests on each of Ubuntu and Windows**, plus source syntax,
installation and packaged-asset checks, at `c2d994dfe95d2202f1d13c32033b769f63c6e832`.
That run included Animate Dead as a source-bound draft and both linked-exile
cards through the reviewed loader. It found no unresolved failure.

Animate Dead subsequently completed printed-face review and received its exact
source-fact hash, complete review basis and `catalog:animate-dead` definition.
Its same 19 methods now load the reviewed program. The first promotion run
caught an outdated admission assertion: one fixture-only card remained, rather
than two. The assertion now checks that count and explicitly identifies Animate
Dead as reviewed while retaining its historical fixture fingerprint. No runtime
or card-program change was needed for that correction.

[Reviewed-loader validation run 34769848367](https://github.com/pope-punk/Edhsimulator/actions/runs/34769848367) passed **1,269 tests on each of Ubuntu and Windows**,
plus source syntax, installation and packaged-asset checks, at
`8a2f6ca5713fc56139dec706666231acb82f4be7`. All three cards load through the reviewed bundle.
The subsequent result-recording commit changes only documentation and this
inventory's validation metadata.

The inventory now contains **240 reviewed programs / 305 deck copies**,
no drafts and **94 unstarted cards**.

## Compatibility and scope

The shared target correction advances checkpoint schema 111 to 112; source
fingerprints also bind the changed kernel. No running or paused game is
migrated. All execution, imports, compilation, installation and tests remain on
GitHub-hosted runners; none run in the user's local Python environment.

These are experimental authored programs. Whole-pod admission stays closed.
Protection, dynamic ability copying or loss, and automatic infinite-loop
adjudication retain their separate unsupported scope. The God case exercises
an existing supported attachment failure; it does not claim protection support.
The repeated Relic-Warder fixture makes three explicit optional choices and
declines the next one; it is not a game launch or general loop shortcut.

## Review sources

Printed text and characteristics are bound to the retained catalog. The unchanged
[Comprehensive Rules baseline](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt)
covers static-ability zones (113.6), Aura casting and attachment (303.4),
zone identity (400.7), intervening conditions and delayed triggers
(603.4, 603.7b/c/e), linked abilities (607.1, 607.2a, 607.3), and
shroud/hexproof (702.18a, 702.11b).

[Modern Masters 2015 release notes](https://magic.wizards.com/en/news/feature/modern-masters-2015-edition-release-notes-2015-05-12)
confirm Oblivion Ring's separate triggers and Aura returns.
[Nathan Long's rules clarification](https://apps.magicjudges.org/forum/topic/13859/)
explains why a returned noncreature God cannot be attached, and is sacrificed
after Animate Dead falls off.

Next: implement casting zone-cost transactions for Crop Rotation and Fling using the existing activation-cost
transaction code where applicable. Fling needs the sacrificed creature's derived
power captured before payment; a selector alone cannot supply that information.
