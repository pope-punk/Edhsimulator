"""Inspection against frozen actor observations, never a planner's live frontier."""
from copy import deepcopy
import json
from .catalog import load_catalog
from .rules_adapter import digest
from .rules_state import RulesViolation


def freeze(campaign,actor,board):
    objects={}
    def collect(value):
        if type(value) is dict:
            if 'name' in value and type(value.get('ref')) is dict:
                try:objects[json.dumps(value['ref'],sort_keys=True)]=campaign.store.inspect(actor,{'kind':'card_rules','source':value['ref']})
                except RulesViolation:pass # Historical stack/LKI references are not live objects.
            for child in value.values():collect(child)
        elif type(value) is list:
            for child in value:collect(child)
    collect(board)
    return objects


def inspect(campaign,actor,role,frozen,queries):
    if type(queries) is not list or not 1<=len(queries)<=8:raise RulesViolation('Batch one to eight inspections')
    catalog=load_catalog(campaign.assets/'data/catalog/cards.json')
    cards={c.name:c for c in catalog};results=[]
    for query in queries:
        if type(query) is not dict:raise RulesViolation('Inspection requires an object')
        kind=query.get('kind')
        if kind=='object' and set(query)=={'kind','source'}:
            value=frozen.get('_knowledge',{}).get(json.dumps(query['source'],sort_keys=True))
            if value is None:raise RulesViolation('Object is not visible in this frozen input')
            results.append(deepcopy(value))
        elif kind=='card' and set(query)=={'kind','name'}:
            card=cards.get(query['name'])
            if card is None:raise RulesViolation('Unknown printed card')
            results.append({'name':card.name,'faces':[{'name':f.name,'oracle_text':f.oracle_text,
                           'mana_cost':f.mana_cost,'type_line':f.type_line} for f in card.faces]})
        elif kind=='deck' and set(query)=={'kind'} and role=='long_term_planner':
            results.append({'cards':[{'name':c.name,'quantity':o.quantity} for c,o in catalog.deck_entries(actor)]})
        elif kind=='history' and set(query)=={'kind','after'} and role!='diplomacy':
            if type(query['after']) is not int or query['after']<0:raise RulesViolation('Invalid evidence cursor')
            rows=campaign.evidence(actor,after=query['after'],through=frozen['evidence_through'],limit=33)
            results.append({'records':rows[:32],'next':rows[31]['id'] if len(rows)>32 else None})
        elif kind=='state' and set(query)=={'kind'}:results.append(deepcopy(frozen['board']))
        else:raise RulesViolation('Unsupported inspection for this role')
    return {'results':results}


def public_input(value):return {k:deepcopy(v) for k,v in value.items() if not k.startswith('_')}
