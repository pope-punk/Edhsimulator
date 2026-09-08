"""Fence a diagnosed background misdelivery with no subsequent tool effects."""
import hashlib
import json
from datetime import datetime
from edh_gauntlet import planner_runtime, pilot_handoff
from edh_gauntlet.agent_architecture import is_background
from edh_gauntlet.runtime_store import read, write, get, locked


def validate(root,path,game,accepted,sessions,failure,previous_launch):
    collection=read(path/'collection.json');launch=read(path/'launch.json')
    def comparable(value):
        value=dict(value or {})
        # PowerShell's JSON round-trip may strip insignificant fractional zeros.
        for key in ('launched_utc','process_started_utc'):
            if key in value:value[key]=datetime.fromisoformat(value[key].replace('Z','+00:00'))
        return value
    events=[json.loads(line) for line in (path/'timing.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
    if (collection.get('gaps')!=[] or len(events)!=collection.get('events') or
            collection.get('accepted')!=accepted or collection.get('next')!='dispatch_pilot' or
            comparable(launch)!=comparable(previous_launch) or launch.get('game')!=game or collection.get('host_pid')!=launch.get('pid')):
        raise SystemExit('Reservation recovery requires complete telemetry for the exact stopped process and prefix.')
    if (failure.get('game')!=game or failure.get('accepted')!=accepted or
            failure.get('code')!='local_host_stop' or failure.get('exception_type')!='SystemExit' or
            failure.get('message_sha256')!=hashlib.sha256(b'A reservation cannot be assigned to a competing agent.').hexdigest()):
        raise SystemExit('Reservation recovery requires the diagnosed competing-agent failure.')
    directory=planner_runtime.directory_for(root,game)
    seats={row['thread']:row for row in sessions};bad={};batches=set()
    for event in events:
        if event['event']!='packet' or not event.get('batch_id'):continue
        batch=get(directory/'batches',event['batch_id'])
        if (batch['actor'],batch.get('role','planner'))==(event.get('actor'),event.get('role')):continue
        seat=seats.get(event.get('thread'),{})
        if (not is_background(seat.get('role')) or
                (seat.get('actor'),seat.get('role'))!=(event.get('actor'),event.get('role'))):
            raise SystemExit('Misdelivery cannot be isolated to a known background context.')
        bad.setdefault(event['thread'],event['epoch']);batches.add(event['batch_id'])
    if not bad:raise SystemExit('No diagnosed background misdelivery in this telemetry.')
    # No tools means no actor inspection, publication, offer, or gameplay effect
    # escaped the tainted context. Check persisted receipts as independent evidence.
    if any(e['event']=='tool_arrived' and e.get('thread') in bad and e['epoch']>=bad[e['thread']] for e in events):
        raise SystemExit('A contaminated context called a tool; reconcile its effects before recovery.')
    for name in ('publications','component_publications','stage_publications'):
        for file in (directory/name).glob('*.json'):
            text=file.name+' '+file.read_text(encoding='utf8')
            if any(batch in text for batch in batches):
                raise SystemExit('Misrouted work has a publication receipt; ordinary recovery is unsafe.')
    for name in ('diplomacy_posts.json','diplomacy_outbox.json','diplomatic_offers.json'):
        text=json.dumps(read(directory/name,{}))
        if any(batch in text for batch in batches):
            raise SystemExit('Misrouted work reached diplomatic state; reconcile before recovery.')
    return {'host_pid':launch['pid'],'telemetry':str(path),'misrouted_batches':sorted(batches),
            'discard_threads':sorted(bad),'no_tools_after_misdelivery':True,'no_publications':True}


def discard(root,game,sessions,audit,server):
    """Called only after process, exact-prefix and unloaded-thread fencing."""
    bad=set(audit['discard_threads']);directory=planner_runtime.directory_for(root,game)
    discarded=[row for row in sessions if row['thread'] in bad]
    agents={row.get('agent','/app-server/'+row['thread']) for row in discarded}
    for row in discarded:
        server.call('thread/archive',{'threadId':row['thread']})
        path=root/'host_runtime'/'context'/f"{pilot_handoff.seat_slug(row['actor'])}_{row['role']}.json"
        # Preserve private forensic evidence outside normal retained-memory paths.
        write(root/'host_runtime'/'discarded_contexts'/f"{row['thread']}.json",read(path))
        path.unlink()
    with locked(directory,'planning'):
        state=planner_runtime._state(directory)
        if state.get('active'):raise SystemExit('Cannot discard an actively reserved background context.')
        state['planners']={k:v for k,v in state['planners'].items() if v.get('agent') not in agents}
        planner_runtime._save(directory,state)
    retained=[row for row in sessions if row['thread'] not in bad]
    write(root/'host_runtime'/'sessions.json',retained)
    return retained
