"""Immutable derived characteristics for the experimental closed instruction set.

Supports copied printed values, type changes, numeric/base-MV P/T setters,
numeric modifiers, P/T counters and switches. No callbacks or card-name logic.
Dependencies are re-evaluated within a layer; multi-layer effects retain their
recipient set. This is not an implementation of arbitrary continuous effects.
"""
from dataclasses import dataclass, replace
import json
from types import MappingProxyType
from .rules_state import Zone, RulesViolation
from .rules_subtypes import CREATURE_TYPES,LAND_TYPES,SUBTYPE_SETS,expanded_subtypes
from .rules_program import DevotionCondition, AddActivated, SetColors, PlayerCountCondition, LifeCondition, AllConditions, AnyConditions, NotCondition, AddSubtypes, AddKeywords, ChangeTypes, SetPT, ModifyPT, SwitchPT


@dataclass(frozen=True)
class Characteristics:
    types: frozenset[str]
    subtypes: frozenset[str]
    mana_value: int
    power: int | None
    toughness: int | None
    applied: tuple[str, ...] = ()
    target_restrictions: tuple = ()
    keywords: frozenset[str] = frozenset()
    supertypes: frozenset[str] = frozenset()
    colors: frozenset[str] = frozenset()
    granted_abilities: tuple = ()
    mana_symbols: tuple[str,...] = ()


def base(obj, definitions):
    definition = definitions[obj.effective_definition]
    subtypes = frozenset(definition.subtypes) | ({'Aura'} if definition.enchant else set())
    subtypes=expanded_subtypes(tuple(sorted(subtypes)),definition.all_subtype_sets) if definition.all_subtype_sets else subtypes
    return Characteristics(frozenset(definition.types) | frozenset(obj.copied_add_types), frozenset(subtypes),
                           definition.mana_value + (definition.cast.cost.mana.x_symbols * obj.cast_x
                               if obj.zone == Zone.STACK and definition.cast else 0), definition.power, definition.toughness,
                           target_restrictions=definition.target_restrictions if obj.zone == Zone.BATTLEFIELD else (),
                           keywords=frozenset(definition.keywords),
                           supertypes=frozenset(definition.supertypes),colors=frozenset(definition.colors),
                           mana_symbols=definition.cast.cost.mana.symbols if definition.cast else ())


def characteristics_match(ranges, view):
    for bound in ranges:
        value=getattr(view,bound.statistic)
        if value is None or bound.minimum is not None and value<bound.minimum or bound.maximum is not None and value>bound.maximum:
            return False
    return True


def counters_match(ranges, obj):
    if not ranges:return True
    counters=dict(obj.counters)
    return all((r.minimum is None or counters.get(r.kind,0)>=r.minimum)
        and (r.maximum is None or counters.get(r.kind,0)<=r.maximum) for r in ranges)


def matches(selector, obj, view, source):
    if selector.characteristics and obj.zone==Zone.BATTLEFIELD and 'Creature' not in view.types and any(bound.statistic in {'power','toughness'} for bound in selector.characteristics):return False
    return (not obj.phased and obj.zone == selector.zone
        and counters_match(selector.counters,obj)
        and (selector.commander is None or obj.commander==selector.commander)
        and (selector.tapped is None or obj.tapped==selector.tapped)
        and (not selector.exclude_source or obj.ref != source.ref)
        and (selector.relation != 'owned' or obj.owner == source.controller)
        and (selector.relation != 'controlled' or obj.zone in {Zone.BATTLEFIELD,Zone.STACK} and obj.controller == source.controller)
        and (selector.relation != 'opponent_controlled' or obj.zone in {Zone.BATTLEFIELD,Zone.STACK} and obj.controller != source.controller)
        and (not selector.colors or set(selector.colors)<=view.colors)
        and (not selector.any_colors or bool(set(selector.any_colors)&view.colors))
        and (not selector.excluded_colors or not set(selector.excluded_colors)&view.colors)
        and (not selector.any_types or bool(set(selector.any_types) & view.types))
        and not set(selector.excluded_types) & view.types
        and set(selector.types) <= view.types and set(selector.subtypes) <= view.subtypes
        and set(selector.supertypes) <= view.supertypes
        and (not selector.any_subtypes or bool(set(selector.any_subtypes) & view.subtypes))
        and not set(selector.excluded_subtypes) & view.subtypes
        and characteristics_match(selector.characteristics,view))


def _layer(change):
    return {ChangeTypes: 4, AddSubtypes: 4, SetColors: 5, AddKeywords: 6, AddActivated: 6, SetPT: 72, ModifyPT: 73, SwitchPT: 74}[type(change)]


def condition_holds(condition, source, objects, views, *, excluding_ref=None, life_totals=None, starting_life_totals=None, live_players=None):
    if condition is None:
        return True
    if isinstance(condition,(AllConditions,AnyConditions)):
        answers=(condition_holds(child,source,objects,views,excluding_ref=excluding_ref,life_totals=life_totals,starting_life_totals=starting_life_totals,live_players=live_players) for child in condition.conditions)
        return all(answers) if isinstance(condition,AllConditions) else any(answers)
    if isinstance(condition,NotCondition):
        return not condition_holds(condition.condition,source,objects,views,excluding_ref=excluding_ref,life_totals=life_totals,starting_life_totals=starting_life_totals,live_players=live_players)
    if isinstance(condition,PlayerCountCondition):
        if live_players is None:raise RulesViolation('Player-count conditions require live-player state')
        count=sum(1 for player in live_players if condition.players=='all'
            or condition.players=='opponents' and player!=source.controller
            or condition.players=='controller' and player==source.controller)
        return count>=condition.minimum
    if isinstance(condition,DevotionCondition):
        remaining=condition.minimum;colors=set(condition.colors)
        for obj in objects:
            if remaining<=0:return True
            if obj.ref!=excluding_ref and obj.zone==Zone.BATTLEFIELD and not obj.phased and obj.controller==source.controller:
                # Each hybrid symbol contributes once to combined devotion.
                remaining-=sum(bool(colors.intersection(symbol.split('/'))) for symbol in views[obj.ref].mana_symbols)
        return remaining<=0
    if isinstance(condition,LifeCondition):
        if life_totals is None or source.controller not in life_totals:
            raise RulesViolation('Life conditions require explicit player state')
        value=life_totals[source.controller]
        if condition.relative_to_starting:
            if starting_life_totals is None or source.controller not in starting_life_totals:
                raise RulesViolation('Relative life conditions require starting life totals')
            value-=starting_life_totals[source.controller]
        return (condition.minimum is None or value>=condition.minimum) and (condition.maximum is None or value<=condition.maximum)
    # Stop counting as soon as the threshold is reached; membership still uses
    # the same derived characteristics as selectors and replacement lookahead.
    remaining = condition.minimum
    for obj in objects:
        if remaining <= 0:
            return True
        if obj.ref != excluding_ref and matches(condition.selector, obj, views[obj.ref], source):
            remaining -= 1
    return remaining <= 0


def _recipients(source, effect, objects, views, entering_ref=None, life_totals=None, starting_life_totals=None, live_players=None):
    if not condition_holds(effect.condition, source, objects, views, excluding_ref=entering_ref,life_totals=life_totals,starting_life_totals=starting_life_totals,live_players=live_players):
        return ()
    return tuple(obj.ref for obj in objects if matches(effect.selector, obj, views[obj.ref], source)
        and (source.ref != entering_ref or obj.ref == entering_ref)
        and (effect.subject != 'self' or obj.ref == source.ref)
        and (effect.subject != 'attached' or obj.ref == source.attached_to))


def _apply(views, refs, changes, key, grant_key=None):
    for ref in refs:
        view = views[ref]
        for change_index,change in enumerate(changes):
            if isinstance(change, ChangeTypes):
                types=(view.types-set(change.remove))|set(change.add)
                subtypes=view.subtypes
                if {'Creature','Kindred'}&view.types and not {'Creature','Kindred'}&types:subtypes=subtypes-CREATURE_TYPES
                if 'Land' in view.types and 'Land' not in types:subtypes=subtypes-LAND_TYPES
                view=replace(view,types=types,subtypes=subtypes)
            elif isinstance(change,AddSubtypes):
                if change.card_type in view.types:view=replace(view,subtypes=view.subtypes|expanded_subtypes(change.subtypes,change.sets))
            elif isinstance(change,SetColors):
                view=replace(view,colors=frozenset(change.colors))
            elif isinstance(change,AddActivated):
                identity=[grant_key[0].to_json() if grant_key else None,key,change_index,change.ability.ability_id]
                ability=replace(change.ability,ability_id='granted:'+json.dumps(identity,sort_keys=True,separators=(',',':')))
                view=replace(view,granted_abilities=view.granted_abilities+(ability,))
            elif isinstance(change,AddKeywords):
                view=replace(view,keywords=view.keywords|set(change.keywords))
            elif 'Creature' in view.types:
                power = view.power if view.power is not None else 0
                toughness = view.toughness if view.toughness is not None else 0
                if isinstance(change, SetPT):
                    value = lambda v: view.mana_value if v == 'mana_value' else v
                    view = replace(view, power=value(change.power), toughness=value(change.toughness))
                elif isinstance(change, ModifyPT):
                    view = replace(view, power=power + change.power, toughness=toughness + change.toughness)
                else:
                    view = replace(view, power=toughness, toughness=power)
        views[ref] = replace(view, applied=view.applied + (key,))


def _without_cycle_edges(dependencies):
    reachable = {}
    for start in dependencies:
        seen = set()
        pending = list(dependencies[start])
        while pending:
            node = pending.pop()
            if node not in seen:
                seen.add(node)
                pending.extend(dependencies[node] - seen)
        reachable[start] = seen
    return {node: {dep for dep in deps if node not in reachable[dep]}
            for node, deps in dependencies.items()}


def condition_selectors(condition):
    """All predicate reads, including branches skipped by short-circuit evaluation."""
    if isinstance(condition,(AllConditions,AnyConditions)):
        for child in condition.conditions:yield from condition_selectors(child)
    elif isinstance(condition,NotCondition):
        yield from condition_selectors(condition.condition)
    elif condition is not None and not isinstance(condition,(LifeCondition,PlayerCountCondition,DevotionCondition)):
        yield condition.selector


def _may_change_recipients(changes, effect):
    """Conservative read/write analysis for the closed characteristic vocabulary.

    Selectors and nested count conditions may read numeric characteristics.
    Changes that can affect those reads retain exhaustive dependency checks.
    """
    selectors=(effect.selector,*condition_selectors(effect.condition))
    reads={kind for selector in selectors for kind in selector.types+selector.any_types+selector.excluded_types}
    statistics={bound.statistic for selector in selectors for bound in selector.characteristics}
    subtype_reads={subtype for selector in selectors for subtype in selector.subtypes+selector.any_subtypes+selector.excluded_subtypes}
    for change in changes:
        if isinstance(change, ChangeTypes):
            if (reads.intersection(change.add + change.remove) or 'Creature' in change.add+change.remove and statistics & {'power','toughness'}
                    or {'Creature','Kindred'}&set(change.remove) and subtype_reads & CREATURE_TYPES
                    or 'Land' in change.remove and subtype_reads & LAND_TYPES):
                return True
        elif isinstance(change,SetColors):
            if any(s.colors or s.any_colors or s.excluded_colors for s in selectors):return True
        elif isinstance(change,AddSubtypes):
            if subtype_reads.intersection(expanded_subtypes(change.subtypes,change.sets)):return True
        elif isinstance(change,(SetPT,ModifyPT,SwitchPT)):
            if statistics & {'power','toughness'}:return True
        elif not isinstance(change,(AddKeywords,AddActivated)):
            return True
    return False


def evaluate(objects, definitions, *, entering_ref=None, temporary=(), life_totals=None, starting_life_totals=None, live_players=None):
    return _evaluate(objects, definitions, entering_ref=entering_ref, temporary=temporary, dependency_pruning=True,life_totals=life_totals,starting_life_totals=starting_life_totals,live_players=live_players)


def evaluate_exhaustive(objects, definitions, *, entering_ref=None, temporary=(), life_totals=None, starting_life_totals=None, live_players=None):
    """Slow comparison oracle for tests/benchmarks, never selected by the kernel."""
    return _evaluate(objects, definitions, entering_ref=entering_ref, temporary=temporary, dependency_pruning=False,life_totals=life_totals,starting_life_totals=starting_life_totals,live_players=live_players)


def _evaluate(objects, definitions, *, entering_ref, temporary, dependency_pruning, life_totals, starting_life_totals, live_players):
    objects = tuple(objects)
    views = {obj.ref: base(obj, definitions) for obj in objects}
    effects = []
    characteristic_setters=[]
    for source in objects:
        definition=definitions[source.effective_definition]
        if definition.characteristic_pt is not None:characteristic_setters.append((source,definition.characteristic_pt.selector))
        if source.zone != Zone.BATTLEFIELD or source.phased:
            continue
        for effect in definition.continuous:
            key = (source.ref, effect.effect_id)
            effects.append((key, source, effect))
    locked = {}
    current={obj.ref:obj for obj in objects}
    for source,effect,refs in temporary:
        key=(source.ref,effect.effect_id)
        effects.append((key,source,effect))
        locked[key]=tuple(ref for ref in refs if ref in current and current[ref].zone==Zone.BATTLEFIELD and not current[ref].phased)
    for layer in (4, 5, 6, 71, 72, 73, 74):
        if layer==71:
            for source,selector in characteristic_setters:
                amount=sum(1 for obj in objects if matches(selector,obj,views[obj.ref],source))
                view=views[source.ref]
                views[source.ref]=replace(view,power=amount,toughness=amount,applied=view.applied+('characteristic_pt',))
            continue
        pending = [row for row in effects if any(_layer(c) == layer for c in row[2].changes)]
        pending.sort(key=lambda row: (row[1].timestamp, row[1].ref, row[2].effect_id))
        changes = {row[0]: tuple(c for c in row[2].changes if _layer(c) == layer) for row in pending}
        if dependency_pruning and not any(
                row[0] not in locked and _may_change_recipients(changes[other[0]], row[2])
                for other in pending for row in pending if row != other):
            # Proven independent: timestamp order is sufficient, with one
            # recipient calculation per effect instead of repeated graph passes.
            for key, source, effect in pending:
                refs = locked[key] if key in locked else _recipients(source, effect, objects, views, entering_ref, life_totals, starting_life_totals, live_players)
                locked.setdefault(key, refs)
                _apply(views, refs, changes[key], effect.effect_id, key)
            pending = []
        while pending:
            def recipients(row, state):
                return locked[row[0]] if row[0] in locked else _recipients(row[1], row[2], objects, state, entering_ref, life_totals, starting_life_totals, live_players)
            # A cache lives only within this dependency pass. Applying an effect
            # invalidates it; cross-layer recipient locking remains separate.
            current = {row[0]: recipients(row, views) for row in pending}
            dependencies = {row[0]: set() for row in pending}
            for other in pending:
                affected = [row for row in pending if row != other and (
                    not dependency_pruning or row[0] not in locked and
                    _may_change_recipients(changes[other[0]], row[2]))]
                if not affected:
                    continue
                hypothetical = dict(views)
                _apply(hypothetical, current[other[0]], changes[other[0]], other[2].effect_id, other[0])
                for row in affected:
                    if current[row[0]] != recipients(row, hypothetical):
                        dependencies[row[0]].add(other[0])
            ordered_dependencies = _without_cycle_edges(dependencies)
            ready = [row for row in pending if not ordered_dependencies[row[0]]]
            row = ready[0]
            refs = current[row[0]]
            locked.setdefault(row[0], refs)
            _apply(views, refs, changes[row[0]], row[2].effect_id, row[0])
            pending.remove(row)
        if layer == 73:
            for obj in objects:
                view = views[obj.ref]
                # Latent printed values survive type-layer evaluation, but
                # noncreature permanents expose no P/T (CR 208.3).
                if obj.zone==Zone.BATTLEFIELD and 'Creature' not in view.types:
                    if view.power is not None or view.toughness is not None:views[obj.ref]=replace(view,power=None,toughness=None)
                    continue
                if obj.zone != Zone.BATTLEFIELD or obj.phased:
                    continue
                counters = dict(obj.counters)
                delta = counters.get('+1/+1', 0) - counters.get('-1/-1', 0)
                if delta:
                    views[obj.ref] = replace(view, power=(view.power or 0) + delta,
                                            toughness=(view.toughness or 0) + delta,
                                            applied=view.applied + ('pt-counters',))
    return MappingProxyType(views)
