"""Build an unlaunched fixed pod from reviewed catalog programs and explicit seats.

This is fresh construction, never a legacy conversion or a production admission
bypass. The returned kernel is at its first private mulligan choice. A campaign
must bind and durably store it before creating any model context.
"""
import json
from pathlib import Path
from .catalog import load_catalog, EXPECTED_DECK_SLOTS
from .paths import PROJECT_ROOT
from .rules_bundle import load_reviewed, digest
from .rules_kernel import RulesKernel
from .rules_state import RulesState, RulesViolation, Zone


def fresh_pod(*, seed, starting_player, root=PROJECT_ROOT):
    root = Path(root)
    config = json.loads((root / 'data/decks/pod_configuration.json').read_text(encoding='utf-8'))
    if (set(config) != {'schema', 'starting_life', 'starting_hand_size', 'seats'}
            or config['schema'] != 1 or config['starting_life'] != 40 or config['starting_hand_size'] != 7
            or type(config['seats']) is not list or len(config['seats']) != 4
            or any(type(row) is not dict or set(row) != {'actor', 'commander'} for row in config['seats'])):
        raise RulesViolation('Unsupported fixed-pod configuration')
    players = tuple(row['actor'] for row in config['seats'])
    if len(set(players)) != 4 or set(players) != set(EXPECTED_DECK_SLOTS) or starting_player not in players:
        raise RulesViolation('Invalid fixed-pod seat order or starting player')
    catalog = load_catalog(root / 'data/catalog/cards.json')
    cards = {c.card_id: c for c in catalog}
    programs = load_reviewed(root)
    decks = {};identities = {};commanders = {}
    for seat in config['seats']:
        actor = seat['actor'];commander = cards.get(seat['commander'])
        rows = catalog.deck_entries(actor)
        if commander is None or sum(o.quantity for c, o in rows if c.card_id == commander.card_id) != 1:
            raise RulesViolation('Commander must occur exactly once in its deck')
        if sum(o.quantity for c, o in rows) != EXPECTED_DECK_SLOTS[actor]:
            raise RulesViolation('Deck must contain exactly 100 physical cards')
        if any(c.card_id not in programs for c, o in rows):
            raise RulesViolation('Every deck card requires a reviewed program')
        if any(not set(c.color_identity) <= set(commander.color_identity) for c, o in rows):
            raise RulesViolation('Deck color identity exceeds its commander')
        decks[actor] = rows;identities[actor] = list(commander.color_identity);commanders[actor] = commander.card_id
    state = RulesState(players, seed=seed, commander_identities=identities, starting_life=40)
    for seat_index, actor in enumerate(players):
        ordinal = 0
        for card, occurrence in decks[actor]:
            for _ in range(occurrence.quantity):
                is_commander = card.card_id == commanders[actor]
                # Physical IDs do not reveal a card name or its shuffled order.
                instance = digest({'seed': seed, 'seat': seat_index, 'slot': ordinal})
                state.add_card(instance, programs[card.card_id]['program'].definition_id, actor,
                               Zone.COMMAND if is_commander else Zone.LIBRARY, commander=is_commander)
                ordinal += 1
    kernel = RulesKernel(state, tuple(row['program'] for row in programs.values()), starting_player)
    kernel.begin_mulligans(starting_player)
    return kernel
