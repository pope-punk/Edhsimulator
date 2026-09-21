# Bounded technical support

The user-authorized `tools/watch_pilot_help.py --mode support` now invokes
`tools/run_pilot_help.py` rather than a general repository agent. This is an
external operator tool: it does not change a started game's contract or host
fingerprint. Queue-only mode is unchanged.

The model receives the help question, intended action, current decision, rejection
feedback, and authoritative command/schema facts. It receives no board history,
plans, other seats' packets, source tree, credentials or recovery instructions.
Packets exceeding 24,000 characters escalate rather than silently omit evidence.
The isolated Sol-low Fast conversation has one result tool, with shell, browsing,
apps, plugins, inspection and delegation disabled. It returns a technical answer
or escalation. Python interrupts after that output; no model turn is spent checking
processes, committing answers or verifying resumption. Actual engine defects and
missing facts escalate to the development conversation.

Python checks the exact request and accepted prefix, stopped/unloaded owned
processes, lifecycle blockers and operator STOP/pause markers. It uses the existing
locked `answer-help` command and then the authenticated dashboard resume route.
It rechecks fences between the two operations, never retries an uncertain mutation,
and verifies a live resumed host or accepted progression. Durable watcher receipts
prevent duplicate dispatch. Operator pauses remain authoritative. Gameplay choices,
contract changes and new games are outside this helper's authority.

The receipt has adjacent `.input.json`, `.model.json`, `.response.json` and
`.recovery.json` evidence. Model metrics record input characters, reported token
usage when available, latency and tool count. Recovery records answer, resume and
verification timestamps. Existing actor evidence retains original help questions
and accepted answers for packet telemetry.

Offline inference smoke test (never opens or changes a game):

```sh
PYTHONPATH=src python tools/run_pilot_help.py \
  --receipt /absolute/path/smoke.json --dry-run-packet /absolute/path/packet.json
```

This improves support overhead; it does not guarantee that every question can be
resolved without an engine fix. Missing or uncertain outcomes escalate once.
