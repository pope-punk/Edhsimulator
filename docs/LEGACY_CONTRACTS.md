# Replay compatibility reference

These historical desktop/contract-1 examples are retained for replay compatibility.
For current split software hosts, GAUNTLET_WORKFLOW.md, HOST_RUNTIME.md and
AGENT_ARCHITECTURE_V1.md take precedence. Legacy examples do not schedule current
planner/diplomat roles. Learning is required only when the run enables it.

## Revision 6: pilot isolation, scheduler, and review

New cohorts use decision surface 6. Already-started revisions 1–5 retain their
original option lists and passing semantics for deterministic replay. Do not edit
an active game's revision or retrofit its decision tape.
Turn-order presentation is also added to rebuilt legacy requests; it does not
change their legal options or replay identities.

The revision-6 next action is `dispatch_pilot`. The coordinator sees only the
actor, decision ID, and seat-specific handoff paths. Start one isolated sub-agent
per seat with no inherited conversation (`fork_turns="none"`), then reuse it for
that seat's later decisions in the same game and accepted branch. Give it only
its specified brief/context and actor-scoped inspection access. Return each
answer verbatim. A pilot may use `python -m edh_gauntlet.pilot_session --cohort
PATH --actor SEAT --response PATH` to submit one own-seat response and receive
the next compact own-seat update. Omit `--response` to read its current update.
The adapter never chooses actions or loops gameplay. It returns only handoff
metadata when the acting seat changes; the pilot must immediately return control
without opening that next packet. For a validated resume route, it first forwards
the exact generated prompt directly to the exact canonical incoming agent with
one `followup_task`, then reports `forwarded: true`; the coordinator owns all
fresh-agent creation but never relays a resume prompt. Before gameplay, clear
unrelated running or pending-initialization agents so the outgoing and incoming
seat can overlap within the host's activation limit. A capacity failure is fixed
by clearing the stale task and asking the outgoing pilot to retry its retained
route. A pilot can thus handle
consecutive own-seat choices within one work turn. `stop` and
`fresh_context_required` also return control immediately. Do not reuse a seat
agent after it has seen another seat or post-game evidence. For legacy games, use the same isolation
discipline with their actor-visible request; legacy serialization alone does not
prevent shared reasoning from leaking private facts.

Each handoff supplies a `seat_session` descriptor binding the cohort, game, seat,
and accepted prefix. Retain it with the seat agent and call
`pilot_handoff.can_resume_session(previous, root, game_number, actor, decisions)`
before any reuse. The registered dispatch path performs this check inside the
checkpoint; no separate coordinator command is needed on ordinary handoffs.
Follow `docs/PILOT_RUNTIME_POLICY.md`: initialize once, read the prepared private
update on resumption, continue from retained plans and facts, and directly forward
validated resume routing when another seat owns the decision. Register new agents
with `pilot_dispatch register`; adopt existing agents with `pilot_dispatch adopt`
using their saved descriptors. Preparation does not mark information as received;
the pilot's next submission or inspection acknowledges its `pilot_delivery_id`.
A false compatibility result requires a fresh context. Any rewind or rebase
also discards all existing seat contexts, even if a particular seat's older prefix
still matches. Game changes and private-input contamination require fresh contexts
as well. A recoverable rules work-item tag does not by itself invalidate compatible
seat contexts. Never transfer a review context back into gameplay.
New-agent routes automatically deliver a complete baseline. The legacy manual
adapter also supports `--fresh` once when starting a new isolated agent. Neither
mechanism permits keeping an old agent after a discarded branch or contamination.

`brief.md` shows turn order (including living seats, active player, acting pilot,
and next player), choices, response requirements, current state, current plan and
relevant notes. `context.json` is a bounded frontier snapshot containing the
structured current decision, literal actor-visible board state, public
messageboard, and that seat's branch-visible Short-Term and Long-Term plan
histories. It records only counts/hashes for provenance; it does not repeat the
event journal, accepted-decision prefix, full candidate-note bank, standing-plan
body, or card catalog. The append-only campaign journals remain the historical
sources of truth. Read the full seed when starting a seat context or if its seed
changes; at planning checkpoints review the retained plan against new information.
Previously established own knowledge may be retained without repeating inspection.
The session adapter now supplies the full frozen seed in its initial output and
again only if it changes. Treat that as the required seed read; a separate seed
command is unnecessary. Exact card text is intentionally not copied into every
planning packet. Use actor-scoped inspection for material uncertainty, retain the
result in the persistent seat session, and do not repeat established queries.
Inspect uncertain
card types, costs, Oracle text, targets, or timing before relying on them.
`inspect object` takes an exact visible object UID, not a card name. Use
`inspect card "CARD NAME"` for a name-based query; preserve those quotes when
passing the complete query as a string to an adapter.

For material questions left unanswered by the supplied information, batch
explicit inspection queries into one replay. Each query's result or error is
saved privately for review; an invalid query does not discard valid results.
The complete grammar is:

```text
object UID
card "NAME"
deck [zone=ZONE]
roles
role "ROLE NAME" [zone=ZONE] [mv<=N] [castable_now=true]
package "PACKAGE NAME" [zone=ZONE]
messageboard
```

`roles protection` is accepted as `role "Protection"`; role labels, aliases,
IDs, and slugs normalize to one cacheable query. `roles` prints the exact role
command for every represented role. Invalid queries return a copyable
correction. `castable_now=true` reads the referee's current legal decision
surface, including timing, targets, and payments; the pilot does not calculate
mana. Mana filters are optional. Append `detail=full` to an explicitly scoped
role or package query when the compact result is insufficient.

```powershell
python -m edh_gauntlet.pilot_session --cohort PATH --actor SEAT --inspect 'object EXACT_VISIBLE_UID' --inspect 'card "CARD NAME"'
```

Role results separate cards in actionable zones from the unordered library
outlook. The library section reports names, remaining counts, mana bands,
package routes, and relevant frozen learning. Use `zone=library` during opening
and long-term revisions, then retain the result in the persistent seat context.
No inspection returns future draw order.

Every planning checkpoint still requires the complete Short-Term replacement,
a Long-Term KEEP/REVISE choice and rationale, and a complete Long-Term replacement
on REVISE. Opening REVISE and the exact opponent-knowledge clauses remain
mandatory. Write concise execution instructions and match objectives; retain
all material contingencies without a narrative recap. On KEEP, do not rewrite
unchanged Long-Term text. The standing doctrine and full historical evidence
remain available, and plan limits remain 1200 characters each.

To remove a separate response-file tool call, pipe one explicit JSON response
envelope to `pilot_session --response-stdin`. For PowerShell, use a literal
single-quoted here-string containing the same `actor`, `decision_id`,
`pilot_context_id`, `pilot_delivery_id` from the prepared input, and `answer`
fields as the file workflow. Set console output
encoding with `$OutputEncoding = [System.Text.UTF8Encoding]::new($false)` before
piping, and run Python with `-X utf8`. The adapter saves `response.json` in the current
own packet and submits that exact answer. It does not choose values, supply a
scheduler default, combine future actions, or cross into another seat. Do not
combine `--response-stdin`, `--response`, or `--inspect` in one invocation. Both
submission paths preserve the existing validation and learning evidence.

The session adapter's compact update always includes current timing, turn order,
legal choices, response requirements, and scheduler state. It omits unchanged
state/plan/personality sections and may render exact line changes relative to its
identified previous own packet. Full briefs and bounded frontier contexts remain
available; accepted decisions, event journals, plan journals, current-request
snapshots, and inspection evidence remain separately retained for post-game review.
A new session receives a complete baseline. Material unknowns still require
inspection; established facts need not be repeatedly queried.

Every gameplay answer supplies its current `--pilot-context` identity and exactly
one appended scheduler directive. Scheduling is not a numbered gameplay option.
For example:

```powershell
.\gauntlet.cmd --cohort runs\example answer 2 --rationale 'Preserve the other source for interaction.' --hold_full_control --pilot-context CURRENT_CONTEXT_HASH
.\gauntlet.cmd --cohort runs\example answer 0 --resolve_my_sequence --pilot-context CURRENT_CONTEXT_HASH
.\gauntlet.cmd --cohort runs\example answer 1 --rationale 'Advance the selected line.' --snooze_table '{"time":"1 beginning of upkeep","wake_condition":"opponent_spell"}' --pilot-context CURRENT_CONTEXT_HASH
.\gauntlet.cmd --cohort runs\example answer 0 --snooze_objects '{"objects":["EXACT_OBJECT_UID"],"time":"2 end of combat","wake_condition":"targeted_or_attacked"}' --pilot-context CURRENT_CONTEXT_HASH
```

`--resolve_my_sequence` replaces stack snooze in new pilot-facing instructions.
It is a snooze: pass optional priority through my spell and its resulting triggers
or abilities; wake for another player's new stack action, a required choice, or
sequence completion. A directive replaces the seat's
previous directive and is required even on target, trigger, combat and mulligan
answers. Hold full control restores all legal opportunities. Table snooze passes
optional decisions until its time boundary or wake condition. Object snooze
suppresses only optional priority actions sourced by the named actor-owned UIDs;
zone/control changes invalidate those entries. Resolve my sequence spans the
initiating spell/ability and its synchronous generated trigger chain, including
temporary empty stacks during resolution. Opposing spells, abilities and triggers
wake the seat. It ends when the outer resolution finishes and no stack remains.
Historical `snooze_stack` / `-snooze_stack` inputs remain accepted with their old
empty-stack/new-spell semantics; accepted tapes and pending packets are not rewritten.
A mandatory choice wakes the seat; no mode chooses targets,
payments, required attackers or other mandatory choices for it. Being attacked
always wakes the defending seat.

The compact feed delivers the scheduler and inspection legends at initialization
and whenever their content changes. A compatible resumed pilot retains those
semantics. Only acknowledged deliveries establish this knowledge; preparation
does not. Legacy sessions receive the legends on their first updated delivery.
Current scheduler state and the requirement for one directive remain explicit
on every decision, as do all current planning and response obligations.

Times count future occurrences of `beginning` or `end` of upkeep, draw, precombat
main, combat, postcombat main, or end step. They are table-wide game boundaries,
not the pilot's own turn and not wall-clock time. Wake conditions are
`opponent_spell`, `opponent_action` (including stack-added abilities/triggers),
`any_spell`, `targeted_or_attacked`, and `deadline_only`. The last condition still
cannot suppress mandatory choices or defending against an attack. Scheduler
telemetry is private; avoided-decision counts require an actual legal option.

At terminal review, schema-3 evidence retains each accepted pilot request bound
to the exact handoff hash only through a bounded schema-4 review projection. It
retains compact actor-visible state for planning, rules, scheduler and terminal
anchors; aggregates routine mechanical events with counts and hashes; and refers
to content-addressed inspection payloads on demand instead of embedding them.
The generated patch centers each pilot's Short-Term and Long-Term plan outcome and
card-level assessments: what each observed card did under that plan, whether it
worked, and whether reusable card guidance is warranted. Detailed six-field
decision review is limited to the listed high-signal anchors. The validator still
enforces all anchor, card, topic, note and rules-issue coverage and seat-valid
citations. The external reviewer assesses strategic and rules correctness, and
its context is never reused for gameplay.

## Rules work items and quarantine

Record every material rules defect against each affected game. The default
severity is recoverable:

```powershell
.\gauntlet.cmd --cohort runs\example quarantine --games 4,6 --reason 'Exact rules defect and affected boundary.'
```

This creates `rules_work_items.json` in each game and a durable registry entry.
The game, every subsequent pilot handoff, all four private evidence packets, and
the consolidated learning template carry a prominent `RULES-AFFECTED GAME` tag.
A recoverable issue may remain in the current game; rewind the affected branch
when correction requires it, otherwise continue from the referee's legal current
state. It never forces replacement of that game.

After repairing and regression-testing the engine, record the repair:

```powershell
.\gauntlet.cmd --cohort runs\example repair-rules --game 4 --summary 'Exact repair and regression coverage.'
```

The temporary quarantine remains until post-game learning reviews every tagged
issue separately for every seat and supplies one consolidated impact and learning
treatment. Learning may retain only conclusions supported independently of the
incorrect resolution. A completed skeptical review releases a recoverable game.

`UnrefereedDecisionError` is the game-breaking threshold. The referee rejects the
uncommitted action, seals the last accepted prefix as a draw, creates a
`game_breaking` work item, and stops pilot dispatch. After repair and skeptical
learning, that draw remains marked `quarantined` within the cohort and the next
scheduled game starts. The draw occupies its original game number; no replacement
game is inserted.

For a defect discovered during post-game review, a `rules_blocker` disposition
performs the same draw conversion and regenerates the four evidence packets with
the rules tag. Repair the work item, then complete the regenerated skeptical
review. For an already-learned historical game, the registry also preserves bound
application hashes and operations. Unreviewed published learning blocks new games
and learning promotion, including from a different cohort.

An independent rules reviewer examines every bound published operation against
Oracle text and the rules, then supplies:

```json
{"quarantine_key":"KEY","review_fingerprint":"HASH","operations":[
  {"index":1,"verdict":"retain","rules_basis":"Specific card interaction and rules basis"}
]}
```

Repair the engine first, then apply with `review-quarantine --response PATH`. Use `remove` for an inconsistent
added note: the command excises that exact unlocked note from the live bank,
without adding editorial replacement text. Changed or locked notes fail closed.
Non-note reversals require an explicit corrective strategy patch before releasing
the work item. Retained learning is rules-revalidated independently. Recoverable
games are released; game-breaking draws remain tagged quarantined within their
cohort. An interrupted bank/registry commit is finished using
`recover-quarantine`. A prepared ordinary learning transaction still has priority:
retry its exact `learn` command first, then quarantine the committed result.

New card/package notes also carry source cohort and review ID; the learning
application retains provenance for every operation. Handoff hashes bind context
and reject stale packets. They cannot prove that a reasoning agent has not read
other files: isolated seat contexts and restricted inputs are required.

This is the authoritative end-to-end operating contract for every gauntlet game,
including smoke tests. `MANUAL_REFEREE_PROTOCOL.md` governs in-game rules and
information boundaries; this document governs the campaign lifecycle.

## Ownership

The external pilot makes every material strategic decision. Python is the
deterministic referee: it realizes the seed, validates choices, resolves supported
rules, reconstructs checkpoints, emits evidence, and enforces lifecycle gates.
It does not choose plays or invent post-game lessons.

The post-game reviewer is a separate reasoning pass by the external pilot. The
repository cannot spontaneously launch an agent, so it exposes the required work
through `NEXT_ACTION.json`, a sealed review request, and generated instructions.
An operating agent must follow that contract before treating a game as finished.

## Required lifecycle

```text
playing
  -> optional unanimous combo shortcut
  -> rules adjudication pending
  -> validated adjudication replay, then playing or terminal game
  -> terminal game
  -> post-game review pending (campaign locked on that game)
  -> learning applied OR explicit no-change review recorded
  -> next game, or cohort complete after the final review
```

The state has three independent axes:

- gameplay: `need_decision`, `awaiting_combo_adjudication`, legacy `release_blocker`,
  `horizon_stop`, or `complete`;
- post-game review: `not_ready`, `pending`, `rules_blocker`, `applied`,
  `no_changes`, or `legacy_waived`; and
- persisted campaign: `active`, `awaiting_review`, `blocked`, or `complete`.

For operator clarity, `NEXT_ACTION.json` projects that persisted state plus the
current checkpoint into a more specific `cohort_state`: `playing`,
`awaiting_combo_adjudication`, `awaiting_review`, `blocked`, `ready_next`, or
`complete`.

Gameplay completion alone never advances `active_game`. The next game's frozen
strategy snapshot is created only after the preceding review has been resolved.
A smoke test uses the same gate and may legitimately end in a reviewed no-change
patch.

The editable private seed plans live at:

```text
data/strategy/gameplan_seeds/
  reaminatour.md
  minsc_and_boo.md
  omo.md
  elenda.md
```

A newly initialized cohort snapshots all four files together. That immutable
snapshot, not later edits to the source Markdown, supplies private starting-plan
context throughout the cohort and is bound into each game configuration and
private evidence. A legacy cohort that has no seed-plan snapshot adopts the
current four files only when `advance` begins its next unstarted game. Adoption
never modifies a game that has already started or reached a terminal seal.
Status, inspection, and draw adjudication refuse to start an untouched game, so
they cannot adopt the editable files before that explicit advance boundary.

Editable messaging personalities use the parallel source directory:

```text
data/strategy/messaging_personalities/
  reaminatour.md
  minsc_and_boo.md
  omo.md
  elenda.md
```

These Markdown files are templates for voice, political style, bargains,
bluffing, tells, and boundaries in public table talk. A new cohort snapshots all
four together in `messaging_personality_snapshot.json`; that exact revision is
bound into each game and sealed with it. Editing a source file after cohort
initialization therefore affects a later cohort, not the active one. A legacy
cohort without this snapshot adopts the current four files only when `advance`
begins its next unstarted game, under the same no-retrofit boundary as seed
plans.

An operator may explicitly refresh the four profiles for the active, unfinished
game only. This is a deliberate exception, recorded in that game's
`messaging_personality_refreshes.jsonl`; it replaces the active game's snapshot
for future table-talk decisions and never changes a completed game's sealed
copy:

```powershell
.\gauntlet.cmd --cohort runs\fresh20 refresh-messaging-personalities
```

Existing schema-1 cohorts are migrated without rewriting history. Only a completed
game with a structurally valid, committed transaction-backed learning audit can
become `applied`; other past completed games become `legacy_waived`. A legacy
waiver is sealed and cannot accept a new unbound learning patch. The recorded
`active_game` is preserved.

## The machine-readable next action

Every campaign command maintains `<cohort>/NEXT_ACTION.json`. Read it after each
command and do exactly the named action:

- `answer_decision`: inspect `STATUS.md` and answer the current request;
- `adjudicate_combo`: review the bound combo request, complete its response file,
  and run the exact published `adjudicate-combo` command;
- `postgame_review`: perform the generated review and apply its patch;
- `retry_learning_transaction`: retry the exact named `learn` command; no gameplay
  operation may proceed until its prepared journal commits;
- `repair_rules_work_items`: repair and regression-test every listed issue before
  learning; a game-breaking issue has already ended that game as a draw;
- `fix_release_blocker`: legacy fallback when a blocker occurs too early to
  reconstruct even a draw checkpoint;
- `resolve_horizon_stop`: obtain an explicit decision about the configured limit;
- `advance_game`: run `advance` to create the next game checkpoint;
- `none`: the reviewed cohort is complete.

`NEXT_ACTION.json` is the authoritative continuation signal. Narrative text is
for humans and must not be used to bypass its gate.

## Start or resume

Create a cohort once:

```powershell
.\gauntlet.cmd --cohort runs\fresh20 init --games 20 --seed-start 2026090201 --max-rounds 16
```

Then resume from the recorded next action rather than assuming which game or
decision is active:

```powershell
.\gauntlet.cmd --cohort runs\fresh20 next
.\gauntlet.cmd --cohort runs\fresh20 status
```

An operator may explicitly terminate an unfinished cohort while preserving every
accepted tape row and checkpoint. Cancellation creates `CANCELLATION.json`,
publishes terminal `NEXT_ACTION.json` state, skips all remaining games and
post-game learning, and blocks later gameplay or learning commands:

```powershell
.\gauntlet.cmd --cohort runs\fresh20 cancel --reason "Operator ended this cohort"
```

Cancellation remains terminal unless the operator explicitly reinitializes that
same preserved cohort. Reinitialization reruns the full release gate, verifies the
active checkpoint still exactly matches its cancellation audit, writes an
append-only reinitialization record, and restores only the authoritative pending
lifecycle action. It does not alter or replay accepted decisions, terminal games,
or review state:

```powershell
.\gauntlet.cmd --cohort runs\fresh20 reinitialize --reason "Engineering work completed; resume the preserved campaign"
```

## Pilot loop

For `answer_decision`:

1. Read the redacted `STATUS.md` and request for the named seat.
2. Use only that seat's legally visible information.
3. Make the strategic choice and record a concise rationale.
4. Submit the choice. The referee replays the complete accepted tape from the
   original seed, reconciles exact state, and commits only a valid checkpoint.
5. Read the new `NEXT_ACTION.json` and continue.

At the top of every pending decision, `STATUS.md` identifies the round and turn,
whose turn it is, the pilot making the decision, the current phase/step, and the
exact decision window or transition. It also renders the complete actor-visible
stack in top-first resolution order, or states explicitly that the stack is
empty. Do not infer the active player from the priority holder.

```powershell
.\gauntlet.cmd --cohort runs\fresh20 answer 1 --rationale "Keep: functional mana and early interaction"
```

Choice numbers are one-based. Choice `0` is legal only when the request lists
`PASS`. Connected plays are made as several atomic answers, not as an unverified
future-action script.

Revision 5 puts object schedules in the same numbered priority answer. Choose
`PASS ON OBJECTS` and repeat `--pass-on` for every object to suppress:

```powershell
.\gauntlet.cmd --cohort runs\fresh20 answer 4 --pass-on "UID-A=1 beginning of upkeep" --pass-on "UID-B=3 end of combat"
```

The batch must contain at least one UID and is atomic: duplicate, stale, foreign,
or ineligible UIDs reject the answer before replay commits anything. Revision 1–4
started games retain the older `pass_on_schedule` typed follow-up after selecting
`PASS ON <object>`. Both forms use this compact grammar:

```text
N beginning|end of PHASE
```

`N` is an integer from `1` through `1,000,000`, and `1` means the next matching
boundary. Supported names are
`upkeep`, `draw`, `precombat main`, `combat`, `postcombat main`, and `end step`.
The count is pod-wide and advances only when that beginning/end boundary actually
occurs. For example:

```powershell
.\gauntlet.cmd --cohort runs\fresh20 answer "1 beginning of upkeep"
.\gauntlet.cmd --cohort runs\fresh20 answer "3 end of combat"
```

On a revision-5 spellcasting choice, append `--autoresolve` to automatically pass
the caster's priority on that stack only when the spell was cast onto an empty
stack. Opponents still receive priority; a new spell wakes the caster.

On a revision-5 postcombat-main PASS, use either:

```powershell
.\gauntlet.cmd --cohort runs\fresh20 answer 0 --snooze-all
.\gauntlet.cmd --cohort runs\fresh20 answer 0 --snooze-all --until "2 beginning of upkeep"
```

The omitted deadline wakes at the end step of the living player immediately
before that pilot's next turn. An attack wakes the defender for responses and
blockers. Mandatory choices also wake the pilot; only optional/passable decisions
can be safely inferred as passes.

If the pending actor has live passed-on objects, every decision type also exposes
the private `MANAGE PASS-ONS` auxiliary action. The structured list gives each
source's exact UID and zone, its canonical wake condition, and the number of
matching boundaries remaining. Review it without consuming the request:

```powershell
.\gauntlet.cmd --cohort runs\fresh20 pass-ons
# Equivalent review from the decision interface:
.\gauntlet.cmd --cohort runs\fresh20 answer "MANAGE PASS-ONS"
```

The same private manager can cancel one exact object, cancel every currently
listed object, or replace one wake schedule:

```powershell
.\gauntlet.cmd --cohort runs\fresh20 pass-ons --unsnooze Omo-Senseis-Divining-Top-0001
.\gauntlet.cmd --cohort runs\fresh20 pass-ons --unsnooze-all
.\gauntlet.cmd --cohort runs\fresh20 pass-ons --reschedule Omo-Senseis-Divining-Top-0001 --wake "2 end of combat"
```

Review is read-only. A cancellation or reschedule changes future prompting, so it
is validated by a candidate replay and retained as a pre-answer control on the
still-pending request. The same decision ID is rebuilt after every change. When
the gameplay choice is finally answered, its control list is stored in that
ordinary decision-tape row; rewind/rebase therefore discards it with its anchoring
decision rather than managing a separate scheduler journal. `--unsnooze-all`
stores sorted concrete UIDs, never an open-ended instruction.

These controls suppress the passed-on object by default until its scheduled wake
boundary, explicit unsnooze, a zone/controller change, or an opposing spell that
targets the player or a permanent they control / an attack against that player
or their planeswalker. If a different,
unsuppressed object otherwise opens a priority prompt for that pilot, the prompt
offers a private `WAKE` control for each snoozed object. Choosing it clears that
object's pass and reopens the pilot's current priority choice; it does not rewind
the game or interrupt the current stack object. Expired boundaries and
zone/controller changes prune stale entries automatically. Only the pending actor
sees the list and its audit events. A displaced/rebase decision is review-only
until its replacement answer is committed.

On the revised decision surface, `CONCEDE` is appended only to priority and
specialized response requests that were already going to be shown. It is not a
modeled instant-speed action and never causes a no-action seat to receive a new
prompt. Legacy started games retain the former passable upkeep concession
request. Concession uses the ordinary multiplayer player-leaves-game and
last-player-standing rules.

Inspection is out of band: it neither consumes priority nor changes the decision
tape. A pilot may inspect a visible object, its own unordered deck accounting,
its represented roles, or a package. Inspection never reveals future draw order.
Every material decision carries a compact inspection reminder, so a newly
initialized pilot does not need to remember the capability from an earlier
decision. Revised requests deliver at most three matching private card notes in
one structured section; they are not duplicated inside `seat_view`.

Full inspection results are stored once under `inspection_evidence/` by their
content hash. `inspections.jsonl` is append-only and contains only the query,
actor, decision, result kind and hash, evidence reference, and compact catalog
and memory identities. Identical normalized queries on the same accepted branch
reuse the stored result. Post-game evidence resolves those references for the
same actor, preserving complete private review evidence without expanding the
audit log.

```powershell
.\gauntlet.cmd --cohort runs\fresh20 inspect object R-42
.\gauntlet.cmd --cohort runs\fresh20 inspect roles
.\gauntlet.cmd --cohort runs\fresh20 inspect role "Removal" zone=hand
.\gauntlet.cmd --cohort runs\fresh20 inspect 'role "Protection" mv<=3 castable_now=true'
.\gauntlet.cmd --cohort runs\fresh20 inspect messageboard
```

New cohorts bind decision-surface revision 6. Revisions 2 through 5 remain replayable for
already-started games. Every material revised request
automatically receives `private_active_plan`, a bounded deterministic projection
of the acting pilot's immutable seed snapshot and branch-visible dynamic journal.
It is regenerated at request decoration and is never stored as an independently
mutable strategy source. No plan text enters public state, message events,
another pilot's request, or another pilot's evidence. Existing started games
without a revision binding remain revision 1 and retain the one-time opening
delivery; they are never retrofitted.

Every pending decision presents the private `GAMEPLAN` auxiliary action beside,
not inside, the numbered gameplay options. Invoking it with no rationale returns
the acting pilot's complete immutable seed plan plus every branch-visible journal
entry for that query. Eligible plan-only writes retain their existing behavior.
In a revised game, an ordinary strategic answer may instead supply
`--plan-delta`; this does not replace the gameplay rationale.

```powershell
.\gauntlet.cmd --cohort runs\fresh20 gameplan
.\gauntlet.cmd --cohort runs\fresh20 gameplan --write "Keep two mana available for interaction"
.\gauntlet.cmd --cohort runs\fresh20 gameplan --write "Preserve the land engine as the primary win route" --scope long-term
# Equivalent append from the decision interface:
.\gauntlet.cmd --cohort runs\fresh20 answer GAMEPLAN --rationale "Keep two mana available for interaction"
# Optional gameplay answer plus private update on revisions 2 and later outside a checkpoint:
.\gauntlet.cmd --cohort runs\fresh20 answer 2 --rationale "Advance the board" --plan-delta "Hold interaction for the current leader after developing."
.\gauntlet.cmd --cohort runs\fresh20 answer 2 --rationale "Advance the board" --plan-delta "Become the control seat until the combo deck is contained." --plan-scope long-term
```

There is one append-only dynamic journal per pilot per game. The seed plan remains
a separate immutable snapshot; it is never rewritten as a dynamic entry. The
Standing Plan is reusable deck-piloting doctrine rather than a match objective.
A dynamic entry is scoped as `short_term` (the default: direct execution guidance
synthesized from current status, inspections, and recent rationales, including
sequencing, timing, targets, combat, interaction, and hazards) or `long_term`
(the determinate current match goal: primary route or development objective,
posture toward each opponent, plausible future branches, and observable pivot cues).
Legacy unscoped entries are interpreted as short-term. The active projection
renders long- and short-term sections separately.
A private `GAMEPLAN` query returns only the pending actor's seed and branch-visible
journal. The active projection carries source hashes/counts and body-free
delivery telemetry. An inline delta is committed only after its candidate
gameplay replay succeeds; the tape stores its ID, size, and hash rather than its
body. Rewind and successful rebase remove entries that depended on the discarded
future branch, retaining only a count and digest in the rejection audit; the seed
snapshot is unchanged. At game end, each
private post-game evidence packet receives only that packet's pilot seed plan and
dynamic journal, with the seed recorded as `private_seed_gameplan` and snapshot
provenance bound by the terminal review artifacts.

On revision 3 and later, the first card each pilot draws during every turn latches one
private planning checkpoint. Further draws by that pilot in the same turn do not
add checkpoints. The checkpoint creates neither priority nor a standalone
decision: it attaches to that pilot's next externally presented decision,
including a decision on another player's turn. The request binds the frozen seed;
the persistent runtime supplies its body only for a fresh/changed seat session and
otherwise relies on the previously verified copy. The checkpoint requires one atomic response containing the gameplay
choice, a complete short-term replacement, and a long-term `keep`/`revise`
review with a private rationale. A revision also requires the complete replacement
long-term plan:

```powershell
.\gauntlet.cmd --cohort runs\fresh20 answer 0 `
  --short-term-plan "Pass this window, then develop the best colored source." `
  --long-term-action keep `
  --long-term-rationale "The draw improves execution but does not change the durable route."

.\gauntlet.cmd --cohort runs\fresh20 answer 2 --rationale "Cast the engine now." `
  --short-term-plan "Resolve the engine, then hold interaction." `
  --long-term-action revise `
  --long-term-rationale "The new engine makes the value route more reliable than combat." `
  --long-term-plan "Use the value engine as the primary route and preserve the compact combo as backup."
```

The short-term and revised long-term texts are replacement snapshots in the
active projection; their append-only journal history remains available for audit.
`GAMEPLAN` remains queryable, but an out-of-band write cannot satisfy this gate.
Revision-2 games retain their original once-per-own-main-phase long-term update.
On revision 4, the checkpoint on each pilot's first own turn requires `revise`,
not `keep`. Its complete replacement Long-Term Plan must name a posture toward
every living opponent as well as the current route, alternatives, and pivot cues.
Because one external operator may pilot every seat, each opening opponent clause
must begin `OPPONENT: strategy unknown beyond public information`. Any additional
posture may use only that pilot's actor-visible request and public game history;
another pilot's private seed, hand, inspection, gameplan, or unrevealed decklist
knowledge is forbidden. The campaign publishes and validates the exact required
clauses in the planning checkpoint.

Revision 3–5 compatibility requests carry the same pilot's prior decision
records. Revision 6 frontier packets deliberately omit those transcript bodies;
accepted rationales remain in the decision journal and strategic continuity is
carried by the Short-Term and Long-Term plan histories. Rewinds and rebases prune
discarded plan continuity rather than leaking it into the replacement branch.
Gameplay rationale is mandatory for
spellcasting choices, activated-ability target choices, and trigger ordering;
it is optional elsewhere.

At every pending decision, both the rendered seat view and structured public
state report modeled mana availability for all players. `total` is simultaneous
spendable capacity; the `W/U/B/R/G/C` figures are independent maxima and can
overlap when a source is flexible. They are derived from the same source model
used by payment validation.

## Public messageboard

On revision 3 and later, every main-action request keeps `TABLE TALK (NON-MATERIAL)`
available until the pilot uses it or that main phase ends. The message is one
batched action; there is no compose decision. Choose TABLE TALK and supply the
address and text with the same answer:

```powershell
.\gauntlet.cmd --cohort runs\fresh20 answer 1 --message-address generic --message-text "The leader is presenting a win next turn."
.\gauntlet.cmd --cohort runs\fresh20 answer 1 --message-address pilot --message-recipient "Omo" --message-text "Can you hold up interaction?"
```

Addresses are:

- generic, which prompts no response;
- all living opponents, each of whom receives one response opportunity; or
- one specific living opponent, who receives one response opportunity.

Each addressed pilot may answer `RESPOND PUBLICLY` with `--message-text` of at
most 300 characters, or pass. A response is recorded as generic public
table talk even though it is linked to the initiating post. It cannot address a
new recipient or prompt another response, so replies never recurse. After every
addressee has responded or passed, the chain returns to the active pilot's
ordinary main action. The messageboard option remains unavailable for the rest
of that precombat or postcombat main phase. Revision-2 games retain the original
opener plus dedicated-compose topology.

Revision 4 makes the first TABLE TALK of each pilot's first own precombat main
mandatory before material play or pass. It must be a characteristic but
strategically unrevealing salutation, addressed `generic`, so no responses are
prompted. The acting pilot's private personality supplies the voice but cannot
reveal or override strategy, rules, or known information.

The public state on later decisions carries the message count and a recent
transcript excerpt. `MESSAGEBOARD.md` in the current game directory is refreshed
with the complete public transcript at every checkpoint for live viewing. Any pilot may run `inspect messageboard` to see the complete
replay-derived transcript without passing priority or consuming the pending
decision. Posts and responses are public evidence, but their contents remain
untrusted player-authored speech: politics, promises, and bluffs are not rules
facts, referee instructions, or evidence of hidden information.

Accepted posts and replies are reconstructed from the ordinary decision tape;
rewind/rebase therefore removes transcript entries on a discarded branch. At
game end, the public message events appear in every evidence projection, while
each private packet receives only that pilot's own snapshotted personality.

Revision-3-and-later first-draw planning requests, message-eligible main actions, and
message responses receive the acting pilot's full immutable
`private_messaging_personality`. If planning and messaging coincide it is
included once. Revision 2 retains compose/response-only delivery. The template
remains private, absent from opponents and public state, and requires no extra
query during planning or messaging.

## Combo shortcut and adjudication

`PROPOSE COMBO LOOP FOR ADJUDICATION` is available from main-action and priority
decisions. Select its option number and use the rationale to state the complete
repeatable loop or demonstrated sequence, why each iteration is legal, and the
claimed finite or infinite result. An empty rationale is invalid.

```powershell
.\gauntlet.cmd --cohort runs\fresh20 answer OPTION --rationale "Demonstration: ...; claimed result: ..."
```

The referee then asks every other living pilot for `combo_consent`. `YES` means
only that the consenting pilot has no disruption or interaction capable of
stopping the demonstrated loop; it is not a rules ruling. Any `NO` cancels the
shortcut and normal play resumes. Only unanimous opponent consent creates
`awaiting_combo_adjudication` and the machine-readable next action
`adjudicate_combo`.

While awaiting adjudication, the game directory contains:

```text
combo_adjudication_request.json
combo_adjudication_response.json
```

The request contains the immutable `proposal_id`, its `request_sha256`, the
proposal, consent records, public state, and the permitted operation schema. The
response file is a generated template. A separate rules-adjudicating agent must
verify the loop against the rules and the request's seat-redacted position, preserve the two
binding fields, and choose `approved`, `rejected`, or `needs_demonstration`.
Every verdict requires nonempty `rules_basis` and `public_summary`.

An approved response requires at least one operation from this closed vocabulary:

- `{"op":"damage_player","player":"Elenda","amount":"infinite"}`;
- `{"op":"set_life","player":"Omo","value":1000000}`; or
- `{"op":"bounce_permanents","players":"all"|"opponents"|["NAME",...],"uids":["UID",...]}`.

For `bounce_permanents`, omit `uids` to return every permanent in the selected
scope to its owner's hand. A `rejected` or `needs_demonstration` response must use
an empty `operations` list. Unknown fields, stale identifiers/hashes, invalid
players, duplicate operations, and out-of-scope UIDs fail closed.

Run the exact command in `NEXT_ACTION.json`; its shape is:

```powershell
.\gauntlet.cmd --cohort runs\fresh20 adjudicate-combo --game N --response runs\fresh20\game_N\combo_adjudication_response.json
```

The campaign validates the response, candidate-replays it against the accepted
decision tape, and only then commits it to `combo_adjudications.jsonl`. Approval
applies the declared damage, life, and bounce operations and then checks state-
based actions and invariants; a bounced commander still asks its owner whether
to use the command-zone replacement. Rejection or a request for a better demonstration
applies no state operations and resumes normal play. Rewind/rebase discards any
adjudication whose proposal decision leaves the accepted branch and records only
its count and digest in the rejection audit.

## Rejection and rewind

Reject a bad proposed branch at its earliest wrong choice. `rewind DECISION_ID`
removes that choice and everything after it, retains only a digest/count audit of
the discarded tail, and regenerates the current request from the surviving tape.
This prevents persisted future-draw leakage even though a human cannot literally
forget information already seen.

```powershell
.\gauntlet.cmd --cohort runs\fresh20 rewind G01-D0012 --reason "Rejected the first action in that branch"
```

A pending review may be invalidated only by rewinding the underlying game; its
evidence and review bundle are then removed and regenerated from the new terminal
fingerprint. A review already recorded as `applied` or `no_changes` seals the game
and cannot be rewound through this workflow.

## Rules and horizon stops

`release_blocker` means the referee cannot establish a trustworthy continuation.
For the current decision surface it ends the game as a draw at the last accepted
prefix and creates a game-breaking rules work item. Repair the interaction and add
a regression before learning. The skeptical review must state which evidence is
unaffected, limited, invalidated, or uncertain and how each issue changes every
proposed lesson. After review, retain the draw as quarantined within the cohort and
start the next scheduled game.

`horizon_stop` is not a game result. Resolve the configured-limit question before
continuing. A user instruction to pause or stop always takes priority over the
campaign's next action.

## Automatic terminal artifacts

At a valid terminal result, the referee writes:

```text
<cohort>/game_N/
  decisions.jsonl
  combo_adjudications.jsonl        # present if a shortcut was adjudicated
  gameplan_seed_snapshot.json      # immutable copy bound to this game
  messaging_personality_snapshot.json  # immutable table-talk personalities bound to this game
  private_gameplans/
    <one append-only journal per pilot>.jsonl
  terminal_result.json
  status.json
  STATUS.md
  postgame_evidence/
    <one private packet per pilot>.json
  postgame_review/
    review_request.json
    REVIEW.md
    learning_patch.json
```

The reviewed `game_summary.txt` is written when the response is recorded, so its
narrative comes from the post-game reasoning turn rather than the referee.

The transient `combo_adjudication_request.json` and editable response template
exist only while that adjudication is pending. The committed adjudication journal
is included in the terminal seal by count and digest.

`terminal_result.json` seals the exact terminal result, decision-tape digest,
frozen strategy revision, adopted seed-plan and messaging-personality snapshots,
and terminal fingerprint.
`review_request.json`
cryptographically binds that seal, the configuration, accepted decision tape,
frozen strategy and private pilot-context snapshots, rules-audit artifacts, and
all four evidence packets. Changing any sealed input makes the request stale and
causes learning validation to fail.

Only the four viewer-projected evidence packets and frozen advisory strategy are
inputs to the strategy review. Raw decision tapes and omniscient narratives remain
sealed for deterministic rules/integrity auditing; the reviewer must not read them
or use their hidden facts as strategy evidence. Event visibility is an allowlisted,
field-level projection: unknown event kinds are redacted until they receive an
explicit policy, and publicly revealed zone changes remain visible.

The campaign remains on game N while this bundle is pending. Gameplay `advance`
and `answer` cannot cross the review gate.

## Post-game review when learning is enabled

Open the generated instructions or print them with:

```powershell
.\gauntlet.cmd --cohort runs\fresh20 review --game N
```

The reviewer must:

1. Read each private pilot packet independently before combining conclusions, so
   one pilot's hidden information is not treated as another pilot's knowledge.
2. Review all four decks, even when only one appears to need a note.
3. Compare proposed changes with the current notes, roles, and packages.
4. Preserve reusable strategic guidance, not a diary of the finished game.
5. Keep rules facts and executable behavior in the catalog/referee rather than in
   advisory strategy memory.
6. Give every pilot a disposition of `changes`, `no_change`, or `rules_blocker`,
   with a nonempty rationale.
7. Consolidate supported operations into the generated `learning_patch.json`.

If any disposition is `rules_blocker`, leave `operations` empty and submit the
response through `learn`. The command records the blocker without changing
strategy memory, converts the result to a tagged draw, and regenerates the review
bundle. `NEXT_ACTION.json` then names the rules repair work item. Repair and
regression-test the defect, record it with `repair-rules`, and perform the new
skeptical review. The resolved draw remains quarantined within the cohort and the
next scheduled game may start.

No strategic update is a valid result. In that case leave `operations` empty,
provide a substantive `no_change_reason`, and still complete all four pilot
dispositions. This proves the learning pass occurred without manufacturing notes.

## Apply, audit, and unlock

Apply only the generated, reviewed patch for that game:

```powershell
.\gauntlet.cmd --cohort runs\fresh20 learn --game N --patch runs\fresh20\game_N\postgame_review\learning_patch.json
```

Validation checks the review identity, sealed hashes, base strategy revision,
four-pilot coverage, and the declarative operation schema. On success it writes:

```text
<cohort>/game_N/postgame_review/response.json
<cohort>/game_N/postgame_learning/transaction.json
<cohort>/game_N/postgame_learning/application_0001.json
```

An `applied` review atomically updates the global inert strategy bank for future
games. A `no_changes` review records the audit without rewriting that bank. Both
unlock the next game; neither can alter the completed game's frozen snapshot.
Repeating the identical apply command is idempotent, while a different second
patch is rejected.

The learning transaction is prepared before the global strategy bank is changed.
If a process stops between the strategy write, audit write, status update, or
campaign transition, retry the exact same `learn` command. It verifies the journal
fingerprint and resumes the one transaction rather than applying the operations a
second time. `NEXT_ACTION.json` publishes `retry_learning_transaction`, and every
gameplay command fails closed, while that journal is unfinished. A different patch
is rejected while that transaction exists.

Finally, follow the regenerated `NEXT_ACTION.json`. It will direct `advance_game`
or report `none` only after the final game's review is recorded.

## Information and authority boundaries

Live requests and checkpoints never persist ordered libraries. Exact hidden state
is reconstructed from the seed and accepted decisions. Post-game evidence is for
learning review only and must not be used to retroactively justify a play.

For priority windows, simultaneous triggers, batch attacker declarations,
autopass behavior, manual corrections, and the no-action-chooser rule, follow
`MANUAL_REFEREE_PROTOCOL.md`.


Fresh CLI contract-4 cohorts default to staged planner publication (`--planner-publication single` opts out). The game configuration binds this choice; existing games retain their original protocol. See [PLANNER_RUNTIME_POLICY.md](PLANNER_RUNTIME_POLICY.md) for routine short_term → actions and initial/pilot-requested long_term → short_term → actions; standing initialization comes first. These are consecutive inference/tool cycles in the same persistent planner context, with no additional pilot planning turns or coordinator inference. Python callers opt in with `campaign.init(..., planning_contract=4, planner_stages=True)`.

Fresh staged games also bind `plan_tiers:true`: initialize immutable standing references before pilot dispatch, automatically initialize opening-hand long-term goals before the first main-phase claim, then sequence short-term actions. Later strategic replacement remains pilot-requested. See PLANNER_RUNTIME_POLICY.md for three-tier ordering and retained context. Existing cohorts do not migrate.
