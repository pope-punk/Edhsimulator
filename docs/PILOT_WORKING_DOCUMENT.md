# Pilot working document

Fresh primitive campaigns bind `pilot_document:1`. Existing campaigns without
that flag retain their original transport. Do not edit a started game's config
to adopt this feature. Rendering does not grant gameplay or inspection authority.

## Model-facing layout

1. Current decision, then a separate action menu.
2. Complete current plans, holds, rejection feedback and combo offers.
3. Board grouped by controller, zone and **complete card-type combination**.
   Objects inherit those headings. An owner appears only when different.
4. Frozen catalog Oracle text, once per visible printed face, and remaining
   authorized context. Changes to characteristics, granted abilities, counters,
   attachments, restrictions and other current state remain explicit.

Known false/empty object defaults and zero damage are omitted. Zero power,
toughness, life, mana costs and choice bounds are not erased. Custom tokens and
fixtures without catalog Oracle text retain explicitly identified implemented
rules; the renderer never invents printed text. Planner object inspections still
expose operational ability descriptors needed for exceptional mana sequences.

On a continuing conversation, identical sections refer to the previous delivered
input in that **same conversation**. Current plans remain supplied in full. A
new physical conversation starts with a self-contained baseline. A failed or
parked delivery does not advance the comparison baseline. Original evidence and
engine commands remain complete; the presentation is not the replay format.

## Actions and references

Python freezes an action-family menu with the actor's decision claim. It lists
casts, activated non-mana abilities, land plays, Room unlocks and current
choice/combat/payment commands. Alternative casting routes and faces have
separate entries, not one entry for every target combination. Parameterized
families are **not a promise that every combination is legal**. Modal, X,
grouped-target and non-mana-cost choices still require final engine validation.
Definite timing/activation blockers are suppressed where verified; other
conditions are reported explicitly rather than guessed away.

For example:

```text
A7 — Cast Remand
Choose one spell; target candidates: S1
S1 — Ghalta, Primal Hunger
```

```json
{"command":{"action":"A7","target":"S1"},"rationale":"…","scheduler":{"mode":"hold_full_control"}}
```

Python expands the action and resolves `S1` to the stack spell's exact source
reference, **not its stack frame ID**, then uses the ordinary atomic submission
path. Targets, modes, X and costs remain the pilot's choices. Menu rendering does
not execute actions or pay anything. Single-target families quote their candidate
choices and distinguish automatic-payment feasibility from target legality.
Consequential sources outside autotap still require an unchanged planner-authored
payment sequence; this presentation change does not authorize extra decider mana
abilities, pay life, sacrifice permanents or bypass a rules blocker.

`C`/`S` labels identify exact object incarnations. `R` labels replace operational
IDs needed for batches, abilities, requests, holds and combo proposals. Labels
are scoped to the physical conversation and never reassigned within it. `A`
labels expire on the next delivered input. A stale object reference still fails
ordinary engine validation. Raw structured command syntax remains compatible.
Future planner references use `{owned_card:"C1",zone:"battlefield"}`; host
translation preserves the existing explicitly guarded symbolic-reference rules.

Only planners may inspect. Diplomats receive only the existing authorized public
board and permitted own-seat plan/brief information; catalog lookup does not
supply private cards. No opponent hands or ordered future library are consulted
while building a menu.

## Historical comparison

`tools/refresh_pilot_preview.py` opens a saved SQLite log **read-only**, verifies
its original command records against an in-memory reconstruction of the requested
prefix, and renders the saved actor packet against that historical position. It
never opens a campaign, writes a game database, contacts a host, or dispatches a
pilot. `/audit/sparse/` displays the result alongside the unchanged original JSON.

This comparison measures UTF-8 bytes, not tokenizer counts or a proven game-speed
improvement. First-packet and repeated-delivery costs differ.
