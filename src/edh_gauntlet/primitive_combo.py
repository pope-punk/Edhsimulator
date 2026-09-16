"""Planner proof -> pilot choice -> opponent consent -> independent adjudication."""
from copy import deepcopy
from .rules_adapter import digest
from .rules_state import RulesViolation,ObjectRef
from .runtime_store import write
from .combo_adjudication import validate_combo_adjudication_response


def validate_proposal(value):
    if type(value) is not dict or set(value)!={'proposal_text','seat_turn','phase','requires'}:raise RulesViolation('Combo requires proposal_text, seat_turn, phase and requires')
    if type(value['proposal_text']) is not str or not 0<len(value['proposal_text'].strip())<=1200:raise RulesViolation('Combo proof must be 1..1200 characters')
    if type(value['seat_turn']) is not int or value['seat_turn']<1 or value['phase'] not in ('precombat_main','postcombat_main'):raise RulesViolation('Combo timing must name an own main phase')
    if type(value['requires']) is not list or len(value['requires'])>8:raise RulesViolation('At most eight combo object guards')
    for guard in value['requires']:
        if type(guard) is not dict or set(guard)!={'source','zone','controller'} or guard['zone'] not in ('battlefield','graveyard','exile','command','hand'):raise RulesViolation('Combo guards require exact source, zone and controller')
        ObjectRef.from_json(guard['source'])


def offer(campaign,actor,plans=None):
    state=campaign.state();seat=state['actors'][actor];component=(plans or seat['plans']).get('actions',{})
    proposal=component.get('value',{}).get('combo_proposal')
    if not proposal or component.get('id') in seat.get('used_combos',[]):return None
    k=campaign.kernel
    if (k.priority!=actor or k.active!=actor or k.stack or proposal['phase']!=k.phase or proposal['seat_turn']!=seat.get('turns')):return None
    for guard in proposal['requires']:
        try:obj=k.state.get(ObjectRef.from_json(guard['source']))
        except RulesViolation:return None
        if obj.zone.value!=guard['zone'] or obj.controller!=guard['controller']:return None
    return {'proposal_id':component['id'],**deepcopy(proposal)}


def _claim(campaign,state,actor,claim_id):
    claim=state['claim']
    if not claim or claim['actor']!=actor or claim['claim_id']!=claim_id or claim['revision']!=campaign.kernel.revision:raise RulesViolation('Combo input does not own the frozen claim')
    return claim


def propose(campaign,actor,claim_id,proposal_id):
    with campaign.transaction() as state:
        claim=_claim(campaign,state,actor,claim_id)
        frozen=claim.get('combo_offer')
        if state.get('combo') or not frozen or frozen['proposal_id']!=proposal_id or offer(campaign,actor,claim['plans'])!=frozen:raise RulesViolation('Combo offer is absent, stale or already consumed')
        from .primitive_planning import public_board
        request={'proposal_id':digest({'binding':campaign.binding,'component':proposal_id,'commit':campaign.store.committed_head()}),'actor':actor,'proposal_text':frozen['proposal_text'],'commit':campaign.store.committed_head(),'binding':deepcopy(campaign.binding),'public_state':public_board(campaign),'consents':[]}
        state['actors'][actor].setdefault('used_combos',[]).append(proposal_id)
        state['combo']={'request':request,'remaining':[p for p in campaign.kernel.state.live_players if p!=actor]}
        state['claim']=None
        for seat in state['actors'].values():seat['approved']=None;seat['snooze']=None
        campaign.record(actor,'combo_proposed',request)
    campaign.publish_next();return {'accepted':True,'proposal_id':request['proposal_id']}


def consent(campaign,actor,claim_id,accept,rationale):
    if type(accept) is not bool or type(rationale) is not str or not 0<len(rationale.strip())<=300:raise RulesViolation('Consent requires a boolean and bounded rationale')
    with campaign.transaction() as state:
        _claim(campaign,state,actor,claim_id);combo=state.get('combo')
        if not combo or not combo['remaining'] or combo['remaining'][0]!=actor:raise RulesViolation('Not this opponent consent turn')
        row={'pilot':actor,'consent':accept,'rationale':rationale}
        combo['request']['consents'].append(row);combo['remaining'].pop(0);state['claim']=None
        campaign.record(actor,'combo_consent',row)
        if not accept:state.pop('combo');campaign.record(actor,'combo_cancelled',{'reason':'Opponent can interact'})
        elif not combo['remaining']:
            request=combo['request']
            request['consent_standard']='Each YES reports no disruption capable of stopping the demonstrated loop; consent is not a rules ruling.'
            request['adjudicator_task']='Independently verify the concrete demonstrated loop against current public state. Use the legacy closed schema: damage_player, set_life, bounce_permanents. Bounce UIDs use card_id@incarnation. Reject or require demonstration if unproven; never invent a winner.'
            request['request_sha256']=digest(request)
            state['paused']={'reason':'combo_adjudication','commit':campaign.store.committed_head()}
    campaign.publish_next();return {'accepted':True,'consent':accept}


def adjudicate(campaign,response,expected):
    from .primitive_lifecycle import stopped_prefix
    if (campaign.root/'HOST_PAUSED.json').exists():raise RulesViolation('Explicit operator pause blocks combo application')
    state=campaign.state();combo=state.get('combo')
    prior=state.get('combo_receipts',{}).get(response.get('proposal_id'))
    if prior:
        if prior['response_sha256']!=digest(response) or prior['before']!=expected:raise RulesViolation('Conflicting adjudication retry')
        return deepcopy(prior)
    process=stopped_prefix(campaign,expected)
    if process:
        from .primitive_recovery import verify_exited
        verify_exited(process['host_identity']);verify_exited(process['transport_identity'],session=process['transport_session'])
    if not combo or combo['remaining']:raise RulesViolation('No independently adjudicable proposal')
    request=combo['request']
    if request['commit']!=expected:raise RulesViolation('Combo prefix changed')
    checked=validate_combo_adjudication_response(response,expected_proposal_id=request['proposal_id'],expected_request_sha256=request['request_sha256'],known_pilots=campaign.kernel.state.players)
    if checked['verdict']=='approved':
        trial=type(campaign.kernel).restore(campaign.kernel.snapshot(),campaign.kernel._base_definitions.values())
        from .rules_combo import apply
        apply(trial,request['actor'],{'action_id':'combo:'+request['proposal_id'],'response':checked})
    with campaign.transaction() as state:
        state['combo']['response']=checked
        campaign.record(request['actor'],'combo_adjudication',checked)
    if checked['verdict']=='approved':
        command={'kind':'adjudicated_combo','revision':campaign.kernel.revision,'action_id':'combo:'+request['proposal_id'],'response':checked}
        # Same prepared/accepted command transaction as normal rules actions.
        campaign.submit(request['actor'],command['action_id'],command,rationale=checked['public_summary'],control={'combo_complete':request['proposal_id']})
    else:
        with campaign.transaction() as state:complete(state,checked)
        campaign.publish_next()
    if process:
        process['commit']=campaign.store.committed_head()
        write(campaign.root/'host_runtime/process.json',process)
    if not campaign.state()['terminal']:
        with campaign.transaction() as state:state['paused']={'reason':'combo_answered','commit':campaign.store.committed_head()}
        campaign.publish_next()
    return deepcopy(campaign.state()['combo_receipts'][request['proposal_id']])


def complete(state,response):
    state.setdefault('combo_receipts',{})[response['proposal_id']]={'response_sha256':digest(response),'verdict':response['verdict'],'before':deepcopy(state['combo']['request']['commit'])}
    state.pop('combo',None);state['claim']=None
    state['paused']=None
