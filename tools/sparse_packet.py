"""Experimental reversible object presentation; not enabled in any live host.

Only recognized object snapshots use defaults. Commands, costs, scalar delta
operations, unknown fields and meaningful zero power/toughness remain verbatim.
Decode this outer layer before existing board-delta/reference decoders.
"""
from copy import deepcopy
from collections import Counter

DEFAULTS = {'commander':False,'token':False,'tapped':False,'phased':False,
            'damage':0,'counters':{},'attached_to':None,'power':None,'toughness':None,
            'keywords':[],'colors':[],'subtypes':[],'supertypes':[]}
META='_sparse_objects_v1'
MARK='_s'


def is_object(value):
    return (isinstance(value,dict) and isinstance(value.get('name'),str)
            and isinstance(value.get('types'),list) and isinstance(value.get('zone'),str)
            and isinstance(value.get('ref'),dict)
            and set(value['ref'])=={'card_id','incarnation'})


def encode(packet):
    if not isinstance(packet,dict) or META in packet:raise ValueError('Expected an unencoded packet object')
    groups={};counts=Counter();objects=0
    def visit(value):
        nonlocal objects
        if isinstance(value,list):return [visit(v) for v in value]
        if not isinstance(value,dict):return deepcopy(value)
        if MARK in value:raise ValueError('Reserved sparse marker already present')
        result={k:visit(v) for k,v in value.items()}
        if not is_object(value):return result
        # Group by original field presence, so absent and explicit-default remain
        # distinguishable after exact reconstruction without per-field bitmaps.
        keys=tuple(k for k in DEFAULTS if k in value)
        omitted=[k for k in keys if type(value[k]) is type(DEFAULTS[k]) and value[k]==DEFAULTS[k]]
        if not omitted:return result
        group=groups.setdefault(keys,len(groups)+1)
        for k in omitted:del result[k];counts[k]+=1
        result[MARK]=group;objects+=1
        return result
    output=visit(packet)
    if groups:
        used={k for group in groups for k in group}
        output[META]={'defaults':{k:deepcopy(v) for k,v in DEFAULTS.items() if k in used},
                     'groups':{str(i):list(keys) for keys,i in groups.items()},
                     'read':'For every object marked _s:N, fill absent fields listed in groups[N] from defaults; keep explicit values, including zero. Remove _s after expansion. Unmarked dictionaries are unchanged. Expand this layer before applying board deltas or checking original hashes. A remove operation in a board delta still removes the original field; it is not an instruction to retain an old value.'}
    return output,{'objects_compacted':objects,'fields_omitted':sum(counts.values()),'omitted_by_field':dict(counts)}


def decode(packet):
    output=deepcopy(packet);meta=output.pop(META,None)
    if meta is None:return output
    def visit(value):
        if isinstance(value,list):return [visit(v) for v in value]
        if not isinstance(value,dict):return value
        result={k:visit(v) for k,v in value.items() if k!=MARK}
        if MARK in value:
            group=meta['groups'][str(value[MARK])]
            for k in group:result.setdefault(k,deepcopy(meta['defaults'][k]))
        return result
    return visit(output)

LOCATION_META='_object_locations_v1'
GROUPS='_object_groups'


def group_locations(packet):
    """Group contiguous object snapshots; never reorder a zone or stack list."""
    if LOCATION_META in packet:raise ValueError('Locations already encoded')
    stats=Counter()
    def visit(value):
        if isinstance(value,list):
            if not value or not all(is_object(row) for row in value):return [visit(v) for v in value]
            groups=[]
            for obj in value:
                # Runs preserve exact list order even for mixed-controller lists.
                location={k:obj[k] for k in ('zone','controller') if isinstance(obj.get(k),str)}
                if not groups or groups[-1]['location']!=location:
                    groups.append({'location':location,'objects':[]})
                groups[-1]['objects'].append(visit(obj))
            for group in groups:
                location=group['location'];objects=group['objects']
                owners=Counter(o['owner'] for o in objects if isinstance(o.get('owner'),str))
                if owners and sum(owners.values())==len(objects):location['owner']=owners.most_common(1)[0][0]
                for obj in objects:
                    for k,v in location.items():
                        if k in obj and obj[k]==v:del obj[k];stats[k]+=1
            stats['groups']+=len(groups)
            return {GROUPS:groups}
        if isinstance(value,dict):
            if GROUPS in value:raise ValueError('Reserved location marker already present')
            return {k:visit(v) for k,v in value.items()}
        return deepcopy(value)
    result=visit(packet)
    result[LOCATION_META]={'read':'An _object_groups container replaces an object list. Each group gives shared location (zone, controller, owner) followed by objects. Missing location fields inherit from that group; explicit object fields override them. Expand groups in listed order, concatenate their objects, then decode _s defaults. Original object identities and list order are unchanged.'}
    return result,dict(stats)


def ungroup_locations(packet):
    result=deepcopy(packet);meta=result.pop(LOCATION_META,None)
    if meta is None:return result
    def visit(value):
        if isinstance(value,list):return [visit(v) for v in value]
        if not isinstance(value,dict):return value
        if set(value)=={GROUPS}:
            return [{**deepcopy(group['location']),**visit(obj)} for group in value[GROUPS] for obj in group['objects']]
        return {k:visit(v) for k,v in value.items()}
    return visit(result)
