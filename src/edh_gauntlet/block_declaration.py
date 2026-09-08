"""Compact combat-wide legal choices and atomic, pilot-authored assignments."""
import json

HELP=('Return choice as an object mapping EVERY attacker UID to a list of blocker UIDs. '
      'Use [] explicitly for each unblocked attacker; an all-empty mapping declares no blocks. '
      'Use only that attacker\'s eligibility group. Each blocker may appear once across the whole declaration. '
      'A nonempty group must meet min_blockers. Supply one rationale and one scheduler directive for the whole declaration.')


def version(value):
    if type(value) is not int or value not in (1,2):raise ValueError('combat_blocker_batch must be version 1 or 2.')
    return value


def specification(game,attackers,blockers):
    groups={};rows=[];group_ids={}
    for attacker in attackers:
        minimum=2 if 'menace' in game.keywords_for(attacker) else 1
        legal=tuple(b.uid for b in blockers if attacker.metadata.get('unblockable_turn')!=game.turn_number and game.can_block(b,attacker))
        if len(legal)<minimum:legal=()
        if legal not in group_ids:
            key='g'+str(len(groups)+1);group_ids[legal]=key;groups[key]=list(legal)
        rows.append({'uid':attacker.uid,'name':attacker.name,'power':game.effective_power(attacker),
            'toughness':game.effective_toughness(attacker),'min_blockers':minimum,'eligible_group':group_ids[legal]})
    return {'attackers':rows,'eligibility_groups':groups}


def validate(request,value):
    if isinstance(value,str):
        def unique(pairs):
            result={}
            for key,item in pairs:
                if key in result:raise ValueError('Repeated attacker UID in block declaration.')
                result[key]=item
            return result
        try:value=json.loads(value,object_pairs_hook=unique)
        except json.JSONDecodeError as exc:raise ValueError('Block declaration must be a JSON object of attacker UID to blocker UID lists.') from exc
    spec=request['block_declaration'];attackers=spec['attackers']
    if not isinstance(value,dict) or set(value)!={a['uid'] for a in attackers}:
        raise ValueError('Declare every supplied attacker exactly once, using [] for each unblocked attacker; no unknown attackers.')
    used=set();result={}
    for attacker in attackers:
        selected=value[attacker['uid']]
        if not isinstance(selected,list) or any(not isinstance(uid,str) for uid in selected):
            raise ValueError('Each attacker requires a list of blocker UIDs.')
        if len(selected)!=len(set(selected)) or used.intersection(selected):
            raise ValueError('Each blocker may be assigned only once across the entire declaration.')
        if set(selected)-set(spec['eligibility_groups'][attacker['eligible_group']]):
            raise ValueError('A selected blocker is not eligible for that attacker.')
        if selected and len(selected)<attacker['min_blockers']:
            raise ValueError(f"{attacker['uid']} requires zero or at least {attacker['min_blockers']} blockers.")
        used.update(selected);result[attacker['uid']]=list(selected)
    return result


def presentation(request):
    if 'block_declaration' not in request:return ''
    return HELP+'\nCombat-wide blocker declaration: '+json.dumps(request['block_declaration'],ensure_ascii=False,separators=(',',':'))
