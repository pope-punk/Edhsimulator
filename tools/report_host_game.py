"""Summarize collected host metadata; never render live seat content."""
import argparse
import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path
from analyze_cache_probe import analyze


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def stats(values):
    values = sorted(values)
    return {'n': len(values), 'median': round(statistics.median(values), 3) if values else None,
            'p90': round(values[min(len(values)-1, int(.9*len(values)))], 3) if values else None,
            'max': round(max(values), 3) if values else None}


def report(cohort, game_number, output):
    game = cohort / f'game_{game_number:02d}'
    events = [json.loads(line) for line in (output/'timing.jsonl').read_text().splitlines()]
    cache = analyze(events)
    packets, starts = {}, {}
    decisions, handoffs, planners = [], [], []
    last = None
    for event in events:
        tid, kind = event.get('thread'), event['event']
        if kind == 'packet' and event.get('decision_id'):
            packets[tid] = event
            if last and last.get('actor') != event.get('actor'):
                handoffs.append(event['epoch']-last['epoch'])
            last = None
        elif kind == 'tool_arrived' and event.get('tool') == 'edh_act':
            packet = packets.pop(tid, None)
            if packet:
                decisions.append(event['epoch']-packet['epoch'])
            last = event
        elif kind == 'turn_request' and event.get('role') in {'planner','short_term_planner','long_term_planner'}:
            starts[tid] = event['epoch']
        elif kind == 'turn_completed' and tid in starts:
            planners.append(event['epoch']-starts.pop(tid))
    failure_keys = ('actor', 'role', 'validation_sections', 'publication_stage', 'error_sha256')
    failures = [{k: e.get(k) for k in failure_keys} for e in events
                if e['event'] == 'tool_returned' and e.get('success') is False]
    snoozes, stages, approvals = Counter(), Counter(), Counter()
    accepted = batch_steps = 0
    for line in (game/'decisions.jsonl').read_text().splitlines():
        row = json.loads(line)
        accepted += 1
        aux = row.get('auxiliary_payload', {})
        mode = aux.get('scheduler', {}).get('mode')
        if mode:
            snoozes[mode] += 1
        batch_steps += bool(aux.get('batch'))
    for path in (game/'continuity/stage_publications').glob('*.json'):
        stages[read(path)['stage']] += 1
    for path in (game/'handoffs/sequences/approvals').glob('*.json'):
        approval = read(path).get('approval', {})
        approvals['batches'] += 1
        for key in ('approve', 'reject', 'add', 'overrides'):
            approvals[key] += len(approval.get(key, []))
    memory = [json.loads(line) for line in (output/'memory.jsonl').read_text().splitlines()]
    files = sorted([{'path': str(p.relative_to(game)), 'bytes': p.stat().st_size}
                    for p in game.rglob('*') if p.is_file()], key=lambda r: r['bytes'], reverse=True)
    launch = read(output/'launch.json')
    active_seconds = max(e['epoch'] for e in events)-datetime.fromisoformat(launch['launched_utc'].replace('Z', '+00:00')).timestamp()
    result = {
        'game': game_number, 'accepted': accepted, 'active_runtime_seconds': round(active_seconds, 3),
        'scope': {'timing_segment':str(output),'segment_end_accepted':read(output/'collection.json')['accepted'],
                  'artifact_counts':'cumulative at report time; see accepted'},
        'decision_seconds': stats(decisions), 'handoff_seconds': stats(handoffs),
        'planner_turn_seconds': stats(planners), 'cache_groups': cache['groups'], 'failures': failures,
        'context_tokens': {role: stats([r['usage']['inputTokens'] for r in cache['requests']
                                       if r.get('role') == role and 'inputTokens' in r['usage']])
                           for role in ('decider','planner','short_term_planner','long_term_planner','diplomacy')},
        'misses': [{k: r.get(k) for k in ('actor', 'role', 'origin', 'decision_id', 'seconds', 'usage')}
                   for r in cache['requests'] if r.get('usage', {}).get('cachedInputTokens') == 0],
        'incomplete_usage_samples': len(cache['incomplete_requests']),
        'scheduler_directives': dict(snoozes), 'published_stages': dict(stages),
        'batch_approvals': dict(approvals), 'batch_executed_decisions': batch_steps,
        'memory_summed_working_set_bytes': stats([r['summed_working_set_bytes'] for r in memory
                                                 if r.get('summed_working_set_bytes') is not None]),
        'memory_coverage': {'samples': len(memory),
                            'unavailable': sum(r.get('summed_working_set_bytes') is None for r in memory)},
        'largest_game_files': files[:10], 'game_file_count': len(files),
        'game_total_bytes': sum(r['bytes'] for r in files), 'collection': read(output/'collection.json'),
        'terminal': read(game/'terminal_result.json') if (game/'terminal_result.json').exists() else None,
        'host_metrics': read(output/'metrics.json'),
    }
    config = read(game/'game_config.json')
    status = read(game/'status.json')
    result['learning'] = {'enabled': config.get('learning_enabled', True),
                          'state': status.get('postgame_review', {}).get('state', 'not_ready')}
    application = game/'postgame_learning/application_0001.json'
    if application.exists():
        audit = read(application)
        result['learning'].update({k: audit.get(k) for k in ('applied_at', 'review_disposition', 'result_revision')})
        result['learning']['operation_count'] = len(audit.get('operations', []))
    (output/'summary.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf8')
    print(json.dumps({k: result[k] for k in ('game', 'accepted', 'active_runtime_seconds', 'decision_seconds',
                                           'planner_turn_seconds', 'cache_groups', 'failures', 'published_stages')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort', type=Path, required=True)
    parser.add_argument('--game', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report(args.cohort, args.game, args.output)
