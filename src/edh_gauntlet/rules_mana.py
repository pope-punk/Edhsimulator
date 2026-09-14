"""Pure could-produce queries and authored convoke contributions."""
from .rules_state import Zone,ObjectRef,RulesViolation
from .rules_program import (LandMana,ConvokeCast,AddMana,ChooseMana,ChooseCommanderMana,
    ProduceMana,IfCondition,IfQuantityAtLeast,May,UnlessEntered,immediate_effect_nodes)

MANA_EFFECTS=(AddMana,ChooseMana,ChooseCommanderMana,ProduceMana,LandMana)


class ManaRules:
    def _mana_after_replacements(self,player,symbols,*,tapped_for_mana=False):
        # The admitted replacements multiply amounts and preserve mana types.
        # Use the same transformation for real production and capability reads.
        factor=1
        if symbols and tapped_for_mana:
            for obj in self.state.objects(Zone.BATTLEFIELD):
                if obj.phased:continue
                for rule in self.definition(obj).tapped_mana_replacements:
                    if (rule.players=='all' or rule.players=='controller' and obj.controller==player
                            or rule.players=='opponents' and obj.controller!=player):factor*=rule.multiplier
        return tuple(symbols)*factor

    def _land_mana_from_table(self,effect,controller,table,lands):
        result=set()
        for obj in lands:
            eligible=(obj.controller==controller) if effect.relation=='controlled' else (obj.controller!=controller)
            if eligible:result.update(table[obj.ref])
        return result&set('WUBRG' if effect.colors_only else 'WUBRGC')

    def _preview_mana_nodes(self,nodes,source,table,lands):
        frame={'source':source.to_json(),'controller':source.controller,'values':{},'bindings':{}}
        result=set()
        for index,node in enumerate(nodes):
            if isinstance(node,AddMana):result.update(node.symbols)
            elif isinstance(node,ChooseMana):result.update(symbol for option in node.options for symbol in option)
            elif isinstance(node,ChooseCommanderMana):result.update(self.state.commander_identity(source.controller))
            elif isinstance(node,LandMana):result.update(self._land_mana_from_table(node,source.controller,table,lands))
            elif isinstance(node,ProduceMana):
                try:amount=self._quantity(node.amount,frame)
                except (KeyError,IndexError) as exc:
                    raise RulesViolation('Could-produce query requires bound mana quantity facts') from exc
                if amount>0:result.update(node.options)
            elif isinstance(node,IfCondition):
                selected=node.effects if self._condition_holds(node.condition,source) else node.otherwise
                result.update(self._preview_mana_nodes(selected,source,table,lands))
            elif isinstance(node,IfQuantityAtLeast):
                try:selected=node.effects if self._quantity(node.value,frame)>=node.minimum else node.otherwise
                except (KeyError,IndexError) as exc:
                    raise RulesViolation('Could-produce query requires bound comparison facts') from exc
                result.update(self._preview_mana_nodes(selected,source,table,lands))
            elif isinstance(node,May):
                available=node.available is None or any(obj.ref in set(self._refs(frame,node.subject)) for obj in self._query(node.available,frame))
                if available:result.update(self._preview_mana_nodes(node.effects,source,table,lands))
                result.update(self._preview_mana_nodes(node.otherwise,source,table,lands))
            elif isinstance(node,UnlessEntered):
                if node.flag not in source.entry_flags:result.update(self._preview_mana_nodes(node.effects,source,table,lands))
            elif any(isinstance(effect,MANA_EFFECTS) for effect in immediate_effect_nodes((node,))):
                raise RulesViolation('Could-produce query requires an implemented conditional mana path')
            elif any(isinstance(effect,MANA_EFFECTS) for effect in immediate_effect_nodes(nodes[index+1:])):
                # Do not approximate side effects that may change a later amount
                # or condition. No reviewed mana source has such a prefix.
                raise RulesViolation('Could-produce query cannot preview state-changing prefixes')
        return result

    def could_produce_mana(self):
        """Least fixed point over current lands; never activate or pay a cost."""
        views=self.characteristics()
        lands=tuple(obj for obj in self.state.objects(Zone.BATTLEFIELD)
            if not obj.phased and 'Land' in views[obj.ref].types)
        table={obj.ref:set() for obj in lands}
        # At most six types per land can be added. Read current characteristics,
        # including granted and intrinsic abilities, without caching across edits.
        abilities={obj.ref:tuple(a for a in self.activated_abilities(obj) if a.zone==Zone.BATTLEFIELD)
            +tuple(self.definition(obj).abilities) for obj in lands}
        while True:
            changed=False
            for obj in lands:
                possible=set()
                for ability in abilities[obj.ref]:
                    condition=getattr(ability,'intervening_if',None)
                    if condition is not None and not self._condition_holds(condition,obj):continue
                    if not any(isinstance(node,MANA_EFFECTS) for node in immediate_effect_nodes(ability.effects)):continue
                    types=self._preview_mana_nodes(ability.effects,obj,table,lands)
                    tap=getattr(getattr(ability,'cost',None),'tap_source',False)
                    possible.update(self._mana_after_replacements(obj.controller,tuple(sorted(types)),tapped_for_mana=tap))
                added=possible-table[obj.ref]
                if added:table[obj.ref].update(added);changed=True
            if not changed:return {ref:frozenset(types) for ref,types in table.items()}

    def land_mana_options(self,effect,controller):
        table=self.could_produce_mana()
        lands=tuple(self.state.get(ref) for ref in table)
        result=self._land_mana_from_table(effect,controller,table,lands)
        return tuple(symbol for symbol in 'WUBRGC' if symbol in result)

    def _convoke_contributions(self,quote,payment,source):
        rows=payment.convoke
        if (not isinstance(rows,tuple) or any(not isinstance(row,tuple) or len(row)!=2
                or not isinstance(row[0],ObjectRef) or type(row[1]) is not str
                or row[1] not in ('generic',*tuple('WUBRG')) for row in rows)):
            raise RulesViolation('Invalid convoke contribution')
        if rows and (quote.kind!='cast' or not isinstance(self.definition(source).cast,ConvokeCast)):
            raise RulesViolation('This action does not permit convoke')
        if len({ref for ref,color in rows})!=len(rows):raise RulesViolation('A creature cannot convoke twice')
        colors={};generic=0
        for ref,color in rows:
            obj=self.state.get(ref);view=self.effective(ref)
            if obj.zone!=Zone.BATTLEFIELD or obj.phased or obj.controller!=quote.actor or obj.tapped or 'Creature' not in view.types:
                raise RulesViolation('Convoke requires an untapped controlled creature')
            if color=='generic':generic+=1
            elif color not in view.colors:raise RulesViolation('Convoke color does not match the creature')
            else:colors[color]=colors.get(color,0)+1
        if generic>quote.cost.mana.generic:raise RulesViolation('Too many generic convoke contributions')
        return tuple(ref for ref,color in rows),colors
