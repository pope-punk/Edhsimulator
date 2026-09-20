# Main-phase action intents and payment

## Problem and evidence

The run `web-campaign-20260920-n` was stopped at accepted prefix 1041, SHA
`2bfcb51d1d42a10e532f9fca0924d514f5cd770d6fc5141ec022e0d88d5bd3be`.
It remains user-stopped, not adjudicated as a draw. Its historical runtime and
actor evidence are preserved. Round 7 was not reached (last table turn: 24).

The audit found 27 durable batch-execution rejection records, all in precombat
main: 16 malformed land commands, 7 automatic payment failures, one land play
attempted with a nonempty stack, one hard-reserve failure, one future battlefield
source unavailable, and one consequential mana bundle. These are records, not a
failure percentage: approvals contain different numbers of steps and can be
interrupted before execution. The local evidence summary is
`archive/releases/main-phase-audit-n-20260920.json` in the operational checkout.

Reaminatour's turn-23 Aminatou line illustrates the larger problem. Silent
Clearing's life cost excluded it from the old bundled-mana pathway; a planner also
used `generic` as a mana payment symbol. The next decider passed after that failed
line even though no resources had been spent. Merely documenting another payment
shape would leave execution timing, future sources and recovery inconsistent.

## Shared contract

`primitive_intent.normalize` is used by planner structural validation and command
binding. Aliases are expanded before this layer. Cast/activate defaults are an
empty target list and X=0; actual target requirements still come from the engine.
An empty targeting artifact on a land is removed. Meaningful invalid fields are
rejected. Normalization does not select targets, modes, optional costs or actions.

| Intent | Host responsibility |
| --- | --- |
| Cast/activate/unlock, no payment | Quote actual current costs; choose and pay mana atomically |
| Non-mana selections only (`payment.taps`, `payment.zone_costs`) | Preserve those choices and still select mana automatically |
| Planner `autotap.reserve` | Enforce the simultaneous remaining-capacity requirement; never silently relax it |
| Explicit planner mana allocation or sequence | Preserve it exactly when approved unchanged |
| Decider replaces a planner command | Replace the whole command, including old reservations; use automatic payment |
| Optional resolution payment | `pay_mana` without payment pays automatically; `payment:null` declines |

Mana amounts are W/U/B/R/G/C; `generic` is a cost, never a produced mana symbol.
Empty explicit mana allocations remain explicit for planner/manual compatibility.
Deciders cannot author mana activations or reserve policies. Their non-mana
selections are accepted consistently in direct commands, new sequences and plan
overrides. Future own-card references may describe a battlefield activation
before that card enters, while retaining visibility/ownership and non-mana checks.

## Validation without speculative gameplay

1. **Publication:** structural validation and canonicalization, independent of
   whether a future action is presently legal. Retries retain the original input
   digest, so normalization does not break publication idempotence.
2. **Approval:** simulate only the first action that would execute immediately,
   on a separate kernel. A failure keeps the frozen claim open for correction in
   the same inference; no approval or costs are committed. No future resolution,
   opposing response or hidden information is simulated.
3. **Execution:** revalidate against the actual state and atomically record the
   exact payment. Failure spends nothing for that step; earlier accepted steps
   are never undone or repeated.

Approval is not execution. A land/sorcery action awaiting an empty stack, or an
own permanent awaiting resolution before its proposed activation, waits with its
cursor intact. Progress requires an already approved priority pass or matching
pilot snooze. Without that authority, the pilot gets the decision. Unknown choices,
new opposing actions, expired windows and missing dependencies still interrupt.
This does not automatically assume a spell resolves or a required choice's answer.

A required decision retains a description of the unexecuted suffix for review,
not permission to resume it. Execution rejection records distinguish completed
step IDs and unexecuted actions and explicitly state that the failed step spent
no resources. The next decision can revise/reapprove remaining proposals or author
a new line. Executed planner steps no longer occupy the displayed approval list.

## Payment coverage and boundaries

Ordinary source selection is the fast path, including paid filters and exact
surplus handling. The additional-cost search supports native life, creature-tap,
counter and zone costs. It obeys cumulative resources and delays state-based
actions/trigger placement until the full payment finishes. Legal lethal payments
are permitted under the user's policy; overpaying life remains illegal. Tagged
mana produced during fallback search is considered under its native restrictions.
Room unlocking uses the same atomic mana bundle path, including exact replay.

The solver is bounded, not a complete solver for arbitrary mana engines. It does
not answer arbitrary non-mana effect choices, repeatedly activate a source without
bound, or silently change a planner's reserve. Failure to find a payment is not
proof that no legal line exists. A pilot should receive the actual blocker and
may request technical clarification; it must not be told to perform mana actions
that its role is forbidden to submit. Remaining-capacity and hand-portfolio
ranking are bounded heuristics, not strategic guarantees.

## Agent-facing presentation

The action menu shows one action family and its parameter requirements, with
actual quoted cost where a complete probe permits one. A checked default probe
is not a guarantee for different targets, X, modes or non-mana selections.
Planner templates include known non-mana battlefield activations of own cards
that are still in hand/command, clearly labeled "After entry". Proposed actions
show factual waiting status; no action is automatically endorsed as strategically
correct. Repeated unchanged sections remain omitted; new conversations get full
baselines. Oracle text, current modifications and native validation retain their
separate roles.

## Submission-issue telemetry

The seat-scoped exporter labels failed tool submissions, failure notifications,
explicit help queries, and durable failed batch executions for every registered
role. Exact call IDs link a failed submission to its returned error. It does not
infer failures from strategy prose or count mirrored transcript events again.
Database evidence and notification records can describe the same failure; summary
counts are **records**, not unique failed actions or a rejection percentage.

Round 1/5/7 CSVs retain their windows and gain issue columns. Separate
`submission-issues.json` and `.csv` include all recorded turns. The authenticated
server-side audit has a "Submission issues · all turns" tab and packet links.
Original packet copies remain lossless. Timestamps/context attribution retain
existing capture limitations; missing timestamps are not invented.

## Release boundary

Use a new fingerprint-bound build. Do not upgrade or resume the stopped N under
these rules, do not silently change its contract, and do not launch another game
without a user request. This work does not claim a hosted playthrough validated
the changes. Focused engine, cross-role document, approval, payment and export
tests are the verification gate; full validation remains waived.

## Verification for this change

- 34 focused intent, direct-sequence, additional-cost, schema, fallback and export
  tests passed.
- The 66-test cross-role packet/decider/filter run passed 65 checks; one assertion
  still expected the old menu wording. That assertion was updated to require the
  new checked-default/changed-parameters distinction; its separate rerun passed.
- Four additional full-path checks passed: non-mana sacrifice selections through
  direct submission, batch approval and override, plus Room payment replay.
- A separate waiting test passed after adding selected-face timing handling.
- The final 13 fast schema/export checks passed, including nested transport
  envelopes, four-role issue classification, and exact call/result pairing.
- Dashboard smoke checks authenticated the all-turn issue endpoint and all 42
  packet links, rejected unauthenticated access, and verified N remained paused
  at prefix 1041. These 42 records are not 42 independent failures.

The operational audit server uses the new presentation/export tools with the
original N runtime package. This updates review access without upgrading the game.
