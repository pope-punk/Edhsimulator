# Automatic decider payments

Fresh games bind `automatic_decider_mana:1` alongside `autotap:1`. Existing game
bindings are unchanged. The decider chooses a spell/non-mana ability, its targets,
X, modes and non-mana costs. Python selects the mana payment. Mana abilities and
intrinsic land activation menus are omitted from decider action facts; the board
still shows lands and mana. Planners retain the complete mana vocabulary.

## Two paths

1. Submit the intended cast or non-mana activation with no mana instructions.
   Optional non-mana costs use `payment.taps`/`payment.zone_costs`; the host fills
   its required empty mana fields. Each action recalculates payment at execution.
2. Approve unchanged short-term planner steps by ID, including the planner's
   explicit mana sequence or reservation. Editing a command returns that action
   to automatic payment; deciders cannot author mana activations, allocations,
   reservations or tagged-unit selections through commands, overrides, added
   steps or direct sequences.

For a resolution mana request, `pay_mana` plus the current request ID pays
with automatic mana; `payment:null` declines. Ordinary mana activations and their
color choices execute atomically inside that payment. A failure spends nothing.
The complete concrete payment is recorded for exact replay. An approval still
authorizes a sequence rather than proving that its steps executed.

## Preferences and limits

The existing bounded solver proves an actual legal payment. The new preference
layer considers alternative source orders, preservation of individual sources,
floating-color expenditures and eligible tagged mana. It ranks candidates by:

1. The largest simultaneously mana-affordable subset of the remaining hand.
2. The number of individual remaining cards that are mana-affordable.
3. Remaining untapped sources, their color flexibility, and reduced floating
   surplus/activation count.

A dual land contributes one of its outputs, never all colors simultaneously.
Only the acting seat's hand and public mana sources inform these preferences;
no opponent hand or future library is read. Already-spent, sacrificed and tapped
cost sources are excluded. A legal baseline payment remains a candidate even
when preference exploration cannot improve it.

This is bounded lookahead, not an exhaustive optimal play search. It considers
up to ten lowest fixed-cost hand cards and at most 4,096 remaining mana profiles.
Variable X, hybrid choices and unknown dynamic reductions are omitted from the
hand heuristic. Printed costs with fixed intrinsic reductions estimate future
mana needs; future taxes, targets, timing, alternative costs, draws and spell
effects are not simulated. Actual submitted action costs and spending
restrictions are always checked by the engine. Planner reservations remain hard
constraints. Tagged units are checked against the submitted action before use.

Ordinary-source eligibility remains conservative: creatures, damage/life costs,
paid filters, sacrifices and consequential mana effects are not silently added
by this change. Planners can author these lines explicitly. This is not complete
automation of every mana mechanic, nor proof that every estimated follow-up card
will be legally castable after the first spell resolves.

## Arena research

Wizards' public material documents individual preferences, not a complete
reference implementation. This implementation must not be described as an exact
clone of Arena's private algorithm.

- [Official 2022.21.0 patch notes](https://mtg-jp.com/reading/publicity/0036480/)
  describe preference for painlands' colorless production for generic costs and
  retaining variable-output sources behind fixed-output sources.
- [Dominaria United](https://magic.wizards.com/en/news/mtg-arena/mtg-arena-state-game-dominaria-united)
  documents preferring life expenditure to sacrificing permanents.
- [New Capenna](https://magic.wizards.com/en/news/mtg-arena/mtg-arena-state-game-streets-new-capenna-2022-04-21)
  describes spending Treasure when mana colors confer an additional benefit.
- [The Brothers' War](https://magic.wizards.com/en/news/mtg-arena/mtg-arena-state-game-the-brothers-war)
  describes showing mana choices for effects that care about colors spent.

These are documented Arena behaviors, not claims that all are implemented here.
The present hand-portfolio objective is the operator-requested extension; public
sources above do not establish that Arena uses this exact scoring function.

## Related Game N correction

N's reported Animate Dead targeting error was stale feedback. Its host journal
first recorded that error at accepted action 1236 during the earlier Elspeth
Conquers Death attempt; it remained in the seat input at 1490. Successful accepted
actions now clear prior rejection feedback. New batch rejections include the
actual command and prefix and retain actor-scoped audit evidence. An end-to-end
regression casts Animate Dead on Leonin Relic-Warder with automatic payment,
checks reanimation/attachment and verifies exact payment replay. This diagnosis
does not alter N's retained terminal seal or declare a counterfactual winner.

See [primitive combo proposals](PRIMITIVE_COMBOS.md) for the restored consent and
independent-adjudication path.
