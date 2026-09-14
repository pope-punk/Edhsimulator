# Phasing and player-choice card review

Cycle base: `9c63ed66dbd07c6fc20deab92314e367c29203c5` on `codex/remaining-card-programs`.
Four complete printed programs remain isolated drafts pending hosted validation.
No project code, Python, imports, compilation, installation or tests ran locally.

## Printed-face mapping

| Card | Complete printed behavior |
| --- | --- |
| Talon Gates of Madara | Optional creature target on entry phases out. Both tap mana abilities retain their costs and colors. The {4} hand activation publicly reveals its exact source, puts that same incarnation onto the battlefield and produces the normal entry trigger. |
| Desert Warfare | Actual Desert sacrifice and owned Desert arrivals from hand/library create exact next-own-end-step returns. Public replacement destinations remain identifiable; later incarnations and hidden replacements are not followed. Own beginning of combat checks five Deserts at occurrence and resolution, counts current Deserts, creates that many 1/1 red/green/white Sand Warriors together and grants permanent, noncopiable haste. |
| Indulgent Tormentor | Normal {3}{B}{B} 5/3 flying creature. Own upkeep targets one opponent, who may pay 3 life, choose and sacrifice one controlled creature, or allow its controller to draw. Illegal targets stop the entire ability; source departure alone does not. |
| Volatile Fault | Tap for colorless mana. Its {1}, tap and source-sacrifice costs precede responses. Destroy one nonbasic opposing land, allow that land's resolution-time controller to search their own library for a basic land and shuffle, then create a functional Treasure for the ability controller. Search is offered even if destruction fails; an illegal target prevents all effects. |

Volatile Fault joins this batch through captured-player choice support.
Necromancy remains unstarted until actual cast-time sorcery eligibility,
next-cleanup scheduling and permanent-to-Aura conversion are implemented.

## Shared semantics

Phasing preserves incarnation, counters, tap state and control history; it emits
no zone or attachment events and removes combat participants immediately.
Attached permanents phase indirectly with the outer direct root, even when they
were also selected directly. Indirect attachments wait for that root, including
orphaned groups. Untap restoration uses the root's controller at phase-out;
departed controllers use the skipped seat's next turn slot under CR 702.26n.
Natural phasing phases in and out simultaneously before ordinary untap.
Actor packets retain public exact-object phase groups and return controllers,
including after checkpoint restoration. Unregistered fixture-only phased states
remain fenced. The existing source-
duration exile and counter-conditioned duration rules retain their distinct
responses to phasing.

Qualified zone patterns filter actual causes, event-time subtypes and destination
ownership. Public successors bind the actual new incarnation under CR 400.7e.
Controller-qualified delayed end steps use the existing one-shot captured
trigger lifecycle. Desert recovery does not depend on its source remaining.

WithCreatedTokens reuses replacement-aware token creation and exact zone-result
bindings, including recursive discovery of token definitions nested in creation
effects. OngoingEffect shares the characteristic layers while surviving cleanup
and phasing. Its grants are not part of a token's copiable definition and cease
to apply to a departed incarnation.

PayLifeOrSacrifice uses one authenticated opponent choice. Life payment uses the
state resource transaction and cannot exceed available life. Sacrifice options
include only the payer's current eligible permanents and use the existing
replacement-aware movement pipeline. SearchByPlayer captures a searching player
and changes only that search's actor, choices and entry controller. Declining
does not search or shuffle; accepting permits failure to find a filtered card
but still shuffles; excluded supertypes also count as a filter. Full-library inspection is available only to that player
during the actual search, after the optional offer is accepted. No other hand
or library contents become public.

## Bound sources

Catalog printed facts are retained with the drafts. The pinned
[Comprehensive Rules](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt)
retain SHA-256 `4381ad1b39ab2c05f7d03633a20f711ed37277074d3266dcba5f38cbb527423f`.
Review covers CR 118 (payments), 400.7e (public successor identity), 502.1
(phasing before untap), 603.7 (delayed abilities), 608.2b (illegal targets) and
702.26a-n (direct/indirect phasing, attachments, durations and departures).
[Modern Horizons 3 release notes](https://magic.wizards.com/en/news/feature/modern-horizons-3-release-notes)
supply Talon Gates and Desert Warfare's printed text and clarifications.
[Lost Caverns of Ixalan release notes](https://magic.wizards.com/en/news/feature/the-lost-caverns-of-ixalan-release-notes)
confirm Volatile Fault's search and illegal-target clauses.

| Card ID | Exact source-facts SHA-256 |
| --- | --- |
| talon-gates-of-madara | `c1fd0a20ba37f7cdb5d77ea536e9d71c5e89dfaf903605e8ea9d074988148ffc` |
| desert-warfare | `5379fe3951854242e50fb24fb03bb900f339d646a91dccefa7d5e497a5cb74f5` |
| indulgent-tormentor | `6c3b28a33ce320bc871b8a611e26fa05b7c5b85481513798ed259608c2297c55` |
| volatile-fault | `7be3aaf3d64e39686c3af45c0985e6ce23011c5d3a6122875f892d502939d5fa` |

## Conformance and compatibility

The **63 new methods** in `tests/test_rules_primitives_phasing_choices.py`
cover printed facts and actual costs; direct, indirect and natural phasing;
departed-seat timing; token identity; combat; source durations; Desert event
filtering, replacement destinations and delayed returns; ongoing haste and
actual copying; payer authentication, life/sacrifice choices; search privacy,
shuffling and control; checkpoint restore and actor replay; and compiler gates.

Kernel checkpoint schema is **119** and state schema remains **13**. The
historical schema-118 test accepts its layout or newer and still rejects 117.
No started game or legacy checkpoint is migrated. Production admission remains
closed. Draft and required reviewed-loader hosted runs are pending; no new test
is counted as passed yet.

The initial draft run `34791142601` passed syntax, installation and packaged
assets. Windows ran 1,609 tests with 17 fixture errors and no assertion failures;
Ubuntu was cancelled by matrix fail-fast. Corrections preserve the upkeep-only
scenario gate, action priority and permanent-source compiler validation. Focused
non-upkeep trigger fixtures now call the internal phase collector explicitly;
Desert recovery and haste/phasing integration traverse real turns. A corrective
hosted run remains required before promotion.
