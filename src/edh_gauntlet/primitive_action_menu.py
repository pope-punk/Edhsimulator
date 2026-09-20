"""Frozen, parameterized action families; no speculative execution or target choice.

A family is not a claim that all its parameter combinations are legal. Exact
announcement and payment validation still run atomically on submission.
"""
import json
from .rules_state import ObjectRef, Zone, RulesViolation
from .rules_program import encode, DoubleFacedProgram, RoomProgram, OverloadAlternative


def sparse(value):
    if isinstance(value,list):return [sparse(v) for v in value]
    if isinstance(value,dict):return {k:sparse(v) for k,v in value.items() if v is not None and v is not False and v!=[] and v!={}}
    return value


def freeze(campaign, actor, packet):
    kernel = campaign.kernel
    decision = packet['board']['decision']
    kind = decision['kind']
    rows = []
    visible={key for key in packet.get('_knowledge',{})}

    def add(label, command, **details):
        rows.append({'label': label, 'command': command, **details})

    if kind == 'priority':
        add('Pass priority', {'kind': 'pass'})
        add('Concede', {'kind': 'concede'})
    elif kind == 'choice':
        allocation=decision['choice']['kind']=='counter_allocation'
        add('Allocate counters' if allocation else 'Answer current choice',
            {'kind':'allocate_counters' if allocation else 'answer','request_id':decision['choice']['request_id']},
            parameters='allocations: use the current allocation specification' if allocation else 'indexes: zero-based indexes from the current choice')
    elif kind == 'mana_payment':
        add('Pay requested mana automatically', {'kind': 'pay_mana', 'request_id': decision['request_id']})
        add('Decline payment', {'kind': 'pay_mana', 'request_id': decision['request_id'], 'payment': None})
    elif kind in ('declare_attackers', 'declare_blockers', 'combat_damage'):
        command = {'declare_attackers': 'attack', 'declare_blockers': 'block', 'combat_damage': 'damage'}[kind]
        add('Submit '+kind.replace('_', ' '), {'kind': command}, parameters='Use the current decision specification; object labels replace exact references.')
    if kind == 'resolution_cast':
        add('Decline optional cast', {'kind':'decline_cast', 'request_id':decision['request_id']})
    if kind not in ('priority', 'resolution_cast'):
        return rows

    def family(label, command, source, spec, targets, modal=None, cost_override=None):
        details = {'cost': sparse(encode(cost_override or spec.cost)), 'timing': spec.timing}
        variable=bool(spec.cost.mana.x_symbols or getattr(spec,'minimum_x',0))
        if variable:details['parameters']='Choose x_value; target candidates and payment depend on X.'
        if targets is not None:
            details['target_rules'] = sparse(encode(targets))
            # Candidate sets, not a Cartesian product or host-selected targets.
            # X-dependent and grouped targets are resolved by final validation.
            if not variable and not targets.groups and type(targets.minimum) is int and type(targets.maximum) in (int, type(None)):
                opts = kernel._target_options(targets, {'source': source.to_json(), 'controller': actor, 'chosen_x': 0})
                details['target_candidates'] = [o.ref.to_json() if o.ref else {'player': o.player} for o in opts
                    if not o.ref or json.dumps(o.ref.to_json(),sort_keys=True) in visible]
        if modal is not None: details['modes'] = sparse(encode(modal))
        # Quotes with unspecified targets/modes are intentionally not a legality
        # oracle. Show the exact blocker instead of silently dropping a family.
        from .primitive_autotap import quote, payment
        probe = {**command, 'action_id': 'pilot-menu', 'targets': [], 'x_value': 0}
        probes=[probe]
        if not variable and targets is not None and not targets.groups and targets.minimum == targets.maximum == 1 and modal is None:
            probes=[{**probe,'targets':[target]} for target in details.get('target_candidates',[])]
            if not probes:
                details['availability']='No visible legal target at this snapshot.'
        results=[]; payment_cache={}
        for candidate in probes:
            try:
                q=quote(kernel,actor,candidate)
            except RulesViolation as exc:
                status='Parameters or conditions required: '+str(exc)
            else:
                details['cost']=sparse(encode(q.cost))
                key=repr(q.cost)
                if key not in payment_cache:
                    try: payment(kernel,actor,{**candidate,'autotap':{}},smart=getattr(campaign,'config',{}).get('automatic_decider_mana')==1)
                    except RulesViolation as exc:
                        payment_cache[key]='Automatic payment not established: '+str(exc).replace('Consequential mana abilities require explicit pilot activation;', 'Consequential mana sources require planner-authored sequencing;').rstrip('.')+'. Supported additional mana costs are included; do not submit preliminary taps.'
                    else:
                        payment_cache[key]='Announcement and ordinary automatic mana checked, including supported filter-land costs, life payments and other mana-ability costs. Submit this action without mana instructions; no planner mana sequence is required for this payment. Chosen non-mana costs and final legality are validated on submission.'
                status=payment_cache[key]
            results.append((candidate['targets'],status))
        if results:
            if all(status in {
                'Parameters or conditions required: Action requires sorcery timing',
                'Parameters or conditions required: Unavailable activated ability source',
                'Parameters or conditions required: Activation condition is not satisfied',
                'Parameters or conditions required: Source is already tapped',
                'Parameters or conditions required: A loyalty ability of this permanent was already activated this turn',
            } for _,status in results):return
            if len({status for _,status in results})==1: details['availability']=results[0][1]
            else: details['availability_by_target']=[{'targets':ts,'status':status} for ts,status in results]
        add(label, command, **details)

    # _knowledge is actor-scoped; never scan hidden hands or the future library.
    for row in packet.get('_knowledge', {}).values():
        ref = row.get('source', row.get('ref'))
        if not isinstance(ref, dict): continue
        try: obj = kernel.state.get(ObjectRef.from_json(ref))
        except RulesViolation: continue
        program = kernel.definition(obj)
        faces = [('front', program)]
        if isinstance(program, DoubleFacedProgram): faces.append(('back', program.back))
        if isinstance(program, RoomProgram): faces = [('left', program), ('right', program.right)]
        for face, face_program in faces:
            if obj.owner != actor and not (kind=='resolution_cast' and ref in decision['candidates'] and decision.get('face')=='back'): continue
            spec = face_program.cast
            alternatives = [None]+[a for a in spec.alternatives] if spec else []
            for alt in alternatives:
                from .rules_program import GraveyardAlternativeCost
                origins = (Zone.GRAVEYARD,) if isinstance(alt, GraveyardAlternativeCost) else spec.origin_zones
                if obj.zone not in origins and not (kind == 'resolution_cast' and ref in decision['candidates']): continue
                if obj.zone == Zone.COMMAND and not obj.commander: continue
                command = {'kind': 'cast', 'source': ref, 'face': face}
                if alt is not None: command['alternative_id'] = alt.alternative_id
                label = 'Cast '+face_program.name+((' — '+alt.alternative_id) if alt else '')
                family(label, command, obj, spec, None if isinstance(alt,OverloadAlternative) else face_program.spell_targets,
                       face_program.modal, alt.cost if alt else None)
            if kind == 'priority' and 'Land' in face_program.types:
                permissions = kernel.player_permissions()[actor]
                top = kernel._visible_library_top(actor, actor)
                if (obj.zone.value in permissions['land_zones'] or
                    obj.zone == Zone.LIBRARY and permissions.get('play_library_top') and top and top.ref == obj.ref):
                    add('Play '+face_program.name, {'kind':'play_land', 'source':ref, 'face':face},
                        availability='Requires own main-phase priority, empty stack and a remaining land play.')
        if kind != 'priority': continue
        for ability in kernel.activated_abilities(obj):
            if ability.mana_ability: continue  # automatic payment or unchanged planner sequence
            if obj.zone != ability.zone or (obj.controller if obj.zone == Zone.BATTLEFIELD else obj.owner) != actor: continue
            family('Activate '+program.name+' — '+ability.ability_id,
                   {'kind':'activate', 'source':ref, 'ability_id':ability.ability_id}, obj, ability, ability.targets)
        if isinstance(program, RoomProgram) and obj.zone == Zone.BATTLEFIELD and obj.controller == actor:
            for door in ('left', 'right'):
                if door not in obj.unlocked:
                    add('Unlock '+program.name+' — '+door, {'kind':'unlock_room','source':ref,'door':door},
                        availability='Requires sorcery timing and explicit payment; use an unchanged planner payment sequence where decider mana restrictions apply.')
    return rows
