# Pass 1: payments, combat and continuous effects

Status: seven complete printed programs authored in the separate draft bundle;
source-bound promotion and required hosted validation are pending.

Cards: Chthonian Nightmare, Maze's End, Rhythm of the Wild, Parasitic Impetus,
Propaganda, Defiler of Vigor, and Darksteel Mutation.

This is pass 1 of the user's four-pass completion target, beginning with
306 reviewed unique cards and 28 remaining. It includes 91 new conformance
methods. Kernel/state schemas are 129/17. No local project code was executed.

## Shared implementation

- Player counter payments and authored ordered public cost groups preserve
  target-before-cost ordering, X zero, replacement choices and checkpoints.
  Energy gain uses the existing player counter placement/replacement primitive.
- Distinct current names compose an immediate controller-win effect after Gate
  search/shuffle, including a failed search and duplicate-name Gates.
- Current creature-spell counter immunity is a continuous player rule; it stops
  when its source stops supplying the permission. Riot is a distinct ability
  instance in entry lookahead, with separate counter/indefinite-haste choices.
- Goad is a designation, retained independently of creature ability removal.
  Attack declarations maximize available requirements without requiring paid
  destinations. Propaganda stacks per attacker and supports bounded authored
  mana abilities during declaration. Invalid plans adopt no partial changes.
- Optional additional life costs bind to distinct current Defiler sources.
  They reduce only green mana, including an explicitly chosen green hybrid half;
  life can still be paid when it does not reduce mana. Costs stay locked.
- Type replacement, ability removal and P/T layers preserve colors, supertypes,
  artifact subtypes, counters and later grants. Trigger discovery retains
  pre-departure ability presence. Effects already begun in earlier layers keep
  their recipient sets, while later-layer-only effects can stop.

Review corrections include basic-land mana suppression, historical tap-trigger
ability presence, and riot haste in entry lookahead. The first hosted attempt
found a scanning-reference signature mismatch and an unanswered trigger-order
fixture; both are repaired for the corrected draft. Further source review
corrected Impetus's life-loss recipient: read the original creature's controller
on resolution, using last known information after departure. Control change,
departure/checkpoint, blink identity and Aura reassignment are covered; the
earlier event-time controller fixture was corrected. See CR 608.2h and 608.2k.
The expanded run also correctly rejected a synthetic Forest grant without a
Land-typed selector. Its fixture now separates the type and subtype grants;
the compiler restriction is unchanged.

The remaining gate is review plus hosted draft and reviewed-loader validation.
These programs do not change production admission or any existing game.

## Rules evidence

- [Modern Horizons 3 notes](https://magic.wizards.com/en/news/feature/modern-horizons-3-release-notes):
  Nightmare's energy and required graveyard target.
- [Dominaria United notes](https://magic.wizards.com/en/news/feature/dominaria-united-release-notes-2022-08-26):
  optional Defiler payments and green-permanent cast triggers.
- [Ravnica Remastered notes](https://magic.wizards.com/en/news/feature/ravnica-remastered-release-notes):
  Maze's End and every riot instance/entry choice.
- [Commander 2020 notes](https://magic.wizards.com/en/news/feature/ikoria-lair-behemoths-and-commander-2020-edition-release-notes-2020-04-10):
  attached-creature attack and sequential Impetus life changes.
- [Commander Masters notes](https://magic.wizards.com/en/news/feature/commander-masters-release-notes):
  Mutation's type, ability, color, supertype and P/T interactions.
- [Comprehensive Rules](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt),
  effective August 7, 2026: 104.2b, 118.8, 205.3g, 508.1, 601.2, 613,
  701.15 and 702.136.

Source facts are retained on every draft row and will be bound at promotion.
