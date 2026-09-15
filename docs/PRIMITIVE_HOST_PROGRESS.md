# Primitive host integration checkpoint

The primitive host is still gated against production launch. This checkpoint adds
an independent campaign surface; existing legacy cohorts retain their runner.

Implemented with focused offline coverage:

- Durable host inputs and accepted receipts, exact request recovery, actor evidence,
  explicit pause handling and rules-review terminal seals.
- Frozen seat decisions, planner stages and actor-only inspection. Hidden hands and
  evidence after the claimed frontier remain unavailable.
- Sixteen independent role lanes, retained waiting tools, explicit approved
  execution, automatic-work caps and narrow zero-tool capacity retries.
- Stable goal identities, stale-assessment fencing, diplomatic authorization and
  duplicate suppression, transactional publication receipts.
- Bound kernel/host/assets/frozen strategy, stopped-host prefix checks and persistent
  logical identities across fresh physical contexts.
- Pilot-authored immediate/scheduled/cancelled planner alarms, counting seat-specific
  game boundaries without duplicate scheduling or gameplay actions.
- Explicit operator pause markers, metadata-only live status, and prefix-fenced
  pause resumption. Indexed evidence reads keep archived boards out of rationales.
- New-information continuation stops and executed-step approval fences.
- Host entrypoint routing by explicit primitive cohort binding, with admission
  still closed.

Validation uses `PYTHONPATH=src python -m unittest discover -s tests -p
 'test_primitive_*.py'`. The latest complete host run passed 50 tests, including the evidence-loading
regression. A subsequent nine-test campaign run passed after adding a fault test
for rules acceptance followed by host-receipt projection failure. A real App Server thread/start probe accepted
Sol-high with requested Fast service, isolated dynamic tools, shell disabled and
approval never. The server reported its service tier as `priority`. No inference
or game action was started by this probe.

Remaining release work:

- Finish object snooze semantics and audit declared tactical dependencies. Expand
  missed-window and multi-turn sequence tests; audit mandatory publication coverage.
- Complete horizon handling, unexpected-crash fencing and host-level replay
  conformance. Validate that stopped physical contexts cannot continue inference.
- Expand fault tests, full suite and installed-package checks; bind admission to
  actual completed host conformance, not a manually flipped readiness flag.
- Update release documentation, push/review/merge the host branch, and initialize
  a fresh hosted-model test game. Preserve the old paused game's accepted prefix.

The authorized local heartbeat is in the main workspace archive at
`archive/resume-heartbeats/host-integration-20260915`. It queues at most one pending
reminder every ten minutes, targets the current conversation, and stops on STOP.
It cannot wake a closed Codespace. It supersedes the old migration heartbeat.

The adapter now accepts a pilot-authored `concede` at an owned priority boundary,
using the existing departure machinery. Seventeen adapter tests and the departure
regressions pass, including terminal replay. This does not implement asynchronous
concessions during suspended choices. Rules basis: CR 104.3a and 800.4a in the
[official comprehensive rules](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt).

The broad local suite started at commit 986b90f before later source edits. Treat
its eventual result as that checkpoint's evidence; CI on the final immutable head
and a fresh installed-package run remain necessary for release.

Current local verification logs live under `/tmp/edh-primitive-*.log`; the broad
pre-checkpoint suite is `/tmp/edh-primitive-full-suite.log` (exec session 79075).
No real game cohort has been initialized. The original paused legacy run remains
untouched. Host production admission remains explicitly closed.

Latest host integration work adds one-shot planner watches for known casts, exact
visible battlefield departures, and committed life-threshold crossings. Watch
installation catches the claim-to-publication interval and unchanged watches do
not rearm. Public messages use a durable outbox that flushes only at an unclaimed
pilot frontier. Superseded/expired/duplicate authorizations retain their receipts
and mandatory renewal debt. Only addressed root messages wake diplomats; replies
and generic chatter do not recursively dispatch models.

Initial tactical admission now waits for the opening goal; own-turn maintenance
waits for cleanup to finish. Cold-context memory excludes rationales already in
the current packet, and waiting contexts park before checkpoint-sized redelivery.
The combined suite passed 63 tests, followed by 13 context/transport checks.
CI also passed on the preceding immutable head 5fbcc92862a0f00c5c02b7270777b982dd676201
(workflow run 34923775174). Further targeted strategic-review race tests are in
`/tmp/edh-planner-frozen-review.log`.

Subsequent focused checks passed: 13 planner tests cover late invalidation and
coalescing, and seven diplomacy tests cover expired authorization after a held
claim and private requests that cannot bypass the settled-hand goal gate. These
changes preserve the frozen input instead of retroactively changing a running
planner's publication obligations.
