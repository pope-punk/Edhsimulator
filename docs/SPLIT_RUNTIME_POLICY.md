# Planning contracts 2, 3 and 4: persistent deciders and planners

For fresh games explicitly binding `agent_architecture:1`, the role, component,
escalation and scheduling rules in [AGENT_ARCHITECTURE_V1.md](AGENT_ARCHITECTURE_V1.md)
supersede the single-planner instructions below. Sol owns strategic goals;
Terra-high owns continuity and tactical prose/actions; Terra-low owns decisions.
Fresh software hosts provide independent short-term, long-term and diplomacy
lanes, each admitting one seat at a time. Legacy serialized hosts retain their
existing slot binding until an explicit verified stopped-host upgrade. Optional
`async_diplomacy:1` routes authorized public conversation to Luna-low and removes
forced reply decisions. Neither binding changes existing games. Use the current host and fenced
stopped-host recovery for this architecture.

With `static_standing:1`, Python loads reviewed standing files; pilots retain
standing through mulligans until their first goal arrives. The short-term planner
retains standing thereafter. Sol retains the full seed. See
[Static standing plans](STATIC_STANDING_PLANS.md).
With async diplomacy, changed goals require refreshed briefs and updated briefs
require public posts. These rules override the legacy standing delivery below.


Enrolled `context_handling:1` packets follow [COMMUNICATIONS.md](COMMUNICATIONS.md)
on both transports. Tables retain all facts; named comparisons retain distinct
origins. Hosted references use only this seat's acknowledged conversation, while
standalone CLI deliveries carry self-contained baselines. Plans, claims, wakes and
handoff ownership continue to follow the rules below.

For legacy games without async diplomacy, short-term planners may suggest one bounded table-talk draft. It appears once at
an eligible current posting opportunity; the pilot retains the choice and message
fields. Already posted exact text is suppressed, and the next short-term update
replaces the suggestion. This does not change immediate messageboard-response rules.

Fresh staged games bind the three-tier contract in [PLANNER_RUNTIME_POLICY.md](PLANNER_RUNTIME_POLICY.md): immutable standing reference at initialization, an automatic opening-hand long-term goal, and frequently refreshed short-term sequencing. Later goal replacements are pilot-requested and precede sequencing. Retain the standing/current goal across compaction; pilots never rewrite plans.


For a fresh game explicitly launched with the software host, see
[HOST_RUNTIME.md](HOST_RUNTIME.md). That transport replaces the direct-followup
and activation-slot instructions here with host-owned dispatch, resident private
contexts and bounded tool waits. All gameplay, plan ownership, claim, information
isolation and lifecycle rules still apply. It cannot control existing desktop
collaboration subagents.

This replaces the plan-writing and prepared-file-read portions of
PILOT_RUNTIME_POLICY.md **only when game_config.json binds planning_contract: 2, 3 or 4**.
Decision surface 6, MANUAL_REFEREE_PROTOCOL.md and the campaign lifecycle remain
authoritative. Missing or planning_contract: 1 means the legacy policy applies.
Contract 4 inherits contract 3 cadence and adds explicit pilot batch approval under
[APPROVED_SEQUENCES.md](APPROVED_SEQUENCES.md). It adds no plan-adoption turn.

New contract-4 games bind `context_handling:1`. [HOST_RUNTIME.md](HOST_RUNTIME.md)
defines same-seat idle transcript checkpoints and [HOST_AGENT_POLICY.md](HOST_AGENT_POLICY.md)
is the software host's role-specific instruction source. A context checkpoint
does not rewind gameplay, replace an agent's role, create planner work or change
snoozes, watches, alarms, pending approvals or accepted choices. Desktop transport
uses the same bounded packet/event presentation but does not invoke App Server
history operations. Started games retain their bound handling.

## Decider

Keep one isolated context for this seat/game/accepted branch. Read the manual
referee protocol once. In three-tier games retain the immutable standing reference
as soon as it is published; the separate planner retains the full seed. Earlier
contracts keep their bound opening seed delivery. Reason about
the current move and supply the explicit action, required rationale, targets,
payments, message fields and exactly one scheduler directive. Required effect
choices always belong to you. Resolve my sequence is the snooze for your own
spell/trigger sequence; required choices and opponent intervention still wake you.

The planner maintains the written continuity and gameplan. Use its current long-term
goal and short-term prose as the primary strategic frame for each decision. Prefer
actions that advance the goal while preserving the intended resources, protection
and snooze policies. The standing plan explains deck capabilities; symbolic steps
are execution proposals whose purpose comes from the prose. Current rules, visible
facts and required choices take precedence. Use Python's factual differences to
adapt actions for material changes, immediate danger or a clearly better opportunity.
When a rationale is required, connect the action to the goal or the material reason
for departing, without repeating the plans. Request long-term maintenance at an
allowed priority decision when the route or survival assumptions become stale.
You do not write, KEEP/REVISE or validate a plan, and never write a fallback plan.
Do all of this within the current decision; do not add a planning/validation turn
or wait for the planner. Existing rationale requirements remain unchanged.

Contract-4 claimed inputs present the full current goal and short-term prose before
the legal decision details, including on compact updates. Each claim reconstructs
those sections from its immutable plan reference; newer publications cannot alter
a claimed input. Turn numbers in plan prose refer to the seat's own turns unless
stated otherwise. Storage retains shared plan components instead of saving another
copy of the prose for each decision. Historical claims keep their original format.

Your generated route contains a claim/read command. Generate one UUID for this
work turn, substitute it for YOUR_WORK_TURN_UUID, and retain it on retries. The
read both claims the decision and returns its immutable input. Do not directly
open a prepared context file instead. Claim creation does not acknowledge model
receipt; inspection/submission does. An identical read retry returns identical
text and the same plan attachment. Another invocation cannot claim that decision.

Submit with `pilot_session --cohort PATH --actor SEAT --response-stdin` (JSON on
stdin) or `--response FILE`. Use the returned game, actor, decision_id,
pilot_context_id and claim_id, plus your answer object:

```json
{
  "game": 1,
  "actor": "YOUR SEAT",
  "decision_id": "FROM INPUT",
  "pilot_context_id": "FROM INPUT",
  "claim_id": "FROM INPUT",
  "answer": {"choice": 1, "rationale": "Your actual rationale", "hold_full_control": true}
}
```

The adapter derives the submission identity and binds the displayed plan/diff;
you do not supply plan IDs or bookkeeping inside answer. An accepted retry is
idempotent, including a retry after another seat takes over. A different answer
cannot replace an accepted choice. Rejected choices can be corrected under the
same claim. In contract 2, an eligible ordinary strategic answer may include
`planner_update: "short_term"` or `"long_term"` to request optional maintenance.
It creates no extra action or plan-writing step. Contract 2 retains its draw cadence.

Contracts 3 and 4 replace planner_update with an optional planner_alarm at any existing
priority decision: {"mode":"now"}, {"mode":"cancel"}, or
{"mode":"schedule","seat":"SEAT","time":"1 beginning of draw"}. Scheduled
occurrences count only the named seat's boundaries. You have one replaceable alarm;
now/cancel clears it. You cannot schedule your own end of end_step: mandatory
own_turn_completed maintenance already runs after end-step activity and cleanup.
The planner's own one-shot watches and mandatory maintenance remain independent.

To request maintenance before submitting your current choice, use
`pilot_session --cohort PATH --actor SEAT --claim-id CLAIM --planner-alarm JSON
--control-id UUID`. Retain the UUID for retries. This actor-scoped control consumes
no decision, changes no priority, and returns without waiting for a planner. Never
add an inference turn just to poll a planner or receive its plan.

Inspect with `pilot_session --cohort PATH --actor SEAT --claim-id ID --inspect QUERY`;
repeat --inspect to batch queries. Normal actor inspection remains available.
`--inspect continuity` returns the frozen full factual event report since the
delivered plan's source. Under context_handling:1, briefs contain conservative
plan differences and summarized observations since the pilot's last seen board;
they do not repeat the since-plan engine timeline. `--inspect decision DECISION_ID`
retrieves an accepted own decision's actual observed board; `--inspect history`
or `--inspect "history after=EVENT_SEQUENCE"` retrieves actor-scoped chronology.
Legacy deliveries retain their bound event previews. Python reports facts,
not strategic validity, and does not guarantee complete modeling of restrictions.

An accepted submission returns another own-seat input in the same work turn, or
handoff/stop/fresh_context_required. On a resume handoff immediately forward the
exact generated prompt to the exact registered incoming agent, then return
`forwarded: true`. Do not open that seat's files, inspect its state or choose its
actions. A fresh route goes to the coordinator for creation. No planner participates
in this healthy path. Return immediately on lifecycle stop, rules blocker or pause.

## Persistent scheduling/recovery coordinator

The coordinator reads only NEXT_ACTION metadata and the status/reserve/dispatch/
stop outputs below. Never read private snapshots, inputs, inspection files, plans,
attachments or raw workboard storage (which contains private opening requirements).
Register deciders with pilot_dispatch register after creation. A lost/replaced
decider must be fenced through recovery before another one registers.

Retain four planner contexts, each fixed to a seat/game, initializing lazily at its
first job with fork_turns="none". Never rotate one shared planner across seats.
At most one planner may be active. Before admitting it, check actual host capacity
and active-agent status: reserve three slots for coordinator, outgoing decider and
incoming decider. Confirm idle contexts do not consume these activation slots.
Do not rely on instantaneous cancellation to make a handoff fit.

Use `python -m edh_gauntlet.planner_runtime --cohort PATH --game N status` for the
metadata-only workboard. At existing coordinator opportunities, if next_actor is
present, call `reserve --admission-id STABLE_UUID --host-capacity N --host-active N`.
Python prioritizes mandatory work then age and groups pending work for that seat.
Reservation retries use the same admission ID. Execute its spawn/resume prompt
using the host tools. Register the host result with
`dispatched --batch ID --agent HOST_TARGET --outcome accepted|unknown|rejected`.
The planner may start reading before registration finishes; the reserved batch and
generation already fence its work. Unknown dispatch is not permission to retry.

In contracts 3 and 4, the latest compatible publication is selected at the next
unclaimed ordinary decision in any phase. A claimed input is immutable; never
interrupt a decider or create an adoption turn. In contract 4 both current prose
plans appear on each new decision, while symbolic proposals arrive on change
and remain inspectable. Staged prose need not wait for the actions stage.
Contract 2 retains main-phase-only selection.
Neither contract requires coordinator routing or approval. Publication does not release
the execution slot. On a host completion/termination notification or explicit host
status check, call `stopped --batch ID --host-status STATUS`. Only then admit the
next planner. Failed work remains pending; terminal mandatory debt remains marked
unfinished. A staged planner finishes its bound stages before returning metadata;
a single-publication planner publishes once. No model heartbeat,
per-action scheduler turn, progress-only inference or planner-to-decider messages.

There is no host wake API inside Python. Use existing initialization/completion/
recovery opportunities for admissions. A deployment that needs fully autonomous
queue notifications must supply a supported host adapter. Do not claim that a
filesystem workboard wakes a dormant coordinator. Count admission inference as
overhead. The four planners replace decider plan maintenance, not tactical reasoning.

Use `python -m edh_gauntlet.handoff_runtime --cohort PATH status` for stall metadata,
or `watch --seconds 60` for a bounded software wait. It never reads private payloads,
chooses moves or restarts agents. Prepared/claimed/submitting thresholds request
investigation. A timeout alone never proves host execution stopped.

`handoff_runtime --cohort PATH metrics --game N` reports route-to-read,
read-to-submit and submit-to-checkpoint timing, plan delivery and maintenance
counts. These are observable intervals. Count decider/planner/coordinator inference
from host telemetry separately; moving already-batched writing to a planner can
increase total model turns while shortening the gameplay critical path. A measured
game-speedup claim requires a comparable gauntlet run and strategy-quality review.

For an exception, inspect the actual destination's host status first. With the
current route ID and matching host agent, `recover --route ID --host-agent TARGET
--host-status idle|completed|cancelled|failed|not_found` reconciles a committed
answer or fences the old generation and emits the replacement route. Unknown or
running status is rejected. Use --replace only for a lost/unusable context. A
coordinator may relay the exact recovery resume prompt only when that result says
coordinator_relay_allowed: true. Healthy resume prompts still travel directly
between deciders. Do not retry an uncertain host call speculatively.

The locally supplied work-turn UUID distinguishes retries from competing reads;
it is not cryptographic proof of host invocation identity. Host tools and explicit
status reconciliation remain necessary for uncertain delivery. At-most-once choice
acceptance is enforced independently by the tape, claims and serialization.

At game end, rules block, learning/review, cancellation or user pause, stop further
admissions and finish/cancel active workers. Never let a planner consume post-game
review knowledge or backfill a terminal obligation. Discard all seat/planner
contexts after game change, rewind, rebase or private-information exposure.

## Activation

New CLI cohorts default to --planning-contract 4; --planning-contract 1 retains
the older workflow. The Python init API defaults to 1 for existing integrations;
pass planning_contract=4 explicitly. Existing game_config files without the field
remain contract 1, regardless of later cohort configuration.

For a running surface-6 cohort, `python -m edh_gauntlet.planner_runtime --cohort PATH
enable-next-game` enrolls only unstarted games. It does not touch the active game's
tape, packets, config or agents. Complete its current review/learning lifecycle
normally before advancing.

## Contract 3 cadence and comparison

Mandatory background maintenance happens once after each seat settles its opening
hand and once at own_turn_completed after cleanup. No draw event automatically
wakes a planner. Four completed ordinary turns therefore create four EOT reasons;
watch/manual wakes add work, and multiple pending reasons for one seat coalesce
into one reservation. Events during active inference accumulate one follow-up
batch; do not restart the active planner. On publication, Python catches watched
edges that happened since the source snapshot, including during inference.

Planners publish a bounded symbolic advisory cast list and a replacement bounded
watch list; see PLANNER_RUNTIME_POLICY.md. The decider still chooses every action.
Python derives actual casts and the delivered plan from accepted decision receipts,
then reports matched/outside-window/missed/late/superseded/conditional facts. An
unseen plan is never treated as ignored. A cast still counts when countered.

`planner_runtime status` includes wake_counts and pending_seat_count. Compare
those with completed turns, reservations and host inference telemetry before
claiming a speedup. More off-turn drawing no longer multiplies mandatory jobs;
loose watches can still increase inference, so keep them conservative.


Fresh CLI contract-4 cohorts default to staged planner publication (`--planner-publication single` opts out). The game configuration binds this choice; existing games retain their original protocol. See [PLANNER_RUNTIME_POLICY.md](PLANNER_RUNTIME_POLICY.md) for routine short_term → actions and initial/pilot-requested long_term → short_term → actions; standing initialization comes first. These are consecutive inference/tool cycles in the same persistent planner context, with no additional pilot planning turns or coordinator inference. Python callers opt in with `campaign.init(..., planning_contract=4, planner_stages=True)`.
