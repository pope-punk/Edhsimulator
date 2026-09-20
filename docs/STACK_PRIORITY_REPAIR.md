# No-action priority checks with a nonempty stack

Game O (`web-campaign-20260920-o`) exposed a blanket exception in
`mana_only_window`: any nonempty stack prevented automatic passing. Reaminatour
therefore received a real inference at accepted action 282, responding to
Sakura-Tribe Elder on turn 8, with Mystic Remora and two tapped lands.

The affordability proof now also runs with a nonempty stack. A main phase is
considered a sorcery-speed window only when the stack is empty. Free spells,
free alternative costs, flash, usable abilities, floating mana and uncertain
resource/effect cases retain pilot control. Required choices are still dispatched
separately; this does not suppress Mystic Remora's optional draw or upkeep payment.
Rules priority and exact pass records remain; only proven no-action inference is
skipped. Unknown cases remain conservative, so this is not a claim that every
unnecessary inference has been eliminated.

The user explicitly authorized pause, fix, application to the current game and
resume. The `affordable_stack_priority` scheduler-upgrade scope permits only
`primitive_priority.py`, `primitive_actions.py` and its own upgrade verifier.
It requires matching before/after release evidence, unchanged rules identity,
assets, strategy and game contract, the exact stopped prefix, unloaded/exited
host and transport, and no unresolved transaction/help/rules blocker. Full offline
replay must match the current snapshot before the exception is journaled.
Existing claims, plans and snoozes are preserved. The normal fenced Resume route
then resumes the same game; installation does not choose or replay live actions.

Validation: 18 priority tests and 10 upgrade tests passed, including the actual
Remora/Sakura scenario, free/alternative responses, floating mana, zero-cost
abilities, own-main sorcery restrictions, unchanged state, active-host rejection,
restricted upgrade scope and idempotent application.
