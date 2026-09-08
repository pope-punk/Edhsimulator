"""Reviewed deck doctrine, frozen once per game; no model initialization turn."""
from pathlib import Path
from .paths import PROJECT_ROOT
from .runtime_store import read,write,get,identity

SOURCE=PROJECT_ROOT/'data/strategy/standing_plans'
SNAPSHOT='standing_plan_snapshot.json'


def enabled(root,game):
    from .agent_architecture import config
    return config(root,game).get('static_standing')==1


def bind(root,config,seed):
    if config.get('static_standing')!=1:return
    from . import campaign
    directory=campaign.game_dir(root,config['game']);path=directory/SNAPSHOT
    old=read(path)
    if old:
        value={k:v for k,v in old.items() if k!='fingerprint'}
        if identity(value)!=old.get('fingerprint') or old['seed_fingerprint']!=seed['fingerprint']:
            raise SystemExit('Frozen standing-plan snapshot or its seed binding changed.')
        return old
    # Missing references may only be created before any decision input exists.
    if (directory/'continuity/workboard.json').exists():
        raise SystemExit('Frozen standing-plan snapshot is missing from an initialized game.')
    catalog=read(SOURCE/'catalog.json');pilots={}
    for actor,row in seed['pilots'].items():
        entry=catalog['pilots'][actor]
        if campaign._seed_gameplan_text_sha256(row['text'])!=entry['seed_sha256']:
            raise SystemExit(f'Review the static standing plan for {actor} against the changed seed before starting a new game.')
        text=(SOURCE/entry['file']).read_text(encoding='utf-8').strip()
        if not 0<len(text)<=3600:raise SystemExit(f'Standing plan for {actor} requires 1–3600 characters.')
        pilots[actor]={'standing_plan':text,'seed_sha256':entry['seed_sha256']}
    value={'schema':1,'seed_fingerprint':seed['fingerprint'],'pilots':pilots}
    value['fingerprint']=identity(value);write(path,value)
    return value


def standing(root,game,actor):
    from . import campaign
    value=read(campaign.game_dir(root,game)/SNAPSHOT)
    if not value:raise SystemExit('Static standing plans must be frozen before preparing a game.')
    return {'standing_plan':value['pilots'][actor]['standing_plan']}


def install(root,game,actor,snapshot):
    """Install the immutable reference through the normal component transaction."""
    from . import component_store as c
    if 'standing' in c.current(root,game,actor):return
    d=c.directory(root,game);snap=get(d/'snapshots',snapshot)
    text=standing(root,game,actor);operation='static_standing'
    pointers,changed=c.prepare(root,game,actor,'static_reference',operation,{'standing':text},
        source_session=snap['source_session'],snapshot=snapshot,event_seq=snap['event_seq'])
    c.commit(root,game,actor,operation,identity(text),snap['source_session'],
        [(c.index_path(d,actor),pointers)],{'changed_components':changed,'source':'static_file'})
