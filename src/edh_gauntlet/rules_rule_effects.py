"""Authored ordered costs, continuous rule permissions and attack declarations."""
from copy import deepcopy
from dataclasses import replace
import hashlib
from .rules_state import ObjectRef,RulesObject,Zone,RulesViolation,ResourcePayment
from .rules_program import OrderedCostSpec,RulePermissions,encode,decode
from .rules_casting import PreparedAction,Payment
from .rules_characteristics import base


class RuleEffects:
    def _commit_ordered_action(self,quote,payment):
        if quote.kind!='activate' or payment.mana_actions or payment.convoke or payment.taps:
            raise RulesViolation('Ordered costs require a separately authored activation payment')
        resources=self._resource_payment(quote,payment)
        counters=tuple((c.kind,c.amount) for c in quote.cost.player_counter_costs)
        resources=replace(resources,player_counters=counters)
        self.state.validate_payment(resources)
        refs=self._zone_cost_refs(quote,payment)
        if len(set(refs))!=len(refs):raise RulesViolation('One object cannot pay multiple zone-cost groups')
        order=payment.cost_order
        required={'zone:'+c.cost_id for c in quote.cost.zone_costs}|{'player:'+c.kind for c in quote.cost.player_counter_costs}
        if quote.cost.life:required.add('life')
        if quote.cost.mana.generic or quote.cost.mana.symbols:required.add('mana')
        if not isinstance(order,tuple) or any(type(k) is not str for k in order) or len(order)!=len(required) or set(order)!=required:
            raise RulesViolation('Declare each cost group exactly once in the chosen payment order')
        source=self.state.get(quote.source)
        ability=next(a for a in self.activated_abilities(source) if a.ability_id==quote.ability_id)
        if ability.mana_ability:raise RulesViolation('Ordered immediate mana activations are not yet supported')
        frame=self._frame(source,quote.actor,ability.effects,targets=quote.targets,target_spec=ability.targets,chosen_x=quote.x_value)
        frame.update(ability_id=ability.ability_id,activated_program=encode(ability))
        self._bind_announced_values(frame,quote);self.stack.append(frame)
        selections=dict(payment.zone_costs)
        self.announcement={'frame_id':frame['id'],'quote':quote.to_json(),'payment':payment.to_json(),
            'source':source.to_json(),'origin_source':source.to_json(),'source_types':sorted(self.effective(source.ref).types),
            'ability':encode(ability),'refs':[ref.to_json() for ref in refs],'ordered':True,'cursor':0,
            'groups':{c.cost_id:[r.to_json() for r in selections[c.cost_id]] if c.selector is not None else [source.ref.to_json()]
                for c in quote.cost.zone_costs},'paid_groups':{}}
        self._event('activation_announced',action_id=quote.action_id,actor=quote.actor)
        return self.advance()

    def _continue_ordered_announcement(self):
        pending=self.announcement;quote=PreparedAction.from_json(pending['quote']);payment=Payment.from_json(pending['payment'])
        frame=next(f for f in self.stack if f['id']==pending['frame_id'])
        while pending['cursor']<len(payment.cost_order):
            group=payment.cost_order[pending['cursor']]
            if group.startswith('zone:'):
                cost=next(c for c in quote.cost.zone_costs if group=='zone:'+c.cost_id)
                refs=tuple(ObjectRef.from_json(r) for r in pending['groups'][cost.cost_id])
                source=RulesObject.from_json(pending['origin_source'])
                if cost.selector is not None:
                    legal={o.ref for o in self._query(cost.selector,{'source':source.to_json(),'controller':quote.actor})}
                    if not set(refs)<=legal:raise RulesViolation('An ordered cost became unpayable')
                views=self.characteristics()
                facts={stat:sum(getattr(views[r],stat) or 0 for r in refs) for stat in ('power','toughness','mana_value')}
                subtypes=sorted({t for r in refs for t in views[r].subtypes})
                destination={'sacrifice':Zone.GRAVEYARD,'discard':Zone.GRAVEYARD,'exile':Zone.EXILE,'return':Zone.HAND}[cost.kind]
                events=self._move(refs,destination,{'source':pending['origin_source'],'controller':quote.actor,'bindings':{}},
                    quote.action_id+':cost:'+str(pending['cursor']),cause=cost.kind,controller_mode='owner')
                for event in events:
                    if event.before.ref==quote.source:pending['source']=event.before.to_json()
                frame['values'].setdefault('paid_cost_stats',{})[cost.cost_id]=facts
                frame['values'].setdefault('paid_cost_subtypes',{})[cost.cost_id]=subtypes
                for task in frame['tasks']:
                    task.setdefault('values',{}).update(deepcopy(frame['values']))
                pending['paid_groups'][cost.cost_id]=pending['groups'][cost.cost_id]
            else:
                if group=='mana':
                    resource=ResourcePayment(quote.actor,payment.mana,tagged_mana=self._tagged_resources(quote.actor,payment.tagged_mana))
                elif group=='life':resource=ResourcePayment(quote.actor,life=quote.cost.life)
                else:
                    cost=next(c for c in quote.cost.player_counter_costs if group=='player:'+c.kind)
                    resource=ResourcePayment(quote.actor,player_counters=((cost.kind,cost.amount),))
                self.state.move((),'ordered_cost',payment=resource)
                if resource.player_counters:
                    self._event('player_counters_paid',player=quote.actor,counters=dict(resource.player_counters))
            pending['cursor']+=1
        resources=ResourcePayment(quote.actor,payment.mana,quote.cost.life,
            tagged_mana=(),player_counters=tuple((c.kind,c.amount) for c in quote.cost.player_counter_costs))
        self.announcement=None
        self._commit_prepared(quote,resources,paid=True,source=RulesObject.from_json(pending['source']),
            ability=decode(pending['ability']),zone_payment=pending['paid_groups'],
            previous_types=pending['source_types'],prepared_frame=frame)
        receipt=self.action_receipts[quote.action_id]['payment']
        receipt['cost_order']=list(payment.cost_order)
        receipt['player_counters']=dict(resources.player_counters)

    def _attack_tax(self,defender):
        return sum(rule.attack_tax for source in self.state.objects(Zone.BATTLEFIELD)
            if not source.phased and source.controller==defender
            and isinstance((rule:=self.definition(source).player_permissions),RulePermissions))

    def _spell_uncounterable(self,ref):
        if any(f['spell'] and self._source(f).ref==ref and f.get('cannot_be_countered') for f in self.stack):return True
        obj=self.state.get(ref)
        turn_permission=any(row['controller']==obj.controller and isinstance((rule:=decode(row['permissions'])),RulePermissions)
            and rule.creature_spells_uncounterable for row in self.player_effects)
        return 'Creature' in self.effective(ref).types and (turn_permission or any(
            not source.phased and source.controller==obj.controller
            and isinstance((rule:=self.definition(source).player_permissions),RulePermissions)
            and rule.creature_spells_uncounterable for source in self.state.objects(Zone.BATTLEFIELD)))

    def _announcement_mana_waiting(self):
        return bool(self.declaration_mana and not self.pending_choice and not self.announcement and self.resolving is None)

    def _run_declaration_mana(self,actor,commands,identity):
        from .rules_adapter import RulesActorAdapter
        if not isinstance(commands,tuple) or len(commands)>128:raise RulesViolation('Invalid declaration mana plan')
        self.declaration_mana={'actor':actor}
        adapter=RulesActorAdapter(self)
        for index,row in enumerate(commands):
            if type(row) is not dict or row.get('kind') not in {'activate','answer','allocate_counters'}:
                raise RulesViolation('Declaration mana plans contain only mana abilities and their choices')
            command=deepcopy(row)
            if any(k in command for k in ('revision','action_id','request_id')):raise RulesViolation('Declaration mana identities are supplied by the engine')
            if command.get('payment',{}).get('mana_actions'):raise RulesViolation('Nested declaration mana is unavailable')
            command['revision']=self.revision
            if command['kind']=='activate':
                command['action_id']='declaration-mana:'+hashlib.sha256(identity.encode()).hexdigest()+':'+str(index)
            else:
                if self.pending_choice is None or self.pending_choice.actor!=actor:raise RulesViolation('No owned mana choice')
                command['request_id']=self.pending_choice.request_id
            adapter._execute(actor,command)
        if not self._announcement_mana_waiting():raise RulesViolation('Finish every immediate mana ability and choice')
        self.declaration_mana=None;self.priority=None

    def _adopt_trial(self,trial):
        state=self.state;state.__dict__.update(trial.state.__dict__)
        self.__dict__.update(trial.__dict__);self.state=state
