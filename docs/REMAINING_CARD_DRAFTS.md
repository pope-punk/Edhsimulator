# Remaining-card authoring branch

Branch: `codex/remaining-card-programs`, based on studious trout commit
`e9c94a41b722a15621a1ab6352e96e97ccc5f8a7`.

Project execution and validation are restricted to GitHub-hosted runners; no
local Python, installation, tests or games are authorized. The library contains
**306 source-bound reviewed programs / 372 deck copies**. There are **28 cards / 28 deck
copies outside the reviewed bundle**: seven drafts and 21 unstarted cards. Reviewed coverage is not production certification.

## Four-pass completion plan

The user requests completing the remaining **28 unique cards in four or fewer
substantive implementation passes**, replacing the former 4–8-card cycle target.
The baseline plan is **four groups of seven**, with a usual working target of
**7–10 complete cards per pass** so that earlier progress can absorb later complexity.
Treat this as an ambitious planning target; do not omit printed clauses or relax
review to meet a count.

| Pass | Shared work | Planned cards |
| --- | --- | --- |
| 1 | Payments, combat and continuous effects | Chthonian Nightmare; Maze's End; Rhythm of the Wild; Parasitic Impetus; Propaganda; Defiler of Vigor; Darksteel Mutation |
| 2 | Planeswalkers, counters and opening choices | Aminatou, the Fateshifter; Domri, Anarch of Bolas; Minsc & Boo, Timeless Heroes; Nissa, Steward of Elements; Sorin, Vengeful Bloodlord; Innkeeper's Talent; Leyline of Hope |
| 3 | Multiface cards, transformation and Saga foundations | Glasswing Grace // Age-Graced Chapel; Kazuul's Fury // Kazuul's Cliffs; Sorin of House Markov; Pontiff of Blight; Invasion of Theros; The Restoration of Eiganjo; Elspeth Conquers Death |
| 4 | Rooms, miracle and remaining Sagas | Aminatou, Veil Piercer; Entity Tracker; Funeral Room // Awakening Hall; Ghostly Dancers; Victor, Valgavoth's Seneschal; The Cruelty of Gix; Urza's Saga |

**Pass 1:** Reuse payment, entry, Aura and characteristic primitives; complete energy and authored cost ordering, Gate-name wins, riot, goad and attack payments, optional life-based green reduction, and ability/type replacement.

**Pass 2:** Share loyalty activation support, X loyalty and entry, control changes, counter/layer updates, Class levels and pregame choices; retain each commander's printed clauses.

**Pass 3:** Implement face selection, transform/return identity, battle protection and defeat, extort and granted triggers, plus complete Saga chapters and lifecycle. Reuse the preceding loyalty and payment primitives.

**Pass 4:** Finish Room doors, unlocking and fully-unlocked events; miracle draw/reveal/cast windows; per-turn ability-resolution counts; read ahead and the remaining Saga programs. Close with a complete inventory and cross-family audit.

The groups cover every remaining card exactly once. They are a dependency-based
authoring plan, not a claim that the required primitives already exist. Refresh
current source and programs before each pass; move cards between groups when
that improves reuse, and combine passes when practical. Start with all seven
Pass 1 cards in scope, rather than stopping at the former four-card shortlist.

A pass includes authoring, source-bound review, successful hosted draft checks,
the required reviewed-loader run and result recording. Continuation turns and
validation repairs remain part of the same pass. Save durable partial progress
when needed, then resume it; do not count an unfinished draft as a completed pass
or restart the four-pass budget at every heartbeat. Track actual completions,
unresolved work and remaining passes in the JSON report's `completion_plan`.
If a concrete dependency or defect makes the target infeasible, record why and
revise the grouping explicitly.

Reuse existing primitives. During hosted CI waits, review or prepare the next
family where useful. Group related validation and avoid redundant full-suite
runs. All existing GitHub-only execution constraints remain in force, and the
heartbeat remains active every 40 minutes.

## Current pass: payments, combat and continuous effects

The seven Pass 1 programs are authored in the separate draft bundle with 91 new
conformance methods. Hosted draft validation and complete source review are
pending. Coverage remains 306 reviewed unique cards / 372 copies; the 28
remaining cards comprise seven drafts and 21 unstarted cards. Pass 1 remains
open through required reviewed-loader validation. See
[the pass review](PAYMENTS_COMBAT_CARD_REVIEW.md). No local execution occurred.

## Previous cycle: resolution casting and top-library permissions

Rishkar's Expertise, Hidden Nursery, Apex Devastator and Oracle of Mul Daya
have complete source-bound reviewed programs. Shared support covers suspended
parent resolution, fixed free-cast permissions, additional costs, authored mana
plans, discover/cascade exile batches and current top-card land play. Apex's
missing Hydra subtype is corrected in both canonical reference and catalog.
Kernel/state schemas are **128/17**.

The **85 new draft methods** passed hosted validation: **2,245 tests on each of
Ubuntu and Windows**, plus syntax, installation and assets, at
`c168dae7c628cde1f37e0381a21a609fe720f088` ([run 34876806875](https://github.com/pope-punk/Edhsimulator/actions/runs/34876806875)).
The required reviewed-loader run covers **95 new methods**, including the
promotion review's mana classification, top-placement disclosure and public-exile
history corrections. All **2,255 tests passed on each platform**, plus syntax,
installation and packaged assets, at
`bfaef8c37152768444ffca8afe5357aaab94a64d` ([run 34878332029](https://github.com/pope-punk/Edhsimulator/actions/runs/34878332029)).
The final result-recording commit changes only documentation and inventory.
See [the review](RESOLUTION_CAST_CARD_REVIEW.md).
No local project execution occurred.

The next implementation pass is the seven-card Pass 1 group above. It expands
the earlier four-card shortlist with Propaganda, Defiler of Vigor and Darksteel
Mutation. Later groups explicitly retain Room unlocking, both card faces, Siege
defeat and Saga lifecycle requirements.

## Previous cycle: spell copies and special mana

Replication Technique, Changing Loyalty, Sunken Palace and Delighted Halfling
have complete source-bound reviewed programs. Shared support covers noncard
stack objects, demonstrate, replicate, copied permanent entry, simultaneous
target reassignment and explicitly spent mana. Copies preserve paid cost
decisions without inheriting escaped status, Necromancy casting history or
counter immunity. Kernel/state schemas are **127/17**.

The **64 new methods** passed hosted draft validation: **2,159 tests on each of
Ubuntu and Windows**, plus syntax, installation and assets, at
`5f13db33ccca589d11e1d6c4feae1785ade8d13a` ([run 34868673387](https://github.com/pope-punk/Edhsimulator/actions/runs/34868673387)).
Required reviewed-loader validation passed **2,160 tests on each platform**,
including **all 65 new methods**, plus syntax, installation and assets, at
`8d29e0e7cf916860c0004605b052b8d3ebd03903` ([run 34869674458](https://github.com/pope-punk/Edhsimulator/actions/runs/34869674458)).
That run includes the copied hand-ability visibility correction. The final
result-recording commit changes only documentation and inventory. See [the current review](SPELL_COPY_MANA_CARD_REVIEW.md).
No local project execution occurred.

The next candidates are Rishkar's Expertise, Hidden Nursery, Apex Devastator and
Chthonian Nightmare. The first three share casting during resolution, discover
and cascade; Nightmare requires energy and ordered additional costs. Entity
Tracker remains incomplete until Room-unlock events are supported.

## Previous cycle: modified creatures, exploration and library movement

Kodama of the West Tree, Rampant Frogantua, Hakbal of the Surging Soul and Chaos
Warp have complete source-bound reviewed programs. Shared support covers current
modified creatures, combat-damage snapshots, live lost-player growth, exact
optional-mill arrivals, sequential exploration, owner capture, shuffling and
top-card permanent entry. Kernel/state schemas are **126/16**.

The **58 new methods** passed hosted draft validation: **2,095 tests on each of
Ubuntu and Windows**, plus syntax, installation and assets, at
`c723b4518af3555124ea1720778e5292d53fb17c` ([run 34860964382](https://github.com/pope-punk/Edhsimulator/actions/runs/34860964382)).
Required reviewed-loader validation passed **2,095 tests on each platform**, plus
syntax, installation and assets, at
`28e3a603461793aea7acff0b9776a79488ba7352` ([run 34861920441](https://github.com/pope-punk/Edhsimulator/actions/runs/34861920441)).
The result-recording commit changes only documentation and inventory; runtime,
programs, source references and tests are unchanged after validation.
See [the current review](LIBRARY_CREATURE_CARD_REVIEW.md).
No local project execution occurred.

The next candidates are Replication Technique, Sunken Palace, Changing Loyalty
and Rishkar's Expertise. See the review and JSON inventory for concrete stack-copy,
replicate, spent-mana and resolution-casting requirements.

## Previous cycle: counter transitions, eternalize and Finale

Fangs of Kalonia, Hydra Broodmaster, Fanatic of Rhonas and Finale of Revelation
have complete source-bound reviewed programs. Shared support covers actual counter recipients,
nontargeted overload, the monstrous designation, variable token base values,
conditional activations, costless copies, graveyard shuffling and indefinite
player permissions. Hydra's source mana cost is corrected to {4}{G}{G} from the
official release notes. Kernel/state schemas are **125/16**.

The **64 new methods** passed expanded hosted draft validation: **2,037 tests on
each of Ubuntu and Windows**, plus syntax, installation and assets, at
`7e7106bf0fa5c8c83e21ce1affac48d5f530c196` ([run 34851080921](https://github.com/pope-punk/Edhsimulator/actions/runs/34851080921)).
Required reviewed-loader validation also passed **2,037 tests on each platform**,
plus syntax, installation and assets, at
`217fc9397506c8b5157c19a856b34c399f2ca447` ([run 34852043326](https://github.com/pope-punk/Edhsimulator/actions/runs/34852043326)).
The following result-recording commit changes only documentation and inventory;
runtime, programs, source references and tests are unchanged after validation. No local project execution
is authorized. See [the current review](TRANSITION_CARD_REVIEW.md).

## Previous cycle: copies of existing permanents and power damage

Mirage Mirror, Thespian's Stage, March from Velis Vel and Ram Through have complete
printed programs and exact source bindings in the reviewed library. Shared work
adds durable, timestamped layer-one copies, copiable retained activations,
nonbasic subtype selection, fixed-arity spell target groups and simultaneous
excess damage. The prior 286 reviewed programs are unchanged.

Kernel schema is **124**, state schema **15**. The **56 new methods** now use the
reviewed loader. [Draft validation 34845683355](https://github.com/pope-punk/Edhsimulator/actions/runs/34845683355)
passed **1,973 tests per platform**, plus syntax, installation and assets, at
`2936bde63ebdcef71a9d1e928e55b640698d89eb`. [Required reviewed-loader validation 34846671618](https://github.com/pope-punk/Edhsimulator/actions/runs/34846671618) passed
**1,973 tests on each of Ubuntu and Windows**, plus syntax, installation and
packaged assets, at `e8bb4f97f82573565eafbae3ec4910068e377057`. The following result-recording
commit changes only documentation and inventory; runtime, programs, references
and tests are unchanged after validation.
See [the current review](PERMANENT_COPY_CARD_REVIEW.md).

## Previous cycle: token copies and fight

Scute Swarm, Helm of the Host, Lazotep Quarry and Aggressive Biomancy now have
complete printed programs and exact source bindings in the reviewed library. Together with the four
mana/convoke cards below, this continues the requested eight-card batch.

The shared copy registry freezes and deduplicates copiable values, preserves
entry behavior and restores from checked lineage. Copy exceptions remain
copiable, while Helm's later haste remains separate. Biomancy reuses a shared
simultaneous fight instruction. The prior 282 reviewed programs are unchanged.

Kernel schema is **123**, state schema **14**. **64 new methods** bring the
hosted suite to **1,917 tests per platform**. [Draft validation 34838551887](https://github.com/pope-punk/Edhsimulator/actions/runs/34838551887)
passed on both platforms at `081eed81e1e1bf9e67d170269a1b52b051115711`, including syntax, installation and assets.
[Required reviewed-loader validation 34839294402](https://github.com/pope-punk/Edhsimulator/actions/runs/34839294402) passed
**1917 tests on each of Ubuntu and Windows**, plus syntax, installation
and packaged assets, at `f4d29b49ca71f04e11b21bf46384a355d7705062`. The following result-recording
commit changes only documentation and inventory; runtime, programs, references
and tests are unchanged after validation. See [the review](TOKEN_COPY_FIGHT_CARD_REVIEW.md).

The current cycle reuses this foundation for Mirage Mirror, Thespian's Stage
and March from Velis Vel. Replication Technique remains queued for real stack
copies and authored demonstrate decisions.

## Previous group: mana capabilities and convoke

Exotic Orchard, Fellwar Stone, Horizon of Progress and Devouring Light have
complete printed review and exact source bindings in the reviewed library. This cycle implements
two shared interpreters: current-land mana capabilities, including recursive
dependencies, and authenticated convoke payment against the final spell cost.
Of the prior 278 reviewed programs, 277 are unchanged. Baldur's Gate has a
source-verified correction to untapped entry and colorless base mana; it does
not count toward the new cards.

Kernel schema is **122**, state schema **14**. The **74 new methods** now use
the reviewed loader. [Draft validation 34835807492](https://github.com/pope-punk/Edhsimulator/actions/runs/34835807492)
passed **1853 tests on each of Ubuntu and Windows**, plus syntax, installation
and packaged assets, at `b5a59145faa7bee3dba851c53af173ddcbd35004`.
[Required reviewed-loader validation 34836442046](https://github.com/pope-punk/Edhsimulator/actions/runs/34836442046) passed **1853 tests on each platform**
at `3c6b2b548c677bc0a0f4326b878f7f390885e63d`, plus syntax, installation and assets.
See [the review](MANA_CONVOKE_CARD_REVIEW.md).

Continue **Scute Swarm, Helm of the Host, Lazotep Quarry and Aggressive Biomancy**
with durable copiable token snapshots, copied entry behavior and copy exceptions.
Keep Helm's later haste grant separate from its nonlegendary copy values. Reuse
the existing entry transaction, explicit created-token bindings, X costs, targets
and creature/Desert sacrifices. Biomancy also needs simultaneous fight damage
with both creatures still present (CR 701.14). The immutable base definition and
trigger registries require deterministic, checkpointed derived copy programs.
All four are complete in the current cycle.

No local execution, game migration or production admission.

## Previous cycle: eight cards sharing guards and history

The user explicitly requested **eight more cards**. Karmic Guide, Alseid of Life's
Bounty, Fanatical Devotion, Pongify, Dimir House Guard, Midnight Snack, Restart
Sequence and Jyoti, Moag Ancient have complete printed review and exact source
bindings. The prior 270 reviewed programs are unchanged.

Shared work covers color protection, fear, regeneration, echo upkeep history,
attack and qualifying combat-damage observations, actual turn life gains,
resolving player statistics and bound library selectors. Jyoti reuses a frozen
source statistic; CR 107.1b clamps a negative calculated bonus to zero.
The implementation identity includes guard and phasing interpreters.

Kernel schema is **121**, state schema **14**. The **107 new methods** now
use the reviewed loader. [Corrected draft validation 34801795555](https://github.com/pope-punk/Edhsimulator/actions/runs/34801795555)
passed **1,779 tests on each of Ubuntu and Windows**, plus syntax, installation
and packaged assets, at `f7aa71651971da75381805bbbb30a04b59226bd5`.
[Required reviewed-loader validation 34802234395](https://github.com/pope-punk/Edhsimulator/actions/runs/34802234395)
passed **1,779 tests on each of Ubuntu and Windows**, plus syntax, installation
and packaged assets, at `6ee170ae43d99944734655967f107c87dd8f9cc9`.
The following result-recording commit changes only documentation and inventory;
runtime, programs, source references and tests are unchanged after validation.
Existing games remain bound to their implementation; no local execution or
production admission.
See [the cycle review](GUARD_HISTORY_CARD_REVIEW.md).

## Next work order: stack copies and damage/library results

The current cycle's required reviewed-loader validation is complete. Next aim
for a coherent **4-card cycle**, selecting **Replication Technique, Sunken Palace,
Kodama of the West Tree and Rampant Frogantua**. All four next candidates remain
unstarted. Reassess shared dependencies before writing their programs.

- Replication Technique needs real stack spell copies, the demonstrate cast
  trigger, optional caster copy, caster-chosen opponent and independent target
  reselection. Copies preserve announcement choices and are not cast.
- Sunken Palace needs distinct mana-unit lineage and a delayed trigger when that
  unit pays for a cast or activation; preserve a copyable record after the
  original is countered. Reuse tapped entry and seven-card graveyard exile costs.
- Kodama needs a reusable modified predicate (counters, Equipment, or an Aura
  controlled by the creature's controller), both static trample and a filtered
  combat-damage trigger from each qualifying creature, then ordinary basic search.
- Rampant Frogantua needs an exact departed-player count, current combat damage
  amount, optional milling, and a captured actual mill result from which any
  number of lands can enter tapped. The official MH3 notes forbid choosing its
  optional mill when the library has fewer cards than the damage amount; a
  partial ordinary mill is insufficient. Reuse the existing mill, departure and
  entry replacement infrastructure, preserving this choice prerequisite.

Reuse durable copy definitions, existing-permanent snapshots, named spell target
clauses, counter transitions and library continuations. Keep direct token copies,
stack copies and paid-mana lineage as distinct operations. Fangs, Hydra, Fanatic
and Finale are tracked in the current cycle above, not in this next queue.

## Previous cycle: casting, entry and paid-cost facts

Necromancy, Nullpriest of Oblivion, Sigarda's Splendor and Wonderscape Sage
have complete printed-face review and exact source bindings. Shared support
records real kicker declarations and additional costs, cast-time sorcery
eligibility, exact next-cleanup sacrifice, entry-life notes, spell colors and
paid lands' derived subtypes. Necromancy composes existing ongoing effects and
attachment rules to become an Aura. Karmic Guide's subsequent implementation is recorded above;
Sage shares the existing payment and subtype machinery.

Kernel schema is **120**, state schema **13**. The **64 new methods** now
use the reviewed loader. [Draft validation 34797317071](https://github.com/pope-punk/Edhsimulator/actions/runs/34797317071)
passed **1,672 tests on each of Ubuntu and Windows**, plus syntax, installation
and packaged assets, at `825827f67c5d3f4fc8397b6cede516d1d1b0862c`.
[Reviewed-loader validation 34798075383](https://github.com/pope-punk/Edhsimulator/actions/runs/34798075383)
passed **1,672 tests on each of Ubuntu and Windows**, plus syntax, installation
and packaged assets, at `1927f33f436a76e920d261b02c87ba9cc6e8a846`.
The following result-recording commit changes only documentation and inventory;
runtime, programs and tests are unchanged after validation.
See [the cycle review](RECORDED_FACT_CARD_REVIEW.md).

The former protection, echo and regeneration work order is complete in the
current cycle. Its original preparation remains in the inventory's cycle history.

## Previous cycle: phasing and player-authored choices

Talon Gates of Madara, Desert Warfare, Indulgent Tormentor and Volatile Fault
have complete printed-face review and exact source bindings. Shared work supplies
direct/indirect phasing with departed-controller timing, qualified Desert zone
observations, next-own-end-step returns, permanent noncopiable token grants,
opponent-authored life/sacrifice payments and optional own-library searches by
captured players. Actor packets preserve public phase groups and their return
controllers. Volatile Fault shares the search work.

Kernel schema is **119**, state schema **13**. The **64 new methods**
now use the reviewed loader. [Draft validation 34791775813](https://github.com/pope-punk/Edhsimulator/actions/runs/34791775813)
passed **1,609 tests on each of Ubuntu and Windows**, plus syntax, installation
and packaged assets, at `df9c4f6e99310bc7fc5f42de12a1e2fc44e582e6`.
[Reviewed-loader validation 34792219355](https://github.com/pope-punk/Edhsimulator/actions/runs/34792219355)
passed **1,609 tests on each of Ubuntu and Windows**, plus syntax, installation
and packaged assets, at `91496fa01239b6261bd27e0582278f695029dcbc`.
The following result-recording commit changes only documentation and inventory;
runtime, programs and tests are unchanged after this validation.
See [the cycle review](PHASING_CHOICE_CARD_REVIEW.md).

Continue **Necromancy, Nullpriest of Oblivion, Karmic Guide and Sigarda's
Splendor**, refreshing source and selecting a practical complete subset. The
JSON inventory retains the concrete requirements: actual cast-time sorcery
eligibility, next-cleanup delays and Aura conversion; true additional kicker
costs and entry flags; complete black protection and echo control history; and
per-incarnation entry life notes, upkeep comparisons and actual white-spell
observations. Reuse current ongoing effects, delays, payments and attachment
lifecycles. Keep all project execution on GitHub-hosted runners, with no game
migration or production admission.

## Previous cycle: upkeep payments and delayed steps

Dance of the Dead, Mystic Remora, Touch the Spirit Realm and Arcane Denial have
complete printed-face review and exact source bindings. Shared additions provide
captured repeated mana payment, attached-controller upkeep, ordinary untap
suppression, one-shot delayed upkeep/end-step events, optional draw counts and
hand-activation reveals. Arcane Denial shares the delay work; Talon Gates remains
queued for complete phasing, indirect attachments and departed-player timing.

Kernel checkpoint schema is **118**; state schema remains **13**.
The **47 new conformance methods** now use the reviewed loader.
[Draft validation 34787026975](https://github.com/pope-punk/Edhsimulator/actions/runs/34787026975)
passed **1,546 tests on each of Ubuntu and Windows**, plus syntax, installation
and packaged assets, at `d032e3c60caf22b585e641c050bc78372c15c611`.
[Reviewed-loader validation 34787728272](https://github.com/pope-punk/Edhsimulator/actions/runs/34787728272)
passed **1,546 tests on each of Ubuntu and Windows**, plus syntax, installation
and packaged assets, at `0a9259b8142247880f7493d7ee02d8e415d996b2`.
The following result-recording commit changes only documentation and inventory;
runtime, programs and tests are unchanged after this validation.
See [the cycle review](UPKEEP_DELAY_CARD_REVIEW.md).

Continue **Talon Gates of Madara, Desert Warfare, Necromancy and Indulgent
Tormentor**, refreshing the source and selecting a practical complete subset.
The JSON inventory retains the exact remaining requirements: full phasing
including CR 702.26n; sacrifice/discard/mill Desert events and next-own-end-step
timing; cast-timing-dependent cleanup sacrifice and complete Aura conversion;
and an opponent-authored choice between creature sacrifice, life payment and
allowing a draw. Reuse the new delay and payment lifecycle where applicable.
Existing games are not migrated and production admission remains closed.

## Previous cycle: counter durations, division, state triggers and Fading

Xolatoyac, The Earth Crystal, Dark Depths and Parallax Wave have complete
printed-face review and exact source bindings. The shared runtime provides
exact-recipient counter-conditioned durations, nonduplicating state triggers,
fixed target counter division during announcement and best-effort removal.
Existing continuous layers, replacement planning, counter costs and linked exile
provide the remaining behavior.

Kernel checkpoint schema is **117**; state schema remains **13**.
The **64 new conformance methods** now use the reviewed loader.
[Draft validation 34782390422](https://github.com/pope-punk/Edhsimulator/actions/runs/34782390422)
passed **1,499 tests on each of Ubuntu and Windows**, plus syntax, installation
and packaged assets, at `bc189ee62527bf3655e16b7b54b7b361cc9ab145`.
[Reviewed-loader validation 34782734602](https://github.com/pope-punk/Edhsimulator/actions/runs/34782734602)
passed **1,499 tests on each of Ubuntu and Windows**, plus syntax, installation
and packaged assets, at `26e46e4d37b7fcb0724d3265099c24a31a46aa0a`.
The following result-recording commit changes only documentation and inventory;
runtime, programs and tests are unchanged after this validation.
See [the cycle review](COUNTER_LIFECYCLE_CARD_REVIEW.md).

That cycle's next queue was **Dance of the Dead, Mystic Remora, Touch the
Spirit Realm and Talon Gates of Madara**. Its retained requirements were
requirements and source findings: attached-controller upkeep and untap
suppression; computed cumulative-upkeep payments; one-shot next-end-step returns;
and full phasing plus announcement-bound hand reveal. Reuse the current
attachment, payment, movement and duration primitives. Existing games are not
migrated and production admission remains closed.

## Previous cycle: counter transfers and turn life-loss history

Forgotten Ancient, The Ozolith, Aven Courier and Essence Channeler have complete
printed-face review and exact source bindings. Shared primitives provide
atomic replacement-aware counter movement, authenticated authored allocation,
last-known departure snapshots and resolution-time counter-kind choice.
Gross life-loss history includes damage and life payments even when gain offsets
the loss. Essence Channeler's catalog toughness is corrected from 2 to 1 using
Wizards' release notes.

Kernel checkpoint schema is **116** and state schema is **13**. Existing games
and checkpoints are not migrated; production admission remains closed.
The **64 new conformance methods** now use the reviewed loader.
[Draft validation 34779216050](https://github.com/pope-punk/Edhsimulator/actions/runs/34779216050)
passed **1,437 tests on each of Ubuntu and Windows**, plus source syntax,
installation and packaged assets, at `3f2b93e1988df3dc45ca7f0e08d61c7c36c1c910`.
[Reviewed-loader validation 34779503219](https://github.com/pope-punk/Edhsimulator/actions/runs/34779503219)
passed **1,437 tests on each of Ubuntu and Windows**, plus source syntax,
installation and packaged assets, at `5a6f83af3add06da91a564212ccb2ef6b062c1a2`.
The following result-recording commit changes only documentation and inventory;
runtime, programs and tests are unchanged after this validation.
See [the cycle review](COUNTER_TRANSFER_CARD_REVIEW.md).

That cycle's next queue was **Xolatoyac, the Smiling Flood; The Earth Crystal;
Dark Depths; and Parallax Wave**, now completed above. Its retained requirements were:
counter-conditioned type grants independent of their source; target division
during activation announcement; nonduplicating state triggers and successful
sacrifice; and the Fading removal/sacrifice lifecycle. Reuse the current counter,
linked-exile and layer primitives, but retain each card's printed timing and
choice semantics.

## Previous cycle: resolution payments and draw ordinals

Dawn of Hope, Rhystic Study, Smothering Tithe and Gleaming Splendor have complete
printed-face review and exact source bindings. PayMana offers the captured payer
an authenticated resolution window for mana abilities and exact optional payment.
Parent resolution survives immediate mana choices, source-sacrifice costs,
checkpoints and replay. DrawEventPattern counts each actual draw across the turn,
including draws before the enchantment enters. Checkpoint schema is **115**.

The **46 new conformance methods** now use the reviewed loader. [Draft validation 34776935566](https://github.com/pope-punk/Edhsimulator/actions/runs/34776935566)
passed **1,384 tests on each of Ubuntu and Windows** at `1d434de1fcabaf4d82d06baf17608df2fa76614f`,
plus syntax, installation and packaged assets. [Reviewed-loader validation 34777218224](https://github.com/pope-punk/Edhsimulator/actions/runs/34777218224)
also passed **1,384 tests on each platform** at `648829318cdfc1f6ebd73ff9a4354db55d00a337`.
The following result-recording commit changes only documentation and inventory;
runtime, programs and tests are unchanged after that validation.
[The cycle review](RESOLUTION_PAYMENT_CARD_REVIEW.md) records the rules mapping,
source bindings, scope and the two corrected fixture setup errors.

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

That earlier cycle used checkpoint schema **114**. Existing games and checkpoints are not migrated.
Production admission remains closed. That payment family is completed by the current cycle above; all project execution remains hosted.

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

That cycle used checkpoint schema **113**. A subsequent cycle added Uro's
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
originally outstanding card IDs, including the thirty-one now promoted. It records
deck membership, printed text and each card's current authoring/review status. It is an authoring report, not an executable-coverage report.

The entry lands, evoke cards, linked-exile cards and Animate Dead completed
card-level review. Crop Rotation and Fling also completed printed-face review;
their same conformance methods now load the source-bound reviewed programs.
The graveyard/exile and payment/draw families also completed review. The counter-transfer and counter-lifecycle families each add four reviewed programs. Continue from the current
queue and validation record at the top of this file.

Uro's graveyard alternative now supports its five-card exile group. Separately
ordered cost groups and mana during announcement remain rejected. Resolution-time optional
mana payments are also implemented and reviewed. Saga,
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
