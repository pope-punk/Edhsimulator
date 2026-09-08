# EDH Agent Gauntlet

A four-seat Commander simulation with AI pilots, independent planning and diplomacy,
and a deterministic Python referee. The pod is Reaminatour (Aminatou), Minsc & Boo,
Omo and Elenda. This is a fixed-deck research engine, not a complete Magic rules implementation.

## Install from a checkout

Use Python 3.10+ and a Codex installation with access to the configured models.
From the repository directory:

```sh
python -m pip install -e .
python -m edh_gauntlet verify
```

The built-in release check verifies the catalog, deck/strategy hierarchy, implemented
abilities and event-visibility coverage. It is not a behavioral test suite or a claim
that every card interaction is supported. See [validation](docs/VALIDATION.md).

Windows also supports `gauntlet.cmd` and `gauntlet.ps1`. Activate your Python environment
or set `EDH_PYTHON` to its executable. No machine-specific interpreter installation is required.

## Initialize and run

```sh
python -m edh_gauntlet --cohort runs/example init --games 1 --seed-start 2026090914 --max-rounds 16 --agent-architecture --async-diplomacy --learning disabled
python -m edh_gauntlet.host_runtime --cohort runs/example --max-decisions 10000 --context-tokens 64000 --timing-events 4096
```

For a hidden Windows host with a local process watcher:

```powershell
.\tools\start_host_game.ps1 -Cohort runs/example -MaxDecisions 10000 -TimingEvents 4096
```

The host controls agents through Codex App Server JSON-RPC. No desktop clicking or
model coordinator is required. Model availability depends on the installed service;
the current routing is Terra-low decisions, Terra-high short-term planning, Sol
long-term planning, and Luna-low diplomacy, with bounded capacity fallback.

`--learning enabled` (the default) requires the sealed post-game review and learning
transaction before advancing. `--learning disabled` records an explicit skip, avoids
learning evidence packets and inference, and leaves strategy memory unchanged. The
setting is bound when a run is initialized. It does not change a started game's policy
or waive rules blockers. [Learning policy](docs/LEARNING.md)

`NEXT_ACTION.json` is authoritative. The host stops for a terminal result, adjudication,
rules blocker, decision cap or explicit pause. For multi-game cohorts, advance only
when the lifecycle says `advance_game`; do not create agents for a future game early.
A local watcher reports attention without spending inference on unchanged status.
[Campaign workflow](docs/GAUNTLET_WORKFLOW.md)

## Planning and execution

- Four deciders handle actual game choices. Python validates all submissions.
- Each seat has separate persistent short-term, long-term and diplomacy contexts.
  One inference lane per role permits concurrent work without a model coordinator.
- Static standing files supply deck doctrine. Long-term planners retain the full seed
  and write the opening goal after keep/mulligan. Diplomats own all public speech.
- Short-term planners maintain concise prose and exact proposed actions. Fresh games
  require updates at the two preceding living opponents' end steps, with explicit
  precombat, combat and postcombat coverage.
- Pilots accept, reject, reorder, edit or append batch actions during real decisions.
  Routine priority passes preserve approved sequences. New information, opposing
  intervention and required choices stop execution for renewed judgment.
- Plans, card knowledge and actor-visible differences use one bounded communication
  adapter. Historical evidence stays inspectable without repeating board timelines.

[Architecture](docs/AGENT_ARCHITECTURE_V1.md) · [Approved sequences](docs/APPROVED_SEQUENCES.md)
· [Host runtime](docs/HOST_RUNTIME.md) · [Communications](docs/COMMUNICATIONS.md)

## Observe and export

Create `OPERATOR_VIEW.json` in the cohort with `{"enabled":true}` before launching
(or before initializing in a pre-created cohort directory). The four files in
`operator/` show hands, life, permanents, graveyards, turn order, active/living seats,
current plans and the messageboard. These omniscient views never enter agent packets.

The Windows `tools/collect_host_telemetry.py` records local timing and process memory metadata;
`tools/report_host_segments.py` combines complete segments, and
`tools/report_sequence_utilization.py` measures actual batch shortcuts. Packet bytes,
model input tokens, cached tokens and elapsed inference time are distinct metrics.
Generated files belong under `runs/` and are excluded from GitHub.

A proposed no-login remote dashboard and CSV specification workflow is described in
[REMOTE_DASHBOARD.md](docs/REMOTE_DASHBOARD.md). It is a design, not a deployed service.

GitHub/Codespaces preparation and the preserved decision-305 game are documented
in [GITHUB_HANDOFF.md](docs/GITHUB_HANDOFF.md). Repository publication does not
automatically start or migrate a game.

## Project map

- `src/edh_gauntlet/`: referee, lifecycle, agent host, planning, communication and reporting modules.
- `data/catalog/`, `data/decks/`, `data/reference/`: canonical card facts and deck inputs.
- `data/strategy/`: advisory strategy, seed plans, static standing plans and personalities.
- `docs/`: current operational contracts and architecture.
- `tools/`: launch/recovery, observation and data-maintenance entrypoints.
- `reports/`: concise release evidence. Local generated runs and archives are not source.

[Module responsibilities](docs/PROJECT_LAYOUT.md) · [Documentation index](docs/README.md)

The pre-release test suite and diagnostic archives were removed at the operator's
request after validation. Release evidence records exactly what was tested and what
was not. Future changes should receive new focused validation before deployment.
