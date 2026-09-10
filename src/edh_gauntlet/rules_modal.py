"""Pure modal announcement preparation shared by paid casting and replay."""
from dataclasses import replace
from .rules_state import RulesViolation


def prepare_modal(kernel,source,actor,spec,choices,*,x_value=0):
    """Validate one authored choice per selected mode, then normalize printed order.

    Choices are immutable (mode ID, target tuple) pairs. A target may appear in
    different modes; each mode independently retains ordinary target validation.
    No state, answers, payments or accepted-action receipts are changed here.
    """
    if not isinstance(choices,tuple) or any(not isinstance(row,tuple) or len(row)!=2
            or type(row[0]) is not str or not isinstance(row[1],tuple) for row in choices):
        raise RulesViolation('Invalid modal choices')
    ids=[row[0] for row in choices]
    modes={mode.mode_id:mode for mode in spec.modes}
    if len(ids)!=len(set(ids)) or any(key not in modes for key in ids):
        raise RulesViolation('Unknown or repeated spell mode')
    maximum=spec.maximum
    if spec.extra_mode_condition is not None and kernel._condition_holds(spec.extra_mode_condition,replace(source,controller=actor)):
        maximum=spec.conditional_maximum
    if not spec.minimum<=len(choices)<=maximum:raise RulesViolation('Wrong number of selected modes')
    selected=dict(choices)
    for key,targets in choices:
        kernel._announcement_targets(source,actor,modes[key].targets,targets,x_value)
    return tuple((mode.mode_id,selected[mode.mode_id]) for mode in spec.modes if mode.mode_id in selected)
