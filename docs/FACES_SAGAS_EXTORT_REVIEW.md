# Pass 3: faces, Sagas, extort and Battles

Status: seven complete card programs drafted; hosted conformance and promotion
are pending. This is Pass 3 of the original four-pass plan, not a new baseline.
Reviewed coverage remains 320/334 unique cards and 386/400 deck copies.

## Printed-card review

| Card | Shared implementation and printed clauses |
| --- | --- |
| Glasswing Grace // Age-Graced Chapel | Front creature Aura grants +2/+2, flying and lifelink. Modal back is a tapped land with a white-or-black mana choice. |
| Kazuul's Fury // Kazuul's Cliffs | Front reuses Fling's additional creature sacrifice and captured power for any-target damage. Modal back is a tapped red-producing land. |
| Sorin of House Markov | Lifelink and extort; own postcombat-main intervening life-gain condition; exile/owner-controlled transformed return. Back has extort, entry loyalty 3, Food, life-gained damage, and indefinite creature control/Vampire addition with the conditional lifelink counter. |
| Pontiff of Blight | Own extort and an independent extort instance on each other controlled creature. |
| Invasion of Theros | Siege entry protector and defense 4; Aura/God/Demigod search; intrinsic defeat and optional free transformed casting. Ephara's other-enchantment draw and conditional lifelink/indestructible are retained. |
| The Restoration of Eiganjo | All three chapters, including the separate discard/return trigger, followed by exact transformed return. Architect has vigilance and creates a colorless Spirit when attacking or blocking. |
| Elspeth Conquers Death | Opposing permanent exile at mana value 3+, temporary noncreature spell tax, and creature/planeswalker return followed by the counter choice. |

The five paired definitions bind an explicit modal or transforming layout.
Printed colors are retained in source annotations: Sorin's back is white-black,
Ephara is white-blue, and Architect is white. Invasion's printed defense is also
retained. The generator and generated catalog are changed together. Printed
back-face mana cost/value remain absent/zero; runtime transforming mana value
comes from the front face. The previous 320 reviewed rows and hashes are unchanged.

## Shared rules and review findings

A RulesObject retains its physical definition and incarnation. Face orientation
is distinct from copied characteristics. Hidden-zone moves reset orientation;
stack-to-battlefield resolution preserves the announced face. Cast declarations
bind their face in the quote, payment, command, receipt and checkpoint.
Land plays select the modal face before validating ordinary permission and limits.

Ordinary permanent copies copy the visible face. Token copies of a double-faced
object retain both faces, including applicable copy exceptions and current
orientation; derived paired definitions have replay-verified lineage.
Transforming an existing object does not produce entry counters or a zone event.
Exile/return does; a single-faced copy cannot return transformed.

Granted triggers are independent instances with source-bound grant identities.
Ability removal and timestamps govern the current grants. Once triggered, a
captured ability remains independent of the original grant. Extort uses the
existing optional hybrid payment and actual-life-loss aggregate, without targets.

Saga lore uses the existing counter replacement transaction. The precombat-main
turn action is retained across choices and checkpoints, before beginning-of-phase
triggers are collected. Chapter thresholds use the counter change, and final
sacrifice waits for outstanding chapter abilities. Simultaneous state actions
retain sacrifice causes so other cards can observe them.

Siege protection is distinct from ownership and control. The controller can
attack its Siege; the protector blocks for it. Defense removal collects the
intrinsic defeat trigger. Its exact exile permission casts the physical
transforming back face, including an opponent-owned card controlled by the
trigger's controller. Additional costs and taxes still apply to free casts.
A Battle with zero defense waits for its outstanding triggered abilities.

Elspeth's tax retains its controller and selector after source departure. It
expires at that controller's next ordinary turn boundary, including the skipped
seat of a departed player. The counter kind is chosen after the return instruction.
Sorin's conditional counter checks other current white permanents, excluding both
Sorin and the gained creature. Keyword counters have retained placement timestamps.

## Validation

All execution is confined to GitHub-hosted runners. No local Python, imports,
installation, tests, simulations, games, checkout or clone were run.

The initial 90 methods are in
[test_rules_primitives_faces_sagas_extort.py](../tests/test_rules_primitives_faces_sagas_extort.py).
The ongoing review expands those scenarios before promotion. Syntax, installation,
installed assets, the complete existing primitive suite, and the new scenarios
must pass on Ubuntu and Windows. After promotion, the same card tests must use
the required source-bound reviewed loader and pass again.

Production admission and historical/started-game contracts are unchanged.
No merge, deployment, gameplay or automatic contract migration is part of this pass.

## Rules sources

- [Modern Horizons 3 release notes](https://magic.wizards.com/en/news/feature/modern-horizons-3-release-notes):
  Sorin's life-gain history, owner-controlled return, loyalty, extort payment,
  actual life loss, and indefinite control.
- [March of the Machine release notes](https://magic.wizards.com/en/news/feature/march-of-the-machine-release-notes):
  Siege protection, defense, transformed casting, and Ephara's entry triggers.
- [Kamigawa: Neon Dynasty release notes](https://magic.wizards.com/en/news/feature/kamigawa-neon-dynasty-release-notes-2022-02-09):
  Restoration's discarded card can be chosen by its separate return trigger.
- [Theros Beyond Death release notes](https://magic.wizards.com/en/news/feature/theros-beyond-death-release-notes-2020-01-10):
  Elspeth's tax duration and post-entry counter choice.
- [Zendikar Rising release notes](https://magic.wizards.com/en/news/feature/zendikar-rising-release-notes-2020-09-10):
  Kazuul's paid sacrifice and captured power.
- [Comprehensive Rules](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt):
  CR 310 (Battles), 707.8 (double-faced copies), 712 (face characteristics), and
  714 (Saga chapters and lifecycle).
- [March of the Machine card images](https://magic.wizards.com/en/news/card-image-gallery/march-of-the-machine)
  and [Neon Dynasty card images](https://magic.wizards.com/en/news/card-image-gallery/kamigawa-neon-dynasty-card-image-gallery)
  retain the printed reverse faces alongside the source annotations.
