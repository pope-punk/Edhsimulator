"""One atomic pilot submission followed by an actor-scoped compact handoff.

The caller supplies every choice. This module never chooses or loops gameplay.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from .runtime_store import serialized

from . import campaign, pilot_handoff


def next_action(root):
    return campaign.read_json(root/'NEXT_ACTION.json')['next_action']


def _session_path(root,action):
    return campaign.game_dir(root,action['game'])/'pilot_sessions'/(pilot_handoff.seat_slug(action['actor'])+'.json')


def _standing_seed(directory,actor,packet):
    """Load and verify the static standing plan once per persistent seat session."""
    if packet.get('schema')==1:
        return packet['full_private_gameplan']['seed']
    reference=pilot_handoff.standing_plan_reference(packet)
    snapshot=campaign._load_game_seed_gameplan_snapshot(directory)
    if snapshot is None:
        seed={
            'text':'','sha256':campaign._seed_gameplan_text_sha256(''),
            'snapshot_fingerprint':None,'source_file':None,'legacy_empty':True,
        }
    else:
        stored=snapshot['pilots'][actor]
        seed={
            'text':stored['text'],'sha256':stored['sha256'],
            'snapshot_fingerprint':snapshot['fingerprint'],
            'source_file':stored['source_file'],'legacy_empty':False,
        }
    for key,value in reference.items():
        if seed.get(key)!=value:
            raise SystemExit('Standing-plan reference does not match the frozen game snapshot.')
    return seed


def _presentation(root,action,*,fresh=False):
    actor=action['actor']
    directory=campaign.game_dir(root,action['game'])
    decisions=campaign.read_jsonl(directory/'decisions.jsonl')
    session_path=_session_path(root,action)
    base=campaign.read_json(session_path) if session_path.exists() else None
    saved=None if fresh else base
    previous=None
    if saved:
        if not pilot_handoff.can_resume_session(saved['seat_session'],root,action['game'],actor,decisions):
            return {'state':'fresh_context_required','actor':actor,'decision_id':action['decision_id']},None,pilot_handoff.fingerprint(base)
        previous_path=pilot_handoff.packet_path(directory,actor,saved['context_id'])
        previous_packet=campaign.read_json(previous_path)
        if pilot_handoff.fingerprint(previous_packet)!=saved['context_id'] or previous_packet['actor']!=actor:
            raise SystemExit('Prior seat packet is invalid; stop this pilot session.')
        previous=pilot_handoff.packet_request(previous_packet)
    path=Path(action['context'])
    packet=campaign.read_json(path)
    if packet['actor']!=actor or pilot_handoff.fingerprint(packet)!=action['pilot_context_id']:
        raise SystemExit('Current seat packet is invalid.')
    request=pilot_handoff.packet_request(packet)
    from . import context_packets
    if context_packets.enabled(root, action['game']):request['context_handling']=1
    known_cards=dict((saved or {}).get('known_card_records',{}))
    text=pilot_handoff.compact_turn(request,previous,known_cards=known_cards,
                                  known_help=(saved or {}).get('runtime_help_fingerprint'))
    if request.get('context_handling')==1 and previous:
        from . import decision_context, planner_runtime
        planning=planner_runtime.directory_for(root,action['game'])
        since=previous.get('public_state',{}).get('seq',0)
        events=planner_runtime.events_since(planning,request.get('continuity_event_head'),since)
        summary=decision_context.event_summary(events)
        if any(summary[key] for key in ('observations','life_excursions','life_sources','card_activity')):
            summary['after_event_seq']=since
            text+='\nIntervening decision context (since your last seen board; inspect history after='+str(since)+' for full history):\n'+json.dumps(summary,ensure_ascii=False,separators=(',',':'))+'\n'
    records=(request.get('planning_materials') or {}).get('catalog_records',{})
    known_cards.update({key:pilot_handoff.fingerprint(record) for key,record in records.items()})
    seed=_standing_seed(directory,actor,packet)
    seed_hash=pilot_handoff.fingerprint(seed)
    from . import plan_tiers,agent_architecture
    if not plan_tiers.enabled(root,action['game']) and (not saved or saved.get('seed_fingerprint')!=seed_hash):
        text+='\nFull frozen seed (retain for this seat session):\n'+seed['text']+'\n'
    if plan_tiers.enabled(root,action['game']) and not agent_architecture.enabled(root,action['game']):
        standing=plan_tiers.standing(root,action['game'],actor)
        standing_id=pilot_handoff.fingerprint(standing) if standing else None
        if standing and (not saved or saved.get('standing_fingerprint')!=standing_id):
            text+='\nImmutable standing plan (retain across compaction):\n'+standing['standing_plan']+'\n'
    else:standing_id=None
    renderer={
        'standing_fingerprint':standing_id,
        'seat_session':pilot_handoff.session_descriptor(root,action['game'],actor,decisions),
        'context_id':action['pilot_context_id'],
        'known_card_records':known_cards,'seed_fingerprint':seed_hash,
        'runtime_help_fingerprint':pilot_handoff.fingerprint(pilot_handoff.runtime_help(request)),
    }
    return {'state':'decision','actor':actor,'decision_id':action['decision_id'],
            **({'context_handling':1} if request.get('context_handling')==1 else {}),
            'pilot_context_id':action['pilot_context_id'],'packet_directory':str(path.parent),
            'brief':text},renderer,pilot_handoff.fingerprint(base)


@serialized
def present(root, actor, *, fresh=False,route_id=None,invocation_id=None):
    action=next_action(root)
    if action['kind']!='dispatch_pilot':return {'state':'stop','next_action':action}
    if action['actor']!=actor:
        result={'state':'handoff','actor':action['actor'],'decision_id':action['decision_id']}
        if action.get('dispatch'):
            # A resume prompt belongs to the outgoing pilot solely for direct
            # delivery. The coordinator may create a fresh seat but never relays
            # a resume prompt between persistent seat contexts.
            result['dispatch']={key:action['dispatch'][key] for key in (
                'kind','agent','prompt','handoff_transport','coordinator_relay_allowed','route_id','generation')
                if key in action['dispatch']}
        return result
    if action.get('dispatch',{}).get('route_id'):
        from . import handoff_runtime
        return handoff_runtime.claim_read(root,actor,route_id or action['dispatch']['route_id'],invocation_id,fresh=fresh)
    result,renderer,base_hash=_presentation(root,action,fresh=fresh)
    if renderer is not None:
        delivery=_store_delivery(root,action,result,renderer,base_hash,fresh=fresh)
        acknowledge(root,actor,delivery['delivery_id'],action=action)
        result['pilot_delivery_id']=delivery['delivery_id']
        campaign.atomic_text(Path(result['packet_directory'])/'turn.md',result['brief'])
    return result


@serialized
def prepare(root,action,*,fresh=False):
    """Prepare an immutable private delivery; preparation is not receipt."""
    result,renderer,base_hash=_presentation(root,action,fresh=fresh)
    if renderer is None:
        fresh=True
        result,renderer,base_hash=_presentation(root,action,fresh=True)
    return _store_delivery(root,action,result,renderer,base_hash,fresh=fresh)


def _store_delivery(root,action,result,renderer,base_hash,*,fresh):
    mode='fresh' if fresh or not (_session_path(root,action)).exists() else 'resume'
    record={'schema':1,'actor':action['actor'],'decision_id':action['decision_id'],
            'pilot_context_id':action['pilot_context_id'],'base_hash':base_hash,
            'packet_directory':result['packet_directory'],
            'renderer':renderer,'mode':mode,'brief':result['brief']}
    delivery_id=pilot_handoff.fingerprint(record)
    directory=campaign.game_dir(root,action['game'])/'pilot_deliveries'/pilot_handoff.seat_slug(action['actor'])
    path=directory/(delivery_id+'.json')
    campaign.write_json(path,record)
    turn=directory/(delivery_id+'.md')
    campaign.atomic_text(turn,_delivery_text(record,delivery_id))
    return {'delivery_id':delivery_id,'turn':str(turn.resolve()),'mode':mode}


def _delivery_text(record,delivery_id):
    return (f"actor: {record['actor']}\ndecision_id: {record['decision_id']}\n"
            f"pilot_context_id: {record['pilot_context_id']}\npilot_delivery_id: {delivery_id}\n"
            f"packet_directory: {record['packet_directory']}\n"
            f"session: {record['mode']}\n\n"+record['brief'])


@serialized
def acknowledge(root,actor,delivery_id,*,action=None):
    action=action or next_action(root)
    if action['kind']!='dispatch_pilot' or action['actor']!=actor:
        raise SystemExit('This seat does not own the pending delivery.')
    if not isinstance(delivery_id,str) or len(delivery_id)!=64 or any(c not in '0123456789abcdef' for c in delivery_id):
        raise SystemExit('Invalid pilot delivery identity.')
    path=campaign.game_dir(root,action['game'])/'pilot_deliveries'/pilot_handoff.seat_slug(actor)/(delivery_id+'.json')
    if not path.exists():raise SystemExit('Pilot delivery does not belong to the current packet.')
    record=campaign.read_json(path)
    if pilot_handoff.fingerprint(record)!=delivery_id:raise SystemExit('Pilot delivery changed.')
    if path.with_suffix('.md').read_text(encoding='utf-8')!=_delivery_text(record,delivery_id):
        raise SystemExit('Rendered pilot delivery changed.')
    for key in ('actor','decision_id','pilot_context_id'):
        if record[key]!=action[key]:raise SystemExit('Pilot delivery identity does not match '+key)
    directory=campaign.game_dir(root,action['game'])
    decisions=campaign.read_jsonl(directory/'decisions.jsonl')
    if not pilot_handoff.can_resume_session(record['renderer']['seat_session'],root,action['game'],actor,decisions):
        raise SystemExit('Pilot delivery belongs to a discarded branch; fresh context required.')
    session_path=_session_path(root,action)
    saved=campaign.read_json(session_path) if session_path.exists() else None
    if saved and saved.get('last_delivery_id')==delivery_id:return
    if pilot_handoff.fingerprint(saved)!=record['base_hash']:
        raise SystemExit('Pilot delivery base changed; obtain the current own-seat update.')
    campaign.write_json(session_path,{**record['renderer'],'last_delivery_id':delivery_id})
    from . import pilot_dispatch
    pilot_dispatch.mark_observed(root,action)


@serialized
def submit(root, actor, response_path):
    # Claimed envelopes retain their game binding for idempotent retries even
    # after NEXT_ACTION has moved to another seat or lifecycle action.
    action=next_action(root)
    if action.get('kind')!='dispatch_pilot' or action.get('actor')!=actor:
        from . import planner_runtime
        split_retry=any(planner_runtime.enabled(path.parent) for path in Path(root).glob('game_*/game_config.json'))
        if not split_retry:
            raise SystemExit('This seat does not own the pending decision; hand control back.')
    envelope=json.loads(Path(response_path).read_text(encoding='utf-8-sig'))
    if envelope.get('claim_id'):
        from . import handoff_runtime
        return handoff_runtime.submit(root,actor,envelope)
    action=next_action(root)
    if action['kind']!='dispatch_pilot' or action['actor']!=actor:
        raise SystemExit('This seat does not own the pending decision; hand control back.')
    response_path=Path(response_path).resolve()
    if response_path!=Path(action['context']).resolve().parent/'response.json':
        raise SystemExit('Response must belong to the current seat packet.')
    envelope=json.loads(response_path.read_text(encoding='utf-8-sig'))
    _submit_envelope(root,actor,action,envelope)


def _validate_envelope(action,envelope):
    if not isinstance(envelope,dict) or not isinstance(envelope.get('answer'),dict):
        raise SystemExit('Supply one response object with an answer object.')
    for key in ('actor','decision_id','pilot_context_id'):
        if envelope.get(key)!=action[key]:raise SystemExit('Response identity does not match '+key)


def _submit_envelope(root,actor,action,envelope,*,acknowledged=False):
    _validate_envelope(action,envelope)
    if envelope.get('pilot_delivery_id') and not acknowledged:
        acknowledge(root,actor,envelope['pilot_delivery_id'],action=action)
    answer=dict(envelope['answer'])
    answer['pilot_context']=action['pilot_context_id']
    for key in ('snooze_table','snooze_objects'):
        if isinstance(answer.get(key),dict):answer[key]=json.dumps(answer[key])
    try:
        campaign.answer(root,**answer)
        from . import pilot_dispatch
        pilot_dispatch.mark_observed(root,action)
    finally:
        # Read the authoritative continuation even on a rejected candidate.
        next_action(root)


@serialized
def submit_payload(root,actor,envelope):
    """Save and submit one explicit response; never fill in a strategic field."""
    if envelope.get('claim_id'):
        from . import handoff_runtime
        return handoff_runtime.submit(root,actor,envelope)
    action=next_action(root)
    if action['kind']!='dispatch_pilot' or action['actor']!=actor:
        raise SystemExit('This seat does not own the pending decision; hand control back.')
    _validate_envelope(action,envelope)
    path=Path(action['context'])
    packet=campaign.read_json(path)
    if pilot_handoff.fingerprint(packet)!=action['pilot_context_id'] or packet['actor']!=actor:
        raise SystemExit('Current seat packet is invalid.')
    if envelope.get('pilot_delivery_id'):acknowledge(root,actor,envelope['pilot_delivery_id'],action=action)
    campaign.write_json(path.parent/'response.json',envelope)
    _submit_envelope(root,actor,action,envelope,acknowledged=True)


@serialized
def inspect_many(root,actor,queries,*,claim_id=None):
    action=next_action(root)
    if action['kind']!='dispatch_pilot' or action['actor']!=actor:
        raise SystemExit('This seat does not own the pending decision; hand control back.')
    if action.get('dispatch',{}).get('route_id'):
        from . import handoff_runtime
        handoff_runtime.acknowledge(root,actor,claim_id)
    try:
        from .agent_architecture import enabled as architecture_enabled
        if architecture_enabled(root,action['game']):
            blocked={'roles','deck','seed'} & {q.strip() for q in queries}
            if blocked:
                queries=list(queries)
                ordinary=[q for q in queries if q.strip() not in blocked]
                other=iter(inspect_many(root,actor,ordinary,claim_id=claim_id)['results'] if ordinary else [])
                results=[{'query':q,'result':{'error':'Broad seed/catalog surveys belong to Sol; inspect a named role/package/card/object or deck zone.'}}
                         if q.strip() in blocked else next(other) for q in queries]
                return {'state':'inspections','actor':actor,'results':results}
        component_queries=[q for q in queries if q.startswith('component ')]
        if component_queries:
            from . import planner_runtime,component_store
            from .runtime_store import get
            _,directory,_,claim=handoff_runtime.validate_claim(root,actor,claim_id)
            attachment=get(directory/'attachments',claim['attachment_id'])
            allowed={v['component_id'] for v in attachment.get('component_refs',{}).values()}
            found={}
            for query in component_queries:
                key=query.removeprefix('component ')
                try:
                    if key not in allowed:raise ValueError('Inspect only the components supplied by this frozen decision claim.')
                    value=component_store.resolve(root,action['game'],actor,key,recipient_role='decider')
                except ValueError as exc:value={'error':str(exc)}
                found[query]={'query':query,'result':value}
                campaign._record_inspection(campaign.game_dir(root,action['game']),action,actor,query,query,value,
                    cache_key=None,branch_sha256=campaign._inspection_branch_sha256(campaign.game_dir(root,action['game'])),cache_hit=False)
            ordinary=[q for q in queries if q not in found]
            other=iter(inspect_many(root,actor,ordinary,claim_id=claim_id)['results'] if ordinary else [])
            return {'state':'inspections','actor':actor,'results':[found[q] if q in found else next(other) for q in queries]}
        context_queries=[query for query in queries if query.startswith(('decision ','history after=')) or query=='history']
        if context_queries:
            from . import decision_context, planner_runtime
            rows=campaign.read_jsonl(campaign.game_dir(root,action['game'])/'decisions.jsonl')
            found={}
            for query in context_queries:
                if query.startswith('decision '):
                    value=decision_context.inspect_decision(root,action['game'],actor,rows,query.removeprefix('decision '))
                else:
                    since=query.removeprefix('history after=') if query!='history' else '0'
                    if not since.isdigit():value={'error':'Use history or history after=NONNEGATIVE_EVENT_SEQUENCE'}
                    else:
                        request=pilot_handoff.packet_request(campaign.read_json(Path(action['context'])))
                        events=planner_runtime.events_since(planner_runtime.directory_for(root,action['game']),request.get('continuity_event_head'),int(since))
                        value={'events':events,'after_event_seq':int(since),'actor':actor}
                found[query]={'query':query,'result':value}
            directory=campaign.game_dir(root,action['game'])
            for query,item in found.items():
                campaign._record_inspection(directory,action,actor,query,query,item['result'],
                    cache_key=None,branch_sha256=campaign._inspection_branch_sha256(directory),cache_hit=False)
            ordinary=[query for query in queries if query not in found]
            other=iter(inspect_many(root,actor,ordinary,claim_id=claim_id)['results'] if ordinary else [])
            results=[found[query] if query in found else next(other) for query in queries]
        elif action.get('dispatch',{}).get('route_id') and set(queries)&{'continuity','sequence'}:
            from . import planner_runtime
            from .runtime_store import get
            _,directory,_,claim=handoff_runtime.validate_claim(root,actor,claim_id)
            attachment=get(directory/'attachments',claim['attachment_id'])
            planning=planner_runtime.directory_for(root,action['game'])
            if attachment.get('comparison_source'):
                from . import continuity_diff
                source=get(planning/'snapshots',attachment['comparison_source'])
                current=pilot_handoff.packet_request(campaign.read_json(Path(action['context'])))
                report={**attachment,'changes':continuity_diff.diff(planner_runtime.factual_board(source['board']),
                    planner_runtime.factual_board(current['public_state'])),
                    'changes_omitted':0,
                    'all_events_since_source':planner_runtime.events_since(planning,attachment.get('event_head'),attachment.get('source_event_seq',0))}
            else:report={**attachment,'all_events_since_source':planner_runtime.events_since(
                planning,attachment.get('event_head'),attachment.get('source_event_seq',0))}
            sequence=(planner_runtime.load_plan(planning,attachment['plan_id']).get('action_sequence',[]) if attachment.get('plan_id') else [])
            ordinary=[query for query in queries if query not in {'continuity','sequence'}]
            inspected=iter(campaign.inspect_many_current(root,ordinary,actor=actor,pilot_context=action['pilot_context_id']) if ordinary else [])
            results=[{'query':query,'result':report if query=='continuity' else {'plan_id':attachment.get('plan_id'),'action_sequence':sequence}}
                     if query in {'continuity','sequence'} else next(inspected) for query in queries]
        else:
            results=campaign.inspect_many_current(root,queries,actor=actor,pilot_context=action['pilot_context_id'])
    finally:
        continuation=next_action(root)
    return {'state':'inspections','actor':actor,'decision_id':action['decision_id'],
            'pilot_context_id':action['pilot_context_id'],'results':results,
            'next':{key:continuation.get(key) for key in ('kind','actor','decision_id')}}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort',type=Path,required=True)
    parser.add_argument('--actor',required=True)
    operation=parser.add_mutually_exclusive_group()
    operation.add_argument('--response',type=Path)
    operation.add_argument('--response-stdin',action='store_true',help='save and submit one JSON envelope from stdin')
    operation.add_argument('--inspect',action='append',dest='queries',help='repeat for a batch of actor-scoped queries')
    operation.add_argument('--planner-alarm',help='contract 3+ non-consuming priority control as JSON')
    parser.add_argument('--control-id',help='stable UUID for one planner-alarm operation and its retries')
    parser.add_argument('--fresh',action='store_true',help='new isolated agent only: deliver a full baseline')
    parser.add_argument('--delivery-id',help='acknowledge the prepared own-seat input before inspection')
    parser.add_argument('--route',help='split-runtime route to claim and read')
    parser.add_argument('--invocation',help='stable UUID for this decider work turn; reuse on read retry')
    parser.add_argument('--claim-id',help='split-runtime claim for actor-scoped inspection')
    args=parser.parse_args(argv)
    root=args.cohort.resolve()
    if args.planner_alarm:
        from . import planner_runtime
        print(json.dumps(planner_runtime.control_alarm(root,args.actor,args.claim_id,args.control_id,
                         json.loads(args.planner_alarm)),ensure_ascii=False))
        return 0
    if args.delivery_id:
        if not args.queries:parser.error('--delivery-id is for --inspect; submissions include pilot_delivery_id in their envelope')
        acknowledge(root,args.actor,args.delivery_id)
    if args.fresh and (args.response or args.response_stdin or args.queries):parser.error('--fresh is only for starting a seat context')
    if args.queries:
        result=inspect_many(root,args.actor,args.queries,claim_id=args.claim_id)
        from . import communications_inspection
        # Preserve every structured fact, including fields the prose renderer
        # does not display. Only exact rendered duplicates are omitted.
        print(json.dumps(communications_inspection.present(result),ensure_ascii=False))
        return 0
    submitted=None
    if args.response:submitted=submit(root,args.actor,args.response)
    elif args.response_stdin:submitted=submit_payload(root,args.actor,json.load(sys.stdin))
    if submitted and submitted.get('game')!=next_action(root).get('game'):
        print(json.dumps({'state':'stop','reason':'game_changed','submission':submitted},ensure_ascii=False))
        return 0
    result=present(root,args.actor,fresh=args.fresh,route_id=args.route,
                   invocation_id=(submitted or {}).get('invocation_id') or args.invocation)
    if submitted and submitted.get('batch_id'):
        result['submission']={key:submitted[key] for key in ('batch_id','state','accepted','reason') if key in submitted}
    if result['state']=='decision':
        from . import communications
        result=communications.present(result,'decider')
        brief=result.pop('brief')
        result.pop('continuity',None)  # Already rendered exactly once in the brief.
        print(json.dumps(result,ensure_ascii=False))
        print(brief)
    else:print(json.dumps(result,ensure_ascii=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
