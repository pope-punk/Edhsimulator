# Software host and resident agents

The supported current path is a fresh staged contract-4 game binding
`agent_architecture:1`, `context_handling:1` and transport version 2. Python owns
coordination; pilots never forward packets or wake another seat through a model.
Legacy desktop dispatch is documented separately in PILOT_RUNTIME_POLICY.md.
Never migrate a started game into this host or change its bound contract silently.

## Start and lifecycle

Initialize through the campaign CLI, then run:

```sh
python -m edh_gauntlet.host_runtime --cohort PATH --max-decisions 10000 --context-tokens 64000 --timing-events 4096
```

The Windows launcher `tools/start_host_game.ps1` starts this hidden and attaches
`tools/watch_host_game.ps1`. Set `EDH_PYTHON` or activate a Python environment.
The host owns a process lock, uses approvalPolicy never, and stops on unexpected
approval requests. It never repairs rules, performs learning or starts the next game.
`NEXT_ACTION.json` remains the lifecycle authority, including when learning is disabled.

A missing learning setting retains the historical enabled policy. Fresh runs may
bind `--learning disabled`; see LEARNING.md. A rules blocker is still a blocker.

## Roles and scheduling

Each living seat retains isolated decider, short_term_planner, long_term_planner
and (with async diplomacy) diplomacy identities for one game. Contexts never share
private seat information. The current model/effort defaults are Terra-low decisions,
Sol-high short-term planning with Fast service, Sol long-term planning and Luna-low diplomacy.
Fresh split cohorts bind `short_term_sol_fast:1`; games without that binding retain
Terra-high short-term planning and their inherited service tier. Fast is a service
tier (`serviceTier: "fast"`), not a different model name: the model is
`gpt-5.6-sol`. Each physical context records the requested tier and passes it on
subsequent turns and context replacement. Other roles retain their own settings.
Capacity fallback rules still apply. Changing this default does not restart or
modify a running game. See the [Codex service-tier reference](https://learn.chatgpt.com/docs/config-file/config-reference).

Fresh split hosts use 16 independent seat/role lanes (`role_slots:2`): one
inference per seat and role at a time, with twelve background lanes and four
decider lanes. A waiting submission call does not occupy an inference lane.
Seats sharing a role can infer concurrently. Decision packets still require
actual game priority; idle roles gain no new wake triggers. Existing `role_slots:1`
hosts keep four shared role lanes until a verified stopped-host upgrade using
`--diagnostic-pause-telemetry PATH --seat-role-lanes`.
Workboard reservations are identified by exact batch, actor and role. A transport
must match that identity before private delivery or publication.

Static standing doctrine requires no inference. A kept hand triggers the initial
long-term goal; short-term work requires that initial goal. Later long-term work
must not block short-term or diplomacy admission in concurrent mode. Invalid goal
assessments queue one long-term revision. Every completed long-term review requires
a diplomat post, including a kept brief. Expired authorization transfers the public
message obligation without allowing an obsolete commitment.

With `turn_batches:1`, two preceding opponents' end steps require full-turn tactical
updates. Mandatory updates publish interim actions even while strategy is invalid.
See APPROVED_SEQUENCES.md for priority continuation, rationale preservation and
coverage. Gameplay never waits for planner completion; frozen claimed inputs remain
immutable and receive new plans only at the next real input.

## Transport and latency

`host_runtime.AppServer` uses an owned `codex app-server` process and bidirectional
JSON-lines RPC. It initializes once, starts isolated model threads and handles
streamed notifications/dynamic tools. The installed implementation opts into
experimental fields needed by the harness. Pin and validate a compatible Codex
version when moving hosts; do not assume every release exposes the same methods.
[Official App Server documentation](https://learn.chatgpt.com/docs/app-server).

Python directly routes the next seat. Retained `edh_act` calls allow warm returns;
pilots wait for their result and never poll. The default idle window is 30 seconds,
with bounded table-wide retention for priority exchanges when a seat is not table
snoozed. No background heartbeat model is used for ordinary status checks.

Capacity fallback is bounded to the supported role models. Only zero-tool terminal
capacity failures may retry. Never replay an accepted decision, accepted planner
stage or ambiguous tool result. Explicit retry/recovery always preserves the exact
accepted prefix and publication receipts.

## Context and memory

Transport version 2 replaces a conversation at an idle checkpoint while preserving
its logical seat identity. Retained memory enters the next real input explicitly;
there is no inference just to summarize or adopt memory. Never silently resume a
legacy rollback context. An ambiguous replacement leaves a journal and stops.

The shared egress adapter in COMMUNICATIONS.md uses exact acknowledged references,
lossless tables and bounded differences. New physical conversations reset those
references and receive self-contained baselines. Both current plan prose fields
remain visible. Long-term planners retain full seed/personality; short-term planners
retain standing doctrine; deciders retain standing only until the initial goal.

Default planner packets contain current actor-visible state, only the latest actual
pilot-seen board (or exact difference), complete own rationales and rejection
explanations, and compact material-event summaries. They do not repeat a board for
every rationale or hundreds of updated engine snapshots. Historical boards/events
remain actor-scoped inspections. No ordered future library enters an input.

The usual context checkpoint threshold is 64,000 input tokens. Planner admission
reserves headroom for the next real packet. A fresh baseline beyond the hard guard,
unsupported history operation, uncertain RPC or failed visibility check stops.
Raw bytes, delivered bytes, model input tokens, cached input and host RAM are reported
separately; reducing one does not establish a reduction in all of them.

## Observation

Enable OPERATOR_VIEW.json for four omniscient Markdown views outside pilot inputs.
The views include graveyards, active/living seats, turn order, hand, battlefield,
life, current prose plans and the public messageboard. Planner publication refreshes
plans without game replay. Models cannot inspect these files.

Use `tools/collect_host_telemetry.py --cohort PATH --game N --output SEGMENT` against
the owned launched process. It records bounded host metadata into one local segment,
including input/cache counts, timings and process-tree memory. Verify collection
has no gaps before comparing runs. `tools/report_host_segments.py` combines segments
without counting engineering downtime; `tools/report_sequence_utilization.py`
counts executed choices and saved submissions. Observers never trigger inference.

## Pause and fenced recovery

A cooperative HOST_PAUSED.json marker stops admission; already accepted work remains
committed. Verify the exact process ID and start time have stopped before recovery.
Never clear a marker merely because a process seems slow. Inspect compact metadata,
not every full model transcript.

`tools/resume_stopped_host.ps1` and its Python helper support explicitly diagnosed
stops. They validate prefix hash/count, unchanged logical seats, unloaded transports,
publication reservations, pause cause and recovery journals. Do not re-run a recovery
that passed preflight without reconciling its result.

For a cooperative diagnostic pause, supply `-DiagnosticPauseTelemetry SEGMENT` with
complete telemetry matching the stopped process, exact prefix and pause failure.
For decision caps or explicit user stops, use the matching documented switch from
`Get-Help`/`--help`; never relabel a different failure to bypass a gate. Concurrent
background enrollment is an explicit stopped-host upgrade, not a contract migration.
Diagnostic recovery preserves clean contexts; ordinary context thresholds still apply.

After an explicitly authorized rewind, `tools/resume_rewound_host.py` supports
Linux recovery with `--cohort`, `--archive` (the preserved pre-rewind cohort),
`--game`, `--accepted` and `--max-decisions`. It verifies the stopped original
process, exact retained prefix, discarded-tail journal, cleared role identities,
fresh route, completed repairs and unloaded archived transports before removing
the user-stop marker. It starts new isolated contexts and never resumes an old
seat's knowledge of the discarded branch. Rewind preserves only prefix-validated
committed public messages and combo deliveries under the new context epoch.

A terminal result ends this host. Adjudication and horizon stops retain recovery
information because gameplay can resume only after the corresponding lifecycle
operation. Post-game learning and future games are separate campaign operations.

Checkpoint rules memory is bounded to 24,000 compact characters of recently
inspected definitions. Original actor-scoped evidence is retained; an explicit
index identifies archived definitions. Only actually carried definitions qualify
for same-conversation references. Seed, plans, roles and deck index are preserved.
A diagnosed oversized baseline can use `-BaselineTelemetry SEGMENT
-BoundedMemoryRecovery` at a verified stop: retained oversized background contexts
receive a new bounded checkpoint before inference, and canceled jobs retain their
accepted publication prefix. This does not waive the 64k guard.

## Opt-in automatic rules repairs

`python -m edh_gauntlet.supervisor --cohort RUN` watches local lifecycle metadata.
Enable it explicitly with `RUN/SUPERVISOR.json`:

```json
{"enabled":true,"hotfixes":true,"auto_advance":true,"repair_sandbox":"workspace-write"}
```

The dashboard's Start button then starts/reuses that supervisor, and Run record
shows its state. Pause stops host admission and interrupts repair work. A paused
run still needs explicit recovery; the supervisor never clears pause markers.
For an externally isolated Codespace explicitly authorized for unrestricted
commands, `repair_sandbox` can be `danger-full-access`. Repair workers always use
approval policy `never` and the existing Codex login; API-key billing variables
are removed. The mechanism uses [Codex non-interactive execution](https://developers.openai.com/codex/noninteractive).

Rules-repair and release-blocker stops launch one fresh, non-pilot repair agent.
Before it edits shared source, the supervisor acquires every existing local
cohort's host admission lock. The agent can fix engine code and add regressions;
it cannot decide gameplay or certify its own lifecycle completion. The parent
independently runs the test suite and release gate, checks unchanged game evidence
and strategy files, and replays sealed results before recording `repair-rules`.
Attempts, agent output, validation logs and outcomes live under `RUN/supervisor/`.
Each exact stop gets one attempt. Failure, interruption, changed evidence or a
changed sealed outcome stops for operator inspection, including after a restart.
Do not remove a failed receipt to force a retry without reconciling its changes.

With `auto_advance`, the supervisor advances only when NEXT_ACTION says
`advance_game`, and starts fresh games through the normal host. Accepted mid-game
prefixes and saved contexts require cause-specific fenced recovery. Postgame
reviews, learning-transaction recovery, combo adjudication and horizon decisions
remain explicit lifecycle gates. Rules draws remain sealed; disabled learning
remains disabled. This opt-in permission does not migrate game contracts.

### Host processing timings

Rolling metadata includes `host_tool_started.queue_seconds` (receipt to handler),
`host_phase` for pilot submission, event handling and scheduling pumps. Durations
use a monotonic clock; phases under 50 ms are omitted. These are host processing
measurements, separate from model response latency and intentionally retained
waiting tools. Nested phase durations overlap and must not be summed.

Telemetry events accumulate in memory and a background writer atomically flushes
at most once per second while dirty. Event capture does not wait for encoding or
fsync. Shutdown drains the transport and flushes the final batch; a hard process
kill can lose the unflushed batch. The rolling retention limit and event counters
are unchanged, and disk errors surface to the host rather than being hidden.

A scheduling pass yields before another background admission when transport events
are queued. Reservations within the same locked pass may share one reproduced
frontier, keyed by the full accepted prefix and bound configuration. Each actor
still receives a separate private projection. The replay is discarded when that
pass returns; it never carries forward across accepted choices.

Read-only legal-menu construction and payment planning reuse continuous-effect
views and mana-source options only for the query's lifetime, discarding them
before actual payment, resolution or another decision. Source keys distinguish
temporary convoke taps, summoning sickness, treasures and floating mana; returned
option containers are copied so callers cannot modify the cached values.
Component projections read one accepted tape per projection and still validate
every component's branch. Atomic JSON writes retain fsync and replacement while
encoding in one pass. No scheduling cadence, role lane, context threshold or
accepted game contract is changed by these optimizations.

For an explicitly authorized Linux environment-restart resume,
`tools/resume_restarted_host.py --cohort PATH --game N --accepted COUNT
--user-resume` verifies the prior boot identity, exact stopped tape, registered
unloaded transports, unambiguous checkpoints and a playable route. It journals
and releases interrupted previous-boot planner reservations, preserving published
jobs and logical seat identities. It refreshes the current unclaimed decider and
idle background contexts, then runs the host. Other deciders wait for their own
eligible checkpoint boundary. Any attempted recovery journal requires explicit
reconciliation before retry; this mode cannot clear an independent rules pause.

### Proliferate selection batching

Fresh surface-6 cohorts bind `proliferate_batch_after: 0`. Each Evolution Sage
resolution requests one multiselect of eligible battlefield permanents and players
with energy (the player counter type modeled by this engine). Choosing none is
legal but is never inferred from a scheduler snooze. Separate stack objects retain
their own resolution and priority boundaries.

Missing bindings retain the legacy per-permanent questions. An explicitly
authorized stopped-host upgrade may bind `proliferate_batch_after` to the verified
accepted count, with the original configuration and prefix digest retained in an
upgrade receipt. Verify identical accepted replay events and pending request before
resuming through the fenced recovery tool. A legacy resolution that began before
the cutoff finishes entirely in its original format; no accepted answers are
converted or replayed as new submissions.

### General bounded selections

Fresh surface-6 cohorts also bind `selection_batch_after: 0`. The shared
`_request_selection` interface carries exact/minimum/maximum counts, optional
one-per-group limits, and explicit ordered-selection semantics. Validation is
shared by CLI answers, recorded replay, and symbolic approved sequences. Pilots
submit one list; its order is retained where requested. No selection is inferred
from a scheduler snooze. Target legality remains checked on resolution.

Covered paths: each controller's simultaneous trigger ordering; Terastodon,
Grasp of Fate, Nissa and Magus target sets; Reveillark/Vesperlark targets; Finale
untaps; Uro and Sunken Palace exile costs; cleanup discards; Gifts search with
distinct names; Brainstorm putbacks; Sensei's Divining Top ordering. The Gifts
opponent's split remains a separate, opponent-authored decision.

A stopped-host upgrade uses the same prefix receipt and replay parity procedure
as proliferate, setting `selection_batch_after` beyond the currently delivered
question. Existing games without the field retain their original decisions.
Choice loops that reveal new information or currently interleave engine effects
(e.g. explore, land-entry search sequences, counter distributions) require
separate semantic work; this helper must not wrap them indiscriminately.

### Supervisor result recaps

`SUPERVISOR.json` may opt into `recaps: true`. The supervisor writes one short
model-authored recap per terminal evidence version, including historical backfill.
Only recorded terminal facts and rules-review status are supplied. The isolated
read-only author receives no private pilot packets or future-library information;
recaps never adjudicate results, complete reviews, or alter accepted play.
`game_XX/supervisor_recap.json` records authorship and evidence identity. Changed
terminal/review evidence invalidates the displayed recap. Failed attempts are
retained rather than retried every tick. Explicit operator-requested backfill is
an observer task and can run while gameplay remains paused.

The dashboard Results tab includes sealed wins/draws even when Cardwise excludes
them for outstanding verification. Cardwise CSV downloads use the same current
verified-game aggregate as the table. Its replay must pass every bound selection
batching setting, including the historical cutoff, to the engine.

### Speculative outcome collection

Explicit operator opt-in `outcome_estimates: true` authorizes a separate isolated
AI estimator for every terminal game carrying rules issues, including historical
backfill and reviewed issues. `ai_outcome_estimate.json` binds the estimate to
SHA-256 hashes of the terminal seal and rules work items. Estimates retain author,
confidence, rationale and material uncertainty; `null` means no supportable winner
preference. Changed evidence invalidates the estimate. Failed generation attempts
are retained, not automatically replayed.

The Results tab and results CSV include these fields beside official outcomes.
They never change terminal seals, clear rules-review gates, modify strategy,
or count as verified wins in Cardwise. Future automatic estimates use bounded
public terminal/rules facts and may be indeterminate; richer historical assessment
must still exclude hidden pilot packets and future-library order.
