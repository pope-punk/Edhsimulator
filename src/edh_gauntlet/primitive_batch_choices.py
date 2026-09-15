"""Exact pilot-approved mana choices tied to one accepted activation frame."""
from .rules_state import RulesViolation


def validate(steps,index):
    command=steps[index]['command'];guard=command.get('choice_from')
    if 'choice_from' not in command:return
    if (set(command)!={'kind','choice_from','indexes'} or command['kind']!='answer'
            or type(guard) is not dict or set(guard)!={'step_id','option_labels'}
            or not index or guard['step_id']!=steps[index-1]['id']
            or steps[index-1]['command'].get('kind') not in {'activate','answer'}
            or (steps[index]['seat_turn'],steps[index]['phase'])!=(steps[index-1]['seat_turn'],steps[index-1]['phase'])):
        raise RulesViolation('Mana continuation must follow its approved activation or mana choice in the same window')
    if steps[index-1]['command']['kind']=='answer' and 'choice_from' not in steps[index-1]['command']:
        raise RulesViolation('Mana continuation requires a guarded predecessor')
    labels=guard['option_labels'];indexes=command['indexes']
    if (type(labels) is not list or not 1<=len(labels)<=32
            or any(type(s) is not str or not s or len(s)>100 for s in labels)
            or type(indexes) is not list or len(indexes)!=1 or type(indexes[0]) is not int
            or not 0<=indexes[0]<len(labels)):
        raise RulesViolation('Mana continuation requires exact ordered option labels and one explicit index')


def bind(campaign,actor,approved,step):
    command=step['command'];guard=command['choice_from'];cursor=approved['cursor']
    request=campaign.kernel.pending_choice;frame=campaign.kernel.resolving
    if (not cursor or guard['step_id']!=approved['steps'][cursor-1]['id']
            or not frame or not frame.get('mana_ability') or frame.get('controller')!=actor
            or not approved.get('continuation_frame') or frame['id']!=approved['continuation_frame']
            or not request or request.actor!=actor or request.kind!='mana_choice'
            or request.minimum!=1 or request.maximum!=1
            or [o.label for o in request.options]!=guard['option_labels']):
        raise RulesViolation('Approved mana choice no longer matches its activation and exact options')
    request.validate(actor,command['indexes'])
    return {'kind':'answer','request_id':request.request_id,'indexes':list(command['indexes'])}
