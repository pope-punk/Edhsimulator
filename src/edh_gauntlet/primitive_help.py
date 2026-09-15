"""Recoverable, actor-owned technical questions; no gameplay choices or repairs."""
from copy import deepcopy
from .rules_adapter import digest
from .rules_state import RulesViolation
from .primitive_planning import text_field


def request(campaign,actor,claim_id,request_id,value):
    if type(value) is not dict or set(value)!={'intended_action','question'}:
        raise RulesViolation('Help requires intended_action and question')
    for name in value:text_field(value,name,1200)
    with campaign.transaction() as state:
        current=state['claim'];frontier=campaign.next_action()
        if (frontier.get('kind')!='dispatch_pilot' or frontier.get('actor')!=actor or
                not current or current['actor']!=actor or current['claim_id']!=claim_id or
                current['revision']!=campaign.kernel.revision or state['pending']):
            raise RulesViolation('Help request does not own the current decision')
        help_request={'id':request_id,'actor':actor,'claim_id':claim_id,
                      'revision':current['revision'],'commit':campaign.store.committed_head(),**deepcopy(value)}
        state['help_request']=help_request
        state['paused']={'reason':'pilot_help_requested','commit':help_request['commit']}
        campaign.record(actor,'help_request',help_request)
    campaign.publish_next()
    return {'state':'stop','reason':'pilot_help_requested','request_id':request_id,
            'instruction':'End. Your decision is preserved; a technical answer requires explicit resumption. No action was submitted.'}


def answer(campaign,*,expected,request_id,response):
    """Stopped-prefix operator answer; resume remains a separate explicit action."""
    from .primitive_lifecycle import stopped_prefix
    from .primitive_recovery import verify_exited
    if type(response) is not dict or set(response)!={'answer'}:
        raise RulesViolation('Technical response requires only answer text, never an executable command')
    text_field(response,'answer',2400)
    process=stopped_prefix(campaign,expected)
    if process:
        verify_exited(process['host_identity'])
        verify_exited(process['transport_identity'],session=process.get('transport_session'))
    with campaign.transaction() as state:
        if state['terminal'] or state['blocker'] or state['pending']:
            raise RulesViolation('Technical help cannot bypass a terminal, rules blocker or pending receipt')
        receipts=state.setdefault('help_responses',{})
        receipt=receipts.get(request_id)
        if receipt:
            if receipt['response_sha256']!=digest(response) or receipt['commit']!=expected:
                raise RulesViolation('An accepted technical answer cannot be replaced')
            return deepcopy(receipt)
        help_request=state.get('help_request');current=state['claim']
        if (not help_request or help_request['id']!=request_id or help_request['commit']!=expected or
                not current or current['claim_id']!=help_request['claim_id'] or
                current['actor']!=help_request['actor'] or current['revision']!=help_request['revision']):
            raise RulesViolation('Technical answer does not match the preserved help request')
        current['technical_help']={**deepcopy(help_request),'answer':response['answer'],
            'instruction':'Technical clarification only. You still choose and submit the action. Never replay accepted actions.'}
        receipt={'request_id':request_id,'actor':help_request['actor'],'commit':expected,
                 'response_sha256':digest(response),'answered':True}
        receipts[request_id]=receipt
        campaign.record(help_request['actor'],'help_answer',{'request_id':request_id,**deepcopy(response),'commit':expected})
        state.pop('help_request')
        # Keep a pause until normal explicit lifecycle resumption. Preserve any
        # independent operator pause instead of clearing it with a help answer.
        if state['paused'] and state['paused']['reason']=='pilot_help_requested':
            state['paused']={'reason':'pilot_help_answered','commit':expected}
    campaign.publish_next()
    return deepcopy(receipt)
