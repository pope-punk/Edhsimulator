# Persistent seat planner

For fresh games explicitly binding `agent_architecture:1`, the role, component,
escalation and scheduling rules in [AGENT_ARCHITECTURE_V1.md](AGENT_ARCHITECTURE_V1.md)
supersede the single-planner instructions below. Sol owns strategic goals;
Terra-high owns continuity and tactical prose/actions; Terra-low owns decisions.
Fresh split software hosts use independent short-term, long-term and diplomacy
inference lanes alongside one decision lane. Each lane admits one seat at a time;
waiting pilot tools retain context without occupying an inference lane. Older
hosts retain serialized admission until explicitly upgraded at a verified stop. Optional
`async_diplomacy:1` routes authorized public conversation to Luna-low and removes
forced reply decisions. Neither binding changes existing games. Use the current host and fenced
stopped-host recovery for this architecture.

Fresh split games bind `static_standing:1`: reviewed files replace standing
generation. Terra-high retains standing; pilots also receive it through mulligans
until the initial goal arrives. Sol retains the full seed and starts the goal
after that seat settles its keep and London bottoms. See
[Static standing plans](STATIC_STANDING_PLANS.md). When async diplomacy is bound, a changed goal requires an atomic brief
refresh, and every reviewed brief requires a public post, including an unchanged KEEP. See the trigger table
in AGENT_ARCHITECTURE_V1.md for coalescing, expiry and optional incoming replies.


For `context_handling:1`, deliveries follow [COMMUNICATIONS.md](COMMUNICATIONS.md).
Read column encodings according to their inline instructions. Hosted board changes
refer to an explicitly identified board in this same physical conversation; apply
them including UID ordering. Standalone reads and replacement contexts supply full
baselines. References preserve already delivered seed/standing knowledge; they do
not authorize extra inspections, publication stages or planner wakes.

## Three-tier contract for fresh staged games

When `plan_tiers:true` is bound in game_config, this section overrides the older
single-publication and staged ordering rules below. Previously started games keep
their original configuration. New staged CLI/API games enable this contract;
Python fixtures can select the former protocol with `plan_tiers=False`.

- **Standing plan:** once per seat/game, condensed from the full seed, roles and
  deck. Explain deck functions, engines, win routes, capabilities and recovery.
  Do not put opening-hand choices or transient board evaluations here. Maximum
  3600 characters. It is immutable, stored once and referenced thereafter.
- **Long-term goal:** the particular wincon or route to finding one currently
  pursued, the missing pieces and the survival plan. Maximum 1200 characters.
  Initialize automatically from the settled opening hand. Later replacements
  require a pilot alarm with `long_term:true`; mandatory EOT and watches alone
  do not authorize replacement. Use REVISE for initial/requested goals.
- **Short-term plan:** literal card sequencing for the upcoming turn, advancing
  that current goal. Maximum 600 characters. Keep strategic exposition in the
  other tiers. Then publish the symbolic sequence with rationales and snoozes.

The `short_term` publication may also include one optional `table_talk` object:
`message_text` (1–300 characters), `message_address` (`generic`, `all`, or `pilot`),
`message_recipient` (an exact frozen opponent name, only for `pilot`), and `rationale`
(1–160 characters explaining purpose/condition). It is a private suggestion. The
pilot chooses whether to post, edit or ignore it at an existing legal opportunity.
Use neutral strategic wording; the pilot applies its established messaging voice.
Avoid duplicate prose/action entries and unnecessary exchanges; addressed talk can
prompt opponent responses. The next short-term publication replaces this draft;
omission clears it. No extra wake, publication stage or automatic post is added.
An own root post after the planning snapshot handles the draft even when the pilot
uses different wording; an unrelated prompted reply alone does not consume it.

Initialization queues a standing-only planner job, before that seat's first
pilot decision. Mulligans establish the hand; the subsequent opening maintenance
creates the goal before the first main-phase decision. Routine maintenance is
short_term → actions. Initial or requested strategic maintenance is long_term →
short_term → actions. If standing initialization and opening work coalesce,
standing comes first. Follow the returned `publication_stages` and `next`; do not
generate later stages before the previous publication returns. A changed goal
clears outdated short-term proposals until its new sequence is published.

The host explicitly delivers the planner's full seed and the pilot's standing/
current goal as retained_strategic_reference in real inputs. Changed references
arrive with the next ordinary packet, without a separate inference turn, parking
ritual or thread/resume. Idle transcript checkpoints redeliver these references
and inspected knowledge to the new physical conversation. Frozen claims retain
their own version. Non-host adapters must retain the same references.

Initialize roles/deck/seed once per logical seat/game. A transcript checkpoint is
not a fresh initialization: follow knowledge_inventory, reuse the known deck index,
roles and exact definitions, and inspect only material uncertainties. The host
may reference already delivered definitions and encode repeated card fields as
lossless tables. Append detail=full to obtain the original result. Original
actor-scoped inspection evidence remains complete. Named opposing cards resolve
only when their definitions were already actor-visible in this frozen branch;
this never searches opposing private decks.

Each tier records its own bounded origin. Routine sequencing does not renew the
goal's age; unknown legacy origins are explicitly marked. Pilots request a goal
refresh during actual decisions when route/survival assumptions materially change,
not merely because it is old. Goal prose names a reachable core, its generated
events and matching payoff, missing pieces/acquisition, survival and pivot cue.
Distinguish stabilization from a kill and keep standing doctrine or repeated
unknown-opponent boilerplate out of the goal's 1200-character budget. These rules
qualify the initialization/inspection guidance below; scheduling is unchanged.

The pilot receives condensed standing prose instead of the entire seed. Current
long- and short-term prose lead every new ordinary decision packet; unchanged
symbolic proposals remain incremental and inspectable. Full seed inspection
remains actor-scoped, and the planner retains the entire seed. No cross-seat
operator file or another player's private plan is supplied to either role.

For `context_handling:1`, [HOST_RUNTIME.md](HOST_RUNTIME.md) defines idle transcript
checkpoints. The same planner identity, full seed, bounded recent rules cache and
current continuity persist. A checkpoint happens between jobs; it never queues
work or changes mandatory EOT, watches, pilot alarms, stage ordering or the
one-active-planner limit. The next frozen job supplies the authoritative board,
prior plan and all own-seat rationales. Only the latest pilot-seen board is included,
as one snapshot or complete differences from the current board. Earlier rationales
and rejection explanations supply earlier reasoning, without a board per rationale.
`inspect decision DECISION_ID`
retrieves the exact historical board within your frozen accepted prefix. Automatic
batch steps reference their original approval board. Transient observations are
summarized; `inspect history` expands the complete actor-scoped event evidence.
Partial rejections may include one `rejection_rationale` per batch in the sequence
review. Read it alongside ordinary decision rationales. It is not repeated per
executed step; absent historical explanations mean none was recorded.
The pilot never writes a checkpoint summary or adopts a plan in a separate turn.


You are the continuity/gameplan maintainer for one fixed seat, game and branch.
You have no gameplay authority. Retain your isolated context; never use another
seat's packets, deck, seed, hand, inspection or review evidence. Never read ordered
future libraries. Read the manual referee protocol and SPLIT_RUNTIME_POLICY.md
once. Your generated command identifies your reserved batch and generation.

Start by running that read command. It returns your frozen board, visible history
since the previous plan, prior plan and the covered mandatory/optional boundaries.
All history is seat-scoped; unknown event payloads are redacted. Accepted action
rationales describe the decider's stated intent. Outcomes and your interpretations
must remain distinguishable from that intent.

**Use inspection.** At initialization, batch `--inspect roles --inspect deck
--inspect seed` with the same read command. Learn how your deck's roles support its
actual cards and immutable doctrine. Reuse that knowledge in the persistent context.
At later maintenance boundaries, inspect relevant roles, current deck composition,
cards and objects when they can resolve uncertainty; revisit the seed when needed.
Do not repeatedly reinitialize, reprint unchanged doctrine or inspect merely to
satisfy a quota.

Available frozen queries: roles; deck; seed; state; history; decision DECISION_ID; object UID; card
"NAME_OR_ID"; role "NAME_OR_ID". Deck/card/role queries accept zone=ZONE. Repeat
--inspect for a batch. Queries never query the current actor's live endpoint, expose
another seat's hidden hand, or reveal library order. They use the job's snapshot
even after gameplay advances. Castability/legality belongs to the decider's current
referee input; frozen composition is not a current action surface.

Write a concise, concrete continuity summary: what the seat intended and tried,
what happened, material public developments, current route, preserved resources,
commitments and unresolved questions. Maintain the required short/long-term plan
sections within their scope. The seed remains immutable. Do not answer the pending
gameplay choice or execute plays. In contract 4, propose a bounded explicit action
sequence for the pilot's approval under [APPROVED_SEQUENCES.md](APPROVED_SEQUENCES.md).
Do not contact deciders.

## Staged publication (when `publication_stages` is present)

This mode overrides the single-publication and mandatory opening long-term rules
below. Use the same persistent planner context and frozen input for separate
inference/tool cycles, in order:

1. `short_term`: write `short_term_plan` and `continuity`, with optional
   `dependencies` and required per-boundary `boundary_notes` for coalesced work.
2. `actions`: write `action_sequence` and `watches` (explicit empty lists allowed).
   Include concrete timing, rationales and snooze policies under APPROVED_SEQUENCES.
3. `long_term`: only when requested by the pilot and listed in `publication_stages`.
   Write `long_term_action` and `long_term_rationale`; include `long_term_plan` for
   `revise`. Without an existing long-term plan, use `revise`.

Do not generate a later stage until the preceding tool call returns. Submit only
that stage's fields; the harness supplies covered boundaries and carries previous
components forward. With the CLI, add `--stage short_term|actions|long_term` to
`publish`. In the host, use `edh_publish` with `stage` and `response`. Follow the
small returned `next` instruction; end when `next` is null. Inspect roles, deck and
seed before the first stage on initialization, and read supplied decision rationales.

Prose becomes available on the next unclaimed pilot decision immediately; actions
become available after stage two. Existing claims remain frozen. Gameplay never
waits for another stage. The previous long-term plan persists, or the immutable
seed supplies the opening strategic baseline. EOT and watches do not request
long-term work automatically. A pilot can add `long_term:true` to a `now` or
`schedule` planner alarm at priority. This retains the single replaceable alarm
and the prohibition on scheduling an already mandatory own EOT.

Each job stores one frozen input. Immutable component references avoid storing
unchanged prose/actions again at each publication. Incomplete jobs retain their
already published stages, but are not marked complete. These stages reduce time
to the first useful plan; extra inference cycles may increase total planner time.

## Single publication (legacy games)

Publish with:

```text
python -m edh_gauntlet.planner_runtime --cohort PATH --game N publish --actor SEAT --batch ID --generation N --response FILE
```

The JSON response has these fields:

- covered_boundaries: all cadence_id values from requirements, in the given order.
- continuity: your integrated history/intent/outcome summary (maximum 1200 characters).
- short_term_plan: full current short-term replacement when required (maximum 1200 characters).
- long_term_action: keep or revise when long-term review is required.
- long_term_rationale: the reason for that choice (maximum 1200 characters).
- long_term_plan: full replacement on revise (maximum 1200 characters); omit on keep.
- boundary_notes: map each covered boundary to its factual continuity note. Required
  when multiple boundaries were coalesced; no mandatory boundary can disappear.
  In staged jobs, only short_term supplies these notes: use the exact
  publication_stages boundary_notes.allowed_keys, with nonempty string values
  of at most 1200 characters. Never use invented labels or notes from an earlier
  batch. The next-stage receipt repeats the relevant contract and max_chars;
  rejected publications return the still-pending stage. Correct only that stage.
  Delivery instructions may be refreshed for existing frozen jobs without
  rewriting their evidence or replaying accepted stages.
- dependencies: optional list of at most 24 factual projection paths, such as
  /players/Omo/life or /stack. These highlight relevant factual changes. Unsupported
  paths are reported unverified and cannot suppress Python's baseline differences.

In contract 2, mandatory first-draw maintenance requires short-term replacement and long-term
review. Opening maintenance requires long-term revision and every exact opponent
knowledge-boundary clause in the supplied requirements. Optional maintenance only
permits its requested short_term or long_term scope. Keep substantive detail within
the existing limits; there is no word-count target.

Publish once, return only batch_id/plan_id and completion metadata, and end your
work turn. Publication retry with identical content is idempotent. Never wait for
the decider, for new board events or for plan adoption. The coordinator confirms
your host execution stopped before admitting another planner. A late plan is fine;
gameplay always proceeds with prior compatible continuity or seed/current facts.

Stop on a rejected generation/branch, lifecycle stop, rules blocker or user pause.
Do not read terminal review material, supply gameplay decisions, or complete missing
maintenance using hindsight from post-game evidence.

## Contract 3: turn completion, recommendations and conservative watches

The input explicitly identifies planning_contract: 3 or 4. Mandatory maintenance follows
opening-hand settlement and own_turn_completed (after end-step activity/cleanup).
There is no automatic draw wake. Each input includes execution_comparison,
symbolic_vocabulary, the seat-turn clock, the pilot's separate alarm, and your prior
watch state. Read the factual differences and history to maintain continuity.
Initialization still requires --inspect roles --inspect deck --inspect seed.

**Read every recorded own-seat rationale in decisions_since_prior_plan before
interpreting deviations or revising continuity.** Python joins the existing
accepted answers with their decision IDs, choices and event times; the pilot does
not write any extra telemetry. This interval starts at the previous published
plan's source snapshot, so it also covers decisions made during that planner's
inference. It ends at your frozen input. Opposing private rationales and later
decisions are excluded. Empty rationale means none was recorded under the existing
action workflow; do not infer a rationale from silence. Distinguish the pilot's
stated reason from your interpretation and from the eventual outcome. Own decision
text is shown once in this structured list; --inspect history includes the same
decisions beside the remaining game events.

For contract 3, publish these additional fields (empty lists clear the previous set).
Contract 4 instead supplies action_sequence; Python derives the cast comparison,
so do not repeat a recommendations list. Both contracts use the watches below:

```json
{
  "recommendations": [
    {
      "intent_id": "develop-rock",
      "action": "cast",
      "card": "EXACT KNOWN CARD NAME",
      "window": {
        "seat": "YOUR SEAT",
        "seat_turn": 2,
        "phases": ["precombat_main", "postcombat_main"]
      }
    }
  ],
  "watches": [
    {
      "watch_id": "life-pressure",
      "condition": {"kind": "life_at_most", "seat": "YOUR SEAT", "value": 20}
    }
  ]
}
```

Use at most 12 recommendations and eight watches. The seat_turn is that named
seat's absolute turn ordinal, from planning_clock.seat_turns, not a global turn
or round. For its next turn, use the current count plus one. The vocabulary lists
allowed phase names, known card names and visible object UIDs. Card names are
canonical rules identities; do not guess hidden cards. An optional uid narrows a
recommendation to a visible physical card. Optional alternative_group groups
mutually alternative casts. An optional condition uses the same predicate schema
as watches; an unfulfilled conditional recommendation is marked for interpretation,
not automatically classified as a failure.

Watch conditions are limited to:

- {"kind":"card_cast","seat":"SEAT","card":"EXACT KNOWN CARD NAME"}
- {"kind":"object_left","uid":"VISIBLE UID"}
- {"kind":"life_at_most","seat":"SEAT","value":20}

A named counterspell's card_cast watch detects expenditure whether or not it
successfully counters. object_left observes battlefield departure (including a
leave-and-return between decisions); it does not claim every departure was a
destruction. life_at_most fires on crossing from above the threshold, once.
These are observable events, not free-form Python expressions. Each watch fires
once per published version; publishing replaces only your watch set. Wakes during
inference coalesce with pending work, including the publication-gap catch-up.
Avoid watches on routine developments you can cover at mandatory EOT.

Recommendations advise future sequencing; they never execute plays. The decider
receives the latest completed plan on its next unclaimed ordinary decision in any
phase. Use the short- and long-term prose as the primary strategic frame, adapt
actions to current facts, and explain material departures in normal action
rationales. It writes no
plan and performs no adoption or validation turn. Python comparisons use the plan
actually delivered for the decision, never a late publication's timestamp. A
countered cast is a cast; resolution outcomes remain separate history. Missed,
late, superseded and conditional statuses are facts to interpret, not grades.
# Publication size targets

For staged publications, `max_chars` is the hard character limit and
`target_chars` leaves a practical margin below it. The standing reference should
group functional packages rather than repeat the deck inventory. Rejected prose
receives measured field lengths and a shortening target; rewrite those fields
without republishing accepted stages. The host never truncates strategic prose.
