# Primitive combo proposals

Fresh primitive hosts restore the legacy division of authority: the tactical
planner describes a concrete loop; the decider chooses whether to propose it;
opponents report whether they can disrupt it; an independent rules adjudicator
verifies the shortcut. No model may declare its own proposal approved.

The optional actions-stage `combo_proposal` contains `proposal_text` (1–1200
characters), `seat_turn`, `phase` (precombat_main/postcombat_main) and `requires`
(up to eight `{source:{card_id,incarnation},zone,controller}` guards). These are
primitive exact-reference guards, not legacy UID predicates. A newer actions
publication that omits the proposal clears it. Offers require the matching own
turn/main phase, priority, an empty stack and satisfied guards. A frozen claim
keeps its offer even if a planner later publishes another plan; execution checks
its exact current guards again. Proposals are consumed once selected.

The decider receives `combo_offer` and may call `edh_propose_combo(proposal_id)`.
Each other live seat gets a `combo_consent` decision and answers with
`edh_combo_consent(accept,rationale)`. A NO cancels the shortcut and restores
normal priority immediately. A YES is only a statement of no disruption. All
YES responses produce `NEXT_ACTION: adjudicate_combo`, with a request path and
hash bound to the game, proposal, accepted prefix, public state and consents.
The host stops and unloads before adjudication.

Follow GAUNTLET_WORKFLOW: use an independent rules adjudicator with the sealed
request. The existing `combo_adjudication` validator supplies the closed response
schema and approved/rejected/needs_demonstration verdicts. Apply its actual
response using:

```
python -m edh_gauntlet.primitive_lifecycle --cohort RUN adjudicate-combo \
  --response RESPONSE.json --expected-sequence SEQUENCE --expected-sha256 SHA256
```

Approved `damage_player`, `set_life` and `bounce_permanents` outcomes enter the
ordinary durable command tape. They represent adjudicated net outcomes, matching
the legacy shortcut interpretation rather than simulating infinitely many loop
iterations. `infinite` life uses the legacy bounded sentinel of 10^18 with the
original response retained in evidence. Bounce UIDs use `card_id@incarnation`;
zone replacements, commander choices and resulting triggers use the normal
checkpointed movement machinery. Invalid targets are rejected before mutation.
Pilots and planner sequences cannot submit the privileged outcome command.

A duplicate identical adjudication returns its receipt, never reapplies effects;
a conflicting response is rejected. Rejected/needs_demonstration verdicts change
no game actions. Nonterminal outcomes require normal fenced dashboard resumption;
terminal outcomes follow NEXT_ACTION. Explicit operator pause markers block
application. No started contract is migrated by these changes.
