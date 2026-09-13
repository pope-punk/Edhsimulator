# Graveyard casting and exile-until-leaves card review

Branch: `codex/remaining-card-programs`. Source base:
`9d918d1db85ef64337615c98b52d0ff546b02ddd`.

This cycle authors four complete printed faces. Initial programs remain in the
isolated draft bundle until their first successful hosted validation. Promotion
uses exact catalog source-fact hashes and the reviewed loader; it does not grant
production certification. No project code or Python was executed locally.

| Card | Reused vocabulary | Shared extension |
| --- | --- | --- |
| Uro, Titan of Nature's Wrath | Entry facts, conditional sacrifice, gain/draw, optional land movement, attack event | Graveyard-only alternative cost plus five other graveyard exiles |
| Bulk Up | Signed recipient power, temporary P/T changes, targeting | Flashback permission and exact stack-departure replacement |
| Grasp of Fate | ETB, nonland selectors, grouped choices, zone replacements | Per-opponent bound targets and immediate exile-duration returns |
| Prayer of Binding | Flash, optional target, gain life, Aura entry | The same exile-duration return transaction |

The reviewed programs preserve their full printed characteristics and normal
mana costs. Uro's benefit triggers independently on entry and attack. Its land
placement uses ordinary Move and does not consume a land play. Normal and escape
origins remain separate, costs validate before mutation, and only a paid escape
carries the entry fact. Bulk Up's modifier captures the signed current power
once; the Flashback replacement belongs to the exact paid stack object and
does not follow the card into a later normal cast.

ExileUntilSourceLeaves tracks actual exile results and exact source incarnations.
It resumes returns before the next resolving instruction, state-based actions
or priority. Simultaneous source departures return all surviving cards in one
entry transaction. Source phasing, control and copy changes preserve the pending
obligation. A departed source at initial resolution suppresses exile. Prayer's
later life gain still occurs unless its chosen target became illegal. Tokens,
commanders moved to command, hidden cards and later exile incarnations are never
recaptured. Return replacements and Aura attachment choices use the ordinary
resumable transaction and each return is attempted only once.

A TargetSpec with `maximum: null` is supported only for triggered battlefield
targets grouped by controller. Its capacity is the available controller groups,
and each selected target remains bound to that player's clause at resolution.
Finite existing target specifications retain their behavior.

Actor packets expose the Flashback marker and public duration links, with hidden
zones filtered through the existing projection. Checkpoints retain the source,
exact exiled references and pending replacement/attachment choice. Schema 114
rejects older layouts; implementation fingerprints reject intervening runtime
changes. Existing games and checkpoints are not migrated.

The shared casting slice still requires already-produced unrestricted mana.
Restricted mana, mana during announcement and separately ordered cost groups
remain rejected. The Dawn of Hope / Rhystic Study / Smothering Tithe family is
next; it needs a resolution-time payment window, including permitted mana
abilities, before its printed payment clauses can be considered complete.

## Validation

Two modules author **45 conformance methods**: 23 graveyard-casting methods and
22 exile-duration methods. These cover printed programs, atomic failure, source
and target control changes, negative power, cleanup, counters and other stack
departures, multiple opponents, simultaneous returns, phasing, tokens, commander
choices, Aura attachment, replacement redirects, actor privacy, replay and
checkpoint reconstruction.

Successful combined hosted validation and reviewed-loader promotion are pending.
The first run rejected an extra GainLife JSON field and an obsolete exact schema
assertion; those authoring/fixture errors are corrected and retained in the
inventory's validation history. No successful result is inferred from a commit.

## Sources

- [Pinned Comprehensive Rules](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt):
  601.2c/f–i, 608.2b, 610.3a–d, 702.34a and 702.138a–b.
- [Theros Beyond Death notes](https://magic.wizards.com/en/news/feature/theros-beyond-death-release-notes-2020-01-10):
  Uro and escape.
- [Foundations notes](https://media.wizards.com/2024/downloads/FDN_Release_Notes_dPeeQG7XyE/EN_FDN%20Release%20Notes%2008282024.pdf):
  Bulk Up (page 13) and Prayer of Binding (pages 89–90).

The catalog blob remains `32708912c5c94b7222af092e578f9a6353475262`.
Original fixture bindings remain historical evidence; whole-card source binding
is recorded in the reviewed bundle on promotion.
