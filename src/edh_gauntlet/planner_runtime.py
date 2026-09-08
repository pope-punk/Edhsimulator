"""Seat-private background continuity, frozen inspection and metadata scheduling.

No operation chooses a move or starts an agent. The host coordinator admits one
planner at a time; publication never takes the campaign lock or wakes a decider.
"""
from __future__ import annotations

import argparse
import json
import shlex
from collections import Counter
from pathlib import Path
from .paths import PROJECT_ROOT
import time

from . import pilot_handoff
from .active_plan import normalize_plan_delta
from .runtime_store import locked, read, write, identity, put, get, checked_id,serialized
from .planner_stages import load_plan

CONTRACT = 4


@serialized
def enable_next_game(root):
    """Enroll only unstarted games; leave current packets/config/tape untouched."""
    from . import campaign
    campaign._require_no_prepared_learning_transaction(root,'enable background planning for future games')
    manifest=campaign.load_manifest(root)
    campaign._require_cohort_not_cancelled(manifest,'enable background planning')
    if manifest.get('decision_surface_revision')!=6:
        raise SystemExit('Background planning requires decision surface 6.')
    started=[number for number in range(1,manifest['target_games']+1)
             if (campaign.game_dir(root,number)/'game_config.json').exists() or
             campaign._game_has_started(campaign.game_dir(root,number))]
    boundary=max(started,default=0)+1
    if boundary>manifest['target_games']:
        raise SystemExit(f'No unstarted games remain; select planning contract {CONTRACT} when initializing a new cohort.')
    existing=manifest.get('planning_runtime') or {}
    if existing.get('contract')==CONTRACT:
        existing['context_handling']=1
        manifest['planning_runtime']=existing
        campaign.write_json(Path(root)/'cohort.json',manifest)
        return {'state':'already_enabled','effective_from_game':existing['effective_from_game'],
                'context_handling_from_unstarted_game':boundary,'current_game_unchanged':True}
    manifest['planning_runtime']={'contract':CONTRACT,'effective_from_game':boundary,'context_handling':1}
    campaign.write_json(Path(root)/'cohort.json',manifest)
    return {'state':'enabled','effective_from_game':boundary,'current_game_unchanged':True}


def enabled(directory):
    return read(Path(directory) / 'game_config.json', {}).get('planning_contract', 1) in {2,3,4}


def directory_for(root, game):
    return Path(root) / f'game_{game:02d}' / 'continuity'


from .background_slots import reservations,reservation,available,assign,release,concurrent


def _state(directory):
    if (directory/'component_transaction.json').exists():
        from .component_store import recover
        recover(directory.parent.parent,int(directory.parent.name.split('_')[-1]))
    return read(directory / 'workboard.json', {'schema': 1, 'jobs': {}, 'planners': {}, 'active': None})


def _save(directory, state):
    write(directory / 'workboard.json', state)


def invalidate_contexts(root, game):
    """Release stale reservations and identities after a branch invalidation.

    ``checkpoint`` fences the associated jobs and snapshots by epoch.  This
    companion cleanup prevents an interrupted reservation from occupying the
    sole planner slot after a rewind or decision migration.
    """
    directory=directory_for(root,game)
    with locked(directory,'planning'):
        state=_state(directory)
        for job in state.get('jobs',{}).values():
            if job.get('status')=='running':job['status']='pending'
        state['active']=None;state['active_by_role']={}
        state['planners']={}
        state.pop('verified_frontier',None)
        _save(directory,state)


def _rows(root, game):
    from . import campaign
    return campaign.read_jsonl(campaign.game_dir(root, game) / 'decisions.jsonl')


def _compatible(descriptor, root, game, actor, rows=None):
    return pilot_handoff.can_resume_session(descriptor, root, game, actor,
                                            _rows(root, game) if rows is None else rows)


def _live(root, game):
    from . import campaign, quarantine
    if (Path(root)/'HOST_PAUSED.json').exists():raise SystemExit('Software host is paused; do not run planners.')
    campaign._require_no_prepared_learning_transaction(root, 'run a planner')
    action = read(Path(root) / 'NEXT_ACTION.json', {}).get('next_action', {})
    if action.get('kind') != 'dispatch_pilot' or action.get('game') != game:
        raise SystemExit('Planner stopped: follow the authoritative lifecycle action.')
    if not enabled(Path(root) / f'game_{game:02d}'):
        raise SystemExit('This started game uses the legacy planning contract.')
    if _state(directory_for(root,game)).get('lifecycle')!='need_decision':
        raise SystemExit('Planner stopped at a non-gameplay frontier.')
    quarantine.require_clean(campaign.DEFAULT_STRATEGY_FILE, root, game)


def _event_view(event, actor):
    from .learning import _event_view as project
    # Deliberately omit ordered top/library knowledge even if an old private
    # event logged it. Own deck inspection supplies unordered composition.
    if event.get('type') in {'look_top', 'top_reorder', 'tutor_top', 'put_on_top'}:
        return {k: event.get(k) for k in ('seq', 'turn', 'phase', 'type', 'actor')}
    return project(event, actor)


def _snapshot(root, game, actor, runtime, rows, previous):
    from . import campaign
    directory = directory_for(root, game)
    previous_value = get(directory / 'snapshots', previous) if previous else {}
    since = previous_value.get('event_seq', 0)
    board = runtime.redacted_snapshot(actor)
    # Opposing private miracle identities are not public facts.
    for name, player in board.get('players', {}).items():
        if name != actor:
            player.pop('miracle_uid', None)
    board_tag=identity(factual_board(board))
    source_session=pilot_handoff.session_descriptor(root,game,actor,rows)
    if (previous_value.get('event_seq')==runtime.seq and previous_value.get('board_tag')==board_tag
            and previous_value.get('source_session')==source_session):
        return previous
    events = [value for event in runtime.events if event['seq'] > since
              if (value := _event_view(event, actor)) is not None]
    inspection = {}
    catalog={}
    public_catalog=(get(directory/'inspection',previous_value['public_catalog_id'])
                    if previous_value.get('public_catalog_id') else {})
    service = getattr(runtime, 'inspection_service', None)
    if service:
        deck=service.inspect_deck(runtime,actor)
        for query, result in [('roles', service.inspect_roles(runtime, actor)),('deck',deck)]:
            inspection[query] = put(directory / 'inspection', result)
        catalog=previous_value.get('catalog',{})
        if not catalog:
            # Catalog definitions are game/branch-bound. Avoid decoding and
            # hash-checking a hundred unchanged records at every frontier.
            profile=service._profile(actor)
            card_ids=list(service._entry_by_id(profile))
            catalog={key:put(directory/'inspection',record) for key,record in
                     service._catalog_records_for_ids(profile,card_ids).items()}
        for item in service.inspectable_object_index(runtime, actor):
            inspected=service.inspect_object(runtime, actor, item['uid'])
            inspection['object ' + item['uid']] = put(directory / 'inspection',inspected)
            # Only actor-inspectable definitions, never an opponent's deck or
            # strategy notes. Preserve revealed definitions when objects leave.
            for field in ('parent_card','effective_parent_card'):
                record=inspected.get(field)
                if record and record.get('card_id') and record['card_id'] not in catalog:
                    public_catalog[record['card_id']]=put(directory/'inspection',record)
    seed = campaign._load_game_seed_gameplan_snapshot(directory.parent)
    inspection['seed'] = put(directory / 'inspection', {
        'kind': 'seed', 'actor': actor,
        'text': seed['pilots'][actor]['text'] if seed else '',
        'snapshot_fingerprint': seed['fingerprint'] if seed else None})
    value = {'schema': 1, 'actor': actor, 'game': game,
             'source_session': source_session,
             'event_seq': runtime.seq, 'board': board, 'board_tag': board_tag,
             'events': events, 'previous_snapshot': previous, 'inspection': inspection,'catalog':catalog,
             'public_catalog_id':put(directory/'inspection',public_catalog)}
    if getattr(runtime,'planning_contract',1)>=3:
        # A publicly revealed opposing card stays known after returning to a
        # hidden hand. Accumulate identities only from this seat's projection.
        value['known_cards']=sorted(set(previous_value.get('known_cards',[])) |
            {e['card'] for e in events if isinstance(e.get('card'),str)})
    return put(directory / 'snapshots', value)


def _queue_boundary(root, game, state, boundary, snapshot, source):
    from . import agent_architecture,split_planning
    if agent_architecture.enabled(root,game) and 'role' not in boundary:
        for item in split_planning.expand(root,game,[boundary]):
            _queue_boundary(root,game,state,item,snapshot,source)
        return
    key=identity({'session':pilot_handoff._session_key(root,game,boundary['actor']),
                  'cadence':boundary['cadence_id']})
    if key not in state['jobs']:
        state['jobs'][key]={'id':key,'actor':boundary['actor'],'boundary':boundary['cadence_id'],
            **({'role':boundary['role']} if 'role' in boundary else {}),
            'mandatory':boundary.get('required',False),'scope':boundary.get('scope','both'),
            'status':'pending','queued_at':time.time(),'snapshot':snapshot,'source_session':source,
            'requirements':{**boundary,'completion':'planner_publication',
                'help':'Maintain written continuity and the requested plan sections; gameplay never waits.'}}


def checkpoint(root, config, runtime, outcome_state, request):
    """Called only after the tape commit, never during speculative replay."""
    if config.get('planning_contract', 1) not in {2,3,4} or runtime is None:
        return
    game = config['game']; directory = directory_for(root, game)
    rows = _rows(root, game)
    with locked(directory, 'planning'):
        state = _state(directory)
        # Epoch/prefix fencing also covers rewind, repair rebase and game changes.
        frontier=state.get('verified_frontier',{})
        continuing=bool(frontier and _compatible(frontier,root,game,'__planning_frontier__',rows))
        if not continuing:
            # An unchanged accepted prefix proves all previously checked jobs.
            # Rehashing every historical prefix at every decision is quadratic.
            checked={}
            for job in state['jobs'].values():
                key=(job['actor'],identity(job['source_session']))
                if key not in checked:checked[key]=_compatible(job['source_session'],root,game,job['actor'],rows)
                if not checked[key]:job['status']='superseded'
            if config.get('planning_contract',1)>=3:
                for key in ('watch_sources','decider_alarms','wake_event_seq','alarm_controls','strategic_watch_sources','strategic_reviews','diplomacy_seen'):
                    state.pop(key,None)
        state['verified_frontier']=pilot_handoff.session_descriptor(root,game,'__planning_frontier__',rows)
        for active in reservations(state):
            if any(state['jobs'][key]['status']=='superseded' for key in active['job_ids']):active['stop_required']=True
        boundaries = list(getattr(runtime, 'planning_boundaries', []))
        if config.get('plan_tiers'):
            from . import plan_tiers
            for actor in runtime.players:
                if not plan_tiers.standing(root,game,actor):
                    boundaries.append({'actor':actor,'required':True,'cadence_id':'standing_initialization',
                        'scope':'standing','reason':'standing_initialization'})
        if config.get('planning_contract',1)>=3:
            from . import planner_wakes
            boundaries.extend(planner_wakes.checkpoint(state,runtime,rows,_event_view))
        for row in rows:
            optional = row.get('auxiliary_payload', {}).get('planner_update')
            if optional:
                boundaries.append({'actor': row['actor'], 'required': False,
                                   'cadence_id': row['decision_id'] + '|optional', 'scope': optional})
        from . import agent_architecture,split_planning
        if agent_architecture.diplomacy_enabled(root,game):
            from .diplomacy import boundaries as diplomatic_boundaries
            boundaries.extend(diplomatic_boundaries(state,runtime))
        if agent_architecture.enabled(root,game):boundaries=split_planning.expand(root,game,boundaries)
        new_by_actor = {}
        if agent_architecture.diplomacy_enabled(root,game):
            for pending_post in read(directory/'diplomacy_outbox.json',{}).values():
                new_by_actor.setdefault(pending_post['actor'],[])
        for boundary in boundaries:
            actor = boundary['actor']
            key = identity({'session': pilot_handoff._session_key(root, game, actor),
                            'cadence': boundary['cadence_id']})
            if key not in state['jobs']:
                new_by_actor.setdefault(actor, []).append((key, boundary))
        if config.get('planning_contract',1)>=3:
            # Freeze the current decider for non-consuming controls, and the
            # running planner for publication-gap watch catch-up. At most two
            # additional seats; no full-table speculative snapshot per read.
            if request:new_by_actor.setdefault(request['actor'],[])
            for active in reservations(state):
                if not active.get('stop_required'):new_by_actor.setdefault(active['actor'],[])
        for actor, pending in new_by_actor.items():
            previous = state.get('snapshots', {}).get(actor)
            if previous and not _compatible(get(directory / 'snapshots', previous)['source_session'],
                                            root, game, actor, rows):
                previous = None
            snapshot = _snapshot(root, game, actor, runtime, rows, previous)
            source = get(directory / 'snapshots', snapshot)['source_session']
            state.setdefault('snapshots', {})[actor] = snapshot
            if config.get('static_standing')==1:
                from .static_standing import install
                install(root,game,actor,snapshot)
            for key, boundary in pending:
                _queue_boundary(root,game,state,boundary,snapshot,source)
            if config.get('planning_contract',1)>=3:
                # Pending work follows the newest committed facts until its
                # reservation freezes it; a running batch is never rewritten.
                for job in state['jobs'].values():
                    if job['actor']==actor and job['status']=='pending':
                        job.update(snapshot=snapshot,source_session=source)
        if request:
            actor=request['actor']
            head=state.get('event_heads',{}).get(actor)
            previous=get(directory/'events',head) if head else None
            if previous and not _compatible(previous['source_session'],root,game,actor,rows):
                head=None;previous=None
            since=previous['event_seq'] if previous else 0
            if runtime.seq>since:
                events=[value for event in runtime.events if event['seq']>since
                        if (value:=_event_view(event,actor)) is not None]
                head=put(directory/'events',{'actor':actor,'previous':head,'event_seq':runtime.seq,
                    'source_session':pilot_handoff.session_descriptor(root,game,actor,rows),'events':events})
                state.setdefault('event_heads',{})[actor]=head
            request['continuity_event_head']=head
            if config.get('planning_contract',1)>=3:
                from .planning_contract import priority_request
                request['planner_stages']=config.get('planner_stages',False)
                request['planner_control']={'allowed':priority_request(request),
                    'alarm':state.get('decider_alarms',{}).get(actor),
                    'mandatory':'own_turn_completed',
                    'help':'planner_alarm: {mode:now|cancel} or {mode:schedule,seat:SEAT,time:"N beginning|end of PHASE"}. '
                           'One pilot alarm; seat-specific occurrences. Own end of end_step is already mandatory. '
                           'Use it on this answer or pilot_session --planner-alarm JSON --control-id UUID --claim-id CLAIM at priority. '
                           'Planner watches and mandatory EOT remain independent; gameplay never waits.'}
                if request['planner_stages']:
                    request['planner_control']['help']+=' Add long_term:true to now/schedule to request long-term maintenance. Follow the bound publication stage order. Otherwise only prose and actions are updated.'
                if config.get('plan_tiers'):
                    request['planner_control']['help']+=' Three-tier mode: the opening long-term goal is automatic. Use long_term:true when that goal becomes stale; replacement precedes upcoming-turn sequencing. The standing plan is immutable.'
        state['lifecycle'] = outcome_state
        if outcome_state != 'need_decision':
            # Retain mandatory debt. Never complete it later with post-game knowledge.
            for job in state['jobs'].values():
                if outcome_state=='complete' and job['status'] in {'pending', 'running'}:
                    job['status'] = 'unfinished_at_stop'
            for active in reservations(state):active['stop_required']=True
        _save(directory, state)


def _job_metadata(job):
    return {key: job.get(key) for key in ('id', 'actor', 'role', 'boundary', 'mandatory', 'scope',
                                        'status', 'queued_at', 'snapshot', 'plan_id')}


def workboard(root, game,*,action=None,role=None):
    """No private payloads, card names, history, requirements or plan text."""
    state = _state(directory_for(root, game))
    action = action or read(Path(root) / 'NEXT_ACTION.json', {}).get('next_action', {})
    live = action.get('kind') == 'dispatch_pilot' and action.get('game') == game
    pending = [job for job in state['jobs'].values() if job['status'] == 'pending']
    from .split_planning import eligible
    pending=available(state,eligible(root,game,state,pending))
    if role is not None:pending=[j for j in pending if j.get('role','planner')==role]
    from .split_planning import sort_pending
    sort_pending(root,game,pending)
    visible=[job for job in state['jobs'].values() if job['status'] in {'pending','running','unfinished_at_stop'}]
    counts=dict(Counter(job['status'] for job in state['jobs'].values()))
    return {'schema': 1, 'game': game, 'lifecycle': action.get('kind'),
            'stop_required': not live, 'active': next(iter(reservations(state)),None),
            'active_by_role':{j.get('role','planner'):j for j in reservations(state)},'role_slots':state.get('role_slots',0),
            'next_actor': pending[0]['actor'] if pending and live else None,
            'next_role':pending[0].get('role','planner') if pending and live else None,
            'jobs': [_job_metadata(job) for job in visible[:32]],'counts':counts,
            'omitted_job_count':max(0,len(visible)-32),'mandatory_boundaries':sum(job['mandatory'] for job in state['jobs'].values()),
            'wake_counts':dict(Counter(job.get('requirements',{}).get('reason','legacy_boundary') for job in state['jobs'].values() if job['status']!='superseded')),
            'pending_seat_count':len({job['actor'] for job in pending}),
            'planners': state['planners'], 'planner_concurrency':3 if concurrent(state) else 1,
            'reserved_decision_slots':1 if concurrent(state) else 3}


def _refresh_reservation(root, game, state, actor, rows):
    """Refresh a queued seat once, at admission; never rewrite active input.

    Call under campaign then planning locks. Replay only the accepted tape and
    project one private seat; no checkpoint, new choice or four-seat cache.
    """
    from . import campaign
    directory = directory_for(root, game)
    previous = state.get('snapshots', {}).get(actor)
    source = pilot_handoff.session_descriptor(root, game, actor, rows)
    old = get(directory / 'snapshots', previous) if previous else {}
    if old.get('source_session') == source:
        # A publication can queue follow-up work from its frozen batch after a
        # checkpoint already captured newer facts for this same seat.
        stale = [job for job in state['jobs'].values() if job['actor'] == actor
                 and job['status'] == 'pending' and job['snapshot'] != previous]
        for job in stale:
            job.update(snapshot=previous, source_session=source)
        return ({'accepted': len(rows), 'seconds': 0, 'replayed': False,
                 'coalesced_jobs': len(stale)} if stale else None)
    started = time.monotonic()
    manifest = campaign.load_manifest(root)
    config = campaign._game_config_with_bound_surface(root, manifest, game)
    scratch = directory / '.reservation_request.json'
    try:
        outcome = campaign._run(root, config, directory.parent / 'decisions.jsonl',
                                scratch, retain_suspended_game=True)
    finally:
        scratch.unlink(missing_ok=True)
    runtime = outcome.get('game')
    if outcome['state'] != 'need_decision' or runtime is None:
        raise SystemExit('Planner reservation requires a reproducible live frontier.')
    if previous and not _compatible(old['source_session'], root, game, actor, rows):
        previous = None
    snapshot = _snapshot(root, game, actor, runtime, rows, previous)
    state.setdefault('snapshots', {})[actor] = snapshot
    for job in state['jobs'].values():
        if job['actor'] == actor and job['status'] == 'pending':
            job.update(snapshot=snapshot, source_session=source)
    return {'previous_accepted': old.get('source_session', {}).get('accepted_prefix_count'),
            'accepted': len(rows), 'seconds': round(time.monotonic() - started, 6), 'replayed': True}


@serialized
def reserve(root, game, *, admission_id, host_capacity, host_active, expected_identity=None):
    """Admission is metadata only; host tools must still create/wake the agent."""
    if not isinstance(admission_id, str) or not admission_id.strip():
        raise SystemExit('Supply a stable admission ID for retries.')
    directory = directory_for(root, game)
    with locked(directory, 'planning'):
        _live(root, game)
        state = _state(directory)
        for active in reservations(state):
            if active['admission_id']==admission_id:
                if expected_identity is not None and tuple(expected_identity)!=(active['actor'],active.get('role','planner')):
                    raise SystemExit('Admission retry belongs to a different seat or role.')
                return active
        if not concurrent(state) and reservations(state):
            raise SystemExit('One planner is already reserved; confirm it stopped before releasing capacity.')
        if host_capacity < 4 or host_active >= host_capacity:
            raise SystemExit('Insufficient inference capacity for background admission.')
        rows=_rows(root,game)
        frontier=state.get('verified_frontier',{})
        validated=bool(frontier and _compatible(frontier,root,game,'__planning_frontier__',rows))
        pending = [job for job in state['jobs'].values() if job['status'] == 'pending'
                   and (validated or _compatible(job['source_session'], root, game, job['actor'],rows))]
        from .split_planning import eligible
        from .agent_architecture import registration_key
        pending=available(state,eligible(root,game,state,pending))
        if expected_identity is not None and concurrent(state):
            pending=[j for j in pending if j.get('role','planner')==expected_identity[1]]
        if not pending:
            return {'state': 'idle'}
        from .split_planning import sort_pending
        sort_pending(root,game,pending)
        actor = pending[0]['actor']
        selected=(actor,pending[0].get('role','planner'))
        if expected_identity is not None and tuple(expected_identity)!=selected:
            return {'state':'reschedule','reason':'next_background_identity_changed'}
        from .agent_architecture import enabled as architecture_enabled
        refresh = _refresh_reservation(root, game, state, actor, rows) if architecture_enabled(root, game) else None
        role=pending[0].get('role','planner');registry_key=registration_key(actor,role)
        if role=='diplomacy':
            from .diplomacy import preflight_required
            if preflight_required(root,game,state,actor):
                _save(directory,state)
                if expected_identity is not None:
                    return {'state':'reschedule','reason':'authorization_refresh_before_inference'}
                return reserve(root,game,admission_id=admission_id,host_capacity=host_capacity,host_active=host_active)
        jobs = sorted([job for job in pending if job['actor'] == actor and job.get('role','planner')==role
                       and (role!='long_term_planner' or (job['scope']=='standing')==(pending[0]['scope']=='standing'))],
                      key=lambda job: (job['source_session']['accepted_prefix_count'], job['queued_at'], job['id']))
        if role=='diplomacy':
            # A message backlog must not evict the mandatory brief that won
            # admission from the bounded batch it is meant to satisfy.
            jobs.sort(key=lambda job:(not job['mandatory'],job['queued_at'],job['id']))
            jobs=jobs[:16]
        existing = state['planners'].get(registry_key)
        compatible = existing and _compatible(existing['source_session'], root, game, actor)
        generation = existing['generation'] if compatible else state.get('generations',{}).get(registry_key,0) + 1
        state.setdefault('generations',{})[registry_key]=generation
        batch = {'actor': actor, 'game': game, 'generation': generation, 'role':role,
                 'job_ids': [job['id'] for job in jobs], 'snapshot': jobs[-1]['snapshot'],
                 'admission_id': admission_id, 'source_session': jobs[-1]['source_session']}
        if role!='planner':batch['job_count']=len(jobs)
        if role=='diplomacy':
            batch['requires_public_post']=any(j['requirements'].get('reason')=='actionable_brief' for j in jobs)
        batch_id = put(directory / 'batches', batch)
        policy = PROJECT_ROOT / 'docs/PLANNER_RUNTIME_POLICY.md'
        command = (f'python -m edh_gauntlet.planner_runtime --cohort "{Path(root).resolve()}" '
                   f'--game {game} read --actor "{actor}" --batch {batch_id} --generation {generation}')
        active = {**batch, 'batch_id': batch_id, 'reserved_at': time.time(), 'wake': 'not_attempted',
                  'queue_seconds':max(0,time.time()-min(job['queued_at'] for job in jobs)),
                  **({'snapshot_refresh': refresh} if refresh else {}),
                  'kind': 'resume' if compatible else 'spawn',
                  'agent': existing['agent'] if compatible else None,
                  'prompt': ('' if compatible else f'Read {policy} once. ') + command}
        for job in jobs:
            job['status'] = 'running'
        assign(state,active)
        _save(directory, state)
        return active


def dispatched(root, game, batch_id, *, agent, outcome):
    if outcome not in {'accepted', 'unknown', 'rejected'} or not agent or any(c in agent for c in '\r\n'):
        raise SystemExit('Supply a host agent identity and accepted/unknown/rejected dispatch outcome.')
    directory = directory_for(root, game)
    with locked(directory, 'planning'):
        state = _state(directory); active = reservation(state,batch_id)
        if not active or active['batch_id'] != batch_id:
            raise SystemExit('Planner reservation changed.')
        if active.get('agent') and active['agent'] != agent:
            raise SystemExit('A reservation cannot be assigned to a competing agent.')
        from .agent_architecture import registration_key
        key=registration_key(active['actor'],active.get('role','planner'))
        if any(k!=key and v.get('agent')==agent for k,v in state['planners'].items()):
            raise SystemExit('A background agent cannot serve another seat or role.')
        active.update(agent=agent, wake=outcome)
        state['planners'][key] = {
            'agent': agent, 'generation': active['generation'], 'source_session': active['source_session']}
        _save(directory, state)
        return {'batch_id': batch_id, 'wake': outcome}


def stopped(root, game, batch_id, *, host_status):
    if host_status not in {'idle', 'completed', 'cancelled', 'failed', 'not_found', 'rejected'}:
        raise SystemExit('Unknown/running host status cannot release planner capacity.')
    directory = directory_for(root, game)
    with locked(directory, 'planning'):
        state = _state(directory); active = reservation(state,batch_id)
        if not active or active['batch_id'] != batch_id:
            raise SystemExit('Planner reservation changed.')
        for job_id in active['job_ids']:
            job = state['jobs'][job_id]
            if job['status'] == 'running':
                # An optional worker that ended without publishing has not
                # acknowledged silence. Preserve that fact, but never turn a
                # blank completion into an unbounded inference retry loop.
                job['status'] = ('unanswered_at_completion' if host_status=='completed'
                                 and active.get('role')=='diplomacy' and not active.get('requires_public_post') else 'pending')
        state['last_execution'] = {'batch_id': batch_id, 'host_status': host_status,
                                   'elapsed_seconds': time.time() - active['reserved_at']}
        if host_status in {'cancelled', 'failed', 'not_found'}:
            from .agent_architecture import registration_key
            state['planners'].pop(registration_key(active['actor'],active.get('role','planner')), None)
        release(state,active)
        _save(directory, state)
        return workboard(root, game)


def _batch(root, game, actor, batch_id, generation):
    _live(root, game)
    directory = directory_for(root, game); state = _state(directory)
    batch = get(directory / 'batches', batch_id)
    active = reservation(state,batch_id)
    if (batch['actor'] != actor or batch['generation'] != generation or not active
            or active['batch_id'] != batch_id or active.get('stop_required')
            or any(state['jobs'][key]['status'] not in {'running', 'published'} for key in batch['job_ids'])
            or not _compatible(batch['source_session'], root, game, actor)):
        raise SystemExit('Stale, stopped or wrong-seat planner reservation.')
    return directory, state, batch, get(directory / 'snapshots', batch['snapshot'])


def _latest(directory, root, game, actor):
    try:
        if (directory/'component_transaction.json').exists():
            from .component_store import recover
            recover(root,game)
        mailbox = read(directory / 'mailboxes' / (pilot_handoff.seat_slug(actor) + '.json'), {})
        if not mailbox.get('plan_id'):return None,None
        plan = load_plan(directory, mailbox['plan_id'])
        if plan['actor']!=actor or plan['game']!=game or not _compatible(plan['source_session'], root, game, actor):
            return None, None
        return mailbox['plan_id'], plan
    except (SystemExit,OSError,ValueError,KeyError,TypeError):
        # A corrupt advisory publication cannot become a gameplay gate.
        return None,None


def read_job(root, game, actor, batch_id, generation):
    directory = directory_for(root, game)
    with locked(directory, 'planning'):
        directory, state, batch, snapshot = _batch(root, game, actor, batch_id, generation)
        path = directory / 'inputs' / (checked_id(batch_id) + '.json')
        if path.exists():
            from . import planner_stages
            return planner_stages.present_input(get(directory/'frozen_inputs',read(path)['input_id']),
                [state['jobs'][key]['boundary'] for key in batch['job_ids']])
        if batch.get('role')=='diplomacy':
            from .diplomacy import input_value
            result=input_value(root,game,actor,batch,batch_id,state,snapshot)
            write(path,{'input_id':put(directory/'frozen_inputs',result)})
            reservation(state,batch_id)['read_at']=time.time();_save(directory,state)
            return result
        prior_id, prior = _latest(directory, root, game, actor)
        since = prior['event_seq'] if prior else 0
        from . import agent_architecture,split_planning
        if agent_architecture.enabled(root,game):since=split_planning.cursor(root,game,actor,batch['role'])
        from . import context_packets
        history = context_packets.history_since(directory, snapshot, since)
        result = {'schema': 1, **batch, 'batch_id': batch_id, 'board_tag': snapshot['board_tag'],
                  'board': snapshot['board'], 'history_since_prior_plan': history,
                  'prior_plan_id': prior_id, 'prior_plan': prior,
                  'requirements': [state['jobs'][key]['requirements'] for key in batch['job_ids']],
                  'inspection': ['roles', 'deck', 'seed', 'state', 'history', 'object UID',
                                 'card NAME_OR_ID', 'role NAME_OR_ID'],
                  'guidance': 'Use --inspect roles --inspect deck --inspect seed on initialization; '
                              'inspect relevant roles/cards/objects during maintenance. Publish once and return; '
                              'do not choose actions, contact deciders or wait for gameplay.'}
        if read(directory.parent/'game_config.json',{}).get('planning_contract',1)>=3:
            from . import planner_wakes, planning_contract
            rows=_rows(root,game)[:snapshot['source_session']['accepted_prefix_count']]
            decisions=planner_wakes.decision_rationales(history,rows,actor)
            names={get(directory/'inspection',key).get('name') for key in snapshot.get('catalog',{}).values()}
            cards,uids=planning_contract.known_facts(snapshot['board'],(names-{None}) | set(snapshot.get('known_cards',[])))
            result.update(planning_contract=read(directory.parent/'game_config.json')['planning_contract'],
                decisions_since_prior_plan=decisions,
                rationale_interval={'after_event_seq':since,'through_event_seq':snapshot['event_seq'],
                    'source':'Existing accepted own-seat answers. Empty rationale means none was recorded; do not invent intent.'},
                history_since_prior_plan=[e for e in history if not (e.get('type')=='llm_decision' and e.get('actor')==actor)],
                execution_comparison=(planner_wakes.report(root,game,actor,directory,state,snapshot,rows,since)
                    if batch.get('role')!='long_term_planner' else {}),
                symbolic_vocabulary={'cards':sorted(cards),'object_uids':sorted(uids),
                    'phases':list(planning_contract.PHASES),'clock':snapshot['board'].get('planning_clock',{})},
                decider_alarm=state.get('decider_alarms',{}).get(actor),
                previous_watches=state.get('watch_sources',{}).get(actor),
                wake_guidance='Mandatory: initial settled hand and own_turn_completed after cleanup. No draw wakes. '
                    'Read decisions_since_prior_plan, including every recorded rationale, before interpreting cast deviations. '
                    'Publish recommendations and a replacement list of at most eight conservative one-shot watches. '
                    'Card-cast watches also cover a named counterspell being spent even if it fails. '
                    'Latest complete continuity enters the next unclaimed ordinary decision at any phase.')
        if result.get('planning_contract',1)>=4:
            from . import sequence_runtime
            result['guidance']='Use --inspect roles --inspect deck --inspect seed on initialization; inspect relevant roles/cards/objects during maintenance. Read every recorded own-seat rationale. Propose concrete actions for pilot approval, never execute them or contact deciders. Publish once and return.'
            result['wake_guidance']=result['wake_guidance'].replace('Publish recommendations','Publish action_sequence')
            if result.get('prior_plan'):
                result['prior_plan']={key:value for key,value in result['prior_plan'].items() if key!='recommendations'}
            if batch.get('role')!='long_term_planner':
                result['sequence_reviews']=sequence_runtime.planner_report(root,game,actor,rows,
                    {event['decision_id'] for event in history if event.get('type')=='llm_decision' and event['seq']>since})
            result['symbolic_vocabulary']['sequence_format']={
                'limit':'16 steps / 12000 UTF-8 bytes; one expected line, no speculative branch tree',
                'fields':['id','seat_turn','phase','kind','choice','rationale','scheduler','requires'],
                'choice_format':'UID object {uid:ID}; player {seat:NAME}; tuple as list; action tuple as {action:KIND,source:OBJECT_OR_NULL,args:EXACT_PARAMETERS}; null is PASS. Multi-select uses a list of choices.',
                'common_kinds':['land_play','main_action','combat_target','declare_attackers'],
                'guidance':'Propose concrete tactical choices and ordering, never execute them. Include required targets/modes as separate steps. Omit unknown future choices. The pilot may approve, reject or override at an ordinary main-phase decision.'}
        from . import planner_stages
        if planner_stages.enabled(root,game):
            from . import plan_tiers
            if plan_tiers.enabled(root,game):plan_tiers.prepare(root,game,actor,result)
            result['publication_stages']=[planner_stages.instruction(stage,tiered=result.get('plan_tiers',False),
                boundaries=[state['jobs'][key]['boundary'] for key in batch['job_ids']]) for stage in planner_stages.sequence(result)]
            result['guidance']='Inspect roles/deck/seed on initialization and read the supplied own decision rationales. Publish short-term prose first, symbolic actions second, and long-term only when requested. Each stage is a separate tool call; await its result before generating the next. Completed stages become available immediately. Keep existing long-term continuity until the pilot requests revision; the seed remains the opening strategic baseline.'
            result['requirements']=[{**item,'opening_long_term_plan_required':False,
                'long_term_policy':'Only a pilot request authorizes stage three.'} for item in result['requirements']]
        if result.get('plan_tiers'):
            from . import plan_tiers
            plan_tiers.prepare(root,game,actor,result)
            for item in result['requirements']:item['long_term_policy']='Initial goal automatically after settled hand; subsequent replacements only on pilot request.'
        if context_packets.enabled(root,game):
            from . import decision_context
            result['context_handling']=1
            result['decision_context_version']=1
            result['intervening_context']=decision_context.event_summary(result.pop('history_since_prior_plan'))
            result['latest_decision_context']=decision_context.latest_decision(root,game,actor,rows,snapshot['board'])
            result['decision_context_guidance']=decision_context.GUIDANCE
            result['inspection'].append('decision DECISION_ID')
        if agent_architecture.enabled(root,game):split_planning.project(root,game,actor,result)
        write(path, {'input_id':put(directory/'frozen_inputs',result)})
        reservation(state,batch_id)['read_at'] = time.time(); _save(directory, state)
        return result


def inspect_many(root, game, actor, batch_id, generation, queries):
    directory, state, batch, snapshot = _batch(root, game, actor, batch_id, generation)
    results = []
    for query in queries:
        clean = ' '.join(query.strip().split())
        clean = clean.removesuffix(' detail=full')
        if batch.get('role')=='diplomacy':
            from .diplomacy import inspect_frozen
            value=inspect_frozen(root,game,actor,batch_id,generation,clean)
        elif clean in {'personality','messaging_personality'} and batch.get('role')=='long_term_planner':
            from .messaging_reference import own
            value=own(root,game,actor)
        elif batch.get('role')=='short_term_planner' and clean in {'roles','deck','seed'}:
            value={'error':'Broad strategic surveys belong to the long-term role. Inspect a named role, card, visible object or deck zone instead.'}
        elif clean.startswith('component '):
            from .component_store import resolve
            job=read_job(root,game,actor,batch_id,generation)
            allowed={v['component_id'] for v in job.get('component_refs',{}).values()}
            for stage in reservation(state,batch_id).get('completed_stages',[]):
                receipt=read(directory/'stage_publications'/(batch_id+'.'+stage+'.json'),{})
                if receipt.get('plan_id'):allowed.update(load_plan(directory,receipt['plan_id']).get('owned_component_ids',{}).values())
            try:
                if clean.removeprefix('component ') not in allowed:raise ValueError('Inspect only component IDs supplied by this frozen job or its own publications.')
                value=resolve(root,game,actor,clean.removeprefix('component '),recipient_role=batch.get('role','planner'))
            except ValueError as exc:value={'error':str(exc)}
        elif clean in {'state', 'history'}:
            if clean=='state':value=snapshot['board']
            else:
                job=read_job(root,game,actor,batch_id,generation)
                from . import context_packets
                events=(context_packets.history_since(directory,snapshot,job['rationale_interval']['after_event_seq'])
                        if job.get('context_handling')==1 else job['history_since_prior_plan'])
                value=({'events':events,'decisions':job['decisions_since_prior_plan'],
                        'rationale_interval':job['rationale_interval']} if job.get('planning_contract',1)>=3
                       else job['history_since_prior_plan'])
        elif clean.startswith('decision '):
            from . import decision_context
            rows=_rows(root,game)[:snapshot['source_session']['accepted_prefix_count']]
            value=decision_context.inspect_decision(root,game,actor,rows,clean.removeprefix('decision '))
        elif clean in snapshot['inspection']:
            value = get(directory / 'inspection', snapshot['inspection'][clean])
        elif clean.startswith('card ') and ('object '+clean[5:].strip('"\'')) in snapshot['inspection']:
            # A visible object UID has one unambiguous actor-scoped definition.
            # Resolve it directly instead of spending an inference on correcting
            # the otherwise harmless card-versus-object query spelling.
            value=get(directory/'inspection',snapshot['inspection']['object '+clean[5:].strip('"\'')])
        elif clean.startswith(('card ','role ','deck ')):
            try:value=_inspect_deck_query(directory,snapshot,clean)
            except ValueError as exc:value={'error':str(exc)}
        else:
            value = {'error': 'Query unavailable in this frozen snapshot; inspect roles, deck, seed, state, history or object UID.'}
        results.append({'query': query, 'snapshot': batch['snapshot'], 'result': value})
    # Content-addressed audit avoids repeating large inspection payloads.
    receipt = {'actor': actor, 'batch_id': batch_id, 'results': [
        {'query': item['query'], 'result': put(directory / 'inspection', item['result'])} for item in results]}
    put(directory / 'inspection_receipts', receipt)
    return results


def _inspect_deck_query(directory,snapshot,query):
    parts=shlex.split(query);kind=parts.pop(0);filters={};words=[]
    for part in parts:
        if '=' in part:
            key,value=part.split('=',1)
            if key!='zone':raise ValueError('Frozen deck queries support zone=ZONE; live castability is unavailable.')
            filters[key]=value
        else:words.append(part)
    target=' '.join(words).casefold()
    deck=get(directory/'inspection',snapshot['inspection']['deck'])
    roles=get(directory/'inspection',snapshot['inspection']['roles'])
    selection=None
    if kind=='role':
        selection=next((role for role in roles['roles'] if target in {
            str(role.get('role_id','')).casefold(),str(role.get('label','')).casefold(),
            *(str(alias).casefold() for alias in role.get('aliases',[]))}),None)
        if not selection:raise ValueError('Unknown frozen role; inspect roles.')
    elif kind=='card' and not target:raise ValueError('Supply a card name or ID.')
    elif kind=='deck' and target:raise ValueError('Deck queries take only zone=ZONE.')
    if filters.get('zone') and filters['zone'] not in deck['zones']:
        raise ValueError('Unknown zone in this frozen deck view.')
    zones={};selected_ids=set()
    for zone,group in deck['zones'].items():
        if filters.get('zone') and filters['zone']!=zone:continue
        cards=[card for card in group['cards'] if (
            kind=='deck' or kind=='role' and selection['role_id'] in card.get('roles',[]) or
            kind=='card' and target in {str(card.get('card_id','')).casefold(),str(card.get('name','')).casefold()})]
        selected_ids.update(card['card_id'] for card in cards)
        zones[zone]={**group,'cards':cards,'matching_known_count':sum(card['quantity'] for card in cards),
                     'count':sum(card['quantity'] for card in cards)}
    if kind=='card' and not selected_ids:
        # Own registered cards with uncertain/currently absent zone membership
        # remain inspectable without inferring which hidden object they are.
        for card_id,digest in snapshot.get('catalog',{}).items():
            record=get(directory/'inspection',digest)
            if target in {card_id.casefold(),str(record.get('name','')).casefold()}:selected_ids.add(card_id)
        if not selected_ids and not filters:
            public_catalog=(get(directory/'inspection',snapshot['public_catalog_id'])
                            if snapshot.get('public_catalog_id') else {})
            for card_id,digest in public_catalog.items():
                record=get(directory/'inspection',digest)
                if target in {card_id.casefold(),str(record.get('name','')).casefold()}:
                    return {'kind':'card','actor':snapshot['actor'],'catalog_records':{card_id:record},
                        'help':'Previously actor-visible card definition only; no current-zone claim or opposing private strategy.'}
        if not selected_ids:raise ValueError('Card absent from this frozen view; inspect an actor-visible object UID if its definition is available there.')
    return {'kind':kind,'actor':snapshot['actor'],'selection':selection,'zones':zones,
            'uncertainty':deck.get('uncertainty'),
            'catalog_records':{key:get(directory/'inspection',snapshot['catalog'][key]) for key in sorted(selected_ids)
                               if key in snapshot.get('catalog',{})},
            'pilot_memory':deck.get('pilot_memory',[]),
            'help':'Frozen actor-scoped composition and rules; library order and current action legality are unavailable.'}


def _find_named(value, target, keys):
    if isinstance(value, dict):
        if any(str(value.get(key, '')).casefold() == target for key in keys):
            return value
        for child in value.values():
            found = _find_named(child, target, keys)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_named(child, target, keys)
            if found:
                return found
    return None


def publish(root, game, actor, batch_id, generation, response, *, _stage=None, _stage_digest=None):
    from . import planner_stages
    staged=planner_stages.enabled(root,game)
    if staged and _stage is None:raise SystemExit('Use staged planner publication for this game.')
    if not staged and _stage is not None:raise SystemExit('This game uses single planner publication.')
    directory = directory_for(root, game)
    with locked(directory, 'planning'):
        directory, state, batch, snapshot = _batch(root, game, actor, batch_id, generation)
        publication_path = directory / ('stage_publications' if staged else 'publications') / (checked_id(batch_id) + ('.'+_stage if staged else '') + '.json')
        previous = read(publication_path)
        response_digest = identity(response)
        if previous:
            if previous['response_digest'] != response_digest:
                raise SystemExit('This batch was already published with different content.')
            for key in batch['job_ids']:
                state['jobs'][key].update(status='published',plan_id=previous['plan_id'])
            reservation(state,batch_id)['published_at']=previous['published_at']
            _install_watches(root,game,actor,directory,state,previous['plan_id'])
            _save(directory,state)
            return previous
        input_binding = read(directory / 'inputs' / (batch_id + '.json'))
        if input_binding is None:
            raise SystemExit('Read the frozen planner input before publishing.')
        input_value=get(directory/'frozen_inputs',input_binding['input_id'])
        final_stage=not staged or _stage==planner_stages.sequence(input_value)[-1]
        if response.get('covered_boundaries') != [state['jobs'][key]['boundary'] for key in batch['job_ids']]:
            raise SystemExit('Publication must cover every reserved boundary in order.')
        allowed = {'covered_boundaries', 'short_term_plan', 'long_term_action', 'long_term_rationale',
                   'long_term_plan', 'continuity', 'dependencies','boundary_notes'}
        contract=read(directory.parent/'game_config.json',{}).get('planning_contract',1)
        if contract>=3:allowed|={'recommendations','watches'}
        if contract>=4:allowed.add('action_sequence')
        if contract>=4:allowed.add('table_talk')
        tiered=input_value.get('plan_tiers',False)
        if tiered:allowed.add('standing_plan')
        if set(response) - allowed:
            raise SystemExit('Unsupported planner publication fields.')
        boundary_notes=response.get('boundary_notes',{})
        if planner_stages.boundary_contract(response['covered_boundaries'])['required'] and not (tiered and _stage in {'standing','long_term'}):
            if not isinstance(boundary_notes,dict) or set(boundary_notes)!=set(response['covered_boundaries']):
                raise SystemExit('Coalesced maintenance requires one factual continuity note for each covered boundary.')
        if not isinstance(boundary_notes,dict) or set(boundary_notes)-set(response['covered_boundaries']):
            raise SystemExit('Boundary notes must refer only to reserved boundaries.')
        if any(not isinstance(value,str) for value in boundary_notes.values()):
            raise SystemExit('Boundary notes must be nonempty factual strings.')
        try:boundary_notes={key:normalize_plan_delta(value) for key,value in boundary_notes.items()}
        except ValueError as exc:raise SystemExit(str(exc)) from exc
        requirements = input_value['requirements']
        both = any(item.get('required') or item.get('scope') == 'both' for item in requirements)
        short_required = both or any(item.get('scope') == 'short_term' for item in requirements)
        long_required = both or any(item.get('scope') == 'long_term' for item in requirements)
        if staged:short_required=True;long_required=_stage=='long_term'
        if tiered:short_required='short_term_plan' in response;long_required='long_term_action' in response
        prior = input_value.get('prior_plan') or {}
        try:
            short = normalize_plan_delta(response['short_term_plan']) if short_required else prior.get('short_term_plan')
            action = str(response['long_term_action']).strip().casefold() if long_required else 'keep'
            if action not in {'keep', 'revise'}:raise ValueError('long_term_action must be keep or revise')
            rationale = normalize_plan_delta(response['long_term_rationale']) if long_required else None
            long_plan = normalize_plan_delta(response['long_term_plan']) if action == 'revise' else prior.get('long_term_plan')
            continuity = normalize_plan_delta(response['continuity']) if not tiered or 'continuity' in response else (prior.get('continuity') or '')
        except (ValueError, KeyError) as exc:
            raise SystemExit('Invalid planner publication: ' + str(exc)) from exc
        if not short_required and 'short_term_plan' in response:
            raise SystemExit('This optional boundary does not permit short-term replacement.')
        table_talk=None
        if 'table_talk' in response:
            from .table_talk_plan import normalize
            if not short_required:raise SystemExit('Table-talk proposals belong to short-term planning only.')
            try:table_talk=normalize(response['table_talk'],actor,snapshot['board'])
            except ValueError as exc:raise SystemExit(str(exc)) from exc
        if not long_required and any(key in response for key in ('long_term_action', 'long_term_rationale', 'long_term_plan')):
            raise SystemExit('This optional boundary does not permit long-term replacement.')
        if staged and long_required and action=='keep' and not long_plan:
            raise SystemExit('No prior long-term plan exists; requested maintenance must revise.')
        if action == 'keep' and 'long_term_plan' in response:
            raise SystemExit('KEEP must not rewrite the long-term plan.')
        for requirement in requirements:
            if requirement.get('opening_long_term_plan_required') and not staged:
                if action != 'revise':
                    raise SystemExit('Opening maintenance requires long-term revision.')
                clauses = requirement.get('opening_information_boundary', {}).get('required_clauses', [])
                if any(clause.casefold() not in long_plan.casefold() for clause in clauses):
                    raise SystemExit('Opening plan is missing a required opponent information-boundary clause.')
        if tiered:
            from . import plan_tiers
            if short and len(short)>600:raise SystemExit('Short-term sequencing must be at most 600 characters.')
            if _stage=='long_term' and action!='revise':raise SystemExit('Initial/requested strategic goals require a replacement, not KEEP.')
            if 'standing_plan' in response:
                text=response['standing_plan']
                if not isinstance(text,str) or not text.strip() or len(text)>3600:raise SystemExit('Standing plan must be 1–3600 characters.')
                plan_tiers.save_standing(root,game,actor,text.strip())
        dependencies = response.get('dependencies', [])
        if not isinstance(dependencies, list) or len(dependencies) > 24 or any(
                not isinstance(item, str) or len(item) > 200 for item in dependencies):
            raise SystemExit('Dependencies must be at most 24 factual projection paths.')
        plan = {'schema': 1, 'actor': actor, 'game': game, 'generation': generation,
                'source_session': batch['source_session'], 'snapshot': batch['snapshot'],
                'board_tag': snapshot['board_tag'], 'event_seq': snapshot['event_seq'],
                'batch_id': batch_id, 'covered_boundaries': response['covered_boundaries'],
                'boundary_notes':boundary_notes,
                'short_term_plan': short, 'long_term_plan': long_plan,
                'long_term_action': action, 'long_term_rationale': rationale,
                'continuity': continuity, 'dependencies': dependencies}
        if table_talk:plan['table_talk']=table_talk
        if tiered:
            plan['standing_plan']=plan_tiers.standing(root,game,actor)['standing_plan']
            if _stage in {'standing','long_term'}:plan['short_term_plan']=None
        if contract>=3:
            from . import planning_contract
            vocabulary=input_value['symbolic_vocabulary']
            try:
                plan.update(planning_contract=contract,
                    recommendations=planning_contract.recommendations(response.get('recommendations',[]),actor,
                        snapshot['board'],set(vocabulary['cards']),set(vocabulary['object_uids'])),
                    watches=planning_contract.watches(response.get('watches',[]),snapshot['board'],
                        set(vocabulary['cards']),set(vocabulary['object_uids'])))
            except (ValueError,TypeError) as exc:raise SystemExit('Invalid symbolic plan: '+str(exc)) from exc
        if contract>=4:
            from . import sequence_contract
            try:
                plan['action_sequence']=sequence_contract.proposals(response.get('action_sequence',[]),actor,
                    snapshot['board'],set(input_value['symbolic_vocabulary']['object_uids']))
            except ValueError as exc:raise SystemExit('Invalid action sequence: '+str(exc)) from exc
            if response.get('recommendations'):raise SystemExit('Contract 4 derives cast recommendations from action_sequence; do not repeat them.')
            plan['recommendations']=sequence_contract.cast_recommendations(plan['action_sequence'],actor,snapshot['board'])
        if staged:
            plan.update(publication_stage=_stage,publication_complete=final_stage)
            from . import plan_provenance
            origin_prior=prior
            for previous_stage in reversed(planner_stages.sequence(input_value)[:planner_stages.sequence(input_value).index(_stage)]):
                receipt=read(directory/'stage_publications'/(batch_id+'.'+previous_stage+'.json'))
                if receipt:
                    origin_prior=load_plan(directory,receipt['plan_id']);break
            plan_provenance.update(plan,origin_prior,_stage,time.time())
            plan_id=planner_stages.store_plan(directory,plan)
        else:plan_id = put(directory / 'plans', plan)
        latest_id, latest = _latest(directory, root, game, actor)
        mailbox = directory / 'mailboxes' / (pilot_handoff.seat_slug(actor) + '.json')
        if latest is None or (plan['event_seq'], plan['source_session']['accepted_prefix_count']) >= (
                latest['event_seq'], latest['source_session']['accepted_prefix_count']):
            write(mailbox, {'plan_id': plan_id, 'published_at': time.time()})
        result = {'batch_id': batch_id, 'plan_id': plan_id, 'response_digest': response_digest,
                  'state': 'published' if final_stage else 'stage_published', 'published_at': time.time()}
        if staged:
            result.update(stage=_stage,stage_response_digest=_stage_digest)
            reservation(state,batch_id).setdefault('completed_stages',[]).append(_stage)
        write(publication_path, result)
        if final_stage:
            if staged:write(directory/'publications'/(batch_id+'.json'),result)
            for key in batch['job_ids']:
                state['jobs'][key].update(status='published', plan_id=plan_id)
            reservation(state,batch_id)['published_at'] = result['published_at']
        elif staged:
            for key in batch['job_ids']:state['jobs'][key]['plan_id']=plan_id
        if not staged or _stage=='actions':_install_watches(root,game,actor,directory,state,plan_id)
        _save(directory, state)
        from . import operator_view
        operator_view.refresh_plans(root,game)
        return result


def _install_watches(root,game,actor,directory,state,plan_id):
    from . import planner_wakes
    plan=load_plan(directory,plan_id)
    if plan.get('planning_contract',1)<3:return
    mailbox=read(directory/'mailboxes'/(pilot_handoff.seat_slug(actor)+'.json'),{})
    if mailbox.get('plan_id')!=plan_id:return
    sources=state.setdefault('watch_sources',{})
    if sources.get(actor,{}).get('plan_id')!=plan_id:
        sources[actor]={'plan_id':plan_id,'checked_seq':plan['event_seq'],
                        'watches':plan['watches'],'fired':[]}
    snapshot_id=state.get('snapshots',{}).get(actor,plan['snapshot'])
    snapshot=get(directory/'snapshots',snapshot_id)
    # Catch edges that occurred while inference was running. Publication stays
    # independent of the campaign mutex and needs no current gameplay replay.
    for item in planner_wakes.evaluate_watches(actor,sources[actor],
            planner_wakes.history(directory,snapshot,sources[actor]['checked_seq'])):
        _queue_boundary(root,game,state,item,snapshot_id,snapshot['source_session'])


@serialized
def control_alarm(root, actor, claim_id, control_id, value):
    """Wake/schedule without consuming the currently claimed priority choice."""
    from . import handoff_runtime, planning_contract
    if not isinstance(control_id,str) or not control_id.strip() or len(control_id)>200:
        raise SystemExit('Supply one stable control-id for this alarm operation and its retries.')
    action,_,_,_=handoff_runtime.validate_claim(root,actor,claim_id)
    request=pilot_handoff.packet_request(read(Path(action['context'])))
    try:normalized=planning_contract.alarm(value,actor,request)
    except ValueError as exc:raise SystemExit(str(exc)) from exc
    handoff_runtime.acknowledge(root,actor,claim_id)
    game=action['game'];directory=directory_for(root,game)
    with locked(directory,'planning'):
        _live(root,game);state=_state(directory)
        controls=state.setdefault('alarm_controls',{})
        key=identity([actor,control_id])
        binding=identity([claim_id,normalized])
        if key in controls:
            if controls[key]['binding']!=binding:raise SystemExit('Control ID already used for a different alarm.')
            return controls[key]['result']
        from . import planner_wakes
        snapshot_id=state['snapshots'][actor];snapshot=get(directory/'snapshots',snapshot_id)
        item=planner_wakes.apply_alarm(state,actor,normalized,key,snapshot['event_seq'])
        if item:_queue_boundary(root,game,state,item,snapshot_id,snapshot['source_session'])
        result={'state':'planner_control_accepted','control_id':control_id,'decision_consumed':False,
                'alarm':state.get('decider_alarms',{}).get(actor),'queued':item is not None}
        controls[key]={'binding':binding,'result':result}
        _save(directory,state)
        return result


def flatten(value, prefix=''):
    result = {}
    if isinstance(value, dict):
        for key in sorted(value):
            result.update(flatten(value[key], prefix + '/' + str(key).replace('~', '~0').replace('/', '~1')))
    elif isinstance(value, list) and value and all(isinstance(item, dict) and item.get('uid') for item in value):
        for item in value:
            result.update(flatten(item, prefix + '/' + str(item['uid'])))
    else:
        result[prefix] = value
    return result


def factual_board(board):
    # Event chronology is a provenance marker, not by itself a reason to
    # reconsider a line. Material transient events are reported separately.
    return {key:value for key,value in board.items() if key!='seq'}


def attachment(root,action,request,previous_plan_id=None):
    try:return _attachment(root,action,request,previous_plan_id)
    except (SystemExit,OSError,ValueError,KeyError,TypeError):
        return {'plan_id':None,'status':'unavailable','reason':'incompatible_or_corrupt_plan',
                'guidance':'Use your retained strategic reference and current facts. No written fallback or plan validation is required.'}


def _attachment(root, action, request, previous_plan_id=None):
    """Select on first claim only. Callers freeze this value in their receipt."""
    directory = directory_for(root, action['game'])
    plan_id = previous_plan_id; plan = None
    if request.get('planning_contract',1)>=3 or request.get('phase') in {'precombat_main', 'postcombat_main'}:
        plan_id, plan = _latest(directory, root, action['game'], action['actor'])
    elif plan_id:
        plan = load_plan(directory, plan_id)
    if plan and (plan['actor']!=action['actor'] or plan['game']!=action['game'] or
                 not _compatible(plan['source_session'], root, action['game'], action['actor'])):
        plan_id = plan = None
    if not plan:
        return {'plan_id': None, 'status': 'unavailable',
                'guidance': 'Use your retained strategic reference and current facts; no written plan or validation step is required.'}
    source = get(directory / 'snapshots', plan['snapshot'])
    board = request.get('public_state', {})
    dependencies = plan.get('dependencies', [])
    if request.get('planning_contract',1)>=4:
        from . import continuity_diff
        from .sequence_contract import pointer
        changes=continuity_diff.diff(factual_board(source['board']),factual_board(board))
        changed_dependencies=[key for key in dependencies if any(
            row['path']==key or row['path'].startswith(key+'/') or key.startswith(row['path']+'/') for row in changes)]
        unverified=[key for key in dependencies if not pointer(source['board'],key)[0] and not pointer(board,key)[0]]
    else:
        before, after = flatten(factual_board(source['board'])), flatten(factual_board(board))
        changes = [{'path': key, 'before': before.get(key), 'after': after.get(key),
                    'before_present': key in before, 'after_present': key in after}
                   for key in sorted(set(before) | set(after)) if before.get(key) != after.get(key)
                   or (key in before) != (key in after)]
        changed_dependencies=[key for key in dependencies if any(
            row['path']==key or row['path'].startswith(key+'/') for row in changes)]
        unverified=[key for key in dependencies if not any(
            path==key or path.startswith(key+'/') for path in set(before)|set(after))]
    events=events_since(directory,request.get('continuity_event_head'),source['event_seq'])
    material=[event for event in events if event.get('type') not in {
        'scheduler_suppressed','scheduler_control','priority_closed','llm_decision','forced_choice'}]
    # The engine's event counter proves intervening activity even when final
    # object fields match. Do not call equal projections strategically current.
    result = {'plan_id': plan_id, 'status': 'facts_changed' if changes else 'projected_facts_unchanged',
              'source_board_tag': source['board_tag'], 'current_board_tag': identity(factual_board(board)),
              'changes': changes, 'dependencies_changed':changed_dependencies,
              'unverified_dependencies':unverified,
              'event_head':request.get('continuity_event_head'),'source_event_seq':source['event_seq'],
              'intervening_event_count':len(material),'recent_events':material[-16:],
              'earlier_events_omitted':max(0,len(material)-16),
              'coverage': 'Conservative factual snapshot and event comparison; unmodeled restrictions may matter. '
                          'This is historical plan context, never strategic validation or legal authority.'}
    if material:result['status']='facts_changed'
    if request.get('planning_contract',1)>=4:
        from .sequence_contract import size
        # Reconstruct full reports from existing immutable snapshots/journal heads.
        # Do not save another cumulative history/diff file at every decision.
        preview=continuity_diff.preview(changes)
        recent=[]
        for event in reversed(material):
            if len(recent)>=6:break
            if size(recent+[event])<=1800:recent.insert(0,event)
        result.update(changes=preview,change_count=len(changes),changes_omitted=len(changes)-len(preview),
                      comparison_source=plan['snapshot'],recent_events=recent,earlier_events_omitted=len(material)-len(recent),
                      inspection='continuity: full frozen differences/events; sequence: frozen full proposal')
    if plan.get('publication_stage'):
        result.update(publication_stage=plan['publication_stage'],publication_complete=plan['publication_complete'])
    if plan.get('agent_architecture')==1:
        from .goal_validity import project as project_assessment
        assessment=project_assessment(plan.get('goal_assessment'),plan.get('owned_component_ids',{}).get('long_term'))
        if assessment:result['goal_assessment']=assessment
        from .sequence_contract import proposal_readiness
        from .sequence_runtime import executed_plan_steps
        result['proposal_readiness']=proposal_readiness(plan,action['actor'],request,
            executed_plan_steps(root,action['game'],action['actor'],plan_id,plan))
        result['component_refs']={kind:{'component_id':key,'version':get(directory/'plan_components',key)['version']}
            for kind,key in plan.get('owned_component_ids',{}).items() if kind not in {'diplomacy_brief','strategic_answer'}}
        from .diplomacy import project_outcomes
        result['diplomacy_outcomes']=project_outcomes(plan.get('diplomacy_outcomes',[]),
            {'event_seq':board.get('seq',0),'events':events_since(directory,request.get('continuity_event_head'),0)
             if plan.get('diplomacy_outcomes') else []},directory)
        result['diplomacy_outcomes_omitted']=plan.get('diplomacy_outcomes_omitted',0)
    from .table_talk_plan import for_decision
    table_talk=for_decision(plan,request,events)
    if table_talk:result['table_talk_suggestion']=table_talk
    if plan_id != previous_plan_id:
        result['plan'] = {key: plan[key] for key in ('continuity', 'short_term_plan', 'long_term_plan')}
        if plan.get('planning_contract',1)==3:result['plan']['recommendations']=plan.get('recommendations',[])
        if plan.get('planning_contract',1)>=4:result['plan']['action_sequence']=plan.get('action_sequence',[])
        if 'phase_coverage' in plan:result['plan']['phase_coverage']=plan['phase_coverage']
    if 'standing_plan' in plan and previous_plan_id and 'plan' in result:
        previous=load_plan(directory,previous_plan_id)
        result['plan']={key:value for key,value in result['plan'].items() if previous.get(key)!=value}
    from . import context_packets
    if context_packets.enabled(root,action['game']):
        # The pilot presentation already describes events since its last seen
        # board. Do not resend a tail of the whole since-plan engine history.
        result.pop('recent_events',None);result.pop('earlier_events_omitted',None)
        preview,categories=context_packets.plan_changes(changes,changed_dependencies)
        result.update(context_handling=1,changes=preview,changes_omitted=len(changes)-len(preview),
                      changed_categories=categories)
    return result


def events_since(directory,head,since):
    chunks=[]
    while head:
        chunk=get(directory/'events',head)
        if chunk['event_seq']<=since:break
        chunks.append([event for event in chunk['events'] if event.get('seq',0)>since])
        head=chunk['previous']
    return [event for chunk in reversed(chunks) for event in chunk]


def evidence(root, game, actor):
    directory = directory_for(root, game); state = _state(directory)
    jobs = [job for job in state['jobs'].values() if job['actor'] == actor]
    plans = {job['plan_id']: load_plan(directory, job['plan_id']) for job in jobs
             if job.get('plan_id') and job['status']=='published' and _compatible(job['source_session'],root,game,actor)}
    # Partial publications may already have informed accepted pilot decisions.
    for path in (directory/'stage_publications').glob('*.json'):
        receipt=read(path);plan=load_plan(directory,receipt['plan_id'])
        if plan['actor']==actor and _compatible(plan['source_session'],root,game,actor):
            plans[receipt['plan_id']]=plan
    inspections=[]
    for path in (directory/'inspection_receipts').glob('*.json'):
        receipt=get(directory/'inspection_receipts',path.stem)
        if receipt['actor']!=actor:continue
        batch=get(directory/'batches',receipt['batch_id'])
        if _compatible(batch['source_session'],root,game,actor):
            inspections.append({'batch_id':receipt['batch_id'],'receipt_id':path.stem,'results':receipt['results']})
    extra={}
    from .agent_architecture import enabled
    if enabled(root,game):
        from . import component_store,diplomacy
        extra={'current_components':component_store.current(root,game,actor),
               'public_diplomacy_posts':diplomacy.committed_posts(root,game)}
    return {**extra,'jobs': [_job_metadata(job) for job in jobs], 'plans': plans,'inspections':inspections,
            'review_guidance': 'Published, delivered and acted-on plans differ. Use accepted runtime receipts; '
                               'undelivered plans were not decider knowledge. Unfinished mandatory work stays unfinished.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort', type=Path, required=True); parser.add_argument('--game', type=int)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    sub.add_parser('flush-diplomacy')
    sub.add_parser('enable-next-game')
    reserve_parser = sub.add_parser('reserve')
    reserve_parser.add_argument('--admission-id', required=True)
    reserve_parser.add_argument('--host-capacity', type=int, required=True)
    reserve_parser.add_argument('--host-active', type=int, required=True)
    dispatch_parser = sub.add_parser('dispatched')
    dispatch_parser.add_argument('--batch', required=True); dispatch_parser.add_argument('--agent', required=True)
    dispatch_parser.add_argument('--outcome', choices=['accepted', 'unknown', 'rejected'], required=True)
    stop_parser = sub.add_parser('stopped')
    stop_parser.add_argument('--batch', required=True); stop_parser.add_argument('--host-status', required=True)
    for command in ('read', 'publish'):
        item = sub.add_parser(command); item.add_argument('--actor', required=True)
        item.add_argument('--batch', required=True); item.add_argument('--generation', type=int, required=True)
        if command == 'read':
            item.add_argument('--inspect', action='append', dest='queries')
        else:
            item.add_argument('--response', type=Path, required=True)
            item.add_argument('--stage',choices=['standing','short_term','actions','long_term','diplomacy'])
    args = parser.parse_args(argv); root = args.cohort.resolve()
    if args.command=='enable-next-game':result=enable_next_game(root)
    elif args.game is None:parser.error('--game is required except for enable-next-game')
    elif args.command == 'status': result = workboard(root, args.game)
    elif args.command == 'flush-diplomacy':
        from .diplomacy import flush
        result={'refreshed_unclaimed_frontier':flush(root,args.game)}
    elif args.command == 'reserve': result = reserve(root, args.game, admission_id=args.admission_id,
                                                    host_capacity=args.host_capacity, host_active=args.host_active)
    elif args.command == 'dispatched': result = dispatched(root, args.game, args.batch, agent=args.agent, outcome=args.outcome)
    elif args.command == 'stopped': result = stopped(root, args.game, args.batch, host_status=args.host_status)
    elif args.command == 'publish' and args.stage:
        from . import planner_stages
        result=planner_stages.publish(root,args.game,args.actor,args.batch,args.generation,args.stage,json.loads(args.response.read_text(encoding='utf-8-sig')))
    elif args.command == 'publish': result = publish(root, args.game, args.actor, args.batch, args.generation,
                                                     json.loads(args.response.read_text(encoding='utf-8-sig')))
    elif args.queries:
        from . import communications_inspection
        result = communications_inspection.present(inspect_many(
            root, args.game, args.actor, args.batch, args.generation, args.queries))
    else: result = read_job(root, args.game, args.actor, args.batch, args.generation)
    if isinstance(result,dict) and result.get('visible_rule_refs'):
        from .planner_facts import prepare
        result,_=prepare(directory_for(root,args.game),result)
    from . import communications
    result=communications.receipt(communications.present(result,result.get('role','planner') if isinstance(result,dict) else 'planner'))
    print(json.dumps(result, ensure_ascii=False)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
