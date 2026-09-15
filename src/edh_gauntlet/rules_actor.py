"""Pure actor projections for the primitive host adapter.

This is an explicit allowlist, never a filtered kernel checkpoint. The current
kernel has no face-down/reveal-permission vocabulary; production admission stays
closed until those semantics and the complete transport/replay contract exist.
"""
from copy import deepcopy
from .rules_program import encode
from .rules_creature_types import CREATURE_TYPES
from .rules_state import Zone,RulesViolation,RulesObject,ObjectRef


PUBLIC_ZONES=(Zone.BATTLEFIELD,Zone.GRAVEYARD,Zone.EXILE,Zone.COMMAND)


def _card(kernel,obj,views):
    view=views[obj.ref]
    all_creature_types=CREATURE_TYPES<=view.subtypes
    limits=[{'ability_id':ability.ability_id,'remaining':kernel.remaining_trigger_uses(obj,ability)}
            for ability in kernel.definition(obj).abilities if ability.trigger_limit is not None] if obj.zone==Zone.BATTLEFIELD else []
    return {'ref':obj.ref.to_json(),'name':kernel.definition(obj).name,
        'definition_id':obj.effective_definition,'owner':obj.owner,'controller':obj.controller,
        'zone':obj.zone.value,'types':sorted(view.types),'subtypes':sorted(view.subtypes-CREATURE_TYPES if all_creature_types else view.subtypes),
        **({'all_creature_types':True} if all_creature_types else {}),
        'supertypes':sorted(view.supertypes),'keywords':sorted(view.keywords),'colors':sorted(view.colors),
        'mana_value':view.mana_value,'power':view.power,'toughness':view.toughness,
        'tapped':obj.tapped,'phased':obj.phased,'counters':dict(obj.counters),
        'damage':obj.damage_marked,'commander':obj.commander,'token':obj.token,
        'attached_to':obj.attached_to.to_json() if obj.attached_to else None,
        **({'limited_triggers':limits} if limits else {}),
        **({'granted_abilities':encode(view.granted_abilities)} if view.granted_abilities else {})}


def decision_for_actor(kernel,actor):
    if kernel.outcome:return {'kind':'finished'}
    request=kernel.pending_choice
    if request is not None:
        if request.revision!=kernel.revision:raise RulesViolation('Choice no longer matches current state')
        if request.actor==actor:return {'kind':'choice','choice':request.to_json()}
        return {'kind':'waiting','actor':request.actor}
    if kernel.resolving or kernel.pending_triggers or kernel.placement or kernel.departure or kernel.announcement:
        return {'kind':'engine_pending'}
    if kernel.priority is not None:
        return {'kind':'priority' if kernel.priority==actor else 'waiting','actor':kernel.priority}
    if kernel.turn_schedule is not None:
        if kernel.phase=='declare_attackers':
            return {'kind':'declare_attackers' if kernel.active==actor else 'waiting','actor':kernel.active}
        combat=kernel.combat
        if combat and kernel.phase=='declare_blockers':
            defenders=kernel._defenders();index=combat['defender_index']
            if index<len(defenders):
                owner=defenders[index]
                if owner!=actor:return {'kind':'waiting','actor':owner}
                spec=kernel._block_specification(actor)
                if spec['attackers']:return {'kind':'declare_blockers','actor':actor,'specification':deepcopy(spec)}
        if combat and kernel.phase in {'first_strike_damage','combat_damage'} and combat['damage_pending']:
            if kernel.active!=actor:return {'kind':'waiting','actor':kernel.active}
            return {'kind':'combat_damage','actor':actor,'specification':deepcopy(combat['damage_pending']['specification'])}
    return {'kind':'engine_pending'}


def project_actor(kernel,actor):
    """Read current settled state without advancing, answering or exposing history."""
    if actor not in kernel.state.players:raise RulesViolation('Unknown actor')
    state=kernel.state;views=kernel.characteristics()
    players=[];permissions=kernel.player_permissions()
    for seat in state.players:
        row={'seat':seat,'life':state.life(seat),'starting_life':state.starting_life(seat),'mana':dict(state.mana_pool(seat)),
             'counters':dict(state.player_counters(seat)),'departed':seat not in state.live_players,
             'permissions':permissions[seat],'hand_count':len(state.zone(seat,Zone.HAND)),'library_count':len(state.zone(seat,Zone.LIBRARY))}
        try:row['commander_identity']=list(state.commander_identity(seat))
        except RulesViolation:pass # Unbound fixture metadata is not an inferred identity.
        players.append(row)
    zones={zone.value:{seat:[_card(kernel,obj,views) for obj in state.zone(seat,zone)]
                      for seat in state.players} for zone in PUBLIC_ZONES}
    def target_summary(value):
        if 'player' in value:return deepcopy(value)
        try:obj=state.get(ObjectRef.from_json(value))
        except RulesViolation:return {'unavailable':True}
        if obj.zone in (*PUBLIC_ZONES,Zone.STACK) or obj.zone==Zone.HAND and obj.owner==actor:
            return obj.ref.to_json()
        return {'hidden':True,'zone':obj.zone.value,'owner':obj.owner}
    def frame_summary(frame):
        source=RulesObject.from_json(frame['source'])
        if frame.get('turn_based'):
            return {'kind':'turn_action','controller':frame['controller'],'phase':kernel.phase}
        if source.zone not in (*PUBLIC_ZONES,Zone.STACK) and not (source.zone==Zone.HAND and source.owner==actor):
            return {'kind':'effect','controller':frame['controller']}
        return {'id':frame['id'],'kind':'spell' if frame['spell'] else 'ability',
            'name':kernel.definition(source).name,'source':source.ref.to_json(),
            'controller':frame['controller'],'ability_id':frame.get('ability_id'),'chosen_x':frame['chosen_x'],
            **({'alternative_id':frame['alternative_id']} if 'alternative_id' in frame else {}),
            **({'event_x':frame['values']['event_x']} if 'event_x' in frame.get('values',{}) else {}),
            **({'event_amount':frame['values']['event_amount']} if 'event_amount' in frame.get('values',{}) else {}),
            **({'defending_player':frame['values']['defending_player']} if 'defending_player' in frame.get('values',{}) else {}),
            **({'event_controllers':list(frame['values']['event_controllers'])} if 'event_controllers' in frame.get('values',{}) else {}),
            **({'event_subjects':[target_summary(value) for value in frame['bindings']['event_subject']]} if 'event_subject' in frame.get('bindings',{}) else {}),
            'targets':[target_summary(value) for value in frame['targets']],
            **({'modes':[{'mode_id':g['mode_id'],'targets':[target_summary(value) for value in g['targets']]} for g in frame['mode_groups']]} if 'mode_groups' in frame else {})}
    stack=[frame_summary(frame) for frame in reversed(kernel.stack)]
    resolving=frame_summary(kernel.resolving) if kernel.resolving else None
    announcement=None
    if kernel.announcement:
        pending=kernel.announcement;source=RulesObject.from_json(pending['source'])
        announcement={'actor':pending['quote']['actor'],'name':kernel.definition(source).name,
            'source':source.ref.to_json(),'ability_id':pending['quote']['ability_id'],'chosen_x':pending['quote']['x_value'],
            'cost_objects':[target_summary(value) for value in pending['refs']]}
        if actor==pending['quote']['actor']:announcement['payment']=deepcopy(pending['payment'])
    combat=None
    if kernel.combat:
        combat={'attackers':[{'ref':deepcopy(row['ref']),'defender':row['defender']} for row in kernel.combat['attackers']],
                'blocks':{key:[deepcopy(row['ref']) for row in rows] for key,rows in kernel.combat['blocks'].items()},
                'blocked':list(kernel.combat['blocked'])}
    hand=sorted(state.zone(actor,Zone.HAND),key=lambda obj:(kernel.definition(obj).name,obj.ref))
    packet={'schema':1,'actor':actor,'revision':kernel.revision,
        'turn':{'active':kernel.active,'phase':kernel.phase,'number':state.turn_number,'land_plays_used':kernel.turn_schedule['land_plays'] if kernel.turn_schedule else 0},
        'players':players,'zones':zones,'stack':stack,'resolving':resolving,'announcement':announcement,'combat':combat,
        'hand':[_card(kernel,obj,views) for obj in hand],
        'decision':decision_for_actor(kernel,actor),'outcome':deepcopy(kernel.outcome)}
    if actor in kernel.library_observations:
        packet['library_observation']=deepcopy(kernel.library_observations[actor])
    if actor in state.live_players:
        try:inspection=kernel.inspect_library_search(actor)
        except RulesViolation:pass
        else:packet['library_search']=[option.to_json() for option in inspection]
    return packet
