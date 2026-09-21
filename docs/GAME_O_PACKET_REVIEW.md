# Game O packet review and interface repair

Reviewed the completed `web-campaign-20260920-o` Reaminatour audit: 108 rows in
round 1 (including labelled opening/setup records), 277 in round 5, and 597 in
round 7. Also reviewed the all-turn submission-issues export and the stopped
short-term planner's recorded inputs, final outputs and tool receipts. Original
CSV rows, packet copies, actor evidence and accepted game tape remain unchanged.

## What the agents need

| Role | Immediate obligation | Supporting information |
| --- | --- | --- |
| Decider | Current choice, full submission wrapper, available action parameters or proposal approval | Current board, exact targets/cost constraints, complete current plans, relevant conversation and rejection feedback |
| Short-term planner | Current unfinished publication stage and frozen target turn | Current goal, own hand/board, prior complete plan and continuity, own non-pass decisions, planning templates |
| Long-term planner | Concrete strategic assessment and diplomatic authority | Current tactical assessment, relevant board/cards, own decision evidence and standing strategy |
| Diplomat | Required versus optional publication; current reply and hold authority | Complete own goal and tactical prose, public state and conversation; no private hand or other seats' private evidence |

Packet brevity must not remove a choice, select an action, authorize a bargain,
truncate plan prose or hide a changed rule. Presentation remains separate from
engine state and lossless evidence. Board section reuse and message deltas apply
only within the same physical conversation; replacement contexts receive baselines.

## Observed problems

The all-turn export contains 21 rejected tool submissions across these roles:

- Seven prose length failures: five long-term plans and two short-term plans.
- Eight diplomat failures: three unaddressed replies, two unknown reply IDs,
  two operational/template labels in prose, and one hold outside its authority.
- Three decider command failures: two missing required action-wrapper fields and
  one unsupported command/field combination.
- Two absent inspection paths and one object absent from the frozen input.

These counts exclude separate failure notifications and the separately recorded
failed batch execution; counting all rows as independent failures would overstate
rejections. The single Reaminatour help request appears as both a transport query
and a durable help record.

For the 38 direct working-document inputs in round 7, decider text totalled
1,677,632 characters. Previous-board sections accounted for 384,347 characters
(23%); public-message sections accounted for 508,995 (30%). For 56 diplomat
inputs in that window, message sections contributed 753,379 of 1,299,084 characters
(58%). These are selected direct input documents, not cumulative context tokens,
all tool-carried inputs, or a measured latency reduction.

The largest inspected decider document contained 76,108 characters, including a
20,958-character previous board. Five recorded input documents also contained an
aliased ordinary mana schema key: an operational ability ID `mana` had registered
an alias, and the generic label encoder incorrectly applied it to dictionary keys.

## Changes

- Current decision and complete action-wrapper instructions precede the decider's
  action menu, which precedes strategy. Choosing a scheduler remains the pilot's
  responsibility; the shown hold-full-control wrapper is an example, not a default
  action taken by the host.
- Previous-board copies no longer enter the working document. Current board state,
  complete current plan prose, original evidence and inspection access remain.
- Public conversation uses full-text baselines and new/changed full-text messages
  thereafter. Repeated authorization metadata is absent. Diplomats receive an
  explicit current set of reply-eligible message labels and absolute hold bounds.
  Old remembered messages do not acquire reply authority.
- Schema keys remain literal. Only known identity-keyed containers (such as combat
  assignments and zone costs) translate their keys to/from operational labels.
- Background publications have a front-of-packet obligation, required next stage,
  completion semantics and nearby character budgets. Length constraints also
  appear in the publication tool schema. Existing validators remain authoritative;
  no prose is silently clipped and no invalid output is silently accepted.
- Missing inspection paths report the available keys or array length at the exact
  failed traversal point, from the same authorized frozen input.

## Why the entire game stopped

At 00:48:49, 00:49:01 and 00:49:04 UTC, Reaminatour's short-term planner completed
with empty final text and no publication for its new job. The host's two
continuations resent documents into the same conversation, then raised an
exception that stopped every lane at accepted action 1336.

A concrete presentation defect compounded the ambiguity: `deliver()` supplied a
publication-required instruction, but the coordination renderer marked that field
handled without rendering its content. The prior completed job's `next:null`
receipt remained in context. This is an observed missing instruction and recovery
defect; the transcript does not prove the model's internal reason for ending.

The repaired host explicitly distinguishes the current task from earlier stop
receipts. After an unfinished completed turn, it retires only that idle physical
context and supplies the same logical role's current unfinished stage in a fresh
baseline. Accepted publications are not replayed. After two bounded continuations,
a repeated failure suspends only that advisory lane and emits a dashboard/runtime
attention record. The decider is told that the lane's last guidance has not been
refreshed. Other lanes continue. The preserved job needs operator recovery if both
fresh-context attempts fail; this is visible degraded planning, not fabricated
success. Ambiguous transport failures and rules blockers retain their existing
stop behavior.

## Validation and review

67 focused tests passed across document/coordination rendering, host scheduling,
inspection and dashboard presentation; JavaScript syntax validation passed. Added
regressions cover literal schema keys, reply eligibility, baseline/delta delivery,
publication-required rendering, full action wrappers, bounded lane isolation and
continued decider admission with the accepted prefix unchanged.

A read-only comparison is generated by `tools/build_packet_review_preview.py`.
It checks the saved host journal hash chain and renders frozen actor inputs; it
never opens a live campaign or submits gameplay. The server-side `/audit/sparse/`
view labels these as prospective documents, not packets actually used in O.

These improvements are for the next validated release. Completed O is preserved;
no new game was launched and no existing game contract was migrated. Runtime
latency and rejection-rate gains still require observation in a subsequent game.

## Second-pass review

Re-read the actual rejected calls, their preceding action menus and notification
pairs rather than relying only on aggregate issue categories. This found several
further problems and two corrections to the first pass:

- **Reply eligibility must match engine semantics.** A committed, addressed
  message does not stop being replyable when it leaves the latest-24 display
  window. The first pass was too restrictive. A continuing conversation now
  retains eligibility for messages it actually received; a fresh conversation
  still gets only its authorized baseline. No unknown message is invented.
- **Omission can make alerts stale.** Working documents explicitly retain omitted
  sections. Cleared rejection feedback, batch interruptions, strategic-review
  notices and background-lane alerts therefore need an explicit clearing update.
  Each clearing notice is sent once, and the same alert can subsequently recur.
  Cancelled jobs also clear their runtime attention records.
- **Combat needs its parameter grammar at the action.** One rejected block
  submission supplied only its A-label. Its menu said to use the specification,
  without showing the required `assignments` object. Attack, block and damage
  action rows now name their required fields and exact nesting, including empty
  declarations, per-source damage totals, and blocker/defender constraints.
  The host supplies no gameplay allocation.
- **Tiny prose overruns should not discard a whole publication.** Recorded failed
  tactical texts were 653 and 601 characters; failed strategic texts were 1310,
  1208, 1214, 1219 and 1201. Fresh coordination documents keep targets of 600/1200
  but permit a bounded 10% margin (hard ceilings 660/1320). All seven recorded
  lengths fit that margin; this does not assert every publication was otherwise
  valid. Text is neither clipped nor summarized. The tool schema and instructions
  agree with validation. Legacy non-coordination validation keeps 600/1200.
  Rejections now include actual character counts. Action, payment, recipient,
  hold-authority and other structured validation are unchanged.
- **An empty decider retry needs the same context hygiene.** The existing single
  retry now retires the completed idle context, preserves the exact claim and
  logical seat identity, and delivers a fresh baseline. A second empty completion
  still stops; an active/waiting tool cannot be retired. No gameplay action,
  publication or unresolved transport call is replayed.

Public dialogue now uses labeled, newest-first message blocks rather than a dense
JSON array. Text is preserved, each line is quoted, and the packet explicitly marks
it as untrusted dialogue; a message cannot visually introduce a new host heading.

Validation: the broader regression run passed 119 tests. Two additional real
publication tests verified prose-margin acceptance, hard-cap atomic rejection and
legacy limits; the updated 11-test readability suite also passed, including the
new multiline-dialogue case. These test runs overlap. No live inference or game
was run for this pass.

The comparison was regenerated from the same sealed game's hash-verified journal.
These are prospective interface changes; O and its original CSVs are unchanged.
