"""Offline human-oriented pilot document, not an engine-state serialization."""
from collections import defaultdict
from copy import deepcopy
import json
from sparse_packet import DEFAULTS,is_object


def compact(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'))


def type_heading(types):
    order={'Kindred':0,'Tribal':0,'Artifact':1,'Enchantment':2,'Planeswalker':3,'Battle':4,'Creature':5,'Land':6}
    names=sorted(set(types),key=lambda x:(order.get(x,7),x))
    if not names:return 'Other cards'
    plurals={'Creature':'Creatures','Land':'Lands','Artifact':'Artifacts','Enchantment':'Enchantments',
             'Planeswalker':'Planeswalkers','Instant':'Instants','Sorcery':'Sorceries','Battle':'Battles'}
    # Composite headings keep all card types, including artifact creatures.
    return ' '.join(names[:-1]+[plurals.get(names[-1],names[-1])])


def groups(objects,level=3):
    grouped=defaultdict(list)
    for index,obj in enumerate(objects):
        key=(obj.get('controller',obj.get('owner','Unknown seat')),obj['zone'],tuple(obj['types']))
        grouped[key].append((index,obj))
    result=[]
    for (controller,zone,types),rows in grouped.items():
        label=zone.replace('_',' ')
        result.append('#'*level+f" {controller}’s {label} — {type_heading(types)}")
        for index,obj in rows:
            details=[]
            for k,v in obj.items():
                if k in ('zone','controller','types','name','ref','definition_id'):continue
                if k=='face' and v=='front':continue
                if k=='owner' and v==controller:continue
                if k in DEFAULTS and type(v) is type(DEFAULTS[k]) and v==DEFAULTS[k]:continue
                if k in ('commander','token','tapped','phased') and v is True:details.append(k)
                else:details.append(k.replace('_',' ')+': '+(v if isinstance(v,str) else compact(v)))
            # The original position makes regrouping unambiguous for ordered zones.
            position=f' [position {index+1}]' if zone!='battlefield' else ''
            result.append(f"- {obj['name']}{position} — "+('; '.join(details) if details else 'No additional state.'))
            result.append('  Reference: '+compact(obj['ref']))
    return '\n'.join(result)


def render_value(value,level=3):
    if is_object(value):return groups([value],level)
    if isinstance(value,list) and value and all(is_object(v) for v in value):return groups(value,level)
    # Walk containers containing snapshots; never leave an internal object dump
    # hidden inside an inspection result or a board delta replacement.
    def has_objects(v):
        if is_object(v):return True
        if isinstance(v,dict):return any(has_objects(x) for x in v.values())
        if isinstance(v,list):return any(has_objects(x) for x in v)
        return False
    if has_objects(value):
        if isinstance(value,dict):return '\n'.join('#'*level+' '+k.replace('_',' ')+'\n'+render_value(v,min(level+1,6)) for k,v in value.items())
        return '\n'.join(f'Item {i+1}:\n'+render_value(v,level) for i,v in enumerate(value))
    return compact(value)


def board(value,title):
    result=['## '+title]
    if value.get('encoding')=='primitive_board_delta_v1':
        result.append('Differences from the named current-board baseline. Apply the listed changes to reconstruct the previous view; unchanged information is inherited.')
        result.append('Baseline: '+value['base_id'])
        for change in value['changes']:
            operation,path,*values=change
            result.append('### '+operation.capitalize()+': '+' / '.join(map(str,path)))
            if values:result.append(render_value(values[0],4))
        return '\n'.join(result)
    copied=deepcopy(value)
    turn=copied.pop('turn',{})
    result.append(f"Turn {turn.get('number','?')}; active seat: {turn.get('active','?')}; phase: {turn.get('phase') or 'opening/setup'}.")
    rest={k:v for k,v in turn.items() if k not in ('number','active','phase')}
    if rest:result.append('Turn details: '+compact(rest))
    zones=copied.pop('zones',{})
    for zone,seats in zones.items():
        for seat,objects in seats.items():
            if objects:result.append(groups(objects))
            else:result.append(f'### {seat}’s {zone.replace("_"," ")}\nEmpty.')
    hand=copied.pop('hand',None)
    if hand is not None:
        result.append(groups(hand) if hand else '### Own hand\nEmpty.')
    for key,v in copied.items():
        result.append('### '+key.replace('_',' ').capitalize())
        result.append(render_value(v,4))
    return '\n\n'.join(result)


def render(packet):
    lines=['# Pilot working document',
           'Object headings specify controller, game zone, and the complete card-type combination. Cards inherit these facts; owner is shown only when different. For zones where order can matter, a position preserves the original list order. Battlefield layout is reorganized for reading; exact object references identify each permanent. References remain exact engine references for tool submissions.',
           'Omitted object state means: not tapped/phased/token/commander; zero damage; no counters or attachment; empty keyword/color/subtype/supertype lists; power/toughness inapplicable unless shown. Explicit zero power/toughness and costs are retained. Omitted face means front. Catalog definition IDs are omitted from card prose because the exact object references identify the cards; the original packet remains available for audit. Subtypes (e.g. Elf) and supertypes (e.g. Legendary) remain when present; they are different from card types.',
           'Current and previous observations are separate. The rules appendix and other non-object fields are retained unchanged for this board-layout experiment. No strategic summary or inference replaces facts.']
    for key,value in packet.items():
        if key in ('board','previous_board') and isinstance(value,dict):lines.append(board(value,'Current board' if key=='board' else 'Previous observed board'))
        else:lines.append('## '+key.replace('_',' ').capitalize()+'\n'+render_value(value))
    return '\n\n'.join(lines)+'\n'
