"""Prevent an automatic payment from silently spending a player's last life."""
from itertools import combinations


def safe_colors(player, source):
    from .engine import Perm, TALISMAN_COLORS, confluence_free_colors
    if not isinstance(source, Perm):return None
    name=source.copy_of or source.name
    if name in TALISMAN_COLORS:return {'C'}
    if name=='Mana Confluence':return confluence_free_colors(player,source)
    return None


def life_cost(player, plan):
    if plan is None:return 0
    sources,colors=plan[:2]
    unique={id(source):source for source in sources if safe_colors(player,source) is not None}
    return sum(colors.get(key) not in safe_colors(player,source) for key,source in unique.items())


def select(player, initial, sources, solve, fixed_life=0):
    """Preserve a nonlethal existing allocation; retry only a lethal default.

    Restrict costly colors by source identity, so reflected units charge life
    once and filters cannot hide a damaging activation used as their input.
    Pending lifegain is not assumed to make a lethal payment safe.
    """
    if initial is None:return None
    budget=player.life-1-fixed_life
    if life_cost(player,initial)<=budget:return initial
    if budget<0:return None
    if callable(sources):sources=sources()
    risky=list(dict.fromkeys(id(source) for source,colors,_ in sources
        if safe_colors(player,source) is not None and set(colors)-safe_colors(player,source)))
    for count in range(min(budget,len(risky))+1):
        for enabled in combinations(risky,count):
            enabled=set(enabled);restricted=[]
            for source,colors,amount in sources:
                free=safe_colors(player,source)
                allowed=set(colors) if free is None or id(source) in enabled else set(colors)&free
                if allowed:restricted.append((source,allowed,amount))
            candidate=solve(restricted)
            if candidate is not None and life_cost(player,candidate)<=budget:return candidate
    return None
