"""Announcement-bound spell/ability copies and explicitly spent mana riders."""
from copy import deepcopy
from dataclasses import replace
import json
from .rules_state import RulesObject,RulesViolation,ObjectRef,PlayerRef,Zone,target_from_json
from .rules_characteristics import base
from .rules_program import CopyCast,CopyCaptured,SpecialMana,CleanupCast,GraveyardAlternativeCost,Move,AbilityProgram,EventPattern,decode,encode
from .rules_choices import Option


class SpellCopyRules:
    def _tagged_resources(self,actor,units,*,quote=None,source=None):
        records=self.state.tagged_payment(actor,units)
        for _,raw in records:
            row=json.loads(raw)
            if row['rider']=='legendary':
                if quote is None or quote.kind!='cast' or 'Legendary' not in base(source,self.definitions).supertypes:
                    raise RulesViolation('This mana can only cast a legendary spell')
        return records

    def _copy_blueprint(self,frame):
        # Costs, choices and the spell's instructions are copiable. Mana riders,
        # flashback's stack-exit replacement and execution progress are not.
        fields=('source','controller','spell','targets','target_spec','bindings','values',
            'entry_flags','chosen_x','mode_groups','target_groups','target_controller_groups',
            'kicker','replicate','alternative_id','activated_program','ability_id','triggered',
            'source_must_remain','intervening_if','announced_source')
        result={key:deepcopy(frame[key]) for key in fields if key in frame}
        result['tasks']=[{k:deepcopy(v) for k,v in task.items() if k!='id'} for task in frame['tasks']]
        if result['spell']:
            specification=self.definition(RulesObject.from_json(result['source'])).cast
            # Actual casting history is not a copied cost decision. Necromancy
            # copies were never cast outside sorcery timing; copies of escaped
            # spells were never cast from a graveyard (CR 702.138b, 707.10).
            if isinstance(specification,CleanupCast):
                result['tasks']=[{'effect':encode(Move('source',Zone.BATTLEFIELD))}]
            alternative=next((a for a in specification.alternatives if a.alternative_id==result.get('alternative_id')),None)
            if isinstance(alternative,GraveyardAlternativeCost):
                result['entry_flags']=[flag for flag in result['entry_flags'] if flag not in alternative.entry_flags]
        return result

    def _queue_captured_copy(self,source,blueprint,kind='single',amount=1):
        ability=AbilityProgram('copy:'+kind,EventPattern('spell_cast'),(CopyCaptured(kind,amount),))
        self._trigger(source,ability,values={'captured_frame':deepcopy(blueprint)})

    def _collect_copy_announcement(self,quote,resources,source,frame,mana_ability):
        blueprint=self._copy_blueprint(frame) if frame is not None and not mana_ability else None
        if quote.kind=='cast':
            specification=self.definition(source).cast
            if isinstance(specification,CopyCast):
                frame['replicate']=quote.replicate
                blueprint['replicate']=quote.replicate
                if specification.copy_kind=='demonstrate' or quote.replicate:
                    self._queue_captured_copy(source,blueprint,specification.copy_kind,quote.replicate or 1)
        batches=set()
        for _,raw in resources.tagged_mana:
            row=json.loads(raw)
            if row['rider']=='legendary':frame['cannot_be_countered']=True
            if row['rider']=='copy' and row['batch'] not in batches:
                batches.add(row['batch']);self.state.consume_mana_rider(quote.actor,row['batch'])
                # The mana ability may already have resolved. Its source and the
                # paid action are retained independently of their live objects.
                self._queue_captured_copy(RulesObject.from_json(row['source']),blueprint)
        if batches:self._event('mana_copy_riders_spent',player=quote.actor,batches=sorted(batches))

    def _retarget_copy(self,copy,key,controller):
        groups=copy.get('mode_groups') or copy.get('target_groups') or [copy]
        for index,group in enumerate(groups):
            old=group['targets'];spec=decode(group['target_spec'])
            if not old or spec is None:continue
            context={**copy,'controller':controller,'targets':old}
            legal=self._target_options(spec,context)
            options=[];controller_groups=[];retained=[];bounds=[]
            records=group.get('target_controller_groups',copy.get('target_controller_groups',[]))
            original_groups={ObjectRef.from_json(row['ref']):row['controller'] for row in records}
            for position,value in enumerate(old):
                slot=str(position);bounds.append((slot,1,1));ref=target_from_json(value)
                # Keeping a target is expressly allowed even if it is now illegal.
                options.append(Option(slot+':keep','Target '+str(position+1)+': keep original',
                    ref=ref if isinstance(ref,ObjectRef) else None,
                    player=ref.player if isinstance(ref,PlayerRef) else None,group=slot))
                current_group=None
                if spec.group_by_controller:
                    if isinstance(ref,PlayerRef):current_group=ref.player
                    else:
                        try:current_group=self.state.get(ref).controller
                        except RulesViolation:current_group=original_groups.get(ref)
                controller_groups.append(current_group);retained.append(True)
                for option in legal:
                    options.append(replace(option,key=slot+':'+option.key,
                        label='Target '+str(position+1)+': '+option.label,group=slot))
                    controller_groups.append(option.group if spec.group_by_controller else None);retained.append(False)
            chosen=self._choose(key+':targets:'+str(index),controller,'copy_targets',
                'Choose one option for each original target. Keep any target or choose a legal replacement.',
                options,len(old),len(old),group_bounds=tuple(bounds),
                copy_groups=tuple(controller_groups),retained=tuple(retained))
            by_slot={int(option.group):option for option in chosen}
            new=[(by_slot[i].ref or PlayerRef(by_slot[i].player)).to_json() for i in range(len(old))]
            division=copy.get('values',{}).get('counter_division')
            if division:
                remap={json.dumps(a,sort_keys=True):b for a,b in zip(old,new)}
                for row in division:row['ref']=deepcopy(remap.get(json.dumps(row['ref'],sort_keys=True),row['ref']))
            if spec.group_by_controller and spec.maximum is None:
                changed=[]
                for i in range(len(old)):
                    option=by_slot[i];ref=option.ref
                    if ref is None:continue
                    if option.key.endswith(':keep') and ref in original_groups:owner=original_groups[ref]
                    else:
                        try:owner=self.state.get(ref).controller
                        except RulesViolation:continue
                    changed.append({'ref':ref.to_json(),'controller':owner})
                group['target_controller_groups']=changed
            group['targets']=new
        if groups!=[copy]:copy['targets']=[value for group in groups for value in group['targets']]

    def _materialize_copy(self,blueprint,controller,key):
        copy=deepcopy(blueprint);copy['controller']=controller
        self._retarget_copy(copy,key,controller)
        if copy['spell']:
            original=RulesObject.from_json(copy['source'])
            source=self.state.add_spell_copy(self._id('spell-copy'),original,controller)
            copy['source']=source.to_json()
            # "Source" in the copied spell denotes the copy; other captured
            # objects (including paid sacrifices and named targets) stay exact.
        copy['id']=self._id('frame');copy['started']=False;copy['copied']=True
        for task in copy['tasks']:task['id']=self._id('effect')
        self.stack.append(copy)
        self._collect_ward(copy)
        self._event('stack_object_copied',frame=copy['id'],controller=controller,
            spell=copy['spell'],source=copy['source']['ref'],targets=deepcopy(copy['targets']))
        return copy

    def _execute_spell_copy(self,effect,frame,task):
        key=task['id'];controller=frame['controller']
        if isinstance(effect,SpecialMana):
            selected=self._choose(key+':mana',controller,'mana_type','Choose the mana to produce.',
                tuple(Option(symbol,symbol) for symbol in effect.options),1,1)
            symbols=self._mana_after_replacements(controller,(selected[0].key,),
                tapped_for_mana=frame.get('tapped_for_mana',False))
            self.state.add_special_mana(controller,symbols,effect.rider,self._source(frame))
            self._event('mana_added',player=controller,symbols=list(symbols),rider=effect.rider)
            return True
        if not isinstance(effect,CopyCaptured):return False
        blueprint=frame['values']['captured_frame']
        if blueprint is None:
            self._event('copy_not_created',reason='Mana abilities cannot be copied')
            return True
        work=self.resolving.setdefault('copy_work',{}).setdefault(key,{'made':0})
        if effect.copy_kind=='demonstrate':
            if 'accepted' not in work:
                choice=self._choose(key+':demonstrate',controller,'demonstrate',
                    'Copy this spell? If you do, choose an opponent to copy it too.',
                    (Option('no','Decline demonstrate'),Option('yes','Copy it')),1,1)
                work['accepted']=choice[0].key=='yes'
            if not work['accepted']:return True
            if work['made']==0:
                self._materialize_copy(blueprint,controller,key+':own');work['made']=1
            opponents=tuple(p for p in self.state.live_players if p!=controller)
            if opponents:
                selected=self._choose(key+':opponent',controller,'demonstrate_opponent',
                    'Choose an opponent to copy the original spell.',
                    tuple(Option(p,p,player=p) for p in opponents),1,1)
                if work['made']==1:
                    self._materialize_copy(blueprint,selected[0].player,key+':opponent-copy');work['made']=2
        else:
            while work['made']<effect.amount:
                self._materialize_copy(blueprint,controller,key+':copy:'+str(work['made']))
                work['made']+=1
        return True
