# Primitive host integration

The 2026-09-15 operator request authorizes local validation, reconciliation into
main, and a fresh hosted-model test. This document tracks the integration after
card authoring. Production admission remains closed until the entire path works.

## Fresh setup

`rules_setup.fresh_pod` constructs the fixed pod from reviewed catalog programs
and `data/decks/pod_configuration.json`. It validates 100 cards per deck, exact
commander occurrence and color identity. Setup is deterministic for its bound
seed, gives each seat 40 life, separates commanders, shuffles and deals seven.
It does not create a campaign, launch a model or convert a legacy game.

`rules_opening.OpeningRules` owns mulligans in the shared kernel. The starting
seat and then the other eligible seats declare before any hand is redrawn.
After each redraw, ordered bottom selections finish before another declaration
round. Multiplayer receives its first mulligan free; a zero-card hand cannot
mulligan again. Kept seats never reenter later rounds. Once all hands are kept,
the existing general opening-permanent choices lead into the first upkeep.
These choices use `answer` through the ordinary authenticated adapter and durable
receipt journal, including checkpoint and duplicate-delivery behavior.

Rules basis: [Comprehensive Rules, 2026-06-19, 103.5–103.6](https://media.wizards.com/2026/downloads/MagicCompRules%2020260619.pdf).
This is the fixed pod's ordinary Commander setup; it does not claim support for
Vanguard, shared-team turns or pre-mulligan card exceptions absent from the pod.
Kernel checkpoint schema is 133. Changed experimental checkpoints are rejected;
the paused legacy game's contract and accepted prefix are untouched.

## Actor-scoped inspection

`RulesActorAdapter.inspect` exposes `card_rules` only for a currently visible
object. It returns the current program and activation vocabulary, including
intrinsic mana abilities and copied/granted behavior. This describes rules, not
current action legality; atomic submission remains authoritative for timing,
targets and payment. Unknown and hidden references share the same rejection.
The durable wrapper fences stale writers and closed stores before inspection.
Read-only inspection never writes an accepted command or exports a checkpoint.

## Remaining launch requirements

- Bind the primitive durable store to a fresh campaign and authoritative
  NEXT_ACTION lifecycle, including pause, rules blockers, terminal seals and
  learning-disabled skip receipts. Preserve implementation and asset identities.
- Provide actor-scoped rules inspection and structured commands to hosted model
  contexts. Route only authenticated seats; retain exact accepted receipts and
  distinguish rejected choices from failures after acceptance.
- Connect the existing split-role scheduling contract: Terra-low deciders,
  Sol-high Fast tactical planning, Sol strategic planning and Luna-low diplomacy.
  Preserve independent seat/role lanes, planner publication, approved sequences,
  continuity, evidence visibility and local process watching.
- Exercise integrated replay, stop/recovery, phase/turn progression, private
  information boundaries and installed-package behavior before opening admission.
- Merge validated integration, initialize a new test cohort, follow NEXT_ACTION
  and verify hosted-model play actually begins. Never substitute a legacy run.
