"""Atomic counter placement, affine replacement ordering and counter-event discovery.

Battlefield entry shares the counter event collector after its atomic zone move.
Replacement side effects and general counter-removal effects remain separate gates.
"""
from .rules_state import ObjectRef,PlayerRef,Zone,RulesViolation,target_from_json
from .rules_choices import Option
from .rules_characteristics import matches


def transformed(counts,rule):
    return {kind:amount for kind,n in counts.items()
            if (amount:=(n*rule.multiplier+rule.additional)//rule.divisor if rule.kind is None or rule.kind==kind else n)>0}


def actor_matches(rule,source,actor):
    return rule.actor_relation=='any' or (source.controller==actor)==(rule.actor_relation=='controller')


def commute(counts,first,second):
    if first.divisor!=1 or second.divisor!=1:
        # Pointwise equality is insufficient for rounded transforms after other
        # replacements. Only identical or disjoint transforms are elided here.
        if first.kind is not None and second.kind is not None and first.kind!=second.kind:return True
        return (first.kind,first.multiplier,first.additional,first.divisor)==(second.kind,second.multiplier,second.additional,second.divisor)
    return transformed(transformed(counts,first),second)==transformed(transformed(counts,second),first)


class CounterRules:
    def _counter_recipients(self,frame,subject):
        if subject in {'controller','opponents','all'}:return tuple(PlayerRef(p) for p in self._players(frame,subject))
        if subject=='target':return tuple(target_from_json(row) for row in frame['targets'])
        return self._refs(frame,subject)

    def _counter_counts(self,recipient):
        if isinstance(recipient,PlayerRef):
            if recipient.player not in self.state.live_players:return None
            return dict(self.state.player_counters(recipient.player))
        try:obj=self.state.get(recipient)
        except RulesViolation:return None
        return dict(obj.counters) if obj.zone==Zone.BATTLEFIELD and not obj.phased else None

    def _put_counters(self,placements,frame,key):
        merged={}
        for recipient,kind,amount in placements:
            if amount<=0 or self._counter_counts(recipient) is None:continue
            counts=merged.setdefault(recipient,{})
            counts[kind]=counts.get(kind,0)+amount
        if not merged:return
        sources=tuple((source,rule) for source in self.state.objects(Zone.BATTLEFIELD) if not source.phased
                      for rule in self.definition(source).counter_replacements)
        views=self.characteristics()
        def affected(recipient):return recipient.player if isinstance(recipient,PlayerRef) else self.state.get(recipient).controller
        order=self._players(frame,'all');ranks={p:i for i,p in enumerate(order)}
        recipients=sorted(merged,key=lambda r:(ranks[affected(r)],isinstance(r,PlayerRef),r.player if isinstance(r,PlayerRef) else r.card_id,r.incarnation if isinstance(r,ObjectRef) else 0))
        final=[];trace=[]
        for index,recipient in enumerate(recipients):
            counts=merged[recipient];used=set();applicable=[]
            for source,rule in sources:
                if not actor_matches(rule,source,frame['controller']):continue
                if isinstance(recipient,PlayerRef):
                    match=rule.players is not None and (rule.players=='all' or (rule.players=='controller')==(source.controller==recipient.player))
                else:
                    obj=self.state.get(recipient)
                    match=(rule.subject!='self' or source.ref==recipient) and rule.selector is not None and matches(rule.selector,obj,views[recipient],source)
                if match:
                    effect_key=(source.ref.card_id,source.ref.incarnation,rule.replacement_id)
                    applicable.append((effect_key,source,rule))
            applicable.sort(key=lambda row:row[0])
            while counts:
                choices=[row for row in applicable if row[0] not in used and (row[2].kind is None or counts.get(row[2].kind,0)>0)]
                if not choices:break
                # With this pure affine vocabulary, commuting orders cannot change
                # gameplay. No inference is needed just to order identical doublers.
                equivalent=all(commute(counts,a[2],b[2]) for i,a in enumerate(choices) for b in choices[i+1:])
                chosen=choices[0]
                if len(choices)>1 and not equivalent:
                    label=recipient.player if isinstance(recipient,PlayerRef) else self.definition(self.state.get(recipient)).name
                    amounts=', '.join(str(n)+' '+kind for kind,n in sorted(counts.items()))
                    options=tuple(Option(str(i),self.definition(source).name+': '+rule.replacement_id) for i,(_,source,rule) in enumerate(choices))
                    answer=self._choose(key+':counter-order:'+str(index)+':'+str(len(used)),affected(recipient),'counter_replacement',
                        'Choose the next counter modifier for '+label+' ('+amounts+').',options,1,1)
                    chosen=choices[int(answer[0].key)]
                effect_key,source,rule=chosen;used.add(effect_key);counts=transformed(counts,rule)
                trace.append({'recipient':recipient.to_json(),'source':source.ref.to_json(),'replacement_id':rule.replacement_id})
            if counts:final.append((recipient,tuple(sorted(counts.items()))))
        # Choices above mutate no resources, counters or event stream. A resumed
        # instruction recomputes the same proposals and reuses its bound answers.
        self.state.put_counters_batch(final)
        for row in trace:self._event('counter_replacement_applied',**row)
        for recipient,counts in final:
            self._emit_counters(recipient,dict(counts),frame['controller'],self._source(frame).ref)

    def _emit_counters(self,recipient,counts,actor,source):
        controller=recipient.player if isinstance(recipient,PlayerRef) else self.state.get(recipient).controller
        self._event('counters_added',ref=recipient.to_json() if isinstance(recipient,ObjectRef) else None,
            recipient_player=recipient.player if isinstance(recipient,PlayerRef) else None,
            player=actor,controller=controller,counters=counts,
            counter=next(iter(counts)) if len(counts)==1 else None,amount=sum(counts.values()),source=source.to_json())
        self._collect_counters(recipient,counts,actor)

    def _collect_counters(self,recipient,counts,actor):
        obj=None if isinstance(recipient,PlayerRef) else self.state.get(recipient)
        recipient_controller=recipient.player if obj is None else obj.controller
        types=frozenset() if obj is None else self.effective(recipient).types
        for source in self.state.objects(Zone.BATTLEFIELD):
            if source.phased:continue
            for ability in self.definition(source).abilities:
                event=ability.event
                if event.kind!='counters_added':continue
                if event.subject=='self' and (obj is None or source.ref!=recipient):continue
                if event.controller_only and source.controller!=actor:continue
                if event.recipient_relation=='controlled' and recipient_controller!=source.controller:continue
                if event.recipient_relation=='opponent_controlled' and recipient_controller==source.controller:continue
                if not set(event.types)<=types:continue
                amount=counts.get(event.counter_kind,0) if event.counter_kind else sum(counts.values())
                if amount:self._trigger(source,ability,values={'event_amount':amount})
