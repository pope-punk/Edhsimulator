"""Bounded authored diplomacy and own-seat holds, never autonomous game choices."""
from copy import deepcopy
import json
from .rules_state import RulesViolation,ObjectRef
from .rules_adapter import digest

SCOPES={'attack','target_permanents'}


def brief(value,actor,players):
    from .primitive_planning import text_field
    if type(value) is not dict or set(value)!={'objective','disclosure_limits','commitment_limits','allowed_recipients','hold_authority'}:
        raise RulesViolation('Diplomatic brief requires objective, disclosure_limits, commitment_limits, allowed_recipients and hold_authority')
    for key in ('objective','disclosure_limits','commitment_limits'):text_field(value,key,900)
    recipients=value['allowed_recipients']
    if type(recipients) is not list or len(set(recipients))!=len(recipients) or any(p not in players or p==actor for p in recipients):
        raise RulesViolation('Brief recipients must be distinct opposing seats')
    authority=value['hold_authority']
    if type(authority) is not dict or set(authority)!={'players','scopes','max_turns'}:
        raise RulesViolation('Hold authority requires players, scopes and max_turns')
    if (type(authority['players']) is not list or any(p not in recipients for p in authority['players'])
            or type(authority['scopes']) is not list or any(s not in SCOPES for s in authority['scopes'])
            or type(authority['max_turns']) is not int or not 0<=authority['max_turns']<=4):
        raise RulesViolation('Invalid delegated hold authority')


def compose(campaign,state,actor,job,operation,value):
    from .primitive_planning import text_field,queue,LONG
    if type(value) is not dict or set(value)-{'messages','holds','release_holds','authorization_request'} or 'messages' not in value:
        raise RulesViolation('Compose messages within the brief; optional holds, release_holds and authorization_request')
    current=state['actors'][actor]['plans'].get('diplomacy_brief',{})
    if current.get('id')!=job['input']['brief_id']:
        campaign.record(actor,'diplomacy_superseded',{'operation':operation,'brief_id':job['input']['brief_id']});return
    bounds=job['input']['brief'];messages=value['messages']
    if type(messages) is not list or len(messages)>4 or job['input']['requires_public_post'] and not messages and 'authorization_request' not in value:
        raise RulesViolation('Publish 1..4 messages for a strategic update; optional requests may select silence')
    ids=set();prepared=[]
    for row in messages:
        if type(row) is not dict or set(row)!={'id','text','to','reply_to','urgent_material_plan_change','private_assessment'}:
            raise RulesViolation('Authored message requires id,text,to,reply_to,urgent_material_plan_change,private_assessment')
        key=text_field(row,'id',80);text_field(row,'text',600)
        if key in ids:raise RulesViolation('Duplicate message ID')
        ids.add(key)
        if campaign.store.connection.execute('SELECT 1 FROM host_messages WHERE actor=? AND text=?',(actor,' '.join(row['text'].split()))).fetchone():raise RulesViolation('Identical public speech was already posted; compose a new message or choose optional silence')
        if type(row['to']) is not list or any(p not in bounds['allowed_recipients'] for p in row['to']):raise RulesViolation('Message recipient exceeds brief')
        if row['reply_to'] is not None:
            parent=campaign.store.connection.execute('SELECT payload FROM host_messages WHERE id=?',(row['reply_to'],)).fetchone()
            if not parent:raise RulesViolation('Reply requires an existing message: copy its exact messages[].id, including the full prefix and suffix; do not use authorization_id or reconstruct an ID')
            parent=json.loads(parent[0])
            if actor not in parent.get('to',[]):raise RulesViolation('Reply only to an addressed message')
            if parent.get('reply_depth',0)>=3:raise RulesViolation('Negotiation reply depth is capped at three')
            depth=parent.get('reply_depth',0)+1
        else:depth=0
        if type(row['urgent_material_plan_change']) is not int or row['urgent_material_plan_change'] not in (0,1):raise RulesViolation('Urgency must be integer 0 or 1')
        assessment=row['private_assessment']
        if type(assessment) is not dict or set(assessment)!={'explanation','recommended_action','truthfulness'}:raise RulesViolation('Include complete private assessment')
        text_field(assessment,'explanation',600);text_field(assessment,'recommended_action',600)
        if assessment['truthfulness'] not in ('truthful','deceptive','uncertain'):raise RulesViolation('Invalid truthfulness assessment')
        prepared.append({**deepcopy(row),'expires_turn':campaign.kernel.state.turn_number+1,'reply_depth':depth})
    holds=value.get('holds',[]);release=value.get('release_holds',[])
    if type(holds) is not list or len(holds)>4 or type(release) is not list or any(type(k) is not str for k in release):raise RulesViolation('Invalid hold changes')
    authority=bounds['hold_authority'];seat=state['actors'][actor]
    seen=set()
    for hold in holds:
        if type(hold) is not dict or set(hold)!={'id','player','scopes','expires_turn','rationale','negotiation_id'}:raise RulesViolation('Hold requires id,player,scopes,expires_turn,rationale,negotiation_id')
        key=text_field(hold,'id',80);text_field(hold,'negotiation_id',80);text_field(hold,'rationale',600)
        if key in seen or key in seat.get('diplomatic_holds',{}):raise RulesViolation('Hold ID already exists')
        seen.add(key)
        if (hold['player'] not in authority['players'] or type(hold['scopes']) is not list or not hold['scopes']
                or any(s not in authority['scopes'] for s in hold['scopes']) or type(hold['expires_turn']) is not int
                or not campaign.kernel.state.turn_number<hold['expires_turn']<=campaign.kernel.state.turn_number+authority['max_turns']):raise RulesViolation('Hold exceeds brief authority or expiry')
        if hold['negotiation_id'] in seat.get('overridden_negotiations',[]):raise RulesViolation('Overridden negotiation cannot automatically reimpose a hold')
    if 'authorization_request' in value:
        request=text_field(value,'authorization_request',600)
        seat.setdefault('brief_change_requests',[]).append({'id':operation,'request':request,'brief_id':current['id']})
        seat['brief_change_requests']=seat['brief_change_requests'][-4:]
        queue(state,actor,LONG,'diplomat_request:'+operation)
    previous=state.setdefault('public_outbox',{}).get(actor)
    if previous:campaign.record(actor,'diplomacy_superseded',{'operation':previous['operation'],'by':operation})
    state['public_outbox'][actor]={'operation':operation,'brief_id':current['id'],
        'required':job['input']['requires_public_post'] and 'authorization_request' not in value,'messages':prepared,'holds':deepcopy(holds),'release_holds':release}


def apply_holds(campaign,state,actor,row):
    seat=state['actors'][actor];seat['diplomatic_holds']=active(campaign,seat);holds=seat['diplomatic_holds']
    for key in row.get('release_holds',[]):holds.pop(key,None)
    for hold in row.get('holds',[]):
        if hold['expires_turn']>campaign.kernel.state.turn_number and hold['negotiation_id'] not in seat.get('overridden_negotiations',[]):
            holds[hold['id']]=deepcopy(hold)
            campaign.record(actor,'diplomatic_hold',hold)


def active(campaign,seat):
    return {k:v for k,v in seat.get('diplomatic_holds',{}).items() if v['expires_turn']>campaign.kernel.state.turn_number}


def conflicts(campaign,actor,command):
    holds=active(campaign,campaign.state()['actors'][actor]);result=[]
    for key,hold in holds.items():
        hit=False
        if 'attack' in hold['scopes'] and command.get('kind')=='attack':
            for attack in command.get('attackers',[]):
                defender=attack.get('defender')
                if type(defender) is dict:
                    defender=campaign.kernel.state.get(ObjectRef.from_json(defender)).controller
                hit|=defender==hold['player']
        if 'target_permanents' in hold['scopes']:
            def targets(value):
                if type(value) is dict:
                    if set(value)=={'card_id','incarnation'}:
                        obj=campaign.kernel.state.get(ObjectRef.from_json(value))
                        return obj.zone.value=='battlefield' and obj.controller==hold['player']
                    return any(targets(v) for v in value.values())
                return type(value) is list and any(targets(v) for v in value)
            hit|=targets(command.get('targets',[]))
        if hit:result.append(key)
    return result


def enforce(campaign,actor,command):
    found=conflicts(campaign,actor,command)
    if found:raise RulesViolation('Diplomatic hold conflict: '+', '.join(found)+'. Honor the hold or call edh_diplomatic_override with an explicit rationale, then submit a fresh choice.')


def override(campaign,actor,claim_id,request_id,ids,rationale):
    from .primitive_planning import queue,LONG,text_field
    text_field({'rationale':rationale},'rationale',600)
    if type(ids) is not list or not ids or any(type(k) is not str for k in ids) or len(set(ids))!=len(ids):raise RulesViolation('Name distinct active hold IDs')
    with campaign.transaction() as state:
        prior=state.setdefault('hold_override_receipts',{}).get(request_id)
        signature=digest({'actor':actor,'claim':claim_id,'ids':ids,'rationale':rationale})
        if prior:
            if prior['signature']!=signature:raise RulesViolation('Override request identity changed')
            return deepcopy(prior['result'])
        claim=state['claim'];seat=state['actors'][actor]
        if state['paused'] or state['terminal'] or state['blocker'] or not claim or claim['actor']!=actor or claim['claim_id']!=claim_id:raise RulesViolation('Override requires the current owned decision')
        holds=active(campaign,seat)
        if any(k not in holds for k in ids):raise RulesViolation('Unknown or expired diplomatic hold')
        negotiations={holds[k]['negotiation_id'] for k in ids}
        for k in ids:seat['diplomatic_holds'].pop(k)
        history=seat.setdefault('overridden_negotiations',[])
        fresh=negotiations-set(history);history.extend(sorted(fresh))
        if fresh:queue(state,actor,LONG,'diplomatic_override:'+digest(sorted(fresh)))
        campaign.record(actor,'diplomatic_override',{'hold_ids':ids,'negotiation_ids':sorted(negotiations),'rationale':rationale})
        result={'accepted':True,'released_hold_ids':ids,'instruction':'Override recorded. Submit your choice for the same decision; no game action was executed.'}
        state['hold_override_receipts'][request_id]={'signature':signature,'result':result}
        return result


def decide_brief(campaign,state,actor,role,job_id,value):
    """Commit authority first so the diplomat need not wait for strategic prose."""
    from .primitive_planning import LONG,DIPLOMAT,queue,text_field
    if role!=LONG or type(value) is not dict or set(value)-{'approved','rationale','brief','update_plan'} or type(value.get('approved')) is not bool:
        raise RulesViolation('Only long-term planner may approve/veto a brief change')
    text_field(value,'rationale',600)
    if type(value.get('update_plan',True)) is not bool:raise RulesViolation('update_plan must be boolean')
    if state['paused'] or state['pending'] or state['terminal'] or state['blocker']:raise RulesViolation('Planning admission is stopped')
    seat=state['actors'][actor];job=seat['jobs'].get(role)
    receipt_id=job_id+':brief_decision'
    prior=campaign.store.connection.execute('SELECT input_sha,receipt FROM host_publications WHERE id=?',(receipt_id,)).fetchone()
    if prior:
        if prior[0]!=digest(value):raise RulesViolation('Accepted brief decision cannot be replaced')
        return json.loads(prior[1])
    if not job or job['id']!=job_id or not job.get('input') or not any(r.startswith('diplomat_request:') for r in job['reasons']):raise RulesViolation('No frozen brief-change request to decide')
    if not value.get('update_plan',True) and not all(r.startswith('diplomat_request:') for r in job['reasons']):raise RulesViolation('Independent strategic work still requires a long-term publication')
    if value['approved']:
        brief(value.get('brief'),actor,state['actors'])
        seat['plans']['diplomacy_brief']={'id':digest({'stage':'diplomacy_brief','value':value['brief']}),'job_id':job_id,'value':deepcopy(value['brief'])}
        queue(state,actor,DIPLOMAT,'brief_approved:'+job_id)
    elif 'brief' in value:raise RulesViolation('A veto retains the existing brief')
    job['brief_decision']=deepcopy(value)
    consumed={r['id'] for r in job['input'].get('brief_change_requests',[])}
    seat['brief_change_requests']=[r for r in seat.get('brief_change_requests',[]) if r['id'] not in consumed]
    campaign.record(actor,'brief_decision',{'job_id':job_id,**deepcopy(value)})
    if not value.get('update_plan',True):
        seat['evidence_cursor'][role]=job['input']['evidence_through']
        queued=job['queued'];del seat['jobs'][role]
        for reason in queued:queue(state,actor,role,reason)
    result={'accepted':True,'approved':value['approved'],'next':'long_term' if value.get('update_plan',True) else None,'instruction':'Authority decision committed; complete strategic assessment. Diplomatically initiated long-term publication does not force another message.'}
    campaign.store.connection.execute('INSERT INTO host_publications VALUES (?,?,?,?,?)',(receipt_id,actor,role,digest(value),json.dumps(result)))
    return result
