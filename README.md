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

## Validate and run the primitive engine

The primitive engine has authored programs for all 334 unique cards in the fixed
400-card pod. Its hosted release scope is **multi-game campaigns with learning disabled**, operated through the web dashboard.
Full-card authoring and passing tests do not certify every possible interaction.
See [release status](docs/PRIMITIVE_RELEASE.md) for validation and hosted-trial results.

From the source checkout, create a release receipt before initializing a new run:

```sh
python -m edh_gauntlet.primitive_release --output "$PWD/archive/releases/local-release.json"
export EDH_PRIMITIVE_RELEASE_RECEIPT="$PWD/archive/releases/local-release.json"
python -m edh_gauntlet.primitive_lifecycle --cohort runs/example init --games 20 --seed 2026091503 --starting-player Omo --max-rounds 32 --learning disabled
python -m edh_gauntlet.host_runtime --cohort runs/example --max-decisions 10000 --context-tokens 64000 --timing-events 4096
```

Use a fresh receipt filename and an empty cohort path. The validator runs the full
repository suite, builds and installs a wheel, checks installed assets and compares
source and installed fingerprints. Set the environment variable in every shell
that starts the host. In PowerShell, use `$env:EDH_PRIMITIVE_RELEASE_RECEIPT`.
Changes to bound runtime files require a new matching receipt.

The host controls isolated agents through Codex App Server. Current routing uses
Terra-low decisions, Sol-high Fast tactical planning, Sol strategic planning and
Luna-low diplomacy, with bounded capacity fallback. Sixteen seat/role lanes keep
private contexts separate.

`NEXT_ACTION.json` is authoritative. Rules-review terminal draws retain their
accepted prefix and evidence; they cannot resume. Learning-disabled runs record
an explicit skip and make no strategy updates. A horizon stop is unfinished play,
not a result. [Campaign workflow](docs/GAUNTLET_WORKFLOW.md)

### Existing legacy games

The original `python -m edh_gauntlet` campaign CLI and Windows launch helpers serve
legacy cohorts and their original contracts.
Existing games keep their original engine, configuration and recovery rules.
Never initialize over a saved cohort or switch its engine to continue it.
[Legacy host runtime](docs/HOST_RUNTIME.md) · [Learning policy](docs/LEARNING.md)

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

## Online interface and reports

Run the dashboard with a private capability key and the same validated release selected:

```sh
export EDH_DASHBOARD_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m edh_gauntlet.dashboard --host 0.0.0.0 --port 8765 --runs runs
```

Open the private forwarded Codespace port and connect with that key. Configure a
campaign, then select **Start supervisor**. The supervisor starts isolated hosted
roles and advances only after a verified completed game. Pause and explicit Resume
retain the accepted prefix. A rules blocker stops the campaign for operator review.

The existing tabs show the live table, all four seat views, full decision log,
messageboard, results and Aminatou cardwise ratings. Card statistics use original
physical cards, count transient battlefield entries, exclude tokens/copies, and
require matching terminal journals and learning-skip receipts. Rules-review games
remain visible in results and are excluded from verified cardwise percentages.
Operator views never enter pilot inputs. Generated runs and evidence stay local.

[Dashboard deployment](docs/DASHBOARD_DEPLOYMENT.md) · [Release status](docs/PRIMITIVE_RELEASE.md)

## Project map

- `src/edh_gauntlet/`: referee, lifecycle, agent host, planning, communication and reporting modules.
- `data/catalog/`, `data/decks/`, `data/reference/`: canonical card facts and deck inputs.
- `data/strategy/`: advisory strategy, seed plans, static standing plans and personalities.
- `docs/`: current operational contracts and architecture.
- `tools/`: launch/recovery, observation and data-maintenance entrypoints.
- `reports/`: concise release evidence. Local generated runs and archives are not source.

[Module responsibilities](docs/PROJECT_LAYOUT.md) · [Documentation index](docs/README.md)

The current repository includes the complete conformance suite under `tests/`.
CI runs it on Windows and Linux. Earlier September 8 cleanup and paused-game
reports are historical evidence; current release status is recorded separately.
