"""Shared combat declarations, batched assignments and nonprevented damage.

Player and planeswalker combat destinations are supported. Battle defense, attack/block
requirements and general prevention remain gated. Color protection and\nregeneration share the kernel's replacement and guard interpreter. Ordinary player losses
reach the shared departure interpreter.
"""
from dataclasses import dataclass
from copy import deepcopy
from .rules_characteristics import matches
from .rules_guard import protection_matches
from types import SimpleNamespace
from . import block_declaration, combat_damage
from .rules_state import ObjectRef, Zone, RulesViolation, ResourcePayment
from .rules_casting import Payment,_mana_symbols_satisfied


def uid(ref):return ref.card_id+'@'+str(ref.incarnation)


def combat_creature(types):
    return 'Creature' in types and 'Battle' not in types


@dataclass(frozen=True)
class CombatChoiceBoundary:
    actor: str
    kind: str
    revision: str
    specification: dict


class CombatView:
    def __init__(self,kernel):self.kernel=kernel;self.turn_number=kernel.state.turn_number;self.block_rules=None
    def card(self,ref):
        obj=self.kernel.state.get(ref);view=self.kernel.effective(ref)
        return SimpleNamespace(ref=ref,uid=uid(ref),name=self.kernel.definition(obj).name,
            power=view.power or 0,toughness=view.toughness or 0,keywords=view.keywords,
            metadata={'damage_marked':obj.damage_marked,
                      'unblockable_turn':self.turn_number if 'unblockable' in view.keywords else None})
    def keywords_for(self,card):return card.keywords
    def effective_power(self,card):return card.power
    def effective_toughness(self,card):return card.toughness
    def can_block(self,blocker,attacker):
        attacker_view=self.kernel.effective(attacker.ref);blocker_view=self.kernel.effective(blocker.ref)
        if protection_matches(attacker_view,blocker_view):return False
        if 'fear' in attacker_view.keywords and 'Artifact' not in blocker_view.types and 'B' not in blocker_view.colors:return False
        if 'flying' in attacker.keywords and not {'flying','reach'} & blocker.keywords:return False
        if self.block_rules is None:
            self.block_rules=[]
            for source in self.kernel.state.objects(Zone.BATTLEFIELD):
                if source.phased:continue
                for rule in self.kernel.definition(source).block_restrictions:
                    context={'source':source.to_json(),'controller':source.controller}
                    self.block_rules.append((source,rule,self.kernel._quantity(rule.value,context)))
        if not self.block_rules:return True
        attacker_obj=self.kernel.state.get(attacker.ref);blocker_obj=self.kernel.state.get(blocker.ref)
        attacker_view=self.kernel.effective(attacker.ref);blocker_view=self.kernel.effective(blocker.ref)
        for source,rule,threshold in self.block_rules:
            if not matches(rule.attackers,attacker_obj,attacker_view,source) or not matches(rule.blockers,blocker_obj,blocker_view,source):continue
            value=getattr(blocker_view,rule.statistic)
            if value is None:continue
            prohibited={'lt':value<threshold,'le':value<=threshold,'eq':value==threshold,'ge':value>=threshold,'gt':value>threshold}[rule.comparison]
            if prohibited:return False
        return True


class CombatRules:
    def _attack_destination(self,actor,destination):
        if isinstance(destination,str):
            if destination not in self.state.live_players or destination==actor:raise RulesViolation('Illegal defending player')
            return destination,None
        if not isinstance(destination,ObjectRef):raise RulesViolation('Expected an exact permanent reference or player')
        obj=self.state.get(destination)
        view=self.effective(destination)
        if obj.zone==Zone.BATTLEFIELD and not obj.phased and 'Battle' in view.types:
            if 'Creature' in view.types or obj.protector==actor or obj.protector not in self.state.live_players:raise RulesViolation('Illegal defending battle')
            return obj.protector,{'ref':destination.to_json(),'protector':obj.protector,'battle':True,'combat_departure':obj.combat_departure,'controller':obj.controller,'controlled_since':obj.controlled_since}
        if (obj.zone!=Zone.BATTLEFIELD or obj.phased or obj.controller==actor
                or obj.controller not in self.state.live_players or 'Planeswalker' not in self.effective(destination).types):
            raise RulesViolation('Illegal defending planeswalker')
        return obj.controller,{'ref':destination.to_json(),'controller':obj.controller,
            'controlled_since':obj.controlled_since,'combat_departure':obj.combat_departure}

    def _defender_present(self,row):
        if row.get('defender_removed') or (row['defender'] not in self.state.live_players and not row.get('defender_object',{}).get('battle')):return False
        target=row.get('defender_object')
        if target is None:return True
        try:obj=self.state.get(ObjectRef.from_json(target['ref']))
        except RulesViolation:return False
        if target.get('battle'):
            view=self.effective(obj.ref)
            return (obj.zone==Zone.BATTLEFIELD and not obj.phased and obj.protector==target['protector']
                and obj.controller==target['controller'] and obj.controlled_since==target['controlled_since']
                and obj.combat_departure==target['combat_departure'] and 'Battle' in view.types and 'Creature' not in view.types)
        return (obj.zone==Zone.BATTLEFIELD and not obj.phased and obj.controller==target['controller']
            and obj.controlled_since==target['controlled_since'] and obj.combat_departure==target['combat_departure']
            and 'Planeswalker' in self.effective(obj.ref).types)

    def _defender_damage(self,row,amount):
        target=row.get('defender_object')
        if target is not None:
            # An attacker remains attacking after its planeswalker leaves combat.
            # It cannot redirect unblocked/trample damage to the former controller.
            return {'source':row['ref'],'target':target['ref'],'amount':amount} if self._defender_present(row) else None
        return {'source':row['ref'],'player':row['defender'],'amount':amount} if self._defender_present(row) else None

    def _combat_record(self,ref,**fields):
        obj=self.state.get(ref)
        return {'uid':uid(ref),'ref':ref.to_json(),'controller':obj.controller,
                'controlled_since':obj.controlled_since,'combat_departure':obj.combat_departure,**fields}

    def _combat_present(self,row):
        ref=ObjectRef.from_json(row['ref'])
        try:obj=self.state.get(ref)
        except RulesViolation:return False
        return (obj.zone==Zone.BATTLEFIELD and not obj.phased and obj.controller==row['controller']
            and obj.controlled_since==row['controlled_since'] and obj.combat_departure==row['combat_departure']
            and combat_creature(self.effective(ref).types))

    def _combat_prune(self):
        if self.combat is None:return
        for row in self.combat['attackers']:
            if row.get('defender_object') is not None and not self._defender_present(row):row['defender_removed']=True
        before={row['uid'] for row in self.combat['attackers']}
        self.combat['attackers']=[row for row in self.combat['attackers'] if self._combat_present(row) and (row['defender'] in self.state.live_players or row.get('defender_object',{}).get('battle'))]
        remaining={row['uid'] for row in self.combat['attackers']}
        for key,rows in self.combat['blocks'].items():
            self.combat['blocks'][key]=[row for row in rows if self._combat_present(row)]
        if before!=remaining:self._event('attackers_removed_from_combat',uids=sorted(before-remaining))

    def _combat_target_refs(self,kind):
        # Target inspection must be pure: filter current membership without
        # pruning records or changing the revision used by an action quote.
        if self.combat is None:return frozenset()
        rows=[]
        if kind in {'attacking','attacking_or_blocking'}:
            rows.extend(row for row in self.combat['attackers'] if row['defender'] in self.state.live_players or row.get('defender_object',{}).get('battle'))
        if kind in {'blocking','attacking_or_blocking'}:
            rows.extend(row for group in self.combat['blocks'].values() for row in group)
        return frozenset(ObjectRef.from_json(row['ref']) for row in rows if self._combat_present(row))

    def attack_candidates(self,actor):
        """Use the same eligibility filter for declarations and forced empty combat."""
        eligible={}
        for obj in self.state.objects(Zone.BATTLEFIELD,controller=actor):
            view=self.effective(obj.ref)
            if (not obj.phased and not obj.tapped and combat_creature(view.types) and 'defender' not in view.keywords
                    and ('haste' in view.keywords or self.state.ready_since_turn_start(obj.ref))):
                eligible[obj.ref]=(obj,view)
        return eligible

    def _attack_rows(self,actor,attackers):
        if self.pending_choice or self.resolving:raise RulesViolation('Resolve the current choice first')
        if (self.turn_schedule is None or self.phase!='declare_attackers' or self.priority is not None
                or actor!=self.active):raise RulesViolation('Not the current attacker declaration')
        if not isinstance(attackers,dict):raise RulesViolation('Attackers require an explicit mapping')
        eligible=self.attack_candidates(actor)
        rows=[];taps=[];total=0
        for ref,defender in attackers.items():
            if ref not in eligible:
                raise RulesViolation('Illegal attacker or defender')
            obj,view=eligible[ref]
            player,target=self._attack_destination(actor,defender)
            fields={'defender':player}
            if target is not None:fields['defender_object']=target
            rows.append(self._combat_record(ref,**fields))
            if 'vigilance' not in view.keywords:taps.append(ref)
            total+=self._attack_tax(player) if target is None else 0
        # With this closed vocabulary each creature's requirements are independent.
        # Paying an attack cost is optional. Among free destinations and the chosen
        # paid destination, obey the maximum number of distinct goad requirements.
        free=tuple(p for p in self.state.live_players if p!=actor and self._attack_tax(p)==0)
        free+=tuple(obj.ref for obj in self.state.objects(Zone.BATTLEFIELD) if not obj.phased
            and ((obj.controller!=actor and obj.controller in self.state.live_players and 'Planeswalker' in self.effective(obj.ref).types and 'Battle' not in self.effective(obj.ref).types)
                or ('Battle' in self.effective(obj.ref).types and 'Creature' not in self.effective(obj.ref).types and obj.protector in self.state.live_players and obj.protector!=actor)))
        for ref,(_,view) in eligible.items():
            goaders=view.goaded_by
            if not goaders:continue
            selected=attackers.get(ref)
            choices=free+((selected,) if selected is not None else ())
            score=lambda p:len(goaders)+(sum(p!=g for g in goaders) if isinstance(p,str) else 0) if p is not None else 0
            if score(selected)<max((score(p) for p in choices),default=0):
                raise RulesViolation('Attack declaration does not satisfy the available goad requirements')
        return rows,tuple(taps),total

    def declare_attackers(self,actor,attackers,*,revision,payment=None):
        if revision!=self.revision:raise RulesViolation('Stale attacker declaration')
        rows,taps,total=self._attack_rows(actor,attackers)
        payment=Payment() if payment is None else payment
        if (not isinstance(payment,Payment) or payment.taps or payment.zone_costs or payment.convoke or payment.cost_order):
            raise RulesViolation('Attack costs accept mana and authored mana abilities only')
        trial=type(self).restore(self.snapshot(),self._base_definitions.values())
        observers=trial._tap_observers(taps)
        # CR 508.1f: attackers tap before mana abilities and payment. All of this
        # happens on the trial; an incomplete plan or wrong payment commits nothing.
        trial.state.move((),'attack_taps',payment=ResourcePayment(actor,taps=taps))
        total=sum(trial._attack_tax(row['defender']) for row in rows if row.get('defender_object') is None)
        trial._collect_tapped(taps,observers)
        if payment.mana_actions:
            if not total:raise RulesViolation('There is no attack mana payment to produce mana for')
            trial._run_declaration_mana(actor,payment.mana_actions,'attack:'+revision)
        resources=ResourcePayment(actor,payment.mana,tagged_mana=trial._tagged_resources(actor,payment.tagged_mana))
        trial.state.validate_payment(resources)
        if sum(dict(payment.mana).values())!=total:raise RulesViolation('Attack payment must match the locked total exactly')
        trial.state.move((),'attack_payment',payment=resources)
        trial.combat={'attackers':rows,'blocks':{},'blocked':[],'declared_any':bool(rows),
            'defender_index':0,'first_strikers':[],'had_first_step':False,'damage_pending':None,'damage_done':False}
        trial._combat_prune()
        if attackers:trial._record_turn_fact('attacked',actor)
        trial._event('attackers_declared',actor=actor,attackers=[{'ref':row['ref'],'defender':row.get('defender_object',{}).get('ref',row['defender'])} for row in trial.combat['attackers']],
            mana_paid=dict(payment.mana),attack_cost=total)
        for row in trial.combat['attackers']:
            trial._collect_announcement('creature_attacks',trial.state.get(ObjectRef.from_json(row['ref'])),actor,
                values={'defending_player':row['defender']})
        trial.priority=actor;trial.passes=[]
        self._adopt_trial(trial)
        return self.advance()

    def _defenders(self):
        start=self.state.players.index(self.active)
        return tuple(p for p in self.state.players[start+1:]+self.state.players[:start] if p in self.state.live_players)

    def _block_specification(self,actor):
        view=CombatView(self)
        attackers=[row for row in self.combat['attackers'] if row['defender']==actor]
        eligible=[obj.ref for obj in self.state.objects(Zone.BATTLEFIELD,controller=actor)
            if not obj.phased and not obj.tapped and combat_creature(self.effective(obj.ref).types)]
        return block_declaration.specification(view,[view.card(ObjectRef.from_json(row['ref'])) for row in attackers],
                                              [view.card(ref) for ref in eligible])

    def declare_blockers(self,actor,assignments,*,revision):
        if self.pending_choice or self.resolving:raise RulesViolation('Resolve the current choice first')
        if (self.phase!='declare_blockers' or self.priority is not None or self.combat is None
                or revision!=self.revision or self._defenders()[self.combat['defender_index']]!=actor):
            raise RulesViolation('Not the current blocker declaration')
        spec=self._block_specification(actor)
        try:accepted=block_declaration.validate({'block_declaration':spec},assignments)
        except ValueError as exc:raise RulesViolation(str(exc)) from exc
        by_uid={uid(obj.ref):obj.ref for obj in self.state.objects(Zone.BATTLEFIELD)}
        for key,blockers in accepted.items():
            self.combat['blocks'][key]=[self._combat_record(by_uid[key]) for key in blockers]
            if blockers:self.combat['blocked'].append(key)
        self.combat['defender_index']+=1
        self._event('blockers_declared',actor=actor,assignments=accepted)
        return self.advance()

    def _finish_blockers(self):
        for attacker in self.combat['attackers']:
            blockers=self.combat['blocks'].get(attacker['uid'],[])
            if blockers:
                source=self.state.get(ObjectRef.from_json(attacker['ref']))
                self._collect_announcement('becomes_blocked',source,source.controller)
            for row in blockers:
                source=self.state.get(ObjectRef.from_json(row['ref']))
                self._collect_announcement('creature_blocks',source,source.controller)
        self.priority=self.priority_player();self.passes=[]

    def _start_damage_step(self,first=False):
        self._combat_prune()
        rows=self.combat['attackers']+[row for group in self.combat['blocks'].values() for row in group]
        first_strikers=[row['uid'] for row in rows if {'first_strike','double_strike'} & self.effective(ObjectRef.from_json(row['ref'])).keywords]
        if first and first_strikers:
            self.combat['first_strikers']=first_strikers;self.combat['had_first_step']=True
            phase='first_strike_damage'
        else:phase='combat_damage'
        self.combat['damage_pending']=None;self.combat['damage_done']=False
        self._begin_phase(phase);self.priority=None

    def _damages_this_step(self,row):
        if not self.combat['had_first_step']:return True
        if self.phase=='first_strike_damage':return row['uid'] in self.combat['first_strikers']
        return row['uid'] not in self.combat['first_strikers'] or 'double_strike' in self.effective(ObjectRef.from_json(row['ref'])).keywords

    def _prepare_damage(self):
        view=CombatView(self);choices=[];assignments=[]
        for attacker in self.combat['attackers']:
            ref=ObjectRef.from_json(attacker['ref']);source=view.card(ref)
            blockers=self.combat['blocks'].get(attacker['uid'],[])
            if self._damages_this_step(attacker):
                power=max(0,source.power);trample='trample' in source.keywords
                if not blockers:
                    if attacker['uid'] not in self.combat['blocked'] or trample:
                        damage=self._defender_damage(attacker,power)
                        if damage is not None:assignments.append(damage)
                else:
                    spec,forced=combat_damage.specification(view,[(source,[view.card(ObjectRef.from_json(row['ref'])) for row in blockers],power,trample)],
                        self.phase,SimpleNamespace(name=attacker['defender']),None)
                    choices.extend({**row,'defender':attacker['defender']} for row in spec['sources'])
                    if forced:assignments.extend(self._expand_damage(attacker,forced[attacker['uid']]))
            for blocker in blockers:
                if self._damages_this_step(blocker):
                    amount=max(0,view.card(ObjectRef.from_json(blocker['ref'])).power)
                    assignments.append({'source':blocker['ref'],'target':attacker['ref'],'amount':amount})
        return {'revision':self.revision,'specification':{'step':self.phase,'sources':choices},'assignments':assignments}

    def _expand_damage(self,attacker,allocation):
        result=[]
        by_uid={row['uid']:row for row in self.combat['blocks'].get(attacker['uid'],[])}
        for key,amount in allocation['blockers'].items():
            result.append({'source':attacker['ref'],'target':by_uid[key]['ref'],'amount':amount})
        if allocation['defender']:
            damage=self._defender_damage(attacker,allocation['defender'])
            if damage is not None:result.append(damage)
        return result

    def assign_combat_damage(self,actor,assignments,*,revision):
        pending=self.combat['damage_pending'] if self.combat else None
        if (pending is None or self.priority is not None or actor!=self.active or revision!=self.revision
                or pending['revision']!=self.revision):raise RulesViolation('Not the current damage assignment')
        try:accepted=combat_damage.validate({'combat_damage':pending['specification']},assignments)
        except ValueError as exc:raise RulesViolation(str(exc)) from exc
        complete=list(pending['assignments']);by_uid={row['uid']:row for row in self.combat['attackers']}
        for key,allocation in accepted.items():complete.extend(self._expand_damage(by_uid[key],allocation))
        self._commit_combat_damage(complete)
        return self.advance()

    def _damage_source(self,source):
        return self._object_information(source)

    def _deal_damage(self,rows,*,combat=False):
        payments=[]
        for source,target,amount in rows:
            source,view=self._damage_source(source)
            if isinstance(target,str) and target in self.state.players and target not in self.state.live_players:continue
            recipient_types=()
            if not isinstance(target,str):
                try:obj=self.state.get(target)
                except RulesViolation:continue
                recipient_types=tuple(sorted(self.effective(target).types & {'Creature','Planeswalker','Battle'}))
                if obj.zone!=Zone.BATTLEFIELD or obj.phased or not recipient_types:continue
                if protection_matches(self.effective(target),view):amount=0
            payments.append({'source':source,'target':target,'amount':amount,'combat':combat,
                             'source_modified':view.modified,'source_types':tuple(sorted(view.types)),
                             'lifelink':'lifelink' in view.keywords,'deathtouch':'deathtouch' in view.keywords,'recipient_types':recipient_types,
                             'freerunning':combat and 'Creature' in view.types and (source.commander or 'Assassin' in view.subtypes)})
        lifelink_sources={}
        for row in payments:
            if row['lifelink'] and row['amount'] and row['source'].controller in self.state.live_players:
                source=row['source'];key=(source.controller,source.ref)
                lifelink_sources[key]=lifelink_sources.get(key,0)+row['amount']
        bonuses={key:self._life_gain_amount(key[0],amount)-amount for key,amount in lifelink_sources.items()}
        for row in payments:
            if row['lifelink'] and row['amount']:
                key=(row['source'].controller,row['source'].ref)
                row['lifelink_gain']=row['amount']+bonuses.pop(key,0)
        before_damage=tuple(self.state.get(ref) for ref in dict.fromkeys(row['target'] for row in payments if not isinstance(row['target'],str)))
        self.state.damage_batch(payments)
        self._collect_defeated_battles(before_damage)
        for row in payments:
            if row['freerunning'] and row['amount'] and isinstance(row['target'],str):
                self._record_turn_fact('freerunning',row['source'].controller)
        for row in payments:
            if not row['amount']:continue
            target=row['target']
            self._event('damage_dealt',source=row['source'].ref.to_json(),target=target if isinstance(target,str) else target.to_json(),amount=row['amount'],combat=combat)
            self._collect_announcement('damage_dealt',row['source'],row['source'].controller,values={
                'event_amount':row['amount'],'combat':combat,'damaged_player':target if isinstance(target,str) else None,
                'source_modified':row['source_modified'],'source_types':list(row['source_types'])})
        received={}
        for row in payments:
            target=row['target']
            if row['amount'] and not isinstance(target,str):received[target]=received.get(target,0)+row['amount']
        for ref,amount in received.items():
            recipient=self.state.get(ref)
            self._event('damage_received',recipient=ref.to_json(),amount=amount,combat=combat)
            self._collect_announcement('damage_received',recipient,recipient.controller,values={'event_amount':amount})
        lifelink_sources={}
        for row in payments:
            if row['lifelink'] and row['amount'] and row['source'].controller in self.state.live_players:
                source=row['source'];key=(source.controller,source.ref)
                lifelink_sources[key]=lifelink_sources.get(key,0)+row.get('lifelink_gain',row['amount'])
        for (player,ref),amount in lifelink_sources.items():
            self._player_event('life_gained',player,amount=amount,cause='lifelink',source=ref.to_json())

    def _commit_combat_damage(self,assignments):
        rows=[(self.state.get(ObjectRef.from_json(row['source'])),row.get('player') or ObjectRef.from_json(row['target']),row['amount']) for row in assignments]
        self._deal_damage(rows,combat=True)
        self.combat['damage_done']=True;self.combat['damage_pending']=None
        self.priority=self.priority_player();self.passes=[]

    def _combat_boundary(self):
        self._combat_prune()
        if self.phase=='declare_blockers':
            defenders=self._defenders()
            while self.combat['defender_index']<len(defenders):
                actor=defenders[self.combat['defender_index']];spec=self._block_specification(actor)
                if spec['attackers']:return CombatChoiceBoundary(actor,'blockers',self.revision,spec)
                self.combat['defender_index']+=1
            self._finish_blockers();return self.advance()
        if self.phase in {'first_strike_damage','combat_damage'}:
            if self.combat['damage_pending'] is None:self.combat['damage_pending']=self._prepare_damage()
            pending=self.combat['damage_pending']
            if pending['revision']!=self.revision:raise RulesViolation('State changed during damage assignment')
            if pending['specification']['sources']:
                return CombatChoiceBoundary(self.active,'combat_damage',self.revision,deepcopy(pending['specification']))
            self._commit_combat_damage(pending['assignments']);return self.advance()
        raise RulesViolation('Unknown combat boundary')
