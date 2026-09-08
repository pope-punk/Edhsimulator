# Contract 4: concrete proposals and pilot-approved sequences

This applies only to games bound to `planning_contract: 4`. Started games retain
their existing contract. Four persistent seat planners, EOT/opening maintenance,
conservative watches, optional pilot alarms and direct player handoffs continue
under SPLIT_RUNTIME_POLICY.md. No extra planner job or pilot inference turn is
required to propose or approve a sequence. The software host routes these handoffs
directly; desktop transport uses the outgoing pilot's prepared route.
Idle transcript checkpoints preserve the stored approval/program/cursor and never
re-execute an old choice. A claimed decision blocks automatic continuation and
cannot be replaced by a checkpoint.

## Planner publication

Read the pilot's recorded rationales since the previous plan before updating
continuity. Short-term prose names the concrete intended card sequence and why it
advances the current long-term goal. Put exact timing, UIDs, choices, rationales
and snoozes in `action_sequence`, replacing the previous list completely. Avoid
duplicating the complete symbolic encoding in prose or a `recommendations` list.
An empty action list clears the proposal.
Use `--inspect roles --inspect deck --inspect seed` at initialization and inspect
relevant known cards/objects as needed. Never use ordered future-library knowledge.

Each proposal has a unique short `id`, absolute own `seat_turn`, `phase`
(`precombat_main`, `combat`, `postcombat_main`), exact referee decision `kind`,
symbolic `choice`, concise `rationale`, one `scheduler`, and optional `requires`.
The list is limited to 16 steps and 12,000 UTF-8 bytes. Each rationale is at most
300 characters, choice 1,500 bytes, and prerequisite list eight predicates.
Plan one expected line, including specific combat and postcombat actions when
known. Do not build a branching program or invent future token/card UIDs.

The current pilot menu exposes aligned `symbolic_options`. Cards/permanents use
`{"uid":"VISIBLE_UID"}`, players `{"seat":"NAME"}`, tuples use lists, and action
tuples use `{"action":"KIND","source":OBJECT_OR_NULL,"args":EXACT_PARAMETERS}`.
The UID must be visible in the planner's frozen input. `null` means PASS; a
multi-select choice is a list of exact choices. Do not use menu numbers or parse
labels as future identities. A land_play uses a UID object; an ordinary main_action
cast uses `{"action":"cast","source":{"uid":"CARD_UID"},"args":{"miracle":false,"x_value":0}}`.
Alternate casting costs/modes may require other exact parameters; inspect first.
Required targets, modes and payments are separate decisions where the referee
exposes them. Propose them separately only when their identities are known.

Example step (substitute a visible card UID and the intended own-turn ordinal):

```json
{
  "id": "develop-rock",
  "seat_turn": 2,
  "phase": "precombat_main",
  "kind": "main_action",
  "choice": {"action":"cast","source":{"uid":"CARD_UID"},"args":{"miracle":false,"x_value":0}},
  "rationale": "Develop mana while preserving the removal spell.",
  "scheduler": {"mode":"resolve_my_sequence"},
  "requires": [{"path":"/players/YOUR SEAT/life","op":"gte","value":20}]
}
```

`requires` are machine-checkable factual prerequisites, not prose about validity.
Paths use JSON Pointer escaping and address UID-keyed objects inside zone lists
(e.g. `/players/Omo/battlefield/UID/tapped`). Operators are `eq`, numeric `gte`/`lte`,
and boolean `present`. Missing facts fail unless `present:false` is explicit.
Global `dependencies` still highlight source-to-current differences; prerequisites
add per-step execution checks. Neither replaces the pilot's tactical judgment.

Attach a snooze policy to every step. `resolve_my_sequence` is the snooze for
optional priority through your own spell and resulting triggers, until another
player acts or a required choice arises. Use `hold_full_control` when appropriate.
An object snooze needs visible eligible UIDs. Table snooze is permitted only on
the last approved step because it could suppress subsequent planned actions.

## Pilot response and execution

Latest published prose arrives on the next unclaimed decision, in any phase;
symbolic proposals follow their actions publication. Three-tier requested goal
updates precede short-term/actions, while routine maintenance has those two stages.
An already claimed input stays frozen, even if a newer plan publishes. Review
the proposed actions and Python's factual changes while reasoning about an
existing own `land_play` or `main_action` in precombat/postcombat main. Approving
a plan is not a standalone turn. Ordinary answers remain available at all times;
reject the entire proposed line by making an ordinary decision instead.
Explain the departure in that decision's rationale. For partial batch rejection,
include one `rejection_rationale` (nonempty text, at most 300 characters) in the
batch alongside approve/reject. It summarizes the reason for the rejected line,
including changed board facts when relevant, and is delivered to the planner once
per batch. Older responses without this field remain valid; absent explanations
must not be inferred. This adds no response or planning turn.

Submit the usual five identity fields with **batch instead of answer**:

```json
{
  "game": 1,
  "actor": "YOUR SEAT",
  "decision_id": "FROM INPUT",
  "pilot_context_id": "FROM INPUT",
  "claim_id": "FROM INPUT",
  "batch": {
    "approve": ["land", "develop-rock", "attack"],
    "reject": ["hold-removal"],
    "overrides": {"attack": {"rationale": "The newly tapped blocker opens this attack."}}
  }
}
```

Name every proposed step exactly once in approve or reject. The approve list
sets execution order; steps must belong to one own turn and cannot go backwards
through phases. Overrides may replace `choice`, `rationale`, `scheduler` or
`requires` on approved IDs. Otherwise you explicitly adopt the planner's rationale
and snooze. You retain authority over tactics; the planner cannot submit choices.
To integrate a newly drawn card or another tactical addition, include `add` in
the same batch: a list of full steps using the proposal schema. Give each a new
ID, explicit rationale and scheduler, and insert its ID anywhere in `approve` to
set the final sequence. Added card/object references are validated against your
current claim's visible board, so they need not have existed in the planner's
older snapshot. Additions must all be approved; existing IDs use overrides.
The final executable list remains limited to 16 steps/12,000 bytes and the entire
batch payload to 12,000 bytes. These tactical edits do not rewrite the stored plan.
The first approved step must match the pending legal choice. `--inspect sequence`
returns the frozen full proposal if its body was already delivered earlier.

Python runs one replay, matching each next approved choice uniquely against the
current legal menu. It never guesses a target, selects an alternative, skips a
failed step, or waits for another player. The first following boundary ends the
batch and commits only its accepted prefix:

- Another seat needs a decision, the turn changes, or the approved list ends.
- A choice is missing, ambiguous, illegal or unapproved, including required choices.
- An explicit prerequisite fails or a snoozed object is no longer eligible.
- New cards/information, opponent intervention, combat damage, a counter/fizzle,
  battlefield departure/control change, or other coded material-event barriers.

These barriers are conservative; declared prerequisites cover additional
strategically relevant facts. Expected effects such as a removal spell causing
a departure can also stop the batch. Public messages, concessions and combo
proposals require ordinary answers. On a referee rules blocker, discard the
uncommitted trial and seal the previously accepted prefix through the normal
tagged-draw lifecycle. By default no automatic suffix resumes after a stopping
boundary. With the software host, a pilot may explicitly include
`"resume_after_passes": true` in its batch approval. The host retains the bounded
approved program and attempts the remainder before delivering the next own-seat
input. Only intervening opponent `priority_action` PASS decisions qualify; any
other accepted choice, existing event barrier, changed branch/turn/prerequisite,
illegal next item or already claimed own input prevents continuation. A newer
planner publication never rewrites the approved program. No new approval, plan
adoption or pilot inference is needed for a valid continuation. Opponents still
receive every decision that their own snooze policies do not suppress.

The CLI returns accepted count and stopping reason beside the normal next input
or handoff. Continue an own-seat decision in the same work turn; forward an
incoming seat's generated route immediately. An identical submission retry
reconciles a lost checkpoint and never reexecutes the suffix. A different response
cannot replace a committed origin decision. Late plans cannot change an approval.

## Packet size, provenance and measurement

One immutable approval and one compact execution audit represent a batch.
Accepted tape rows reference those records and the frozen plan by ID, retaining
each rationale with `adopted_planner`, `pilot_override` or `pilot_added` provenance. Review evidence
deduplicates attachments and approvals; it does not repeat full plans per action.
The tape also retains the exact symbolic choice for replay: identical card labels
and reordered menus cannot silently substitute a different physical card.
The next planner sees new decision rationales plus grouped executed/rejected/
overridden/added step IDs and the stopping reason (at most 16 batches, with an
explicit omitted count).

Only the stopping frontier produces a checkpoint, route and pilot packet.
Continuity inputs store an attachment reference rather than a second inline copy.
Full symbolic proposal text arrives on version changes and context baselines;
both prose plans remain visible every decision. For `context_handling:1`, factual
previews are capped at 1,200 bytes with dependency changes prioritized, changed
categories and event-type counts. Older contract-4 games retain 24 rows/6,000 bytes
and six recent events/1,800 bytes. Omission counts are explicit. `--inspect continuity`
reconstructs the full frozen comparison from existing snapshots and the event
journal; it does not create another cumulative diff file. These are section bounds,
not a hard cap on the current board or legal menu.

Runtime metrics count accepted decisions, completed submissions, approved batches
and submissions elided by batching. One batch can replace several pilot calls and
replays; the actual reduction depends on how long approved prefixes survive.
Host inference turns and live game speed still require comparable measurement.

Architecture-1 readiness also reports executed proposal IDs and a bounded set of
exact legal alternatives for a mismatched symbol. Alternatives never authorize
substitution: the pilot must supply an explicit override. Executed IDs remain
executed when a strategic update preserves the same actions component. Reported
continuation stop reasons supersede the initial handoff reason without rewriting
the original acceptance receipt. To span main-phase exit with full control, a
legacy program needs both the main_action PASS and the end-of-main priority_action PASS
before combat choices; omission correctly returns control to the pilot.

## Explicit combat proposals in new tests

Fresh split cohorts bind `combat_proposals:1`; existing game configurations retain
their original packet guidance. The short-term actions stage explicitly proposes
combat inside the existing bounded action_sequence. No new planning stage or
second copy of a combat plan is introduced.

Use combat_target choice `[{"seat":"DEFENDER"},null]` for a player, or replace
null with `{"uid":"TARGET_UID"}` for a planeswalker/battle. A bare player reference
is not the target tuple. Then use declare_attackers choice `[{"uid":"ATTACKER_UID"},...]`.
For no attack, use an empty attacker list after the required target choice; choosing
a target alone does not declare an attack. Every step carries timing, rationale,
scheduler and prerequisites. Pilot approval, rejection, reordering, overrides and
new visible attacker additions use the existing batch response.

Python rejects malformed target/list proposals before publication in enrolled games.
Execution still requires exact current legal options, required attackers, ordinary
priority/intervention boundaries, and the normal combat-damage stop. Include known
intervening PASS choices or suitable explicit snoozes; do not invent automatic
approval for an unplanned priority choice unless the game explicitly binds the
turn-batch policy below.

Operator statistics: `python tools/report_sequence_utilization.py --cohort PATH
--game N --output REPORT.json` counts accepted batch steps separately from saved
submissions. A one-step batch saves no submission. Counts do not include snooze
windows or infer wall-time savings.

## Full-turn batches (`turn_batches:1`)

Fresh split cohorts bind this policy. Started games retain their original binding;
do not retrofit an accepted game or its frozen claims.

At the end of each of the two living opponents' turns immediately preceding a
seat, queue a mandatory short-term update. This occurs after end-step priority,
before cleanup; the seat's existing own-turn completion wake remains after cleanup.
Each pre-turn update uses the existing prose then actions stages. Even an invalid
goal assessment must proceed to concrete interim actions while Sol revises the goal
concurrently. No extra pilot approval turn or planner validation inference is added.

The actions response must include bounded `phase_coverage` for precombat_main,
combat and postcombat_main: each is `{status:planned|no_action|reassess,reason:...}`.
Planned phases require actual sequence steps; other statuses require a concrete
reason (at most 180 characters). Unknown draws do not excuse omitting known plays.
The frozen input specifies the target own-turn ordinal. A late reservation uses
the current or next available turn, never a turn already over. Existing 16-step /
12,000-byte limits remain. Coverage is stored once with the actions component.

Batch acceptance defaults to `resume_after_passes:true` and `pass_priority:true`.
Use explicit false to opt out. While approved actions remain, Python passes
unplanned, unforced own-seat priority without consuming a planned step. Explicit
approved priority abilities still execute; unavailable ones stop. Opponents decide
for themselves. Opponent passes preserve the program; intervention, new information,
failed prerequisites, required choices, combat damage and turn changes still stop.
Automatic passes preserve existing snoozes and exact deadlines, and are capped at
64 per approval. The program is not active after its approved steps are exhausted.

Keep the original rationale unless the choice, scheduler or prerequisites change.
Rationale-only overrides and redundant scheduler restatements retain the original
rationale without a correction inference. Actual edits may include updated rationales;
newly visible cards can still be appended as full steps with snooze instructions.

Imminent pre-turn work precedes routine maintenance within the short-term lane;
aged work retains its starvation protection. Admission remains asynchronous: wakes
are mandatory, but game progression never waits for a planner. If both boundaries
arrive before admission, existing coalescing covers both in one fresh publication
rather than generating two identical plans. Telemetry retains both wake identities.

Utilization reports distinguish planned steps, automatic priority passes, ignored
rationale rewrites and net saved submissions. Publication telemetry records only
the three coverage status labels, not another copy of plan text or board state.
