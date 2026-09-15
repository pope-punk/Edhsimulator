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

- Complete final fixed-pod surface review and mandatory publication coverage.
- Finish final host conformance and admission checks.
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

Round-limit stops now support `primitive_lifecycle --cohort PATH extend-horizon
--expected-sequence N --expected-sha256 HASH --max-rounds N`. The command requires
a stopped, unloaded transport with matching campaign, generation and accepted
prefix. It records the extension once in every seat's evidence, preserves the
original contract, and does not clear a pause or declare a result. Resume an
operator pause separately before fenced transport startup. Extending a game with
a pending input or terminal result is rejected.

Approved steps now require the deciding seat's own active turn as well as the
specified turn counter and phase. Backward phase/turn ordering is rejected, and a
missed window stops the sequence without an automatic pass. Object snoozes remain
unfinished: the primitive surface now rejects them before acceptance instead of
silently accepting legacy source IDs with no effect. This is still release work,
not a supported object-snooze implementation.

The complete primitive host suite passed 77 tests in 94.441 seconds after these
changes (`/tmp/edh-primitive-horizon-sequences.log`).

Linux crash recovery now supports `primitive_lifecycle --cohort PATH fence-crash
--expected-sequence N --expected-sha256 HASH` under the host-driver lock. New
primitive transports launch in a separate process session and record boot/start
identities for host and transport. Recovery refuses live processes, surviving
session children, missing process evidence, changed generation or changed prefix.
It never kills a process, executes a pending input, clears an operator pause or
changes logical seat identities. After fencing, normal `--resume-fenced` transport
startup reconciles the retained pending receipt. A failed marker write can retry
without duplicating the fence evidence. Platforms without Linux process evidence
retain graceful stopped-host recovery; they cannot use this crash-fence command.

Graceful shutdown also verifies the isolated Linux transport session is empty
before marking contexts unloaded. A real App Server initialize/close probe passed
this check without starting a model turn. Seven focused recovery tests passed,
including a real isolated subprocess (`/tmp/edh-primitive-process-evidence.log`).
The combined primitive suite passed 83 tests in 115.826 seconds; the subsequently
expanded recovery and host transport suites passed seven and 14 tests respectively.
Logs: `/tmp/edh-primitive-crash-fence.log` and `/tmp/edh-primitive-shutdown.log`.

Short-term publications now accept optional `dependencies`, up to 24 distinct
JSON pointers into existing facts in the frozen actor board (for example `/hand`
or `/players/0/life`). Only digests of those selected facts are retained for
comparison; no extra historical board is added to the packet. A changed goal
queues tactical follow-up only if declared facts changed. A late tactical
publication is compared against its own frozen baseline, so a concurrent goal
revision cannot lose the needed follow-up. Missing facts, nonfactual metadata,
duplicate paths and invalid pointers are rejected at publication.
The combined primitive suite passed 90 tests in 101.616 seconds after this change
(`/tmp/edh-primitive-dependencies.log`). Distribution CI for preceding commit
1d1c479 is running as workflow 34925867957; final-head release validation remains.

Host projection replay now has a transactional hash chain. It records changed
state plus affected input, publication, message and compressed evidence rows in
the same SQLite transaction. No-op and rolled-back transactions do not advance
the journal. Reopening reconstructs those projections and compares them with
the stored tables before any pending-input recovery; each entry binds an existing
rules prefix. Replay does not dispatch tools, run models or execute game actions.
Terminal artifacts include the host commit as well as the rules commit.

`primitive_lifecycle --cohort PATH verify-journal` performs an explicit stopped
audit and reports only the verified host/rules hashes. It does not recover pending
choices. Full reconstruction is an open-time/offline check; the live transaction
path appends changes without replaying the archive. Focused checks passed six
journal tests, nine campaign tests and nine lifecycle tests, including corrupted
state, interrupted transactions and a pending choice during audit.
The combined primitive suite passed 96 tests in 121.471 seconds
(`/tmp/edh-primitive-journal-suite.log`). A final focused regression also checks
that changing a numeric state value to a boolean cannot pass replay equality.

Source snoozes now accept exact primitive `{card_id,incarnation}` references and
bind their zone, controller and control epoch. Moved or control-changed sources
drop out. Current held/unheld candidates are marked in place on the unchanged
board. Required decisions clear the snooze and return to the pilot.

This host uses a conservative candidate inventory, not a complete legal-action
enumerator: visible nonbattlefield cards and battlefield ability/room sources
can remain candidates even when currently unusable. Automatic passing requires
every candidate to be explicitly held. This can produce extra pilot wakes but
does not infer that an unheld source is unusable. Visible stack sources are also
included. Legacy string UIDs are rejected; planner steps and ordinary decisions
share the same source validation before rules acceptance.
The final combined primitive suite passed 103 tests in 125.688 seconds
(`/tmp/edh-primitive-source-final.log`). The earlier source-suite run was stopped
and restarted after fixing an immutable-object test fixture; the final run above
contains the corrected fixture. Internal source-binding rows are omitted from the
pilot's scheduler projection to avoid duplicating its source references.

Next: reconcile `rules_admission` and `rules_launch_preflight`, whose static blocker
text still describes pre-migration capabilities. Admission must consume actual
current validation evidence and supported launch scope, not simply flip a flag.

Admission now checks an explicit local release receipt selected with
`EDH_PRIMITIVE_RELEASE_RECEIPT`. Produce it using
`PYTHONPATH=src python -m edh_gauntlet.primitive_release --output /absolute/fresh-receipt.json`.
The validator executes the entire repository suite, builds and installs a wheel
in an isolated directory, verifies installed assets, compares installed/source
fingerprints, and refuses publication if source or tests changed during the run.
The receipt binds Python/kernel identity, all package modules, fixed-pod assets,
policy documents and frozen strategy. It is local build evidence, not a whole-card
correctness certificate. Generic production factories remain closed.

With matching evidence, preflight supplies a primitive lifecycle command for one
fresh game with learning disabled. It never initializes a cohort or adopts a
legacy game. Unsupported multi-game/learning-enabled intents stay blocked.
Focused admission, launch and release-evidence checks pass. The complete release
validator is the next gate; no release receipt or hosted-model game exists yet.

Release validation completed successfully at runtime implementation 83edf6d:
2,835 repository tests passed, isolated installed assets verified, and installed
and source fingerprints matched. The receipt is
`/workspaces/Edhsimulator/archive/releases/primitive-host-20260915-a1.json`
(SHA256 `009aa748d550425cdac6e38f8be390311712c838caf415a342ad84dd75c4e84b`).
Selected with `EDH_PRIMITIVE_RELEASE_RECEIPT`, it produces a ready preflight for
`/workspaces/Edhsimulator/runs/primitive-hosted-test-20260915`; that directory has
not been initialized.

Ubuntu CI found one installed-layout test-path assumption: the release test used
the installed asset root to locate repository tests. The fixture now derives its
source root from its own file. All three release tests pass both locally and
against an isolated installed package (`/tmp/edh-ci-layout.log`). Runtime source
and assets are unchanged, so the release receipt still matches. Final CI on this
test correction remains required before merge and hosted-model gameplay.

Final Ubuntu/Windows CI passed on 3e08637 and PR #2 merged to main as
30ef03102291d95195df758498110e6de316d1b8. A fresh hosted-model game was initialized
at `/workspaces/Edhsimulator/runs/primitive-hosted-test-20260915`, seed 2026091501,
32-round horizon, learning disabled. It accepted one pilot decision before a
transport-reader exception stopped the host. Process metadata confirms inactive
transport generation 1 with contexts unloaded. Accepted prefix:
`1:b906887dfc333bb7529fee019ac6f7ed425528d43098b4928d8b1661742ac0a7`.

A reproduced telemetry defect hashes structured primitive inspection queries as
if they were strings. The fix records only bounded category names and also avoids
calling len on malformed proposal fields before tool validation. Two new tests
and 13 existing telemetry/performance checks pass. Work continues on
`fix/primitive-telemetry-inspection`. The game has not resumed or been replaced.
Because the host implementation is bound, next work must provide explicit checked
transport-repair compatibility while preserving its game contract, accepted
prefix, journal and logical seats. Do not bypass the binding or replay actions.
