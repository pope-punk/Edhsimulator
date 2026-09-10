"""Small, ordered continuous-effect pipeline for the fixed four-deck pod.

This is intentionally a rules primitive rather than a list of card-name queries.
The referee supplies applicable effects; this module orders them by Magic's layer
system, honors explicit dependencies within a layer, and produces one immutable-ish
view consumed by type, ability, combat, targeting, and state-based checks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Iterable, Optional


def read_only_views(function):
    """Reuse derived characteristics only during one non-mutating rules query.

    Nested menu queries share the view. It must never surround resolution,
    payment, or a decision request: those can change game state.
    """
    from functools import wraps
    @wraps(function)
    def wrapped(self,*args,**kwargs):
        owner=not hasattr(self,'_continuous_view_cache')
        source_owner=not hasattr(self,'_query_source_cache')
        if owner:self._continuous_view_cache={}
        if source_owner:self._query_source_cache={}
        try:return function(self,*args,**kwargs)
        finally:
            if source_owner:del self._query_source_cache
            if owner:del self._continuous_view_cache
    return wrapped


class Layer(IntEnum):
    COPY = 10
    CONTROL = 20
    TEXT = 30
    TYPE = 40
    COLOR = 50
    ABILITY = 60
    PT_CHARACTERISTIC = 71
    PT_SET = 72
    PT_MODIFY = 73
    PT_COUNTERS = 74
    PT_SWITCH = 75
    RULE = 80


@dataclass
class ContinuousView:
    uid: str
    name: str
    controller: str
    types: set[str] = field(default_factory=set)
    subtypes: set[str] = field(default_factory=set)
    colors: set[str] = field(default_factory=set)
    abilities: set[str] = field(default_factory=set)
    power: int = 0
    toughness: int = 0
    rules: dict[str, Any] = field(default_factory=dict)
    applied: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ContinuousEffect:
    name: str
    layer: Layer
    apply: Callable[[ContinuousView], None]
    timestamp: int = 0
    depends_on: tuple[str, ...] = ()
    active: Callable[[], bool] = lambda: True


def _dependency_order(rows: list[ContinuousEffect]) -> list[ContinuousEffect]:
    """Stable topological order, falling back to timestamp for dependency cycles."""
    pending=sorted(rows,key=lambda row:(row.timestamp,row.name));ordered=[];done=set()
    while pending:
        ready=[row for row in pending if set(row.depends_on)<=done]
        if not ready:ready=[pending[0]]
        for row in ready:
            pending.remove(row);ordered.append(row);done.add(row.name)
    return ordered


def evaluate(base:ContinuousView,effects:Iterable[ContinuousEffect])->ContinuousView:
    active=[effect for effect in effects if effect.active()]
    for layer in Layer:
        for effect in _dependency_order([row for row in active if row.layer==layer]):
            effect.apply(base);base.applied.append(effect.name)
    return base
