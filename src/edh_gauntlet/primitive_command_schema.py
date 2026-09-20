"""Validate proposed command shape before publication; never test future legality."""
from .rules_state import RulesViolation

FIELDS={
 'cast':({'source','targets','x_value'},{'payment','autotap','face','modes','alternative_id','counter_division','kicker','replicate','life_costs','hybrid_choices'}),
 'activate':({'source','ability_id','targets','x_value'},{'payment','autotap','counter_division'}),
 'play_land':({'source'},{'face'}),
 'unlock_room':({'source','door'},{'payment','autotap'}),
 'answer':({'indexes'},{'request_id','choice_from'}),
 'allocate_counters':({'request_id','allocations'},set()),
 'pay_mana':({'request_id'},{'payment','autotap'}),
 'decline_cast':({'request_id'},set()),
 'attack':({'attackers'},{'payment'}),'block':({'assignments'},set()),
 'damage':({'assignments'},set()),'pass':(set(),set())}

def validate(command):
    from .primitive_intent import normalize
    normalized=normalize(command);command.clear();command.update(normalized)
    kind=command.get('kind')
    if kind not in FIELDS:raise RulesViolation('Unsupported proposed primitive command')
    # Empty targeting metadata carries no choice. Canonicalize this common
    # template artifact instead of spending another planner turn correcting it.
    if kind=='play_land' and command.get('targets')==[]:command.pop('targets')
    required,optional=FIELDS[kind]
    missing=required-command.keys();extra=command.keys()-required-optional-{'kind'}
    if missing or extra:
        raise RulesViolation(f'{kind} command fields: missing {sorted(missing)}; unexpected {sorted(extra)}. Required: {sorted(required)}; optional: {sorted(optional)}. No proposal was published.')
    if kind=='answer' and ('request_id' in command)==('choice_from' in command):
        raise RulesViolation('answer requires exactly one of request_id or choice_from')
    for key in ('targets','indexes','attackers','allocations','modes','counter_division'):
        if key in command and type(command[key]) is not list:raise RulesViolation(f'{kind}.{key} requires an array')
    if 'assignments' in command and type(command['assignments']) is not dict:raise RulesViolation(f'{kind}.assignments requires an object keyed by combat UID')
    if 'x_value' in command and (type(command['x_value']) is not int or command['x_value']<0):raise RulesViolation('x_value requires a nonnegative integer')
    if 'indexes' in command and any(type(i) is not int or i<0 for i in command['indexes']):raise RulesViolation('indexes requires nonnegative integers')
    if 'face' in command and command['face'] not in ('front','back','left','right'):raise RulesViolation('Invalid face')

    def reference(value,player=False):
        if type(value) is not dict:raise RulesViolation('Use an exact object reference or a host-resolved object label')
        if player and set(value)=={'player'} and isinstance(value['player'],str):return
        if set(value)=={'owned_card','zone'} and isinstance(value['owned_card'],str) and value['zone'] in ('hand','battlefield','graveyard','exile','command','stack','library'):return
        if set(value)=={'card_id','incarnation'} and isinstance(value['card_id'],str) and type(value['incarnation']) is int and value['incarnation']>=0:return
        raise RulesViolation('Object reference requires card_id/incarnation or owned_card/zone')
    if 'source' in command:reference(command['source'])
    for target in command.get('targets',[]):reference(target,player=True)
    if 'payment' in command and command['payment'] is not None:
        from .rules_casting import Payment
        def mana_counts(value):
            if type(value) is not dict:return
            if 'mana' in value:
                mana=value['mana']
                if (type(mana) is not dict or set(mana)-set('WUBRGC')
                    or any(type(n) is not int or n<0 for n in mana.values())):
                    raise RulesViolation('payment.mana requires nonnegative W/U/B/R/G/C counts of actual mana spent. Generic is a cost, not a mana type; omit payment for autotap.')
            rows=value.get('mana_actions',[])
            for row in rows if isinstance(rows,list) else []:
                if isinstance(row,dict):mana_counts(row.get('payment'))
        mana_counts(command['payment'])
        def payment_shape(value):
            if isinstance(value,dict):
                if 'owned_card' in value:
                    reference(value)
                    return {'card_id':value['owned_card'],'incarnation':0}
                return {k:payment_shape(v) for k,v in value.items()}
            if isinstance(value,list):return [payment_shape(v) for v in value]
            return value
        try:Payment.from_json(payment_shape(command['payment']))
        except (KeyError,TypeError,ValueError) as exc:raise RulesViolation('Invalid proposed payment format') from exc
