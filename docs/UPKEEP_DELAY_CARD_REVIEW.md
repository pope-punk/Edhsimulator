# Upkeep and delayed-step card review

Cycle base: `e4aee73dd1af7739487ff3ac4919bcc5af394a75` on `codex/remaining-card-programs`.
Four complete printed programs are source-bound and promoted after successful
hosted draft and reviewed-loader validation. No project code or Python ran locally.

## Printed-face mapping

| Card | Printed facts | Complete behavior |
| --- | --- | --- |
| Dance of the Dead | {1}{B}; black enchantment Aura | Enchants a creature card in any graveyard; on entry while present, changes its enchant restriction, returns that card tapped under its controller, attaches to the exact return, and creates a delayed departure sacrifice by that creature's controller. The creature gets +1/+1 and skips ordinary untap. Its own controller's upkeep offers that player {1}{B} to untap it. |
| Mystic Remora | {U}; blue enchantment | Own-upkeep battlefield condition, age counter placement, then optional complete cumulative {1} payment for each actual age counter, otherwise sacrifice. Each opponent noncreature spell offers its caster {4}; after nonpayment the Remora controller may draw one. |
| Touch the Spirit Realm | {2}{W}; white enchantment | Entry optionally exiles one artifact or creature until the source leaves. Its hand Channel activation pays {1}{W} and discards itself, exiles the target, then returns the actual exiled incarnation under its owner at the next end step. |
| Arcane Denial | {1}{U}; blue instant | Targets and counters any spell. Captures that spell's controller before countering and creates two independent delayed abilities for the next turn's upkeep: that player may draw zero, one or two; the Denial controller draws one. |

All source facts and ordinary costs are retained. Arcane Denial replaces Talon
Gates in this batch because it shares delayed-step work. Talon Gates needs a
larger phasing lifecycle, particularly indirect attachments and departed-player
timing under CR 702.26n; it remains unstarted with explicit requirements.

## Shared primitives and rules timing

`PayRepeatedMana` captures a validated repetition count after replacement-aware
age placement and freezes the complete mana cost in the existing resolution
window. Later mana abilities cannot change that quoted payment. Zero payment is
still an authored optional choice. Existing payer authentication, mana abilities,
atomic payment, suspension and replay are reused. A `SpellEventPattern` type
exclusion observes the actual cast spell, including artifact creatures.

`SkipUntap` applies the ordinary untap restriction after characteristic layers.
It is distinct from an untap effect, which remains legal. The kernel passes exact
blocked references to the state turn-start transaction. Attached-upkeep discovery
binds the creature and active controller at occurrence; an Aura controlled by
another player does not charge that Aura controller. Existing exact attachment
and departure-sacrifice handling is reused for Dance of the Dead.

`DelayedNextStep` preserves original lexical bindings and captured values,
creates one future upkeep/end-step occurrence, and can exclude the current turn.
It is removed when it triggers, so countering that trigger cannot recreate it.
A return registered after an end step has begun waits for a later end step.
Each Arcane Denial draw is a separate delayed ability controlled by the spell's
controller; the affected player chooses the optional count before any draws.
The normal individual-draw machinery still supplies draw events and failures.
Uncaptured parent targets and X values are rejected in delayed bodies.

Hand activations reveal their source for the live announced ability, including
payment and resolution. Projection exposes only that original source and any
still-current hand incarnation. A new incarnation, an unrelated hand card or
an expired ability does not inherit reveal permission. Channel's discarded
source and public stack ability retain the announced identity. Delayed abilities
inherit public source history without prolonging the hand reveal.

## Bound sources

The catalog source facts are unchanged and bound by the exact hashes below.
The pinned [Comprehensive Rules](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt)
remain at SHA-256
`4381ad1b39ab2c05f7d03633a20f711ed37277074d3266dcba5f38cbb527423f`.
Review uses 303.4 (Auras), 502.3 (untap), 602.2a/701.20a (hand activation reveal),
603.7b/603.7d (delayed occurrence and controller), 608.2b (illegal targets),
610.3 (source-duration exile), 613.11 (rule-changing effects), and
702.24a/702.24b (cumulative upkeep).
[Dominaria Remastered release notes](https://magic.wizards.com/en/news/feature/dominaria-remastered-release-notes)
support Remora's full cumulative payment, and
[Neon Dynasty release notes](https://magic.wizards.com/en/news/feature/kamigawa-neon-dynasty-release-notes-2022-02-09)
support Touch's printed clauses and departure/return behavior.

| Card ID | Exact source-facts SHA-256 |
| --- | --- |
| dance-of-the-dead | `8a10f4f1e9403538bb8ed98fcab0c60d95f64a1e391e4596fe8b019a9cd90742` |
| mystic-remora | `049fc0391f3d8fd57dffc68e9db1153e5677bb547d2cb01e1e892273f4545c23` |
| touch-the-spirit-realm | `83aaac5ab0b65890aad8edb37ef6d71b9d246c222daf64c17c8cd03a3b39c168` |
| arcane-denial | `50edb16e0afcd12531f002d411cddb9f8dbfb9d2ffacb33a16d5f4422b2838c3` |

## Conformance and compatibility

The 47 new methods in `tests/test_rules_primitives_upkeep_delays.py` exercise
printed facts, casting, tapped reanimation, exact attachment, control changes,
ordinary versus effect untap, cumulative costs/replacements and frozen payment,
spell type exclusions, Channel payment/response windows, optional and delayed
returns, exact hidden references, separate delayed draws, optional draw counts,
compiler rejection, actor replay and checkpoint restore.

Kernel checkpoint schema is **118**; state schema remains **13**. Older kernel
layouts are rejected. The historical schema-117 case now accepts its layout or
newer while still rejecting schema 116. No existing game is migrated.
Draft authoring, source-bound review, hosted validation and production admission
remain separate. Production admission remains closed.

[Draft validation 34787026975](https://github.com/pope-punk/Edhsimulator/actions/runs/34787026975)
passed **1,546 tests on each of Ubuntu and Windows**, plus syntax, installation
and packaged assets, at `d032e3c60caf22b585e641c050bc78372c15c611`. All 47 new methods passed.
The four programs now use catalog identities and exact source-facts hashes;
all 258 previously reviewed rows are unchanged. [Reviewed-loader validation 34787728272](https://github.com/pope-punk/Edhsimulator/actions/runs/34787728272)
passed **1,546 tests on each of Ubuntu and Windows**, plus syntax, installation
and packaged assets, at `0a9259b8142247880f7493d7ee02d8e415d996b2`.
The following result-recording commit changes only documentation and inventory;
runtime, programs and tests are unchanged after this validation.
The suite exercises all four through the reviewed loader.

The first reviewed-loader run [34787419424](https://github.com/pope-punk/Edhsimulator/actions/runs/34787419424)
executed 1,546 Ubuntu tests and found four errors in one source-metadata test;
Windows was cancelled by matrix fail-fast. The fixture used the wrong loader
record level for the source hash. It now reads the nested review metadata while
retaining the exact hash and encoded-program assertions. Card behavior and
runtime are unchanged; the corrected reviewed-loader success is recorded above.
