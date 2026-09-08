"""A bounded tactical assessment of an exact strategic component, not a new plan."""
from .runtime_store import identity

FIELDS={'long_term_validity','long_term_invalid_reason'}
GUIDANCE=(
    'Every short_term publication requires long_term_validity:valid or invalid. '
    'Evaluate the current goal against the supplied facts: completed milestones still '
    'described as future work, acquired/lost pieces, obsolete survival assumptions, '
    'or tactical prose that supersedes the strategic route mean invalid when they '
    'make its guidance no longer applicable. For example, "find the fourth land" is '
    'stale when five lands are already controlled. Age alone is not invalidity. '
    'If invalid, include long_term_invalid_reason (1–300 characters). If valid, omit '
    'the reason. Do not repeat strategic_disposition or strategic_review. Python '
    'binds the assessment to the frozen goal, delivers it with the short-term prose '
    'to the pilot and long-term planner, and queues one strategic revision only for '
    'an invalid current goal. Invalid publication releases this background slot; '
    'do not wait or write the replacement goal yourself.'
)


def assess(root,game,actor,state,batch,snapshot,value,response):
    from . import component_store as components, split_planning
    if {'strategic_disposition','strategic_review'} & set(response):
        raise ValueError('Use long_term_validity instead of strategic_disposition/strategic_review in this packet.')
    status=response.get('long_term_validity');reason=response.get('long_term_invalid_reason')
    if status not in ('valid','invalid'):raise ValueError('Every short_term publication requires long_term_validity: valid or invalid.')
    if status=='invalid' and (not isinstance(reason,str) or not reason.strip() or len(reason)>300):
        raise ValueError('An invalid goal requires long_term_invalid_reason of 1–300 characters.')
    if status=='valid' and reason is not None:raise ValueError('A valid goal does not need long_term_invalid_reason.')
    source=value.get('component_refs',{}).get('long_term')
    if not source:raise ValueError('Assess the goal component supplied in the frozen input.')
    assessment={'status':status,'goal_component_id':source['component_id'],'goal_version':source['version']}
    if reason:assessment['reason']=reason.strip()
    current=components.current(root,game,actor).get('long_term')
    review=None
    if status=='invalid' and current and identity(current)==source['component_id']:
        review=split_planning._review(root,game,actor,state,batch,snapshot,{
            'strategic_disposition':'review_requested','strategic_review':{
                'question':'Revise the no-longer-applicable goal: '+reason.strip(),
                'evidence':['Invalidated goal component '+source['component_id']],
                'interim':response['short_term_plan'],
                'useful_by':'Next real pilot decision; publish the replacement with its diplomacy brief.'}},
            _invalid_goal=source['component_id'])
    return assessment,review


def project(assessment,current_goal_id):
    if not assessment:return None
    return {**assessment,'applies_to_current_goal':assessment['goal_component_id']==current_goal_id}


def requires_revision(value,current_goal_id):
    return any(r.get('invalid_goal_component_id')==current_goal_id for r in value.get('strategic_reviews',[]))


def presentation(assessment):
    if not assessment:return ''
    label='Long term plan still valid' if assessment['status']=='valid' else 'Long term plan invalid'
    if not assessment.get('applies_to_current_goal',True):label+=' (assessment of a previous goal; current goal not yet assessed)'
    return label+f" — assessed goal v{assessment['goal_version']}."+(' '+assessment['reason'] if assessment.get('reason') else '')
