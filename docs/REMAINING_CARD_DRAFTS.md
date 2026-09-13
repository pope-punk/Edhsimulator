# Remaining-card authoring branch

Branch: `codex/remaining-card-programs`, based on studious trout commit
`e9c94a41b722a15621a1ab6352e96e97ccc5f8a7`.

Project execution and validation are restricted to GitHub-hosted runners; no
local Python, installation, tests or games are authorized. The library contains
**246 reviewed programs / 311 deck copies**. There are **88 cards outside the
reviewed bundle**: **4 isolated drafts** and **84 unstarted**. Reviewed coverage is not production certification.

## Cycle ambition and context use

The user requests slightly more ambitious cycles. Aim for **4–8 complete cards**
where shared mechanics make that practical. This is a planning target: a difficult
primitive may justify fewer, with the concrete reason recorded. Continue into
another coherent family when useful context remains.

Prefer primitives that unlock several cards, accompanied by cards that already
fit existing vocabulary. During hosted CI waits, author or review independent
work. Use focused reads, concise retained findings and meaningful commit
boundaries; group related validation and avoid redundant full-suite runs.
Completion still requires every printed clause, source-bound review and relevant
successful hosted validation.

The next candidate queue is **Dawn of Hope, Rhystic Study and Smothering Tithe**.
They need a shared optional payment boundary during resolution, with the paying
player permitted to activate mana abilities. The inventory records concrete
implementation notes and the existing primitives to reuse. Assess **Gleaming
Splendor** as a fourth card using second-draw event tracking. Continue into another
coherent family when useful context remains.

## Current cycle: resolution payments and draw ordinals

Dawn of Hope, Rhystic Study, Smothering Tithe and Gleaming Splendor now have isolated
complete printed programs. PayMana offers the captured payer an authenticated
resolution window for mana abilities and exact optional payment. Parent resolution
survives immediate mana choices, source-sacrifice costs, checkpoints and replay.
DrawEventPattern counts each actual draw across the turn, including draws before
the enchantment enters. Checkpoint schema is 115. The 46 new conformance methods
await GitHub-hosted validation; no draft is admitted to the reviewed loader yet.

## Previous cycle: four-card graveyard casting and exile durations

Uro, Bulk Up, Grasp of Fate and Prayer of Binding have complete printed-face
review and exact source bindings. GraveyardAlternativeCost adds origin-bound
payment; Bulk Up's Flashback replacement follows the paid spell's exact stack
incarnation. ExileUntilSourceLeaves provides immediate, simultaneous returns
without adding a return trigger. Existing gain/draw, land, signed power, target,
replacement and attachment primitives supply the remaining behavior.

The same **45 conformance methods** now use the reviewed loader.
[Draft validation 34774446530](https://github.com/pope-punk/Edhsimulator/actions/runs/34774446530)
passed **1,338 tests on each of Ubuntu and Windows**, plus source syntax,
installation and packaged-asset checks, at `a806a1822952084aa4fddf1510af6db899036914`.
[Reviewed-loader validation 34774679040](https://github.com/pope-punk/Edhsimulator/actions/runs/34774679040)
also passed **1,338 tests on each of Ubuntu and Windows**, plus source syntax,
installation and packaged assets, at `15fb17030a66d7c8e0e379645be3f5bf0eecd454`.
The following result-recording commit changes only documentation and inventory
metadata; runtime, programs and tests are unchanged after this validation. [The cycle review](GRAVEYARD_AND_EXILE_CARD_REVIEW.md)
records the complete mappings, public projection and historical fixture fixes.

Checkpoint schema is **114**. Existing games and checkpoints are not migrated.
Production admission remains closed. The next family is the three payment
triggers above; all project execution remains hosted.

## Prior cycle: casting sacrifices for Crop Rotation and Fling

Both reviewed programs reuse selected ZoneCost sacrifices. The shared casting
transaction keeps the announced spell public on the stack during payment choices,
commits payment once, and then collects cast triggers. PaidCostStat captures the
sacrificed creature's derived power for Fling. Crop Rotation reuses SearchLibrary.

Twenty-four new conformance methods cover the printed cards, atomic rejection,
replacement/priority boundaries, exact source information, hidden zones, actor
replay, checkpoints, cost reductions and modal/X casting. Both cards have complete
printed-face review and exact source bindings; the same methods now use the
reviewed loader. See [the cycle record](CASTING_SACRIFICE_CARD_DRAFTS.md).

[Draft validation run 34770970728](https://github.com/pope-punk/Edhsimulator/actions/runs/34770970728) passed **1,293 tests on each of Ubuntu and Windows**,
plus syntax, installation and packaged-asset checks, at
`679a0e5971fdb21deb36d39a484a2b3c2fffdafa`. This validated all 24 new methods and the existing conformance suite.

[Reviewed-loader validation run 34771234815](https://github.com/pope-punk/Edhsimulator/actions/runs/34771234815) passed **1,293 tests on each of Ubuntu and Windows**,
plus source syntax, installation and packaged-asset checks, at
`06dddf4b88366f0bd9e2a0a75ba6afe31a81a7e0`. Both cards now run through the reviewed loader.
The following result-recording commit changes only documentation and inventory
validation metadata; no runtime, card-program or test changes follow this result.

That cycle used checkpoint schema **113**. The current cycle above adds Uro's
escape permission/payment and attack trigger alongside three further cards.
All project execution remains hosted.

## Prior cycle: Animate Dead and linked-exile review

Oblivion Ring and Leonin Relic-Warder completed printed-face review and now
have source-bound `catalog:` definitions. Their existing 18 conformance
methods use the reviewed loader. Animate Dead is authored using the existing
attachment, exact-reference movement, delayed sacrifice and attached P/T
primitives. A shared correction restricts shroud/hexproof targeting protection
to battlefield permanents while preserving printed keywords in other zones.

Animate Dead also completed its printed-face review and source binding. Its
same fixtures now use `load_reviewed()`. Nineteen new methods cover casting,
targeting, attachment failures, controller
changes, blink, Starfield/Oblivion Ring return, finite optional Relic-Warder
cycles, replay and checkpoints. See [the cycle review](ANIMATE_DEAD_CARD_REVIEW.md).
The cycle source base is `c1f5e17d0fbfee7a5dfe147e086243025797e319`.
[Hosted run 34769235605](https://github.com/pope-punk/Edhsimulator/actions/runs/34769235605)
passed **1,269 tests on each of Ubuntu and Windows**, plus source syntax,
installation and packaged-asset checks, at `c2d994dfe95d2202f1d13c32033b769f63c6e832`.
This validated the target correction, Animate Dead draft and linked-exile
promotions.

[Reviewed-loader validation run 34769848367](https://github.com/pope-punk/Edhsimulator/actions/runs/34769848367) passed **1,269 tests on each of Ubuntu and Windows**,
plus source syntax, installation and packaged-asset checks, at
`8a2f6ca5713fc56139dec706666231acb82f4be7`. All three cards load through the reviewed bundle.
The subsequent result-recording commit changes only documentation and this
inventory's validation metadata.
This evidence precedes the current casting-sacrifice cycle.

That cycle's checkpoint schema was 112. Existing checkpoints and started games are not
migrated. Authoring, card review, hosted conformance and production admission
remain distinct.

## Earlier linked-exile evidence

[Run 34767597799](https://github.com/pope-punk/Edhsimulator/actions/runs/34767597799)
passed 1,250 tests on each Ubuntu/Windows runner at
`2617d40e0a55f40892cd1a3f43d37558c12b5a4e`. The two linked-exile drafts
subsequently completed review in the current cycle; see
[their historical batch record](LINKED_EXILE_CARD_DRAFTS.md).

## Earlier ten-card promotion

The seven entry lands plus Mulldrifter, Reveillark and Vesperlark completed
card-level printed-face review and exact source-fact bindings. They now load
through `load_reviewed()`; their land and evoke fixtures exercise that path.
See [the promotion review](DRAFT_PROMOTION_REVIEW.md).

[Promotion validation run 34767022703](https://github.com/pope-punk/Edhsimulator/actions/runs/34767022703)
passed **1,232 tests on each of Ubuntu and Windows**, plus source syntax,
installation and packaged-asset checks, at `0788981d6851606eced204e7fe39b805a0a053e7`.

## Earlier batch evidence

The sections below preserve entry-land and library-audit implementation history.
Counts and draft-review status in those earlier records describe their original
commits; the current inventory and promotion review above supersede them.

## Entry-land batch

| Card | Shared entry behavior |
| --- | --- |
| Godless Shrine | Optional two-life payment; Plains/Swamp intrinsic mana |
| Hallowed Fountain | Optional two-life payment; Plains/Island intrinsic mana |
| Stomping Ground | Optional two-life payment; Mountain/Forest intrinsic mana |
| Watery Grave | Optional two-life payment; Island/Swamp intrinsic mana |
| Game Trail | Reveal a Mountain or Forest from hand; red/green mana |
| Shineshadow Snarl | Reveal a Plains or Swamp from hand; white/black mana |
| Vineglimmer Snarl | Reveal a Forest or Island from hand; green/blue mana |

The shared `EntryPayment` program node offers either a fixed life payment or
one matching card from the entering controller's hand. Declining makes the
proposal tapped; accepting leaves its existing orientation intact. This allows
other entry replacements to retain their effects and their existing ordering
choices. There is no card-name dispatch.

Life payments reserve a shared budget across a simultaneous batch and are
validated with any ordinary resource payment before the atomic state commit.
Replacement conditions continue to read the pre-entry life totals. Choice
reconstruction has no payment or reveal side effects, so a suspended request can
be restored before the batch commits. The reveal selector reads the pre-move
hand, including another land entering simultaneously, and checks subtypes rather
than the Basic supertype.

Accepted reveals produce explicit public receipts containing only the revealed
names and original references. They do not expose unselected hand cards or grant
permission to track hidden objects after movement or shuffling.

## Draft isolation and compatibility

[Draft programs](../data/rules/draft_cards.json) have a separate top-level schema,
a `drafts` collection, `unvalidated_draft` status, and `draft:` definition IDs.
The normal `load_reviewed()` path does not import them. The new card fixture
tests read the drafts from their source checkout (not the installed distribution),
opt in explicitly, compare the retained source facts with the catalog,
and exercise the draft definitions with the shared interpreter.

The experimental checkpoint schema moves from 108 to 109 because the entry
vocabulary and interpreter behavior changed. Existing implementation fingerprints
also bind the modified modules. No checkpoint conversion or game-contract
migration is supplied or implied. Production admission remains closed.

The two existing count assertions now match the source branch's already-authored
Fierce Guardianship: 227 reviewed-bundle programs and 107 remaining cards. This
is a static inventory correction, not a new validation result.

GitHub-hosted validation also reproduced two Windows-only fixture problems on
the unchanged source branch. The fingerprint test now reads UTF-8 explicitly,
and SQLite corruption/backup fixtures explicitly close their temporary database
connections. SQLite transaction context managers do not close connections. The
durable runtime and reviewed source fingerprints are unchanged.

## Validation and remaining review

Twenty-four regression test methods were written across
[test_rules_primitives_entry_payment.py](../tests/test_rules_primitives_entry_payment.py)
and [test_rules_primitives_card_drafts.py](../tests/test_rules_primitives_card_drafts.py).
They cover payment and decline, exact-life payment, insufficient life, controller
ownership, tapped entry, replacement ordering, entry copying, simultaneous
budgets, pre-payment conditions, redirects, private options, public reveals,
shared hand reveals, checkpoint restoration, compiler rejection, mana production,
source bindings, and once-only land-play accounting.

No Python or tests were run on the user's computer. GitHub-hosted
[validation run 34759002475](https://github.com/pope-punk/Edhsimulator/actions/runs/34759002475)
passed source syntax, distribution installation, installed catalog/runtime asset
verification, and **1,205 primitive conformance tests on each of Ubuntu and
Windows**, including all 24 new test methods. The validated code/test commit is
`90b2612d588bf0386f8e6c595316f9c929b19b21`; this result update changes only
documentation, the inventory's validation metadata, and a test-module docstring.

No reviewed coverage report or certificate was regenerated. Before promotion,
complete the existing rules review, examine replay and actor projections, and
review interactions with replacement ordering, departures, entry copying, and
any future life-payment prohibitions. Card programs must follow the reviewed-bundle
process; passing these conformance scenarios does not certify whole-pod production
readiness. The seven entry-land programs and three evoke programs have since completed
card-level review; see the current promotion record above.

## Library review follow-up

The [2026-09-13 library audit](CARD_LIBRARY_AUDIT.md) records six corrected
reviewed cards and consistent single-color mana composition for 26 reviewed
cards and three drafts. It changes authored programs, not runtime modules or
reviewed coverage. [GitHub-hosted validation 34761841466](https://github.com/pope-punk/Edhsimulator/actions/runs/34761841466)
passed 1,213 tests on each of Ubuntu and Windows at code/test commit
`5ca100ea394a34c6a09b652b5a0a52dd9bbdd457`. Continue with the next card family,
using the audit's selector and mana conventions. Draft promotion and production
admission remain separate review steps.

## Continuing the remaining cards

[The static inventory](../reports/remaining-card-drafts.json) retains all 107
originally outstanding card IDs, including the nineteen now promoted. It records
deck membership, printed text and each card's current authoring/review status. It is an authoring report, not an executable-coverage report.

The entry lands, evoke cards, linked-exile cards and Animate Dead completed
card-level review. Crop Rotation and Fling also completed printed-face review;
their same conformance methods now load the source-bound reviewed programs.
The current four-card cycle adds Uro, Bulk Up, Grasp of Fate and Prayer of Binding.
Continue from the current queue and validation record at the top of this file.

Uro's graveyard alternative now supports its five-card exile group. Separately
ordered cost groups and mana during announcement remain rejected. Next, add
resolution-time optional mana payments for the three queued enchantments. Saga,
Room, planeswalker and transforming programs still need their shared lifecycle
support before whole-card coverage.

## Rules references used while writing

- [Edge of Eternities release notes](https://magic.wizards.com/en/news/feature/edge-of-eternities-release-notes):
  paying a shock land's life option does not undo another instruction to enter tapped.
- [Strixhaven release notes](https://magic.wizards.com/en/news/feature/strixhaven-school-mages-and-commander-2021-edition-release-notes-2021-04-16):
  Snarl reveal choices use land subtypes and can reveal a land entering from the
  same hand simultaneously.
- [Duskmourn release notes](https://magic.wizards.com/en/news/feature/duskmourn-house-of-horror-release-notes):
  simultaneous life-based entry checks use life totals before the shock-land choices.

The catalog source facts are retained beside each draft. These references inform
the draft and its regression cases; they do not replace the project's bound
rules review or silently update its Comprehensive Rules baseline.

## Connector read note

The reviewed program JSON now exceeds GitHub's inline contents limit. If the file
read returns an empty body with a blob SHA, retrieve that Git blob through the
GitHub connector. Do not interpret an empty contents response as an empty file
or overwrite the reviewed bundle from it.
