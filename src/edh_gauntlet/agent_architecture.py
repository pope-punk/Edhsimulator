"""Explicit game binding and role identities for the split planning architecture."""
from pathlib import Path
from .runtime_store import read, write, locked

VERSION=1
SHORT='short_term_planner'
LONG='long_term_planner'
DIPLOMACY='diplomacy'
PLANNERS=frozenset({'planner',SHORT,LONG})
MODELS={'decider':'gpt-5.6-terra',SHORT:'gpt-5.6-sol',LONG:'gpt-5.6-sol',DIPLOMACY:'gpt-5.6-luna'}
LEGACY_MODELS={**MODELS,SHORT:'gpt-5.6-terra'}
EFFORTS={'decider':'low',SHORT:'high',DIPLOMACY:'low'}


def config(root,game):
    return read(Path(root)/f'game_{game:02d}'/'game_config.json',{})


def enabled(root,game):return config(root,game).get('agent_architecture')==VERSION


def models(root,game):
    return dict(MODELS if config(root,game).get('short_term_sol_fast')==1 else LEGACY_MODELS)


def service_tier(root,game,role):
    return 'fast' if role==SHORT and config(root,game).get('short_term_sol_fast')==1 else None


def diplomacy_enabled(root,game):
    value=config(root,game)
    return value.get('agent_architecture')==VERSION and value.get('async_diplomacy')==VERSION


def is_planner(role):return role in PLANNERS

def is_background(role):return is_planner(role) or role==DIPLOMACY


def registration_key(actor,role='planner'):
    return actor if role=='planner' else actor+'::'+role


def roles(root,game):
    if not enabled(root,game):return ('decider','planner')
    return ('decider',SHORT,LONG)+((DIPLOMACY,) if diplomacy_enabled(root,game) else ())


def validate_binding(value):
    for key in ('agent_architecture','async_diplomacy','decision_roles','static_standing','combat_proposals','turn_batches','short_term_sol_fast'):
        if value.get(key) is not None and type(value[key]) is not int:
            raise ValueError(f'{key} must be an integer version.')
    if value.get('short_term_sol_fast') not in (None,1):raise ValueError('Unknown short-term model policy.')
    if value.get('short_term_sol_fast') and value.get('agent_architecture')!=1:
        raise ValueError('Sol Fast short-term planning requires split planning.')
    if value.get('agent_architecture') not in (None,VERSION):raise ValueError('Unknown agent architecture.')
    if value.get('async_diplomacy') not in (None,VERSION):raise ValueError('Unknown diplomacy contract.')
    if value.get('decision_roles') not in (None,1):raise ValueError('Unknown decision role contract.')
    if value.get('turn_batches') not in (None,1):raise ValueError('Unknown full-turn batch policy.')
    if value.get('turn_batches') and value.get('agent_architecture')!=1:raise ValueError('Full-turn batches require split planning.')
    if value.get('combat_proposals') not in (None,1):raise ValueError('Unknown combat proposal guidance version.')
    if value.get('combat_proposals') and value.get('agent_architecture')!=1:raise ValueError('Combat proposals require split planning.')
    if value.get('static_standing') not in (None,1):raise ValueError('Unknown standing-plan contract.')
    if value.get('static_standing') and value.get('agent_architecture')!=1:
        raise ValueError('Static standing plans require split planning.')
    if value.get('decision_roles') and value.get('async_diplomacy')!=1:raise ValueError('Decision roles require asynchronous diplomacy.')
    if value.get('async_diplomacy') and value.get('agent_architecture')!=VERSION:
        raise ValueError('Asynchronous diplomacy requires split planning.')
    if value.get('agent_architecture') and not (value.get('planning_contract')==4 and
            value.get('plan_tiers') and value.get('planner_stages') and value.get('context_handling')==1):
        raise ValueError('Split planning requires staged three-tier contract 4 and context handling 1.')


def enroll(root,game,*,diplomacy=False):
    """Explicit enrollment only before any role, accepted choice or packet exists."""
    root=Path(root);directory=root/f'game_{game:02d}'
    with locked(root),locked(directory/'continuity','planning'):
        value=config(root,game)
        if not value:raise ValueError('Enroll an initialized, unstarted configuration.')
        if any((directory/name).exists() for name in ('pilot_turns','continuity/workboard.json','handoffs')):
            raise ValueError('Game already prepared role/decision inputs; initialize a fresh cohort with the architecture flag.')
        tape=directory/'decisions.jsonl'
        if tape.exists() and tape.read_bytes().strip():raise ValueError('Never migrate an accepted game.')
        value['agent_architecture']=VERSION
        value['short_term_sol_fast']=1
        if diplomacy:value['async_diplomacy']=VERSION
        validate_binding(value);write(directory/'game_config.json',value)
        return {'game':game,'agent_architecture':VERSION,'async_diplomacy':diplomacy}
