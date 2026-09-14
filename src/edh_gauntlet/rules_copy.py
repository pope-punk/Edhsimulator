"""Copiable token values, deterministic derived definitions and simultaneous fight."""
import hashlib
import json
from collections import ChainMap
from dataclasses import replace
from types import MappingProxyType
from .rules_program import CardProgram,CopyTokens,CopyPermanent,SelectBySubtype,PowerDamage,CreateTokens,WithCreatedTokens,Fight,encode,decode,validate
from .rules_state import RulesViolation,Zone,ObjectRef
from .rules_choices import Option
from .rules_subtypes import SUBTYPE_SETS
from .rules_creature_types import CREATURE_TYPES


class CopyRules:
    def _init_copy_registry(self,records):
        self._base_definitions=self.definitions
        self._derived_definitions={}
        self.definitions=MappingProxyType(ChainMap(self._derived_definitions,self._base_definitions))
        self._base_trigger_index=self._trigger_index
        self._derived_trigger_index={}
        self._trigger_index=MappingProxyType(ChainMap(self._derived_trigger_index,self._base_trigger_index))
        self.copy_programs=[]
        if not isinstance(records,(tuple,list)):raise RulesViolation('Invalid copy registry')
        for row in records:
            if not isinstance(row,dict) or set(row)!={'parent','added_types','changes','definition_id','retained_activation'}:
                raise RulesViolation('Invalid copy lineage')
            if row['parent'] not in self.definitions:raise RulesViolation('Unknown copy parent')
            if not isinstance(row['added_types'],list) or any(t not in {'Artifact','Battle','Creature','Enchantment','Instant','Kindred','Land','Planeswalker','Sorcery'} for t in row['added_types']):
                raise RulesViolation('Invalid copied type additions')
            if not isinstance(row['changes'],dict) or set(row['changes'])!={'nonlegendary','power','toughness','colors','creature_types','abilities'}:
                raise RulesViolation('Invalid copy exceptions')
            changes={k:decode(v) for k,v in row['changes'].items()}
            before=len(self.copy_programs)
            program=self._register_copy_program(row['parent'],tuple(row['added_types']),changes,decode(row['retained_activation']))
            if program.definition_id!=row['definition_id'] or len(self.copy_programs)!=before+1:
                raise RulesViolation('Invalid copy registry identity')

    def _register_copy_program(self,parent,added_types,changes,retained_activation=None):
        validate(CardProgram('copy:validation','Copy validation',('Artifact',),
            spell_effects=(CopyTokens('source',**changes),)))
        original=self.definitions[parent]
        attrs={'types':tuple(dict.fromkeys(original.types+tuple(added_types)))}
        if changes['nonlegendary']:attrs['supertypes']=tuple(s for s in original.supertypes if s!='Legendary')
        if changes['power'] is not None:
            attrs.update(power=changes['power'],toughness=changes['toughness'],characteristic_pt=None)
        if changes['colors'] is not None:attrs['colors']=changes['colors']
        if changes['creature_types'] is not None:
            attrs['subtypes']=tuple(t for t in original.subtypes if t not in CREATURE_TYPES)+changes['creature_types']
            attrs['all_subtype_sets']=tuple(t for t in original.all_subtype_sets if t!='creature')
        abilities=list(original.abilities)
        for ability in changes['abilities']:
            ids={a.ability_id for a in abilities};ability_id=ability.ability_id;number=1
            while ability_id in ids:
                ability_id=ability.ability_id+':copy:'+str(number);number+=1
            abilities.append(replace(ability,ability_id=ability_id))
        attrs['abilities']=tuple(abilities)
        if retained_activation is not None:
            validate(CardProgram('copy:retained-review','Retained activation',('Artifact',),activated=(retained_activation,)))
            activated=list(original.activated);ids={a.ability_id for a in activated}
            ability_id=retained_activation.ability_id;number=1
            while ability_id in ids:
                ability_id=retained_activation.ability_id+':copy:'+str(number);number+=1
            attrs['activated']=tuple(activated)+(replace(retained_activation,ability_id=ability_id),)
        program=replace(original,definition_id='copy:values',**attrs)
        digest=hashlib.sha256(json.dumps(encode(program),sort_keys=True,separators=(',',':')).encode()).hexdigest()
        program=validate(replace(program,definition_id='copy:'+digest))
        existing=self.definitions.get(program.definition_id)
        if existing is not None:
            if existing!=program:raise RulesViolation('Copy definition collision')
            return existing
        grouped={}
        for ability in program.abilities:grouped.setdefault(ability.event.kind,[]).append(ability)
        self._derived_definitions[program.definition_id]=program
        self._derived_trigger_index[program.definition_id]=MappingProxyType({kind:tuple(rows) for kind,rows in grouped.items()})
        self._has_attachment_observers|=any(a.event.subject=='attached' for a in program.abilities)
        self._has_tap_triggers|=any(a.event.kind=='becomes_tapped' for a in program.abilities)
        self._has_state_triggers|=any(a.event.kind=='counter_state' for a in program.abilities)
        self.copy_programs.append({'parent':parent,'added_types':list(added_types),
            'changes':{k:encode(v) for k,v in changes.items()},'definition_id':program.definition_id,
            'retained_activation':encode(retained_activation)})
        return program

    def _copy_information(self,ref):
        try:return self.state.get(ref)
        except RulesViolation:
            known=self.last_known.get(ref)
            return known[0] if known is not None else None

    def _execute_copy(self,effect,frame,key):
        if isinstance(effect,SelectBySubtype):
            choice=self._choose(key+':subtype',frame['controller'],'subtype',
                'Choose a nonbasic land type.',tuple(Option(t,t) for t in sorted(SUBTYPE_SETS[effect.subtype_set])),1,1)[0]
            selector=replace(effect.selector,subtypes=tuple(dict.fromkeys(effect.selector.subtypes+(choice.key,))))
            frame['bindings']['selected']=[obj.ref.to_json() for obj in self._query(selector,frame)]
            self._insert(frame,effect.effects)
            return True
        if isinstance(effect,CopyPermanent):
            originals=self._refs(frame,effect.original)
            if len(originals)!=1:return True
            original=self._copy_information(originals[0])
            if original is None:return True
            recipients=[]
            for ref in self._refs(frame,effect.subject):
                try:obj=self.state.get(ref)
                except RulesViolation:continue
                if obj.zone==Zone.BATTLEFIELD and not obj.phased:recipients.append(ref)
            if not recipients:return True
            retained=decode(frame.get('activated_program')) if effect.retain_activation else None
            if effect.retain_activation and retained is None:raise RulesViolation('Missing captured activation')
            changes={name:getattr(CopyTokens('source'),name) for name in ('nonlegendary','power','toughness','colors','creature_types','abilities')}
            program=self._register_copy_program(original.effective_definition,original.effective_add_types,changes,retained)
            refs=self.state.apply_copy(recipients,program.definition_id,until_end_of_turn=effect.until_end_of_turn)
            self._event('permanents_copied',refs=[ref.to_json() for ref in refs],original=original.ref.to_json(),
                definition_id=program.definition_id,until_end_of_turn=effect.until_end_of_turn)
            return True
        if isinstance(effect,PowerDamage):
            sources=self._refs(frame,effect.source);targets=self._refs(frame,effect.target)
            if len(sources)!=1 or len(targets)!=1:return True
            try:source=self.state.get(sources[0]);target=self.state.get(targets[0])
            except RulesViolation:return True
            if any(obj.zone!=Zone.BATTLEFIELD or obj.phased for obj in (source,target)):return True
            view=self.effective(source.ref);other=self.effective(target.ref)
            if 'Creature' not in view.types or 'Creature' not in other.types:return True
            amount=max(0,view.power or 0);creature_damage=amount
            if effect.trample_excess and 'trample' in view.keywords:
                lethal=max(0,(other.toughness or 0)-target.damage_marked)
                if 'deathtouch' in view.keywords:lethal=min(lethal,1)
                creature_damage=min(amount,lethal)
            assignments=[(source,target.ref,creature_damage)]
            if amount>creature_damage:assignments.append((source,target.controller,amount-creature_damage))
            self._deal_damage(assignments)
            return True
        if isinstance(effect,Fight):
            first=self._refs(frame,effect.first);second=self._refs(frame,effect.second)
            if len(first)!=1 or len(second)!=1:return True
            creatures=[]
            for ref in (first[0],second[0]):
                try:obj=self.state.get(ref)
                except RulesViolation:return True
                view=self.effective(ref)
                if obj.zone!=Zone.BATTLEFIELD or obj.phased or 'Creature' not in view.types:return True
                creatures.append((obj,max(0,view.power or 0)))
            (a,ap),(b,bp)=creatures
            self._deal_damage([(a,b.ref,ap),(b,a.ref,bp)])
            return True
        if not isinstance(effect,CopyTokens):return False
        if not self._quantity(effect.amount,frame):return True
        if effect.subject=='equipped':
            holder=self._copy_information(self._source(frame).ref)
            refs=() if holder is None or holder.attached_to is None else (holder.attached_to,)
        else:refs=self._refs(frame,effect.subject)
        if len(refs)!=1:return True
        obj=self._copy_information(refs[0])
        if obj is None:return True
        original=self.definition(obj)
        changes={name:getattr(effect,name) for name in ('nonlegendary','power','toughness','colors','creature_types','abilities')}
        program=self._register_copy_program(original.definition_id,obj.effective_add_types,changes)
        token_effect=WithCreatedTokens(program,effect.amount,'controller',effect.effects)
        self._execute(frame,{'id':key,'effect':encode(token_effect)})
        return True
