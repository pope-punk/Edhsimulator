"""Face choices, transforming returns, Saga chapters and Siege designations.

The physical definition never changes. A face is an object characteristic on the
stack or battlefield; zone changes otherwise restore the physical front face.
"""
from dataclasses import replace
from .rules_state import ObjectRef,RulesObject,Zone,RulesViolation
from .rules_choices import Option
from .rules_characteristics import matches
from .rules_replacements import ReplacementCandidate
from .rules_program import (RoomProgram,ReadAheadProgram,DoubleFacedProgram,BattleProgram,ChapterAbility,EntryCounters,
    ReturnTransformed,Transform,DiscardThenTrigger,SpellTaxUntilNextTurn,ChooseCounter,
    IfOtherPermanent,DefeatBattle,AbilityProgram,EventPattern,AddCounters,Selector,
    encode,decode)


class FaceRules:
    def _validate_face_state(self):
        for obj in self.state.objects():
            if obj.back_face and not isinstance(self.definitions[obj.definition],DoubleFacedProgram):raise RulesViolation('Back face lacks a physical paired definition')
        window=self.phase_action
        if window is not None:
            if (not isinstance(window,dict) or set(window) not in ({'id','actor'},{'id','actor','sources'})
                    or type(window['id']) is not str or not window['id'] or window['actor']!=self.active or self.phase!='precombat_main'):
                raise RulesViolation('Invalid lore turn action')
            if 'sources' in window:
                refs=[ObjectRef.from_json(r) for r in window['sources']]
                if len(set(refs))!=len(refs) or any(self.state.get(r).zone!=Zone.BATTLEFIELD for r in refs):raise RulesViolation('Invalid lore recipients')
        if not isinstance(self.timed_spell_taxes,list):raise RulesViolation('Invalid timed spell taxes')
        ids=set()
        for row in self.timed_spell_taxes:
            if (not isinstance(row,dict) or set(row)!={'id','source','controller','selector','generic'} or type(row['id']) is not str or not row['id'] or row['id'] in ids or row['controller'] not in self.state.players):raise RulesViolation('Invalid timed spell tax')
            source=RulesObject.from_json(row['source'])
            if source.controller!=row['controller']:raise RulesViolation('Invalid timed tax controller')
            from .rules_program import CardProgram,validate
            validate(CardProgram('tax-validation','Tax validation',('Instant',),spell_effects=(SpellTaxUntilNextTurn(decode(row['selector']),row['generic']),)))
            ids.add(row['id'])

    def _announced_face(self,obj,face,*,resolution_cast=False,land=False):
        physical=self.definitions[obj.definition]
        if isinstance(physical,RoomProgram):
            if face not in {'front','left','right'} or land or obj.token or obj.spell_copy:raise RulesViolation('Choose a castable Room door')
            return replace(obj,room_cast='left' if face=='front' else face)
        if type(face) is not str or face not in {'front','back'}:raise RulesViolation('Choose front or back')
        if obj.token or obj.spell_copy:raise RulesViolation('A token or spell copy cannot be played as a card')
        if face=='back':
            if not isinstance(physical,DoubleFacedProgram):raise RulesViolation('This card has no back face')
            if physical.layout!='modal' and not (resolution_cast and self.resolution_cast.get('transformed')):
                raise RulesViolation('A transforming back face needs an explicit casting permission')
        elif resolution_cast and self.resolution_cast.get('transformed'):
            raise RulesViolation('This permission casts only the transformed face')
        return replace(obj,back_face=face=='back')

    def _intrinsic_entry_counters(self,proposal,entering,view):
        result=[]
        if 'Saga' in view.subtypes and 'Enchantment' in view.types:
            rule=EntryCounters('intrinsic-lore','lore',1)
            if 'intrinsic:lore' not in proposal.used:
                result.append(ReplacementCandidate('intrinsic:lore','Saga lore counter','entry_counters',3,entering.controller,rule,entering))
        program=self.definitions[entering.effective_definition]
        if 'Battle' in view.types and isinstance(program,BattleProgram) and program.defense:
            rule=EntryCounters('intrinsic-defense','defense',program.defense)
            if 'intrinsic:defense' not in proposal.used:
                result.append(ReplacementCandidate('intrinsic:defense','Battle defense counters','entry_counters',3,entering.controller,rule,entering))
        return tuple(result)

    def _entry_protector(self,proposal,frame,key):
        entering,view=self._proposal_view(proposal)
        if 'Battle' not in view.types:return None
        choices=tuple(p for p in self.state.live_players if 'Siege' not in view.subtypes or p!=entering.controller)
        if not choices:return None
        chosen=self._choose(key,entering.controller,'battle_protector','Choose a player to protect this battle.',
            tuple(Option(p,p) for p in choices),1,1)
        return chosen[0].key

    def _chapters(self,obj):
        return tuple(a for a in self._trigger_abilities(obj,'counters_added') if isinstance(a,ChapterAbility))

    def _continue_phase_action(self):
        window=self.phase_action;actor=window['actor']
        if 'sources' not in window:
            window['sources']=[obj.ref.to_json() for obj in self.state.objects(Zone.BATTLEFIELD,controller=actor)
                if not obj.phased and 'Saga' in self.effective(obj.ref).subtypes and 'Enchantment' in self.effective(obj.ref).types and self._chapters(obj)]
        refs=tuple(ObjectRef.from_json(r) for r in window['sources'])
        if refs:
            source=self.state.get(refs[0])
            frame={'source':source.to_json(),'controller':actor,'bindings':{},'values':{},'chosen_x':0}
            self._put_counters(((ref,'lore',1) for ref in refs),frame,window['id'])
        self.phase_action=None
        self._collect_step('precombat_main')

    def _source_ability_pending(self,ref,marker=None):
        for trigger in self.pending_triggers:
            if trigger['source']['ref']==ref.to_json() and (marker is None or trigger.get('values',{}).get(marker)):return True
        frames=tuple(self.stack)+((self.resolving,) if self.resolving is not None else ())
        if self.resolution_cast:frames+=(self.resolution_cast['parent'],)
        if self.mana_payment:frames+=(self.mana_payment['parent'],)
        return any(f['source']['ref']==ref.to_json() and (f.get('triggered') if marker is None else f.get('values',{}).get(marker)) for f in frames)

    def _collect_defeated_battles(self,before):
        for old in before:
            if not dict(old.counters).get('defense',0):continue
            try:obj=self.state.get(old.ref)
            except RulesViolation:continue
            if obj.zone!=Zone.BATTLEFIELD or obj.phased or dict(obj.counters).get('defense',0):continue
            view=self.effective(obj.ref)
            if 'Battle' in view.types and 'Siege' in view.subtypes and not view.abilities_removed:
                ability=AbilityProgram('intrinsic-siege-defeat',EventPattern('step_began',step='upkeep'),(DefeatBattle(),))
                self._trigger(obj,ability,values={'siege_defeat':True})

    def _face_sba(self,obj,view):
        """Return the zone-change cause, or None; designation choices stay pure."""
        if 'Battle' in view.types:
            if not dict(obj.counters).get('defense',0) and not self._source_ability_pending(obj.ref):
                return 'permanent_sba'
            protected=(obj.protector in self.state.live_players and ('Siege' not in view.subtypes or obj.protector!=obj.controller))
            attacked=self.combat is not None and any(row.get('defender_object',{}).get('ref')==obj.ref.to_json()
                and self._defender_present(row) for row in self.combat['attackers'])
            if not protected and not attacked:
                legal=tuple(p for p in self.state.live_players if 'Siege' not in view.subtypes or p!=obj.controller)
                if not legal:return 'permanent_sba'
                return 'protector'
        if 'Enchantment' in view.types and 'Saga' in view.subtypes:
            chapters=self._chapters(obj)
            if chapters and dict(obj.counters).get('lore',0)>=max(a.chapter for a in chapters) and not self._source_ability_pending(obj.ref,'saga_chapter'):
                return 'sacrifice'
        return None

    def _temporary_spell_tax(self,obj,view):
        total=0
        for row in self.timed_spell_taxes:
            source=RulesObject.from_json(row['source'])
            if matches(decode(row['selector']),obj,view,source):total+=row['generic']
        return total

    def _expire_spell_taxes(self,active):
        previous=self.state.turn_active
        if previous is None:crossed={active}
        else:
            players=self.state.players;start=players.index(previous);end=players.index(active)
            distance=(end-start)%len(players) or len(players)
            crossed={players[(start+i)%len(players)] for i in range(1,distance+1)}
        expired=[r['id'] for r in self.timed_spell_taxes if r['controller'] in crossed]
        self.timed_spell_taxes[:]=[r for r in self.timed_spell_taxes if r['id'] not in expired]
        if expired:self._event('spell_taxes_expired',effects=expired)

    def _execute_face_instruction(self,effect,frame,task):
        key=task['id'];actor=frame['controller'];source=self._source(frame)
        if isinstance(effect,(ReturnTransformed,DefeatBattle)):
            if 'face_exile' not in task:
                refs=(source.ref,) if isinstance(effect,DefeatBattle) else self._refs(frame,effect.subject)
                refs=tuple(ref for ref in refs if any(o.ref==ref and not o.phased for o in self.state.objects(Zone.BATTLEFIELD)))
                events=self._move(refs,Zone.EXILE,frame,key+':exile',controller_mode='owner')
                task['face_exile']=[e.after.ref.to_json() for e in events if e.after.zone==Zone.EXILE]
            refs=[]
            for value in task['face_exile']:
                try:obj=self.state.get(ObjectRef.from_json(value))
                except RulesViolation:continue
                physical=self.definitions[obj.definition]
                if obj.zone==Zone.EXILE and not obj.token and not obj.spell_copy and isinstance(physical,DoubleFacedProgram) and physical.layout=='transform':
                    refs.append(obj.ref)
            if isinstance(effect,DefeatBattle):
                if refs or self.resolution_cast is not None and self.resolution_cast['id']==key:
                    self._offer_resolution_cast(frame,task,2**31-1,Zone.EXILE,refs,transformed=True)
            elif refs:
                self._move(tuple(refs),Zone.BATTLEFIELD,frame,key+':return',controller_mode=effect.controller,back_face=True)
        elif isinstance(effect,Transform):
            for ref in self._refs(frame,effect.subject):
                try:obj=self.state.get(ref)
                except RulesViolation:continue
                physical=self.definitions[obj.definition]
                if obj.zone==Zone.BATTLEFIELD and not obj.phased and isinstance(physical,DoubleFacedProgram) and physical.layout=='transform':
                    self.state.set_face(ref,not obj.back_face)
                    self._event('transformed',source=ref.to_json(),back_face=not obj.back_face)
        elif isinstance(effect,DiscardThenTrigger):
            if 'discard_offer' not in task:
                options=self._options(self.state.zone(actor,Zone.HAND)) if actor in self.state.live_players else ()
                chosen=self._choose(key+':discard',actor,'reflexive_discard','You may discard a card.',options,0,1) if options else ()
                task['discard_offer']=chosen[0].ref.to_json() if chosen else None
            if task['discard_offer'] is not None:
                events=self._move((ObjectRef.from_json(task['discard_offer']),),Zone.GRAVEYARD,frame,key+':discard',cause='discard',controller_mode='owner')
                if events:
                    ability=AbilityProgram('reflexive:'+key,EventPattern('step_began',step='upkeep'),effect.effects,targets=effect.targets)
                    self._trigger(replace(source,controller=actor),ability)
        elif isinstance(effect,SpellTaxUntilNextTurn):
            self.timed_spell_taxes.append({'id':key,'source':replace(source,controller=actor).to_json(),
                'controller':actor,'selector':encode(effect.selector),'generic':effect.generic})
            self._event('spell_tax_created',effect=key,controller=actor,generic=effect.generic)
        elif isinstance(effect,ChooseCounter):
            refs=tuple(ref for ref in self._refs(frame,effect.subject)
                if any(o.ref==ref and not o.phased for o in self.state.objects(Zone.BATTLEFIELD)))
            if refs:
                chosen=self._choose(key+':kind',actor,'counter_kind','Choose the kind of counter.',
                    tuple(Option(kind,kind) for kind in effect.kinds),1,1)[0].key
                self._put_counters(((ref,chosen,1) for ref in refs),frame,key+':counter')
        elif isinstance(effect,IfOtherPermanent):
            excluded=set(self._refs(frame,effect.excluded))|{source.ref}
            if any(obj.ref not in excluded for obj in self._query(effect.selector,frame)):self._insert(frame,effect.effects)
        else:return False
        return True
