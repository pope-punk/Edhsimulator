# Completed-card reconciliation and hosted test

The current user request supersedes the completed authoring branch's stop:
validate and reconcile its work, merge the validated result to main, and begin
a fresh test game with hosted models. Preserve the paused legacy game.

## Provenance

The completed-card tip is f3db1acbb72dd8adb4f558d6cd8dc59c9e15fa38.
Its starting commit e9c94a41b722a15621a1ab6352e96e97ccc5f8a7 and the local
preservation commit 2970435 have the identical Git tree
16bde00a1707959024d7b12acadc9c5fd12b0220. The later branch therefore already
contains the local shared primitives and interrupted alternative-cost draft;
there is no unique local implementation to overwrite it with.

GitHub Actions run 34915167658 completed successfully at
108572c4eeacbb55635a0aaa30ade1eed50e04dc. The completed-card tip differs from
that commit only in two review documents and the inventory report. Its workflow
ran the primitive suite, syntax and installation checks on Ubuntu and Windows.
This is evidence for card authoring, not a production host certificate.

## Validation and remaining integration

The reconciliation workflow runs the entire repository suite, including host,
campaign and legacy tests, then retains newly generated coverage, readiness and
one-game launch-preflight reports for each platform. Refreshed readiness and coverage reports now describe all 334 authored cards
and 400 physical deck copies; none is advertised as production certified.
The user explicitly authorized local Python, validation and hosted-model host
processes in the Codespace on 2026-09-15, superseding the authoring branch's
GitHub-only execution restriction. Both local and hosted validation are permitted.

The current production admission function still unconditionally rejects, and
rules_launch_preflight has no production campaign/host adapter registered.
The software host still routes the legacy campaign. Connecting the new engine,
actor-scoped legal commands, planner scheduling, durable replay and fresh-game
initialization remains necessary before an actual migrated hosted-model game.
Do not merely remove the gate or silently launch the legacy engine.

Main has not been updated. No test game has been initialized. The existing paused
legacy cohort must retain its accepted prefix and contract throughout this work.
