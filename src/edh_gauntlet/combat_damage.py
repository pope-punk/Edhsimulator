"""One bounded, atomic assignment for all discretionary sources in a damage step."""
import json

HELP=('Return choice as an object mapping EVERY supplied source UID to '
      '{blockers:{BLOCKER_UID:INTEGER,...},defender:INTEGER}. Include every listed blocker, even for zero damage. '
      'Use nonnegative integers summing to that source\'s power. Defender damage requires trample and lethal '
      'assigned to every blocker; without defender damage you may divide freely. One rationale and scheduler '
      'directive cover the whole step. First-strike and regular damage are separate requests.')


def version(value):
    if type(value) is not int or value!=1:raise ValueError('combat_damage_batch must be version 1.')
    return value


def specification(game,sources,step,defender,defended_object):
    rows=[];forced={}
    for source,blockers,amount,trample in sources:
        power=max(0,amount)
        lethal=[1 if 'deathtouch' in game.keywords_for(source) else max(0,game.effective_toughness(b)-b.metadata.get('damage_marked',0)) for b in blockers]
        if not power or len(blockers)==1 and (not trample or power<=sum(lethal)):
            forced[source.uid]={'blockers':{b.uid:power if i==0 else 0 for i,b in enumerate(blockers)},'defender':0}
            continue
        rows.append({'uid':source.uid,'name':source.name,'power':power,'trample':bool(trample),
            'blockers':[{'uid':b.uid,'name':b.name,'lethal':n} for b,n in zip(blockers,lethal)]})
    return {'step':step,'defender':{'seat':defender.name,'uid':defended_object.uid if defended_object else None,
            'name':defended_object.name if defended_object else defender.name},'sources':rows},forced


def validate(request,value):
    if isinstance(value,str):
        def unique(pairs):
            result={}
            for key,item in pairs:
                if key in result:raise ValueError('Repeated UID or field in damage assignment.')
                result[key]=item
            return result
        try:value=json.loads(value,object_pairs_hook=unique)
        except json.JSONDecodeError as exc:raise ValueError('Damage assignment must be a JSON object.') from exc
    sources=request['combat_damage']['sources']
    if not isinstance(value,dict) or set(value)!={s['uid'] for s in sources}:
        raise ValueError('Assign every supplied damage source exactly once; no unknown sources.')
    result={}
    for source in sources:
        row=value[source['uid']]
        if not isinstance(row,dict) or set(row)!={'blockers','defender'}:
            raise ValueError('Each source requires exactly blockers and defender.')
        blockers=row['blockers'];face=row['defender']
        if not isinstance(blockers,dict) or set(blockers)!={b['uid'] for b in source['blockers']}:
            raise ValueError('Include every listed blocker and no other damage recipients.')
        amounts=[face,*blockers.values()]
        if any(type(n) is not int or n<0 for n in amounts):raise ValueError('Damage amounts must be nonnegative integers.')
        if sum(amounts)!=source['power']:raise ValueError('Each damage distribution must sum to its source power.')
        if face and (not source['trample'] or any(blockers[b['uid']]<b['lethal'] for b in source['blockers'])):
            raise ValueError('Defender damage requires trample and lethal assigned to every blocker.')
        result[source['uid']]={'blockers':dict(blockers),'defender':face}
    return result


def presentation(request):
    return HELP+'\nDamage assignment: '+json.dumps(request['combat_damage'],ensure_ascii=False,separators=(',',':'))
