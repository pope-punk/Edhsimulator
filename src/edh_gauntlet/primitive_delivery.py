"""Lossless primitive-seat presentation, scoped to one physical conversation."""
from copy import deepcopy
import json
from .rules_adapter import digest
from .primitive_journal import delta,apply
from .communications import prepare as legacy_prepare


def size(value):return len(json.dumps(value,ensure_ascii=False,separators=(',',':')))


def board_packet(board,base,base_id):
    if base is None:return deepcopy(board)
    encoded={'encoding':'primitive_board_delta_v1','base_id':base_id,'board_id':digest(board),
             'changes':delta(base,board),
             'read':'Copy the named base board; apply ordered [set,path,value] or [remove,path] operations. Paths are arrays of exact object keys; list values replace whole lists. Unlisted fields remain unchanged.'}
    return encoded if size(encoded)<size(board) else deepcopy(board)


def prepare(packet,role,previous=None,*,schema_available=True):
    previous=previous or {};identity=[packet.get('game'),packet.get('actor'),role]
    if previous.get('primitive_identity')!=identity:previous={}
    if role!='decider' or packet.get('context_handling')!=1:
        value,state=legacy_prepare(packet,role,previous.get('presentation'),schema_available=schema_available)
        return value,{'primitive_identity':identity,'presentation':state}
    result=deepcopy(packet);board=packet.get('board')
    state={'primitive_identity':identity}
    if isinstance(board,dict):
        current_id=digest(board)
        result['board']=board_packet(board,previous.get('board'),previous.get('board_id'))
        result['board_id']=current_id
        old=packet.get('previous_board')
        if isinstance(old,dict):result['previous_board']=board_packet(old,board,current_id)
        state.update(board=deepcopy(board),board_id=current_id)
    facts=result.get('action_facts')
    if isinstance(facts,dict):
        known=set(previous.get('rules_ids',[]));rules=facts.get('rules',{})
        facts['rules']={key:value for key,value in rules.items() if key not in known}
        facts['retained_rule_ids']=[key for key in rules if key in known]
        facts['format']='Objects list current source references. Resolve rules_id in rules or the retained rules with that exact ID from this physical conversation. Changed rules receive new IDs. A new conversation receives every current definition.'
        state['rules_ids']=sorted(known|set(rules))
    for field in ('messages','private_diplomacy'):
        records=packet.get(field)
        if isinstance(records,list):
            known=set(previous.get(field+'_ids',[]));ids=[digest(row) for row in records]
            fresh={key:row for key,row in zip(ids,records) if key not in known}
            result[field]={'encoding':'primitive_records_v1','ids':ids,'new':fresh,
                          'read':'Ordered current IDs reference records in new or previously delivered in this same physical conversation.'}
            state[field+'_ids']=sorted(known|set(ids))
    return result,state


def expand(packet,previous=None):
    """Reference decoder for losslessness tests and offline tooling."""
    previous=previous or {};result=deepcopy(packet)
    def board(value,bases):
        if not isinstance(value,dict) or value.get('encoding')!='primitive_board_delta_v1':return deepcopy(value)
        base=bases.get(value['base_id'])
        if base is None or digest(base)!=value['base_id']:raise ValueError('Missing or changed board baseline')
        expanded=apply(deepcopy(base),value['changes'])
        if digest(expanded)!=value['board_id']:raise ValueError('Board delta checksum mismatch')
        return expanded
    bases=deepcopy(previous.get('boards',{}));current=board(result.get('board'),bases)
    if current is not None:bases[digest(current)]=current;result['board']=current
    if isinstance(result.get('previous_board'),dict):result['previous_board']=board(result['previous_board'],bases)
    rules={**previous.get('rules',{}),**result.get('action_facts',{}).get('rules',{})}
    facts=result.get('action_facts')
    if facts is not None:
        for key in facts.get('retained_rule_ids',[]):
            if key not in rules:raise ValueError('Missing retained rule')
        facts['rules']={key:rules[key] for key in set(facts.get('rules',{}))|set(facts.pop('retained_rule_ids',[]))}
    retained={}
    for field in ('messages','private_diplomacy'):
        records=dict(previous.get(field,{}));encoded=result.get(field)
        if isinstance(encoded,dict) and encoded.get('encoding')=='primitive_records_v1':
            records.update(encoded['new'])
            try:result[field]=[records[key] for key in encoded['ids']]
            except KeyError as exc:raise ValueError('Missing retained record') from exc
        retained[field]=records
    result.pop('board_id',None)
    return result,{'boards':bases,'rules':rules,**retained}
