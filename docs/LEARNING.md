# Run-level learning policy

Choose `--learning enabled` or `--learning disabled` on `init`. Python callers use
`campaign.init(..., learning_enabled=False)`. The default is enabled. The cohort
manifest records the choice and each game freezes it in game_config.json.

Enabled runs require the four-pilot post-game review and atomic learning transaction.
An empty, reviewed patch records no_changes; a supported patch records applied.
Interrupted prepared transactions must be retried exactly. Only future games adopt
changes to the strategy bank.

Disabled runs still seal terminal results and retain gameplay/observer output.
They omit postgame_evidence and postgame_review packets, write a small
`postgame_learning/skipped.json` receipt bound to the terminal fingerprint, and
report `skipped_by_configuration`. No reviewer is scheduled, no learning response
is fabricated, and no strategy mutation is permitted. Normal cohort advancement
uses this explicit resolved state. CSV generation must label the learning setting.

The flag is not a rules-relaxation switch. Legality validation, referee blockers,
quarantine gates and accepted-prefix fencing still apply. It is also distinct from
a temporary operator request to defer review in an already-started enabled test.
An existing game without the flag remains enabled; changing the parent manifest
does not silently alter a started game's binding.
