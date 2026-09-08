"""Actor-visible rules references and compact, non-strategic planning guidance."""
from __future__ import annotations

import json


def materials(request, game):
    """Bundle exact rules without inspecting libraries or opposing hidden cards."""
    service = getattr(game, 'inspection_service', None)
    if service is None:
        return None
    actor = request['actor']
    objects, records = [], {}
    choices = '\n'.join(request.get('options', ())).casefold()
    for row in service.inspectable_object_index(game, actor):
        if row['zone'] not in {'hand', 'command', 'battlefield', 'stack'}:
            # Graveyard/exile targets explicitly offered in this decision.
            if not row['identity_visible'] or row['name'].casefold() not in choices:
                continue
        result = service.inspect_object(game, actor, row['uid'])
        entry = {'state': result['object'], 'card_ids': []}
        for key in ('parent_card', 'effective_parent_card'):
            record = result.get(key)
            if record:
                card_id = record['card_id']
                records[card_id] = record
                if card_id not in entry['card_ids']:
                    entry['card_ids'].append(card_id)
        objects.append(entry)
    return {'schema': 1, 'actor': actor, 'objects': objects, 'catalog_records': records}


def requirements(request):
    """Present the existing obligation once, without changing validation."""
    checkpoint = request.get('planning_checkpoint') or {}
    if not checkpoint.get('required'):
        return []
    opening = checkpoint.get('opening_long_term_plan_required')
    lines = [
        'Planning checkpoint — submit all required fields with this ONE gameplay answer:',
        'short_term_plan: complete current execution plan: sequence, held resources/interaction, '
        'relevant timing/targets/combat and hazards. Use concise instructions; omit narrative recap.',
        'long_term_action: ' + ('revise (mandatory opening revision).' if opening else
                               'keep if the goal, route, opponent postures, alternatives and pivot cues remain accurate; otherwise revise.'),
        'long_term_rationale: concise reason for KEEP/REVISE, tied to new information or the unchanged basis.',
        'long_term_plan: required on revise; complete match goal/route, posture toward each opponent, '
        'alternatives and observable pivot cues. On keep, omit the unchanged plan text.',
        'Use the frozen standing plan as doctrine and the current short/long plans as match context. '
        'Preserve material detail; no word-count target. Each replacement plan is limited to 1200 characters.',
    ]
    boundary = checkpoint.get('opening_information_boundary') or {}
    if opening:
        lines += ['Opening opponent clauses required verbatim:']
        lines.extend('- ' + clause for clause in boundary.get('required_clauses', ()))
    lines.append('Base opponent postures on public information. Other seats\' private plans, hands, '
                 'inspections and unrevealed decklists or future libraries are unavailable.')
    return lines


def render(material, known_cards, fingerprint):
    """Show current object identities; repeat exact Oracle text only when changed."""
    if not material:
        return []
    lines = ['Rules reference — supplied from actor-scoped inspection; no extra lookup is needed '
             'for these facts. Check material uncertainty that is not answered here.']
    for entry in material['objects']:
        state = entry['state']
        lines.append(f"- {state.get('uid')}: {state.get('name', 'Unknown')} | "
                     f"{state.get('controller', state.get('owner'))} / {state.get('zone')}")
    for card_id, record in material['catalog_records'].items():
        if known_cards.get(card_id) == fingerprint(record):
            continue
        lines.append(f"{record['name']} | {record.get('mana_cost', '')} | {record.get('type_line', '')}")
        oracle = record.get('oracle_text', record.get('text'))
        if oracle:
            lines.append(str(oracle))
        # Keep complete face rules and characteristics for multi-face cards.
        for key in ('power', 'toughness', 'loyalty', 'defense', 'card_faces', 'faces'):
            if record.get(key) is not None:
                lines.append(key + ': ' + json.dumps(record[key], ensure_ascii=False))
    lines.append('Previously delivered card text is unchanged unless printed above. This supplied '
                 'material is decision-local; actor-scoped inspections remain the durable on-demand source.')
    return lines
