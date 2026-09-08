# Release validation — 2026-09-08

The final pre-cleanup regression suite passed **1,030 tests**, with no failures,
errors or skips, in 968 seconds. Tests covered referee behavior, campaign/learning
lifecycle, publication and handoff recovery, actor isolation, communication
reconstruction, context checkpoints, split-role scheduling and approved sequences.
The test code was then removed at the operator's explicit request.

The first full pass found 11 errors: ten outdated mock-fixture fields and one real
missing server binding in unused-transport recovery. Those were corrected; 94
focused checks passed, followed by the clean full-suite run. Optional learning
was verified for enabled review, disabled skip receipts, immutable existing-game
bindings, exact retry and two-game advancement without strategy writes.

The newer turn-batch policy passed execution/publication tests for two preceding
opponent end-step wakes, full three-phase coverage, interim tactical proposals
while strategic review runs, priority continuation, exact retry and rationale-only
overrides. This is behavioral test evidence, not a measured live speedup.

## Paused live trial

Game 1, seed 2026090805, remains paused after **305 accepted decisions**. No terminal
result or learning pass is claimed. The original configuration lacks turn_batches
and combat_proposals and has not been migrated. A checksummed preservation archive
and the original local cohort are retained for future hosted continuation.

Five complete telemetry segments cover the accepted prefix without gaps:

- Active host runtime: 4,311 seconds, excluding engineering/recovery downtime.
- Observed packet-to-submission time: median 4.39 seconds, p90 8.447 seconds
  (300 samples); this is not a full-game average or an internal inference clock.
- Cross-seat gap: median 9.48 seconds, p90 20.378 seconds (99 samples).
- Completed planner turns: median 56.72 seconds, p90 88.151 seconds (65 samples).
- 14 approved batches executed 19 planned steps, saving 5 separate submissions
  (1.64% of accepted decisions) under that game's older policy.
- Process-memory coverage: 72 samples, 42 unavailable. Unavailable is not zero.

A full regression run overlapped part of the live trial. These are descriptive
measurements, not a controlled speed comparison. Planner turns may contain multiple
inference requests and publication stages. Summed working sets can count shared
pages more than once.

At decision 303, Omo's newly checkpointed long-term context reached 64,341 input
tokens because all 53 inspected definitions were reinserted. Checkpoints now carry
at most 24,000 compact characters of recent definitions plus an explicit archive
index, while preserving seed, plan, role and deck memory. Omo's saved inspection
projection shrank from 105,582 to 41,988 characters; omitted definitions remain
actor-inspectable and cannot be falsely referenced as already delivered. This
passed focused tests. Only two further decisions ran before the operator paused;
sustained live confirmation remains outstanding.

## Distribution and limits

Source and installed-wheel release checks passed during preparation, including
asset discovery from outside the source checkout. GitHub CI runs installed-package
checks on Windows and Linux; it never starts model inference. See the repository's
Actions results for remote CI status.

`python -m edh_gauntlet verify` remains after cleanup. It checks catalog, deck and
strategy parity, registered action backing, printed stats and event visibility.
It does not replace behavioral testing or establish that every Magic interaction
is supported. Future changes need new focused validation.

The source and software release are published on GitHub; the no-login web dashboard is a design.
Cross-machine import of the saved game and live remote hosting are not certified.
See [GITHUB_HANDOFF.md](GITHUB_HANDOFF.md) for the required boundary checks.

After cleanup, four historical strategy source paths were made project-relative;
all other strategy fields and paused-game snapshots remain unchanged. The release
gate was rerun. The optional archive decryption helper separately passed full-game
roundtrip, tamper rejection and existing-output protection checks. No game evidence
archive was uploaded; both encrypted backup and key remain local by operator choice.
