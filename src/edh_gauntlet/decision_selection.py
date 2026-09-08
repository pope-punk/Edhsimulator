"""Shared bounds for pilot-authored multi-select answers and replay."""


def validate_count(request, indexes):
    minimum=request.get('min_selected_if_any',1)
    if indexes and len(indexes)<minimum:
        raise ValueError(f'Select no blockers or at least {minimum} distinct blockers for this attacker.')
