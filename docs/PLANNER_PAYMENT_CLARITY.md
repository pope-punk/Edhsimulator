# Planner command validation and automatic additional mana costs

Planner actions are checked for command shape at publication, before a decider
can approve them. Errors name the command, missing fields and unexpected fields.
This validation is structural: a future land play or combat action is not rejected
because it cannot execute at the planner's current observation.

An empty `targets: []` on `play_land` is safely removed. A nonempty target list,
unknown field or malformed reference is rejected at publication. The original
publication digest is retained for idempotent retries; the normalized plan is
what reaches the decider. Templates and examples now distinguish land commands
from targeted spells rather than suggesting targeting fields for every action.

The ordinary autotapper remains the fast path. A bounded fallback simulates
mana abilities and their full native costs, including life, creature taps,
counter removal, and supported sacrifice/discard/exile/return selections. It
validates cumulative resource use and the final action on isolated kernels.
Only actual mana choices can be answered inside this bundle; arbitrary effect
choices still require a planner sequence. Explicit planner payments remain usable.

Ordinary sources are preferred. The fallback prefers a surviving payment among
its discovered candidates; a legal payment that reaches zero life is permitted
if it does not find one. Paying more life than the player has is never legal.
State-based actions and trigger placement wait until the complete action payment
finishes. The accepted payment records exact costs and mana choices for replay.
Failed search or execution leaves the live state untouched.

Search is bounded (64 explored states, up to 12 distinct sources, 32 alternatives
per selected cost group). It is not a claim of complete solving for every mana
engine. No unknown non-mana choice, optional spell parameter or gameplay action
is inferred by this search. Insufficient optimistic total mana is rejected before
simulation; normal payments do not pay the fallback's search cost.

Repeated decision documents omit unchanged sections and Oracle entries rather
than adding an 'unchanged since previous input' marker. Current decisions, action
labels and complete plan prose retain their existing delivery rules. New physical
conversations retain self-contained baselines; original evidence remains intact.

This change includes an engine payment-timing fix and must be released as a new
fingerprint-bound build. It does not alter an already running game's bound rules.

For the integrated publication, approval, execution, recovery and telemetry path,
see [Main-phase action intents](INTEGRATED_ACTION_INTENTS.md).
