"""Lossless presentation of already actor-scoped event summaries.

This codec does not summarize events, infer causes, filter payloads, or change the
evidence store. It shares repeated fields in the existing summary. Unknown event
types and fields receive exactly the same treatment as known ones.
"""
from copy import deepcopy
import json


VERSION = 1
FORMAT = (
    'Table sections use record_columns_v1 with JSON Pointer field paths to '
    'reconstruct nested objects. Unlisted sections are literal. All observations, '
    'counts and sequence bounds are preserved; this is not a causal event replay.'
)
_ENVELOPE = {'event_summary_encoding', 'format', 'table_sections', 'summary'}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _flatten(record, prefix=''):
    fields = {}
    for key, value in record.items():
        path = prefix + '/' + key.replace('~', '~0').replace('/', '~1')
        if isinstance(value, dict) and value:
            fields.update(_flatten(value, path))
        else:
            # Lists, empty objects, false, zero, and null are ordinary values.
            fields[path] = value
    return fields


def _assign(record, path, value):
    if not isinstance(path, str) or not path.startswith('/'):
        raise ValueError('Event table columns must be JSON Pointer field paths')
    parts = [part.replace('~1', '/').replace('~0', '~')
             for part in path[1:].split('/')]
    target = record
    for part in parts[:-1]:
        target = target.setdefault(part, {})
        if not isinstance(target, dict):
            raise ValueError('Conflicting event table field paths')
    if parts[-1] in target:
        raise ValueError('Repeated event table field path')
    target[parts[-1]] = deepcopy(value)


def encode_summary(summary):
    """Encode repeated records only when the complete representation is smaller.

    Input and actor scoping are unchanged. The original object is returned when
    encoding saves no compact-JSON characters; successful encoding owns a copy.
    Original evidence remains independently inspectable through existing APIs.
    """
    if not isinstance(summary, dict) or _is_encoded(summary):
        return summary
    from .communication_codec import encode_records

    body = dict(summary)
    sections = []
    for key, value in summary.items():
        if (isinstance(value, list) and len(value) > 1
                and all(isinstance(record, dict) for record in value)):
            table = encode_records([_flatten(record) for record in value])
            if isinstance(table, dict):
                body[key] = table
                sections.append(key)
    if not sections:
        return summary
    encoded = {'event_summary_encoding': VERSION, 'format': FORMAT,
               'table_sections': sections, 'summary': body}
    return deepcopy(encoded) if len(_json(encoded)) < len(_json(summary)) else summary


def _is_encoded(value):
    return (isinstance(value, dict) and set(value) == _ENVELOPE
            and value.get('format') == FORMAT)


def decode_summary(encoded):
    """Reconstruct an encoded summary exactly, or return a literal unchanged."""
    if not _is_encoded(encoded):
        return encoded
    if type(encoded['event_summary_encoding']) is not int or encoded['event_summary_encoding'] != VERSION:
        raise ValueError('Unsupported event summary encoding version')
    from .communication_codec import decode_records

    sections = encoded['table_sections']
    if (not isinstance(encoded['summary'], dict) or not isinstance(sections, list)
            or not all(isinstance(section, str) for section in sections)
            or len(sections) != len(set(sections))):
        raise ValueError('Invalid event summary table sections')
    result = deepcopy(encoded['summary'])
    for section in sections:
        if section not in result:
            raise ValueError('Missing event summary table section')
        records = decode_records(result[section])
        if not isinstance(records, list) or not all(isinstance(record, dict) for record in records):
            raise ValueError('Invalid event summary table records')
        result[section] = []
        for flattened in records:
            record = {}
            for path, value in flattened.items():
                _assign(record, path, value)
            result[section].append(record)
    return result
