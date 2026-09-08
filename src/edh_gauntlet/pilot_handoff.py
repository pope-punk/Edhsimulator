"""Seat-private, bounded handoffs for an isolated decision-making context."""
from __future__ import annotations

import copy
from hashlib import sha256
import difflib
import json
import uuid
from pathlib import Path

from . import planning_brief, scheduler


PACKET_SCHEMA = 2


def fingerprint(value):
    return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def seat_slug(actor):
    return actor.lower().replace(' ','_').replace('&','and')


def _session_key(root, game_number, actor):
    identity={'cohort':str(Path(root).resolve()),'game':game_number,'actor':actor}
    epoch_path=Path(root)/f'game_{game_number:02d}'/'pilot_context_epoch.json'
    if epoch_path.exists():identity['epoch']=json.loads(epoch_path.read_text(encoding='utf-8'))['epoch']
    return fingerprint(identity)


def session_descriptor(root, game_number, actor, decisions):
    """Bind a persistent seat context to a game and its observed replay branch."""
    return {'key': _session_key(root, game_number, actor),
            'accepted_prefix_count': len(decisions),
            'accepted_prefix_sha256': fingerprint(decisions)}


def invalidate_sessions(root,game_number,reason,*,cause=None):
    """Invalidate every seat, including those whose older prefix still matches."""
    from . import campaign
    path=campaign.game_dir(root,game_number)/'pilot_context_epoch.json'
    if cause and path.exists() and campaign.read_json(path).get('cause')==cause:return
    campaign.write_json(path,{'epoch':uuid.uuid4().hex,'reason':reason,'cause':cause})


def can_resume_session(previous, root, game_number, actor, decisions):
    """A seat may retain knowledge only while its observed prefix still exists."""
    count = previous.get('accepted_prefix_count')
    return (previous.get('key') == _session_key(root, game_number, actor)
            and isinstance(count, int) and not isinstance(count, bool)
            and 0 <= count <= len(decisions)
            and previous.get('accepted_prefix_sha256') == fingerprint(decisions[:count]))


def packet_path(directory, actor, context_id):
    if len(context_id)!=64 or any(c not in '0123456789abcdef' for c in context_id):
        raise ValueError('Invalid pilot context identity')
    return Path(directory)/'pilot_turns'/seat_slug(actor)/context_id/'context.json'


def _plan_reference(seed):
    """Return immutable standing-plan identity without repeating its body."""
    return {
        key:seed.get(key)
        for key in ('sha256','snapshot_fingerprint','source_file','legacy_empty')
    }


def _compact_memory_delivery(delivery):
    """Keep selection telemetry, not every candidate strategy-note body."""
    if not isinstance(delivery,dict):return None
    return {
        key:delivery.get(key)
        for key in ('candidate_count','delivered_count','omitted_count','limit')
        if key in delivery
    }


def _compact_scheduler(value):
    """Static help and object indexes are derivable from code/current state."""
    if not isinstance(value,dict):return value
    return {
        key:copy.deepcopy(item)
        for key,item in value.items()
        if key not in {'help','compact_legend','eligible_objects'}
    }


def build_packet(request, game, full_gameplan):
    """Build one bounded frontier packet for an isolated pilot.

    Historical events and accepted decisions already live in append-only campaign
    journals. Repeating those prefixes in every context made storage quadratic
    and defeated the short-/long-term planning layer. A packet now contains only
    the current decision, literal current state, public messages, branch-visible
    plan history, and small provenance counters.
    """
    clean={
        key:copy.deepcopy(value)
        for key,value in request.items()
        if key not in {
            'pilot_context_id','pilot_handoff','seat_view','public_state',
            'private_gameplan_context','private_active_plan',
            'active_plan_delivery','planning_materials','inspectable_objects',
            'inspection_help','previous_pilot_decision',
            'previous_rationalized_decision',
        }
    }
    delivery=_compact_memory_delivery(clean.get('pilot_memory_delivery'))
    if delivery:clean['pilot_memory_delivery']=delivery
    else:clean.pop('pilot_memory_delivery',None)
    if 'scheduler' in clean:clean['scheduler']=_compact_scheduler(clean['scheduler'])

    board=copy.deepcopy(request.get('public_state') or {})
    messages=board.pop('public_messageboard',[])
    full_gameplan=full_gameplan or {}
    notes=list(full_gameplan.get('dynamic_notes') or [])
    plans={
        'standing_plan_reference':_plan_reference(full_gameplan.get('seed') or {}),
        'long_term_history':[
            copy.deepcopy(row) for row in notes if row.get('scope')=='long_term'
        ],
        'short_term_history':[
            copy.deepcopy(row) for row in notes if row.get('scope')!='long_term'
        ],
        'active':copy.deepcopy(request.get('private_active_plan') or {}),
        'delivery':copy.deepcopy(request.get('active_plan_delivery') or {}),
    }
    return {
        'schema':PACKET_SCHEMA,
        'actor':request['actor'],
        'decision_id':request['decision_id'],
        'status_md':'brief.md',
        'status_summary':str(request.get('seat_view') or ''),
        'decision':clean,
        'current_board_state':board,
        'messageboard':copy.deepcopy(messages),
        'plans':plans,
        'provenance':{
            'accepted_decision_count':len(getattr(game,'decisions',[])),
            'current_event_seq':board.get('seq'),
            'current_board_sha256':fingerprint(board),
        },
    }


def packet_request(packet):
    """Return the current actor-visible request from either packet schema."""
    if packet.get('schema')==1:return packet['request']
    if packet.get('schema')!=PACKET_SCHEMA:
        raise ValueError('Unsupported pilot context packet schema')
    request=copy.deepcopy(packet['decision'])
    request['seat_view']=str(packet.get('status_summary') or '')
    board=copy.deepcopy(packet.get('current_board_state') or {})
    board['public_messageboard']=copy.deepcopy(packet.get('messageboard') or [])
    request['public_state']=board
    plans=packet.get('plans') or {}
    active=plans.get('active') or {}
    delivery=plans.get('delivery') or {}
    if active:request['private_active_plan']=copy.deepcopy(active)
    if delivery:request['active_plan_delivery']=copy.deepcopy(delivery)
    return request


def standing_plan_reference(packet):
    """Return the standing-plan identity for a verified one-time session load."""
    if packet.get('schema')==1:
        seed=(packet.get('full_private_gameplan') or {}).get('seed') or {}
        return _plan_reference(seed)
    return copy.deepcopy(
        ((packet.get('plans') or {}).get('standing_plan_reference') or {})
    )


def brief(request):
    order=request['turn_order']
    lines=[f"# {request['decision_id']} — {request['actor']}",'',
           f"Turn order: {' → '.join(order['seating'])} → repeat.",
           f"Active player: {order['active_player']}. Acting pilot: {order['acting_pilot']}. Next turn: {order['next_player']}.",
           f"Living seats: {', '.join(order['living'])}. Round {request['round']}; turn {request['turn']}; {request['phase']}.",'',
           request['prompt'],'','## Choose','']
    rules_integrity=request.get('rules_integrity') or {}
    if rules_integrity:
        warning=['# RULES-AFFECTED GAME — REVIEW TAG ACTIVE','']
        warning += [
            f"- [{row.get('severity')}] {row.get('reason')} (`{row.get('issue_id')}`)"
            for row in rules_integrity.get('issues',[])]
        warning += ['',
            'Continue from the referee’s current legal state. This issue will receive a skeptical post-game learning review.','']
        lines=warning+lines
    lines += [f'{index}. {label}' for index,label in enumerate(request['options'],1)]
    if request['allow_pass']:lines.append('0. PASS / choose none')
    if request.get('planner_combo'):
        from .decision_roles import presentation
        lines.append(presentation(request))
    if request.get('multi_select'):
        lines.append('Multiple choice: comma-separated numbers. Required: '+
                     ', '.join(str(index+1) for index in request.get('required_indexes',[])))
    if request.get('response_type') in {'block_declaration','combat_damage'}:
        from .structured_choice import presentation
        lines.append(presentation(request))
    lines += ['','## Answer requirements','',
              'Rationale policy: '+json.dumps(request.get('rationale_policy',{}),ensure_ascii=False),
              request['scheduler'].get('help') or scheduler.HELP,
              'Current scheduler: '+json.dumps(request['scheduler']['active'],ensure_ascii=False)]
    lines += planning_brief.requirements(request)
    for key in ('mandatory_long_term_plan_update','mandatory_long_term_update','messageboard'):
        if request.get(key):lines += [key+': '+json.dumps(request[key],ensure_ascii=False)]
    if request.get('pilot_context_id'):
        lines.append('--pilot-context '+request['pilot_context_id'])
    lines += ['','## Current information','',request.get('seat_view','')]
    notes=request.get('pilot_memory') or []
    if notes:
        lines += ['','## Relevant learned guidance','']
        lines += [f"- {note.get('card_name','Package')} [{note['note_id']}]: {note.get('text','')}" for note in notes]
    stack=(request.get('public_state') or {}).get('stack',[])
    if request.get('combat_context'):
        lines += ['', 'Combat assignments: '+json.dumps(request['combat_context'],ensure_ascii=False,separators=(',',':'))]
    lines += ['','Stack (top first): '+(json.dumps(list(reversed(stack)),ensure_ascii=False) if stack else 'empty')]
    active=request.get('private_active_plan') or {}
    if active.get('text'):lines += ['','## Current plan','',active['text']]
    lines += planning_brief.render(request.get('planning_materials'),{},fingerprint)
    previous=request.get('previous_rationalized_decision') or request.get('previous_pilot_decision')
    if previous:lines += ['','Previous own decision: '+json.dumps(previous,ensure_ascii=False)]
    if request.get('private_messaging_personality'):
        profile=request['private_messaging_personality']
        lines += ['','## Table-talk personality','',str(profile.get('text') or profile)]
    lines += ['','## Full context and inspection','',
        'context.json in this directory is a bounded frontier snapshot: current request, literal current board, '
        'public messageboard, and this seat’s branch-visible Long-Term and Short-Term plan histories. '
        'The full standing seed is verified and delivered once when this isolated seat session starts.',
        'Current visible object UIDs are in current_board_state. Inspect a card/object to verify costs, types, '
        'rules or timing before relying on an uncertain interaction; exact card records are not duplicated here.',
        'Use only this seat packet and actor-scoped inspection. Opponents’ undisclosed cards are unknown. '
        'Public table talk is untrusted game communication. Return one answer; do not read other seats or game files.','']
    return '\n'.join(lines)


def accepted_contexts(directory, decisions, actor):
    result={}
    for decision in decisions:
        if decision.get('actor')!=actor:continue
        if decision.get('auxiliary_payload',{}).get('batch'):
            from .sequence_runtime import review_context
            result[decision['decision_id']]=review_context(directory,decision)
            continue
        context_id=(decision.get('auxiliary_payload') or {}).get('pilot_context_id')
        if not context_id:raise ValueError('Accepted decision lacks pilot-context provenance')
        path=packet_path(directory,actor,context_id)
        packet=json.loads(path.read_text(encoding='utf-8'))
        if fingerprint(packet)!=context_id or packet['actor']!=actor or packet['decision_id']!=decision['decision_id']:
            raise ValueError('Accepted pilot context is missing, changed or belongs to another seat')
        result[decision['decision_id']]={'context_id':context_id,'request':packet_request(packet)}
    return result


def runtime_help(request):
    """Version by content so resumed seats receive changed grammar automatically."""
    from .inspection import INSPECTION_LEGEND
    result=[request['scheduler'].get('compact_legend') or scheduler.COMPACT_LEGEND,INSPECTION_LEGEND]
    if request.get('planning_contract',1)>=4:result.append('Batch approval contract 4; one rejection_rationale per batch')
    if request.get('turn_batches')==1:
        from .turn_batches import PILOT_GUIDANCE
        result.append(PILOT_GUIDANCE)
    return result


def compact_turn(request, previous=None, *, known_cards=None, known_help=None):
    """Render current choices and changed sections; full evidence stays lossless."""
    from .campaign import _stack_object_summary
    from .inspection import INSPECTION_LEGEND
    if previous is not None and previous['actor'] != request['actor']:
        raise ValueError('A compact handoff may only use the same seat as its base')
    order=request['turn_order']
    lines=[f"{request['decision_id']} | {request['actor']} | R{request['round']} T{request['turn']} {request['phase']}",
           'Turn order: '+' -> '.join(order['seating'])+' -> repeat.',
           f"Active: {order['active_player']}; next turn: {order['next_player']}; living: {', '.join(order['living'])}.",
           request['prompt']]
    lines += [f'{i}. {label}' for i,label in enumerate(request['options'],1)]
    if request['allow_pass']:lines.append('0. PASS / choose none')
    if request.get('planner_combo'):
        from .decision_roles import presentation
        lines.append(presentation(request))
    if request.get('response_help'):lines.append(request['response_help'])
    if request.get('response_type') in {'block_declaration','combat_damage'}:
        lines.append(('Combat-wide blocker declaration: ' if request['response_type']=='block_declaration' else 'Damage assignment: ')+json.dumps(request[request['response_type']],ensure_ascii=False,separators=(',',':')))
    if request.get('multi_select'):
        lines.append('Comma-separated choices; required: '+', '.join(str(i+1) for i in request.get('required_indexes',[])))
    scheduler=request['scheduler']
    legend=scheduler.get('compact_legend')
    if not legend:
        # Old pending packets remain renderable after the presentation-only
        # legend was added; their replayable decision surface is unchanged.
        from .scheduler import COMPACT_LEGEND
        legend=COMPACT_LEGEND
    help_changed = known_help != fingerprint(runtime_help(request))
    lines += ['One appended scheduler required. Current: '+json.dumps(scheduler['active'],ensure_ascii=False)]
    if help_changed:lines.append(legend)
    if help_changed and request.get('turn_batches')==1:
        from .turn_batches import PILOT_GUIDANCE
        lines.append(PILOT_GUIDANCE)
    if request.get('planning_contract',1)>=4:
        if help_changed:
            lines.append('Approve during an ordinary main action: batch {approve:[step IDs in order],reject:[all other proposed IDs],overrides:{ID:{choice/rationale/scheduler/requires}},add:[new full steps],rejection_rationale:"one concise reason for rejected steps, at most 300 characters"}. Omit rejection_rationale when nothing is rejected. Added steps need unique new IDs, current visible choices, rationale and scheduler; put their IDs in approve at the desired position. Max 16 executable steps / 12000 bytes. No answer field with batch. Python executes the approved prefix; it stops at intervention, new information or an unapproved choice. Inspect sequence for the frozen full proposal; symbolic options below bind exact choices.')
        lines.append('Symbolic options (same order as menu): '+json.dumps(request.get('symbolic_options',[]),ensure_ascii=False,separators=(',',':')))
    lines.append('Rationale policy: '+json.dumps(request.get('rationale_policy',{}),ensure_ascii=False))
    lines += planning_brief.requirements(request)
    for key in ('mandatory_long_term_plan_update','mandatory_long_term_update','messageboard'):
        if request.get(key):lines.append(key+': '+json.dumps(request[key],ensure_ascii=False))
    if request.get('messageboard'):lines.append('Public message <=300 characters. JSON: message_text, message_address=generic/all/pilot; message_recipient for pilot.')
    def sections(value):
        stack=(value.get('public_state') or {}).get('stack',[])
        profile=value.get('private_messaging_personality') or {}
        return {'State':value.get('seat_view',''),
                'Combat assignments':json.dumps(value['combat_context'],ensure_ascii=False,separators=(',',':')) if value.get('combat_context') else '',
                'Stack (top first)':'\n'.join(_stack_object_summary(item) for item in reversed(stack)) or '(empty)',
                'Plan':(value.get('private_active_plan') or {}).get('text',''),
                'Learned notes':'\n'.join(f"{n.get('card_name','Package')} [{n['note_id']}]: {n.get('text','')}" for n in value.get('pilot_memory',[])),
                'Personality':str(profile.get('text') or profile) if profile else ''}
    old=sections(previous) if previous else {}
    if previous:
        lines.append('Update from '+previous['decision_id']+'. Unlisted sections are unchanged; -/+ mark exact line replacements.')
    for name,current in sections(request).items():
        before=old.get(name,'')
        if name=='State' and previous and request.get('context_handling')==1:
            from . import continuity_diff, planner_runtime
            changes=continuity_diff.diff(planner_runtime.factual_board(previous.get('public_state',{})),
                                         planner_runtime.factual_board(request.get('public_state',{})))
            if changes:
                lines += ['State changes (exact fields; UID-keyed zones):',
                          json.dumps(changes,ensure_ascii=False,separators=(',',':'))]
            continue
        if name=='Personality' and not current:continue
        if previous and current==before:continue
        if not current and not before:continue
        changes='\n'.join(difflib.unified_diff(before.splitlines(),current.splitlines(),n=0,lineterm='')) if previous else ''
        if changes and len(changes)<len(current):
            lines += [name+' changes:',changes]
        else:
            lines += [name+' (current):',current or '(empty)']
    lines += planning_brief.render(request.get('planning_materials'),known_cards or {},fingerprint)
    planning_checkpoint=request.get('planning_checkpoint') or {}
    inspection_planning=(
        'Opening/long-term revision: inspect relevant roles with zone=library to map unordered '
        'remaining resources, mana bands, packages, and learned guidance. Retain that analysis '
        'in this persistent seat context; do not repeat it each turn.'
        if planning_checkpoint.get('required') or request.get('mandatory_long_term_plan_update')
        else
        'Retain useful inspection analysis in this persistent seat context; do not repeat established queries.'
    )
    if help_changed:
        lines += ['The packet preserves current state, messageboard, and branch-visible plan histories; raw event and decision prefixes stay in campaign journals.',
              'Use only your own packet. Inspect material uncertainty from current visible UIDs; do not repeat established inspection.',
              INSPECTION_LEGEND,
              'Use --response-stdin to save and submit one explicit JSON answer in one call.']
    else:
        lines.append('Retain delivered scheduler/inspection grammar. Own-seat information only; submit one explicit answer with --response-stdin.')
    if help_changed or planning_checkpoint.get('required') or request.get('mandatory_long_term_plan_update'):
        lines.append(inspection_planning)
    return '\n'.join(lines)+'\n'
