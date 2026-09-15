# Rules primitives implementation progress

Status: experimental vertical slice, 2026-09-09. **Not a production engine and not enabled in any game.** The migration plan remains in progress.

## Implemented

- `rules_baseline.py`: content-addressed snapshots of source, rules assets, policy, tests and tooling; verification detects changed content and duplicate/unsafe archive members. Live run directories and private pilot memory are excluded. This captures dirty source rather than assuming a Git commit describes the running code. It is an integrity artifact, not yet a complete historical runtime launcher or dependency lock.
- `rules_inventory.py`: raw clause/registry/replacement inventory with execution claims explicitly unverified. Card-name comparisons are diagnostic references, not proof of support. The generated report currently includes 334 definitions and 777 overlapping records; no coverage percentage is asserted.
- `rules_state.py`: one physical-card location index, incarnation references, immutable object views, object/attachment timestamps, validated simultaneous zone changes and non-zone state actions, stale-reference rejection, token identity retirement, and JSON checkpoints.
- `rules_program.py`: a closed serializable instruction vocabulary with validation of selectors, targets, nested selection bindings and trigger patterns. No callable or arbitrary Python nodes.
- `rules_choices.py`: shared serializable choices, separated from execution. Controller-group capacity is validated before creating a required prompt or accepting a spell announcement.
- `rules_replacements.py`: immutable zone-event proposals, re-evaluated replacement applicability, affected-player ordering, entry-copy precedence, and per-event application tracking. Commander hand/library replacement uses the same resolver with its explicit repeat exception. Simultaneous moves wait for all required choices before committing. Ordinary destination redirects are supported; self-replacements, entry-control changes, transforming entries and prevention remain outside this slice.
- `rules_attachments.py`: exact-incarnation Aura attachments, enchant restrictions, one-shot delayed leaves triggers, and simultaneous cleanup of illegal Auras at state-based-action boundaries. Attachment changes and delayed trigger creation compose with movement effects; there is no named-card execution branch.
- `rules_characteristics.py`: immutable copied/base characteristics and declarative type changes, base power/toughness setters, numeric modifiers, counters and switches. The evaluator resolves supported same-layer dependencies, retains recipients across layers, and uses timestamps. Targeting, attachments, replacements and state-based checks share this view. One bounded cache is invalidated by state mutation.
- `rules_casting.py`: pure revision-bound action quotes, revalidated atomic payments, unrestricted colored/colorless/generic mana and X, generic spell-cost modifiers, per-card commander tax, life/tap and atomic activation zone costs, stack activations and immediate mana abilities with supported additional effects. Accepted action receipts survive checkpoints and reject replay. Mana abilities during an announcement, restricted mana, casting zone costs, separately ordered activation cost groups and broader mana/cost semantics are still unsupported. One simultaneous activation zone-cost group now supports sacrifice, discard, exile and return. Creature tap-symbol readiness now uses continuous-control history and haste.
- Shared battlefield target restrictions represent shroud and ordinary hexproof. Casting, trigger target menus and resolution use one check; copied definitions inherit it, current control determines opponents, and nontargeted selection/attachment use their own legality checks. Protection, ward, player defenses and continuously granted/removed abilities remain unsupported. Player targets are implemented below.
- `rules_identity.py`: import-time source and Python identity bound into checkpoints.
- `rules_admission.py`: deterministic production-readiness report and a rejecting production factory. Seven mapped interaction fixtures and 226 authored card programs are explicitly distinguished from production certification; no cards are production-certified by this experimental interpreter.
- `rules_kernel.py`: an isolated scenario interpreter with effective copied abilities, entry and upkeep discovery, pre-event leaves observations, APNAP trigger placement, explicit priority passes, target revalidation, commander destination choices, and a subset of state-based actions. Choices are bound to actor, request and state revision; accepted answers cannot be resubmitted. Nested selections retain independent bindings.
- `rules_scenarios.py`: authored fixture programs for Body Double copying Uro's ETB abilities, Starfield's upkeep and animation abilities, Evolution Sage's proliferate trigger, Remand's counter/draw sequence, and Animate Dead/Felidar reanimation and blink sequences. These are **partial interaction fixtures**, not declarations of full card support. Runtime mechanics contain no card-name dispatch.

## Validation

Run from the repository:

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_rules_primitives*.py' -v
PYTHONPATH=src python -m edh_gauntlet.rules_inventory --output reports/rules-support-inventory.json
PYTHONPATH=src python -m edh_gauntlet.rules_baseline --output archive/rules-baselines
PYTHONPATH=src python -m edh_gauntlet.rules_admission --output reports/rules-primitives-readiness.json
```

On Windows or an installed checkout, omit `PYTHONPATH=src` after installing the package. CI runs the primitive conformance suite on both supported operating systems.

1146 conformance/tooling tests cover identity, copied triggers, priorities, choices, replacements, Aura/delayed-trigger lifecycles, layers, turn actions and combat. New layer cases include:

- Starfield's changing threshold, Aura exclusion, two-Starfield interaction, and phased/opponent permanents.
- Setters, numeric modifiers, counters and switching; source timestamp changes; dependency ordering and cycles; and recipient retention across layers.
- Printed versus derived types for targeting, replacement effects and pre-event death observations.
- Entry look-ahead that does not count the incoming fifth enchantment before it enters, contrasted with animation already active before entry.
- Atomic batches of zero-toughness moves, opposing-counter cancellation and creature-Aura detachment.
- Checkpoint replay at timestamp choices, changed-implementation rejection, immutable views, and explicit rejection of missing creature statistics.

Six catalog card-text fingerprints are checked. These are bounded interaction checks, not general Magic certification. The full repository suite passes **1041 tests** and catalog/runtime-asset verification passes. CI runs every `test_rules_primitives*.py` file without inference calls or live gauntlet games. The isolated installed wheel passes all 914 primitive tests and asset verification. A source-created SQLite journal reopens under that wheel, replays its bounded committed tail, suppresses a duplicate request and commits the next command with matching actor packets and archive.


## Reference and checkpoint binding

`data/reference/rules_primitives_sources.json` records the consulted [official Comprehensive Rules](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt), its content hash, the effective date reported inside the document (2026-08-07), relevant rule numbers, and catalog Oracle-text fingerprints. This is a source identity record; it does not include an offline copy of the rules document or certify every card clause.

Experimental kernel checkpoints now use schema **54** and state checkpoints use schema **11**. Earlier experimental formats are rejected explicitly. Production game contracts and host checkpoints are untouched. The rules bundle fingerprint includes replacement definitions, enchant restrictions, base characteristics, continuous programs and instruction programs. A separate implementation fingerprint binds the source modules and Python implementation/version; changed implementations are rejected on restore.

## Remaining gates

Work now covers portions of stages 0–4. The complete production migration remains **unfinished**. In particular:

1. Bind historical runtime artifacts and dependencies to games; build a clause-to-executor review ledger without double-counting catalog records. Extend source identity records into a complete offline, reproducible review bundle.
2. Expand the event and mutation model beyond the implemented destination replacements and exact attachment references: self-replacements, entry-control changes, prevention, broader last-known information, and other linked abilities still need shared semantics.
3. Implement the full casting/activation transaction, mana and nonmana costs, target permissions, hidden-information search protocol, the remaining characteristic/control/text/color/ability layers and general power/toughness expressions, full attachment legality (including protection and phasing propagation), and all required state-based actions. The already-paid scenario API remains a test helper; the new payment transaction covers only the explicitly documented cost vocabulary. Neither is a production pilot adapter.
4. Extend trigger semantics beyond the supported battlefield/zone/upkeep/cast/activation patterns. Complete copy characteristics, general intervening-if predicates, further linked/delayed ability forms, and token/copy creation. Exact-source zone conditions and battlefield-count intervening clauses are implemented, along with one-shot source-leaves delayed triggers. Other predicate forms remain unsupported. Unsupported fixture omissions must never be interpreted as supported whole-card behavior.
5. Migrate the fixed decks clause by clause with reviewed scenarios, extending the Animate Dead/Felidar/Body Double/Starfield fixtures to full card coverage. Animate Dead's power modifier and Starfield animation now use shared continuous programs. Add differential comparisons with explicit exceptions for known legacy bugs.
6. Add versioned production routing, replay compatibility, public/private projections and performance measurements. No host may choose this interpreter until its required clauses pass the support gate.

The casting/activation slice, initial target permissions and ordinary player-target combat are implemented. Next gates include loss/win exceptions, concessions, planeswalker/battle combat, broader costs, remaining characteristic/permission primitives, and clause-by-clause deck coverage. `RulesKernel.for_production` currently rejects admission explicitly; the readiness report lists the blockers. No production host has been switched to this engine.

## Entry interpretation reference

The [Magic Rules NetRep clarification](https://apps.magicjudges.org/forum/topic/38979/) distinguishes the proposed object's characteristics from the actual battlefield population used by threshold conditions. The two entry-replacement tests preserve that distinction. Current rules identities and the [Starfield release notes](https://magic.wizards.com/en/news/feature/magic-origins-release-notes-2015-07-08) are recorded in the reference manifest.

## Casting and permission checks

New cases verify pure quotes, exact colored/colorless payment, X mana value on the stack, generic reductions, per-card commander tax, stale/forged/duplicate action rejection, atomic resource failure, immediate mana abilities, tap/life costs, cast-trigger priority, and checkpoint commit parity. Permission cases cover copied restrictions, control changes before resolution, trigger target availability, graveyard inactivity and nontargeted selection. The seven real-card interaction fixtures now carry their catalog normal mana costs; this does not certify alternative casting methods or the whole card.

## Condition semantics and measured optimization

`CountCondition` now serves continuous effects, intervening trigger clauses and
`IfCondition` effect instructions. Intervening clauses check at occurrence and
resolution; ordinary conditional instructions check when executed. Battlefield
leaves observations use pre-event evidence, and entry checks see the complete
post-event batch. Trigger control remains captured if the source leaves or changes
control. Hidden-zone count conditions remain explicitly unsupported.

The characteristic evaluator now prunes dependencies using the closed vocabulary's
read/write sets. Proven-independent effects apply once each in timestamp order.
Dependent type changes retain graph evaluation, cycle handling and recipient
locking. Tests compare exhaustive evaluation against 80 deterministic generated
boards and check that independent effects avoid hypothetical applications.

Run `python -m edh_gauntlet.rules_benchmark --repeats 7 --output reports/rules-primitives-performance.json`
for the synthetic engine-only benchmark. The recorded medians are approximately
1128 ms to 24 ms for 120 objects/24 independent modifiers (47×), and 42 ms to
5.2 ms for mixed layers (8×). Both paths produce identical characteristic views.
The no-effect case remains about 0.46 ms. These compare the optimized and exhaustive
experimental evaluator; they do not measure legacy-host replay, inference, queue
stalls or live gameplay. The report includes samples, platform, implementation
identity and output fingerprints. Wall-clock timing is not a unit-test gate.

## Turn runtime, authored cards and reinitialization status

`rules_turns.py` now advances ordinary untap, upkeep, draw and main phases through
explicit priority passes; land play is a special action, and landfall goes through
the shared trigger pipeline. All players' mana pools empty at phase/step ends.
Cleanup discards are one batched choice; cleanup triggers require priority and
a repeated cleanup step. Empty attacker declarations are explicit pilot choices.
Combat declarations and ordinary losses now delegate to shared rules.
Automatic phasing, day/night and unsupported turn-based mechanics remain gated. This is still
a scenario turn runtime, not a completed game engine.

Continuous-control timestamps implement creature tap-cost readiness against the
controller's own most recent turn start. Losing/regaining control and blinking
reset readiness; haste overrides it. Animated lands use the same rule. Basic land
mana abilities derive from land subtypes. Supertype selectors and the legend rule
now share copied characteristics; legend choices and zero-toughness deaths commit
in the same state-based-action batch.

`data/rules/primitive_cards.json` contains 143 authored, source-fingerprinted
programs. The exact card list and printed-text bindings live in that bundle and
`reports/rules-primitives-deck-coverage.json`; `rules_bundle.py` rejects changed
catalog facts. These programs cover 207 of 400 card copies; **191 of 334 unique
cards still lack complete reviewed programs**, and the runtime/host gates remain
open. No supported-clause percentage or full-card production certification is
inferred from the fixture suite.

`reports/rules-primitives-reinitialization.json` binds a proposed new 20-game
cohort to the current source, card bundle, catalog and decks, with Sol Fast
short-term planning and disabled learning carried forward from the stopped run.
The preflight explicitly reports `initialized:false` and has no launch command.
It never falls back to legacy initialization or creates an empty replacement
cohort. The previous run remains stopped and retained. Reinitialization is not
complete and must wait for full deck, runtime, visibility and host-adapter gates.

Regenerate the launch preflight after every relevant implementation or bundle
change; its content fingerprint binds an intent, not a permission to bypass
readiness. Use `rules_admission --deck-coverage-output PATH` to regenerate the
per-deck card/text-unit ledger. Text units preserve evidence and are not an
automatically inferred count of rules clauses.

## Shared combat and damage

`rules_combat.py` uses the existing pure blocker/damage validators with exact
incarnation references and effective characteristics. Attackers are one explicit
choice; each defender chooses its own complete blocker batch. Discretionary
attacker damage is one batch with each source's defending player displayed.
No priority or partial damage occurs between allocation and simultaneous damage.

First/double strike, trample, flying/reach, menace, vigilance, defender,
unblockable, deathtouch, lifelink and indestructible have shared semantics. Combat
membership tracks control history and phasing, and blocked status survives the
last blocker leaving. Damage-based deaths share the existing simultaneous
state-action commit. Commander combat damage follows physical identity across
incarnations; checkpoints preserve and validate that ledger. Damage requests are
detached from mutable internal validation state and replay from checkpoints.

This does not implement prevention, regeneration, protection, attack/block
requirements, creatures blocking multiple attackers or planeswalker/battle defense.
Ordinary lethal damage now reaches shared player-loss and departure execution.
Control provenance distinguishes ending a theft effect from a foreign-owned
permanent entering under a departing controller; ownership is not substituted
for control history.

## Resolved control effects and departure preparation

`GainControl` is a closed, fixed-recipient primitive with indefinite or
until-end-of-turn duration. The state keeps the battlefield entry controller
and each later resolved control effect with its own timestamp. Expiring an
effect reveals the latest remaining effect; it does not assume ownership
determines control. Same-controller effects retain independent lifetimes without
resetting creature readiness. Blinking retires all old-incarnation effects.
Cleanup expires temporary control alongside damage removal before state checks.
Static control abilities, control exchanges and control-layer dependencies remain
unsupported; this is a resolved-effect subset of layer 2.

`rules_departure.py` computes an immutable, state-bound CR 800.4a transaction
plan and executes it with resumable replacement-aware exile. Owned objects leave,
control effects end, surviving controllers retain their relevant stack objects,
and later expiration over a departed default controller causes exile. Phased
owned objects leave without leaves triggers. The original seat order remains
an internal turn anchor; priority and APNAP placement use surviving seats.
The active player's departure does not skip the rest of that turn.

Life, empty-library draws, poison and per-physical-card commander damage now
produce losses at state-action boundaries. Simultaneous last-player losses draw;
one remaining player wins immediately. Effects finish before ordinary losses
are checked. Paying all remaining life is legal and can cause loss before the
paid ability resolves. Terminal results and suspended departure transactions
survive checkpoints. Concessions during suspended choices, player-lost triggers,
win/loss exceptions and unsupported static control effects remain outside this
subset. Production admission is still rejected.

The four additional catalog programs reuse existing entry, targeting, movement,
combat-keyword and counter primitives. Source fingerprints and whole-face program
scope remain separate from production certification. Tests cast these cards with
real payments, resolve their stack/ETB actions and check Zombify's ownership
restriction; no named-card runtime branches were added.

## Complete matching sets and destruction

Selectors now express type alternatives and excluded types. Dependency pruning
accounts for those reads, and randomized parity tests compare against exhaustive
layer evaluation. `SelectAll` binds every matching object without a pilot menu;
the nested instruction owns execution semantics. `Move` commits that complete set
simultaneously. `Destroy` uses effective indestructible and the existing replacement
pipeline; it does not reinterpret sacrifice or ordinary movement as destruction.
General regeneration and prevention remain gated.

Acidic Slime and Whelming Wave are authored entirely with these shared primitives.
Tests cover type-union target menus, indestructible, nontargeted shroud interaction,
excluded creature subtypes and simultaneous return to each owner's hand.

## Library searches and player-event subscriptions

`SearchLibrary` gives only the searching actor a matching-card menu, sorted
independently of library order. While that search is active, an actor-checked
inspection API also exposes the whole library in unordered form, including
nonmatching cards; other actors and completed searches are rejected. Stated-quality searches may fail to find;
unqualified searches require the requested quantity or as many as available.
Reveal instructions are explicit. Ordinary destination moves retain the shared
replacement/entry pipeline, and a suspended replacement preserves the accepted
search instead of repeating it. The library shuffles once after movement.

Shuffling uses a checkpointed seed and nonce with rejection-sampled Fisher–Yates
permutations. It retires old hidden-card inspection references without creating
zone-change events. Identical checkpoints and accepted choices produce identical
continuations. Shuffle seeds and physical library order are internal state and
must be excluded from future production actor projections. Search replacements,
opponents’ libraries, top-card placement, and enter-tapped search instructions
remain unsupported. This work does not admit the new engine to a live host.

Life gain, individual draws, searches and shuffles now dispatch through shared
player-event subscriptions. Copies inherit these abilities. Lifelink groups life
gain by source, not by damaged recipient or total per player; distinct sources
create distinct occurrences, and gaining zero life creates none. Tests cover
copied Pridemate, simultaneous lifelink sources, draw counts and empty-library
shuffle triggers. Search cards and Ajani’s Pridemate are authored programs using
these primitives, still subject to the overall production gates.

## Active completion goal and next implementation families

The explicit completion goal remains active: migrate the remaining unique cards,
finish production host/visibility/replay integration, and initialize the fresh
bound simulation only after the actual admission gates pass. The stopped legacy
run remains retained. This is not a claim of completion.

`reports/rules-primitives-mechanics-backlog.json` contains overlapping text signals
for prioritization, not support measurements. The largest immediately useful
families include mana choices/restrictions (35 remaining cards with matching text),
entry modifiers (26), and richer sacrifice/discard/exile/return costs (30).
Variable values/counters, token creation, effective abilities and additional
library operations also need shared implementations. Review each card's complete
face after its required primitives exist; matching a text signal never certifies
that card. Host actor projections must exclude shuffle seeds and library order,
while preserving explicitly authorized unordered search inspection.

### Immediate mana choices and bound commander identities

`ChooseMana` represents alternatives within one paid activation, including bundles
of symbols. `ChooseCommanderMana` uses immutable game-bound color identities for
the current controller. Unknown bindings reject before payment; an explicitly
colorless commander produces no mana. One alternative resolves without a prompt.
Multiple alternatives use the existing actor/revision-bound choice and checkpoint
protocol. Neither form uses the stack, and paying the last life resolves the mana
ability before checking player loss. Copied abilities inherit the same behavior.

Fifteen new tests cover atomic rejection, duplicate submission, checkpoint parity,
nonactive priority over an existing stack, last-life payment, copied/controller
identity, colorless identities, forced choices, Birds' readiness and the five
authored cards, including payment before Signet mana production. Restricted mana and mana activation during an announcement remain
unsupported; the production adapter and whole-pod gates remain closed.

### Conditional entry replaces the move itself

`EntryModifier` carries tapped/untapped entry through the shared replacement
proposal and atomic zone-move pipeline. Copy replacement precedence determines
which entry modifiers exist; affected players order competing modifiers, each
applies once, and the final zone event already contains the entry state. A
redirect away from the battlefield discards battlefield-only attributes.

Conditions use the existing shared battlefield count selector. Simultaneous
entrants do not count one another, and basic lands are distinguished from lands
with basic land types. Twelve new cases cover copied entry/checkpoint parity,
competing replacement order, invalid moves without mutation, simultaneous entry,
normal Diamond casting, slow-land special actions, Cinder Glade's intrinsic mana
and Scoured Barrens' normal entry trigger. This adds ten authored cards through
one shared mechanism. Paid/revealed entry choices, entry counters, global entry
modifiers and ability-removal layers remain unfinished.

### Actor packets, command routing and new-adapter replay

The [primitive host adapter](RULES_PRIMITIVES_HOST_ADAPTER.md) now has an explicit
actor projection, one-command casting/payment, seat/revision-bound choices and
combat batches, and a hash-linked internal replay archive. Twenty-three new
conformance cases cover hidden-information noninterference, search visibility,
private target and turn-draw redaction, command rejection, replay tampering, combat
batches, and preservation of a failure after accepting a choice.

The implementation fingerprint includes both adapter modules. Journal updates
hash only new events and use an indexed immutable tail; actor packets carry no
checkpoint history. Measurements are recorded separately in
`reports/rules-primitives-adapter-performance.json`. Durable host persistence,
actor-scoped historical evidence, full reveal/face-down semantics, legacy replay
mapping, scheduler/contract integration and whole-pod admission remain open.
This is not a production host launch or certification of the 143 authored cards.

### Resolution shortages and forced selections

A resolving `Select` now clamps its requested count to the eligible capacity,
including grouped capacity, under rule 609.3. Empty and unordered complete-set
selections resolve without an agent prompt; optional subsets, multiple candidates
within a group and explicit ordering retain their actual choices. Costs and
announcement targets keep separate strict validation. Six earlier conformance
cases now skip obsolete forced prompts while retaining their checks for nested
bindings, simultaneous events, timestamp choice, APNAP replacements and hexproof.

Eight new cases cover shortages, atomic sacrifice, optional/grouped/ordered
selection, strict costs and the two bounce lands. A lone Gruul Turf or Simic
Growth Chamber returns itself and does not restore a spent land play; a stolen
land returns to its owner. Their land-play/trigger sequence passes adapter replay.
The adapter's accepted-failure regression now injects a deliberate interpreter
failure instead of relying on the repaired selection defect. Optional resolution
costs still require their own payment vocabulary; `Select` is not that protocol.

### Mana abilities with additional immediate effects

Mana classification now walks immediately executed nodes, including conditional
branches, and excludes future delayed-trigger bodies. Targeted or library-moving
activations use the stack. Untargeted mana/life and mana/damage activations resolve
in the shared immediate frame. Nested commander-color choices validate their
binding before costs are paid. Pure fixed-mana activations retain their short
execution path and now emit the same semantic production event after activation.

`Damage('controller', amount)` uses the existing simultaneous damage pipeline,
including lifelink; it is not a life-payment shortcut. Twelve new tests cover
classification, future delayed effects, nested choices, last-life timing, common
event ordering, raw-library-selection rejection and adapter replay. Pristine
Talisman, three Talismans and four pain lands add eight reviewed programs without
card-name execution branches. The Talisman and pain-land tests exercise both
colorless and colored modes. Triggered mana abilities, prevention/replacement
coverage, loyalty and richer costs, and mana activation during announcement still
require implementation before full production admission.

### Private scry partitions

`Scry(N)` supplies exactly the authorized top cards, in their current order, plus
a bottom divider. One ordered choice specifies top order, bottom membership and
bottom order; no permutation menu or repeated per-card submission is generated.
The engine preserves the unseen middle, changes no zones and performs no shuffle.
Only the deciding actor receives the choice. Full-library search inspection is
not authorized by scry.

Nine new tests cover both ordered groups, empty/short libraries, scry zero, private
visibility, invalid partitions, scry-event timing, Opt's subsequent draw, Temple
entry triggers and adapter replay. Opt, Temple of Mystery and Temple of Silence
add three authored programs. Scry events occur after the partition, including for
nonzero scry with an empty library; scry zero emits no scry event. General top-card
permissions, multiple-player simultaneous scry and actor-scoped knowledge retention
across host context replacement still require separate implementation.

### Atomic activation zone costs

`ZoneCost` supplies a strict exact-object cost group for sacrifice, discard, exile
or return. The interpreter validates selections and all ordinary resources before
announcing. Nonmana abilities enter the stack at announcement; no player receives
priority while payment is pending. Replacement choices resolve before the group
and its mana/life/tap resources commit. A source may tap and sacrifice itself,
retaining its tapped last-known state. The saved ability survives its source and
a copied source retains the copied ability. Payment receipts and pending
announcements survive checkpoints without replaying costs.

Actor packets show the announcing ability and visible cost objects, with selected
hand cards and payment details restricted to their actor. Subtype-union selectors,
tapped placement instructions and ordinary flash casting permission support the
new programs. Eighteen tests cover invalid/duplicate costs, grouped sacrifice,
replacement checkpoints, private discard, copied sources, last-known activation types, death-trigger timing,
last-life fetch activation, subtype searches, tapped search entry, flash and
search/draw/scry outcomes. Eighteen additional programs include all ten fetch
lands, Expedition Map, Wayfarer's Bauble, Urza's Cave, Sakura-Tribe Elder, Viscera
Seer, Omen of the Sea, Mind Stone and Silent Clearing.

The compiler still rejects casting zone costs and multiple separately ordered
zone-cost groups. Hidden-zone activation, resolution-time optional costs, counter
removal/loyalty costs, tap-event subscriptions and the full announcement protocol
remain incomplete. These limitations keep production admission closed.


### Resolution quantities and additional card composition

`ChosenX`, `CountObjects` and `ScaledValue` are closed numeric expressions shared
by draw, life gain, damage, counters and `ProduceMana`. The compiler permits chosen
X only for the enclosing cast or activation with an X cost; it rejects unbound X,
negative/boolean quantities, hidden-zone counts and excessively nested expressions.
Frames retain the action's announced X independently of the source card, including
a sacrificed source and a restored pending choice. Public stack/announcement
summaries include this value. Delayed-trigger X inheritance is not yet supported.

Battlefield counts use the existing effective-characteristic selector at resolution,
after activation payment. A draw quantity is fixed before its individual draws;
mana production counts other players' objects or excludes the source according to
the printed selector. A choice of mana type has at most six short options regardless
of quantity; producing 10,000 mana does not create 10,000-symbol choice labels.
The resulting mana event still retains the complete produced symbols.

Priest of Titania, Cloudpost and Baldur's Gate now use these expressions and shared
entry replacements. Eighteen additional reviewed programs compose existing
operations: Arvad, Body Double, Eternal Witness, Eureka Moment, Evacuation,
Evolution Sage, Farseek, Felidar Guardian, Murder, Oasis Gardener, Mossfire Valley,
Overflowing Basin, Rampant Growth, Remand, Rootbound Crag, Rune-Scarred Demon,
Tatyova and Utter End. Twenty-four new tests exercise those compositions and numeric
semantics. The seven historical interaction fixtures are retained; Body Double,
Felidar, Evolution Sage and Remand now also have full printed-face authored programs.
Animate Dead, Uro and Starfield remain fixture-only. No card is production-certified.

This expression vocabulary does not yet cover characteristic-derived quantities,
broader event-result amounts, arbitrary arithmetic, dynamic cost reductions, variable target
counts or general continuous P/T expressions. The host integration and whole-pod
rules gates remain closed; the preserved stopped game was not resumed.


### Player permissions and cleanup

`PlayerPermissions` combines additional land plays, permission to play owned
lands from the graveyard, and absence of a maximum hand size. Static permissions
come from current unphased battlefield sources under their current controller;
copied definitions inherit them. `GrantPermissions` applies the same vocabulary
to the resolving effect's controller until end of turn, independently of whether
the source survives. One scan computes all seats' current public permissions.

Land plays compare the total current allowance against all lands already played
this turn (305.2). They are not assigned to individual granting sources, so blinking
Azusa cannot reset the count. Removing, phasing or changing control of a source
immediately changes its controller's allowance. Graveyard permission retains
normal ownership, main-phase priority, empty-stack and per-turn limit checks.
Putting a land onto the battlefield remains distinct from playing it.

Cleanup evaluates the current maximum hand size and batches excess discards into
one choice. Only afterward do temporary permissions expire (514.1–2); a later
cleanup can apply the newly reduced limit. Serialized grants survive checkpoints.
Actor packets expose the public permissions and the active turn's used land plays.

Azusa, Ramunap Excavator, Reliquary Tower, Thought Vessel and Urban Evolution now
compose these shared permissions with ordinary costs, mana and draw instructions.
Twelve additional tests cover source loss/blink/control/phasing/copying, graveyard
adapter replay, additive static/temporary allowances, the printed card effects,
cleanup order and restored discard choices. The original target-permission suite
remains separate. Numeric hand-size overrides, library-top play/reveal permissions,
non-battlefield static sources, ability-removal layers and other permission scopes
remain unfinished; those cards are not inferred to be supported.


### Player targets, player draw cursors and life-result bindings

`TargetSpec` can describe object targets, player targets or both. `PlayerRef` is a
separate exact serialized reference; it cannot be used as a source or a payment.
The same target menu handles announcement, trigger placement and resolution,
including opponent/controller scope and shared controller groups. Departed players
become illegal targets; losing every target suppresses all effects, while surviving
targets still resolve. Adapter commands and public stack summaries preserve the
player reference without broadening private card visibility. Player shroud,
hexproof/protection, ward and target-changing effects remain unfinished.

Draw instructions bind recipients and quantity once, then use a saved cursor to
perform each player's individual draws in APNAP order (121.2c). Replacement choices
resume the exact player/draw position; no extra priority window appears between
draws. A twenty-card draw uses one task rather than a chain of newly allocated
instructions. Ordinary draw restrictions and draw-event replacement semantics
remain separate gates from the existing zone-destination replacement fixtures.

`LoseLife` commits one atomic batch for its live recipients, without treating the
loss as damage or payment. `WithLifeLost` makes the actual batch total available as
`LifeLost` to its nested effects. `EventAmount` captures the amount of the originating
life-gain trigger. Nested numeric bindings have lexical scope and survive pending
choices/checkpoints; unrelated events cannot overwrite them. Unsupported or unbound
numeric references fail compilation. Life-change replacement/prevention exceptions
remain unfinished, and `life_lost` semantic records currently describe effect loss;
a general life-loss trigger vocabulary has not been enabled.

Nine more cards are authored: Grim Guardian, Marauding Blight-Priest, Phyrexian
Arena, Underworld Coinsmith, Lush Oasis, Loran of the Third Path, Defiant Bloodlord,
Exsanguinate and Debt to the Deathless. Twenty-one new tests cover actual card
programs, player/mixed targets, stale/invalid/departed targets, APNAP draws and
private replacement menus, cursor recovery, nested result scope and source-specific
lifelink event amounts. Production remains closed pending all remaining card and
engine/host rules gates; the preserved stopped run was untouched.


### Counter transactions, replacements and limited counter triggers

`rules_counters.py` now routes `AddCounters`, `MultiplyCounters` and proliferate
through one transaction for battlefield permanents and live players. It aggregates
counter kinds per recipient, resolves affected-player replacement choices in APNAP
order, then commits every recipient in one state mutation. A pending replacement
choice cannot leave an earlier recipient partly updated. Player targets and explicit
player sets use the same counter path as permanent targets.

`CounterReplacement` supplies pure multiplication/addition, recipient selectors and
optional counter-kind filters. Each modifier applies at most once to the recipient's
proposed event, only while matching positive additions remain. Modified additions
never multiply counters already present; doubling existing counters instead places
that many new counters through the same replacement path (701.10e). Additions of
zero stay zero. Equivalent orders of these pure affine modifiers resolve
canonically without a model choice; noncommuting orders such as Scales plus
Branching Evolution remain an affected-player decision.

Counter events now include proliferate placements and aggregate all kinds placed
on one recipient in that event. Trigger filters distinguish the placing actor,
recipient controller, type and counter kind; `EventAmount` captures either the
matching kind's amount or the total. This fixes proliferate bypassing counter event
discovery in the experimental interpreter. It does not alter the stopped legacy run.

A bounded `trigger_limit=1` tracks an exact source/ability per turn and is consumed
when the trigger occurs, even before it resolves. It currently supports self counter
events only; broader limits require arbitration when several qualifying occurrences
are simultaneous. Limits survive checkpoints and reset for a new turn or a new
object incarnation. Public battlefield cards expose remaining limited-trigger uses.

Hardened Scales, Branching Evolution, Bristly Bill, Invigorating Surge, Exemplar of
Light and Managorger Hydra are authored from these shared operations. Sixteen new
tests cover replacement order, commuting/cancelling modifiers, player and permanent
batches, APNAP choice ownership, replay, counter-event amounts, proliferate and the
printed card programs. Entry-counter integration follows below. Moving/removing counters, replacement
side effects, broader simultaneous-trigger limits and resolution-use limits remain
unfinished. Whole-pod admission stays closed.


## Entry counters share the zone transaction

`EntryCounters` describes an incoming permanent's own counters or an existing
source's selector-scoped entry addition. Entry additions and affine counter
modifiers participate in the same replacement sequence, after entry-copy
precedence. Each modifier applies once to the whole entry event; additions may
occur before or after a multiplier. The proposed characteristics are evaluated
once per replacement step and shared by destination and counter applicability.

Final counters commit with the zone move, so ETB observations and state-based
actions see them immediately. The ordinary counter-event collector then discovers
counter triggers, including abilities on the incoming permanent. Redirected entries
retain no battlefield counters and emit no counter-added event. A pending ordering
choice commits neither the zone move nor partial counters. Checkpoint continuation
recomputes the proposal from its bound answers.

Incoming broad static modifiers do not apply to their own or simultaneous peers'
entries. An explicitly self-only counter replacement can apply to its own entry.
Entry X uses the incoming stack object's announced value and is zero from other
zones; it does not borrow a resolving reanimation or blink spell's X. Entry counter
placement defaults to the incoming controller; outer replacement ordering retains
the affected object's controller/owner rule.

Kalonian Hydra and Grumgully, the Generous add two authored programs. Twelve new
tests cover atomic entry observations and triggers, once-per-event Scales,
interleaved doubling, exact checkpoint replay, copy inheritance, self versus broad
modifiers, simultaneous entry, redirection, X, validation, Hydra's attack and
Grumgully's non-Human/control/phasing filters. An installed-wheel continuation of
Body Double copying Kalonian Hydra with Grumgully, Scales and Branching Evolution
matches the source archive and both actor packets exactly (11 final counters for
the tested ordering).

Entry side-effect choices, paid replacements, arbitrary counter quantities,
separately ordered counter/zone costs and full production host integration remain unsupported.
The legacy accepted prefix remains stopped, and the fresh simulation remains
uninitialized while whole-pod admission is blocked.


## Counter removal as an activation resource

`CounterCost(kind, amount)` binds fixed positive counter removal from an activating
source. The shared resource transaction validates counters together with mana,
life and tapping before committing anything. Quotes reject insufficient counters;
commit checks current revision, exact resources and the recomputed quote. Multiple
counter kinds pay together, with duplicate kinds rejected. No additive counter
replacement or counter-added trigger runs for this removal.

The stack frame retains the source after payment. Removing its last toughness
counter can cause an SBA death while the ability remains on the stack. Costs-paid
receipts record exact source incarnation, kind and amount, and adapter archives
replay the payment exactly once. Deterministic source-counter costs require no new
selection field or inference round. Counter-paid mana abilities retain immediate
resolution.

Mikaeus, the Lunarch now composes announced-X entry, tap readiness, source-counter
costs and other-controlled-creature counter placement. Ten new tests cover payment
atomicity, insufficient resources, source death with surviving ability, multiple
kinds, absence of additive replacement/events, mana abilities, replay, compiler
boundaries, casting X, readiness and Scales-modified distribution.

This slice deliberately rejects source counter costs on spells and combinations
with zone-cost groups: independently ordered cost groups are still needed before
those combinations can be represented. Selected non-source counter payments,
variable counter-removal amounts and generic counter-removal effects/triggers
remain unfinished. Parallax Wave still needs fading and linked exile/return
semantics; it is not authored by merely supporting its activation cost.


## Atomic token creation and complete fixed token programs

`CreateTokens` embeds a bounded, validated `CardProgram` and a shared numeric
quantity. The kernel closes over embedded definitions once when loading its bundle,
rejects conflicting identities, and fingerprints the complete dependency set.
Tokens retain name, types, subtypes, colors, base statistics, keywords, triggered
abilities, activated abilities and other supported program fields. Token programs
cannot grant casting permission or describe instant/sorcery tokens. Recursive
program nesting is bounded.

Creation builds unpublished proposals with deterministic unused identities. The
ordinary entry-copy, replacement, entry-counter, attachment and timestamp pipeline
resolves them before one state commit. No token objects or identities are committed
while a replacement choice is pending. The outside-zone object in a creation
proposal is an internal origin placeholder, not an existing out-of-game object;
ordinary outside objects still cannot move back into the game. Tokens enter under
the creator's control and ownership. Normal ETB/counter discovery follows the
complete batch; normal SBA/departure rules apply afterward.

Printed colors are now part of base characteristics, copy inheritance and public
actor rows, and are included in reviewed source-fact fingerprints. This does not
implement color-changing layers. Twelve new tests cover simultaneous entry,
creator ownership, public colors, ETB ordering, replacement checkpoint atomicity,
blink/cessation, zero and counted creation, unique identity, token activations,
validation, and the four new printed card programs: Avenger of Zendikar, Rampaging
Baloths, Hour of Promise and Trading Post.

`rules_token_benchmark` records seven-sample synthetic 1/10/100-token creation and
public-packet measurements in `reports/rules-primitives-token-performance.json`.
Each sample checks a single atomic batch and exact checkpoint restoration. These
measurements exclude modifiers, triggers, inference, transport and live queues;
they are not a production throughput claim. Source-to-installed replay also covers
a two-token batch paused at counter replacement ordering, followed by ETB ordering
and resolution, with exact final archive and actor-packet agreement.

Token-copy effects, copiable exceptions, variable token power/toughness, explicit
token-creation replacement effects and broader token prohibitions remain migration
work. The four programs above are authored; whole-pod production admission remains
closed and the legacy run stays stopped.


## Captured controllers and recipient-owned token batches

`WithControllers(subject, effects)` captures the controllers of exact live
battlefield/stack objects at that instruction. A departed ability source may use
its bound last-known source snapshot. Nested instructions retain a lexical list of
player identities; they do not change the controller of the resolving spell or
ability. The capture does not substitute a card's owner after a zone change and
does not retain a whole board or redundant object snapshots.

`CreateTokens` accepts ordinary player recipients and scoped
`captured_controllers`. Each captured object contributes its quantity, including
multiple objects that had the same controller. Counts are combined by creator and
all tokens commit in one APNAP-ordered entry batch. Token ownership/control and
replacement-choice ownership follow each creator. Capturing identities adds no
choice or inference round. Player-target creation requires a player-only target
domain; object captures cannot consume player targets or escape lexical scope.

Beast Within and Swan Song are authored through controller capture, destruction or
countering, and recipient-owned creation. Ten new tests cover stolen permanents,
duplicate controllers, nesting, private checkpoint continuation after removal,
player-target creation, departed source information, malformed/unbound programs,
indestructible versus illegal targets, and Swan Song's blue flying Bird. A paused
replacement choice after destroying C's permanent controlled by B replays under an
installed wheel with exact final archive and A/B/C packet agreement; B receives
the token.

The capture is explicit at its program instruction, not a general history lookup.
Owner/power/toughness result expressions, successful-removal result groups,
regeneration restrictions, broader uncounterability and other remaining production
rules still require migration work. Whole-pod admission remains closed.


## Successful zone results and announced-X target batches

`WithZoneResult(operation, destination, effects)` wraps the shared move, destroy,
sacrifice, discard or counter interpreter. Its follow-up runs only for returned
zone events that actually reached the specified destination. The lexical result
contains exact after-move references, the count (`MovedCount`) and former
battlefield/stack controllers (`moved_controllers`). It does not infer success from
an attempted instruction or a card's final owner. Existing `WithMoved` also exposes
these result fields. Nested result scopes preserve their parent's values.

The counter refactor exposed and fixed an independent bug: countering a spell
must remove its spell frame, not another triggered-ability frame carrying the same
source reference. A regression verifies that the spell goes to its graveyard while
its cast trigger remains on the stack and resolves normally.

Target minima/maxima may now use `ChosenX` for a cast or activation with its own X
cost. Announcement validates X before target counts and payment. Wrong counts and
duplicates reject before enumerating legal targets; a legal empty target set skips
that enumeration. Resolution retains the announced X and processes remaining legal
targets normally. Trigger targets and arbitrary variable-bound expressions remain
separate work. `SetTapped` provides a validated atomic battlefield orientation
batch; effects do not apply tap-symbol summoning-readiness restrictions.

Curse of the Swine, Terastodon and Magus of the Candelabra are authored from these
operations. Fourteen new tests cover actual destinations, indestructible,
replacement redirection, empty and nested results, numeric counts, pending replay,
compiler scope, orientation atomicity, independent cast triggers, X=0, wrong target
counts, partial legality, paid X, and all three printed programs. Source-to-installed
replay covers an X=2 Curse paused at C's replacement decision: after C redirects its
creature to the graveyard, only B's exiled creature produces a Boar, with exact final
archive and all actor packets matching.

The result path inspects only the returned event batch, never the full historical
log. Token follow-ups remain one creation batch. Regeneration, untap restrictions,
arbitrary target/result expressions, broader replacement effects and production
host integration remain uncompleted gates. The legacy stopped prefix is untouched.

## Cast-event X and bounded integer division

`EventX` captures the announced spell's X at the cast event, independently of
the observing permanent or the triggered ability's own action values. It is
compiler-bound only inside spell-cast triggers; other contexts reject it.
`DividedValue` composes numeric expressions with a positive integer divisor and
explicit up/down rounding. No floating-point conversion is involved.

Hydroid Krasis composes these primitives with existing draw, life gain, entry
counters, flying and trample. Its cast benefit survives the spell being countered.
Six additional tests cover odd and zero X, independent observers, checkpoint
continuation, nested arithmetic and invalid bindings/division. Public stack
summaries expose the retained event X. Source-to-installed replay compares the
complete continuation archive and both actor packets after countering Krasis.
Kernel schema 24 binds these semantics; production contracts remain untouched.

## Derived source statistics and last known information

`SourceStat` reads current source power, toughness or mana value; after departure
it uses the complete pre-event derived characteristics keyed by exact incarnation.
The same lookup now serves departed damage sources. `BattlefieldStat` computes a
filtered maximum or sum from the existing cached characteristic view. Numeric
quantities clamp negative results to zero without changing the characteristics.
Entry-source statistic expressions remain rejected pending incoming-object rules.

The kernel records one derived view per departing battlefield incarnation before
trigger discovery, including continuous effects whose sources depart in the same
batch. This adds storage proportional to departures and avoids repeated history
scans for supported movement. Direct state mutations in scenario helpers retain
the earlier printed-characteristic fallback; normal engine movement records the
full view. Private schema 25 checkpoints preserve the index; actor packets do not
expose it. Earlier experimental schemas are rejected.

Elenda's Hierophant composes life-gain counters, flying and death-trigger Vampire
creation. Nine new tests cover simultaneous modifier loss, current source reads,
returned incarnations, departed damage information, battlefield aggregates,
Body Double inheritance, counter growth and replay, negative values and invalid
programs. An installed-package replay resumes a pending death trigger after both
the creature and its modifier leave, creates six tokens, and matches the complete
source continuation archive and both actor packets.

## Shared library arrangements and private observations

Scry, surveil and top-only rearrangement share one ordered-partition interpreter.
The player sees only the authorized prefix; the selected partition persists
through destination replacement choices. Surveil uses the ordinary simultaneous
zone transaction and emits its player event after completion. A positive surveil
of an empty library still emits that event; surveil zero does not. No repeated
inspection or partial graveyard movement occurs at replacement pauses.

Top-only rearrangement skips ordering choices for zero or one card. The actor
packet retains the latest authorized `library_observation`, including its original
revision and exact looked-at cards, so this optimization does not discard the
player's information. It is a historical observation, not a claim about current
library order. Other actors receive none of it. Inspection does not grant action
permission on hidden references. Full observations remain in the private archive;
this is not yet the complete production evidence-delivery/knowledge system.
Kernel schema 26 binds arrangement plans and observations.

Six programs compose these and existing effects: Consider, Sensei's Divining Top,
Harmonize, Growth Spiral, Inspiring Overseer and Solemn Simulacrum. Fourteen new
tests cover privacy, replacement replay, ordering, singleton optimization,
historical observation retention, all six cards and malformed programs. The
source-to-installed proof resumes a paid Consider paused at a surveil replacement,
then verifies exile, draw, the full continuation archive and both actor packets.

## Temporary continuous effects and keyword grants

`UntilEndOfTurn` captures exact battlefield recipients and numeric values on
resolution. Its timestamp shares the state clock with permanent and attachment
timestamps. It survives source departure and control changes, excludes new
entrants and new incarnations, and ends during cleanup alongside damage removal.
The existing layer evaluator accepts fixed-recipient effects as well as static
programs; `AddKeywords` applies in layer 6. Keyword grants include ordinary
combat keywords, hexproof and shroud, with target permissions checked at
announcement and resolution. General ability removal, copying and dependencies
remain incomplete. Phasing excludes recipients while out without erasing the
effect; automatic phasing/attachment propagation remains gated.

Repeated equal numeric expressions within an effect are evaluated once. The
existing dependency-pruning evaluator agrees with the exhaustive evaluator on
the added composite animation/keyword case. Schema 27 retains temporary effects
and their recipients; admission now derives its checkpoint schema directly from
the kernel, correcting stale report metadata.

Eight programs compose these rules: Give In to Violence, Moment of Craving,
Doomwake Giant, Halana and Alena, Partners, Heroic Intervention, Basilisk Gate,
Kessig Wolf Run and Hashep Oasis. The audit also corrected Consider and Growth
Spiral from sorcery to instant timing. A new printed-instant bundle guard and
opponent-turn quote tests prevent that authoring mistake from recurring.
Nineteen new tests cover lifetime, ordering, cleanup, all eight cards, timing,
replay and numeric reuse. The source-to-installed proof starts from a paid Kessig
activation and replays through cleanup into the next turn, verifying expiration,
the complete archive and both actor packets.

## Per-recipient numeric capture

`RecipientStat` binds only within temporary power/toughness changes. All
recipients are measured against the same derived view before any new effect is
installed. Ordinary reads clamp negative results to zero; explicit signed reads
implement the negative-power doubling exception. Nested arithmetic retains the
bound value. Equal captured change tuples share one effect record and all groups
share the instruction's timestamp. Recipient-independent expressions still use
the common memo, and instructions with no recipient-dependent values retain the
single-group fast path. Schema 28 binds these semantics.

Unleash Fury and Unnatural Growth use this shared vocabulary. Glimmerpost, Hall
of Heliod's Generosity, Healer's Hawk and Hero's Downfall compose existing counts,
zone movement, keywords and destruction. Thirteen new tests cover all six cards,
signed and repeated doubling, differing P/T and counters, snapshot timing, scope
validation and grouping. One hundred identical recipients produce one record.
The installed proof resumes an opponent-combat growth trigger over three
creatures, retains two distinct signed result groups, and matches the full
continuation archive and both actor packets. Planeswalker combat, loyalty and
other outstanding production requirements remain gated.

## Equipment attachment legality and printed-fact checks

The attachment interpreter now distinguishes Equipment from Auras. Equip
programs compose ordinary costs, sorcery timing, controlled-creature targets and
`Attach`; other attachment effects use the same legality check. Control may change
after attachment without detaching. Illegal or missing hosts, animated Equipment
and attached objects without an attachment type are detached by shared state-based
actions. Equipment remains on the battlefield. Attempts by a phased source or
at an illegal host do nothing. Attaching to the current host neither emits a new
attachment event nor changes its timestamp, while equip still pays its cost.

Swiftfoot Boots and Celestial Armor compose these rules with attached continuous
grants and temporary entry-trigger protection. Removing Armor in response does
not remove the independent protection instruction. Reconfigure, Fortifications,
protection and automatic attachment phasing remain unsupported. Schema 29 binds
the updated attachment semantics.

Seventeen additional tests cover both cards, control, host departure/type changes,
source animation/phasing, timing, no-op reattachment and replay. The installed
proof pays to switch hosts, then removes the new host, preserving unattached
Equipment and comparing the complete continuation archive and both actor packets.
The bundle loader now checks printed types, subtypes, supertypes, colors, base
P/T, mana value and normal casting cost as well as the existing instant-timing
check. All 143 authored programs pass this structural audit. These checks detect
transcription errors; they do not certify complete rules behavior or host readiness.

Attachment legality now validates the exact referenced object against cached
characteristics instead of building a full battlefield candidate set for each
attachment. The no-scan test covers this path; existing Aura tests retain their
behavior. This removes repeated board scans from attachment state-based checks.

## Durable experimental command adapter

`rules_durable.py` adds a private SQLite FULL/WAL journal around the actor adapter.
A transaction appends one command/receipt, updates the committed head and returns
only after commit. Every 32 commands by default it also writes a full checkpoint;
accepted execution failures force a checkpoint and stop dispatch. Normal appends
do not serialize a whole-history checkpoint. Reopening verifies the receipt and
adapter hash chains, restores the latest checkpoint and replays fewer than one
checkpoint interval of deterministic engine commands. It never calls a pilot or
replays a model/tool delivery. A process exit before commit leaves the previous
committed prefix; after commit the same request ID finds its receipt.

Transport request IDs bind the authenticated actor and exact command. Duplicates
do not execute again; their acknowledgment names the original accepted revision
and includes the current actor packet. Different input with the same ID rejects.
A second writer is fenced once another instance advances the head. A failed
transaction closes its in-memory instance; reopen the same file before retrying
the same request ID. This resolves an uncertain commit from durable evidence.
The database and its archives are private engine evidence, not pilot packets.
Creation never overwrites an existing file. Journal schema 2 is implementation-
bound and is reported separately from kernel schema 29.

Twenty tests cover receipt binding, validation rejection, periodic checkpoints,
no-checkpoint appends, writer fencing, corruption, forced failure checkpoints,
production rejection and actual subprocess exits immediately before/after SQLite
commit. The installed proof opens a source-created database, reconstructs one
committed tail command, suppresses a duplicate and commits a new continuation.
Card coverage remains 143/334; this host-adapter work does not certify more cards.

`rules_durable_benchmark` compares checkpoint intervals 1 and 32 over 65 synthetic
commands, three repetitions, on local temporary storage. The recorded ordinary
commit median is about 0.9 ms with periodic checkpoints; writing a checkpoint for
every command has a median of about 3.0 ms. The report also records checkpoint
commit and reopen costs. These include engine/packet work but exclude inference,
network, production disks and campaign integration. Full production host binding,
quarantine/sealing, role/evidence delivery and historical-runtime selection remain
unfinished. No existing game or software host uses this wrapper.

The durable journal now requires a cohort/game/branch/contract binding, checked
before engine restoration. Recovery can require an externally retained commit
receipt, rejecting valid older backups and divergent same-height prefixes while
accepting a later head containing the acknowledged ancestor. Duplicate replies
return the original receipt and current packet. Six additional regressions cover
these boundaries and validation before file creation/open. The installed proof
also rejects the wrong branch before recovering with a retained ancestor receipt.
The caller must preserve the strongest receipt; this component does not yet bind
the production host lifecycle or provide a global execution lease.


## Static tribal grants: 145 authored cards

Lyra Dawnbringer and Lord of the Unreal reuse `ContinuousProgram`, subtype and
controller selectors, source exclusion, `AddKeywords` and `ModifyPT`. No runtime
card-name branches or new instruction types were added. Static membership is
recomputed as creatures enter, controllers change, or sources depart or phase out;
multiple sources add their numeric bonuses while either remaining source retains
the keyword. Lyra excludes itself; Lord's selector does not exclude its source
when that source is an Illusion. Body Double inherits the copied static program.

Eight regressions cover these boundaries, printed-cost casting, real target
rejection from granted hexproof, and checkpoint/replay of a copied Lord. Full
repository validation passes 668 tests; the isolated installed wheel passes 547
primitive tests and asset verification. The shared rules remain experimental,
including unfinished general ability-loss and layer interactions.

Coverage is now 145/334 unique cards and 209/400 copies, leaving 189 unique cards
without complete programs. The [full fixed-pod list](RULES_PRIMITIVES_CARD_LIST.md)
shows authored programs, fixture-only cards and remaining cards with deck names.
No production gate was removed and the stopped legacy game remains untouched.


## Composable conditions and fallback effects: 148 authored cards

`AllConditions`, `AnyConditions` and `NotCondition` compose the existing battlefield
count predicates. Effects, intervening clauses, entry modifiers and continuous
programs use the same evaluator. Boolean evaluation short-circuits; the layer
dependency analysis separately visits every nested selector, including operands
that were skipped in the current state. The optimized evaluator retains agreement
with exhaustive evaluation when a later type change alters a nested condition.
Validation rejects empty/mutable compound operands, unsupported leaves, excessive
width and excessive depth.

`IfCondition` now has an explicit `otherwise` instruction tuple. It checks once
and schedules exactly one branch, preserving that choice across pauses. Validation,
target checks, token discovery and mana-ability classification inspect both
branches. Existing authored programs were re-encoded with an empty fallback;
experimental kernel checkpoint schema is now 30. Production contracts are untouched.

Urza's Mine, Urza's Power Plant and Urza's Tower use these shared predicates to
check controlled land subtypes. Each activation produces normal or enhanced mana,
never both. A single land with both required subtype combinations can satisfy both
conditions; names alone do not qualify. Opponent-controlled and phased lands do
not qualify. The interpreter still lacks general mana replacements, so these
programs carry no production certification.

Eleven new tests cover truth tables, short-circuiting, one-time branch selection,
fallback validation/classification, pending fallback recovery, entry look-ahead,
intervening-condition replay, nested layer dependencies and the three cards.
Repository validation passes 679 tests, and the fresh installed wheel passes 558
primitive tests plus asset verification and source-created durable recovery.
Coverage is 148/334 unique cards and 212/400 copies, with 186 unique cards remaining.


## Numeric selectors and occurrence-only conditions: 151 authored cards

`CharacteristicRange` supplies inclusive power, toughness and mana-value bounds
for shared selectors and zone-event filters. Missing power/toughness never counts
as zero; signed bounds remain signed. Battlefield checks read the same derived
view used by targeting and state-based actions. Leaves filters use the pre-event
view, retaining simultaneous departing modifiers. Resolution rechecks numeric
target restrictions. Library searches recognize numeric constraints as a stated
quality and permit failure to find through the existing search protocol.

Layer dependency pruning now accounts for numeric predicate reads, including
nested condition selectors. Setters, modifiers and switches retain dependency
checks when they may change those reads; optimized and exhaustive results are
compared in regression coverage. Event-range filters outside zone events reject
explicitly rather than being silently ignored.

`AbilityProgram.occurrence_condition` evaluates only when an event occurs. It is
separate from `intervening_if`, which still checks both occurrence and resolution.
Ruby's attack wording uses the former, as confirmed by the official Wilds of
Eldraine release notes in the source ledger. A queued occurrence never acquires a
new resolution condition. Copied definitions retain these fields. Kernel schema
31 and re-encoded authored assets bind the new vocabulary; production contracts
remain untouched.

Garruk's Uprising, Ruby, Daring Tracker and Sun Titan now use shared instructions
for their complete printed text. Fifteen new regressions cover the numeric and
timing boundaries, simultaneous departure evidence, target resolution, search
choices, real attacks, optional returns, printed casting costs and Ruby's haste
mana activation. Repository validation passes 694 tests; the isolated installed
wheel passes 573 primitive tests plus verification and durable recovery.
Coverage is 151/334 unique cards and 215/400 copies; 183 unique cards remain.
Production certification and host adoption remain blocked.


## Variable casting reductions: 153 authored cards

`CastSpec.generic_reduction` evaluates a bounded shared numeric expression during
pure action quoting. Battlefield counts and aggregate derived statistics reuse the
existing evaluator. The discount combines with static modifiers and per-card
commander tax before the generic-cost zero floor; colored requirements and printed
mana value remain unchanged. The proposal's base view is computed once per quote
rather than once per modifier. Revision-bound commit revalidation rejects a changed
battlefield before paying resources. Runtime event values, source statistics,
unannounced X and hidden-zone counts are rejected in this expression context.

Ghalta, Primal Hunger uses the signed total power of controlled unphased creatures,
clamped only after summation. Blasphemous Act counts creatures of every controller
and deals its damage through ordinary simultaneous damage handling. Both retain
normal timing and complete printed characteristics. Kernel schema 32 and the
re-encoded bundle bind the new cast field; general announcement/mana replacement
and production requirements remain separate gates.

Ten new regressions cover negative totals, counters, phasing, opponent counts,
colored requirements, increases, commander tax, stale quotes, pure quoting,
checkpoint payment and resolved damage. The full suite passes 704 tests and the
fresh installed wheel passes 583 primitive tests plus verification and durable
recovery. Coverage is 153/334 unique cards and 217/400 copies, with 181 unique
cards remaining. The legacy stopped prefix is preserved.


## Shared mass enchantment return: 154 authored cards

Replenish combines `SelectAll` over owned graveyard enchantments with ordinary
simultaneous movement. No runtime changes were needed. Aura attachment choices
finish before the batch enters; an Aura cannot attach to a creature entering in
the same batch, and an Aura with no legal attachment stays in its graveyard while
other enchantments return. This attachment is not targeting, so an opposing
hexproof creature can be enchanted when the enchant restriction permits it.

Eight regressions verify complete selection, ownership/type exclusions, printed
cost payment, entry triggers, mutual entry observation, impossible Aura entries,
and checkpoint/replay while the second Aura choice is pending. The complete entry
batch waits for all choices, then commits once. The suite passes 712 repository
tests and 591 installed primitive tests, with asset verification and durable
source-to-wheel recovery. Coverage is 154/334 unique cards and 218/400 copies;
180 unique cards remain. Production gates and the stopped legacy game are intact.


## Additive subtype layers: 156 authored cards

`AddSubtypes` appends named subtypes in layer 4 without replacing existing
subtypes, types, supertypes, colors or printed abilities. Static programs require
an explicit matching card-type selector. The dependency analysis includes all
subtype reads, including exclusions, unions and nested predicates. Adding a
subtype can therefore change another effect's recipients before it applies;
optimized and exhaustive layer evaluations are compared in regression coverage.
This is additive handling, not general subtype replacement/removal or ability loss.
Temporary subtype changes remain outside the accepted vocabulary.

Dryad of the Ilysian Grove grants the five basic land types to controlled lands
and uses existing additional-land permissions. Yavimaya, Cradle of Growth grants
Forest to every battlefield land, including itself. The existing intrinsic land
mana ability derivation supplies the corresponding activations; neither card has
a bespoke mana execution branch. Grants track current control and phasing and
end when their source leaves. Other zones remain unchanged. Body Double inherits
Dryad's static programs and land permission through ordinary copied definitions.

Eleven new tests cover subtype membership, real mana payment, preserved original
abilities, opposing lands, overlapping sources, source departure, control changes,
phasing, dependency order, copied-program replay and Dryad's printed casting cost.
The full suite passes 723 tests and the fresh installed wheel passes 602 primitive
tests plus verification and durable recovery. Kernel schema 33 binds the new node.
Coverage is 156/334 unique cards and 220/400 copies, leaving 178 unique cards.
No production gate or started game contract was changed.

## Shared milling: 157 authored cards

`Mill` composes shared quantities and player recipients with simultaneous zone
proposals. It fixes the recipient set, quantity and top-card references before any
replacement choice and checkpoints those references. Short or empty libraries
move as many cards as possible without generating a draw or failed-draw event;
zero explicitly selects no cards. Redirected destinations use the normal zone
replacement machinery. This implements the movement instruction in CR 701.17a–c
(pinned 2026-08-19 rules file); it does not implement milling costs, mill-trigger
patterns, replacement multiplication, or downstream “the milled card” bindings.

Trenchpost now uses ordinary colorless mana, a targeted nonmana activation with
three generic mana and a tap cost, and a current controlled-Locus count evaluated
on resolution. There is no card-name execution branch. The nine new tests cover
atomic multi-player milling, shortages, zero, replacement suspension and restored
continuation, quantities, validation, mana classification, costs and targeting.
Kernel schema 34 binds the new instruction and persisted in-flight batch.

The full suite passes 732 tests; the isolated installed wheel passes 611 primitive
tests, asset verification and source-to-wheel durable recovery. Coverage is
157/334 unique cards and 221/400 copies, leaving 177 unique cards. Production
admission and simulation initialization remain blocked by the remaining gates.

## Rogue's Passage: existing combat composition

Rogue's Passage uses the existing colorless mana activation and a four-generic,
tap activation targeting any creature. The existing exact-incarnation temporary
combat restriction prevents declaring blockers against that creature and expires
at cleanup. Source departure does not end the effect; an opposing creature is a
legal target, and a blinked target is not the same incarnation at resolution.
The internal `unblockable` flag is a combat-restriction representation, not a claim
that “can't be blocked” is a Magic keyword ability. General ability removal is
still gated separately.

Four tests exercise paid activation, source departure and replay, cleanup,
incarnation legality, real block declaration, mana activation and invalid targets.
No runtime module or checkpoint schema changed. The full suite passes 736 tests;
the installed wheel passes 615 primitive tests, asset verification and durable
recovery. Coverage is 158/334 cards and 223/400 copies, leaving 176 unique cards.
Production initialization remains blocked. Existing synthetic benchmarks retain
the same runtime identity; no new speed improvement is claimed for a data-only
card migration.

## Shared current-life conditions: 159 authored cards

`LifeCondition` provides inclusive optional minimum/maximum bounds on the source
controller's current life total. It composes with the same AND/OR/NOT tree used
by occurrence checks, intervening clauses, resolving branches, entry modifiers
and continuous layers. Explicit life totals flow into optimized and exhaustive
layer evaluation, including entry lookahead and pre-event reconstruction. Missing
player state fails closed rather than guessing. Existing state revisions invalidate
cached characteristics after life changes. Life predicates read no object selector
and do not introduce false layer dependencies.

Twinblade Paladin combines the shared life-gain trigger and counter instruction
with a self-only double-strike grant above the 25-life threshold. Nine tests cover
thresholds, signed bounds, controller changes, one counter per gain event, nested
layer parity, missing state, condition rechecking, checkpoints and printed costs.
Starting-life comparisons, life-gain replacement effects and turn-history
conditions remain unsupported; no partial programs for those cards are admitted.

Kernel schema 35 binds this new condition and its explicit evaluation inputs.
The full suite passes 745 tests; the installed wheel passes 624 primitive tests,
asset verification and durable recovery. Coverage is 159/334 cards and 224/400
copies, leaving 175 unique cards. Production initialization remains blocked.

Simultaneous life payment and sacrifice retain pre-event life totals for leaves
trigger conditions. The new regression distinguishes occurrence-only evaluation
from current-life checks at resolution; the sacrificed source triggers at 25 life
even though paying its cost leaves its controller at 24.

## Starting-life comparisons: 160 authored cards

State schema 11 retains each player's starting life separately from current life.
The default remains 40; explicit synthetic setup supports a positive integer or
an exact per-player mapping, copied and validated at construction and restoration.
Resource changes do not alter starting life. Public actor packets expose both.
Kernel schema 36 binds this state and the extended condition vocabulary; old
experimental snapshots fail explicitly, without changing any production game.

`LifeCondition.relative_to_starting` compares signed offsets from that player's
starting total. Its inputs pass through nested predicates, layers, entry lookahead
and trigger lookback. Starting totals are immutable throughout play; current life
still uses the pre-event snapshot for leaves-trigger occurrence checks. Missing
starting totals fail closed when a relative predicate needs them.

Cosmos Elixir now uses a controller end-step trigger and one resolving branch:
above starting life draws one card, otherwise gains two life. This is not an
intervening-if trigger. Life changes in response can change which branch resolves.
Eight tests cover nonstandard totals, immutable setup, invalid restoration, public
visibility, layers/control, branch changes in both directions, replay and costs.
The full suite passes 753 tests; the isolated wheel passes 632 primitive tests,
asset verification and durable recovery. Coverage is 160/334 cards and 225/400
copies, leaving 174 unique cards. Life-gain replacement and turn-history mechanics
remain separate gates, and production initialization remains blocked.

## User-authorized commit milestone

On 2026-09-10 the user authorized committing the verified migration work to
`main` once the build is stable and a real test game has completed successfully.
Conformance scenarios and package recovery checks do not satisfy that gameplay
condition. Keep the commit pending until actual admission gates pass and the
fresh simulation supplies the successful game evidence. Preserve the stopped
legacy prefix and unrelated work when preparing that commit.

## Shared modal casting: 163 authored cards

`SpellMode` and `ModalSpec` describe independently targeted modes, bounded
selection counts and an optional condition granting a larger maximum at casting.
`rules_modal.prepare_modal` validates immutable selections without changing state
and normalizes them to printed order. The same target may occur in different
modes, while ordinary uniqueness and target-domain checks still apply within each.
Repeated modes, weighted modes, mode-specific additional costs, modal activations,
entwine and spree remain separate unsupported semantics.

Paid quotes bind mode IDs and targets, then revalidate the complete quote before
payment. Actor casts accept an optional `modes` list of `{mode_id, targets}` rows;
modal spells require their targets there and reject a competing flat target list.
Public stack summaries show chosen modes and their targets. Resolution checks
legality separately for each mode before executing any effects. If every announced
target is illegal, the entire spell fails to resolve, including nontargeted modes;
otherwise the chosen modes execute in printed order with surviving targets.
Nested selections and optional choices retain their mode's target bindings through
checkpoints and replay. General rules basis: CR 601.2b–c, 608.2b and 700.2, plus
[official modal targeting notes](https://media.wizards.com/2026/downloads/SOS_Release_Notes_FwhcBWdFIE/EN_MTGSOS_ReleaseNotes_20260410.pdf).

The commander selector reads physical object identity, not copied characteristics,
and composes with current controller, zone and phasing filters. Drown in Dreams
uses it to allow both modes at casting; the condition is not rechecked during
resolution. Valorous Stance and Return of the Wildspeaker use the same modal
path with existing targeting, destruction, temporary effects and draw quantities.

Twenty tests cover declaration validation, independent target domains, printed
order, shared targets across modes, partial/all target illegality, nested-choice
replay, actor commands/public summaries, conditional counts and all three cards.
The full suite passes 773 tests; the installed wheel passes 652 primitive tests,
asset verification and durable recovery. Kernel schema 37 binds the new program,
quote and frame formats; the implementation manifest includes `rules_modal.py`.
Coverage is 163/334 cards and 228/400 copies, leaving 171 unique cards.
Production admission remains blocked; the user-authorized commit remains pending
stability and a successfully completed real test game.

## Shared orientation selectors: 164 authored cards

`Selector.tapped` is an optional exact boolean for battlefield objects. It shares
matching across targets, queries and continuous effects, and rejects orientation
constraints outside the battlefield. Tapping and untapping invalidate derived
views through the existing state revision. Deadly Riposte uses this selector with
ordinary damage and life gain; an untapped target is illegal both at announcement
and resolution, and an all-illegal target prevents the life gain as well.
Five new orientation tests cover costs, damage, rejection, response untapping,
layer parity and validation. A further modal regression confirms that a later
mode cannot affect a target incarnation retired by an earlier mode; existing
shared movement already handled that case correctly.

Kernel schema 38 binds the selector extension. The full suite passes 779 tests;
the installed wheel passes 658 primitive tests, asset verification and durable
recovery. Coverage is 164/334 cards and 229/400 copies, leaving 170 unique cards.
Production admission and the conditional commit to main remain pending.

## Shared live-player conditions: 168 authored cards

`PlayerCountCondition` compares the count of live players, opponents or the source
controller against a nonnegative threshold. It composes with the existing boolean
condition tree, entry modifiers, layers and modal announcement conditions. Live
players are explicit evaluation input; missing player state fails closed. These
opponent relations describe the supported free-for-all game, not team rules.

Morphic Pool, Sea of Clouds, Spire Garden and Vault of Champions now use the same
unless-entry modifier and ordinary two-color mana choice. One opponent causes
tapped entry; two or more permit untapped entry. A later departure does not retap
a land that is already on the battlefield. Departure captures the pre-event live
player set for leaves-trigger conditions, alongside existing battlefield lookback;
resolution-time conditions still read the current live set.

Seven tests cover all four lands at three player counts, eliminated opponents,
entry-only duration, both colors for every land with checkpoint recovery, compound
conditions, validation, continuous-layer parity and departure-trigger lookback.
Kernel schema 39 binds the new node and evaluation inputs. The full suite passes
786 tests; the installed wheel passes 665 primitive tests, asset verification and
durable recovery. Coverage is 168/334 cards and 233/400 copies, leaving 166
unique cards. Production admission and the conditional main commit remain pending.

## Player-resource restoration audit

Checkpoint restoration previously accepted booleans, fractional/string/null life
values, incomplete player-counter ledgers and malformed counter entries. New
regressions reproduced those failures. Restored life now requires exact integers
while retaining legitimate zero or negative totals. Player counter rows require
the exact player set, nonempty string kinds and positive integer amounts.

The older `add_player_counters` helper now delegates positive additions to the
shared counter batch. A zero addition is a genuine no-op: it creates no zero-count
entry and does not increment the state revision. Invalid kinds fail before
mutation, and departed players remain unaffected. Five tests cover invalid
restoration, legitimate negative life, counter roundtrips and helper semantics.
Kernel schema 40 binds the tightened runtime invariants; state shape stays 11.

The full suite passes 791 tests; the installed wheel passes 670 primitive tests,
asset verification and durable recovery. Coverage remains 168/334 cards and
233/400 copies. This is checkpoint correctness work, not new card coverage or
production certification. The conditional main commit remains pending.


### Permanent counter restoration and shared additions

The permanent resource audit reproduced nine failures: restored object counters
accepted invalid amounts, empty/non-string kinds, duplicate kinds and incomplete
rows, while a zero direct addition created a counter row and advanced the state
revision. Object invariants now reject those malformed rows. Direct additions
use the same batch mutation as other counter placement; zero additions leave
state unchanged after recipient and argument validation. Phased and nonbattlefield
recipients remain unavailable. Four regression tests also cover direct/batch
parity, checkpoint round trips and opposing-counter cancellation.

Kernel checkpoint schema 41 binds this tightened implementation; the state shape
remains schema 11. Authored coverage remains 168/334 unique cards and 233/400
copies. No production certification or real test game is claimed.


## Shared activation origins: 170 authored cards

Activated programs now declare a zone, defaulting to the battlefield. Hand and
graveyard activations use ownership permission; battlefield activations retain
controller permission and phasing checks. Source discard is an exact source cost,
not a free choice of another hand card. Source tap/counter costs and incompatible
source sacrifice/return origins are rejected at program validation. The existing
announcement transaction pays mana and moves the source only after replacement
choices, then retains the ability on the stack independently of that source.

Akroma's Vengeance and Raffine's Tower use this path for cycling: three generic
mana, discard the source from hand, then draw one on resolution (pinned CR
702.29a-b). Their ordinary destruction, entry-tapped and intrinsic basic-land mana
behaviors use existing primitives. No card-name execution branch was added.
Cycling-specific trigger matching, cycling cost modifiers and typecycling are
not certified by these programs; these interactions remain production gates.

Eight tests cover both cards, exact discard selection, opponent-turn timing,
wrong origins/owners, replacement-choice checkpoints, actor visibility and replay,
three intrinsic mana colors, simultaneous destruction, and a separate generic
graveyard activation. Kernel schema 42 adds the activation zone to serialized
programs; state schema remains 11. Coverage is 170/334 unique cards and 235/400
copies, leaving 164 without authored programs. Production admission remains false.


## Shared life-payment mana ability: 171 authored cards

Mana Confluence uses existing tap/life costs and five-color mana choice with no
runtime changes. Four tests cover all colors, paid-choice checkpoint recovery,
zero-life and tapped-source rejection, actor replay and duplicate rejection.
At one life, the ability finishes its mana choice before the payer departs at
the state-based-action boundary; payment is not damage. This confirms existing
shared behavior rather than introducing a card-specific exception. Coverage is
171/334 unique cards and 236/400 copies, leaving 163 unauthored. Kernel schema
42 and state schema 11 remain unchanged; production admission remains gated.


## Shared damage results for permanent types

Damage transactions now receive the recipient's current relevant types from the
shared characteristics view. Creature damage is marked, planeswalker damage
removes loyalty, and battle damage removes defense (pinned CR 120.3c/e/h).
A permanent with several of these types receives every applicable result.
Multiple assignments share the remaining counter ledger and commit once;
removing fewer counters than damage dealt does not reduce lifelink's life gain.
Zero-loyalty planeswalkers join the simultaneous state-action graveyard group
under CR 704.5i, independently of indestructible.

Six tests cover these results, animated planeswalkers, multiple assignments,
atomic rejection, zero damage and checkpoint recovery. Kernel schema 43 binds
the updated damage/state-action semantics; state shape remains 11. This does
not implement battle defeat/transform triggers, battle zero-defense state actions,
loyalty activation costs, or attacks against planeswalkers/battles. Those remain
explicit gaps, so no additional card is claimed authored or production-certified
in this pass. Coverage remains 171/334 unique cards and 236/400 copies.


## Damage recipients changed during resolution

End-to-end instruction tests reproduced three failures: damage after moving its
target, damage after blinking that target, and damage after removing its animation
effect all aborted an accepted spell. The damage interpreter now skips obsolete
incarnations, unavailable objects and permanents without a damage-recipient type
(CR 120.1a). It does not substitute a blinked object's new incarnation. Later
instructions still resolve, and skipped damage produces neither damage events
nor lifelink gain. Target legality remains checked at the ordinary resolution
boundary; this is per-instruction recipient handling, not a second fizzle check.

Four tests cover the reproduced failures and real actor-command damage to
planeswalkers/battles with matching replay packets. Kernel schema 44 binds the
fix; state schema 11 and authored coverage of 171/334 remain unchanged. Battle
defeat/transform and non-player combat defenders still require migration.


## Shared counter-range selection: 172 authored cards

Selectors now compose named counter ranges with type, control and other existing
predicates. Bounds are inclusive nonnegative exact integers; absent counters count
as zero. Duplicate kinds, empty names, contradictory bounds and nonbattlefield
counter selectors are rejected. Ordinary selectors skip counter-map allocation
and range evaluation when no counter constraint is present.

Inspiring Call captures controlled creatures with positive +1/+1 counters, draws
once per creature using the unchanged set immediately before drawing, then gives
that retained group indestructible until cleanup. More counters on a creature do
not multiply the draws. Later counter removal does not revoke the granted ability.
No target choice or card-specific runtime code is involved. Six tests cover
selection, zero/phased groups, changes before and after resolution, expiry, actor
replay, numeric ranges and cached/exhaustive layer parity. Kernel schema 45 adds
counter ranges to serialized selectors; state schema remains 11. Authored coverage
is 172/334 unique cards and 237/400 copies, leaving 162 unauthored. Production
certification and launch remain gated.


## Captured selection counts remove duplicate queries

`SelectedCount` is a shared numeric expression bound inside Select/SelectAll.
It counts the exact chosen group once, survives subsequent object movement and
checkpoint suspension, and composes with numeric scaling/division. Nested
selections override their own count while later outer siblings retain the outer
value. Unbound uses are rejected during program validation.

Inspiring Call now draws using this captured count instead of querying its
counter-filtered group a second time. An instrumented regression verifies one
query for the group; the retained indestructible recipients and draw behavior
are unchanged. Five tests cover movement, actual optional selections, nested
scope, paused recovery, validation/codec and this query count. Kernel schema 46
binds the new numeric result; state schema remains 11. Authored coverage remains
172/334 unique cards and 237/400 copies. Production admission remains gated.


## Shared damage-received triggers: 173 authored cards

The damage interpreter now emits one damage_received event per permanent per
simultaneous batch, with the total amount available through EventAmount. Existing
object type, self and controller filters apply. Occurrences are collected before
state-based actions, so lethal damage does not erase them. Separate batches
remain separate occurrences; zero damage creates none. Player-damage recipient
triggers and per-source recipient wording remain outside this event's scope.

High Priest of Penance uses this event, ordinary nonland targeting and optional
destruction at resolution. The [official Gatecrash FAQ](https://magic.wizards.com/en/news/feature/frequently-asked-questions-2013-01-21)
confirms per-instance and lethal-damage triggering. Six tests cover simultaneous
sources, separate/zero batches, lethal-source departure, target-before-optional
ordering, checkpoint recovery, a generic numeric observer, copied-definition
inheritance and the printed casting cost. Kernel schema 47 binds this event
vocabulary; state shape remains 11. Coverage is 173/334 unique cards and 238/400
copies, leaving 161 unauthored. Production launch remains gated.


## Event type lookups shared across observers

Announcement-trigger dispatch now computes the announced object's type view
lazily and at most once per event. Unfiltered observers skip the lookup entirely.
The local value also preserves the existing explicit prior-type/LKI fallback for
a source that left during payment. Trigger occurrence checks and observer order
remain unchanged; no cross-event cache is introduced.

Three instrumented tests reproduced 12 lookups for 12 observers before the change.
The same cases now perform zero lookups without type filters and one with type
filters, including a departed source; all 12 expected occurrences remain. An
incompatible prior type still excludes the observers. Kernel schema 48 binds the
implementation; state schema remains 11. Authored coverage remains 173/334 unique
cards and 238/400 copies, with production admission still gated.


## Captured zone-event subjects and controllers: 174 authored cards

Zone-change occurrences retain an event_subject exact incarnation and
event_controllers from the observed battlefield/stack object. Leaves events use
the pre-event object; other zone events use the post-event object. Objects outside
those controller-bearing zones contribute an empty controller list. Shared
recipient_relation filters now apply to zone events as well as counter events.
Contradictory controller filters and unbound event values are rejected.

Polluted Bonds uses the opponent-controlled land-entry filter and captured player
for non-targeted life loss, followed by controller life gain. Its source or land
leaving, and later control changes, do not redirect the effects. Eight tests cover
ordinary and simultaneous entry, departure/control changes, generic event-object
movement, cast payment, checkpoint/actor replay, validation and actor visibility.
Stack summaries show captured players and visibility-filtered event subjects;
opponents do not receive exact identities of hidden hand cards.

Kernel schema 49 binds these occurrence fields and the expanded filters. State
schema remains 11. Coverage is 174/334 unique cards and 239/400 copies, leaving
160 unauthored; production admission remains gated.


## Controller predicates distinguish ownership

Two regression cases reproduced controller filters treating hand-card ownership
as control. Controlled/opponent-controlled selectors and zone-event filters now
require a battlefield or stack subject (pinned CR 109.4); owned selectors remain
independent. Leaves-the-battlefield events still use the pre-departure object's
controller, including when that controller differs from the owner. Unfiltered
hand events retain an exact subject but no actual event controller. This does
not implement effects that explicitly request a controller and invoke the owner
fallback under CR 108.4a, nor the separate exceptions in CR 109.4.

Four tests cover hand/graveyard/exile/library predicates, hand-entry filters,
pre-departure control and unfiltered event bindings. The authored bundle contains
no controller selectors in non-controller-bearing zones. Kernel schema 50 binds
the corrected predicates; state schema remains 11. Coverage remains 174/334
unique cards and 239/400 copies; production admission remains gated.


## Death Grasp composes existing damage and X rules: 175 authored cards

Death Grasp has an authored XWB sorcery program: its any-target specification
unions players with creatures, planeswalkers and battles; damage precedes an
independent gain-X-life instruction. No runtime change or card-name branch was
needed. Six tests cover all recipient domains, self-targeting, X=0, printed
colored/generic payment, sorcery timing, target illegality, checkpoint recovery
and actor replay. Battle tests retain positive defense and do not certify battle
defeat/transform; damage prevention and other general rules remain production
gates. Kernel schema 50 and state schema 11 are unchanged. Coverage is 175/334
unique cards and 240/400 copies, leaving 159 unauthored.


## Damage no-ops preserve revisions and sparse ledgers

Two reproduced state-layer defects created unnecessary history: damage directed
only to a departed player advanced the revision, and a zero commander-damage
assignment created a zero ledger row when another assignment dealt damage. The
shared transaction now tracks actual applicable nonzero damage and skips
zero-valued results after validation. Ignored damage neither gains lifelink life
nor advances the revision. Invalid zero assignments still reject the entire batch
before mutation. Three tests cover these cases and atomic rejection.

Kernel schema 51 binds this tightened mutation behavior; state shape remains 11.
Coverage remains 175/334 unique cards and 240/400 copies. Production admission
and the successful-real-game commit milestone remain gated.


## Shared two-color hybrid payment matching: 176 authored cards

Mana costs now admit ordinary two-color hybrid pips. Fixed requirements consume
paid colors first; remaining hybrid requirements use a small residual network
with identical pips aggregated. This handles overlapping choices without greedy
misassignment or enumeration of every color combination. Generic cost still
requires the exact remaining total; only unrestricted already-produced mana is
used. Two-brid, Phyrexian and colorless-hybrid costs remain unsupported.

Flooded Grove uses the ordinary colorless tap ability and G/U-plus-tap filter
with the existing mana-choice continuation. Six tests cover all six input/output
combinations, suspended payment recovery, colorless output and payment rejection,
shared casting with fixed/generic/overlapping hybrid costs, large grouped costs,
validation/codec and exhaustive small matching against a brute-force oracle.
Kernel schema 52 binds the expanded payment semantics; state schema remains 11.
Coverage is 176/334 unique cards and 241/400 copies, leaving 158 unauthored.
Production admission and fresh simulation remain gated.


## Shared color selectors: 177 authored cards

Selectors now support required colors, any-of colors and excluded colors using
the derived characteristics view. Invalid colors and duplicate entries are
rejected. Colorless means no colors, not a sixth color. Library color predicates
count as qualifying restrictions and permit failure to find through the existing
private search protocol. Color-changing layer effects remain a separate gap.

Goblin Anarchomancer uses one red-or-green predicate on controlled spells and the
shared generic reduction. A red-green spell receives one reduction per Goblin;
multiple Goblins stack reductions before the existing zero floor. Colored and
hybrid pips remain payable, and choosing blue to pay a green-blue hybrid spell
does not change that spell's colors. Six tests cover the color matrix, control
changes, stacked reductions, hybrid payment, predicate validation, library search,
printed RG cost and actor replay. Kernel schema 53 adds color selector fields;
state schema remains 11. Coverage is 177/334 unique cards and 242/400 copies,
leaving 157 unauthored. Production launch remains gated.


## Shared land animation and color layer: 179 authored cards

SetColors applies in layer 5 for static and temporary effects, including clearing
all colors. Dependency pruning tracks color reads in selectors and nested
conditions; exhaustive and optimized evaluation agree in a same-layer dependency
regression. Temporary AddSubtypes uses the existing guarded subtype union.
Activation declarations gain a validated minimum_x constraint, checked before
any payment or announcement mutation.

Lumbering Falls and Lair of the Hydra combine these primitives with existing
entry, mana, type addition, base-P/T, keyword and cleanup rules. Their “still a
land” wording retains prior types/subtypes under pinned CR 205.1b. Lair requires
positive X; repeated activations use the latest base P/T. Seven tests cover both
entry rules, mana choices, paid animations, control-duration readiness, retained
subtypes, blink/cleanup, checkpoint recovery, color dependencies and validation.
Kernel schema 54 adds the color operation and activation minimum; state schema
remains 11. Coverage is 179/334 unique cards and 244/400 copies, leaving 155
unauthored. Production admission remains gated.

## Copied animation and pending-source recovery audit

Two additional regressions verify inherited Lair of the Hydra activation under
another controller, captured X and paid mana across a pending-stack checkpoint,
and cleanup after restoring an active animation. The original land stays
unanimated; the copy retains its copied definition after the temporary layers
expire. A separate pending activation resolves without affecting a blinked
source's new incarnation, identically before and after recovery. Both checks
passed without an engine change. Kernel schema remains 54; authored coverage
remains 179/334 unique cards and 244/400 copies. These fixtures do not certify
arbitrary checkpoint input or constitute a production test game.

## Shared defending-player capture: 180 authored cards

Each declared attack occurrence retains its own defending_player value. Shared
Draw, Mill, LoseLife, WithLifeLost and CreateTokens player selection can use this
binding; validation rejects it outside attack triggers. Actor summaries expose
the public player identity. The retained value survives source departure and
controller changes, and replay includes the original attacker declaration. This
implements the supported player-only combat case of pinned CR 508.5/508.5a;
planeswalker/battle defenders and attack reassignment remain separate gaps.

Restless Fortress combines this binding with existing tapped entry, W/B mana
choice, temporary type/subtype/color/base-P/T layers and controller life gain.
Seven regressions cover printed actions, different defenders in one declaration,
actor replay, source departure/checkpoint recovery, controller change, copied
abilities, generic observer effects and invalid bindings. Kernel schema is 55;
state schema remains 11. Coverage is 180/334 unique cards and 245/400 copies,
leaving 154 unauthored. No production admission or real game is claimed.

## Battle combat eligibility and immediate removal audit

Four regressions reproduced Battle creatures being accepted as attackers or
blockers and remaining in combat after gaining the Battle type. One shared
combat-creature predicate now excludes Battles in declaration, blocker menus
and combat retention (pinned CR 508.1a, 509.1a and 506.4). Illegal declarations
leave state unchanged; removing a blocker retains the attacker's blocked status.

A fifth regression exposed a more general timing defect: losing and regaining
Creature, or gaining and losing Battle, within one resolution could escape
combat removal. Completed state-mutating instructions now prune combat before
the next instruction. The guard skips unchanged instructions and absent combat;
removal does not wait for state-based actions or re-add recovered creatures.
Checkpoint recovery preserves the resulting combat state. Kernel schema is 56;
state schema remains 11. Authored coverage remains 180/334 and 245/400 copies.
Battle defense, defeat/transform, and other missing combat rules remain gated.

## Shared search-to-top placement: 182 authored cards

SearchLibrary now accepts a library destination: choose matching cards in one
ordered selection, shuffle, and place the chosen cards on top in the specified
order. Shuffling the full library and pinning the selected cards produces a
uniformly shuffled remainder; no selected card changes zones. Old inspection
references retire on shuffle, and a private search_top observation retains the
chosen cards with their current references. Explicit reveal remains separate.

Enlightened Tutor uses the artifact-or-enchantment quality selector and reveal;
Vampiric Tutor requires finding a card when possible and then loses 2 life,
including with an empty library. Both use their printed instant timing/cost.
Six regressions cover required/optional finding, reveal/private visibility,
empty-library completion, printed payment/life, multi-card ordered placement,
checkpoint/actor replay, one shuffle, no false zone events and invalid tapped
placement. Kernel schema is 57; state schema remains 11. Coverage is 182/334
unique cards and 247/400 copies, leaving 152 unauthored. Production gates remain.

## Entry-copy orientation and search-trigger audit: 183 authored cards

The shared optional entry-copy declaration can now impose tapped entry only
when accepted. The replacement updates the same atomic proposal before copied
entry modifiers are evaluated. It preserves an existing tapped proposal and
does not change orientation when declined. Validation requires a copy selector
and an exact boolean. All authored CardProgram records carry the new default.

Vesuva uses a battlefield Land selector and this orientation constraint. Four
regressions cover acceptance/decline and checkpoint parity, copied entry-trigger
controller, exclusion of temporary animation/counters from copied values, and
validation/codec. A fifth audit regression confirms a shuffle trigger draws
the tutored card only after search-to-top placement and subsequent life loss
finish, identically after checkpoint recovery. No search runtime repair was
needed for that interaction. Kernel schema is 58; state remains 11. Coverage is
183/334 unique cards and 248/400 copies, leaving 151 unauthored. General copy
exceptions and all production gates remain separate.

## Accumulated entry orientation audit

The incoming-object view now uses the accumulated zone proposal's tapped
orientation. Previously, an accepted tapped copy replacement changed the final
entry but later selectors still saw the original untapped object, suppressing
an applicable entry-counter replacement. A regression reproduced the missing
counter and now passes with checkpoint parity. Another regression orders an
untap replacement before or after a tapped-only counter replacement: eligibility
is re-evaluated after untapping, while an already applied counter is retained.
A third check verifies copying an existing copy uses its copied definition
without another copy prompt. Kernel schema is 59; state schema remains 11.
Authored coverage remains 183/334 unique cards and 248/400 copies.

## Ordered library zone placement: 184 authored cards

Move can explicitly place newly moved cards on top or bottom of their owners'
libraries. Selection order reads top-to-bottom within each library. Replacement
resolution remains atomic; only cards whose resulting destination is Library
are positioned. Explicit placement also repositions retained references already in the library
(extended in the audit below); ordinary same-zone moves remain a no-op. Own-library placement retains a
private observation with resulting references, while the event records only
player, position and amount. All authored Move nodes carry the new default.

Brainstorm uses printed instant U casting, Draw(3), one required ordered hand
selection, and top placement. Six tests cover selecting old or newly drawn
cards, top/bottom and multiowner order, checkpoint/actor replay and visibility,
redirected destinations, invalid placements, and completing put-back before
failed-draw loss. Kernel schema is 60; state remains 11. Coverage is 184/334
unique cards and 249/400 copies, leaving 150 unauthored. Production gates remain.

## Existing-library placement and replacement audit

Explicit top/bottom placement now handles retained library references alongside
new arrivals, preserving their combined requested order within each owner
library. A regression reproduced the existing card being omitted from mixed
placement. The interpreter groups results in one pass through the selected
references; same-zone cards retain identity and create no zone-change events.

Three new tests cover top/bottom positioning of existing references with
checkpoint parity, mixed existing/incoming order, and a commander destination
choice that pauses before atomic placement and restores identically. Synthetic
retained bindings exercise the low-level operation; ordinary Select still
rejects library access without explicit visibility semantics. Kernel schema is
61; state remains 11. Authored coverage remains 184/334 and 249/400 copies.

## Shared target statistics: 185 authored cards

TargetStat reads power, toughness, mana value or color count from distinct
object targets in the current target scope. It supports sum or maximum with
a nonnegative final quantity. Current objects use derived characteristics;
departed incarnations use the retained battlefield view. An unavailable
last-known view fails closed. Validation requires a target binding and rejects
unsupported statistics/aggregations. No card-name dispatch is introduced.

Breathe Your Last uses printed instant 1BB casting, a creature-or-planeswalker
target, shared destruction and color-count life gain. Seven tests cover zero
through five colors and planeswalkers, indestructibility, temporary-color LKI,
illegal/blinked targets, a checkpoint between destruction and life gain,
actor replay, aggregation/deduplication and validation/codec. Kernel schema is
62; state remains 11. Coverage is 185/334 unique cards and 250/400 copies,
leaving 149 unauthored. Production admission remains gated.

## Destination-independent zone results: 186 authored cards

WithZoneResult accepts a null destination to follow up on completed zone
changes without requiring a particular resulting zone. Existing destination
filters remain unchanged; no event still means no follow-up. This shares the
same moved-reference/controller/count bindings and replacement transaction.

Noxious Gearhulk combines printed 4BB casting, 5/4 artifact creature Construct
characteristics, menace, targeted optional entry destruction, this result
check and TargetStat toughness. The [official Kaladesh release notes](https://magic.wizards.com/en/news/feature/kaladesh-release-notes-2016-09-16)
confirm that destruction to another zone still grants life, indestructibility
does not, and toughness uses last battlefield information. Six regressions
cover printed casting, success/decline/indestructibility, replaced destination,
temporarily boosted token toughness, checkpoint/actor replay and generic
result validation. Kernel schema is 63; state remains 11. Coverage is 186/334
unique cards and 251/400 copies, leaving 148 unauthored. Production gates remain.

## Public-zone last-known information audit

The retained-information ledger now records departures from Stack, Graveyard,
Exile and Command as well as Battlefield. Ordinary kernel movement supplies derived
pre-event views; direct scenario collection can fall back to public printed
characteristics. The previous battlefield-only ledger caused four reproduced
errors: a countered X spell lost its stack mana value, and targets moved from
each of three other public zones lost statistics needed later in resolution.

New tests verify stack X through a post-counter checkpoint, public-card movement
into a hidden zone, and exclusion of hidden-zone departures from the ledger.
A copied Noxious Gearhulk entry ability also passes controller, target-LKI and
checkpoint checks. Kernel schema is 64; state remains 11. This extends retained
engine information, not actor visibility or hidden-zone access permissions.
Coverage remains 186/334 unique cards and 251/400 copies; production gates remain.

## Count-based characteristic P/T: 187 authored cards

CardProgram can define both power and toughness as a shared CountObjects
expression. The evaluator collects these definitions in its existing object
pass and applies them in layer 7a, after type/color/ability layers and before
ordinary P/T setters, modifiers, counters and switches. Definitions function
in every zone and outside the game (pinned CR 604.3 and 613.4a), and copies
inherit them. Validation currently admits battlefield counts whose predicates
do not read P/T, excluding circular P/T dependencies rather than guessing.

Ulvenwald Hydra combines this definition with printed 4GG casting, reach and
an optional tapped-land search. Auxiliary catalog keyword metadata incorrectly
also lists trample; the authored program follows the Oracle text's reach only,
retains the source fingerprint, and records the discrepancy in its review basis.
Six tests cover all zones/controller context, land-count changes and zero-P/T
death, setters/modifiers/counters/cleanup with restore, copies and exhaustive
parity, printed casting/search, and validation/codec. Kernel schema is 65;
state remains 11. Coverage is 187/334 unique cards and 252/400 copies, leaving
147 unauthored. Production gates remain.

## Noncreature P/T and dependency audit

Four regressions reproduced noncreature permanents exposing printed or
characteristic-defined P/T, incorrectly satisfying numeric selectors and
contributing power to life-gain quantities. Under pinned CR 208.3/208.3a,
noncreature permanents now expose no P/T while their dormant setters/modifiers
remain available if they become creatures. Nonbattlefield printed P/T is kept.

P/T selectors reject noncreature battlefield objects during layer evaluation.
Dependency pruning recognizes that adding/removing Creature can change numeric
selector eligibility even when Creature is not an explicit type predicate.
Final P/T normalization is folded into the existing layer-7 object pass, and
empty numeric predicates avoid an extra selector scan. Tests cover printed
vehicles, characteristic definitions, animation/cleanup/checkpoint parity and
optimized/exhaustive dependency agreement. Kernel schema is 66; state remains
11. Coverage remains 187/334 unique cards and 252/400 copies; production gates
remain closed.

## External entry orientation and filtered results: 188 authored cards

EntryModifier now supports a battlefield selector for other incoming
permanents. Existing sources supply these replacements, sharing one scan with
entry-counter effects. Copy precedence, controller relations, phasing and
affected-player ordering use the existing replacement transaction. A source
entering simultaneously does not supply a general external replacement.

WithZoneResult can filter resulting objects by a selector, including derived
subtypes. Spelunking combines these primitives with printed 2G casting, entry
draw, one optional hand-land selection and four life for a resulting Cave.
Seven tests cover printed resolution, declining/non-Caves, control changes,
competing tap/untap order and atomic restore, derived Cave types, redirected
entries, simultaneous-source entry and validation. A separate integration
regression confirms a departed noncreature's absent battlefield P/T is not
replaced by its graveyard card's characteristic-defined P/T. Kernel schema is
67; state remains 11. Coverage is 188/334 unique cards and 253/400 copies,
leaving 146 unauthored. Production gates remain.

## Copied external entry effects and phasing audit

Three additional regressions verify that a copied Spelunking supplies both its
entry trigger and external replacement for its own controller, including actor
replay across a pending replacement order; that phasing disables and restores
the external replacement without changing source identity; and that two sources
apply independently at most once before a competing local tap replacement.
All pass using the existing shared implementation, with no card-specific fix or
schema change. Coverage remains 188/334 unique cards and 253/400 copies. These
synthetic checks do not close production admission or the real-game commit gate.

## Zone-event type unions and source exclusion: 189 authored cards

EventPattern supports a type union and exact-source exclusion for zone changes.
A permanent with multiple qualifying types matches once. The same predicate uses
post-entry derived characteristics and pre-departure information for leaves
patterns. Validation rejects these filters on unsupported event families and
rejects contradictory self-only/source-excluding patterns.

Liliana the Faultless composes this with its printed W legendary 1/2 body,
one-life trigger and shared mana/tap/discard activation granting another
controlled creature or planeswalker hexproof until end of turn. Seven tests
cover printed casting/self exclusion, dual-type and simultaneous entries,
copied controller context, atomic target rejection, paid discard/tap costs,
checkpoint/replay, expiry, blinked targets and codec validation. Kernel schema
is 68; state remains 11. Coverage is 189/334 unique cards and 254/400 copies,
leaving 145 unauthored. Production and real-game commit gates remain closed.

## Power-based mana and additive counter composition: 190 authored cards

Kami of Whispered Hopes uses existing controlled-permanent counter replacement
and SourceStat/ProduceMana primitives. Its printed 2G 1/1 Spirit program adds one
to positive +1/+1 placements and produces current derived power in one chosen
color through a tap mana ability. No interpreter branch or schema change was
needed. Seven tests cover printed casting and tap readiness, self/noncreature
recipients and excluded placements, derived and nonpositive power, single-color
production, atomic replacement ordering, copied controller context, phasing,
checkpoint/replay and duplicate rejection. Coverage is 190/334 unique cards and
255/400 copies, leaving 144 unauthored. Production gates remain closed.

## Exact-source counter quantities: 191 authored cards

SourceCounter reads a named counter count through the shared exact-object/current
or last-known-information lookup. It composes with quantity arithmetic and effects;
entry look-ahead rejects unsupported incoming-source queries. Lotus Blossom
combines it with printed 2 casting, optional controller-upkeep petal placement,
and the existing atomic tap/sacrifice single-color mana ability.

Seven tests cover printed casting/upkeep choices, retained counts after sacrifice,
non-petal exclusion, zero-count payment, replaced destinations and payment
checkpoints, copied controller context, generic arithmetic/validation, and
replay/duplicate rejection. A deliberately intervening scenario mutation verifies
both exact-incarnation retention and stale-choice rejection. Kernel schema is 69;
state remains 11. Coverage is 191/334 unique cards and 256/400 copies, leaving
143 unauthored. Production admission and real-game commit gates remain closed.

## Resolution-time numeric selection bounds: 192 authored cards

Select and SelectAll accept characteristic bounds expressed using the existing
quantity vocabulary. Bounds resolve before querying; equal lower/upper expressions
are evaluated once, and literal-only selectors avoid rebuilding their ranges.
Quantity validation carries announced-X and enclosing result bindings. Target,
continuous, event and other selectors continue to reject dynamic bounds until
their distinct timing semantics are implemented.

Blast Zone uses this with an entry charge counter, colorless mana, XX/tap charge
activation and 3/tap/sacrifice destruction of nonlands with mana value equal to
its retained charge count. Six tests cover all printed abilities, simultaneous
multi-controller destruction and indestructible survival, checkpoint/replay,
selection choices, preceding changes to bound values, signed literals, announced
X and invalid/unbound uses. Kernel schema is 70; state remains 11. Coverage is
192/334 unique cards and 257/400 copies, leaving 142 unauthored. Production and
real-game commit gates remain closed.

## Signed source-statistic bound audit

SourceStat now has an explicitly signed form for resolution-time numeric
selection bounds. Ordinary quantities retain their nonnegative default, and
validation rejects signed source statistics outside a bound. This avoids treating
a negative power threshold as zero when comparing mana values. Equal bound
expressions retain the existing single evaluation optimization.

Three regressions cover negative current power excluding zero-mana-value objects,
retained negative power after departure through a choice checkpoint, codec
roundtrip and rejection of invalid flags or effect-position use. Kernel schema
is 71; state remains 11. Coverage remains 192/334 unique cards and 257/400 copies;
142 cards and the production/real-game gates remain unfinished.

## Dynamic target characteristic bounds

Target selectors now admit numeric expressions that need no unavailable
announcement/result bindings, including current or signed source statistics,
source counters and battlefield counts. The existing shared query path evaluates
them for legal target menus and again at resolution. Departed sources use exact
last known information, including modified power; a returned incarnation does
not replace that information. Announced-X expressions inside characteristic
bounds remain rejected until announcement frames explicitly carry that binding;
existing X-based target cardinalities are separate and unchanged.

Six regressions cover atomic quote rejection, current-power resolution rechecks,
death-trigger modified-power menus, checkpoint/replay, new source incarnations,
negative power, copied controller/ownership context and unbound-expression
rejection. Kernel schema is 72; state remains 11. No additional complete card
program is claimed: coverage remains 192/334 unique cards and 257/400 copies,
with 142 cards and production/real-game gates unfinished.

## Public source successors and Fiendish Panda: 193 authored cards

A zone-change trigger retains its own exact public successor when its source
moves. Source-excluding target/selection queries exclude that successor as well
as the original source; subsequent incarnations are distinct. Trigger-target
contexts receive the same retained values as their resolution frames. This is a
generic application of pinned CR 400.7e public-zone association, not card-ID
exclusion or a Panda-specific runtime branch.

Fiendish Panda composes printed 2WB 3/2 Bear Demon characteristics, a life-event
counter trigger and death reanimation with signed last-known-power bounds,
non-Bear and ownership filters. [Foundations release notes](https://magic.wizards.com/en/news/feature/foundations-release-notes)
confirm its last battlefield power governs targets. Six tests cover casting and
life events, modified LKI/subtype/owner filters, copied-source successor
exclusion, negative power, target removal, exact later-incarnation distinction,
replay and stale-choice rejection. Kernel schema is 73; state remains 11.
Coverage is 193/334 unique cards and 258/400 copies, leaving 141 unauthored.
Production and real-game commit gates remain closed.

## Counter-event damage composition: 194 authored cards

All Will Be One composes its printed 3RR enchantment cost with existing
counter-placement actor attribution, per-recipient event amounts and mixed
opponent player/creature/planeswalker targets. No engine branch or schema change
was needed. Seven tests cover printed casting, placing counters on opposing
objects versus opponents placing counters on owned objects, player/zero
placements, target union and planeswalker damage, multi-kind proliferate
aggregation, replacement/entry counts, copied controller context, departed
sources, target control rechecks and replay. Kernel remains 73; state remains 11.
Coverage is 194/334 unique cards and 259/400 copies, leaving 140 unauthored.
Production and real-game commit gates remain closed.

## Counter replacement and cycling composition: 195 authored cards

Ozolith, the Shattered Spire composes its printed 1G legendary artifact with
controlled artifact/creature union counter replacement, sorcery-only 1G/tap
counter placement and hand-zone cycling 2. No engine branch or schema change
was needed. Six tests cover printed casting/self targeting, one replacement for
a dual-type recipient, exclusions, sorcery timing and atomic illegal targets,
cycling discard-before-draw and replay, control-change rechecking, copied
controller context and inactive hand-zone replacement behavior. Kernel remains
73; state remains 11. Coverage is 195/334 unique cards and 260/400 copies,
leaving 139 unauthored. Production and real-game commit gates remain closed.

## Battlefield-entry X and signed P/T scaling: 196 authored cards

Battlefield-entry events retain EventX from the prior stack object, or zero when
entry is from another zone. Self and external entry observers receive the same
value without preserving obsolete X on a reanimated permanent. ScaledValue
permits negative factors only in temporary P/T expressions or numeric bounds;
ordinary mana, damage and life quantities retain their nonnegative validation.
Existing temporary-change grouping evaluates shared expressions once.

The Meathook Massacre composes printed XBB legendary enchantment casting, entry
-X/-X until end of turn, and controller-relative creature death triggers. Seven
tests cover casting, simultaneous deaths and life changes, cleanup, source
departure/replay, reanimation, simultaneous animated source death, external
entry observers, copied abilities/controller context and validation. Kernel
schema is 74; state remains 11. Coverage is 196/334 unique cards and 261/400
copies, leaving 138 unauthored. Production/real-game commit gates remain closed.

## Additive life-gain replacement: 197 authored cards

LifeGainReplacement declares an additive increase for a source's controller,
opponents or all players. Supported additions commute; multiplication, prevention
and replacement side effects remain separate gates. A state-versioned cache
computes per-player totals once for unchanged state. Ordinary GainLife and
lifelink use the same calculation, excluding zero gains and phased sources.
Lifelink bonuses are aggregated once per source event and passed into the atomic
damage transaction; split damage does not multiply the bonus, and life is never
updated in a separate post-damage operation. Event amounts report actual gains.

Angel of Vitality composes printed 2W flying 2/2 characteristics, a 25-life self
P/T condition and additive gain replacement. Eight tests cover casting/threshold,
zero/opponent gains, multiple sources, split and simultaneous lifelink events,
atomic damage/life totals, copy/control/phasing, checkpoint/replay and malformed
input rejection. Kernel schema is 75; state remains 11. Coverage is 197/334
unique cards and 262/400 copies, leaving 137 unauthored. Production and real-game
commit gates remain closed.

## Counter placer filters and rounded transforms: 198 authored cards

CounterReplacement gains an actor relation and positive divisor, applying its
multiply/add expression then rounding division down separately per counter kind.
Placement effects use their captured controller; entry counters use the entering
permanent's controller. Both paths share transformation and actor matching.
Identical/disjoint rounded transforms can elide ordering; other rounded pairs
retain affected-player choice instead of inferring commutation from one value.

Vorinclex, Monstrous Raider composes printed 4GG legendary 6/6 haste/trample with
controller-placement doubling and opponent-placement halving for permanents and
players. Seven tests cover casting, placer/recipient distinction, per-kind
rounding/zero results, opposing replacement order and atomic checkpoints, entry
counters, copies/phasing and validation/commutation. Kernel schema is 76; state
remains 11. Coverage is 198/334 unique cards and 263/400 copies, leaving 136
unauthored. Production and real-game commit gates remain closed.

## Gate-count animation and tap-cost composition: 199 authored cards

Sage of the Maze composes printed 2G 1/3 Elf Wizard characteristics, 15 distinct
two-color mana bundles, sorcery-only tap animation using twice the controlled
Gate count, and a Gate tap cost to untap itself. The animation captures its value
at resolution, preserves land types, adds Citizen/haste and expires at cleanup.
No engine or schema change was needed. Six tests cover casting/readiness, mana
bundles, current count/captured duration, replay/cleanup, a fresh Gate creature
paid without a tap-symbol restriction, invalid costs/targets/timing and zero-Gate
state-based death. Kernel remains 76; state remains 11. Coverage is 199/334
unique cards and 264/400 copies, leaving 135 unauthored. Production and real-game
commit gates remain closed.

## Whole-card Starfield composition: 200 authored cards

Starfield of Nyx now has a catalog-bound full printed program, using existing
controller-upkeep targeting, optional graveyard return and continuous layers.
The threshold counts all controlled enchantments; animation excludes the source
and Auras and sets base power/toughness to each recipient’s mana value.
Six added scenarios verify paid casting, threshold changes and counters,
controller/phase exclusions, optional return and target invalidation, actor
replay and duplicate rejection, nontargeted Aura entry onto a hexproof creature,
two Starfields and copied-program controller semantics. No card-name runtime
branch or schema change was needed.

Coverage is 200/334 unique cards and 265/400 deck copies, leaving 134 unauthored.
Only Uro and Animate Dead remain fixture-only; original Starfield fixtures are
retained as historical interaction tests. Production admission remains blocked.
The last user-requested local backup is commit 4582512 on
`backup/rules-migration-20260910-200-wip`; main remains unchanged.

## Bounded top-card selection: 201 authored cards

`ChooseFromTop` inspects only a fixed top-library window, optionally reveals it
to all players, and offers one optional filtered multiselection. Chosen cards
move to hand; the remaining inspected cards move to graveyard. This is not
a library search, so neither unseen cards nor search permissions are exposed.
The original observation, selected references and completed hand-movement stage
are retained across destination replacements and checkpoints. Public observations
include the library owner; private looks remain actor-bound. No shuffle occurs.

Satyr Wayfinder composes this primitive with the ordinary inherited ETB trigger.
Seven scenarios cover paid casting and exact window boundaries, private and
public observations, multiselection, empty/short/no-match/declined choices,
selected and remaining destination replacements, copied-controller behavior,
codec validation, mana-ability classification and exact replay/duplicate rejection.
This bounded primitive currently moves selections to hand and the rest to
graveyard; battlefield placement and random bottom ordering remain separate work.
Kernel checkpoint schema is 77; state remains 11. Authored coverage is 201/334
unique cards and 266/400 copies, leaving 133 unauthored. Production admission
and real-game initialization remain blocked.

## Top-card battlefield placement and random bottom ordering: 202 cards

The same `ChooseFromTop` instruction now supports hand or battlefield placement,
optional tapped entry, and either graveyard or random-bottom remainder handling.
Elvish Rejuvenator uses private top-five inspection and the new destination pair.
Entry replacements finish before remainder randomization. The shared state
randomization helper uses the existing deterministic rejection-sampled shuffle
algorithm; subset placement preserves unseen order, retires only randomized
inspection references, and emits no zone-change or library-shuffle event.

Four additional tests verify paid casting and unseen-prefix preservation, private
observation, entry replacement checkpoints and actor replay, randomization across
seeds, atomic invalid-subset rejection and unsupported program-field rejection.
Kernel is 78; state remains 11. Coverage is 202/334 unique cards and 267/400
copies, with 132 unauthored. Production admission remains blocked.

## Split search destinations: 203 authored cards

`SearchLibrary` now supports an ordered partition into hand and battlefield
groups, with independent tapped-entry flags. One multiselection assigns both
groups. Shared movement proposals resolve all replacement and entry choices
before committing the heterogeneous zone batch, followed by one shuffle.
No destination group is replayed or reassigned when a replacement redirects
another group. Existing whole-group and library-top searches retain defaults.

Cultivate composes a two-card optional basic-land search, public reveal, first
card to battlefield tapped, and second to hand. Six scenarios verify printed
casting, zero/one/two finds, primary and secondary replacement checkpoints,
actor replay and duplicate rejection, simultaneous batches, reverse partitions
and malformed-field rejection. Kernel is 79; state remains 11. Coverage is
203/334 unique cards and 268/400 copies, leaving 131 unauthored. Production
admission and real-game initialization remain blocked.

## Bound damage sources: 204 authored cards

`Damage` can now take its dealing objects from a bound subject, add controller,
opponent or all-player recipients, and exclude each dealing object from its own
recipients. Objects and players share one deduplicated damage batch. The existing
damage pipeline supplies current or last-known source characteristics, control,
lifelink and deathtouch; card programs do not duplicate those rules.

Chandra’s Ignition uses its controlled creature target as dealer, reads current
power, and selects all creatures plus opponents while excluding that dealer.
Six scenarios cover printed casting, attribution, source exclusion, lifelink and
deathtouch, one additive life replacement for the simultaneous gain, power
changes, target invalidation, actor replay, departed bound sources, zero/negative
power and malformed bindings. Kernel is 80; state remains 11. Coverage is
204/334 unique cards and 269/400 copies, leaving 130 unauthored. Production
admission remains blocked.

## Waiting spell retirement on ordinary zone movement

A shared stack audit found that ordinary `Move` instructions could move a waiting
spell out of the stack without retiring its queued resolution frame. Only the
`Counter` path explicitly removed those frames. The central zone-batch commit now
retires waiting spell frames for exact references that actually leave the stack.
Pending replacement choices retain the frame until movement commits. This is
not a counter event, and independent abilities survive their source’s departure.
An already resolving spell continues its remaining instructions when it moves.

Five regressions cover exile/hand/graveyard moves, replacement-choice actor replay,
independent abilities, mass stack exile, and a resolving spell that exiles itself
before a later effect. Kernel checkpoint schema is 81; state remains 11. Authored
coverage remains 204/334; production admission and real-game initialization remain
blocked. This is a general correctness repair before further stack mechanics.

## Waiting ability countering: 205 authored cards

`CounterAbilities` removes waiting activated and triggered stack frames within
a controller, opponent or all-player domain. It uses captured frame controllers,
leaves resolving frames intact and does not remove triggers awaiting placement.
Summary Dismissal composes this instruction with ordinary other-spell exile;
spell exile emits no spell-counter event. No card-name runtime branch is added.

Six regressions cover paid casting with mixed spells and abilities, newly triggered
abilities after exile, source control changes, opponent-only filtering, exact
actor replay after destination replacement, resolving-ability continuation and
malformed domains. Kernel is 82; state remains 11. Authored coverage is 205/334
unique cards and 270/400 copies, leaving 129 unauthored. Production admission
and real-game initialization remain blocked.

## Numeric blocking restrictions: 206 authored cards

`BlockRestriction` combines attacker and blocker selectors with a current blocker
statistic, comparison operator and source-bound threshold. Combat menus and
declaration validation use the same evaluator. Rules and thresholds are collected
lazily once per combat view, avoiding repeated battlefield scans for each pair.
Copied definitions, source control changes and phasing use the existing object
and characteristic model. Signed power comparisons retain negative values.

Champion of Lambholt combines that restriction with the existing other-controlled
creature entry-counter trigger. Six scenarios cover printed casting/self-entry
exclusion, counter-driven thresholds, strict and negative comparisons, phasing,
control changes, copied rules and replay, atomic illegal-block rejection and
validation. Kernel is 83; state remains 11. Coverage is 206/334 unique cards
and 271/400 copies, leaving 128 unauthored. Production admission remains blocked.

## Blocking restriction interaction and cost audit

Four additional regressions verify that restrictions are checked at declaration
without retroactively removing established blocks, that multiple sources combine
with flying/reach, and that filtered toughness comparisons work independently of
Champion’s power rule. A measured call-count assertion verifies that four blocker
pairs evaluate the source threshold only once within a combat view. All ten
blocking-restriction tests pass without another engine change. Coverage remains
206/334; kernel remains 83 and state 11. Production admission remains blocked.

## Layer-six activated ability grants: 207 authored cards

`AddActivated` grants a validated battlefield activation through the shared
continuous-effect layer. The recipient supplies the ability source, costs and
controller. Exact granting-source/effect identities distinguish multiple grants
and are exposed in actor packets; optimized and exhaustive evaluation agree.
Derived grants are not copiable printed values. Last-known characteristics encode
them explicitly for checkpoint recovery. Temporary grants and arbitrary ability
removal remain separate work.

Chromatic Lantern combines a native tap-for-any-color ability with the same
activation granted to controlled lands. Seven tests cover printed casting and
recipient costs, intrinsic land abilities, copied granters, multiple sources,
phasing/control, granter departure after activation, actor replay and projections,
copy exclusions, last-known serialization, summoning sickness, compiler guards
and optimized/exhaustive identity parity. Kernel is 84; state remains 11.
Coverage is 207/334 unique cards and 272/400 copies, with 127 unauthored.
Production admission and real-game initialization remain blocked.

## Public successor effect bindings: 208 authored cards

The existing exact public source-successor record is now available as an effect
binding for self-observing battlefield-to-public-zone triggers. Validation rejects
hidden destinations and events that cannot guarantee that binding. Effects retain
the exact successor incarnation and never follow a later return to that zone.

Fallen Ideal combines Aura targeting, attached flying and a granted sacrifice-to-
pump activation with a successor-bound graveyard-to-owner-hand return. Seven
scenarios verify printed casting, recipient-controlled costs, temporary pumping,
sacrificing the host, exact return/replay, stale successor rejection, stolen Aura
ownership, compiler guards and a copied Aura returning its underlying card.
Kernel is 85; state remains 11. Coverage is 208/334 unique cards and 273/400
copies, leaving 126 unauthored. Production admission remains blocked.


## Shared split-search composition: 209 authored cards

Kodama's Reach reuses the existing optional basic-land search and ordered
battlefield-tapped/hand partition, preserving its Arcane subtype. No interpreter
branch or schema change is needed. Both printed spells now exercise the same
behavioral tests: zero/one/two finds, one shuffle, public reveal and private
search, simultaneous placement, destination replacements, checkpoint recovery
and duplicate rejection. An additional check preserves Arcane characteristics
and rejects casting on another player's turn.

Coverage is 209/334 unique cards and 274/400 copies, leaving 125 unauthored.
Kernel remains 85 and state remains 11. Production admission remains blocked;
this does not satisfy the real-test-game condition for committing to main.


## Shared tap transition triggers: 210 authored cards

`becomes_tapped` observes actual untapped-to-tapped transitions from effects,
activation payments and attack declarations. Entering tapped, remaining tapped,
untapping and phasing do not publish that event (pinned CR 603.2e). Observers use
effective copied programs, captured controller identity and optional type/control
filters. `event_subject` retains the exact observed incarnation for effects.

City of Brass composes a five-color mana choice with a separate one-damage
trigger. Its mana ability finishes before the damage trigger uses the stack.
Tap-and-sacrifice payments retain the predeparture observer, while pending
replacement choices publish no tap or trigger before payment commits. Recovery
and accepted-command rejection preserve that boundary. Animated attacking
sources trigger when tapped; vigilance avoids that tap.

Bundles without tap-trigger subscriptions skip battlefield capture. Type/layer
evaluation is deferred until a matching trigger actually needs it. This is not
an implementation of untap triggers, arbitrary cost ordering, or triggered mana
abilities. Existing production gates remain in force.

Kernel checkpoint schema is 86; state remains 11. Coverage is 210/334 unique
cards and 275/400 copies, leaving 124 unauthored. The stopped legacy game remains
untouched and the authorized fresh cohort remains uninitialized.


## Death-counter predicates and movement entry counters: 211 authored cards

Zone-event patterns now share counter-range matching with ordinary selectors.
Deaths inspect the complete predeparture counter state; entry events inspect the
actual resulting counters. `Move.counters` supplies counters as part of entry,
through the existing replacement and simultaneous-movement pipeline, before ETB
observation and state-based actions. Other destinations reject entry counters.

Glen Elendra Archmage composes these primitives with exact public successor
bindings for persist, plus its printed flying body and sacrifice/counter-spell
activation. The persist condition concerns a fixed historical death fact; its
truth cannot change while the trigger waits. It does not read counters from a
new graveyard incarnation or bypass dynamic intervening conditions generally.
A copied Archmage returns as its underlying card under its owner's control.
Leaving the graveyard invalidates the old trigger's exact successor reference.

The regressions include repeated paid activations, graveyard replacements,
pending return replacement recovery and duplicate rejection, counter-doubling
entry replacements, ETB counter predicates, and simultaneous death/counter
cancellation. The latter follows the pinned rules and
[official persist notes](https://magic.wizards.com/en/news/feature/lorwyn-eclipsed-release-notes).
These additions do not implement general ability grants of persist or certify
production readiness.

Kernel checkpoint schema is 87; state remains 11. Coverage is 211/334 unique
cards and 276/400 copies, leaving 123 unauthored. The main-commit condition still
requires a stable production build and a successful real test game.


## Indexed trigger discovery

Each immutable effective definition now has an event-kind index preserving its
printed ability order. Player events, announcements/combat events, counters,
zone changes, steps and tap transitions query that index before applying their
existing filters. Copies use the effective definition on each lookup; phasing,
controller identity, LKI and APNAP placement retain their existing semantics.
The derived index is rebuilt at construction/recovery and is not checkpoint data.
Kernel schema remains 87; authored coverage remains 211/334 (276/400 copies).

`rules_trigger_benchmark` compares the indexed path against the same collectors
with definition-wide scanning restored. It requires identical complete kernel
snapshots for every sample, and alternates measurement order. The synthetic
120-permanent cases include an event with no listeners and sparse upkeep
listeners. Construction, inference, transport and live gameplay are excluded;
these measurements do not explain or quantify the old host's queue stalls.
Results are retained in `reports/rules-primitives-trigger-performance.json`.

Six focused tests cover all authored definitions, immutable indexing, every
collector family, copies/control/phasing, checkpoint continuation and benchmark
parity. The existing full rules suite remains the regression gate. Production
migration and the real-test-game condition for a main commit remain unfinished.


## Shared dynamic activation reductions: 212 authored cards

Activated programs now use the same generic-reduction quantity calculation as
casting specifications. Reduction applies to the announced generic/X cost,
floors at zero and leaves colored/colorless symbols unchanged. Revision-bound
quotes are revalidated before acceptance, and the existing announcement/payment
transaction retains the locked total through replacement choices. Spell-only
static cost modifiers remain spell-only.

Otawara, Soaring City composes the printed legendary land and U mana activation
with hand-zone channel, source-discard payment, a four-type battlefield target
union and a reduction counting controlled legendary creatures. The count uses
current derived types, control and phasing. The discarded card's ability remains
on the stack, and target departure does not refund the cost.

Eight tests cover zero/one/many reducers, colored costs, stale quotes, animated
legendary lands, target/zone checks, pending discard replacement recovery,
duplicate rejection, target departure, X reductions and sacrificing a counted
permanent as part of the locked payment. No card-name execution branch was added.

Kernel schema is 88; state remains 11. Coverage is 212/334 unique cards and
277/400 copies, leaving 122 unauthored. Production migration and the successful
real-test-game requirement for a main commit remain unfinished.


## Combat target domains and surviving blockers: 213 authored cards

Target specifications now support attacking, blocking, and attacking-or-blocking
battlefield domains. Announcement checks, trigger menus and resolution all use
the same pure membership query. It checks current exact references, controller
history, phasing, creature status and removal-from-combat history without pruning
records or changing the revision during inspection. Targeting restrictions such
as hexproof/shroud continue to apply independently.

The audit found and repaired a combat-pruning defect: removing an attacker also
removed its surviving blockers. CR 509.1g/510.1d retain those creatures as blocking
until they leave combat or combat ends; they assign no damage without a surviving
attacker. Block groups retain the historical attacker key to preserve membership.
Such a blocker can still qualify for a first-strike damage step. Existing damage
assignment only iterates surviving attackers and therefore produces no orphaned
blocker damage.

Eiganjo, Seat of the Empire composes the printed legendary land, W mana ability,
hand-zone channel/discard, legendary-creature cost reduction and four damage to
a combat-constrained target. Nine tests exercise these paths, including pure
inspection, orphaned blockers, first strike, control changes, phase-out target
invalidation, end-of-combat lifetime, trigger menus and replay.

Kernel schema is 89; state remains 11. Coverage is 213/334 unique cards and
278/400 copies, leaving 121 unauthored. Production admission and the real-test-game
condition for committing to main remain unmet; the legacy game stays stopped.


## Optional fallback branches and exact availability: 214 authored cards

`May` now accepts an `otherwise` instruction sequence and an optional selector
applied to an exact bound subject. An unavailable subject takes the fallback
without presenting an impossible optional branch. Both branches are validated
for bindings and target domains, included in immediate-effect classification,
and traversed for embedded token definitions. The availability guard is a
selector/exact-reference check, not a general instruction-legality evaluator;
counter prohibitions and other unsupported replacements remain production gates.

Angel of Invention composes its printed Angel Artificer body, three keywords,
controlled-other-creature anthem, and fabricate using these primitives. The
counter choice occurs on trigger resolution rather than entry; the fallback
creates two colorless 1/1 artifact creature Servos in one shared movement batch.
A departed/phased source cannot receive counters, and the old trigger cannot
follow a newly entered incarnation. Copied abilities retain the original trigger
controller even if control changes before resolution. These interactions follow
[the official fabricate notes](https://magic.wizards.com/en/news/feature/kaladesh-release-notes-2016-09-16)
and pinned CR 702.123.

Eight focused tests cover printed casting/anthem, both branches, exact-reference
availability, copied control, counter modifiers, token-entry replacement recovery,
duplicate rejection and recursive validation. Kernel schema is 90; state remains
11. Coverage is 214/334 unique cards and 279/400 copies, leaving 120 unauthored.
Production admission and the real-test-game condition for a main commit remain
unmet. The stopped legacy run is preserved.


## Library-boundary mana classification audit

The pinned August 2026 version of CR 605.1a explicitly excludes abilities whose
cost or effect moves cards to or from a library. This is a recent functional
change, documented in the
[official Hobbit update bulletin](https://magic.wizards.com/en/news/announcements/the-hobbit-update-bulletin).
The existing draw/mill restriction is therefore retained.

The audit repaired two classification gaps. Positive surveil can move cards out
of a library and must disqualify an otherwise mana-producing activation. Looking,
scrying, searching to the same library's top, or randomly bottoming an inspected
window without selecting any cards to leave the library do not cross that zone
boundary and must not be rejected solely as library operations. Supported zero
card draw/mill/surveil instructions likewise cannot move a card. Classification
uses possible movement from the instruction, not the current library's contents,
and does not account for ordinary external replacement effects. Immediate optional
fallbacks count; bodies of future delayed triggers do not.

Eight focused tests cover stack use, private choices, nonactive priority return,
replay, same-zone search/rearrangement, empty libraries, fallback/delayed effects,
and external replacement redirects. This does not enable mana abilities during
spell announcements or implement self-replacements/loyalty/library-moving costs.
Those remaining general rules and production gates are unchanged.

Kernel schema is 91; state remains 11. Coverage remains 214/334 unique cards and
279/400 copies. Production readiness and the real-test-game condition for a main
commit remain unmet.


## Source-type targeting restrictions: 215 authored cards

`TargetRestriction` now accepts an optional union of source card types. The
shared targeting query applies it at announcement, target choice and resolution,
using current characteristics or exact-reference last-known information when
the source has left its zone. Source characteristics are computed lazily once
per query only when a qualified restriction requires them. Controller checks
use the spell or ability controller, not the source's later controller. Ordinary
non-targeted selection is unaffected. Empty type filters retain existing behavior.

Elenda, Saint of Dusk composes hexproof from instants with this restriction,
printed casting/lifelink, and two independent continuous effects measured against
the current controller's starting life. Pinned CR 702.11d covers type-qualified
hexproof, including abilities from instant sources; the
[Foundations release notes](https://magic.wizards.com/en/news/feature/foundations-release-notes)
explain how life thresholds interact with marked and simultaneous damage.

Nine tests cover paid casting, both thresholds, controller changes, enemy instant
versus sorcery and own-spell targeting, departed source identity, copied source
last-known types, copied Elenda, phasing, simultaneous lifelink, lethal damage
after life loss, replay, pure queries and validation. General ability removal,
hexproof-ignoring permissions and keyword-quality queries remain unsupported
production gates; this does not claim those semantics are implemented.

Kernel schema is 92; state remains 11. Coverage is 215/334 unique cards and
280/400 copies, leaving 119 unauthored. The mechanics backlog has also been
filtered against current authored programs to remove stale completed entries.
Production admission and the real-test-game condition for committing to main
remain unmet. The stopped legacy game remains untouched.


## Tapped-mana production replacements: 216 authored cards

`TappedManaReplacement` supplies a shared multiplicative replacement for mana
produced by activating a permanent's mana ability with the tap symbol in its
cost. That provenance is retained through choices and zone-cost payment recovery.
All four production instructions and the fixed-mana fast path share one emission
method. Active replacements modify the chosen mana bundle once before the pool
and production event are written. Multiple supported multipliers commute, so no
meaningless ordering choice is introduced. Copies, control and phasing use current
battlefield sources; a replacement sacrificed as a cost no longer applies.

Mana Reflection composes its printed 4GG enchantment with a controller-scoped
multiplier of two. Pinned CR 106.12 and 106.12b define the supported event. An
activation that merely taps a selected permanent without the tap symbol is not
a qualifying event. Nor is a non-mana ability that produces mana while moving
a library card under August 2026 CR 605.1a. Independent triggered abilities and
scenario mana additions do not inherit the activation's production provenance.

Ten tests cover fixed/mixed and variable bundles, color and commander choices,
native and granted land abilities, printed casting, multiplicative copied
replacements, control/phasing, absent tap symbols, stack-using library abilities,
sacrificed sources/replacements, independent triggers, zero output, validation,
pending cost recovery and duplicate rejection. This does not implement restricted
mana, mana abilities during announcement/resolution payment windows, triggered
mana-ability scheduling, or other noncommuting mana replacement categories.
Those remain explicit general production gates.

Kernel schema is 93; state remains 11. Coverage is 216/334 unique cards and
281/400 copies, leaving 118 unauthored. Production admission and the successful
real-test-game condition for committing to main remain unmet; the legacy run
remains stopped at its accepted prefix.


## Static zero-quantity mana classification audit

The shared classifier now distinguishes provably zero numeric formulas from
state-bound values that happen to be zero on the current board. Constant amounts,
scaling and explicitly rounded division are folded only for classification;
validation still visits every operand, and execution retains normal binding
checks. An activation whose only mana instruction always produces zero cannot
qualify under CR 605.1a. A variable amount remains eligible even on a board where
it produces nothing, as required by CR 605.2. Another positive immediate branch
can still qualify it; future delayed bodies do not.

The same analysis recognizes zero draw/mill formulas as incapable of crossing
the library boundary. Dynamic draw/mill amounts and positive rounded amounts
remain disqualifying under the pinned August 2026 rule. Surveil retains its
existing constant-integer vocabulary; this audit does not broaden it.

Six new tests cover stack versus immediate effects, rounded constants, zero
scaling, dynamic empty-board values, library boundaries, optional/delayed branches,
unbound operands and choice replay. The previous zero-mana modifier test now
correctly uses a non-mana activation. No card gains authored status from this
audit: coverage remains 216/334 unique cards and 281/400 copies.
Kernel schema is 94; state remains 11. Production admission remains blocked,
and the legacy game stays stopped.


## Actor-relative events and captured triggering players

The existing event relation vocabulary now also supports spell casts, activated
abilities, life gain, card draws, library searches/shuffles and scry/surveil.
For these events, `controlled` means the event player is the observer's controller;
`opponent_controlled` means another player. One shared predicate preserves the
existing `controller_only` behavior and rejects contradictory filters. Zone and
counter event relations retain their existing meanings. Other event kinds remain
closed to these new relation filters until explicitly implemented.

Each supported event captures its player in the existing `event_controllers`
value. Later instructions can address that exact player even after control of
the observer changes. Existing life amounts and announced X are retained alongside
that identity. This supplies common prerequisites for opponent-cast and opponent-
draw cards without inventing card-specific trigger branches. It does not implement
the optional payments, changeling or other remaining mechanics of those cards.

Six tests cover every supported kind/relation across three players, paid casts
and real activations, own/opponent filtering, per-card draws, copied/phased
observers, event amount/X binding, changed control, replay and invalid/unbound
forms. Kernel schema is 95; state remains 11. Coverage remains 216/334 authored
unique cards and 281/400 copies. Production readiness is still blocked, and
the stopped legacy run is preserved.


## All-creature-type characteristics: 217 authored cards

`CardProgram.all_creature_types` represents an all-zone characteristic-defining
ability. The complete 324-type vocabulary is copied from pinned CR 205.3m and
included in the implementation identity. Its exact sorted digest is checked by
a regression test. It includes Time Lord as one type and excludes land, artifact
and other noncreature subtypes. A printed Shapeshifter subtype alone does not
activate this characteristic. Copies use the copied definition; a departed copy
reverts to the physical card's printed characteristics.

Shared type changes now remove creature subtypes when both Creature and Kindred
are absent after the change, and dependency detection accounts for subtype reads.
Actor projections use an explicit `all_creature_types: true` flag with only the
remaining noncreature subtypes in `subtypes`, preventing a 324-name expansion in
every board packet. The full derived set remains in the engine and checkpoint;
the compact representation is lossless against the pinned registry.

Taurean Mauler composes its printed 2R 2/2 body, all-creature-type characteristic,
opponent-cast event and optional +1/+1 counter. Seven tests cover every zone,
type inclusions/exclusions, paid casting, own/opponent triggers, optional decline,
source departure, control changes, copy inheritance, tribal anthems, type removal,
optimized/exhaustive layer parity, compact projection, validation and replay.
These interactions follow pinned CR 702.73a and the
[Lorwyn Eclipsed release notes](https://magic.wizards.com/en/news/feature/lorwyn-eclipsed-release-notes).
Ability removal, arbitrary subtype-setting effects and other remaining general
rules are still production gates.

Kernel schema is 96; state remains 11. Coverage is 217/334 unique cards and
282/400 copies, leaving 117 unauthored. Production admission and the successful
real-test-game condition for committing to main remain unmet. The stopped legacy
game remains preserved.


## Named subtype sets and Planar Nexus: 218 authored cards

The creature-only characteristic flag has been replaced by the shared immutable
`all_subtype_sets` tuple. Supported names currently select all creature types or
all nonbasic land types, with validation requiring a supporting printed card
type. Both categories can coexist on one definition. Pinned CR 205.3i supplies
the 12 current nonbasic land types, including Planet and Town. Apostrophes in
the pinned type lists are normalized to the catalog's ASCII spelling, including
Urza's, C'tan and Shi'ar; the creature-list digest test now checks that canonical
representation. The new subtype registry is bound into implementation identity.

Shared type changes remove land subtypes if Land is lost while preserving
creature types when their supporting card type remains. Dependency detection
tracks land-subtype reads. Additive basic land types still grant their ordinary
intrinsic mana abilities; the nonbasic set alone grants none. Taurean Mauler
uses the same named-set primitive and retains its compact actor projection.

Planar Nexus composes the nonbasic-land set, printed tap-for-colorless ability
and one-generic paid tap/color choice. Seven tests cover all zones, land play,
atomic cost failure, choice recovery/duplicate rejection, Urza mana requirements,
Locus counts, phasing, Gate library search, copy inheritance, category-specific
type removal, additive Forest and optimized/exhaustive layer parity. The seven
changeling regressions also pass with the generalized vocabulary. This follows
the [Modern Horizons 3 release notes](https://magic.wizards.com/en/news/feature/modern-horizons-3-release-notes)
and current pinned land-type list rather than the older reminder-text list.

Kernel schema is 97; state remains 11. Coverage is 218/334 unique cards and
283/400 copies, leaving 116 unauthored. General land-type setting/ability removal
and other remaining rules still block production admission. The real-test-game
condition for a main commit remains unmet; the legacy prefix is untouched.


## Named subtype sets in continuous and temporary effects

`AddSubtypes` now combines explicit names with supported named sets. Static and
temporary effects share validation of category compatibility, immutable inputs
and nonempty additions. The registry now also includes the complete land-type
set, allowing a single Land effect to grant basic and nonbasic types together.
Layer dependency analysis reads the expanded subtype set, so earlier effects
that require Gate correctly wait for later effects that grant all land types.
Expansion uses a bounded 128-entry immutable cache and is reused by all-zone
characteristics as well as continuous additions.

Five tests cover the continuous clauses needed by everything counters: marked
lands gain all land types, marked nonland creatures gain all creature types, and
marked land creatures receive only the land category. Effects apply across
controllers; source departure/phasing removes the grants but leaves counters.
Other tests cover intrinsic basic-land abilities, compact actor views, temporary
expiry/replay, validation and optimized/exhaustive layer parity with a subtype
dependency whose timestamps require reordering. These are explicitly bounded
fixtures, not a complete authored Omo program: its multi-domain targeting trigger
and other outstanding game rules remain to be migrated.

Kernel schema is 98; state remains 11. Coverage remains 218/334 authored cards
and 283/400 copies. Production admission remains blocked and the stopped legacy
game is preserved.


## Independent cardinalities in batched choices

`ChoiceRequest.group_bounds` optionally binds named groups to independent
minimum/maximum counts, in addition to overall bounds. Options must name a
declared group. Immutable, unique and feasible bounds are validated before
presentation; accepted indexes are checked against each group. Existing
one-per-group choices retain their existing path. Distinct clause options may
refer to the same physical object, while duplicate option indexes remain invalid.
Group capacity and validation count options in linear passes instead of rescanning
the whole menu for each group. Empty optional groups need no user prompt.

The kernel choice helper binds these constraints into serialized requests and
checkpoints. Six tests cover optional two-domain selection, arbitrary bounds,
global feasibility, duplicate/foreign submissions, same-object distinct clauses,
serialization, legacy choice decoding, malformed groups, kernel retention and
empty-group behavior. This is the choice-protocol prerequisite for grouped targets,
not a complete targeting implementation: target declaration, effect bindings and
per-clause resolution legality still need integration. Omo remains unauthored.

Kernel schema is 99; state remains 11. Coverage remains 218/334 authored cards
and 283/400 copies. Production admission remains closed and the stopped legacy
game remains preserved.


## Trigger target clauses

`TargetSpec.groups` now declares named, independent object-target clauses for
triggered abilities. One batched choice enforces each clause's bounds; required
empty clauses make the trigger unplaceable even when other clauses have excess
candidates. Optional empty clauses do not create a prompt. Menu counting and
selected-target partitioning use linear passes.

Stack frames preserve each clause and revalidate it separately at resolution.
A physical object may be selected once per clause, with different legality in
each clause. The aggregate `target` recipient list preserves multiplicity;
`target:<group_id>` addresses just one clause. Existing atomic counter placement
merges repeated placements before replacement effects and event discovery.
Object operations use unique physical recipients; named clauses are captured
into delayed-effect bindings after resolution legality has been checked.
An ability with no chosen targets resolves; one with chosen targets that all
become illegal does not resolve. This follows the separate target-instance rule
in CR 601.2c, triggered placement in 603.3d, and resolution in 608.2b.

Ten tests cover independent bounds, duplicate physical targets, partial and
complete illegality, optional empty clauses, required empty clauses, per-clause
effects, delayed binding retention, single movement for repeated physical targets,
actor-adapter replay, checkpoint continuation and closed validation.
This stage supports fixed-bound, nonrecursive, object-only trigger clauses.
Spell/activation announcements, player clauses, and controller grouping within
clauses remain explicitly rejected. Omo remains unauthored pending its complete
card composition and card-specific conformance tests; its printed target clauses
are documented in the [official MH3 release notes](https://magic.wizards.com/en/news/feature/modern-horizons-3-release-notes).

Kernel schema is 100; state remains 11. Coverage remains 218/334 authored cards
and 283/400 copies. Production admission remains closed; no game was started.


## Omo, Queen of Vesuva: 219 authored cards

Omo composes existing primitives without runtime changes: self-entry and attack
triggers share one counter-placement program and independent optional land and
creature target clauses. The printed hybrid casting cost and characteristics
are retained. Counter-selected static effects grant all land subtypes to lands
and all creature subtypes to nonland creatures, across all controllers. A land
creature gains land types but does not gain every creature type from Omo.

Six card-specific tests cover both hybrid payment colors, a real attack
declaration, optional empty selection, a land creature selected for both
clauses, copied-entry inheritance, source departure and return, phasing, actor
replay and compact creature-subtype presentation. Counters persist without Omo;
the subtype grants require an active source. The existing shared target tests
cover partial illegality, atomic repeated counter placement and delayed bindings.
The [official MH3 release notes](https://magic.wizards.com/en/news/feature/modern-horizons-3-release-notes)
provide the printed clauses; current subtype registries remain bound to the
pinned Comprehensive Rules rather than old reminder-text lists.

Kernel schema remains 100 and state remains 11. Coverage is 219/334 authored
cards and 284/400 copies, leaving 115 cards unauthored. No card is production
certified; production-host and general-rules gates remain open. The legacy
accepted prefix is preserved and no fresh simulation was launched.


## Shared devotion conditions and Xenagos: 220 authored cards

`DevotionCondition` counts matching mana symbols on controlled, unphased
battlefield permanents. Combined-color devotion counts a hybrid symbol once.
Derived characteristics retain copied mana symbols independently of an object's
current color, and last-known characteristics restore them immutably. Evaluation
stops once the required threshold is reached. Entry replacement lookahead
excludes incoming symbols; actual post-entry characteristics include them.
No supported continuous instruction changes mana costs, so the new predicate
introduces no selector/layer dependency on mutable types or colors.

Xenagos uses that predicate to remove its creature type below seven devotion,
while retaining printed indestructible. Its own beginning-of-combat trigger
uses the existing target selector and temporary effects: another controlled
creature gains haste and a nonnegative power/toughness bonus captured at resolution.
CR 107.1b makes that calculated bonus zero for a negative-power target; it
is not an instruction to double a characteristic.
Later power changes do not change that captured bonus, and cleanup expires it.

Nine tests cover hybrid counting, copied costs, color changes, control, phasing,
nonbattlefield exclusions, entry lookahead, paid casting, negative-power zero bonuses,
source departure, own/opponent combat, actor replay, last-known checkpoint
values and closed validation. The [Born of the Gods release notes](https://magic.wizards.com/en/news/feature/release-notes-2014-01-22)
confirm combined devotion's once-per-hybrid-symbol counting. The pinned CR
entry-replacement and post-entry observation rules remain separate.

Kernel schema is 101; state remains 11. Coverage is 220/334 authored cards and
285/400 copies, leaving 114 unauthored. No production certification or fresh
game launch is implied; the legacy accepted prefix remains preserved.


## Casting origins and Gravebreaker Lamia: 221 authored cards

`CastSpec.origin_zones` explicitly binds intrinsic casting permissions, defaulting
to hand and command zone. The bounded vocabulary additionally admits owned
cards in graveyard or exile when their program grants that permission. Command
zone casting still requires a commander. This does not implement flashback,
escape, external permissions, hidden exile cards, library casting, or alternative
costs. Existing authored cards keep their original hand/command permissions.

`CostModifier.origin_zones` independently filters the pre-stack source zone.
An empty tuple retains the previous unrestricted cost-modifier behavior.
Modifiers grant no casting permission, preserve the proposed stack selector,
combine generic adjustments before clamping, and never reduce colored costs.
Copied definitions, current control and phasing use the same shared path.

Gravebreaker Lamia now has its printed cost and lifelink, a self-entry library
search to graveyard followed by shuffling, and a controlled-spell generic
reduction restricted to graveyard origin. SearchLibrary's single-destination
vocabulary now includes graveyard using the existing move/replacement pipeline;
unrestricted searches remain mandatory when the library contains cards.

Eight tests cover origin permissions versus discounts, command/owner checks,
paid graveyard casting with replay and duplicate rejection, copied stacking
modifiers, generic clamping, colored payment, control/phasing quote invalidation,
Lamia's paid entry and mandatory search, empty libraries, actor-scoped inspection,
search checkpoints, and closed serialization/validation. Graveyard/exile casting
permission is exercised with explicit synthetic programs, not implicitly granted
to any existing card by Lamia.

Kernel schema is 102; state remains 11. Coverage is 221/334 authored cards and
286/400 copies, leaving 113 unauthored. Production admission remains closed;
no fresh game was initialized and the legacy accepted prefix is preserved.


## Optional turn-use limits and Terrasymbiosis: 222 authored cards

`AbilityProgram.optional_once_per_turn` implements a bounded optional-use policy:
one root May, no fallback, and no simultaneous trigger-count limit. Acceptance
consumes the turn allowance before executing its effects; declining and countering
the trigger do not. After acceptance, future occurrences are suppressed and
already pending instances skip the optional action. Nested optional instructions
in the accepted body are not accidentally limited again.

The shared ledger keys source incarnation, definition, ability and controller.
CR 603.2h tracks whether the source's controller has taken the action; a different
controller has a separate allowance, while control returning to a previous
controller retains that controller's used allowance. A new turn or a new source
incarnation starts fresh. The existing trigger-count limit retains its behavior.

Terrasymbiosis uses shared counter actor/recipient filters and captured actual
+1/+1 counter amounts to draw optionally. Simultaneous placements on multiple
creatures generate separate instances, with one accepted use rather than summing
all recipients into one draw. Eight tests cover decline/accept, simultaneous
instances, countering with a paid spell, turn/incarnation resets, controller
changes, event filters, pending/consumed replay, nested optional effects and
closed validation. No card-name runtime branch was added.

Kernel schema is 103; state remains 11. Coverage is 222/334 authored cards and
287/400 copies, leaving 112 unauthored. Production admission remains closed;
no fresh simulation was launched and the legacy accepted prefix is preserved.


## Bounded prospective-entry characteristic cache

Repeated replacement-order and trace changes now reuse prospective battlefield
characteristics. The cache keys the immutable original object, prospective
controller, copied definition, counters and tapped status. Any state sequence
change discards the prior epoch; an LRU bound retains at most 64 entries.
Material proposal changes still evaluate independently. Cached results are
immutable and excluded from checkpoints, so restoration starts with no cache.
The original evaluator remains available as the uncached reference path.

Seven tests verify evaluator call counts, material keys, state invalidation,
eviction, temporary-effect creation/cleanup, real replacement-choice replay,
checkpoint continuation and benchmark parity. A paired synthetic benchmark
compares 24 incoming objects over six passes on an 80-object battlefield,
alternates measurement order and checks every resulting characteristic plus
unchanged semantic snapshots. Its material-change case measures cache misses
rather than implying all entry work benefits. This is engine evaluation timing,
not a live-game or model-queue speed claim.

The entry-view benchmark is retained alongside the five previous benchmark
reports, increasing each package-verification evidence set to 21 artifacts.
Kernel schema remains 103 and state remains 11; the implementation identity
still fences source changes. Card coverage remains 222/334 and 287/400 copies.
Production admission remains closed and the legacy run remains paused.


## Origin prohibitions and Kunoros: 223 authored cards

Shared entry selectors prevent prohibited graveyard/exile cards from moving to
battlefield, preserving their incarnation and using their origin characteristics
before entry copy choices. Shared casting restrictions override explicit casting
permission from a prohibited origin. Active battlefield sources, including copies,
supply both restrictions; phasing disables them and simultaneous incoming sources
do not retroactively prohibit their own batch. Rejected entry does not interrupt
later instructions. Casting quotes remain pure and are revalidated on commit.

Kunoros uses these primitives for creature cards entering from graveyards and all
spells cast from graveyards, alongside vigilance, menace and lifelink. Official
[Theros Beyond Death release notes](https://magic.wizards.com/en/news/feature/theros-beyond-death-release-notes-2020-01-10)
confirm origin characteristics determine entry legality and casting after moving
to exile is permitted. Casting permission itself is a separate mechanism.

Focused checks cover copies, devotion creatures, partial simultaneous movement,
tokens, phasing, controllers, permissions, paid casting, replay and validation.
Kernel schema is 104; state remains 11. Coverage is 223/334 authored cards and
288/400 copies, leaving 111 unauthored. Production admission remains closed;
no real game has been started and the legacy accepted prefix remains paused.


## Copiable additive type exceptions and Copy Land: 224 authored cards

Entry copying now supports additive card-type exceptions as copiable values.
The immutable object and zone proposal retain those values separately from
ordinary continuous effects. Copies inherit the target's exception, entry
lookahead evaluates it, and leaving the battlefield resets it with the copy.
The bounded entry-view cache includes the exception in its material key.

Copy Land uses the shared optional land selector and Enchantment exception.
Copied entry triggers and intrinsic land mana abilities use the existing engine.
Declining preserves the printed enchantment. Tapped status, counters, token
status and ordinary continuous type changes are not copied.
[Official MH3 release notes](https://magic.wizards.com/en/news/feature/modern-horizons-3-release-notes)
provide the card-specific conformance reference. This slice adds card types;
it does not claim arbitrary name, color, ability or power/toughness copy exceptions.

Eight focused tests cover paid casting, inherited triggers and mana, declining,
copies of copies, noncopy changes, zone resets, actor/checkpoint replay, cache
separation and invalid definitions. Kernel schema is 105; state schema is 12.
Coverage is 224/334 authored cards, 289/400 copies, with 110 unauthored.
Production admission remains closed and the paused legacy game is unchanged.


## Attached-object departure and Angelic Destiny: 225 authored cards

Zone-event patterns now support the exact previously attached object as their
subject. Departure observers use pre-event attachments and characteristics.
Aura observers receive a narrow graveyard successor binding under CR 400.7f
and 603.6e: simultaneous movement qualifies, as does a later unattached-Aura
state-based action. A separate later destruction does not. Exile and later
incarnations cannot be followed. Pending tracking is serialized across choices
inside the resolving effect, before state-based actions run. Bundles without
attachment observers skip the extra tracking maps.

Angelic Destiny composes this with existing Aura targeting and continuous
+4/+4, flying, first strike and additive Angel subtype primitives. Its return
uses the Aura's owner even when another player controls it. Copied Auras inherit
the ability and return their underlying cards. The pinned Comprehensive Rules
and [Foundations release notes](https://magic.wizards.com/en/news/feature/foundations-release-notes)
provide conformance references.

Ten focused tests cover the paid Aura spell and bonuses, unrelated deaths,
non-graveyard departures, simultaneous deaths, separate destruction, exile,
later incarnations, stolen/copied Auras and replay before and after the Aura SBA.
Kernel schema is 106; state remains 12. Coverage is 225/334 authored cards and
290/400 copies, leaving 109 unauthored. Production admission remains closed;
the paused legacy prefix and main branch remain unchanged.


## Distinct-name search and player partitions: 226 authored cards

Shared library searches now support distinct-name groups and a separate
partition chooser, either the controller or exactly one targeted player.
The compiler requires a public reveal before another player partitions the
cards. The first choice remains an unordered, actor-private library search;
the second includes only the selected revealed cards. Search inspection ends
before partitioning. Both choices retain exact references through checkpoints.

Gifts Ungiven composes these fields with the existing optional search, reveal,
simultaneous placement and shuffle pipeline. When the entire found set must go
to the primary destination, no redundant model choice is generated. The
[official Double Masters 2022 release notes](https://magic.wizards.com/en/news/feature/double-masters-2022-release-notes-2022-06-24)
confirm that finding one or two cards forces them all into the graveyard.

Eight focused tests cover paid casting, duplicate-name and actor rejection,
zero/one/two-card forced partitions, visibility, replay at both choices,
controller partitions, destination replacement and closed validation. Kernel
schema is 107; state remains 12. Coverage is 226/334 authored cards and 291/400
copies, with 108 remaining. Production admission stays closed; the legacy game
remains paused and main is unchanged.
