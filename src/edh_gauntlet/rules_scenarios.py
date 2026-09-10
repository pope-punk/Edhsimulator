"""Authored conformance programs, NOT production card support declarations.

These model only the named interactions. Uro escape costs, combat and the general
casting procedure remain only partially implemented in this fixture bundle. Never load this bundle into a gauntlet host.
"""
from .rules_program import (
    CardProgram, AbilityProgram, EventPattern, Selector, TargetSpec, Move,
    Sacrifice, Counter, Draw, GainLife, May, UnlessEntered, Select, Proliferate,
    WithMoved, WithAttached, SetAttachmentRule, Attach, DelayedTrigger,
    ContinuousProgram, CountCondition, ChangeTypes, SetPT, ModifyPT, CastSpec, CostSpec, ManaCost,
)
from .rules_state import Zone


def fixture_programs():
    etb = EventPattern('zone_changed', to_zone=Zone.BATTLEFIELD, subject='self')
    return (
        CardProgram('uro', 'Uro (ETB fixture)', ('Creature',), supertypes=('Legendary',), cast=CastSpec(CostSpec(ManaCost(1, ('G', 'U')))), mana_value=3, power=6, toughness=6, abilities=(
            AbilityProgram('sacrifice-unless-escaped', etb,
                           (UnlessEntered('escaped', (Sacrifice('source'),)),)),
            AbilityProgram('gain-draw-land', etb, (GainLife(3), Draw(),
                Select(Selector(Zone.HAND, ('Land',), 'owned'), 0, 1,
                       (Move('selected', Zone.BATTLEFIELD),)))),
        )),
        CardProgram('body-double', 'Body Double (entry-copy fixture)', ('Creature',), cast=CastSpec(CostSpec(ManaCost(4, ('U',)))), mana_value=5, power=0, toughness=0,
                    entry_copy=Selector(Zone.GRAVEYARD, ('Creature',))),
        CardProgram('starfield', 'Starfield (upkeep and animation fixture)', ('Enchantment',), cast=CastSpec(CostSpec(ManaCost(4, ('W',)))), mana_value=5,
            continuous=(ContinuousProgram('animate-enchantments',
                Selector(Zone.BATTLEFIELD, ('Enchantment',), 'controlled', True, excluded_subtypes=('Aura',)),
                (ChangeTypes(add=('Creature',)), SetPT('mana_value', 'mana_value')),
                condition=CountCondition(Selector(Zone.BATTLEFIELD, ('Enchantment',), 'controlled'), 5)),),
            abilities=(
            AbilityProgram('upkeep-return', EventPattern('step_began', controller_only=True, step='upkeep'),
                (May((Move('target', Zone.BATTLEFIELD),)),),
                TargetSpec(Selector(Zone.GRAVEYARD, ('Enchantment',), 'owned'))),
        )),
        CardProgram('sage', 'Evolution Sage (landfall fixture)', ('Creature',), cast=CastSpec(CostSpec(ManaCost(2, ('G',)))), mana_value=3, power=3, toughness=2, abilities=(
            AbilityProgram('landfall-proliferate', EventPattern('zone_changed', to_zone=Zone.BATTLEFIELD,
                types=('Land',), controller_only=True), (Proliferate(),)),
        )),
        CardProgram('remand', 'Remand (counter fixture)', ('Instant',), mana_value=2,
                    cast=CastSpec(CostSpec(ManaCost(1, ('U',))), 'instant'),
                    spell_effects=(Counter(destination=Zone.HAND), Draw()),
                    spell_targets=TargetSpec(Selector(Zone.STACK))),
        CardProgram('animate', 'Animate Dead (attachment fixture)', ('Enchantment',), cast=CastSpec(CostSpec(ManaCost(1, ('B',)))), mana_value=2,
            continuous=(ContinuousProgram('enchanted-power', Selector(Zone.BATTLEFIELD, ('Creature',)),
                (ModifyPT(-1, 0),), subject='attached'),),
            enchant=Selector(Zone.GRAVEYARD, ('Creature',)),
            spell_targets=TargetSpec(Selector(Zone.GRAVEYARD, ('Creature',))),
            abilities=(AbilityProgram('return-enchanted', etb, (
                WithAttached((
                    SetAttachmentRule(Selector(Zone.BATTLEFIELD, ('Creature',))),
                    WithMoved('attached', Zone.BATTLEFIELD, (
                        SetAttachmentRule(Selector(Zone.BATTLEFIELD, ('Creature',)), 'moved'),
                        Attach('source', 'moved'),
                        DelayedTrigger(EventPattern('zone_changed', from_zone=Zone.BATTLEFIELD, subject='self'),
                                       (Sacrifice('moved', by_subject_controller=True),)),
                    )),
                )),
            ), source_must_remain=Zone.BATTLEFIELD),)),
        CardProgram('felidar', 'Felidar Guardian (blink fixture)', ('Creature',), cast=CastSpec(CostSpec(ManaCost(3, ('W',)))), mana_value=4, power=1, toughness=4, abilities=(
            AbilityProgram('blink-another', etb,
                (May((WithMoved('target', Zone.EXILE, (Move('moved', Zone.BATTLEFIELD, controller='owner'),)),)),),
                TargetSpec(Selector(Zone.BATTLEFIELD, relation='controlled', exclude_source=True))),
        )),
        CardProgram('land', 'Land fixture', ('Land',)),
        CardProgram('creature', 'Creature fixture', ('Creature',), power=2, toughness=2),
        CardProgram('enchantment', 'Enchantment fixture', ('Enchantment',), mana_value=2),
    )
