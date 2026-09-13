# Remaining-card authoring branch

Branch: `codex/remaining-card-programs`, based on studious trout commit
`e9c94a41b722a15621a1ab6352e96e97ccc5f8a7`.

This is a writing head start, with no local Python execution, test run, package
installation, game launch, or paused-game migration. The ten new card programs
remain separate drafts awaiting card-level review. The reviewed bundle contains 227 programs;
107 catalog cards remain outside that bundle, comprising these ten drafts and
97 cards not yet started on this branch. Reviewed-program coverage is not a
production certificate.

## Current cycle: evoke

Mulldrifter, Reveillark and Vesperlark now have complete printed programs in the
draft bundle, using shared `EntryAlternativeCost` and `EntryFlagCondition`
nodes with ordinary entry, sacrifice and return triggers. Eighteen new conformance
methods cover casting costs, trigger order, blink, control changes, LTB targeting,
replay and checkpoints. See [the evoke batch record](EVOKE_CARD_DRAFTS.md).

The source base for this cycle is `dbf4fd69fb345f86d2ec701e845eb323bb2dcbac`.
GitHub-hosted CI is pending. Finish that validation and fix any introduced failure
before the next batch. The earlier seven land drafts passed hosted conformance;
their inventory status now distinguishes that result from the pending rules review.

Checkpoint schema is now 110. No local execution or live-game migration is
authorized. The next cycle should finish the rules review and source bindings
for the ten drafts, then implement linked exile/return for Oblivion Ring and
Leonin Relic-Warder.

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
readiness. These seven entry-land programs remain separate drafts; the three evoke programs
also require the reviewed-bundle process before promotion.

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
outstanding card IDs, their deck membership, printed text, and this branch's
authoring status. It is an authoring report, not an executable-coverage report.

After the ten-draft review, the next concrete implementation family is linked
exile and return (Oblivion Ring, Leonin Relic-Warder), followed by casting costs
with zone-changing payments (Crop Rotation, Fling). These require shared mechanics
and complete card behavior; the existing gate against casting zone costs should
remain until the full announcement transaction is implemented. Saga, Room,
planeswalker, and transforming-card programs need their corresponding shared
lifecycle support before claiming whole-card coverage.

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
