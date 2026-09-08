"""Stateless, lossless presentation of actor-scoped inspection responses.

No previous conversation is assumed. Tables use the common record grammar;
references name only earlier results in this same response. Original inspection
evidence is never edited. ``detail=full`` results are delivered unchanged.
"""
from copy import deepcopy
import json

from .communication_codec import encode_records, decode_records


MARKER = 'inspection_presentation'
VERSION = 1
REFERENCE_GUIDANCE = ('JSON Pointers reference earlier results in this same response, '
    'after expanding their presentation. No prior conversation is assumed.')
RENDERED_KINDS = {'object', 'roles', 'messageboard', 'deck', 'card', 'role', 'package'}


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def size(value):
    """Compact JSON characters for transport telemetry (not token counts)."""
    return len(_json(value))


def _smaller(candidate, original):
    return len(_json(candidate).encode('utf-8')) < len(_json(original).encode('utf-8'))


def _escape(part):
    return str(part).replace('~', '~0').replace('/', '~1')


def _pointer(value, path):
    for part in path.split('/')[1:]:
        part = part.replace('~1', '/').replace('~0', '~')
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _replace(value, path, replacement):
    parent_path, _, key = path.rpartition('/')
    parent = _pointer(value, parent_path)
    key = key.replace('~1', '/').replace('~0', '~')
    parent[int(key) if isinstance(parent, list) else key] = replacement


def rendered_text_is_duplicate(payload):
    """Recognize the actual renderer's exact output, not merely a text field."""
    if (not isinstance(payload, dict) or payload.get('kind') not in RENDERED_KINDS
            or not isinstance(payload.get('text'), str)):
        return False
    from .inspection import render_inspection
    try:
        return payload['text'] == render_inspection({k: v for k, v in payload.items() if k != 'text'})
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def _tables(value, path, paths):
    if isinstance(value, list):
        encoded = encode_records(value)
        if isinstance(encoded, dict):
            paths.append(path)
            return encoded
        return [_tables(item, path + '/' + str(i), paths) for i, item in enumerate(value)]
    if isinstance(value, dict):
        return {key: _tables(item, path + '/' + _escape(key), paths) for key, item in value.items()}
    return value


def _rows(value):
    if isinstance(value, list):
        return value, ''
    if isinstance(value, dict) and isinstance(value.get('results'), list):
        return value['results'], '/results'
    return [], ''


def present(value, *, rendered_text_sources=None):
    """Present a result list or wrapper without assuming previous knowledge.

    A stateful adapter may supply exact text strings it already proved against
    original structured records before replacing fields with retained references.
    The ordinary stateless path performs that proof directly on each input.
    """
    result = deepcopy(value)
    rows, prefix = _rows(result)
    seen_results, seen_cards = {}, {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get('result'), dict):
            continue
        payload = row['result']
        location = prefix + '/' + str(index) + '/result'
        signature = _json(payload)
        full = ' '.join(str(row.get('query', '')).split()).endswith(' detail=full')
        candidate = deepcopy(payload)
        if not full and MARKER not in payload:
            if signature in seen_results:
                candidate = {MARKER: {'version': VERSION, 'same_response_result': seen_results[signature],
                                     'read': REFERENCE_GUIDANCE}}
            else:
                metadata = {'version': VERSION}
                proven_text = (rendered_text_sources or {}).get(index)
                if (isinstance(proven_text, str) and payload.get('text') == proven_text
                        or rendered_text_is_duplicate(payload)):
                    candidate.pop('text')
                    metadata['text_renderer'] = 'inspection.render_inspection'
                catalog = candidate.get('catalog_records')
                if isinstance(catalog, dict):
                    references = {key: seen_cards[_json(record)] for key, record in catalog.items()
                                  if _json(record) in seen_cards}
                    if references:
                        metadata['catalog_references'] = references
                        metadata['catalog_order'] = list(catalog)
                        metadata['read'] = REFERENCE_GUIDANCE
                        candidate['catalog_records'] = {key: record for key, record in catalog.items()
                                                        if key not in references}
                paths = []
                candidate = _tables(candidate, '', paths)
                if paths:
                    metadata['tables'] = paths
                if len(metadata) > 1:
                    candidate[MARKER] = metadata
            if _smaller(candidate, payload):
                row['result'] = candidate
        # Sources always name a material result/definition, never a reference
        # chain. A full result is also a valid source for a later compact one.
        delivered = row['result']
        meta = delivered.get(MARKER, {})
        if not isinstance(meta, dict):
            meta = {}
        if not meta.get('same_response_result'):
            seen_results.setdefault(signature, location)
            references = meta.get('catalog_references', {})
            records = payload.get('catalog_records')
            for key, record in (records.items() if isinstance(records, dict) else []):
                if key not in references:
                    seen_cards.setdefault(_json(record), location + '/catalog_records/' + _escape(key))
    return result


def expand(value):
    """Reconstruct original results for verification, including rendered text."""
    from .inspection import render_inspection
    result = deepcopy(value)
    rows, _ = _rows(result)
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('result'), dict):
            continue
        payload = row['result']
        metadata = payload.get(MARKER)
        if (not isinstance(metadata, dict) or metadata.get('version') != VERSION
                or not set(metadata) & {'same_response_result', 'tables', 'catalog_references', 'text_renderer'}):
            continue
        if 'same_response_result' in metadata:
            source = _pointer(result, metadata['same_response_result'])
            if MARKER in source:
                raise ValueError('Inspection reference must target an earlier expanded result')
            row['result'] = deepcopy(source)
            continue
        payload.pop(MARKER)
        for path in metadata.get('tables', []):
            _replace(payload, path, decode_records(_pointer(payload, path)))
        for key, path in metadata.get('catalog_references', {}).items():
            payload['catalog_records'][key] = deepcopy(_pointer(result, path))
        if 'catalog_order' in metadata:
            payload['catalog_records'] = {key: payload['catalog_records'][key] for key in metadata['catalog_order']}
        if metadata.get('text_renderer') == 'inspection.render_inspection':
            payload['text'] = render_inspection(payload)
    return result
