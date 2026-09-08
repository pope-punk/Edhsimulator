# Persistent pilot runtime policy

This is the legacy planning-contract-1 delivery policy. For a game explicitly
bound to planning_contract: 2, 3 or 4, use `SPLIT_RUNTIME_POLICY.md` instead: claim/read
through pilot_session, separate persistent planners, and no decider plan-writing
fields. A missing planning_contract retains this policy for replay compatibility.

This policy implements the revision-6 isolation contract in GAUNTLET_WORKFLOW.md.
MANUAL_REFEREE_PROTOCOL.md remains the rules authority. Every material gameplay
choice belongs to the pilot; Python prepares, validates and routes data only.

## Initialize once

Create each seat agent with no inherited conversation. Read this policy, the
manual referee protocol and the revision-6 workflow contract once. Read the full
frozen seed supplied with the first private delivery. Keep that protocol, your
own known card facts, current plans, opponent observations and unresolved
questions in the same seat context. Other seats' unrevealed information is unknown.

Do not read another seat's packets, raw game/status/decision files, ordered future
libraries, source deck lists, coordinator analysis, or post-game reviews. The
coordinator receives only routing metadata and never reads private deliveries.

## Resume the existing decision process

A normal wake-up is a continuation, not a new research assignment. The outgoing pilot
forwards the generated one-line dispatch prompt verbatim. Your first operation is
to read its prepared private update. In PowerShell use `Get-Content -LiteralPath
'ABSOLUTE_PREPARED_PATH'`; with the timed runner use `tools/read_pilot_turn.ps1`
as described below. A separate `pilot_session`/`show` call is unnecessary.

```powershell
.\tools\read_pilot_turn.ps1 -Cohort COHORT -Actor 'SEAT' -Path 'ABSOLUTE_PREPARED_PATH'
```

The reader checks the acting seat, current path and any timed segment cap before
opening the delivery. Timing records contain identities and durations only.
The software host uses `tools/report_host_segments.py` for timing reports.
It separates route-to-input delay, input-to-response time and referee submission;
these are observable intervals, not measurements of hidden model reasoning.

Use the retained plan as the starting point. Check changed facts, current timing,
options, targets, payments and relevant pivot conditions. Reconsider an established
conclusion when new information or a material uncertainty warrants it. Do not
reconstruct the deck strategy, reread unchanged seed/protocol text, repeat known
inspections, or add a procedural recap merely because the agent was resumed.

Every required planning checkpoint still supplies a complete short-term
replacement, long-term KEEP/REVISE and rationale. REVISE supplies the complete
long-term replacement. Opening revisions and exact opponent-knowledge clauses
remain mandatory. KEEP omits unchanged long-term text. Preserve the required
objectives, route, opponent postures, alternatives and pivot cues; avoid repeating
standing doctrine in decision rationale. Plans remain limited to 1200 characters.

## Atomic response and continuation

Each input supplies `actor`, `decision_id`, `pilot_context_id` and
`pilot_delivery_id`. Use those current identities in a JSON envelope with `answer`.
The answer contains the explicit choice, exactly one scheduler directive, and
the rationale, planning or messaging fields required by the current request.
Choices are one-based; 0 is valid only when PASS is offered. Multiselect uses
comma-separated numbers. Public messages have a 300-character limit.

`resolve_my_sequence: true` (CLI `--resolve_my_sequence`) replaces stack snooze
in new answers. **Resolve my sequence is a snooze:** pass optional priority
through my spell and its resulting triggers or abilities; wake when another
player adds a spell, ability, or trigger, a choice requires my input, or the
sequence finishes. Temporary empty stacks during resolution do not end it.
Resolution choices, including optional "may" effects, still require your answer;
the scheduler never chooses them. Supply a new directive with that answer.
Historical `snooze_stack` answers retain their original behavior for replay.

Pipe one literal JSON envelope to:

```powershell
$env:PYTHONPATH='src'
$OutputEncoding=[System.Text.UTF8Encoding]::new($false)
@'
EXPLICIT_PILOT_AUTHORED_JSON_ENVELOPE
'@ | python -X utf8 -m edh_gauntlet.pilot_session --cohort COHORT --actor 'SEAT' --response-stdin
```

Use the configured Python executable and retain any explicit decision cap.
The adapter acknowledges the delivered input with that submission; preparation
alone does not mark its seed or card facts as received. No extra acknowledgment
command is needed.

Use supplied card facts and retained knowledge before requesting an inspection.
Batch material unknowns into one actor-scoped inspection. Before a first
inspection on a prepared delivery, pass `--delivery-id CURRENT_DELIVERY_ID` to
`pilot_session` (or the timed wrapper), with repeated `--inspect` queries
(`--query` in the timed wrapper). Use exact UIDs for `object` and quoted names for
`card`. Retain the complete grammar delivered at initialization; it is repeated
when its content changes or a fresh context starts. Receipt, rather than preparation,
records that knowledge. Current choices and planning obligations still appear on
every decision. `roles` lists exact
role commands; role queries may add `zone=ZONE`, `mv<=N`, or
`castable_now=true`, with the referee calculating current legality. During an
opening or long-term revision, use `role "ROLE NAME" zone=library` when the
unordered remaining composition matters, then retain that analysis in the
persistent seat context. Inspecting never makes a gameplay choice or consumes
priority.

If submission returns another own-seat `decision`, continue in the same work
turn using its supplied update and current identities. Do not call `show` again.
On `handoff` with a resume route, verify `handoff_transport` is
`direct_followup_task`, then call `followup_task` once using the exact
canonical `dispatch.agent` target and exact `dispatch.prompt` message. Do not open
or summarize the next pilot's prepared file. Then return the routing metadata with
`"forwarded": true`. If that tool call fails, return `"forwarded": false` and the
failure class while retaining the unchanged route in this seat context. Do not
send the incoming prompt to the coordinator. A
spawn route always returns unforwarded for coordinator creation. No tactical
summary, receipt narration, coordinator question, or extra file inspection is
needed. On `stop`, `fresh_context_required`, a rules blocker, user stop, or segment
cap, stop immediately. Never open the next actor's packet.

## Coordinator policy

Before starting or resuming gameplay, inspect the live agent tree. Finish or
cancel every unrelated `running` or `pending_init` task from earlier work. During
play, do not run auxiliary sub-agents: root, the outgoing seat, and the directly
woken incoming seat must fit concurrently. Completed seat contexts may remain
idle for later resumption.

Register a newly created agent once with `pilot_dispatch register`. To adopt
existing agents, use `pilot_dispatch adopt` with their saved descriptors; it
rejects stale branches. Checkpoints then prepare the incoming seat's private
update and publish `dispatch` metadata with a validated agent identity and prompt.

An outgoing pilot forwards every resume route directly before returning.
When its response says `forwarded: true`, wait for the already-running incoming
pilot and do not send the prompt again. A resume route sets
`coordinator_relay_allowed: false`. If forwarding fails because agent capacity is
full, finish/cancel the stale unrelated task and wake the outgoing pilot with a
request to retry its retained validated route. If the retry fails with clean
capacity, pause on an orchestration blocker. The coordinator never copies the
resume prompt to the incoming agent. Create a fresh isolated agent only for a
spawn route. Do not
insert a separate dispatch-check command, repeat initialization instructions,
rewrite the prompt, or inspect the private file. The checkpoint already called
`can_resume_session`. Do status analysis after dispatch, while the pilot works.
An ordinary recoverable `RULES-AFFECTED GAME` tag stays public in the handoff and
does not itself invalidate a compatible seat session. A true rules blocker ends
the game as a draw, so no further seat is dispatched for that game.

After an intervening lifecycle command or interruption that could change the
branch, refresh authoritative NEXT_ACTION before forwarding an old route. Never
forward at a user stop, cap, terminal-review boundary or rules blocker. Rewinds,
rebases, migration and contamination discard affected contexts; new games always
use fresh contexts. A missing agent is replaced only after confirming it cannot
be resumed, not merely because an abbreviated status listing omitted it.

The host still begins a model turn on agent resumption. This policy preserves
conversation and explicit working state; it cannot guarantee a continuously
running internal reasoning process. Do not keep idle agents busy with polling,
sleeping tool loops or speculative decisions to simulate that guarantee.
