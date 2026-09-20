# Automatic filter payments and immediate technical support

Pure tap-for-mana abilities with a finite mana input are now supported by the
autotapper. The fast free-source search runs first. If it cannot pay, a bounded
search considers ordered funding and filtering: each permanent is tapped at most
once, its input must already exist, and only then is its output credited. Fixed,
hybrid and color-choice filter outputs retain their native validation.

The selected sequence and final payment execute on an isolated kernel and commit
atomically. A failed payment leaves the live pool and permanents unchanged.
Surplus production is not silently spent. Tagged mana is not treated as
unrestricted filter input. Sources with life, sacrifice, creature-tapping or
other consequential effects retain their existing planner-only boundaries.

The fallback is a bounded feasible-payment search, not an assertion of globally
optimal future-hand play. Existing free-source portfolio preferences remain.
Decision menus explicitly say that a verified automatic payment includes supported
filter costs and color choices; the decider submits the chosen spell or ability,
without preliminary taps or planner mana steps.

## Explicit repair of game N

`primitive_payment_repair` records an operator-authorized exception for the
payment implementation at a stopped, unloaded technical frontier. It validates
before/after release fingerprints, a narrow module allowlist, unchanged rules
identity/assets/strategy, exact process identities and the accepted prefix.
Full deterministic replay must match before installation. The original game
configuration is not rewritten. Plans, strategic choices and accepted actions
are preserved. Only the frozen action menu is recomputed at that same position;
a technical-update notice explains the capability repair.

The retained help question still requires the ordinary exact-prefix `answer-help`
command. Resumption uses the existing fenced dashboard route.

## Immediate help listener

`tools/watch_pilot_help.py --mode support --interval 2` watches NEXT_ACTION and
starts a separate technical operator for a new request. Configure `--run-id`,
`--dashboard-url` and `--key-file` explicitly when running from another worktree.
The release-receipt environment must match that worktree's current implementation.

A durable receipt is written before dispatch. It records request identity,
creation/start/finish timestamps and worker PID; operator events stream to disk
while it runs. Uncertain results escalate once and are never blindly retried.
The operator may answer schema questions and resume a verified stopped game. It
cannot choose gameplay, change runtime source, migrate contracts, create games,
replay actions, override a user pause or bypass a rules/combo/horizon blocker.
The listener stops when its selected game closes. It is independent of the
10-minute terminal keepalive, so routine help is not delayed until a heartbeat.
