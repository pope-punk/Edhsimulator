"""Explicit combat guidance using the existing bounded approved sequence."""
GUIDANCE={
    'instruction':'Include one concrete combat recommendation for the upcoming own turn when visible attackers make it relevant: hold all creatures back or declare the exact attacking group. Put it in action_sequence, not a separate response or planning round. Omit unknown future attackers; the pilot may add them later.',
    'steps':[
        {'kind':'combat_target','phase':'combat','choice':[{'seat':'KNOWN_DEFENDER'},None]},
        {'kind':'declare_attackers','phase':'combat','choice':[{'uid':'VISIBLE_ATTACKER_UID'}]},
    ],
    'no_attack':'Keep the required combat_target step with a known legal defender, then use declare_attackers choice:[] to hold everything back. Target selection alone declares no attack. combat_target does not allow PASS. Never pass a mandatory attack requirement.',
    'review':'The pilot approves/rejects each step and may override the defender or attacker list in its ordinary main-phase batch, including new visible creatures. Supply id, seat_turn, rationale, scheduler and factual requires on every step. Keep the existing 16-step/12000-byte total limit.',
    'boundaries':'Include only known intervening main/priority PASS choices you intend to decline. Use explicit snooze policies on each step. Opponent passes may preserve resume_after_passes; intervention, new information, changed legality or mandatory choices stop execution for the pilot. Combat damage is still an execution boundary.',
}


def apply(value):
    if value.get('role')!='short_term_planner' or value.get('combat_proposals')!=1:return value
    for stage in value.get('publication_stages',[]):
        if stage['stage']=='actions':stage['instruction']+=' Include the combat recommendation described in symbolic_vocabulary.sequence_format.combat, using the same action_sequence and approval mechanism.'
    value['symbolic_vocabulary']['sequence_format']['combat']=GUIDANCE
    return value


def validate(sequence):
    for step in sequence:
        kind=step.get('kind');choice=step.get('choice')
        if kind=='combat_target':
            if (not isinstance(choice,list) or len(choice)!=2 or not isinstance(choice[0],dict) or
                    set(choice[0])!={'seat'} or (choice[1] is not None and
                    (not isinstance(choice[1],dict) or set(choice[1])!={'uid'}))):
                raise ValueError('combat_target requires [{seat:DEFENDER}, null] or [{seat:DEFENDER}, {uid:TARGET}]; a bare player reference and PASS are invalid.')
        if kind=='declare_attackers' and (not isinstance(choice,list) or
                any(not isinstance(item,dict) or set(item)!={'uid'} for item in choice)):
            raise ValueError('declare_attackers requires a list of visible UID objects; [] means no attackers.')
