# Linked exile and return drafts — 2026-09-13

Oblivion Ring and Leonin Relic-Warder now have complete printed programs in
the separate draft bundle on `codex/remaining-card-programs`. Both use the
same new linked-ability primitives with ordinary target, optional-effect,
departure-trigger and battlefield-entry behavior. They passed hosted conformance and await card-level review.

The reviewed library remains at 237 unique cards / 302 deck copies following
[the completed ten-card promotion](DRAFT_PROMOTION_REVIEW.md). The outstanding
97 cards comprise these two drafts and 95 unstarted cards.

## Card compositions

| Card | Cost and characteristics | Entry ability | Departure ability |
| --- | --- | --- | --- |
| Oblivion Ring | {2}{W}; Enchantment | Exile another target nonland permanent; required target and effect | Return its linked exiled cards under their owners' control |
| Leonin Relic-Warder | {W}{W}; white 2/2 Cat Cleric | Choose a target artifact or enchantment, then optionally exile it on resolution; artifact lands and the source itself are eligible when their types allow | Return its linked exiled cards under their owners' control |

Each departure ability triggers on any battlefield departure. These are separate
entry and departure triggers, not delayed triggers or an exile-until-leave
replacement. If departure resolves before entry, it finds no linked card; a
later entry resolution can still exile its target. The old source incarnation's
record never transfers to a newly entered source.

## Shared implementation

`ExileLinked(subject, link_id)` sends the selected objects through the existing
atomic move/replacement interpreter. Only resulting exile incarnations are
recorded, after the move commits. Replaced or prevented moves add no speculative
link; suspended choices cannot record the same move twice.

`WithLinkedExile(link_id, effects)` binds the still-existing, nontoken exile
objects as `linked`. Ordinary `Move('linked', BATTLEFIELD, controller='owner')`
handles the return, including simultaneous batches, Auras, entry restrictions,
entry payments and triggers. The binding is lexical, like other selection
combinators. Multiple resolutions append records rather than replacing earlier
ones; different link IDs remain independent.

The registry key includes the source's exact object reference, effective printed
program and link ID. It is independent of controller changes. An exiled card that
leaves exile and later returns there has a new reference and is no longer linked.
Records survive source departure so already-created abilities can resolve
correctly. Tokens cannot return, even before their state-based removal.

Actor packets explicitly expose only current face-up exile references and the
source's public historical identity. They do not follow a linked object into a
hand/library or reveal unselected private cards. Hidden activation sources are
rejected for this bounded public-link vocabulary.

## Authored conformance

Eighteen methods in
[test_rules_primitives_linked_exile.py](../tests/test_rules_primitives_linked_exile.py)
exercise real printed casting costs, target domains, optional exile, artifact
self-exile, early departure and source reentry, independent sources, control and
ownership, changed exile incarnations, countered abilities, illegal targets,
replacement-choice atomicity, multiple exiles and simultaneous returns, nested
bindings, ceased tokens, Aura entry and attachment failure, entry payment
checkpoints, actor replay and privacy, entry copying, and compiler rejection.

[GitHub-hosted validation run 34767597799](https://github.com/pope-punk/Edhsimulator/actions/runs/34767597799)
passed source syntax, installation, packaged-asset checks and **1,250 tests on
each of Ubuntu and Windows**, including all 18 new methods. The validated
code/test commit is `2617d40e0a55f40892cd1a3f43d37558c12b5a4e`. No unresolved failure was found.
This result update changes only documentation and inventory metadata.
No project execution, imports, installation, compilation, tests or games ran
on the user's computer.

## Compatibility and limits

The experimental checkpoint schema advances from 110 to 111 because snapshots
now retain the link registry. Implementation fingerprints include the modified
program, kernel and actor modules. Existing checkpoint/game migration is not
provided; production admission stays closed.

The nodes cover the public exile links used by these two printed programs.
This is not face-down exile, linked casting permissions, dynamic acquisition
or loss of linked abilities, spell/ability copying, or automatic infinite-loop
adjudication. Those shared capabilities retain their own authoring and review
requirements. Repeated exile instructions in the conformance fixture exercise
the registry's multi-card semantics without claiming a copy-spell implementation.

## Review references

The retained catalog binds printed text and characteristics beside both drafts.
The unchanged [Comprehensive Rules baseline](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt)
defines linked abilities (607.1, 607.2a, 607.3), new objects after zone changes
(400.7), departure triggers (603.6c), target revalidation (608.2b), and
non-targeted Aura entry (303.4f/g).

[Modern Masters 2015 release notes](https://magic.wizards.com/en/news/feature/modern-masters-2015-edition-release-notes-2015-05-12)
confirm Oblivion Ring's early-departure interaction and Aura return handling.
Leonin Relic-Warder's optionality and target types are taken from the retained
catalog; it uses the same separately linked trigger structure.

Next: review these two validated drafts for promotion. Then check the existing
Animate Dead attachment fixture against the complete printed card, reusing its
shared primitives where complete, before implementing casting zone-cost
transactions for Crop Rotation and Fling.
