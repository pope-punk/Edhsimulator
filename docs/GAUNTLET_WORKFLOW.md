# Gauntlet workflow

This is the campaign lifecycle authority. MANUAL_REFEREE_PROTOCOL.md defines in-game
rules authority; AGENT_ARCHITECTURE_V1.md defines current split role ownership.
Legacy desktop/contract examples are isolated in LEGACY_CONTRACTS.md and do not
change a current game's bound configuration.

## Initialize

Run the release gate, then initialize a new, empty cohort directory. Use
`--agent-architecture --async-diplomacy` for the current concurrent software host.
The defaults are contract 4, staged publication, static standing doctrine, batched
blockers/damage and full-turn proposals. Choose `--learning enabled|disabled` now;
missing settings on existing games preserve enabled learning. A run freezes deck
strategy, seed plans and messaging personalities. No source edit changes a frozen
started game or a claimed input.

Never overwrite an existing cohort or silently migrate a paused game. The
`planner_runtime enable-next-game` command applies only to unstarted games.
Model routing and context transport are described in HOST_RUNTIME.md.

## Follow NEXT_ACTION.json

After every lifecycle command, read the current NEXT_ACTION.json. Its action is
authoritative; an old prepared route is invalid after an intervening lifecycle change.

| Action | Required handling |
| --- | --- |
| dispatch_pilot | Let the registered isolated host seat decide. Root/coordinator never chooses for a pilot. |
| adjudicate_combo | Use the sealed request and an independent rules adjudicator; commit only its verified permitted response. |
| resolve_horizon_stop | Resolve the configured limit before continuing; a horizon stop is not a game result. |
| repair_rules_work_items / fix_release_blocker | Stop pilot dispatch. Preserve the tagged accepted prefix and record the rules issue. |
| postgame_review | Learning is enabled: review all four isolated evidence packets, then apply one consolidated response. |
| retry_learning_transaction | Retry that exact learn command before inspection, answering or advancing. |
| advance_game | Start the next scheduled game; discard all prior game's seat contexts. |
| none | Check the reason: cohort_complete and cohort_cancelled are different outcomes. |

The host handles gameplay only. It never silently learns, patches rules, creates the
next game or substitutes a default decision. Explicit pauses and cancellations
supersede all actions. Unattended hosts use approvalPolicy never and stop on an
unexpected approval request instead of asking a terminal.

## Current agent loop

Use one persistent isolated identity per seat and role, registered to that game.
Each seat has a decider, short-term planner, long-term planner and diplomat. The
software host routes directly through App Server. In concurrent mode it admits
one inference per role lane; waiting decider tools retain context without occupying
an inference lane. A pending long-term revision does not serialize tactical work.

Deciders reason about actual choices, inspect only actor-visible information and
submit their own structured answers. Contract 4 additionally supports explicit
pilot-approved symbolic batches (APPROVED_SEQUENCES.md). Python checks each choice
against the current legal menu and stops at the first execution boundary. New cards
may enter the pilot's acceptance through full added steps with rationale and snooze.
Root must never inspect another seat's private packet and then act as a pilot.

Static standing plans replace seed-summary inference. Long-term planners keep the
full seed/personality and initialize the goal as soon as the hand is kept. Short-term
planners retain standing doctrine and maintain continuity plus concrete actions.
Deciders retain standing until the initial goal arrives. Diplomats own all talk.

The two preceding living opponents' end steps trigger mandatory short-term updates
in fresh turn-batch games. Every update covers precombat, combat and postcombat.
An invalid goal triggers long-term work, while those mandatory tactical updates
still publish an interim batch. Completed long-term review always requires a
renewed diplomat message, including when the brief is kept unchanged.

## Pause, blockers and recovery

Stop pilot admission immediately on a user pause, missing authority or true rules
blocker. A recoverable rules defect is a tagged work item. An
UnrefereedDecisionError seals the accepted prefix as a tagged draw. Never replace
that game to hide the defect, and never use ordered future-library information.

For tests explicitly suspending hotfixes, record defects but do not patch during
play. True referee blockers still stop and receive their draw tag. Never reinterpret
a failed legality check as permission to invent a choice. Disabled learning does not
waive rules integrity or open-repair gates.

Only the host recovery tools may reconcile a known stopped transport. Validate the
owned process identity, exact accepted prefix, unloaded role contexts and any
unfinished receipt/journal. A normal opponent pass is not a reason to invalidate
an approved program. A rewind, changed game or private-information contamination
requires new contexts. See HOST_RUNTIME.md for exact stopped-host recovery modes.

## Completion and learning

A terminal seal binds the result, game configuration, accepted tape and frozen
strategy. Observer reports remain outside seat packets. CSV generation occurs after
the cohort's terminal lifecycle is complete; do not initialize an empty CSV before
play. A draw is a result; an unfinished or horizon-stopped game is not.

With learning disabled, Python writes `postgame_learning/skipped.json`, reports
`skipped_by_configuration`, omits learning evidence/response packets and leaves
strategy unchanged. The next game can advance normally when no rules gate blocks it.
The receipt is not a claim that an AI reviewed the game.

With learning enabled, the campaign remains locked while review is pending:

1. Read all four private evidence packets independently before combining conclusions.
2. Do not treat one pilot's hidden facts as another pilot's knowledge.
3. Review every deck against current notes, roles and packages.
4. Give each pilot changes, no_change or rules_blocker with a substantive rationale.
5. Consolidate supported declarative operations into the generated learning_patch.json.
6. Include every tagged rules issue in the skeptical synthesis and bound rules audit.
7. Run the exact learn command published by NEXT_ACTION.json.

An empty patch is valid only with an explicit reviewed no-change explanation and
four-pilot coverage. Rules facts belong in the referee/catalog, not strategy notes.
The atomic learning journal is prepared before changing the strategy bank. A crash
requires retrying the identical command, never generating a second patch. An applied
or no_changes receipt unlocks advancement without modifying the completed game's
snapshot. A rules-blocker response applies no strategy operations.

Cancellation preserves provenance and does not retroactively erase learning. A
terminal test with learning explicitly deferred is gameplay-complete but must not
be represented as a learned cohort. Operator-authorized archive cleanup is separate
from gameplay and happens only after hosts stop and release evidence is recorded.
