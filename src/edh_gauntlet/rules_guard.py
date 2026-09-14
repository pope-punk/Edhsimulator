"""Shared color protection, regeneration and public turn-history observations."""
from .rules_state import ObjectRef, Zone, RulesViolation
from .rules_program import ChooseProtection, Regenerate, UntilEndOfTurn, AddKeywords
from .rules_replacements import ReplacementCandidate
from .rules_choices import Option

PROTECTION_COLORS = {'W':'white','U':'blue','B':'black','R':'red','G':'green'}


def protection_matches(recipient, source):
    return any('protection_'+PROTECTION_COLORS[color] in recipient.keywords for color in source.colors)


class GuardRules:
    def _validate_guard_state(self):
        history=self.turn_history
        if (not isinstance(history,dict) or set(history)!={'turn','attacked','freerunning'}
                or type(history['turn']) is not int or not 0<=history['turn']<=self.state.turn_number
                or any(not isinstance(history[kind],list) or any(type(p) is not str or p not in self.state.players for p in history[kind])
                    or len(history[kind])!=len(set(history[kind])) for kind in ('attacked','freerunning'))):
            raise RulesViolation('Invalid public turn history')
        if (not isinstance(self.upkeep_history,dict) or set(self.upkeep_history)!=set(self.state.players)
                or any(type(n) is not int or not 0<=n<=self.state.sequence for n in self.upkeep_history.values())):
            raise RulesViolation('Invalid upkeep history')
        if not isinstance(self.regeneration_shields,dict):raise RulesViolation('Invalid regeneration shields')
        for key,ref in self.regeneration_shields.items():
            if (type(key) is not str or not key or not isinstance(ref,dict) or set(ref)!={'card_id','incarnation'}
                    or type(ref['card_id']) is not str or not ref['card_id']
                    or type(ref['incarnation']) is not int or ref['incarnation']<0):
                raise RulesViolation('Invalid regeneration shield identity')

    def _history_players(self, kind):
        return frozenset(self.turn_history[kind]) if self.turn_history['turn']==self.state.turn_number else frozenset()

    def _record_turn_fact(self, kind, actor):
        if self.turn_history['turn']!=self.state.turn_number:
            self.turn_history={'turn':self.state.turn_number,'attacked':[],'freerunning':[]}
        if actor not in self.turn_history[kind]:
            self.turn_history[kind].append(actor)
            self._event('turn_fact_recorded',fact=kind,player=actor)

    def _regeneration_candidates(self, proposal):
        if not proposal.destruction or proposal.destination!=Zone.GRAVEYARD or proposal.before.zone!=Zone.BATTLEFIELD:
            return ()
        return tuple(ReplacementCandidate(key,'Regenerate this permanent','regenerate',3,proposal.before.controller)
            for key,ref in self.regeneration_shields.items() if ref==proposal.before.ref.to_json())

    def _remove_regenerated_from_combat(self, refs):
        if self.combat is None:return
        refs=set(refs)
        removed=[row['uid'] for row in self.combat['attackers'] if ObjectRef.from_json(row['ref']) in refs]
        self.combat['attackers']=[row for row in self.combat['attackers'] if ObjectRef.from_json(row['ref']) not in refs]
        for key,rows in self.combat['blocks'].items():
            removed.extend(row['uid'] for row in rows if ObjectRef.from_json(row['ref']) in refs)
            self.combat['blocks'][key]=[row for row in rows if ObjectRef.from_json(row['ref']) not in refs]
        # The attacker's blocked designation remains even if its blockers leave.
        if removed:self._event('regenerated_removed_from_combat',uids=sorted(set(removed)))

    def _execute_guard(self, effect, frame, key):
        if isinstance(effect,ChooseProtection):
            options=tuple(Option(color,name.capitalize()) for color,name in PROTECTION_COLORS.items())
            chosen=self._choose(key+':color',frame['controller'],'protection_color','Choose a color for protection until end of turn.',options,1,1)
            self._insert(frame,(UntilEndOfTurn(effect.subject,(AddKeywords(('protection_'+PROTECTION_COLORS[chosen[0].key],)),)),))
            return True
        if isinstance(effect,Regenerate):
            for index,ref in enumerate(self._refs(frame,effect.subject)):
                try:obj=self.state.get(ref)
                except RulesViolation:continue
                if obj.zone!=Zone.BATTLEFIELD or obj.phased:continue
                shield=key+':regeneration:'+str(index)
                self.regeneration_shields[shield]=ref.to_json()
                self._event('regeneration_shield_created',shield=shield,source=ref.to_json())
            return True
        return False
