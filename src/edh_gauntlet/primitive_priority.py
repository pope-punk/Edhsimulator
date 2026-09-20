"""Conservative proof that priority offers no affordable non-mana action.

Upper-bound mana supply and lower-bound costs: uncertainty keeps pilot control.
No commands are simulated and no ordered library is read.
"""
from collections import Counter
from dataclasses import fields, is_dataclass
from .rules_state import Zone
from .rules_program import (AddMana, ChooseMana, ChooseCommanderMana, LandMana,
    CostSpec, DoubleFacedProgram, RoomProgram, GraveyardAlternativeCost,
    ConvokeCast, LifeCostModifier, Selector)
from .rules_casting import _mana_symbols_satisfied

PLAIN_MANA = (AddMana, ChooseMana, ChooseCommanderMana, LandMana)


def _orientation_sensitive(value):
    if isinstance(value, Selector) and value.tapped is not None:
        return True
    if is_dataclass(value):
        return any(_orientation_sensitive(getattr(value, f.name)) for f in fields(value))
    if isinstance(value, (tuple, list)):
        return any(_orientation_sensitive(v) for v in value)
    return False


def _mana_bound(kernel, actor, objects):
    """Optimistic total and per-color capacities; None means unbounded/unknown.

Each tapped source contributes at most its largest production, not the sum of
its mutually exclusive abilities. Per-color maxima may overestimate flexible
sources; that can retain an extra inference, never suppress a payable action.
"""
    colors = Counter(dict(kernel.state.mana_pool(actor)))
    total = sum(colors.values())
    for obj in objects:
        owner = obj.controller if obj.zone == Zone.BATTLEFIELD else obj.owner
        if owner != actor or obj.phased:
            continue
        capacities = []
        for ability in kernel.activated_abilities(obj):
            if ability.zone != obj.zone or not ability.mana_ability:
                continue
            if ability.cost.tap_source and obj.tapped:
                continue
            if not ability.cost.tap_source:
                return None  # Repeatable/filter/sacrifice engines require fuller analysis.
            if any(type(e) not in PLAIN_MANA for e in ability.effects):
                return None
            amount = 0; by_color = Counter()
            for effect in ability.effects:
                if type(effect) is AddMana:
                    options = (effect.symbols,)
                elif type(effect) is ChooseMana:
                    options = effect.options
                else:
                    # Treat commander/other-land choices as any color, conservatively.
                    options = tuple((c,) for c in 'WUBRGC')
                options = [kernel._mana_after_replacements(actor, option, tapped_for_mana=True) for option in options]
                amount += max((len(option) for option in options), default=0)
                for color in 'WUBRGC':
                    by_color[color] += max((option.count(color) for option in options), default=0)
            capacities.append((amount, by_color))
        total += max((n for n, _ in capacities), default=0)
        for color in 'WUBRGC':
            colors[color] += max((c[color] for _, c in capacities), default=0)
    return total, colors


def _could_pay(kernel, obj, spec, bound, *, spell=False):
    if bound is None or not isinstance(spec.generic_reduction, int):
        return True
    if isinstance(spec, ConvokeCast):
        return True
    costs = [spec.cost]
    if spell:
        costs.extend(a.cost for a in spec.alternatives)
    reduction = max(0, spec.generic_reduction)
    if spell:
        # Ignore applicability and taxes when forming a lower bound. This may
        # overestimate affordability but never excludes a discounted/free spell.
        for permanent in kernel.state.objects(Zone.BATTLEFIELD):
            if permanent.phased:
                continue
            for modifier in kernel.definition(permanent).cost_modifiers:
                if isinstance(modifier, LifeCostModifier):
                    return True
                reduction += max(0, -modifier.generic_delta)
    total, colors = bound
    for cost in costs:
        generic = max(0, cost.mana.generic - reduction)
        if generic + len(cost.mana.symbols) <= total and _mana_symbols_satisfied(cost.mana.symbols, colors):
            return True
    return False


def mana_only_window(kernel, actor):
    # Stack presence alone is not an available response. Apply the same
    # conservative affordability proof while retaining unknown delayed effects.
    if kernel.delayed_triggers or kernel.temporary_effects:
        return False
    main = not kernel.stack and kernel.active == actor and kernel.phase in {'precombat_main', 'postcombat_main'}
    public = (Zone.BATTLEFIELD, Zone.GRAVEYARD, Zone.EXILE, Zone.COMMAND, Zone.STACK)
    objects = [o for o in kernel.state.objects() if o.zone in public or o.zone == Zone.HAND and o.owner == actor]
    objects.extend(kernel.revealed_ability_sources())
    top = kernel._visible_library_top(actor, actor)
    if top is not None:
        objects.append(top)
    objects = list({o.ref: o for o in objects}.values())
    bound = _mana_bound(kernel, actor, objects)
    mana_available = any(not obj.phased and
        (obj.controller if obj.zone == Zone.BATTLEFIELD else obj.owner) == actor and
        any(a.mana_ability and a.zone == obj.zone and not (a.cost.tap_source and obj.tapped)
            for a in kernel.activated_abilities(obj)) for obj in objects)
    permissions = kernel.player_permissions()[actor] if main else None
    for obj in objects:
        if obj.phased:
            continue
        program = kernel.definition(obj)
        if mana_available and obj.zone == Zone.BATTLEFIELD and _orientation_sensitive(program.continuous):
            return False
        if mana_available and any(kernel._trigger_abilities(obj, kind) for kind in ('becomes_tapped', 'ability_activated')):
            return False
        if obj.owner == actor and obj.zone != Zone.BATTLEFIELD:
            physical = kernel.definitions[obj.definition]
            profiles = [program]
            if isinstance(physical, DoubleFacedProgram) and physical.layout == 'modal':
                profiles.append(physical.back)
            if isinstance(physical, RoomProgram):
                return False
            for profile in profiles:
                if main and 'Land' in profile.types and kernel.turn_schedule is not None:
                    land_origin = obj.zone.value in permissions['land_zones'] or (
                        obj.zone == Zone.LIBRARY and permissions.get('play_library_top'))
                    if land_origin and kernel.turn_schedule['land_plays'] < permissions['land_play_limit']:
                        return False
                spec = profile.cast
                if spec is None:
                    continue
                origins = set(spec.origin_zones)
                if any(isinstance(a, GraveyardAlternativeCost) for a in spec.alternatives):
                    origins.add(Zone.GRAVEYARD)
                if obj.zone in origins and (obj.zone != Zone.COMMAND or obj.commander):
                    if (main or spec.timing != 'sorcery' or 'flash' in profile.keywords) and _could_pay(kernel, obj, spec, bound, spell=True):
                        return False
        owner = obj.controller if obj.zone == Zone.BATTLEFIELD else obj.owner
        if owner != actor:
            continue
        if main and isinstance(kernel.definitions[obj.definition], RoomProgram):
            return False  # Unlock is a separate special action.
        for ability in kernel.activated_abilities(obj):
            if ability.zone != obj.zone or ability.timing == 'sorcery' and not main:
                continue
            if ability.cost.tap_source and obj.tapped:
                continue
            if not ability.mana_ability:
                if _could_pay(kernel, obj, ability, bound):
                    return False
                continue
            cost = ability.cost
            # Even a mana ability can be material for its other effects/costs.
            if (type(cost) is not CostSpec or cost.life or cost.tap_selector or cost.tap_count
                    or cost.zone_costs or cost.counter_costs):
                return False
            if obj.zone == Zone.BATTLEFIELD and 'Creature' in kernel.effective(obj.ref).types:
                return False  # Deliberately tapping a creature can affect combat.
            if not ability.effects or any(type(effect) not in PLAIN_MANA for effect in ability.effects):
                return False
    return True
