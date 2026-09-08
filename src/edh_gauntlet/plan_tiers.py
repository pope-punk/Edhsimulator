"""Three-tier planning contract, bound only to newly enrolled games."""
from .runtime_store import read,write,get,put


def enabled(root,game):
    from . import campaign
    return read(campaign.game_dir(root,game)/'game_config.json',{}).get('plan_tiers',False)


def standing(root,game,actor):
    from . import agent_architecture,component_store
    if agent_architecture.enabled(root,game):
        current=component_store.current(root,game,actor)
        if 'standing' not in current:
            from . import static_standing
            return static_standing.standing(root,game,actor) if static_standing.enabled(root,game) else None
        return get(component_store.directory(root,game)/'plan_components',current['standing']['content_id'])
    from . import planner_runtime,pilot_handoff
    directory=planner_runtime.directory_for(root,game)
    binding=read(directory/'standing'/ (pilot_handoff.seat_slug(actor)+'.json'))
    return get(directory/'plan_components',binding['component_id']) if binding else None


def save_standing(root,game,actor,text):
    from .agent_architecture import enabled as split_enabled
    if split_enabled(root,game):raise SystemExit('Standing publication requires the owning long-term reservation.')
    from . import planner_runtime,pilot_handoff,campaign
    directory=planner_runtime.directory_for(root,game)
    seed=campaign._load_game_seed_gameplan_snapshot(directory.parent)
    value={'standing_plan':text}
    old=standing(root,game,actor)
    if old and old!=value:raise SystemExit('The standing plan is immutable for this game.')
    component=put(directory/'plan_components',value)
    write(directory/'standing'/(pilot_handoff.seat_slug(actor)+'.json'),{'component_id':component,'actor':actor,'game':game,'seed_fingerprint':seed['fingerprint']})


def prepare(root,game,actor,value):
    value['plan_tiers']=True
    value['standing_plan']=standing(root,game,actor)
    value['standing_only']=all(r.get('reason')=='standing_initialization' for r in value['requirements'])
    value['initial_goal_required']=not value['standing_only'] and not (value.get('prior_plan') or {}).get('long_term_plan')
    value['guidance']='Standing: immutable deck capabilities (3600 characters). Long-term: concrete core, generated events, matching payoff, missing pieces/acquisition, survival and pivot cue (1200 characters). Short-term: next-turn sequencing (600 characters), then symbolic actions. Initial goal follows the settled hand; later replacements require the pilot request. Follow publication_stages in order. Read own rationales. Initialize roles/deck/seed once per logical seat/game; reuse retained knowledge after checkpoints and inspect only material uncertainties. Privacy rules apply globally; do not spend goal text repeating unknown-opponent boilerplate.'
    for requirement in value['requirements']:
        requirement.pop('opening_information_boundary',None)


def order(value):
    stages=[] if value.get('standing_plan') else ['standing']
    if value.get('standing_only'):return stages
    if value.get('initial_goal_required') or any(r.get('long_term_requested') for r in value['requirements']):stages.append('long_term')
    return stages+['short_term','actions']


def anchors(root,game,actor,role):
    """Authoritative durable context; no other seat or ordered-library content."""
    from . import campaign,planner_runtime
    if role in {'planner','long_term_planner'}:
        seed=campaign._load_game_seed_gameplan_snapshot(campaign.game_dir(root,game))
        result={'full_seed_plan':seed['pilots'][actor]['text']}
        if role=='long_term_planner':
            from .messaging_reference import own
            result['messaging_personality']=own(root,game,actor)
        return result
    if role=='diplomacy':
        from .messaging_reference import own
        return {'messaging_personality':own(root,game,actor)}
    base=standing(root,game,actor)
    _,plan=planner_runtime._latest(planner_runtime.directory_for(root,game),root,game,actor)
    result={'long_term_plan':(plan or {}).get('long_term_plan')}
    from .agent_architecture import enabled as split_enabled,SHORT
    from . import static_standing
    opening=role=='decider' and static_standing.enabled(root,game) and not result['long_term_plan']
    if role==SHORT or not split_enabled(root,game) or opening:
        result['standing_plan']=base['standing_plan'] if base else None
    return result


def pilot_ready(root,game,actor,request):
    if not enabled(root,game):return True
    values=anchors(root,game,actor,'decider')
    if not standing(root,game,actor):return False
    from . import static_standing
    if static_standing.enabled(root,game):return True
    # Mulligan choices establish the opening hand. The first actual turn's
    # sequence must then have the automatically initialized strategic goal.
    return bool(values['long_term_plan'] or request.get('phase') not in {'precombat_main','postcombat_main'})
