"""Conservative exact-source snoozes; never infer that an unheld source is unusable."""
from copy import deepcopy
from .rules_state import ObjectRef,RulesViolation
from .rules_adapter import digest


def normalize(value,standard):
    refs=value.get('objects')
    if type(refs) is not list or not refs or len(refs)>200:raise RulesViolation('Supply 1–200 exact source references')
    result=[]
    for raw in refs:
        if type(raw) is not dict or set(raw)!={'card_id','incarnation'}:raise RulesViolation('Object snoozes require exact primitive references')
        ref=ObjectRef.from_json(raw).to_json()
        if ref in result:raise RulesViolation('Duplicate snoozed source')
        result.append(ref)
    directive=standard({**value,'objects':[digest(ref) for ref in result]})
    directive['objects']=result
    return directive


def sources(campaign,actor,packet=None):
    packet=packet or campaign.store.packet(actor)
    cards=list(packet['hand'])+list(packet.get('revealed_hand',[]))
    for owners in packet['zones'].values():
        for rows in owners.values():cards.extend(rows)
    cards.extend(packet.get('revealed_library_tops',{}).values())
    if packet.get('own_library_top'):cards.append(packet['own_library_top'])
    for frame in packet['stack']:
        if not frame.get('source'):continue
        try:obj=campaign.kernel.state.get(ObjectRef.from_json(frame['source']))
        except RulesViolation:continue
        if obj.zone.value=='stack':
            cards.append({'ref':obj.ref.to_json(),'zone':'stack','controller':obj.controller})
    result={}
    for card in cards:
        if card.get('phased'):continue
        ref=ObjectRef.from_json(card['ref'])
        if card['zone']=='battlefield':
            obj=campaign.kernel.state.get(ref)
            if card.get('layout')!='room' and not campaign.kernel.activated_abilities(obj):continue
        obj=campaign.kernel.state.get(ref)
        result[digest(card['ref'])]={'ref':deepcopy(card['ref']),'zone':card['zone'],'controller':card['controller'],
                                   'controlled_since':obj.controlled_since}
    return result


def bind(campaign,actor,directive):
    if directive['mode']!='snooze_objects':return directive
    candidates=sources(campaign,actor);bound=deepcopy(directive);bound['sources']=[]
    for ref in directive['objects']:
        source=candidates.get(digest(ref))
        if source is None:raise RulesViolation('Snoozed source is not a current visible priority candidate')
        bound['sources'].append(source)
    return bound


def retained(campaign,directive):
    held={}
    for row in directive.get('sources',[]):
        try:obj=campaign.kernel.state.get(ObjectRef.from_json(row['ref']))
        except RulesViolation:continue
        if (obj.zone.value==row['zone'] and obj.controller==row['controller']
                and obj.controlled_since==row['controlled_since']):
            held[digest(row['ref'])]=row
    return held


def annotate(campaign,actor,packet,directive):
    if not directive or directive['mode']!='snooze_objects':return
    candidates=sources(campaign,actor,packet);held=retained(campaign,directive)
    # Keep all board facts. Mark source policy in place rather than copying a menu.
    def walk(value):
        if type(value) is dict:
            if 'ref' in value and 'zone' in value and digest(value['ref']) in candidates:
                value['priority_snoozed']=digest(value['ref']) in held
            if type(value.get('source')) is dict and digest(value['source']) in candidates:
                value['priority_snoozed']=digest(value['source']) in held
            for item in list(value.values()):walk(item)
        elif type(value) is list:
            for item in value:walk(item)
    walk(packet)


def covers(campaign,actor,directive):
    candidates=sources(campaign,actor)
    return set(candidates)<=set(retained(campaign,directive))
