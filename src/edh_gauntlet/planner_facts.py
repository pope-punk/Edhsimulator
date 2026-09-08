"""Bounded visible-card prefetch using the existing immutable inspection archive.

Frozen inputs store references only. Egress supplies exact unknown definitions;
successful delivery retains them through the ordinary inspection knowledge path.
No ordered library, strategic catalog survey, new wake or new tool round.
"""
from .runtime_store import get
from .planner_memory import size

MAX_REFS=24
MAX_CARDS=6
MAX_CHARS=12000


def references(directory,snapshot,actor):
    own=snapshot['board'].get('players',{}).get(actor,{})
    names=[]
    for zone in ('hand','commander','battlefield'):
        cards=own.get(zone,[])
        if isinstance(cards,(dict,str)):cards=[cards]
        for card in reversed(cards or []):
            name=card.split(':',1)[-1] if isinstance(card,str) else card.get('name')
            if name and name not in names:names.append(name)
    by_name={}
    for key,ref in snapshot.get('catalog',{}).items():
        record=get(directory/'inspection',ref)
        if record.get('name') in names:by_name[record['name']]=(key,ref)
    selected=[by_name[n] for n in names if n in by_name]
    return {'records':dict(selected[:MAX_REFS]),'omitted':max(0,len(selected)-MAX_REFS)}


def prepare(directory,packet,knowledge=None):
    refs=packet.get('visible_rule_refs')
    if not refs:return packet,[]
    known=(knowledge or {}).get('catalog_records',{})
    selected={};omitted=refs['omitted'];retained=0
    for key,ref in refs['records'].items():
        record=get(directory/'inspection',ref)
        if record.get('card_id')!=key:raise ValueError('Frozen card reference identity mismatch')
        if known.get(key)==record:
            retained+=1;continue
        if len(selected)>=MAX_CARDS or size({**selected,key:record})>MAX_CHARS:
            omitted+=1;continue
        selected[key]=record
    result={k:v for k,v in packet.items() if k!='visible_rule_refs'}
    rows=([{'query':'visible-card prefetch','snapshot':packet['snapshot'],
            'result':{'catalog_records':selected}}] if selected else [])
    if rows:
        from .planner_memory import present
        result['visible_card_rules']=present(rows,knowledge or {})
    result['visible_card_rules_scope']={'new_definitions':len(selected),'retained_definitions':retained,
        'omitted_definitions':omitted,'guidance':'Exact rules for visible own cards, not an instruction to play them. Read these and retained definitions before inspecting the same facts. Current zones and legality come from the frozen board. Inspect other cards or unresolved facts normally.'}
    return result,rows
