"""Canonical action intent shared by publication, revision and execution.

This supplies syntax defaults, never gameplay choices. Explicit planner mana
payments remain explicit; non-mana selections do not opt out of autotapping.
"""
from copy import deepcopy
from .rules_state import RulesViolation

PAID={'cast','activate','pay_mana','unlock_room'}

def normalize(value):
    if type(value) is not dict:raise RulesViolation('Expected an action command')
    command=deepcopy(value);kind=command.get('kind')
    if kind in {'cast','activate'}:
        command.setdefault('targets',[])
        command.setdefault('x_value',0)
    if kind in {'cast','activate','unlock_room'}:
        if command.get('payment',{}) is None:
            raise RulesViolation('payment:null declines only an optional pay_mana request; omit payment to pay for this action automatically')
    if kind=='play_land' and command.get('targets')==[]:command.pop('targets')
    p=command.get('payment')
    if kind in PAID and isinstance(p,dict):
        # No mana allocation was authored. Preserve the chosen sacrifice/tap
        # costs while delegating production and spending to the host.
        if not set(p)&{'mana','mana_actions','tagged_mana','convoke','cost_order'}:
            command.setdefault('autotap',{})
        p.setdefault('mana',{})
        p.setdefault('taps',[])
    return command


def waiting_reason(campaign,actor,command):
    """Recognize a dependency already on the stack, not hypothetical legality.

    Only approved passes/snoozes may progress this wait. A missing object with
    no live stack dependency is still an execution failure, not an endless wait.
    """
    kernel=campaign.kernel
    if not kernel.stack:return None
    kind=command.get('kind')
    if kind in {'play_land','unlock_room'}:return 'waiting for an empty stack'
    source=command.get('source',{})
    try:
        if set(source)=={'owned_card','zone'}:
            obj=kernel.state.get(kernel.state.current(source['owned_card']))
            campaign.store._adapter._visible_ref(obj.ref.to_json(),actor)
            if obj.owner!=actor:return None
            if obj.zone.value=='stack' and source['zone']=='battlefield':
                return 'waiting for the proposed permanent to resolve'
        else:
            obj=kernel.state.get(campaign.store._adapter._visible_ref(source,actor))
        if kind=='cast':
            obj=kernel._announced_face(obj,command.get('face','front'))
            spec=kernel.definition(obj).cast
            from .rules_characteristics import base
            if spec and spec.timing=='sorcery' and 'flash' not in base(obj,kernel.definitions).keywords:
                return 'waiting for sorcery timing after resolution'
        elif kind=='activate':
            spec=next((a for a in kernel.activated_abilities(obj) if a.ability_id==command.get('ability_id')),None)
            if spec and spec.timing=='sorcery':return 'waiting for sorcery timing after resolution'
    except (RulesViolation,KeyError,TypeError):return None
    return None


def preflight(campaign,actor,steps,request_id):
    """Check only the first action that would execute *now* on an isolated kernel.

    Later actions depend on unknown resolution/opponent choices. Do not simulate
    those or reject future plans against the present board. Failure keeps the
    claim open so the same inference can correct its unaccepted approval.
    """
    if not steps:return
    from .primitive_actions import phase_group,bind_command
    step=steps[0];kernel=campaign.kernel
    if (kernel.active!=actor or step['seat_turn']!=campaign.state()['actors'][actor].get('turns',0)
        or step['phase']!=phase_group(kernel.phase)
        or campaign.next_action().get('decision_kind')!='priority'
        or step['command'].get('kind') not in {'cast','activate','play_land','unlock_room'}
        or waiting_reason(campaign,actor,step['command'])):return
    from .rules_adapter import RulesActorAdapter
    try:
        command=bind_command(campaign,actor,step['command'],request_id)
        trial=type(kernel).restore(kernel.snapshot(),kernel._base_definitions.values())
        RulesActorAdapter(trial)._execute(actor,command)
    except RulesViolation as exc:
        raise RulesViolation(f'First planned action {step["id"]} cannot execute now: {exc}. No batch was approved and no resources were spent. Correct only the unaccepted action; do not replay earlier accepted steps.') from exc
