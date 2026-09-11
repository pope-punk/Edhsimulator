"""Experimental deterministic interpreter; explicitly isolated from live hosts.

The supported vertical slice covers identity, entry copies, event subscriptions,
trigger ordering, priority, destination replacement and bounded pilot choices.
Unsupported semantics stop rather than being approximated. This is not yet a
replacement for ManualGame's four-deck implementation.
"""
from __future__ import annotations
import hashlib,json
from collections import Counter as Counts, OrderedDict
from dataclasses import replace
from types import MappingProxyType
from .rules_state import RulesState,RulesObject,ObjectRef,Zone,ZoneMove,RulesViolation
from .rules_characteristics import Characteristics, evaluate as evaluate_characteristics, base as base_characteristics, matches as matches_selector, condition_holds, characteristics_match, counters_match
from .rules_identity import IMPLEMENTATION_ID
from .rules_choices import Option, ChoiceRequest, PriorityBoundary, choice_capacity
from .rules_attachments import AttachmentRules
from .rules_casting import CastingRules
from .rules_turns import TurnRules, TurnActionBoundary
from .rules_combat import CombatRules
from .rules_departure import DepartureRules,GameResult
from .rules_library import LibraryRules
from .rules_counters import CounterRules, transformed, actor_matches
from .rules_replacements import ZoneProposal, ReplacementCandidate, affected_player, candidates, apply_replacement
from .rules_program import (event_player_matches,SourceCounter,TargetStat,SelectedCount,RecipientStat,UntilEndOfTurn,AddKeywords,ModifyPT,SetPT,ContinuousProgram,SourceStat,BattlefieldStat,EventX,DividedValue,MovedCount,SetTapped,WithZoneResult,WithControllers,CreateTokens,token_programs,MultiplyCounters,LifeLost,EventAmount,WithLifeLost,LoseLife,GrantPermissions,ChosenX,CountObjects,ScaledValue,ProduceMana,CardProgram,AbilityProgram,Selector,TargetSpec,IfCondition,AddMana,ChooseMana,ChooseCommanderMana,Move,Sacrifice,Destroy,Discard,Counter,CounterAbilities,Damage,GainControl,ChooseFromTop,SearchLibrary,Surveil,LookTop,Scry,Draw,Mill,GainLife,May,UnlessEntered,Proliferate,AddCounters,Select,SelectAll,WithMoved,validate,encode,decode)


class UnsupportedRule(RulesViolation):pass


def fingerprint(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class _NeedsChoice(Exception):pass


from .rules_state import PlayerRef,target_from_json


class RulesKernel(CounterRules,LibraryRules,DepartureRules,CombatRules,TurnRules,CastingRules,AttachmentRules):
    CHECKPOINT_SCHEMA=108
    @classmethod
    def for_production(cls, *args, **kwargs):
        # Only scenario construction is available until the complete production
        # contract and reviewed card bundle exist. Do not infer readiness from
        # an individual CardProgram being syntactically valid.
        from .rules_admission import require_production_ready
        require_production_ready()

    def __init__(self,state:RulesState,definitions,active_player=None):
        self.state=state;programs=tuple(definitions)
        self.definitions={p.definition_id:validate(p) for p in programs}
        if len(self.definitions)!=len(programs):raise RulesViolation('Duplicate program definition')
        pending=list(programs)
        while pending:
            for token in token_programs(pending.pop()):
                previous=self.definitions.get(token.definition_id)
                if previous is not None:
                    if previous!=token:raise RulesViolation('Conflicting embedded token definition')
                else:self.definitions[token.definition_id]=token;pending.append(token)
        programs=tuple(self.definitions.values())
        index={}
        for program in programs:
            grouped={}
            for ability in program.abilities:grouped.setdefault(ability.event.kind,[]).append(ability)
            index[program.definition_id]=MappingProxyType({kind:tuple(rows) for kind,rows in grouped.items()})
        self._trigger_index=MappingProxyType(index)
        self._has_attachment_observers=any(a.event.subject=='attached' for p in programs for a in p.abilities)
        self._has_tap_triggers=any(a.event.kind=='becomes_tapped' for p in programs for a in p.abilities)
        self.definitions=MappingProxyType(self.definitions)
        self.bundle=fingerprint([encode(p) for p in sorted(programs,key=lambda p:p.definition_id)])
        self.active=active_player or state.players[0]
        if self.active not in state.players:raise RulesViolation('Unknown active player')
        for obj in state.objects():self.definition(obj)
        self.stack=[];self.resolving=None;self.pending_triggers=[];self.placement=None
        self.pending_choice=None;self.answers={};self.accepted=[];self.semantic_events=[]
        self.priority=None;self.passes=[];self._serial=0;self._revision=0
        self.temporary_effects=[];self.library_observations={};self.last_known={};self.attachment_rules={};self.delayed_triggers=[];self.player_effects=[];self.trigger_limits={};self.trigger_limit_turn=state.turn_number
        self.phase=None;self.action_receipts={};self.turn_schedule=None;self.combat=None;self.departure=None;self.outcome=None;self.announcement=None

    @property
    def revision(self):return f'{self.state.sequence}:{self._revision}'

    def definition(self,obj):
        try:return self.definitions[obj.effective_definition]
        except KeyError as exc:raise UnsupportedRule('No supported program for '+obj.effective_definition) from exc

    def _trigger_abilities(self,source,kind):
        return self._trigger_index[self.definition(source).definition_id].get(kind,())

    def _id(self,prefix):self._serial+=1;return f'{prefix}-{self._serial}'

    def _event(self,kind,**data):
        self._revision+=1;self.semantic_events.append({'index':len(self.semantic_events)+1,'kind':kind,**data})

    def _life_gain_amount(self,player,amount):
        if type(amount) is not int or amount<0:raise RulesViolation('Invalid life gain')
        if not amount or player not in self.state.live_players:return 0
        cached=getattr(self,'_life_gain_bonus_cache',None)
        if cached is None or cached[0]!=self.state.sequence:
            bonuses={p:0 for p in self.state.live_players}
            for source in self.state.objects(Zone.BATTLEFIELD):
                if source.phased:continue
                for rule in self.definition(source).life_gain_replacements:
                    for recipient in bonuses:
                        if rule.players=='all' or (recipient==source.controller)==(rule.players=='controller'):
                            bonuses[recipient]+=rule.additional
            cached=(self.state.sequence,bonuses);self._life_gain_bonus_cache=cached
        return amount+cached[1][player]

    def _player_event(self,kind,player,**data):
        self._event(kind,player=player,**data)
        for source in self.state.objects(Zone.BATTLEFIELD):
            if source.phased:continue
            for ability in self._trigger_abilities(source,kind):
                pattern=ability.event
                if pattern.kind==kind and event_player_matches(pattern,source.controller,player):
                    captured={'event_controllers':[player]}
                    if kind=='life_gained':captured['event_amount']=data['amount']
                    self._trigger(source,ability,values=captured)

    def _frame(self,source,controller,effects,*,spell=False,targets=(),target_spec=None,entry_flags=(),chosen_x=0):
        return {'id':self._id('frame'),'source':source.to_json(),'controller':controller,'spell':spell,
                'targets':[ref.to_json() for ref in targets],'target_spec':encode(target_spec),
                'bindings':{},'values':{},'entry_flags':list(entry_flags),'started':False,'chosen_x':chosen_x,
                'tasks':[{'id':self._id('effect'),'effect':encode(effect)} for effect in effects]}

    def _idle(self):
        if self.outcome:raise RulesViolation('Game has finished')
        if self.pending_choice or self.resolving or self.pending_triggers or self.announcement:raise RulesViolation('Resolve the current rules boundary first')

    def _source(self,frame):return RulesObject.from_json(frame['source'])

    def _object_information(self,source):
        try:
            current=self.state.get(source.ref)
            return current,self.effective(current.ref)
        except RulesViolation:
            if source.ref in self.last_known:return self.last_known[source.ref]
            # Direct state mutations exist only in scenario harnesses. Production
            # zone movement records the derived view in _collect before triggers.
            previous=next((event.before for event in reversed(self.state.events) if event.before.ref==source.ref),source)
            return previous,base_characteristics(previous,self.definitions)

    def _temporary_rows(self):
        return tuple((RulesObject.from_json(row['source']),decode(row['effect']),tuple(ObjectRef.from_json(ref) for ref in row['refs'])) for row in self.temporary_effects)

    def characteristics(self):
        # A mutation invalidates the single bounded cache. Historical event
        # views are passed explicitly and never retrieved through this cache.
        cached = getattr(self, '_characteristics_cache', None)
        if cached is None or cached[0] != self.state.sequence:
            cached = (self.state.sequence, evaluate_characteristics(self.state.objects(), self.definitions,temporary=self._temporary_rows(),life_totals={p:self.state.life(p) for p in self.state.players},starting_life_totals={p:self.state.starting_life(p) for p in self.state.players},live_players=self.state.live_players))
            self._characteristics_cache = cached
        return cached[1]

    def effective(self, ref):
        self.state.get(ref)
        return self.characteristics()[ref]

    def _query(self,selector,frame):
        if selector.zone==Zone.LIBRARY:raise UnsupportedRule('Library search needs its own visibility and failure-to-find protocol')
        if selector.characteristics and any(bound is not None and type(bound) is not int
                for item in selector.characteristics for bound in (item.minimum,item.maximum)):
            ranges=[]
            for bound in selector.characteristics:
                minimum=bound.minimum if bound.minimum is None or type(bound.minimum) is int else self._quantity(bound.minimum,frame)
                maximum=(minimum if bound.maximum==bound.minimum else bound.maximum
                         if bound.maximum is None or type(bound.maximum) is int else self._quantity(bound.maximum,frame))
                ranges.append(replace(bound,minimum=minimum,maximum=maximum))
            selector=replace(selector,characteristics=tuple(ranges))
        source=replace(self._source(frame),controller=frame['controller'])
        successor=frame.get('values',{}).get('source_successor') if selector.exclude_source else None
        excluded=ObjectRef.from_json(successor) if successor is not None else None
        views=self.characteristics()
        return tuple(obj for obj in self.state.objects(selector.zone)
                     if obj.ref!=excluded and matches_selector(selector,obj,views[obj.ref],source))

    def _players(self,frame,which):
        controller=frame['controller']
        targets={target_from_json(row).player for row in frame.get('targets',[]) if 'player' in row}
        if which=='controller':selected={controller}
        elif which=='opponents':selected=set(self.state.live_players)-{controller}
        elif which=='all':selected=set(self.state.live_players)
        elif which=='target':selected=targets
        elif which=='controller_and_target':selected=targets|{controller}
        elif which=='event_controllers':selected=set(frame['values']['event_controllers'])
        elif which=='defending_player':selected={frame['values']['defending_player']}
        else:raise UnsupportedRule('Unsupported player recipients')
        order=self.state.players;start=order.index(self.active);order=order[start:]+order[:start]
        return tuple(p for p in order if p in selected and p in self.state.live_players)

    def _target_options(self,spec,frame):
        if spec.groups:
            return tuple(replace(option,key=json.dumps([group.group_id,option.key],separators=(',',':')),
                label=group.group_id+': '+option.label,group=group.group_id)
                for group in spec.groups for option in self._target_options(group.targets,frame))
        candidates=self._target_query(spec.selector,frame) if spec.selector is not None else ()
        if spec.combat is not None:
            combat_refs=self._combat_target_refs(spec.combat)
            candidates=tuple(obj for obj in candidates if obj.ref in combat_refs)
        objects=self._options(candidates)
        players=tuple(Option('player:'+p,p+' (player)',player=p,group=p) for p in self._players(frame,spec.players)) if spec.players else ()
        return objects+players

    def _target_query(self,selector,frame):
        # These permissions constrain targeting, not nontargeted selection.
        permitted=[];source_types=None
        for obj in self._query(selector,frame):
            view=self.effective(obj.ref)
            if 'shroud' in view.keywords or 'hexproof' in view.keywords and obj.controller!=frame['controller']:continue
            restricted=False
            for rule in view.target_restrictions:
                if rule.opponents_only and obj.controller==frame['controller']:continue
                if rule.source_types:
                    if source_types is None:source_types=self._object_information(self._source(frame))[1].types
                    if not source_types.intersection(rule.source_types):continue
                restricted=True;break
            if restricted:continue
            permitted.append(obj)
        return tuple(permitted)

    def _options(self,objects):
        return tuple(Option(f'{obj.ref.card_id}@{obj.ref.incarnation}',f'{obj.controller}: {self.definition(obj).name} [{obj.ref.card_id}@{obj.ref.incarnation}]',ref=obj.ref,group=obj.controller) for obj in objects)

    def _choose(self,key,actor,kind,prompt,options,minimum=0,maximum=None,ordered=False,groups=False,group_bounds=()):
        options=tuple(options);capacity=choice_capacity(options,groups,group_bounds)
        maximum=capacity if maximum is None else min(maximum,capacity)
        if minimum>maximum:raise RulesViolation('Required choice has insufficient legal options')
        if not options and not group_bounds:return ()
        if actor not in self.state.live_players:actor=self.next_live_player(actor)
        request=ChoiceRequest(key,actor,kind,prompt,options,minimum,maximum,ordered,groups,self.revision,group_bounds)
        if not options:return ()
        accepted=self.answers.get(key)
        if accepted is not None:
            # Each execution frame retains exactly the request which was answered.
            if accepted['request']!=request.to_json():raise RulesViolation('Accepted choice no longer matches its bound request')
            return tuple(options[i] for i in accepted['indexes'])
        self.pending_choice=request;raise _NeedsChoice()

    def answer(self,request_id,actor,indexes):
        request=self.pending_choice
        if request is None or request.request_id!=request_id:raise RulesViolation('No matching unanswered request')
        if request.revision!=self.revision:raise RulesViolation('State changed after the request was issued')
        indexes=request.validate(actor,indexes)
        self.answers[request_id]={'request':request.to_json(),'indexes':list(indexes)}
        self.accepted.append({'request_id':request_id,'actor':actor,'indexes':list(indexes)})
        self.pending_choice=None
        mana_actor=self.resolving.get('return_priority') if self.resolving and self.resolving.get('mana_ability') else None
        if self.announcement and decode(self.announcement['ability']).mana_ability:mana_actor=self.announcement['quote']['actor']
        boundary=self.advance()
        if boundary is None and mana_actor in self.state.live_players:self.priority=mana_actor
        return boundary

    def enter(self,ref,controller=None,*,entry_flags=()):
        """Scenario entry API; no production pilot action is exposed here."""
        self._idle()
        if self.stack:raise RulesViolation('Cannot inject a scenario entry into a live stack')
        obj=self.state.get(ref);self.resolving=self._frame(obj,controller or obj.owner,(Move('source',Zone.BATTLEFIELD),),entry_flags=entry_flags)
        return self.advance()

    def execute_for_scenario(self,source,controller,effects,bindings=None):
        self._idle()
        if self.stack:raise RulesViolation('Scenario effects require an empty stack')
        # Validate effects using the same closed program compiler.
        validate(CardProgram('scenario','Scenario',(),spell_effects=tuple(effects)))
        self.resolving=self._frame(self.state.get(source),controller,effects)
        self.resolving['bindings']={k:[ref.to_json() for ref in refs] for k,refs in (bindings or {}).items()}
        return self.advance()

    def stage_spell_for_scenario(self,ref,controller,targets=(),*,entry_flags=()):
        """Test harness only: stage an already-paid spell, never infer mana payment."""
        self._idle()
        if self.priority is not None and self.priority!=controller:raise RulesViolation('Caster does not have priority')
        obj=self.state.get(ref);program=self.definition(obj)
        if program.modal is not None:raise UnsupportedRule('Modal fixture spells require a fully prepared cast')
        if obj.zone not in {Zone.HAND,Zone.COMMAND} or obj.owner!=controller:raise RulesViolation('Invalid spell origin')
        self._announcement_targets(obj,controller,program.spell_targets,targets)
        events=self.state.move((ZoneMove(ref,Zone.STACK,controller),),'cast')
        if obj.commander and obj.zone==Zone.COMMAND:self.state.record_command_cast(controller,obj.ref.card_id)
        source=events[0].after;effects=program.spell_effects
        if not effects and not {'Instant','Sorcery'}&set(program.types):effects=(Move('source',Zone.BATTLEFIELD),)
        self.stack.append(self._frame(source,controller,effects,spell=True,targets=targets,target_spec=program.spell_targets,entry_flags=entry_flags))
        self._event('spell_cast',source=source.ref.to_json(),controller=controller)
        self.priority=controller;self.passes=[]
        self._collect_announcement('spell_cast',source,controller)
        return self.advance()

    def _matches(self,pattern,source,*,event=None,step=None,views=None):
        if step is not None:
            return pattern.kind=='step_began' and pattern.step==step and (not pattern.controller_only or source.controller==self.active)
        if pattern.kind!='zone_changed':return False
        if event.cause=='owner_left_game' and (pattern.from_zone!=Zone.BATTLEFIELD or pattern.to_zone is not None):return False
        if pattern.from_zone==Zone.BATTLEFIELD and event.before.phased:return False
        if pattern.from_zone is not None and pattern.from_zone!=event.before.zone:return False
        if pattern.to_zone is not None and pattern.to_zone!=event.after.zone:return False
        subject=event.before if pattern.from_zone==Zone.BATTLEFIELD else event.after
        if pattern.subject=='self' and source.ref!=subject.ref:return False
        if pattern.subject=='attached' and source.attached_to!=subject.ref:return False
        if pattern.exclude_source and source.ref==subject.ref:return False
        if not counters_match(pattern.counters,subject):return False
        if (pattern.controller_only or pattern.recipient_relation!='any') and subject.zone not in {Zone.BATTLEFIELD,Zone.STACK}:return False
        if pattern.controller_only and source.controller!=subject.controller:return False
        if pattern.recipient_relation=='controlled' and source.controller!=subject.controller:return False
        if pattern.recipient_relation=='opponent_controlled' and source.controller==subject.controller:return False
        view=views.get(subject.ref) if views is not None else None
        if view is None:view=base_characteristics(subject,self.definitions)
        return (set(pattern.types)<=view.types and (not pattern.any_types or bool(set(pattern.any_types)&view.types))
                and characteristics_match(pattern.characteristics,view))

    def _tap_observers(self,refs):
        # Avoid a battlefield snapshot for bundles without orientation triggers.
        return self.state.objects(Zone.BATTLEFIELD) if refs and self._has_tap_triggers else ()

    def _collect_tapped(self,refs,before):
        if not refs or not before or not self._has_tap_triggers:return
        refs=set(refs)
        # Resource payments may tap and then sacrifice the same permanent.
        # Observe the tap before its departure, including copied abilities.
        objects=tuple(replace(obj,tapped=True) if obj.ref in refs else obj for obj in before)
        subjects=tuple(obj for obj in objects if obj.ref in refs and not obj.phased)
        views=None
        for source in objects:
            if source.phased:continue
            for ability in self._trigger_abilities(source,'becomes_tapped'):
                pattern=ability.event
                if pattern.kind!='becomes_tapped':continue
                for subject in subjects:
                    if pattern.subject=='self' and source.ref!=subject.ref:continue
                    if pattern.controller_only and source.controller!=subject.controller:continue
                    if views is None and (pattern.types or ability.occurrence_condition or ability.intervening_if):
                        views=evaluate_characteristics(objects,self.definitions,temporary=self._temporary_rows(),
                            life_totals={p:self.state.life(p) for p in self.state.players},
                            starting_life_totals={p:self.state.starting_life(p) for p in self.state.players},live_players=self.state.live_players)
                    if pattern.types and not set(pattern.types)<=views[subject.ref].types:continue
                    self._trigger(source,ability,bindings={'event_subject':[subject.ref.to_json()]},
                        condition_objects=objects,condition_views=views)

    def _collect(self,events,before,after,before_views=None,before_life_totals=None,before_live_players=None):
        before_views=before_views if before_views is not None else evaluate_characteristics(before,self.definitions,temporary=self._temporary_rows(),life_totals=before_life_totals if before_life_totals is not None else {p:self.state.life(p) for p in self.state.players},starting_life_totals={p:self.state.starting_life(p) for p in self.state.players},live_players=before_live_players if before_live_players is not None else self.state.live_players)
        after_views=self.characteristics()
        # Retain public-zone information before collecting any triggers.
        # Battlefield views include simultaneous departing effects; stack views
        # include announced X. Hidden zones do not become inspection baselines.
        for event in events:
            if event.before.zone in {Zone.BATTLEFIELD,Zone.STACK,Zone.GRAVEYARD,Zone.EXILE,Zone.COMMAND}:
                view=before_views.get(event.before.ref)
                if view is None:view=base_characteristics(event.before,self.definitions)
                self.last_known[event.before.ref]=(event.before,view)
        grave_successors={e.before.ref:e.after.ref for e in events
            if e.before.zone==Zone.BATTLEFIELD and e.after.zone==Zone.GRAVEYARD} if self._has_attachment_observers else {}
        # CR 400.7f: only the same batch or the unattached-Aura SBA may
        # bridge this identity boundary. Later destruction cannot qualify.
        aura_sbas={e.before.ref:e for e in events if e.cause=='permanent_sba'
            and e.before.ref in grave_successors} if grave_successors and self.pending_triggers else {}
        if aura_sbas:
            for trigger in self.pending_triggers:
                tracked=trigger.get('values',{}).get('aura_tracking')
                if not tracked:continue
                event=aura_sbas.get(ObjectRef.from_json(tracked['source']))
                if event is not None and event.before.attached_to==ObjectRef.from_json(tracked['attached']):
                    try:self.state.get(event.before.attached_to)
                    except RulesViolation:
                        trigger['bindings']['aura_successor']=[event.after.ref.to_json()]
                        trigger['values'].pop('aura_tracking',None)
        for event in events:
            # Leaves/dies observations use the whole pre-event battlefield;
            # entrants and ordinary ETB observers use the whole post-event view.
            for sources,lookback in ((before,True),(after,False)):
                for source in sources:
                    if source.phased:continue
                    for ability in self._trigger_abilities(source,'zone_changed'):
                        if (ability.event.from_zone==Zone.BATTLEFIELD)!=lookback:continue
                        if self._matches(ability.event,source,event=event,views=before_views if lookback else after_views):
                            subject=event.before if lookback else event.after
                            values={'event_controllers':[subject.controller] if subject.zone in {Zone.BATTLEFIELD,Zone.STACK} else []}
                            if event.after.zone==Zone.BATTLEFIELD:values['event_x']=event.before.cast_x if event.before.zone==Zone.STACK else 0
                            if source.ref==event.before.ref and event.after.zone in {Zone.BATTLEFIELD,Zone.STACK,Zone.GRAVEYARD,Zone.EXILE,Zone.COMMAND}:
                                values['source_successor']=event.after.ref.to_json()
                            bindings={'event_subject':[subject.ref.to_json()]}
                            if 'source_successor' in values:bindings['source_successor']=[values['source_successor']]
                            if ability.event.subject=='attached' and self.definition(source).enchant is not None:
                                successor=grave_successors.get(source.ref)
                                bindings['aura_successor']=[successor.to_json()] if successor else []
                                if successor is None:
                                    values['aura_tracking']={'source':source.ref.to_json(),'attached':subject.ref.to_json()}
                            self._trigger(source,ability,bindings=bindings,
                                values=values,
                                condition_objects=sources,condition_views=before_views if lookback else after_views,condition_life_totals=before_life_totals if lookback else None,condition_live_players=before_live_players if lookback else None)

        self._collect_delayed(events)

    def _source_condition(self,source,zone):
        if zone is None:return True
        try:
            current=self.state.get(source.ref)
            return current.zone==zone and not current.phased
        except RulesViolation:return False

    def _condition_holds(self,condition,source,objects=None,views=None,life_totals=None,live_players=None):
        if condition is None:return True
        return condition_holds(condition,source,
            self.state.objects(Zone.BATTLEFIELD) if objects is None else objects,
            self.characteristics() if views is None else views,life_totals=life_totals if life_totals is not None else {p:self.state.life(p) for p in self.state.players},starting_life_totals={p:self.state.starting_life(p) for p in self.state.players},live_players=live_players if live_players is not None else self.state.live_players)

    def _trigger_limit_key(self,source,ability):
        return json.dumps([source.ref.to_json(),source.effective_definition,ability.ability_id],sort_keys=True)

    def _optional_limit_key(self,source,ability):
        return json.dumps(['optional',self._trigger_limit_key(source,ability),source.controller])

    def remaining_trigger_uses(self,source,ability):
        if ability.trigger_limit is None and not ability.optional_once_per_turn:return None
        key=self._optional_limit_key(source,ability) if ability.optional_once_per_turn else self._trigger_limit_key(source,ability)
        used=self.trigger_limits.get(key,0) if self.trigger_limit_turn==self.state.turn_number else 0
        return max(0,(1 if ability.optional_once_per_turn else ability.trigger_limit)-used)

    def _trigger(self,source,ability,bindings=None,*,condition_objects=None,condition_views=None,condition_life_totals=None,condition_live_players=None,values=None):
        if source.controller not in self.state.live_players:return
        if not self._source_condition(source,ability.source_must_remain):return
        if not self._condition_holds(ability.occurrence_condition,source,condition_objects,condition_views,condition_life_totals,condition_live_players):
            self._event('trigger_occurrence_condition_failed',ability=ability.ability_id,source=source.ref.to_json())
            return
        if not self._condition_holds(ability.intervening_if,source,condition_objects,condition_views,condition_life_totals,condition_live_players):
            self._event('trigger_condition_failed',ability=ability.ability_id,source=source.ref.to_json())
            return
        if self.trigger_limit_turn!=self.state.turn_number:
            self.trigger_limit_turn=self.state.turn_number;self.trigger_limits={}
        if ability.optional_once_per_turn and self.trigger_limits.get(self._optional_limit_key(source,ability),0):return
        if ability.trigger_limit is not None:
            limit_key=self._trigger_limit_key(source,ability)
            if self.trigger_limits.get(limit_key,0)>=ability.trigger_limit:return
            self.trigger_limits[limit_key]=self.trigger_limits.get(limit_key,0)+1
        occurrence={'id':self._id('trigger'),'source':source.to_json(),'controller':source.controller,'ability':encode(ability),'bindings':bindings or {},'values':values or {}}
        self.pending_triggers.append(occurrence)
        self._event('trigger_created',trigger=occurrence['id'],ability=ability.ability_id,source=source.ref.to_json(),controller=source.controller)

    def begin_step(self,active,step):
        self._idle()
        if self.turn_schedule is not None:raise RulesViolation('Cannot inject a step into running turns')
        if self.stack or active not in self.state.players:raise RulesViolation('Invalid step boundary')
        if step!='upkeep':raise UnsupportedRule('Only upkeep step discovery is in this vertical slice')
        self.state.empty_mana_pools();self.phase=step;self.priority=active
        self.active=active;self._event('step_began',active=active,step=step)
        self._collect_step(step)
        return self.advance()

    def _collect_step(self,step):
        for source in self.state.objects(Zone.BATTLEFIELD):
            if source.phased:continue
            for ability in self._trigger_abilities(source,'step_began'):
                if self._matches(ability.event,source,step=step):self._trigger(source,ability)

    ENTRY_VIEW_CACHE_LIMIT=64

    def _proposal_view(self, proposal):
        # Replacement ordering/trace bookkeeping cannot change characteristics.
        # Retain only this state epoch and a bounded number of material proposals.
        epoch=(self.state,self.state.sequence)
        if getattr(self,'_entry_view_epoch',None)!=epoch:
            self._entry_view_epoch=epoch;self._entry_view_cache=OrderedDict()
        key=(proposal.before,proposal.controller,proposal.copied_definition,proposal.counters,proposal.tapped,proposal.copied_add_types)
        cache=self._entry_view_cache
        if key in cache:
            cache.move_to_end(key)
            return cache[key]
        result=self._compute_proposal_view(proposal)
        cache[key]=result
        if len(cache)>self.ENTRY_VIEW_CACHE_LIMIT:cache.popitem(last=False)
        return result

    def _compute_proposal_view(self, proposal):
        entering=replace(proposal.before,ref=ObjectRef(proposal.before.ref.card_id,proposal.before.ref.incarnation+1),
            zone=Zone.BATTLEFIELD,controller=proposal.controller,copied_definition=proposal.copied_definition,copied_add_types=proposal.copied_add_types,
            counters=proposal.counters,tapped=proposal.tapped,attached_to=None,phased=False,timestamp=self.state.sequence+1)
        objects=tuple(obj for obj in self.state.objects() if obj.ref.card_id!=entering.ref.card_id)+(entering,)
        return entering,evaluate_characteristics(objects,self.definitions,entering_ref=entering.ref,temporary=self._temporary_rows(),life_totals={p:self.state.life(p) for p in self.state.players},starting_life_totals={p:self.state.starting_life(p) for p in self.state.players},live_players=self.state.live_players)[entering.ref]

    def _proposal_types(self, proposal):
        if proposal.destination == Zone.BATTLEFIELD:return self._proposal_view(proposal)[1].types
        return self.characteristics().get(proposal.before.ref,base_characteristics(proposal.before,self.definitions)).types

    def _entry_effect_candidates(self, proposal, entry_view):
        if proposal.destination!=Zone.BATTLEFIELD:return ()
        entering,view=entry_view
        result=[]
        sources=tuple(o for o in self.state.objects(Zone.BATTLEFIELD) if not o.phased)+(entering,)
        for source in sources:
            own=source.ref==entering.ref
            definition=self.definition(source)
            if not own:
                for modifier in definition.entry_modifiers:
                    if modifier.selector is None or not matches_selector(modifier.selector,entering,view,source):continue
                    key=f'entry-global:{source.ref.card_id}@{source.ref.incarnation}:{modifier.modifier_id}'
                    if key in proposal.used:continue
                    if modifier.condition is not None and self._condition_holds(modifier.condition,source)==modifier.unless:continue
                    result.append(ReplacementCandidate(key,definition.name+': '+modifier.modifier_id,'entry',3,source.controller,modifier,source))
            for rule in definition.entry_counters:
                if own and rule.selector is not None:continue
                if not own and (rule.selector is None or not matches_selector(rule.selector,entering,view,source)):continue
                key=f'entry-counter:{source.ref.card_id}@{source.ref.incarnation}:{rule.replacement_id}'
                if key not in proposal.used:
                    result.append(ReplacementCandidate(key,definition.name+': '+rule.replacement_id,'entry_counters',3,source.controller,rule,source))
            for rule in definition.counter_replacements:
                if not actor_matches(rule,source,entering.controller):continue
                if own and rule.subject!='self':continue
                if rule.subject=='self' and not own:continue
                if rule.selector is None or not matches_selector(rule.selector,entering,view,source):continue
                if not proposal.counters or rule.kind is not None and not dict(proposal.counters).get(rule.kind,0):continue
                key=f'counter:{source.ref.card_id}@{source.ref.incarnation}:{rule.replacement_id}'
                if key not in proposal.used:
                    result.append(ReplacementCandidate(key,definition.name+': '+rule.replacement_id,'counter',3,source.controller,rule,source))
        return tuple(result)

    def _resolve_zone_proposal(self, proposal, frame, key):
        while True:
            definition=self.definitions[proposal.copied_definition or proposal.before.effective_definition]
            source=replace(proposal.before,controller=proposal.controller)
            applicable={modifier.modifier_id for modifier in definition.entry_modifiers
                if modifier.selector is None and (modifier.condition is None or self._condition_holds(modifier.condition,source)!=modifier.unless)}
            entry_view=self._proposal_view(proposal) if proposal.destination==Zone.BATTLEFIELD else None
            types=entry_view[1].types if entry_view is not None else self._proposal_types(proposal)
            available = candidates(self.state, self.definitions, proposal, types,applicable)
            if not available or available[0].priority>=3:
                available=available+self._entry_effect_candidates(proposal,entry_view)
            if not available:
                return proposal
            step_key = key + ':replacement:' + str(len(proposal.trace))
            if len(available) > 1:
                chosen = self._choose(step_key + ':order', affected_player(proposal),
                    'replacement_order', 'Choose which applicable replacement to apply next.',
                    tuple(Option(c.key, c.label) for c in available), 1, 1)
                candidate = next(c for c in available if c.key == chosen[0].key)
            else:
                candidate = available[0]
            accepted = True
            copied_definition = None
            copied_add_types = ()
            counters = None
            if candidate.kind == 'commander':
                chosen = self._choose(step_key + ':commander', candidate.controller,
                    'commander_destination', 'Choose the commander destination.',
                    (Option('command', 'Command zone'), Option('original', proposal.destination.value)), 1, 1)
                accepted = chosen[0].key == 'command'
            elif candidate.kind == 'copy':
                context = {**frame, 'source': proposal.before.to_json(), 'controller': proposal.controller}
                chosen = self._choose(step_key + ':copy', candidate.controller, 'entry_copy',
                    'Choose a card to copy as this enters, or choose none.',
                    self._options(self._query(candidate.program, context)), 0, 1)
                accepted = bool(chosen)
                if chosen:
                    copied = self.state.get(chosen[0].ref)
                    copied_definition = copied.effective_definition
                    copied_add_types = copied.copied_add_types
            elif candidate.kind=='entry_counters':
                context={**frame,'source':candidate.source.to_json(),'controller':candidate.controller,
                    'chosen_x':proposal.before.cast_x if proposal.before.zone==Zone.STACK else 0}
                amount=self._quantity(candidate.program.amount,context)
                counts=dict(proposal.counters)
                if amount>0:counts[candidate.program.kind]=counts.get(candidate.program.kind,0)+amount
                counters=tuple(sorted(counts.items()))
            elif candidate.kind=='counter':
                counters=tuple(sorted(transformed(dict(proposal.counters),candidate.program).items()))
            elif candidate.kind=='redirect' and candidate.program.optional:
                chosen = self._choose(step_key + ':optional', affected_player(proposal),
                    'replacement_optional', 'Apply ' + candidate.label + '?',
                    (Option('yes', 'Apply replacement'), Option('no', 'Decline replacement')), 1, 1)
                accepted = chosen[0].key == 'yes'
            proposal = apply_replacement(proposal, candidate, accepted=accepted,
                                         copied_definition=copied_definition,counters=counters,copied_add_types=copied_add_types)

    def _move(self, refs, destination, frame, key, *, cause='effect', entry_flags=(), controller_mode='effect', detaches=(), counter_pairs=(),payment=None,entry_tapped=False,creates=(),placements=None,entry_counters=()):
        before = self.state.objects(Zone.BATTLEFIELD)
        before_views = self.characteristics()
        before_life_totals = {p:self.state.life(p) for p in self.state.players}
        before_live_players = self.state.live_players
        proposals = [];blocked=[]
        entry_restrictions=tuple((source,restriction) for source in before if not source.phased
            for restriction in self.definition(source).entry_restrictions)
        default_destination=destination;default_tapped=entry_tapped
        if placements is not None:
            if (not isinstance(placements,dict) or set(placements)!=set(refs)
                    or any(not isinstance(row,tuple) or len(row)!=2 or not isinstance(row[0],Zone)
                        or type(row[1]) is not bool or row[1] and row[0]!=Zone.BATTLEFIELD for row in placements.values())):
                raise RulesViolation('Invalid simultaneous placement groups')
        created={obj.ref:obj for obj in creates}
        def get_source(ref):return created.get(ref) or self.state.get(ref)
        seen = set()
        for index, ref in enumerate(refs):
            destination,entry_tapped=placements[ref] if placements is not None else (default_destination,default_tapped)
            if ref in seen:
                raise RulesViolation('Duplicate source in a simultaneous move')
            seen.add(ref)
            try:
                obj = get_source(ref)
            except RulesViolation:
                continue  # A departed incarnation is no longer affected.
            if (obj.phased and cause!='departed_controller_exile') or obj.zone==destination or ref not in created and (obj.zone==Zone.OUTSIDE or obj.token and obj.zone not in {Zone.BATTLEFIELD, Zone.STACK}):
                continue
            if destination==Zone.BATTLEFIELD and controller_mode=='effect' and frame['controller'] not in self.state.live_players:continue
            if destination==Zone.BATTLEFIELD:
                blocker=next((source for source,restriction in entry_restrictions
                    if obj.zone==restriction.zone and matches_selector(restriction,obj,before_views[obj.ref],source)),None)
                if blocker is not None:
                    blocked.append((obj.ref,blocker.ref));continue
            proposals.append((index, ZoneProposal(obj, destination,
                frame['controller'] if destination == Zone.BATTLEFIELD and controller_mode == 'effect' else obj.owner,tapped=entry_tapped,counters=entry_counters)))
        # Choices for different affected players follow APNAP. Commit order
        # stays bound to the input batch, independently of choice scheduling.
        start = self.state.players.index(self.active)
        players = self.state.players[start:] + self.state.players[:start]
        resolved = {}
        for index, proposal in sorted(proposals, key=lambda row: players.index(affected_player(row[1]))):
            resolved[index] = self._resolve_zone_proposal(proposal, frame, key + ':' + str(index))
        attachments = {}
        for index, proposal in sorted(resolved.items(), key=lambda row: players.index(row[1].controller)):
            if proposal.destination != Zone.BATTLEFIELD:
                continue
            allowed, attached_to = self._aura_entry(proposal, frame, key + ':' + str(index))
            if allowed:
                attachments[index] = attached_to
            elif proposal.before.zone == Zone.STACK:
                # CR 303.4g: failure to find a legal attachment sends a stack
                # Aura to its graveyard; that new proposal can be replaced.
                fallback = ZoneProposal(proposal.before, Zone.GRAVEYARD, proposal.before.owner, trace=proposal.trace)
                resolved[index] = self._resolve_zone_proposal(fallback, frame, key + ':' + str(index) + ':aura-failed')
            else:
                resolved[index] = None  # Non-stack Aura stays in its current zone.
        moves = []
        for index, _ in proposals:
            proposal = resolved[index]
            if proposal is None or proposal.destination == proposal.before.zone:
                continue
            entering = proposal.destination == Zone.BATTLEFIELD
            moves.append(ZoneMove(proposal.before.ref, proposal.destination,
                proposal.controller if entering else proposal.before.owner,
                proposal.copied_definition if entering else None,
                frozenset(entry_flags) if entering else frozenset(), attached_to=attachments.get(index),
                tapped=proposal.tapped if entering else False,counters=proposal.counters if entering else (),
                copied_add_types=proposal.copied_add_types if entering else ()))
        # Timestamp choices matter when simultaneous entrants carry competing
        # continuous effects. Other entrants have no timestamp-sensitive static
        # behavior in this vocabulary and retain stable relative order.
        by_player = {player: [] for player in players}
        for move in moves:
            controller = move.controller if move.destination == Zone.BATTLEFIELD else get_source(move.source).owner
            by_player[controller].append(move)
        ordered_moves = []
        for player in players:
            own = by_player[player]
            relevant = [move for move in own if move.destination == Zone.BATTLEFIELD
                and self.definitions[move.copied_definition or get_source(move.source).definition].continuous]
            if len(relevant) > 1:
                options = tuple(Option(str(i), self.definitions[move.copied_definition or get_source(move.source).definition].name,
                                       ref=move.source) for i, move in enumerate(relevant))
                chosen = self._choose(key + ':timestamps:' + player, player, 'timestamp_order',
                    'Order these simultaneous continuous-effect sources from earliest to latest timestamp.',
                    options, len(options), len(options), ordered=True)
                replacement = iter(relevant[int(option.key)] for option in chosen)
                own = [next(replacement) if move in relevant else move for move in own]
            ordered_moves.extend(own)
        events = self.state.move(ordered_moves, cause, detaches=detaches, counter_pairs=counter_pairs,payment=payment,creates=tuple(created[m.source] for m in ordered_moves if m.source in created))
        for ref,blocker in blocked:self._event('entry_prohibited',ref=ref.to_json(),source=blocker.to_json())
        departed_spells={event.before.ref for event in events if event.before.zone==Zone.STACK}
        if departed_spells:
            self.stack=[waiting for waiting in self.stack if not (waiting['spell'] and self._source(waiting).ref in departed_spells)]
        for index, _ in proposals:
            proposal = resolved[index]
            for replacement in proposal.trace if proposal is not None else ():
                self._event('replacement_considered', source=proposal.before.ref.to_json(), **replacement)
        for event in events:
            self._event('zone_changed', event=event.to_json())
        self._collect(events, before, self.state.objects(Zone.BATTLEFIELD), before_views,before_life_totals,before_live_players)
        for event in events:
            if event.after.zone==Zone.BATTLEFIELD and event.after.counters:
                self._emit_counters(event.after.ref,dict(event.after.counters),event.after.controller,event.after.ref)
        if payment is not None:self._collect_tapped(payment.taps,before)
        self._prune_attachment_rules()
        return events

    def _refs(self,frame,subject):
        if subject=='source':return (self._source(frame).ref,)
        if subject=='target':return tuple(dict.fromkeys(target_from_json(v) for v in frame['targets'] if 'player' not in v))
        return tuple(ObjectRef.from_json(v) for v in frame['bindings'].get(subject,[]))

    def _insert(self,frame,effects):
        frame['tasks'][1:1]=[{'id':self._id('effect'),'effect':encode(effect),
            'bindings':json.loads(json.dumps(frame['bindings'])),'values':dict(frame.get('values',{})),
            **({'mode_id':frame['active_mode']} if 'active_mode' in frame else {})} for effect in effects]

    def _quantity(self,value,frame):
        if type(value) is int:return value
        if isinstance(value,TargetStat):
            amounts=[]
            for ref in dict.fromkeys(self._refs(frame,'target')):
                try:
                    self.state.get(ref);view=self.effective(ref)
                except RulesViolation:
                    known=self.last_known.get(ref)
                    if known is None:raise UnsupportedRule('No last known characteristics for target statistic')
                    view=known[1]
                amounts.append(len(view.colors) if value.statistic=='color_count' else getattr(view,value.statistic) or 0)
            return max(0,max(amounts,default=0) if value.operation=='maximum' else sum(amounts))
        if isinstance(value,RecipientStat):
            amount=frame['values']['recipient_stat'][value.statistic] or 0
            return amount if value.allow_negative else max(0,amount)
        if isinstance(value,SourceCounter):
            source,_=self._object_information(self._source(frame))
            return dict(source.counters).get(value.kind,0)
        if isinstance(value,SourceStat):
            _,view=self._object_information(self._source(frame))
            amount=getattr(view,value.statistic) or 0
            return amount if value.allow_negative else max(0,amount)
        if isinstance(value,BattlefieldStat):
            views=self.characteristics()
            amounts=[getattr(views[obj.ref],value.statistic) or 0 for obj in self._query(value.selector,frame)]
            return max(0,max(amounts,default=0) if value.operation=='maximum' else sum(amounts))
        if isinstance(value,EventX):return frame["values"]["event_x"]
        if isinstance(value,DividedValue):
            amount=self._quantity(value.value,frame)
            return (amount+(value.divisor-1 if value.rounding=="up" else 0))//value.divisor
        if isinstance(value,MovedCount):return frame['values']['moved_count']
        if isinstance(value,LifeLost):return frame['values']['life_lost']
        if isinstance(value,EventAmount):return frame['values']['event_amount']
        if isinstance(value,ChosenX):return frame['chosen_x']
        if isinstance(value,SelectedCount):return frame['values']['selected_count']
        if isinstance(value,CountObjects):return len(self._query(value.selector,frame))
        if isinstance(value,ScaledValue):return value.factor*self._quantity(value.value,frame)
        raise UnsupportedRule('No evaluator for quantity expression')

    def _zone_operation(self,effect,frame,key):
        controller=frame['controller']
        if isinstance(effect,Move):
            refs=self._refs(frame,effect.subject)
            retained={}
            if effect.library_position is not None:
                for ref in refs:
                    try:obj=self.state.get(ref)
                    except RulesViolation:continue
                    if obj.zone==Zone.LIBRARY and not obj.phased:retained[ref]=obj
            events=self._move(refs,effect.destination,frame,key,entry_flags=frame['entry_flags'] if effect.subject=='source' else (),controller_mode=effect.controller,entry_tapped=effect.tapped,entry_counters=effect.counters)
            if effect.library_position is not None:
                arrivals={e.before.ref:e.after for e in events if e.after.zone==Zone.LIBRARY}
                groups={}
                for ref in refs:
                    obj=arrivals.get(ref) or retained.get(ref)
                    if obj is not None:groups.setdefault(obj.owner,[]).append(obj.ref)
                for player,group in groups.items():
                    if player not in self.state.live_players:continue
                    placed=tuple(group)
                    if not placed:continue
                    selected=set(placed)
                    middle=tuple(o.ref for o in self.state.zone(player,Zone.LIBRARY) if o.ref not in selected)
                    ordered=tuple(reversed(placed))
                    self.state.reorder(player,Zone.LIBRARY,middle+ordered if effect.library_position=='top' else ordered+middle)
                    self._event('library_positioned',player=player,position=effect.library_position,amount=len(placed))
                    if player==controller:
                        self.library_observations[player]={'id':key+':placement','kind':'library_'+effect.library_position,'observed_revision':self.revision,
                            'cards':[{'ref':ref.to_json(),'name':self.definition(self.state.get(ref)).name} for ref in placed]}
            return events
        elif isinstance(effect,Destroy):
            refs=[]
            for ref in self._refs(frame,effect.subject):
                try:obj=self.state.get(ref)
                except RulesViolation:continue
                if obj.zone==Zone.BATTLEFIELD and not obj.phased and 'indestructible' not in self.effective(ref).keywords:refs.append(ref)
            return self._move(refs,Zone.GRAVEYARD,frame,key,cause='destroy')
        elif isinstance(effect,Sacrifice):
            refs=[]
            for ref in self._refs(frame,effect.subject):
                try:obj=self.state.get(ref)
                except RulesViolation:continue
                if obj.zone==Zone.BATTLEFIELD and (effect.by_subject_controller or obj.controller==controller) and not obj.phased:refs.append(ref)
            return self._move(refs,Zone.GRAVEYARD,frame,key,cause='sacrifice')
        elif isinstance(effect,Discard):
            refs=[]
            for ref in self._refs(frame,effect.subject):
                try:obj=self.state.get(ref)
                except RulesViolation:continue
                if obj.zone==Zone.HAND and obj.owner==controller:refs.append(ref)
            events=self._move(refs,Zone.GRAVEYARD,frame,key,cause='discard')
            self._event('cards_discarded',player=controller,refs=[e.before.ref.to_json() for e in events])
            return events
        elif isinstance(effect,Counter):
            refs=[]
            for ref in self._refs(frame,effect.subject):
                try:obj=self.state.get(ref)
                except RulesViolation:continue
                if obj.zone==Zone.STACK:refs.append(ref)
            events=self._move(refs,effect.destination,frame,key,cause='counter')
            removed={e.before.ref for e in events}
            self.stack=[f for f in self.stack if not (f['spell'] and self._source(f).ref in removed)]
            if events:self._event('spells_countered',refs=[ref.to_json() for ref in sorted(removed)])
            return events
        raise UnsupportedRule('Unsupported zone-result operation')

    def _insert_zone_result(self,events,destination,frame,effects,selector=None):
        matching=[event for event in events if destination is None or event.after.zone==destination]
        if selector is not None:
            source=replace(self._source(frame),controller=frame['controller'])
            matching=[event for event in matching if matches_selector(selector,event.after,self._object_information(event.after)[1],source)]
        if not matching:return
        frame['bindings']['moved']=[event.after.ref.to_json() for event in matching]
        frame['values']['moved_count']=len(matching)
        frame['values']['moved_controllers']=[event.before.controller for event in matching if event.before.zone in {Zone.BATTLEFIELD,Zone.STACK}]
        self._insert(frame,effects)

    def _execute(self,frame,task):
        # Nested selections have lexical bindings: an inner selection cannot
        # overwrite the outer selection's remaining instructions.
        frame={**frame,'bindings':dict(task.get('bindings',frame['bindings'])),'values':dict(task.get('values',frame.get('values',{})))}
        if 'mode_id' in task:
            frame['active_mode']=task['mode_id']
            frame['targets']=next(group['targets'] for group in frame['mode_groups'] if group['mode_id']==task['mode_id'])
        for group in frame.get('target_groups',()):
            frame['bindings']['target:'+group['group_id']]=group['targets']
        effect=decode(task['effect']);key=task['id'];controller=frame['controller'];source=self._source(frame)
        if self._execute_attachment(effect,frame,key):return
        if isinstance(effect,UntilEndOfTurn):
            refs=[]
            for ref in self._refs(frame,effect.subject):
                try:obj=self.state.get(ref)
                except RulesViolation:continue
                if obj.zone==Zone.BATTLEFIELD and not obj.phased:refs.append(ref)
            if not refs:return
            def dependent(value):
                return isinstance(value,RecipientStat) or isinstance(value,(ScaledValue,DividedValue)) and dependent(value.value)
            dynamic=any(dependent(value) for change in effect.changes if isinstance(change,(ModifyPT,SetPT)) for value in (change.power,change.toughness))
            common={}
            def frozen_changes(context):
                local={}
                def freeze(value):
                    if type(value) is int:return value
                    captured=local if dependent(value) else common
                    if value not in captured:captured[value]=self._quantity(value,context)
                    return captured[value]
                return tuple(replace(change,**{name:freeze(value) for name,value in (('power',change.power),('toughness',change.toughness))}) if isinstance(change,(ModifyPT,SetPT)) else change for change in effect.changes)
            groups={}
            if dynamic:
                # Capture all per-recipient values against the same derived view
                # before creating any effect; earlier recipients cannot affect later ones.
                views=self.characteristics()
                for ref in refs:
                    context={**frame,'values':{**frame.get('values',{}),'recipient_stat':{name:getattr(views[ref],name) for name in ('power','toughness','mana_value')}}}
                    groups.setdefault(frozen_changes(context),[]).append(ref)
            else:groups[frozen_changes(frame)]=refs
            timestamp=self.state.allocate_effect_timestamp()
            for index,(changes,recipients) in enumerate(groups.items()):
                effect_id=key if len(groups)==1 else key+':'+str(index)
                program=ContinuousProgram(effect_id,Selector(Zone.BATTLEFIELD),changes)
                self.temporary_effects.append({'source':replace(source,timestamp=timestamp).to_json(),'effect':encode(program),'refs':[ref.to_json() for ref in recipients]})
                self._event('temporary_effect_created',effect_id=effect_id,refs=[ref.to_json() for ref in recipients],changes=encode(changes))
        elif isinstance(effect,WithControllers):
            captured=[]
            for ref in self._refs(frame,effect.subject):
                try:obj=self.state.get(ref)
                except RulesViolation:
                    if ref!=source.ref:continue
                    obj=source
                if obj.zone not in {Zone.BATTLEFIELD,Zone.STACK} or obj.phased:continue
                captured.append(obj.controller)
            frame['values']['captured_controllers']=captured
            self._insert(frame,effect.effects)
        elif isinstance(effect,WithZoneResult):
            events=self._zone_operation(effect.operation,frame,key)
            self._insert_zone_result(events,effect.destination,frame,effect.effects,effect.selector)
        elif isinstance(effect,WithMoved):
            events=self._move(self._refs(frame,effect.subject),effect.destination,frame,key,controller_mode=effect.controller)
            self._insert_zone_result(events,effect.destination,frame,effect.effects)
        elif isinstance(effect,(Move,Destroy,Sacrifice,Discard,Counter)):
            self._zone_operation(effect,frame,key)
        elif isinstance(effect,SetTapped):
            refs=[]
            for ref in self._refs(frame,effect.subject):
                try:obj=self.state.get(ref)
                except RulesViolation:continue
                if obj.zone==Zone.BATTLEFIELD and not obj.phased:refs.append(ref)
            before=self._tap_observers(refs) if effect.tapped else ()
            changed=self.state.set_tapped_batch(refs,effect.tapped)
            if changed:self._event('objects_tapped' if effect.tapped else 'objects_untapped',controller=controller,refs=[r.to_json() for r in changed])
            self._collect_tapped(changed,before)
        elif isinstance(effect,GainControl):
            refs=[]
            for ref in self._refs(frame,effect.subject):
                try:obj=self.state.get(ref)
                except RulesViolation:continue
                if obj.zone==Zone.BATTLEFIELD and not obj.phased:refs.append(ref)
            keys=self.state.change_control_batch(refs,controller,duration=effect.duration)
            self._event('control_effects_created',controller=controller,effects=list(keys),refs=[ref.to_json() for ref in refs])
            self._combat_prune()
        elif isinstance(effect,CounterAbilities):
            players=set(self._players(frame,effect.players))
            removed=[waiting['id'] for waiting in self.stack if not waiting['spell']
                and not waiting.get('turn_based') and waiting['controller'] in players]
            if removed:
                ids=set(removed);self.stack=[waiting for waiting in self.stack if waiting['id'] not in ids]
                self._event('abilities_countered',frames=removed)
        elif isinstance(effect,Damage):
            recipients=(controller,) if effect.subject=='controller' else tuple(target_from_json(v).player if 'player' in v else target_from_json(v) for v in frame['targets']) if effect.subject=='target' else self._refs(frame,effect.subject)
            amount=self._quantity(effect.amount,frame)
            if effect.players is not None:recipients+=self._players(frame,effect.players)
            recipients=tuple(dict.fromkeys(recipients));sources=[]
            if effect.source_subject=='source':sources=[source]
            else:
                for ref in self._refs(frame,effect.source_subject):
                    try:obj=self.state.get(ref)
                    except RulesViolation:
                        obj=self.last_known[ref][0] if ref in self.last_known else next((event.before for event in reversed(self.state.events) if event.before.ref==ref),None)
                    if obj is not None:sources.append(obj)
            self._deal_damage([(dealer,recipient,amount) for dealer in sources for recipient in recipients
                if not effect.exclude_damage_source or recipient!=dealer.ref])
        elif isinstance(effect,ProduceMana):
            amount=self._quantity(effect.amount,frame)
            if not amount:return
            symbol=effect.options[0]
            if len(effect.options)>1:
                options=tuple(Option(c,str(amount)+' {'+c+'}') for c in effect.options)
                symbol=self._choose(key,controller,'mana_choice','Choose the mana to produce.',options,1,1)[0].key
            symbols=(symbol,)*amount
            self._produce_mana(controller,symbols,tapped_for_mana=frame.get('tapped_for_mana',False))
        elif isinstance(effect,(ChooseMana,ChooseCommanderMana)):
            alternatives=effect.options if isinstance(effect,ChooseMana) else tuple((c,) for c in self.state.commander_identity(controller))
            if not alternatives:return
            if len(alternatives)==1:symbols=alternatives[0]
            else:
                options=tuple(Option(str(i),''.join('{'+symbol+'}' for symbol in symbols)) for i,symbols in enumerate(alternatives))
                chosen=self._choose(key,controller,'mana_choice','Choose the mana to produce.',options,1,1)
                symbols=alternatives[int(chosen[0].key)]
            self._produce_mana(controller,symbols,tapped_for_mana=frame.get('tapped_for_mana',False))
        elif isinstance(effect,AddMana):
            self._produce_mana(controller,effect.symbols,tapped_for_mana=frame.get('tapped_for_mana',False))
        elif isinstance(effect,GainLife):
            amount=self._quantity(effect.amount,frame)
            amount=self._life_gain_amount(controller,amount)
            self.state.gain_life(controller,amount)
            if amount and controller in self.state.live_players:self._player_event('life_gained',controller,amount=amount,source=source.ref.to_json())
        elif isinstance(effect,(Scry,Surveil,LookTop)):
            kind='scry' if isinstance(effect,Scry) else 'surveil' if isinstance(effect,Surveil) else 'look_top'
            self._arrange_top(effect,frame,task,kind)
        elif isinstance(effect,ChooseFromTop):
            self._choose_from_top(effect,frame,task)
        elif isinstance(effect,SearchLibrary):
            self._search_library(effect,frame,task)
        elif isinstance(effect,(LoseLife,WithLifeLost)):
            players=self._players(frame,effect.players);amount=self._quantity(effect.amount,frame)
            losses=self.state.lose_life_batch(players,amount)
            for player,lost in losses.items():self._event('life_lost',player=player,amount=lost,source=source.ref.to_json(),cause='effect')
            if isinstance(effect,WithLifeLost):
                frame['values']['life_lost']=sum(losses.values());self._insert(frame,effect.effects)
        elif isinstance(effect,Mill):
            # Freeze recipients, quantity and physical top cards before any
            # replacement-order choice. A resumed batch never selects new cards.
            if 'mill_refs' not in task:
                amount=self._quantity(effect.amount,frame)
                task['mill_refs']=[obj.ref.to_json()
                    for player in self._players(frame,effect.players)
                    for obj in (self.state.zone(player,Zone.LIBRARY)[-amount:] if amount else ())]
            self._move(tuple(ObjectRef.from_json(ref) for ref in task['mill_refs']),
                Zone.GRAVEYARD,frame,key+':mill',cause='mill',controller_mode='owner')
        elif isinstance(effect,Draw):
            # Fix the recipient set and amount once, then perform each player's
            # individual draws in APNAP order (121.2c). A choice resumes this cursor.
            if 'draw_plan' not in task:
                task['draw_plan']={'players':list(self._players(frame,effect.players)),'amount':self._quantity(effect.amount,frame),'player_index':0,'draw_index':0}
            plan=task['draw_plan']
            while plan['player_index']<len(plan['players']):
                player=plan['players'][plan['player_index']]
                while plan['draw_index']<plan['amount'] and player in self.state.live_players:
                    library=self.state.zone(player,Zone.LIBRARY)
                    if not library:
                        self.state.fail_draw(player);self._event('draw_failed',player=player)
                    else:
                        ref=library[-1].ref
                        self._move((ref,),Zone.HAND,frame,key+':draw:'+str(plan['player_index'])+':'+str(plan['draw_index']),cause='draw',controller_mode='owner')
                        self._player_event('card_drawn',player,card_id=ref.card_id)
                    plan['draw_index']+=1
                plan['player_index']+=1;plan['draw_index']=0
        elif isinstance(effect,GrantPermissions):
            self.player_effects.append({'controller':controller,'permissions':encode(effect.permissions),'duration':effect.duration})
            self._event('player_permissions_granted',player=controller,permissions=encode(effect.permissions),duration=effect.duration)
        elif isinstance(effect,IfCondition):
            branch=effect.effects if self._condition_holds(effect.condition,replace(source,controller=controller)) else effect.otherwise
            self._insert(frame,branch)
        elif isinstance(effect,May):
            limit_key=frame.get('optional_limit_key') if frame.get('optional_limit_task')==key else None
            if limit_key is not None:
                if self.trigger_limit_turn!=self.state.turn_number:
                    self.trigger_limit_turn=self.state.turn_number;self.trigger_limits={}
                if self.trigger_limits.get(limit_key,0):return
            available=True
            if effect.available is not None:
                subjects=set(self._refs(frame,effect.subject))
                available=any(obj.ref in subjects for obj in self._query(effect.available,frame))
            if available:
                selected=self._choose(key,controller,'may','Perform the optional effect?',(Option('yes','Yes'),Option('no','No')),1,1)
                accepted=selected[0].key=='yes'
            else:accepted=False
            if accepted and limit_key is not None:
                self.trigger_limits[limit_key]=1
                self._event('optional_turn_use_consumed',source=source.ref.to_json(),ability=frame['ability_id'],controller=controller)
            self._insert(frame,effect.effects if accepted else effect.otherwise)
        elif isinstance(effect,UnlessEntered):
            if effect.flag not in source.entry_flags:self._insert(frame,effect.effects)
        elif isinstance(effect,SelectAll):
            frame['bindings']['selected']=[obj.ref.to_json() for obj in self._query(effect.selector,frame)]
            frame['values']['selected_count']=len(frame['bindings']['selected'])
            self._insert(frame,effect.effects)
        elif isinstance(effect,Select):
            options=self._options(self._query(effect.selector,frame))
            capacity=choice_capacity(options,effect.group_by_controller)
            minimum=min(effect.minimum,capacity);maximum=min(effect.maximum,capacity)
            # Resolving instructions do as much as possible (609.3). Costs and
            # announcement targets retain their separate strict requirements.
            if maximum==0:selected=()
            elif not effect.ordered and minimum==maximum==len(options):selected=options
            else:selected=self._choose(key,controller,'selection','Choose the requested objects.',options,minimum,maximum,effect.ordered,effect.group_by_controller)
            frame['bindings']['selected']=[option.ref.to_json() for option in selected]
            frame['values']['selected_count']=len(selected);self._insert(frame,effect.effects)
        elif isinstance(effect,CreateTokens):
            amount=self._quantity(effect.amount,frame)
            if not amount:return
            recipients=(frame['values'][effect.players] if effect.players in {'captured_controllers','moved_controllers'}
                else self._players(frame,effect.players))
            # Each captured object contributes one creation instruction, even
            # when several objects had the same controller. Commit one batch.
            multiplicity={}
            for player in recipients:
                if player in self.state.live_players:multiplicity[player]=multiplicity.get(player,0)+1
            created=[]
            for player in self.turn_order():
                for _ in range(amount*multiplicity.get(player,0)):
                    created.append(RulesObject(ObjectRef('token:'+key+':'+str(len(created)),0),effect.token.definition_id,
                        player,player,Zone.OUTSIDE,token=True))
            events=self._move(tuple(o.ref for o in created),Zone.BATTLEFIELD,frame,key+':tokens',cause='token_created',controller_mode='owner',creates=created)
            for player in self.turn_order():
                refs=[e.after.ref.to_json() for e in events if e.after.owner==player]
                if refs:self._event('tokens_created',controller=player,source=source.ref.to_json(),tokens=refs)
        elif isinstance(effect,(AddCounters,MultiplyCounters)):
            placements=[]
            amount=self._quantity(effect.amount,frame) if isinstance(effect,AddCounters) else None
            for recipient in self._counter_recipients(frame,effect.subject):
                counts=self._counter_counts(recipient)
                if counts is None:continue
                n=amount if amount is not None else counts.get(effect.kind,0)*(effect.factor-1)
                placements.append((recipient,effect.kind,n))
            self._put_counters(placements,frame,key)
        elif isinstance(effect,Proliferate):
            objects=[o for o in self.state.objects(Zone.BATTLEFIELD) if not o.phased and any(n>0 for _,n in o.counters)]
            options=list(self._options(objects))
            options.extend(Option('player:'+p,p+' (player counters)',player=p) for p in self.state.live_players if any(n>0 for _,n in self.state.player_counters(p)))
            selected=self._choose(key,controller,'proliferate','Choose any number of eligible permanents and players; each gets another of every counter kind present.',options)
            placements=[]
            for option in selected:
                recipient=option.ref if option.ref else PlayerRef(option.player)
                placements.extend((recipient,kind,1) for kind,n in self._counter_counts(recipient).items() if n>0)
            self._put_counters(placements,frame,key)
            self._event('proliferated',controller=controller,recipients=[o.key for o in selected])
        else:raise UnsupportedRule('No interpreter for effect node')

    def _legal_targets(self,frame):
        if 'target_groups' in frame or 'mode_groups' in frame:
            group_key='target_groups' if 'target_groups' in frame else 'mode_groups'
            had_targets=False;remaining=[]
            for group in frame[group_key]:
                had_targets=had_targets or bool(group['targets'])
                local={**frame,'targets':group['targets'],'target_spec':group['target_spec']}
                del local[group_key]
                self._legal_targets(local)
                group['targets']=local['targets'];remaining.extend(local['targets'])
            frame['targets']=remaining
            return not had_targets or bool(remaining)
        spec=decode(frame['target_spec'])
        if spec is None:return True
        legal={o.ref if o.ref is not None else PlayerRef(o.player) for o in self._target_options(spec,frame)}
        # Shared target permissions are re-evaluated against current control.
        # Player protection, shroud/hexproof and ward remain separate unsupported permissions.
        original=tuple(target_from_json(v) for v in frame['targets'])
        frame['targets']=[ref.to_json() for ref in original if ref in legal]
        return not original or bool(frame['targets'])

    def _state_based_actions(self):
        losses=self.state.losing_players()
        self._combat_prune()
        views=self.characteristics()
        doomed=[];cancellations=[];detaches=[];counter_amounts={}
        for obj in self.state.objects(Zone.BATTLEFIELD):
            if obj.phased:continue
            view=views[obj.ref]
            counters=dict(obj.counters)
            if counters.get('+1/+1',0) and counters.get('-1/-1',0):
                cancellations.append(obj.ref);counter_amounts[obj.ref]=min(counters['+1/+1'],counters['-1/-1'])
            zero_loyalty='Planeswalker' in view.types and not counters.get('loyalty',0)
            zero_toughness='Creature' in view.types and (view.toughness or 0)<=0
            lethal_damage=('Creature' in view.types and (view.toughness or 0)>0
                and 'indestructible' not in view.keywords and (obj.deathtouch_hit or obj.damage_marked>0 and obj.damage_marked>=view.toughness))
            creature_attachment='Creature' in view.types and obj.attached_to is not None
            enchant=self._enchant_rule(obj)[0]
            invalid_non_aura_attachment=(obj.attached_to is not None and enchant is None
                and ('Equipment' not in view.subtypes or not self._attachment_legal(obj,obj.attached_to)))
            if creature_attachment or invalid_non_aura_attachment:detaches.append(obj.ref)
            illegal_aura=not creature_attachment and self._enchant_rule(obj)[0] is not None and not self._attachment_legal(obj,obj.attached_to)
            if zero_loyalty or zero_toughness or lethal_damage or illegal_aura:doomed.append(obj)
        legends={}
        for obj in self.state.objects(Zone.BATTLEFIELD):
            if not obj.phased and 'Legendary' in views[obj.ref].supertypes:
                legends.setdefault((obj.controller,self.definition(obj).name),[]).append(obj)
        start=self.state.players.index(self.active)
        players=self.state.players[start:]+self.state.players[:start]
        for (actor,name),objects in sorted(legends.items(),key=lambda row:(players.index(row[0][0]),row[0][1])):
            if len(objects)<2:continue
            selected=self._choose('legend:'+str(self.state.sequence)+':'+actor+':'+name,actor,
                'legend_rule','Choose one legendary permanent named '+name+' to keep.',self._options(objects),1,1)
            doomed.extend(obj for obj in objects if obj.ref!=selected[0].ref and obj not in doomed)
        if doomed or cancellations or detaches:
            source=(doomed[0] if doomed else self.state.get((cancellations or detaches)[0]))
            self._move(tuple(obj.ref for obj in doomed),Zone.GRAVEYARD,
                {'source':source.to_json(),'controller':self.active},
                'permanent-sba:'+str(self.state.sequence),cause='permanent_sba',
                detaches=detaches,counter_pairs=cancellations)
            self.state.clear_deathtouch_history()
            for ref in detaches:self._event('detached',source=ref.to_json())
            for ref in cancellations:self._event('opposing_counters_removed',source=ref.to_json(),pairs=counter_amounts[ref])
            if losses:self._depart_players(losses)
            return True
        self.state.clear_deathtouch_history()
        if losses:self._depart_players(losses);return True
        for obj in self.state.objects():
            if obj.token and obj.zone not in {Zone.BATTLEFIELD,Zone.STACK}:
                self.state.cease_token(obj.ref);self._event('token_ceased',ref=obj.ref.to_json());return True
        handled=getattr(self,'_commander_sba_handled',set())
        self._commander_sba_handled=handled
        for obj in self.state.objects():
            if not obj.commander or obj.zone not in {Zone.GRAVEYARD,Zone.EXILE} or obj.ref in handled:continue
            key=f'sba:{obj.ref.card_id}:{obj.ref.incarnation}'
            chosen=self._choose(key,obj.owner,'commander_sba','Move your commander from '+obj.zone.value+' to the command zone?',
                (Option('command','Command zone'),Option('stay','Leave it here')),1,1)
            if chosen[0].key=='command':
                self._move((obj.ref,),Zone.COMMAND,{'source':obj.to_json(),'controller':obj.owner},key,cause='commander_sba')
            handled.add(obj.ref);return True
        self.state.assert_invariants();return False

    def _place_triggers(self):
        self._mark_cleanup_priority()
        if self.placement is None:
            start=self.state.players.index(self.active)
            self.placement={'id':self._id('placement'),'players':list(self.turn_order()),'index':0,'orders':{},'return_priority':self.priority or self.priority_player()}
        placement=self.placement
        while placement['index']<len(placement['players']):
            actor=placement['players'][placement['index']]
            own=[t for t in self.pending_triggers if t['controller']==actor]
            if actor not in placement['orders']:
                if len(own)>1:
                    options=tuple(Option(t['id'],self.definition(RulesObject.from_json(t['source'])).name+': '+decode(t['ability']).ability_id+' ['+t['id']+']') for t in own)
                    chosen=self._choose(placement['id']+':order:'+actor,actor,'trigger_order',
                        'Order your triggers bottom-to-top; the last chosen resolves first.',options,len(options),len(options),ordered=True)
                    placement['orders'][actor]=[o.key for o in chosen]
                else:placement['orders'][actor]=[t['id'] for t in own]
            order=placement['orders'][actor]
            while order:
                trigger=next(t for t in self.pending_triggers if t['id']==order[0]);ability=decode(trigger['ability'])
                context={'source':trigger['source'],'controller':actor,'values':trigger.get('values',{})};targets=();target_groups=[]
                if ability.targets:
                    options=self._target_options(ability.targets,context);spec=ability.targets
                    group_bounds=tuple((g.group_id,g.targets.minimum,g.targets.maximum) for g in spec.groups)
                    available=Counts(o.group for o in options) if spec.groups else {}
                    if (choice_capacity(options,spec.group_by_controller,group_bounds)<spec.minimum
                            or any(available[name]<minimum for name,minimum,_ in group_bounds)):
                        self._event('trigger_unplaceable',trigger=trigger['id'],reason='No legal required targets')
                        self.pending_triggers.remove(trigger);order.pop(0);continue
                    amount=trigger.get('values',{}).get('event_amount')
                    prompt='Choose targets for '+ability.ability_id+(' (amount '+str(amount)+')' if amount is not None else '')+'.'
                    selected=self._choose(trigger['id']+':targets',actor,'trigger_targets',prompt,options,spec.minimum,spec.maximum,groups=spec.group_by_controller,group_bounds=group_bounds)
                    grouped={g.group_id:[] for g in spec.groups}
                    if grouped:
                        for option in selected:grouped[option.group].append(option.ref.to_json())
                    target_groups=[{'group_id':g.group_id,'target_spec':encode(g.targets),
                        'targets':grouped[g.group_id]} for g in spec.groups]
                    targets=tuple(o.ref if o.ref is not None else PlayerRef(o.player) for o in selected)
                frame=self._frame(RulesObject.from_json(trigger['source']),actor,ability.effects,targets=targets,target_spec=ability.targets)
                if ability.optional_once_per_turn:
                    frame['optional_limit_key']=self._optional_limit_key(RulesObject.from_json(trigger['source']),ability)
                    frame['optional_limit_task']=frame['tasks'][0]['id']
                if target_groups:frame['target_groups']=target_groups
                frame['ability_id']=ability.ability_id;frame['source_must_remain']=ability.source_must_remain.value if ability.source_must_remain else None
                frame['intervening_if']=encode(ability.intervening_if)
                frame['bindings']=json.loads(json.dumps(trigger.get('bindings',{})));frame['values']=dict(trigger.get('values',{}));self.stack.append(frame)
                self._event('trigger_placed',trigger=trigger['id'],frame=frame['id'],controller=actor,targets=[r.to_json() for r in targets])
                self.pending_triggers.remove(trigger);order.pop(0)
            placement['index']+=1
        self.priority=placement['return_priority'];self.placement=None;self.passes=[]

    def advance(self):
        if self.pending_choice:return self.pending_choice
        try:
            while True:
                if self.outcome:return GameResult(self.outcome['kind'],tuple(self.outcome['winners']),tuple(self.outcome['departed']))
                if self.announcement:self._continue_announcement();continue
                if self.departure:self._continue_departure();continue
                if self._exile_abandoned_control():continue
                frame=self.resolving
                if frame is not None:
                    if not frame['started']:
                        frame['started']=True
                        if not self._source_condition(self._source(frame),Zone(frame['source_must_remain']) if frame.get('source_must_remain') else None):
                            self._event('intervening_condition_failed',frame=frame['id']);frame['tasks']=[]
                        elif not self._condition_holds(decode(frame.get('intervening_if')),replace(self._source(frame),controller=frame['controller'])):
                            self._event('intervening_condition_failed',frame=frame['id']);frame['tasks']=[]
                        elif not self._legal_targets(frame):
                            self._event('all_targets_illegal',frame=frame['id']);frame['tasks']=[]
                    if frame['tasks']:
                        task=frame['tasks'][0];sequence=self.state.sequence
                        self._execute(frame,task)
                        # Combat removal is immediate, even between instructions
                        # of one resolution; it is not a state-based action.
                        if self.combat is not None and self.state.sequence!=sequence:self._combat_prune()
                        frame['tasks'].pop(0);continue
                    if frame['spell']:
                        source=self._source(frame)
                        try:current=self.state.get(source.ref)
                        except RulesViolation:current=None
                        if current and current.zone==Zone.STACK:
                            self._move((current.ref,),Zone.GRAVEYARD,frame,frame['id']+':finish',cause='spell_finished')
                    if frame.get('cleanup_after'):self._finish_cleanup_actions()
                    self._event('resolution_finished',frame=frame['id']);self.resolving=None;self.priority=frame.get('return_priority',self.priority_player());self.passes=[]
                    continue
                if self.turn_schedule is not None and self.priority is None:
                    if self.phase=='declare_attackers' and self.active not in self.state.live_players:
                        self.combat=None;self._begin_phase('end_combat');continue
                    if self.phase=='declare_attackers':return TurnActionBoundary(self.active,'declare_attackers',self.revision)
                    if self.phase in {'declare_blockers','first_strike_damage','combat_damage'}:
                        return self._combat_boundary()
                if self._state_based_actions():
                    self._mark_cleanup_priority();continue
                if self.pending_triggers or self.placement:self._place_triggers();continue
                if self.stack:
                    if self.priority is None:self.priority=self.priority_player()
                    return PriorityBoundary(self.priority,tuple(f['id'] for f in reversed(self.stack)))
                if self.turn_schedule is not None:return self._turn_boundary()
                self.priority=None;return None
        except _NeedsChoice:return self.pending_choice

    def pass_priority(self,actor):
        if self.outcome or actor not in self.state.live_players or self.pending_choice or self.resolving or self.announcement or not self.stack and self.turn_schedule is None or actor!=self.priority:raise RulesViolation('Player does not own this priority boundary')
        self.passes.append(actor);self._event('priority_pass',actor=actor)
        if len(self.passes)==len(self.state.live_players):
            if self.stack:
                self.resolving=self.stack.pop();self.passes=[];self.priority=None
                self._event('resolution_started',frame=self.resolving['id'])
            else:
                self.passes=[];self.turn_schedule['advance']=True
        else:self.priority=self.next_live_player(actor)
        return self.advance()

    def snapshot(self):
        # Round-trip through JSON also detaches caller-visible dictionaries.
        value={'schema':self.CHECKPOINT_SCHEMA,'implementation':IMPLEMENTATION_ID,'bundle':self.bundle,'state':self.state.snapshot(),'active':self.active,
            'last_known':[{'object':obj.to_json(),'view':{**view.__dict__,**{name:sorted(getattr(view,name)) for name in ('types','subtypes','keywords','supertypes','colors')},'applied':list(view.applied),'target_restrictions':encode(view.target_restrictions),'granted_abilities':encode(view.granted_abilities)}} for ref,(obj,view) in sorted(self.last_known.items(),key=lambda row:(row[0].card_id,row[0].incarnation))],
            'temporary_effects':self.temporary_effects,'library_observations':self.library_observations,'stack':self.stack,'resolving':self.resolving,'pending_triggers':self.pending_triggers,'placement':self.placement,
            'pending_choice':self.pending_choice.to_json() if self.pending_choice else None,'answers':self.answers,
            'accepted':self.accepted,'semantic_events':self.semantic_events,'priority':self.priority,'passes':self.passes,
            'serial':self._serial,'revision':self._revision,'phase':self.phase,'action_receipts':self.action_receipts,'turn_schedule':self.turn_schedule,'combat':self.combat,'departure':self.departure,'outcome':self.outcome,'announcement':self.announcement,
            'attachment_rules':self.attachment_rules,'delayed_triggers':self.delayed_triggers,'player_effects':self.player_effects,'trigger_limits':self.trigger_limits,'trigger_limit_turn':self.trigger_limit_turn,
            'commander_sba_handled':[ref.to_json() for ref in sorted(getattr(self,'_commander_sba_handled',set()))]}
        return json.loads(json.dumps(value))

    @classmethod
    def restore(cls,value,definitions):
        if value.get('schema')!=cls.CHECKPOINT_SCHEMA:raise RulesViolation('Unsupported kernel checkpoint')
        if value.get('implementation')!=IMPLEMENTATION_ID:raise RulesViolation('Rules implementation or Python runtime changed across checkpoint')
        kernel=cls(RulesState.restore(value['state']),definitions,value['active'])
        if kernel.bundle!=value['bundle']:raise RulesViolation('Rules bundle changed across checkpoint')
        value=json.loads(json.dumps(value))
        for name in ('temporary_effects','library_observations','stack','resolving','pending_triggers','placement','answers','accepted','semantic_events','priority','passes','attachment_rules','delayed_triggers','phase','action_receipts','turn_schedule','combat','departure','outcome','announcement','player_effects','trigger_limits','trigger_limit_turn'):
            setattr(kernel,name,value[name])
        for row in value['last_known']:
            obj=RulesObject.from_json(row['object']);view=row['view']
            kernel.last_known[obj.ref]=(obj,Characteristics(**{**view,**{name:frozenset(view[name]) for name in ('types','subtypes','keywords','supertypes','colors')},'applied':tuple(view['applied']),'mana_symbols':tuple(view['mana_symbols']),'target_restrictions':decode(view['target_restrictions']),'granted_abilities':decode(view['granted_abilities'])}))
        kernel.pending_choice=ChoiceRequest.from_json(value['pending_choice']) if value['pending_choice'] else None
        kernel._serial=value['serial'];kernel._revision=value['revision']
        kernel._commander_sba_handled={ObjectRef.from_json(r) for r in value['commander_sba_handled']}
        return kernel
