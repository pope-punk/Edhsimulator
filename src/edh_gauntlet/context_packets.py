"""Bounded presentation; complete evidence remains in actor-scoped journals."""
from collections import Counter
import json
from .runtime_store import get, read


def enabled(root, game):
    from .campaign import game_dir
    return read(game_dir(root, game)/'game_config.json', {}).get('context_handling') == 1


ROUTINE = {'scheduler_control', 'scheduler_suppressed', 'priority_closed',
           'planner_phase_boundary', 'planner_turn_boundary'}

TIMING = ('round', 'turn', 'phase', 'active_player', 'seat_turn')
HISTORY_GUIDANCE = ('Event facts are stored once. Timeline occurrence pairs are [event sequence, '
    'zero-based fact index]; combine each fact with its timeline timing fields. Repeated '
    'occurrences are distinct events, not duplicates. Net state changes list each changed '
    'field once; a net-unchanged field can still have intervening events. Full actor-scoped '
    'history remains inspectable. Every own-seat decision rationale is supplied separately.')


def material_delivery(events):
    """Lossless fact interning, without hiding repeated effects or their order.

    Only presentation changes. Never feed this representation to watch evaluation,
    execution validation or the immutable evidence journal.
    """
    facts=[];indices={};timeline=[]
    for event in events:
        # Unknown/unsequenced events remain exact in the legacy list fallback.
        if 'seq' not in event:return events
        timing={key:event[key] for key in TIMING if key in event}
        fact={key:value for key,value in event.items() if key not in TIMING and key!='seq'}
        signature=json.dumps(fact,sort_keys=True,ensure_ascii=False,separators=(',',':'))
        if signature not in indices:
            indices[signature]=len(facts);facts.append(fact)
        if not timeline or timeline[-1]['timing']!=timing:
            timeline.append({'timing':timing,'occurrences':[]})
        timeline[-1]['occurrences'].append([event['seq'],indices[signature]])
    packed={'encoding':'event_facts_v1','event_count':len(events),'facts':facts,'timeline':timeline}
    size=lambda value:len(json.dumps(value,ensure_ascii=False,separators=(',',':')))
    return packed if size(packed)<size(events) else events


def expand_material(delivery):
    """Exact inverse for verification and tooling; model packets explain the table."""
    if isinstance(delivery,list):return delivery
    if delivery.get('encoding')!='event_facts_v1':raise ValueError('Unknown material event encoding')
    return [{**delivery['facts'][index],**block['timing'],'seq':seq}
            for block in delivery['timeline'] for seq,index in block['occurrences']]


def state_changes(before,after):
    """One exact net difference per path; temporal evidence stays in event history."""
    from .continuity_diff import diff
    from .planner_runtime import factual_board
    return diff(factual_board(before),factual_board(after))


def history_since(directory, snapshot, since):
    history = []
    while snapshot:
        history.extend(e for e in snapshot['events'] if e.get('seq', 0) > since)
        if not snapshot.get('previous_snapshot') or snapshot['event_seq'] <= since:
            break
        snapshot = get(directory/'snapshots', snapshot['previous_snapshot'])
    return sorted(history, key=lambda e: e.get('seq', 0))


def history_delivery(history):
    """Collapse only known operational events; retain every other event verbatim."""
    material, groups = [], {}
    for event in history:
        if event.get('type') not in ROUTINE:
            material.append(event)
            continue
        key = (event['type'], event.get('actor'), event.get('mode'))
        group = groups.setdefault(key, {'type': key[0], 'actor': key[1], 'mode': key[2],
                                       'count': 0, 'first_seq': event.get('seq'),
                                       'last_seq': event.get('seq')})
        group['count'] += 1
        group['last_seq'] = event.get('seq')
    return material, list(groups.values())


def plan_changes(changes, dependencies):
    """Small factual report. Never mistake omitted detail for unchanged facts."""
    from .continuity_diff import preview
    selected = [row for row in changes if any(row['path'] == key or
                row['path'].startswith(key+'/') or key.startswith(row['path']+'/')
                for key in dependencies)]
    remaining = [row for row in changes if row not in selected]
    shown = preview(selected+remaining, limit=1200)
    categories = Counter('/'.join(row['path'].split('/')[:4]) for row in changes)
    return shown, dict(categories)
