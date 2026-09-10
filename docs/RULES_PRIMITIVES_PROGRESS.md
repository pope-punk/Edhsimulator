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
- `rules_admission.py`: deterministic production-readiness report and a rejecting production factory. Seven mapped interaction fixtures and 199 authored card programs are explicitly distinguished from production certification; no cards are production-certified by this experimental interpreter.
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

914 conformance/tooling tests cover identity, copied triggers, priorities, choices, replacements, Aura/delayed-trigger lifecycles, layers, turn actions and combat. New layer cases include:

- Starfield's changing threshold, Aura exclusion, two-Starfield interaction, and phased/opponent permanents.
- Setters, numeric modifiers, counters and switching; source timestamp changes; dependency ordering and cycles; and recipient retention across layers.
- Printed versus derived types for targeting, replacement effects and pre-event death observations.
- Entry look-ahead that does not count the incoming fifth enchantment before it enters, contrasted with animation already active before entry.
- Atomic batches of zero-toughness moves, opposing-counter cancellation and creature-Aura detachment.
- Checkpoint replay at timestamp choices, changed-implementation rejection, immutable views, and explicit rejection of missing creature statistics.

Six catalog card-text fingerprints are checked. These are bounded interaction checks, not general Magic certification. The full repository suite passes **1035 tests** and catalog/runtime-asset verification passes. CI runs every `test_rules_primitives*.py` file without inference calls or live gauntlet games. The isolated installed wheel passes all 914 primitive tests and asset verification. A source-created SQLite journal reopens under that wheel, replays its bounded committed tail, suppresses a duplicate request and commits the next command with matching actor packets and archive.


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
commit median is about 0.8 ms with periodic checkpoints; writing a checkpoint for
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
