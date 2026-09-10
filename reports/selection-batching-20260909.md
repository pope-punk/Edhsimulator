# Selection batching — 2026-09-09

Implemented a shared bounded selection interface and enabled it by explicit user
request in game 3 of `first-dashboard-run`. No accepted choices were replaced.

Proliferate now offers one multiselect per Evolution Sage resolution, including
eligible opposing permanents and players with energy, excluding phased-out objects.
A chosen permanent receives another of each positive counter type. Empty selection
is legal and remains pilot-authored. Separate trigger resolutions retain priority.

The general interface handles 13 additional paths: simultaneous trigger ordering
per controller, Terastodon, Grasp of Fate, Finale untaps, Brainstorm putbacks,
Nissa land targets, Magus land targets, Sunken Palace exile costs, Top ordering,
Uro escape exile costs, Gifts search, cleanup discards, and lark targets.
Examples: five Uro exile choices become one submission; seven Sunken Palace choices
become one; a controller's N-trigger ordering becomes one ordered submission.
These are reductions in decision requests, not measured wall-clock speedups.

Validation supports exact/minimum/maximum selection sizes, one-per-group rules,
and preserved answer order. It applies to direct answers, replay, and approved
symbolic sequences. Gifts enforces different names and permits failing to find.
A scheduler snooze cannot silently decline these effect/cost selections.

Verification: 102 unit tests pass, including ordered tape replay, rejection of
invalid cardinalities/groups, APNAP trigger ownership and reverse resolution,
Brainstorm order, Finale self-exile, cleanup hand size, Gifts constraints,
proliferate eligibility, and legacy game binding isolation.

Live upgrades were fenced while the prior host was stopped. Proliferate was bound
at accepted count 349; general selections are bound after decision count 370,
leaving the already delivered G03-D0370 question unchanged. Both before/after
replays produced identical event histories and pending requests. Original configs,
accepted-prefix SHA-256 digests and authorization are retained in game_03's
`proliferate_batch_upgrade.json` and `selection_batch_upgrade.json`.

Information-dependent sequences such as explore and existing land-entry/search
interleavings retain separate choices. Counter allocation needs a distribution
schema rather than a plain set and remains separate. This work does not certify
all card semantics or remove existing rules-review tags.

Rules references: [Wizards proliferate explanation](https://magic.wizards.com/en/news/feature/phyrexia-all-will-be-one-mechanics)
and [Wizards rules resources](https://magic.wizards.com/en/rules).

Final symbolic-sequence integration check verifies group constraints against resolved
option indexes, preserving the submitted order. The final host resumed from 370
after stopping the initial upgraded host; no accepted answers were discarded.
