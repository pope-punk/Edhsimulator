"""Closed, externally adjudicated shortcut outcomes with replayable continuations.

Only the host lifecycle can author this command. It is not a pilot action.
As in the legacy referee, operations describe adjudicated net outcomes: damage
shortcuts reduce life, rather than replaying an arbitrarily long damage loop.
"""
from copy import deepcopy
from .rules_state import RulesViolation,Zone,ObjectRef
from .combo_adjudication import validate_combo_adjudication_response,MAX_INTEGER


def apply(kernel,actor,command):
    kernel._idle()
    if kernel.priority!=actor or kernel.stack:raise RulesViolation('Shortcut requires the preserved empty-stack priority window')
    response=validate_combo_adjudication_response(command['response'],known_pilots=kernel.state.players)
    if response['verdict']!='approved':raise RulesViolation('Only approved adjudications change rules state')
    if command['action_id'] in kernel.action_receipts:raise RulesViolation('Shortcut already applied')
    ops=deepcopy(response['operations'])
    # Bind every affected permanent before making any mutation.
    for op in ops:
        if op['op'] in ('damage_player','set_life'):
            if op['player'] not in kernel.state.live_players:raise RulesViolation('Shortcut names an eliminated player')
        else:
            scope=op['players'];players=(kernel.state.live_players if scope=='all' else tuple(p for p in kernel.state.live_players if p!=actor) if scope=='opponents' else scope)
            objects=[o for o in kernel.state.objects(Zone.BATTLEFIELD) if o.controller in players and not o.phased]
            ids=op.get('uids');mapping={o.ref.card_id+'@'+str(o.ref.incarnation):o for o in objects}
            if ids is not None and any(uid not in mapping for uid in ids):raise RulesViolation('Shortcut bounce has an unavailable exact UID')
            op['refs']=[o.ref.to_json() for o in objects if ids is None or o.ref.card_id+'@'+str(o.ref.incarnation) in ids]
    public=[o for z in (Zone.BATTLEFIELD,Zone.COMMAND,Zone.GRAVEYARD,Zone.EXILE) for o in kernel.state.objects(z) if o.owner==actor]
    if not public:raise RulesViolation('Shortcut requires a public source anchor')
    anchor=sorted(public,key=lambda o:(not o.commander,o.ref.card_id))[0]
    frame=kernel._frame(anchor,actor,())
    frame['adjudicated_combo']=response['proposal_id']
    frame['tasks']=[{'id':kernel._id('combo-operation'),'effect':None,'combo_operation':op} for op in ops]
    kernel.resolving=frame
    kernel.action_receipts[command['action_id']]={'combo_proposal':response['proposal_id'],'response':response}
    kernel._event('combo_adjudication_approved',actor=actor,response=response)
    return kernel.advance()


def execute(kernel,frame,task):
    op=task['combo_operation'];kind=op['op']
    if kind=='bounce_permanents':
        kernel._move(tuple(ObjectRef.from_json(r) for r in op['refs']),Zone.HAND,frame,task['id'])
    else:
        player=op['player']
        if player not in kernel.state.live_players:return
        old=kernel.state.life(player)
        if kind=='damage_player':new=0 if op['amount']=='infinite' else old-op['amount']
        else:new=MAX_INTEGER if op['value']=='infinite' else op['value']
        # Net adjudicated state, not a second execution of the demonstrated loop.
        if new<old:kernel.state.lose_life_batch((player,),old-new)
        elif new>old:kernel.state.gain_life(player,new-old)
        kernel._event('combo_life_result',player=player,life=new,proposal_id=frame['adjudicated_combo'])
