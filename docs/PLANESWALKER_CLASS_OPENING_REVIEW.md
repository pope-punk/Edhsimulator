# Pass 2 review: planeswalkers, Class and opening choices

Status: all seven complete printed programs are authored as isolated drafts.
Hosted draft conformance and final source review are pending. No cards have been
promoted in this pass. The original four-pass, 28-card baseline is unchanged.

The runtime adds signed loyalty costs, Class designations, ward, planeswalker
combat destinations, explicit post-mulligan opening actions, reflexive sacrifice
triggers, directional control rotation and entry subtype effects. Kernel/state
checkpoint schemas are 130/18. The new suite has 81 conformance methods.
All project execution remains on GitHub-hosted runners.

## Shared scope

The five planeswalkers require loyalty entry, activation costs, once-per-turn
tracking, loyalty damage, zero-loyalty state actions and attacking/defending
planeswalkers together. Reuse existing counter storage, damage source history,
target groups, replacement choices, exact object identity and replay. Keep
ordinary mana-producing loyalty abilities on the stack.

Class levels need their own persistent designation, not level counters or copy
values. Reuse normal activation and layer machinery. Opening-hand actions need
an explicit optional choice after mulligans and before turn one.

## Complete card requirements and reviewed edge cases

**Aminatou, the Fateshifter.** Reuse draw and authored hand-to-top placement as
one resolution. Her blink can select another owned permanent even if an opponent
controls it, and returns it under her controller. The direction choice rotates
nonland control simultaneously, excluding only this Aminatou. Preserve
indefinite control history and player-departure handling. Tokens do not return
after exile.
[Commander 2018 notes](https://magic.wizards.com/en/news/feature/commander-2018-edition-release-notes-2018-07-27).

**Domri, Anarch of Bolas.** Reuse the controlled +1/+0 layer and two-group fight
targeting. His +1 uses the stack despite producing mana. Its counter-immunity
rule applies to creature spells cast during the turn, independently of which
mana paid for them. A counterspell can still target such a spell and perform
its other effects. If Domri leaves after paying -2, his anthem stops before the
fight resolves.
[War of the Spark notes](https://magic.wizards.com/en/news/feature/war-spark-release-notes-2019-04-19).

**Minsc & Boo, Timeless Heroes.** Entry and own upkeep each offer a legendary
Boo token. The +1 accepts zero or one creature with either trample or haste.
The -2 sacrifices during resolution, then creates a separate reflexive trigger;
choose its damage target after the sacrifice and retain the sacrificed power
and Hamster subtype. An absent or subsequently illegal damage target prevents
the Hamster draw as well. Preserve the printed commander permission.
[Baldur's Gate notes](https://magic.wizards.com/en/news/feature/commander-legends-battle-baldurs-gate-release-notes-2022-06-01).

**Nissa, Steward of Elements.** X determines starting loyalty. At X zero she
leaves before activation is possible. Her zero ability privately inspects the
top card and permits any land or a creature within the loyalty bound. Declining
leaves it on top. Use current loyalty when resolving, or last known loyalty
after departure; lethal damage may make that remembered value zero. Her -6
targets up to two controlled lands, untaps them and adds temporary 5/5
Elemental, flying and haste changes while retaining their land types.
[Amonkhet notes](https://magic.wizards.com/en/news/feature/amonkhet-release-notes-2017-04-14).

**Sorin, Vengeful Bloodlord.** The active-turn lifelink grant covers controlled
creatures and planeswalkers. His +2 targets a player or planeswalker; last known
source lifelink still matters if he has left. His -X requires an exact mana-value
graveyard creature and returns it with an additive Vampire type. Graveyard X
mana costs use zero. Preserve the entrant type change in entry lookahead.
[War of the Spark notes](https://magic.wizards.com/en/news/feature/war-spark-release-notes-2019-04-19).

**Innkeeper's Talent.** The own beginning-combat trigger targets a controlled
creature. Level activations use the stack, require the preceding level and retain
earlier abilities. At level 2, every controlled permanent with any counters gets
ward; an already-created ward trigger survives losing the grant. At level 3,
counter replacement follows the player putting counters, not merely the
recipient's controller. Entry counters default to the entrant's controller when
no putting player is specified. Audit positive loyalty-cost placement against
this replacement as well as effect and entry placement.
[Bloomburrow notes](https://magic.wizards.com/en/news/feature/bloomburrow-release-notes).

**Leyline of Hope.** Opening-hand placement is optional after all mulligans,
with players acting in starting-player order before the first turn. Additional
life applies once per life-gain event and stacks across copies. Distinct
lifelink sources generate distinct events; one source damaging several recipients
simultaneously yields one life-gain event. Reuse the starting-life-relative anthem,
including state actions when falling below its threshold.
[Duskmourn notes](https://magic.wizards.com/en/news/feature/duskmourn-house-of-horror-release-notes).

## Implementation and validation work

Extend the primitive compiler, runtime, actor commands and checkpoint identity
coherently, then author all seven complete programs in the draft bundle. Reuse
the recent current/last-known object information and counter machinery. Do not
add name-based interpreter dispatch or count isolated loyalty effects as complete
planeswalker support.

Include checkpoints during choices, stale/forged input rejection, control changes,
ability removal, source departure, copies, counter replacements, response timing
and interactions with pass 1 goad/Propaganda/Rhythm/Mutation. Apply the ordinary
draft and required reviewed-loader gates. No local project execution is authorized.

## Existing primitive audit

- `RulesKernel._state_based_actions` already handles zero loyalty. Retain it.
- `RulesState.damage_batch` already removes loyalty/defense counters by recipient
  type. Wire planeswalker combat through the existing damage pipeline.
- `SourceCounter` already uses exact current/last-known object information for
  counters, including a departed Nissa's loyalty.
- `CounterReplacement` already distinguishes the putting player with
  `actor_relation` and supports permanent/player recipients. Add Class gating.
- `GrantPermissions` and `player_effects` already support turn-duration storage;
  extend rule interpretation for Domri.
- `OngoingEffect` and `AddSubtypes` already express indefinite additive types;
  Sorin's return must also expose the Vampire change during entry lookahead.

This is a source inspection, not runtime validation of the future programs.
