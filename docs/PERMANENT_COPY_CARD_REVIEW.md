# Existing-permanent copies and power damage review

Date: 2026-09-14. Base: `4ced453d79a9df87d0e63823c9c3e7d469267939`.
Branch: `codex/remaining-card-programs`.

Four complete printed drafts: Mirage Mirror, Thespian's Stage, March from Velis
Vel and Ram Through. The reviewed library remains at 286 cards until hosted
validation and source-bound promotion. All prior reviewed programs are unchanged.

## Shared implementation

A permanent stores ordered, immutable layer-one snapshots with explicit durations
and creation timestamps. Effective definitions feed characteristic evaluation,
ability and trigger lookup, mana queries, attachments, last known information and
future copies. Copying preserves identity, counters, tap status, damage and
continuous-control history; it emits no entry event. Cleanup removes all temporary
copies simultaneously and exposes any earlier indefinite copy. Phased objects
still lose effects at expiration. Zone changes create fresh objects.

Static abilities acquired through copies use the later copy-effect timestamp.
The content-addressed registry preserves the immutable base bundle and restores
checked lineage, including retained activated abilities. Activations retain the
announced ability program, so an earlier change of form does not alter its copy
exception. New schema boundaries are kernel 124 and state 15.

March selects an authored nonbasic land type, freezes the current matching
controlled land set, applies one snapshot to that set, and separately grants
temporary haste. Existing flashback payment and exile replacement are reused.

Ram Through uses fixed-arity named spell-target groups. Each clause has its own
announcement and resolution legality; a surviving target cannot fill a missing
clause. Current source power, trample, deathtouch and marked damage determine
excess before ordinary damage prevention. Both damage destinations share one
damage transaction, including lifelink.

## Printed clauses and primary-source review

- Mirage Mirror: {3} artifact; {2} copies a target artifact, creature, enchantment
  or land until end of turn. Loses its own ability after copying, supports queued
  activations, and rechecks attachment legality. [Wizards release notes](https://magic.wizards.com/en/news/feature/hour-devastation-release-notes-2017-06-30).
- Thespian's Stage: colorless tap mana; {2} and tap to copy any target land
  indefinitely, retaining the exact activation as a copiable exception. It stays
  tapped and receives no entry counters. [Wizards release notes](https://magic.wizards.com/en/news/feature/edge-of-eternities-release-notes).
- March from Velis Vel: {2}{U}, controlled creature target, authored nonbasic
  land-type choice, controlled matching land copies and separate haste until end
  of turn; flashback {4}{U}. [Wizards release notes](https://magic.wizards.com/en/news/feature/modern-horizons-3-release-notes).
- Ram Through: {1}{G} instant; controlled source creature and opposing target
  creature; current power damage with excess to that creature's controller when
  the source has trample. Either illegal target prevents all damage.
  [Wizards release notes](https://magic.wizards.com/en/news/feature/commander-masters-release-notes).

Pinned Comprehensive Rules: CR 120.4a, 613.2, 613.7a, 707.2, 707.5 and 707.9;
existing CR 702.34 flashback and 608.2b target rules also apply.
Source: https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt
SHA-256: 4381ad1b39ab2c05f7d03633a20f711ed37277074d3266dcba5f38cbb527423f.

## Validation

54 new hosted conformance methods cover complete source bindings, copy lifetime,
identity and noncopiable state, current and copied abilities, static timestamps,
Dark Depths, entry copies, later token copies, registry restoration and tamper
rejection, actor replay, subtype decisions, flashback, target groups and excess
damage. Hosted draft validation is pending. No local Python, installation,
compilation, tests or games were run.

Replication Technique remains unstarted. Demonstrate needs genuine stack copies
and authored target reselection. No production admission or started-game migration.
