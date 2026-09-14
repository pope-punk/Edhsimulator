"""Checkpointed casts during resolution and public discover/cascade exile batches.

The offer grants one exact permission, never priority. Additional costs use the
ordinary quote/payment machinery. Optional authored mana plans run after the
spell is announced and its cost is locked; failed plans leave no accepted prefix.
"""
from copy import deepcopy
from dataclasses import replace
from .rules_state import ObjectRef,RulesObject,Zone,ZoneMove,RulesViolation
from .rules_program import CastDuringResolution,Discover,Cascade,SourceStat,encode
from .rules_choices import ResolutionCastBoundary


class ResolutionCastingRules:
    def _cast_waiting(self):
        window=self.resolution_cast
        return bool(window and not window['completed'] and not window.get('announcing')
            and not self.pending_choice and not self.announcement and self.resolving is not None
            and self.resolving['id']==window['parent']['id'])

    def _casting_mana_waiting(self):
        window=self.resolution_cast
        return bool(window and window.get('announcing') and not self.pending_choice
            and not self.announcement and self.resolving is not None
            and self.resolving['id']==window['parent']['id'])

    def _resolution_cast_candidates(self):
        window=self.resolution_cast
        if window['origin']==Zone.HAND.value:
            objects=self.state.zone(window['actor'],Zone.HAND)
        else:
            objects=[]
            for value in window['refs']:
                try:obj=self.state.get(ObjectRef.from_json(value))
                except RulesViolation:continue
                if obj.zone==Zone.EXILE:objects.append(obj)
        result=[]
        for obj in objects:
            if obj.token or obj.spell_copy or obj.owner!=window['actor'] and not window.get('transformed'):continue
            try:announced=self._announced_face(obj,'back' if window.get('transformed') else 'front',resolution_cast=True)
            except RulesViolation:continue
            program=self.definition(announced)
            from .rules_characteristics import base
            view=base(announced,self.definitions)
            if program.cast is not None and 'Land' not in view.types and view.mana_value<=window['maximum']:result.append(obj.ref)
        return tuple(result)

    def _cast_boundary(self):
        window=self.resolution_cast
        return ResolutionCastBoundary(window['actor'],window['id'],window['maximum'],
            window['origin'],self._resolution_cast_candidates(),self.revision)

    def decline_resolution_cast(self,action_id,actor,request_id,*,revision):
        if (not self._cast_waiting() or actor!=self.resolution_cast['actor']
                or actor not in self.state.live_players or revision!=self.revision
                or request_id!=self.resolution_cast['id']):
            raise RulesViolation('Stale or unauthorized resolution-cast decision')
        if type(action_id) is not str or not action_id or len(action_id)>128 or action_id in self.action_receipts:
            raise RulesViolation('Resolution cast requires a fresh bounded action identity')
        self.resolution_cast['completed']=True
        self.action_receipts[action_id]={'request_id':request_id,'actor':actor,'cast':False}
        self._event('resolution_cast_declined',action_id=action_id,actor=actor,request_id=request_id)
        return self.advance()

    def _offer_resolution_cast(self,frame,task,maximum,origin,refs=(),*,transformed=False):
        window=self.resolution_cast
        if window is None:
            self.resolution_cast={'id':task['id'],'actor':frame['controller'],'maximum':maximum,
                'origin':origin.value,'refs':[ref.to_json() for ref in refs],'transformed':transformed,
                'parent':self.resolving,'completed':False,'cast':False}
            self.priority=None;self.passes=[]
            self._event('resolution_cast_opened',request_id=task['id'],actor=frame['controller'],
                maximum=maximum,origin=origin.value)
            return False
        if window['id']!=task['id']:raise RulesViolation('Resolution-cast parent mismatch')
        if not window['completed']:return False
        task['cast_result']=window['cast'];self.resolution_cast=None
        return True

    def _execute_resolution_cast(self,effect,frame,task):
        if not isinstance(effect,(CastDuringResolution,Discover,Cascade)):return False
        actor=frame['controller'];key=task['id']
        if actor not in self.state.live_players:return True
        if isinstance(effect,CastDuringResolution):
            self._offer_resolution_cast(frame,task,effect.maximum,Zone.HAND)
            return True
        if 'exile_plan' not in task:
            maximum=effect.amount if isinstance(effect,Discover) else self._quantity(SourceStat('mana_value'),frame)-1
            task['exile_plan']={'maximum':maximum,'exiled':[],'scanned':0,'hit':None,'finished':False}
        plan=task['exile_plan']
        while not plan['finished']:
            if 'top' not in plan:
                library=self._library_cards(actor)
                if not library:plan['finished']=True;break
                plan['top']=library[-1].ref.to_json()
            ref=ObjectRef.from_json(plan['top'])
            events=self._move((ref,),Zone.EXILE,frame,key+':exile:'+str(plan['scanned']),controller_mode='owner')
            exiled=[e.after for e in events if e.after.zone==Zone.EXILE]
            if exiled:
                self._event('cards_revealed',player=actor,refs=[obj.ref.to_json() for obj in exiled],
                    names=[self.definition(obj).name for obj in exiled],cause='resolution_exile')
            plan['exiled'].extend(obj.ref.to_json() for obj in exiled)
            plan['scanned']+=1;plan.pop('top')
            for obj in exiled:
                view=self.effective(obj.ref)
                if 'Land' not in view.types and view.mana_value<=plan['maximum']:
                    plan['hit']=obj.ref.to_json();plan['finished']=True
            # A replacement that leaves the top card in place cannot loop.
            if any(obj.ref==ref for obj in self._library_cards(actor)):plan['finished']=True
        if plan['hit'] is not None and 'cast_result' not in task:
            if not self._offer_resolution_cast(frame,task,plan['maximum'],Zone.EXILE,
                    (ObjectRef.from_json(plan['hit']),)):return True
        if isinstance(effect,Discover) and plan['hit'] is not None and not task.get('cast_result') and not plan.get('hand_done'):
            refs=self._current_exiled_refs((plan['hit'],))
            self._move(refs,Zone.HAND,frame,key+':hand',controller_mode='owner')
            plan['hand_done']=True
        if not plan.get('bottom_done'):
            refs=self._current_exiled_refs(plan['exiled'])
            events=self._move(refs,Zone.LIBRARY,frame,key+':bottom',controller_mode='owner',defer_library_tops=True)
            arrivals=tuple(e.after.ref for e in events if e.after.zone==Zone.LIBRARY and e.after.owner==actor)
            self.state.random_bottom(actor,arrivals)
            self._sync_library_tops()
            plan['bottom_done']=True
            self._event('discovered' if isinstance(effect,Discover) else 'cascade_finished',
                player=actor,maximum=plan['maximum'],exiled_count=len(plan['exiled']),cast=bool(task.get('cast_result')))
        return True

    def _commit_cast_mana_plan(self,quote,payment):
        """Validate an authored, finite announcement payment on an isolated state.

        Commands may activate mana abilities and answer their own choices only.
        There is no priority, automatic target selection or hidden-library read.
        The spell and its total cost are fixed before any mana ability executes.
        """
        import hashlib
        from .rules_casting import Payment
        from .rules_adapter import RulesActorAdapter
        if not self._cast_waiting() or quote.kind!='cast':
            raise RulesViolation('Authored announcement mana is currently limited to resolution casts')
        if not isinstance(payment.mana_actions,tuple) or len(payment.mana_actions)>128:
            raise RulesViolation('Invalid bounded announcement mana plan')
        trial=type(self).restore(self.snapshot(),self._base_definitions.values())
        source=trial.state.get(quote.source)
        trial._zone_cost_refs(quote,replace(payment,mana_actions=()))
        stack_source=trial.state.move((ZoneMove(source.ref,Zone.STACK,quote.actor,cast_x=quote.x_value,back_face=quote.face=='back'),),'spell_announced')[0].after
        frame=trial._spell_frame(stack_source,quote);trial.stack.append(frame)
        trial.resolution_cast['announcing']=True
        trial._event('spell_announced',action_id=quote.action_id,actor=quote.actor)
        adapter=RulesActorAdapter(trial)
        for index,command in enumerate(payment.mana_actions):
            if type(command) is not dict or command.get('kind') not in {'activate','answer','allocate_counters'}:
                raise RulesViolation('Mana plans contain only authored mana activations and their choices')
            if command['kind']=='activate' and command.get('payment',{}).get('mana_actions'):
                raise RulesViolation('Nested announcement mana plans are unavailable')
            command=deepcopy(command)
            if 'revision' in command:raise RulesViolation('Mana-plan revisions are bound by their enclosing action')
            command['revision']=trial.revision
            if command['kind']=='activate':command['action_id']='cast-mana:'+hashlib.sha256(quote.action_id.encode()).hexdigest()+':'+str(index)
            if command['kind'] in {'answer','allocate_counters'}:
                request=trial.pending_choice
                if request is None or request.actor!=quote.actor:raise RulesViolation('Mana plan has no owned choice')
                command['request_id']=request.request_id
            adapter._execute(quote.actor,command)
        if not trial._casting_mana_waiting():raise RulesViolation('Mana plan must finish every immediate ability and choice')
        final_payment=replace(payment,mana_actions=())
        # Recheck paid objects after producing mana, keeping the locked total.
        refs=trial._zone_cost_refs(replace(quote,source=stack_source.ref),final_payment)
        resources=trial._resource_payment(quote,final_payment,source=stack_source)
        trial.resolution_cast.pop('announcing')
        if quote.cost.zone_costs:
            trial.announcement={'frame_id':frame['id'],'quote':quote.to_json(),'payment':final_payment.to_json(),
                'source':stack_source.to_json(),'origin_source':source.to_json(),
                'source_types':sorted(trial.effective(stack_source.ref).types),'ability':None,
                'refs':[ref.to_json() for ref in refs]}
        else:
            observers=trial._tap_observers(resources.taps)
            trial.state.move((),'cast_payment',payment=resources)
            trial._commit_prepared(quote,resources,paid=True,source=source,prepared_frame=frame,convoke=payment.convoke)
            trial._collect_tapped(resources.taps,observers)
        # Commit the prepared prefix while preserving callers' state identity.
        state=self.state;state.__dict__.update(trial.state.__dict__)
        self.__dict__.update(trial.__dict__);self.state=state
        return self.advance()
