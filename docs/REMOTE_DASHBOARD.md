# No-login remote operator dashboard: proposed design

This document describes the next interface; no website or domain has been deployed.
The operator requested a personal project with no accounts or login screen. All
players are AIs, so the human observer can see every hand and plan. Those omniscient
views must still remain unavailable to the playing agents.

## Existing integration

The simulation already coordinates agents through `host_runtime.AppServer`: an
owned Codex process, JSON-lines RPC, isolated conversations and dynamic tool results.
Desktop UI automation is unnecessary. Official documentation describes bidirectional
JSON-RPC, local stdio and experimental remote transports; it recommends transport
authentication before remote exposure. Keep App Server private behind the Python
worker rather than exposing its full command surface to a webpage.
[Codex App Server documentation](https://learn.chatgpt.com/docs/app-server).

## One source of truth

Browser tabs -> a narrow EDH operator API -> one serialized campaign worker -> the
existing host and referee. The worker owns the same process lock and NEXT_ACTION
lifecycle. A website must not become a second coordinator or duplicate scheduling.

The browser loads compact snapshots and subscribes to revisions through server-sent
events. Large telemetry/history pages are paginated. It never polls model transcripts
or triggers inference for status. Reconnecting fetches the current revision; it does
not replay a start command. Model credentials remain on the worker.

## Tabs and views

| Tab | Operator needs |
| --- | --- |
| Setup | Deck/pod selection, seat order, seed, game count, round/decision caps, model routing, learning toggle, hotfix policy, output retention, estimated limits |
| Live table | Current game/round/phase, priority owner, stack, living seats, life, battlefield, hands, graveyards and public messageboard |
| Players | One view per seat with standing/current long-term/short-term plans, source decision and age, validity assessment, accepted/rejected/modified sequence, snoozes |
| Agents | Role lanes, active/queued jobs, mandatory wake reason, elapsed stage time, current routing/fallback, latest publication, failure/recovery state |
| Performance | Handoff and decision latency, planner-stage time, first-output delay, input/cached tokens, packet size, process memory, file growth and batch shortcuts |
| Cohort | Per-game results, duration, seed, adjudications, rules tags, learning state and progress |
| Exports | Saved CSV specifications, generation readiness, result adjudication overrides, preview and download |
| Run record | Bounded errors and operator actions, pause reason, accepted prefix, terminal seal and provenance |

Long plan text should load only in its player view. Show new/stale/invalid states by
version and factual changes, not by age alone. Never equate approval rate with actual
execution or input tokens with uncached cost.

## Narrow control API

Read routes: run list, run status, current operator snapshot, role/workboard summary,
paginated public events, telemetry aggregates, immutable export specifications and
completed export downloads. No arbitrary filesystem or Codex RPC proxy.

Write routes: initialize, start, cooperative pause, fenced resume, cancel, explicitly
resolve a horizon/adjudication, and request a terminal export. Every write uses a
run ID, expected revision and idempotency key; return the same receipt on retry.
Starting a duplicate worker or answering for a pilot is forbidden. A stopped run
needs its actual recovery cause, not a generic force-resume switch.

The observer page can be publicly readable without login. For remote controls that
spend model capacity, a personal deployment can use a device-held capability key
(no accounts/login UI) or keep write controls local. This is a deployment choice;
do not expose the underlying App Server or secrets in a public frontend bundle.

## CSV specification

Store a compact specification independently of the generated CSV. Fields: actor/deck,
selected terminal games, card identity, whether kept opening hands count as drawn,
stack-entry and battlefield-entry definitions, their union, draw/adjudication policy,
denominator rules and output columns. Generation happens only after every selected
game reaches the configured terminal learning disposition, including explicit skips.

For the earlier Aminatou question, each card row needs games_drawn,
games_entered_stack_or_battlefield, wins_in_each_subset and the two conditional
win rates. Count a card at most once per game in each subset; union stack/battlefield
before counting. Reanimation counts battlefield entry, countered casts count stack
entry, and zero-denominator rates are blank. A token/copy is not automatically an
original deck-card occurrence. Explicit result overrides affect reporting only,
never the accepted game tape. Label all definitions and selected seeds in a compact
sidecar. No premature empty CSV, inferred unseen draws or card-performance causal claims.

## Deployment sequence

First build read-only views against recorded bounded snapshots, then connect live
revision events, add terminal exports, and finally add serialized controls. Use a
persistent Python worker/container with storage for long games; a static page or
short-lived serverless function cannot own the simulation. A custom .io domain
requires an available domain and hosting/DNS configuration supplied by the owner.
The current release prepares the backend; hosting and the domain are separate work.
