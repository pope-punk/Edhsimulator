"""Opt-in omniscient operator display, never part of a seat packet."""
from pathlib import Path
from .runtime_store import read,locked

START='<!-- OPERATOR PLANS START -->'
END='<!-- OPERATOR PLANS END -->'


def enabled(root):return read(Path(root)/'OPERATOR_VIEW.json',{}).get('enabled') is True
def is_current(root,game):
    return read(Path(root)/'cohort.json',{}).get('active_game',game)==game


def path(root,actor):
    from .pilot_handoff import seat_slug
    return Path(root)/'operator'/f'{seat_slug(actor)}.md'
def quoted(text):return '\n'.join('> '+line for line in str(text).splitlines())


def plans(root,game,actor=None):
    from .plan_provenance import label
    from . import planner_runtime,campaign
    directory=planner_runtime.directory_for(root,game)
    actors=[actor] if actor is not None else list(planner_runtime._state(directory).get('snapshots',{}))
    lines=[START,'## Current published plans','',
        'Latest publication per seat; a pilot with an already claimed decision may still hold an older version.','']
    for actor in actors:
        pid,plan=planner_runtime._latest(directory,root,game,actor)
        lines += [f'### {actor}','']
        if not plan:
            lines += ['Short-term plan: not published yet.','',
                      'Long-term plan: not published yet; the immutable seed remains the strategic baseline.','']
            continue
        if plan.get('standing_plan'):
            lines += ['**Standing plan (immutable)**','',quoted(plan['standing_plan']),'']
        lines += [f"Version `{pid[:12]}`; source after decision {plan['source_session']['accepted_prefix_count']}; stage: {plan.get('publication_stage','complete')}.",'',
                  '**Short-term plan**',label(plan,'short_term'),'',quoted(plan.get('short_term_plan') or 'Not published yet.'),'',
                  '**Long-term plan**',label(plan,'long_term'),'',quoted(plan.get('long_term_plan') or 'Not requested/published yet; immutable seed remains the strategic baseline.'),'']
        if plan.get('goal_assessment'):
            from .goal_validity import project,presentation
            lines += ['**Tactical assessment of strategic guidance**',presentation(project(plan['goal_assessment'],plan.get('owned_component_ids',{}).get('long_term'))),'']
        if plan.get('table_talk'):
            draft=plan['table_talk']
            target=draft.get('message_recipient') or draft['message_address']
            lines += ['**Suggested table talk (private draft; pilot decides)**','',
                      f'To: {target}',quoted(draft['message_text']),quoted('Purpose: '+draft['rationale']),'']
        if plan.get('agent_architecture')==1:
            from . import component_store
            current=component_store.current(root,game,actor)
            lines+=['**Component ownership and versions**','',
                *[f"- {k}: v{v['version']}, {v['writer']}, source after decision {v['source_session']['accepted_prefix_count']}." for k,v in current.items()],'']
            if plan.get('strategic_answer'):lines+=['**Latest strategic answer**','',quoted(plan['strategic_answer']['rationale']),'']
            if plan.get('diplomacy_brief'):lines+=['**Diplomacy objective (private authorization)**','',quoted(plan['diplomacy_brief']['objective']),'']
            if plan.get('diplomacy_outcomes'):lines+=['**Advisory diplomatic outcomes**','',*[quoted(str(r)) for r in plan['diplomacy_outcomes']],'']
    lines.append(END);return '\n'.join(lines)


def checkpoint(root,config,game,request,decision_count,state):
    if not enabled(root) or game is None or not is_current(root,config['game']):return
    from .campaign import atomic_text,_messageboard_markdown
    # Lock order matches publication: planning, then operator. No private state
    # is copied to any tool response, brief, status.md or seat context.
    with locked(Path(root)/f"game_{config['game']:02d}"/'continuity','planning'),locked(root,'operator-view'):
        header=['# PRIVATE — operator view','',
            'Private seat report. Operator use only; never provide this file to a pilot or planner. Ordered libraries are excluded.','',
            f"Game {config['game']:02d} | accepted decisions: **{decision_count}** | next decision: **{(request or {}).get('decision_id','none')}**",'',
            f"State: {state} | round {game.round} | turn {game.turn_number} | phase {game.phase}",'']
        header += ['Turn order: '+ ' → '.join(game.turn_order),
                   'Active player: '+game.turn_order[game.active_idx],
                   'Living seats: '+', '.join(actor for actor in game.turn_order if not game.players[actor].eliminated),'']
        messageboard=_messageboard_markdown(config['game'],game.public_messageboard)
        for actor,player in game.players.items():
            lines=list(header)
            life='infinite (adjudicated)' if player.dungeon.get('adjudicated_infinite_life') else player.life
            lines += [f'## {actor}', '',f'Life: **{life}**'+(' — eliminated' if player.eliminated else ''),'','### Cards in hand','']
            lines += [f'- {card.d.name} [{card.uid}] — {card.d.mana_cost or "no mana cost"} | {card.d.type_line}' for card in player.hand] or ['Empty.']
            lines += ['','### Graveyard','']
            lines += [f'- {card.d.name} [{card.uid}] — {card.d.type_line}' for card in player.graveyard] or ['Empty.']
            lines += ['','### Permanents controlled','']
            for permanent in player.battlefield:
                flags=['tapped' if permanent.tapped else 'untapped']
                if permanent.counters:flags.append('counters: '+str(permanent.counters))
                if permanent.copy_of:flags.append('copy: '+permanent.copy_of)
                lines.append(f'- {permanent.name} [{permanent.uid}] — '+ '; '.join(flags))
            if not player.battlefield:lines.append('None.')
            if player.treasures:lines.append(f'- Treasure tokens (aggregate ledger): {player.treasures}')
            lines.append('')
            lines += [plans(root,config['game'],actor),'',messageboard]
            atomic_text(path(root,actor),'\n'.join(lines)+'\n')
        (Path(root)/'operator'/'STATUS.md').unlink(missing_ok=True)


def refresh_plans(root,game):
    if not enabled(root) or not is_current(root,game):return
    from .campaign import atomic_text
    with locked(root,'operator-view'):
        from .engine import DECK_HEADINGS
        for actor in DECK_HEADINGS:
            target=path(root,actor)
            if not target.exists():continue
            text=target.read_text(encoding='utf8')
            before,marker,rest=text.partition(START)
            if marker and END in rest:
                atomic_text(target,before+plans(root,game,actor)+rest.split(END,1)[1])


def split_existing(root):
    """Migrate a paused display without replaying or inspecting any library."""
    from .engine import DECK_HEADINGS
    from .campaign import atomic_text
    with locked(root,'operator-view'):
        legacy=Path(root)/'operator'/'STATUS.md'
        if not legacy.exists():return []
        text=legacy.read_text(encoding='utf8')
        board,marker,tail=text.partition(START)
        plan_text,end_marker,messageboard=tail.partition(END)
        if not marker or not end_marker:raise ValueError('Unrecognized operator display')
        header=board.split('## ',1)[0]
        # Split only level-two/three headings at the start of a line; hand and
        # permanent subsections belong to the seat above them.
        import re
        sections=re.split(r'^## (.+)\n',board,flags=re.M)
        bodies=dict(zip(sections[1::2],sections[2::2]))
        sections=re.split(r'^### (.+)\n',plan_text,flags=re.M)
        plan_bodies=dict(zip(sections[1::2],sections[2::2]))
        if any(actor not in bodies for actor in DECK_HEADINGS):raise ValueError('Missing seat in operator display')
        targets=[]
        for actor in DECK_HEADINGS:
            rendered=header+f'## {actor}\n'+bodies[actor]+START+'\n## Current published plans\n\n'+f'### {actor}\n'+plan_bodies.get(actor,'Not published yet.\n\n')+END+messageboard
            target=path(root,actor);atomic_text(target,rendered);targets.append(target)
        legacy.unlink()
        return targets
