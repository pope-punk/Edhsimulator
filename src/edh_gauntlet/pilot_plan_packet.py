"""Plan-first presentation reconstructed from an immutable decision claim."""
import json
from .scheduler import CHOICE_GUIDANCE


GUIDANCE = (
    'Use the long-term goal and short-term prose below as the primary strategic frame '
    'for this decision. Prefer actions that advance that goal and preserve the sequence\'s '
    'intended resources, protection and snooze policies. Apply Python-reported changes and current legal options to the '
    'choice: adapt when a material change, immediate danger or clearly better opportunity '
    'warrants it. Prose explains intent; symbolic steps are execution proposals, not a '
    'substitute for that intent. Do this within the current decision; do not write or '
    'validate a plan, add an inference turn, or wait for the planner. When a rationale is '
    'required, connect the action to the goal or the material reason for departing; do not '
    'recap the plans. If the goal\'s route or survival assumptions are stale, request '
    'planner_alarm {mode:now,long_term:true} at an allowed priority decision and keep '
    'playing. A goal still naming acquired/lost pieces, a completed stabilization loop, '
    'or obsolete survival assumptions needs that existing alarm when material; a recent '
    'short-term publication does not refresh the goal. Age alone is not a mandatory wake. '
    'Current rules, visible facts and required choices take precedence. '+CHOICE_GUIDANCE
)


def render(brief, attachment, plan):
    """Keep prose visible on every turn without storing it in each input file."""
    prose = plan or attachment.get('plan') or {}
    lines = ['Strategic focus for this decision', GUIDANCE, '']
    if attachment.get('plan_id'):
        lines.append('Frozen plan version: ' + attachment['plan_id'][:12] + '.')
        prefix = (plan or {}).get('source_session', {}).get('accepted_prefix_count')
        if prefix is not None:
            lines.append(f'Planning snapshot: after global decision {prefix}. '
                         'Turn numbers in plan prose refer to your own turns unless stated otherwise.')
    from .plan_provenance import label
    lines += ['Current long-term goal:', label(prose,'long_term'), prose.get('long_term_plan') or
              '(No published goal in this claim; use current facts and legal options.)',
              '', 'Current short-term sequence:', label(prose,'short_term'), prose.get('short_term_plan') or
              '(No published short-term prose in this claim; decide from the goal and current facts.)', '']
    if attachment.get('goal_assessment'):
        from .goal_validity import presentation
        lines += [presentation(attachment['goal_assessment'])]
        if attachment['goal_assessment']['status']=='invalid' and attachment['goal_assessment'].get('applies_to_current_goal'):
            lines.append('Use current facts and the tactical interim plan while the invalid goal is being revised; do not author a replacement goal.')
        lines.append('')
    if attachment.get('table_talk_suggestion'):
        lines += ['Optional table talk (edit/use/ignore at this legal opportunity; never post automatically):',
                  json.dumps(attachment['table_talk_suggestion'],ensure_ascii=False,separators=(',',':')), '']
    if attachment.get('diplomacy_outcomes'):
        lines+=['Actionable diplomacy (advisory; adapt actual choices and explain material departures in existing rationales):',
                json.dumps(attachment['diplomacy_outcomes'],ensure_ascii=False,separators=(',',':')),
                'Earlier omitted outcomes: '+str(attachment.get('diplomacy_outcomes_omitted',0))+'. Full public transcript remains inspectable.','']
    lines += ['Changes since planning (Python):',
              json.dumps({key: attachment[key] for key in (
                  'status', 'change_count', 'dependencies_changed', 'unverified_dependencies',
                  'intervening_event_count', 'publication_stage', 'publication_complete')
                  if key in attachment}, ensure_ascii=False, separators=(',', ':')),
              'Factual differences and the symbolic proposal follow the decision details.',
              '', 'Current decision and legal information:', brief]
    if attachment.get('proposal_readiness'):
        lines[lines.index('Current decision and legal information:'):lines.index('Current decision and legal information:')]=[
            'Symbolic proposal readiness (Python; compatibility is not approval):',
            json.dumps(attachment['proposal_readiness'],ensure_ascii=False,separators=(',',':')),
            'Approve a batch only at land_play or main_action. In that batch, list every proposed ID exactly once '
            'in approve or reject; put expired and executed_ids in reject. Without a batch, no separate rejection turn is needed. '
            'current_choice_alternatives are exact legal symbols for the same proposed card. If appropriate, explicitly '
            'adopt one through batch.overrides[step_id].choice; Python never substitutes it automatically.','']
    # Display each prose field once. Preserve the existing bounded diff and
    # incremental sequence payload, without repeating the full action history.
    detail = {key: value for key, value in attachment.items() if key not in {'plan','table_talk_suggestion','goal_assessment'}}
    if attachment.get('context_handling')==1:
        detail={key:attachment[key] for key in ('changes','changes_omitted','changed_categories',
                'event_types','inspection') if key in attachment}
    remaining = {key: value for key, value in attachment.get('plan', {}).items()
                 if key not in {'long_term_plan', 'short_term_plan','table_talk'}}
    if remaining:
        detail['plan'] = remaining
    lines += ['', 'Supporting continuity and symbolic proposal:',
              json.dumps(detail, ensure_ascii=False, separators=(',', ':'))]
    return '\n'.join(lines) + '\n'
