"""Room special actions, linked miracle reveals and ordinal resolution effects."""
import json
from dataclasses import replace
from .rules_state import ObjectRef,Zone,RulesViolation,ResourcePayment
from .rules_choices import Option
from .rules_casting import Payment,_mana_symbols_satisfied
from .rules_program import (RoomProgram,RoomEventPattern,MiraclePermissions,MiracleCast,
    UnlockRoom,LockRoom,ResolutionSequence,DiscardPlayers,RevealHandDiscard,
    ReturnEnchantmentOrUnlock,AbilityProgram,EventPattern,Selector,Move,Select,encode)


class RoomRules:
    def _validate_room_state(self):
        if type(self.resolution_count_turn) is not int or not 0<=self.resolution_count_turn<=self.state.turn_number or not isinstance(self.resolution_counts,dict):raise RulesViolation('Invalid resolution-count checkpoint')
        for key,n in self.resolution_counts.items():
            if type(key) is not str or type(n) is not int or n<1:raise RulesViolation('Invalid resolution ordinal')
            try:row=json.loads(key)
            except (TypeError,ValueError) as exc:raise RulesViolation('Invalid resolution identity') from exc
            if not isinstance(row,list) or len(row)!=4 or row[1] not in self.definitions or type(row[2]) is not int or row[2]<0 or type(row[3]) is not str or not row[3]:raise RulesViolation('Invalid resolution identity')
            ObjectRef.from_json(row[0])
        for obj in self.state.objects():
            if obj.room_cast and self._room(obj) is None:raise RulesViolation('Room spell half has no paired definition')
        window=self.resolution_cast
        if window and window.get('miracle_reduction') is not None:
            n=window['miracle_reduction']
            if type(n) is not int or n<0 or window['origin']!=Zone.HAND.value or len(window['refs'])!=1 or window['parent'].get('values',{}).get('miracle_reveal')!=window['refs'][0]:raise RulesViolation('Invalid linked miracle permission')

    def _room(self,obj):
        return self.definitions[obj.effective_definition] if isinstance(self.definitions[obj.effective_definition],RoomProgram) else None

    def _room_events(self,obj,old,actor):
        added=set(obj.unlocked)-set(old)
        if not added:return
        full=len(obj.unlocked)==2 and len(old)<2
        for source in self.state.objects(Zone.BATTLEFIELD):
            if source.phased:continue
            for kind in ('door_unlocked','fully_unlocked'):
                if kind=='fully_unlocked' and (not full or 'Room' not in self.effective(obj.ref).subtypes):continue
                for ability in self._trigger_abilities(source,kind):
                    pattern=ability.event
                    if pattern.kind!=kind:continue
                    if pattern.subject=='self' and source.ref!=obj.ref:continue
                    if pattern.controller_only and source.controller!=actor:continue
                    if pattern.recipient_relation=='controlled' and source.controller!=actor:continue
                    if pattern.recipient_relation=='opponent_controlled' and source.controller==actor:continue
                    doors=(pattern.door,) if isinstance(pattern,RoomEventPattern) else tuple(sorted(added))
                    if kind=='door_unlocked':
                        for door in doors:
                            if door in added:self._trigger(source,ability,values={'event_controllers':[actor],'unlocked_door':door})
                    else:self._trigger(source,ability,values={'event_controllers':[actor]})

    def _set_room_doors(self,obj,doors,actor):
        old=obj.unlocked
        if doors==old:return
        self.state.set_unlocked(obj.ref,doors)
        self._event('room_designations_changed',source=obj.ref.to_json(),player=actor,unlocked=list(doors))
        self._room_events(self.state.get(obj.ref),old,actor)

    def unlock_room(self,action_id,actor,ref,door,payment,*,revision):
        self._idle()
        if (revision!=self.revision or actor!=self.priority or actor!=self.active or actor not in self.state.live_players
                or self.phase not in {'precombat_main','postcombat_main'} or self.stack):raise RulesViolation('Unlocking requires sorcery timing and current priority')
        if type(action_id) is not str or not action_id or len(action_id)>128 or action_id in self.action_receipts:raise RulesViolation('Unlocking requires a fresh action identity')
        obj=self.state.get(ref);program=self._room(obj)
        if obj.zone!=Zone.BATTLEFIELD or obj.phased or obj.controller!=actor or program is None or door not in {'left','right'} or door in obj.unlocked:raise RulesViolation('Choose a locked door you control')
        if not isinstance(payment,Payment) or payment.taps or payment.zone_costs or payment.convoke or payment.mana_actions or payment.cost_order:raise RulesViolation('Unlocking accepts an authored mana payment')
        half=program if door=='left' else program.right
        cost=half.cast.cost.mana if half.cast else None
        if cost is None:raise RulesViolation('An absent mana cost cannot be paid')
        resources=ResourcePayment(actor,payment.mana,tagged_mana=self._tagged_resources(actor,payment.tagged_mana))
        self.state.validate_payment(resources);paid=dict(payment.mana)
        if not _mana_symbols_satisfied(cost.symbols,paid) or sum(paid.values())!=cost.generic+len(cost.symbols):raise RulesViolation('Unlock payment must match the door cost')
        self.state.move((),'unlock_payment',payment=resources)
        self.action_receipts[action_id]={'actor':actor,'source':ref.to_json(),'door':door}
        self._set_room_doors(obj,tuple(d for d in ('left','right') if d in obj.unlocked or d==door),actor)
        self.priority=actor;self.passes=[]
        return self.advance()

    def _miracle_reductions(self,actor):
        return tuple(sorted({p.generic_reduction for obj in self.state.objects(Zone.BATTLEFIELD,controller=actor)
            if not obj.phased and isinstance(p:=self.definition(obj).player_permissions,MiraclePermissions)}))

    def _offer_miracle_reveal(self,frame,task,plan,key,actor):
        row=plan['current_draw']
        if row['ref'] is None or not row['reductions']:return
        ref=ObjectRef.from_json(row['ref'])
        try:obj=self.state.get(ref)
        except RulesViolation:return
        if obj.zone!=Zone.HAND:return
        selected=self._choose(key+':miracle',actor,'miracle_reveal','Reveal the first drawn card for miracle?',
            (Option('no','Keep private'),)+tuple(Option(str(n),'Reveal; reduce generic cost by '+str(n)) for n in row['reductions']),1,1)
        if selected[0].key=='no':return
        self._event('cards_revealed',player=actor,refs=[ref.to_json()],names=[self.definition(obj).name],cause='miracle')
        ability=AbilityProgram('miracle:'+key,EventPattern('step_began',step='upkeep'),(MiracleCast(int(selected[0].key)),))
        self._trigger(replace(obj,controller=actor),ability,values={'miracle_reveal':ref.to_json()})

    def _live_miracle_sources(self):
        values=[t.get('values',{}).get('miracle_reveal') for t in self.pending_triggers]
        frames=list(self.stack)+([self.resolving] if self.resolving else [])
        if self.resolution_cast:frames.append(self.resolution_cast['parent'])
        if self.mana_payment:frames.append(self.mana_payment['parent'])
        values.extend(f.get('values',{}).get('miracle_reveal') for f in frames)
        result={}
        for value in values:
            if value is None:continue
            try:obj=self.state.get(ObjectRef.from_json(value))
            except RulesViolation:continue
            if obj.zone==Zone.HAND:result[obj.ref]=obj
        return tuple(result.values())

    def _execute_room_instruction(self,effect,frame,task):
        key=task['id'];actor=frame['controller'];source=self._source(frame)
        if isinstance(effect,(UnlockRoom,LockRoom)):
            choices=[]
            for ref in self._refs(frame,effect.subject):
                try:obj=self.state.get(ref)
                except RulesViolation:continue
                if obj.zone!=Zone.BATTLEFIELD or obj.phased or self._room(obj) is None:continue
                available=tuple(d for d in ('left','right') if (d in obj.unlocked)==isinstance(effect,LockRoom))
                doors=available if effect.door=='both' else (effect.door,) if effect.door in available else ()
                if effect.door is None and available:
                    door=self._choose(key+':door:'+ref.card_id,actor,'room_door','Choose a door.',tuple(Option(d,d) for d in available),1,1)[0].key
                    doors=(door,)
                choices.append((obj,tuple(d for d in ('left','right') if (d in obj.unlocked and d not in doors if isinstance(effect,LockRoom) else d in obj.unlocked or d in doors))))
            for obj,doors in choices:self._set_room_doors(obj,doors,actor)
        elif isinstance(effect,ReturnEnchantmentOrUnlock):
            cards=self._query(Selector(Zone.GRAVEYARD,types=('Enchantment',),relation='owned'),frame)
            rooms=tuple(o for o in self.state.objects(Zone.BATTLEFIELD,controller=actor) if not o.phased and self._room(o) is not None and 'Room' in self.effective(o.ref).subtypes and len(o.unlocked)<2)
            # This is a nonmodal instruction: choose a possible alternative at resolution.
            choices=tuple(Option('return:'+str(i),'Return '+self.definition(o).name,ref=o.ref) for i,o in enumerate(cards))+tuple(Option('unlock:'+str(i),'Unlock '+(self.definition(o).name or 'Room'),ref=o.ref) for i,o in enumerate(rooms))
            if choices:
                selected=self._choose(key,actor,'return_or_unlock','Return an enchantment or unlock a Room door.',choices,1,1)[0]
                if selected.key.startswith('return:'):self._move((selected.ref,),Zone.HAND,frame,key+':return',controller_mode='owner')
                else:
                    self._insert({**frame,'bindings':{**frame['bindings'],'selected':[selected.ref.to_json()]}},(UnlockRoom('selected'),))
        elif isinstance(effect,ResolutionSequence):
            identity=json.dumps([source.ref.to_json(),source.effective_definition,source.characteristic_timestamp,effect.group],sort_keys=True)
            if self.resolution_count_turn!=self.state.turn_number:self.resolution_counts={};self.resolution_count_turn=self.state.turn_number
            number=self.resolution_counts.get(identity,0)+1;self.resolution_counts[identity]=number
            self._event('ability_resolution_counted',source=source.ref.to_json(),group=effect.group,ordinal=number)
            if number<=len(effect.stages):self._insert(frame,effect.stages[number-1])
        elif isinstance(effect,DiscardPlayers):
            if 'discard_plan' not in task:task['discard_plan']={'players':list(self._players(frame,effect.players)),'index':0,'refs':[]}
            plan=task['discard_plan']
            # Every affected player chooses privately in APNAP order before any
            # chosen hand card is disclosed or moved (CR 101.4 and 701.8).
            while plan['index']<len(plan['players']):
                player=plan['players'][plan['index']];hand=self.state.zone(player,Zone.HAND) if player in self.state.live_players else ()
                amount=min(effect.amount,len(hand))
                selected=self._choose(key+':choose:'+str(plan['index']),player,'discard_card','Choose cards to discard.',self._options(hand),amount,amount) if amount else ()
                plan['refs'].extend(o.ref.to_json() for o in selected);plan['index']+=1
            events=self._move(tuple(ObjectRef.from_json(r) for r in plan['refs']),Zone.GRAVEYARD,frame,key+':discard',cause='discard',controller_mode='owner')
            for player in plan['players']:
                self._event('cards_discarded',player=player,refs=[e.before.ref.to_json() for e in events if e.before.owner==player])
        elif isinstance(effect,RevealHandDiscard):
            if 'discard_plan' not in task:task['discard_plan']={'players':list(self._players(frame,effect.players)),'index':0}
            plan=task['discard_plan']
            while plan['index']<len(plan['players']):
                player=plan['players'][plan['index']];step=key+':'+str(plan['index'])
                if player not in self.state.live_players:plan['index']+=1;continue
                hand=self.state.zone(player,Zone.HAND)
                if isinstance(effect,RevealHandDiscard):
                    if not plan.get('revealed'):
                        self._event('cards_revealed',player=player,refs=[o.ref.to_json() for o in hand],names=[self.definition(o).name for o in hand],cause='hand_discard')
                        plan['revealed']=True
                    from .rules_characteristics import matches
                    hand=tuple(o for o in hand if matches(effect.selector,o,self.effective(o.ref),replace(source,controller=actor)))
                    chooser=actor;amount=min(1,len(hand))
                else:chooser=player;amount=min(effect.amount,len(hand))
                if amount:
                    selected=self._choose(step,chooser,'discard_card','Choose cards to discard.',self._options(hand),amount,amount)
                    events=self._move(tuple(o.ref for o in selected),Zone.GRAVEYARD,frame,step+':move',cause='discard',controller_mode='owner')
                    self._event('cards_discarded',player=player,refs=[e.before.ref.to_json() for e in events])
                plan['index']+=1;plan.pop('revealed',None)
        elif isinstance(effect,MiracleCast):
            self._offer_resolution_cast(frame,task,1000000,Zone.HAND,(source.ref,),miracle_reduction=effect.reduction)
        else:return False
        return True
