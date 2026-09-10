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
                or not frame['tasks'] or frame['tasks'][0]['effect']['node']!='SearchLibrary'):
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
            options=tuple(Option(obj.ref.card_id+'@'+str(obj.ref.incarnation),self.definition(obj).name,ref=obj.ref) for obj in eligible)
            quality=any((selector.colors,selector.any_colors,selector.excluded_colors,selector.types,selector.any_subtypes,selector.any_types,selector.excluded_types,selector.subtypes,selector.excluded_subtypes,selector.supertypes,selector.characteristics,selector.commander is not None))
            maximum=min(effect.count,len(options));minimum=0 if quality or effect.optional_find else maximum
            selected=self._choose(task['id']+':search',actor,'library_search',
                ('Search your library. Choose matching cards in top-to-bottom order; this menu does not show library order.' if effect.destination==Zone.LIBRARY else 'Search your library. Choose matching cards; this menu does not show library order.'),options,minimum,maximum,ordered=effect.destination==Zone.LIBRARY)
            task['search_plan']={'refs':[option.ref.to_json() for option in selected]}
            self._player_event('library_searched',actor,found=len(selected))
            if effect.reveal and selected:
                self._event('cards_revealed',player=actor,refs=[option.ref.to_json() for option in selected],
                            names=[self.definition(self.state.get(option.ref)).name for option in selected])
        refs=tuple(ObjectRef.from_json(row) for row in task['search_plan']['refs'])
        if effect.destination!=Zone.LIBRARY:
            self._move(refs,effect.destination,frame,task['id']+':search-move',entry_tapped=effect.tapped)
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
