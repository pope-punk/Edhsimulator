"""Closed, serializable ability programs for the experimental rules interpreter."""
from __future__ import annotations
from dataclasses import dataclass,fields
from .rules_state import Zone,RulesViolation
from .rules_subtypes import SUBTYPE_SETS,SUBTYPE_SUPPORT


@dataclass(frozen=True)
class CharacteristicRange:
    statistic: str
    minimum: int | ChosenX | CountObjects | ScaledValue | LifeLost | EventAmount | MovedCount | SelectedCount | EventX | DividedValue | SourceCounter | SourceStat | BattlefieldStat | RecipientStat | TargetStat | None = None
    maximum: int | ChosenX | CountObjects | ScaledValue | LifeLost | EventAmount | MovedCount | SelectedCount | EventX | DividedValue | SourceCounter | SourceStat | BattlefieldStat | RecipientStat | TargetStat | None = None


@dataclass(frozen=True)
class CounterRange:
    kind: str
    minimum: int | None = 1
    maximum: int | None = None


@dataclass(frozen=True)
class Selector:
    zone:Zone
    types:tuple[str,...]=()
    relation:str='any'  # any, owned, controlled, opponent_controlled
    exclude_source:bool=False
    subtypes:tuple[str,...]=()
    excluded_subtypes:tuple[str,...]=()
    supertypes:tuple[str,...]=()
    any_types:tuple[str,...]=()
    excluded_types:tuple[str,...]=()
    any_subtypes:tuple[str,...]=()
    characteristics:tuple[CharacteristicRange,...]=()
    commander: bool | None = None
    tapped: bool | None = None
    counters: tuple[CounterRange,...] = ()
    colors: tuple[str,...] = ()
    any_colors: tuple[str,...] = ()
    excluded_colors: tuple[str,...] = ()


@dataclass(frozen=True)
class SelectedCount:
    """Number of exact objects captured by the enclosing selection."""
    pass


@dataclass(frozen=True)
class MovedCount:
    """Number of objects reaching the enclosing zone result's required destination."""
    pass


@dataclass(frozen=True)
class LifeLost:
    """Total life actually lost by the enclosing WithLifeLost instruction."""
    pass


@dataclass(frozen=True)
class EventAmount:
    """The amount captured when a supported life-gain trigger occurred."""
    pass


@dataclass(frozen=True)
class RecipientStat:
    """Statistic of one recipient when a temporary effect begins."""
    statistic: str = 'power'
    allow_negative: bool = False


@dataclass(frozen=True)
class TargetStat:
    statistic: str = 'power'
    operation: str = 'sum'


@dataclass(frozen=True)
class SourceCounter:
    """Counters of one kind on the source, using exact last known information."""
    kind: str


@dataclass(frozen=True)
class SourceStat:
    """Current source statistic, or its exact last known public characteristics."""
    statistic: str = 'power'
    allow_negative: bool = False


@dataclass(frozen=True)
class BattlefieldStat:
    selector: Selector
    statistic: str = 'power'
    operation: str = 'maximum'


@dataclass(frozen=True)
class EventX:
    """Announced X retained by a cast or battlefield-entry event, independent of the trigger source."""
    pass


@dataclass(frozen=True)
class DividedValue:
    """Nonnegative integer quotient, explicitly rounded down or up."""
    value: int | ChosenX | CountObjects | ScaledValue | LifeLost | EventAmount | MovedCount | SelectedCount | EventX | DividedValue | SourceCounter | SourceStat | BattlefieldStat | RecipientStat | TargetStat
    divisor: int
    rounding: str = "down"


@dataclass(frozen=True)
class ChosenX:
    """The X announced for this spell or activated ability, not its source card."""
    pass


@dataclass(frozen=True)
class CountObjects:
    selector: Selector


@dataclass(frozen=True)
class ScaledValue:
    value: int | ChosenX | CountObjects | ScaledValue | LifeLost | EventAmount | MovedCount | SelectedCount | EventX | DividedValue | SourceCounter | SourceStat | BattlefieldStat | RecipientStat | TargetStat
    factor: int


@dataclass(frozen=True)
class ProduceMana:
    """Produce an amount of one chosen type without enumerating mana bundles."""
    amount: int | ChosenX | CountObjects | ScaledValue | LifeLost | EventAmount | MovedCount | SelectedCount | EventX | DividedValue | SourceCounter | SourceStat | BattlefieldStat | RecipientStat | TargetStat
    options: tuple[str,...]


@dataclass(frozen=True)
class TargetSpec:
    selector:Selector|None=None
    minimum:int | ChosenX=1
    maximum:int | ChosenX=1
    group_by_controller:bool=False
    players:str|None=None
    combat:str|None=None
    groups:tuple[TargetGroup,...]=()


@dataclass(frozen=True)
class TargetGroup:
    group_id:str
    targets:TargetSpec


@dataclass(frozen=True)
class EventPattern:
    kind:str  # zone_changed or step_began
    from_zone:Zone|None=None
    to_zone:Zone|None=None
    subject:str='any'  # any or self
    types:tuple[str,...]=()
    controller_only:bool=False
    step:str|None=None
    counter_kind:str|None=None
    recipient_relation:str='any'
    characteristics:tuple[CharacteristicRange,...]=()
    any_types:tuple[str,...]=()
    exclude_source:bool=False
    counters:tuple[CounterRange,...]=()


@dataclass(frozen=True)
class Move:
    subject:str
    destination:Zone
    controller:str='effect'
    tapped:bool=False
    library_position:str|None=None
    counters:tuple[tuple[str,int],...]=()


@dataclass(frozen=True)
class Sacrifice:
    subject:str
    by_subject_controller:bool=False


@dataclass(frozen=True)
class Destroy:
    subject: str


@dataclass(frozen=True)
class Discard:
    subject: str


@dataclass(frozen=True)
class Counter:
    subject:str='target'
    destination:Zone=Zone.GRAVEYARD


@dataclass(frozen=True)
class CounterAbilities:
    """Counter waiting activated and triggered abilities in a controller domain."""
    players: str = 'all'


@dataclass(frozen=True)
class Damage:
    subject: str
    amount: int | ChosenX | CountObjects | ScaledValue | LifeLost | EventAmount | MovedCount | SelectedCount | EventX | DividedValue | SourceCounter | SourceStat | BattlefieldStat | RecipientStat | TargetStat

    source_subject: str = 'source'
    players: str | None = None
    exclude_damage_source: bool = False

@dataclass(frozen=True)
class GainControl:
    subject: str
    duration: str = 'indefinite'


@dataclass(frozen=True)
class SearchLibrary:
    selector: Selector
    destination: Zone
    count: int = 1
    reveal: bool = False
    optional_find: bool = False
    tapped: bool = False
    secondary_destination: Zone | None = None
    primary_count: int = 1
    secondary_tapped: bool = False
    distinct_names: bool = False
    partition_player: str | None = None


@dataclass(frozen=True)
class ChooseFromTop:
    """Partition a bounded library window using a filtered optional selection."""
    amount: int
    selector: Selector
    count: int = 1
    reveal: bool = False
    destination: Zone = Zone.HAND
    remainder: str = 'graveyard'
    tapped: bool = False


@dataclass(frozen=True)
class Surveil:
    amount: int = 1


@dataclass(frozen=True)
class LookTop:
    """Look at the top cards of your library and return them in any order."""
    amount: int = 1


@dataclass(frozen=True)
class Scry:
    amount: int = 1


@dataclass(frozen=True)
class Draw:
    amount:int | ChosenX | CountObjects | ScaledValue | LifeLost | EventAmount | MovedCount | SelectedCount | EventX | DividedValue | SourceCounter | SourceStat | BattlefieldStat | RecipientStat | TargetStat=1
    players:str='controller'


@dataclass(frozen=True)
class Mill:
    """Move up to the requested number of top library cards simultaneously."""
    amount: int | ChosenX | CountObjects | ScaledValue | LifeLost | EventAmount | MovedCount | SelectedCount | EventX | DividedValue | SourceCounter | SourceStat | BattlefieldStat | RecipientStat | TargetStat = 1
    players: str = 'controller'


@dataclass(frozen=True)
class WithLifeLost:
    players: str
    amount: int | ChosenX | CountObjects | ScaledValue | LifeLost | EventAmount | MovedCount | SelectedCount | EventX | DividedValue | SourceCounter | SourceStat | BattlefieldStat | RecipientStat | TargetStat
    effects: tuple


@dataclass(frozen=True)
class LoseLife:
    players:str
    amount:int | ChosenX | CountObjects | ScaledValue | LifeLost | EventAmount | MovedCount | SelectedCount | EventX | DividedValue | SourceCounter | SourceStat | BattlefieldStat | RecipientStat | TargetStat


@dataclass(frozen=True)
class GainLife:
    amount:int | ChosenX | CountObjects | ScaledValue | LifeLost | EventAmount | MovedCount | SelectedCount | EventX | DividedValue | SourceCounter | SourceStat | BattlefieldStat | RecipientStat | TargetStat


@dataclass(frozen=True)
class May:
    effects:tuple
    otherwise:tuple=()
    available:Selector|None=None
    subject:str='source'


@dataclass(frozen=True)
class UnlessEntered:
    flag:str
    effects:tuple


@dataclass(frozen=True)
class Proliferate:pass


@dataclass(frozen=True)
class MultiplyCounters:
    subject: str
    kind: str
    factor: int = 2


@dataclass(frozen=True)
class AddCounters:
    subject:str
    kind:str
    amount:int | ChosenX | CountObjects | ScaledValue | LifeLost | EventAmount | MovedCount | SelectedCount | EventX | DividedValue | SourceCounter | SourceStat | BattlefieldStat | RecipientStat | TargetStat


@dataclass(frozen=True)
class Select:
    selector:Selector
    minimum:int
    maximum:int
    effects:tuple
    ordered:bool=False
    group_by_controller:bool=False


@dataclass(frozen=True)
class SelectAll:
    selector: Selector
    effects: tuple


@dataclass(frozen=True)
class SetTapped:
    subject: str
    tapped: bool


@dataclass(frozen=True)
class WithZoneResult:
    operation: Move | Destroy | Sacrifice | Discard | Counter
    destination: Zone | None
    effects: tuple
    selector: Selector | None = None


@dataclass(frozen=True)
class WithControllers:
    subject: str
    effects: tuple


@dataclass(frozen=True)
class WithMoved:
    subject: str
    destination: Zone
    effects: tuple
    controller: str = 'effect'


@dataclass(frozen=True)
class WithAttached:
    effects: tuple


@dataclass(frozen=True)
class SetAttachmentRule:
    selector: Selector
    exact_subject: str | None = None


@dataclass(frozen=True)
class Attach:
    subject: str
    to: str


@dataclass(frozen=True)
class DelayedTrigger:
    event: EventPattern
    effects: tuple


@dataclass(frozen=True)
class AbilityProgram:
    ability_id:str
    event:EventPattern
    effects:tuple
    targets:TargetSpec|None=None
    source_must_remain:Zone|None=None
    intervening_if:CountCondition|PlayerCountCondition|DevotionCondition|LifeCondition|AllConditions|AnyConditions|NotCondition|None=None
    trigger_limit:int|None=None
    occurrence_condition:CountCondition|PlayerCountCondition|DevotionCondition|LifeCondition|AllConditions|AnyConditions|NotCondition|None=None
    optional_once_per_turn:bool=False


@dataclass(frozen=True)
class ZoneReplacement:
    replacement_id: str
    destination: Zone
    redirect: Zone
    from_zone: Zone | None = None
    types: tuple[str, ...] = ()
    relation: str = 'any'
    subject: str = 'any'
    optional: bool = False


@dataclass(frozen=True)
class PlayerCountCondition:
    minimum: int
    players: str = 'opponents'


@dataclass(frozen=True)
class DevotionCondition:
    colors:tuple[str,...]
    minimum:int


@dataclass(frozen=True)
class LifeCondition:
    """Inclusive life bounds, optionally measured relative to starting life."""
    minimum: int | None = None
    maximum: int | None = None
    relative_to_starting: bool = False


@dataclass(frozen=True)
class CountCondition:
    selector: Selector
    minimum: int


@dataclass(frozen=True)
class AllConditions:
    conditions: tuple


@dataclass(frozen=True)
class AnyConditions:
    conditions: tuple


@dataclass(frozen=True)
class NotCondition:
    condition: CountCondition | PlayerCountCondition | DevotionCondition | LifeCondition | AllConditions | AnyConditions | NotCondition


@dataclass(frozen=True)
class EntryModifier:
    modifier_id: str
    tapped: bool = True
    condition: CountCondition | PlayerCountCondition | DevotionCondition | LifeCondition | AllConditions | AnyConditions | NotCondition | None = None
    unless: bool = False
    selector: Selector | None = None


@dataclass(frozen=True)
class IfCondition:
    condition: CountCondition | PlayerCountCondition | DevotionCondition | LifeCondition | AllConditions | AnyConditions | NotCondition
    effects: tuple
    otherwise: tuple = ()


@dataclass(frozen=True)
class SetColors:
    colors: tuple[str,...]


@dataclass(frozen=True)
class ChangeTypes:
    add: tuple[str, ...] = ()
    remove: tuple[str, ...] = ()


@dataclass(frozen=True)
class AddSubtypes:
    card_type: str
    subtypes: tuple[str,...] = ()
    sets: tuple[str,...] = ()


@dataclass(frozen=True)
class SetPT:
    power: int | str
    toughness: int | str


@dataclass(frozen=True)
class ModifyPT:
    power: int
    toughness: int


@dataclass(frozen=True)
class SwitchPT:
    pass


@dataclass(frozen=True)
class AddActivated:
    ability: ActivatedProgram


@dataclass(frozen=True)
class AddKeywords:
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class UntilEndOfTurn:
    subject: str
    changes: tuple


@dataclass(frozen=True)
class ContinuousProgram:
    effect_id: str
    selector: Selector
    changes: tuple
    subject: str = 'any'
    condition: CountCondition | PlayerCountCondition | DevotionCondition | LifeCondition | AllConditions | AnyConditions | NotCondition | None = None


@dataclass(frozen=True)
class ManaCost:
    generic: int = 0
    symbols: tuple[str, ...] = ()
    x_symbols: int = 0


@dataclass(frozen=True)
class ZoneCost:
    cost_id: str
    kind: str
    selector: Selector | None = None  # None means the activating source itself.
    count: int = 1


@dataclass(frozen=True)
class CreateTokens:
    token: CardProgram
    amount: int | ChosenX | CountObjects | ScaledValue | LifeLost | EventAmount | MovedCount | SelectedCount | EventX | DividedValue | SourceCounter | SourceStat | BattlefieldStat | RecipientStat | TargetStat = 1
    players: str = 'controller'


@dataclass(frozen=True)
class CounterCost:
    kind: str
    amount: int


@dataclass(frozen=True)
class CostSpec:
    mana: ManaCost = ManaCost()
    life: int = 0
    tap_source: bool = False
    tap_selector: Selector | None = None
    tap_count: int = 0
    zone_costs: tuple[ZoneCost,...] = ()
    counter_costs: tuple[CounterCost,...] = ()


@dataclass(frozen=True)
class AlternativeCost:
    alternative_id: str
    cost: CostSpec
    condition: CountCondition | PlayerCountCondition | DevotionCondition | LifeCondition | AllConditions | AnyConditions | NotCondition | None = None


@dataclass(frozen=True)
class CastSpec:
    cost: CostSpec
    timing: str = 'sorcery'
    generic_reduction: int | CountObjects | BattlefieldStat | ScaledValue | DividedValue = 0
    origin_zones:tuple[Zone,...]=(Zone.HAND,Zone.COMMAND)
    alternatives:tuple[AlternativeCost,...]=()


@dataclass(frozen=True)
class ActivatedProgram:
    ability_id: str
    cost: CostSpec
    effects: tuple
    targets: TargetSpec | None = None
    timing: str = 'instant'
    mana_ability: bool = False
    zone: Zone = Zone.BATTLEFIELD
    minimum_x: int = 0
    generic_reduction: int | CountObjects | BattlefieldStat | ScaledValue | DividedValue = 0


@dataclass(frozen=True)
class AddMana:
    symbols: tuple[str, ...]


@dataclass(frozen=True)
class ChooseMana:
    options: tuple[tuple[str,...],...]


@dataclass(frozen=True)
class ChooseCommanderMana:
    pass


@dataclass(frozen=True)
class CostModifier:
    modifier_id: str
    selector: Selector
    generic_delta: int
    origin_zones:tuple[Zone,...]=()


@dataclass(frozen=True)
class CastRestriction:
    selector:Selector
    origin_zones:tuple[Zone,...]


@dataclass(frozen=True)
class BlockRestriction:
    attackers: Selector
    blockers: Selector
    statistic: str
    comparison: str
    value: int | SourceStat | SourceCounter | CountObjects | BattlefieldStat | ScaledValue


@dataclass(frozen=True)
class TargetRestriction:
    opponents_only: bool = False
    source_types: tuple[str,...] = ()


@dataclass(frozen=True)
class EntryCounters:
    replacement_id: str
    kind: str
    amount: int | ChosenX | CountObjects | ScaledValue | DividedValue
    selector: Selector | None = None


@dataclass(frozen=True)
class CounterReplacement:
    replacement_id: str
    selector: Selector | None = None
    players: str | None = None
    kind: str | None = None
    multiplier: int = 1
    additional: int = 0
    subject: str = 'any'
    divisor: int = 1
    actor_relation: str = 'any'


@dataclass(frozen=True)
class TappedManaReplacement:
    replacement_id: str
    multiplier: int = 2
    players: str = 'controller'


@dataclass(frozen=True)
class LifeGainReplacement:
    replacement_id: str
    additional: int = 1
    players: str = 'controller'


@dataclass(frozen=True)
class PlayerPermissions:
    additional_land_plays: int = 0
    no_maximum_hand_size: bool = False
    land_zones: tuple[Zone,...] = ()


@dataclass(frozen=True)
class GrantPermissions:
    permissions: PlayerPermissions
    duration: str = 'until_end_of_turn'


@dataclass(frozen=True)
class SpellMode:
    mode_id: str
    effects: tuple
    targets: TargetSpec | None = None


@dataclass(frozen=True)
class ModalSpec:
    modes: tuple[SpellMode,...]
    minimum: int = 1
    maximum: int = 1
    extra_mode_condition: CountCondition | PlayerCountCondition | DevotionCondition | LifeCondition | AllConditions | AnyConditions | NotCondition | None = None
    conditional_maximum: int | None = None


@dataclass(frozen=True)
class CardProgram:
    definition_id:str
    name:str
    types:tuple[str,...]
    abilities:tuple[AbilityProgram,...]=()
    spell_effects:tuple=()
    spell_targets:TargetSpec|None=None
    entry_copy:Selector|None=None
    entry_modifiers:tuple[EntryModifier,...]=()
    replacements:tuple[ZoneReplacement,...]=()
    enchant:Selector|None=None
    subtypes:tuple[str,...]=()
    mana_value:int=0
    power:int|None=None
    toughness:int|None=None
    continuous:tuple[ContinuousProgram,...]=()
    cast:CastSpec|None=None
    activated:tuple[ActivatedProgram,...]=()
    cost_modifiers:tuple[CostModifier,...]=()
    target_restrictions:tuple[TargetRestriction,...]=()
    keywords:tuple[str,...]=()
    supertypes:tuple[str,...]=()
    player_permissions:PlayerPermissions=PlayerPermissions()
    counter_replacements:tuple[CounterReplacement,...]=()
    entry_counters:tuple[EntryCounters,...]=()
    colors:tuple[str,...]=()
    modal:ModalSpec|None=None
    entry_copy_tapped:bool=False
    characteristic_pt:CountObjects|None=None
    life_gain_replacements:tuple[LifeGainReplacement,...]=()
    block_restrictions:tuple[BlockRestriction,...]=()
    tapped_mana_replacements:tuple[TappedManaReplacement,...]=()
    all_subtype_sets:tuple[str,...]=()
    entry_restrictions:tuple[Selector,...]=()
    casting_restrictions:tuple[CastRestriction,...]=()
    entry_copy_add_types:tuple[str,...]=()


KEYWORDS=frozenset(('haste','flying','reach','menace','vigilance','defender','first_strike','double_strike','trample','deathtouch','lifelink','indestructible','unblockable','flash','hexproof','shroud'))

TYPES={cls.__name__:cls for cls in (AlternativeCost,CastRestriction,DevotionCondition,TappedManaReplacement,AddActivated,BlockRestriction,LifeGainReplacement,SourceCounter,TargetStat,SetColors,SelectedCount,CounterRange,PlayerCountCondition,SpellMode,ModalSpec,LifeCondition,AddSubtypes,CharacteristicRange,AllConditions,AnyConditions,NotCondition,RecipientStat,UntilEndOfTurn,AddKeywords,SourceStat,BattlefieldStat,EventX,DividedValue,MovedCount,SetTapped,WithZoneResult,WithControllers,CreateTokens,CounterCost,EntryCounters,CounterReplacement,MultiplyCounters,LifeLost,EventAmount,WithLifeLost,LoseLife,PlayerPermissions,GrantPermissions,ChosenX,CountObjects,ScaledValue,ProduceMana,Selector,TargetSpec,TargetGroup,EventPattern,Move,Sacrifice,Destroy,Discard,Counter,CounterAbilities,Damage,GainControl,ChooseFromTop,SearchLibrary,Surveil,LookTop,Scry,Draw,Mill,GainLife,May,UnlessEntered,Proliferate,AddCounters,Select,SelectAll,WithMoved,WithAttached,SetAttachmentRule,Attach,DelayedTrigger,AbilityProgram,ZoneReplacement,CountCondition,EntryModifier,IfCondition,ChangeTypes,SetPT,ModifyPT,SwitchPT,ContinuousProgram,ManaCost,ZoneCost,CostSpec,CastSpec,ActivatedProgram,AddMana,ChooseMana,ChooseCommanderMana,CostModifier,TargetRestriction,CardProgram)}
EFFECTS=(UntilEndOfTurn,SetTapped,WithZoneResult,WithControllers,CreateTokens,MultiplyCounters,WithLifeLost,LoseLife,GrantPermissions,ProduceMana,Move,Sacrifice,Destroy,Discard,Counter,CounterAbilities,Damage,GainControl,ChooseFromTop,SearchLibrary,Surveil,LookTop,Scry,Draw,Mill,GainLife,May,UnlessEntered,Proliferate,AddCounters,Select,SelectAll,WithMoved,WithAttached,SetAttachmentRule,Attach,DelayedTrigger,AddMana,ChooseMana,ChooseCommanderMana,IfCondition)


def encode(value):
    if type(value).__name__ in TYPES and type(value) is TYPES[type(value).__name__]:
        return {'node':type(value).__name__,**{field.name:encode(getattr(value,field.name)) for field in fields(value)}}
    if isinstance(value,Zone):return {'zone':value.value}
    if isinstance(value,tuple):return [encode(item) for item in value]
    if value is None or type(value) in (str,int,bool):return value
    raise RulesViolation('Program contains an unsupported value')


def decode(value):
    if isinstance(value,list):return tuple(decode(item) for item in value)
    if isinstance(value,dict):
        if set(value)=={'zone'}:return Zone(value['zone'])
        cls=TYPES.get(value.get('node'))
        if cls is None or set(value)-{'node'}!={field.name for field in fields(cls)}:raise RulesViolation('Unknown or malformed program node')
        return cls(**{key:decode(item) for key,item in value.items() if key!='node'})
    if value is None or type(value) in (str,int,bool):return value
    raise RulesViolation('Invalid serialized program')


def immediate_effect_nodes(nodes):
    """Walk effects executed now, excluding bodies of future delayed triggers."""
    for node in nodes:
        yield node
        if isinstance(node,WithZoneResult):
            yield from immediate_effect_nodes((node.operation,))
            yield from immediate_effect_nodes(node.effects)
        if isinstance(node,(May,UnlessEntered,Select,SelectAll,WithMoved,WithControllers,WithAttached,IfCondition,WithLifeLost)):
            yield from immediate_effect_nodes(node.effects)
        if isinstance(node,(IfCondition,May)):
            yield from immediate_effect_nodes(node.otherwise)


ACTOR_EVENTS=frozenset({'spell_cast','ability_activated','life_gained','card_drawn',
    'library_searched','library_shuffled','scried','surveilled'})


def event_player_matches(pattern,controller,player):
    return ((not pattern.controller_only or controller==player)
        and (pattern.recipient_relation=='any'
             or (controller==player)==(pattern.recipient_relation=='controlled')))


def constant_quantity(value):
    """Return a provable nonnegative constant, or None for state-bound values.

    This is static classification only; program validation still visits every
    operand and runtime evaluation still enforces its ordinary bindings.
    """
    if type(value) is int:return max(0,value)
    if isinstance(value,ScaledValue):
        if value.factor==0:return 0
        operand=constant_quantity(value.value)
        if operand is not None:return max(0,operand*value.factor)
    if isinstance(value,DividedValue):
        operand=constant_quantity(value.value)
        if operand is not None:
            return (operand+value.divisor-1)//value.divisor if value.rounding=='up' else operand//value.divisor
    return None


def activation_is_mana(ability):
    """Classify the supported activation vocabulary under 605.1a.

    Loyalty and library-moving costs need their own nodes.
    """
    nodes=tuple(immediate_effect_nodes(ability.effects))
    produces=any(isinstance(node,(AddMana,ChooseMana,ChooseCommanderMana))
        or isinstance(node,ProduceMana) and constant_quantity(node.amount)!=0 for node in nodes)
    # CR 605.1a (August 2026): moving cards across the library boundary
    # disqualifies an activation. Merely looking, shuffling or rearranging
    # within that zone does not. Assess possible movement, not current contents.
    def moves_library_card(node):
        if isinstance(node,(Draw,Mill,Surveil)):
            return constant_quantity(node.amount)!=0
        if isinstance(node,SearchLibrary):
            return node.count>0 and (node.destination!=Zone.LIBRARY or node.secondary_destination is not None)
        if isinstance(node,ChooseFromTop):
            return node.amount>0 and (node.remainder=='graveyard' or node.count>0)
        return (isinstance(node,(Move,WithMoved,Counter)) and node.destination==Zone.LIBRARY
            or isinstance(node,(Select,SelectAll)) and node.selector.zone==Zone.LIBRARY)
    library=any(moves_library_card(node) for node in nodes)
    return ability.targets is None and produces and not library


def validate(program,_depth=0):
    if _depth>16:raise RulesViolation('Token program nesting is too deep')
    """Reject malformed programs and unresolved bindings before execution."""
    def strings(values):
        return isinstance(values, tuple) and all(type(v) is str and v for v in values)

    def characteristic_ranges(values,dynamic=False,allow_x=False,available_values=frozenset()):
        if not isinstance(values,tuple):raise RulesViolation('Characteristic ranges must be immutable')
        seen=set()
        for value in values:
            if (not isinstance(value,CharacteristicRange) or type(value.statistic) is not str or value.statistic not in {'power','toughness','mana_value'}
                    or value.statistic in seen or value.minimum is None and value.maximum is None
                    or not dynamic and any(bound is not None and type(bound) is not int for bound in (value.minimum,value.maximum))
                    or type(value.minimum) is int and type(value.maximum) is int and value.minimum>value.maximum):
                raise RulesViolation('Invalid characteristic range')
            for bound in (value.minimum,value.maximum):
                if bound is not None and type(bound) is not int:quantity(bound,allow_x,available_values=available_values|{'signed_bound','signed_scaling'})
            seen.add(value.statistic)

    def selector(value,dynamic=False,allow_x=False,available_values=frozenset()):
        if (not isinstance(value, Selector) or not isinstance(value.zone, Zone)
                or value.relation not in {'any', 'owned', 'controlled', 'opponent_controlled'}
                or not strings(value.types) or not strings(value.any_subtypes) or not strings(value.any_types) or not strings(value.excluded_types) or not strings(value.supertypes) or not strings(value.subtypes) or not strings(value.excluded_subtypes) or type(value.exclude_source) is not bool or value.commander is not None and type(value.commander) is not bool):
            raise RulesViolation('Invalid selector')
        if value.tapped is not None and (type(value.tapped) is not bool or value.zone!=Zone.BATTLEFIELD):raise RulesViolation('Orientation selectors require battlefield objects')
        characteristic_ranges(value.characteristics,dynamic,allow_x,available_values)
        for colors in (value.colors,value.any_colors,value.excluded_colors):
            if not strings(colors) or len(set(colors))!=len(colors) or any(color not in 'WUBRG' or len(color)!=1 for color in colors):raise RulesViolation('Invalid color selector')
        if not isinstance(value.counters,tuple) or value.counters and value.zone!=Zone.BATTLEFIELD:raise RulesViolation('Counter selectors require battlefield objects')
        kinds=set()
        for counter in value.counters:
            if (not isinstance(counter,CounterRange) or type(counter.kind) is not str or not counter.kind or counter.kind in kinds
                    or counter.minimum is None and counter.maximum is None
                    or any(bound is not None and (type(bound) is not int or bound<0) for bound in (counter.minimum,counter.maximum))
                    or counter.minimum is not None and counter.maximum is not None and counter.minimum>counter.maximum):
                raise RulesViolation('Invalid counter range')
            kinds.add(counter.kind)

    def subtype_addition(change):
        if (type(change.card_type) is not str or change.card_type not in {'Land','Creature','Kindred','Artifact','Enchantment','Planeswalker','Battle','Instant','Sorcery'}
                or not strings(change.subtypes) or len(set(change.subtypes))!=len(change.subtypes)
                or not strings(change.sets) or len(set(change.sets))!=len(change.sets)
                or not (change.subtypes or change.sets)
                or any(name not in SUBTYPE_SETS or change.card_type not in SUBTYPE_SUPPORT[name] for name in change.sets)):
            raise RulesViolation('Invalid subtype additions')

    def bounds(minimum, maximum):
        if type(minimum) is not int or type(maximum) is not int or not 0 <= minimum <= maximum:
            raise RulesViolation('Invalid choice bounds')

    def target(value,allow_x=False,allow_groups=False):
        if not isinstance(value, TargetSpec) or type(value.group_by_controller) is not bool:
            raise RulesViolation('Invalid targets')
        if not isinstance(value.groups,tuple):raise RulesViolation('Target groups must be immutable')
        if value.groups:
            if not allow_groups:raise RulesViolation('Grouped targets currently require a triggered ability')
            if value.selector is not None or value.players is not None or value.combat is not None or value.group_by_controller:
                raise RulesViolation('Grouped targets cannot also declare a flat domain')
            bounds(value.minimum,value.maximum);ids=[]
            for group in value.groups:
                if not isinstance(group,TargetGroup) or type(group.group_id) is not str or not group.group_id:
                    raise RulesViolation('Invalid target group')
                target(group.targets)
                if group.targets.players is not None or group.targets.group_by_controller:
                    raise RulesViolation('Grouped targets currently require object-only independent clauses')
                ids.append(group.group_id)
            if len(ids)!=len(set(ids)):raise RulesViolation('Duplicate target group ID')
            if (value.minimum,value.maximum)!=(sum(g.targets.minimum for g in value.groups),sum(g.targets.maximum for g in value.groups)):
                raise RulesViolation('Grouped target bounds must equal the clause totals')
            return
        if value.selector is not None:selector(value.selector,dynamic=True)
        if (value.combat is not None and (type(value.combat) is not str or value.combat not in {'attacking','blocking','attacking_or_blocking'}
                or value.selector is None or value.selector.zone!=Zone.BATTLEFIELD or value.players is not None)):
            raise RulesViolation('Invalid combat target domain')
        if value.players not in {None,'all','opponents','controller'} or value.selector is None and value.players is None:
            raise RulesViolation('Invalid target domains')
        if isinstance(value.minimum,ChosenX) or isinstance(value.maximum,ChosenX):
            if not allow_x:raise RulesViolation('Variable targets require an announced X cost')
            for bound in (value.minimum,value.maximum):
                if not isinstance(bound,ChosenX) and (type(bound) is not int or bound<0):raise RulesViolation('Invalid variable target bounds')
        else:bounds(value.minimum,value.maximum)

    def mana(value):
        if (not isinstance(value, ManaCost) or type(value.generic) is not int or value.generic < 0
                or type(value.x_symbols) is not int or value.x_symbols < 0
                or not isinstance(value.symbols, tuple) or any(not (type(symbol) is str and (symbol in tuple('WUBRGC')
                    or len(symbol)==3 and symbol[1]=='/' and symbol[0] in 'WUBRG' and symbol[2] in 'WUBRG' and symbol[0]!=symbol[2])) for symbol in value.symbols)):
            raise RulesViolation('Unsupported mana cost')

    def cost(value):
        if (not isinstance(value, CostSpec) or type(value.life) is not int or value.life < 0
                or type(value.tap_source) is not bool or type(value.tap_count) is not int or value.tap_count < 0):
            raise RulesViolation('Invalid cost specification')
        mana(value.mana)
        if not isinstance(value.counter_costs,tuple):raise RulesViolation('Counter costs must be immutable')
        kinds=[]
        for counter_cost in value.counter_costs:
            if (not isinstance(counter_cost,CounterCost) or type(counter_cost.kind) is not str or not counter_cost.kind
                    or type(counter_cost.amount) is not int or counter_cost.amount<1):raise RulesViolation('Invalid source counter cost')
            kinds.append(counter_cost.kind)
        if len(kinds)!=len(set(kinds)):raise RulesViolation('Duplicate counter-cost kind')
        if value.counter_costs and value.zone_costs:raise RulesViolation('Counter and zone costs require separately ordered cost groups')
        if not isinstance(value.zone_costs,tuple) or len(value.zone_costs)>1:
            raise RulesViolation('Only one simultaneous zone-cost group is currently supported')
        for zone_cost in value.zone_costs:
            if (not isinstance(zone_cost,ZoneCost) or type(zone_cost.cost_id) is not str or not zone_cost.cost_id
                    or zone_cost.kind not in {'sacrifice','discard','exile','return'}
                    or type(zone_cost.count) is not int or zone_cost.count<1):raise RulesViolation('Invalid zone cost')
            if zone_cost.selector is None:
                if zone_cost.count!=1:raise RulesViolation('Invalid source zone cost')
            else:
                selector(zone_cost.selector);sel=zone_cost.selector
                allowed=(sel.zone==Zone.BATTLEFIELD and sel.relation=='controlled' if zone_cost.kind in {'sacrifice','return'}
                    else sel.zone==Zone.HAND and sel.relation=='owned' if zone_cost.kind=='discard'
                    else sel.zone in {Zone.HAND,Zone.GRAVEYARD} and sel.relation=='owned' or sel.zone==Zone.BATTLEFIELD and sel.relation in {'owned','controlled'})
                if not allowed:raise RulesViolation('Unsupported zone-cost selection')
        if (value.tap_selector is None) != (value.tap_count == 0):
            raise RulesViolation('Tap selection and count must be supplied together')
        if value.tap_selector is not None:
            selector(value.tap_selector)
            if value.tap_selector.zone != Zone.BATTLEFIELD or value.tap_selector.relation != 'controlled':
                raise RulesViolation('Tap costs require controlled battlefield objects')

    def condition(value,depth=0):
        if depth>16:raise RulesViolation('Condition expression is too deep')
        if isinstance(value,(AllConditions,AnyConditions)):
            if not isinstance(value.conditions,tuple) or not 1<=len(value.conditions)<=32:
                raise RulesViolation('Compound conditions require 1 to 32 immutable operands')
            for child in value.conditions:condition(child,depth+1)
            return
        if isinstance(value,NotCondition):
            condition(value.condition,depth+1)
            return
        if isinstance(value,PlayerCountCondition):
            if type(value.minimum) is not int or value.minimum<0 or type(value.players) is not str or value.players not in {'all','opponents','controller'}:
                raise RulesViolation('Invalid player-count condition')
            return
        if isinstance(value,DevotionCondition):
            if (not strings(value.colors) or not value.colors or len(value.colors)!=len(set(value.colors)) or not set(value.colors)<=set("WUBRG")
                    or type(value.minimum) is not int or value.minimum<0):raise RulesViolation("Invalid devotion condition")
            return
        if isinstance(value,LifeCondition):
            if (type(value.relative_to_starting) is not bool or value.minimum is None and value.maximum is None
                    or any(bound is not None and type(bound) is not int for bound in (value.minimum,value.maximum))
                    or value.minimum is not None and value.maximum is not None and value.minimum>value.maximum):
                raise RulesViolation('Invalid life condition bounds')
            return
        if not isinstance(value, CountCondition):
            raise RulesViolation('Unsupported rules condition')
        selector(value.selector)
        if value.selector.zone != Zone.BATTLEFIELD or type(value.minimum) is not int or value.minimum < 0:
            raise RulesViolation('Count conditions require a nonnegative battlefield threshold')

    def permissions(value):
        if (not isinstance(value,PlayerPermissions) or type(value.additional_land_plays) is not int or value.additional_land_plays<0
                or type(value.no_maximum_hand_size) is not bool or not isinstance(value.land_zones,tuple)
                or any(zone!=Zone.GRAVEYARD or not isinstance(zone,Zone) for zone in value.land_zones)
                or len(set(value.land_zones))!=len(value.land_zones)):
            raise RulesViolation('Unsupported player permissions')

    def quantity(value,allow_x=False,depth=0,available_values=frozenset(),allow_source=True):
        if depth>16:raise RulesViolation('Quantity expression is too deep')
        if type(value) is int:
            if value<0:raise RulesViolation('Invalid quantity')
        elif isinstance(value,SourceCounter):
            if not allow_source:raise RulesViolation('Incoming source counter expressions are not yet supported')
            if type(value.kind) is not str or not value.kind:raise RulesViolation('Invalid source counter kind')
        elif isinstance(value,TargetStat):
            if 'target_statistics' not in available_values:raise RulesViolation('Unbound target statistic')
            if type(value.statistic) is not str or value.statistic not in {'power','toughness','mana_value','color_count'} or type(value.operation) is not str or value.operation not in {'sum','maximum'}:raise RulesViolation('Invalid target statistic')
        elif isinstance(value,RecipientStat):
            if 'recipient_stat' not in available_values:raise RulesViolation('Unbound recipient statistic')
            if type(value.statistic) is not str or value.statistic not in {'power','toughness','mana_value'} or type(value.allow_negative) is not bool:raise RulesViolation('Invalid recipient statistic')
        elif isinstance(value,(SourceStat,BattlefieldStat)):
            if isinstance(value,SourceStat):
                if not allow_source:raise RulesViolation('Incoming source statistic expressions are not yet supported')
                if type(value.allow_negative) is not bool or value.allow_negative and 'signed_bound' not in available_values:
                    raise RulesViolation('Signed source statistics require a numeric selection bound')
            if type(value.statistic) is not str or value.statistic not in {'power','toughness','mana_value'}:raise RulesViolation('Invalid characteristic statistic')
            if isinstance(value,BattlefieldStat):
                selector(value.selector)
                if value.selector.zone!=Zone.BATTLEFIELD or type(value.operation) is not str or value.operation not in {'maximum','sum'}:raise RulesViolation('Invalid battlefield statistic aggregation')
        elif isinstance(value,EventX):
            if "event_x" not in available_values:raise RulesViolation("Unbound numeric result: event_x")
        elif isinstance(value,(LifeLost,EventAmount,MovedCount,SelectedCount)):
            key='selected_count' if isinstance(value,SelectedCount) else 'life_lost' if isinstance(value,LifeLost) else 'moved_count' if isinstance(value,MovedCount) else 'event_amount'
            if key not in available_values:raise RulesViolation('Unbound numeric result: '+key)
        elif isinstance(value,ChosenX):
            if not allow_x:raise RulesViolation('Chosen X requires this action to have an X cost')
        elif isinstance(value,CountObjects):
            selector(value.selector)
            if value.selector.zone!=Zone.BATTLEFIELD:raise RulesViolation('Count expressions currently require battlefield objects')
        elif isinstance(value,DividedValue):
            if type(value.divisor) is not int or value.divisor<=0 or type(value.rounding) is not str or value.rounding not in {"down","up"}:raise RulesViolation("Invalid quantity division")
            quantity(value.value,allow_x,depth+1,available_values,allow_source)
        elif isinstance(value,ScaledValue):
            if type(value.factor) is not int or value.factor<0 and 'signed_scaling' not in available_values:raise RulesViolation('Invalid quantity multiplier')
            quantity(value.value,allow_x,depth+1,available_values,allow_source)
        else:raise RulesViolation('Invalid quantity expression')

    def effects(nodes, bindings,allow_x=False,available_values=frozenset()):
        if 'target' in bindings:available_values=available_values|{'target_statistics'}
        if not isinstance(nodes, tuple):
            raise RulesViolation('Effects must be immutable tuples')
        for node in nodes:
            if type(node) not in EFFECTS:
                raise RulesViolation('Unregistered effect node')
            if isinstance(node,UntilEndOfTurn):
                if not isinstance(node.changes,tuple) or not node.changes:raise RulesViolation('Empty or mutable temporary changes')
                for change in node.changes:
                    if isinstance(change,(ModifyPT,SetPT)):
                        for value in (change.power,change.toughness):
                            if type(value) is not int:quantity(value,allow_x,available_values=available_values|{'recipient_stat','signed_scaling'})
                    elif isinstance(change,AddKeywords):
                        if not strings(change.keywords) or not change.keywords or set(change.keywords)-KEYWORDS:raise RulesViolation('Invalid keyword grants')
                    elif isinstance(change,SetColors):
                        if not strings(change.colors) or len(set(change.colors))!=len(change.colors) or any(c not in tuple('WUBRG') for c in change.colors):raise RulesViolation('Invalid color changes')
                    elif isinstance(change,AddSubtypes):
                        subtype_addition(change)
                    elif isinstance(change,ChangeTypes):
                        if not strings(change.add) or not strings(change.remove):raise RulesViolation('Invalid type changes')
                    elif not isinstance(change,SwitchPT):raise RulesViolation('Unsupported temporary continuous change')
            if isinstance(node,CreateTokens):
                if type(node.players) is not str or node.players not in {'controller','opponents','all','target','controller_and_target','captured_controllers','moved_controllers','event_controllers','defending_player'}:raise RulesViolation('Invalid token creators')
                if node.players in {'captured_controllers','moved_controllers','event_controllers','defending_player'} and node.players not in available_values:raise RulesViolation('Unbound captured token creators')
                if not isinstance(node.token,CardProgram) or node.token.cast is not None:raise RulesViolation('Token creation requires a permanent token program without casting permission')
                if not set(node.token.types)&{'Artifact','Battle','Creature','Enchantment','Land','Planeswalker'} or set(node.token.types)&{'Instant','Sorcery'}:raise RulesViolation('Token program must describe a permanent')
                validate(node.token,_depth+1);quantity(node.amount,allow_x,available_values=available_values)
            if isinstance(node,ChooseFromTop):
                selector(node.selector)
                if (type(node.amount) is not int or node.amount<0 or type(node.count) is not int or node.count<0
                        or type(node.reveal) is not bool or type(node.tapped) is not bool
                        or not isinstance(node.destination,Zone) or node.destination not in {Zone.HAND,Zone.BATTLEFIELD,Zone.GRAVEYARD}
                        or node.tapped and node.destination!=Zone.BATTLEFIELD
                        or type(node.remainder) is not str or node.remainder not in {'graveyard','random_bottom'}
                        or node.selector.zone!=Zone.LIBRARY
                        or node.selector.relation!='owned' or node.selector.exclude_source):
                    raise RulesViolation('Unsupported top-card selection')
            if isinstance(node, SearchLibrary):
                selector(node.selector)
                if (node.selector.zone!=Zone.LIBRARY or node.selector.relation!='owned' or node.selector.exclude_source
                        or not isinstance(node.destination,Zone) or node.destination not in {Zone.HAND,Zone.BATTLEFIELD,Zone.LIBRARY,Zone.GRAVEYARD} or type(node.count) is not int or node.count<1
                        or type(node.reveal) is not bool or type(node.optional_find) is not bool or type(node.tapped) is not bool or node.tapped and node.destination!=Zone.BATTLEFIELD):
                    raise RulesViolation('Unsupported library search')
                if (type(node.primary_count) is not int or node.primary_count<1
                        or type(node.secondary_tapped) is not bool
                        or node.secondary_destination is None and (node.primary_count!=1 or node.secondary_tapped)
                        or node.secondary_destination is not None and (not isinstance(node.secondary_destination,Zone)
                            or node.secondary_destination not in {Zone.HAND,Zone.BATTLEFIELD,Zone.GRAVEYARD}
                            or node.destination not in {Zone.HAND,Zone.BATTLEFIELD,Zone.GRAVEYARD}
                            or node.secondary_destination==node.destination
                            or node.primary_count>node.count
                            or node.secondary_tapped and node.secondary_destination!=Zone.BATTLEFIELD)):
                    raise RulesViolation('Unsupported split library search')
                if (type(node.distinct_names) is not bool or node.partition_player is not None and type(node.partition_player) is not str or node.partition_player not in {None,'controller','target'}
                        or node.partition_player is not None and node.secondary_destination is None
                        or node.partition_player=='target' and (not node.reveal or 'target' not in bindings)):
                    raise RulesViolation('Invalid search name constraint or partition player')
            if isinstance(node,GrantPermissions):
                permissions(node.permissions)
                if node.duration!='until_end_of_turn':raise RulesViolation('Unsupported permission duration')
            if isinstance(node,ProduceMana):
                quantity(node.amount,allow_x,available_values=available_values)
                if (not strings(node.options) or not node.options or len(set(node.options))!=len(node.options)
                        or any(symbol not in tuple('WUBRGC') for symbol in node.options)):
                    raise RulesViolation('Invalid mana type choices')
            if isinstance(node, ChooseMana):
                if (not isinstance(node.options,tuple) or not node.options or len(node.options)>32
                        or any(not isinstance(option,tuple) or not option or any(symbol not in tuple('WUBRGC') for symbol in option) for option in node.options)
                        or len(set(node.options))!=len(node.options)):
                    raise RulesViolation('Invalid mana production choices')
            if isinstance(node, AddMana) and (not isinstance(node.symbols, tuple) or not node.symbols
                    or any(symbol not in tuple('WUBRGC') for symbol in node.symbols)):
                raise RulesViolation('Unsupported mana production')
            if isinstance(node, (Move, Sacrifice, Destroy, Discard, Counter, Damage, GainControl, AddCounters, MultiplyCounters, WithMoved, WithControllers, SetTapped, UntilEndOfTurn, Attach)) and (type(node.subject) is not str or node.subject not in bindings and not (isinstance(node,Damage) and node.subject=='controller') and not (isinstance(node,(AddCounters,MultiplyCounters)) and node.subject in {'controller','opponents','all'})):
                raise RulesViolation('Unbound subject: ' + str(node.subject))
            if isinstance(node,CounterAbilities) and (type(node.players) is not str or node.players not in {'controller','opponents','all'}):
                raise RulesViolation('Invalid ability-counter controller domain')
            if isinstance(node,Damage):
                if (type(node.source_subject) is not str or node.source_subject not in bindings
                        or node.players is not None and (type(node.players) is not str or node.players not in {'controller','opponents','all'})
                        or type(node.exclude_damage_source) is not bool):raise RulesViolation('Invalid damage source or additional recipients')
            if isinstance(node,SetTapped) and type(node.tapped) is not bool:raise RulesViolation('Invalid orientation effect')
            if isinstance(node,Move) and node.library_position is not None and (node.destination!=Zone.LIBRARY or type(node.library_position) is not str or node.library_position not in {'top','bottom'}):raise RulesViolation('Invalid library placement')
            if isinstance(node,Move) and (type(node.tapped) is not bool or node.tapped and node.destination!=Zone.BATTLEFIELD):raise RulesViolation('Tapped placement requires battlefield entry')
            if isinstance(node,Move) and (not isinstance(node.counters,tuple)
                    or any(not isinstance(row,tuple) or len(row)!=2 or type(row[0]) is not str or not row[0] or type(row[1]) is not int or row[1]<=0 for row in node.counters)
                    or len({row[0] for row in node.counters})!=len(node.counters)
                    or node.counters and node.destination!=Zone.BATTLEFIELD):raise RulesViolation('Invalid movement entry counters')
            if isinstance(node, (Move, Counter, WithMoved)) and not isinstance(node.destination, Zone):
                raise RulesViolation('Invalid destination')
            if isinstance(node,(Draw,Mill,LoseLife,WithLifeLost,GainLife,AddCounters,Damage)):quantity(node.amount,allow_x,available_values=available_values)
            if isinstance(node,(Draw,Mill,LoseLife,WithLifeLost)):
                if node.players not in {'controller','opponents','all','target','controller_and_target','event_controllers','defending_player'}:raise RulesViolation('Invalid player recipients')
                if node.players in {'event_controllers','defending_player'} and node.players not in available_values:raise RulesViolation('Unbound event player recipients')
            if isinstance(node,(Scry,Surveil,LookTop)) and (type(node.amount) is not int or node.amount<0):raise RulesViolation('Invalid quantity')
            if isinstance(node,MultiplyCounters) and (type(node.factor) is not int or node.factor<1):raise RulesViolation('Invalid counter multiplier')
            if isinstance(node, (AddCounters,MultiplyCounters)) and (type(node.kind) is not str or not node.kind):
                raise RulesViolation('Invalid counter kind')
            if isinstance(node, UnlessEntered) and (type(node.flag) is not str or not node.flag):
                raise RulesViolation('Invalid entry flag')
            if isinstance(node, (Move, WithMoved)) and node.controller not in {'effect', 'owner'}:
                raise RulesViolation('Invalid destination controller mode')
            if isinstance(node, GainControl) and node.duration not in {'indefinite','until_end_of_turn'}:
                raise RulesViolation('Unsupported control duration')
            if isinstance(node, Sacrifice) and type(node.by_subject_controller) is not bool:
                raise RulesViolation('Invalid sacrifice instruction')
            if isinstance(node, Attach) and node.to not in bindings:
                raise RulesViolation('Unbound attachment destination')
            if isinstance(node, SetAttachmentRule):
                selector(node.selector)
                if node.exact_subject is not None and node.exact_subject not in bindings:
                    raise RulesViolation('Unbound attachment restriction')
            if isinstance(node, DelayedTrigger):
                # Explicitly bounded to a one-shot, exact-source leaves trigger.
                if node.event != EventPattern('zone_changed', from_zone=Zone.BATTLEFIELD, subject='self'):
                    raise RulesViolation('Unsupported delayed event pattern')
                effects(node.effects, bindings)
            if isinstance(node, IfCondition):
                condition(node.condition)
                effects(node.effects, bindings,allow_x,available_values)
                effects(node.otherwise, bindings,allow_x,available_values)
            if isinstance(node,WithLifeLost):
                effects(node.effects,bindings,allow_x,available_values|{'life_lost'})
            if isinstance(node,WithZoneResult):
                if type(node.operation) not in (Move,Destroy,Sacrifice,Discard,Counter) or node.destination is not None and not isinstance(node.destination,Zone):raise RulesViolation('Invalid zone result operation')
                if node.selector is not None:
                    selector(node.selector)
                    if node.destination is not None and node.selector.zone!=node.destination:raise RulesViolation('Zone result selector destination mismatch')
                effects((node.operation,),bindings,allow_x,available_values)
                effects(node.effects,bindings|{'moved'},allow_x,available_values|{'moved_controllers','moved_count'})
            if isinstance(node,WithControllers):
                effects(node.effects,bindings,allow_x,available_values|{'captured_controllers'})
            if isinstance(node, WithMoved):
                effects(node.effects, bindings | {'moved'},allow_x,available_values|{'moved_controllers','moved_count'})
            if isinstance(node, WithAttached):
                effects(node.effects, bindings | {'attached'},allow_x,available_values)
            if isinstance(node, SelectAll):
                selector(node.selector,True,allow_x,available_values)
                if node.selector.zone==Zone.LIBRARY:raise RulesViolation('Library operations require explicit visibility semantics')
                effects(node.effects, bindings | {'selected'},allow_x,available_values|{'selected_count'})
            if isinstance(node, Select):
                selector(node.selector,True,allow_x,available_values)
                if node.selector.zone==Zone.LIBRARY:raise RulesViolation('Library operations require explicit visibility semantics')
                bounds(node.minimum, node.maximum)
                if type(node.ordered) is not bool or type(node.group_by_controller) is not bool:
                    raise RulesViolation('Invalid selection semantics')
                effects(node.effects, bindings | {'selected'},allow_x,available_values|{'selected_count'})
            elif isinstance(node, (May, UnlessEntered)):
                effects(node.effects, bindings,allow_x,available_values)
                if isinstance(node,May):
                    effects(node.otherwise,bindings,allow_x,available_values)
                    if type(node.subject) is not str or node.subject not in bindings:raise RulesViolation('Unbound optional availability subject')
                    if node.available is None:
                        if node.subject!='source':raise RulesViolation('Availability subject requires an availability selector')
                    else:
                        selector(node.available)
                        if node.available.zone in {Zone.LIBRARY,Zone.OUTSIDE}:raise RulesViolation('Unsupported optional availability zone')

    def target_effects(nodes,spec):
        for node in immediate_effect_nodes(nodes):
            if isinstance(node,DelayedTrigger):target_effects(node.effects,spec)
            if isinstance(node,SearchLibrary) and node.partition_player=='target':
                if spec is None or spec.players is None or spec.selector is not None or spec.minimum!=1 or spec.maximum!=1:
                    raise RulesViolation('Search partition requires exactly one player target')
            if isinstance(node,(Draw,Mill,LoseLife,WithLifeLost,CreateTokens)) and node.players in {'target','controller_and_target'}:
                if spec is None or spec.players is None or spec.selector is not None:
                    raise RulesViolation('Player instructions require player-only targets')
            if spec is not None and spec.players is not None:
                if (isinstance(node,(Move,Sacrifice,Destroy,Discard,Counter,GainControl,WithMoved,WithControllers,SetTapped,UntilEndOfTurn,Attach,May)) and node.subject=='target'
                        or isinstance(node,Attach) and node.to=='target'
                        or isinstance(node,SetAttachmentRule) and node.exact_subject=='target'):
                    raise RulesViolation('Object instructions cannot consume player targets')

    if (not isinstance(program, CardProgram) or type(program.definition_id) is not str
            or not program.definition_id or type(program.name) is not str or not program.name
            or not strings(program.types) or not isinstance(program.abilities, tuple)):
        raise RulesViolation('Invalid card program')
    if (not strings(program.subtypes) or type(program.mana_value) is not int or program.mana_value < 0
            or any(value is not None and type(value) is not int for value in (program.power, program.toughness))
            or (program.power is None) != (program.toughness is None)):
        raise RulesViolation('Invalid base characteristics')
    if not isinstance(program.entry_counters,tuple):raise RulesViolation('Entry counter rules must be immutable')
    entry_counter_ids=[]
    for rule in program.entry_counters:
        if (not isinstance(rule,EntryCounters) or type(rule.replacement_id) is not str or not rule.replacement_id
                or type(rule.kind) is not str or not rule.kind):raise RulesViolation('Invalid entry counters')
        if rule.selector is not None:
            selector(rule.selector)
            if rule.selector.zone!=Zone.BATTLEFIELD:raise RulesViolation('Entry counter selectors require battlefield objects')
        quantity(rule.amount,bool(rule.selector is None and isinstance(program.cast,CastSpec) and isinstance(program.cast.cost,CostSpec) and isinstance(program.cast.cost.mana,ManaCost) and program.cast.cost.mana.x_symbols),allow_source=False)
        entry_counter_ids.append(rule.replacement_id)
    if len(entry_counter_ids)!=len(set(entry_counter_ids)):raise RulesViolation('Duplicate entry counter ID')
    if not isinstance(program.counter_replacements,tuple):raise RulesViolation('Counter replacements must be immutable')
    counter_ids=[]
    for rule in program.counter_replacements:
        if (not isinstance(rule,CounterReplacement) or type(rule.replacement_id) is not str or not rule.replacement_id
                or rule.subject not in {'any','self'} or rule.subject=='self' and rule.players is not None
                or rule.players not in {None,'controller','opponents','all'}
                or rule.selector is None and rule.players is None
                or rule.kind is not None and (type(rule.kind) is not str or not rule.kind)
                or type(rule.multiplier) is not int or rule.multiplier<0
                or type(rule.additional) is not int or rule.additional<0
                or type(rule.divisor) is not int or rule.divisor<1 or rule.actor_relation not in {'any','controller','opponents'}
                or rule.multiplier==1 and rule.additional==0 and rule.divisor==1):raise RulesViolation('Invalid counter replacement')
        if rule.selector is not None:
            selector(rule.selector)
            if rule.selector.zone!=Zone.BATTLEFIELD:raise RulesViolation('Counter replacement selectors require battlefield objects')
        counter_ids.append(rule.replacement_id)
    if len(counter_ids)!=len(set(counter_ids)):raise RulesViolation('Duplicate counter replacement ID')
    if not strings(program.colors) or set(program.colors)-set('WUBRG') or len(set(program.colors))!=len(program.colors):raise RulesViolation('Invalid printed colors')
    permissions(program.player_permissions)
    if not isinstance(program.target_restrictions, tuple) or any(
            not isinstance(rule, TargetRestriction) or type(rule.opponents_only) is not bool
            or not strings(rule.source_types) or len(set(rule.source_types))!=len(rule.source_types)
            or set(rule.source_types)-{'Artifact','Battle','Creature','Enchantment','Instant','Kindred','Land','Planeswalker','Sorcery'}
            for rule in program.target_restrictions):
        raise RulesViolation('Unsupported target restriction')
    if (not strings(program.all_subtype_sets) or len(set(program.all_subtype_sets))!=len(program.all_subtype_sets)
            or any(name not in SUBTYPE_SETS or not SUBTYPE_SUPPORT[name]&set(program.types) for name in program.all_subtype_sets)):
        raise RulesViolation('Invalid all-subtype-set characteristic')
    if not strings(program.supertypes) or set(program.supertypes)-{'Basic','Legendary','Snow'}:
        raise RulesViolation('Unsupported supertype semantics')
    if not strings(program.keywords) or set(program.keywords)-KEYWORDS:
        raise RulesViolation('Unsupported keyword semantics')
    if 'Creature' in program.types and program.power is None:
        raise RulesViolation('Creature definition requires explicit base power and toughness')
    if not isinstance(program.block_restrictions,tuple):raise RulesViolation('Block restrictions must be immutable')
    for rule in program.block_restrictions:
        if not isinstance(rule,BlockRestriction):raise RulesViolation('Invalid block restriction')
        selector(rule.attackers);selector(rule.blockers)
        if (rule.attackers.zone!=Zone.BATTLEFIELD or rule.blockers.zone!=Zone.BATTLEFIELD
                or type(rule.statistic) is not str or rule.statistic not in {'power','toughness','mana_value'}
                or type(rule.comparison) is not str or rule.comparison not in {'lt','le','eq','ge','gt'}):
            raise RulesViolation('Invalid block comparison')
        if type(rule.value) is not int:quantity(rule.value,available_values=frozenset({'signed_bound','signed_scaling'}))
    if program.cast is not None:
        if not isinstance(program.cast, CastSpec) or program.cast.timing not in {'instant', 'sorcery'}:
            raise RulesViolation('Invalid casting specification')
        if (not isinstance(program.cast.origin_zones,tuple) or not program.cast.origin_zones
                or any(not isinstance(zone,Zone) or zone not in {Zone.HAND,Zone.COMMAND,Zone.GRAVEYARD,Zone.EXILE} for zone in program.cast.origin_zones)
                or len(program.cast.origin_zones)!=len(set(program.cast.origin_zones))):raise RulesViolation("Invalid casting origin permission")
        cost(program.cast.cost)
        if not isinstance(program.cast.alternatives,tuple):raise RulesViolation('Alternative costs must be immutable')
        alternative_ids=set()
        for alternative in program.cast.alternatives:
            if (not isinstance(alternative,AlternativeCost) or type(alternative.alternative_id) is not str
                    or not alternative.alternative_id or alternative.alternative_id in alternative_ids):raise RulesViolation('Invalid alternative cost identity')
            alternative_ids.add(alternative.alternative_id);cost(alternative.cost)
            if alternative.condition is not None:condition(alternative.condition)
            if (program.cast.cost.life or program.cast.cost.mana.x_symbols or alternative.cost.mana.x_symbols
                    or alternative.cost.tap_source or alternative.cost.zone_costs or alternative.cost.counter_costs):
                raise RulesViolation('Alternative costs currently support fixed mana and life payments')
        quantity(program.cast.generic_reduction,allow_source=False)
        if program.cast.cost.counter_costs:raise RulesViolation('Source counter costs require a battlefield activation')
        if program.cast.cost.zone_costs:raise RulesViolation('Casting zone costs require the complete spell announcement transaction')
        if program.cast.cost.tap_source:
            raise RulesViolation('A spell cannot pay a tap-symbol source cost')
        if 'Land' in program.types:
            raise RulesViolation('Playing a land is not casting a spell')
    if not isinstance(program.entry_restrictions,tuple) or not isinstance(program.casting_restrictions,tuple):
        raise RulesViolation('Prohibitions must be immutable')
    for restriction in program.entry_restrictions:
        selector(restriction)
        if restriction.zone not in {Zone.GRAVEYARD,Zone.EXILE}:
            raise RulesViolation('Entry prohibitions currently require public off-battlefield origins')
    for restriction in program.casting_restrictions:
        if not isinstance(restriction,CastRestriction):raise RulesViolation('Invalid casting prohibition')
        selector(restriction.selector)
        if (restriction.selector.zone!=Zone.STACK or not isinstance(restriction.origin_zones,tuple) or not restriction.origin_zones
                or any(not isinstance(zone,Zone) or zone not in {Zone.HAND,Zone.COMMAND,Zone.GRAVEYARD,Zone.EXILE} for zone in restriction.origin_zones)
                or len(restriction.origin_zones)!=len(set(restriction.origin_zones))):raise RulesViolation('Invalid casting prohibition origins')
    if not isinstance(program.activated, tuple) or not isinstance(program.cost_modifiers, tuple):
        raise RulesViolation('Ability/cost definitions must be immutable tuples')
    activation_ids = []
    for ability in program.activated:
        if (not isinstance(ability, ActivatedProgram) or not isinstance(ability.ability_id, str) or not ability.ability_id
                or ability.timing not in {'instant', 'sorcery'} or type(ability.mana_ability) is not bool
                or not isinstance(ability.zone,Zone) or ability.zone not in {Zone.BATTLEFIELD,Zone.HAND,Zone.GRAVEYARD}):
            raise RulesViolation('Invalid activated ability')
        if ability.ability_id.startswith(('intrinsic-land:','granted:')):
            raise RulesViolation('Reserved intrinsic ability identity')
        cost(ability.cost)
        quantity(ability.generic_reduction,allow_source=False)
        if type(ability.minimum_x) is not int or ability.minimum_x<0 or ability.minimum_x and not ability.cost.mana.x_symbols:raise RulesViolation('Invalid activation minimum X')
        if ability.zone!=Zone.BATTLEFIELD and (ability.cost.tap_source or ability.cost.counter_costs):
            raise RulesViolation('Source tap and counter costs require battlefield activation')
        for zone_cost in ability.cost.zone_costs:
            if zone_cost.selector is None:
                allowed=({Zone.BATTLEFIELD} if zone_cost.kind in {'sacrifice','return'}
                    else {Zone.HAND} if zone_cost.kind=='discard' else {Zone.BATTLEFIELD,Zone.HAND,Zone.GRAVEYARD})
                if ability.zone not in allowed:raise RulesViolation('Source zone cost does not match activation zone')
        if ability.targets is not None:target(ability.targets,bool(ability.cost.mana.x_symbols))
        effects(ability.effects, {'source', 'target'} if ability.targets is not None else {'source'},bool(ability.cost.mana.x_symbols))
        target_effects(ability.effects,ability.targets)
        if ability.mana_ability != activation_is_mana(ability):
            raise RulesViolation('Activation mana-ability classification does not match its targets and immediate effects')
        activation_ids.append(ability.ability_id)
    if len(activation_ids) != len(set(activation_ids)):
        raise RulesViolation('Duplicate activated ability ID')
    modifier_ids = []
    if not isinstance(program.tapped_mana_replacements,tuple):raise RulesViolation('Mutable tapped-mana replacements')
    mana_ids=[]
    for rule in program.tapped_mana_replacements:
        if (not isinstance(rule,TappedManaReplacement) or type(rule.replacement_id) is not str or not rule.replacement_id
                or type(rule.multiplier) is not int or rule.multiplier<2 or type(rule.players) is not str or rule.players not in {'controller','opponents','all'}):
            raise RulesViolation('Invalid tapped-mana replacement')
        mana_ids.append(rule.replacement_id)
    if len(mana_ids)!=len(set(mana_ids)):raise RulesViolation('Duplicate tapped-mana replacement ID')
    if not isinstance(program.life_gain_replacements,tuple):raise RulesViolation('Mutable life-gain replacements')
    life_ids=[]
    for rule in program.life_gain_replacements:
        if (not isinstance(rule,LifeGainReplacement) or type(rule.replacement_id) is not str or not rule.replacement_id
                or type(rule.additional) is not int or rule.additional<1 or rule.players not in {'controller','opponents','all'}):
            raise RulesViolation('Invalid additive life-gain replacement')
        life_ids.append(rule.replacement_id)
    if len(life_ids)!=len(set(life_ids)):raise RulesViolation('Duplicate life-gain replacement ID')
    for modifier in program.cost_modifiers:
        if (not isinstance(modifier, CostModifier) or not isinstance(modifier.modifier_id, str) or not modifier.modifier_id
                or type(modifier.generic_delta) is not int):
            raise RulesViolation('Invalid cost modifier')
        if (not isinstance(modifier.origin_zones,tuple)
                or any(not isinstance(zone,Zone) or zone not in {Zone.HAND,Zone.COMMAND,Zone.GRAVEYARD,Zone.EXILE} for zone in modifier.origin_zones)
                or len(modifier.origin_zones)!=len(set(modifier.origin_zones))):raise RulesViolation("Invalid spell-cost origin filter")
        selector(modifier.selector)
        if modifier.selector.zone != Zone.STACK:
            raise RulesViolation('Spell cost modifiers require a stack selector')
        modifier_ids.append(modifier.modifier_id)
    if len(modifier_ids) != len(set(modifier_ids)):
        raise RulesViolation('Duplicate cost modifier ID')
    if not isinstance(program.continuous, tuple):
        raise RulesViolation('Continuous programs must be immutable')
    continuous_ids = []
    for effect in program.continuous:
        if (not isinstance(effect, ContinuousProgram) or type(effect.effect_id) is not str or not effect.effect_id
                or effect.subject not in {'any', 'self', 'attached'} or not isinstance(effect.changes, tuple)
                or not effect.changes):
            raise RulesViolation('Invalid continuous program')
        selector(effect.selector)
        if effect.selector.zone != Zone.BATTLEFIELD:
            raise RulesViolation('Only battlefield continuous effects are supported')
        if effect.condition is not None:
            condition(effect.condition)
        for change in effect.changes:
            if isinstance(change,SetColors):
                if not strings(change.colors) or len(set(change.colors))!=len(change.colors) or any(c not in tuple('WUBRG') for c in change.colors):raise RulesViolation('Invalid color changes')
            elif isinstance(change,AddSubtypes):
                subtype_addition(change)
                if change.card_type not in effect.selector.types:raise RulesViolation('Subtype additions require a matching typed selector')
            elif isinstance(change,AddActivated):
                if not isinstance(change.ability,ActivatedProgram) or change.ability.zone!=Zone.BATTLEFIELD:
                    raise RulesViolation('Granted activation must be a battlefield ability')
                validate(CardProgram('grant-validation','Grant validation',('Artifact',),activated=(change.ability,)),_depth+1)
            elif isinstance(change,AddKeywords):
                if not strings(change.keywords) or not change.keywords or set(change.keywords)-KEYWORDS:raise RulesViolation('Invalid keyword grants')
            elif isinstance(change, ChangeTypes):
                if not strings(change.add) or not strings(change.remove):
                    raise RulesViolation('Invalid type changes')
            elif isinstance(change, SetPT):
                if any(type(v) is not int and v != 'mana_value' for v in (change.power, change.toughness)):
                    raise RulesViolation('Unsupported power/toughness expression')
            elif isinstance(change, ModifyPT):
                if type(change.power) is not int or type(change.toughness) is not int:
                    raise RulesViolation('Invalid power/toughness modifier')
            elif not isinstance(change, SwitchPT):
                raise RulesViolation('Unsupported continuous operation')
        continuous_ids.append(effect.effect_id)
    if len(continuous_ids) != len(set(continuous_ids)):
        raise RulesViolation('Duplicate continuous effect ID')
    if not isinstance(program.entry_modifiers,tuple):raise RulesViolation('Entry modifiers must be immutable')
    entry_ids=[]
    for modifier in program.entry_modifiers:
        if (not isinstance(modifier,EntryModifier) or type(modifier.modifier_id) is not str or not modifier.modifier_id
                or type(modifier.tapped) is not bool or type(modifier.unless) is not bool
                or modifier.unless and modifier.condition is None):raise RulesViolation('Invalid entry modifier')
        if modifier.condition is not None:condition(modifier.condition)
        if modifier.selector is not None:
            selector(modifier.selector)
            if modifier.selector.zone!=Zone.BATTLEFIELD:raise RulesViolation('Entry orientation selector requires battlefield')
        entry_ids.append(modifier.modifier_id)
    if len(entry_ids)!=len(set(entry_ids)):raise RulesViolation('Duplicate entry modifier ID')
    if not isinstance(program.replacements, tuple):
        raise RulesViolation('Replacements must be an immutable tuple')
    replacement_ids = []
    for replacement in program.replacements:
        if (not isinstance(replacement, ZoneReplacement)
                or type(replacement.replacement_id) is not str or not replacement.replacement_id
                or not isinstance(replacement.destination, Zone)
                or not isinstance(replacement.redirect, Zone)
                or replacement.redirect in {Zone.BATTLEFIELD, Zone.STACK, Zone.OUTSIDE}
                or replacement.from_zone is not None and not isinstance(replacement.from_zone, Zone)
                or not strings(replacement.types) or replacement.relation not in {'any', 'owned', 'controlled'}
                or replacement.subject not in {'any', 'self'} or type(replacement.optional) is not bool):
            raise RulesViolation('Unsupported or malformed zone replacement')
        replacement_ids.append(replacement.replacement_id)
    if len(replacement_ids) != len(set(replacement_ids)):
        raise RulesViolation('Duplicate replacement ID')
    ids = []
    for ability in program.abilities:
        if (not isinstance(ability, AbilityProgram) or not isinstance(ability.event, EventPattern)
                or type(ability.ability_id) is not str or not ability.ability_id):
            raise RulesViolation('Invalid ability')
        if ability.source_must_remain is not None and not isinstance(ability.source_must_remain, Zone):
            raise RulesViolation('Invalid intervening source condition')
        if ability.intervening_if is not None:
            condition(ability.intervening_if)
        if ability.occurrence_condition is not None:
            condition(ability.occurrence_condition)
        if type(ability.optional_once_per_turn) is not bool:raise RulesViolation('Invalid optional use limit')
        if ability.optional_once_per_turn and (ability.trigger_limit is not None or not isinstance(ability.effects,tuple)
                or len(ability.effects)!=1 or not isinstance(ability.effects[0],May) or ability.effects[0].otherwise):
            raise RulesViolation('Optional turn limit requires one root May without a fallback or trigger limit')
        event = ability.event
        characteristic_ranges(event.characteristics)
        selector(Selector(Zone.BATTLEFIELD,counters=event.counters))
        if event.counters and event.kind!='zone_changed':raise RulesViolation('Counter predicates require zone events')
        if (not strings(event.any_types) or type(event.exclude_source) is not bool
                or (event.any_types or event.exclude_source) and event.kind!='zone_changed'
                or event.exclude_source and event.subject=='self'):
            raise RulesViolation('Invalid zone-event type union or source exclusion')
        if event.characteristics and event.kind!='zone_changed':
            raise RulesViolation('Characteristic event filters require zone events')
        if (event.kind not in {'zone_changed', 'step_began', 'spell_cast', 'ability_activated', 'creature_attacks', 'creature_blocks', 'becomes_blocked', 'damage_dealt', 'damage_received', 'life_gained', 'card_drawn', 'library_searched', 'library_shuffled', 'scried','surveilled','counters_added','becomes_tapped'} or event.subject not in {'any', 'self', 'attached'}
                or not strings(event.types) or type(event.controller_only) is not bool
                or any(z is not None and not isinstance(z, Zone) for z in (event.from_zone, event.to_zone))):
            raise RulesViolation('Unsupported trigger event')
        if event.subject=='attached' and (event.kind!='zone_changed' or event.from_zone!=Zone.BATTLEFIELD):
            raise RulesViolation('Attached-object events require battlefield departure')
        if (ability.trigger_limit is not None and (type(ability.trigger_limit) is not int or ability.trigger_limit!=1 or event.kind!='counters_added' or event.subject!='self')):
            raise RulesViolation('Only self counter-event once-per-turn limits are currently supported')
        if (event.counter_kind is not None and (event.kind!='counters_added' or type(event.counter_kind) is not str or not event.counter_kind)
                or event.recipient_relation not in {'any','controlled','opponent_controlled'}
                or event.kind not in {'counters_added','zone_changed'}|ACTOR_EVENTS and event.recipient_relation!='any'
                or event.controller_only and event.recipient_relation=='opponent_controlled'):
            raise RulesViolation('Invalid counter event filters')
        if event.kind in {'life_gained','card_drawn','library_searched','library_shuffled', 'scried','surveilled'} and (event.subject!='any' or event.types or event.from_zone is not None or event.to_zone is not None or event.step is not None):
            raise RulesViolation('Player events cannot use object or step filters')
        if event.kind == 'step_began':
            if event.step not in {'upkeep','draw','precombat_main','begin_combat','declare_attackers','declare_blockers','first_strike_damage','combat_damage','end_combat','postcombat_main','end_step','cleanup'} or event.from_zone is not None or event.to_zone is not None or event.subject != 'any' or event.types:
                raise RulesViolation('Unsupported step pattern')
        elif event.kind in {'spell_cast', 'ability_activated', 'creature_attacks', 'creature_blocks', 'becomes_blocked', 'damage_dealt', 'damage_received', 'life_gained', 'card_drawn', 'library_searched', 'library_shuffled', 'scried','surveilled','counters_added','becomes_tapped'} and (event.step is not None or event.from_zone is not None or event.to_zone is not None):
            raise RulesViolation('Announcement event cannot specify zones or step')
        elif event.step is not None:
            raise RulesViolation('Zone event cannot specify a step')
        if ability.targets is not None:
            target(ability.targets,allow_groups=True)
        bindings=({'source','target'} if ability.targets is not None else {'source'})|({'event_subject'} if event.kind in {'zone_changed','becomes_tapped'} else set())
        if ability.targets is not None:bindings.update('target:'+group.group_id for group in ability.targets.groups)
        if event.kind=='zone_changed' and event.subject=='self' and event.from_zone==Zone.BATTLEFIELD and event.to_zone in {Zone.STACK,Zone.GRAVEYARD,Zone.EXILE,Zone.COMMAND}:
            bindings.add('source_successor')
        if event.subject=='attached' and program.enchant is not None:bindings.add('aura_successor')
        values={'event_amount'} if event.kind in {'life_gained','counters_added','damage_received'} else {'event_x'} if event.kind=='spell_cast' else {'event_controllers'} if event.kind=='zone_changed' else {'defending_player'} if event.kind=='creature_attacks' else frozenset()
        if event.kind in ACTOR_EVENTS:values=values|{'event_controllers'}
        if event.kind=='zone_changed' and event.to_zone==Zone.BATTLEFIELD:values=values|{'event_x'}
        effects(ability.effects,bindings,available_values=values)
        target_effects(ability.effects,ability.targets)
        ids.append(ability.ability_id)
    if len(ids) != len(set(ids)):
        raise RulesViolation('Duplicate ability ID')
    if program.enchant is not None:
        selector(program.enchant)
        if 'Enchantment' not in program.types:
            raise RulesViolation('Aura requires an enchantment definition')
    if program.characteristic_pt is not None:
        if not isinstance(program.characteristic_pt,CountObjects) or 'Creature' not in program.types:raise RulesViolation('Invalid characteristic P/T definition')
        quantity(program.characteristic_pt)
        if any(bound.statistic!='mana_value' for bound in program.characteristic_pt.selector.characteristics):raise RulesViolation('Characteristic P/T count cannot depend on P/T')
    if (not strings(program.entry_copy_add_types) or len(set(program.entry_copy_add_types))!=len(program.entry_copy_add_types)
            or any(t not in {'Artifact','Battle','Creature','Enchantment','Instant','Kindred','Land','Planeswalker','Sorcery'} for t in program.entry_copy_add_types)
            or program.entry_copy_add_types and program.entry_copy is None):raise RulesViolation('Invalid entry copy type exception')
    if type(program.entry_copy_tapped) is not bool or program.entry_copy_tapped and program.entry_copy is None:raise RulesViolation('Tapped entry copy requires a copy selector')
    if program.entry_copy is not None:
        selector(program.entry_copy)
    if program.spell_targets is not None:
        target(program.spell_targets,bool(program.cast and program.cast.cost.mana.x_symbols))
    effects(program.spell_effects, {'source', 'target'} if program.spell_targets is not None else {'source'},bool(program.cast and program.cast.cost.mana.x_symbols))
    target_effects(program.spell_effects,program.spell_targets)
    if program.modal is not None:
        modal=program.modal
        if (not isinstance(modal,ModalSpec) or not isinstance(modal.modes,tuple) or not 1<=len(modal.modes)<=32
                or any(not isinstance(mode,SpellMode) for mode in modal.modes)
                or type(modal.minimum) is not int or type(modal.maximum) is not int
                or not 1<=modal.minimum<=modal.maximum<=len(modal.modes)
                or not {'Instant','Sorcery'}&set(program.types) or program.cast is None
                or program.spell_effects or program.spell_targets is not None):
            raise RulesViolation('Invalid modal spell specification')
        if modal.extra_mode_condition is None:
            if modal.conditional_maximum is not None:raise RulesViolation('Conditional mode maximum requires a condition')
        else:
            condition(modal.extra_mode_condition)
            if type(modal.conditional_maximum) is not int or not modal.maximum<modal.conditional_maximum<=len(modal.modes):
                raise RulesViolation('Invalid conditional mode maximum')
        ids=[]
        for mode in modal.modes:
            if type(mode.mode_id) is not str or not mode.mode_id or len(mode.mode_id)>128:raise RulesViolation('Invalid spell mode identity')
            ids.append(mode.mode_id)
            if mode.targets is not None:target(mode.targets,bool(program.cast.cost.mana.x_symbols))
            effects(mode.effects,{'source','target'} if mode.targets is not None else {'source'},bool(program.cast.cost.mana.x_symbols))
            target_effects(mode.effects,mode.targets)
        if len(ids)!=len(set(ids)):raise RulesViolation('Duplicate spell mode identity')
    if program.enchant is not None and program.spell_targets is not None and program.spell_targets.players is not None:
        raise RulesViolation('Player-enchanting Auras are not supported')
    encode(program)
    return program


def token_programs(program):
    """Direct embedded token definitions; recurse into each through its own validation."""
    def walk(value):
        if isinstance(value,CreateTokens):
            yield value.token
            return
        if isinstance(value,tuple):
            for item in value:yield from walk(item)
        elif hasattr(type(value),'__dataclass_fields__'):
            for field in fields(value):yield from walk(getattr(value,field.name))
    for field in fields(program):yield from walk(getattr(program,field.name))
