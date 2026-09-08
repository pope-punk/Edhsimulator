# Operational tools

Launch and recovery: start_host_game.ps1, watch_host_game.ps1, python_runtime.ps1,
resume_stopped_host.ps1/.py and reservation_recovery.py. Start only fresh games;
recovery requires an explicitly diagnosed stopped prefix. `read_pilot_turn.ps1`
supports the older isolated desktop dispatch path.

Observation: collect_host_telemetry.py (Windows process collector), analyze_cache_probe.py (the shared cache
accounting library), report_host_game.py, report_host_segments.py,
report_agent_architecture.py, report_decision_workflow.py,
report_sequence_utilization.py and export_plan_trace.py. Reports read metadata or
explicit actor-scoped records and do not dispatch inference. Keep outputs under runs/.

Review: read_review_packet.py and read_review_anchors.py provide bounded evidence
reads for a learning-enabled terminal game. They do not manufacture a learning response.

Data maintenance: generate_card_catalog.py, generate_strategy_profiles.py and
rules_scan.py. Generation is an explicit maintenance operation; it is not part of
every game. The runtime's `verify` command checks catalog/strategy consistency.

Disposable probes, benchmark scripts, fixture-specific review fillers and the test
runner are removed from the release after validation. The runtime API remains in
src/edh_gauntlet; these files are operational entrypoints, not a second game engine.

Handoff: open_handoff.py decrypts an authenticated saved-game archive to a new ZIP
using a separately supplied private key. Its optional dependency is cryptography.
It never imports, extracts, or starts gameplay.
