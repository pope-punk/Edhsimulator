"""Read-only operator card statistics from isolated replays of sealed games.

Never starts model inference, reads ordered libraries, or changes agent artifacts.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ACTOR = 'Reaminatour'
SEEN_DEFINITION = 'Entered hand, battlefield, or graveyard from any source, including opening hands, tutors, mills, and reanimation. Scry alone and the command zone do not count.'
CAST_DEFINITION = 'Cast or entered the battlefield, including land plays and reanimation. Count each card name once per game; %won_if_cast uses this same combined set.'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def deck_rows(root):
    snapshots=sorted(Path(root).glob('game_*/strategy_snapshot.json'))
    if snapshots:
        decks=read(snapshots[-1])['decks']
        deck=next(d for d in decks if d['deck_id']=='reaminatour')
        rows=[{'card':c['card_name'],'quantity':c['quantity'],
               'commander':c['card_id']==deck['commander_card_id']} for c in deck['cards']]
    else:
        from .catalog import load_catalog
        rows=[{'card':card.name,'quantity':occurrence.quantity,'commander':occurrence.ordinal==1}
              for card,occurrence in load_catalog().deck_entries(ACTOR)]
    if sum(r['quantity'] for r in rows)!=100 or sum(r['commander'] for r in rows)!=1:
        raise ValueError('Expected the complete 100-card Aminatou deck, including one commander.')
    return sorted(rows,key=lambda r:(not r['commander'],r['card'].casefold()))


def rules_signature():
    source=Path(__file__).parent
    return hashlib.sha256(b''.join((source/name).read_bytes() for name in (
        'engine.py','referee.py','continuous.py','cardwise_replay.py','cardwise_report.py'))).hexdigest()


def observations(directory,seal):
    import subprocess,sys
    from .runtime_store import read as optional_read,write
    cache=directory.parent/'dashboard'/'cardwise'/f"game_{seal['game']:02d}.json"
    prior=optional_read(cache,{})
    evidence_signature=hashlib.sha256(b''.join(p.read_bytes() for p in sorted([
        directory/'rules_reconciliation.json',directory/'rules_work_items.json',
        directory/'continuity/diplomacy_posts.json',directory/'continuity/combo_deliveries.json']) if p.exists())).hexdigest()
    if prior.get('schema')==3 and prior.get('rules_signature')==rules_signature() and prior.get('evidence_signature')==evidence_signature and prior.get('terminal_fingerprint')==seal['terminal_fingerprint']:
        return set(prior['seen']),set(prior['cast'])
    try:
        result=subprocess.run([sys.executable,'-m','edh_gauntlet.cardwise_replay',str(directory)],
                              capture_output=True,text=True,timeout=300)
    except subprocess.TimeoutExpired as exc:
        raise ValueError('Statistics reconstruction timed out; no counts included.') from exc
    if result.returncode:raise ValueError('Card statistics could not reconstruct the sealed game; no counts included.')
    value=json.loads(result.stdout)
    if (value['decisions_sha256']!=seal['decisions_sha256'] or value['accepted']!=seal['decision_count']):
        raise ValueError('Statistics replay does not match the accepted prefix.')
    terminal=seal['result'].get('terminal')
    if terminal=='rules_blocker_draw':
        if value['state']!='rules_blocker' or value['events']+1!=seal['result']['events']:
            raise ValueError('Statistics replay does not match the sealed rules draw.')
    elif terminal=='adjudicated_draw' and seal['result'].get('rules_reconciliation_id'):
        receipt=read(directory/'rules_reconciliation.json')
        if (receipt.get('terminal_fingerprint')!=seal['terminal_fingerprint'] or
            receipt.get('response_sha256')!=seal['result']['rules_reconciliation_id'] or
            receipt.get('retained')!=seal['decision_count'] or receipt.get('verdict')!='rules_draw' or
            value['state']!='unanswered' or value['events']+1!=seal['result']['events'] or
            seal['result'].get('winner') is not None):
            raise ValueError('Statistics replay does not match the adjudicated rules draw.')
    elif value['state']!='terminal' or value['result']!=seal['result']:
        raise ValueError('Statistics replay does not match the terminal result.')
    seen=set(value['seen']);cast=set(value['cast'])
    write(cache,{'schema':3,'rules_signature':rules_signature(),'evidence_signature':evidence_signature,'terminal_fingerprint':seal['terminal_fingerprint'],'seen':sorted(seen),'cast':sorted(cast)})
    return seen,cast


def eligible_game(directory):
    seal=read(directory/'terminal_result.json');status=read(directory/'status.json')
    if status.get('state')!='complete':raise ValueError('Game is not complete.')
    payload={k:v for k,v in seal.items() if k!='terminal_fingerprint'}
    fingerprint='terminal-'+hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if seal.get('terminal_fingerprint')!=fingerprint:raise ValueError('Terminal seal does not validate.')
    if hashlib.sha256((directory/'decisions.jsonl').read_bytes()).hexdigest()!=seal['decisions_sha256']:
        raise ValueError('Accepted decisions differ from the terminal seal.')
    if hashlib.sha256((directory/'strategy_snapshot.json').read_bytes()).hexdigest()!=seal['strategy_snapshot_sha256']:
        raise ValueError('Deck snapshot differs from the terminal seal.')
    config=read(directory/'game_config.json')
    if config.get('game')!=seal['game'] or config.get('seed')!=seal['seed']:
        raise ValueError('Game identity differs from the terminal seal.')
    if config.get('learning_enabled',True) is False:
        skip=read(directory/'postgame_learning/skipped.json')
        if skip.get('state')!='skipped_by_configuration' or skip.get('terminal_fingerprint')!=fingerprint:
            raise ValueError('Learning skip is not bound to this terminal result.')
    else:
        from .campaign import _review_applications
        if not _review_applications(directory):raise ValueError('Postgame review is not complete.')
    work=directory/'rules_work_items.json'
    if work.exists() and any(i.get('repair',{}).get('state')!='repaired' or i.get('critical_review',{}).get('state')!='complete' for i in read(work).get('issues',[])):
        raise ValueError('Rules reconciliation or critical review is pending.')
    result=seal['result']
    if result.get('terminal')=='horizon':raise ValueError('Unresolved horizon is not a completed result.')
    return seal


def report(root):
    root=Path(root);rows=deck_rows(root);names={row['card'] for row in rows}
    counts={name:{'games_seen':0,'games_etb_cast':0,'wins_seen':0,'wins_cast':0} for name in names}
    included=[];excluded=[];pending=0
    for directory in sorted(root.glob('game_*')):
        if not directory.is_dir():continue
        if not (directory/'terminal_result.json').exists():pending+=1;continue
        try:
            seal=eligible_game(directory)
            deck=next(d for d in read(directory/'strategy_snapshot.json')['decks'] if d['deck_id']=='reaminatour')
            if {(c['card_name'],c['quantity']) for c in deck['cards']}!={(r['card'],r['quantity']) for r in rows}:
                raise ValueError('Game used a different Aminatou deck list.')
            seen,cast=observations(directory,seal)
            seen&=names;cast&=names
            won=seal['result'].get('winner')==ACTOR
            for name in seen:
                counts[name]['games_seen']+=1;counts[name]['wins_seen']+=int(won)
            for name in cast:
                counts[name]['games_etb_cast']+=1;counts[name]['wins_cast']+=int(won)
            included.append({'game':seal['game'],'seed':seal['seed'],'winner':seal['result'].get('winner')})
        except (OSError,ValueError,KeyError,TypeError,StopIteration) as exc:
            excluded.append({'game':directory.name,'reason':str(exc)})
    for row in rows:
        c=counts[row['card']];row.update(c)
        row['won_if_seen']=100*c['wins_seen']/c['games_seen'] if c['games_seen'] else None
        row['won_if_cast']=100*c['wins_cast']/c['games_etb_cast'] if c['games_etb_cast'] else None
    return {'actor':ACTOR,'commander':next(r['card'] for r in rows if r['commander']),
            'deck_size':sum(r['quantity'] for r in rows),'included_games':included,
            'completed_games':len(included),'pending_games':pending,'excluded_games':excluded,
            'seen_definition':SEEN_DEFINITION,'cast_definition':CAST_DEFINITION,
            'result_definition':'Completed games after their learning disposition. Draws count in denominators and are not wins. Blank percentages have no qualifying games.',
            'rows':rows}


def source_signature(root):
    paths=[Path(__file__).parent/name for name in ('engine.py','referee.py','continuous.py','cardwise_replay.py','cardwise_report.py')]
    for directory in Path(root).glob('game_*'):
        if not directory.is_dir():continue
        paths.extend(directory/name for name in ('terminal_result.json','status.json','game_config.json','strategy_snapshot.json','rules_reconciliation.json','rules_work_items.json'))
        if (directory/'terminal_result.json').exists():
            paths.append(directory/'decisions.jsonl')
            paths.extend((directory/'continuity').glob('*.json'))
            paths.extend((directory/'postgame_learning').glob('*.json'))
            paths.extend((directory/'postgame_review').glob('*.json'))
    return tuple((str(p),p.stat().st_mtime_ns,p.stat().st_size) for p in sorted(paths) if p.is_file())
