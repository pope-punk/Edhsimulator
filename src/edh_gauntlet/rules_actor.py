"""Pure actor projections for the primitive host adapter.

This is an explicit allowlist, never a filtered kernel checkpoint. The current
kernel exposes only explicitly bound reveals; arbitrary reveal permissions and
face-down objects remain unsupported. Production admission stays closed.
"""
import json
from copy import deepcopy
from .rules_program import encode,ConvokeCast,CopyCast
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
        **({'convoke':True} if isinstance(kernel.definition(obj).cast,ConvokeCast) else {}),
        **({'copy_cast':encode(kernel.definition(obj).cast)} if isinstance(kernel.definition(obj).cast,CopyCast) else {}),
        'zone':obj.zone.value,'types':sorted(view.types),'subtypes':sorted(view.subtypes-CREATURE_TYPES if all_creature_types else view.subtypes),
        **({'all_creature_types':True} if all_creature_types else {}),
        'supertypes':sorted(view.supertypes),'keywords':sorted(view.keywords),'colors':sorted(view.colors),
        'mana_value':view.mana_value,'power':view.power,'toughness':view.toughness,
        'tapped':obj.tapped,'phased':obj.phased,'counters':dict(obj.counters),
        **({'monstrous':True} if obj.monstrous else {}),
        **({'untap_blocked':True} if view.untap_blocked else {}),
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
    if kernel._casting_mana_waiting():
        owner=kernel.resolution_cast['actor']
        return {'kind':'casting_mana' if actor==owner else 'waiting','actor':owner}
    if kernel._cast_waiting():
        window=kernel.resolution_cast
        if actor!=window['actor']:return {'kind':'waiting','actor':window['actor']}
        return {'kind':'resolution_cast','request_id':window['id'],'maximum':window['maximum'],
            'origin':window['origin'],'candidates':[ref.to_json() for ref in kernel._resolution_cast_candidates()],
            'revision':kernel.revision}
    if kernel._payment_waiting():
        window=kernel.mana_payment
        if actor!=window['actor']:return {'kind':'waiting','actor':window['actor']}
        return {'kind':'mana_payment','request_id':window['id'],'mana':deepcopy(window['mana']),'revision':kernel.revision}
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
    """Project current state plus explicitly public entry-reveal receipts."""
    if actor not in kernel.state.players:raise RulesViolation('Unknown actor')
    state=kernel.state;views=kernel.characteristics()
    revealed={obj.ref:obj for obj in kernel.revealed_ability_sources()}
    players=[];permissions=kernel.player_permissions()
    for seat in state.players:
        row={'seat':seat,'life':state.life(seat),'starting_life':state.starting_life(seat),'mana':dict(state.mana_pool(seat)),
             'counters':dict(state.player_counters(seat)),'departed':seat not in state.live_players,
             'permissions':permissions[seat],'hand_count':len(state.zone(seat,Zone.HAND)),'library_count':len(state.zone(seat,Zone.LIBRARY))}
        try:row['commander_identity']=list(state.commander_identity(seat))
        except RulesViolation:pass # Unbound fixture metadata is not an inferred identity.
        if seat==actor and state.mana_tags(seat):row['tagged_mana']=state.mana_tags(seat)
        players.append(row)
    zones={zone.value:{seat:[_card(kernel,obj,views) for obj in state.zone(seat,zone)]
                      for seat in state.players} for zone in PUBLIC_ZONES}
    def target_summary(value):
        if 'player' in value:return deepcopy(value)
        try:obj=state.get(ObjectRef.from_json(value))
        except RulesViolation:return {'unavailable':True}
        if obj.zone in (*PUBLIC_ZONES,Zone.STACK) or obj.zone==Zone.HAND and (obj.owner==actor or obj.ref in revealed):
            return obj.ref.to_json()
        return {'hidden':True,'zone':obj.zone.value,'owner':obj.owner}
    def frame_summary(frame):
        source=RulesObject.from_json(frame['source'])
        if frame.get('turn_based'):
            return {'kind':'turn_action','controller':frame['controller'],'phase':kernel.phase}
        if source.zone not in (*PUBLIC_ZONES,Zone.STACK) and not (source.zone==Zone.HAND and source.owner==actor) and not (frame.get('announced_source') or frame.get('values',{}).get('public_source')):
            return {'kind':'effect','controller':frame['controller']}
        return {'id':frame['id'],'kind':'spell' if frame['spell'] else 'ability',
            'name':kernel.definition(source).name,'source':source.ref.to_json(),
            'controller':frame['controller'],'ability_id':frame.get('ability_id'),'chosen_x':frame['chosen_x'],
            **({'alternative_id':frame['alternative_id']} if 'alternative_id' in frame else {}),
            **({'kicker':frame['kicker']} if 'kicker' in frame else {}),
            **({'replicate':frame['replicate']} if 'replicate' in frame else {}),
            **({'without_mana_cost':True} if frame.get('without_mana_cost') else {}),
            **({'copied':True} if frame.get('copied') else {}),
            **({'cannot_be_countered':True} if frame.get('cannot_be_countered') else {}),
            **({'cast_timing':frame['cast_timing']} if 'cast_timing' in frame else {}),
            **({'source_notes':deepcopy(kernel.object_notes[kernel._attachment_key(source.ref)]['values'])}
                if kernel._attachment_key(source.ref) in kernel.object_notes else {}),
            **({'exile_on_stack_exit':True} if frame.get('exile_on_stack_exit') else {}),
            **({'target_controller_groups':[{'target':target_summary(row['ref']),'controller':row['controller']}
                for row in frame['target_controller_groups']]} if 'target_controller_groups' in frame else {}),
            **({'event_x':frame['values']['event_x']} if 'event_x' in frame.get('values',{}) else {}),
            **({'event_amount':frame['values']['event_amount']} if 'event_amount' in frame.get('values',{}) else {}),
            **({'defending_player':frame['values']['defending_player']} if 'defending_player' in frame.get('values',{}) else {}),
            **({'event_controllers':list(frame['values']['event_controllers'])} if 'event_controllers' in frame.get('values',{}) else {}),
            **({'event_subjects':[target_summary(value) for value in frame['bindings']['event_subject']]} if 'event_subject' in frame.get('bindings',{}) else {}),
            **({'paid_cost_stats':deepcopy(frame['values']['paid_cost_stats'])} if 'paid_cost_stats' in frame.get('values',{}) else {}),
            **({'paid_cost_subtypes':deepcopy(frame['values']['paid_cost_subtypes'])} if 'paid_cost_subtypes' in frame.get('values',{}) else {}),
            **({'counter_division':[{'target':target_summary(row['ref']),'amount':row['amount']} for row in frame['values']['counter_division']]} if 'counter_division' in frame.get('values',{}) else {}),
            'targets':[target_summary(value) for value in frame['targets']],
            **({'target_groups':[{'group_id':g['group_id'],'targets':[target_summary(value) for value in g['targets']]} for g in frame['target_groups']]} if 'target_groups' in frame else {}),
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
        'counter_durations':[{'effect_id':row['effect']['effect_id'],'counter_kind':row['counter_kind'],
            'recipients':[ref.to_json() for ref in refs],'changes':deepcopy(row['effect']['changes'])}
            for row in kernel.counter_effects if (refs:=kernel._counter_duration_refs(row))],
        'hand':[_card(kernel,obj,views) for obj in hand],
        'revealed_hand':[_card(kernel,obj,views) for obj in revealed.values()],
        'decision':decision_for_actor(kernel,actor),'outcome':deepcopy(kernel.outcome)}
    # These are historical disclosures, not permission to inspect a hand or to
    # follow a hidden card after a move/shuffle. Never forward choice options or
    # raw event dictionaries; only the identities actually revealed are public.
    entry_reveals=[{'event_index':event['index'],'player':event['player'],
                   'refs':deepcopy(event['refs']),'names':list(event['names'])}
                  for event in kernel.semantic_events
                  if event['kind']=='cards_revealed' and event.get('cause')=='entry_payment']
    if entry_reveals:packet['public_entry_reveals']=entry_reveals
    # Links disclose only exact objects still face up in exile. Source refs
    # describe their public historical incarnation, never its later hidden card.
    links=[]
    for key,values in sorted(kernel.linked_exile.items()):
        refs=kernel._current_exiled_refs(values)
        if not refs:continue
        source,definition_id,link_id=json.loads(key)
        links.append({'source':deepcopy(source),'source_name':kernel.definitions[definition_id].name,
                      'link_id':link_id,'exiled':[ref.to_json() for ref in refs]})
    if links:packet['linked_exile']=links
    durations=[]
    for key,row in kernel.exile_durations.items():
        refs=kernel._current_exiled_refs(row['refs'])
        if not refs:continue
        source=RulesObject.from_json(row['source'])
        durations.append({'source':source.ref.to_json(),'source_name':kernel.definition(source).name,
            'exiled':[ref.to_json() for ref in refs]})
    if durations:packet['exile_until_source_leaves']=durations
    phased=[]
    for key,row in sorted(kernel.phase_links.items()):
        try:obj=kernel.state.get(ObjectRef.from_json(row['ref']))
        except RulesViolation:continue
        if obj.zone!=Zone.BATTLEFIELD or not obj.phased:continue
        root_ref=ObjectRef.from_json(row['root'])
        root=kernel.phase_links.get(kernel._phase_key(root_ref))
        try:root_object=state.get(root_ref)
        except RulesViolation:root_object=None
        if root_object is None or root_object.zone!=Zone.BATTLEFIELD or not root_object.phased:root=None
        phased.append({'ref':deepcopy(row['ref']),'root':deepcopy(row['root']),
            'indirect':row['ref']!=row['root'],'controller_at_phase_out':row['controller'],
            'return_controller':root['controller'] if root is not None else None})
    if phased:packet['phasing']=phased
    notes=[]
    for row in kernel.object_notes.values():
        try:obj=state.get(ObjectRef.from_json(row['ref']))
        except RulesViolation:continue
        if obj.zone==Zone.BATTLEFIELD:notes.append(deepcopy(row))
    if notes:packet['object_notes']=notes
    if kernel.mana_payment:
        window=kernel.mana_payment
        packet['resolution_payment']={'actor':window['actor'],'request_id':window['id'],
            'mana':deepcopy(window['mana']),'parent_frame':window['parent']['id']}
    packet['life_lost_this_turn']={p:state.life_lost_this_turn(p) for p in state.live_players}
    packet['life_gained_this_turn']={p:state.life_gained_this_turn(p) for p in state.live_players}
    packet['turn_history']={kind:sorted(kernel._history_players(kind)) for kind in ('attacked','freerunning')}
    packet['upkeep_history']=dict(kernel.upkeep_history)
    packet['regeneration_shields']=[{'id':key,'ref':deepcopy(ref)} for key,ref in kernel.regeneration_shields.items()
        if any(obj.ref.to_json()==ref and obj.zone==Zone.BATTLEFIELD for obj in state.objects())]
    packet['draw_counts']={player:kernel.draw_counts.get(player,0) if kernel.draw_count_turn==state.turn_number else 0
        for player in state.live_players}
    if actor in kernel.library_observations:
        packet['library_observation']=deepcopy(kernel.library_observations[actor])
    if actor in state.live_players:
        try:inspection=kernel.inspect_library_search(actor)
        except RulesViolation:pass
        else:packet['library_search']=[option.to_json() for option in inspection]
    packet['revealed_library_tops']={owner:_card(kernel,top,views) for owner in state.live_players
        if kernel.player_permissions()[owner].get('reveal_library_top')
        and (top:=kernel._visible_library_top(owner,actor)) is not None}
    top=kernel._visible_library_top(actor,actor)
    if top is not None and kernel.player_permissions()[actor].get('play_library_top'):
        packet['own_library_top']=_card(kernel,top,views)
    packet['public_library_reveals']=[{'event_index':event['index'],'player':event['player'],
        'refs':deepcopy(event['refs']),'names':list(event['names'])} for event in kernel.semantic_events
        if event['kind']=='cards_revealed' and event.get('cause')=='library_top']
    return packet
