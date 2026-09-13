# Remaining-card authoring branch

Branch: `codex/remaining-card-programs`, based on studious trout commit
`e9c94a41b722a15621a1ab6352e96e97ccc5f8a7`.

This is a writing head start, with no local Python execution, test run, package
installation, game launch, or paused-game migration. The seven new card programs
are **unvalidated drafts**. The 227 programs in the reviewed bundle are unchanged;
107 catalog cards remain outside that bundle, comprising these seven drafts and
100 cards not yet started on this branch. Reviewed-program coverage is not a
production certificate.

## Written in this batch

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

## Validation still required

Twenty-four regression test methods were written across
[test_rules_primitives_entry_payment.py](../tests/test_rules_primitives_entry_payment.py)
and [test_rules_primitives_card_drafts.py](../tests/test_rules_primitives_card_drafts.py).
They cover payment and decline, exact-life payment, insufficient life, controller
ownership, tapped entry, replacement ordering, entry copying, simultaneous
budgets, pre-payment conditions, redirects, private options, public reveals,
shared hand reveals, checkpoint restoration, compiler rejection, mana production,
source bindings, and once-only land-play accounting.

These tests were not run locally. GitHub's existing push workflow may run them
on GitHub-hosted Ubuntu and Windows runners; this document does not claim a
successful workflow result. No reviewed coverage report or certificate was
regenerated. Before promotion, obtain syntax and conformance results, examine
replay and actor projections, and review interactions with replacement ordering,
departures, entry copying, and any future life-payment prohibitions. Card programs
must then follow the existing reviewed-bundle process; do not relabel drafts as
reviewed merely because they decode or pass an isolated scenario.

## Continuing the remaining cards

[The static inventory](../reports/remaining-card-drafts.json) retains all 107
outstanding card IDs, their deck membership, printed text, and this branch's
authoring status. It is an authoring report, not an executable-coverage report.

Useful next families are evoke (Mulldrifter, Reveillark, Vesperlark), linked exile
and return (Oblivion Ring, Leonin Relic-Warder), and alternate casting costs with
zone-changing payments (Crop Rotation, Fling). Each requires shared mechanics
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
