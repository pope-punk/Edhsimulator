"""Bounded factual dependencies on an actor's frozen board, stored as digests."""
from .rules_adapter import digest
from .rules_state import RulesViolation

ROOTS={'players','zones','hand','revealed_hand','turn','stack','resolving','announcement','combat','outcome'}


def pointer(board,path):
    node=board
    for raw in path.split('/')[1:]:
        key=raw.replace('~1','/').replace('~0','~')
        if type(node) is dict and key in node:node=node[key]
        elif type(node) is list and key.isascii() and key.isdecimal() and str(int(key))==key and int(key)<len(node):node=node[int(key)]
        else:return {'present':False}
    return {'present':True,'value':node}


def freeze(board,paths):
    if type(paths) is not list or len(paths)>24:raise RulesViolation('Declare at most 24 factual dependency paths')
    values={}
    for path in paths:
        if (type(path) is not str or len(path)>200 or not path.startswith('/')
                or path.split('/')[1] not in ROOTS or path in values):
            raise RulesViolation('Dependencies require distinct board fact JSON pointers')
        # JSON Pointer has exactly two escape sequences; do not accept aliases.
        if '~' in path.replace('~1','').replace('~0',''):
            raise RulesViolation('Invalid dependency pointer escape')
        value=pointer(board,path)
        if not value['present']:raise RulesViolation('Dependency is absent from the frozen board')
        values[path]=digest(value)
    return values


def changed(board,values):
    return [path for path,value in values.items() if digest(pointer(board,path))!=value]
