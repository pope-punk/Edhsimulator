"""Read-only operator projections and journal-bound physical-card statistics.

Operator aggregates are never supplied to role contexts. No reporting path opens
an ordered library, submits commands, recovers pending inputs or starts inference.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import zlib
from .runtime_store import read
from .rules_adapter import digest
from .rules_state import Zone,RulesViolation

ACTOR='Reaminatour'


def deck_rows(root):
    from .catalog import load_catalog
    catalog=load_catalog(Path(root)/'data/catalog/cards.json')
    config=read(Path(root)/'data/decks/pod_configuration.json')
    commander=next(row['commander'] for row in config['seats'] if row['actor']==ACTOR)
    return sorted([{'card':card.name,'quantity':occurrence.quantity,'commander':card.card_id==commander}
                   for card,occurrence in catalog.deck_entries(ACTOR)],key=lambda r:(not r['commander'],r['card']))


def capture_statistics(campaign,state):
    """Capture actual zone entries, including transient ETBs and original copy identity."""
    kernel=campaign.kernel
    if not hasattr(campaign,'_report_card_names'):
        from .catalog import load_catalog
        campaign._report_card_names={'catalog:'+card.card_id:card.name for card in load_catalog(campaign.assets/'data/catalog/cards.json')}
    def printed_name(obj):return campaign._report_card_names.get(obj.definition,kernel.definitions[obj.definition].name)
    stats=state.setdefault('operator_statistics',{'seen':[],'cast':[],'zone_cursor':0,'event_cursor':0})
    seen=set(stats['seen']);cast=set(stats['cast'])
    def observe(obj,zone):
        if obj.owner!=ACTOR or obj.token or obj.spell_copy:return
        name=printed_name(obj)
        if zone in (Zone.HAND,Zone.BATTLEFIELD,Zone.GRAVEYARD):seen.add(name)
        if zone==Zone.BATTLEFIELD:cast.add(name)
    # The initial hand exists before the first host capture. Do not enumerate libraries.
    if not stats['zone_cursor']:
        for zone in (Zone.HAND,Zone.BATTLEFIELD,Zone.GRAVEYARD):
            for obj in kernel.state.objects(zone):observe(obj,zone)
    for event in kernel.state.events_since(stats['zone_cursor']):observe(event.after,event.after.zone)
    for event in kernel.semantic_events[stats['event_cursor']:]:
        if event['kind']=='spell_cast':
            try:obj=kernel.state.get(kernel.state.current(event['source']['card_id']))
            except (KeyError,RulesViolation):continue
            if obj.owner==ACTOR and not obj.token and not obj.spell_copy:cast.add(printed_name(obj))
    stats.update(seen=sorted(seen),cast=sorted(cast),zone_cursor=kernel.state.event_count,event_cursor=len(kernel.semantic_events))


@contextmanager
def connection(directory):
    db=sqlite3.connect((Path(directory)/'rules.sqlite').resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
    try:
        db.execute('BEGIN')
        yield db
    finally:db.close()


def state_of(db):return json.loads(db.execute('SELECT value FROM host_state WHERE id=1').fetchone()[0])


def verified_result(directory):
    """Verify completed report evidence without restoring or mutating the engine."""
    from .primitive_journal import verify
    directory=Path(directory);seal=read(directory/'terminal_result.json',{})
    if not seal:raise RulesViolation('Game is not complete')
    with connection(directory) as db:
        header_text,genesis=db.execute('SELECT data,sha FROM header WHERE id=1').fetchone()
        header=json.loads(header_text);binding=header['binding']
        config=read(directory/'game_config.json')
        if digest(header)!=genesis or digest(config)!=binding['contract_sha256']:
            raise RulesViolation('Game configuration or durable header changed')
        if config.get('campaign') and digest(read(directory.parent/'deck_snapshot.json',[]))!=config['campaign']['deck_sha256']:
            raise RulesViolation('Frozen report deck changed')
        previous=genesis;count=0
        for seq,request_id,payload,sha in db.execute('SELECT seq,request_id,entry,sha FROM commands ORDER BY seq'):
            entry=json.loads(payload)
            if (seq!=count+1 or entry['seq']!=seq or entry['request_id']!=request_id or
                entry['previous']!=previous or digest(entry)!=sha):raise RulesViolation('Accepted command chain changed')
            previous=sha;count=seq
        head={'sequence':count,'sha256':previous}
        if tuple(db.execute('SELECT seq,chain FROM head WHERE id=1').fetchone())!=(count,previous):
            raise RulesViolation('Durable head changed')
        journal=verify(db,binding);state=state_of(db)
        if seal!={**(state['terminal'] or {}),'host_commit':journal} or seal['rules_commit']!=head:
            raise RulesViolation('Terminal result differs from verified journals')
        skip=read(directory/'postgame_learning/skipped.json',{})
        if skip!={'status':'skipped_by_configuration','terminal_sha256':digest(seal),'rules_commit':head}:
            raise RulesViolation('Learning skip does not match the terminal result')
        if state['blocker'] or seal.get('tag')=='rules_review':raise RulesViolation('Rules review is pending')
        if 'operator_statistics' not in state:raise RulesViolation('Historical game has no bound card statistics')
        return seal,state['operator_statistics'],binding


def result_rows(root):
    result=[]
    for directory in sorted(Path(root).glob('game_[0-9]*')):
        if not (directory/'rules.sqlite').exists():continue
        number=int(directory.name[5:]);seal=read(directory/'terminal_result.json',{})
        winner=next(iter(seal.get('winners',[])),None)
        blocked=seal.get('tag')=='rules_review'
        result.append({'game':number,'state':'complete' if seal else 'playing','winner':winner,
            'losers':[],'outcome':('win' if winner else 'draw') if seal else 'in_progress',
            'rules_review_pending':blocked,'decisions':seal.get('rules_commit',{}).get('sequence'),
            'narrative':('Stopped for rules review; excluded from verified card statistics.' if blocked else
                         f'{winner} won.' if winner else 'Recorded draw.' if seal else None),
            'narrative_state':'complete' if seal else 'waiting_for_result','author':'Recorded game result',
            'ai_outcome_estimate':None})
    return result


def cardwise(root):
    from .cardwise_report import SEEN_DEFINITION,CAST_DEFINITION
    root=Path(root);rows=read(root/'deck_snapshot.json',[])
    if not rows:raise RulesViolation('This historical primitive run has no frozen card-report deck')
    if sum(row['quantity'] for row in rows)!=100 or sum(row['commander'] for row in rows)!=1:
        raise RulesViolation('Invalid frozen 100-card deck')
    counts={row['card']:{'games_seen':0,'games_etb_cast':0,'wins_seen':0,'wins_cast':0} for row in rows}
    included=[];excluded=[];pending=0
    for directory in sorted(root.glob('game_[0-9]*')):
        if not (directory/'terminal_result.json').exists():pending+=1;continue
        try:
            seal,stats,binding=verified_result(directory)
            won=ACTOR in seal['winners']
            for name in set(stats['seen'])&counts.keys():counts[name]['games_seen']+=1;counts[name]['wins_seen']+=int(won)
            for name in set(stats['cast'])&counts.keys():counts[name]['games_etb_cast']+=1;counts[name]['wins_cast']+=int(won)
            included.append({'game':binding['game_number'],'winner':next(iter(seal['winners']),None)})
        except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as exc:
            excluded.append({'game':directory.name,'reason':str(exc)})
    for row in rows:
        c=counts[row['card']];row.update(c)
        row['won_if_seen']=100*c['wins_seen']/c['games_seen'] if c['games_seen'] else None
        row['won_if_cast']=100*c['wins_cast']/c['games_etb_cast'] if c['games_etb_cast'] else None
    return {'actor':ACTOR,'commander':next(row['card'] for row in rows if row['commander']),
        'deck_size':100,'rows':rows,'included_games':included,'completed_games':len(included),
        'pending_games':pending,'excluded_games':excluded,'seen_definition':SEEN_DEFINITION,'cast_definition':CAST_DEFINITION,
        'result_definition':'Only verified terminal journals with matching learning-skip receipts count. Rules-review games are excluded. Draws are non-wins; empty denominators are blank.'}


def snapshot(root):
    root=Path(root);manifest=read(root/'cohort.json');number=manifest['active_game']
    directory=root/f'game_{number:02d}'
    with connection(directory) as db:
        state=state_of(db);seq,sha=db.execute('SELECT seq,chain FROM head WHERE id=1').fetchone()
        packets={}
        for actor in state['actors']:
            row=db.execute("SELECT payload FROM host_evidence WHERE actor=? AND kind='observation' ORDER BY seq DESC LIMIT 1",(actor,)).fetchone()
            if row:packets[actor]=json.loads(zlib.decompress(row[0]))
        messages=[json.loads(row[0]) for row in db.execute('SELECT payload FROM host_messages ORDER BY rowid')]
        decisions=[]
        for index,(actor,payload) in enumerate(db.execute("SELECT actor,payload FROM host_evidence WHERE kind='rationale' ORDER BY seq"),1):
            value=json.loads(zlib.decompress(payload));command=value['command']
            decisions.append({'id':f'G{number:02d}-D{index:04d}','actor':actor,
                'action':json.dumps(command,ensure_ascii=False),'rationale':value['rationale']})
        journal=db.execute('SELECT seq,sha256 FROM host_journal ORDER BY seq DESC LIMIT 1').fetchone()
    board=next(iter(packets.values()),{});turn=board.get('turn',{});players={}
    for player in board.get('players',[]):
        actor=player['seat'];players[actor]={**player,'eliminated':player['departed'],
            'hand':packets.get(actor,{}).get('hand',[]),'battlefield':board['zones']['battlefield'][actor]}
    action=read(root/'NEXT_ACTION.json',{}).get('next_action',{})
    actor=action.get('actor');decision=packets.get(actor,{}).get('decision',{})
    choice=decision.get('choice',{});options=choice.get('options',[])
    request={'actor':actor,'kind':decision.get('kind'),'prompt':choice.get('prompt',decision.get('kind','')),
             'options':[o.get('label',str(o)) for o in options]}
    operators={}
    for seat,packet in packets.items():
        text=[f'# {seat} — operator view',f"Turn {turn.get('number',0)} · {turn.get('active','')} · {turn.get('phase','')}"]
        for who,player in players.items():
            text.extend([f"\n## {who} · {player['life']} life",'Hand: '+', '.join(c['name'] for c in player['hand'])])
            for zone in ('battlefield','graveyard','exile','command'):
                text.append(zone.title()+': '+', '.join(c['name']+(' (tapped)' if c.get('tapped') else '') for c in packet['zones'][zone][who]))
        for stage,plan in state['actors'][seat]['plans'].items():text.extend([f'\n## {stage}',json.dumps(plan.get('value'),ensure_ascii=False,indent=2)])
        operators[seat]='\n'.join(text)
    plan=state['actors'].get(actor,{}).get('plans',{}).get('short_term',{}).get('value',{})
    return {'revision':journal[1][:16],'game':number,'manifest':manifest,
        'config':read(directory/'game_config.json'),'next_action':action,'operator':operators,
        'status':{'state':'complete' if state['terminal'] else 'paused' if state['paused'] else 'playing',
            'game':number,'decision_count':seq,'request':request,'result':state['terminal'],
            'public_state':{'active':turn.get('active'),'phase':turn.get('phase'),'turn_number':turn.get('number'),
                'round':(max(1,turn.get('number',1))-1)//4+1,'players':players,'stack':board.get('stack',[])}},
        'messages':[{'sender':m['actor'],'turn':m['turn'],'phase':m.get('phase',''),'message':m['text']} for m in messages],
        'messageboard':'\n\n'.join(f"{m['actor']} · Turn {m['turn']}\n{m['text']}" for m in messages),
        'decision_log':decisions[-250:],'decision_log_total':len(decisions),'all_decisions':decisions,
        'game_results':result_rows(root),'deciding_plan':plan.get('short_term_plan',''),
        'pending_game':action.get('game') if action.get('kind')=='advance_game' else None,'events':[]}
