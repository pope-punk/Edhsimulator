"""Exact direct/indirect phasing and controller-bound untap restoration.

Status changes preserve object incarnations and never emit zone/attachment
events. Unsupported fixture-only phased objects remain explicitly fenced.
"""
from .rules_state import ObjectRef, Zone, RulesViolation


class PhasingRules:
    @staticmethod
    def _phase_key(ref):
        return str(ref.card_id)+'@'+str(ref.incarnation)

    def _prune_phase_links(self):
        for key,row in tuple(self.phase_links.items()):
            try:obj=self.state.get(ObjectRef.from_json(row['ref']))
            except RulesViolation:obj=None
            if obj is None or obj.zone!=Zone.BATTLEFIELD or not obj.phased:
                del self.phase_links[key]

    def _phase_out(self, refs):
        self._prune_phase_links()
        objects={obj.ref:obj for obj in self.state.objects(Zone.BATTLEFIELD) if not obj.phased}
        direct={ref for ref in refs if ref in objects}
        affected=set(direct)
        while True:
            attached={ref for ref,obj in objects.items() if obj.attached_to in affected}
            if attached<=affected:break
            affected.update(attached)
        def root(ref):
            seen=set()
            while objects[ref].attached_to in affected:
                if ref in seen:raise RulesViolation('Cyclic phasing attachment')
                seen.add(ref);ref=objects[ref].attached_to
            return ref
        planned=[]
        for ref in sorted(affected):
            anchor=root(ref)
            planned.append((ref,{'ref':ref.to_json(),'root':anchor.to_json(),
                'controller':objects[ref].controller}))
        # No choices, observations or state-based actions occur between statuses.
        for ref,row in planned:
            self.state.phase(ref,True);self.phase_links[self._phase_key(ref)]=row
        if planned:
            self._combat_prune()
            self._event('objects_phased_out',refs=[ref.to_json() for ref,_ in planned])

    def _phase_at_untap(self, active):
        self._prune_phase_links()
        previous=self.state.players.index(self.active)
        upcoming=self.state.players.index(active)
        distance=(upcoming-previous)%len(self.state.players) or len(self.state.players)
        passed={self.state.players[(previous+n)%len(self.state.players)] for n in range(1,distance+1)}
        incoming=set()
        for row in self.phase_links.values():
            if row['root']!=row['ref']:continue
            controller=row['controller']
            if controller==active or controller not in self.state.live_players and controller in passed:
                incoming.add(ObjectRef.from_json(row['root']))
        returning=[ObjectRef.from_json(row['ref']) for row in self.phase_links.values()
                   if ObjectRef.from_json(row['root']) in incoming]
        views=self.characteristics()
        outgoing=[obj.ref for obj in self.state.objects(Zone.BATTLEFIELD,controller=active)
                  if not obj.phased and 'phasing' in views[obj.ref].keywords]
        self._phase_out(outgoing)
        for ref in returning:
            self.state.phase(ref,False);self.phase_links.pop(self._phase_key(ref),None)
        if returning:self._event('objects_phased_in',refs=[ref.to_json() for ref in returning])

    def _validate_untap(self, active):
        if any(obj.phased and self._phase_key(obj.ref) not in self.phase_links
               for obj in self.state.objects(Zone.BATTLEFIELD,controller=active)):
            raise RulesViolation('Phased fixture lacks a registered return lifecycle')
