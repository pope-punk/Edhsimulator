"""Authorized public egress commits only between frozen pilot decisions."""
from copy import deepcopy
import json
from .rules_state import RulesViolation


def prepare(campaign,state,actor,job,operation,value):
    from .primitive_planning import queue,LONG
    if not {'authorized_ids'}<=set(value) or set(value)-{'authorized_ids','authorization_request'} or type(value['authorized_ids']) is not list:
        raise RulesViolation('Select authorized public messages by ID')
    ids=value['authorized_ids']
    if any(type(key) is not str for key in ids) or len(ids)!=len(set(ids)):
        raise RulesViolation('Message IDs must be distinct strings')
    authorized={m['id']:m for m in job['input']['authorized_messages']}
    if any(key not in authorized for key in ids):raise RulesViolation('Unknown frozen authorization')
    brief=state['actors'][actor]['plans'].get('diplomacy_brief',{})
    current=brief.get('id')==job['input']['brief_id']
    valid=[m for m in authorized.values() if m['expires_turn']>=campaign.kernel.state.turn_number]
    required=job['input']['requires_public_post']
    if required and current and valid and not ids:raise RulesViolation('A strategic review requires an authorized public post')
    if not current:
        campaign.record(actor,'diplomacy_superseded',{'operation':operation,'brief_id':job['input']['brief_id']})
        return
    if required and not valid:
        queue(state,actor,LONG,'renew_expired_diplomacy:'+brief['id']);return
    if 'authorization_request' in value:
        from .primitive_planning import text_field
        request=text_field(value,'authorization_request',600)
        queue(state,actor,LONG,'diplomat_request:'+request)
    if not ids:return
    previous=state.setdefault('public_outbox',{}).get(actor)
    if previous:campaign.record(actor,'diplomacy_superseded',{'operation':previous['operation'],'by':operation})
    state['public_outbox'][actor]={'operation':operation,'brief_id':brief['id'],
        'required':required,'messages':[deepcopy(authorized[key]) for key in ids]}


def flush_state(campaign,state):
    if state['claim'] or state['pending'] or state['paused'] or state['terminal'] or state['blocker']:
        return False
    from .primitive_planning import queue,LONG,DIPLOMAT
    posted=False
    for actor,row in list(state.get('public_outbox',{}).items()):
        seat=state['actors'][actor];brief=seat['plans'].get('diplomacy_brief',{})
        if brief.get('id')!=row['brief_id']:
            campaign.record(actor,'diplomacy_superseded',{'operation':row['operation'],'brief_id':row['brief_id']})
            del state['public_outbox'][actor];continue
        committed=0
        for authorization in row['messages']:
            if authorization['expires_turn']<campaign.kernel.state.turn_number:continue
            normalized=' '.join(authorization['text'].split())
            if campaign.store.connection.execute('SELECT 1 FROM host_messages WHERE actor=? AND text=?',(actor,normalized)).fetchone():
                continue
            message={'id':row['operation']+':'+authorization['id'],'actor':actor,'text':authorization['text'],
                     'turn':campaign.kernel.state.turn_number,'brief_id':row['brief_id'],
                     'authorization_id':authorization['id'],'rules_commit':campaign.store.committed_head(),
                     'to':authorization.get('to',[]),'reply_to':authorization.get('reply_to')}
            campaign.store.connection.execute('INSERT INTO host_messages VALUES (?,?,?,?)',
                (message['id'],actor,normalized,json.dumps(message)))
            state['messages']=(state['messages']+[message])[-24:]
            for recipient in state['actors']:campaign.record(recipient,'message',message)
            # Generic talk and replies cannot create recursive inference chains.
            if not message['reply_to']:
                for recipient in message['to']:
                    queue(state,recipient,DIPLOMAT,'incoming:'+message['id'])
            committed+=1;posted=True
        if row['required'] and not committed:
            queue(state,actor,LONG,'renew_unposted_diplomacy:'+row['operation'])
        campaign.record(actor,'diplomacy_delivery',{'operation':row['operation'],'posted':committed,
                                                   'rules_commit':campaign.store.committed_head()})
        del state['public_outbox'][actor]
    if posted:
        for seat in state['actors'].values():seat['approved']=None
    return posted


def flush(campaign):
    if not campaign.state().get('public_outbox'):return False
    with campaign.transaction() as state:return flush_state(campaign,state)
