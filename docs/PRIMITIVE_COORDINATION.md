# Primitive role coordination

Fresh `coordination_document:1` working documents and compact publications are
described in [COORDINATION_DOCUMENT.md](COORDINATION_DOCUMENT.md). They preserve
the scheduling and role authority specified here.

This describes the new primitive host build. Started games retain their recorded
implementation and require explicit migration or a fresh cohort; source changes
never silently rewrite a bound game.

## Planning cadence

Each kept opening hand queues its own short- and long-term planners concurrently.
Short-term work starts from standing strategy and the actor-visible hand, with
long_term_validity pending until its frozen input contains a strategic goal.
Publication order is frozen when the short-term job is claimed:
- EOT1 (after own cleanup): tactical prose, then action proposals.
- EOT3 (opposite-seat gate): action proposals, then tactical prose.
- Opening and other wakes: tactical prose, then action proposals.

If an unclaimed job coalesces both gates, EOT3 ordering takes precedence. A new
wake cannot reorder stages in an already claimed job; it queues the next job.
Publish the first stage promptly; optional inspection must not hold it back.
Necessary inspection for legal proposals remains available. The second publication
may carry a diplomacy_request. Finish after the two publications, without an
automatic refinement stage. Combined publication is permitted only when both are
already ready without delaying the first; it commits in the frozen order.

Actions-first proposals immediately become available for the decider's next claim.
Their following same-job prose preserves proposal identity, active approvals and
executed-step tracking. They are linked to the planning job rather than older
prose. Existing frozen decider claims stay immutable. Later prose-first jobs still
invalidate older proposals when their prose changes. Accepted stages cannot be
rewritten; retries return the original receipt.

After own cleanup, always queue short-term maintenance. At the opposite seat's end
step (two positions away in the current live-seat order), queue only if any
nonland battlefield or the planning seat's hand count differs from its last
claimed planning snapshot. No immediately preceding-seat gate. With fewer than
three survivors only own-cleanup maintenance remains. Python hashes stable ordered
object facts, split into lands/nonlands. Nonland tapping, counters, combat damage,
attachments and control changes count. Land changes, life totals, floating mana,
stack changes and opponent hand counts do not independently trigger this gate.
Skipped gates never advance the baseline. Planner-authored watches are unavailable.
Decider alarms and strategic invalidity escalation remain available.

## Authored diplomacy

The long-term planner supplies a standing brief: objective, disclosure_limits,
commitment_limits, allowed_recipients, and hold_authority (players, scopes,
max_turns up to four). The diplomat composes the actual words. Python enforces
recipient/hold structure; adherence of natural-language disclosures and commitments
is the diplomat's responsibility under the brief, not an engine truth oracle.
Every ordinary long-term publication requires a new diplomatic message, including
an unchanged goal. Optional addressed-message and tactical-request jobs may choose
silence. Reply chains are bounded to three addressed replies; no generic broadcast
reply cascade. Duplicates are rejected, not sent back to the strategic planner.

Each message privately supplies urgency 0/1, explanation, recommended_action and
truthfulness (truthful/deceptive/uncertain). Private assessments are exposed only
to the speaker's own decider, and use acknowledged record references to avoid
repeating prose. Public message payloads never include them. Routine speech leaves
batches intact. Urgent posted speech cancels remaining batches with an explicit
interruption notice and clears those batches' snoozes. No speech approves actions.

## Holds and overrides

Diplomats may restrain only their own seat, within delegated authority: attacks
against a named player and/or targeting that player's permanents. Holds include an
ID, negotiation ID, rationale, and bounded game-turn expiry. Python checks every
submitted/automatic step. Unrelated actions continue. A conflicting batch stops
before the offending step and reports why; executed steps are never replayed.

The decider can call edh_diplomatic_override with named holds and a rationale at
its owned decision. Override executes no action and does not wait for strategic
review. It releases the named holds, records evidence and queues one long-term
review per negotiation. That review triggers the ordinary new diplomatic message.
An overridden negotiation cannot automatically reimpose the same restraint.

## Brief changes without negotiation ping-pong

Diplomats negotiate autonomously inside the brief. They request strategic work
only to change that brief. The long-term planner has unconditional veto and first
publishes brief_decision (approved, rationale, and new brief if approved). Approval
immediately queues the diplomat with new authority; it need not wait for strategic
prose. The long-term planner then updates its strategy only if necessary. Set
update_plan:false on the authority decision to finish without redundant prose.
If the review was initiated solely by diplomatic requests, this final publication
does NOT trigger another diplomatic message. Independent strategic triggers and
hold overrides retain normal mandatory posting. Ordinary continuation never
repeatedly wakes the strategist.

## Direct plan context and self-contained tactics

Every new diplomatic job receives its own complete current long- and short-term
prose components directly, including their IDs and metadata. No separate summary
inference is used. The job remains frozen during its turn; later jobs capture new
publications. These plans may include private intent; receiving them does not
expand the brief's public disclosure permissions. Other seats' plans, raw private
hand/deck packets and decision rationales remain excluded.

Short-term plan prose must stand alone for a decider without earlier planning
history. Reuse still-applicable self-contained prose verbatim, or write the complete
replacement. Do not publish only differences or references to earlier plans.
Historical explanation belongs in continuity, not as a prerequisite for reading
the current tactical plan. Diplomats should add a real diplomatic contribution,
not a board recap or echo; optional work can choose silence.


## Telemetry follow-up from game g

Deciders prefer approving usable supplied action steps by ID and preserve planner
rationales. Direct sequences remain available for changed or absent proposals;
explain a mismatch in the existing action rationale, without an extra inference.
Executed or expired steps are rejected, never replayed. Deciders have no inspection
tool; all command schemas and current choice facts must be delivered directly.
Block assignments are an object mapping every exact attacker UID to blocker UID
lists, including empty lists for unblocked attackers.

Diplomats copy the complete public message ID for replies, not authorization IDs
or reconstructed names. Holds obey the brief's allowed players/scopes and absolute
game-turn expiry. Invalid references remain rejected rather than guessed.

Host telemetry retains per-role input-to-first-tool count, sum and maximum after
rolling event eviction. This measures the first tool after a real input, including
warm delivery, and excludes time spent holding a tool before that input. It is
neither complete planning-job duration nor proof that background planning blocked
gameplay. Aggregates describe one host process lifetime and reset on recovery.


## Recoverable technical help

A decider missing command syntax or facing an unexplained rejected input calls
`edh_request_help` with `intended_action` and `question` (each at most 1200
characters). The host stops and unloads, retaining the exact decision, accepted
prefix, planner jobs, approvals, snoozes and logical seat identities. It does not
seal a draw. The dashboard displays the pending technical-help notice.

The operator reads only the submitted question and necessary command/schema
facts. Explain representation and validation, not strategic choices, targets,
which cards to pay, or another seat's private information. No helper inference
lane, automatic repair, new game or executable default action is introduced.

Read the request after the host stops:

```sh
python -m edh_gauntlet.primitive_lifecycle --cohort RUN help-status
```

Write a response file containing only `{"answer":"Technical explanation."}`
(up to 2400 characters) and bind it to the request and exact stopped prefix:

```sh
python -m edh_gauntlet.primitive_lifecycle --cohort RUN answer-help \
  --request-id REQUEST_ID --response RESPONSE_JSON \
  --expected-sequence SEQUENCE --expected-sha256 SHA256
```

Then use the dashboard's existing Resume operation. Answering help itself never
resumes play or clears an independent user pause. Unanswered requests block Resume.
The requesting logical pilot receives its preserved decision with `technical_help`
and authors the next action itself. Other seats do not receive that answer.
Identical answer retries are idempotent; changed answers cannot overwrite an
accepted response. Full original questions and answers remain in actor evidence.

A technical answer cannot repair an implementation defect, change a started
contract, bypass a pending receipt, or reopen a terminal game. Leave such a game
suspended for verified repair through the existing procedures. `edh_rules_issue`
remains available for actual rules-integrity concerns. This fresh-build feature
does not retroactively unseal H or other terminal games.


## Mana-only priority windows

Fresh games bind `mana_only_priority:1`. Before admitting an unclaimed decider,
Python can pass an empty-stack priority window with no affordable non-mana action.
It counts floating mana plus an optimistic bound on untapped mana sources, including
mana doublers and color choices. It compares lower-bound spell/ability costs,
including alternative payments and discounts. It does not select a payment.
Insufficient total mana or an impossible color requirement can therefore skip
inference even when an instant or instant-speed ability exists.

This is deliberately a proof of unavailability, not an exhaustive legal menu.
Uncertain mana engines, dynamic reductions, convoke, material mana side effects,
tap/activation triggers, temporary or delayed effects, and stack responses retain
pilot control. Affordable candidates retain control even if a later target/cost
check might reject them. Available land plays, Room actions and affordable own-main
plays also retain control. Mana-source color capacities can overestimate mutually
exclusive color choices; that causes extra wakes, never an unsafe skip.

Approved sequences run first; an extant batch that declines automatic passing is
not overridden. Required choices and frozen claims are untouched. Automatic passes
retain the normal accepted replay/evidence and do not publish a new snooze. Games
without this binding retain their original behavior; deployment does not migrate
an active game.


## Combat decision stages

Fresh games bind `combat_stage_batches:1`. A `combat` proposal covers several
steps; it does not make an attack legal during beginning-of-combat priority.
An explicitly approved attack waits for `declare_attackers`. While waiting,
Python passes priority only under the pilot's existing batch/snooze authorization.
At the declaration it validates and executes that exact approved attack, advances
the cursor once, and preserves the rest of the approved sequence. Changed legality
or diplomacy holds still cancel execution and return control to the pilot.

Without an approved attack, the declaration remains a pilot decision. Forced empty
attacks remain automatic; if no eligible attackers remain, the stale attack batch
is cancelled with an explanation. A missed declaration window cannot execute a
late attack or silently roll it into another combat. Old bindings retain their
original scheduling. Direct sequences with explicitly approved attack commands
follow the same stage gate in fresh bound games.

Ordinary attack, block and damage commands require `declare_attackers`,
`declare_blockers` and `combat_damage` respectively. Mistimed calls now identify
both the actual and required stages, retain the claim, and accept no action.
Blocker/damage decisions retain their existing pilot-owned boundaries.


Tapped sources whose abilities require tapping no longer keep priority alive.
Tap/activation-trigger caution applies only while this actor has a potentially
usable mana activation. A tapped City of Brass or painland cannot by itself wake
a fully tapped-out pilot. Required choices, including Rhystic Study's optional draw
and resolution payments, remain separate from ordinary priority and are delivered.

## Default automatic mana payment

Fresh games bind `autotap:1`. Planners propose the intended cast or activation
without `payment`; deciders approve it or submit the same command directly.
Do not normally propose preliminary land taps or mana-color answer steps.
Python quotes the actual cost, selects ordinary mana sources and colors, and
executes a single atomic payment plus the intended action. Exact selected mana
commands are retained in `payment.mana_actions` for deterministic replay.
Publication never authorizes execution; only the decider does.

A hard reservation is attached to the action being paid for:

```json
{"kind":"cast","source":{"card_id":"KNOWN_CARD","incarnation":3},
 "targets":[],"x_value":0,"autotap":{"reserve":{"B":1}}}
```

This leaves one black mana available after payment, either floating or producible
from ordinary untapped sources. `{ "W":1, "B":1 }` requires both simultaneously;
a single flexible one-mana source does not satisfy both. The reservation applies
to this payment only, so repeat it on later actions when desired. The decider may
replace the intended spell/ability and reservation using a complete batch step
override retaining the step ID, or author a direct command/sequence. For example,
replace `reserve:{B:1}` with `reserve:{W:1}`. Allocation is recomputed at execution,
not frozen to the planner's earlier board.

Explicit `payment` without `autotap` opts out. Use it for a deliberate mana float,
a consequential mana source or a payment the bounded solver does not support.
For automatic mana plus explicit non-mana costs, use `autotap:{}` alongside
`payment:{mana:{},taps:[],zone_costs:{...}}`; pilots still select all targets,
modes, X values and non-mana payments. No reservation is silently relaxed.

The initial solver handles free tap-for-mana abilities on noncreature permanents:
fixed production, ordinary color choices, commander colors, land-derived colors,
and mana multipliers. It excludes paid filters, sacrifice/life/counter costs,
creature tapping, consequential triggers and other effects. Search is bounded;
unsupported or impossible payments return for revision without spending resources.
Resolution-payment choices, attack taxes and room unlocks retain explicit payment.
Older games retain their bound explicit-payment contract.

## Concrete strategic reviews

Fresh `strategic_review:1` games ask long-term planners to name the current cards,
engine/win route, available and missing pieces, opposing obstacles, and fallback.
Standing deck doctrine remains separate; tactical mana/cast sequencing remains
with the short-term planner and decider. The existing 1200-character limit remains.
Both short-term and long-term planner watches remain disabled.

Short-term `long_term_validity` adds `review` alongside `valid`, `invalid`, and
`pending`. Use `review` for a material change to named pieces, achieved milestones,
obstacles, or a better concrete route, even when the broad strategy remains viable.
Supply the changed card/fact and question in `long_term_invalid_reason` (300 chars).
The host binds the request to the assessed goal, supplies it as `review_goal`,
coalesces work, and ignores assessments of superseded goals. Tactical publication
continues without waiting. A review may confirm the goal; `invalid` still requires
revised prose. Routine mana/priority changes do not warrant strategic review.

A decider's explicit override of a diplomatic hold already queues long-term review
once per newly overridden negotiation. It does not execute a gameplay action.
That review retains the ordinary diplomatic-publication behavior; the exception
for reviews initiated solely by diplomat brief-change requests remains unchanged.
