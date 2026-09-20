"""Fresh-contract deciders choose actions, not mana production or allocation."""
from copy import deepcopy
from .rules_state import RulesViolation, ObjectRef


def validate(campaign,actor,command,*,future=False):
    if campaign.config.get('automatic_decider_mana')!=1:return
    if not isinstance(command,dict):raise RulesViolation('Expected an action command')
    if 'autotap' in command:raise RulesViolation('Mana selection is automatic; omit autotap or accept the planner sequence unchanged')
    p=command.get('payment') or {}
    if not isinstance(p,dict):raise RulesViolation('Invalid non-mana cost selections')
    if any(p.get(k) for k in ('mana','mana_actions','tagged_mana','convoke','cost_order')):
        raise RulesViolation('Deciders do not author mana payments; choose the action or accept planner steps unchanged')
    if command.get('kind')=='activate':
        ref=command.get('source',{})
        if isinstance(ref,dict) and set(ref)=={'owned_card','zone'}:
            obj=campaign.kernel.state.get(campaign.kernel.state.current(ref['owned_card']))
            campaign.store._adapter._visible_ref(obj.ref.to_json(),actor)
            if obj.owner!=actor or (not future and obj.zone.value!=ref['zone']):raise RulesViolation('Symbolic object is unavailable')
        else:obj=campaign.kernel.state.get(campaign.store._adapter._visible_ref(ref,actor))
        ability=next((a for a in campaign.kernel.activated_abilities(obj) if a.ability_id==command.get('ability_id')),None)
        if ability is None:raise RulesViolation('Unavailable activation; choose a supplied non-mana ability')
        if ability.mana_ability:
            raise RulesViolation('Mana abilities belong to automatic payment or unchanged planner sequences, not direct decider actions')


def presentation(value):
    """Hide mana activation menus; retain board objects and approved plan prose."""
    value=deepcopy(value)
    def clean(node):
        if isinstance(node,list):return [clean(v) for v in node if not (isinstance(v,dict) and v.get('mana_ability') is True)]
        if isinstance(node,dict):return {k:clean(v) for k,v in node.items() if k!='intrinsic_land_mana'}
        return node
    for key in ('board','previous_board','current_decision','action_facts'):
        if key in value:value[key]=clean(value[key])
    value['payment_policy']='Choose the spell or non-mana ability without mana instructions. Python pays automatically, including supported filter costs, color choices, life payments and other mana-ability costs. No preliminary taps or planner sequence is needed when the menu marks automatic mana checked. Accept planner mana sequencing by approving its unchanged step IDs. Pay an optional mana request with pay_mana and request_id only, or decline with payment:null.'
    return value

COMMANDS='''Primitive commands omit revision, action_id and actor; Python supplies them.
cast:{kind:"cast",source:REF,targets:[],x_value:0};
activate:{kind:"activate",source:REF,ability_id:EXACT_NON_MANA_ID,targets:[],x_value:0}.
Python selects and pays mana automatically, including supported paid mana filters and additional mana-ability costs (including life and sacrifice). Submit the intended spell/ability; the host sequences funding, filtering and payment atomically. Do not submit autotap, reservations,
mana production commands or mana allocations. To use a planner's mana sequencing,
approve the unchanged planner steps by ID. A changed action returns to auto payment.
You still choose targets, modes, X, optional casting choices and non-mana costs.
Non-mana cost selections use payment:{taps:[REF],zone_costs:{COST_ID:[REF]}};
source tap costs are implicit. REF is {card_id,incarnation}; player targets {player:SEAT}.
answer:{kind:"answer",request_id:CURRENT_CHOICE_ID,indexes:[ZERO_BASED_INDEXES]};
pass:{kind:"pass"}; concede:{kind:"concede"} only at priority;
play_land:{kind:"play_land",source:REF,face:"front"|"back"}.
unlock_room:{kind:"unlock_room",source:REF,door:"left"|"right"} also pays automatically.
Optional casting fields: face, modes, alternative_id, counter_division, kicker,
replicate, life_costs, hybrid_choices. These are gameplay choices, not mana taps.
attack:{kind:"attack",attackers:[{source:REF,defender:SEAT_OR_REF}]};
block:{kind:"block",assignments:{ATTACKER_UID:[BLOCKER_UID,...]}}. Include every
attacker UID exactly once, [] if unblocked; use eligible blockers at most once.
damage uses assignments matching the supplied specification.
pay_mana:{kind:"pay_mana",request_id:CURRENT_ID} automatically pays a requested
resolution cost. Add payment:null only to decline. No mana instructions required.
decline_cast:{kind:"decline_cast",request_id}; allocate_counters:{kind:"allocate_counters",request_id,allocations}.
Never infer a future request ID. No approved sequence answers unknown choices.
'''
