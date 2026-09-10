# Rules reconciliation — 9 September 2026

The known historical rules work items are reconciled. This is an operator-authorized root adjudication, not an independent second-agent review or a learning pass. Learning remains disabled. The earlier general audit's broader implementation risks remain open; this does not certify the whole engine.

## Recorded decisions

- **Game 1: uphold Elenda's result.** The exiled Kalonian Hydra was already absent from actual blocker assignments and damage. The repaired combat context now agrees with those assignments. Public events 1287, 1299 and 1302 establish the relevant sequence. Replay reproduces all 253 choices, 2,550 events and the original terminal result. The pending rules review is complete; the terminal seal was not replaced.
- **Game 2: rules-affected draw after 110 accepted choices.** Body Double copying Uro did not escape and must be sacrificed. Choice 110 is the last pilot choice before the failed sacrifice; choice 111 was made from the incorrect battlefield. Matching menus through 154 choices was insufficient to establish informed pilot parity. Corrected replay through 110 puts Body Double and Animate Dead in the graveyard, then stops at choice 111. Root adjudicated a draw rather than inventing choices or a counterfactual winner.
- **Game 3: exact current-frontier parity.** All 155 accepted choices, the complete current public-state projection, and the pending question's actor, prompt, options, response type and choice bounds match the corrected replay. Its accepted tape, bound configuration and saved status were preserved.

Game two's original full 365-choice directory and terminal seal remain under `runs/first-dashboard-run/rules_reconciliations/fc5e028441782348d7dacb90ac504eaca597af072ea07c09a75c8139252f1ec1/original_game`. Its 255 later choices are invalidated on the canonical branch and preserved in that archive. The replacement draw has a new terminal seal, matching learning-skip receipt and `rules_reconciliation.json` provenance. Both game-two rules tags retain their repair histories and now reference the explicit operator review. No game was replaced with a new seed, and no learning was performed or removed.

The game-one pilot also incorrectly reasoned that exile would prevent The Ozolith retaining counters. The engine correctly gave The Ozolith eight counters in events 1289–1293; that was a pilot misconception, not another engine defect. Strategy was not changed under disabled learning.

## Correction tooling and display

Historical checkpoint and plan publications are now prevented from replacing the active game’s operator view. A regression test covers this; game three’s displayed plan was restored and rechecked in Chromium.

`tools/reconcile_sealed_rules.py` checks the original seal and tape, learning policy, completed repairs and explicit adjudication. Dry-run replay must reproduce the proposed prefix. Applying it archives the original game and root routing records; a failed/interrupted installation rolls back on retry. Repeated application of a committed response returns its receipt. The later active game's route and core artifacts are checked for preservation.

Cardwise caches now include rules-code and evidence signatures. A changed engine or adjudication cannot silently reuse old observations. Open rules reviews are excluded. The corrected draw is included only after its bound receipt and replay validate. Refreshed totals include game one and the game-two draw, with game three pending and no excluded completed games.

Validation: **76 tests pass**, release verification reports `ok: true`, corrected-game statistics reconstruct successfully, and current game-three board/menu parity is exact. The dashboard was restarted. The rules-audit hold is resolved; gameplay transport remains stopped at game three's pending decision 156. No new pilot action was submitted during reconciliation.

## Card-art board view feasibility

**High feasibility; use Scryfall first.** A live exact-name lookup for Body Double returned its card identity and working image URLs. Scryfall documents full-card images and art crops. Cache card identity/image metadata, load thumbnails only when visible, and use the existing board snapshot for tapped state, counters, power/toughness, attachments and copy labels. Fetches should run in the observer/dashboard path so art loading cannot delay gameplay or enlarge model context. Keep text fallbacks for unavailable images and ambiguous/custom tokens.

The lookup is straightforward; the larger UI work is arranging four readable battlefields, handling transformed cards/tokens/copies and displaying state changes without covering the card's credits. Full-card zoom and source links make details accessible. I did not verify a supported Gatherer API, so I would not make Gatherer the primary automated dependency.

Sources: [Scryfall API documentation](https://scryfall.com/docs/api), [card images](https://scryfall.com/docs/api/images), [exact-name lookup](https://scryfall.com/docs/api/cards/named), [Comprehensive Rules](https://magic.wizards.com/en/rules).
