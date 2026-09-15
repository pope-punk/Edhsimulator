"""One-shot planner watches over known objects and committed public facts."""
from copy import deepcopy
from .rules_adapter import digest
from .rules_state import RulesViolation,ObjectRef,Zone
from .primitive_planning import queue,LONG,SHORT,text_field


def validate(campaign,frozen,values):
    if type(values) is not list or len(values)>8:raise RulesViolation('Use at most eight one-shot watches')
    ids=set();result=[]
    visible={digest(card['ref']) for cards in frozen['board']['zones']['battlefield'].values() for card in cards}
    names=set()
    for program in campaign.kernel.definitions.values():
        names.add(program.name)
        for face in ('back','right'):
            if getattr(program,face,None):names.add(getattr(program,face).name)
    for row in values:
        if type(row) is not dict or set(row)!={'watch_id','condition'}:raise RulesViolation('A watch requires watch_id and condition')
        key=text_field(row,'watch_id',80)
        if key in ids:raise RulesViolation('Duplicate watch ID')
        ids.add(key);condition=row['condition']
        if type(condition) is not dict:raise RulesViolation('Watch condition must be an object')
        kind=condition.get('kind')
        expected={'card_cast':{'kind','seat','card'},'object_left':{'kind','source'},'life_at_most':{'kind','seat','value'}}
        if kind not in expected or set(condition)!=expected[kind]:raise RulesViolation('Unsupported watch condition')
        if 'seat' in condition and condition['seat'] not in campaign.kernel.state.players:raise RulesViolation('Unknown watched seat')
        if kind=='card_cast' and condition['card'] not in names:raise RulesViolation('Watch an exact known printed face name')
        if kind=='object_left' and digest(condition['source']) not in visible:raise RulesViolation('Watch an exact visible battlefield object')
        if kind=='life_at_most' and (type(condition['value']) is not int or not 0<=condition['value']<=1000000):
            raise RulesViolation('Invalid life threshold')
        result.append(deepcopy(row))
    return result


def install(campaign,state,actor,role,job,values):
    if role not in {LONG,SHORT}:raise RulesViolation('Only planners own watches')
    values=validate(campaign,job['input'],values)
    seat=state['actors'][actor];sources=seat.setdefault('watches',{})
    if not values:
        sources.pop(role,None);return
    version=digest({'role':role,'watches':values})
    previous=sources.get(role)
    if previous and previous['version']==version:return
    sources[role]={'version':version,'watches':values,'checked_event':job['input']['_event_cursor'],
                   'checked_zone':job['input']['_zone_cursor'],
                   'life':{p['seat']:p['life'] for p in job['input']['board']['players']}}
    evaluate(campaign,state,actor,role,sources[role])


def evaluate(campaign,state,actor,role,source):
    kernel=campaign.kernel;seat=state['actors'][actor]
    events=kernel.semantic_events[source['checked_event']:]
    zones=kernel.state.events_since(source['checked_zone'])
    cast_names=[]
    # Local last-known objects resolve cast faces even after a same-command move.
    needs_casts=any(watch['condition']['kind']=='card_cast' for watch in source['watches'])
    objects={obj.ref:obj for event in zones for obj in (event.before,event.after)} if needs_casts else {}
    for event in events if needs_casts else ():
        if event['kind']!='spell_cast':continue
        ref=ObjectRef.from_json(event['source']);obj=objects.get(ref)
        if obj is None:obj=kernel.state.get(ref)
        cast_names.append((event['controller'],kernel.definition(obj).name))
    departed={event.before.ref for event in zones if event.before.zone==Zone.BATTLEFIELD
              and event.after.zone!=Zone.BATTLEFIELD and not event.before.phased}
    fired=seat.setdefault('fired_watches',[])
    for watch in source['watches']:
        identity=digest({'role':role,'watch':watch})
        if identity in fired:continue
        condition=watch['condition'];kind=condition['kind']
        hit=(kind=='card_cast' and (condition['seat'],condition['card']) in cast_names or
             kind=='object_left' and ObjectRef.from_json(condition['source']) in departed or
             kind=='life_at_most' and source['life'][condition['seat']]>condition['value']>=kernel.state.life(condition['seat']))
        if hit:
            fired.append(identity)
            queue(state,actor,role,'watch:'+identity)
            campaign.record(actor,'watch_fired',{'role':role,'watch':watch,'identity':identity,
                                               'rules_commit':campaign.store.committed_head()})
    source['checked_event']=len(kernel.semantic_events);source['checked_zone']=kernel.state.event_count
    source['life']={p:kernel.state.life(p) for p in kernel.state.players}


def observe(campaign,state):
    for actor,seat in state['actors'].items():
        if actor not in campaign.kernel.state.live_players:continue
        for role,source in seat.get('watches',{}).items():evaluate(campaign,state,actor,role,source)
