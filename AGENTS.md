# EDH gauntlet agent entrypoint

For fresh games explicitly binding `agent_architecture:1`, the role, component,
escalation and scheduling rules in [AGENT_ARCHITECTURE_V1.md](docs/AGENT_ARCHITECTURE_V1.md)
supersede the single-planner instructions below. Sol owns strategic goals; static standing files serve fresh split games;
Terra-high owns continuity and tactical prose/actions; Terra-low owns decisions.
Fresh split software hosts use independent short-term, long-term and diplomacy
inference lanes alongside one decision lane. Each lane admits one seat at a time;
waiting pilot tools retain context without occupying an inference lane. Older
hosts retain serialized admission until explicitly upgraded at a verified stop. Optional
`async_diplomacy:1` routes authorized public conversation to Luna-low and removes
forced reply decisions. Neither binding changes existing games. Use the current host and fenced stopped-host recovery for this architecture.


Enrolled seat communications use the shared egress adapter described in
`docs/COMMUNICATIONS.md`: lossless records, named comparison origins, and exact
references bound to an acknowledged physical conversation. Preserve original
evidence and complete pilot plan prose; new conversations and standalone CLI
deliveries receive self-contained baselines. Presentation does not alter scheduling
or a started game's contract.

Software-host routing uses Terra-low deciders, Terra-high short-term planners,
Sol long-term planners and Luna-low diplomats in fresh split games. Legacy
single-planner contracts use Sol planners. See docs/HOST_RUNTIME.md for bounded capacity fallback between those
role models. Only zero-tool terminal capacity failures are retried; never replay
accepted actions or planner stages. Explicit stopped-transport recovery preserves
logical seats and the exact accepted prefix; it is not a game-contract migration.

Fresh contract-4 games bind `context_handling:1`; see `docs/HOST_RUNTIME.md` and
the concise `docs/HOST_AGENT_POLICY.md`. Bounded transcript checkpoints happen
only at idle seat boundaries, preserve the same registered seat role/identity, and never rewind
the game or change planner scheduling, snoozes, approvals or accepted decisions.
Host transport_version:2 uses a fresh isolated model conversation at checkpoints
while preserving the logical seat agent ID and explicitly delivering retained
memory in the next real input. Never silently resume legacy rollback contexts.
Use local process watching, not model heartbeats, for unchanged status.
Keep full material events in actor-scoped evidence and all own-seat rationales
in decision context. Default packets supply current state, only the latest actual
pilot-seen board, rationales/rejection explanations and transient summaries, not
per-rationale boards or engine timelines.
Original boards/history remain inspectable. New handling can be enabled
for unstarted games using `planner_runtime enable-next-game`; do not silently
migrate a started game's bound contract. Unattended hosts use approvalPolicy
never and stop on unexpected approval requests instead of asking the terminal.

The opt-in software host in `docs/HOST_RUNTIME.md` replaces model-to-model routing
only for a fresh contract-4 game launched with `edh_gauntlet.host_runtime`.
Its isolated App Server contexts use actor-scoped dynamic tools; Python routes
directly and may retain a waiting submission call. Desktop collaboration contexts
continue to follow the direct-handoff policy below. Never silently adopt or migrate
a running/paused game into the software host.

Planning contracts 2, 3 and 4 are game-bound extensions. When game_config.json explicitly
sets `planning_contract` to 2, 3 or 4, follow `docs/SPLIT_RUNTIME_POLICY.md` for decider
claim/read, planner scheduling and fenced exception recovery, and
`docs/PLANNER_RUNTIME_POLICY.md` for each planner. Create/reuse one isolated
persistent planner per seat/game with `fork_turns="none"`, alongside its separate
decider; admit at most one planner at a time and reserve three activation slots
for coordinator/outgoing/incoming deciders. This is a gameplay delegation
requirement, not authorization to delegate repository work. Healthy handoffs
remain direct. The coordinator may relay only an explicit fenced recovery route
after checking host execution status. Contract 1 or a missing field retains the
legacy planning/delivery rules below. Never migrate a started game silently.

For every request to play, smoke-test, resume, or run a gauntlet, first read and
follow `docs/GAUNTLET_WORKFLOW.md`. It is the authoritative campaign lifecycle;
`docs/MANUAL_REFEREE_PROTOCOL.md` is the in-game authority.

After every campaign command, follow the cohort's `NEXT_ACTION.json`. New runs
choose `--learning enabled|disabled`; missing legacy settings mean enabled. With
learning enabled, a terminal game remains unfinished while review is pending:
review all four private evidence packets and apply one consolidated response,
including explicit reviewed no-change when appropriate. With learning disabled,
Python writes a bound skip receipt, omits learning packets and leaves strategy
unchanged. Disabled learning never bypasses a rules blocker. Never claim a skipped
review was performed. See `docs/LEARNING.md`.

If the next action is `retry_learning_transaction`, retry that exact `learn`
command before inspecting, answering, rewinding, or advancing gameplay.

Stop pilot dispatch immediately for a rules blocker, a user pause/stop instruction,
or missing authority. A true referee blocker ends that game as a tagged draw; do
not try to continue its play. Never use ordered future-library information, and
never treat one pilot's private post-game evidence as information another pilot
had during play.

For revision-6 gameplay, follow `dispatch_pilot` using one persistent isolated
sub-agent per seat, initially created with `fork_turns="none"`. Reuse that agent
only for the same seat and game on a continuing accepted branch. This is an
explicit delegation requirement for gameplay, not for repository implementation
or reviews. Give the pilot only
its current brief/context paths, actor-scoped inspection commands, and the game
protocol. Do not send prior conversation, another pilot's files, shared analysis,
or post-game review material. The coordinator must not make gameplay choices or
read private packets. The pilot may submit its own structured answers through
`python -m edh_gauntlet.pilot_session --cohort PATH --actor SEAT --response PATH`.
Every ordinary call validates and accepts at most one pilot-authored choice. Only
contract 4 permits a batch of explicitly pilot-approved symbolic choices under
`docs/APPROVED_SEQUENCES.md`; Python stops at the first execution boundary. Each call follows
NEXT_ACTION, and returns a compact update only if the same seat still owns the
  decision. The pilot may handle consecutive own-seat decisions in one work turn;
  it must return immediately on `handoff`, `stop`, or `fresh_context_required`.
  It must never open the next seat's packet. The outgoing pilot directly wakes a
  compatible incoming seat; the coordinator creates fresh seats and handles
  lifecycle/review work. Follow `docs/PILOT_RUNTIME_POLICY.md` for
initialization, resumption and immediate handoff. Register each seat agent once
with `pilot_dispatch`; checkpoints validate its previous `seat_session` with
`pilot_handoff.can_resume_session` and publish the prepared private delivery and
metadata-only route. Forward a current route immediately without an additional
dispatch-check command or repeated initialization instructions. On a resume route,
the outgoing pilot forwards the exact generated prompt directly to the canonical
  incoming agent and reports `forwarded: true`; the coordinator never relays a
  resume prompt and creates only a requested fresh agent. Before starting or
  resuming play, finish or cancel unrelated `running`/`pending_init` agents so
  root, outgoing seat, and incoming seat can occupy three concurrent activation
  slots. On a capacity failure, clear the stale task and ask the outgoing seat to
  retry its retained route; do not copy its prompt into a coordinator dispatch.
  Refresh NEXT_ACTION
after an intervening lifecycle change before using an old route. Discard
contexts after any rewind, rebase, game change, or exposure to another seat's
private information. A recoverable rules work-item tag alone does not invalidate
an otherwise compatible seat context. Never reuse a review agent as a gameplay pilot. If
isolated contexts cannot be created, stop rather than play all seats in one
reasoning context.

On discovering a recoverable rules defect, record it with `quarantine` as a
temporary game work item. Keep its prominent tag through the engine repair and
the mandatory skeptical post-game synthesis; do not replace that game. An
`UnrefereedDecisionError` is game-breaking: seal the accepted prefix as a draw,
record the defect, repair the engine when hotfixes are authorized, complete the
skeptical learning pass when learning is enabled, and retain the quarantined game.
Advance only when NEXT_ACTION permits it. Explicitly suspended hotfixes/learning
remain suspended; never silently migrate the game to change those choices. Revalidate
any previously published learning with the bound independent rules review in
`docs/GAUNTLET_WORKFLOW.md`. A cancelled run does not by itself remove learning.
