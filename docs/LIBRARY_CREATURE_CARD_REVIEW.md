# Library and creature-state card review

Repository: pope-punk/Edhsimulator. Branch: codex/remaining-card-programs.
Review date: 2026-09-14. Starting head: `2b4264189953c1fb4453c2318e12d0e3dbecc29a`.

## Scope and source bindings

Complete single-face programs for Kodama of the West Tree, Rampant Frogantua,
Hakbal of the Surging Soul and Chaos Warp. Printed mana costs, type lines,
colors, base characteristics and every rules clause are retained. Source facts
are hashed by the reviewed loader. None of these four requires a catalog edit.

- Kodama: {2}{G}, legendary 3/3 Spirit with reach. Modified controlled creatures
  receive trample. Each qualifying combat-damage event independently searches
  for a basic land, puts it onto the battlefield tapped and shuffles.
- Frogantua: {2}{G}, 3/3 Frog with trample. A live layer-seven modifier counts
  players who have lost, including earlier departures. Capture actual combat
  damage to a player; optionally mill the full amount and choose any subset of
  land cards actually moved to the graveyard by that mill for tapped entry.
- Hakbal: {2}{G}{U}, legendary 3/3 Merfolk Scout. Its own beginning-of-combat
  trigger selects current controlled Merfolk creatures at resolution. Each
  exploration completes before the next creature is chosen. Its attack trigger
  offers a land from hand; declining or having no land draws a card.
- Chaos Warp: {2}{R} instant targeting any permanent. Capture its owner before
  moving it; shuffle that owner's library even when a replacement changes the
  target's destination. Reveal the current top card and put a permanent card
  onto the battlefield under its owner's control. Nonpermanents remain on top.

Primary rules evidence:
[modified creatures](https://magic.wizards.com/en/news/feature/kamigawa-neon-dynasty-release-notes-2022-02-09),
[Frogantua](https://magic.wizards.com/en/news/feature/modern-horizons-3-release-notes),
[Hakbal](https://magic.wizards.com/en/news/feature/the-lost-caverns-of-ixalan-release-notes),
[Chaos Warp](https://magic.wizards.com/en/news/feature/double-masters-2022-release-notes-2022-06-24).
The [pinned Comprehensive Rules](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt)
include CR 701.44a-d for exploration, particularly APNAP selection of one
explorer at a time and last known information after departure; CR 111.6/111.8
distinguish cards from departed tokens; CR 701.20/701.24 govern reveal and shuffle.
The pinned text SHA-256 is
`4381ad1b39ab2c05f7d03633a20f711ed37277074d3266dcba5f38cbb527423f`.
Frogantua's official release note forbids choosing the optional mill when fewer
cards remain than the captured damage amount.

## Shared implementation and review findings

`ModifiedSelector` reads a derived, noncopiable predicate. Any positive counter,
attached Equipment controlled by anyone, or an attached Aura controlled by the
creature's controller qualifies; noncreatures and phased objects do not.
Equipment and Aura qualification also requires the corresponding current card type.
Type-layer changes refresh the predicate during ordinary and hypothetical
dependency evaluation. `LostPlayerPT` requires explicit player history, remains
a static modifier, and never becomes a counter or a copied printed value.

`CombatDamageToPlayer` observes positive combat damage and retains pre-damage
source qualification plus actual damage amount. Existing unqualified damage
triggers retain their behavior. `MayMill` binds only exact graveyard successors;
`SelectBound` intersects that captured set with current eligible objects and
supports an unbounded maximum without a fabricated deck-size limit.

`Explore` freezes the current instruction at each choice boundary, selects the
next explorer before revealing, uses the shared counter and zone replacement
engines, and retains its cursor across checkpoints. It adds a counter even with
an empty library, while a departed explorer uses its last known controller.
Reveals disclose only the actual top card to all players. No priority window
opens between explorations.

`WithOwners`, `ShuffleLibrary`, and `RevealTopPermanent` compose Warp.
Shuffle retires inspected identities. A pending entry or attachment choice
retains the already revealed card without a second shuffle/reveal. Tokens
awaiting state-based removal are not library cards. An Aura unable to attach
stays in the library. Illegal targets prevent the entire spell's resolution.

Kernel checkpoint schema: **126**. State schema: **16**. Changed modules remain
bound into implementation identity. Existing games are not migrated.

## Hosted validation

Draft validation passed **2,095 tests on each of Ubuntu and Windows**, plus
syntax, complete installation and packaged assets, at
`c723b4518af3555124ea1720778e5292d53fb17c` ([run 34860964382](https://github.com/pope-punk/Edhsimulator/actions/runs/34860964382)).
Required reviewed-loader validation passed **2,095 tests on each platform**, plus
syntax, installation and packaged assets, at
`28e3a603461793aea7acff0b9776a79488ba7352` ([run 34861920441](https://github.com/pope-punk/Edhsimulator/actions/runs/34861920441)).
The final result-recording commit changes only this review, the work order and
inventory; tested code, programs and source references are unchanged.
The new test file contains **58 methods**, bringing the suite to
**2,095 tests per platform**. Checks cover printed costs, static filters,
event qualification, source departure, exact mill arrivals, replacement behavior,
exploration order and empty libraries, owner-bound Warp, commander replacement,
Aura entry, actor privacy, strict compilation, and checkpoint/replay.

All execution is on GitHub-hosted Ubuntu and Windows runners. No local Python,
imports, compilation, installation, tests, simulation or gameplay occurred.
This review is card-program coverage, not a production or gameplay certificate.

Initial hosted attempts exposed two missing kernel imports, then an incorrect
test assumption that a ceased token remains archived. Both were corrected.
The final draft also includes the attachment-type-loss regression. No failing
check was disabled and no expected card behavior was weakened.

## Coverage after this cycle

**298 reviewed unique cards / 364 deck copies**, with **36 remaining unique cards
/ 36 copies**, all unstarted and no drafts. **71 of the original 107** outstanding
cards are now promoted. Coverage by deck is Omo 92/100, Reaminatour 87/100,
Elenda 93/100 and Minsc & Boo 92/100. All prior 294 reviewed rows are unchanged.

## Next concrete work order

Prioritize Replication Technique, Sunken Palace, Changing Loyalty and Rishkar's
Expertise. Preserve the existing stack-copy and spent-mana requirements in the
inventory. Changing Loyalty adds replicate payments and permanent spell copies
that become Aura tokens without a token-creation event; each copy chooses its
targets independently, and the replicate trigger survives loss of the original.
Its death return can reuse attached-object successor bindings. See the official
[Secrets of Strixhaven notes](https://magic.wizards.com/en/news/feature/secrets-of-strixhaven-release-notes).
Rishkar's Expertise can reuse greatest-power draw, but needs an actual optional
cast during resolution with ordinary target/cost legality and a no-mana-cost
alternative. These remain unstarted candidates, not completed programs.
