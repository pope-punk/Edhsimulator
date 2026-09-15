"""Authoritative, versioned components in the existing immutable component archive.

Current pointers are bounded. Operation receipts and prepared transactions are
evidence, never default packet history. Caller-supplied role identity must come
from the registered job/transport, not from model-authored response content.
"""
from pathlib import Path
import time
from .runtime_store import read,write,put,get,identity,locked,checked_id
from .agent_architecture import SHORT,LONG,DIPLOMACY

WRITERS={'standing':LONG,'long_term':LONG,'continuity':SHORT,'short_term':SHORT,
         'actions':SHORT,'strategic_answer':LONG,'diplomacy_brief':LONG,'diplomacy_outcomes':DIPLOMACY}


def directory(root,game):return Path(root)/f'game_{game:02d}'/'continuity'


def index_path(directory,actor):
    from .pilot_handoff import seat_slug
    return Path(directory)/'current_components'/(seat_slug(actor)+'.json')


def recover(root,game):
    """Finish exactly one prepared metadata commit before exposing a mixed view."""
    d=directory(root,game)
    with locked(d,'planning'):
        journal=read(d/'component_transaction.json')
        if not journal:return
        from .planner_runtime import _compatible
        if not _compatible(journal['source_session'],root,game,journal['actor']):
            raise SystemExit('Prepared component publication belongs to a different accepted branch.')
        for relative,value in journal['writes']:
            target=(d/relative).resolve()
            if not target.is_relative_to(d.resolve()):raise SystemExit('Invalid component transaction path.')
            write(target,value)
        (d/'component_transaction.json').unlink()


def current(root,game,actor):
    d=directory(root,game)
    with locked(d,'planning'):
        recover(root,game)
        values=read(index_path(d,actor),{})
        result={}
        from .planner_runtime import _compatible,_rows
        # One immutable tape read per pointer projection, rather than one per
        # component. Validation still binds every envelope to this exact branch.
        rows=_rows(root,game) if values else []
        for kind,key in values.items():
            envelope=get(d/'plan_components',key)
            if envelope['actor']!=actor or envelope['game']!=game or envelope['kind']!=kind:
                raise SystemExit('Wrong-seat component pointer.')
            if _compatible(envelope['source_session'],root,game,actor,rows):result[kind]=envelope
        return result


def resolve(root,game,actor,component_id,*,recipient_role=None):
    key=checked_id(component_id);d=directory(root,game)
    value=get(d/'plan_components',key)
    if value.get('actor')!=actor or value.get('game')!=game or value.get('schema')!='component/1':
        raise ValueError('Component is not in this seat/game namespace.')
    if recipient_role==DIPLOMACY and value['kind'] not in {'diplomacy_brief','diplomacy_outcomes'}:
        raise ValueError('Diplomacy cannot inspect private planning components.')
    if value['kind']=='standing' and recipient_role is not None and recipient_role!=SHORT:
        raise ValueError('Standing doctrine is delivered only to the short-term planner.')
    from .planner_runtime import _compatible
    if not _compatible(value['source_session'],root,game,actor):raise ValueError('Component belongs to a discarded branch.')
    return {**value,'component_id':key,'content':get(d/'plan_components',value['content_id'])}


def prepare(root,game,actor,role,operation,updates,*,source_session,snapshot,event_seq,
            dependencies=None,change_rationale=None,dependent_versions=None):
    """Construct one atomic candidate; caller holds the shared planning lock.

    Returns immutable envelopes and proposed pointers without publishing them.
    Equal content preserves the original component version and identity.
    """
    from .agent_architecture import enabled
    from .planner_runtime import _compatible
    if not enabled(root,game):raise ValueError('Versioned role publication requires explicit game enrollment.')
    if not _compatible(source_session,root,game,actor):raise ValueError('Publication belongs to a discarded branch.')
    if not isinstance(operation,str) or not operation or len(operation)>200:raise ValueError('Invalid component operation.')
    if change_rationale is not None and (not isinstance(change_rationale,str) or len(change_rationale)>1200):
        raise ValueError('Change rationale must be at most 1200 characters.')
    d=directory(root,game);prior=current(root,game,actor)
    pointers={kind:identity(value) for kind,value in prior.items()}
    changed=[]
    for kind,content in updates.items():
        from . import static_standing
        static=kind=='standing' and static_standing.enabled(root,game)
        if static:
            if role!='static_reference' or content!=static_standing.standing(root,game,actor):
                raise ValueError('Static standing doctrine can only be installed from the frozen file.')
        elif WRITERS.get(kind)!=role:raise ValueError(f'{role} cannot publish {kind}.')
        if not isinstance(content,dict):raise ValueError('Component content must be an object.')
        old=prior.get(kind);content_id=put(d/'plan_components',content)
        deps=(dependencies or {}).get(kind,[])
        if not isinstance(deps,list) or len(deps)>24 or any(not isinstance(p,str) or not p.startswith('/') or len(p)>200 for p in deps):
            raise ValueError('Dependencies must be at most 24 factual JSON Pointer paths.')
        same_basis=(kind!='actions' or old and old['dependent_versions'].get('short_term')==(dependent_versions or {}).get('short_term'))
        if kind=='diplomacy_brief':
            same_basis=old and all(old['dependent_versions'].get(k)==(dependent_versions or {}).get(k)
                                  for k in ('long_term','diplomacy_refresh'))
        if old and old['content_id']==content_id and old['dependencies']==deps and same_basis:continue
        if kind=='standing' and old:raise ValueError('Standing doctrine is immutable.')
        value={'schema':'component/1','kind':kind,'actor':actor,'game':game,'writer':role,
               'version':old['version']+1 if old else 1,'content_id':content_id,
               'source_session':source_session,'snapshot':snapshot,'coverage':{'through_event_seq':event_seq},
               'dependent_versions':dict(dependent_versions or {}),'dependencies':deps,
               'operation':operation,'published_at':time.time()}
        if change_rationale:value['change_rationale']=change_rationale
        pointers[kind]=put(d/'plan_components',value);changed.append(kind)
    return pointers,changed


def commit(root,game,actor,operation,binding,source_session,writes,result):
    """Idempotent write-ahead commit, including stage/job/mailbox receipts."""
    d=directory(root,game);key=identity([actor,operation]);receipt=d/'component_publications'/(key+'.json')
    with locked(d,'planning'):
        recover(root,game)
        previous=read(receipt)
        if previous:
            if previous['binding']!=binding:raise ValueError('Publication operation already has different content.')
            return previous['result']
        rows=[]
        for path,value in writes:
            path=Path(path).resolve()
            if not path.is_relative_to(d.resolve()):raise ValueError('Publication writes must remain inside continuity.')
            rows.append((str(path.relative_to(d.resolve())),value))
        rows.append((str(receipt.relative_to(d)),{'binding':binding,'result':result}))
        write(d/'component_transaction.json',{'actor':actor,'source_session':source_session,'writes':rows})
        recover(root,game)
        return result


def receipt(root,game,actor,operation,binding):
    d=directory(root,game);recover(root,game)
    row=read(d/'component_publications'/(identity([actor,operation])+'.json'))
    if row and row['binding']!=binding:raise ValueError('Publication operation already has different content.')
    return row['result'] if row else None


def projection(root,game,actor,kinds,*,recipient_role,acknowledged=None):
    """Cross-role delivery is self-contained unless THIS recipient knows the ID."""
    values=current(root,game,actor);result={}
    for kind in kinds:
        if kind not in values:continue
        value=values[kind];key=identity(value)
        if (acknowledged or {}).get(kind)==key:
            result[kind]={'component_id':key,'version':value['version'],'retained':True}
        else:result[kind]=resolve(root,game,actor,key,recipient_role=recipient_role)
    return result
