# Counter-transfer card review

Branch: `codex/remaining-card-programs`. Source base:
`5285058b45badafddf7fa740ef6ef377deb5e75a`.
All project execution and validation remain on GitHub-hosted runners.

## Complete printed programs

| Card | Printed characteristics and complete behavior |
| --- | --- |
| Forgotten Ancient | {3}{G}, green 0/3 Elemental. Every player's spell offers its controller one optional +1/+1 counter. Its controller's upkeep offers any number of current +1/+1 counters among other creatures, including opponents' creatures. An empty authored allocation declines. There are no targets for the distribution. |
| The Ozolith | {1}, colorless legendary artifact. Each controlled creature leaving with counters captures every departing kind and amount. Its controller's beginning of combat checks that this exact artifact has counters, announces any creature target, rechecks the condition, then offers transfer of all current counters. |
| Aven Courier | {1}{U}, blue 1/1 Bird Advisor with flying. Its actual attack trigger targets a controlled permanent first. On resolution its controller chooses a counter currently on a controlled permanent; one counter of that kind is placed only if the target lacks it. The original counter remains. |
| Essence Channeler | {1}{W}, white 2/1 Bat Cleric. Current controller's gross life loss this turn supplies flying and vigilance. Each controller life-gain event adds one +1/+1 counter. Death copies every kind and amount from the departing incarnation to a targeted controlled creature. |

Casting, keywords, targeting, trigger ordering, life gain, counters and replacement
effects reuse the existing shared interpreter. No card-name dispatch is added.

## Source correction

The catalog annotations and generated catalog incorrectly recorded Essence
Channeler as 2/2. Wizards' [Bloomburrow release notes](https://magic.wizards.com/en/news/feature/bloomburrow-release-notes)
list 2/1. Both toughness fields are corrected to 1; the printed text, deck rows,
other cards and previously reviewed source bindings are unchanged. The corrected
full source-facts digest is
`a2e96ff0a43e27cea2c42b471a30d72d20e0494176e33866bfa9e761a5757862`.
The fixture compares the annotation, catalog and program. This corrects an
unreviewed card before its program is source-bound.

## Counter semantics and actor boundaries

CR 122.5 describes counter movement as removal plus placement. A pure placement
plan resolves every affected player's replacement order before one state
transaction removes original amounts and commits replacement-adjusted placements.
A doubled placement does not remove twice as many counters. A rounded-to-zero
replacement still consumes the moved amount; this is distinct from a prohibition
on placing counters, which the current closed vocabulary does not implement.
Missing, phased, identical or stale source/destination references cannot transfer.
All recipients commit before counter-added observers inspect the resulting board.

CR 122.8 distinguishes copying a departed object's counters from moving counters.
The event captures the exact last battlefield counts, including simultaneous
opposing counters before lethal state actions. It never inspects a later
incarnation. Independent Ozolith and Channeler triggers each copy that snapshot.
Current battlefield sources must still exist to receive counters.

The Ozolith's departure predicate is evaluated from the departing creature's
counter snapshot. Its combat predicate is an intervening condition on the exact
current source. Illegal targets, departure and blink cannot remove counters
from a different incarnation. See [Ikoria release notes](https://magic.wizards.com/en/news/feature/ikoria-lair-behemoths-and-commander-2020-edition-release-notes-2020-04-10).

Aven's target and resolution-time counter selection are separate decisions.
Counter choices can come from noncreature permanents; selecting a kind already
present on the target is a legal no-op. See [New Capenna release notes](https://magic.wizards.com/en/news/feature/streets-new-capenna-release-notes-2022-04-20).

CounterAllocationRequest carries an authenticated actor, exact source, current
revision, kind, maximum and legal recipient references. The allocate_counters
command requires authored positive integer amounts, distinct legal recipients
and a total within budget. Empty allocations are accepted; bools, stale revisions,
forged actors, duplicate receipts and ordinary index answers are rejected.
Options scale with recipients rather than the number of possible distributions.
Checkpoints and actor journals retain the exact request and canonical answer.
Public packets contain public counter/life history, without library identities.

## Turn history and compatibility

Life loss is recorded independently of life gain for damage, explicit loss,
ordinary costs and entry payments. A simultaneous lifelink gain cannot erase a
loss. Every new turn resets every player's history; sources entering afterward
and control changes consult the current controller's record. Pre-event trigger
checks receive the pre-transaction ledger along with existing last-known views.

State schema **13** and kernel checkpoint schema **116** bind the new ledger,
requests and semantics. Legacy layouts are rejected; existing games and
checkpoints are not migrated. The historical payment fixture accepts newer
schemas while continuing to reject its unsupported predecessor.

## Validation

**53 new conformance methods** cover all four printed cards and normal costs,
source facts, authenticated allocation, atomic failure, large budgets,
replacement ordering, checkpoint/replay, exact departure copies, target and
source changes, counter-kind timing, life history and compiler rejection.
The same methods now load the four source-bound reviewed programs. The reviewed-loader
hosted validation also passed; both results are recorded below. This document records printed-card review;
it is not a production admission certificate.

The pinned [Comprehensive Rules](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt)
remain the runtime rules baseline. No Python, imports, compilation, installation,
tests, simulations or games were run on the user's computer.

The first [draft run](https://github.com/pope-punk/Edhsimulator/actions/runs/34778960568)
ran 1,437 tests on Ubuntu with one scenario-window fixture error; Windows was
cancelled by matrix fail-fast. The fixture now opens each empty-stack caster's
scenario window explicitly. Runtime and card programs were unchanged. The corrected
run passed; see the result below.

[Draft validation 34779216050](https://github.com/pope-punk/Edhsimulator/actions/runs/34779216050)
passed **1,437 tests on each of Ubuntu and Windows**, plus source syntax,
installation and packaged assets, at `3f2b93e1988df3dc45ca7f0e08d61c7c36c1c910`.

All four complete printed programs are promoted with exact source-fact digests.
The other 250 reviewed rows are unchanged. The bundle now contains **254 unique
reviewed cards / 319 deck copies**, with **80 unstarted cards / 81 copies** and
zero drafts. The reviewed-loader validation below also passed.

| Card | Source-facts SHA-256 |
| --- | --- |
| Aven Courier | `8b3b0586224fa7b9478aa813bac65808142d8b026cadade3ad18a4326de0992b` |
| Essence Channeler | `a2e96ff0a43e27cea2c42b471a30d72d20e0494176e33866bfa9e761a5757862` |
| Forgotten Ancient | `e3c90e3543c9d71797ec0c67d4bc4ee7f6de9b91b6fa31856a35102c65a1f07a` |
| The Ozolith | `38d3ab4a07bf008fbe1252996c25ac9dff5ae755497ee1b7b4e0738fadf032ab` |

[Reviewed-loader validation 34779503219](https://github.com/pope-punk/Edhsimulator/actions/runs/34779503219)
passed **1,437 tests on each of Ubuntu and Windows**, plus source syntax,
installation and packaged assets, at `5a6f83af3add06da91a564212ccb2ef6b062c1a2`.

The following result-recording commit changes only documentation and inventory;
runtime, programs and tests are unchanged after this validation.

The next multi-card queue is Xolatoyac, the Smiling Flood; The Earth Crystal;
Dark Depths; and Parallax Wave. The work order and inventory retain their
source-independent counter durations, announcement-time distribution, state-trigger
and Fading requirements. No unsupported clause is counted as complete.
