# Project responsibilities and dependency boundaries

The repository uses a single Python package with explicit module names. Public
module/CLI paths remain stable rather than moving them into new nested packages
that would invalidate import paths, registered commands and recovery tools.

| Layer | Primary modules | Responsibility |
| --- | --- | --- |
| Card facts | catalog, ability_registry, engine card definitions | Printed facts and executable capabilities; no pilot strategy |
| Rules | referee, engine, scheduler, block_declaration, combat_damage | Legal choices, seeded replay, priority, combat and snoozes |
| Campaign | campaign, learning_policy, quarantine, review_contract | Frozen run settings, lifecycle, terminal seals and learning transactions |
| Agent transport | host_runtime, host_context, host_routing, host_failures, host_watch | Isolated conversations, capacity, bounded contexts and local supervision |
| Decision delivery | pilot_handoff, pilot_dispatch, pilot_session, handoff_runtime | Claimed immutable inputs and actor-scoped submissions |
| Planning | planner_runtime, split_planning, planner_stages, component_store, background_slots | Role reservations and immutable publications |
| Tactical execution | sequence_contract, sequence_runtime, turn_batches, combat_proposals | Exact pilot-approved actions and continuation boundaries |
| Strategy | strategy, static_standing, plan_tiers, goal_validity, diplomacy | Deck doctrine, current plans, assessments and authorized speech |
| Communication | communication_codec, context_packets, pilot_plan_packet, continuity_diff | Bounded lossless presentation; no game choices |
| Observation | operator_view, host_telemetry, reporting tools | Omniscient human views and metadata, never agent authority |
| Persistence | runtime_store, paths | Atomic writes/locking and shared asset discovery |

`paths.py` resolves the same data/policy root for editable source checkouts and
installed distributions. `EDH_PROJECT_ROOT` explicitly selects a checkout if needed.
The wheel includes required data and policies under share/edh-gauntlet. Operational
PowerShell helpers use one `python_runtime.ps1`; set EDH_PYTHON or activate Python.

The four data directories have different authority: catalog/reference store card
facts, decks store composition, strategy stores advisory knowledge. Strategy must
not select referee actions. Per-run snapshots preserve that distinction during play.

Tools are grouped by purpose in tools/README.md. Generated cohorts and telemetry go
under runs/; they are ignored by Git. Historical archives and disposable tests are
not shipped. A concise validation report survives cleanup. Python modules remain
small where responsibilities permit; the large rules adapter stays together until
a separately validated rules refactor can preserve its timing/trigger invariants.
