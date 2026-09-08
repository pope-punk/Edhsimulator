"""Durable claims, immutable reads and metadata-only stalled-handoff diagnostics."""
from __future__ import annotations

import argparse
import json
import inspect
from pathlib import Path
from .paths import PROJECT_ROOT
import time
import statistics

from . import pilot_handoff, planner_runtime
from .runtime_store import locked, read, write, identity, get, put, checked_id, serialized


def directory_for(root, game):
    return Path(root) / f'game_{game:02d}' / 'handoffs'


def _current(root):
    return read(Path(root) / 'NEXT_ACTION.json', {}).get('next_action', {})


def _route_path(directory, route_id):
    return directory / 'routes' / (checked_id(route_id) + '.json')


def _input(directory,claim):
    value=get(directory/'inputs',claim['input_id'])
    if 'continuity_id' in value:
        attachment=get(directory/'attachments',value.pop('continuity_id'))
        value['continuity']=attachment
        if value.pop('plan_presentation', None) == 1:
            from . import pilot_plan_packet
            plan = None
            if attachment.get('plan_id'):
                # Use the claimed immutable version, never the current mailbox.
                plan = planner_runtime.load_plan(directory.parent/'continuity', attachment['plan_id'])
            value['brief'] = pilot_plan_packet.render(value['brief'], attachment, plan)
        else:
            value['brief']+='\nContinuity from the background planner (no plan-writing or adoption required):\n'+json.dumps(attachment,ensure_ascii=False,separators=(',',':'))+'\n'
    return value


def build_route(root, action):
    from . import campaign, pilot_dispatch
    game = action['game']; actor = action['actor']; directory = directory_for(root, game)
    rows = campaign.read_jsonl(directory.parent / 'decisions.jsonl')
    record = pilot_dispatch.registry(root, game).get(actor)
    compatible = bool(record and pilot_handoff.can_resume_session(record['seat_session'], root, game, actor, rows))
    generations = read(directory / 'generations.json', {})
    generation = generations.get(actor, 1)
    if record and not compatible:
        # Branch identity fences discarded contexts even if a generation was reused.
        generation = max(generation, record.get('generation', 1) + 1)
        generations[actor] = generation; write(directory / 'generations.json', generations)
    binding = {'actor': actor, 'game': game, 'generation': generation,
               'decision_id': action['decision_id'], 'pilot_context_id': action['pilot_context_id'],
               'seat_session': pilot_handoff.session_descriptor(root, game, actor, rows)}
    route_id = identity(binding); path = _route_path(directory, route_id)
    route = read(path)
    agent = pilot_dispatch.agent_target(record['agent']) if compatible else None
    if route is None:
        route = {**binding, 'route_id': route_id, 'state': 'prepared', 'prepared_at': time.time(),
                 'agent': agent, 'wake': 'not_attempted'}
        write(path, route)
    elif agent and route.get('agent') != agent:
        if route.get('agent'):
            raise SystemExit('Route destination changed without fencing its generation.')
        route['agent'] = agent; write(path, route)
    command = (f'python -m edh_gauntlet.pilot_session --cohort "{Path(root).resolve()}" '
               f'--actor "{actor}" --route {route_id} --invocation YOUR_WORK_TURN_UUID')
    policy = PROJECT_ROOT / 'docs/SPLIT_RUNTIME_POLICY.md'
    prompt = ('' if compatible else f'Read {policy} once. ') + (
        'Generate one UUID for this work turn, retain it for retries, then claim/read your seat input: ' + command)
    host_managed=(Path(root)/'HOST_RUNTIME.json').exists()
    if host_managed:prompt='Software host owns dispatch. Do not forward or manually claim this route.'
    return {**binding, 'route_id': route_id, 'kind': 'resume' if compatible else 'spawn',
            'agent': agent, 'mode': 'resume' if compatible else 'fresh',
            'handoff_transport': 'software_host' if host_managed else ('direct_followup_task' if compatible else 'coordinator_spawn'),
            'coordinator_relay_allowed': False, 'prompt': prompt}


def _validate_route(root, actor, route_id, *, allow_stopped_host=False):
    from . import campaign,quarantine
    pause=read(Path(root)/'HOST_PAUSED.json',{})
    if pause and not (allow_stopped_host and pause.get('reason')=='host_stopped'):
        raise SystemExit('Software host is paused; do not dispatch pilots.')
    campaign._require_no_prepared_learning_transaction(root, 'claim a decision')
    action = _current(root)
    if (action.get('kind') != 'dispatch_pilot' or action.get('actor') != actor
            or action.get('dispatch', {}).get('route_id') != route_id):
        raise SystemExit('Route no longer owns the authoritative frontier.')
    directory = directory_for(root, action['game'])
    quarantine.require_clean(campaign.DEFAULT_STRATEGY_FILE,root,action['game'])
    route = read(_route_path(directory, route_id))
    rows = campaign.read_jsonl(directory.parent / 'decisions.jsonl')
    if not route or not pilot_handoff.can_resume_session(route['seat_session'], root, action['game'], actor, rows):
        raise SystemExit('Route belongs to a discarded branch.')
    return action, directory, route


@serialized
def claim_read(root, actor, route_id, invocation_id, *, fresh=False, context_checkpoint=False):
    from . import pilot_session, pilot_dispatch
    if not isinstance(invocation_id, str) or not invocation_id.strip() or len(invocation_id) > 128:
        raise SystemExit('Supply one stable work-turn invocation ID; retain it for read retries.')
    action, directory, route = _validate_route(root, actor, route_id)
    if any((directory.parent/'continuity'/name).exists() for name in ('diplomacy_refresh.json','combo_refresh.json')):
        raise SystemExit('Reconcile the prepared public-post frontier with planner_runtime flush-diplomacy before claiming a decision.')
    if context_checkpoint:
        from . import context_packets
        if not context_packets.enabled(root,action['game']) or not (Path(root)/'HOST_RUNTIME.json').exists():
            raise SystemExit('A context checkpoint requires the enrolled software host.')
    if route.get('claim_id'):
        if context_checkpoint:
            raise SystemExit('A context checkpoint cannot replace an already claimed input.')
        claim = claim_record(directory, route['claim_id'])
        if claim['invocation_id'] != invocation_id:
            raise SystemExit('Another invocation owns this decision. Inspect host status before recovery.')
        return _input(directory,claim)
    record = pilot_dispatch.registry(root, action['game']).get(actor)
    needs_baseline=not record or record.get('bootstrap_required') or action['dispatch']['kind']=='spawn'
    if fresh and record and not needs_baseline:
        raise SystemExit('Registered deciders must retain their own context; recover/fence a lost context first.')
    from . import plan_tiers
    request=pilot_handoff.packet_request(read(Path(action['context'])))
    if not plan_tiers.pilot_ready(root,action['game'],actor,request):
        raise SystemExit('Initial standing plan or opening goal pending; dispatch the planner before claiming this decision.')
    result, renderer, base_hash = pilot_session._presentation(root, action, fresh=fresh or needs_baseline or context_checkpoint)
    if renderer is None:
        return result
    renderer_id=put(directory/'renderers',{'renderer':renderer,'base_hash':base_hash})
    packet = read(Path(action['context']))
    request = pilot_handoff.packet_request(packet)
    saved = read(pilot_session._session_path(root, action), {})
    attachment = planner_runtime.attachment(root, action, request, None if context_checkpoint else saved.get('continuity_plan_id'))
    attachment_id = put(directory / 'attachments', attachment)
    claim_binding = {'schema': 1, 'route_id': route_id, 'invocation_id': invocation_id,
                     'actor': actor, 'game': action['game'], 'generation': route['generation'],
                     'decision_id': action['decision_id'], 'pilot_context_id': action['pilot_context_id'],
                     'renderer_id':renderer_id, 'attachment_id': attachment_id}
    # Input IDs include all displayed text and references. The claim ID is bound
    # to its input without a recursive hash by hashing the binding first.
    claim_id = identity(claim_binding)
    result.update(game=action['game'],claim_id=claim_id, route_id=route_id, invocation_id=invocation_id,
                  continuity=attachment)
    if request.get('planning_contract',1)>=4:
        result.pop('continuity')
        result['continuity_id']=attachment_id
        result['plan_presentation']=1
    else:
        result['brief'] += '\nContinuity from the background planner (no plan-writing or adoption required):\n' + json.dumps(attachment, ensure_ascii=False) + '\n'
    input_id = put(directory / 'inputs', result)
    # The public claim handle hashes its identity binding; the separately checked
    # input digest binds immutable presentation, including the selected plan.
    write(directory / 'claims' / (claim_id + '.json'), {**claim_binding, 'input_id': input_id})
    route.update(claim_id=claim_id,plan_id=attachment.get('plan_id'), state='claimed', claimed_at=time.time(), read_completed_at=time.time())
    write(_route_path(directory, route_id), route)
    return _input(directory,{'input_id':input_id})


def claim_record(directory, claim_id):
    claim = read(directory / 'claims' / (checked_id(claim_id) + '.json'))
    if not claim or identity({k: v for k, v in claim.items() if k != 'input_id'}) != claim_id:
        raise SystemExit('Decision claim missing or corrupted.')
    get(directory / 'inputs', claim['input_id'])
    return claim


def validate_claim(root, actor, claim_id):
    action = _current(root)
    if action.get('kind') != 'dispatch_pilot' or action.get('actor') != actor:
        raise SystemExit('This seat no longer owns a decision.')
    directory = directory_for(root, action['game'])
    claim = claim_record(directory, claim_id)
    action, directory, route = _validate_route(root, actor, claim['route_id'])
    if route.get('claim_id') != claim_id or claim['generation'] != route['generation'] or claim['actor'] != actor:
        raise SystemExit('Decision claim was fenced or belongs to another seat.')
    return action, directory, route, claim


@serialized
def acknowledge(root, actor, claim_id):
    from . import campaign, pilot_session,pilot_dispatch
    action, directory, route, claim = validate_claim(root, actor, claim_id)
    path = pilot_session._session_path(root, action)
    saved = read(path)
    if saved and saved.get('last_claim_id')==claim_id:return claim
    rendered=get(directory/'renderers',claim['renderer_id'])
    if identity(saved)!=rendered['base_hash']:
        raise SystemExit('Claim renderer base changed; recover the current own-seat route.')
    saved={**rendered['renderer'],'last_claim_id':claim_id}
    saved['continuity_plan_id'] = get(directory / 'attachments', claim['attachment_id']).get('plan_id')
    campaign.write_json(path, saved)
    pilot_dispatch.mark_observed(root,action)
    return claim


def validate_answer(root, request, receipt,submitted_arguments):
    """Campaign enforces this gate even if a caller bypasses pilot_session."""
    if not isinstance(receipt, dict) or not receipt.get('claim_id'):
        raise SystemExit('Split-contract decisions must be submitted through a claimed pilot_session.')
    action, directory, route, claim = validate_claim(root, request['actor'], receipt['claim_id'])
    expected = {'claim_id': receipt['claim_id'], 'input_id': claim['input_id'],
                'attachment_id': claim['attachment_id'], 'route_id': claim['route_id'],
                'submission_id': receipt.get('submission_id'), 'payload_digest': receipt.get('payload_digest')}
    if receipt != expected or claim['pilot_context_id'] != request.get('pilot_context_id'):
        raise SystemExit('Runtime answer receipt does not match the frozen decision input.')
    intent = read(directory / 'submissions' / (checked_id(receipt['submission_id']) + '.json'))
    if not intent or intent['receipt'] != receipt:
        raise SystemExit('Submission intent missing or changed.')
    if intent.get('answer_binding')!=identity(submitted_arguments):
        raise SystemExit('Submission content differs from its bound intent.')


@serialized
def submit(root, actor, envelope):
    from . import campaign, pilot_session, pilot_dispatch
    if isinstance(envelope,dict) and 'batch' in envelope:
        from . import sequence_runtime
        return sequence_runtime.submit(root,actor,envelope)
    if not isinstance(envelope, dict) or not isinstance(envelope.get('answer'), dict):
        raise SystemExit('Supply one response with an answer object.')
    claim_id = envelope.get('claim_id')
    # Game is explicit for safe retries after NEXT_ACTION advances to review/a new game.
    game = envelope.get('game')
    if not isinstance(game, int) or isinstance(game, bool):
        raise SystemExit('Split-contract envelopes require game and claim_id from the input.')
    directory = directory_for(root, game)
    claim = claim_record(directory, claim_id)
    if claim['actor'] != actor:
        raise SystemExit('Wrong-seat claim.')
    for key in ('actor', 'decision_id', 'pilot_context_id'):
        if envelope.get(key) != claim[key]:
            raise SystemExit('Response identity does not match ' + key)
    if set(envelope['answer']) & {'runtime_receipt','pilot_context','game_number','root'}:
        raise SystemExit('Runtime metadata is supplied by the adapter.')
    payload_digest = identity(envelope['answer'])
    submission_id = identity({'claim_id': claim_id, 'payload_digest': payload_digest})
    rows = campaign.read_jsonl(directory.parent / 'decisions.jsonl')
    prior = next((row for row in rows if row.get('auxiliary_payload', {}).get('runtime', {}).get('submission_id') == submission_id), None)
    if prior:
        # Tape acceptance is authoritative even if the process died before the
        # status checkpoint. Reconcile only when NEXT_ACTION is still behind.
        current = _current(root)
        if current.get('decision_id') == claim['decision_id'] and current.get('game') == game:
            campaign.advance(root, game)
        route=read(_route_path(directory,claim['route_id']))
        if route and route.get('state')!='completed':
            route.update(state='completed',completed_at=time.time(),submission_id=submission_id,recovered_commit=True)
            write(_route_path(directory,claim['route_id']),route)
        return {'state': 'already_accepted', 'game':game,'submission_id': submission_id, 'invocation_id': claim['invocation_id']}
    if any(row.get('decision_id')==claim['decision_id'] for row in rows):
        raise SystemExit('This decision already accepted a different submission.')
    action, directory, route, claim = validate_claim(root, actor, claim_id)
    receipt = {'claim_id': claim_id, 'input_id': claim['input_id'], 'attachment_id': claim['attachment_id'],
               'route_id': claim['route_id'], 'submission_id': submission_id, 'payload_digest': payload_digest}
    acknowledge(root, actor, claim_id)
    answer = dict(envelope['answer']); answer['pilot_context'] = claim['pilot_context_id']
    answer['runtime_receipt'] = receipt
    for key in ('snooze_table', 'snooze_objects'):
        if isinstance(answer.get(key), dict):answer[key] = json.dumps(answer[key])
    try:
        bound=inspect.signature(campaign.answer).bind(root,**answer)
    except TypeError as error:
        raise ValueError('Invalid answer fields: '+str(error)+'. Use the answer fields from your packet; snooze directives are top-level answer fields.') from error
    bound.apply_defaults()
    write(directory/'submissions'/(submission_id+'.json'),{'receipt':receipt,
        'answer_binding':identity({key:value for key,value in bound.arguments.items()
                                  if key not in {'root','pilot_context','runtime_receipt'}})})
    route.update(state='submitting', submitting_at=time.time())
    write(_route_path(directory, claim['route_id']), route)
    try:
        campaign.answer(root, **answer)
    except BaseException:
        # A crash after tape acceptance is uncertain, not a rejected decision.
        accepted = any(row.get('auxiliary_payload', {}).get('runtime', {}).get('submission_id') == submission_id
                       for row in campaign.read_jsonl(directory.parent / 'decisions.jsonl'))
        route['state'] = 'accepted_pending_checkpoint' if accepted else 'claimed'
        write(_route_path(directory, claim['route_id']), route)
        raise
    route.update(state='completed', completed_at=time.time(), submission_id=submission_id)
    write(_route_path(directory, claim['route_id']), route)
    pilot_dispatch.mark_observed(root, action)
    return {'state': 'accepted', 'game':game,'submission_id': submission_id, 'invocation_id': claim['invocation_id']}


@serialized
def wake_result(root, route_id, *, attempt_id, outcome):
    if outcome not in {'accepted', 'unknown', 'rejected'} or not attempt_id:
        raise SystemExit('Record an attempt ID and accepted/unknown/rejected outcome.')
    action = _current(root)
    _, directory, route = _validate_route(root, action.get('actor'), route_id)
    route.setdefault('wake_attempts', {})[attempt_id] = {'outcome': outcome, 'at': time.time()}
    route['wake'] = outcome
    write(_route_path(directory, route_id), route)
    return {'route_id': route_id, 'wake': outcome, 'state': route['state']}


def status(root, *, now=None):
    """Read tiny metadata only; thresholds request investigation, never restart."""
    action = _current(root); game = action.get('game')
    result = {'schema': 1, 'action': action.get('kind'), 'game': game, 'alerts': []}
    if action.get('kind') != 'dispatch_pilot' or not action.get('dispatch', {}).get('route_id'):
        return result
    route_id = action['dispatch']['route_id']; directory = directory_for(root, game)
    route = read(_route_path(directory, route_id), {})
    current_time = time.time() if now is None else now
    result['route'] = {key: route.get(key) for key in ('route_id', 'actor', 'agent', 'generation', 'decision_id',
                      'state', 'wake', 'prepared_at', 'claimed_at', 'read_completed_at', 'submitting_at')}
    elapsed = current_time - route.get('submitting_at', route.get('claimed_at', route.get('prepared_at', current_time)))
    threshold = (0 if route.get('state')=='accepted_pending_checkpoint' else
                 120 if route.get('state')=='submitting' else (600 if route.get('claim_id') else 90))
    if elapsed > threshold:
        result['alerts'].append({'kind': 'handoff_needs_host_status', 'elapsed_seconds': elapsed,
                                 'instruction': 'Inspect actual host execution and pending answer transaction before recovery.'})
    result['planning'] = planner_runtime.workboard(root, game)
    return result


def metrics(root,game):
    """Observable stage costs, not an estimate of hidden model inference."""
    directory=directory_for(root,game)
    routes=[read(path) for path in (directory/'routes').glob('*.json')]
    stages={}
    for label,start,end in [('route_to_read','prepared_at','claimed_at'),
                            ('read_to_submit','claimed_at','submitting_at'),
                            ('submit_to_checkpoint','submitting_at','completed_at')]:
        values=sorted(row[end]-row[start] for row in routes if start in row and end in row
                      and row[end]>=row[start] and not row.get('recovered_commit'))
        stages[label]={'samples':len(values),'total_seconds':sum(values),
                       'median_seconds':statistics.median(values) if values else None,
                       'p95_seconds':values[min(len(values)-1,int(.95*len(values)))] if values else None}
    board=planner_runtime.workboard(root,game)
    completed=[row for row in routes if row['state']=='completed']
    continued=[row for row in routes if row['state']=='continued']
    batches=[row for row in completed if row.get('batch_id')]
    return {'game':game,'route_count':len(routes),'completed_decisions':sum(row.get('accepted',1) for row in completed+continued),
            'completed_submissions':len(completed),'approved_batches':len(batches),
            'batch_decisions':sum(row.get('accepted',0) for row in batches+continued),
            'automatic_continuations':len(continued),
            'submissions_elided_by_batches':sum(max(0,row.get('accepted',0)-1) for row in batches)+sum(row['accepted'] for row in continued),
            'claimed_without_plan':sum(bool(row.get('claim_id')) and not row.get('plan_id') for row in routes),
            'distinct_plans_delivered':len({row['plan_id'] for row in routes if row.get('plan_id')}),
            'mandatory_boundaries':board['mandatory_boundaries'],
            'wake_counts':board.get('wake_counts',{}),
            'published_boundaries':board['counts'].get('published',0),
            'unfinished_at_stop':board['counts'].get('unfinished_at_stop',0),
            'stages':stages,'inference_turns':'requires host telemetry',
            'coverage':'All retained route metadata, including recovery history. Recovered-commit durations excluded. '
                       'No claim of measured inference or end-to-end game speedup.'}


@serialized
def recover(root, route_id, *, host_status, host_agent, replace=False):
    """Explicit exception route after the coordinator checked the actual host."""
    from . import campaign, pilot_dispatch
    if host_status not in {'idle', 'completed', 'cancelled', 'failed', 'not_found'}:
        raise SystemExit('Unknown/running host execution cannot be recovered or replaced.')
    action = _current(root)
    action, directory, route = _validate_route(
        root, action.get('actor'), route_id, allow_stopped_host=True)
    if route.get('agent') != host_agent:
        raise SystemExit('Host status must name the current route destination.')
    if campaign._recover_answer_transaction_before_operation(root, action['game']):
        return {'state': 'reconciled', 'next_action': _current(root)}
    # A plain tape commit may also have preceded a lost checkpoint.
    rows = campaign.read_jsonl(directory.parent / 'decisions.jsonl')
    origin=next((row for row in rows if row.get('decision_id')==route['decision_id']),None)
    if origin:
        campaign.advance(root, action['game'])
        route.update(state='completed',completed_at=time.time(),recovered_commit=True)
        batch=origin.get('auxiliary_payload',{}).get('batch')
        if batch:route.update(batch_id=batch['id'],accepted=sum(
            row.get('auxiliary_payload',{}).get('batch',{}).get('id')==batch['id'] for row in rows))
        write(_route_path(directory,route_id),route)
        return {'state': 'reconciled', 'next_action': _current(root)}
    generations = read(directory / 'generations.json', {})
    generations[action['actor']] = route['generation'] + 1
    write(directory / 'generations.json', generations)
    route.update(state='superseded', recovered_at=time.time(), host_status=host_status)
    write(_route_path(directory, route_id), route)
    if replace:
        records = pilot_dispatch.registry(root, action['game'])
        records.pop(action['actor'], None)
        campaign.write_json(pilot_dispatch.registry_path(root, action['game']), records)
        # A fresh agent gets the full baseline; the old renderer stays as audit.
    result = campaign.next_action(root)['next_action']
    if not replace:
        result = {**result, 'dispatch': {**result['dispatch'], 'coordinator_relay_allowed': True,
                                         'recovery_of': route_id}}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort', type=Path, required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    metric=sub.add_parser('metrics');metric.add_argument('--game',type=int,required=True)
    watch = sub.add_parser('watch'); watch.add_argument('--seconds', type=float, default=60)
    wake = sub.add_parser('wake'); wake.add_argument('--route', required=True)
    wake.add_argument('--attempt', required=True); wake.add_argument('--outcome', required=True)
    recovery = sub.add_parser('recover'); recovery.add_argument('--route', required=True)
    recovery.add_argument('--host-status', required=True); recovery.add_argument('--host-agent', required=True)
    recovery.add_argument('--replace', action='store_true')
    args = parser.parse_args(argv); root = args.cohort.resolve()
    if args.command=='metrics':result=metrics(root,args.game)
    elif args.command == 'wake':result = wake_result(root, args.route, attempt_id=args.attempt, outcome=args.outcome)
    elif args.command == 'recover':result = recover(root, args.route, host_status=args.host_status,
                                                   host_agent=args.host_agent, replace=args.replace)
    elif args.command == 'watch':
        if not 0 < args.seconds <= 60:parser.error('--seconds must be in (0, 60]')
        deadline = time.monotonic() + args.seconds; initial = status(root)
        while True:
            result = status(root)
            if result != initial or result['alerts'] or time.monotonic() >= deadline:break
            time.sleep(min(2, max(0, deadline - time.monotonic())))
    else:result = status(root)
    from . import communications
    result=communications.present(result,'decider')
    print(json.dumps(result, ensure_ascii=False)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
