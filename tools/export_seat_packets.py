"""Read-only, seat-scoped transcript export. Never dispatches or replays gameplay."""
import argparse
import csv
import hashlib
import html
import io
import json
import os
from pathlib import Path
import sqlite3
import time
import zlib

ROUNDS = {1: (1, 4), 5: (17, 20), 7: (25, 28)}
FIELDS = ['decision #', 'turn #', 'active seat', 'phase', 'stack contents',
          'sender', 'recipient', 'type', 'rationale', 'length', 'hyperlink to copy',
          'timestamp UTC', 'role', 'inference turn', 'context basis', 'record ID', 'source']


def decode(blob):
    return json.loads(zlib.decompress(blob))


def atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(text, encoding='utf8')
    temp.replace(path)


def safe_cell(value):
    # Only the exporter-generated hyperlink column is allowed to be a formula.
    text = str(value)
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text


def text_parts(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for row in value:
            yield from text_parts(row)
    elif isinstance(value, dict):
        if isinstance(value.get('text'), str):
            yield value['text']


def objects(text):
    """Decode complete JSON text blocks, never execute model-authored code."""
    if isinstance(text,str) and text.startswith('# Pilot working document\n'):
        import re
        count=re.search(r'^Accepted decision count: (\d+)$',text,re.M)
        observation={'sequence':int(count[1]) if count else ''}
        for field in ('turn','stack'):
            section=re.search(r'^## '+field+r'\n([^\n]+)',text,re.M)
            if section:
                try:observation[field]=json.loads(section[1])
                except ValueError:pass # Explicit unchanged section inherits the previous delivery.
        yield {'pilot_document_observation':observation}
        return
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return
    if isinstance(value, dict):
        yield value


def rationales(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ('rationale', 'reason', 'explanation') and isinstance(child, str):
                yield child
            elif key not in ('plans', 'rationales', 'retained_memory', 'previous_board'):
                yield from rationales(child)
    elif isinstance(value, list):
        for child in value:
            yield from rationales(child)


def database(run, actor):
    # One read transaction gives a consistent head/journal/observation snapshot.
    manifest = json.loads((run / 'cohort.json').read_text())
    game = int(manifest['active_game'])
    db = sqlite3.connect(f'file:{run / f"game_{game:02}" / "rules.sqlite"}?mode=ro', uri=True)
    db.execute('BEGIN')
    observations = {}
    revisions = {}
    supervisors = []
    for evidence_id, kind, sequence, blob in db.execute(
            'SELECT seq,kind,rules_seq,payload FROM host_evidence WHERE actor=? ORDER BY seq', (actor,)):
        if kind not in ('observation', 'help_request', 'help_answer'):
            continue
        value = decode(blob)
        if kind == 'observation':
            # Retain only public board context, not hidden zones/library.
            observations[sequence] = {k: value.get(k) for k in ('turn', 'stack', 'revision')}
            revisions[value['revision']] = sequence
        else:
            supervisors.append((evidence_id, kind, sequence, value))
    threads = {}
    for blob, in db.execute('SELECT payload FROM host_journal ORDER BY seq'):
        for change in decode(blob)['state']:
            if len(change) < 3 or 'registrations' not in change[1]:
                continue
            path, value = change[1], change[2]
            keys = [k for k in path if isinstance(k, str) and k.startswith(actor + '::')]
            if not keys:
                continue
            role = keys[0].split('::', 1)[1]
            if isinstance(value, dict) and value.get('thread'):
                threads[value['thread']] = role
            elif path[-1] == 'thread' and isinstance(value, str):
                threads[value] = role
    state = json.loads(db.execute('SELECT value FROM host_state').fetchone()[0])
    for key, value in state['registrations'].items():
        if key.startswith(actor + '::'):
            threads[value['thread']] = value['role']
    head = state['last_rules_commit']
    db.close()
    return game, observations, revisions, supervisors, threads, head


def context_packet(value, current, boards, revisions):
    """Use a primary delivered board, never a historical board nested in a plan."""
    from edh_gauntlet.rules_adapter import digest
    from edh_gauntlet.primitive_journal import apply
    from edh_gauntlet.communications import expand_board
    from copy import deepcopy
    if 'pilot_document_observation' in value:
        return {**current,**value['pilot_document_observation'],'basis':'delivered pilot document (may lag live play)'}
    candidates = [value]
    if isinstance(value.get('next'), dict):
        candidates.append(value['next'])
    for candidate in candidates:
        board = candidate.get('board')
        if not isinstance(board, dict):
            continue
        if board.get('encoding') == 'primitive_board_delta_v1':
            base = boards.get(board['base_id'])
            if base is None:
                raise ValueError('Missing recorded primitive board baseline')
            board = apply(deepcopy(base), board['changes'])
            if digest(board) != candidate['board']['board_id']:
                raise ValueError('Recorded board delta checksum mismatch')
        elif board.get('encoding') == 'board_delta_v1':
            board = expand_board(board, boards.get(candidate['board']['from_snapshot']))
        else:
            board = expand_board(board)
        if not isinstance(board.get('turn'), dict):
            continue
        boards[digest(board)] = board
        if candidate.get('snapshot'):
            boards[candidate['snapshot']] = board
        revision = board.get('revision', candidate.get('revision'))
        current = {'turn': board['turn'], 'stack': board.get('stack', []),
                   'sequence': revisions.get(revision, ''),
                   'basis': 'delivered board snapshot (may lag live play)'}
    return current


def round_for(turn):
    # Opening-hand/initial-planner context is an explicitly labelled prelude.
    if turn == 0:
        return 1
    for number, (first, last) in ROUNDS.items():
        if first <= turn <= last:
            return number
    return None


def packet_html(raw, record_id, previous, metadata):
    link = f'<a href="{previous}.html">Previous packet in this role conversation</a>' if previous else ''
    return ('<!doctype html><meta charset="utf-8"><title>Seat packet ' + record_id + '</title>'
            '<style>body{font:16px system-ui;margin:2rem;max-width:1100px}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
            '<a href="../index.html">Round exports</a> · ' + link + '<h1>Original recorded packet</h1>'
            '<p>' + html.escape(metadata) + '</p><button onclick="navigator.clipboard.writeText(document.querySelector(\'pre\').textContent)">Copy packet</button>'
            '<pre>' + html.escape(raw) + '</pre>')


def export(run, output, sessions, actor='Reaminatour'):
    game, observations, revisions, supervisors, threads, head = database(run, actor)
    rows = {n: [] for n in ROUNDS}
    missing, errors, opaque = [], [], 0
    paths = list(sessions.rglob('rollout-*.jsonl'))
    files = {thread: next((p for p in paths if p.name.endswith(thread + '.jsonl')), None) for thread in threads}
    all_count = 0

    def add(record_id, role, kind, sender, recipient, raw, payload, context, timestamp, inference, source, previous):
        nonlocal all_count
        all_count += 1
        turn = (context.get('turn') or {}).get('number')
        metadata = f'{actor} / {role}; {kind}; {timestamp}; input-context turn {turn}'
        path = output / 'packets' / (record_id + '.html')
        rendered = packet_html(raw, record_id, previous, metadata)
        if not path.exists() or path.read_text(encoding='utf8') != rendered:
            atomic(path, rendered)
        number = round_for(turn) if isinstance(turn, int) else None
        if number is None:
            return
        why = list(dict.fromkeys(rationales(payload)))
        # Tool code is retained verbatim in the copy; only extract quoted rationale literals.
        if kind.startswith(('custom_tool_call/', 'function_call/')):
            import re
            code = payload.get('input', payload.get('arguments', ''))
            for match in re.finditer(r'\b(?:rationale|reason)\s*:\s*("(?:[^"\\]|\\.)*")', code):
                try: why.append(json.loads(match[1]))
                except ValueError: pass
        t = context.get('turn') or {}
        row = [context.get('sequence', ''), turn, t.get('active', ''), t.get('phase') or 'opening/setup',
               json.dumps(context.get('stack', []), ensure_ascii=False), sender, recipient, kind,
               '\n'.join(dict.fromkeys(why)), len(raw.encode('utf8')),
               f'=HYPERLINK("packets/{record_id}.html","Open packet")', timestamp,
               role, inference, context.get('basis', 'unknown'), record_id, source]
        rows[number].append(row)

    for thread, role in sorted(threads.items()):
        path = files[thread]
        if path is None:
            missing.append({'thread': thread, 'role': role})
            continue
        entries = []
        for line_number, line in enumerate(path.read_text(encoding='utf8').splitlines(), 1):
            try: value = json.loads(line)
            except ValueError:
                errors.append({'source': str(path), 'line': line_number, 'error': 'Incomplete JSON line; retry on next poll'})
                break
            entries.append((line_number, line.rstrip('\n'), value))
        current, boards = {}, {}
        first_context = None
        inference_contexts = {}
        pre_boards, pre_context, pre_inference = {}, {}, ''
        # Bind setup/configuration to the first actual packet of that inference,
        # including configuration records written just before a round boundary.
        for _, _, value in entries:
            p = value.get('payload', {})
            if value.get('type') == 'turn_context':
                pre_inference = p.get('turn_id', pre_inference)
            pre_inference = p.get('internal_chat_message_metadata_passthrough', {}).get('turn_id', pre_inference)
            if value.get('type') != 'response_item':
                continue
            if p.get('role') != 'user' and not p.get('type', '').endswith('_output'):
                continue
            for text in text_parts(p.get('content', p.get('output', []))):
                for obj in objects(text):
                    before = pre_context
                    try: pre_context = context_packet(obj, pre_context, pre_boards, revisions)
                    except (ValueError, KeyError, TypeError): continue
                    if pre_context and pre_context is not before:
                        if first_context is None: first_context = pre_context
                        inference_contexts.setdefault(pre_inference, pre_context)
        current = first_context or {}
        if current:
            current = dict(current, basis='first delivered snapshot; initialization context')
        previous = None
        inference = ''
        for line_number, raw, value in entries:
            p = value.get('payload', {})
            typ = value.get('type')
            kind = p.get('type', typ)
            timestamp = value.get('timestamp', '')
            if typ == 'turn_context':
                inference = p.get('turn_id', inference)
            if typ == 'session_meta':
                # Only inference-facing setup; exclude unrelated session/user metadata.
                p = {k: p[k] for k in ('base_instructions', 'dynamic_tools') if k in p}
                raw = json.dumps(p, ensure_ascii=False, indent=2)
                kind = 'session_instructions_and_tools'
            elif typ == 'response_item':
                if kind == 'reasoning':
                    opaque += 1
                    continue  # encrypted internal reasoning is not readable packet evidence
                if kind not in ('message', 'custom_tool_call', 'custom_tool_call_output', 'function_call', 'function_call_output'):
                    continue
            elif typ not in ('turn_context', 'compacted'):
                continue  # event_msg duplicates response items; no double counting
            inference = p.get('internal_chat_message_metadata_passthrough', {}).get('turn_id', inference)
            if typ == 'turn_context' or p.get('role') in ('system', 'developer'):
                current = inference_contexts.get(inference, current)
            incoming = kind.endswith('_output') or p.get('role') in ('user', 'system', 'developer') or typ != 'response_item'
            if incoming:
                for text in text_parts(p.get('content', p.get('output', []))):
                    for obj in objects(text):
                        try: current = context_packet(obj, current, boards, revisions)
                        except (ValueError, KeyError, TypeError) as exc:
                            errors.append({'source': str(path), 'line': line_number, 'error': str(exc)})
                            current = {}  # do not attribute a new undecodable input to an old board
            if kind in ('custom_tool_call', 'function_call'):
                import re
                tool_names = re.findall(r'\btools\.(edh_\w+)\s*\(', p.get('input', ''))
                display_kind = kind + '/' + ','.join(dict.fromkeys(tool_names or [p.get('name', 'unknown')]))
            else:
                display_kind = kind
            endpoint = actor + '/' + role
            sender, recipient = ('host/runtime', endpoint) if incoming else (endpoint, 'host/tools' if 'call' in kind else 'host/runtime')
            record_id = hashlib.sha256(f'{thread}:{line_number}'.encode()).hexdigest()[:24]
            add(record_id, role, display_kind, sender, recipient, raw, p, current,
                timestamp, inference, f'{path.name}:{line_number}', previous)
            previous = record_id

    for evidence_id, kind, sequence, value in supervisors:
        obs = observations.get(sequence, {})
        context = {'turn': obs.get('turn'), 'stack': obs.get('stack', []), 'sequence': sequence,
                   'basis': 'exact rules prefix of supervisor record; delivery separately recorded in role transcript'}
        record_id = f'help-{evidence_id}'
        raw = json.dumps(value, ensure_ascii=False, indent=2)
        sender, recipient = ('rules supervisor', actor + '/decider') if kind == 'help_answer' else (actor + '/decider', 'rules supervisor')
        add(record_id, 'decider', 'supervisor_record/' + kind, sender, recipient,
            raw, value, context, '', '', f'host_evidence:{evidence_id}', None)

    latest_turn = (observations[max(observations)]['turn'] or {}).get('number', 0)
    counts = {}
    for number, data in rows.items():
        data.sort(key=lambda r: (int(r[1]), r[11] or '9999', r[15]))
        stream = io.StringIO(newline=''); writer = csv.writer(stream)
        writer.writerow(FIELDS)
        for row in data:
            writer.writerow([v if i == 10 else safe_cell(v) for i, v in enumerate(row)])
        atomic(output / f'round-{number}.csv', stream.getvalue())
        counts[number] = {'rows': len(data), 'turns': ROUNDS[number],
                          'status': 'window_passed' if latest_turn > ROUNDS[number][1] else 'collecting' if latest_turn >= ROUNDS[number][0] else 'not_reached'}
    manifest = {'run': run.name, 'game': game, 'actor': actor, 'accepted_prefix': head,
                'latest_turn': latest_turn, 'rounds': counts, 'registered_conversations': len(threads),
                'source_packet_copies': all_count, 'missing_transcripts': missing, 'decode_errors': errors,
                'opaque_reasoning_records_not_exported': opaque,
                'updated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    atomic(output / 'manifest.json', json.dumps(manifest, indent=2) + '\n')
    description = f'''# {actor} packet audit — {run.name}

These are communication-audit exports, not game-result/cardwise CSVs. No game commands are executed.

* Round 1: turns 1–4, plus explicitly labelled turn-0 opening/setup inputs.
* Round 5: turns 17–20. Round 7: turns 25–28.
* One row per preserved response item, plus inference configuration and supervisor help records.
* **Turn, phase, stack and decision # describe the latest board delivered to this role, not an asserted live board at wall-clock output time.** Planner snapshots can lag play. Round membership follows that input context. `decision #` is the global accepted prefix at that snapshot when a revision is available; blank means unavailable, not zero. Diplomat public boards may omit revisions.
* Timestamp is the recorded transcript timestamp. Supervisor database records have exact prefixes but no timestamps; their timestamp cells are blank.
* Length is UTF-8 bytes of the linked original JSON record (including its envelope), not tokenizer-measured tokens or cumulative inference context size.
* Hyperlinks open escaped local HTML copies. Keep the `packets` folder beside the CSVs; download/extract the entire directory. Each packet links to the previous packet in that physical role conversation, including intervening rounds, so retained context can be inspected.
* Plans and diplomat/table messages are included **as actually delivered inside packets**, not falsely counted as separate model calls. Tool calls include rejected inputs and waiting/poll calls. Passes are not filtered from this audit.
* Technical-help request/answer records supplement the actual model deliveries and are labelled `supervisor_record`; a recorded answer alone does not prove the pilot received it.
* Transcript event mirrors are excluded to avoid counting the same message twice. Encrypted internal reasoning is not readable; it is counted in the manifest but not exported or reconstructed. System content not preserved by the transport cannot be recovered. Retained context is not re-labelled as freshly sent on each inference turn.
* Source copies include all available recorded packets in the selected seat's registered conversations, so earlier retained instructions/references remain reachable. No other seat's private transcript is read.
* Review `manifest.json` for missing transcripts, decoding gaps and incomplete windows. `window_passed` means the game passed the selected turns, not that there were no capture limitations.
'''
    atomic(output / 'README.md', description)
    links = ''.join(f'<li><a href="round-{n}.csv">Round {n} CSV</a>: {v["rows"]} rows — {v["status"]}</li>' for n, v in counts.items())
    atomic(output / 'index.html', '<!doctype html><meta charset="utf-8"><title>Reaminatour packet audit</title><h1>' + html.escape(actor + ' — ' + run.name) + '</h1><ul>' + links + '</ul><pre>' + html.escape(description) + '</pre>')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sessions', type=Path, default=Path.home() / '.codex/sessions')
    parser.add_argument('--actor', default='Reaminatour')
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--interval', type=float, default=30)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    import fcntl
    with (args.output / '.collector.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        atomic(args.output / 'collector.json', json.dumps({'pid': os.getpid(), 'run': str(args.cohort.resolve())}))
        while True:
            result = export(args.cohort.resolve(), args.output.resolve(), args.sessions, args.actor)
            print(json.dumps({k: result[k] for k in ('latest_turn', 'rounds', 'missing_transcripts', 'decode_errors')}), flush=True)
            if not args.watch or (args.output / 'STOP').exists():
                break
            time.sleep(max(1, args.interval))


if __name__ == '__main__':
    main()
