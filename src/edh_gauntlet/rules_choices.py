"""Serializable, actor-bound choices shared by experimental interpreters."""
from dataclasses import dataclass, asdict
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

    def validate(self,actor,indexes):
        if actor!=self.actor:raise RulesViolation('Choice belongs to another player')
        if not isinstance(indexes,(list,tuple)) or any(type(i) is not int for i in indexes):raise RulesViolation('Choice must be integer indexes')
        if len(set(indexes))!=len(indexes) or any(not 0<=i<len(self.options) for i in indexes):raise RulesViolation('Duplicate or unavailable choice')
        if not self.minimum<=len(indexes)<=self.maximum:raise RulesViolation('Choice count is outside bounds')
        groups=[self.options[i].group for i in indexes]
        if self.one_per_group and len(set(groups))!=len(groups):raise RulesViolation('More than one choice in a group')
        return tuple(indexes)

    def to_json(self):return {**asdict(self),'options':[option.to_json() for option in self.options]}

    @classmethod
    def from_json(cls,value):
        value=dict(value);value['options']=tuple(Option(**{**o,'ref':ObjectRef.from_json(o['ref']) if o['ref'] else None}) for o in value['options'])
        return cls(**value)


@dataclass(frozen=True)
class PriorityBoundary:
    actor:str
    stack:tuple[str,...]  # top first




def choice_capacity(options, one_per_group=False):
    return len({option.group for option in options}) if one_per_group else len(options)
