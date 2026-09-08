# Reaminatour EDH Gauntlet — Manual Pilot / Rules Ledger Protocol

For fresh games explicitly binding `agent_architecture:1`, the role, component,
escalation and scheduling rules in [AGENT_ARCHITECTURE_V1.md](AGENT_ARCHITECTURE_V1.md)
supersede the single-planner instructions below. Sol owns strategic goals; static standing files serve fresh split games;
Terra-high owns continuity and tactical prose/actions; Terra-low owns decisions.
Fresh software hosts provide independent short-term, long-term and diplomacy
lanes, each admitting one seat at a time. Legacy serialized hosts retain their
existing slot binding until an explicit verified stopped-host upgrade. Optional
`async_diplomacy:1` routes authorized public conversation to Luna-low and removes
forced reply decisions. Neither binding changes existing games. Use the current host and fenced
stopped-host recovery for this architecture.


For planning contracts 2–4, SPLIT_RUNTIME_POLICY.md replaces the legacy
pilot-written/draw-triggered planning procedures below. Fresh three-tier games
use a planner-owned immutable standing reference, opening long-term goal, then
short-term prose and symbolic proposals. Only actual decisions belong to pilots.
HOST_AGENT_POLICY.md is the concise resident-role instruction source for bounded
context handling. Idle transcript checkpoints never rewind this referee, consume
priority, change snoozes, approve actions or satisfy a planning obligation.

This document governs in-game authority and timing. The complete campaign,
post-game review, learning, and advancement lifecycle is normatively defined in
`GAUNTLET_WORKFLOW.md`.

Revision-6 games use the appended scheduler and isolated pilot handoff described
at the start of `GAUNTLET_WORKFLOW.md`. That contract supersedes the legacy
numbered AUTOPASS/PASS ON and SNOOZE ALL controls below for new games. Each brief
states the seating cycle and distinguishes whose turn it is from who is making
the current decision. The coordinator never uses another pilot's private
rationale, hand or plan to make a seat's choice.

## Governing separation

The Python program is a **rules/state ledger**, not a strategic pilot.

There is no action chooser in the manual gauntlet architecture.

Python may only:
- deterministically realize shuffle/random outcomes once a seed is chosen;
- maintain ordered libraries and all zones;
- validate and pay mana;
- maintain card objects, counters, attachments, linked exile, copy identity and commander-zone replacement;
- when a commander enters a graveyard or exile, ask its owner whether to move it
  to the command zone as the state-based action; a linked-exile brief must say
  which objects remain in exile and which commanders moved away and will not return;
- resolve implemented mandatory rules primitives after choices have been supplied;
- perform combat arithmetic and state-based actions after attackers/blockers/targets have been supplied;
- log events, snapshots, invariants, metrics, and explicit manual state corrections.

The external pilot (ChatGPT) owns every material strategic choice:
- mulligans and London bottoms;
- land sequencing where more than one meaningful option exists;
- spell/ability sequencing and whether to pass or hold interaction;
- tutor/search/Gifts selections and opponent Gifts splits;
- targets, modes, optional triggers and copy/reanimation choices;
- removal, countermagic and protection timing;
- sacrifice/blink/exile routing choices;
- combat target, attackers and blocks;
- whether to attempt, stop, route through, protect or abandon a combo line;
- multiplayer threat assessment and political targeting; and
- the content, audience, and optional response to public table talk.

## Decision tape, not decision engine

Fresh revision-6 cohorts bind `combat_blocker_batch:2`. All attackers against
the current defender arrive in one `blockers_declaration` request with
`response_type:block_declaration`. The pilot's ordinary answer uses
`choice:{"ATTACKER_UID_A":["BLOCKER_UID_1","BLOCKER_UID_2"],"ATTACKER_UID_B":[]}`.
Every attacker must be named, with an explicit empty list for unblocked attackers.
One rationale and scheduler directive covers the entire defense. All assignments
validate before any group is recorded. Shared eligibility groups avoid repeating
identical legal-blocker lists; no attacker/blocker combinations are enumerated.
Menace requires zero or at least two blockers. Duplicate selections, unavailable
blockers and reuse across attackers are rejected or excluded. Blocking remains a
required pilot choice even though choosing no blockers is legal. Block triggers,
post-declaration priority and combat damage retain their existing boundaries.
This is an ordinary structured answer, not a main-phase plan-approval batch.
CLI callers pass the mapping as a quoted JSON choice; software-host callers may
pass the object directly. The accepted tape stores exact UIDs in `choice_value`.
Existing version-1 games retain one multi-select per attacker. Games without
either binding retain their original per-blocker sequence. Persisted game
bindings override later changes to the cohort configuration.

`DecisionTape` is deliberately dumb. It receives only a serialized decision
request and can do exactly one of two things:

1. replay an explicit pilot-authored record, including any validated pre-answer
   PASS ON controls followed by the final choice; or
2. raise `NeedDecision` and write the request to disk.

It receives **no `Game` object**, has no access to hidden future information, and contains no scoring, threat ranking, target priorities, policy weights, or fallback behavior.

The interactive console path is equally dumb: it displays the request and records the option number typed by the external pilot.

A material decision with no externally supplied answer must stop the run. The program must never infer, score, rank, randomize, or default that decision.

The pending-decision presentation must make timing explicit rather than relying
on the pilot to infer it from prose: round and turn, active player, acting pilot,
current phase/step, and the exact window or transition. It must also show the
actor-visible stack in top-first resolution order, including an explicit empty
state. The active player and the pilot currently receiving priority are distinct
facts and may name different players.

Every material decision request carries a compact reminder of the pilot's
out-of-band inspection capability. Inspection may be repeated while the request
remains pending and cannot consume the decision or priority. The reminder states
the complete object/card/deck/roles/role/package/messageboard grammar and that
multiple queries may be batched. Role queries accept optional `zone=ZONE`,
`mv<=N`, and `castable_now=true`; castability comes from the referee's current
legal decision surface. Unfiltered role results separate current actionable
zones from an explicitly unordered library outlook. Library inspection may
report remaining identities, counts, mana bands, package relationships, and
frozen pre-game learning, but never ordered future draws. Revised requests also
carry at most three matching private card notes in one canonical section.

Inspection uses the game's frozen strategy snapshot. Later learning never
changes a running game's role assignments, packages, or notes. Inspection
evidence is actor-private and content-addressed; the append-only audit stores a
compact hash reference and identity indexes, while post-game review can recover
the complete result. Repeating the same normalized query on one accepted branch
may reuse that exact stored result without consuming priority, a decision, or
RNG.

Every material request in a revision-2-or-later game automatically includes the acting
pilot's bounded `private_active_plan`. The campaign derives it deterministically
from the frozen seed snapshot plus branch-visible dynamic journal on every
request; it is not an independently mutable third source. The complete source
material remains available through GAMEPLAN. Revision-1 games retain the former
one-time opening behavior.

At every pending decision, the private `GAMEPLAN` auxiliary action can
explicitly query the acting pilot's seed plan and branch-visible journal. The
query result is transient: it is returned privately for that invocation and is
not persisted back into the ordinary request, status, or checkpoint. An
already-open main-action, upkeep-action, priority, or specialized response window
also permits appending a note and proactively suggests doing so when strategy has
changed; other decision types are review-only. This action remains outside the
legal option list and decision tape: it cannot create a prompt, pass priority,
change RNG or game state, or satisfy the pending decision. After it runs, the same
decision ID and legal options remain pending. Rewind/rebase removes only dynamic
gameplan entries authored with knowledge of a discarded future branch; the seed
snapshot is unchanged, and a rebase prompt is review-only until its replacement
choice is committed. A revision-2-or-later ordinary strategic answer outside a
mandatory planning checkpoint may also carry a
separate `--plan-delta`. Candidate gameplay replay must succeed before that
private journal entry is committed; its body never replaces or suppresses the
ordinary rationale recorded in game history.

Dynamic entries have either `short_term` or `long_term` scope. The immutable
Standing Plan describes reusable deck mechanics, win conditions, inspection
vocabulary, and piloting doctrine. Short-term is the backward-compatible default
and translates current status, inspections, and recent rationale into direct
sequencing, priority/trigger, target, combat, interaction, and hazard instructions.
Long-term describes the determinate current match objective, primary route,
posture toward each opponent, plausible alternatives, and observable pivot cues. Both remain in
the same branch-anchored private journal and are rendered as separate sections in
the active projection and full GAMEPLAN view.

For revision-2 replay compatibility, the first `main_action` decision in each
active pilot's precombat and postcombat main phase automatically includes that
pilot's complete frozen seed plan and a
mandatory private long-term-plan checkpoint. The gameplay answer is not accepted
until the pilot either appends a `long_term` GAMEPLAN entry without consuming the
decision, or attaches a long-term inline delta to the answer. The completion
entry is bound to that pilot/turn/phase and current replay branch; subsequent
main-action decisions in the same phase do not repeat the full seed. Rewind or
rebase pruning removes completions from discarded futures exactly like every
other dynamic note. This is a campaign-layer planning gate, not a new Magic
priority object or rules-engine decision.

Revision-3-or-later handoffs do not repeat prior decision bodies. Accepted choices
and rationales remain in the append-only decision journal for audit, while
Short-Term and Long-Term plan histories carry strategic continuity into the
bounded frontier packet. This avoids making raw transcript reconstruction compete
with the planning system and cannot alter the legal decision surface.

If that pending actor owns live passed-on objects, every serialized decision type
also exposes a private `MANAGE PASS-ONS` auxiliary action outside its legal option
list. A read-only review changes nothing. Explicit unsnooze and reschedule actions
do affect future prompting, so the campaign candidate-replays them before showing
the same decision ID again. They remain attached to the unanswered request and
are folded into its ordinary decision record when the pilot finally answers.
The tape supplies only the authored control data; `ManualGame` validates and
applies it without exposing the game object to `DecisionTape`.

## Forced bookkeeping

A choice may auto-resolve only when there is exactly one legal option and passing is not legal. Such events are logged as `forced_choice`.

Planning contract 4 separately permits **explicit pilot-approved choices** in one
batch under [APPROVED_SEQUENCES.md](APPROVED_SEQUENCES.md). These are ordinary
accepted decisions with adopted or overridden rationales, not `forced_choice`.
Python matches the approved symbolic choice to the current legal menu and stops
at the first interruption, missing prerequisite or unapproved choice. It never
selects an alternative, and the coordinator never approves plays for a seat.

If two materially different legal options exist, the game must request an external decision.

## Priority and timing

The manual game exposes APNAP priority at upkeep after triggers, the end of the draw step, the end of each main phase, beginning of combat, after attackers, after blockers, the end of combat, the end step, and while a spell or trigger is on the stack. Seats with no legal instant-speed action are skipped. A pass advances priority; taking an action clears all prior passes and priority circles again. In routine nonresponsive windows, an ordinary pass also debounces the same action until that player's material state changes. New spell, trigger, and combat-response windows may still ask again.

The same neutral action surface is used for every deck. Revision 2 relies on the
concrete legal actions plus on-demand card inspection; it neither generates nor
repeats the former full-Oracle `Priority notes` block. Legacy timing-affordance
storage remains only for revision-1 replay compatibility.

In revision 5, any priority prompt with action-bearing sources offers one `PASS ON
OBJECTS` choice. The same answer may schedule any nonempty subset of those exact
objects by repeating `--pass-on "OBJECT_UID=SCHEDULE"`; every entry is validated
before any is applied. This is objectwise rather than abilitywise: both abilities
of Sensei's Divining Top are covered together, while a card that changes zones is
a new object and loses the pass. Revision 1–4 games retain the single-source
`PASS ON` choice and its required typed follow-up. Both forms use the grammar
`N beginning|end of PHASE`.
`N` is an integer from `1` through `1,000,000`, and `1` means the next matching
pod-wide boundary from the moment the schedule is chosen. Supported phase/step names are `upkeep`, `draw`,
`precombat main`, `combat`, `postcombat main`, and `end step`.

The object is suppressed by default until that boundary count arrives. A
beginning boundary wakes it before that phase's triggers/actions; an end boundary
wakes it before the phase's final root priority window. In
particular, beginning of end step wakes before beginning-of-end-step triggers,
while end of end step remains snoozed through those triggers and wakes for the
root end-step window. Only boundaries that actually occur count. The referee
still recomputes and audits the complete legal action surface in every window,
including dedicated counterspell and Summary Dismissal response questions. Those
questions also expose `PASS ON` and whole-stack `AUTOPASS`. A passed-on object
does not appear as an ordinary action merely because another object opens a
question. Instead, when a different unsuppressed object has opened that prompt,
the player may choose its explicit `WAKE` control; that clears the schedule and
reopens that player's current priority choice. Selecting the object after it has
woken, or its zone/controller changing, cancels its schedule.
Stack `AUTOPASS` is independent and may continue to suppress a prompt after an
object schedule expires.

Revision 5 spellcasting choices may carry `--autoresolve`. The tag starts the
existing whole-stack autopass only when the selected spell was cast onto an empty
stack. It never suppresses opponents' priority. If any player casts a new spell,
the spell-cast epoch changes and the caster wakes; if the stack empties, the
shortcut is discarded. A spell cast in response to a nonempty stack receives no
autoresolve shortcut.

Also in revision 5, passing a postcombat-main `main_action` may carry
`--snooze-all` and an optional `--until "SCHEDULE"`. It suppresses that pilot's
optional/passable decisions and priority prompts until the chosen public boundary.
Without `--until`, the deadline is the end step of the living seat immediately
before that pilot in turn order. An attack against the pilot or their planeswalker
wakes them before post-attack priority and blocker declarations. A genuinely
mandatory choice wakes them as well; SNOOZE ALL is not authority for the referee
to invent targets, ordering, payments, or other required choices. The seat-wide
record is separate from objectwise passes so a future scheduler can subsume both
without changing their semantics.

At any already-open decision, `MANAGE PASS-ONS` lists only that actor's exact live
objects, zones, wake conditions, and remaining boundary counts. The pilot may
unsnooze one, unsnooze all listed UIDs, or reschedule one using the same typed
grammar. Bulk cancellation resolves to a concrete sorted UID set before replay.
Every requested target is validated before any entry changes, so a stale or
foreign UID fails atomically. Rescheduling computes its new ordinal from the
boundary counters at replay time and never briefly makes the source prompt-active.

Unsnoozing removes the object-wide suppression. It neither creates priority nor
interrupts or rewinds the pending choice. The source waits until the pilot next
receives priority normally. The gameplay question remains open under the same
decision ID. Review remains available during a displaced/rebase decision, but
mutation waits until its replacement is committed.

An opposing spell that targets a player or a permanent they control, and an
attack directed at that player or a planeswalker they control, automatically
wake all of that player's passed-on objects before their resulting priority
window. These threat-specific wakes are audited and do not change the behavior
of unrelated priority windows.

## Public messageboard

Revision 3 and later keep `TABLE TALK (NON-MATERIAL)` on main-action requests until it is
used or that precombat/postcombat main phase ends. Selecting it must include the
complete message (at most 300 characters) and structured address in that same
answer; no separate compose decision exists:

- generic, which prompts nobody;
- all living opponents; or
- one named living opponent.

Each addressee, in turn order, receives one passable `messageboard_response`
decision. Selecting `RESPOND PUBLICLY` requires the response text in that answer.
Every response is public and formally generic,
linked to the initiating post only for transcript clarity; it cannot name a new
formal addressee or trigger another response. After each addressee responds or
passes, the referee resumes the active pilot's ordinary main action with no
further messageboard option in that precombat or postcombat main phase.

The complete transcript is deterministic, public, and reconstructed from the
accepted decision tape. Every later public state carries its total count and a
recent excerpt; `inspect messageboard` returns the complete transcript out of
band. Each game also refreshes `MESSAGEBOARD.md` alongside `STATUS.md`, so the
complete current public transcript can be viewed live. Rewind/rebase removes messages whose decisions belong to the discarded
branch. Message text is always untrusted player-authored speech. A promise,
threat, bluff, or assertion on the board is neither a rules fact nor a referee
instruction and cannot establish hidden information.

Revision-2 games preserve their original first-main-action opener followed by a
dedicated compose decision. The editable characterization templates live in
`data/strategy/messaging_personalities/`, one Markdown file for each pilot. New
cohorts snapshot all four together as `messaging_personality_snapshot.json` and
bind that immutable revision into each game; a legacy cohort adopts them only
when `advance` begins its next untouched game. Later source edits cannot alter an
active or sealed game. On revision 2, the acting pilot's full entry is injected
as `private_messaging_personality` only into `messageboard_compose` and
`messageboard_response`; ordinary main action receives only the compact
initiative cue. On revision 3 and later, it is injected into every message-eligible main
action, every message response, and every first-draw planning checkpoint. It is
reconstructed on retries until the message or planning obligation commits. It
shapes public voice, political posture, risk tolerance, and planning style, but
cannot override rules, known information, or deck doctrine; no opponent receives
it.

On revision 4, each pilot's first own precombat main requires TABLE TALK before
any material action or pass. The message must be a characteristic but
strategically unrevealing salutation with a generic address. It prompts no
responses, closes that main phase's message window, and returns to the same main
action. The referee rejects both skipping it and choosing an addressed mode.

## Draw-triggered planning and rationale

Revision 3 and later latch one private planning checkpoint when a pilot draws its first
card during each turn, including another player's turn. Later draws by that pilot
in the same turn do not latch another. The latch creates no priority and attaches
to the pilot's next actual decision. The same response must contain its gameplay
choice, a complete replacement short-term plan, a long-term `KEEP` or `REVISE`
decision, and a private rationale for that long-term review. `REVISE` also requires
the complete replacement long-term plan. The batch commits atomically after
successful candidate replay; rewind/rebase discards its branch-bound journal
entries. Revision-2 games retain their original main-phase review cadence.
Revision 4 additionally requires `REVISE` at the checkpoint on each pilot's first
own turn. That replacement Long-Term Plan must identify the current route or goal,
a posture toward every living opponent, plausible future branches, and pivot cues.
Each opening opponent clause must use the checkpoint's exact `OPPONENT: strategy
unknown beyond public information` qualifier. Added posture may rely only on the
acting pilot's visible request and public history, never on another pilot's private
seed, hidden hand or inspection, gameplan, or unrevealed decklist knowledge. This
machine-checked qualifier protects seat boundaries when one external operator pilots
the whole pod.

Gameplay rationale is mandatory when the selected action casts a spell, when a
pilot chooses targets for an activated ability, and when a pilot orders
simultaneous triggers. It is optional for every other externally presented
decision. Each request receives the same pilot's full immediately previous
decision item and full most recent rationalized decision item. These projections
include the original request, options, choice, and rationale, but never recursively
embed older context or another seat's private information.

## Priority concession

Every already-open revision-2 priority or specialized response request includes
`CONCEDE`. It is deliberately excluded from legal-action discovery, so it cannot
cause a seat with no other action to receive a prompt. Selecting it immediately
uses multiplayer player-leaves-game cleanup: owned objects, controlled stack
objects, borrowed permanents, delayed returns, and private priority state are
handled before play continues. Revision-1 games retain the former upkeep prompt.
Reaminatour's concession still ends the focal pilot game even if opponents remain.

## Combo shortcut adjudication

The main-action and priority surfaces include `PROPOSE COMBO LOOP FOR
ADJUDICATION`. A pilot selecting it must put a complete demonstrated loop or
sequence, its rules basis, and claimed result in the decision rationale. The
proposal is a shortcut request, not permission for either the pilot or Python to
assume success.

Every other living pilot receives a separate consent decision in turn. `YES`
means that pilot has no disruption or interaction capable of stopping the stated
demonstration. Any `NO` cancels the shortcut and returns to normal play. Only
unanimous opponent consent pauses deterministic replay for a separate rules
adjudicator.

The adjudicator receives a proposal ID, a hash-bound seat-redacted state request, all
consent records, and a closed operation schema. It must return a nonempty rules
basis and public summary with one of three verdicts:

- `approved`, with one or more validated operations;
- `rejected`, with no operations; or
- `needs_demonstration`, with no operations.

The only operations are player damage, setting a player's life, and returning
permanents in a declared player/UID scope to their owners' hands. Damage and life
may use a bounded integer or `"infinite"`; the latter is represented by explicit
ledger semantics rather than an unchecked arbitrary mutation. The adjudicator
cannot edit libraries, hands, RNG, arbitrary fields, or execute code. The
campaign rejects stale IDs/hashes and malformed or out-of-scope operations,
candidate-replays a valid response, and binds the committed result immutably to
the exact proposal. State-based actions, elimination, triggers caused by bounced
objects, commander owners' command-zone replacement choices, and invariants run
normally after approved operations. A rejected or
insufficiently demonstrated shortcut resumes play without modifying game state.

An instant-speed action discovered by the audit but lacking an exact resolver is still shown. Selecting it raises `UnrefereedDecisionError` and records a material unsupported interaction; it is a release blocker rather than permission to suppress the option or use a deterministic fallback.

## Simultaneous triggers

Trigger batches use APNAP stack placement. When one controller owns two or more triggers created at the same time, `trigger_order` asks that controller to choose their bottom-to-top order. Active-player triggers are placed first, followed by each nonactive player in turn order, so the last nonactive bundle resolves first. The chosen order is part of the replay tape and changes actual resolution order.

## Information discipline

For a decision made on behalf of a player, the request exposes only that player's legally available information:
- that player's hand and cards they are legally searching/looking at;
- public battlefield, graveyards, exile, commanders, life totals, counters and prior public actions;
- opponent hand/library sizes, not hidden identities;
- cards revealed by the current effect.

The public portion of every decision also reports each player's modeled mana
capacity from currently usable sources. It gives one simultaneous total and
independent maxima for white, blue, black, red, green, and colorless mana.
Flexible sources contribute to several maxima but only once to the total. A
pilot's seed plan, active projection, and dynamic gameplan text are private: they
are absent from public state and from every other pilot's request and evidence
packet. Revision-2-and-later requests automatically receive only the acting pilot's bounded
active projection. A private `GAMEPLAN` query returns the complete sources for
the pending actor. A terminal
private evidence packet stores only its own seed under `private_seed_gameplan`.
A messaging personality is similarly private. Its revision-2 compose/response
delivery and revision-3-and-later planning/message delivery are actor-only, and it is
stored only in that pilot's terminal packet under
`private_messaging_personality`.
Messageboard transcript entries themselves are public. PASS ON management lists
and control events are actor-only and never enter the structured public snapshot.

The omniscient machine snapshot exists only for rules validation and post-game audit. Strategic rationales must be supportable from the seat-visible request.

## Manual tracker override

The ledger is not infallible. If the external pilot can identify a determinate rules/state error, the state may be corrected manually instead of abandoning the game.

Every such correction must log:
- state immediately before correction;
- exact fields/zones/life/counters changed;
- the rules reason for the correction;
- state immediately after correction.

Manual overrides may correct bookkeeping. They may never alter hidden randomness or manufacture a strategic advantage.

Combo adjudication is not a manual tracker override. It is available only after
a taped proposal and unanimous live-opponent consent, and it is constrained by
the request-bound operation vocabulary described above.

## Release gate

The active manual workspace must pass `python -m edh_gauntlet verify` before a gauntlet run. Its built-in release scan rejects any reintroduction of:
- `StrategicReferee`;
- `.choose()` as a decision API;
- `action_score` or board-threat scoring in the manual decision layer;
- `STRATEGIC_FALLBACK`;
- an automatic strategic-gauntlet driver.

Old automated burn-in outputs are invalidated debugging provenance and must never enter card-performance statistics. Disposable test archives are removed during operator-authorized cleanup.

## Checkpoint and rewind discipline

A recoverable rules error is recorded immediately as a game-local work item and
shown on subsequent pilot briefs. Correct the accepted branch with `rewind` when
needed; otherwise preserve the legal current state. The same game continues and
its four post-game evidence packets must review the tagged issue skeptically.

An `UnrefereedDecisionError` is game-breaking. Reject the uncommitted action and
end the game as a draw at the last accepted prefix. After an authorized engine repair and
validation are recorded, run the tagged skeptical review if learning is enabled.
Explicitly suspended hotfixes and learning remain suspended. Preserve
that game as quarantined within the cohort and advance to the next scheduled game.
Never replace the blocked draw or resume gameplay after the blocker.

Live artifacts never persist ordered libraries. The exact position is reconstructed from the seed and accepted decision tape, while requests and checkpoints expose only seat-legal information.

Campaign reconstruction distinguishes the accepted prefix from the
pilot-visible frontier. Accepted decisions rebuild and validate only their
semantic option surface plus the strategy-note IDs needed for evidence; the
complete seat view, public snapshot, inspection index, active plan, and
continuity are generated at the first missing or displaced decision. A rare
semantic mismatch is hydrated into a complete replacement request before it is
shown. A successfully validated candidate frontier is reused when writing the
next checkpoint rather than replaying the same tape a second time.

Campaign mode omits full state copies formerly attached to every internal event
and accepted decision. Those fields are not inputs to the public checkpoint,
narrative, terminal seal, or knowledge-safe evidence projection; each artifact
is generated explicitly at its authoritative boundary. Direct/manual game
construction retains snapshot-rich defaults for diagnostics. Snapshot rendering
may cache continuous-effect views only for the lifetime of that single snapshot,
so later game mutations are always recomputed.

An accepted decision is first replayed as a candidate and committed atomically
only after reconciliation succeeds. Pending gameplay-affecting PASS ON controls
are also candidate-replayed, then embedded in the eventual answer row. Rejecting
decision `D` therefore truncates its controls together with `D` and every later
decision/checkpoint; the rejection audit retains only a count and content hash of
the discarded tail.

New cohorts bind all four source seed plans into an immutable snapshot at
initialization. Legacy cohorts do so only when `advance` begins the next unstarted
game. A started or terminal game is never retrofitted from mutable source
Markdown. Rewind can prune branch-dependent dynamic notes, but it cannot alter
the adopted seed snapshot or its evidence provenance.

The same immutable cohort/game boundary applies to messaging-personality source
files. Accepted messageboard posts and replies are ordinary replayed decisions,
so rewind/rebase drops public transcript entries from a rejected future branch
without changing the personality snapshot that supplied private context.

## Batched combat damage (fresh games)

`combat_damage_batch:1` binds one `response_type:combat_damage` request for all
discretionary attacking sources in the current damage step. Choice maps every
supplied source UID to `{blockers:{BLOCKER_UID:INTEGER,...},defender:INTEGER}`.
Include all listed blockers, even for zero damage. Nonnegative integer amounts
must sum to each source's power. Defender damage requires trample and lethal
assigned to each blocker; without defender damage allocation among blockers is
unordered. The request supplies current lethal values, including marked damage
and deathtouch. Forced distributions need no inference. Python validates the
entire assignment before recording or applying any damage. One rationale and
scheduler directive cover the whole response. First-strike and regular steps
remain separate, with the existing intervening priority window. Legacy games
retain their recorded individual assignment requests. Symbolic action sequences
do not bypass this damage decision.
