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
Terra-high short-term planning, Sol long-term planning and Luna-low diplomacy.

Fresh split hosts use independent role lanes (`role_slots:1`): one inference per
role at a time. A waiting submission call does not occupy an inference lane.
Short-term, long-term and diplomacy jobs therefore run concurrently with decisions.
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
