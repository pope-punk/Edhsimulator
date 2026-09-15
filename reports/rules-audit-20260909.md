# Rules and runtime audit — 9 September 2026

Follow-up: the historical results and pending rules reviews have now been reconciled; see [the reconciliation report](rules-reconciliation-20260909.md). The pending-review descriptions below record the state at the initial audit.

The engine has systemic copy-handling defects. Body Double's Uro sacrifice ability **was created and resolved**, but the callback referred to a synthetic Uro permanent rather than the Body Double object actually on the battlefield. Its membership check failed and silently skipped the sacrifice. Game two's events 1030, 1039 and 1059 demonstrate the sequence; no corresponding Body Double sacrifice followed.

The implementation is a catalog-backed, card-specific rules engine, not a general interpreter of Oracle text. `Game.on_etb` dispatches through named handlers, and other abilities use additional name checks. Catalog coverage and the release gate must not be presented as proof of complete rules support.

## Repairs and regression coverage

| Finding | Change | Verification |
| --- | --- | --- |
| Copied ETBs captured a synthetic permanent | Dispatch effective copied characteristics using the actual battlefield object | Body Double/Uro sacrifice moves the physical Body Double card to its graveyard |
| Distinct incarnations could compare equal as dataclasses | Battlefield permanents use object identity | An old Uro trigger cannot sacrifice a newly returned Uro-copy with the same physical UID |
| Several copied death abilities checked printed names | Dispatch source's copied characteristics for those LTB/death handlers | Copied Solemn Simulacrum death draws a card and preserves Body Double's physical identity |
| Named ability lookup ignored copies | `perm` matches the copied name | A Body Double copying Grim Guardian is found as Grim Guardian |
| Copied secondary creature-entry abilities could be lost | Effective-name matching for those ETB observers | Copied Inspiring Overseer gains life and draws |
| Escaped Uro omitted its first trigger altogether | Always create the trigger; check escape when its effect resolves | Escaped Uro triggers but is not sacrificed |
| A removed reanimation Aura could still return its target | Check that the same Aura remains on the battlefield before resolution | Removed Animate Dead leaves its target in the graveyard |

Rules reference: [Theros Beyond Death release notes](https://magic.wizards.com/en/news/feature/theros-beyond-death-release-notes-2020-01-10), especially Uro's two ETB abilities; [Comprehensive Rules](https://magic.wizards.com/en/rules), including copying, zone changes and triggered abilities.

## Replay impact and lifecycle

- Game one still reproduces its terminal result: Elenda wins, 253 accepted decisions, 2,550 events in the tested replay.
- The repaired game-two replay reaches a different decision after 154 accepted choices. Its prior completed result is affected; a recoverable quarantine work item records the repairs and pending critical review. The final replay supersedes the interim 107-choice observation made during implementation. It has **not** been silently rewritten or certified.
- Game three reproduces its stopped 155-decision prefix in the tested replay. The host was already absent after the environment restart. It remains held for rules review; the dashboard is an observer only.
- Original sealed files, private evidence, learning configuration and accepted game-three choices are preserved. A general audit is not an independent post-game rules adjudication.

## Remaining risks requiring follow-up

1. **Hard-coded combo shortcuts:** `check_ream_combo` recognizes named battlefield combinations, and `attempt_combo_win` offers a restricted list of interaction spells. This is not equivalent to a complete legal demonstration with arbitrary interaction. The earlier invalid Felidar/Aura Spirit shortcut was one concrete example.
2. **Silent numerical caps:** examples include `min(lki_power,40)` in Elenda's Hierophant token creation and bounded draw/token counts elsewhere. These need exact aggregate representations or explicit unsupported-interaction stops, not silently smaller outcomes. This audit has not established that those caps changed these games.
3. **Aura legality and attachments:** the blink-entry repair covers the confirmed Animate Dead case, and this audit adds the removed-source guard. Protection, copied characteristics, illegal attachments, and all noncast Aura-entry paths still need broader integration coverage.
4. **Name-based rules outside the repaired paths:** other static, attack, upkeep and replacement-effect checks still use physical names. Some are intentionally about card identity; others require copied/effective characteristics. They need individual classification and tests, not a blind global replacement.
5. **Changing copied characteristics:** choosing a named graveyard card is not a complete implementation of copying another object's copiable values, text-changing effects, or layered ability removal. The current repairs are not a rewrite of that architecture.

This was a targeted general audit of copy identity, ETB/LTB execution, reanimation timing, shortcut assumptions, numerical caps, replay behavior and host metadata. It was **not** an exhaustive certification of every card, rule or state transition.

## Context and submission observations

The last retained host segment contains 4,096 timing events and 364 nonduplicate usage samples:

- Largest input: **72,365 tokens**.
- **25** samples at or above 64,000 input tokens. The checkpoint threshold is checked at eligible idle boundaries; it is not a strict maximum on every delivered input. Packet growth and long waiting conversations deserve follow-up.
- No repeated accepted decision IDs in games one, two or three.
- No repeated `tool_arrived` request IDs and no rejected tool returns in the retained segment. This does not prove that two different requests never contained equivalent text: full arguments are intentionally absent from telemetry.
- Game three has 14 saved public posts, including four extra occurrences of repeated same-author text. One text appears three times. This is stale/repetitive communication, not evidence of replaying an accepted gameplay action.

The dashboard now exposes a bounded runtime-health summary under Run record. It reads saved metadata; it does not wake models or inspect their transcripts.

## Operator display

The live table now emphasizes the current question, deciding seat, stack summary, published short-term plan, board cards and six recent accepted choices. Raw checkpoint JSON is under Run record. A separate Decision log presents accepted actions with optional rationale, preserving the current branch order; a full Markdown download is available. Published plans are explicitly labeled because an already-claimed decision may use an earlier version.

## Final validation

- All 71 unit/regression tests pass; the release verification reports `ok: true`.
- Final isolated replays produce the counts above without editing live accepted choices.
- Chromium desktop (1440 × 1080) and mobile (390 × 844) checks: decision and plan visible, decision log populated, full Markdown download successful, no JavaScript errors or horizontal overflow.
- Observer dashboard restarted on port 8765. Game-three host and supervisor remain stopped, with the rules-audit pause retained.
- Human-readable current-game export: `runs/first-dashboard-run/operator_logs/game_03_decisions.md` (private operator artifact; not pilot input).
