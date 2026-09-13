# Card library consistency review — 2026-09-13

Reviewed the printed-text/program compositions of all 227 programs in the
reviewed bundle and the seven separate land drafts at commit
`7351dd303d1612696a65ea5200bf4f10d7d74f09`. This pass looks for missed existing primitives,
inconsistent composition, and clear wording errors. It is not an exhaustive
rules proof or a production certificate.

## Corrections

| Cards | Finding and correction |
| --- | --- |
| Avenger of Zendikar | Landfall said Plant but omitted Creature. Add the existing type filter so noncreature Kindred Plants receive no counters. |
| Lyra Dawnbringer | The Angel selector unnecessarily required Creature. Other controlled Kindred Angels also receive lifelink; existing layers give noncreatures no power or toughness. |
| Angel of Invention | Fabricate named its tokens Servo. The default token name is Servo Token under CR 111.4. |
| Doomwake Giant, Grim Guardian, Underworld Coinsmith | A blanket Enchantment filter could suppress the source's own entry after a continuous type change. Compose disjoint self-entry and other-controlled-enchantment patterns, preserving exactly one ordinary self-entry trigger. |

All six corrected cards use existing primitives. The constellation composition
follows the existing approach for multiple event clauses, with source exclusion
making its event branches mutually exclusive.

## Shared mana vocabulary

Twenty-six reviewed cards and three draft reveal lands now use
`ProduceMana(1, colors)` for a choice of a single color, matching the newer card
programs. The complete list is in the [audit record](../reports/card-library-audit.json).

`ChooseMana` remains appropriate for Flooded Grove and Sage of the Maze because
their output can contain different colors together. Fixed bundles still use
`AddMana`, and commander-dependent choices still use `ChooseCommanderMana`.
Painland damage stays a damage effect after mana production; Mana Confluence and
Silent Clearing retain life payment as an activation cost.

The mana options now have color-symbol keys and quantity-bearing labels through
the existing ProduceMana interpreter. Printed color order is preserved. The draft
fixture now chooses by the returned color key instead of interpreting an old
numeric key.

## Patterns retained

Priest of Titania correctly counts Elf permanents without requiring Creature,
including opposing Kindreds. Subtype-only selectors should not be normalized by
blindly adding type restrictions.

Swan Song and Beast Within correctly capture the target's controller independently
of successful countering/destruction. Terastodon and Curse of the Swine instead
condition token production on the actual zone-change result. These are different
printed requirements and should retain their different shared operations.

No card-name dispatch or new runtime primitive is needed for this batch.

## Validation and compatibility

Eight new regression methods in
[test_rules_primitives_library_audit.py](../tests/test_rules_primitives_library_audit.py)
exercise the six corrections, all printed choices on the 26 normalized reviewed
cards, the two mixed-mana cards, damage versus life costs, Mana Reflection, and
pending-choice restoration. The existing draft fixtures cover the three normalized
reveal lands.

GitHub-hosted validation is pending. No local Python, package installation, tests,
or gameplay was executed. Runtime modules and checkpoint schema 109 are unchanged.
Program fingerprints change, so this is not a conversion or authorization to
resume an existing game under different definitions.

Reviewed-program coverage remains 227. Seven drafts remain isolated and
100 cards remain unstarted; the review does not promote drafts or regenerate
coverage/admission certificates. Continue from the
[remaining-card work order](REMAINING_CARD_DRAFTS.md).

## Rules basis

The catalog's retained Oracle text is the card wording authority for this pass.
The already-bound [Comprehensive Rules, effective August 7, 2026](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt)
support subtype descriptions (109.2), default token names (111.4), noncreature P/T
(208.3), and entry-trigger checks (603.6a). Wizards' [Lorwyn Eclipsed mechanics article](https://magic.wizards.com/en/news/feature/lorwyn-eclipsed-mechanics)
also explains how Kindred permanents differ from effects specifying a creature.
The rules baseline and catalog fingerprints are not changed.
