"""Fresh-game decision ownership and replay-bound tactical combo offers.

Publications never edit a claimed request. One current proposal per seat is
committed at an unclaimed frontier; the small journal preserves replay timing.
"""
from .runtime_store import read, write, get, identity, locked


def enabled(root, game):
    from .agent_architecture import config
    return config(root, game).get('decision_roles') == 1


COMBO_SCHEMA = {'type':'object','properties':{
    'proposal_text':{'type':'string','minLength':1,'maxLength':1200},
    'seat_turn':{'type':'integer','minimum':1},
    'phase':{'type':'string','enum':['precombat_main','postcombat_main']},
    'requires':{'type':'array','maxItems':8,'items':{'type':'object'}}},
    'required':['proposal_text','seat_turn','phase','requires'],'additionalProperties':False}


def normalize_combo(value, actor, board):
    from .sequence_contract import proposals
    if not isinstance(value,dict) or set(value)!=set(COMBO_SCHEMA['required']):
        raise ValueError('combo_proposal requires proposal_text, seat_turn, phase and requires.')
    if not isinstance(value['proposal_text'],str) or not 0<len(value['proposal_text'].strip())<=1200:
        raise ValueError('Combo proof must be 1–1200 characters.')
    if value['phase'] not in ('precombat_main','postcombat_main'):
        raise ValueError('Combo proposals target a named main phase.')
    # Reuse the same typed timing and factual guard validation as approved steps.
    proposals([{'id':'combo','seat_turn':value['seat_turn'],'phase':value['phase'],
        'kind':'main_action','choice':None,'rationale':'Review proposed loop.',
        'scheduler':{'mode':'hold_full_control'},'requires':value['requires']}],actor,board,set())
    return {**value,'proposal_text':value['proposal_text'].strip()}


def deliveries(root, game):
    from .component_store import directory
    from .planner_runtime import _compatible
    return [r for r in read(directory(root,game)/'combo_deliveries.json',[])
            if _compatible(r['source_session'],root,game,r['actor'])]


def offer(runtime, player):
    from .sequence_contract import guards_hold
    if not runtime.decision_roles:return ('propose_combo_loop',None,{})
    latest=None
    for row in runtime.combo_deliveries:
        if row['actor']==player.name and row['after_decision']<=runtime.decision_counter:latest=row
    if not latest or not latest.get('proposal') or latest['id'] in runtime.used_combo_proposals:return None
    value=latest['proposal'];board=runtime.redacted_snapshot(player.name)
    if (board.get('active')!=player.name or runtime.phase!=value['phase'] or
        board.get('planning_clock',{}).get('seat_turns',{}).get(player.name)!=value['seat_turn'] or
        guards_hold(value['requires'],board)):return None
    return ('propose_combo_loop',None,{'planner_proposal_id':latest['id']})


def flush(root, game):
    """Publish current tactical recommendations before claim, never during inference."""
    if not enabled(root,game):return False
    from . import campaign, pilot_handoff, component_store as components
    d=components.directory(root,game)
    with locked(root),locked(d,'planning'):
        components.recover(root,game)
        refresh=read(d/'combo_refresh.json')
        if refresh:
            if len(campaign.read_jsonl(root/f'game_{game:02d}'/'decisions.jsonl'))!=refresh['after_decision']:
                raise SystemExit('Reconcile prepared combo delivery before accepting a decision.')
            campaign.advance(root,game)
            (d/'combo_refresh.json').unlink()
            return True
        action=read(root/'NEXT_ACTION.json',{}).get('next_action',{})
        if action.get('kind')!='dispatch_pilot' or action.get('game')!=game:return False
        route=read(root/f'game_{game:02d}'/'handoffs'/'routes'/(action['dispatch']['route_id']+'.json'),{})
        if route.get('claim_id'):return False
        rows=deliveries(root,game);changed=False
        decisions=campaign.read_jsonl(root/f'game_{game:02d}'/'decisions.jsonl')
        for actor in read(d/'workboard.json',{}).get('snapshots',{}):
            current_components=components.current(root,game,actor)
            current=current_components.get('actions')
            if not current:continue
            key=identity(current)
            previous=next((r for r in reversed(rows) if r['actor']==actor),None)
            proposal=get(d/'plan_components',current['content_id']).get('combo_proposal')
            if current.get('dependent_versions',{}).get('short_term')!=current_components.get('short_term',{}).get('version'):proposal=None
            if previous and previous['id']==key and previous.get('proposal')==proposal:continue
            if not proposal and (not previous or not previous.get('proposal')):continue
            rows.append({'actor':actor,'id':key,'proposal':proposal,'after_decision':len(decisions),
                         'source_session':pilot_handoff.session_descriptor(root,game,actor,decisions)})
            changed=True
        if changed:
            write(d/'combo_refresh.json',{'after_decision':len(decisions)})
            write(d/'combo_deliveries.json',rows)
            campaign.advance(root,game)
            (d/'combo_refresh.json').unlink(missing_ok=True)
        return changed


def proposal_by_id(runtime, key):
    return next(row['proposal'] for row in reversed(runtime.combo_deliveries) if row['id']==key and row.get('proposal'))


def presentation(request):
    import json
    value=request.get('planner_combo')
    if not value:return ''
    return 'Short-term planner combo proposal (approve only if valid now; selecting menu option '+str(value['option_index']+1)+' submits this exact proof): '+json.dumps(value,ensure_ascii=False,separators=(',',':'))
