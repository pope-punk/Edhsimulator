"""Serializable, actor-bound choices shared by experimental interpreters."""
from dataclasses import dataclass, asdict
from collections import Counter
from .rules_state import ObjectRef, RulesViolation


@dataclass(frozen=True)
class Option:
    key:str
    label:str
    ref:ObjectRef|None=None
    player:str|None=None
    group:str|None=None

    def to_json(self):return {**asdict(self),'ref':self.ref.to_json() if self.ref else None}


@dataclass(frozen=True)
class ChoiceRequest:
    request_id:str
    actor:str
    kind:str
    prompt:str
    options:tuple[Option,...]
    minimum:int
    maximum:int
    ordered:bool
    one_per_group:bool
    revision:str
    group_bounds:tuple[tuple[str,int,int],...]=()

    def __post_init__(self):
        if not isinstance(self.group_bounds,tuple):raise RulesViolation('Group bounds must be immutable')
        names=set()
        for row in self.group_bounds:
            if (not isinstance(row,tuple) or len(row)!=3 or type(row[0]) is not str or not row[0]
                    or row[0] in names or any(type(n) is not int for n in row[1:]) or not 0<=row[1]<=row[2]):
                raise RulesViolation('Invalid group bounds')
            names.add(row[0])
        if self.group_bounds:
            if type(self.minimum) is not int or type(self.maximum) is not int or not 0<=self.minimum<=self.maximum:raise RulesViolation('Invalid global bounds')
            if self.one_per_group:raise RulesViolation('Use one group constraint representation')
            if any(type(option.group) is not str or option.group not in names for option in self.options):raise RulesViolation('Option has no declared group')
            counts=Counter(option.group for option in self.options)
            if any(counts[name]<low for name,low,high in self.group_bounds):raise RulesViolation('Required group has insufficient options')
            low=sum(row[1] for row in self.group_bounds)
            high=sum(min(counts[name],maximum) for name,minimum,maximum in self.group_bounds)
            if max(self.minimum,low)>min(self.maximum,high):raise RulesViolation('Global and group bounds cannot be satisfied')

    def validate(self,actor,indexes):
        if actor!=self.actor:raise RulesViolation('Choice belongs to another player')
        if not isinstance(indexes,(list,tuple)) or any(type(i) is not int for i in indexes):raise RulesViolation('Choice must be integer indexes')
        if len(set(indexes))!=len(indexes) or any(not 0<=i<len(self.options) for i in indexes):raise RulesViolation('Duplicate or unavailable choice')
        if not self.minimum<=len(indexes)<=self.maximum:raise RulesViolation('Choice count is outside bounds')
        groups=[self.options[i].group for i in indexes]
        if self.one_per_group and len(set(groups))!=len(groups):raise RulesViolation('More than one choice in a group')
        counts=Counter(groups) if self.group_bounds else {}
        for name,minimum,maximum in self.group_bounds:
            count=counts[name]
            if not minimum<=count<=maximum:raise RulesViolation('Choice count is outside group bounds')
        return tuple(indexes)

    def to_json(self):return {**asdict(self),'options':[option.to_json() for option in self.options],
        'group_bounds':[list(row) for row in self.group_bounds]}

    @classmethod
    def from_json(cls,value):
        value=dict(value);value['options']=tuple(Option(**{**o,'ref':ObjectRef.from_json(o['ref']) if o['ref'] else None}) for o in value['options'])
        value['group_bounds']=tuple(tuple(row) for row in value.get('group_bounds',()))
        return cls(**value)


@dataclass(frozen=True)
class PriorityBoundary:
    actor:str
    stack:tuple[str,...]  # top first




def choice_capacity(options, one_per_group=False, group_bounds=()):
    if group_bounds:
        counts=Counter(option.group for option in options)
        return sum(min(maximum,counts[name]) for name,minimum,maximum in group_bounds)
    return len({option.group for option in options}) if one_per_group else len(options)
