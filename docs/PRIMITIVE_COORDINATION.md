# Primitive role coordination

This describes the new primitive host build. Started games retain their recorded
implementation and require explicit migration or a fresh cohort; source changes
never silently rewrite a bound game.

## Planning cadence

Each kept opening hand queues its own short- and long-term planners concurrently.
Short-term work starts from standing strategy and the actor-visible hand, with
long_term_validity pending until its frozen input contains a strategic goal.
Initial tactical prose should publish before optional inspections. Concrete action
proposals follow; an optional diplomacy_request can accompany that actions stage.
Combined prose/actions publication remains available when immediately ready.

After own cleanup, always queue short-term maintenance. At the opposite seat's end
step (two positions away in the current live-seat order), queue only if any
nonland battlefield or the planning seat's hand count differs from its last
claimed planning snapshot. No immediately preceding-seat gate. With fewer than
three survivors only own-cleanup maintenance remains. Python hashes stable ordered
object facts, split into lands/nonlands. Nonland tapping, counters, combat damage,
attachments and control changes count. Land changes, life totals, floating mana,
stack changes and opponent hand counts do not independently trigger this gate.
Skipped gates never advance the baseline. Planner-authored watches are unavailable.
Decider alarms and strategic invalidity escalation remain available.

## Authored diplomacy

The long-term planner supplies a standing brief: objective, disclosure_limits,
commitment_limits, allowed_recipients, and hold_authority (players, scopes,
max_turns up to four). The diplomat composes the actual words. Python enforces
recipient/hold structure; adherence of natural-language disclosures and commitments
is the diplomat's responsibility under the brief, not an engine truth oracle.
Every ordinary long-term publication requires a new diplomatic message, including
an unchanged goal. Optional addressed-message and tactical-request jobs may choose
silence. Reply chains are bounded to three addressed replies; no generic broadcast
reply cascade. Duplicates are rejected, not sent back to the strategic planner.

Each message privately supplies urgency 0/1, explanation, recommended_action and
truthfulness (truthful/deceptive/uncertain). Private assessments are exposed only
to the speaker's own decider, and use acknowledged record references to avoid
repeating prose. Public message payloads never include them. Routine speech leaves
batches intact. Urgent posted speech cancels remaining batches with an explicit
interruption notice and clears those batches' snoozes. No speech approves actions.

## Holds and overrides

Diplomats may restrain only their own seat, within delegated authority: attacks
against a named player and/or targeting that player's permanents. Holds include an
ID, negotiation ID, rationale, and bounded game-turn expiry. Python checks every
submitted/automatic step. Unrelated actions continue. A conflicting batch stops
before the offending step and reports why; executed steps are never replayed.

The decider can call edh_diplomatic_override with named holds and a rationale at
its owned decision. Override executes no action and does not wait for strategic
review. It releases the named holds, records evidence and queues one long-term
review per negotiation. That review triggers the ordinary new diplomatic message.
An overridden negotiation cannot automatically reimpose the same restraint.

## Brief changes without negotiation ping-pong

Diplomats negotiate autonomously inside the brief. They request strategic work
only to change that brief. The long-term planner has unconditional veto and first
publishes brief_decision (approved, rationale, and new brief if approved). Approval
immediately queues the diplomat with new authority; it need not wait for strategic
prose. The long-term planner then updates its strategy only if necessary. Set
update_plan:false on the authority decision to finish without redundant prose.
If the review was initiated solely by diplomatic requests, this final publication
does NOT trigger another diplomatic message. Independent strategic triggers and
hold overrides retain normal mandatory posting. Ordinary continuation never
repeatedly wakes the strategist.

## Direct plan context and self-contained tactics

Every new diplomatic job receives its own complete current long- and short-term
prose components directly, including their IDs and metadata. No separate summary
inference is used. The job remains frozen during its turn; later jobs capture new
publications. These plans may include private intent; receiving them does not
expand the brief's public disclosure permissions. Other seats' plans, raw private
hand/deck packets and decision rationales remain excluded.

Short-term plan prose must stand alone for a decider without earlier planning
history. Reuse still-applicable self-contained prose verbatim, or write the complete
replacement. Do not publish only differences or references to earlier plans.
Historical explanation belongs in continuity, not as a prerequisite for reading
the current tactical plan. Diplomats should add a real diplomatic contribution,
not a board recap or echo; optional work can choose silence.


## Telemetry follow-up from game g

Deciders prefer approving usable supplied action steps by ID and preserve planner
rationales. Direct sequences remain available for changed or absent proposals;
explain a mismatch in the existing action rationale, without an extra inference.
Executed or expired steps are rejected, never replayed. Deciders have no inspection
tool; all command schemas and current choice facts must be delivered directly.
Block assignments are an object mapping every exact attacker UID to blocker UID
lists, including empty lists for unblocked attackers.

Diplomats copy the complete public message ID for replies, not authorization IDs
or reconstructed names. Holds obey the brief's allowed players/scopes and absolute
game-turn expiry. Invalid references remain rejected rather than guessed.

Host telemetry retains per-role input-to-first-tool count, sum and maximum after
rolling event eviction. This measures the first tool after a real input, including
warm delivery, and excludes time spent holding a tool before that input. It is
neither complete planning-job duration nor proof that background planning blocked
gameplay. Aggregates describe one host process lifetime and reset on recovery.
