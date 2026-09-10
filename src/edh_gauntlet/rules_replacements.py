"""Pure zone-event proposals and replacement applicability.

No state is mutated until all choices for a simultaneous batch are complete.
This slice supports destination replacements, entry copying and conditional
tapped/untapped entry. Entry-control changes, paid entry choices, transforming
entries and prevention remain outside this vocabulary.
"""
from dataclasses import dataclass, replace
from .rules_state import RulesObject, Zone


@dataclass(frozen=True)
class ZoneProposal:
    before: RulesObject
    destination: Zone
    controller: str
    copied_definition: str | None = None
    used: frozenset[str] = frozenset()
    commander_considered: bool = False
    trace: tuple = ()
    tapped: bool = False
    counters: tuple = ()


@dataclass(frozen=True)
class ReplacementCandidate:
    key: str
    label: str
    kind: str
    priority: int
    controller: str
    program: object = None
    source: RulesObject | None = None
    copy_tapped: bool = False


def affected_player(proposal):
    obj = proposal.before
    return obj.controller if obj.zone in {Zone.BATTLEFIELD, Zone.STACK} else obj.owner


def candidates(state, definitions, proposal, affected_types=None, applicable_entry_ids=None):
    obj = proposal.before
    definition = definitions[proposal.copied_definition or obj.effective_definition]
    result = []
    if obj.commander and proposal.destination in {Zone.HAND, Zone.LIBRARY} and not proposal.commander_considered:
        result.append(ReplacementCandidate('rule:903.9b', 'Commander destination', 'commander', 3, obj.owner))
    if proposal.destination == Zone.BATTLEFIELD and definition.entry_copy:
        key = f'entry-copy:{obj.ref.card_id}@{obj.ref.incarnation}:{definition.definition_id}'
        if key not in proposal.used:
            result.append(ReplacementCandidate(key, 'Choose an entry copy', 'copy', 2,
                                               proposal.controller, definition.entry_copy,copy_tapped=definition.entry_copy_tapped))
    if proposal.destination == Zone.BATTLEFIELD:
        for modifier in definition.entry_modifiers:
            if modifier.selector is not None:continue
            key=f'entry:{obj.ref.card_id}@{obj.ref.incarnation}:{definition.definition_id}:{modifier.modifier_id}'
            if key not in proposal.used and (applicable_entry_ids is None and modifier.condition is None or applicable_entry_ids is not None and modifier.modifier_id in applicable_entry_ids):
                result.append(ReplacementCandidate(key,definition.name+': '+modifier.modifier_id,'entry',3,proposal.controller,modifier))
    for source in state.objects(Zone.BATTLEFIELD):
        if source.phased:
            continue
        for program in definitions[source.effective_definition].replacements:
            key = f'{source.ref.card_id}@{source.ref.incarnation}:{program.replacement_id}'
            if key in proposal.used or program.destination != proposal.destination:
                continue
            if program.from_zone is not None and program.from_zone != obj.zone:
                continue
            if program.subject == 'self' and source.ref != obj.ref:
                continue
            if program.relation == 'owned' and obj.owner != source.controller:
                continue
            if program.relation == 'controlled' and (obj.zone not in {Zone.BATTLEFIELD, Zone.STACK} or obj.controller != source.controller):
                continue
            if not set(program.types) <= (set(definition.types) if affected_types is None else affected_types):
                continue
            result.append(ReplacementCandidate(key, definitions[source.effective_definition].name + ': ' + program.replacement_id,
                                               'redirect', 3, source.controller, program))
    if not result:
        return ()
    priority = min(candidate.priority for candidate in result)
    return tuple(candidate for candidate in result if candidate.priority == priority)


def apply_replacement(proposal, candidate, *, accepted=True, copied_definition=None,counters=None):
    destination = proposal.destination
    copy = proposal.copied_definition
    tapped = proposal.tapped
    used = proposal.used | {candidate.key}
    commander_considered = proposal.commander_considered
    if candidate.kind == 'commander':
        commander_considered = True
        if accepted:
            destination = Zone.COMMAND
    elif candidate.kind == 'copy':
        if accepted:
            copy = copied_definition
            tapped = tapped or candidate.copy_tapped
    elif candidate.kind == 'entry':
        if accepted:tapped = candidate.program.tapped
    elif candidate.kind in {'entry_counters','counter'}:
        pass  # The kernel evaluates quantities and supplies the new counter proposal.
    elif accepted:
        destination = candidate.program.redirect
    # CR 903.9b is reconsidered after another effect changes the event, even
    # after an earlier decline. Ordinary replacements remain in `used`.
    if candidate.kind != 'commander' and (destination != proposal.destination or copy != proposal.copied_definition):
        commander_considered = False
    trace = {'replacement': candidate.key, 'replacement_kind': candidate.kind, 'accepted': accepted,
             'from_destination': proposal.destination.value, 'to_destination': destination.value,
             'copied_definition': copy, 'from_tapped': proposal.tapped, 'to_tapped': tapped}
    if counters is not None:trace['counters']=list(counters)
    return replace(proposal, destination=destination, copied_definition=copy,
                   used=frozenset(used), commander_considered=commander_considered,
                   tapped=tapped,counters=proposal.counters if counters is None else counters,
                   trace=proposal.trace + (trace,))
