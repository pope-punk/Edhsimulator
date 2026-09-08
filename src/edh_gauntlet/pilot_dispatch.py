"""Mechanical routing of prepared private deliveries to registered seat agents.

Only paths, identities and lifecycle metadata leave this module. The operator
still owns agent creation and gameplay remains entirely pilot-authored.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .paths import PROJECT_ROOT
from .runtime_store import serialized
from . import campaign, pilot_handoff, pilot_session, quarantine

POLICY_REVISION=5


def agent_target(value):
    """Return a sibling-safe canonical collaboration target."""
    return value if value.startswith('/') else '/root/'+value


def registry_path(root,game):return campaign.game_dir(root,game)/'pilot_agents.json'


def registry(root,game):
    path=registry_path(root,game)
    return campaign.read_json(path) if path.exists() else {}


def invalidate_registry(root,game):
    """Forget agent identities after a branch-wide context invalidation."""
    registry_path(root,game).unlink(missing_ok=True)


@serialized
def mark_observed(root,action):
    records=registry(root,action['game']);record=records.get(action['actor'])
    if not record:return
    rows=campaign.read_jsonl(campaign.game_dir(root,action['game'])/'decisions.jsonl')
    if pilot_handoff.can_resume_session(record['seat_session'],root,action['game'],action['actor'],rows):
        record['seat_session']=pilot_handoff.session_descriptor(root,action['game'],action['actor'],rows)
        cache=pilot_session._session_path(root,action)
        if cache.exists() and campaign.read_json(cache).get('last_delivery_id')==record.get('bootstrap_delivery_id'):
            record.pop('bootstrap_delivery_id',None)
        record['policy_revision']=POLICY_REVISION
        record.pop('bootstrap_required',None)
        campaign.write_json(registry_path(root,action['game']),records)


def build_route(root,action):
    from . import planner_runtime, handoff_runtime
    if planner_runtime.enabled(campaign.game_dir(root,action['game'])):
        return handoff_runtime.build_route(root,action)
    rows=campaign.read_jsonl(campaign.game_dir(root,action['game'])/'decisions.jsonl')
    record=registry(root,action['game']).get(action['actor'])
    compatible=bool(record and pilot_handoff.can_resume_session(
        record['seat_session'],root,action['game'],action['actor'],rows))
    cache=pilot_session._session_path(root,action)
    saved=campaign.read_json(cache) if cache.exists() else None
    bootstrap=bool(record and record.get('bootstrap_delivery_id') and
                   (saved or {}).get('last_delivery_id')!=record['bootstrap_delivery_id'])
    delivery=pilot_session.prepare(root,action,fresh=not compatible or bootstrap)
    # A stale renderer must never be silently attached to a continuing agent.
    if delivery['mode']=='fresh' and record and compatible:
        if cache.exists() and not pilot_handoff.can_resume_session(
            campaign.read_json(cache)['seat_session'],root,action['game'],action['actor'],rows):
            compatible=False
    path=delivery['turn']
    policy=PROJECT_ROOT/'docs/PILOT_RUNTIME_POLICY.md'
    prompt=f"Continue your seat from this prepared private update: {path}"
    if not compatible:
        prompt=(f"You are the isolated {action['actor']} pilot in {Path(root).resolve().parent}. "
                f"Read {policy} once, then read your prepared private update: "+path)
    elif record.get('policy_revision')!=POLICY_REVISION:
        prompt=f"Retain your seat context. Read the runtime policy update once: {policy}. Then continue from {path}"
    kind='resume' if compatible else 'spawn'
    return {'kind':kind,'actor':action['actor'],
            'agent':agent_target(record['agent']) if compatible else None,
            'handoff_transport':'direct_followup_task' if compatible else 'coordinator_spawn',
            'coordinator_relay_allowed':False,
            'decision_id':action['decision_id'],'pilot_context_id':action['pilot_context_id'],
            'seat_session':pilot_handoff.session_descriptor(root,action['game'],action['actor'],rows),
            **delivery,'prompt':prompt}


def refresh(root):
    return campaign.next_action(root)['next_action']


@serialized
def register(root,actor,agent,*,previous=None):
    campaign._require_no_prepared_learning_transaction(root,'register a seat context')
    action=pilot_session.next_action(root)
    if action['kind']!='dispatch_pilot':raise SystemExit('Follow the pending lifecycle action before registering pilots.')
    game=action['game']
    quarantine.require_clean(campaign.DEFAULT_STRATEGY_FILE,root,game)
    if actor not in campaign.PILOT_GAMEPLAN_FILES:raise SystemExit('Unknown pilot seat.')
    if not isinstance(agent,str) or not agent.strip() or any(c in agent for c in '\r\n'):
        raise SystemExit('Supply one agent identity.')
    rows=campaign.read_jsonl(campaign.game_dir(root,game)/'decisions.jsonl')
    if previous is not None:
        if not pilot_handoff.can_resume_session(previous,root,game,actor,rows):
            raise SystemExit('Existing seat context is not valid on this branch.')
    elif actor!=action['actor']:
        raise SystemExit('A new seat context must register at its own dispatch.')
    records=registry(root,game)
    from . import planner_runtime
    split=planner_runtime.enabled(campaign.game_dir(root,game))
    if split and actor in records and pilot_handoff.can_resume_session(records[actor]['seat_session'],root,game,actor,rows):
        if records[actor]['agent']==agent:return refresh(root)
        raise SystemExit('Fence the old decider through handoff_runtime recover before replacement.')
    record={'agent':agent,'seat_session':previous or pilot_handoff.session_descriptor(root,game,actor,rows),
            'policy_revision':POLICY_REVISION}
    if split and previous is None:record['bootstrap_required']=True
    if previous is None and not split:
        # Registration can race the new pilot's first read. Preserve the full
        # delivery already dispatched instead of advancing its renderer cache.
        delivery=action.get('dispatch') or {}
        if delivery.get('kind')!='spawn' or delivery.get('mode')!='fresh':
            delivery=pilot_session.prepare(root,action,fresh=True)
        record['bootstrap_delivery_id']=delivery['delivery_id']
    records[actor]=record
    campaign.write_json(registry_path(root,game),records)
    return refresh(root)


@serialized
def adopt(root,path):
    """Validate and import the earlier coordinator's metadata-only registry."""
    campaign._require_no_prepared_learning_transaction(root,'adopt seat contexts')
    action=pilot_session.next_action(root)
    if action['kind']!='dispatch_pilot':raise SystemExit('Follow the pending lifecycle action before adopting pilots.')
    game=action['game'];quarantine.require_clean(campaign.DEFAULT_STRATEGY_FILE,root,game)
    rows=campaign.read_jsonl(campaign.game_dir(root,game)/'decisions.jsonl')
    records=campaign.read_json(path)
    for actor,record in records.items():
        if actor not in campaign.PILOT_GAMEPLAN_FILES or not isinstance(record.get('agent'),str):
            raise SystemExit('Invalid seat registry entry.')
        if not pilot_handoff.can_resume_session(record.get('seat_session',{}),root,game,actor,rows):
            raise SystemExit('Cannot adopt a stale seat context: '+actor)
    campaign.write_json(registry_path(root,game),{
        actor:{'agent':record['agent'],'seat_session':record['seat_session'],'policy_revision':0}
        for actor,record in records.items()})
    return refresh(root)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort',type=Path,required=True)
    sub=parser.add_subparsers(dest='command',required=True)
    create=sub.add_parser('register',help='register a newly created isolated seat agent')
    create.add_argument('--actor',required=True);create.add_argument('--agent',required=True)
    migrate=sub.add_parser('adopt',help='adopt existing agents after validating their saved descriptors')
    migrate.add_argument('--registry',type=Path,required=True)
    sub.add_parser('next',help='refresh metadata after an interruption or lifecycle command')
    args=parser.parse_args(argv);root=args.cohort.resolve()
    if args.command=='register':result=register(root,args.actor,args.agent)
    elif args.command=='adopt':result=adopt(root,args.registry)
    else:result=refresh(root)
    print(json.dumps(result,ensure_ascii=False));return 0


if __name__=='__main__':raise SystemExit(main())
