"""Inspection against frozen actor observations, never a planner's live frontier."""
from copy import deepcopy
import json
from .catalog import load_catalog
from .rules_adapter import digest
from .rules_state import RulesViolation


def decision_records(rows):
    """Passes remain in the replay audit, outside model-received decision logs."""
    return [row for row in rows if not (row.get('kind')=='rationale' and
            row.get('value',{}).get('command',{}).get('kind')=='pass')]


def select(value,path='',offset=None,limit=None):
    if type(path) is not str or path and not path.startswith('/'):
        raise RulesViolation('Inspection path must be a JSON pointer')
    try:
        for part in path.split('/')[1:] if path else ():
            part=part.replace('~1','/').replace('~0','~')
            if type(value) is list:
                if not part.isdecimal():raise ValueError()
                value=value[int(part)]
            else:value=value[part]
    except (KeyError,IndexError,TypeError,ValueError):raise RulesViolation('Path is absent from this frozen inspection') from None
    if offset is not None or limit is not None:
        if type(value) is not list or type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=32:
            raise RulesViolation('Array inspection requires nonnegative offset and limit 1..32')
        value={'offset':offset,'total':len(value),'items':value[offset:offset+limit]}
    return value


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
        query=deepcopy(query);path=query.pop('path','');offset=query.pop('offset',None);limit=query.pop('limit',None)
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
        elif kind=='history' and {'kind','after'}<=set(query) and set(query)<={'kind','after','page_size'} and role!='diplomacy':
            if type(query['after']) is not int or query['after']<0:raise RulesViolation('Invalid evidence cursor')
            count=query.get('page_size',8)
            if type(count) is not int or not 1<=count<=32:raise RulesViolation('History page_size must be 1..32')
            rows=campaign.evidence(actor,after=query['after'],through=frozen['evidence_through'],limit=count+1)
            results.append({'records':decision_records(rows[:count]),'next':rows[count-1]['id'] if len(rows)>count else None})
        elif kind=='decision' and set(query)=={'kind'}:
            results.append(deepcopy(frozen['board']['decision']))
        elif kind=='state' and set(query)=={'kind'}:results.append(deepcopy(frozen['board']))
        else:raise RulesViolation('Unsupported inspection for this role')
        value=select(results.pop(),path,offset,limit)
        size=len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode())
        if size>12000//len(queries):
            value={'inspection_too_large':True,'bytes':size,
                'read':'Narrow this same frozen query with path (JSON pointer); arrays support offset and limit 1..32. History supports page_size 1..32. Use kind:decision for current choice IDs.',
                **({'keys':list(value)[:32],'key_count':len(value)} if type(value) is dict else {'items':len(value)} if type(value) is list else {})}
        results.append(value)
    return {'results':results}


def public_input(value):return {k:deepcopy(v) for k,v in value.items() if not k.startswith('_')}
