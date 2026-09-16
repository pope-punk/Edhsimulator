# Game N — quarantined rules-review draw

Game `web-campaign-20260916-n` ended at **1,490 accepted actions**, with no winner.
The engine sealed a `rules_review` draw; this is a failed hosted trial, not a clean
completed-game validation. Learning was disabled and skipped, not performed.

## Reported blocker

Reaminatour reported that Animate Dead's supplied rules program required a
creature-card target in a graveyard, but its attempted targeted cast was rejected
as having no target specification. The reported target was Leonin Relic-Warder.
This discrepancy still requires diagnosis and rules review. The report records
the pilot's complaint; it does not establish the engine defect's root cause.

## Evidence and lifecycle

- Build: `caff4fb`; seed: `2026091625`.
- Accepted-prefix SHA-256: `7249578c73cca71e53449f20651ae01c1e4f4e8d305f59a24e5048d8b2e50b17`.
- Configuration, complete command chain, head, host journal, terminal seal and
  learning-skip receipt passed the existing report integrity checks.
- The report eligibility gate then correctly rejected the game because rules
  review is pending. Cardwise CSV/JSON was therefore not generated.
- Host and transport exit were verified; contexts are unloaded. The game
  watchdog is stopped. The sealed game has not been resumed or replaced.
- `NEXT_ACTION` is `repair_rules_work_items`. Original local evidence remains
  preserved; this publication neither clears that gate nor changes the result.

[Terminal result and blocker](result.json)

## Follow-up work

The same branch contains bounded unfinished-publication continuations, visible
stack-source rules, clearer payment rejections and payment-stage documentation.
These changes were not applied to N midgame. Focused checks passed: 22 host tests,
one stack-visibility regression and 20 casting tests. Full validation was waived
by the user. The known reopen-test failure was reproduced on the unchanged
baseline. These checks do not resolve or validate the Animate Dead report.
