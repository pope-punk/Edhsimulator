# Rooms, miracle and remaining Sagas: Pass 4

Seven complete printed programs are promoted to `data/rules/primitive_cards.json`:
Aminatou, Veil Piercer; Entity Tracker; Funeral Room // Awakening Hall;
Ghostly Dancers; Victor, Valgavoth's Seneschal; The Cruelty of Gix; and Urza's Saga.

## Status

Source-bound review and hosted draft validation are complete. The reviewed library
contains 334/334 unique cards and 400/400 deck copies; its draft bundle is empty.
Required reviewed-loader validation is pending, so Pass 4 is not yet complete.
No local Python, installations, tests or games have run. No production admission,
existing game contracts, hosts or migrations are changed. This work remains on
`codex/remaining-card-programs`, based on `ad19e060ff529c17b0b260b64be4499003f2b960`.

## Shared implementation

- Room programs retain both printed halves. Object state records the announced
  door, unlocked designations and the entry turn. Characteristics and event
  discovery use the currently applicable half or halves. Unlocking is a paid
  special action at sorcery timing; lock/unlock instructions use the same event
  collection, including door-entry triggers and fully-unlocked observations.
- The first actual draw of each turn may expose a miracle reveal choice. A
  checkpointed cursor finishes that choice before the next draw. The linked
  trigger grants only its exact hand incarnation a cast window, uses the chosen
  spell's reduced alternative cost, and preserves ordinary additional costs.
  Public reveals expire with their linked ability or hand incarnation.
- ResolutionSequence counts executed instances of one source's ability group
  within the turn. Victor's entry and full-unlock subscriptions share this
  group; its discard choices and third-resolution selection happen on resolution.
- Read ahead chooses entry lore and suppresses skipped chapters for the entire
  entry turn. Saga chapter grants use ongoing layer-six abilities. Construct
  tokens retain a 0/0 base and a live layer-seven artifact-count modifier.
- Exact printed mana-cost selection distinguishes {0}, {1}, absent costs,
  colored pips and X. Hand-reveal discard records the public disclosure and
  gives the choice to the resolving controller.

Kernel/state checkpoint schemas become 132/20. Original source-bound reviewed
records are preserved; only the previously unreviewed Room gains explicit
`room` layout metadata in catalog and generator annotations.

## Rules evidence

[Current Comprehensive Rules](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt),
sections 116, 702.94, 702.155, 709.5 and 714 establish special-action timing,
linked miracle revelation, entry-turn Read Ahead restrictions, Room designations
and the Saga lifecycle.

[Duskmourn release notes](https://magic.wizards.com/en/news/feature/duskmourn-house-of-horror-release-notes)
confirm sequential draws, miracle's additional costs and exact-card timing;
Room copying retains both halves and spell copies retain the announced door.

[Dominaria United release notes](https://magic.wizards.com/en/news/feature/dominaria-united-release-notes-2022-08-26)
support the three Cruelty chapters and Read Ahead entry choice.
[Modern Horizons 2 release notes](https://magic.wizards.com/en/news/feature/modern-horizons-2-release-notes-2021-06-04)
support Urza's Saga's persistent grants and exact {0}/{1} search.
The current CR controls the chapter-ability requirement for Saga turn actions
and sacrifice; older notes about Sagas with no chapter abilities are superseded.

## Validation

Initial draft run [34911639077](https://github.com/pope-punk/Edhsimulator/actions/runs/34911639077)
at `593b793100867470a4585c92476189d683e83805` ran 2584 tests on Ubuntu:
2581 passed; two test fixtures used the wrong inspection API, and catalog output
needed the generator's literal Unicode formatting. These are corrected in the
follow-up, which also adds eight edge-case and land/search integration methods. Windows was cancelled by the
workflow's fail-fast setting. The new conformance module now has 56 focused methods. Both hosted draft
validation and the required reviewed-loader run must pass on Ubuntu and Windows
before promotion is recorded. No completion count is inferred from authoring.

Run [34912464358](https://github.com/pope-punk/Edhsimulator/actions/runs/34912464358)
at `6d8756b5b4eaf418ae2221f594bc7b51601cbc4f` ran 2592 Ubuntu tests with two
failures: the known catalog formatting mismatch and the expanded scanning parity
case. The latter exposed a missing event-kind filter in state-trigger collection:
the scanning reference offered unrelated abilities to that collector. The filter
is now explicit, matching the other collectors and preserving indexed behavior.
The canonical Unicode catalog correction is already committed at
`c83caac04b4296617dd09298721b470c8d0fc094`.


Corrected draft [run 34913303661](https://github.com/pope-punk/Edhsimulator/actions/runs/34913303661) at `245c67c9d5e5192a4fa3577a4e9fe570a976f158`
passed **2592 tests on each of Ubuntu and Windows**, plus source syntax,
full distribution installation and packaged assets. All 56 focused methods passed.
The seven promoted rows bind every printed face to the catalog; all 327 prior
reviewed rows remain unchanged. The same 56 methods now strictly require
`load_reviewed()`, with no draft fallback. The existing library-wide trigger
index test also checks both Room doors separately and together.
Required reviewed-loader validation must pass before this pass is marked complete.
