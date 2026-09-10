"""Exact-incarnation Aura and Equipment attachments and delayed leaves triggers.

Protection, reconfigure, Fortifications and phasing propagation remain unsupported.
The mixin shares the kernel's mutation/choice/event boundaries; it has no card
names, independent scheduler or alternate state store.
"""
import json
from .rules_state import Zone, ObjectRef, RulesObject, RulesViolation
from .rules_characteristics import matches
from .rules_program import (AbilityProgram, WithAttached, SetAttachmentRule,
                            Attach, DelayedTrigger, Selector, encode, decode)


class AttachmentRules:
    @staticmethod
    def _attachment_key(ref):
        return json.dumps(ref.to_json(), sort_keys=True)

    def _enchant_rule(self, source):
        override = self.attachment_rules.get(self._attachment_key(source.ref))
        if override:
            return decode(override['selector']), ObjectRef.from_json(override['exact']) if override['exact'] else None
        return self.definition(source).enchant, None

    def _attachment_legal(self, source, target):
        if source.zone!=Zone.BATTLEFIELD or source.phased:return False
        selector, exact = self._enchant_rule(source)
        view=self.effective(source.ref)
        if selector is None and 'Equipment' in view.subtypes:
            selector=Selector(Zone.BATTLEFIELD,types=('Creature',))
        if 'Creature' in view.types:
            return False
        if selector is None or target is None or source.ref.card_id == target.card_id:
            return False
        if exact is not None and target != exact:
            return False
        if selector.zone==Zone.LIBRARY:raise RulesViolation('Library attachment restrictions are not supported')
        try:attached=self.state.get(target)
        except RulesViolation:return False
        return matches(selector,attached,self.effective(target),source)

    def _aura_entry(self, proposal, frame, key):
        definition = self.definitions[proposal.copied_definition or proposal.before.effective_definition]
        if definition.enchant is None:
            return True, None
        context = {**frame, 'source': proposal.before.to_json(), 'controller': proposal.controller}
        legal = tuple(obj for obj in self._query(definition.enchant, context)
                      if obj.ref.card_id != proposal.before.ref.card_id)
        if (frame.get('spell') and self._source(frame).ref == proposal.before.ref
                and self.definition(self._source(frame)).enchant is not None):
            targets = tuple(ObjectRef.from_json(ref) for ref in frame['targets'])
            return (True, targets[0]) if len(targets) == 1 and targets[0] in {obj.ref for obj in legal} else (False, None)
        if not legal:
            return False, None
        chosen = self._choose(key + ':aura-entry', proposal.controller, 'aura_attachment',
            'Choose what this Aura will enchant as it enters.', self._options(legal), 1, 1)
        return True, chosen[0].ref

    def _execute_attachment(self, effect, frame, key):
        source = self._source(frame)
        if isinstance(effect, WithAttached):
            try:
                current = self.state.get(source.ref)
            except RulesViolation:
                return True
            if current.zone == Zone.BATTLEFIELD and current.attached_to is not None:
                frame['bindings']['attached'] = [current.attached_to.to_json()]
                self._insert(frame, effect.effects)
        elif isinstance(effect, SetAttachmentRule):
            try:
                current = self.state.get(source.ref)
            except RulesViolation:
                return True
            if current.zone != Zone.BATTLEFIELD:
                return True
            refs = self._refs(frame, effect.exact_subject) if effect.exact_subject else ()
            if effect.exact_subject and len(refs) != 1:
                raise RulesViolation('An exact enchant restriction needs one bound object')
            self.attachment_rules[self._attachment_key(source.ref)] = {
                'source': source.ref.to_json(), 'selector': encode(effect.selector),
                'exact': refs[0].to_json() if refs else None}
            self._event('enchant_rule_changed', source=source.ref.to_json())
        elif isinstance(effect, Attach):
            refs, targets = self._refs(frame, effect.subject), self._refs(frame, effect.to)
            if len(refs) != 1 or len(targets) != 1:
                raise RulesViolation('Attach requires one source and one destination')
            try:
                aura = self.state.get(refs[0])
            except RulesViolation:
                return True
            if aura.zone == Zone.BATTLEFIELD and self._attachment_legal(aura, targets[0]):
                if self.state.attach(aura.ref, targets[0]):
                    self._event('attached', source=aura.ref.to_json(), target=targets[0].to_json())
        elif isinstance(effect, DelayedTrigger):
            delayed_id = self._id('delayed')
            self.delayed_triggers.append({'id': delayed_id, 'source': source.to_json(),
                'ability': encode(AbilityProgram(delayed_id, effect.event, effect.effects)),
                'controller': frame['controller'],
                'bindings': json.loads(json.dumps(frame['bindings']))})
            self._event('delayed_trigger_registered', delayed=delayed_id, source=source.ref.to_json())
        else:
            return False
        return True

    def _collect_delayed(self, events):
        for delayed in tuple(self.delayed_triggers):
            source = RulesObject.from_json({**delayed['source'],'controller':delayed['controller']})
            ability = decode(delayed['ability'])
            if delayed['controller'] not in self.state.live_players:
                self.delayed_triggers.remove(delayed);continue
            if any(self._matches(ability.event, source, event=event) for event in events):
                # Controller is bound at creation, independent of later control changes.
                self._trigger(source, ability, delayed['bindings'])
                self.pending_triggers[-1]['controller'] = delayed['controller']
                self.delayed_triggers.remove(delayed)
                self._event('delayed_trigger_fired', delayed=delayed['id'])

    def _prune_attachment_rules(self):
        for key, rule in tuple(self.attachment_rules.items()):
            try:
                current = self.state.get(ObjectRef.from_json(rule['source']))
            except RulesViolation:
                del self.attachment_rules[key]
                continue
            if current.zone != Zone.BATTLEFIELD:
                del self.attachment_rules[key]
