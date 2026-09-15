# Agent architecture v1

Fresh split cohorts also bind `turn_batches:1`: two mandatory short-term updates
at the preceding living opponents' end steps, full-turn phase coverage, and
pilot-approved priority continuation. See [APPROVED_SEQUENCES.md](APPROVED_SEQUENCES.md#full-turn-batches-turn_batches1).
For those mandatory updates, an invalid goal queues Sol concurrently but does not
skip the short-term actions stage. Existing games keep their bound workflow.

This is an opt-in, game-bound extension of planning contract 4, not a migration
of contract-4 games. `agent_architecture: 1` binds split planning;
`async_diplomacy: 1` additionally binds asynchronous public conversation.
Neither flag changes an existing started game.

Fresh cohorts additionally bind [static_standing:1](STATIC_STANDING_PLANS.md):
Python loads reviewed standing files; legacy games retain Sol's initialization.
Sol owns the current strategic goal, strategic answers and diplomacy authorization;
Sol-high with Fast service owns continuity, short-term prose and symbolic proposals
in fresh cohorts bound to `short_term_sol_fast:1`; older games retain Terra-high. Terra-low
owns actual choices and approvals; Luna-low owns only authorized public talk.
Python coordinates them. Fresh split hosts use 16 independent inference lanes:
one decider, short-term planner, long-term planner and diplomat per seat. Each
seat/role admits one inference at a time; a
waiting decision tool does not occupy an inference lane. Roles never reserve a
slot while waiting for another role.

Implementation checkpoints:

1. Versioned components, branch/ownership checks and atomic publication recovery.
2. Split initialization and role-bound scheduling, including KEEP answers and
   coalesced escalation within ordinary short-term publication.
3. Shared delivery/inspection/checkpoint/CLI/operator projections and telemetry.
4. Separately gated diplomacy with mandatory brief-update posts and optional incoming replies.
5. Offline compatibility/fault tests, then fresh-seed behavioral trials.

Design constraints and likely failure modes:

- One current component pointer per seat/type. Its immutable content and prior
  envelopes live in the existing `continuity/plan_components` archive. A new
  strategic answer must not overwrite tactical components from another writer.
- Component publication, successful transport delivery, and recipient
  acknowledgement are distinct facts. Cross-role references need a resolvable
  actor-scoped artifact; another role's receipt is never a delivery baseline.
- A KEEP answer resolves a review request without changing the goal version.
  Equivalent content is not a new version. Evidence coverage remains explicit.
- Frozen work remains frozen. Pending work may coalesce current facts. A
  strategic revision only queues tactical rework when declared dependencies
  establish material incompatibility; version churn alone is insufficient.
- Short-term escalation releases the slot after the current publication; it
  does not produce an empty actions turn merely to await Sol. An interim line
  is permitted and marked provisional. Gameplay continues with current plans.
- Broad seed/catalog retention belongs to the long-term role. Continuity has
  one writer. Default packets omit old component versions and full message logs.
- Diplomacy needs machine-readable offer/authorization IDs and expiries. An LLM
  cannot create permission merely by claiming that its prose stays in scope.
  Claims, proposals and confirmed agreements remain distinct advisory facts.
- Diplomacy must never update a claimed decision. Public posts are committed
  at a replayable unclaimed frontier; duplicate publication cannot post twice.
- Measure proposal availability, review/approval and execution separately; smaller
  packets alone are not evidence of fewer decisions or stronger play.

Choose learning at initialization with `--learning enabled|disabled`. Tests may
explicitly suspend rules hotfixes as well; record defects and stop at genuine
blockers. Learning and rules repair are separate policies (LEARNING.md). A skipped
review is not an AI review, and changing source does not migrate a bound game.

Acceptance evidence must separate initialization, warm decisions, planner stages,
strategic review and diplomatic work. Count all extra/reworked/discarded turns,
not just reduced pilot latency. Track packet bytes/tokens, cache, file growth,
memory coverage gaps, stale goals and whether plans arrived before use.

## Running and reviewing an enrolled trial

Use `python -m edh_gauntlet --cohort PATH init --games 1 --seed-start SEED
--max-rounds 12 --agent-architecture --async-diplomacy --learning disabled`. Omit the final flag to
test split planning with the original messageboard flow. Both require staged
contract 4, three plan tiers and context handling 1. Initial configuration binding
persists the flags in each seed/personality/strategy binding path; old persisted
game configurations never inherit these flags from later manifest changes.

`tools/start_host_game.ps1` launches the fresh host. Use its ordinary decision cap
and a local `collect_host_telemetry.py` process, with 4096 retained timing events.
Use `resume_stopped_host.ps1 -DecisionLimitResume` only after the owned process
stops and its watcher records the exact capped prefix. Recovery keys registrations
by seat AND role; lazy background identities do not require inventing missing
contexts. Current recovery utilities preserve the exact accepted prefix.

The standalone planner CLI reserves from the same workboard. Its generated batch
contains the owning role; register/reuse a persistent isolated context for that
seat/game/role. The read response supplies role-specific instructions, current
components and resolvable IDs. `publish --stage standing|long_term|short_term|actions`
uses the same transactional publisher as the host. Diplomacy uses
`publish --stage diplomacy`. The local standalone scheduler must run
`flush-diplomacy` before claiming the next decision. This is a Python operation,
not a model routing or validation turn. A prepared public-post refresh blocks
claims until replay has reconstructed the unclaimed frontier.

`report_host_game.py`, `report_host_segments.py` and
`report_agent_architecture.py` report all four role names. The architecture report
separates request origins, cached versus total input tokens, goal content changes,
publication latency, requests/rework, proposal availability and accepted batches.
It does not equate availability with adoption or fewer bytes with stronger play.
Operator views list current versions, writers, strategic answers and authorized
diplomatic objectives. Old versions remain in immutable actor-scoped evidence.

## Publication and input boundaries

`continuity/current_components/SEAT.json` contains only current immutable envelope
IDs. Envelopes and text share the existing `plan_components` archive. Composite
`plans` are compatibility views containing component references; they do not copy
every writer's text. New prose invalidates action proposals written for a different
short-term version. A strategic publication merges with existing tactical pointers
and preserves the tactical comparison snapshot. A fresh short-term review can
advance its comparison snapshot while retaining identical component text/version;
original authorship and latest review coverage are distinct.

`component_transaction.json` is a write-ahead record for current pointers,
mailboxes, receipts, coverage and workboard updates. Recovery applies the same
candidate before another reader observes a mixed view. Stage retries bind the
same response digest; conflicting content is rejected. Standing replacement is
forbidden. Per-role coverage prevents a strategic publication from consuming the
short-term role's unreviewed rationale interval.

Short-term publication requires a `strategic_disposition`. `continue` carries no
extra explanation. `review_requested` carries `question`, `evidence`, `interim`
and `useful_by`; at most four distinct pending questions per seat are coalesced.
`review_pending` refers to existing work. Escalation finishes that batch without
an empty actions stage. Answers cover only the questions in the frozen input.
An answered tactical request queues its needed follow-up; an authorization-only
answer does not. Independently revised strategy queues tactical rework only when
declared tactical factual dependencies changed. Idle components do not wake all
dependents merely because a version changed.

Successful transport delivery records offered IDs per physical context; its next
tool call acknowledges those offered IDs. Checkpoints and explicit transport
recovery clear those baselines and deliver self-contained content again. Shared
presentation comparisons remain scoped to a single seat/role/conversation.

## Diplomacy authorization

A brief contains an objective, up to six identified public disclosure atoms,
four identified offers with an exact recipient and terms, four exact public offer
IDs authorized for acceptance, an event-sequence expiry, and up to eight factual
invalidation conditions. With asynchronous diplomacy bound, every initial or
revised goal must publish its refreshed brief atomically. KEEP with no revision
does not force a brief. An authorization question or expired-authorization refresh
requires a brief even when Sol keeps the goal. Each brief requires at least one
public-safe disclosure that fits the 300-character message limit on its own.
The worker may combine authorized atoms, select offers, accept an authorized
offer or withdraw its own offer. A brief update mandates a public post; optional
incoming-message work may instead record silence or request authorization.
The private goal and objective are never automatically broadcast.

This initial contract deliberately composes public text from authorized atoms;
it does not attempt to prove semantic compliance of unrestricted generated prose.
Disclosures are unverified public claims. Proposed offers, agreements and
withdrawals are separate typed facts. No promise changes game legality or causes
Python to choose an action. The decider may depart when current facts warrant it.

The worker receives public facts only, with own hand/seed and face-down identities
removed. Directly addressed root messages and every updated brief queue work;
generic chatter and nonrecursive replies do not. Up to sixteen incoming messages
are coalesced per job. Additional evidence is inspected, not copied into a growing
default transcript. No diplomacy turn is required just because a player can talk.

Publication queues an outbox entry. At an unclaimed frontier Python rechecks its
branch, brief and offers, then commits one public sidecar entry with an exact
accepted-decision boundary. Referee replay inserts it once at that boundary;
an interrupted refresh must finish before a claim. Already claimed inputs remain
unchanged. Public-post and component receipts make retries idempotent. Diplomacy
shares bounded background capacity and never acquires gameplay authority.

For optional message work, silence is an explicit `edh_diplomacy` call with an empty response object. An
incoming offer does not itself authorize acceptance; an absent brief permits
silence or a private authorization request. If the worker ends without a valid
publication, its optional jobs become `unanswered_at_completion`, not pending
retries and not fabricated silence receipts. A new message or brief may queue new
work. Mandatory brief jobs cannot finish silently: blank completion preserves
pending debt and stops the host. Expiry during inference or before outbox commit
transfers the obligation to one deduplicated Sol refresh job. Superseded unclaimed
briefs coalesce to the latest authorization; stale text is never posted merely
to discharge an obsolete job. Equal-content KEEP and publication retries do not
create messages. A revised goal refreshes its brief version even if its public
wording stays the same. The immutable brief envelope records the goal version.
Split strategic/tactical planners that end before completing their stages
stop the host for recovery rather than entering a redispatch loop. Their mandatory
debt remains recorded. User pauses still stop all dispatch immediately.

## Trigger and context routing

Python owns the following routes; no coordinator inference is required. A wake
queues background work. Delivery updates the next real recipient input, without
interrupting an active inference or creating a plan-validation decision.

| Trigger | Recipient and effect |
| --- | --- |
| Game initialization | With static_standing:1, Python freezes reviewed standing files without inference. The pilot retains standing until its initial goal arrives; the short-term planner retains standing thereafter. Sol retains the complete seed. Legacy bindings still initialize standing through Sol. |
| Each seat's settled opening hand | After keep and any London bottoms, immediately queue that seat's initial goal and brief, without waiting for other keeps. Short-term planning follows the goal, and diplomacy must post from the brief. |
| Completion of a seat's turn, after cleanup | Mandatory short-term maintenance, with own rationales and execution deviations. There is no routine draw-step wake. |
| A short-term or strategic watch fires | Wake its owning planner once per watch version. Supported facts: exact known card cast, visible object leaves, life at/below a threshold. |
| Pilot alarm at an allowed priority choice | Wake short-term planning now or schedule one phase/seat/occurrence alarm. `long_term:true` routes to Sol. A pilot can replace/cancel its alarm; its own mandatory EOT cannot be duplicated. |
| Short-term strategic review request | Queue Sol with a targeted question and interim plan; end the tactical batch to release capacity. Duplicate pending questions coalesce. |
| Sol answers a tactical request, including KEEP | Queue the requesting short-term planner to continue. An answer to a diplomat alone does not wake the tactical planner. |
| Revised goal plus changed declared tactical dependencies | Queue a short-term revision. A changed goal otherwise enters the next real input without an automatic tactical replan. |
| Changed goal | Atomically refresh the diplomacy brief. Every long-term review queues mandatory diplomatic posting, including keeping a valid brief unchanged. |
| Addressed root public message | Queue the respondent's diplomat. Generic chatter and replies do not recursively wake agents. Replies are optional unless the batch also contains a brief update. |
| Diplomat needs authorization | Queue Sol privately; his answer must refresh the brief, which mandates a public message. |
| Authorization becomes invalid before a mandatory post commits | Queue one Sol authorization refresh for that brief; do not retry stale text. |
| Any completed plan or diplomatic outcome | Deliver changed components at the next actual pilot/planner input, using exact acknowledged references where available. No separate adoption or response inference. |
| Short-term table-talk suggestion | Offer it in the pilot's existing decision packet; suggestion alone does not wake a diplomat or automatically post. |
| Accepted decision, priority transfer, snooze expiry, or approved-sequence boundary | Python routes the next required pilot choice. Approved steps may continue across opponent passes; a new opposing action interrupts them. Snoozed unforced choices require no inference. |

Pending work for one seat/role coalesces. Fresh software hosts bind `role_slots:2`
in the workboard: all twelve background seat/role lanes can run concurrently
alongside four independent decider lanes. Only the seat owning the actual decision
receives a decision packet; capacity does not create out-of-turn choices. Initial tactical work requires a
completed opening goal; later strategic jobs do not block it. Each role prioritizes
missing initial tactical plans and then aged work, preventing repeated maintenance
from starving another seat. Mandatory brief posts lead their own diplomacy queue. Python transfers already-expired authorization to strategic refresh before
admitting a diplomat. Idle transport checkpoints and capacity recovery preserve logical
roles and accepted decisions; they are not planning triggers. Communication policy
2 refreshes older split-role conversations once at an idle boundary before reuse,
so old standing-plan input and obsolete optional-post instructions are not retained.
Sol's original standing-plan authorship remains archived evidence; the summary is
not returned in its subsequent inputs or component inspections. Legacy unsplit
contracts retain their original standing delivery and diplomacy behavior.

## Tactical delivery and reservation freshness

Explicit strategic questions precede routine maintenance in the shared background
queue; their required tactical follow-up also precedes routine maintenance.
Running jobs retain their frozen inputs. At reservation, pending work adopts the
latest committed seat snapshot, including follow-ups queued from an older planner
publication. If that seat has not been observed at the current accepted frontier,
Python reconstructs the accepted tape once and projects only that seat before
freezing the batch. This happens under campaign then planning locks, creates no
decision or inference, and retains no additional full-game cache. Reservation
telemetry records any refresh cost and the source accepted count. Admission retries
return the original frozen batch.

Tactical inputs resolve bounded visible own-card definitions from existing
inspection evidence: at most six unknown definitions and 12,000 characters of
definition content per real input. Oversized definitions are left inspectable,
never truncated. Immutable references reside in frozen evidence; the delivery
adapter skips definitions already retained by that physical conversation. Fresh
contexts receive a self-contained bounded baseline. Current zones remain board
facts, not retained card knowledge. Static symbolic vocabulary uses the same
per-conversation retention boundary.

Planner checkpoint admission reserves 20% of the configured context budget for
the next real input, since tactical packets can add substantial context at once.
Measured input size persists at delivery/tool boundaries, completed turns and
host shutdown so explicit stopped-host recovery does not forget it. Replacement
clears the old measurement. The hard fresh-baseline guard remains in place, and
running publications are never interrupted to checkpoint between stages. This
is headroom, not a hard bound on every intermediate inference request.

Sequence readiness identifies already executed proposal items across harmless
goal-view updates. They cannot be approved twice. Exact legal alternatives for a
malformed proposed symbol are advisory and require an explicit pilot override.
Main-phase exit and end-of-phase priority are separate choices; sequence guidance
names both. The engine never invents a missing pass, target or snooze policy.

## Release validation

See [VALIDATION.md](VALIDATION.md) for current release evidence. Disposable trials and diagnostic archives are not distributed.

## Decision ownership in fresh asynchronous games

`decision_roles:1` is an immutable additional game binding. Fresh asynchronous
cohorts use it by default; already accepted games keep their old menu/replay
semantics. Do not retrofit an accepted tape.

- Diplomats own all table talk, including the one mandatory generic opening
  salutation. The first authorized publication supplies `opening_salutation`
  alongside authorized IDs. Python emits the greeting once as a separate generic
  post within that same publication; it creates neither a pilot turn nor a reply
  wake. Each changed strategic brief still requires its authorized public post.
  An expired brief transfers that obligation as before.
- Tactical planners may supply `combo_proposal` in the existing actions stage:
  `{proposal_text,seat_turn,phase,requires}`. The proof is at most 1200 characters;
  phase is a named main phase, and guards use the normal factual predicates.
  Proposals should explain the concrete repeatable loop and claimed outcome.
  Omission on a newer actions publication clears the old proposal. New tactical
  prose invalidates an actions component derived from an older short-term version.
- Python commits a proposal at an unclaimed frontier, with its accepted-prefix
  position for replay. The pilot sees the proof once, next to the corresponding
  menu option. Only selecting that option submits the exact planner-authored proof
  for the existing opponent-consent/adjudication process. Selection consumes it.
  Invalid timing/guards hide it; publication cannot change a claimed inference.
- Empty main phases advance automatically. Concede is appended only to an
  otherwise material decision. Planning approvals never create standalone turns;
  diplomats and strategic planners cannot execute or approve gameplay snoozes.

Pilots and tactical planners share situational snooze guidance. Propose complete,
known executable prefixes, including required targets/modes; do not invent
mandatory phase-exit calls. `resume_after_passes:true` retains explicit pilot
permission after opponents pass, while new information, intervention, unavailable
choices and unapproved decisions retain their execution fences.


## Required strategic validity assessment

For `decision_roles:1`, every short-term prose publication requires
`long_term_validity: valid|invalid`. An invalid tag also requires
`long_term_invalid_reason` (1–300 characters). A valid tag needs no reason.
This replaces `strategic_disposition` and the separate tactical strategic-review
object in that workflow; older bound games retain their frozen submission format.
A completed milestone still presented as future work (such as finding land four
with five lands already controlled), obsolete survival assumptions or a superseded
route should be marked invalid when the guidance no longer applies. Age alone
is not invalidity.

Python binds the assessment to the exact long-term component/version in the
short-term planner's frozen input. The assessment travels with that short-term
component to the pilot, operator view and the long-term planner's next input.
Long-term input includes the latest short-term prose regardless of validity,
once, rather than removing it from the default packet. Idle persistent contexts
receive this current projection on their next scheduled input; publishing a valid
tag never starts a model turn just to deliver it.

An invalid **current** goal queues/coalesces one mandatory strategic review and
releases the short-term slot. Repeated invalidations of the same goal share that
review even if the short reason changes. A late assessment of an already replaced
goal remains labeled with its old version and cannot invalidate its successor.
An outstanding invalidation requires changed long-term prose plus the fresh
mandatory diplomatic brief in one publication. KEEP or identical prose cannot
clear it. The existing mandatory diplomat publication and tactical follow-up then
run. Other established strategic watches, pilot requests and diplomatic
authorization wakes remain; a **validity tag itself** wakes only for invalidity.

## Brief review and personality references

Every completed long-term review creates mandatory diplomat posting debt, even
when the goal and brief remain unchanged. `diplomacy_brief_action:keep` explicitly
reauthorizes valid current text without resending it; `revise` includes a complete
brief. A revised goal may keep valid public authorization explicitly. Missing or
invalid authorization must be renewed. Unchanged text and goal preserve component
versions; posting debt uses the publication operation identity. Retries are
idempotent and unclaimed obsolete debt coalesces. A repeated message does not
recreate an already-published offer.

Both Sol and Luna retain only their own seat's messaging personality from the
frozen game source snapshot. The host sends that reference once per physical
context and restores it after a checkpoint. Either role may inspect `personality`
without filesystem access. Sol writes authorized disclosures in that voice; Luna
uses it for message selection and the generic opener. Personality conveys no
additional authority to disclose hidden strategy or invent commitments.

## Independent inference lanes

Seat/role reservations are stored in `active_by_role`, keyed by `SEAT::ROLE`
under `role_slots:2`, and are looked up by immutable
batch ID for every read, inspection, publication, retry and cancellation. All
publications retain the existing atomic transaction lock and merge current component
pointers, so concurrent inference does not mean concurrent unprotected file writes.
A superseded mandatory diplomatic authorization is resolved in Python without a
correction inference; the new brief still carries its mandatory posting obligation.
Tactical assessments stay tied to their frozen goal version.

Fresh split hosts enable independent lanes before dispatch. A previously started
host changes this transport policy only on explicit user authorization and through
`resume_stopped_host.ps1 -DiagnosticPauseTelemetry PATH -SeatRoleLanes`
(or Python `tools/resume_stopped_host.py --diagnostic-pause-telemetry PATH
--seat-role-lanes` with the required cohort, game and accepted-prefix arguments).
Existing `role_slots:1` hosts retain their four shared role lanes until explicitly
upgraded; `-ConcurrentBackground` continues to select that older policy.
It verifies the stopped process, accepted prefix, no active reservations and all
unloaded seat contexts before enabling lanes. It preserves gameplay bindings,
accepted decisions, wake triggers and clean contexts. Legacy desktop collaboration
retains its one-background-slot policy. Local `planner_reserved` telemetry includes
queue delay and simultaneous background count; no extra model status calls.
