# Mana capabilities and convoke: four complete cards

Cycle base: `107f2e9069d2631646cc0fbb4dbad2e0d9cf10f8`, branch `codex/remaining-card-programs`.
All four programs are source-bound in the reviewed library after draft validation.
Required reviewed-loader validation is pending. No project code ran on the user's computer.

## Printed behavior

| Card | Complete mapping |
| --- | --- |
| Exotic Orchard | Tap to add one color a current opposing land could produce. No applicable color still consumes the tap and adds nothing. |
| Fellwar Stone | Normal {2} artifact cast; same opposing-land color query and tap cost. Its two deck copies share one reviewed program. |
| Horizon of Progress | Tap and pay 1 life for a type a controlled land could produce, including colorless. Separately pay {3} and tap to optionally put an owned hand land onto the battlefield tapped; pay {1}, tap and sacrifice the source to draw one card. |
| Devouring Light | {1}{W}{W} instant; convoke is optional payment after the total cost is determined. Exile a targeted attacking or blocking creature, with normal legality checks on announcement and resolution. |

## Shared rules review

`LandMana` delegates to a pure current-battlefield capability query. It reads
derived land types, copied definitions, intrinsic basic-land abilities and
currently granted activations. It ignores activation costs and timing. Conditions
and nonnegative production quantities are evaluated against current information;
an empty or zero result defines no mana type. It also recognizes mana-producing
targeted and triggered abilities without activating or triggering them.

Recursive land queries converge from empty sets. A cycle without a grounded
type stays empty; a real source propagates its types through the dependency
network. Each land can gain at most six types, so the monotone process terminates.
No result is cached across state changes. Actual production and capability reads
share the current multiplier-only replacement transformation; those replacements
preserve types and cannot turn zero production into a defined type.

The query covers the mana sources in the current reviewed library, including
pain lands, filters, commander identity, zero-count Gates and granted abilities.
Hypothetical state-changing prefixes and unsupported bound-result paths stop
explicitly instead of guessing. They do not occur in the reviewed sources used
by these four printed cards. Adding new mana-source forms requires extending
this interpreter and its tests.

`ConvokeCast` preserves the ordinary cost calculation. A payment supplies exact
creature references and either generic or a current creature color contribution.
A colored contribution may satisfy a matching colored/hybrid requirement or
generic mana. It cannot pay an explicit colorless symbol. The existing mana
matching algorithm validates the combination; each creature contributes once.
Control, type, phasing, orientation, actual mana and the complete total are
validated before mutation. Summoning sickness does not prohibit convoking.

Convoke taps join the existing atomic resource payment and tap-trigger path;
they add no mana and are not tap-for-mana activations. Source references are
validated through the actor visibility gate. Contributions survive payment
serialization, announced zone-cost continuations, receipts, checkpoints and actor
replay. The public visible-card packet identifies convoke casting capability.
Countering the spell or invalidating its target does not refund costs.

Kernel checkpoint schema is **122**; state schema remains **14**.
`rules_mana.py` participates in implementation identity. Prior kernel checkpoints
are rejected, and no started game is migrated. Production admission is unchanged.

## Sources and exact bindings

The pinned [Comprehensive Rules](https://media.wizards.com/2026/downloads/MagicCompRules%2020260819.txt),
106.7 and 702.51a-d, govern capability queries and convoke.
The file retains SHA-256
`4381ad1b39ab2c05f7d03633a20f711ed37277074d3266dcba5f38cbb527423f`.
[Modern Horizons 3 release notes](https://magic.wizards.com/en/news/feature/modern-horizons-3-release-notes)
clarify Horizon's distinction between types and colors and its treatment of
activation costs and legality. Printed faces are bound to the repository catalog.

| Card ID | Source-facts SHA-256 |
| --- | --- |
| exotic-orchard | `cbc562116d86e72249cb5bf17db85d1bed23f9456d12c752b363d947d90c9a0c` |
| fellwar-stone | `33ef14fcff285d036572df648176f0bac18899380fff5883d3a7abad1613f10a` |
| horizon-of-progress | `868537fbdd8088bc679d6dcbb6ed95fd734b2f50458d16019bdb0f42da092a16` |
| devouring-light | `529a8bca36a37da0180a1dc759af60ed850e5243a491ebe3406c2adb83dc872e` |

## Existing-card source correction

The first hosted run exposed an incorrect stored face for **Baldur's Gate**.
The [official Wizards card image](https://media.wizards.com/2022/clb/en_Vp5dLGW0fI.png),
linked from the [set mechanics article](https://magic.wizards.com/en/news/feature/commander-legends-battle-for-baldurs-gate-mechanics),
shows `{T}: Add {C}.` and the variable Gate ability, with no tapped-entry clause.
The reference text, mana annotation, generated catalog and reviewed program now
agree. Its color identity is empty. The corrected source-facts SHA-256 is
`219f1fd41ef5b9f0fa550f82f10d93d2b87625f13eb96dcad7125b5406ddb398`.

This scoped correction retains the reference snapshot identifier and is audited
here and in Git history. Of the prior 278 programs, 277 are unchanged; Baldur's
Gate is the single intentional correction and is not counted as a new card.
The old entry-threshold test now checks unconditional untapped entry. New tests
check actual colorless production and byte-for-byte catalog regeneration from
the corrected source inputs. Existing games retain their bound implementation.

[Initial draft run 34805862822](https://github.com/pope-punk/Edhsimulator/actions/runs/34805862822)
ran 1,851 tests on Ubuntu with one failure and two errors; Windows was cancelled
by matrix fail-fast. Besides the source error, two scenario helpers needed to
restore their unbound priority window after resolving an empty stack.

## Hosted evidence

The **74 new methods** in `tests/test_rules_primitives_mana_convoke.py`
cover all four programs, recursion and pure reads, current/granted mana abilities,
zero outputs, payment choices, full Horizon behavior, convoke resources, target
legality, privacy and replay. Historical schema checks retain their earlier
minimum layout while this suite requires schema 122/14.

[Draft validation 34835807492](https://github.com/pope-punk/Edhsimulator/actions/runs/34835807492) passed **1853 tests
on each of Ubuntu and Windows**, plus source syntax, full installation and
packaged-asset checks, at `b5a59145faa7bee3dba851c53af173ddcbd35004`.
All 74 new methods now use the reviewed loader. Required reviewed-loader
validation is pending.
