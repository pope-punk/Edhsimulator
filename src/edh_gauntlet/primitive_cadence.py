"""Coarse tactical freshness: nonland battlefields and own hand count only."""
from .rules_adapter import digest


def summary(board,actor):
    # Stable object ordering; routine nonland tapping and combat damage count.
    fields=('ref','definition_id','face','controller','owner','types','subtypes','supertypes',
            'keywords','colors','power','toughness','tapped','phased','counters','damage','attached_to','loyalty_used_this_turn')
    chunks={}
    for seat,cards in board['zones']['battlefield'].items():
        parts={kind:[] for kind in ('lands','nonlands')}
        for card in cards:
            parts['lands' if 'Land' in card['types'] else 'nonlands'].append({k:card[k] for k in fields if k in card})
        chunks[seat]={kind:digest(sorted(rows,key=digest)) for kind,rows in parts.items()}
    own=next(p for p in board['players'] if p['seat']==actor)
    return {'boards':chunks,'hand_count':own['hand_count']}


def relevant(value):
    return {'boards':{seat:chunk['nonlands'] for seat,chunk in value['boards'].items()},'hand_count':value['hand_count']}


def changed(campaign,state,actor):
    previous=state['actors'][actor].get('tactical_baseline')
    now=summary(campaign.store.packet(actor),actor)
    return previous is None or relevant(now)!=relevant(previous)
