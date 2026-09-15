"""Actor-bound, fixed-quantity own-library searches with deterministic shuffling.

Search replacements and opponents' libraries remain separate unsupported
semantics. Tapped search placement modifies the initial entry proposal. Scry partitions only the authorized top
cards in one ordered choice without showing the rest of the library. Production visibility adapters
must keep search choices, shuffle seeds and physical library order private.
"""
from .rules_state import ObjectRef,Zone,RulesViolation
from .rules_choices import Option
from .rules_characteristics import matches


class LibraryRules:
    def inspect_library_search(self,actor):
        """The searching player may look at the whole library, not only matches."""
        frame=self.resolving
        if (frame is None or frame['controller']!=actor or actor not in self.state.live_players
                or not frame['tasks'] or frame['tasks'][0]['effect']['node']!='SearchLibrary'
                or frame['tasks'][0]['effect'].get('partition_player') is not None and 'search_plan' in frame['tasks'][0]):
            raise RulesViolation('No authorized library search inspection')
        objects=sorted(self.state.zone(actor,Zone.LIBRARY),key=lambda obj:(self.definition(obj).name,obj.ref.card_id))
        return tuple(Option(obj.ref.card_id+'@'+str(obj.ref.incarnation),self.definition(obj).name,ref=obj.ref) for obj in objects)

    def _search_library(self,effect,frame,task):
        actor=frame['controller']
        if actor not in self.state.live_players:return
        if 'search_plan' not in task:
            selector=effect.selector;source=self._source(frame)
            # The source's controller may have changed since the ability began;
            # the searching player remains the captured ability controller.
            from dataclasses import replace
            source=replace(source,controller=actor)
            views=self.characteristics()
            eligible=[obj for obj in self.state.zone(actor,Zone.LIBRARY) if matches(selector,obj,views[obj.ref],source)]
            eligible.sort(key=lambda obj:(self.definition(obj).name,obj.ref.card_id))
            options=tuple(Option(obj.ref.card_id+'@'+str(obj.ref.incarnation),self.definition(obj).name,ref=obj.ref,group=self.definition(obj).name if effect.distinct_names else None) for obj in eligible)
            quality=any((selector.colors,selector.any_colors,selector.excluded_colors,selector.types,selector.any_subtypes,selector.any_types,selector.excluded_types,selector.subtypes,selector.excluded_subtypes,selector.supertypes,selector.characteristics,selector.commander is not None))
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
