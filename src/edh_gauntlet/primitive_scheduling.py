"""Pilot-authored planner alarms; deadlines count game boundaries, never time."""
from copy import deepcopy
import json
from .rules_adapter import digest
from .rules_state import RulesViolation
from .referee import parse_pass_on_schedule
from .primitive_actions import phase_group
from .primitive_planning import queue,LONG,SHORT


def normalize(value,actor,players):
    if type(value) is not dict or value.get('mode') not in {'now','schedule','cancel'}:
        raise RulesViolation('Alarm mode must be now, schedule or cancel')
    mode=value['mode'];allowed={'mode'}
    if mode!='cancel':allowed.add('long_term')
    if mode=='schedule':allowed|={'seat','time'}
    if set(value)-allowed or type(value.get('long_term',False)) is not bool:
        raise RulesViolation('Invalid planner alarm fields')
    result={'mode':mode}
    if mode!='cancel':result['long_term']=value.get('long_term',False)
    if mode=='schedule':
        if value.get('seat') not in players:raise RulesViolation('Unknown alarm seat')
        timing=parse_pass_on_schedule(value.get('time'))
        if value['seat']==actor and timing['edge']=='end' and timing['phase']=='end_step':
            raise RulesViolation('Own end step already has mandatory planner maintenance')
        result.update(seat=value['seat'],time=timing)
    return result


def control(campaign,actor,claim_id,control_id,value):
    """A replayed accepted alarm returns its receipt; it cannot arm twice."""
    normalized=normalize(value,actor,campaign.kernel.state.players)
    binding=digest({'claim_id':claim_id,'alarm':normalized})
    key='alarm:'+control_id
    with campaign.transaction() as state:
        receipt=campaign.store.connection.execute(
            'SELECT actor,role,input_sha,receipt FROM host_publications WHERE id=?',(key,)).fetchone()
        if receipt:
            if receipt[:3]!=(actor,'decider',binding):raise RulesViolation('Alarm control identity was reused')
            return json.loads(receipt[3])
        frontier=campaign.next_action();claim=state['claim']
        if (frontier.get('kind')!='dispatch_pilot' or frontier.get('actor')!=actor or
                frontier.get('decision_kind')!='priority' or not claim or
                claim['actor']!=actor or claim['claim_id']!=claim_id or claim['revision']!=campaign.kernel.revision):
            raise RulesViolation('Planner alarm requires the current frozen priority claim')
        seat=state['actors'][actor];seat['alarm']=None
        if normalized['mode']=='now':
            queue(state,actor,LONG if normalized['long_term'] else SHORT,'pilot_alarm:'+key)
        elif normalized['mode']=='schedule':
            seat['alarm']={**normalized,'id':key,'armed_after':len(campaign.kernel.semantic_events),
                           'remaining':normalized['time']['occurrences']}
        result={'accepted':True,'control_id':key,'alarm':deepcopy(seat['alarm'])}
        campaign.record(actor,'planner_alarm',{'claim_id':claim_id,**result})
        campaign.store.connection.execute('INSERT INTO host_publications VALUES (?,?,?,?,?)',
            (key,actor,'decider',binding,json.dumps(result)))
        return result


def advance(state,events):
    previous=state.get('alarm_boundary')
    for event in events:
        if event['kind']!='step_began':continue
        current={'seat':event['active'],'phase':phase_group(event['step'])}
        if current==previous:continue
        boundaries=[('beginning',current)]
        if previous:boundaries.insert(0,('end',previous))
        for actor,seat in state['actors'].items():
            alarm=seat.get('alarm')
            if not alarm or event['index']<=alarm['armed_after']:continue
            timing=alarm['time']
            if any(edge==timing['edge'] and boundary=={'seat':alarm['seat'],'phase':timing['phase']}
                   for edge,boundary in boundaries):
                alarm['remaining']-=1
                if alarm['remaining']==0:
                    queue(state,actor,LONG if alarm['long_term'] else SHORT,'pilot_alarm:'+alarm['id'])
                    seat['alarm']=None
        previous=current
    state['alarm_boundary']=previous


def observe(campaign,state):
    events=campaign.kernel.semantic_events
    advance(state,events[state.get('alarm_event_cursor',0):])
    state['alarm_event_cursor']=len(events)
