"""Load authored primitive programs only when their reviewed catalog facts match.

A reviewed program is not a production certificate. Admission must also establish
all required runtime semantics and host/replay compatibility for the whole pod.
"""
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from .catalog import load_catalog
from .paths import PROJECT_ROOT
from .rules_program import decode, validate
from .rules_state import RulesViolation


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def source_facts(card):
    return {'card_id':card.card_id,'name':card.name,'color_identity':card.color_identity,
        'faces':[{'face_id':face.face_id,'oracle_text':face.oracle_text,'type_line':face.type_line,
            'mana_cost':face.mana_cost,'power':face.power,'toughness':face.toughness,
            'loyalty':face.loyalty,'loyalty_variable':face.loyalty_variable,'colors':face.colors} for face in card.faces]}


def load_reviewed(root=PROJECT_ROOT):
    root=Path(root)
    value=json.loads((root/'data/rules/primitive_cards.json').read_text())
    if value.get('schema')!=1:raise RulesViolation('Unsupported reviewed program bundle')
    catalog={card.card_id:card for card in load_catalog(root/'data/catalog/cards.json')}
    result={};identities=set()
    for row in value['cards']:
        key=row['card_id'];card=catalog.get(key)
        if key in result or card is None:raise RulesViolation('Duplicate or unknown reviewed card')
        if row.get('source_facts_sha256')!=digest(source_facts(card)):
            raise RulesViolation('Reviewed source facts changed: '+key)
        if row.get('scope')!='all_printed_faces' or not row.get('review_basis'):
            raise RulesViolation('Program needs an explicit reviewed scope and basis')
        program=validate(decode(row['program']))
        if len(card.faces)!=1 or program.name!=card.name or program.definition_id in identities:
            raise RulesViolation('Reviewed program does not match a unique single-face card')
        face=card.faces[0]
        for field in ('types','subtypes','supertypes','colors'):
            if set(getattr(program,field))!=set(getattr(face,field)):
                raise RulesViolation('Printed characteristic mismatch: '+key+' '+field)
        for field in ('mana_value','power','toughness'):
            if getattr(program,field)!=getattr(face,field):
                raise RulesViolation('Printed characteristic mismatch: '+key+' '+field)
        if 'Instant' in face.types and (program.cast is None or program.cast.timing!='instant'):
            raise RulesViolation('Printed instant requires instant casting timing: '+key)
        if 'Land' not in face.types and face.mana_cost and program.cast is None:
            raise RulesViolation('Missing printed casting cost: '+key)
        if program.cast:
            if not face.mana_cost:raise RulesViolation('Printed casting cost absent: '+key)
            symbols=re.findall(r'\{([^}]+)\}',face.mana_cost);mana=program.cast.cost.mana
            printed=(sum(int(x) for x in symbols if x.isdigit()),Counter(x for x in symbols if not x.isdigit() and x!='X'),symbols.count('X'))
            if (mana.generic,Counter(mana.symbols),mana.x_symbols)!=printed:
                raise RulesViolation('Printed casting cost mismatch: '+key)
        identities.add(program.definition_id);result[key]={'program':program,'review':row}
    return result


def deck_coverage(root=PROJECT_ROOT):
    root=Path(root);reviewed=load_reviewed(root)
    catalog={card.name:card for card in load_catalog(root/'data/catalog/cards.json')}
    decks=json.loads((root/'data/decks/pod_decklists.json').read_text())
    result=[]
    for deck,rows in decks.items():
        entries=[]
        for name,quantity in rows:
            card=catalog.get(name)
            if card is None:raise RulesViolation('Deck card lacks a catalog identity: '+name)
            program=reviewed.get(card.card_id)
            entries.append({'card_id':card.card_id,'name':name,'quantity':quantity,
                'source_facts_sha256':digest(source_facts(card)),
                'program_definition':program['program'].definition_id if program else None,
                'status':'program_authored' if program else 'unmapped',
                'production_certified':False,
                'text_units':[{'face_id':face.face_id,'index':index,'text':text,
                    'sha256':hashlib.sha256(text.encode()).hexdigest()}
                    for face in card.faces for index,text in enumerate(face.oracle_text.splitlines()) if text.strip()]})
        result.append({'deck':deck,'cards':sum(row['quantity'] for row in entries),
            'authored_copies':sum(row['quantity'] for row in entries if row['program_definition']),
            'unmapped_copies':sum(row['quantity'] for row in entries if not row['program_definition']),
            'entries':entries})
    return {'schema':1,'scope':'Exact fixed-pod program coverage; text units are evidence, not an automatically inferred clause count',
        'decks_sha256':hashlib.sha256((root/'data/decks/pod_decklists.json').read_bytes()).hexdigest(),
        'authored_unique_cards':len(reviewed),'production_ready':False,'decks':result}
