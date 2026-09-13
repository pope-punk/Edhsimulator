# Crop Rotation and Fling — casting sacrifice costs

This cycle begins at `374d00fc3b76d1820cb4cbafa1e24335f5a29d4c` on
`codex/remaining-card-programs`. Both complete printed programs are initially
isolated drafts. They are not imported by the normal reviewed loader.

## Shared transaction

The existing activation payment transaction now also supports a spell's single
selected sacrifice group together with unrestricted mana. The complete quote,
targets, available resources and exact sacrifice selections are validated before
the first mutation. A valid announcement puts the spell and its frame on the
stack. It is public while destination-replacement choices are pending, but is
not yet a completed cast; no priority or spell-cast trigger is issued.

Replacement choices retain their exact request and revision. After those choices,
the existing movement/payment operation commits the sacrifice and resource payment
once. Its receipt, commander-cast accounting and cast event follow that payment.
The ordinary trigger-placement boundary then places death and cast triggers above
the completed spell. The prepared cost stays locked if its reducer was sacrificed.
The shared spell-frame constructor preserves ordinary, modal, X and alternative
casting behavior on their supported paths.

`PaidCostStat(cost_id, statistic)` reads a named spell sacrifice group's captured
derived power, toughness or mana value. The group is captured immediately before
payment, including continuous effects and counters; quantities sum the group and
clamp negative results to zero. The compiler only binds these values within that
spell's effects and selected modes. Trigger bodies, unrelated actions, declaration
targets and cost-reduction expressions cannot invent a paid result.

The value survives replacement redirects, token disappearance, later movement or
reentry, checkpoint restoration and actor replay. Actor packets expose only these
public battlefield statistics, while retaining existing private hand/payment
filtering. Fling itself remains the damage source.

## Printed programs

| Card clause | Program |
| --- | --- |
| Crop Rotation: {G}, instant | Green one-mana instant casting specification |
| Sacrifice a land as an additional cost | Exactly one controlled battlefield Land selected by ZoneCost |
| Search for a land, put it onto the battlefield, then shuffle | Existing SearchLibrary with unrestricted Land quality and ordinary entry replacements |
| Fling: {1}{R}, instant | Red two-mana instant casting specification |
| Sacrifice a creature as an additional cost | Exactly one controlled battlefield Creature selected by ZoneCost |
| Damage equal to the sacrificed creature's power, to any target | Damage from the spell using PaidCostStat; player, Creature, Planeswalker or Battle target domain |

A quality-filtered hidden-library search can fail to find and still shuffles.
Sacrifices use control, not ownership, do not target, and can consume a tapped
permanent or a token. Countering the paid spell does not refund its costs.
Fling can target its chosen sacrifice; that target is gone at resolution.

## Conformance and review status

Twenty-four methods in
[test_rules_primitives_casting_sacrifices.py](../tests/test_rules_primitives_casting_sacrifices.py)
cover both printed programs, invalid payments without mutation, target legality,
all damage-recipient types, derived/negative/token power, source damage keywords,
controller versus owner, payment replacement and actor privacy, replay and
checkpoint restoration, countered spells, cost reducers, trigger ordering,
nonactive casting, command-zone tax, modal/X declarations and compiler boundaries.

GitHub-hosted validation is pending. Review/source binding and promotion remain
separate from the draft's initial conformance result.

## Compatibility and boundaries

Checkpoint schema advances from 112 to 113; implementation fingerprints bind all
changed modules. No existing checkpoint, running game or paused game is migrated.
No project execution, import, installation, compilation or testing occurs on the
user's computer. Validation runs only on GitHub-hosted runners.

The new casting path supports one selected sacrifice group plus mana. Casting
discard/exile/return costs, combinations with life or tapping costs, multiple
ordered groups and additional-sacrifice/alternative-cost composition remain
explicitly rejected. Existing activation zone costs retain their supported
behavior. Restricted mana and activating mana abilities during an announcement
remain separate unsupported mechanics; mana may be produced before announcing.
Production admission remains closed.

## Sources

The catalog supplies the exact printed facts.
[Outlaws of Thunder Junction release notes](https://magic.wizards.com/en/news/feature/outlaws-of-thunder-junction-release-notes)
confirm Fling's last battlefield power, exactly one sacrifice and response timing.
[Dominaria Remastered release notes](https://magic.wizards.com/en/news/feature/dominaria-remastered-release-notes)
confirm Crop Rotation's required single land sacrifice.
The unchanged [Comprehensive Rules baseline](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt)
supplies the announced stack object (601.2a), locked costs (601.2f), full payment
and completed casting (601.2h–i), and modified payment actions (118.11).
