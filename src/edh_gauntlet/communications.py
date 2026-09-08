"""One presentation boundary for seat-scoped communications.

Never used by rules, scheduling, claim validation or evidence writers. Inputs are
immutable authoritative records; this module produces an equivalent model view.
Conversation state retains one acknowledged board or plan preview and reference IDs.
"""
from copy import deepcopy
import json

VERSION = 1
PILOT_CUE = ('Use the current goal and short-term prose to guide this choice. Adapt to '
             'material changes; request a planner goal refresh if its route or survival '
             'assumptions are stale. Continue deciding without an adoption turn.')
FORMAT = ('Column encodings preserve every field; follow their read instructions. '
          'Named change sets have distinct origins. References point to information '
          'already delivered in this packet or this model conversation, never another seat.')


def stage_instruction(value):
    """Keep live stage constraints, not another copy of the static tool manual."""
    from .host_contract import PLANNER_GUIDANCE
    result = deepcopy(value)
    if isinstance(result, dict) and isinstance(result.get('instruction'), str):
        result['instruction'] = result['instruction'].replace(PLANNER_GUIDANCE,
            'Use the action_sequence/watch tool schema, exact frozen identities, and an object scheduler on every step. Do not replay an accepted stage.')
    return result


def receipt(value, *, schema_available=False):
    result = deepcopy(value)
    if schema_available and isinstance(result, dict) and isinstance(result.get('next'), dict):
        result['next'] = stage_instruction(result['next'])
    return result


def size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')))


def _key(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _uid_orders(value, path=''):
    """Carry list ordering only when a delta's UID view would otherwise lose it."""
    result = {}
    if isinstance(value, list) and value and all(isinstance(x, dict) and x.get('uid') for x in value):
        if len({x['uid'] for x in value}) == len(value):
            result[path] = [x['uid'] for x in value]
    elif isinstance(value, dict):
        for key, item in value.items():
            result.update(_uid_orders(item, path + '/' + key.replace('~', '~0').replace('/', '~1')))
    return result


def expand_board(value, previous=None):
    """Reconstruct a presented planner board, verifying a delta's before-values."""
    from .communication_codec import decode_board, decode_changes
    if not isinstance(value, dict) or value.get('encoding') != 'board_delta_v1':
        return decode_board(value)
    if previous is None:
        raise ValueError('A board delta requires its acknowledged baseline')
    from .runtime_store import identity
    if value.get('from_board_id') and identity(previous) != value['from_board_id']:
        raise ValueError('Board delta baseline mismatch')
    result = deepcopy(previous)
    for row in decode_changes(value['changes']):
        parts = [x.replace('~1', '/').replace('~0', '~') for x in row['path'].split('/')[1:]]
        parent = result
        for part in parts[:-1]:
            parent = next(x for x in parent if x['uid'] == part) if isinstance(parent, list) else parent[part]
        if not parts:
            if _key(result) != _key(row['before']):
                raise ValueError('Board delta baseline mismatch')
            result = deepcopy(row['after'])
            continue
        key = parts[-1]
        if isinstance(parent, list):
            index = next((i for i,x in enumerate(parent) if x['uid'] == key), None)
            present = index is not None
            before = parent[index] if present else None
        else:
            present = key in parent
            before = parent.get(key)
        if present != row.get('before_present', True) or _key(before) != _key(row.get('before')):
            raise ValueError('Board delta baseline mismatch at ' + row['path'])
        if isinstance(parent, list):
            if not row.get('after_present', True):
                parent.pop(index)
            elif present:
                parent[index] = deepcopy(row['after'])
            else:
                parent.append(deepcopy(row['after']))
        elif row.get('after_present', True):
            parent[key] = deepcopy(row['after'])
        else:
            parent.pop(key)
    for path, order in value.get('uid_orders', {}).items():
        target = result
        for part in path.split('/')[1:]:
            target = target[part.replace('~1', '/').replace('~0', '~')]
        by_id = {x['uid']: x for x in target}
        target[:] = [by_id[uid] for uid in order]
    if 'event_seq' in value:
        result['seq'] = value['event_seq']
    elif value.get('seq_present') is False:
        result.pop('seq', None)
    if value.get('to_board_id') and identity(result) != value['to_board_id']:
        raise ValueError('Reconstructed board differs from the frozen destination')
    return result


def change_sets(sets):
    """Intern identical complete changes, retaining each comparison's row order."""
    from .communication_codec import encode_changes
    direct = {name: encode_changes(rows) for name, rows in sets.items()}
    facts, positions, indices = [], {}, {}
    for name, rows in sets.items():
        indices[name] = []
        for row in rows:
            key = json.dumps(row, ensure_ascii=False, separators=(',', ':'))
            if key not in positions:
                positions[key] = len(facts)
                facts.append(row)
            indices[name].append(positions[key])
    shared = {'encoding': 'change_sets_v1',
              'read': 'Expand facts, then each named set selects its zero-based row indices in order. Origins and directions remain distinct.',
              'facts': encode_changes(facts), 'sets': indices}
    return shared if size(shared) < size(direct) else direct


def expand_change_sets(value):
    from .communication_codec import decode_changes
    if value.get('encoding') == 'change_sets_v1':
        facts = decode_changes(value['facts'])
        return {name: [deepcopy(facts[i]) for i in rows] for name, rows in value['sets'].items()}
    return {name: decode_changes(rows) for name, rows in value.items()}


def _pilot_brief(brief, previous=None, plan_id=None, decision_id=None):
    """Adapt the existing immutable renderer's named sections at the boundary.

    Unknown text is retained verbatim. The producer remains unchanged so old
    claim fingerprints and inspectable historical renderings stay valid.
    """
    from .pilot_plan_packet import GUIDANCE
    from .communication_events import encode_summary
    lines = brief.replace(GUIDANCE, PILOT_CUE).splitlines()
    # Recognized headings are renderer boundaries, not a license to discard a
    # second section embedded in prose or added by a future renderer.
    matches = [sum(line == 'State changes (exact fields; UID-keyed zones):' for line in lines),
               sum(line.startswith('Intervening decision context (') for line in lines),
               sum(line == 'Supporting continuity and symbolic proposal:' for line in lines)]
    if any(count > 1 for count in matches):
        return '\n'.join(lines) + '\n', {}
    kept, comparisons, context = [], {}, {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if i + 1 < len(lines):
            kind = ('state' if line == 'State changes (exact fields; UID-keyed zones):' else
                    'events' if line.startswith('Intervening decision context (') else
                    'plan' if line == 'Supporting continuity and symbolic proposal:' else None)
            if kind:
                try:
                    value = json.loads(lines[i + 1])
                except ValueError:
                    value = None
                if kind == 'state' and isinstance(value, list):
                    comparisons['last_seen_to_current'] = value
                    i += 2
                    continue
                if kind == 'events' and isinstance(value, dict):
                    context['intervening'] = encode_summary(value)
                    context['history_scope'] = line
                    i += 2
                    continue
                if kind == 'plan' and isinstance(value, dict):
                    if isinstance(value.get('changes'), list):
                        comparisons['plan_snapshot_to_current'] = value.pop('changes')
                    context['plan_support'] = value
                    i += 2
                    continue
        kept.append(line)
        i += 1
    next_state = {}
    if 'plan_snapshot_to_current' in comparisons:
        from .runtime_store import identity
        from .communication_codec import encode_changes
        # Cache only this bounded preview, never a cumulative event timeline.
        plan_origin = plan_id or next((l for l in lines if l.startswith('Frozen plan version:')), None)
        full = comparisons['plan_snapshot_to_current']
        next_state = {'origin': plan_origin, 'changes': deepcopy(full), 'at_decision': decision_id}
        prior = (previous or {}).get('plan_comparison')
        if plan_origin and prior and prior.get('origin') == plan_origin:
            old = prior['changes']
            # An exact retained preview is a named reference, not a claim that
            # the current board or the complete since-plan history is unchanged.
            if _key(old) == _key(full):
                retained = {
                    'from_decision': prior.get('at_decision', previous.get('decision_id')), 'preview_id': identity(full),
                    'read': 'The plan-to-current preview is identical to the one delivered at from_decision. Current warnings, omitted counts, state changes and events still apply.'}
                if size(retained) < size(encode_changes(full)):
                    context['retained_plan_comparison'] = retained
                    next_state['at_decision'] = retained['from_decision']
                    comparisons.pop('plan_snapshot_to_current')
            else:
                old_by_key = {_key(row): i for i,row in enumerate(old)}
                added, order = [], []
                for row in full:
                    if _key(row) in old_by_key:
                        order.append(['retained', old_by_key[_key(row)]])
                    else:
                        order.append(['added', len(added)]);added.append(row)
                delta = {'encoding': 'comparison_delta_v1', 'from_decision': prior.get('at_decision', previous.get('decision_id')),
                         'from_id': identity(old), 'to_id': identity(full), 'added': encode_changes(added), 'order': order,
                         'read': 'Replace the previous plan preview with order: each pair selects a zero-based retained row or added row. Unselected old rows are removed. This updates only the preview, not the full plan comparison.'}
                if size(delta) < size(encode_changes(full)):
                    context['plan_comparison_update'] = delta
                    comparisons.pop('plan_snapshot_to_current')
    if comparisons:
        context['factual_changes'] = change_sets(comparisons)
    if context:
        kept += ['', 'Decision context (named comparison origins):',
                 json.dumps(context, ensure_ascii=False, separators=(',', ':'))]
    return '\n'.join(kept) + '\n', next_state


def expand_comparison(value, previous):
    from .communication_codec import decode_changes
    from .runtime_store import identity
    if value['from_id'] != identity(previous):
        raise ValueError('Plan comparison baseline mismatch')
    choices = {'retained': previous, 'added': decode_changes(value['added'])}
    result = [deepcopy(choices[kind][index]) for kind,index in value['order']]
    if identity(result) != value['to_id']:
        raise ValueError('Plan comparison reconstruction mismatch')
    return result


def _historical(value):
    from .communication_codec import encode_board, encode_changes
    if not isinstance(value, dict):
        return value
    result = deepcopy(value)
    if isinstance(result.get('board'), dict):
        result['board'] = encode_board(result['board'])
    if isinstance(result.get('changes_from_current_board'), list):
        result['changes_from_current_board'] = encode_changes(result['changes_from_current_board'])
    return result


def _memory(value):
    from .communication_codec import encode_records
    from .communication_events import encode_summary
    result = deepcopy(value)
    for key in ('own_decisions_since_plan', 'last_card_observations'):
        if isinstance(result.get(key), list):
            result[key] = encode_records(result[key])
    if isinstance(result.get('intervening_context'), dict):
        result['intervening_context'] = encode_summary(result['intervening_context'])
    if 'latest_decision_context' in result:
        result['latest_decision_context'] = _historical(result['latest_decision_context'])
    knowledge = result.get('inspected_knowledge', {})
    for key in ('roles', 'last_deck_inspection'):
        if isinstance(knowledge.get(key), dict):
            for field in ('roles', 'known_card_index'):
                if isinstance(knowledge[key].get(field), list):
                    knowledge[key][field] = encode_records(knowledge[key][field])
    return result


def _anchor_in_section(brief, key, text):
    if key == 'standing_plan':
        return 'Immutable standing plan (retain across compaction):\n' + text + '\n' in brief
    if key == 'long_term_plan' and 'Current long-term goal:\n' in brief:
        section = brief.split('Current long-term goal:\n', 1)[1].split('Current short-term sequence:', 1)[0]
        return '\n' + text + '\n' in '\n' + section
    return False


def prepare(packet, role, previous=None, *, schema_available=True):
    """Return (delivery, next conversation state), without mutating either input.

    previous may be supplied only after a successful delivery on the same physical
    conversation/seat/branch. A new conversation must pass None, forcing baseline.
    Non-enrolled/unknown packets pass through. Callers retain original evidence.
    """
    if not isinstance(packet, dict) or packet.get('context_handling') != 1:
        return deepcopy(packet), deepcopy(previous or {})
    if packet.get('communication_version') == VERSION:
        return deepcopy(packet), deepcopy(previous or {})
    from .communication_codec import encode_board, encode_changes, encode_records
    from .communication_events import encode_summary
    from .context_packets import state_changes
    result = deepcopy(packet)
    previous = previous or {}
    identity = [packet.get('game'), packet.get('actor'), role]
    if previous.get('identity') != identity:
        previous = {}
    state = {'identity': identity}
    references = {}
    if role == 'decider' and isinstance(result.get('brief'), str):
        plan_id = result.get('plan_id') or (result.get('continuity') or {}).get('plan_id')
        result['brief'], comparison_state = _pilot_brief(result['brief'], previous, plan_id, packet.get('decision_id'))
        state.update(decision_id=packet.get('decision_id'), plan_comparison=comparison_state)
        # Long/short prose stays prominently present on every actual decision.
        anchor = result.get('retained_strategic_reference', {})
        for key, text in list(anchor.items()):
            if isinstance(text, str) and text and _anchor_in_section(result['brief'], key, text):
                anchor.pop(key)
                references['retained_strategic_reference.' + key] = 'brief: ' + (
                    'Immutable standing plan' if key == 'standing_plan' else 'Current long-term goal')
        if not anchor:
            result.pop('retained_strategic_reference', None)
    elif role in {'planner','short_term_planner','long_term_planner','diplomacy'} and isinstance(result.get('board'), dict):
        board = result['board']
        state.update(board=deepcopy(board), board_tag=result.get('board_tag'),
                     snapshot=result.get('snapshot'))
        baseline = encode_board(board)
        if previous.get('board') is not None and previous.get('snapshot'):
            changes = encode_changes(state_changes(previous['board'], board))
            delta = {'encoding': 'board_delta_v1', 'from_snapshot': previous['snapshot'],
                     'to_snapshot': result.get('snapshot'),
                     'read': 'Apply these exact UID-keyed factual changes to the board from from_snapshot. Unlisted fields remain unchanged. A new conversation always receives a baseline.',
                     'changes': changes}
            from .runtime_store import identity as digest
            delta.update(from_board_id=digest(previous['board']), to_board_id=digest(board))
            if 'seq' in board:
                delta['event_seq'] = board['seq']
            else:
                delta['seq_present'] = False
            old_order = _uid_orders(previous['board'])
            order = {k:v for k,v in _uid_orders(board).items() if old_order.get(k) != v}
            if order:
                delta['uid_orders'] = order
            delta['read'] += ' Apply uid_orders afterward; event_seq sets board.seq (seq_present:false removes it).'
            try:
                exact = _key(expand_board(delta, previous['board'])) == _key(board)
            except (KeyError, ValueError, TypeError, IndexError, StopIteration):
                exact = False
            result['board'] = delta if exact and size(delta) < size(baseline) else baseline
        else:
            result['board'] = baseline
        standing = result.get('standing_plan', {})
        text = standing.get('standing_plan') if isinstance(standing, dict) else None
        prior = result.get('prior_plan')
        if text and isinstance(prior, dict) and prior.get('standing_plan') == text:
            prior.pop('standing_plan')
            references['prior_plan.standing_plan'] = 'standing_plan.standing_plan'
        # The standing reference is immutable, but only reuse an exact delivered value.
        if text:
            from .runtime_store import identity as digest
            ref = digest(text)
            state['standing_id'] = ref
            if previous.get('standing_id') == ref:
                result['standing_plan'] = {k:v for k,v in standing.items() if k != 'standing_plan'}
                result['standing_plan']['retained_reference'] = ref
                references['standing_plan.standing_plan'] = 'previously delivered immutable standing reference ' + ref
        for key in ('decisions_since_prior_plan',):
            if isinstance(result.get(key), list):
                result[key] = encode_records(result[key])
        if isinstance(result.get('intervening_context'), dict):
            result['intervening_context'] = encode_summary(result['intervening_context'])
        if 'latest_decision_context' in result:
            result['latest_decision_context'] = _historical(result['latest_decision_context'])
        if 'publication_stages' in result:
            if schema_available:
                result['publication_stages'] = [stage_instruction(v) for v in result['publication_stages']]
            if packet.get('agent_architecture')!=1:
                result['guidance'] = ('Maintain this seat from its frozen board, complete own rationales and current plan. '
                    'Follow publication_stages in order, awaiting each receipt. Reuse retained seed/roles/deck; inspect only missing or materially uncertain facts.')
        if packet.get('agent_architecture')==1 and isinstance(result.get('symbolic_vocabulary'),dict):
            from .runtime_store import identity as digest
            for field in ('cards','sequence_format'):
                vocabulary=result['symbolic_vocabulary']
                if field not in vocabulary:continue
                key='vocabulary_'+field+'_id';ref=digest(vocabulary[field]);state[key]=ref
                marker={'retained_reference':ref,'read':'Exact '+field+' from the previously delivered symbolic vocabulary in this conversation.'}
                if previous.get(key)==ref and size(marker)<size(vocabulary[field]):
                    vocabulary[field]=marker
        anchor=result.get('retained_strategic_reference',{})
        if text and anchor.get('standing_plan')==text:
            anchor.pop('standing_plan')
            references['retained_strategic_reference.standing_plan']='standing_plan.standing_plan'
        if isinstance(prior,dict) and anchor.get('long_term_plan') and anchor.get('long_term_plan')==prior.get('long_term_plan'):
            anchor.pop('long_term_plan')
            references['retained_strategic_reference.long_term_plan']='prior_plan.long_term_plan'
    if isinstance(result.get('seat_continuity'), dict):
        memory = result['seat_continuity']
        prior = packet.get('prior_plan') or {}
        if role in {'planner','short_term_planner','long_term_planner'} and memory.get('continuity') and memory.get('continuity') == prior.get('continuity'):
            memory.pop('continuity')
            references['seat_continuity.continuity'] = 'prior_plan.continuity'
        result['seat_continuity'] = _memory(memory)
    if references:
        result['reference_locations'] = references
    result['communication_version'] = VERSION
    if not previous.get('format_delivered'):
        result['communication_format'] = FORMAT
    state['format_delivered'] = True
    return result, state


def present(packet, role):
    """Standalone view with no new cross-call references.

    Preserve the source packet's bound last-seen-state contract; baseline any
    additional board/plan-preview encodings introduced by this adapter.
    """
    return prepare(packet, role, schema_available=False)[0]
