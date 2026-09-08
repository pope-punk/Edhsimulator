"""Decision-centred presentation over existing, actor-scoped immutable evidence.

No new snapshots or journals, no strategic judgements, and no scheduling effects.
Inspection expands historical boards only when a reader needs them.
"""
import json
from . import context_packets, pilot_handoff
from .runtime_store import read, get

GUIDANCE = ('Current board/decision facts are authoritative. Read the complete own decision '
    'rationales and plan rejection explanations; they carry earlier decision context. '
    'Only latest_decision_context supplies a historical board: the most recent board '
    'the pilot actually saw. It is either a full board or exact changes from the current '
    'board to that observed board. Automatic batch steps use the original approval '
    'board, never an invented pilot review of an automatic step. Use inspection only '
    'for material uncertainty. Intervening event summaries are observations, '
    'not an event replay or a count of independent effects. Inspect history for original '
    'chronology. An unchanged final board does not imply no intervening activity.')

# These are execution/scheduling bookkeeping, not additional pilot decisions.
# Rules, watches and execution validation always consume the unfiltered journal.
TRANSPORT = context_packets.ROUTINE | {
    'trigger_stack_add','trigger_resolve','triggers_deferred','stack_add',
    'resolve','ability_resolve','scheduler_wake','mana_payment','llm_decision',
    'untap','cleanup',
}
CARD_ACTIVITY={'etb','ltb','token_etb','land_play','spell_to_graveyard','leaves_game'}


def event_summary(events):
    """Keep transient observations; share repeated facts and life excursions."""
    groups={};life={};omitted={};cards={};life_sources={}
    for event in events:
        kind=event.get('type')
        if kind in TRANSPORT:
            omitted[kind]=omitted.get(kind,0)+1
            continue
        if kind=='planner_life_change' and all(isinstance(event.get(k),(int,float)) for k in ('before','after')):
            actor=event.get('actor');before,after=event['before'],event['after']
            item=life.setdefault(actor,{'actor':actor,'before':before,'after':after,
                'minimum':min(before,after),'maximum':max(before,after),'changes':0})
            item.update(after=after,minimum=min(item['minimum'],before,after),
                        maximum=max(item['maximum'],before,after),changes=item['changes']+1)
            continue
        if kind in {'life_gain','life_loss'} and isinstance(event.get('amount'),(int,float)):
            key=(event.get('actor'),event.get('card'),kind)
            item=life_sources.setdefault(key,{'actor':key[0],'source':key[1],'type':kind,'total':0,'count':0})
            item['total']+=event['amount'];item['count']+=1
            continue
        if kind in CARD_ACTIVITY:
            key=(event.get('actor'),event.get('card'),event.get('uid'))
            item=cards.setdefault(key,{'actor':key[0],'card':key[1],'uid':key[2],'activity':{}})
            attributes={name:value for name,value in event.items() if name not in {
                'seq',*context_packets.TIMING,'actor','card','uid','type','detail','visibility'}}
            activity_key=json.dumps({'type':kind,**attributes},sort_keys=True,ensure_ascii=False)
            activity=item['activity'].setdefault(activity_key,{'type':kind,**attributes,'count':0})
            activity['count']+=1
            continue
        # Do not infer card identities from unseen events or discard unknown fields.
        fact={key:value for key,value in event.items() if key not in {'seq',*context_packets.TIMING}}
        key=json.dumps(fact,sort_keys=True,ensure_ascii=False,separators=(',',':'))
        group=groups.setdefault(key,{'fact':fact,'count':0,'first_seq':event.get('seq'),'last_seq':event.get('seq')})
        group['count']+=1;group['last_seq']=event.get('seq')
    return {'through_event_seq':max((event.get('seq',0) for event in events),default=0),
        'observations':list(groups.values()),'life_excursions':list(life.values()),
        'life_sources':list(life_sources.values()),
        'card_activity':[{**item,'activity':list(item['activity'].values())} for item in cards.values()],
        'execution_events_not_repeated':omitted,
        'coverage':'Grouped observations preserve distinct payloads and occurrence counts, not full ordering. '
                   'Card activity summarizes entries/exits, not destinations or cause text; inspect history if those matter. '
                   'Life extrema preserve transient thresholds. Original actor-scoped history remains inspectable.'}


def observed(root,game,actor,row):
    """Locate the exact pilot-seen input, not an automatic execution snapshot."""
    from . import handoff_runtime, sequence_runtime
    if row.get('actor')!=actor:raise ValueError('Decision belongs to another seat')
    directory=root/f'game_{game:02d}';aux=row.get('auxiliary_payload',{});batch=aux.get('batch')
    approval=None;decision_id=row['decision_id'];context_id=aux.get('pilot_context_id')
    if batch:
        approval=get(sequence_runtime.batch_directory(root,game)/'approvals',batch['id'])
        claim=handoff_runtime.claim_record(handoff_runtime.directory_for(root,game),approval['claim_id'])
        if claim['actor']!=actor or claim['game']!=game:raise ValueError('Wrong-seat batch approval')
        context_id=claim['pilot_context_id'];decision_id=claim['decision_id']
    if not context_id:return None
    packet=read(pilot_handoff.packet_path(directory,actor,context_id))
    if (not packet or pilot_handoff.fingerprint(packet)!=context_id or packet.get('actor')!=actor
            or packet.get('decision_id')!=decision_id):raise ValueError('Historical decision packet changed')
    request=pilot_handoff.packet_request(packet)
    return {'decision_id':decision_id,'context_id':context_id,'board':request.get('public_state',{}),
        'prompt':request.get('prompt'),'options':request.get('options',[]),
        'approval':approval['approval'] if approval else None}


def inspect_decision(root,game,actor,rows,decision_id):
    row=next((row for row in rows if row.get('actor')==actor and row.get('decision_id')==decision_id),None)
    if row is None:return {'error':'No accepted own-seat decision at this frozen frontier.'}
    result=observed(root,game,actor,row)
    if result is None:return {'error':'Historical pilot snapshot unavailable; do not infer its contents.'}
    return {**result,'requested_decision_id':decision_id,
        'execution_kind':'approved_batch_step' if row.get('auxiliary_payload',{}).get('batch') else 'pilot_decision',
        'rationale':row.get('rationale','')}


def latest_decision(root,game,actor,rows,current_board):
    """Exactly one pilot-seen board, independent of the number of rationales."""
    row=next((row for row in reversed(rows) if row.get('actor')==actor),None)
    if row is None:return None
    source=observed(root,game,actor,row)
    if source is None:return {'decision_id':row['decision_id'],'state':'snapshot_unavailable'}
    changes=context_packets.state_changes(current_board,source['board']) if current_board is not None else None
    size=lambda value:len(json.dumps(value,ensure_ascii=False,separators=(',',':')))
    representation=({'changes_from_current_board':changes} if changes is not None and size(changes)<size(source['board'])
                    else {'board':source['board']})
    return {'decision_id':source['decision_id'],
        'execution_kind':'batch_approval' if source['approval'] is not None else 'pilot_decision',
        **representation}
