# Seat communications

For fresh games explicitly binding `agent_architecture:1`, the role, component,
escalation and scheduling rules in [AGENT_ARCHITECTURE_V1.md](AGENT_ARCHITECTURE_V1.md)
supersede the single-planner instructions below. Sol owns strategic goals; static standing files serve fresh split games;
Terra-high owns continuity and tactical prose/actions; Terra-low owns decisions.
Fresh software hosts provide independent short-term, long-term and diplomacy
lanes, each admitting one seat at a time. Legacy serialized hosts retain their
existing slot binding until an explicit verified stopped-host upgrade. Optional
`async_diplomacy:1` routes authorized public conversation to Luna-low and removes
forced reply decisions. Neither binding changes existing games. Use the current host and fenced
stopped-host recovery for this architecture.


`communications.py` is the shared presentation boundary for packets enrolled in
`context_handling:1`. It presents `communication_version:1` to hosted pilots and
planners and to their standalone CLI deliveries. It does not change the bound
game contract, evidence, claims, legal choices, planner stages or scheduling.

## One owner for each kind of information

| Information | Authoritative source | Delivery |
| --- | --- | --- |
| Current board and legal choices | Actor-scoped referee projection | Current facts or exact changes from a named baseline |
| Standing plan | Immutable seat reference | Retained across the conversation; restored at checkpoints |
| Current goal and short-term prose | Latest published plan | Prominent in every pilot decision |
| Proposed sequence, warnings and freshness | Python plan assessment | Current support alongside the prose |
| Optional table-talk draft | Short-term plan component | Once at an eligible posting opportunity; pilot may edit/use/ignore |
| Own rationales and rejection explanations | Accepted decision evidence | Complete; repeated record keys may be encoded as columns |
| Most recent actual pilot-seen board | Decision context evidence | One historical snapshot or exact comparison |
| Intervening observations | Actor-scoped event summary | Unique factual records with original counts and bounds |
| Full seed, roles and card definitions | Private reference and inspection receipts | Retained knowledge, with current zone facts separate |

Original evidence remains inspectable. Presentation never drops an unknown field,
truncates a rationale, or promotes a summary into complete engine history.

## One grammar for repeated records

`communication_codec.py` supplies lossless column records, board tables and change
tables. A field's name and constant value can be declared once for many records.
Row layouts preserve field presence, order and the distinction between missing and
null. Each encoding includes its own reading instructions and is used only when
smaller than its unencoded counterpart. `communication_events.py` uses the same
grammar for event summaries, preserving section boundaries and unfamiliar facts.

Pilot factual comparisons have explicit origins: `last_seen_to_current` and
`plan_snapshot_to_current`. Identical complete change rows can be shared by index;
the same path with different before/after values remains two different facts.
Counts of omitted plan-preview changes remain visible. An unchanged preview is
not a statement that no new events happened or that the complete plan remains valid.

## Retention belongs to a physical conversation

The host commits presentation state only after a successful packet delivery. It
retains one planner board or one bounded pilot plan preview plus reference IDs,
not a growing timeline. The state is bound to the physical thread, game, role and
seat. Checkpoints, replacement transports and explicit stopped-host recovery receive
full communication baselines. Standalone CLI calls introduce no new cross-call
references; the source packet's existing last-seen-state contract is preserved.
A completed pipe write alone does not prove that a stopped backend retained its
input, so explicit recovery also re-delivers static inspection knowledge once.

Planner board deltas carry source and destination identifiers, exact before/after
facts, sequence presence and changed UID ordering. Python reconstructs the entire
destination and verifies equality before selecting a smaller delta. Unsupported
shapes fall back to a full board. Pilot plan-preview updates select exact old or
new rows and carry hashes of both previews; a new plan version resets the preview.

Standing text is referenced only after its exact value was delivered. Within a
packet, duplicate strategic text is replaced only by a reference to its actual
named section. Current long/short pilot prose continues to appear in full on every
decision. Hosted publication receipts retain current stage constraints and schema
limits without repeating their loaded static tool manual. Standalone CLI responses
retain full grammar help because they cannot assume a loaded tool schema. Dependency
paths have the existing 24-item limit exposed in both the tool schema and stage
instruction.

## Boundaries and verification

Builders and journals continue to store their original records. The final egress
adapter is shared by `host_runtime`, `pilot_session`, `handoff_runtime` and
`planner_runtime`; it does not rewrite frozen packet fingerprints. Inspection
deduplication remains actor-scoped and retains original receipts. The existing
idle checkpoint policy and all snooze, watch, approval and wake rules are unchanged.

Inspection results use `communications_inspection.py` on both transports. Only
text proven to equal the original renderer is removed; unfamiliar text stays.
Tables and explicit same-response pointers preserve all structured fields.
`detail=full` returns the original result. Hosted planners can additionally reuse
exact acknowledged definitions; fresh CLI invocations assume no prior knowledge.
Architecture-1 tactical packets can prefetch up to six visible own-card definitions
from existing inspection evidence, bounded to 12,000 characters of definition
content. They omit already retained exact definitions and label remaining
omissions. Stable symbolic vocabulary likewise uses physical-conversation
references; a replacement context receives the full vocabulary again.
`inspection_chars` records both roles, retaining the previous planner metric.

Legacy pilot-owned table-talk drafts (games without the newer decision-role and
asynchronous diplomacy bindings) have one 300-character message and one 160-character purpose,
stored in the current short-term component. A new short-term update replaces the
draft, including clearing it on omission. The pilot receives it only when a post is
currently available and its recipient is eligible. Already posted exact text is
suppressed; any own root post since the planning snapshot handles the draft, including
edited or replacement wording. An unrelated prompted reply does not consume it.
Proposals never generate game actions, wakes or response turns. Existing
public posts and their immediate response decisions retain their original rules.
Fresh asynchronous diplomacy games instead route public talk to the dedicated
diplomat lane; deciders never receive talk-only turns. See AGENT_ARCHITECTURE_V1.md.

Release validation covers reconstruction, missing/null fields, stack order, wrong baselines, checkpoint resets, privacy and unchanged legal choices. Diagnostic archives are not part of the distribution.

Host `communication_chars` telemetry records source/delivered character totals
and packet counts by role. These measure serialization savings, not model tokens,
latency, reasoning quality or win rate. Raw archives are intentionally unchanged.

Idle host checkpoints bound the re-delivered card-definition cache; this is an
explicit memory-selection policy, separate from the lossless communication codec.
Archived definitions remain inspectable and are not eligible as already-delivered
references. Full strategic prose and source evidence are not truncated.
