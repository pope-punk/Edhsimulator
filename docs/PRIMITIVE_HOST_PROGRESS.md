# Primitive host integration checkpoint

The primitive host is still gated against production launch. This checkpoint adds
an independent campaign surface; existing legacy cohorts retain their runner.

Implemented and covered by 38 focused offline tests:

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
- Host entrypoint routing by explicit primitive cohort binding, with admission
  still closed.

Validation: `PYTHONPATH=src python -m unittest discover -s tests -p
 'test_primitive_*.py'` passed 38 tests. A real App Server thread/start probe accepted
Sol-high with requested Fast service, isolated dynamic tools, shell disabled and
approval never. The server reported its service tier as `priority`. No inference
or game action was started by this probe.

Remaining release work:

- Finish split-contract scheduling parity: timed alarms, planner watches, dependency
  and action invalidation, public-post debt at unclaimed boundaries, and object
  snooze semantics. Audit new-information sequence stops and repeat approval fences.
- Complete fresh-cohort lifecycle CLI, horizon handling, crash fencing and replay
  conformance. Validate that stopped physical contexts cannot continue inference.
- Expand fault tests, full suite and installed-package checks; bind admission to
  actual completed host conformance, not a manually flipped readiness flag.
- Update release documentation, push/review/merge the host branch, and initialize
  a fresh hosted-model test game. Preserve the old paused game's accepted prefix.

The authorized local heartbeat is in the main workspace archive at
`archive/resume-heartbeats/host-integration-20260915`. It queues at most one pending
reminder every ten minutes, targets the current conversation, and stops on STOP.
It cannot wake a closed Codespace. It supersedes the old migration heartbeat.
