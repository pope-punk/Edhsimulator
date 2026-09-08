"""Durable rules work items and quarantine history.

Recoverable defects remain attached to the affected game until the engine repair
and the game's skeptical learning review are both recorded.  A game-breaking
referee blocker is retained as a quarantined draw after those gates complete.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path


RULES_WORK_ITEMS_FILE='rules_work_items.json'
SEVERITIES={'recoverable','game_breaking'}


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    from .atomic_files import replace
    replace(temporary,path)


def registry_path(strategy_path):
    return Path(strategy_path).with_name('learning_quarantine.json')


def read_registry(strategy_path):
    path=registry_path(strategy_path)
    data=_read(path) if path.exists() else {'schema':1,'games':[]}
    if data.get('schema')!=1 or not isinstance(data.get('games'),list):raise ValueError('Invalid learning quarantine registry')
    return data


def game_key(root,number):
    return sha256((str(Path(root).resolve()).casefold()+'#'+str(number)).encode()).hexdigest()


def work_items_path(root,number):
    return Path(root)/f'game_{int(number):02d}'/RULES_WORK_ITEMS_FILE


def read_work_items(root,number):
    path=work_items_path(root,number)
    data=_read(path) if path.exists() else {'schema':1,'game':int(number),'issues':[]}
    if (data.get('schema')!=1 or data.get('game')!=int(number) or
            not isinstance(data.get('issues'),list)):
        raise ValueError(f'Invalid rules work-item file for game {number}')
    return data


def _issue_id(root,number,reason,severity):
    payload=f'{game_key(root,number)}#{severity}#{reason.strip()}'
    return 'rules-'+sha256(payload.encode()).hexdigest()[:20]


def record_work_item(root,number,reason,severity='recoverable'):
    reason=str(reason or '').strip();severity=str(severity or '').strip()
    if not reason:raise ValueError('Rules work item requires a reason')
    if severity not in SEVERITIES:raise ValueError('Rules severity must be recoverable or game_breaking')
    path=work_items_path(root,number)
    if not path.parent.is_dir():raise ValueError(f'Missing rules-affected game {number}')
    data=read_work_items(root,number);issue_id=_issue_id(root,number,reason,severity)
    existing=next((row for row in data['issues'] if row.get('issue_id')==issue_id),None)
    if existing:return existing
    issue={
        'issue_id':issue_id,'severity':severity,'reason':reason,
        'recorded_at':datetime.now(timezone.utc).isoformat(),
        'repair':{'state':'pending'},'critical_review':{'state':'pending'},
    }
    data['issues'].append(issue);_write(path,data)
    return issue


def rules_integrity_tag(root,number):
    issues=read_work_items(root,number)['issues']
    if not issues:return None
    return {
        'tag':'RULES-AFFECTED GAME — SKEPTICAL REVIEW REQUIRED',
        'game_breaking':any(row.get('severity')=='game_breaking' for row in issues),
        'issues':[
            {'issue_id':row['issue_id'],'severity':row['severity'],'reason':row['reason']}
            for row in issues
        ],
        'learning_instruction':(
            'Treat each issue explicitly in every private evidence review and in the '
            'consolidated learning synthesis. Preserve only conclusions supported '
            'independently of the affected rules resolution.'
        ),
    }


def pending_repairs(root,number):
    return [row for row in read_work_items(root,number)['issues']
            if (row.get('repair') or {}).get('state')!='repaired']


def repair_work_items(strategy_path,root,number,summary,issue_id=None):
    summary=str(summary or '').strip()
    if not summary:raise ValueError('Rules repair requires a non-empty summary')
    data=read_work_items(root,number);targets=[
        row for row in data['issues'] if issue_id is None or row.get('issue_id')==issue_id]
    if not targets:raise ValueError('No matching rules work item')
    repaired_at=datetime.now(timezone.utc).isoformat()
    for row in targets:
        prior=row.get('repair') or {}
        if prior.get('state')=='repaired':
            if issue_id is not None and prior.get('summary')!=summary:
                raise ValueError('Rules work item already has a different repair')
            continue
        row['repair']={'state':'repaired','repaired_at':repaired_at,'summary':summary}
    _write(work_items_path(root,number),data)
    _refresh_game_state(strategy_path,root,number)
    return data


def require_repairs_complete(root,number):
    pending=pending_repairs(root,number)
    if pending:
        ids=', '.join(row['issue_id'] for row in pending)
        raise ValueError(f'Game {number} has unrepaired rules work items: {ids}')


def complete_critical_review(strategy_path,root,number,review_id,review_fingerprint):
    data=read_work_items(root,number)
    if not data['issues']:return data
    require_repairs_complete(root,number)
    completed_at=datetime.now(timezone.utc).isoformat()
    for row in data['issues']:
        prior=row.get('critical_review') or {}
        desired={'state':'complete','completed_at':prior.get('completed_at') or completed_at,
                 'review_id':review_id,'review_fingerprint':review_fingerprint}
        if prior.get('state')=='complete' and {
                key:prior.get(key) for key in ('review_id','review_fingerprint')}!={
                'review_id':review_id,'review_fingerprint':review_fingerprint}:
            raise ValueError('Rules work item already has a different critical review')
        row['critical_review']=desired
    _write(work_items_path(root,number),data)
    _refresh_game_state(strategy_path,root,number)
    return data


def _refresh_game_state(strategy_path,root,number):
    data=read_registry(strategy_path);key=game_key(root,number)
    entry=next((row for row in data['games'] if row.get('key')==key),None)
    if entry is None:return
    items=read_work_items(root,number)['issues']
    repairs_complete=all((row.get('repair') or {}).get('state')=='repaired' for row in items)
    reviews_complete=all((row.get('critical_review') or {}).get('state')=='complete' for row in items)
    entry['work_items_path']=str(work_items_path(root,number).resolve())
    entry['repair_state']='complete' if repairs_complete else 'pending'
    entry['critical_review_state']='complete' if reviews_complete else 'pending'
    if repairs_complete and reviews_complete:
        entry['game_state']='quarantined' if any(
            row.get('severity')=='game_breaking' for row in items) else 'released'
        entry['resolved_at']=entry.get('resolved_at') or datetime.now(timezone.utc).isoformat()
    else:entry['game_state']='temporary_quarantine'
    _write(registry_path(strategy_path),data)


def require_clean(strategy_path,root=None,game=None):
    if registry_path(strategy_path).with_name('quarantine_transaction.json').exists():
        raise ValueError('An unfinished quarantine transaction requires recover-quarantine')
    requested_key=game_key(root,game) if root is not None and game is not None else None
    for entry in read_registry(strategy_path)['games']:
        if entry['learning_state']=='pending':
            raise ValueError('Published learning is quarantined. Complete its bound rules review before starting or learning from another game.')
        path=entry.get('work_items_path')
        if not path or not Path(path).exists():continue
        work=_read(path)
        open_repairs=[row for row in work.get('issues',[])
                      if (row.get('repair') or {}).get('state')!='repaired']
        if open_repairs and entry.get('key')!=requested_key:
            raise ValueError('An engine rules repair work item is open. Repair it before starting another game or cohort.')


def require_snapshot_clean(strategy_path,state):
    notes={(deck.deck_id,card.card_name,note.note_id,note.text)
           for deck in state.decks for card in deck.cards for note in card.notes}
    for entry in read_registry(strategy_path)['games']:
        removed=set(entry.get('removed_note_ids',[]))
        for app in entry['applications']:
            for operation in app['operations']:
                note=operation.get('note') or {}
                if note.get('note_id') in removed and (operation.get('deck'),operation.get('card'),note.get('note_id'),note.get('text')) in notes:
                    raise ValueError('Frozen strategy contains excised rules-inconsistent learning; start a fresh cohort with the corrected bank')


def quarantine_games(strategy_path,root,numbers,reason,severity='recoverable'):
    if not isinstance(reason,str) or not reason.strip():raise ValueError('Quarantine requires a reason')
    if severity not in SEVERITIES:raise ValueError('Rules severity must be recoverable or game_breaking')
    data=read_registry(strategy_path);existing={entry['key']:entry for entry in data['games']}
    added=[]
    for number in sorted(set(numbers)):
        if isinstance(number,bool) or not isinstance(number,int) or number<1:raise ValueError('Invalid quarantine game')
        key=game_key(root,number)
        directory=Path(root)/f'game_{number:02d}'
        if not directory.is_dir():raise ValueError(f'Missing quarantine game {number}')
        issue=record_work_item(root,number,reason,severity)
        if key in existing:
            entry=existing[key]
            entry['work_items_path']=str(work_items_path(root,number).resolve())
            entry['game_state']='temporary_quarantine'
            entry['repair_state']='pending'
            entry['critical_review_state']='pending'
            entry['latest_issue_id']=issue['issue_id']
            added.append(entry)
            continue
        applications=[]
        for path in sorted((directory/'postgame_learning').glob('*.json')):
            raw=_read(path)
            if raw.get('patch') is not None and raw.get('applied_at'):
                applications.append({'path':str(path.resolve()),'sha256':sha256(path.read_bytes()).hexdigest(),
                                     'review_id':raw.get('review_id'),'operations':raw['patch'].get('operations',[])})
        entry={'key':key,'cohort':str(Path(root).resolve()),'game':number,'reason':reason.strip(),
               'recorded_at':datetime.now(timezone.utc).isoformat(),
               'game_state':'temporary_quarantine',
               'repair_state':'pending','critical_review_state':'pending',
               'work_items_path':str(work_items_path(root,number).resolve()),
               'latest_issue_id':issue['issue_id'],
               'learning_state':'pending' if any(a['operations'] for a in applications) else 'no_published_learning',
               'applications':applications}
        entry['review_fingerprint']=sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest()
        data['games'].append(entry);added.append(entry)
    _write(registry_path(strategy_path),data)
    return added


def resolve_learning(strategy_path,response):
    """Revalidate exact published operations; removal edits live notes only.

    A bank+registry receipt makes interrupted removals recoverable. Historical
    snapshots, results, requests and application audits remain byte-for-byte intact.
    """
    from .strategy import StrategyState,load_strategy_state
    data=read_registry(strategy_path)
    entry=next((row for row in data['games'] if row['key']==response.get('quarantine_key')),None)
    if entry is None or response.get('review_fingerprint')!=entry['review_fingerprint']:
        raise ValueError('Rules review must bind the exact quarantine record')
    if entry.get('work_items_path') and Path(entry['work_items_path']).exists():
        require_repairs_complete(entry['cohort'],entry['game'])
    if entry['learning_state']=='reviewed':
        if entry['rules_response']!=response:raise ValueError('A different rules review is already recorded')
        if entry.get('work_items_path') and Path(entry['work_items_path']).exists():
            complete_critical_review(
                strategy_path,entry['cohort'],entry['game'],
                'quarantine-'+entry['review_fingerprint'][:20],entry['review_fingerprint'])
        return entry
    operations=[op for app in entry['applications'] for op in app['operations']]
    rows=response.get('operations')
    if not isinstance(rows,list) or len(rows)!=len(operations) or any(not isinstance(row,dict) for row in rows):raise ValueError('Review every published operation')
    if [row.get('index') for row in rows]!=list(range(1,len(operations)+1)):raise ValueError('Rules review indexes must match published operation order')
    for app in entry['applications']:
        if sha256(Path(app['path']).read_bytes()).hexdigest()!=app['sha256']:raise ValueError('Quarantined learning audit changed')
    state=load_strategy_state(strategy_path);raw=state.to_dict();removed=[];invalidated=[]
    for index,(op,row) in enumerate(zip(operations,rows),1):
        if row.get('verdict') not in {'retain','remove'} or not str(row.get('rules_basis','')).strip():raise ValueError('Each operation needs a rules basis and retain/remove verdict')
        if row['verdict']=='retain':continue
        if op['op']!='add_note':raise ValueError('This operation needs an explicit corrective strategy patch before quarantine can be released')
        note=op['note'];found=False;invalidated.append(note['note_id'])
        for deck in raw['decks']:
            if deck['deck_id']!=op['deck']:continue
            for card in deck['cards']:
                if card['card_name']!=op['card']:continue
                matches=[n for n in card['notes'] if n['note_id']==note['note_id']]
                if not matches:continue
                if len(matches)!=1 or matches[0]['text']!=note['text'] or matches[0].get('locked'):
                    raise ValueError('Refusing to remove a changed or locked note')
                card['notes']=[n for n in card['notes'] if n['note_id']!=note['note_id']];found=True
        if found:removed.append(note['note_id'])
    entry['learning_state']='reviewed';entry['rules_response']=response
    entry['removed_note_ids']=invalidated
    entry['live_notes_removed']=removed
    if removed:raw['revision']+=1
    updated=StrategyState.from_dict(raw)
    receipt=registry_path(strategy_path).with_name('quarantine_transaction.json')
    transaction={'schema':1,'base':state.freeze().revision_id,'result':updated.freeze().revision_id,
                 'bank':updated.to_dict(),'registry':data}
    if receipt.exists():
        prior=_read(receipt)
        if prior!=transaction:raise ValueError('An unfinished quarantine transaction requires recover-quarantine')
    else:_write(receipt,transaction)
    recover(strategy_path)
    if entry.get('work_items_path') and Path(entry['work_items_path']).exists():
        complete_critical_review(
            strategy_path,entry['cohort'],entry['game'],
            'quarantine-'+entry['review_fingerprint'][:20],entry['review_fingerprint'])
    return entry


def recover(strategy_path):
    from .strategy import load_strategy_state
    receipt=registry_path(strategy_path).with_name('quarantine_transaction.json')
    if not receipt.exists():return
    transaction=_read(receipt);current=load_strategy_state(strategy_path).freeze().revision_id
    if current not in {transaction['base'],transaction['result']}:raise ValueError('Quarantine transaction conflicts with a later bank revision')
    if current!=transaction['result']:_write(strategy_path,transaction['bank'])
    _write(registry_path(strategy_path),transaction['registry']);receipt.unlink()
