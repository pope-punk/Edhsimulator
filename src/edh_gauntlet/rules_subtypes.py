"""Named subtype sets from pinned CR 205.3i/m, with catalog-normalized spelling."""
from types import MappingProxyType
from functools import lru_cache
from .rules_creature_types import CREATURE_TYPES

BASIC_LAND_TYPES=frozenset(('Plains','Island','Swamp','Mountain','Forest'))
NONBASIC_LAND_TYPES=frozenset(('Cave','Desert','Gate','Lair','Locus','Mine','Planet',
    'Power-Plant','Sphere','Tower','Town',"Urza's"))
LAND_TYPES=BASIC_LAND_TYPES|NONBASIC_LAND_TYPES
SUBTYPE_SETS=MappingProxyType({'creature':CREATURE_TYPES,'nonbasic_land':NONBASIC_LAND_TYPES,'land':LAND_TYPES})
SUBTYPE_SUPPORT=MappingProxyType({'creature':frozenset(('Creature','Kindred')),'nonbasic_land':frozenset(('Land',)),'land':frozenset(('Land',))})

@lru_cache(maxsize=128)
def expanded_subtypes(subtypes,sets):
    result=frozenset(subtypes)
    for name in sets:result=result|SUBTYPE_SETS[name]
    return result
