"""Loyalty costs, Class designations, reflexive triggers and opening actions.

All pilot selections use the kernel's ordinary actor-bound choices. Opening
actions accept finalized post-mulligan hands; they never replace an active game.
"""
from copy import deepcopy
from dataclasses import replace
from .rules_state import ObjectRef,PlayerRef,RulesObject,ResourcePayment,Zone,RulesViolation,target_from_json
from .rules_choices import Option
from .rules_casting import Payment,PreparedAction
from .rules_program import (LoyaltyCost,SetClassLevel,RotateControl,PutEligibleTop,
    SacrificeThenTrigger,WardPayment,CounterBoundStack,OpeningHandPermissions,
    AbilityProgram,EventPattern,PayMana,Counter,encode,decode)


class WalkerRules:
    def loyalty_used(self,ref):
        return self.loyalty_uses.get(self._attachment_key(ref))==self.state.turn_number

    def _commit_loyalty_action(self,quote,payment):
        if quote.kind!='activate' or payment!=Payment():
            raise RulesViolation('A loyalty symbol accepts no additional payment packet')
        source=self.state.get(quote.source)
        ability=next(a for a in self.activated_abilities(source) if a.ability_id==quote.ability_id)
        frame=self._frame(source,quote.actor,ability.effects,targets=quote.targets,
            target_spec=ability.targets,chosen_x=quote.x_value)
        frame.update(ability_id=ability.ability_id,activated_program=encode(ability))
        self._bind_announced_values(frame,quote);self.stack.append(frame)
        self.announcement={'loyalty':True,'frame_id':frame['id'],'quote':quote.to_json(),
            'payment':payment.to_json(),'source':source.to_json(),'ability':encode(ability),'refs':[]}
        self._event('activation_announced',action_id=quote.action_id,actor=quote.actor)
        return self.advance()

    def _continue_loyalty_announcement(self):
        pending=self.announcement;quote=PreparedAction.from_json(pending['quote'])
        source=self.state.get(quote.source);delta=quote.cost.loyalty
        frame=next(f for f in self.stack if f['id']==pending['frame_id'])
        # Replacement ordering is pure until all affected-player choices finish.
        final,trace=self._plan_counter_placements(((source.ref,'loyalty',max(0,delta)),),frame,quote.action_id)
        removals=((source.ref,(('loyalty',-delta),)),) if delta<0 else ()
        self._commit_counters(final,trace,frame,removals)
        self.loyalty_uses[self._attachment_key(source.ref)]=self.state.turn_number
        self.announcement=None
        self._commit_prepared(quote,ResourcePayment(quote.actor),paid=True,
            source=self.state.get(source.ref),ability=decode(pending['ability']),prepared_frame=frame)
        self.action_receipts[quote.action_id]['payment']['loyalty']=delta
        self._event('loyalty_cost_paid',source=source.ref.to_json(),delta=delta,actor=quote.actor)

    def _collect_ward(self,frame):
        """Each newly acquired target triggers every current instance of ward."""
        seen=frame.setdefault('ward_targets',[])
        for value in frame['targets']:
            if value in seen:continue
            seen.append(deepcopy(value));ref=target_from_json(value)
            if isinstance(ref,PlayerRef):continue
            try:obj=self.state.get(ref)
            except RulesViolation:continue
            if obj.zone!=Zone.BATTLEFIELD or obj.phased or obj.controller==frame['controller']:continue
            for index,(_,_,mana) in enumerate(self.effective(ref).wards):
                ability=AbilityProgram('ward:'+str(index),EventPattern('step_began',step='upkeep'),
                    (WardPayment(mana),))
                self._trigger(obj,ability,values={'ward_frame':frame['id'],'event_controllers':[frame['controller']]})

    def _execute_walker_instruction(self,effect,frame,task):
        key=task['id'];actor=frame['controller'];source=self._source(frame)
        if isinstance(effect,SetClassLevel):
            try:current=self.state.get(source.ref)
            except RulesViolation:return True
            if current.zone==Zone.BATTLEFIELD and not current.phased:
                self.state.set_class_level(current.ref,effect.level)
                self._event('class_level_changed',source=current.ref.to_json(),level=effect.level)
        elif isinstance(effect,RotateControl):
            direction=self._choose(key+':direction',actor,'control_direction','Choose left or right.',
                (Option('left','Left'),Option('right','Right')),1,1)[0].key
            players=self.state.live_players;offset=1 if direction=='left' else -1
            # Seating order runs to the left. Freeze every assignment before mutation.
            recipients={players[(i+offset)%len(players)]:p for i,p in enumerate(players)}
            assignments=tuple((obj.ref,recipients[obj.controller]) for obj in self._query(effect.selector,frame))
            keys=self.state.change_control_map(assignments)
            self._event('control_rotated',direction=direction,effects=list(keys),
                assignments=[{'ref':ref.to_json(),'controller':p} for ref,p in assignments])
        elif isinstance(effect,PutEligibleTop):
            if actor not in self.state.live_players:return True
            if 'top_offer' not in task:
                library=self._library_cards(actor);top=library[-1] if library else None
                task['top_offer']={'ref':top.ref.to_json() if top else None,'eligible':False}
                if top:
                    view=self.effective(top.ref);limit=self._quantity(effect.maximum,frame)
                    task['top_offer']['eligible']='Land' in view.types or 'Creature' in view.types and view.mana_value<=limit
                    observation={'id':key,'kind':'look_top','library_owner':actor,'reveal':False,
                        'observed_revision':self.revision,'cards':[{'ref':top.ref.to_json(),'name':self.definition(top).name}]}
                    self.library_observations[actor]=deepcopy(observation)
                    self._event('library_cards_looked',player=actor,observation=deepcopy(observation))
            offer=task['top_offer']
            if offer['ref'] is None:return True
            options=(Option('leave','Leave it on top'),)
            if offer['eligible']:options=(Option('put','Put it onto the battlefield'),)+options
            selected=self._choose(key+':top',actor,'top_entry','Choose whether to put the looked-at card onto the battlefield.',options,1,1)
            if selected[0].key=='put':
                self._move((ObjectRef.from_json(offer['ref']),),Zone.BATTLEFIELD,frame,key+':entry')
        elif isinstance(effect,SacrificeThenTrigger):
            if 'sacrifice_offer' not in task:
                options=self._options(self._query(effect.selector,frame))
                selected=options if len(options)<=1 else self._choose(key+':sacrifice',actor,'reflexive_sacrifice',
                    'Choose a permanent to sacrifice.',options,1,1)
                if not selected:return True
                obj=self.state.get(selected[0].ref);view=self.effective(obj.ref)
                task['sacrifice_offer']={'ref':obj.ref.to_json(),
                    'stats':{name:getattr(view,name) or 0 for name in ('power','toughness','mana_value')},
                    'subtypes':sorted(view.subtypes)}
            chosen=task['sacrifice_offer']
            events=self._move((ObjectRef.from_json(chosen['ref']),),Zone.GRAVEYARD,frame,key+':sacrifice',cause='sacrifice',controller_mode='owner')
            if events:
                ability=AbilityProgram('reflexive:'+key,EventPattern('step_began',step='upkeep'),effect.effects,targets=effect.targets)
                self._trigger(replace(source,controller=actor),ability,values={
                    'paid_cost_stats':{'sacrifice':chosen['stats']},
                    'paid_cost_subtypes':{'sacrifice':chosen['subtypes']}})
        elif isinstance(effect,WardPayment):
            # The targeted spell/ability's controller pays, regardless of later control.
            self._insert(frame,(PayMana(effect.mana,(),otherwise=(CounterBoundStack(),),players='event_controllers'),))
        elif isinstance(effect,CounterBoundStack):
            bound=next((f for f in self.stack if f['id']==frame['values']['ward_frame']),None)
            if bound is not None:
                if bound['spell']:
                    context={**frame,'targets':[self._source(bound).ref.to_json()]}
                    self._zone_operation(Counter('target'),context,key+':counter')
                else:
                    self.stack.remove(bound)
                    self._event('ability_countered',frame=bound['id'],cause='ward')
        else:return False
        return True

    def begin_opening_hand_actions(self,starting_player):
        """Bootstrap boundary after every player has completed mulligans."""
        self._idle()
        if (self.state.turn_number or self.phase is not None or self.turn_schedule is not None
                or self.stack or self.opening_actions is not None or self.mulligans is not None or starting_player not in self.state.live_players):
            raise RulesViolation('Opening actions require an unstarted post-mulligan game')
        self._start_opening_actions(starting_player)
        return self.advance()

    def _start_opening_actions(self,starting_player):
        self.active=starting_player;self.priority=None
        index=self.state.players.index(starting_player)
        players=self.state.players[index:]+self.state.players[:index]
        self.opening_actions={'id':self._id('opening'),'players':list(players),'index':0}
        self._event('opening_actions_began',starting_player=starting_player)

    def _continue_opening_actions(self):
        window=self.opening_actions
        while window['index']<len(window['players']):
            actor=window['players'][window['index']]
            if actor not in self.state.live_players:window['index']+=1;continue
            if 'chosen' not in window:
                options=self._options(tuple(obj for obj in self.state.zone(actor,Zone.HAND)
                    if isinstance((rule:=self.definition(obj).player_permissions),OpeningHandPermissions)
                    and rule.battlefield_from_opening_hand))
                selected=self._choose(window['id']+':'+actor,actor,'opening_hand',
                    'Choose opening-hand permanents to begin on the battlefield, in order.',
                    options,0,len(options),ordered=True) if options else ()
                window['chosen']=[o.ref.to_json() for o in selected];window['cursor']=0
            while window['cursor']<len(window['chosen']):
                ref=ObjectRef.from_json(window['chosen'][window['cursor']]);obj=self.state.get(ref)
                frame={'source':obj.to_json(),'controller':actor,'bindings':{},'values':{},'chosen_x':0}
                self._move((ref,),Zone.BATTLEFIELD,frame,window['id']+':entry:'+actor+':'+str(window['cursor']))
                window['cursor']+=1
            window.pop('chosen');window.pop('cursor');window['index']+=1
        self.opening_actions=None
        self._event('opening_actions_completed')
        self.turn_schedule={'land_plays':0,'advance':False,'cleanup_priority':False}
        self._start_turn(self.active)
