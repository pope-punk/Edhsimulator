"""Actor-bound, fixed-quantity own-library searches with deterministic shuffling.

Search replacements and searching another player's library remain unsupported.
SearchByPlayer lets a captured player optionally search their own library. Tapped search placement modifies the initial entry proposal. Scry partitions only the authorized top
cards in one ordered choice without showing the rest of the library. Production visibility adapters
must keep search choices, shuffle seeds and physical library order private.
"""
from .rules_state import ObjectRef,Zone,RulesViolation
from .rules_choices import Option
from .rules_program import Explore,MayMill,ShuffleLibrary,RevealTopPermanent,SearchByPlayer,SupertypeSelector,decode
from .rules_characteristics import matches


class LibraryRules:
    def _library_cards(self,actor):
        # Tokens are not cards (111.6); a departed token can await SBAs here,
        # but it cannot replace a card in a reveal or mill instruction.
        return tuple(obj for obj in self.state.zone(actor,Zone.LIBRARY) if not obj.token)

    def _reveal_current_top(self,actor,key):
        from copy import deepcopy
        library=self._library_cards(actor)
        cards=[{'ref':library[-1].ref.to_json(),'name':self.definition(library[-1]).name}] if library else []
        observation={'id':key,'kind':'reveal_top','library_owner':actor,'observed_revision':self.revision,'cards':cards}
        for viewer in self.state.live_players:self.library_observations[viewer]=deepcopy(observation)
        if cards:self._event('cards_revealed',player=actor,refs=[cards[0]['ref']],names=[cards[0]['name']])
        return cards[0]['ref'] if cards else None

    def _execute_library(self,effect,frame,task):
        key=task['id'];actor=frame['controller']
        if isinstance(effect,ShuffleLibrary):
            for player in self._players(frame,effect.players):
                self.state.shuffle_library(player);self._player_event('library_shuffled',player)
        elif isinstance(effect,RevealTopPermanent):
            if 'reveal_plan' not in task:task['reveal_plan']={'players':list(self._players(frame,effect.players)),'index':0}
            plan=task['reveal_plan']
            while plan['index']<len(plan['players']):
                player=plan['players'][plan['index']]
                if 'top' not in plan:plan['top']=self._reveal_current_top(player,key+':'+str(plan['index']))
                if plan['top'] is not None:
                    ref=ObjectRef.from_json(plan['top'])
                    if self.effective(ref).types & {'Artifact','Battle','Creature','Enchantment','Land','Planeswalker'}:
                        self._move((ref,),Zone.BATTLEFIELD,{**frame,'controller':player},key+':entry:'+str(plan['index']),controller_mode='owner')
                plan['index']+=1;plan.pop('top',None)
        elif isinstance(effect,MayMill):
            if actor not in self.state.live_players:return True
            if 'mill_offer' not in task:
                amount=self._quantity(effect.amount,frame);library=self._library_cards(actor)
                if len(library)<amount:return True
                chosen=self._choose(key+':offer',actor,'optional_mill',
                    'Mill '+str(amount)+' cards?',(Option('yes','Mill'),Option('no','Do not mill')),1,1)
                task['mill_offer']=chosen[0].key=='yes'
                task['mill_refs']=[obj.ref.to_json() for obj in library[-amount:]] if amount and task['mill_offer'] else []
            if not task['mill_offer']:return True
            events=self._move(tuple(ObjectRef.from_json(ref) for ref in task['mill_refs']),
                Zone.GRAVEYARD,frame,key+':mill',cause='mill',controller_mode='owner')
            self._insert_zone_result(events,Zone.GRAVEYARD,frame,effect.effects)
        elif isinstance(effect,Explore):
            self._explore(effect,frame,task)
        else:return False
        return True

    def _explore(self,effect,frame,task):
        key=task['id']
        if 'explore_plan' not in task:
            remaining=[]
            for ref in self._refs(frame,effect.subject):
                try:obj=self.state.get(ref)
                except RulesViolation:obj=self.last_known.get(ref,(None,None))[0]
                if obj is None or obj.zone!=Zone.BATTLEFIELD or obj.phased:continue
                remaining.append({'ref':ref.to_json(),'actor':obj.controller,'name':self.definition(obj).name})
            task['explore_plan']={'remaining':remaining,'index':0}
        plan=task['explore_plan']
        while plan['remaining']:
            if 'current' not in plan:
                actor=next((p for p in self.turn_order() if any(row['actor']==p for row in plan['remaining'])),None)
                if actor is None:return
                rows=[row for row in plan['remaining'] if row['actor']==actor]
                options=tuple(Option(str(i),row['name'],ref=ObjectRef.from_json(row['ref'])) for i,row in enumerate(rows))
                selected=options if len(options)==1 else self._choose(key+':order:'+str(plan['index']),actor,
                    'explore_order','Choose the next permanent to explore before revealing the top card.',options,1,1)
                plan['current']=dict(rows[int(selected[0].key)])
            row=plan['current'];actor=row['actor'];ref=ObjectRef.from_json(row['ref']);step=key+':explore:'+str(plan['index'])
            if 'top' not in row:
                row['top']=self._reveal_current_top(actor,step)
                row['land']=row['top'] is not None and 'Land' in self.effective(ObjectRef.from_json(row['top'])).types
            if row['land']:
                self._move((ObjectRef.from_json(row['top']),),Zone.HAND,{**frame,'controller':actor},step+':land',controller_mode='owner')
            else:
                if not row.get('counter_done'):
                    if self._counter_counts(ref) is not None:self._put_counters(((ref,'+1/+1',1),),{**frame,'controller':actor},step+':counter')
                    row['counter_done']=True
                if row['top'] is not None:
                    if 'bury' not in row:
                        chosen=self._choose(step+':bury',actor,'explore_card','Leave the revealed card on top or put it into your graveyard?',
                            (Option('top','Leave on top'),Option('graveyard','Put into graveyard')),1,1)
                        row['bury']=chosen[0].key=='graveyard'
                    if row['bury']:self._move((ObjectRef.from_json(row['top']),),Zone.GRAVEYARD,{**frame,'controller':actor},step+':graveyard',controller_mode='owner')
            self._event('explored',player=actor,source=ref.to_json(),revealed=row['top'])
            plan['remaining']=[r for r in plan['remaining'] if r['ref']!=row['ref']]
            plan['index']+=1;plan.pop('current')

    def inspect_library_search(self,actor):
        """The searching player may look at the whole library, not only matches."""
        frame=self.resolving
        task=frame['tasks'][0] if frame is not None and frame['tasks'] else None
        effect=decode(task['effect']) if task is not None else None
        context={**frame,'values':task.get('values',frame.get('values',{}))} if task is not None else None
        search_actor=self._search_actor(effect,context) if task is not None and task['effect']['node'] in {'SearchLibrary','SearchByPlayer'} else None
        if (search_actor!=actor or actor not in self.state.live_players
                or isinstance(effect,SearchByPlayer) and effect.optional_search and not task.get('search_accepted')
                or effect.partition_player is not None and 'search_plan' in task):
            raise RulesViolation('No authorized library search inspection')
        objects=sorted(self.state.zone(actor,Zone.LIBRARY),key=lambda obj:(self.definition(obj).name,obj.ref.card_id))
        return tuple(Option(obj.ref.card_id+'@'+str(obj.ref.incarnation),self.definition(obj).name,ref=obj.ref) for obj in objects)

    def _search_actor(self,effect,frame):
        if not isinstance(effect,SearchByPlayer):return frame['controller']
        players=self._players(frame,effect.players)
        if len(players)>1:raise RulesViolation('Search requires one captured player')
        return players[0] if players else None

    def _search_library(self,effect,frame,task):
        actor=self._search_actor(effect,frame)
        if actor not in self.state.live_players:return
        if isinstance(effect,SearchByPlayer):
            if effect.optional_search and 'search_accepted' not in task:
                chosen=self._choose(task['id']+':search-offer',actor,'optional_search',
                    'Search your library?',(Option('yes','Search'),Option('no','Do not search')),1,1)
                task['search_accepted']=chosen[0].key=='yes'
            if effect.optional_search and not task['search_accepted']:return
            frame={**frame,'controller':actor}
        if 'search_plan' not in task:
            selector=self._bound_selector(effect.selector,frame);source=self._source(frame)
            # The source's controller may have changed since the ability began;
            # the searching player remains the captured ability controller.
            from dataclasses import replace
            source=replace(source,controller=actor)
            views=self.characteristics()
            eligible=[obj for obj in self.state.zone(actor,Zone.LIBRARY) if matches(selector,obj,views[obj.ref],source)]
            eligible.sort(key=lambda obj:(self.definition(obj).name,obj.ref.card_id))
            options=tuple(Option(obj.ref.card_id+'@'+str(obj.ref.incarnation),self.definition(obj).name,ref=obj.ref,group=self.definition(obj).name if effect.distinct_names else None) for obj in eligible)
            quality=any((selector.colors,selector.any_colors,selector.excluded_colors,selector.types,selector.any_subtypes,selector.any_types,selector.excluded_types,selector.subtypes,selector.excluded_subtypes,selector.supertypes,isinstance(selector,SupertypeSelector) and selector.excluded_supertypes,selector.characteristics,selector.commander is not None))
            maximum=min(effect.count,len({option.group for option in options}) if effect.distinct_names else len(options));minimum=0 if quality or effect.optional_find or effect.distinct_names else maximum
            split=effect.secondary_destination is not None
            prompt=(f'Search your library. Choose matching cards in order: the first {effect.primary_count} go to {effect.destination.value}'+(' tapped' if effect.tapped else '')+f'; the rest go to {effect.secondary_destination.value}'+(' tapped' if effect.secondary_tapped else '')+'. This menu does not show library order.') if split else ('Search your library. Choose matching cards in top-to-bottom order; this menu does not show library order.' if effect.destination==Zone.LIBRARY else 'Search your library. Choose matching cards; this menu does not show library order.')
            if effect.partition_player is not None:prompt='Search your library. Choose cards to reveal; a separate choice assigns their destinations. This menu does not show library order.'
            if effect.distinct_names:prompt+=' Choose no more than one card with each name.'
            selected=self._choose(task['id']+':search',actor,'library_search',
                prompt,options,minimum,maximum,ordered=(split and effect.partition_player is None) or effect.destination==Zone.LIBRARY,groups=effect.distinct_names)
            task['search_plan']={'refs':[option.ref.to_json() for option in selected]}
            self._player_event('library_searched',actor,found=len(selected))
            if effect.reveal and selected:
                self._event('cards_revealed',player=actor,refs=[option.ref.to_json() for option in selected],
                            names=[self.definition(self.state.get(option.ref)).name for option in selected])
        refs=tuple(ObjectRef.from_json(row) for row in task['search_plan']['refs'])
        if effect.partition_player is not None and 'partition' not in task['search_plan']:
            players=self._players(frame,effect.partition_player)
            if len(players)!=1:raise RulesViolation('Search partition requires one live choosing player')
            options=tuple(Option(ref.card_id+'@'+str(ref.incarnation),self.definition(self.state.get(ref)).name,ref=ref) for ref in refs)
            amount=min(effect.primary_count,len(options))
            chosen=options if len(options)<=amount else self._choose(task['id']+':partition',players[0],'search_partition',
                f'Choose {amount} revealed cards for {actor} to put into their {effect.destination.value}; the rest go to their {effect.secondary_destination.value}.',
                options,amount,amount)
            task['search_plan']['partition']=[option.ref.to_json() for option in chosen]
        if effect.destination!=Zone.LIBRARY:
            placements=None
            if effect.secondary_destination is not None:
                primary=set(ObjectRef.from_json(row) for row in task['search_plan']['partition']) if effect.partition_player is not None else set(refs[:effect.primary_count])
                placements={ref:((effect.destination,effect.tapped) if ref in primary else (effect.secondary_destination,effect.secondary_tapped)) for ref in refs}
            self._move(refs,effect.destination,frame,task['id']+':search-move',entry_tapped=effect.tapped,placements=placements)
        self.state.shuffle_library(actor)
        self._player_event('library_shuffled',actor)
        if effect.destination==Zone.LIBRARY and refs:
            # Shuffling retires inspection references, without changing zones.
            # Pin the chosen cards above a uniformly shuffled remainder.
            top=tuple(self.state.current(ref.card_id) for ref in refs)
            selected=set(top)
            middle=tuple(obj.ref for obj in self.state.zone(actor,Zone.LIBRARY) if obj.ref not in selected)
            self.state.reorder(actor,Zone.LIBRARY,middle+tuple(reversed(top)))
            observation={'id':task['id']+':search-top','kind':'search_top','observed_revision':self.revision,
                'cards':[{'ref':ref.to_json(),'name':self.definition(self.state.get(ref)).name} for ref in top]}
            from copy import deepcopy
            self.library_observations[actor]=deepcopy(observation)
            self._event('library_cards_looked',player=actor,observation=deepcopy(observation))

    def _choose_from_top(self,effect,frame,task):
        from copy import deepcopy
        from dataclasses import replace
        actor=frame['controller']
        if not effect.amount or actor not in self.state.live_players:return
        if 'looked' not in task:
            looked=tuple(reversed(self.state.zone(actor,Zone.LIBRARY)[-effect.amount:]))
            task['looked']=[{'ref':obj.ref.to_json(),'name':self.definition(obj).name} for obj in looked]
            observation={'id':task['id']+':choose_top','kind':'choose_top','library_owner':actor,'observed_revision':self.revision,'cards':task['looked']}
            recipients=self.state.players if effect.reveal else (actor,)
            for viewer in recipients:self.library_observations[viewer]=deepcopy(observation)
            self._event('library_cards_looked',player=actor,observation=deepcopy(observation))
            if effect.reveal and looked:
                self._event('cards_revealed',player=actor,refs=[obj.ref.to_json() for obj in looked],names=[self.definition(obj).name for obj in looked])
        if 'top_selection' not in task:
            source=replace(self._source(frame),controller=actor);views=self.characteristics()
            options=[]
            for row in task['looked']:
                ref=ObjectRef.from_json(row['ref']);obj=self.state.get(ref)
                if matches(effect.selector,obj,views[ref],source):options.append(Option(ref.card_id+'@'+str(ref.incarnation),row['name'],ref=ref))
            chosen=self._choose(task['id']+':choose_top',actor,'choose_top',
                'Choose matching cards to put '+('into your hand' if effect.destination==Zone.HAND else 'onto the battlefield'+(' tapped' if effect.tapped else ''))+'. The remaining inspected cards go '+('to your graveyard.' if effect.remainder=='graveyard' else 'on the bottom in random order.'),
                tuple(options),0,min(effect.count,len(options))) if options and effect.count else ()
            task['top_selection']=[option.ref.to_json() for option in chosen]
        if not task.get('selection_moved'):
            selected=tuple(ObjectRef.from_json(row) for row in task['top_selection'])
            self._move(selected,effect.destination,frame,task['id']+':choose-top-selected',entry_tapped=effect.tapped)
            task['selection_moved']=True
        # Keep the original inspected window through all replacement boundaries.
        # Cards actually removed by the first instruction are no longer in it.
        present={obj.ref for obj in self.state.zone(actor,Zone.LIBRARY)}
        remaining=tuple(ObjectRef.from_json(row['ref']) for row in task['looked'] if ObjectRef.from_json(row['ref']) in present)
        if effect.remainder=='graveyard':
            self._move(remaining,Zone.GRAVEYARD,frame,task['id']+':choose-top-rest')
        else:
            self.state.random_bottom(actor,remaining)

    def _arrange_top(self,effect,frame,task,kind):
        actor=frame['controller']
        if not effect.amount or actor not in self.state.live_players:return
        if 'arrangement' not in task:
            if 'looked' not in task:
                library=self.state.zone(actor,Zone.LIBRARY)
                looked=tuple(reversed(library[-effect.amount:]))
                task['looked']=[{'ref':obj.ref.to_json(),'name':self.definition(obj).name} for obj in looked]
                observation={'id':task['id']+':'+kind,'kind':kind,'observed_revision':self.revision,'cards':task['looked']}
                from copy import deepcopy
                self.library_observations[actor]=deepcopy(observation)
                self._event('library_cards_looked',player=actor,observation=deepcopy(observation))
            looked=task['looked']
            top=();other=()
            if looked:
                options=tuple(Option(row['ref']['card_id']+'@'+str(row['ref']['incarnation']),row['name'],ref=ObjectRef.from_json(row['ref'])) for row in looked)
                if kind=='look_top':
                    prompt='Order these cards from top to bottom.'
                else:
                    label='BOTTOM' if kind=='scry' else 'GRAVEYARD'
                    options+=(Option(label.lower()+'-divider',label+': cards after this divider go '+('on the bottom' if kind=='scry' else 'to your graveyard')),)
                    prompt='Order every card and the '+label+' divider. Cards before it stay on top; cards after it go '+('on the bottom' if kind=='scry' else 'to your graveyard')+'. Both groups read top to bottom.'
                selected=options if len(options)==1 else self._choose(task['id']+':'+kind,actor,kind,prompt,options,len(options),len(options),ordered=True)
                divider=len(selected) if kind=='look_top' else next(i for i,option in enumerate(selected) if option.ref is None)
                top=tuple(option.ref for option in selected[:divider])
                other=tuple(option.ref for option in selected[divider+1:])
            # Retain the exact authorized partition through destination choices;
            # never repeat inspection or change the set of looked-at cards.
            task['arrangement']={'top':[r.to_json() for r in top],'other':[r.to_json() for r in other]}
        plan=task['arrangement'];top=tuple(ObjectRef.from_json(r) for r in plan['top']);other=tuple(ObjectRef.from_json(r) for r in plan['other'])
        if kind=='surveil':
            self._move(other,Zone.GRAVEYARD,frame,task['id']+':surveil-move',cause='surveil')
        library=self.state.zone(actor,Zone.LIBRARY);present={obj.ref for obj in library}
        top=tuple(ref for ref in top if ref in present)
        bottom=other if kind=='scry' else ()
        ordered=set(top)|set(bottom)
        middle=tuple(obj.ref for obj in library if obj.ref not in ordered)
        if top or bottom:self.state.reorder(actor,Zone.LIBRARY,tuple(reversed(bottom))+middle+tuple(reversed(top)))
        if kind=='look_top':self._event('library_looked',player=actor,amount=effect.amount)
        else:self._player_event('scried' if kind=='scry' else 'surveilled',actor,amount=effect.amount)
