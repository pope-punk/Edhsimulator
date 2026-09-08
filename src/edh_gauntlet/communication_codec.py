"""Lossless, presentation-only tables for already authorized JSON projections.

The codec does no visibility filtering, state comparison, or gameplay inference.
Inputs and decoded outputs are independent deep copies. Encoders select a table
only when its complete JSON representation is smaller than the original.
"""
from collections import Counter
from copy import deepcopy
import json


RECORD_GUIDANCE = (
    "Rows follow columns, omitting values supplied by defaults. Optional layout "
    "(or layouts[row]) lists present column indices in original order; otherwise "
    "use all columns. Missing columns are absent, not null."
)
BOARD_GUIDANCE = (
    "Only table_paths identify battlefield tables; other board data is unchanged. "
    + RECORD_GUIDANCE
)
CHANGE_GUIDANCE = (
    RECORD_GUIDANCE + " A path [i,suffix] means prefixes[i]+suffix verbatim; "
    "strings are complete JSON pointers. Before and after retain their direction."
)


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _size(value):
    return len(_json(value).encode('utf-8'))


def _smaller(original, packed):
    return packed if _size(packed) < _size(original) else deepcopy(original)


def _records(rows):
    return (isinstance(rows, list) and bool(rows) and
            all(isinstance(row, dict) and all(isinstance(key, str) for key in row)
                for row in rows))


def _table(rows):
    """Build the shared grammar, including exact per-record key order."""
    columns = list(dict.fromkeys(key for row in rows for key in row))
    indices = {key: index for index, key in enumerate(columns)}
    orders = [tuple(indices[key] for key in row) for row in rows]
    layout = Counter(orders).most_common(1)[0][0]
    # JSON equality preserves value types (False != 0), nested key order and -0.
    defaults = {
        key: deepcopy(rows[0][key]) for key in rows[0]
        if all(key in row and _json(row[key]) == _json(rows[0][key]) for row in rows)
    }
    result = {'columns': columns}
    if defaults:
        result['defaults'] = defaults
    if layout != tuple(range(len(columns))):
        result['layout'] = list(layout)
    result['rows'] = [[deepcopy(value) for key, value in row.items() if key not in defaults]
                      for row in rows]
    exceptions = {str(index): list(order) for index, order in enumerate(orders) if order != layout}
    if exceptions:
        result['layouts'] = exceptions
    return result


def _expand(table):
    columns = table['columns']
    defaults = table.get('defaults', {})
    layout = table.get('layout', list(range(len(columns))))
    layouts = table.get('layouts', {})
    result = []
    for index, values in enumerate(table['rows']):
        order = layouts.get(str(index), layout)
        if len(order) != len(set(order)) or any(
                not isinstance(column, int) or isinstance(column, bool) or
                column < 0 or column >= len(columns) for column in order):
            raise ValueError('Invalid record column layout')
        expected = sum(columns[column] not in defaults for column in order)
        if len(values) != expected:
            raise ValueError('Record values do not match their column layout')
        iterator = iter(values)
        result.append({columns[column]: deepcopy(defaults[columns[column]]
                       if columns[column] in defaults else next(iterator)) for column in order})
    return result


def encode_records(rows):
    """Compact a heterogeneous list of records without changing any field."""
    if not _records(rows):
        return deepcopy(rows)
    packed = {'encoding': 'record_columns_v1', 'read': RECORD_GUIDANCE, **_table(rows)}
    return _smaller(rows, packed)


def decode_records(value):
    """Expand a record table, or copy an unencoded value."""
    if isinstance(value, dict) and value.get('encoding') == 'record_columns_v1':
        return _expand(value)
    return deepcopy(value)


def _escape(segment):
    return segment.replace('~', '~0').replace('/', '~1')


def _segments(pointer):
    if pointer == '':
        return []
    if not isinstance(pointer, str) or not pointer.startswith('/'):
        raise ValueError('Invalid JSON pointer')
    return [segment.replace('~1', '/').replace('~0', '~') for segment in pointer[1:].split('/')]


def _locate(value, pointer):
    for segment in _segments(pointer):
        value = value[int(segment)] if isinstance(value, list) else value[segment]
    return value


def _replace(value, pointer, replacement):
    segments = _segments(pointer)
    if not segments:
        return replacement
    parent = value
    for segment in segments[:-1]:
        parent = parent[int(segment)] if isinstance(parent, list) else parent[segment]
    key = int(segments[-1]) if isinstance(parent, list) else segments[-1]
    parent[key] = replacement
    return value


def encode_board(board):
    """Table battlefield lists; do not transform hands or other private data.

    The board may use a mapping or a list of players. Only their direct
    battlefield fields (and a top-level battlefield) are eligible.
    """
    if not isinstance(board, dict):
        return deepcopy(board)
    candidates = []
    if 'battlefield' in board:
        candidates.append('/battlefield')
    players = board.get('players')
    if isinstance(players, dict):
        candidates.extend('/players/' + _escape(key) + '/battlefield'
                          for key, player in players.items()
                          if isinstance(key, str) and isinstance(player, dict) and 'battlefield' in player)
    elif isinstance(players, list):
        candidates.extend('/players/' + str(index) + '/battlefield'
                          for index, player in enumerate(players)
                          if isinstance(player, dict) and 'battlefield' in player)
    result = deepcopy(board)
    paths = []
    for path in candidates:
        rows = _locate(board, path)
        if not _records(rows):
            continue
        table = _table(rows)
        if _size(table) < _size(rows):
            result = _replace(result, path, table)
            paths.append(path)
    if not paths:
        return result
    packed = {'encoding': 'board_columns_v1', 'read': BOARD_GUIDANCE,
              'table_paths': paths, 'board': result}
    return _smaller(board, packed)


def decode_board(value):
    """Expand only explicitly declared tables; never infer one from card data."""
    if not (isinstance(value, dict) and value.get('encoding') == 'board_columns_v1'):
        return deepcopy(value)
    result = deepcopy(value['board'])
    for path in value['table_paths']:
        result = _replace(result, path, _expand(_locate(result, path)))
    return result


def _prefix_paths(rows):
    """Intern useful shared pointer prefixes without decoding their segments."""
    paths = {index: row['path'] for index, row in enumerate(rows) if 'path' in row}
    candidates = {}
    for index, path in paths.items():
        if not path.startswith('/'):
            continue
        segments = path.split('/')
        for stop in range(2, len(segments)):
            prefix = '/'.join(segments[:stop])
            if len(prefix) > 8:
                candidates.setdefault(prefix, set()).add(index)
    unused = set(paths)
    prefixes = []
    replacements = {}
    while candidates:
        # A prefix has an entry cost and an index/suffix cost per occurrence.
        prefix, members = max(candidates.items(), key=lambda pair:
                              len(pair[1] & unused) * (len(pair[0]) - 8) - len(pair[0]) - 4)
        members = members & unused
        gain = len(members) * (len(prefix) - 8) - len(prefix) - 4
        if gain <= 0:
            break
        reference = len(prefixes)
        prefixes.append(prefix)
        for index in members:
            replacements[index] = [reference, paths[index][len(prefix):]]
        unused -= members
        del candidates[prefix]
    return prefixes, replacements


def encode_changes(rows):
    """Compact ordered factual changes; before/after and presence stay exact."""
    if not _records(rows) or any('path' in row and not isinstance(row['path'], str) for row in rows):
        return deepcopy(rows)
    prefixes, replacements = _prefix_paths(rows)
    changed = deepcopy(rows)
    for index, path in replacements.items():
        changed[index]['path'] = path
    packed = {'encoding': 'change_columns_v1', 'read': CHANGE_GUIDANCE}
    if prefixes:
        packed['prefixes'] = prefixes
    packed.update(_table(changed))
    return _smaller(rows, packed)


def decode_changes(value):
    """Expand pointer prefixes by literal concatenation; do not apply a diff."""
    if not (isinstance(value, dict) and value.get('encoding') == 'change_columns_v1'):
        return deepcopy(value)
    rows = _expand(value)
    prefixes = value.get('prefixes', [])
    for row in rows:
        path = row.get('path')
        if isinstance(path, list):
            if (len(path) != 2 or not isinstance(path[0], int) or isinstance(path[0], bool)
                    or path[0] < 0 or path[0] >= len(prefixes) or not isinstance(path[1], str)):
                raise ValueError('Invalid compressed change path')
            row['path'] = prefixes[path[0]] + path[1]
    return rows
