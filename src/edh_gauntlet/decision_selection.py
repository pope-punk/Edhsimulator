"""Shared bounds for pilot-authored multi-select answers and replay."""


def validate_count(request, indexes):
    minimum=request.get('min_selected_if_any',1)
    if indexes and len(indexes)<minimum:
        raise ValueError(f'Select no blockers or at least {minimum} distinct blockers for this attacker.')
    lower=request.get('min_selected',0)
    upper=request.get('max_selected',len(request.get('options',[])))
    if len(indexes)<lower:raise ValueError(f'Select at least {lower} distinct options.')
    if len(indexes)>upper:raise ValueError(f'Select at most {upper} distinct options.')
    groups=request.get('selection_groups')
    if groups is not None:
        counts={}
        for index in indexes:
            if type(index) is not int or not 0<=index<len(groups):raise ValueError('Invalid selection option.')
            group=groups[index];counts[group]=counts.get(group,0)+1
            if counts[group]>request.get('max_per_group',1):
                raise ValueError(f'Too many selections for {group}; maximum {request.get("max_per_group",1)}.')
