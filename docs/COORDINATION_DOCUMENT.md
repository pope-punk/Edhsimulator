# Agent-facing coordination documents

Fresh primitive campaigns bind `coordination_document:1` together with
`pilot_document:1`. Existing games keep their original presentation and publication
contract. Do not add these flags to a started game. This interface changes how
roles read and publish information; it does not grant execution authority, change
planning wakeups or add planner watches.

## Role views

All four roles use grouped board objects, sparse object defaults, frozen Oracle
text and conversation-local references described in
[PILOT_WORKING_DOCUMENT.md](PILOT_WORKING_DOCUMENT.md).

| Role | Early context | Owned output |
| --- | --- | --- |
| Short-term planner | Next stage, completed stages, target own turn, full strategic/tactical prose, planner continuity, holds, prior proposal and frozen planning templates | Self-contained tactical plan and phase-grouped action proposal |
| Long-term planner | Review/brief requests, named strategic route, tactical assessment and planner continuity; proposal intent and phase coverage | Strategic goal and diplomacy authority |
| Diplomat | Brief and disclosure limits, negotiation requests/holds, full own strategic/tactical prose | Public messages and private assessments within its brief |
| Decider | Current decision, complete plans, proposal intent/status and individually labelled steps, current action menu | Explicit action or approval/revision of a proposal |

Only planners inspect. They retain non-pass decision evidence. Deciders and
diplomats do not receive planner continuity or restored historical decision logs.
Diplomats retain their existing public board visibility: own plan prose is private
negotiation context, not permission to disclose a hand or hidden intent. A catalog
lookup never adds hidden cards to their input.

The long-term planner can inspect complete proposal commands with
`{"kind":"plans","path":"/actions/value"}`. This avoids copying detailed tactical
commands into every strategic review. Both planners may inspect frozen plans and
request `kind:protocol` for exceptional native command syntax. No inspection is
required to publish a normal template-based proposal.

## Compact tactical publications

Own-cleanup jobs publish prose then actions. Opposite-seat jobs publish actions
then prose. The order and target turn are frozen on claim; neither role waits for
another role to publish. Optional inspections and diplomacy must not delay the
first stage. Scheduling remains governed by
[PRIMITIVE_COORDINATION.md](PRIMITIVE_COORDINATION.md).

The actions stage accepts three phase blocks in order:

```json
{
  "intent": "A complete explanation of this proposed line, independent of prior prose.",
  "phases": [
    {
      "phase": "precombat_main",
      "status": "planned",
      "reason": "The reason for these proposed actions.",
      "steps": [{"command": {"action": "T1", "autotap": {"reserve": {"B": 1}}}}]
    },
    {"phase": "combat", "status": "reassess", "reason": "Reassess after new information."},
    {"phase": "postcombat_main", "status": "no_action", "reason": "No known action to propose."}
  ]
}
```

Python supplies sequential step IDs, the job's target own turn, each phase and
`hold_full_control` scheduler. A missing step rationale inherits its phase reason.
Explicit seat turn, scheduler and step rationales remain supported. The existing
64-step/12,000-byte bound and canonical validation still apply. An intent is
limited to 600 characters; phase reasons to 180. Native canonical proposals remain
accepted. Python does not create strategic choices or execute a publication.

`T` templates describe casts, faces, alternative costs, land plays and non-mana
abilities from this job's frozen visible objects and rules. They are planning
vocabulary, **not a claim of current legality or affordability**. The planner
chooses parameters; publication expands templates into exact canonical commands.
Ordinary casts use autotap by default. Explicit reservations and exceptional
planner-authored mana sequences remain supported. A guarded mana answer may name
an earlier one-based `choice_from.step`; Python translates it to the canonical
step ID without relaxing its execution guard. Combo proposals retain their
existing approval and adjudication path.

Tactical prose must describe the complete current plan, never only its changes.
`reuse_plan:true` may replace `short_term_plan` when the frozen prior plan is still
complete and sound; continuity and strategic validity must still be supplied.
Planner continuity remains separate from decider-facing prose.

## Handoff and freshness

Object labels are local to a physical conversation. Before storing a publication,
Python expands supplied C/S labels in prose to observed card names. Structured
commands retain exact object incarnations. Template/action/proposal/operational
labels are rejected in prose rather than passed to another lane as meaningless
IDs. This does not summarize or shorten the model's plan.

A decider receives fresh `P` labels for the offered proposal steps. The document
states whether each step executed, is past its timing window, targets a future
window, or needs checking against current facts. It also identifies whether
matching tactical prose has arrived from that planning job. Strategic-validity
assessments identify whether they assessed the currently supplied goal or an older
goal snapshot. Actions-first work
therefore has its own intent and rationales while prose is pending. Age and
status are facts, not endorsements or automatic approvals.

Approval uses current `P` labels with explicit `pass_priority` and
`resume_after_passes` booleans. They authorize different behavior and cannot be
silently omitted in this host interface. Step overrides retain unchanged timing,
rationale and scheduler; replacing a command replaces the whole command. Labels
expire at the next delivered input, including when no new proposal is present.
Existing execution validation still handles intervening state and timing changes.

After one publication stage is accepted, a subsequent claim includes completed
stages and the role's own accepted same-job components. The original board and
other lanes' facts remain frozen. This prevents a fresh physical conversation
from mistaking its own already-published work for missing work. Accepted stages
cannot be repeated.

The host records `proposal_offered` telemetry after successful decider delivery:
step/executed/expired counts, age in accepted decisions and whether matching prose
exists. These measures help distinguish delayed planning, stale proposals and
adoption; they do not by themselves establish a speed improvement.

## Review and validation

`tools/refresh_pilot_preview.py --roles-only` reconstructs historical role jobs
from the verified host journal, read-only. The comparison page labels each role's
snapshot count. Planner/diplomat comparison sources are frozen job inputs before
transport presentation, not claims about their exact historical inference text.
The decider comparison retains the recorded original inference packet.

Focused tests cover role visibility, completed-stage continuity, compact expansion,
prose references, label expiry, actions-first delivery and an end-to-end offline
planner-template → publication → separate decider approval → exact cast execution
with a preserved mana reserve. Saved games are not used as mutable test fixtures.
