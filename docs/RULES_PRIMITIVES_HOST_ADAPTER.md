# Primitive actor and replay adapter

This is an experimental adapter over `RulesKernel`, not a deployed host or an
admission certificate. `RulesActorAdapter.for_production` rejects while the
whole-pod and runtime gates remain incomplete. Existing games are untouched.

## Actor packets

The transport must select the actor from its registered seat binding; it must
never derive that identity from a submitted command. `packet(actor)` is a pure
read. It returns public zones, player totals, the actor's own hand, public combat,
stack and resolving-source summaries, and the current decision stage. A search
menu and full unordered search inspection appear only for the searching actor.
Scry supplies only the authorized top cards in a single ordered partition; it
does not grant whole-library inspection. Other seats receive only a waiting actor. A stale pending choice rejects.

Packets use an explicit allowlist. They contain no shuffle seed, ordered library,
other hand, checkpoint, effect tasks, private bindings, accepted answers, or
replay journal. Turn-draw frames omit their source identity. Private target
references are redacted in public stack summaries. A copied public source still
uses its known effective name. Current hand display is sorted rather than
carrying hand order; graveyard order remains intact.

Face-down objects, additional reveal/look permissions and actor-scoped historical
evidence need their own rule-bound visibility implementation before deployment.
These packets deliberately do not infer that inspecting a checkpoint is safe.

## Commands

`submit(authenticated_actor, command)` accepts one command at the current revision.
Every command has `kind` and `revision`; unexpected fields, including `actor`, are
rejected. Current command-specific fields are:

| Kind | Required fields |
| --- | --- |
| `answer` | `request_id`, integer `indexes` list |
| `pass` | None |
| `cast` | `action_id`, `source`, `targets`, `x_value`, `payment` |
| `activate` | Casting fields plus `ability_id` |
| `play_land` | `action_id`, `source` |
| `attack` | `attackers`: list of `{source, defender}` |
| `block` | `assignments`, matching the current blocker specification |
| `damage` | `assignments`, matching the current damage specification |

An object reference is `{card_id, incarnation}`. Payment has `mana` and `taps`,
with a symbol-to-count map and exact tap references. Optional `zone_costs` maps
cost IDs to exact selected references; implicit source costs require no selection
entry. One simultaneous activation zone-cost group is currently supported. A
replacement choice can leave an announced ability on the stack while resources
remain unpaid; priority stays closed. Packets include the public announcement
summary, with private selections restricted to their actor. Casting and activation quote
and revalidate internally in one submission, avoiding a required extra inference
round trip. Stale revisions, wrong seats, hidden sources/targets, invalid costs
and duplicate submissions fail before acceptance. The full approved-sequence
protocol is not yet bridged to this adapter.

Combat declaration/allocation specifications preserve the kernel's existing
batched choices. The adapter never chooses for a seat, advances during inspection,
or replays a partially accepted action as a capacity retry.

## Replay and failure handling

The internal archive contains the initial checkpoint and a hash-linked command
prefix, plus a final checkpoint digest. Each record binds actor, exact command,
before/after revision, newly emitted semantic/zone events and any accepted
execution failure. Prefix hashes use new events only. An indexed immutable event
tail avoids copying the entire zone-event history for every command. A complete
checkpoint is serialized at archive boundaries, not for every submitted command.

`replay(archive, definitions)` requires the same implementation and rules bundle,
re-executes the prefix without model calls, checks every record and verifies the
final checkpoint. This validates new-adapter replay; it does not establish
compatibility with legacy host records or a corrected implementation.

A failure after choice or action acceptance records the failing prefix and raises
`AcceptedTransitionError`. Subsequent dispatch stops and packets show
`engine_stopped`. Nothing rolls back. The durable wrapper below supplies experimental command persistence. The production
host must still bind it to lifecycle quarantine/sealing, authorized recovery,
actor-scoped history, planner/decision bindings and historical-runtime selection.
The archive is private engine evidence, never a pilot packet.

## Measurement

`python -m edh_gauntlet.rules_adapter_benchmark --repeats 7 --output PATH` measures
current actor packets and empty event-tail reads after 0, 1,000 and 10,000 synthetic
zone events. It excludes inference, live queue admission, durable persistence and
production replay throughput. `reports/rules-primitives-adapter-performance.json`
binds results to the loaded implementation; packet size should depend on current
visible state, not accumulated history.

Public spell and ability summaries include `chosen_x`, bound to that action rather
than inferred from its source card. Pending activation announcements expose the
announced value while keeping selected private cost details actor-scoped.

Player rows expose current public `permissions`: total land-play allowance,
maximum hand size (`null` means no maximum), and authorized land zones. The turn
summary includes `land_plays_used`. Graveyard land plays use the existing exact-ref,
revision-bound `play_land` command and retain ordinary ownership and timing checks.


Targets may use an exact card reference or `{"player":"SEAT"}`. Player references
are accepted only in `targets`; source and payment fields still require visible
card objects. The program's target domain, opponent/controller scope, count and
controller-group restrictions apply before payment and again during resolution.
Player targets are public in stack summaries. Individual draw replacement choices
remain private to the affected player even when another seat controls the spell.

Counter replacement choices belong to the affected recipient controller/player,
which may differ from the resolving agent. Battlefield card rows expose
`limited_triggers` when relevant, with each ability ID and its remaining uses this
turn. Counter transactions and consumed limits are included in private replay
archives; the actor packet still excludes the checkpoint and event history.


Entry counter ordering uses the existing `replacement_order` answer command.
Pending choices retain the pre-entry board; the accepted zone transition exposes
the final counters atomically. Private archives bind the replacement answers and
counter events. Kernel checkpoint schema 29 rejects earlier experimental formats;
actor packet and replay envelope schemas remain unchanged. Source-to-installed
replay covers a paused copied entry with multiple counter modifiers.


Fixed source counter costs are derived from the reviewed activation program;
`activate` still uses the same payment packet. Quotes and atomic commits validate
available counters. Private costs-paid receipts record source/kind/amount; the
public board reflects counters only after the payment commits. A replayed accepted
action cannot pay again. Kernel schema 29 also binds the extended cost program.


Public object rows include printed/copied `colors`. Fixed tokens use the same
object rows and visible references as other permanents. A pending token-entry
replacement shows the pre-creation board; the complete batch becomes visible only
on commit. Embedded token definitions are private checkpoint/replay dependencies,
not extra pilot context. Token replacement and ETB choices use existing answer
commands. Kernel schema 29 binds these definitions and the creation transaction.


Controller captures are lexical player-identity lists in private frames. They add
no pilot prompt or redundant board data. Recipient-owned token entry uses the same
replacement answers as ordinary entry; the recipient can differ from the
resolving actor. A paused entry after the original target leaves retains that
recipient through source-to-installed replay. Kernel schema 29 binds these scopes.


An existing `cast`/`activate` command's `x_value` also binds variable target counts.
Targets and exact payment remain a single accepted submission; partial target
illegality during resolution never changes paid X. Zone-result counts, controller
lists and after-move refs remain lexical private-frame data. Pending replacement
choices commit no partial move batch. Kernel schema 29 binds these result scopes and
variable target specifications; source-to-installed replay includes paid X and a
redirected result.

Cast-trigger stack summaries expose `event_x`, the value captured from the
announced spell. It is separate from the triggered frame's own `chosen_x`.
Schema 29 replay preserves this value after countering its spell; the installed
package proof compares the remaining life gain, draw, archive and actor packets.

Private kernel schema 29 records complete pre-departure characteristics by exact
incarnation. Public actor packets omit that index. The installed replay proof
retains a simultaneous departing modifier and counters through a pending death
trigger, comparing the complete continuation archive and both actor packets.

Schema 29 retains ordered library partitions across movement choices. Each actor
packet may include only that actor's latest `library_observation`: original
revision, observation ID and ordered looked-at cards. This historical record
survives later shuffles without asserting current order or granting permission
to act on hidden references. Complete observations remain in the private replay
archive. The installed proof resumes a paid surveil replacement and compares both
actor packets, including observation privacy. Broader production evidence and
reveal-permission semantics remain gated.

Kernel schema 29 retains temporary continuous effects with fixed recipient
incarnations, captured values and effect timestamps. The paid-X installed replay
proof continues through cleanup into the next turn and compares the complete
archive and both actor packets. Readiness obtains the actual schema constant from
the kernel rather than maintaining a separate version literal. Keyword-grant
projections expose derived keywords; ordinary object targeting applies current
hexproof/shroud permissions. Full ability-layer and production host gates remain.

Kernel schema 29 binds per-recipient temporary arithmetic. All values are
captured before effect installation; identical changes share one record while
retaining all exact recipient references. The installed replay proof preserves
different positive and negative doubled values and compares both actor packets.

Kernel schema 29 binds Equipment legality, detachment and no-op attachment
semantics. Equip uses the existing authenticated `activate` command with ordinary
source, target, cost and timing checks. Actor rows already expose attachment
references and derived bonuses. The installed proof compares a paid host switch
followed by host destruction, including unattached Equipment and both actor packets.

## Durable command wrapper

`DurableRulesAdapter.create(path, kernel, binding=..., checkpoint_interval=32)` creates a new
private SQLite journal without overwriting existing files. `open(path, definitions, binding=..., minimum_commit=...)`
verifies schema/runtime and hash chains, restores the last checkpoint and replays
only its bounded committed engine tail. Production construction remains rejected.
This component neither migrates game contracts nor invokes model conversations.

`submit(authenticated_actor, transport_request_id, command)` returns
`request_id`, `accepted_revision`, `duplicate`, a `commit` receipt and the current actor `packet`.
The receipt is durable before return. Reusing a request ID with identical actor
and command suppresses execution; conflicting input rejects. Acknowledging an old
request still delivers the current packet. Checkpoints occur periodically and on
accepted failures, while ordinary commits append only incremental records. An
accepted failure preserves its failed checkpoint and leaves dispatch stopped.

One connection owns its in-memory adapter; all mutation must go through the
wrapper. SQLite serializes writes, and stale instances reject once another writer
advances the committed head. Failed transactions close the instance. Reopen the
same database and retain the original request ID when resolving a lost reply or
uncertain commit. A process exit before commit has no durable receipt; after
commit recovery finds the receipt and does not execute the command a second time.
The transaction contains only deterministic in-process engine work, with no
external effects or pilot tools. Database files and replay archives must never be
sent to pilots. Recovery verifies all stored record hashes but executes at most
`checkpoint_interval - 1` tail commands; this still entails a history-sized scan
at open, not at each ordinary submission.

`python -m edh_gauntlet.rules_durable_benchmark --repeats 3 --commands 65 --output PATH`
measures local SQLite FULL/WAL commit and reopen costs. It compares checkpoint
intervals 1 and 32 and excludes inference, transport, campaign integration and
production-storage behavior. `reports/rules-primitives-durable-performance.json`
binds the measurements to the loaded implementation. Durable journal schema 2 is
separate from kernel checkpoint schema 76 and actor/replay schemas 1.

The live host still needs explicit integration, lifecycle and quarantine handling,
actor-scoped historical evidence, planner/decider bindings and historical runtime
selection. This wrapper is not a deployed production host or a readiness waiver.

Both creation and recovery require an explicit binding containing `cohort_id`,
`game_number`, `branch_id` and `contract_sha256`. The caller supplies the canonical
contract fingerprint; the wrapper does not infer identity from a path or validate
contract contents. The binding is hashed into genesis and checked before engine
restoration. Experimental schema-1 journals are rejected without migration.

A commit receipt contains `sequence` and `sha256`. The host must retain its
strongest known receipt outside the journal and supply it as `minimum_commit`
during recovery. Recovery checks that exact ancestor before restoring the engine:
an older valid backup or divergent prefix rejects, while a later committed head
can reconcile a lost reply. Without an external receipt, recovery cannot detect
replacement by an otherwise valid older journal. `committed_head()` returns the
current receipt; duplicate acknowledgments return the original command's receipt,
so callers must not replace a newer retained receipt with an older duplicate.
These fields are host control metadata and do not enter actor packets. This is
neither a global host lease nor integration with campaign lifecycle authority.


## Compound predicates and selected branches

Kernel schema 30 serializes `AllConditions`, `AnyConditions`, `NotCondition` and
both `IfCondition` branches. Only the selected branch is queued; a pending choice
inside it survives recovery without rechecking the original predicate. Intervening
trigger conditions retain their separate occurrence/resolution checks. Mana
classification and program validation inspect both branches even when the current
state would skip one. This format change does not adopt an existing game contract.


## Numeric filters and trigger timing

Kernel schema 31 carries inclusive `CharacteristicRange` bounds on selectors and
zone events. Trigger programs distinguish occurrence-only predicates from
intervening conditions. Stored pending triggers retain the authored distinction;
recovery does not turn an occurrence check into a resolution check. Numeric target
restrictions still revalidate against the current object and exact incarnation.
Old experimental checkpoints reject; started game contracts remain untouched.


## Variable costs

Kernel schema 32 binds a casting program's numeric generic reduction. Prepared
quotes store the resulting fixed cost and revision; a changed battlefield requires
a fresh quote before payment. Restoring a quote and checkpoint reproduces the
same payment. Printed mana value and colored requirements are unaffected.


## Additive subtype programs

Kernel schema 33 serializes static `AddSubtypes` operations. Restored derived land
types feed the same intrinsic mana ability enumeration and action quoting used by
ordinary basic lands. No separate host card-name routing is introduced. General
subtype replacement and ability removal remain production gates.

Kernel schema 34 adds shared milling. Private in-flight tasks retain the exact
selected top-card references across replacement choices; actor packets continue
to expose library counts rather than those task internals. Recovery resumes one
atomic zone batch without selecting a fresh set of cards. Milling has no new
production-host admission or gameplay authority.

Kernel schema 35 supports current-life conditions. Restored player life feeds
both conditional execution and derived characteristics, including entry lookahead.
No new actor visibility or production-host authority is introduced.

Kernel schema 36 and state schema 11 retain starting life per player. Public actor
player rows now include `starting_life` alongside `life`; checkpoints and replay
retain both, including synthetic games initialized with nonstandard totals.
Production game configuration and the preserved stopped host are unchanged.

Kernel schema 37 binds modal spell choices to paid quotes and resolution frames.
Actor `cast` commands may include `modes: [{mode_id, targets}]`; existing nonmodal
commands keep their shape. A modal cast supplies an empty flat `targets` list and
binds each selected mode's targets in its row. Target visibility is validated for
each row before quotation or payment. Stack/resolving summaries publish selected
mode IDs and their surviving targets. Mode choices survive nested choice pauses,
checkpoint recovery and replay without another model decision. This does not
add production admission, modal activations or spell-copy support.

Kernel schema 38 adds shared battlefield orientation selectors. Target legality
uses current tapped state at announcement and resolution; actor tap-state fields
and command shapes are unchanged.

Kernel schema 39 supports explicit live-player conditions. Departure-trigger
lookback uses the retained pre-event live set; restored current state supplies
subsequent conditions. Actor packet and command schemas remain unchanged.

Kernel schema 40 rejects invalid restored life and player-counter ledgers. The
state shape remains 11; zero counter additions do not create revision changes.
No live host or preserved accepted action is replayed by this audit.

Kernel schema 41 rejects malformed restored permanent counter rows and routes
direct positive counter additions through the shared batch mutation. Zero additions
do not advance state revisions. Production admission remains gated.

Kernel schema 42 binds explicit activation zones (battlefield, hand, graveyard).
The existing actor activation command and replay format remain unchanged; source
visibility is checked before quoting, followed by zone and controller/owner
permission checks. Hand source discard uses the existing suspended zone-cost
announcement and accepted receipt, so replacement prompts do not repay costs.

Kernel schema 43 binds recipient-type damage results and zero-loyalty state
actions. Existing object counter and damage fields carry the results through
actor packets and checkpoints. Battle defeat/transform and combat defenders
other than players remain gated; this is not complete planeswalker/battle support.

Kernel schema 44 skips obsolete or unavailable damage recipients within an
already resolving instruction sequence. Actor-command regressions exercise
planeswalker/battle counter damage and verify packet equality after replay.
No new actor command or production admission is introduced.

Kernel schema 45 binds counter-range selectors. Existing actor commands and
retained exact-object effect bindings are unchanged. Inspiring Call replay tests
verify private draws and public temporary abilities through the same adapter.

Kernel schema 46 serializes selected_count within the existing retained task
values. Selection prompts and actor commands are unchanged; suspended and nested
selection scopes preserve their own counts without querying a newer board.

Kernel schema 47 records aggregated permanent damage_received events and retains
their event_amount in trigger occurrences. Targets and optional resolution use
existing actor choices and checkpoint state; lethal source departure retains
the accepted occurrence. Production admission is unchanged.

Kernel schema 48 shares an event-local type lookup across announcement observers.
It introduces no retained cache, packet fields or command changes; departed-source
fallback and trigger occurrence ordering remain covered by regression tests.

Kernel schema 49 retains event_subject bindings and event_controllers on zone
trigger occurrences. Public stack summaries add event_controllers and
event_subjects through the existing per-actor target visibility filter. Exact
hidden-zone references stay private; regression tests compare owner/opponent
views and replay packets. Production admission remains closed.

Kernel schema 50 makes actual controller predicates distinct from ownership in
selectors and zone events. Pre-departure controllers remain captured; hand-card
owner identities are not mislabeled as controlling players. No actor command
shape or production contract changes.

Kernel schema 51 avoids state revisions for damage only to departed players and
zero commander-damage ledger rows in mixed batches. Validation still precedes
mutation; actor commands and state shape remain unchanged.

Kernel schema 52 accepts two-color hybrid symbols in cost declarations. Actor
payments still contain concrete produced mana colors; shared matching verifies
that payment covers fixed, hybrid and generic requirements. Suspended mana-choice
recovery retains the paid cost and does not require a new command shape.

Kernel schema 53 binds required/any/excluded color selector fields. Existing
actor payments and private library menus remain unchanged; reduced spell payment
and actor replay are covered by the Goblin Anarchomancer regressions.

Kernel schema 54 binds layer-5 color changes, temporary subtype additions and
activation minimum_x. Existing actor activation commands supply x_value; invalid
low values are rejected before payment. Animated characteristics and checkpoint
cleanup use the current actor projection and retained exact-incarnation effects.

Kernel schema 55 retains the defending player on each declared attack occurrence.
Actor stack summaries expose that public player identity; restored and replayed
triggers retain it independently of the attacker remaining on the battlefield.
This remains player-only combat; attack reassignment and planeswalker/battle
defenders are not implemented by this binding.

Kernel schema 56 excludes Battles from combat participation and preserves
immediate combat removal between state-mutating resolution instructions.

Kernel schema 57 supports library searches followed by shuffled top placement.
Selections are ordered for this destination; search_top observations retain
only the chosen top cards for the searching actor, using fresh post-shuffle
references. Explicit reveal events remain in the complete semantic record.

Kernel schema 58 binds optional tapped orientation to accepted entry-copy
replacements. It composes with copied entry modifiers in the same atomic
proposal; declining the copy does not impose its tapped orientation.

Kernel schema 59 uses accumulated entry orientation in hypothetical incoming
objects, so later replacement selectors observe prior tap/untap replacements.

Kernel schema 60 binds explicit top/bottom placement for cards moved into
libraries. Selected order reads top-to-bottom within each owner library;
redirected cards are excluded. Own-library placement retains a private
observation of the moved cards, with their resulting incarnation references.

Kernel schema 61 includes retained same-library references in explicit
top/bottom placement. Their identities stay unchanged; no new library access
permission is granted. Replacement choices retain the combined ordering.

Kernel schema 62 adds TargetStat quantities over distinct object targets in
the current target scope. Current characteristics or exact retained battlefield
last-known views supply power, toughness, mana value and color count. Missing
required last-known information fails closed. Existing snapshots retain those
views through pauses between instructions.

Kernel schema 63 permits destination-independent WithZoneResult follow-ups
using destination null. An operation must still produce a zone-change result;
indestructibility, stale references and same-zone no-ops do not qualify.

Kernel schema 64 retains last-known information from all supported public
zones, including stack X. Hidden-zone departures are excluded, and actor
packets do not receive the raw retained-information ledger.

Kernel schema 65 binds count-based characteristic P/T definitions. These
apply in layer 7a in every zone and use the effective copied definition.
Self-referential P/T count predicates remain rejected.

Kernel schema 66 suppresses P/T on noncreature permanents while preserving
dormant continuous effects and printed nonbattlefield statistics. Numeric
selector dependency checks include changes to Creature type.

Kernel schema 67 adds selectors to external entry-orientation declarations
and zone-result follow-ups. External orientation shares the entry-counter
source scan and affected-player replacement ordering; incoming sources cannot
provide their own general external replacement. Result filters use the
resulting object and its derived characteristics.


Kernel schema 68 adds zone-event type unions and exact source exclusion. These
filters share the existing event predicate and copied-definition trigger path;
other event families reject them until explicitly implemented. No production
routing or started-game contract changes accompany this authored-card addition.


Kernel schema 69 adds SourceCounter quantity nodes. Source-counter expressions
use exact-source current or retained object data through the existing information
lookup and survive sacrifice-payment and mana-choice checkpoints. This does not
change production routing or a started game's contract.


Kernel schema 70 allows shared quantity expressions in resolution-time Select
and SelectAll characteristic bounds. Announcement targets and continuous/event
selectors remain statically bounded. Actor/replay schemas and live host contracts
are unchanged; no production launch is implied by this authored-card addition.


Kernel schema 71 adds the optional signed flag to SourceStat. It is validated
only for numeric selection bounds and preserves exact-source last known values.
Default effect quantities, actor/replay schemas and started-game contracts retain
their existing behavior.


Kernel schema 72 extends target characteristic bounds to source/current-state
expressions through the same menu and resolution query path. Unbound X/result
expressions remain rejected. Actor/replay schemas and existing game contracts
are unchanged; production routing remains gated.


Kernel schema 73 retains exact public source successors in zone-trigger values
and carries them into target menus and resolution queries. Source exclusion
uses exact references; hidden successors are not retained through this mechanism.
Production routing and started-game contracts remain gated and unchanged.


Kernel schema 74 binds announced X into battlefield-entry event values and
admits signed scaling in temporary P/T and numeric bounds. Non-stack entries
bind zero. Production routing and started-game contracts are unchanged.


Kernel schema 75 adds additive life-gain replacement declarations. Ordinary and
lifelink gains share state-versioned replacement totals; adjusted lifelink gains
commit atomically with damage. No serialized state fields or live contracts change.
Broader life replacement/prevention and production admission remain gated.


Kernel schema 76 adds counter-placer relations and rounded counter transforms.
Ordinary placement and battlefield-entry replacements share actor matching and
numeric transformation. Rounded ordering remains explicit unless structurally
safe to elide; no production routing or started-game contract changes are made.
