"""Bounded model presentation of inspections; original evidence stays intact."""
import copy
import json


def size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')))


def inventory(knowledge, seed_available):
    return {
        'roles_retained': bool(knowledge.get('roles')),
        'deck_index_retained': bool(knowledge.get('last_deck_inspection', {}).get('known_card_index')),
        'seed_retained': seed_available,
        'card_definitions_retained': len(knowledge.get('catalog_records', {})),
        'instruction': 'Initialization is once per logical seat/game. Reuse retained definitions; inspect material uncertainties. Append detail=full to expand any referenced inspection.'}


def table(cards):
    from .communication_codec import encode_records
    return encode_records(cards)


def expand_table(value):
    from .communication_codec import decode_records
    if isinstance(value,list) or value.get('encoding')=='record_columns_v1':
        return decode_records(value)
    # Archived inspection receipts still use this earlier table grammar.
    return [dict(zip(value['columns'], row)) if isinstance(row, list) else
            {value['columns'][i]: item for i, item in zip(row['indices'], row['values'])}
            for row in value['rows']]


def present(results, knowledge, seed=None, *, current_board=None, snapshot=None):
    """Reference only exact previously delivered facts, never stale zone claims."""
    output = copy.deepcopy(results)
    known = copy.deepcopy(knowledge) if isinstance(knowledge,dict) else {}
    from . import communications_inspection
    exact=lambda value:json.dumps(value,ensure_ascii=False,separators=(',',':'))
    rendered_text_sources={}
    for index,row in enumerate(output):
        payload = row.get('result')
        query = ' '.join(row.get('query', '').split())
        if not isinstance(payload, dict) or query.endswith(' detail=full'):
            continue
        if query=='state' and snapshot and current_board is not None and payload==current_board:
            row['result']={'retained_reference':'board from the current frozen input','snapshot':snapshot,
                'help':'This inspection is exactly the already-delivered frozen board. Append detail=full to expand it.'}
            continue
        if communications_inspection.rendered_text_is_duplicate(payload):
            # Prove against the complete original record, before catalog fields
            # are replaced by references to acknowledged prior knowledge.
            rendered_text_sources[index]=payload['text']
        if query == 'seed' and seed is not None and payload.get('text') == seed:
            payload.pop('text')
            payload['retained_reference'] = 'retained_strategic_reference.full_seed_plan'
        if query == 'roles':
            structured = {k: v for k, v in payload.items() if k != 'text'}
            previous=known.get('roles')
            previous={k:v for k,v in previous.items() if k!='text'} if isinstance(previous,dict) else {}
            if (exact(structured)==exact(previous) and
                    ('text' not in payload or communications_inspection.rendered_text_is_duplicate(payload))):
                row['result'] = {'retained_reference': 'inspected_knowledge.roles'}
                continue
        records = payload.get('catalog_records', {})
        if not isinstance(records,dict):continue
        retained = known.get('catalog_records', {})
        if not isinstance(retained,dict):retained={}
        reused = [key for key, record in records.items() if key in retained and exact(retained[key]) == exact(record)]
        if reused:
            payload['catalog_records'] = {key: record for key, record in records.items() if key not in reused}
            payload['retained_card_definitions'] = reused
            payload['reference_help'] = 'These exact definitions are already in retained inspected_knowledge; current zones below remain authoritative. Append detail=full to expand.'
        # New same-response knowledge is not earlier conversation knowledge.
        # The stateless presenter supplies explicit locations for those repeats.
    projected=communications_inspection.present(output,rendered_text_sources=rendered_text_sources)
    if output==results:return projected
    baseline=communications_inspection.present(results)
    # Referencing a tiny known record can cost more than simply repeating it.
    return projected if size(projected)<size(baseline) else baseline
