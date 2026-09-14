# Counter transitions, eternalize and Finale review

This cycle covers Fangs of Kalonia, Hydra Broodmaster, Fanatic of Rhonas and
Finale of Revelation, with every printed clause authored. Base:
`5fd2f0071f9bcb2d52996cd1b1537976d449ab5a`. Kernel schema **125**, state schema **16**.
The branch remains an experimental library; this is not production admission.

## Evidence and source correction

The source catalog and frozen reference incorrectly gave Hydra Broodmaster a
{3}{G}{G}{G} mana cost. The [official Journey into Nyx release notes](https://magic.wizards.com/en/news/feature/release-notes-2014-04-23)
give {4}{G}{G}, a 7/7 body, and X in the trigger equal to the activation's chosen X.
Both source files are corrected together; the source-facts hash binds that cost.

The [Modern Horizons 3 release notes](https://magic.wizards.com/en/news/feature/modern-horizons-3-release-notes)
confirm Fangs' overload behavior and Fanatic's 1/4 printed body, both tap abilities
and eternalize {2}{G}{G}. [Wizards' official Japanese-site English card gallery](https://mtg-jp.com/products/card-gallery/0000284/680728/)
supplies Finale's complete printed instructions. The existing catalog wording
uses a self-reference to the spell with the same meaning.

Rules use the pinned [August 2026 Comprehensive Rules](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt),
SHA-256 `4381ad1b39ab2c05f7d03633a20f711ed37277074d3266dcba5f38cbb527423f`.
Relevant rules include 601.2, 602.5, 605.1, 608.2c, 611.2a, 701.37,
702.96, 702.129a, 707.2 and 707.9.

## Implementation review

- **Fangs:** a normal {1}{G} targeted spell and a real {4}{G}{G} overload
  alternative with an explicit nontargeted body. Its first counter transaction
  binds actual positive recipients after replacements. Only those recipients
  receive the second replacement-aware doubling instruction. Overload includes
  eligible shrouded creatures, excludes phased objects and checks current control.
  Alternative payment preserves the printed mana value and ordinary cost modifiers.
- **Hydra:** {X}{X}{G} pays X twice. Monstrosity checks an exact live permanent
  and records its designation only once, after counter replacements complete.
  X=0 and prevented counters still allow that transition. The designation survives
  copying, phasing and control, is absent from copiable characteristics and resets
  on departure. Its separate trigger retains X after source departure. Token
  power and toughness are frozen base values, so later copies retain their size.
- **Fanatic:** the ordinary green mana ability and restricted four-green ability
  share tap/readiness checks. Ferocious evaluates current derived controlled
  creature power at activation, without deleting an unavailable ability from its
  copiable definition. Eternalize exiles the graveyard source as a sorcery-timed
  cost. Its copy is black, 4/4, Zombie Snake Druid and has no mana cost and has mana value 0;
  those exceptions remain copiable. The token retains all three abilities and
  its own power can enable ferocious once it can pay a tap-symbol cost.
- **Finale:** X below ten draws normally. The large branch first moves the entire
  own graveyard into the library and shuffles, then draws, then authors a
  nontargeted choice of zero to five lands belonging to any controller. The
  hand-size permission lasts indefinitely. Exiling the resolving spell happens
  after either branch; a countered spell never executes that instruction.
  Shuffle identity retirement, queued draw/shuffle triggers and checkpointed
  choices use the existing library, event and continuation machinery.

New instruction variants keep existing card-program encodings stable. Copy lineage
adds an explicit mana-cost exception, and state checkpoints carry the noncopiable
monstrous designation. Old checkpoint versions are rejected; no started game is
migrated. The 290 earlier reviewed programs remain byte-for-byte unchanged.

## Hosted conformance

The focused module currently contains **64 new test methods**. It covers source
bindings, costs and target domains, actual counter recipients, both replacement
stages, multiple queued monstrosity activations, copied and reset designations,
captured X, frozen token values, conditional mana, exile-as-cost, token copying,
Finale thresholds, opponent lands, invalid and replayed choices, shuffle identity,
trigger ordering, cleanup duration and malformed/unbound instruction rejection.

[Initial draft validation](https://github.com/pope-punk/Edhsimulator/actions/runs/34850413847)
passed 2,029 tests on each platform at `9680ca5adb8e0728a5f1ffbbec59e9f40bbaf933`.
[Expanded draft validation](https://github.com/pope-punk/Edhsimulator/actions/runs/34851080921) passed **2,037 tests on each of
Ubuntu and Windows**, plus syntax, installation and packaged assets, at
`7e7106bf0fa5c8c83e21ce1affac48d5f530c196`. All 64 focused methods passed.

The four source-bound programs have now been promoted into the reviewed bundle;
the conformance module requires the reviewed loader. This promotion's required
hosted validation is pending. Coverage is 294 unique cards / 360 deck copies,
with 40 unique cards / 40 copies unstarted and zero drafts.

No local Python, installation, compilation, tests or games have been run.
