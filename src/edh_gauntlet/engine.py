#!/usr/bin/env python3
from __future__ import annotations
from .continuous import read_only_views
import re, json, random, hashlib, math, shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path
from collections import defaultdict, Counter
from typing import List, Dict, Optional, Tuple, Set, Any

from .catalog import load_catalog
from .event_visibility import event_visibility, public_event_stub
from . import mana_filters

from .paths import PROJECT_ROOT
RULES_FILE = PROJECT_ROOT / 'data' / 'reference' / 'four_deck_oracle.txt'

DECK_HEADINGS = {
    'Reaminatour': 'REAMINATOUR — AMINATOU, VEIL PIERCER',
    'Minsc & Boo': 'MINSC & BOO, TIMELESS HEROES',
    'Omo': 'OMO, QUEEN OF VESUVA',
    'Elenda': 'ELENDA, SAINT OF DUSK',
}
COMMANDERS = {
    'Reaminatour': 'Aminatou, Veil Piercer',
    'Minsc & Boo': 'Minsc & Boo, Timeless Heroes',
    'Omo': 'Omo, Queen of Vesuva',
    'Elenda': 'Elenda, Saint of Dusk',
}
COLOR_ID = {
    'Reaminatour': set('WUB'),
    'Minsc & Boo': set('RG'),
    'Omo': set('GU'),
    'Elenda': set('WB'),
}

@dataclass(frozen=True)
class CardDef:
    name: str
    mana_cost: str
    type_line: str
    text: str
    quantity: int
    deck: str
    mv: int

    @property
    def is_land(self): return 'Land' in self.type_line.split(' // ')[0]
    @property
    def is_creature(self): return 'Creature' in self.type_line.split(' // ')[0]
    @property
    def is_enchantment(self): return 'Enchantment' in self.type_line.split(' // ')[0]
    @property
    def is_artifact(self): return 'Artifact' in self.type_line.split(' // ')[0]
    @property
    def is_planeswalker(self): return 'Planeswalker' in self.type_line.split(' // ')[0]
    @property
    def is_instant(self): return 'Instant' in self.type_line.split(' // ')[0]
    @property
    def is_sorcery(self): return 'Sorcery' in self.type_line.split(' // ')[0]
    @property
    def is_permanent(self): return not (self.is_instant or self.is_sorcery)

@dataclass
class CardObj:
    uid: str
    d: CardDef

@dataclass(eq=False)
class Perm:
    uid: str
    name: str
    owner: str
    controller: str
    tapped: bool=False
    summoning_sick: bool=True
    counters: Dict[str,int]=field(default_factory=dict)
    attached_to: Optional[str]=None
    copy_of: Optional[str]=None
    token: bool=False
    base_power: int=0
    base_toughness: int=0
    keywords: Set[str]=field(default_factory=set)
    entered_turn: int=0
    metadata: Dict[str,Any]=field(default_factory=dict)

@dataclass
class PlayerState:
    name: str
    life: int=40
    library: List[CardObj]=field(default_factory=list)
    hand: List[CardObj]=field(default_factory=list)
    graveyard: List[CardObj]=field(default_factory=list)
    exile: List[CardObj]=field(default_factory=list)
    battlefield: List[Perm]=field(default_factory=list)
    commander: Optional[CardObj]=None
    command_tax: int=0
    eliminated: bool=False
    land_plays_used: int=0
    land_play_limit: int=1
    energy: int=0
    treasures: int=0
    clues: int=0
    commander_damage: Dict[str,int]=field(default_factory=dict)
    miracle_card_uid: Optional[str]=None
    cards_drawn_this_turn: int=0
    spells_cast_this_turn: int=0
    enchantments_entered_this_turn: int=0
    life_gained_this_turn: int=0
    counters_placed_this_turn: int=0
    dungeon: Dict[str,Any]=field(default_factory=dict)

# Exact or deliberately simplified deterministic handlers by card. Cards outside this table can still be
# cast as permanents; their static/combat text is processed by generic hooks. A material-unsupported audit
# is emitted whenever such a card's unhandled rules text could affect the simulated line.
EXACT_HANDLERS = set()


def mana_value(cost:str)->int:
    if not cost or cost=='—': return 0
    face=cost.split(' // ')[0]
    total=0
    for s in re.findall(r'\{([^}]+)\}',face):
        if s.isdigit(): total += int(s)
        elif s in {'X','Y','Z'}: pass
        elif '/' in s:
            total += 1
        else: total += 1
    return total

CATALOG=load_catalog()


def _catalog_card_def(card, occurrence):
    """Project immutable catalog data onto the stable, deck-specific CardDef API."""

    return CardDef(
        card.name,
        card.mana_cost,
        card.type_line,
        card.text,
        occurrence.quantity,
        occurrence.deck,
        card.front.mana_value,
    )


# Ordinals in the catalog preserve the exact former reference-file row order.
# Keeping deck-specific CardDef instances also preserves quantity/deck fields for
# shared cards while CARDDEF retains the historical last-deck-wins projection.
DECKDEFS={
    deck:[_catalog_card_def(card,occurrence) for card,occurrence in CATALOG.deck_entries(deck)]
    for deck in DECK_HEADINGS
}
if any(sum(card.quantity for card in cards)!=100 for cards in DECKDEFS.values()):
    raise ValueError('catalog-backed deck definitions must contain exactly 100 cards per deck')
CARDDEF={card.name:card for deck in DECK_HEADINGS for card in DECKDEFS[deck]}

# Generated compatibility views; the canonical definitions own every value.
_CATALOG_COMPAT=CATALOG.legacy_projections()
PT=dict(_CATALOG_COMPAT['PT'])
KEYWORDS=dict((name,set(values)) for name,values in _CATALOG_COMPAT['KEYWORDS'].items())


def cost_symbols(card:CardDef, command_tax=0, miracle=False, x_value=0):
    cost=card.mana_cost.split(' // ')[0]
    need=Counter(); generic=command_tax
    for s in re.findall(r'\{([^}]+)\}',cost):
        if s.isdigit(): generic += int(s)
        elif s=='X': generic += x_value
        elif s in {'W','U','B','R','G','C'}: need[s]+=1
        elif '/' in s:
            # hybrid: take a color from identity if possible; represented as flexible pair
            need[s]+=1
        else: generic += 1
    if miracle and card.is_enchantment:
        generic=max(0,generic-4)
    return generic,need

# Generated reverse indexes.  These are derived from card-owned metadata, not
# independent lists that must be maintained when a card is added.
LAND_COLOR_HINTS=dict((name,set(values)) for name,values in _CATALOG_COMPAT['LAND_COLOR_HINTS'].items())
FETCHES=set(_CATALOG_COMPAT['FETCHES'])
FETCH_TYPES={name:set(values) for name,values in _CATALOG_COMPAT['FETCH_TYPES'].items()}
BOUNCE_LANDS=set(_CATALOG_COMPAT['BOUNCE_LANDS'])
TAPPED_LANDS=set(_CATALOG_COMPAT['TAPPED_LANDS'])
SHOCK_LANDS=set(_CATALOG_COMPAT['SHOCK_LANDS'])
SLOW_LANDS=set(_CATALOG_COMPAT['SLOW_LANDS'])
MANA_ROCKS=set(_CATALOG_COMPAT['MANA_ROCKS'])
MANA_DORKS=set(_CATALOG_COMPAT['MANA_DORKS'])


def permanent_identity_hidden(perm:Perm)->bool:
    metadata=perm.metadata or {}
    return bool(
        metadata.get('face_down') or metadata.get('identity_hidden') or
        metadata.get('hidden_identity') or metadata.get('hidden') or
        getattr(perm,'face_down',False) or getattr(perm,'identity_hidden',False) or
        getattr(perm,'hidden_identity',False)
    )


def permanent_phased_out(perm:Perm)->bool:
    metadata=perm.metadata or {}
    return bool(metadata.get('phased_out') or getattr(perm,'phased_out',False))


def permanent_mana_inactive(perm:Perm)->bool:
    return permanent_identity_hidden(perm) or permanent_phased_out(perm)


def omo_everything_active(p:PlayerState)->bool:
    return any(
        (permanent.copy_of or permanent.name)=='Omo, Queen of Vesuva' and not permanent_mana_inactive(permanent)
        for player in getattr(p,'_table_players',{p.name:p}).values()
        for permanent in player.battlefield
    )


def land_colors(p:PlayerState, perm:Perm, *, reference_base=False)->Set[str]:
    """Mana colors this land can actually produce under the current modeled state.
    Uses stored rules text rather than assuming every land taps for {C}.
    Omo everything counters add all five basic land types, which grant WUBRG mana abilities.
    """
    n=perm.copy_of or perm.name
    d=CARDDEF.get(n)
    typ=(d.type_line if d else '')+' '+' '.join(perm.metadata.get('land_types',[]))
    cols=set()
    for basic,col in [('Plains','W'),('Island','U'),('Swamp','B'),('Mountain','R'),('Forest','G')]:
        if basic in typ: cols.add(col)
    cols |= LAND_COLOR_HINTS.get(n,set())
    if d:
        low=d.text.lower()
        # Only symbols in the effect of an ``add`` clause are mana output.
        # Scanning the whole rules text after seeing the word "add" mistakes
        # colored activation costs in later abilities for producible mana (for
        # example Hall of Heliod's Generosity's {1}{W} recursion cost).
        for clause in re.findall(r'\badd\b([^\.\n]*)',d.text,re.I):
            for sym in re.findall(r'\{([WUBRGC])\}',clause,re.I):
                cols.add(sym.upper())
        if 'mana of any color' in low or 'one mana of any color' in low: cols |= set('WUBRG')
    # These utility abilities have non-mana costs.  Their lands do not freely
    # produce the colors mentioned elsewhere in the rules text.
    if n in {'Lazotep Quarry','Talon Gates of Madara','Hashep Oasis'}:cols={'C'}
    if n=='Command Tower':cols=set(COLOR_ID[p.name])
    if reference_base and n in {'Exotic Orchard','Horizon of Progress'}:cols=set()
    if perm.counters.get('everything',0)>0 and omo_everything_active(p):
        cols |= set('WUBRG')
    if perm.counters.get('flood',0)>0:
        cols.add('U')
    if any(z.name=='Dryad of the Ilysian Grove' and not permanent_mana_inactive(z)
           for z in p.battlefield):
        # Dryad gives each land every basic land type in addition to its others.
        cols |= set('WUBRG')
    return cols


def _has_land_type(p:PlayerState, type_fragment:str)->bool:
    if type_fragment in {'Plains','Island','Swamp','Mountain','Forest'} and any(
        z.name=='Dryad of the Ilysian Grove' and not permanent_mana_inactive(z)
        for z in p.battlefield
    ):
        return any(is_land_permanent(z) for z in p.battlefield)
    for z in p.battlefield:
        if land_has_type(z,type_fragment,p):return True
    return False

def land_has_type(perm:Perm,type_fragment:str,p:Optional[PlayerState]=None)->bool:
    d=CARDDEF.get(perm.copy_of or perm.name)
    return bool(is_land_permanent(perm) and ((d and type_fragment in d.type_line) or type_fragment in perm.metadata.get('land_types',[]) or
                perm.name=='Planar Nexus' or (p is not None and perm.counters.get('everything',0)>0 and omo_everything_active(p)) or
                (type_fragment=='Island' and perm.counters.get('flood',0)>0)))

def is_land_permanent(perm:Perm)->bool:
    if permanent_mana_inactive(perm):return False
    d=CARDDEF.get(perm.copy_of or perm.name)
    return bool(perm.metadata.get('is_land') or (d and d.is_land))


def mana_reflection_multiplier(p):
    return 2**sum((z.copy_of or z.name)=='Mana Reflection' and not permanent_mana_inactive(z)
                  for z in p.battlefield)


TALISMAN_COLORS={'Talisman of Dominance':'UB','Talisman of Hierarchy':'WB','Talisman of Progress':'WU'}


def confluence_free_colors(p:PlayerState,perm:Perm)->Set[str]:
    """Independent mana abilities granted to Mana Confluence do not pay its printed cost."""
    colors={color for basic,color in [('Plains','W'),('Island','U'),('Swamp','B'),('Mountain','R'),('Forest','G')]
            if basic in perm.metadata.get('land_types',[])}
    if perm.counters.get('flood',0):colors.add('U')
    if perm.counters.get('everything',0) and omo_everything_active(p):colors |= set('WUBRG')
    if any((z.copy_of or z.name) in {'Dryad of the Ilysian Grove','Chromatic Lantern'}
           and not permanent_mana_inactive(z) for z in p.battlefield):colors |= set('WUBRG')
    if any((z.copy_of or z.name)=='Yavimaya, Cradle of Growth' and not permanent_mana_inactive(z)
           for player in getattr(p,'_table_players',{p.name:p}).values() for z in player.battlefield):colors.add('G')
    return colors


def fellwar_colors(p:PlayerState)->Set[str]:
    """CR 106.7: resolve possible output, ignoring activation costs.

    A fixed point handles Orchard/Horizon references without recursion or
    inventing colors when the only lands reference one another.
    """
    players=getattr(p,'_table_players',{p.name:p})
    yavimaya=any(
        (z.copy_of or z.name)=='Yavimaya, Cradle of Growth' and not permanent_mana_inactive(z)
        for player in players.values() if not player.eliminated for z in player.battlefield)
    lands=[];outputs={}
    for opponent in players.values():
        if opponent.eliminated:continue
        lantern=any((z.copy_of or z.name)=='Chromatic Lantern' and not permanent_mana_inactive(z)
                    for z in opponent.battlefield)
        for land in opponent.battlefield:
            if not is_land_permanent(land):continue
            colors=land_colors(opponent,land,reference_base=True)
            name=land.copy_of or land.name
            if name=='Hashep Oasis':colors.add('G')
            if name in {'Lazotep Quarry','Talon Gates of Madara'}:colors |= set('WUBRG')
            if name=="Urza's Saga" and not land.metadata.get('urza_mana'):colors.discard('C')
            if yavimaya:colors.add('G')
            if lantern:colors |= set('WUBRG')
            lands.append((opponent,land));outputs[id(land)]=colors
    changed=True
    while changed:
        changed=False
        for owner,land in lands:
            name=land.copy_of or land.name
            if name not in {'Exotic Orchard','Horizon of Progress'}:continue
            colors=outputs[id(land)]
            before=len(colors)
            for other,source in lands:
                if (other is owner)==(name=='Horizon of Progress'):
                    colors |= outputs[id(source)] & (set('WUBRGC') if name=='Horizon of Progress' else set('WUBRG'))
            changed |= len(colors)!=before
    return set().union(*(outputs[id(land)] for owner,land in lands if owner.name!=p.name)) & set('WUBRG')


def source_colors(p:PlayerState, perm:Perm, continuous_view=None)->Tuple[Set[str],int]:
    if perm.tapped: return set(),0
    # A face-down permanent has no printed mana abilities.  Besides matching
    # the rules, this prevents a public mana summary from leaking its hidden
    # front-face identity through the colors it appears able to produce.
    if permanent_mana_inactive(perm):return set(),0
    effective_name=perm.copy_of or perm.name
    d=CARDDEF.get(effective_name)
    live_view=continuous_view(perm) if continuous_view else None
    tap_ready=not perm.summoning_sick or 'haste' in (live_view.abilities if live_view else perm.keywords)
    if is_land_permanent(perm):
        if perm.summoning_sick and (perm.token or (d and d.is_creature)):
            return set(),0
        if effective_name=="Urza's Saga" and not perm.metadata.get('urza_mana'):return set(),0
        cols=land_colors(p,perm)
        if effective_name=='Mana Confluence' and p.life<1 and not p.dungeon.get('adjudicated_infinite_life'):
            cols &= confluence_free_colors(p,perm)
        if not cols: return set(),0
        amt=len(mana_filters.PAIRED_LANDS.get(effective_name,'C'))
        if effective_name=='Cloudpost':
            # Only Cloudpost has this printed ability; everything-counter lands merely count as Loci.
            amt=max(1,sum(1 for z in p.battlefield if land_has_type(z,'Locus',p)))
        elif effective_name=="Urza's Tower" and _has_land_type(p,"Urza's Mine") and _has_land_type(p,"Urza's Power-Plant"):
            amt=3
        elif effective_name in {"Urza's Mine","Urza's Power Plant"} and _has_land_type(p,"Urza's Tower") and (_has_land_type(p,"Urza's Power-Plant") if effective_name=="Urza's Mine" else _has_land_type(p,"Urza's Mine")):
            amt=2
        amt*=mana_reflection_multiplier(p)
        return cols,amt
    # Signets require an external payment; the filter path models both outputs.
    if effective_name in mana_filters.SIGNET_OUTPUTS:return set(),0
    if effective_name=='Sol Ring': cols,amt={'C'},2
    elif effective_name=='Arcane Signet': cols,amt=set(COLOR_ID[p.name]),1
    elif effective_name=='Fellwar Stone':
        cols=fellwar_colors(p);amt=int(bool(cols))
    elif effective_name=='Chromatic Lantern': cols,amt=set('WUBRG'),1
    elif effective_name in TALISMAN_COLORS: cols,amt=set(TALISMAN_COLORS[effective_name])|{'C'},1
    elif effective_name in {'Mind Stone','Thought Vessel','Pristine Talisman'}:cols,amt={'C'},1
    elif effective_name=='Charcoal Diamond':cols,amt={'B'},1
    elif effective_name=='Marble Diamond':cols,amt={'W'},1
    elif effective_name=='Sage of the Maze' and tap_ready: cols,amt=set(COLOR_ID[p.name]),2
    elif effective_name=='Kami of Whispered Hopes' and tap_ready: cols,amt=set(COLOR_ID[p.name]),max(1,(live_view.power if live_view else perm.base_power+perm.counters.get('+1/+1',0)))
    elif effective_name=='Fanatic of Rhonas' and tap_ready:
        ferocious=any(
            not permanent_mana_inactive(z) and (
                ('Creature' in continuous_view(z).types and continuous_view(z).power>=4) if continuous_view else
                ((z.token or (CARDDEF.get(z.copy_of or z.name) and CARDDEF[z.copy_of or z.name].is_creature)) and
                 (z.base_power+z.counters.get('+1/+1',0))>=4))
            for z in p.battlefield)
        cols,amt={'G'},(4 if ferocious else 1)
    elif effective_name=='Ruby, Daring Tracker' and tap_ready: cols,amt=set('RG'),1
    elif effective_name=='Priest of Titania' and tap_ready:
        # Priest counts all Elves on the battlefield, including opponents'.
        elves=0
        for owner in getattr(p,'_table_players',{p.name:p}).values():
            if owner.eliminated:continue
            for creature in owner.battlefield:
                if permanent_mana_inactive(creature):continue
                if continuous_view:
                    view=continuous_view(creature)
                    elf='Elf' in view.subtypes or view.rules.get('all_creature_types')
                else:
                    definition=CARDDEF.get(creature.copy_of or creature.name)
                    elf=bool(definition and 'Elf' in definition.type_line)
                    is_creature=bool((definition and definition.is_creature) or
                                     (creature.token and not creature.metadata.get('noncreature_token')))
                    elf |= bool(is_creature and not is_land_permanent(creature) and
                                creature.counters.get('everything',0)>0 and omo_everything_active(owner))
                elves+=bool(elf)
        cols,amt={'G'},elves
    elif effective_name=='Birds of Paradise' and tap_ready: cols,amt=set('WUBRG'),1
    elif effective_name=='Delighted Halfling' and tap_ready:
        # Its colored mode is restricted to legendary spells.  Preserve the
        # deck-relevant commander colors while retaining unrestricted {C}.
        cols,amt=set(COLOR_ID[p.name])|{'C'},1
    elif effective_name in {'Elvish Mystic','Fyndhorn Elves','Llanowar Elves'} and tap_ready:
        cols,amt={'G'},1
    # Magus of the Candelabra has an untap ability, not a mana ability.
    elif effective_name=='Oasis Gardener' and tap_ready: cols,amt=set('WUBRG'),1
    else: return set(),0
    amt*=mana_reflection_multiplier(p)
    return cols,amt

def enters_tapped(name:str, p:PlayerState)->bool:
    if name in TAPPED_LANDS: return True
    if name in {'Charcoal Diamond','Marble Diamond'}: return True
    return False


def base_stats(name, d):
    if name=='Kalonian Hydra': return (0,0)
    if name in PT: return PT[name]
    if d and d.is_creature: return (max(1,d.mv-1),max(1,d.mv))
    return (0,0)


def catalog_starting_loyalty(name, *, face_name=None, x_value=None):
    """Resolve fixed or X starting loyalty from the canonical face metadata."""

    definition=CATALOG.get(name)
    if definition is None:return None
    face=definition.face(face_name) if face_name else definition.front
    return face.starting_loyalty(x_value=x_value)

class Game:
    def __init__(self, seed:int, game_no:int, outdir:Path, max_turns:int=16):
        self.seed=seed; self.game_no=game_no; self.rng=random.Random(seed); self.outdir=outdir; self.max_turns=max_turns
        self.players:Dict[str,PlayerState]={}
        self.turn_order=list(DECK_HEADINGS); self.rng.shuffle(self.turn_order)
        self.active_idx=0; self.turn_number=0; self.round=0; self.phase='setup'; self.seq=0; self.stack=[]; self.events=[]
        self.pending_arcane_denials=[]
        self.winner=None; self.win_turn=None; self.win_reason=''; self.material_unsupported=[]; self.stat_fallback=set(); self.validation=[]
        # CardObj deliberately stays small and does not carry ownership.  Keep
        # the original deck identity by UID so effects that put another
        # player's card onto a battlefield can change its controller without
        # silently changing its owner.
        self.card_owners:Dict[str,str]={}
        self.ream_metrics={k:defaultdict(int) for k in ['appear','drawn','cast','realized']}
        self.ream_game_flags={k:defaultdict(bool) for k in ['appear','drawn','cast','realized']}
        self.setup()

    def setup(self):
        for deck in self.turn_order:
            cards=[]; idx=0; commander=None
            for d in DECKDEFS[deck]:
                for k in range(d.quantity):
                    idx+=1; c=CardObj(f'{deck[:2]}-{self.game_no:02d}-{idx:03d}',d)
                    self.card_owners[c.uid]=deck
                    if d.name==COMMANDERS[deck] and commander is None: commander=c
                    else: cards.append(c)
            self.rng.shuffle(cards)
            p=PlayerState(deck,library=cards,commander=commander)
            # Runtime-only table reference for continuous effects; never serialized.
            p._table_players=self.players
            p.dungeon['commander_uid']=commander.uid
            self.players[deck]=p
        self.log('game_start',None,None,f'Seating: {" → ".join(self.turn_order)}')
        for deck in self.turn_order:
            self.mulligan(self.players[deck])
        # Leyline of Hope may begin on the battlefield from the opening hand.
        ep=self.players.get('Elenda')
        if ep:
            ly=next((c for c in ep.hand if c.d.name=='Leyline of Hope'),None)
            if ly:
                ep.hand.remove(ly); bp,bt=base_stats(ly.d.name,ly.d)
                ep.battlefield.append(Perm(ly.uid,ly.d.name,ep.name,ep.name,False,False,{},None,None,False,bp,bt,set(),0))
                self.log('pregame_leyline',ep.name,ly.d.name,'Leyline of Hope begins the game on the battlefield')
        self.assert_invariants('post_setup')

    def snapshot(self):
        # A snapshot asks for the same permanent's effective characteristics
        # several times (view, power, toughness, targeting metadata).  Manual
        # referee subclasses may cache those pure reads for this one snapshot;
        # the cache is discarded before gameplay can mutate again.
        cache_owner=not hasattr(self,'_continuous_view_cache')
        if cache_owner:self._continuous_view_cache={}
        try:
            ps={}
            for n,p in self.players.items():
                def permanent_view(q):
                    # Snapshot both printed/runtime fields and the effective view when
                    # the manual referee's continuous-effect pipeline is available.
                    # Inspection consumes this read-only projection; it must never
                    # need to reach into hidden engine objects or recompute rules.
                    effective_keywords=set(q.keywords);effective_types=[];effective_subtypes=[];effective_colors=[]
                    if hasattr(self,'continuous_view'):
                        try:
                            view=self.continuous_view(q)
                            effective_keywords=set(view.abilities);effective_types=sorted(view.types)
                            effective_subtypes=sorted(view.subtypes);effective_colors=sorted(view.colors)
                        except (AttributeError,KeyError,TypeError,ValueError):
                            # Base-engine snapshots and partially constructed setup
                            # positions still need to be serializable.
                            pass
                    return {
                        'uid':q.uid,'name':q.name,'owner':q.owner,'controller':q.controller,
                        'tapped':q.tapped,'sick':q.summoning_sick,'counters':dict(q.counters),
                        'attached_to':q.attached_to,'copy_of':q.copy_of,'token':q.token,
                        'base_power':q.base_power,'base_toughness':q.base_toughness,
                        'power':self.power(q),'toughness':self.toughness(q),
                        'printed_keywords':sorted(q.keywords),'effective_keywords':sorted(effective_keywords),
                        'effective_types':effective_types,'effective_subtypes':effective_subtypes,
                        'effective_colors':effective_colors,'metadata':dict(q.metadata),
                    }
                ps[n]={
                    'life':p.life,'eliminated':p.eliminated,'library':[c.uid+':'+c.d.name for c in p.library],
                    'hand':[c.uid+':'+c.d.name for c in p.hand],'graveyard':[c.uid+':'+c.d.name for c in p.graveyard],
                    'exile':[c.uid+':'+c.d.name for c in p.exile],
                    'battlefield':[permanent_view(q) for q in p.battlefield],
                    'commander':p.commander.uid+':'+p.commander.d.name if p.commander else None,'command_tax':p.command_tax,'energy':p.energy,'treasures':p.treasures,
                    'land_plays_used':p.land_plays_used,'land_play_limit':p.land_play_limit,'miracle_uid':p.miracle_card_uid,
                }
                if not p.eliminated and p.dungeon.get('ecd_tax_effects'):
                    ps[n]['resolved_noncreature_tax']={'amount':2*p.dungeon['ecd_tax_effects'],
                        'applies_to':'opponents','expires':'beginning of this controller\'s next turn'}
            return {'game':self.game_no,'seed':self.seed,'seq':self.seq,'round':self.round,'turn_number':self.turn_number,'active':self.turn_order[self.active_idx] if self.turn_order else None,'phase':self.phase,'stack':list(self.stack),'delayed_arcane_denials':list(self.pending_arcane_denials),'players':ps}
        finally:
            if cache_owner:del self._continuous_view_cache

    def log(self, etype, actor, card, detail, **extra):
        self.seq+=1
        visibility=event_visibility(etype,extra.pop('visibility',None))
        public_view=extra.pop('public_view',None)
        if visibility=='actor_public' and public_view is None:
            public_view=public_event_stub(etype,actor,extra)
        ev={'game':self.game_no,'seed':self.seed,'seq':self.seq,'round':self.round,'turn':self.turn_number,'phase':self.phase,'actor':actor,'type':etype,'card':card,'detail':detail,'visibility':visibility,**extra}
        if visibility in {'actor','actor_public'}:
            ev['visible_to']=[actor] if actor else []
        if public_view is not None:ev['public_view']=public_view
        if getattr(self,'capture_event_state',True):ev['state']=self.snapshot()
        self.events.append(ev)
        if actor=='Reaminatour' and card and card in CARDDEF:
            self.mark_appearance(card)

    def mark_appearance(self,name, drawn=False, cast=False, realized=False):
        if name not in CARDDEF or CARDDEF[name].deck!='Reaminatour': return
        self.ream_game_flags['appear'][name]=True
        if drawn:self.ream_game_flags['drawn'][name]=True
        if cast:self.ream_game_flags['cast'][name]=True
        if realized:self.ream_game_flags['realized'][name]=True

    def mulligan(self,p:PlayerState):
        original=list(p.library)
        kept=None; mull=0
        # Commander multiplayer: first mulligan free; subsequent London bottom one per paid mulligan.
        while mull<4:
            hand=[p.library.pop() for _ in range(7)]
            lands=sum(c.d.is_land for c in hand)
            cheap=sum((not c.d.is_land and c.d.mv<=2) for c in hand)
            acceptable=(2<=lands<=5) or (lands==1 and cheap>=2 and any(c.d.name in MANA_ROCKS for c in hand))
            if acceptable or mull==3:
                paid=max(0,mull-1)
                if paid:
                    # bottom worst nonland expensive first, else lands
                    hand.sort(key=lambda c:(c.d.is_land, -c.d.mv))
                    bottom=hand[:paid]; hand=hand[paid:]
                    p.library=[*bottom,*p.library]
                kept=hand; break
            p.library.extend(hand); self.rng.shuffle(p.library); mull+=1
        p.hand=kept
        for c in p.hand:
            if p.name=='Reaminatour': self.mark_appearance(c.d.name,drawn=True)
        self.log('mulligan_keep',p.name,None,f'Kept {len(p.hand)} after {mull} mulligan(s): '+', '.join(c.d.name for c in p.hand),mulligans=mull,hand_size=len(p.hand))

    def assert_invariants(self,where):
        # Audit physical ownership globally. A card controlled by another player on the
        # battlefield still belongs to its original 100-card deck.
        for n,p in self.players.items():
            ids=[]
            ids += [c.uid for c in p.library+p.hand+p.graveyard+p.exile]
            for ctrl in self.players.values():
                ids += [q.uid for q in ctrl.battlefield if (not q.token) and q.owner==n]
            if p.commander: ids.append(p.commander.uid)
            if p.eliminated:
                if ids:
                    raise AssertionError(f'{where} eliminated player {n} still owns {len(ids)} physical objects in the game')
                continue
            if len(ids)!=len(set(ids)):
                raise AssertionError(f'{where} duplicate physical card owned by {n}')
            if len(ids)!=100:
                raise AssertionError(f'{where} {n} owns {len(ids)} physical cards !=100')
            if p.life < -10000000: raise AssertionError('life underflow')
        self.validation.append((self.seq,where,'OK'))

    def card_in_hand(self,p,name):
        return next((c for c in p.hand if c.d.name==name),None)
    def perm(self,p,name):
        return next((q for q in p.battlefield if (q.copy_of or q.name)==name and not q.metadata.get('mutated')),None)
    def controls_commander(self,p):
        """Return whether *p* controls any object designated as a commander.

        Commander designation is independent of an object's rules text.  In
        particular, Darksteel Mutation removes abilities but does not stop the
        enchanted permanent from being a commander.
        """
        commander_uids={
            player.dungeon.get('commander_uid')
            for player in self.players.values()
            if player.dungeon.get('commander_uid')
        }
        return any(q.uid in commander_uids for q in p.battlefield)
    def has_no_maximum_hand_size(self,p):
        return bool(p.dungeon.get('no_max_hand') or self.perm(p,'Reliquary Tower') or self.perm(p,'Thought Vessel'))
    def cards_in_zone(self,p,zone,name=None):
        arr=getattr(p,zone)
        return [c for c in arr if name is None or c.d.name==name]

    def move_card(self,p:PlayerState,c:CardObj,src:str,dst:str,reason=''):
        arr=getattr(p,src); arr.remove(c); getattr(p,dst).append(c)
        self.log('zone_move',p.name,c.d.name,f'{src} → {dst}: {reason}',uid=c.uid,src=src,dst=dst)

    def make_perm(self,p,c:CardObj,from_zone='hand',copy_of=None, tapped=False):
        if from_zone=='commander':
            assert p.commander and p.commander.uid==c.uid; p.commander=None
        else:
            getattr(p,from_zone).remove(c)
        bp,bt=base_stats(c.d.name,c.d)
        if c.d.is_creature and c.d.name not in PT: self.stat_fallback.add(c.d.name)
        q=Perm(c.uid,c.d.name,p.name,p.name,tapped=(tapped or c.d.name in {'Charcoal Diamond','Marble Diamond'}),summoning_sick=c.d.is_creature,counters={},copy_of=copy_of,token=False,base_power=bp,base_toughness=bt,keywords=set(KEYWORDS.get(c.d.name,set())),entered_turn=self.turn_number)
        p.battlefield.append(q)
        self.mark_appearance(c.d.name,realized=True)
        self.log('etb',p.name,c.d.name,f'{c.d.name} entered battlefield'+(f' copying {copy_of}' if copy_of else ''),uid=c.uid,copy_of=copy_of)
        self.on_etb(p,q)
        return q

    def token(self,p,name,power,toughness,keywords=None,counters=None):
        uid=f'TOK-{self.game_no}-{self.seq+1}-{name}'
        # Tokens are subject to summoning sickness exactly like nontoken creatures;
        # can_attack/source_colors separately honor haste when appropriate.
        q=Perm(uid,name,p.name,p.name,False,True,dict(counters or {}),None,None,True,power,toughness,set(keywords or []),self.turn_number)
        if name=='Forest Dryad':
            q.metadata['is_land']=True;q.metadata['land_types']=['Forest']
        p.battlefield.append(q)
        self.log('token_etb',p.name,name,f'Created {power}/{toughness} {name} token',uid=uid)
        # Entry replacement/static adjustments apply to tokens too.  This must
        # precede ETB-trigger evaluation so power-sensitive listeners observe
        # the object with its required entry counters already present.
        self.after_permanent_entry_adjustments(p,q)
        self.trigger_creature_etb(p,q)
        if q.metadata.get('is_land'):self.on_landfall(p,q)
        return q

    def find_card_obj_on_bf(self,p,uid):
        return next((q for q in p.battlefield if q.uid==uid),None)

    def is_creature_perm(self,q):
        d=CARDDEF.get(q.name)
        if q.metadata.get('noncreature_token'): return False
        owner=self.players[q.controller]
        if q.name!='Starfield of Nyx' and d and d.is_enchantment and 'Aura' not in d.type_line and self.perm(owner,'Starfield of Nyx'):
            ens=sum(1 for z in owner.battlefield if CARDDEF.get(z.name) and CARDDEF[z.name].is_enchantment)
            if ens>=5:return True
        # Xenagos is a creature only while red+green devotion is seven or greater.
        if q.name=='Xenagos, God of Revels':
            owner=self.players[q.controller]
            devotion=0
            for z in owner.battlefield:
                dd=CARDDEF.get(z.name)
                if not dd: continue
                front=dd.mana_cost.split(' // ')[0]
                devotion += len(re.findall(r'\{[RG]\}',front))
            q.metadata['devotion_on']=devotion>=7
            if devotion<7:return False
        return bool(q.token or (d and d.is_creature) or q.metadata.get('march_animated') or q.metadata.get('sage_animated'))

    def has_creature_type(self,q,creature_type):
        definition=CARDDEF.get(q.copy_of or q.name)
        if definition and creature_type in definition.type_line:return True
        owner=self.players[q.controller]
        return bool(self.is_creature_perm(q) and not is_land_permanent(q) and
                    q.counters.get('everything',0)>0 and omo_everything_active(owner))

    def has_hexproof(self,q):
        owner=self.players[q.controller]
        return bool('hexproof' in q.keywords or q.metadata.get('celestial_hexproof_turn')==self.turn_number or
                    q.metadata.get('liliana_hexproof_turn')==self.turn_number or
                    (self.has_creature_type(q,'Illusion') and self.perm(owner,'Lord of the Unreal') and q.name!='Lord of the Unreal'))

    def commander_grave_exile_choice(self,owner,q,dst,reason):
        """Automated-game policy; ManualGame overrides this material choice."""
        return True

    def leave_battlefield(self,p:PlayerState,q:Perm,dst='graveyard',reason=''):
        if q not in p.battlefield: return
        # "Dies" means "is put into a graveyard from the battlefield *as a
        # creature*."  Preserve that last-known fact before removing the
        # permanent: a land sacrificed to a fetch ability is not a death, while
        # an animated land still is.
        was_creature=self.is_creature_perm(q)
        p.battlefield.remove(q)
        p.land_play_limit=self.max_land_plays(p)
        self.log('ltb',p.name,q.name,f'{q.name} left battlefield → {dst}: {reason}',uid=q.uid)
        if q.token:
            # token ceases to exist after leaving
            self.on_ltb(p,q,died=(dst=='graveyard' and was_creature))
            return
        # A commander reaches graveyard/exile before its owner may move it to the
        # command zone as a state-based action (CR 704.6d / 903.9a).
        # Preserve original deck identity for shared card names (e.g. Sol Ring, Solemn).
        d=next((d for d in DECKDEFS.get(q.owner,[]) if d.name==q.name), CARDDEF.get(q.name))
        c=CardObj(q.uid,d) if d else None
        owner=self.players[q.owner]
        if c and q.uid==owner.dungeon.get('commander_uid') and dst in {'graveyard','exile'}:
            zone=getattr(owner,dst);zone.append(c)
            if self.commander_grave_exile_choice(owner,q,dst,reason):
                zone.remove(c);owner.commander=c
                self.log('commander_zone',owner.name,q.name,f'{q.name} moved from {dst} to command zone')
        elif c:
            getattr(owner,dst).append(c)
        self.on_ltb(p,q,died=(dst=='graveyard' and was_creature))

    def destroy(self,p:PlayerState,q:Perm,reason='destroy'):
        if 'indestructible' in q.keywords or q.metadata.get('heroic_protected_turn')==self.turn_number or q.metadata.get('celestial_indestructible_turn')==self.turn_number:
            self.log('destroy_prevented',p.name,q.name,f'{reason}: indestructible prevents destruction',uid=q.uid)
            return False
        self.leave_battlefield(p,q,'graveyard',reason)
        return True
    def exile_perm(self,p,q,reason='exile'):
        self.leave_battlefield(p,q,'exile',reason)

    def draw(self,p:PlayerState,n=1,reason='draw'):
        for _ in range(n):
            if not p.library:
                p.eliminated=True; self.log('deck_loss',p.name,None,'Tried to draw from empty library'); return
            c=p.library.pop();p.hand.append(c);p.cards_drawn_this_turn+=1
            if p.name=='Reaminatour':self.mark_appearance(c.d.name,drawn=True)
            self.log('draw',p.name,c.d.name,f'Drew {c.d.name}: {reason}',uid=c.uid,draw_number=p.cards_drawn_this_turn)
            if p.name=='Reaminatour' and self.perm(p,'Aminatou, Veil Piercer') and p.cards_drawn_this_turn==1 and c.d.is_enchantment:
                p.miracle_card_uid=c.uid;self.log('miracle_available',p.name,c.d.name,f'{c.d.name} is first card drawn; Aminatou grants miracle',uid=c.uid)
            # Smothering Tithe: opponent may pay {2}; deterministic policy pays only with ample untapped mana.
            for owner in self.players.values():
                if owner.name==p.name or owner.eliminated or not self.perm(owner,'Smothering Tithe'):continue
                tax=CardDef('Smothering Tithe tax','{2}','Ability','',1,p.name,2)
                units=sum(amt for _,_,amt in self.available_sources(p))
                if units>=6 and self.can_pay(p,tax):self.pay(p,tax)
                else:
                    owner.treasures+=1;self.log('treasure',owner.name,'Smothering Tithe',f'{p.name} declines/pay-unavailable for Tithe; create Treasure',treasures=owner.treasures)
            if p.cards_drawn_this_turn==2:
                for owner in self.players.values():
                    if owner.name!=p.name and not owner.eliminated and self.perm(owner,'Gleaming Splendor'):
                        owner.treasures+=1;self.log('treasure',owner.name,'Gleaming Splendor',f'{p.name} drew second card this turn; create Treasure',treasures=owner.treasures)

    def mill(self,p,n,reason='mill'):
        for _ in range(min(n,len(p.library))):
            c=p.library.pop(); p.graveyard.append(c); self.log('mill',p.name,c.d.name,f'{c.d.name} → graveyard: {reason}',uid=c.uid)

    def gain_life(self,p,n,reason=''):
        if n<=0:return
        # Independent replacement effects each add one.
        if self.perm(p,'Angel of Vitality'): n+=1
        if self.perm(p,'Leyline of Hope'): n+=1
        p.life+=n; p.life_gained_this_turn+=n
        self.log('life_gain',p.name,None,f'{p.name} gains {n} life ({reason})',amount=n)
        if p.name=='Elenda':
            pr=self.perm(p,"Ajani's Pridemate")
            if pr:self.add_counters(p,pr,'+1/+1',1,"Ajani's Pridemate")
            channeler=self.perm(p,'Essence Channeler')
            if channeler:self.add_counters(p,channeler,'+1/+1',1,'Essence Channeler lifegain trigger')
            # Marauding drains every opponent by 1 for each gain event.
            if self.perm(p,'Marauding Blight-Priest'):
                for opp in self.opponents(p): self.lose_life(opp,1,'Marauding Blight-Priest')
            # Defiant Bloodlord targets one opponent for the amount gained.
            if self.perm(p,'Defiant Bloodlord'):
                opp=min(self.opponents(p),key=lambda x:x.life,default=None)
                if opp:self.lose_life(opp,n,'Defiant Bloodlord')
            # Dawn of Hope: deterministic policy pays when a card is worth more than holding two mana.
            if self.perm(p,'Dawn of Hope') and len(p.hand)<7:
                fake=CardDef('Dawn of Hope trigger','{2}','Ability','',1,p.name,2)
                if self.can_pay(p,fake):
                    self.pay(p,fake);self.draw(p,1,'Dawn of Hope lifegain trigger')
            for nm in ["Elenda's Hierophant",'Exemplar of Light','Fiendish Panda','Twinblade Paladin']:
                cr=self.perm(p,nm)
                if cr:
                    self.add_counters(p,cr,'+1/+1',1,f'{nm} lifegain trigger')
                    if nm=='Exemplar of Light' and cr.metadata.get('exemplar_draw_turn')!=self.turn_number:
                        cr.metadata['exemplar_draw_turn']=self.turn_number;self.draw(p,1,'Exemplar of Light counter trigger')

    def lose_life(self,p,n,reason=''):
        if n<=0:return
        p.life-=n; self.log('life_loss',p.name,None,f'{p.name} loses {n} life ({reason}); life={p.life}',amount=n)
        if p.life<=0: self.eliminate(p,reason or 'life total')

    def eliminate(self,p,reason):
        if p.eliminated:return
        p.eliminated=True; self.log('eliminated',p.name,None,f'{p.name} eliminated: {reason}')
        # Multiplayer player-leaves-game cleanup. Owned objects leave the game;
        # attached Auras must stop applying before their owner's zones disappear.
        for controller in self.players.values():
            for permanent in list(controller.battlefield):
                if permanent.owner!=p.name:continue
                # Removing one owned object can synchronously remove another
                # (for example Dance of the Dead leaving sacrifices its linked
                # creature).  The outer snapshot may therefore contain an
                # object that has already left; process every object at most once.
                if permanent not in controller.battlefield:continue
                controller.battlefield.remove(permanent)
                self.log('leaves_game',p.name,permanent.name,f'{permanent.name} leaves the game with {p.name}',uid=permanent.uid)
                self.on_ltb(controller,permanent,died=False)
        p.library.clear();p.hand.clear();p.graveyard.clear();p.exile.clear();p.commander=None
        alive=[x for x in self.players.values() if not x.eliminated]
        if len(alive)==1:
            self.winner=alive[0].name; self.win_turn=self.turn_number; self.win_reason=reason; self.log('winner',self.winner,None,f'{self.winner} wins; last player standing')

    def opponents(self,p): return [q for q in self.players.values() if q.name!=p.name and not q.eliminated]

    def add_counters(self,p,q,kind,n,reason=''):
        if n<=0:return
        original=n
        if p.name=='Minsc & Boo':
            if kind=='+1/+1':
                if self.perm(p,'Hardened Scales') and self.is_creature_perm(q):n+=1
                if self.perm(p,'Ozolith, the Shattered Spire'):n+=1
                if self.perm(p,'Kami of Whispered Hopes'):n+=1
                if self.perm(p,'The Earth Crystal'):n*=2
                if self.perm(p,'Branching Evolution'):n*=2
            if self.perm(p,'Vorinclex, Monstrous Raider'):n*=2
            it=self.perm(p,"Innkeeper's Talent")
            if it and it.metadata.get('level',1)>=3:n*=2
        q.counters[kind]=q.counters.get(kind,0)+n;p.counters_placed_this_turn+=n
        self.log('counters',p.name,q.name,f'Put {n} {kind} counter(s) on {q.name} (base request {original}; {reason})',amount=n,requested=original)
        if p.name=='Minsc & Boo' and self.perm(p,'All Will Be One'):
            opp=min(self.opponents(p),key=lambda x:x.life,default=None)
            if opp:self.lose_life(opp,n,'All Will Be One')
        if p.name=='Minsc & Boo' and kind=='+1/+1' and self.perm(p,'Terrasymbiosis') and p.dungeon.get('terrasymbiosis_turn')!=self.turn_number:
            p.dungeon['terrasymbiosis_turn']=self.turn_number;self.draw(p,min(n,30),'Terrasymbiosis counter trigger')

    def power(self,q:Perm):
        if q.metadata.get('march_animated'):p=q.metadata.get('march_power',0)
        else:p=q.base_power+q.counters.get('+1/+1',0)-q.counters.get('-1/-1',0)-q.metadata.get('eot_pt_penalty',0)
        if q.name=='Rampant Frogantua':p+=10*sum(1 for x in self.players.values() if x.eliminated)
        if q.name=='Kalonian Hydra': p=q.counters.get('+1/+1',0)
        if q.name=='Hydroid Krasis': p=q.counters.get('+1/+1',0)
        d=CARDDEF.get(q.name);owner_sf=self.players[q.controller]
        if q.name!='Starfield of Nyx' and d and d.is_enchantment and 'Aura' not in d.type_line and self.perm(owner_sf,'Starfield of Nyx') and sum(1 for z in owner_sf.battlefield if CARDDEF.get(z.name) and CARDDEF[z.name].is_enchantment)>=5:
            p=d.mv+q.counters.get('+1/+1',0)-q.counters.get('-1/-1',0)-q.metadata.get('eot_pt_penalty',0)
        if q.name=='Ulvenwald Hydra': p=max(p, sum(1 for x in self.players[q.controller].battlefield if is_land_permanent(x)))
        owner=self.players[q.controller]
        if q.name=='Elenda, Saint of Dusk':
            if owner.life>40:p+=1
            if owner.life>=50:p+=5
        if q.name=='Angel of Vitality' and owner.life>=25:p+=2
        if self.perm(owner,'Leyline of Hope') and owner.life>=47 and CARDDEF.get(q.name) and CARDDEF[q.name].is_creature:p+=2
        if self.perm(owner,'Arvad the Cursed') and q.name!='Arvad the Cursed' and CARDDEF.get(q.name) and 'Legendary' in CARDDEF[q.name].type_line:p+=2
        if self.perm(owner,'Lord of the Unreal') and q.name!='Lord of the Unreal' and self.has_creature_type(q,'Illusion'):p+=1
        if q.name=='Xenagos, God of Revels' and not self.is_creature_perm(q): p=0
        linked=next((a for a in owner.battlefield if a.uid==q.metadata.get('reanimated_by')),None)
        if linked:
            if linked.name=='Animate Dead':p-=1
            elif linked.name=='Dance of the Dead':p+=1
        return max(0,p)

    def toughness(self,q:Perm):
        if q.metadata.get('march_animated'):t=q.metadata.get('march_toughness',0)
        else:t=q.base_toughness+q.counters.get('+1/+1',0)-q.counters.get('-1/-1',0)-q.metadata.get('eot_pt_penalty',0)
        if q.name=='Rampant Frogantua':t+=10*sum(1 for x in self.players.values() if x.eliminated)
        if q.name=='Kalonian Hydra': t=q.counters.get('+1/+1',0)
        if q.name=='Hydroid Krasis': t=q.counters.get('+1/+1',0)
        d=CARDDEF.get(q.name);owner_sf=self.players[q.controller]
        if q.name!='Starfield of Nyx' and d and d.is_enchantment and 'Aura' not in d.type_line and self.perm(owner_sf,'Starfield of Nyx') and sum(1 for z in owner_sf.battlefield if CARDDEF.get(z.name) and CARDDEF[z.name].is_enchantment)>=5:
            t=d.mv+q.counters.get('+1/+1',0)-q.counters.get('-1/-1',0)-q.metadata.get('eot_pt_penalty',0)
        if q.name=='Ulvenwald Hydra': t=max(t, sum(1 for x in self.players[q.controller].battlefield if is_land_permanent(x)))
        owner=self.players[q.controller]
        if q.name=='Elenda, Saint of Dusk':
            if owner.life>40:t+=1
            if owner.life>=50:t+=5
        if q.name=='Angel of Vitality' and owner.life>=25:t+=2
        if self.perm(owner,'Leyline of Hope') and owner.life>=47 and CARDDEF.get(q.name) and CARDDEF[q.name].is_creature:t+=2
        if self.perm(owner,'Arvad the Cursed') and q.name!='Arvad the Cursed' and CARDDEF.get(q.name) and 'Legendary' in CARDDEF[q.name].type_line:t+=2
        if self.perm(owner,'Lord of the Unreal') and q.name!='Lord of the Unreal' and self.has_creature_type(q,'Illusion'):t+=1
        linked=next((a for a in owner.battlefield if a.uid==q.metadata.get('reanimated_by')),None)
        if linked and linked.name=='Dance of the Dead':t+=1
        return max(0,t)

    def available_sources(self,p):
        # Menu enumeration is read-only: mana sources do not change between
        # affordability checks for different cards or X values. Copy containers
        # on return so a payment solver cannot mutate the cached source options.
        cache=getattr(self,'_query_source_cache',None)
        # Convoke previews temporarily tap creatures even inside a read-only
        # menu query. Distinguish those previews and restored source availability.
        key=('available_sources',id(p),tuple((id(q),q.tapped,q.summoning_sick) for q in p.battlefield),
             p.treasures,tuple(p.dungeon.get('domri_floating',())),tuple(p.dungeon.get('floating_mana',())))
        if cache is not None and key in cache:
            return [(source,set(colors),amount) for source,colors,amount in cache[key]]
        src=[]
        yavimaya_active=any(
            z.name=='Yavimaya, Cradle of Growth' and not permanent_mana_inactive(z)
            for owner in self.players.values() for z in owner.battlefield
        )
        for q in p.battlefield:
            cols,amt=source_colors(p,q,getattr(self,'continuous_view',None))
            d=CARDDEF.get(q.name)
            if yavimaya_active and is_land_permanent(q) and not q.tapped:
                # Yavimaya makes every land a Forest in addition to its other types,
                # including itself, so even lands with no printed mana ability gain {T}: {G}.
                cols=set(cols)|{'G'};amt=max(1,amt)
            if amt: src.append((q,cols,amt))
        # treasure virtual sources individual
        for i in range(p.treasures): src.append((None,set('WUBRG'),1))
        for color in p.dungeon.get('domri_floating',[]):src.append(('DOMRI',set(color),1))
        for token in p.dungeon.get('floating_mana',[]):
            color=token.split('-')[-1]
            src.append((f'FLOAT:{token}',set(color),1))
        if cache is not None:
            cache[key]=tuple((source,frozenset(colors),amount) for source,colors,amount in src)
        return src

    def mana_filters(self,p):
        multiplier=mana_reflection_multiplier(p)
        result=[]
        for q in p.battlefield:
            name=q.copy_of or q.name
            if name not in mana_filters.SIGNET_OUTPUTS and name!='Talon Gates of Madara':continue
            if q.tapped or permanent_mana_inactive(q):continue
            definition=CARDDEF.get(name)
            if q.summoning_sick and (q.metadata.get('is_creature') or (definition and definition.is_creature)):continue
            outputs=(tuple(color*multiplier for color in 'WUBRG') if name=='Talon Gates of Madara'
                     else mana_filters.SIGNET_OUTPUTS[name]*multiplier)
            result.append((q,outputs))
        return result

    def mana_availability(self,p):
        """Return the public mana capacity represented by the payment engine.

        ``total`` counts each currently usable mana unit once.  ``by_color``
        reports the independent maximum that could be spent as each mana type;
        flexible sources therefore contribute to more than one color ceiling,
        and those ceilings must not be added together.
        """
        color_order='WUBRGC'
        by_color={color:0 for color in color_order}
        if p.eliminated:return {
            'total':0,'by_color':by_color,'by_color_semantics':'independent_maxima',
        }
        total=0
        sources=self.payment_sources(p)
        for _,colors,amount in sources:
            amount=max(0,int(amount))
            total+=amount
            for color in colors:
                if color in by_color:by_color[color]+=amount
        fixed_sources=self.fixed_mana_sources(p)
        filters=self.mana_filters(p)
        def capacity(index,subtotal,ceilings):
            if index<len(fixed_sources):
                candidates=[capacity(index+1,subtotal+len(output),
                    {color:ceilings[color]+output.count(color) for color in color_order})
                    for output in fixed_sources[index][1]]
                return max(value[0] for value in candidates),{
                    color:max(value[1][color] for value in candidates) for color in color_order}
            if not subtotal or not filters:return subtotal,ceilings
            result=dict(ceilings)
            for color in color_order:
                generated=sum(max(value.count(color) for value in ((output,) if isinstance(output,str) else output))
                              for _,output in filters)
                initial_loss=int(ceilings[color]==subtotal)
                result[color]+=max(0,generated-initial_loss)
            return subtotal+sum(max(len(value) for value in ((output,) if isinstance(output,str) else output))-1
                                for _,output in filters),result
        total,by_color=capacity(0,total,by_color)
        return {
            'total':total,'by_color':by_color,'by_color_semantics':'independent_maxima',
        }

    def payment_sources(self,p):
        """Represent multi-mana Tron and granted one-mana abilities separately."""
        result=[];multiplier=mana_reflection_multiplier(p)
        for source,colors,amount in self.available_sources(p):
            name=(source.copy_of or source.name) if isinstance(source,Perm) else None
            if name in mana_filters.PAIRED_LANDS:continue
            if (name in {"Urza's Mine","Urza's Power Plant","Urza's Tower"}
                    and amount>multiplier and set(colors)-{'C'}):
                result.append((source,set(colors),multiplier))
                result.append((source,{'C'},amount-multiplier))
            else:result.append((source,colors,amount))
        return result

    def fixed_mana_sources(self,p):
        """A printed paired output and granted single-color abilities are alternatives."""
        result=[];multiplier=mana_reflection_multiplier(p)
        for source,colors,_ in self.available_sources(p):
            name=(source.copy_of or source.name) if isinstance(source,Perm) else None
            if name not in mana_filters.PAIRED_LANDS:continue
            # A paired activation already covers any single mana of its printed
            # colors. Only independently granted extra colors add useful options.
            printed=mana_filters.PAIRED_LANDS[name]
            outputs=[printed*multiplier]+[color*multiplier for color in 'WUBRGC'
                                         if color in colors and color not in printed]
            result.append((source,tuple(outputs)))
        return result

    def establish_ecd_tax(self,p):
        # A resolved chapter creates an effect independent of its source.
        p.dungeon['ecd_tax_effects']=p.dungeon.get('ecd_tax_effects',0)+1

    def expire_turn_start_effects(self,p):
        # Use the controller's actual next turn, including extra turns and
        # eliminated seats, rather than assuming a four-seat rotation.
        p.dungeon.pop('ecd_tax_effects',None)

    def noncreature_spell_tax(self,p):
        return 2*sum(op.dungeon.get('ecd_tax_effects',0) for op in self.opponents(p))

    @read_only_views
    def _payment_plan(self,p,card:CardDef,commander=False,miracle=False,x_value=0,avoid_source=None):
        from . import mana_safety
        def solve(sources=None):
            return self._raw_payment_plan(p,card,commander,miracle,x_value,avoid_source,source_override=sources)
        initial=solve()
        fixed_life=(2 if self.perm(p,'Defiler of Vigor') and card.is_permanent
                    and '{G}' in card.mana_cost.split(' // ')[0] and p.life>4 else 0)
        return mana_safety.select(p,initial,lambda:self.payment_sources(p),solve,fixed_life)

    def _raw_payment_plan(self,p,card:CardDef,commander=False,miracle=False,x_value=0,avoid_source=None,*,source_override=None):
        generic,need=cost_symbols(card,p.command_tax if commander else 0,miracle,x_value)
        need=Counter(need)
        if not card.is_creature:generic+=self.noncreature_spell_tax(p)
        mana_syms=set(re.findall(r'\{([WUBRG])\}',card.mana_cost.split(' // ')[0]))
        # Printed cost reducers in the frozen lists.
        if self.perm(p,'The Earth Crystal') and 'G' in mana_syms: generic=max(0,generic-1)
        if self.perm(p,'Goblin Anarchomancer') and (mana_syms & {'R','G'}): generic=max(0,generic-1)
        if card.name=='Ghalta, Primal Hunger':
            generic=max(0,generic-sum(self.power(q) for q in p.battlefield if CARDDEF.get(q.name) and CARDDEF[q.name].is_creature))
        if card.name=='Blasphemous Act':
            generic=max(0,generic-sum(
                1 for owner in self.players.values() for q in owner.battlefield
                if self.is_creature_perm(q)
            ))
        if self.perm(p,'Defiler of Vigor') and card.is_permanent and 'G' in mana_syms and need.get('G',0)>0 and p.life>4:
            need['G']-=1
        src=self.payment_sources(p) if source_override is None else source_override
        filters=self.mana_filters(p)
        fixed_sources=self.fixed_mana_sources(p)
        if filters or fixed_sources:
            protected={id(q) for q in p.battlefield if q.name=="Hall of Heliod's Generosity"
                       and any(card.d.is_enchantment for card in p.graveyard)}
            return mana_filters.payment(src,filters,generic,need,avoid_source,protected,fixed_sources)
        # flatten Sol Ring into two units sharing source id; payment later taps once
        units=[]
        for q,cols,amt in src:
            for _ in range(amt): units.append((q,cols))
        used=set(); chosen=[];activation_colors={}
        def source_key(index):
            q=units[index][0]
            # Each Treasure is an independent source.  Multiple units from a
            # permanent (for example Sol Ring) share one activation color.
            return ('TREASURE',index) if q is None else (
                id(q) if not isinstance(q,str) else q)
        # Colored and hybrid symbols require a matching problem rather than a
        # greedy walk: spending a flexible land on W can otherwise strand a U
        # symbol even though another W source was available.  Trying candidates
        # in the old order preserves the established payment choice whenever
        # that choice can still complete the cost.
        colored_symbols=[sym for sym,count in need.items() for _ in range(count)]
        def assign_colored(position):
            if position>=len(colored_symbols):return True
            sym=colored_symbols[position]
            required=set(sym.split('/')) if '/' in sym else {sym}
            opts=[]
            for i,(q,cols) in enumerate(units):
                if i in used:continue
                legal_colors=cols & required
                fixed=activation_colors.get(source_key(i))
                if legal_colors and (fixed is None or fixed in legal_colors):
                    opts.append(i)
            opts.sort(key=lambda index:(units[index][0] is avoid_source,index))
            for i in opts:
                q,cols=units[i];key=source_key(i)
                previous=activation_colors.get(key)
                legal_colors=cols & required
                if previous is None:
                    activation_colors[key]=next(
                        color for color in 'WUBRGC' if color in legal_colors)
                used.add(i);chosen.append(q)
                if assign_colored(position+1):return True
                chosen.pop();used.remove(i)
                if previous is None:activation_colors.pop(key,None)
                else:activation_colors[key]=previous
            return False
        if not assign_colored(0):return None
        remain=generic
        # If Hall currently has a legal recursion target, do not consume it for
        # generic mana while an interchangeable source is available.  This is
        # intentionally conditional: changing ordinary source order makes old
        # manual decision tapes diverge even when no activated line exists.
        def generic_payment_priority(index):
            q,cols=units[index]
            live_hall=(
                q is not None and not isinstance(q,str) and
                q.name=="Hall of Heliod's Generosity" and
                any(card.d.is_enchantment for card in p.graveyard)
            )
            # Spend colorless-only mana on generic costs before colored or
            # flexible sources.  Otherwise a late-played Sol Ring can remain
            # untapped while every land is consumed, silently defeating an
            # explicit plan to hold up colored interaction.
            colorless_only=cols=={'C'}
            return (1 if q is avoid_source else 0,1 if live_hall else 0,
                    0 if colorless_only else 1,index)
        for i in sorted(range(len(units)),key=generic_payment_priority):
            q,cols=units[i]
            if i in used:continue
            if remain<=0:break
            key=source_key(i)
            if key not in activation_colors:
                activation_colors[key]=next(
                    color for color in 'CWUBRG' if color in cols)
            used.add(i);chosen.append(q);remain-=1
        if remain>0:return None
        return chosen,activation_colors

    def can_pay(self,p,card:CardDef,commander=False,miracle=False,x_value=0,avoid_source=None):
        plan=self._payment_plan(p,card,commander,miracle,x_value,avoid_source=avoid_source)
        return None if plan is None else plan[0]

    def pay(self,p,card,commander=False,miracle=False,x_value=0,avoid_source=None):
        plan=self._payment_plan(p,card,commander,miracle,x_value,avoid_source=avoid_source)
        if plan is None:return False
        chosen,activation_colors=plan[:2]
        filter_residual=plan[2] if len(plan)>2 else {}
        mana_syms=set(re.findall(r'\{([WUBRG])\}',card.mana_cost.split(' // ')[0]))
        if self.perm(p,'Defiler of Vigor') and card.is_permanent and 'G' in mana_syms and p.life>4:
            self.lose_life(p,2,'Defiler of Vigor alternate cost')
        # unique permanents tap once; treasure Nones consume count
        treas=sum(1 for q in chosen if q is None)
        if treas:p.treasures-=treas
        domri=sum(1 for q in chosen if q=='DOMRI')
        if domri:
            del p.dungeon['domri_floating'][:domri]
        floating=[q for q in chosen if isinstance(q,str) and q.startswith('FLOAT:')]
        for source in floating:
            token=source.split(':',1)[1]
            p.dungeon.get('floating_mana',[]).remove(token)
        for q in {id(x):x for x in chosen if x is not None and x!='DOMRI' and not (isinstance(x,str) and x.startswith('FLOAT:'))}.values():
            if id(q) in filter_residual:
                q.tapped=True
                p.dungeon.setdefault('floating_mana',[]).extend(filter_residual[id(q)])
                continue
            _,amount=source_colors(p,q,getattr(self,'continuous_view',None))
            spent=sum(1 for source in chosen if source is q)
            q.tapped=True
            if amount>spent:
                color=activation_colors[id(q)]
                p.dungeon.setdefault('floating_mana',[]).extend([color]*(amount-spent))
            effective_name=q.copy_of or q.name
            color=activation_colors[id(q)]
            if effective_name=='Mana Confluence' and color not in confluence_free_colors(p,q):
                self.lose_life(p,1,'Mana Confluence activation cost')
            if effective_name in TALISMAN_COLORS and color!='C':
                self.lose_life(p,1,effective_name+' mana damage')
                self.log('damage',p.name,effective_name,'Mana ability deals 1 damage to its controller',amount=1)
            if q.name=='Pristine Talisman': self.gain_life(p,1,'Pristine Talisman mana')
        def source_name(q):return 'Treasure' if q is None else ('Domri' if q=='DOMRI' else (q.split(':',1)[1] if isinstance(q,str) and q.startswith('FLOAT:') else q.name))
        def source_uid(q):return 'Treasure' if q is None else ('Domri' if q=='DOMRI' else (q if isinstance(q,str) and q.startswith('FLOAT:') else q.uid))
        p.dungeon['last_payment_sources']=[source_uid(q) for q in chosen]
        self.log('mana_payment',p.name,card.name,f'Paid {card.mana_cost}'+(' with miracle -4 generic' if miracle else '')+f' using '+', '.join(source_name(q) for q in chosen),sources=[source_uid(q) for q in chosen],x=x_value)
        return True

    def play_land(self,p,c):
        if p.land_plays_used>=p.land_play_limit:return False
        if c not in p.hand or not c.d.is_land:return False
        copy_name=self.vesuva_copy_choice(p,c) if c.d.name=='Vesuva' else None
        p.hand.remove(c); bp,bt=(0,0)
        q=Perm(c.uid,c.d.name,p.name,p.name,tapped=(True if copy_name else self.land_enters_tapped(p,c)),summoning_sick=False,copy_of=copy_name,base_power=0,base_toughness=0,entered_turn=self.turn_number)
        if (copy_name or c.d.name)=='Dark Depths':q.counters['ice']=10
        if self.perm(p,'Spelunking'):q.tapped=False
        p.battlefield.append(q); p.land_plays_used+=1
        self.mark_appearance(c.d.name,cast=True,realized=True)
        copy_text=f' copying {copy_name}' if copy_name else ''
        self.log('land_play',p.name,c.d.name,f'Played land {c.d.name}{copy_text}'+(' tapped' if q.tapped else ''),uid=c.uid,copy_of=copy_name)
        self.on_landfall(p,q)
        if (copy_name or c.d.name) in {'Temple of Silence','Temple of Mystery'}:
            self.scry(p,1,copy_name or c.d.name)
        if (copy_name or c.d.name) in BOUNCE_LANDS:
            returned=self.bounce_land_return(p,q)
            if returned:self.bounce(p,returned,c.d.name+' ETB return-land trigger')
        return True

    def vesuva_copy_choice(self,p,c):
        lands=[q for owner in self.players.values() for q in owner.battlefield if is_land_permanent(q)]
        if not lands:return None
        target=max(lands,key=lambda q:source_colors(p,q)[1])
        return target.copy_of or target.name

    def reveal_land_choice(self,p,land,candidates):
        return candidates[0] if candidates else None

    def normal_shock_untapped_choice(self,p,c):return p.life>10

    def land_enters_tapped(self,p,c):
        name=c.d.name
        if name in SHOCK_LANDS:
            if self.normal_shock_untapped_choice(p,c):
                self.lose_life(p,2,name+' untapped replacement')
                return False
            return True
        if name in TAPPED_LANDS:return True
        lands=[q for q in p.battlefield if CARDDEF.get(q.name) and CARDDEF[q.name].is_land]
        if name in SLOW_LANDS:return len(lands)<2
        if name=='Lair of the Hydra':return len(lands)>=2
        if name=='Cinder Glade':
            basics=sum(1 for q in lands if CARDDEF[q.name].type_line.startswith('Basic Land'))
            return basics<2
        if name=='Baldur\'s Gate':
            gates=sum(1 for q in lands if 'Gate' in CARDDEF[q.name].type_line or q.counters.get('everything',0)>0)
            return gates<2
        reveal_types={
            'Game Trail':('Mountain','Forest'),'Shineshadow Snarl':('Plains','Swamp'),
            'Vineglimmer Snarl':('Island','Forest'),
        }
        if name in reveal_types:
            types=reveal_types[name]
            candidates=[card for card in p.hand if card.uid!=c.uid and any(land_type in card.d.type_line for land_type in types)]
            return self.reveal_land_choice(p,c,candidates) is None
        check_types={'Rootbound Crag':('Mountain','Forest')}
        if name in check_types:return not any(any(land_type in CARDDEF[q.name].type_line for land_type in check_types[name]) for q in lands)
        return enters_tapped(name,p)

    def crack_fetch(self,p,q):
        # Activation timing/target/shock choices are overridden in ManualGame.
        if q not in p.battlefield or q.name not in FETCHES:return False
        self.lose_life(p,1,'fetch land activation')
        self.leave_battlefield(p,q,'graveyard','sacrificed fetch land')
        candidates=self.legal_fetch_cards(p,q.name)
        if not candidates:return
        # prefer untapped source covering missing colors
        def score(c):
            cols=LAND_COLOR_HINTS.get(c.d.name,set()) | ({'W'} if 'Plains' in c.d.type_line else set()) | ({'U'} if 'Island' in c.d.type_line else set()) | ({'B'} if 'Swamp' in c.d.type_line else set()) | ({'R'} if 'Mountain' in c.d.type_line else set()) | ({'G'} if 'Forest' in c.d.type_line else set())
            return (len(cols & COLOR_ID[p.name]), c.d.name not in TAPPED_LANDS)
        c=self.fetch_land_choice(p,q,candidates) or max(candidates,key=score); p.library.remove(c)
        tapped=self.land_enters_tapped_for_fetch(p,c)
        if c.d.name in {'Hallowed Fountain','Godless Shrine','Watery Grave','Stomping Ground'} and self.shock_untapped_choice(p,c):
            self.lose_life(p,2,'shock land untapped'); tapped=False
        q2=self._put_card_bf(p,c,'fetch land')
        q2.tapped=tapped; q2.summoning_sick=False
        self.rng.shuffle(p.library); self.log('shuffle',p.name,None,'Shuffled after fetch')
        return True

    def legal_fetch_cards(self,p,fetch_name):
        types=FETCH_TYPES[fetch_name]
        return [c for c in p.library if c.d.is_land and any(land_type in c.d.type_line for land_type in types)]

    def fetch_land_choice(self,p,q,candidates):
        return max(candidates,key=lambda c:(len(LAND_COLOR_HINTS.get(c.d.name,set()) & COLOR_ID[p.name]),c.d.name not in TAPPED_LANDS),default=None)

    def shock_untapped_choice(self,p,c):return p.life>10

    def land_enters_tapped_for_fetch(self,p,c):
        if c.d.name in SHOCK_LANDS:return True
        return self.land_enters_tapped(p,c)

    def bounce_land_return(self,p,bounce_land):
        lands=[q for q in p.battlefield if CARDDEF.get(q.name) and CARDDEF[q.name].is_land]
        return lands[0] if lands else None

    def land_drop_choice(self,p):
        lands=[c for c in p.hand if c.d.is_land]
        if not lands:return None
        # prioritize color breadth, untapped, then utility slightly later
        def sc(c):
            cols=LAND_COLOR_HINTS.get(c.d.name,set())
            if not cols:
                for b,col in [('Plains','W'),('Island','U'),('Swamp','B'),('Mountain','R'),('Forest','G')]:
                    if b in c.d.type_line:cols.add(col)
            return (c.d.name in FETCHES, c.d.name not in TAPPED_LANDS, len(cols & COLOR_ID[p.name]))
        return max(lands,key=sc)

    def cast(self,p,c,commander=False,miracle=False,x_value=0,free=False):
        if not free and not self.pay(p,c.d,commander=commander,miracle=miracle,x_value=x_value):return False
        if commander:
            assert p.commander and p.commander.uid==c.uid
            p.commander=None
            p.dungeon['commander_casts']=p.dungeon.get('commander_casts',0)+1
        else:
            if c not in p.hand:return False
            p.hand.remove(c)
        p.spells_cast_this_turn+=1
        self.mark_appearance(c.d.name,cast=True)
        self.log('cast',p.name,c.d.name,f'Cast {c.d.name}'+(' for miracle cost' if miracle else '')+(' for free' if free else ''),uid=c.uid,commander=commander,miracle=miracle,x=x_value)
        self.stack.append({'actor':p.name,'uid':c.uid,'card':c.d.name})
        self.log('stack_add',p.name,c.d.name,f'{c.d.name} on stack')
        # Cascade triggers on cast and therefore exists even if the original spell is countered.
        if c.d.name=='Apex Devastator':
            for _ in range(4):self.cascade_once(p,10,'Apex Devastator')
        # Cast-trigger layer: these occur even if the spell is later countered.
        for owner in self.players.values():
            fa=self.perm(owner,'Forgotten Ancient')
            if fa:self.add_counters(owner,fa,'+1/+1',1,'Forgotten Ancient spell-cast trigger')
            tm=self.perm(owner,'Taurean Mauler')
            if tm and owner.name!=p.name:self.add_counters(owner,tm,'+1/+1',1,'Taurean Mauler opponent spell trigger')
            mh=self.perm(owner,'Managorger Hydra')
            if mh:self.add_counters(owner,mh,'+1/+1',1,'Managorger Hydra spell trigger')
        if self.perm(p,'Defiler of Vigor') and c.d.is_permanent and 'G' in re.findall(r'\{([WUBRG])\}',c.d.mana_cost.split(' // ')[0]):
            for cr in [z for z in p.battlefield if self.is_creature_perm(z)]:self.add_counters(p,cr,'+1/+1',1,'Defiler of Vigor green permanent cast')
        if self.perm(p,"Sigarda's Splendor") and 'W' in re.findall(r'\{([WUBRG])\}',c.d.mana_cost.split(' // ')[0]):self.gain_life(p,1,"Sigarda's Splendor white spell")
        for owner in self.players.values():
            if owner.name==p.name or owner.eliminated:continue
            # Deterministic tax policy: pay if mana remains and the spell is strategically important; otherwise feed the engine.
            if self.perm(owner,'Rhystic Study'):
                tax=CardDef('Rhystic Study tax','{1}','Ability','',1,p.name,1)
                if self.spell_threat(p,c.d)>=8 and self.can_pay(p,tax):self.pay(p,tax)
                else:self.draw(owner,1,'Rhystic Study opponent spell')
            if self.perm(owner,'Mystic Remora') and not c.d.is_creature:
                tax=CardDef('Mystic Remora tax','{4}','Ability','',1,p.name,4)
                if self.spell_threat(p,c.d)>=9 and self.can_pay(p,tax):self.pay(p,tax)
                else:self.draw(owner,1,'Mystic Remora opponent noncreature spell')
        if self.react_to_spell(p,c):
            # countered; goes graveyard or commander zone
            self.stack.pop()
            if commander:
                p.commander=c; p.command_tax+=2; self.log('commander_zone',p.name,c.d.name,'Countered commander returned to command zone')
            else:
                p.graveyard.append(c); self.log('countered',p.name,c.d.name,f'{c.d.name} countered → graveyard')
            if c.d.is_instant or c.d.is_sorcery:self.mark_appearance(c.d.name,realized=True)
            return True
        self.stack.pop(); self.log('resolve',p.name,c.d.name,f'{c.d.name} resolves')
        if c.d.is_permanent:
            q=self.make_perm(p,c,'commander' if commander else 'hand') if False else None
            # c removed above; need create directly without make_perm removing twice
            bp,bt=base_stats(c.d.name,c.d)
            if c.d.is_creature and c.d.name not in PT:self.stat_fallback.add(c.d.name)
            q=Perm(c.uid,c.d.name,p.name,p.name,tapped=enters_tapped(c.d.name,p),summoning_sick=c.d.is_creature,counters={},base_power=bp,base_toughness=bt,keywords=set(KEYWORDS.get(c.d.name,set())),entered_turn=self.turn_number)
            p.battlefield.append(q); self.mark_appearance(c.d.name,realized=True)
            self.log('etb',p.name,c.d.name,f'{c.d.name} entered battlefield after resolving',uid=c.uid)
            self.on_etb(p,q,x_value=x_value)
            if commander:p.command_tax+=2
        else:
            p.graveyard.append(c); self.mark_appearance(c.d.name,realized=True)
            self.resolve_spell(p,c,x_value=x_value)
            self.log('spell_to_graveyard',p.name,c.d.name,f'{c.d.name} finished resolving → graveyard',uid=c.uid)
        if p.name=='Reaminatour' and p.miracle_card_uid==c.uid:p.miracle_card_uid=None
        self.check_sba()
        self.check_ream_combo()
        return True

    def commander_cast(self,p):
        if not p.commander:return False
        return self.cast(p,p.commander,commander=True)

    def react_to_spell(self,caster:PlayerState,c:CardObj):
        # deterministic threat assessment and counter use. Protection can counter the counter where modeled.
        threat=self.spell_threat(caster,c.d)
        if threat<7:return False
        # order from next player around table
        ci=self.turn_order.index(caster.name)
        for k in range(1,4):
            op=self.players[self.turn_order[(ci+k)%4]]
            if op.eliminated:continue
            counters=[]
            for nm in ['Swan Song','Fierce Guardianship','Remand','Counterspell','Summary Dismissal','Arcane Denial']:
                cc=self.card_in_hand(op,nm)
                if not cc:continue
                # Swan only noncreature; Remand any spell; Fierce free with commander
                if nm=='Swan Song' and c.d.is_creature:continue
                if nm=='Fierce Guardianship' and c.d.is_creature:continue
                free=(nm=='Fierce Guardianship' and self.controls_commander(op))
                if free or self.can_pay(op,cc.d):counters.append((cc,free))
            if counters:
                cc,free=counters[0]
                if not free:self.pay(op,cc.d)
                op.hand.remove(cc);op.graveyard.append(cc);self.mark_appearance(cc.d.name,cast=True,realized=True)
                self.log('counterspell',op.name,cc.d.name,f'{cc.d.name} counters {c.d.name}',target=c.d.name)
                if cc.d.name=='Summary Dismissal':caster.exile.append(c);self.log('exile',caster.name,c.d.name,'Summary Dismissal exiles the spell from the stack')
                # caster can protect with a counter against the counter
                prot=None
                for nm in ['Swan Song','Fierce Guardianship','Remand','Counterspell','Arcane Denial']:
                    pc=self.card_in_hand(caster,nm)
                    if not pc:continue
                    if nm=='Fierce Guardianship' and c.d.is_creature:continue
                    freep=(nm=='Fierce Guardianship' and self.controls_commander(caster))
                    if freep or self.can_pay(caster,pc.d):prot=(pc,freep);break
                if prot:
                    pc,freep=prot
                    if not freep:self.pay(caster,pc.d)
                    caster.hand.remove(pc);caster.graveyard.append(pc);self.mark_appearance(pc.d.name,cast=True,realized=True)
                    self.log('counter_counter',caster.name,pc.d.name,f'{pc.d.name} counters {cc.d.name}; {c.d.name} remains live')
                    if pc.d.name=='Arcane Denial':self.schedule_arcane_denial(op,caster)
                    return False
                if cc.d.name=='Arcane Denial':self.schedule_arcane_denial(caster,op)
                return True
        return False

    def schedule_arcane_denial(self,spell_controller,denial_controller):
        trigger={'due_turn':self.turn_number+1,'spell_controller':spell_controller.name,'denial_controller':denial_controller.name}
        self.pending_arcane_denials.append(trigger)
        self.log('delayed_trigger',denial_controller.name,'Arcane Denial',f"At the next turn's upkeep, {spell_controller.name} draws two cards and {denial_controller.name} draws one",**trigger)

    def resolve_arcane_denial_triggers(self):
        due=[row for row in self.pending_arcane_denials if row['due_turn']<=self.turn_number]
        self.pending_arcane_denials=[row for row in self.pending_arcane_denials if row not in due]
        for row in due:
            spell_controller=self.players[row['spell_controller']];denial_controller=self.players[row['denial_controller']]
            self.draw(spell_controller,2,'Arcane Denial delayed upkeep trigger')
            self.draw(denial_controller,1,'Arcane Denial delayed upkeep trigger')
            self.log('delayed_trigger_resolved',denial_controller.name,'Arcane Denial',f'{spell_controller.name} drew two cards; {denial_controller.name} drew one')

    def spell_threat(self,p,d):
        name=d.name
        if name in {'Chandra\'s Ignition','Exsanguinate','Debt to the Deathless','Death Grasp','Replenish','Parallax Wave','Starfield of Nyx','Felidar Guardian','Grim Guardian','Animate Dead','Dance of the Dead','Necromancy','Gifts Ungiven','Apex Devastator','Replication Technique','Aggressive Biomancy','Unnatural Growth','Branching Evolution','The Earth Crystal','Kalonian Hydra'}:return 9
        if d.mv>=6:return 7
        if name in {'Minsc & Boo, Timeless Heroes','Aminatou, Veil Piercer','Omo, Queen of Vesuva','Elenda, Saint of Dusk'}:return 6
        return 3

    def on_landfall(self,p,land):
        if p.name=='Omo':
            if self.perm(p,'Rampaging Baloths'): self.token(p,'Beast',4,4,{'trample'})
            sc=self.perm(p,'Scute Swarm')
            if sc:
                lands=sum(1 for q in p.battlefield if CARDDEF.get(q.name) and CARDDEF[q.name].is_land)
                if lands>=6:
                    existing=[q for q in list(p.battlefield) if q.name=='Scute Swarm']
                    for _ in existing:self.token(p,'Scute Swarm',1,1)
                else:self.token(p,'Insect',1,1)
            av=self.perm(p,'Avenger of Zendikar')
            if av:
                for q in p.battlefield:
                    if q.name=='Plant':self.add_counters(p,q,'+1/+1',1,'Avenger landfall')
            if self.perm(p,'Tatyova, Benthic Druid'):
                self.gain_life(p,1,'Tatyova landfall');self.draw(p,1,'Tatyova landfall')
            bill=self.perm(p,'Bristly Bill, Spine Sower')
            if bill:
                target=self.strongest_creature(p)
                if target:self.add_counters(p,target,'+1/+1',1,'Bristly Bill landfall')
            sage=self.perm(p,'Evolution Sage')
            if sage:
                for q in p.battlefield:
                    for kind,val in list(q.counters.items()):
                        if val>0 and kind in {'+1/+1','loyalty','everything'}:q.counters[kind]=val+1
                self.log('proliferate',p.name,'Evolution Sage','Landfall proliferates each relevant permanent counter once')
        el=self.players.get('Elenda')
        if el and not el.eliminated and p.name!='Elenda' and self.perm(el,'Polluted Bonds'):
            self.lose_life(p,2,'Polluted Bonds');self.gain_life(el,2,'Polluted Bonds')

    def trigger_creature_etb(self,p,q):
        if self.perm(p,'Liliana the Faultless') and q.name!='Liliana the Faultless':self.gain_life(p,1,'Liliana ETB trigger')
        if p.name=='Elenda' and q.name=='Inspiring Overseer':self.gain_life(p,1,'Inspiring Overseer');self.draw(p,1,'Inspiring Overseer')
        # Champion grows for every other creature entering.
        champ=self.perm(p,'Champion of Lambholt')
        if champ and q.uid!=champ.uid:self.add_counters(p,champ,'+1/+1',1,'Champion of Lambholt creature ETB')
        if self.perm(p,"Garruk's Uprising") and self.power(q)>=4:self.draw(p,1,"Garruk's Uprising creature ETB")

    def changing_loyalty_target(self,p,choices):
        return max(choices,key=lambda row:self.perm_threat(row[1]),default=None)

    def trigger_planeswalker_etb(self,p,q):
        if self.perm(p,'Liliana the Faultless') and q.name!='Liliana the Faultless':
            self.gain_life(p,1,'Liliana planeswalker ETB trigger')

    def on_etb(self,p,q,x_value=0):
        n=q.copy_of or q.name
        d=CARDDEF.get(n)
        starting_loyalty=catalog_starting_loyalty(n,x_value=x_value)
        if starting_loyalty is not None:q.counters.setdefault('loyalty',starting_loyalty)
        # Entry replacement effects exist when other permanents observe the entry.
        if n=='Kalonian Hydra':self.add_counters(p,q,'+1/+1',4,'Kalonian Hydra enters')
        elif n=='Hydroid Krasis':self.hydroid_krasis_etb(p,q,x_value)
        if d and d.is_enchantment:
            p.enchantments_entered_this_turn+=1
            self.on_enchantment_etb(p,q)
        if d and d.is_creature:self.trigger_creature_etb(p,q)
        if d and d.is_planeswalker and not d.is_creature:self.trigger_planeswalker_etb(p,q)
        # mana/ramp/draw/value exact handlers
        if n=='Minsc & Boo, Timeless Heroes':
            self.minsc_enters(p,q)
        elif n=='Omo, Queen of Vesuva':self.omo_everything(p,q)
        elif n=='Baleful Strix':self.baleful_strix_etb(p,q)
        elif n=='Solemn Simulacrum':self.solemn_simulacrum_etb(p,q)
        elif n=='Spirited Companion':self.spirited_companion_etb(p,q)
        elif n=='Omen of the Sea':self.omen_of_the_sea_etb(p,q)
        elif n=='Entity Tracker': pass
        elif n=='Funeral Room // Awakening Hall':q.metadata['funeral_unlocked']=True;q.metadata['awakening_unlocked']=False
        elif n=='Chthonian Nightmare':self.chthonian_nightmare_etb(p,q)
        elif n=='Gravebreaker Lamia':self.gravebreaker_lamia_etb(p,q)
        elif n=='Invasion of Theros':self.invasion_of_theros_etb(p,q)
        elif n=='Leonin Relic-Warder':self.lrw_etb(p,q)
        elif n=='Loran of the Third Path':self.loran_etb(p,q)
        elif n=='Acidic Slime':self.acidic_slime_etb(p,q)
        elif n=='Eternal Witness':self.eternal_witness_etb(p,q)
        elif n=='Spelunking':self.spelunking_etb(p,q)
        elif n=='Ulvenwald Hydra':self.ulvenwald_hydra_etb(p,q)
        elif n=='Xolatoyac, the Smiling Flood':self.xolatoyac_counter(p,'ETB')
        elif n=='Terastodon':self.terastodon_etb(p,q)
        elif n=='Avenger of Zendikar':self.avenger_of_zendikar_etb(p,q)
        elif n=='Elvish Rejuvenator':self.elvish_rejuvenator_etb(p,q)
        elif n=='Satyr Wayfinder':self.satyr_wayfinder_etb(p,q)
        elif n=='Rampant Frogantua':pass
        elif n=="Uro, Titan of Nature's Wrath":self.uro_etb(p,q)
        elif n=='Apex Devastator':pass
        elif n=='Jyoti, Moag Ancient':self.jyoti_etb(p,q)
        elif n=='Rune-Scarred Demon':self.rune_scarred_demon_etb(p,q)
        elif n=='Noxious Gearhulk':self.noxious_gearhulk_etb(p,q)
        elif n=='Angel of Invention':
            self.angel_fabricate(p,q)
        elif n=='Celestial Armor':
            self.celestial_armor_etb(p,q)
        elif n=='Angelic Destiny':
            self.angelic_destiny_etb(p,q)
        elif n=='The Cruelty of Gix':
            self.saga_enters(p,q)
        elif n in {'Elspeth Conquers Death','The Restoration of Eiganjo'}:
            self.saga_enters(p,q)
        elif n=='Phyrexian Arena': pass
        elif n=='Doomwake Giant': pass  # constellation is collected by on_enchantment_etb(), including its own entry
        elif n=='The Meathook Massacre': self.meathook_etb(p,x_value)
        elif n=='Ghostly Dancers':self.ghostly_dancers_etb(p,q)
        elif n=='Felidar Guardian':self.felidar_etb(p,q)
        elif n=='Fallen Ideal':self.fallen_ideal_etb(p,q)
        elif n in {'Animate Dead','Dance of the Dead','Necromancy'}:
            self.reanimate_aura_etb(p,q)
        elif n=='Karmic Guide':self.karmic_guide_etb(p,q)
        elif n=='Sun Titan':self.sun_titan_etb(p,q)
        elif n=='Mulldrifter':self.mulldrifter_etb(p,q)
        elif n=='Alseid of Life\'s Bounty':pass
        elif n=='Gleaming Splendor':pass
        elif n=='Victor, Valgavoth\'s Seneschal':pass
        elif n=='Starfield of Nyx':pass
        elif n=='Parallax Wave':q.counters['fade']=5
        elif n=='The Ozolith':pass
        elif n=='Ozolith, the Shattered Spire':pass
        elif n=='The Earth Crystal':pass
        elif n=='Branching Evolution':pass
        elif n=='Hardened Scales':pass
        elif n=='Rhythm of the Wild':pass
        elif n=='Dawn of Hope':pass
        elif n=='Leyline of Hope':pass
        elif n=='Pristine Talisman':pass
        elif n=='Mystic Remora':q.counters['age']=0
        elif n=='Rhystic Study':pass
        elif n=="Garruk's Uprising":self.garruks_uprising_etb(p,q)
        elif n=="Sigarda's Splendor":q.metadata['noted_life']=p.life
        elif n in {'Touch the Spirit Realm','Oblivion Ring','Prayer of Binding'}:
            self.linked_exile_etb(p,q)
        elif n=='Grasp of Fate':
            self.grasp_of_fate_etb(p,q)
        elif n=='Darksteel Mutation':
            self.darksteel_mutation_etb(p,q)
        elif n=='Changing Loyalty':
            self.changing_loyalty_etb(p,q)
        # generic draw on ETB one card
        elif d and 'When' in d.text and 'enters' in d.text and 'draw a card' in d.text.lower():self.generic_draw_etb(p,q)
        self.check_sba()

    # ETB handlers are virtual so the manual referee can turn each material
    # ability into a real stack object while the compact simulation retains its
    # original immediate-resolution policy.
    def hydroid_krasis_etb(self,p,q,x_value):
        self.add_counters(p,q,'+1/+1',x_value,'Hydroid Krasis');self.gain_life(p,x_value//2,'Hydroid Krasis');self.draw(p,x_value//2,'Hydroid Krasis')

    def baleful_strix_etb(self,p,q):self.draw(p,1,'Baleful Strix ETB')
    def solemn_simulacrum_etb(self,p,q):self.search_basic_to_battlefield(p,'Solemn Simulacrum')
    def spirited_companion_etb(self,p,q):self.draw(p,1,'Spirited Companion ETB')
    def omen_of_the_sea_etb(self,p,q):self.scry(p,2,'Omen of the Sea');self.draw(p,1,'Omen of the Sea')
    def chthonian_nightmare_etb(self,p,q):p.energy+=3;self.log('energy',p.name,q.name,'Got 3 energy',energy=p.energy)

    def gravebreaker_lamia_etb(self,p,q):
        target=self.request_ream_grave_target(p) if p.name=='Reaminatour' else None
        if target:self.search_to_zone(p,target,'graveyard','Gravebreaker Lamia')

    def invasion_of_theros_etb(self,p,q):
        if p.name=='Reaminatour':
            target=self.request_ream_tutor(p,filter_kind='aura')
            if target:self.search_to_zone(p,target,'hand','Invasion of Theros',reveal=True)

    def loran_etb(self,p,q):self.destroy_best_noncreature(p,'Loran ETB')
    def acidic_slime_etb(self,p,q):self.destroy_best_noncreature(p,'Acidic Slime ETB',allow_land=True)
    def spelunking_etb(self,p,q):self.draw(p,1,'Spelunking ETB');self.extra_land_from_hand(p,'Spelunking ETB')

    def ulvenwald_hydra_etb(self,p,q):
        lands=[card for card in p.library if card.d.is_land]
        if lands:
            card=max(lands,key=lambda candidate:self.generic_card_score(p,candidate.d.name));p.library.remove(card)
            land=self._put_card_bf(p,card,'Ulvenwald Hydra ETB land search');land.tapped=True;land.summoning_sick=False
            self.rng.shuffle(p.library);self.log('shuffle',p.name,None,'Shuffle after Ulvenwald Hydra')

    def terastodon_etb(self,p,q):
        for _ in range(3):
            choices=[(owner,target) for owner in self.players.values() for target in owner.battlefield
                     if target.uid!=q.uid and CARDDEF.get(target.name) and not CARDDEF[target.name].is_creature]
            if not choices:break
            owner,target=max(choices,key=lambda row:self.perm_threat(row[1]))
            if self.destroy(owner,target,'Terastodon ETB'):self.token(owner,'Elephant',3,3)

    def avenger_of_zendikar_etb(self,p,q):
        for _ in range(sum(1 for permanent in p.battlefield if is_land_permanent(permanent))):self.token(p,'Plant',0,1)
    def elvish_rejuvenator_etb(self,p,q):self.look_land_to_bf(p,5,'Elvish Rejuvenator')
    def satyr_wayfinder_etb(self,p,q):self.look_land_to_hand_mill(p,4,'Satyr Wayfinder')

    def uro_etb(self,p,q):
        escaped=(p.dungeon.pop('escaping_uro_uid',None)==q.uid) or q.metadata.get('escaped')
        if escaped:q.metadata['escaped']=True
        self.gain_life(p,3,'Uro ETB');self.draw(p,1,'Uro ETB');self.extra_land_from_hand(p,'Uro ETB')
        actual=self.find_card_obj_on_bf(p,q.uid)
        if not escaped and actual:self.leave_battlefield(p,actual,'graveyard','Uro ETB sacrifice unless escaped')

    def jyoti_etb(self,p,q):
        for _ in range(p.dungeon.get('commander_casts',0)):self.token(p,'Forest Dryad',1,1)
    def rune_scarred_demon_etb(self,p,q):self.search_to_zone(p,self.request_library_card(p),'hand','Rune-Scarred Demon')

    def noxious_gearhulk_etb(self,p,q):
        target=self.best_enemy_creature(p)
        if target:
            owner,creature=target;toughness=self.toughness(creature)
            if self.destroy(owner,creature,'Noxious Gearhulk'):self.gain_life(p,toughness,'Noxious Gearhulk')

    def karmic_guide_etb(self,p,q):self.reanimate_best_creature(p,'Karmic Guide')
    def sun_titan_etb(self,p,q):self.sun_titan_trigger(p,'ETB')
    def garruks_uprising_etb(self,p,q):
        if any(self.is_creature_perm(creature) and self.power(creature)>=4 for creature in p.battlefield):self.draw(p,1,"Garruk's Uprising ETB")
    def generic_draw_etb(self,p,q):self.draw(p,1,f'{q.name} ETB')

    def ghostly_dancers_etb(self,p,q):
        room=self.perm(p,'Funeral Room // Awakening Hall')
        creatures=[c for c in p.graveyard if c.d.is_creature]
        if room and not room.metadata.get('awakening_unlocked') and len(creatures)>=2:
            self.unlock_awakening_hall(p,room,'Ghostly Dancers')
            return
        ens=[c for c in p.graveyard if c.d.is_enchantment]
        if ens:
            c=max(ens,key=lambda z:self.ream_card_score(z.d.name) if p.name=='Reaminatour' else z.d.mv)
            p.graveyard.remove(c);p.hand.append(c);self.log('return_to_hand',p.name,c.d.name,'Ghostly Dancers ETB')

    def celestial_armor_etb(self,p,q):
        target=self.strongest_creature(p)
        if target:
            q.attached_to=target.uid;target.metadata['celestial_armor_uid']=q.uid;target.metadata['celestial_hexproof_turn']=self.turn_number;target.metadata['celestial_indestructible_turn']=self.turn_number
            self.log('attach',p.name,q.name,f'Celestial Armor attaches to {target.name}; hexproof/indestructible this turn',target_uid=target.uid)

    def angelic_destiny_etb(self,p,q):
        target=self.strongest_creature(p)
        if target:q.attached_to=target.uid;target.metadata['angelic_destiny_uid']=q.uid;self.log('attach',p.name,q.name,f'Angelic Destiny enchants {target.name}',target_uid=target.uid)

    def darksteel_mutation_etb(self,p,q):
        target=self.best_enemy_creature(p)
        if target:
            owner,creature=target
            creature.metadata['darksteel_original']={'base_power':creature.base_power,'base_toughness':creature.base_toughness,'keywords':sorted(creature.keywords)}
            creature.base_power=0;creature.base_toughness=1;creature.keywords={'indestructible'};creature.metadata['mutated']=True;q.attached_to=creature.uid
            self.log('aura_disable',p.name,q.name,f'Darksteel Mutation disables {creature.name}',target=creature.name)

    def changing_loyalty_etb(self,p,q):
        choices=[(owner,target) for owner in self.players.values() for target in owner.battlefield if self.is_creature_perm(target)]
        chosen=self.changing_loyalty_target(p,choices)
        if chosen:
            owner,target=chosen;q.attached_to=target.uid;self.log('attach',p.name,q.name,f'Changing Loyalty enchants {target.name}',target_uid=target.uid,target_controller=owner.name)

    def mulldrifter_etb(self,p,q):
        self.draw(p,2,'Mulldrifter ETB')

    def eternal_witness_etb(self,p,q):
        cards=[card for card in p.graveyard if card.uid!=q.uid]
        if cards:
            card=max(cards,key=lambda candidate:self.generic_card_score(p,candidate.d.name))
            p.graveyard.remove(card);p.hand.append(card);self.log('return_to_hand',p.name,card.d.name,'Eternal Witness ETB')

    def minsc_enters(self,p,q):
        loyalty=catalog_starting_loyalty(q.name)
        if loyalty is not None:q.counters.setdefault('loyalty',loyalty)
        self.create_boo(p)

    def linked_exile_etb(self,p,q):
        choices=[]
        for op in self.opponents(p):
            for target in op.battlefield:
                definition=CARDDEF.get(target.name)
                if not definition or definition.is_land:continue
                if q.name=='Touch the Spirit Realm' and not (definition.is_artifact or definition.is_creature):continue
                choices.append((op,target))
        if choices:
            owner,target=max(choices,key=lambda row:self.perm_threat(row[1]));uid=target.uid
            self.leave_battlefield(owner,target,'exile',q.name+' linked exile');q.metadata['linked_exiled_uids']=[uid]
        if q.name=='Prayer of Binding':self.gain_life(p,2,'Prayer of Binding')

    def grasp_of_fate_etb(self,p,q):
        uids=[]
        for opponent in self.opponents(p):
            choices=[target for target in opponent.battlefield if CARDDEF.get(target.name) and not CARDDEF[target.name].is_land]
            if choices:
                target=max(choices,key=self.perm_threat);uids.append(target.uid)
                self.leave_battlefield(opponent,target,'exile','Grasp of Fate linked exile')
        q.metadata['linked_exiled_uids']=uids

    def fallen_ideal_etb(self,p,q):
        choices=[t for t in p.battlefield if self.is_creature_perm(t)]
        if not choices:return
        target=max(choices,key=self.power);q.attached_to=target.uid
        if 'flying' not in target.keywords:target.metadata['fallen_granted_flying']=True;target.keywords.add('flying')
        self.log('attach',p.name,q.name,f'Fallen Ideal enchants {target.name}',target_uid=target.uid)

    def angel_fabricate(self,p,q):
        self.token(p,'Servo',1,1);self.token(p,'Servo',1,1)

    def on_enchantment_etb(self,p,q):
        if self.perm(p,'Grim Guardian'):
            for op in self.opponents(p):self.lose_life(op,1,'Grim Guardian constellation')
        if self.perm(p,'Underworld Coinsmith'):self.gain_life(p,1,'Underworld Coinsmith constellation')
        if self.perm(p,'Entity Tracker') and q.name!='Entity Tracker':self.draw(p,1,'Entity Tracker eerie')
        if self.perm(p,'Ghostly Dancers') and q.name!='Ghostly Dancers':self.token(p,'Spirit',3,1,{'flying'})
        vic=self.perm(p,"Victor, Valgavoth's Seneschal")
        if vic:
            if vic.metadata.get('eerie_count_turn_number')!=self.turn_number:
                vic.metadata['eerie_count_turn_number']=self.turn_number
                vic.metadata['eerie_count_turn']=0
            cnt=vic.metadata.get('eerie_count_turn',0)+1;vic.metadata['eerie_count_turn']=cnt
            if cnt==1:self.scry(p,2,'Victor surveil')
            elif cnt==2:
                for op in self.opponents(p):
                    if op.hand:
                        c=op.hand.pop(0);op.graveyard.append(c);self.log('discard',op.name,c.d.name,'Victor second eerie')
            elif cnt==3:self.reanimate_best_creature(p,'Victor third eerie',any_grave=True)
        if self.perm(p,'Doomwake Giant'):self.doomwake(p)
        # Gleaming Splendor reacts to second draws in draw(), not here

    def on_ltb(self,p,q,died=False):
        ozolith=self.perm(p,'The Ozolith')
        if ozolith and q.uid!=ozolith.uid and self.is_creature_perm(q) and q.counters:
            for kind,count in q.counters.items():
                self.add_counters(p,ozolith,kind,count,'The Ozolith leave-the-battlefield trigger')
        if died:
            # death triggers
            if q.name=='Essence Channeler' and q.counters:
                targets=[creature for creature in p.battlefield if self.is_creature_perm(creature)]
                target=self.essence_channeler_death_target(p,q,targets) if targets else None
                if target:
                    for kind,count in q.counters.items():
                        self.add_counters(p,target,kind,count,'Essence Channeler death trigger')
            room=self.perm(p,'Funeral Room // Awakening Hall')
            if room and room.metadata.get('funeral_unlocked',True):
                for op in self.opponents(p):self.lose_life(op,1,'Funeral Room death trigger')
                self.gain_life(p,1,'Funeral Room')
            if self.perm(p,'The Meathook Massacre'):
                for op in self.opponents(p):self.lose_life(op,1,'Meathook own-creature death')
            # opponent meathooks gain life
            for op in self.opponents(p):
                if self.perm(op,'The Meathook Massacre'):self.gain_life(op,1,'Meathook opponent creature death')
            if q.name=='Solemn Simulacrum':self.draw(p,1,'Solemn death')
            if q.name=="Elenda's Hierophant":
                for _ in range(min(self.power(q),40)):self.token(p,'Vampire',1,1,{'lifelink'})
            if q.name=='Fiendish Panda':
                targets=[c for c in p.graveyard if c.d.is_creature and 'Bear' not in c.d.type_line and c.d.mv<=self.power(q) and c.uid!=q.uid]
                if targets:self.put_grave_creature_bf(p,max(targets,key=lambda c:c.d.mv),'Fiendish Panda death trigger')
            ad=next((a for a in p.battlefield if a.name=='Angelic Destiny' and a.attached_to==q.uid),None)
            if ad:
                p.battlefield.remove(ad);p.hand.append(CardObj(ad.uid,CARDDEF[ad.name]));self.log('return_to_hand',p.name,'Angelic Destiny','Enchanted creature died; Angelic Destiny returns to hand')
        if q.name in {'Vesperlark','Reveillark'}:self.lark_ltb(p,q)
        if died and q.name=='Glen Elendra Archmage' and q.counters.get('-1/-1',0)==0:
            owner=self.players[q.owner]
            card=next((c for c in owner.graveyard if c.uid==q.uid),None)
            if card:
                owner.graveyard.remove(card)
                returned=self._put_card_bf(owner,card,'Glen Elendra Archmage persist')
                returned.counters['-1/-1']=1
                self.log('persist',owner.name,q.name,'Returned with a -1/-1 counter',uid=q.uid)

        # Changing Loyalty triggers when its enchanted creature dies.
        if died:
            cl=next((a for a in p.battlefield if a.name=='Changing Loyalty' and a.attached_to==q.uid),None)
            if cl:
                c=next((c for c in p.graveyard if c.uid==q.uid),None)
                if c:
                    p.graveyard.remove(c);self._put_card_bf(p,c,'Changing Loyalty death trigger')
        if q.name=='Angelic Destiny' and q.attached_to:
            t=self.find_card_obj_on_bf(p,q.attached_to)
            if t:t.metadata.pop('angelic_destiny_uid',None)
        if q.name=='Celestial Armor' and q.attached_to:
            t=self.find_card_obj_on_bf(p,q.attached_to)
            if t:t.metadata.pop('celestial_armor_uid',None)
        if q.name=='Darksteel Mutation' and q.attached_to:
            for controller in self.players.values():
                target=self.find_card_obj_on_bf(controller,q.attached_to)
                if not target:continue
                original=target.metadata.pop('darksteel_original',None)
                if original:
                    target.base_power=original['base_power'];target.base_toughness=original['base_toughness']
                    target.keywords=set(original['keywords'])
                else:
                    copied=target.copy_of or target.name;definition=CARDDEF.get(copied)
                    target.base_power,target.base_toughness=base_stats(copied,definition)
                    target.keywords=set(KEYWORDS.get(copied,set()))
                target.metadata.pop('mutated',None)
                self.log('aura_restore',controller.name,q.name,f'{target.name} regains its printed characteristics',target_uid=target.uid)
                break
        if q.name=='Fallen Ideal' and q.attached_to:
            for controller in self.players.values():
                target=self.find_card_obj_on_bf(controller,q.attached_to)
                if target and target.metadata.pop('fallen_granted_flying',False):target.keywords.discard('flying')
            owner=self.players[q.owner]
            card=next((card for card in owner.graveyard if card.uid==q.uid),None)
            if card:
                owner.graveyard.remove(card);owner.hand.append(card);self.log('return_to_hand',owner.name,q.name,'Fallen Ideal graveyard trigger')
        # Linked-exile enchantments return their specific exiled objects when they leave.
        for uid in q.metadata.get('linked_exiled_uids',[]):
            for owner in self.players.values():
                c=next((c for c in owner.exile if c.uid==uid),None)
                if c:
                    owner.exile.remove(c);self._put_card_bf(owner,c,f'{q.name} leaves linked return');break
        # linked auras: if Aura leaves, sacrifice linked creature
        if q.name in {'Animate Dead','Dance of the Dead','Necromancy'} and q.attached_to:
            t=self.find_card_obj_on_bf(p,q.attached_to)
            if t:self.leave_battlefield(p,t,'graveyard',f'{q.name} left battlefield')
        # LRW leaves -> return exiled linked object
        if q.name=='Leonin Relic-Warder' and q.metadata.get('exiled_uid'):
            uid=q.metadata['exiled_uid']
            for owner in self.players.values():
                c=next((c for c in owner.exile if c.uid==uid),None)
                if c:
                    owner.exile.remove(c); self._put_card_bf(owner,c,'LRW leaves');break

    def lark_ltb(self,p,q):
        power_limit=1 if q.name=='Vesperlark' else 2
        maximum=1 if q.name=='Vesperlark' else 2
        targets=[card for card in p.graveyard if card.d.is_creature and self.card_base_power(card.d.name)<=power_limit]
        ordered=sorted(targets,key=lambda card:self.ream_card_score(card.d.name) if p.name=='Reaminatour' else card.d.mv,reverse=True)
        for card in ordered[:maximum]:self.put_grave_creature_bf(p,card,q.name+' LTB')

    def essence_channeler_death_target(self,p,channeler,targets):
        return max(targets,key=self.power,default=None)

    def card_base_power(self,name):return base_stats(name,CARDDEF.get(name))[0]

    def check_sba(self):
        # Destroy creatures with toughness <= 0, and put attached Auras into
        # their owners' graveyards when the enchanted permanent has left.
        changed=True
        while changed:
            changed=False
            for p in self.players.values():
                for q in list(p.battlefield):
                    d=CARDDEF.get(q.name)
                    if self.is_creature_perm(q) and self.toughness(q)<=0:
                        self.leave_battlefield(p,q,'graveyard','state-based toughness <= 0');changed=True;break
                    if self.is_creature_perm(q) and q.metadata.get('damage_marked',0)>=self.toughness(q):
                        # Lethal marked damage destroys rather than reducing
                        # toughness.  An indestructible permanent therefore
                        # remains a stable state with that damage marked; only
                        # restart the SBA scan when destruction actually moved
                        # the object (regeneration likewise returns False after
                        # making its own state changes).
                        if self.destroy(p,q,'state-based lethal marked damage'):
                            changed=True;break
                    if d and d.is_planeswalker and q.counters.get('loyalty',0)<=0:
                        self.leave_battlefield(p,q,'graveyard','state-based loyalty <= 0');changed=True;break
                    is_aura=(d and 'Aura' in d.type_line) or q.name in {'Animate Dead','Dance of the Dead','Necromancy','Fallen Ideal','Changing Loyalty'}
                    attachment_exists=q.attached_to and any(
                        self.find_card_obj_on_bf(controller,q.attached_to)
                        for controller in self.players.values()
                    )
                    if is_aura and q.attached_to and not attachment_exists:
                        self.leave_battlefield(p,q,'graveyard','state-based Aura attachment illegal');changed=True;break
                if changed:break

    def activate_dark_depths(self,p,depths):
        if depths not in p.battlefield or (depths.copy_of or depths.name)!='Dark Depths' or depths.counters.get('ice',0)<=0:return False
        cost=CardDef('Dark Depths activation','{3}','Ability','',1,p.name,3)
        if self.can_pay(p,cost) is None:return False
        self.pay(p,cost);depths.counters['ice']-=1
        self.log('counter_removed',p.name,depths.name,f'Removed an ice counter from {depths.name}',remaining=depths.counters['ice'])
        if depths.counters['ice']==0:self.resolve_dark_depths_zero(p,depths)
        return True

    def resolve_dark_depths_zero(self,p,depths):
        if depths not in p.battlefield or (depths.copy_of or depths.name)!='Dark Depths' or depths.counters.get('ice',0)>0:return False
        self.leave_battlefield(p,depths,'graveyard','Dark Depths triggered sacrifice')
        self.token(p,'Marit Lage',20,20,{'flying','indestructible'})
        self.log('dark_depths',p.name,'Marit Lage','Created legendary 20/20 black Avatar token with flying and indestructible')
        return True

    def can_activate_stage(self,p,stage):
        if stage not in p.battlefield or stage.tapped or stage.name!="Thespian's Stage":return False
        stage.tapped=True
        payable=self.can_pay(p,CardDef("Thespian's Stage activation",'{2}','Ability','',1,p.name,2)) is not None
        stage.tapped=False
        return payable

    def activate_stage(self,p,stage,target=None):
        if not self.can_activate_stage(p,stage):return False
        lands=[q for owner in self.players.values() for q in owner.battlefield if CARDDEF.get(q.name) and CARDDEF[q.name].is_land]
        if not lands:return False
        if target is None:target=max(lands,key=lambda q:20 if (q.copy_of or q.name)=='Dark Depths' else source_colors(p,q)[1])
        stage.tapped=True
        cost=CardDef("Thespian's Stage activation",'{2}','Ability','',1,p.name,2)
        if not self.pay(p,cost):stage.tapped=False;return False
        stage.copy_of=target.copy_of or target.name
        self.log('land_copy',p.name,stage.name,f"Thespian's Stage becomes a copy of {stage.copy_of}",target_uid=target.uid)
        if stage.copy_of=='Dark Depths':
            # Before the state trigger can resolve, the legend rule applies to
            # every Dark Depths this player controls.  Keeping the counterless
            # Stage-copy is what permits its trigger to sacrifice it for Marit
            # Lage; keeping the original makes the pending trigger do nothing.
            others=[q for q in p.battlefield if q.uid!=stage.uid and (q.copy_of or q.name)=='Dark Depths']
            if others:
                keep=self.stage_depths_legend_choice(p,stage,others)
                for q in [stage]+others:
                    if q is not keep and q in p.battlefield:self.leave_battlefield(p,q,'graveyard','legend rule: Dark Depths')
        self.resolve_dark_depths_zero(p,stage)
        return True

    def stage_depths_legend_choice(self,p,stage,others):
        return stage

    def doomwake(self,p):
        for op in self.opponents(p):
            for q in list(op.battlefield):
                if self.is_creature_perm(q):q.metadata['eot_pt_penalty']=q.metadata.get('eot_pt_penalty',0)+1
        self.log('global_effect',p.name,'Doomwake Giant','Opposing creatures get -1/-1 until end of turn')
        self.check_sba()

    def meathook_etb(self,p,x):
        if x<=0:return
        for pp in self.players.values():
            for q in list(pp.battlefield):
                if self.is_creature_perm(q):q.metadata['eot_pt_penalty']=q.metadata.get('eot_pt_penalty',0)+x
        self.log('global_effect',p.name,'The Meathook Massacre',f'All creatures get -{x}/-{x} until end of turn')
        self.check_sba()

    def reset_eot_modifiers(self):
        for p in self.players.values():
            for q in p.battlefield:
                q.metadata.pop('eot_pt_penalty',None)
                q.metadata.pop('xenagos_bonus',None)
                q.metadata.pop('unnatural_growth',None)
                q.metadata.pop('power_doubles',None)
                q.metadata.pop('wildspeaker_bonus',None)
                q.metadata.pop('damage_marked',None)
                for k in ['march_copy','march_power','march_toughness','march_keywords','march_animated','sage_animated','sage_power','jyoti_bonus','ruby_attack_bonus','fixed_power_bonus','fixed_toughness_bonus','power_doubles','heroic_protected_turn','celestial_hexproof_turn','celestial_indestructible_turn','lifelink_turn']:
                    q.metadata.pop(k,None)

    def lrw_etb(self,p,q):
        candidates=[]
        for pp in self.players.values():
            for x in pp.battlefield:
                if x.uid==q.uid:continue
                d=CARDDEF.get(x.name)
                if d and (d.is_artifact or d.is_enchantment):candidates.append((pp,x))
        if not candidates:return
        # preferentially self-exile a reanimation aura if setting a combo; otherwise strongest enemy engine
        own=[z for z in candidates if z[0].name==p.name and z[1].name in {'Animate Dead','Dance of the Dead','Necromancy'}]
        if own:target=own[0]
        else:
            enemy=[z for z in candidates if z[0].name!=p.name]
            target=max(enemy,key=lambda z:self.perm_threat(z[1]),default=None)
        if target:
            pp,x=target; uid=x.uid
            self.leave_battlefield(pp,x,'exile','Leonin Relic-Warder ETB')
            q.metadata['exiled_uid']=uid

    def felidar_etb(self,p,q):
        candidates=[t for t in p.battlefield if t.uid!=q.uid]
        if candidates:self.blink_own_permanent(p,max(candidates,key=self.perm_threat),'Felidar Guardian ETB')

    def blink_own_permanent(self,p,target,reason):
        if target not in p.battlefield:return None
        uid=target.uid
        self.leave_battlefield(p,target,'exile',reason+' exile')
        if target.token:return None
        owner=self.players[target.owner]
        card=next((c for c in owner.exile if c.uid==uid),None)
        if not card:return None
        owner.exile.remove(card)
        return self._put_card_bf(owner,card,reason+' return')

    def reanimate_aura_etb(self,p,aura):
        creatures=[c for c in p.graveyard if c.d.is_creature]
        if not creatures:return
        c=max(creatures,key=lambda z:self.ream_card_score(z.d.name) if p.name=='Reaminatour' else z.d.mv)
        p.graveyard.remove(c)
        copy=None
        if c.d.name=='Body Double':
            targets=[x for x in p.graveyard if x.d.is_creature]
            if targets:copy=max(targets,key=lambda z:self.ream_copy_score(z.d.name)).d.name
        aura.attached_to=c.uid
        q=self._put_card_bf(p,c,f'{aura.name} reanimation',copy_of=copy)
        if q.name=='Karmic Guide' and aura.name in {'Animate Dead','Dance of the Dead','Necromancy'}:
            self.log('aura_illegal_attach',p.name,aura.name,f'{q.name} has protection from black; {aura.name} cannot remain attached and goes to graveyard')
            aura.attached_to=None
            if aura in p.battlefield:self.leave_battlefield(p,aura,'graveyard','state-based Aura attachment illegal')
            return
        if aura not in p.battlefield or q not in p.battlefield:return
        aura.attached_to=q.uid;q.metadata['reanimated_by']=aura.uid
        self.log('attach',p.name,aura.name,f'{aura.name} attached to {q.name}',target_uid=q.uid)

    def _put_card_bf(self,p,c,reason,copy_of=None,x_value=0):
        if c.d.name=='Vesuva' and copy_of is None:
            copy_of=self.vesuva_copy_choice(p,c)
        bp,bt=base_stats(copy_of or c.d.name,CARDDEF.get(copy_of or c.d.name,c.d))
        if (CARDDEF.get(copy_of or c.d.name,c.d).is_creature) and (copy_of or c.d.name) not in PT:self.stat_fallback.add(copy_of or c.d.name)
        physical_owner=self.card_owners.get(c.uid,p.name)
        q=Perm(c.uid,c.d.name,physical_owner,p.name,False,True,{},None,copy_of,False,bp,bt,set(KEYWORDS.get(copy_of or c.d.name,set())),self.turn_number)
        if (copy_of or c.d.name)=='Dark Depths':q.counters['ice']=10
        if c.d.is_land and not self.perm(p,'Spelunking'):
            q.tapped=bool(c.d.name=='Vesuva' and copy_of) or enters_tapped(c.d.name,p)
        if c.d.name in {'Charcoal Diamond','Marble Diamond'}:q.tapped=True
        p.battlefield.append(q);self.mark_appearance(c.d.name,realized=True)
        p.land_play_limit=self.max_land_plays(p)
        self.log('etb',p.name,c.d.name,f'{c.d.name} entered battlefield: {reason}'+(f' copying {copy_of}' if copy_of else ''),uid=c.uid,copy_of=copy_of)
        # Dispatch copied characteristics on the real battlefield object.
        # A synthetic Perm breaks delayed callbacks and zone-change identity.
        self.on_etb(p,q,x_value=x_value)
        return q

    def put_grave_creature_bf(self,p,c,reason):
        if c not in p.graveyard:return None
        p.graveyard.remove(c);return self._put_card_bf(p,c,reason)

    def reanimate_best_creature(self,p,reason,any_grave=False):
        pools=[]
        for pp in self.players.values() if any_grave else [p]:
            for c in pp.graveyard:
                if c.d.is_creature:pools.append((pp,c))
        if not pools:return
        pp,c=max(pools,key=lambda z:self.ream_card_score(z[1].d.name) if p.name=='Reaminatour' else z[1].d.mv)
        pp.graveyard.remove(c);self._put_card_bf(p,c,reason)

    def sun_titan_trigger(self,p,reason):
        targets=[c for c in p.graveyard if c.d.mv<=3 and c.d.is_permanent]
        if not targets:return
        c=max(targets,key=lambda z:self.ream_card_score(z.d.name) if p.name=='Reaminatour' else z.d.mv)
        p.graveyard.remove(c);self._put_card_bf(p,c,f'Sun Titan {reason}')

    def scry(self,p,n,reason):
        if not p.library:return
        seen=p.library[-n:]
        for c in seen:
            if p.name=='Reaminatour':self.mark_appearance(c.d.name)
        # Ream surveil/scry: keep best on top; scry bottoms junk but doesn't grave
        best=max(seen,key=lambda c:self.ream_card_score(c.d.name) if p.name=='Reaminatour' else self.generic_card_score(p,c.d.name))
        # move best to top, randomize others beneath deterministically
        p.library.remove(best);p.library.append(best)
        self.log('scry',p.name,best.d.name,f'{reason}: inspected {", ".join(c.d.name for c in seen)}; kept {best.d.name} on top')

    def aminatou_surveil(self,p):
        n=min(2,len(p.library));seen=p.library[-n:]
        for c in seen:self.mark_appearance(c.d.name)
        # Choose one highest-value card to keep on top; bin sufficiently low-value other card.
        ranked=sorted(seen,key=lambda c:self.ream_card_score(c.d.name),reverse=True)
        keep=ranked[0] if ranked else None
        for c in list(seen):
            if c is keep:continue
            # aggressively bin recursion targets/combo pieces or junk if graveyard useful
            score=self.ream_card_score(c.d.name)
            if c.d.is_creature or c.d.is_enchantment or score<4:
                p.library.remove(c);p.graveyard.append(c);self.log('surveil_bin',p.name,c.d.name,'Aminatou surveil → graveyard',uid=c.uid)
        if keep and keep in p.library:
            p.library.remove(keep);p.library.append(keep);self.log('surveil_keep',p.name,keep.d.name,'Aminatou surveil kept on top',uid=keep.uid)

    def search_to_zone(self,p,name,dst,reason,reveal=False):
        c=next((c for c in p.library if c.d.name==name),None)
        if not c:return None
        p.library.remove(c);getattr(p,dst).append(c);self.mark_appearance(c.d.name)
        visibility='public' if reveal or dst in {'battlefield','graveyard','exile','command'} else None
        self.log('tutor',p.name,c.d.name,f'{reason}: library → {dst}',uid=c.uid,destination=dst,visibility=visibility)
        self.rng.shuffle(p.library);self.log('shuffle',p.name,None,f'Shuffle after {reason}')
        return c

    def tutor_top(self,p,name,reason):
        c=next((c for c in p.library if c.d.name==name),None)
        if not c:return None
        visibility='public' if reason=='Enlightened Tutor' else None
        p.library.remove(c);p.library.append(c);self.mark_appearance(name);self.log('tutor_top',p.name,name,f'{reason}: put {name} on top',uid=c.uid,visibility=visibility)
        return c

    def request_ream_grave_target(self,p):
        desired=['Sun Titan','Body Double','Leonin Relic-Warder','Karmic Guide','Reveillark','Felidar Guardian','Grim Guardian','Vesperlark']
        for n in desired:
            if any(c.d.name==n for c in p.library):return n
        return self.request_library_card(p)

    def request_ream_tutor(self,p,filter_kind=None,mv=None):
        names=[c.d.name for c in p.library if (mv is None or c.d.mv==mv)]
        if filter_kind=='aura':names=[n for n in names if 'Aura' in CARDDEF[n].type_line or n in {'Animate Dead','Dance of the Dead','Necromancy','Fallen Ideal','Changing Loyalty'}]
        if filter_kind=='enchant_art':names=[n for n in names if CARDDEF[n].is_enchantment or CARDDEF[n].is_artifact]
        return max(names,key=self.ream_card_score,default=None)

    def request_library_card(self,p):
        if p.name=='Reaminatour':return max((c.d.name for c in p.library),key=self.ream_card_score,default=None)
        return max((c.d.name for c in p.library),key=lambda n:self.generic_card_score(p,n),default=None)

    def cruelty_read_ahead_choice(self,p,q):
        pools=[c for pp in self.players.values() for c in pp.graveyard if c.d.is_creature]
        return 3 if any(self.ream_card_score(c.d.name)>=14 for c in pools) else 2

    def cruelty_discard_choice(self,p):
        opponents=[op for op in self.opponents(p) if any(c.d.is_creature or c.d.is_planeswalker for c in op.hand)]
        if not opponents:return None
        opponent=max(opponents,key=lambda op:max(c.d.mv for c in op.hand if c.d.is_creature or c.d.is_planeswalker))
        card=max((c for c in opponent.hand if c.d.is_creature or c.d.is_planeswalker),key=lambda c:c.d.mv)
        return opponent,card

    def cruelty_reanimation_target(self,p):
        pools=[]
        for owner in self.players.values():
            pools.extend((owner,c) for c in owner.graveyard if c.d.is_creature)
        return max(pools,key=lambda row:self.ream_card_score(row[1].d.name) if p.name=='Reaminatour' else row[1].d.mv,default=None)

    def ream_copy_score(self,name):
        return {'Leonin Relic-Warder':20,'Sun Titan':18,'Karmic Guide':17,'Reveillark':16,'Felidar Guardian':16,'Vesperlark':10}.get(name,self.ream_card_score(name))

    def ream_card_score(self,name):
        p=self.players.get('Reaminatour')
        base={
            'Parallax Wave':22,'Felidar Guardian':20,'Grim Guardian':20,'Animate Dead':19,'Dance of the Dead':18,'Necromancy':18,'Body Double':18,'Leonin Relic-Warder':18,
            'Replenish':19,'Gifts Ungiven':18,'Starfield of Nyx':17,'Sun Titan':17,'Karmic Guide':16,'Reveillark':16,'Viscera Seer':15,'Fanatical Devotion':14,'Changing Loyalty':14,
            'Vampiric Tutor':19,'Enlightened Tutor':18,'Dimir House Guard':17,'Gravebreaker Lamia':15,'Invasion of Theros':15,'The Cruelty of Gix':15,
            'The Meathook Massacre':15,'Doomwake Giant':13,'Ghostly Dancers':13,'Entity Tracker':12,"Victor, Valgavoth's Seneschal":12,'Funeral Room // Awakening Hall':16,
            'Sol Ring':15,'Arcane Signet':11,'Talisman of Dominance':10,'Talisman of Hierarchy':10,'Talisman of Progress':10,'Smothering Tithe':13,'Rhystic Study':13,'Mystic Remora':12,
            'Swan Song':12,'Fierce Guardianship':13,'Remand':10,'Touch the Spirit Realm':13,'Loran of the Third Path':9,'Gleaming Splendor':8,'Chthonian Nightmare':12,'Vesperlark':12,
        }.get(name,6)
        if p:
            bf={q.name for q in p.battlefield}; gy={c.d.name for c in p.graveyard}; hand={c.d.name for c in p.hand}
            if name=='Parallax Wave' and ('Felidar Guardian' in hand|bf or 'Starfield of Nyx' in bf|hand):base+=8
            if name=='Felidar Guardian' and 'Parallax Wave' in bf|hand:base+=8
            if name=='Grim Guardian' and ('Parallax Wave' in bf or any(x in bf for x in ['Animate Dead','Dance of the Dead','Necromancy'])):base+=7
            if name in {'Animate Dead','Dance of the Dead','Necromancy'} and gy & {'Body Double','Leonin Relic-Warder','Sun Titan','Karmic Guide','Felidar Guardian'}:base+=6
            if name=='Replenish' and sum(c.d.is_enchantment for c in p.graveyard)>=3:base+=8
        return base

    def generic_card_score(self,p,name):
        d=CARDDEF.get(name)
        if not d:return 0
        score=d.mv
        if name in MANA_ROCKS or name in MANA_DORKS:score+=6
        if name==COMMANDERS[p.name]:score+=7
        if any(k in d.text.lower() for k in ['draw','search your library','destroy target','exile target']):score+=4
        return score

    def search_basic_to_battlefield(self,p,reason):
        c=next((c for c in p.library if c.d.type_line.startswith('Basic Land')),None)
        if not c:return
        p.library.remove(c);self._put_card_bf(p,c,reason);self.rng.shuffle(p.library)

    def look_land_to_bf(self,p,n,reason):
        seen=p.library[-n:]; land=next((c for c in reversed(seen) if c.d.is_land),None)
        if land:
            p.library.remove(land);self._put_card_bf(p,land,reason)
        # rest bottom in random order
        self.rng.shuffle(p.library)

    def look_land_to_hand_mill(self,p,n,reason):
        seen=[p.library.pop() for _ in range(min(n,len(p.library)))]
        land=next((c for c in seen if c.d.is_land),None)
        if land:seen.remove(land);p.hand.append(land);self.log('reveal_to_hand',p.name,land.d.name,f'{reason} found land')
        for c in seen:p.graveyard.append(c);self.log('mill',p.name,c.d.name,f'{reason} → graveyard')

    def destroy_best_noncreature(self,p,reason,allow_land=False):
        choices=[]
        for op in self.opponents(p):
            for q in op.battlefield:
                d=CARDDEF.get(q.name)
                if not d:continue
                if d.is_artifact or d.is_enchantment or (allow_land and d.is_land):choices.append((op,q))
        if choices:
            op,q=max(choices,key=lambda z:self.perm_threat(z[1]));self.destroy(op,q,reason)

    def perm_threat(self,q):
        d=CARDDEF.get(q.name)
        s=(d.mv if d else 1)+self.power(q)
        if q.name in {'Parallax Wave','Grim Guardian','Starfield of Nyx','Branching Evolution','The Earth Crystal','Unnatural Growth','All Will Be One','Phyrexian Arena','Rhystic Study','Smothering Tithe','Mana Reflection','Rampaging Baloths','Scute Swarm'}:s+=10
        return s

    def best_enemy_creature(self,p):
        choices=[]
        for op in self.opponents(p):
            for q in op.battlefield:
                if self.is_creature_perm(q):choices.append((op,q))
        return max(choices,key=lambda z:self.power(z[1])+self.toughness(z[1]),default=None)

    def strongest_creature(self,p):
        cs=[q for q in p.battlefield if self.is_creature_perm(q)]
        return max(cs,key=self.power,default=None)

    def omo_everything(self,p,source=None):
        lands=[q for q in p.battlefield if is_land_permanent(q)]
        if lands:
            q=min(lands,key=lambda x:x.counters.get('everything',0));q.counters['everything']=1;self.log('everything_counter',p.name,q.name,'Omo puts everything counter on land')
        creatures=[q for q in p.battlefield if self.is_creature_perm(q)]
        if creatures:
            q=creatures[0];q.counters['everything']=1;self.log('everything_counter',p.name,q.name,'Omo puts everything counter on creature')

    def create_boo(self,p):
        boo=self.token(p,'Boo',1,1,{'trample','haste'})
        legends=[q for q in p.battlefield if q.name=='Boo']
        if len(legends)>1:
            keep=self.boo_legend_choice(p,legends)
            for other in list(legends):
                if other is not keep:self.leave_battlefield(p,other,'graveyard','legend rule: Boo')
        return boo

    def boo_legend_choice(self,p,legends):
        return max(legends,key=lambda q:(not q.metadata.get('mutated'),self.power(q)))

    def ozolith_move_target(self,p,ozolith,targets):
        return max(targets,key=self.power,default=None)

    def resolve_ozolith_begin_combat(self,p):
        ozolith=self.perm(p,'The Ozolith')
        if not ozolith or not ozolith.counters:return
        targets=[q for q in p.battlefield if self.is_creature_perm(q)]
        target=self.ozolith_move_target(p,ozolith,targets) if targets else None
        if not target:
            self.log('ozolith_decline',p.name,'The Ozolith','Declined to move stored counters at beginning of combat')
            return
        stored=dict(ozolith.counters);ozolith.counters.clear()
        for kind,count in stored.items():self.add_counters(p,target,kind,count,'The Ozolith beginning-of-combat move')
        self.log('ozolith_move',p.name,'The Ozolith',f'Moved all counters to {target.name}',target_uid=target.uid,counters=stored)

    def resolve_spell(self,p,c,x_value=0):
        n=c.d.name
        if n in {'Consider'}:
            # surveil 1 then draw
            if p.library:
                top=p.library[-1];self.mark_appearance(top.d.name)
                if p.name=='Reaminatour' and self.ream_card_score(top.d.name)<8:
                    p.library.pop();p.graveyard.append(top);self.log('surveil_bin',p.name,top.d.name,'Consider surveil')
            self.draw(p,1,n)
        elif n=='Opt':self.scry(p,1,'Opt');self.draw(p,1,'Opt')
        elif n=='Brainstorm':
            self.draw(p,3,'Brainstorm')
            # put two lowest-value cards back
            if len(p.hand)>=2:
                key=(lambda z:self.ream_card_score(z.d.name)) if p.name=='Reaminatour' else (lambda z:self.generic_card_score(p,z.d.name))
                back=sorted(p.hand,key=key)[:2]
                for z in back:p.hand.remove(z);p.library.append(z);self.log('put_on_top',p.name,z.d.name,'Brainstorm putback')
        elif n=='Enlightened Tutor':
            target=self.request_ream_tutor(p,filter_kind='enchant_art') if p.name=='Reaminatour' else self.request_library_card(p)
            if target:self.tutor_top(p,target,'Enlightened Tutor')
        elif n=='Vampiric Tutor':
            target=self.request_ream_tutor(p) if p.name=='Reaminatour' else self.request_library_card(p)
            if target:self.tutor_top(p,target,'Vampiric Tutor');self.lose_life(p,2,'Vampiric Tutor')
        elif n=='Gifts Ungiven' and p.name=='Reaminatour':self.resolve_gifts(p)
        elif n=='Replenish' and p.name=='Reaminatour':
            ens=list(c2 for c2 in p.graveyard if c2.d.is_enchantment)
            for z in ens:
                p.graveyard.remove(z);self._put_card_bf(p,z,'Replenish')
        elif n in {'Nature\'s Lore','Three Visits','Farseek','Rampant Growth','Cultivate','Kodama\'s Reach'}:
            count=2 if n in {'Cultivate','Kodama\'s Reach'} else 1
            for i in range(count):
                basics=[z for z in p.library if z.d.is_land and any(t in z.d.type_line for t in ['Forest','Plains','Island','Swamp','Mountain'])]
                if not basics:break
                z=basics[0];p.library.remove(z)
                if i==0 or count==1:self._put_card_bf(p,z,n)
                else:p.hand.append(z);self.log('tutor',p.name,z.d.name,f'{n}: revealed land to hand',visibility='public')
            self.rng.shuffle(p.library)
        elif n=='Rishkar\'s Expertise':
            greatest=max([self.power(q) for q in p.battlefield]+[0]);self.draw(p,min(greatest,30),'Rishkar\'s Expertise')
            eligible=[z for z in p.hand if not z.d.is_land and z.d.mv<=5]
            if eligible:
                z=max(eligible,key=lambda z:self.generic_card_score(p,z.d.name));self.cast(p,z,free=True)
        elif n=="Chandra's Ignition":
            q=self.strongest_creature(p)
            if q:
                dmg=self.power(q);self.log('mass_damage',p.name,n,f'{q.name} deals {dmg} to each other creature and opponent')
                for op in self.opponents(p):self.lose_life(op,dmg,"Chandra's Ignition")
                for pp in self.players.values():
                    for t in list(pp.battlefield):
                        if t.uid==q.uid:continue
                        d=CARDDEF.get(t.name)
                        if self.is_creature_perm(t) and self.toughness(t)<=dmg and 'indestructible' not in t.keywords:self.destroy(pp,t,"Chandra's Ignition")
        elif n in {'Fling','Kazuul\'s Fury // Kazuul\'s Cliffs'}:
            q=self.strongest_creature(p)
            if q:
                dmg=self.power(q);self.leave_battlefield(p,q,'graveyard',n+' sacrifice');op=min(self.opponents(p),key=lambda x:x.life,default=None)
                if op:self.lose_life(op,dmg,n)
        elif n in {'Bulk Up','Unleash Fury'}:
            q=self.strongest_creature(p)
            if q:
                # "Double its power" creates a fixed +X/+0 modifier where X is
                # the creature's power as the spell resolves. Counters added
                # later in the turn are not doubled retroactively.
                bonus=self.effective_power(q)
                q.metadata['fixed_power_bonus']=q.metadata.get('fixed_power_bonus',0)+bonus
                self.log('combat_buff',p.name,n,f'{n} gives {q.name} +{bonus}/+0 until end of turn')
        elif n=='Invigorating Surge':
            q=self.strongest_creature(p)
            if q:
                self.add_counters(p,q,'+1/+1',1,'Invigorating Surge first counter')
                cur=q.counters.get('+1/+1',0)
                if cur:self.add_counters(p,q,'+1/+1',cur,'Invigorating Surge doubles counters')
        elif n=='Ram Through':
            q=self.strongest_creature(p); target=self.best_enemy_creature(p)
            if q and target:
                op,t=target;dmg=self.power(q);lethal=self.toughness(t)
                if dmg>=lethal:self.destroy(op,t,'Ram Through lethal damage')
                if 'trample' in q.keywords and dmg>lethal:self.lose_life(op,dmg-lethal,'Ram Through excess trample damage')
                self.log('fight_damage',p.name,n,f'{q.name} deals {dmg} to {t.name}',target=t.name,damage=dmg)
        elif n=='Return of the Wildspeaker':
            greatest=max([self.power(q) for q in p.battlefield if CARDDEF.get(q.name) and CARDDEF[q.name].is_creature and 'Human' not in CARDDEF[q.name].type_line]+[0])
            if len(p.hand)<=5:self.draw(p,min(greatest,20),n)
            else:
                for q in p.battlefield:
                    if CARDDEF.get(q.name) and CARDDEF[q.name].is_creature and 'Human' not in CARDDEF[q.name].type_line:q.metadata['wildspeaker_bonus']=3
                self.log('combat_buff',p.name,n,'Non-Human creatures get +3/+3 until end of turn')
        elif n=='Blasphemous Act':
            for pp in self.players.values():
                for q in list(pp.battlefield):
                    d=CARDDEF.get(q.name)
                    if self.is_creature_perm(q) and self.toughness(q)<=13 and 'indestructible' not in q.keywords:self.destroy(pp,q,'Blasphemous Act')
        elif n in {'Beast Within','Chaos Warp','Pongify','Curse of the Swine','Breathe Your Last','Utter End','Hero\'s Downfall','Murder','Valorous Stance','Prayer of Binding','Grasp of Fate','Darksteel Mutation'}:
            self.resolve_removal_spell(p,n,x_value)
        elif n=='March from Velis Vel':
            creature=self.strongest_creature(p)
            if creature:
                # Gate is the maximally populated nonbasic type in Omo once everything counters exist.
                lands=[q for q in p.battlefield if CARDDEF.get(q.name) and CARDDEF[q.name].is_land and (q.counters.get('everything',0)>0 or 'Gate' in CARDDEF[q.name].type_line.split(' // ')[0])]
                for land in lands:
                    land.metadata['march_copy']=creature.name;land.metadata['march_power']=self.power(creature);land.metadata['march_toughness']=self.toughness(creature);land.metadata['march_keywords']=list(creature.keywords);land.metadata['march_animated']=True
                self.log('land_copy_effect',p.name,n,f'{len(lands)} Gate-type lands become copies of {creature.name} with haste until end of turn',count=len(lands),copy=creature.name)
        elif n in {'Harmonize','Urban Evolution','Eureka Moment','Drown in Dreams'}:
            draws={'Harmonize':3,'Urban Evolution':3,'Eureka Moment':1,'Drown in Dreams':max(1,x_value)}[n]
            self.draw(p,min(draws,20),n)
        elif n=='Finale of Revelation':
            if c in p.graveyard:p.graveyard.remove(c)
            if x_value>=10:
                p.library.extend(p.graveyard);p.graveyard.clear();self.rng.shuffle(p.library)
                p.dungeon['no_max_hand']=True
            self.draw(p,min(max(0,x_value),40),n)
            if x_value>=10:
                for land in [q for q in p.battlefield if CARDDEF.get(q.name) and CARDDEF[q.name].is_land and q.tapped][:5]:land.tapped=False
            p.exile.append(c);self.log('exile',p.name,n,'Finale of Revelation exiles itself after resolving')
        elif n=="Rishkar's Expertise":
            greatest=max((self.effective_power(q) for q in p.battlefield if self.is_creature_perm(q)),default=0)
            self.draw(p,min(greatest,40),n)
            legal=[card for card in p.hand if not card.d.is_land and card.d.mv<=5]
            if legal:
                choice=max(legal,key=lambda card:self.generic_card_score(p,card.d.name))
                self.cast(p,choice,free=True,x_value=0)
        elif n=='Growth Spiral':
            self.draw(p,1,n);self.extra_land_from_hand(p,n)
        elif n=='Hour of Promise':
            for _ in range(2):
                lands=[z for z in p.library if z.d.is_land]
                if lands:
                    z=max(lands,key=lambda z:self.generic_card_score(p,z.d.name));p.library.remove(z);land=self._put_card_bf(p,z,n);land.tapped=True
            self.rng.shuffle(p.library)
            if sum(1 for land in p.battlefield if land_has_type(land,'Desert',p))>=3:
                self.token(p,'Zombie',2,2);self.token(p,'Zombie',2,2)
        elif n=='Sylvan Scrying':
            lands=[z for z in p.library if z.d.is_land]
            if lands:
                z=max(lands,key=lambda z:self.generic_card_score(p,z.d.name));p.library.remove(z);p.hand.append(z);self.log('tutor',p.name,z.d.name,'Sylvan Scrying revealed land',visibility='public')
            self.rng.shuffle(p.library);self.log('shuffle',p.name,None,'Shuffle after Sylvan Scrying')
        elif n=='Crop Rotation':
            land=next((q for q in p.battlefield if CARDDEF.get(q.name) and CARDDEF[q.name].is_land),None)
            if land:self.leave_battlefield(p,land,'graveyard','Crop Rotation cost')
            lands=[z for z in p.library if z.d.is_land]
            if lands:
                z=max(lands,key=lambda z:self.generic_card_score(p,z.d.name));p.library.remove(z);self._put_card_bf(p,z,n)
        elif n in {'Exsanguinate','Debt to the Deathless'}:
            # Debt scales at twice X, while Exsanguinate scales at X.  Snapshot
            # the affected opponents before applying any losses because an
            # opponent can leave the game during resolution; the caster still
            # gains the life lost by every opponent affected by the spell.
            loss=max(0,x_value)*(2 if n=='Debt to the Deathless' else 1)
            targets=list(self.opponents(p))
            total_lost=0
            for op in targets:
                before=op.life
                self.lose_life(op,loss,n)
                total_lost+=max(0,before-op.life)
            self.gain_life(p,total_lost,n)
        elif n=='Death Grasp':
            # Single-target damage plus one life-gain event. ManualGame overrides
            # target selection so official play never delegates this choice.
            dmg=max(0,x_value)
            target=self.death_grasp_target(p)
            if target:
                kind,owner,obj=target
                if kind=='player':
                    self.lose_life(obj,dmg,n)
                elif kind=='planeswalker':
                    obj.counters['loyalty']=obj.counters.get('loyalty',0)-dmg
                    self.log('damage',p.name,n,f'Death Grasp deals {dmg} damage to {obj.name}',target=obj.name,damage=dmg)
                    if obj.counters['loyalty']<=0 and obj in owner.battlefield:
                        self.leave_battlefield(owner,obj,'graveyard','Death Grasp reduced loyalty to zero')
                else:
                    self.log('damage',p.name,n,f'Death Grasp deals {dmg} damage to {obj.name}',target=obj.name,damage=dmg)
                    if dmg>=self.effective_toughness(obj) and obj in owner.battlefield:
                        self.destroy(owner,obj,'Death Grasp lethal damage')
                self.gain_life(p,dmg,n)
        elif n=='Diabolic Tutor':
            target=self.request_library_card(p)
            if target:self.search_to_zone(p,target,'hand',n)
        elif n=='Zombify':self.reanimate_best_creature(p,'Zombify')
        elif n=='Akroma\'s Vengeance':
            for pp in self.players.values():
                for q in list(pp.battlefield):
                    d=CARDDEF.get(q.name)
                    if (self.is_creature_perm(q) or (d and (d.is_artifact or d.is_enchantment))) and 'indestructible' not in q.keywords:self.destroy(pp,q,n)
        elif n=='Replication Technique':
            # copy two best own permanents (demonstrate if enabled)
            best=sorted([q for q in p.battlefield if not (CARDDEF.get(q.name) and CARDDEF[q.name].is_land)],key=self.perm_threat,reverse=True)[:2]
            for q in best:self.token(p,q.name,self.power(q),self.toughness(q),q.keywords,counters=q.counters)
        elif n=='Aggressive Biomancy':
            q=self.strongest_creature(p)
            if q:
                for _ in range(min(x_value,6)):self.token(p,q.name,self.power(q),self.toughness(q),q.keywords,counters=q.counters)
        elif n=='Whelming Wave':
            protected_types={'Kraken','Leviathan','Octopus','Serpent'}
            for pp in self.players.values():
                for q in list(pp.battlefield):
                    d=CARDDEF.get(q.name)
                    printed_types=set((d.type_line if d else '').replace('—',' ').split())
                    has_all_types=bool(not is_land_permanent(q) and q.counters.get('everything',0)>0 and omo_everything_active(pp))
                    if self.is_creature_perm(q) and not (has_all_types or protected_types & printed_types):
                        self.bounce(pp,q,n)
        elif n=='Evacuation':self.resolve_evacuation(p)
        elif n=='Restart Sequence':
            # simplified board wipe creatures
            for pp in self.players.values():
                for q in list(pp.battlefield):
                    d=CARDDEF.get(q.name)
                    if self.is_creature_perm(q) and 'indestructible' not in q.keywords:self.destroy(pp,q,n)
        else:
            # Generic supported textual effects where unambiguous
            low=c.d.text.lower()
            m=re.search(r'draw (?:a|one) card',low)
            if m:self.draw(p,1,n)
            elif 'draw two cards' in low:self.draw(p,2,n)
            elif 'draw three cards' in low:self.draw(p,3,n)
            # Record if an unhandled nontrivial spell was materially cast.
            if c.d.text and c.d.text!='No printed Oracle text.' and any(k in low for k in ['target','search','create','destroy','exile','return','counter','damage','draw','gain']):
                self.material_unsupported.append({'game':self.game_no,'seq':self.seq,'card':n,'text':c.d.text,'context':'spell'})
                self.log('unsupported_audit',p.name,n,'Nontrivial spell text had no dedicated exact handler; generic subset only')

    def resolve_evacuation(self,p):
        creatures=[(owner,q) for owner in self.players.values() for q in list(owner.battlefield) if self.is_creature_perm(q)]
        for owner,q in creatures:
            if q in owner.battlefield:self.bounce(owner,q,'Evacuation')
        for owner in self.players.values():owner.dungeon.pop('infinite_spirits_turn',None)
        self.log('global_bounce',p.name,'Evacuation',f'Returned {len(creatures)} creatures; creature tokens ceased to exist')

    def bounce(self,p,q,reason):
        p.battlefield.remove(q)
        if q.token:self.log('token_ceases',p.name,q.name,f'{reason}: token bounced then ceases');return
        c=CardObj(q.uid,CARDDEF[q.name])
        if q.uid==p.dungeon.get('commander_uid'):
            p.commander=c; self.log('commander_zone',p.name,q.name,f'{reason}: commander moved to command zone instead of hand')
        else:
            p.hand.append(c);self.log('bounce',p.name,q.name,f'{reason}: battlefield → hand')
        self.on_ltb(p,q,died=False)

    def death_grasp_targets(self,p):
        """Return target shapes represented by this pod ledger."""
        targets=[('player',pp,pp) for pp in self.players.values() if not pp.eliminated]
        for owner in self.players.values():
            for permanent in owner.battlefield:
                card=CARDDEF.get(permanent.name)
                if self.is_creature_perm(permanent):
                    targets.append(('creature',owner,permanent))
                elif card and card.is_planeswalker:
                    targets.append(('planeswalker',owner,permanent))
        return targets

    def death_grasp_target(self,p):
        opponents=[row for row in self.death_grasp_targets(p) if row[0]=='player' and row[2].name!=p.name]
        return min(opponents,key=lambda row:row[2].life,default=None)

    def resolve_removal_spell(self,p,n,x=0):
        target=self.best_enemy_permanent_for_removal(p,n)
        if not target:return
        op,q=target
        hi=self.card_in_hand(op,'Heroic Intervention')
        if hi and self.can_pay(op,hi.d) and self.use_heroic_intervention(op,n,q):
            self.pay(op,hi.d);op.hand.remove(hi);op.graveyard.append(hi);self.mark_appearance(hi.d.name,cast=True,realized=True)
            for z in op.battlefield:z.metadata['heroic_protected_turn']=self.turn_number
            self.log('reactive_protection',op.name,'Heroic Intervention',f'Heroic Intervention protects permanents from {n}',target=q.name)
            return
        if n=='Darksteel Mutation':
            q.metadata['darksteel_original']={
                'base_power':q.base_power,
                'base_toughness':q.base_toughness,
                'keywords':sorted(q.keywords),
            }
            q.base_power=0;q.base_toughness=1;q.keywords.clear();q.metadata['mutated']=True;self.log('aura_disable',p.name,n,f'Darksteel Mutation disables {q.name}',target=q.name);return
        if n in {'Utter End','Prayer of Binding','Grasp of Fate','Curse of the Swine','Pongify'}:
            self.exile_perm(op,q,n)
            if n=='Pongify':self.token(op,'Ape',3,3)
            if n=='Curse of the Swine':self.token(op,'Boar',2,2)
        elif n=='Chaos Warp':
            self.leave_battlefield(op,q,'library',n)
            self.rng.shuffle(op.library)
            if op.library:
                top=op.library.pop()
                if top.d.is_permanent:self._put_card_bf(op,top,'Chaos Warp reveal')
                else:op.library.append(top);self.rng.shuffle(op.library)
        elif n=='Beast Within':
            self.destroy(op,q,n);self.token(op,'Beast',3,3)
        else:self.destroy(op,q,n)

    def use_heroic_intervention(self,p,removal_name,target):
        return True

    def best_enemy_permanent_for_removal(self,p,n):
        choices=[]
        for op in self.opponents(p):
            for q in op.battlefield:
                d=CARDDEF.get(q.name)
                if not d:continue
                legal=True
                if n=='Utter End':legal=not d.is_land
                if n in {'Pongify','Breathe Your Last','Murder'}:legal=self.is_creature_perm(q)
                if n=='Hero\'s Downfall':legal=self.is_creature_perm(q) or d.is_planeswalker
                if n=='Valorous Stance':legal=self.is_creature_perm(q) and self.toughness(q)>=4
                if q.name=='Elenda, Saint of Dusk' and CARDDEF.get(n) and CARDDEF[n].is_instant:legal=False
                if q.metadata.get('heroic_protected_turn')==self.turn_number or self.has_hexproof(q):legal=False
                if legal:choices.append((op,q))
        return max(choices,key=lambda z:self.perm_threat(z[1]),default=None)

    def resolve_gifts(self,p):
        # Exact legal <=4 search use: when BD + LRW are available and an aura/sensor route exists, search exactly two to force both to graveyard.
        libnames={c.d.name for c in p.library}
        if {'Body Double','Leonin Relic-Warder'}<=libnames:
            pile=['Body Double','Leonin Relic-Warder']
        else:
            ranked=sorted((c for c in p.library),key=lambda c:self.ream_card_score(c.d.name),reverse=True)
            pile=[c.d.name for c in ranked[:4]]
        if len(pile)<=2:
            for n in pile:self.search_to_zone_no_shuffle(p,n,'graveyard','Gifts forced <=2')
        else:
            # opponent chooses two highest-value cards to graveyard (worst for Ream usually), remaining hand
            cards=[next(c for c in p.library if c.d.name==n) for n in pile]
            cards.sort(key=lambda c:self.ream_card_score(c.d.name),reverse=True)
            grave=cards[:2];hand=cards[2:]
            for c in grave:p.library.remove(c);p.graveyard.append(c);self.mark_appearance(c.d.name);self.log('gifts_split',p.name,c.d.name,'Opponent chooses Gifts card → graveyard')
            for c in hand:p.library.remove(c);p.hand.append(c);self.mark_appearance(c.d.name);self.log('gifts_split',p.name,c.d.name,'Gifts remainder → hand')
        self.rng.shuffle(p.library);self.log('shuffle',p.name,None,'Shuffle after Gifts Ungiven')

    def search_to_zone_no_shuffle(self,p,name,dst,reason):
        c=next((c for c in p.library if c.d.name==name),None)
        if c:
            visibility='public' if dst in {'battlefield','graveyard','exile','command'} else None
            p.library.remove(c);getattr(p,dst).append(c);self.mark_appearance(name);self.log('tutor',p.name,name,f'{reason}: library → {dst}',uid=c.uid,destination=dst,visibility=visibility)

    def extra_land_from_hand(self,p,reason):
        c=self.land_drop_choice(p)
        if c:
            # effect land does not consume normal land play
            old=p.land_plays_used;p.land_plays_used=max(0,p.land_plays_used-1);self.play_land(p,c);p.land_plays_used=old;self.log('extra_land',p.name,c.d.name,reason)

    def upkeep(self,p):
        self.phase='upkeep';p.cards_drawn_this_turn=0;p.spells_cast_this_turn=0;p.enchantments_entered_this_turn=0;p.life_gained_this_turn=0;p.counters_placed_this_turn=0;p.miracle_card_uid=None
        self.resolve_arcane_denial_triggers()
        for q in p.battlefield:
            if q.name=="Victor, Valgavoth's Seneschal":
                q.metadata['eerie_count_turn_number']=self.turn_number;q.metadata['eerie_count_turn']=0
        sf=self.perm(p,'Starfield of Nyx')
        if sf:
            ens=[c for c in p.graveyard if c.d.is_enchantment]
            if ens:
                c=max(ens,key=lambda z:self.ream_card_score(z.d.name) if p.name=='Reaminatour' else z.d.mv);p.graveyard.remove(c);self._put_card_bf(p,c,'Starfield of Nyx upkeep')
        if self.perm(p,'Aminatou, Veil Piercer'):self.aminatou_surveil(p)
        if self.perm(p,'Phyrexian Arena'):
            self.lose_life(p,1,'Phyrexian Arena upkeep');self.draw(p,1,'Phyrexian Arena')
        if self.perm(p,'Indulgent Tormentor'):
            opp=min(self.opponents(p),key=lambda x:x.life,default=None)
            if opp and opp.life>8:self.lose_life(opp,3,'Indulgent Tormentor choice')
            else:self.draw(p,1,'Indulgent Tormentor upkeep')
        # Forgotten Ancient moves accumulated counters to the best attacker.
        fa=self.perm(p,'Forgotten Ancient')
        if fa and fa.counters.get('+1/+1',0)>0:
            candidates=[q for q in p.battlefield if CARDDEF.get(q.name) and CARDDEF[q.name].is_creature and q.uid!=fa.uid]
            if candidates:
                n=fa.counters.pop('+1/+1');target=max(candidates,key=self.power);self.add_counters(p,target,'+1/+1',n,'Forgotten Ancient upkeep transfer')
        if self.perm(p,'Phyrexian Arena'):
            self.draw(p,1,'Phyrexian Arena upkeep');self.lose_life(p,1,'Phyrexian Arena')
        ss=self.perm(p,"Sigarda's Splendor")
        if ss:
            last=ss.metadata.get('noted_life',p.life)
            if p.life>=last:self.draw(p,1,"Sigarda's Splendor upkeep")
            ss.metadata['noted_life']=p.life
        if self.perm(p,'Starfield of Nyx'):
            ens=[c for c in p.graveyard if c.d.is_enchantment]
            if ens:
                c=max(ens,key=lambda c:self.ream_card_score(c.d.name));p.graveyard.remove(c);self._put_card_bf(p,c,'Starfield upkeep')
        rem=self.perm(p,'Mystic Remora')
        if rem:
            age=rem.counters.get('age',0)+1;rem.counters['age']=age
            fake=CardDef('Remora upkeep',f'{{{age}}}','', '',1,p.name,age)
            if not self.pay(p,fake):self.leave_battlefield(p,rem,'graveyard','did not pay cumulative upkeep')
        # Maze's End can win once Omo has turned ten differently named lands into Gates.
        if p.name=='Omo':self.try_maze_end(p)

    def try_maze_end(self,p):
        maze=self.perm(p,"Maze's End")
        if not maze or maze.tapped:return False
        # Maze returns as a cost; calculate Gates that remain, then include a printed Gate searchable from library.
        existing=[]
        for q in p.battlefield:
            if q.uid==maze.uid:continue
            d=CARDDEF.get(q.name)
            if d and d.is_land and (('Gate' in d.type_line.split(' // ')[0]) or q.counters.get('everything',0)>0):existing.append(q.name)
        gate_cards=[c for c in p.library if c.d.is_land and 'Gate' in c.d.type_line.split(' // ')[0]]
        projected=set(existing)
        if gate_cards:projected.add(gate_cards[0].d.name)
        if len(projected)<10:return False
        fake=CardDef("Maze's End activation",'{3}','Ability','',1,p.name,3)
        if self.can_pay(p,fake) is None:return False
        self.pay(p,fake);maze.tapped=True
        p.battlefield.remove(maze);p.hand.append(CardObj(maze.uid,CARDDEF[maze.name]));self.log('maze_end_activate',p.name,maze.name,"Pay {3}, tap and return Maze's End to hand")
        if gate_cards:
            c=gate_cards[0];p.library.remove(c);q=self._put_card_bf(p,c,"Maze's End search");q.tapped=enters_tapped(c.d.name,p);q.summoning_sick=False;self.rng.shuffle(p.library);self.log('shuffle',p.name,None,"Shuffle after Maze's End search")
        gates=[]
        for q in p.battlefield:
            d=CARDDEF.get(q.name)
            if d and d.is_land and (('Gate' in d.type_line.split(' // ')[0]) or q.counters.get('everything',0)>0):gates.append(q.name)
        if len(set(gates))>=10:
            self.winner=p.name;self.win_turn=self.turn_number;self.win_reason="Maze's End ten-Gate win";self.log('winner',p.name,"Maze's End",f"Omo wins via Maze's End controlling {len(set(gates))} differently named Gates")
            return True
        return False

    def untap(self,p):
        self.phase='untap'
        for q in p.battlefield:q.tapped=False;q.summoning_sick=False
        self.log('untap',p.name,None,'Untap step')

    def draw_step(self,p):
        self.phase='draw';self.draw(p,1,'draw step')

    def main_phase(self,p,post=False):
        self.phase='postcombat_main' if post else 'precombat_main'
        if not post:self.saga_step(p)
        # Land-play permissions are continuous effects. Recalculate here and
        # after every material action so a Dryad/Azusa cast this turn immediately
        # grants its additional plays (including in the postcombat main phase).
        p.land_play_limit=self.max_land_plays(p)
        if not post:
            while p.land_plays_used<p.land_play_limit:
                c=self.land_drop_choice(p)
                if not c:break
                self.play_land(p,c)
        if not post:
            # cast spells until no attractive cast
            for _ in range(12):
                if p.eliminated or self.winner:break
                action=self.choose_main_action(p)
                if not action:break
                prior_land_limit=p.land_play_limit
                prior_had_land=any(card.d.is_land for card in p.hand)
                kind,c,kwargs=action
                if kind=='cast':
                    if not self.cast(p,c,**kwargs):break
                elif kind=='commander':
                    if not self.commander_cast(p):break
                elif kind=='transmute':self.transmute_house_guard(p,c)
                elif kind=='nightmare':self.activate_nightmare(p)
                elif kind=='escape_uro':self.escape_uro(p,c)
                else:break
                self.check_ream_combo()
                p.land_play_limit=self.max_land_plays(p)
                gained_land_access=(not prior_had_land and any(card.d.is_land for card in p.hand) and p.land_plays_used<p.land_play_limit)
                if p.land_play_limit>prior_land_limit or gained_land_access:
                    while p.land_plays_used<p.land_play_limit:
                        land=self.land_drop_choice(p)
                        if not land:break
                        self.play_land(p,land)
            if p.name=='Minsc & Boo':self.activate_bristly_bill(p)
            self.activate_value_abilities(p)
        else:
            # one additional spell after combat if available and mana
            action=self.choose_main_action(p)
            if action:
                kind,c,kwargs=action
                if kind=='cast':self.cast(p,c,**kwargs)
                elif kind=='nightmare':self.activate_nightmare(p)

    def choose_main_action(self,p):
        if p.name=='Reaminatour':
            dh=self.card_in_hand(p,'Dimir House Guard')
            if dh and self.can_pay(p,CardDef('transmute','{1}{B}{B}','Ability','',1,p.name,3)) and any(c.d.name=='Parallax Wave' for c in p.library):return ('transmute',dh,{})
            if self.perm(p,'Chthonian Nightmare') and p.energy>=1 and any(c.d.is_creature for c in p.graveyard) and any(self.is_creature_perm(q) for q in p.battlefield):
                if max((self.ream_card_score(c.d.name) for c in p.graveyard if c.d.is_creature),default=0)>12:return ('nightmare',None,{})
        if p.name=='Omo':
            uro=next((c for c in p.graveyard if c.d.name=="Uro, Titan of Nature's Wrath"),None)
            others=[c for c in p.graveyard if c.uid!=(uro.uid if uro else None)]
            esc=CardDef('Uro escape','{G}{G}{U}{U}','Ability','',1,p.name,4)
            if uro and len(others)>=5 and self.can_pay(p,esc):return ('escape_uro',uro,{})
        if p.name=='Omo' and self.try_maze_end(p):return None
        if p.commander and self.can_pay(p,p.commander.d,commander=True):
            lands=sum(1 for q in p.battlefield if CARDDEF.get(q.name) and CARDDEF[q.name].is_land)
            if lands>=3:return ('commander',p.commander,{})
        # Proactive interaction is legal in main phase and used against genuinely dangerous engines.
        removal={'Beast Within','Chaos Warp','Pongify','Breathe Your Last','Utter End','Hero\'s Downfall','Murder','Valorous Stance','Prayer of Binding','Grasp of Fate','Darksteel Mutation','Curse of the Swine'}
        enemy_peak=max((self.perm_threat(q) for op in self.opponents(p) for q in op.battlefield),default=0)
        cards=[]
        for c in p.hand:
            if c.d.is_land:continue
            if c.d.is_instant and c.d.name not in {'Consider','Opt','Brainstorm','Enlightened Tutor','Vampiric Tutor','Growth Spiral'}|removal and not (p.name=='Minsc & Boo' and c.d.name in {'Bulk Up','Unleash Fury','Invigorating Surge','Ram Through'}):continue
            if c.d.name in removal and enemy_peak<12:continue
            miracle=(p.name=='Reaminatour' and p.miracle_card_uid==c.uid and c.d.is_enchantment)
            x=0
            if '{X}' in c.d.mana_cost:x=max(1,self.max_x_payable(p,c.d,miracle))
            if self.can_pay(p,c.d,miracle=miracle,x_value=x) is not None:
                score=self.action_score(p,c,miracle,x)
                if c.d.name in removal:score+=max(0,enemy_peak-8)
                cards.append((score,c,{'miracle':miracle,'x_value':x}))
        if not cards:return None
        score,c,kw=max(cards,key=lambda x:x[0])
        if score<3:return None
        return ('cast',c,kw)

    def max_x_payable(self,p,d,miracle=False):
        # brute small
        best=0
        for x in range(0,31):
            if self.can_pay(p,d,miracle=miracle,x_value=x) is not None:best=x
            else:break
        return best

    def action_score(self,p,c,miracle=False,x=0):
        n=c.d.name
        if p.name=='Reaminatour':s=self.ream_card_score(n)
        else:s=self.generic_card_score(p,n)
        if n in MANA_ROCKS or n in MANA_DORKS:s+=8 if self.turn_number<=4 else 1
        if miracle:s+=6
        if c.d.mv>7 and self.turn_number<5:s-=3
        if p.name=='Minsc & Boo':
            s += {'The Earth Crystal':10,'Branching Evolution':10,'Hardened Scales':8,'Rhythm of the Wild':8,'Kalonian Hydra':12,"Chandra's Ignition":15,'Rishkar\'s Expertise':11,'Unnatural Growth':10,'All Will Be One':10,'Bulk Up':9,'Unleash Fury':9,'Invigorating Surge':10,'Ram Through':10,'Return of the Wildspeaker':9}.get(n,0)
        elif p.name=='Omo':
            s += {'Spelunking':10,'Azusa, Lost but Seeking':9,'Dryad of the Ilysian Grove':8,'Tatyova, Benthic Druid':9,'Rampaging Baloths':11,'Scute Swarm':10,'Mana Reflection':10,'Apex Devastator':12,'Hour of Promise':9,'Replication Technique':10}.get(n,0)
        elif p.name=='Elenda':
            s += {'Leyline of Hope':9,'Phyrexian Arena':11,'Dawn of Hope':8,"Ajani's Pridemate":7,'Angel of Vitality':8,'Marauding Blight-Priest':8,'Defiant Bloodlord':9,'Exsanguinate':14,'Debt to the Deathless':15}.get(n,0)
        return s

    def activate_bristly_bill(self,p):
        bill=self.perm(p,'Bristly Bill, Spine Sower')
        if not bill:return False
        creatures=[q for q in p.battlefield if self.is_creature_perm(q) and q.counters.get('+1/+1',0)>0]
        if sum(q.counters.get('+1/+1',0) for q in creatures)<4:return False
        fake=CardDef('Bristly Bill activation','{3}{G}{G}','Ability','',1,p.name,5)
        if self.can_pay(p,fake) is None:return False
        self.pay(p,fake)
        for q in creatures:
            cur=q.counters.get('+1/+1',0);self.add_counters(p,q,'+1/+1',cur,'Bristly Bill doubles counters')
        self.log('activated_ability',p.name,'Bristly Bill, Spine Sower','Double +1/+1 counters on each creature')
        return True

    def transmute_house_guard(self,p,c):
        fake=CardDef('Dimir House Guard transmute','{1}{B}{B}','Ability','',1,p.name,3)
        if not self.pay(p,fake):return
        p.hand.remove(c);p.graveyard.append(c);self.mark_appearance(c.d.name);self.log('transmute',p.name,c.d.name,'Discard Dimir House Guard to transmute for MV 4; not cast/realized')
        target=self.request_ream_tutor(p,mv=4)
        if target:self.search_to_zone(p,target,'hand','Dimir House Guard transmute',reveal=True)

    def activate_nightmare(self,p):
        nm=self.perm(p,'Chthonian Nightmare')
        creatures=[c for c in p.graveyard if c.d.is_creature and c.d.mv<=p.energy]
        sacs=[q for q in p.battlefield if self.is_creature_perm(q) and q.name!='Aminatou, Veil Piercer']
        if not nm or not creatures or not sacs:return
        target=max(creatures,key=lambda c:self.ream_card_score(c.d.name));x=target.d.mv
        if x>p.energy:return
        sac=min(sacs,key=lambda q:self.ream_card_score(q.name));p.energy-=x
        self.leave_battlefield(p,sac,'graveyard','Chthonian Nightmare sacrifice')
        # return Nightmare to hand
        p.battlefield.remove(nm);c=CardObj(nm.uid,CARDDEF[nm.name]);p.hand.append(c);self.log('return_to_hand',p.name,nm.name,'Chthonian Nightmare activation returns itself')
        p.graveyard.remove(target);self._put_card_bf(p,target,'Chthonian Nightmare')

    def combat(self,p):
        self.phase='combat'
        if p.eliminated:return
        # Beginning-of-combat triggers before attacker declaration.
        helm=self.perm(p,'Helm of the Host')
        if helm:
            equipped=self.find_card_obj_on_bf(p,helm.attached_to) if helm.attached_to else None
            if not equipped:
                equipped=self.strongest_creature(p)
                if equipped and self.pay(p,CardDef('Helm equip','{5}','Ability','',1,p.name,5)):
                    helm.attached_to=equipped.uid;self.log('equip',p.name,'Helm of the Host',f'Equip {equipped.name}',target_uid=equipped.uid)
            if equipped:
                tok=self.token(p,equipped.name,self.power(equipped),self.toughness(equipped),set(equipped.keywords)|{'haste'},counters=dict(equipped.counters));tok.copy_of=equipped.name
                self.log('helm_copy',p.name,'Helm of the Host',f'Created nonlegendary hasty copy of {equipped.name}',target=equipped.name)
        if p.name=='Omo' and self.perm(p,'Desert Warfare'):
            deserts=[q for q in p.battlefield if CARDDEF.get(q.name) and CARDDEF[q.name].is_land and ('Desert' in CARDDEF[q.name].type_line or q.counters.get('everything',0)>0)]
            if len(deserts)>=5:
                for _ in range(min(len(deserts),30)):self.token(p,'Sand Warrior',1,1,{'haste'})
                self.log('desert_warfare',p.name,'Desert Warfare',f'Created {len(deserts)} Sand Warrior tokens at beginning of combat')
        if p.name=='Minsc & Boo':
            # Use -2 for lethal or a huge hamster cash-in; otherwise +1.
            if not self.minsc_minus_two(p):self.minsc_activation(p)
        self.resolve_ozolith_begin_combat(p)
        if p.name=='Minsc & Boo':
            # Innkeeper and Halana/Alena are beginning-of-combat counter engines.
            inn=self.perm(p,"Innkeeper's Talent")
            if inn:
                q=self.strongest_creature(p)
                if q:self.add_counters(p,q,'+1/+1',1,"Innkeeper's Talent")
            ha=self.perm(p,'Halana and Alena, Partners')
            if ha:
                q=max([z for z in p.battlefield if self.is_creature_perm(z) and z.uid!=ha.uid],key=self.power,default=None)
                if q:
                    n=max(1,self.power(ha));self.add_counters(p,q,'+1/+1',n,'Halana and Alena');q.keywords.add('haste')
        if p.name=='Omo' and self.perm(p,'Hakbal of the Surging Soul'):
            merfolk=[q for q in list(p.battlefield) if CARDDEF.get(q.name) and CARDDEF[q.name].is_creature and ('Merfolk' in CARDDEF[q.name].type_line or q.counters.get('everything',0)>0)]
            for q in merfolk:
                if not p.library:break
                top=p.library[-1]
                if top.d.is_land:
                    p.library.pop();p.hand.append(top);self.log('explore_land',p.name,q.name,f'Hakbal explore reveals {top.d.name} to hand')
                else:
                    self.add_counters(p,q,'+1/+1',1,'Hakbal explore');self.log('explore_keep',p.name,q.name,f'Hakbal explore keeps {top.d.name} on top')
        if p.name=='Minsc & Boo' and self.perm(p,'Xenagos, God of Revels'):
            q=self.strongest_creature(p)
            if q:q.metadata['xenagos_bonus']=self.power(q);q.keywords.add('haste');self.log('combat_buff',p.name,'Xenagos, God of Revels',f'Xenagos gives {q.name} +{q.metadata["xenagos_bonus"]}/+{q.metadata["xenagos_bonus"]} and haste')
        if p.name=='Minsc & Boo' and self.perm(p,'Unnatural Growth'):
            for q in p.battlefield:
                d=CARDDEF.get(q.name)
                if self.is_creature_perm(q):q.metadata['unnatural_growth']=True
        if p.name=='Omo':
            sage=self.perm(p,'Sage of the Maze')
            if sage and not sage.tapped:
                gates=sum(1 for q in p.battlefield if CARDDEF.get(q.name) and CARDDEF[q.name].is_land and ('Gate' in CARDDEF[q.name].type_line.split(' // ')[0] or q.counters.get('everything',0)>0))
                if gates>=3:
                    land=next((q for q in p.battlefield if CARDDEF.get(q.name) and CARDDEF[q.name].is_land and not q.tapped),None)
                    if land:
                        sage.tapped=True;land.metadata['sage_animated']=True;land.metadata['sage_power']=2*gates;self.log('land_animation',p.name,'Sage of the Maze',f'{land.name} becomes {2*gates}/{2*gates} Citizen with haste until end of turn',target=land.name)
            jy=self.perm(p,'Jyoti, Moag Ancient')
            if jy:
                bonus=self.power(jy)
                for q in p.battlefield:
                    if q.metadata.get('sage_animated') or q.metadata.get('march_animated') or q.name=='Forest Dryad':q.metadata['jyoti_bonus']=bonus
                self.log('combat_buff',p.name,'Jyoti, Moag Ancient',f'Land creatures get +{bonus}/+{bonus} this combat')
        ruby=self.perm(p,'Ruby, Daring Tracker')
        if ruby and any(self.is_creature_perm(z) and self.power(z)>=4 for z in p.battlefield):ruby.metadata['ruby_attack_bonus']=2
        attackers=[q for q in p.battlefield if self.can_attack(q)]
        if not attackers:return
        for q in attackers:
            if q.name=='Kalonian Hydra':
                for t in [z for z in p.battlefield if CARDDEF.get(z.name) and CARDDEF[z.name].is_creature and z.counters.get('+1/+1',0)>0]:self.add_counters(p,t,'+1/+1',t.counters.get('+1/+1',0),'Kalonian Hydra attack double')
        target=self.choose_combat_target(p)
        if not target:return
        defender=target[0]
        if self.perm(defender,'Propaganda'):
            paid=[]
            for a in sorted(attackers,key=self.effective_power,reverse=True):
                tax=CardDef('Propaganda attack tax','{2}','Ability','',1,p.name,2)
                if self.can_pay(p,tax) and self.effective_power(a)>=4:
                    self.pay(p,tax)
                    if not a.tapped:paid.append(a)
            attackers=paid
            self.log('propaganda_tax',p.name,'Propaganda',f'Paid to attack with {len(attackers)} creature(s) into {defender.name}')
            if not attackers:return
        # Don't suicide tiny utility bodies into blockers unless they are effectively unblockable or needed for lethal.
        def unblockable_by_power(q,defender):
            champ=self.perm(p,'Champion of Lambholt')
            return bool(champ and self.power(champ)>0 and all(self.power(b)<self.power(champ) for b in defender.battlefield if self.is_creature_perm(b)))
        defender=target[0]
        atk=[q for q in attackers if self.effective_power(q)>=2 or q.name in {'Boo','Elenda, Saint of Dusk','Omo, Queen of Vesuva'} or unblockable_by_power(q,defender)]
        if not atk:return
        p.dungeon['attacked_turn']=self.turn_number
        self.resolve_combat(p,target,atk)

    def can_attack(self,q):
        if not self.is_creature_perm(q):return False
        if q.tapped:return False
        if q.summoning_sick and 'haste' not in q.keywords and not q.metadata.get('march_animated') and not q.metadata.get('sage_animated'):return False
        return self.effective_power(q)>0

    def can_block(self,blocker,attacker):
        if not self.is_creature_perm(blocker) or blocker.tapped or self.effective_toughness(blocker)<=0:return False
        if 'flying' in attacker.keywords and not ({'flying','reach'} & blocker.keywords):return False
        attack_controller=self.players.get(attacker.controller)
        if attack_controller:
            champion=self.perm(attack_controller,'Champion of Lambholt')
            if champion and self.effective_power(blocker)<self.effective_power(champion):return False
        return True

    def effective_power(self,q):
        v=q.metadata.get('sage_power',self.power(q))
        v+=q.metadata.get('jyoti_bonus',0)
        if q.metadata.get('xenagos_bonus'):v+=q.metadata['xenagos_bonus']
        if q.metadata.get('unnatural_growth'):v*=2
        v+=q.metadata.get('fixed_power_bonus',0)
        v+=q.metadata.get('wildspeaker_bonus',0)
        # Angel of Invention / Domri static bonuses
        p=self.players[q.controller]
        if self.perm(p,'Domri, Anarch of Bolas'):v+=1
        v+=q.metadata.get('ruby_attack_bonus',0)
        if self.perm(p,'Angel of Invention') and q.name!='Angel of Invention':v+=1
        if q.metadata.get('angelic_destiny_uid'):v+=4
        if q.metadata.get('celestial_armor_uid'):v+=2
        return v
    def effective_toughness(self,q):
        v=q.metadata.get('sage_power',self.toughness(q))
        if q.metadata.get('angelic_destiny_uid'):v+=4
        v+=q.metadata.get('jyoti_bonus',0)
        if q.metadata.get('xenagos_bonus'):v+=q.metadata['xenagos_bonus']
        if q.metadata.get('unnatural_growth'):v*=2
        v+=q.metadata.get('wildspeaker_bonus',0)
        v+=q.metadata.get('fixed_toughness_bonus',0)
        p=self.players[q.controller]
        if self.perm(p,'Angel of Invention') and q.name!='Angel of Invention':v+=1
        return v

    def choose_combat_target(self,p):
        ops=self.opponents(p)
        if not ops:return None
        total=sum(self.effective_power(q) for q in p.battlefield if self.can_attack(q))
        # Finish a player whenever raw attack power is plausibly lethal; otherwise retain target focus.
        lethal=[op for op in ops if total>=op.life]
        if lethal:
            op=min(lethal,key=lambda x:x.life);return (op,None)
        cur=p.dungeon.get('combat_target')
        op=next((x for x in ops if x.name==cur),None)
        def score(x):
            board=sum(self.perm_threat(q) for q in x.battlefield if not (CARDDEF.get(q.name) and CARDDEF[q.name].is_land))
            if x.name=='Reaminatour' and (self.perm(x,'Aminatou, Veil Piercer') or self.perm(x,'Parallax Wave')):board+=12
            return board+(40-x.life)*0.8
        best=max(ops,key=score)
        if op is None or score(best)>score(op)+18:op=best
        p.dungeon['combat_target']=op.name
        # Attack a dangerous planeswalker if it can realistically be removed this combat.
        pws=[q for q in op.battlefield if CARDDEF.get(q.name) and CARDDEF[q.name].is_planeswalker]
        if pws:
            pw=max(pws,key=self.perm_threat);loy=pw.counters.get('loyalty',3)
            if total>=loy and self.perm_threat(pw)>=8:return (op,pw)
        return (op,None)

    def resolve_combat(self,attacker,target_spec,atk):
        target,pw=target_spec
        blockers=[q for q in target.battlefield if self.is_creature_perm(q) and not q.tapped and self.effective_toughness(q)>0]
        blockers.sort(key=lambda q:self.effective_toughness(q)+self.effective_power(q),reverse=True)
        # Champion of Lambholt forbids low-power blockers.
        champ=self.perm(attacker,'Champion of Lambholt')
        if champ:blockers=[b for b in blockers if self.power(b)>=self.power(champ)]
        atk_sorted=sorted(atk,key=self.effective_power,reverse=True)
        assignments={q.uid:[] for q in atk_sorted};bi=0
        for a in atk_sorted:
            need=2 if 'menace' in a.keywords or (a.name=='Elenda, Saint of Dusk' and self.players[attacker.name].life>40) else 1
            if len(blockers)-bi>=need:assignments[a.uid]=blockers[bi:bi+need];bi+=need
        total_to_defended=0;lifelink_gain=0;deaths=[]
        for a in atk_sorted:
            a.tapped=True;ap=self.effective_power(a);bs=assignments[a.uid]
            if a.name=='Twinblade Paladin' and attacker.life>=25:ap*=2
            if not bs:total_to_defended+=ap
            else:
                block_t=sum(self.effective_toughness(b) for b in bs);trample=('trample' in a.keywords or self.perm(attacker,"Garruk's Uprising") is not None or (self.perm(attacker,'Kodama of the West Tree') is not None and a.counters.get('+1/+1',0)>0))
                if trample:total_to_defended+=max(0,ap-block_t)
                rem=ap
                for b in bs:
                    # deathtouch needs only positive damage; otherwise toughness.
                    lethal=1 if 'deathtouch' in a.keywords else self.effective_toughness(b)
                    if rem>=lethal:deaths.append((target,b))
                    rem=max(0,rem-self.effective_toughness(b))
                back=sum(self.effective_power(b) for b in bs)
                if any('deathtouch' in b.keywords and self.effective_power(b)>0 for b in bs) or back>=self.effective_toughness(a):deaths.append((attacker,a))
            if 'lifelink' in a.keywords or self.perm(attacker,'Sorin, Vengeful Bloodlord'):lifelink_gain+=ap
        defended=pw.name if pw else target.name
        self.log('combat_damage',attacker.name,None,f'{attacker.name} attacks {defended} with '+', '.join(f'{a.name}({self.effective_power(a)})' for a in atk_sorted)+f'; {total_to_defended} damage reaches defended object',attackers=[a.uid for a in atk_sorted],target=defended,damage=total_to_defended,blocks={k:[b.uid for b in v] for k,v in assignments.items()})
        if total_to_defended:
            if pw and pw in target.battlefield:
                pw.counters['loyalty']=pw.counters.get('loyalty',3)-total_to_defended;self.log('loyalty_damage',attacker.name,pw.name,f'{pw.name} loses {total_to_defended} loyalty',loyalty=pw.counters['loyalty'])
                if pw.counters['loyalty']<=0:self.leave_battlefield(target,pw,'graveyard','combat damage reduced loyalty to zero')
            else:self.lose_life(target,total_to_defended,'combat damage')
        # Kodama: each modified attacker that dealt player combat damage fetches a tapped basic.
        if not pw and self.perm(attacker,'Kodama of the West Tree'):
            triggers=0
            for a in atk_sorted:
                if a.counters.get('+1/+1',0)<=0:continue
                bs=assignments[a.uid];ap=self.effective_power(a)
                dealt=(not bs) or (('trample' in a.keywords or self.perm(attacker,"Garruk's Uprising")) and ap>sum(self.effective_toughness(b) for b in bs))
                if dealt:triggers+=1
            for _ in range(triggers):
                basics=[c for c in attacker.library if c.d.type_line.split(' // ')[0].startswith('Basic Land')]
                if not basics:break
                c=basics[0];attacker.library.remove(c);q=self._put_card_bf(attacker,c,'Kodama of the West Tree combat trigger');q.tapped=True;q.summoning_sick=False;self.rng.shuffle(attacker.library);self.log('shuffle',attacker.name,None,'Shuffle after Kodama basic search')
        # Rampant Frogantua mills on combat damage to a player and puts any lands milled onto the battlefield tapped.
        if not pw and total_to_defended>0 and any(a.name=='Rampant Frogantua' and not assignments[a.uid] for a in atk_sorted):
            frog=next(a for a in atk_sorted if a.name=='Rampant Frogantua' and not assignments[a.uid]);n=min(self.effective_power(frog),len(attacker.library));milled=[attacker.library.pop() for _ in range(n)]
            for c in milled:
                if c.d.is_land:
                    q=self._put_card_bf(attacker,c,'Rampant Frogantua combat mill land');q.tapped=True;q.summoning_sick=False
                else:
                    attacker.graveyard.append(c);self.log('mill',attacker.name,c.d.name,'Rampant Frogantua combat damage mill')
        if lifelink_gain:self.gain_life(attacker,lifelink_gain,'combat lifelink')
        seen=set()
        for pp,q in deaths:
            if q.uid in seen or q not in pp.battlefield:continue
            seen.add(q.uid);self.destroy(pp,q,'combat lethal damage')
        if self.perm(attacker,'Sun Titan') and any(a.name=='Sun Titan' for a in atk_sorted):self.sun_titan_trigger(attacker,'attack')
        if any(a.name=='Omo, Queen of Vesuva' for a in atk_sorted):self.omo_everything(attacker)
        if any(a.name=='Xolatoyac, the Smiling Flood' for a in atk_sorted):self.xolatoyac_counter(attacker,'attack')
        if attacker.name=='Omo' and any(a.name=='Hakbal of the Surging Soul' for a in atk_sorted):
            if any(c.d.is_land for c in attacker.hand):self.extra_land_from_hand(attacker,'Hakbal attack')
            else:self.draw(attacker,1,'Hakbal attack')

    def resolve_saga_chapter(self,p,q,ch):
        n=q.name;self.log('saga_chapter',p.name,n,f'Chapter {ch} resolves',chapter=ch)
        if n=='The Cruelty of Gix':
            if ch==1:
                choice=self.cruelty_discard_choice(p)
                if choice:
                    opp,c=choice
                    self.log('reveal_hand',opp.name,n,f'{opp.name} reveals '+(', '.join(card.d.name for card in opp.hand) or 'an empty hand'))
                    if c is not None and c in opp.hand:
                        opp.hand.remove(c);opp.graveyard.append(c);self.log('discard',opp.name,c.d.name,'Cruelty of Gix I')
            elif ch==2:
                target=self.request_ream_tutor(p) if p.name=='Reaminatour' else self.request_library_card(p)
                if target:self.search_to_zone(p,target,'hand','Cruelty of Gix II')
                self.lose_life(p,3,'Cruelty of Gix II')
            elif ch==3:
                choice=self.cruelty_reanimation_target(p)
                if choice:
                    owner,c=choice
                    if c in owner.graveyard:
                        owner.graveyard.remove(c);self._put_card_bf(p,c,'Cruelty of Gix III')
        elif n=='Elspeth Conquers Death':
            if ch==1:
                choices=[(op,t) for op in self.opponents(p) for t in op.battlefield if CARDDEF.get(t.name) and CARDDEF[t.name].mv>=3]
                if choices:
                    op,t=max(choices,key=lambda z:self.perm_threat(z[1]));self.exile_perm(op,t,'Elspeth Conquers Death I')
            elif ch==2:self.establish_ecd_tax(p)
            elif ch==3:
                before={z.uid for z in p.battlefield};self.reanimate_best_creature(p,'Elspeth Conquers Death III')
                made=[z for z in p.battlefield if z.uid not in before]
                if made:self.add_counters(p,made[-1],'+1/+1',1,'Elspeth Conquers Death III')
        elif n=='The Restoration of Eiganjo':
            if ch==1:
                opts=[c for c in p.library if c.d.name=='Plains']
                if opts:
                    c=opts[0];p.library.remove(c);p.hand.append(c);self.log('tutor',p.name,c.d.name,'Restoration I revealed basic Plains',visibility='public');self.rng.shuffle(p.library)
            elif ch==2:
                discard=min(p.hand,key=lambda c:self.ream_card_score(c.d.name) if p.name=='Reaminatour' else self.generic_card_score(p,c.d.name),default=None)
                targets=[c for c in p.graveyard if c.d.is_permanent and c.d.mv<=2]
                if discard and targets:
                    p.hand.remove(discard);p.graveyard.append(discard);self.log('discard',p.name,discard.d.name,'Restoration II')
                    c=max(targets,key=lambda z:self.ream_card_score(z.d.name) if p.name=='Reaminatour' else z.d.mv)
                    if c in p.graveyard:p.graveyard.remove(c);t=self._put_card_bf(p,c,'Restoration II');t.tapped=True
            elif ch==3:
                q.metadata['transformed_restoration']=True;q.base_power=3;q.base_toughness=4;self.log('transform',p.name,n,'Restoration transforms into Architect of Restoration')
        if ch>=3 and n in {'The Cruelty of Gix','Elspeth Conquers Death'} and q in p.battlefield:self.leave_battlefield(p,q,'graveyard','Saga final chapter state-based sacrifice')

    def saga_enters(self,p,q):
        chapter=self.cruelty_read_ahead_choice(p,q) if q.name=='The Cruelty of Gix' else 1
        q.counters['lore']=chapter;self.resolve_saga_chapter(p,q,chapter)

    def saga_step(self,p):
        for q in list(p.battlefield):
            if q.name not in {'The Cruelty of Gix','Elspeth Conquers Death','The Restoration of Eiganjo'}:continue
            lore=q.counters.get('lore',0)+1;q.counters['lore']=lore
            if lore<=3:self.resolve_saga_chapter(p,q,lore)

    def unlock_awakening_hall(self,p,room,reason='unlock'):
        if room.metadata.get('awakening_unlocked'):return False
        room.metadata['awakening_unlocked']=True
        creatures=list(c for c in p.graveyard if c.d.is_creature)
        self.log('room_unlock',p.name,'Funeral Room // Awakening Hall',f'Awakening Hall unlocked via {reason}; return {len(creatures)} creature card(s)')
        for c in creatures:
            if c in p.graveyard:p.graveyard.remove(c);self._put_card_bf(p,c,'Awakening Hall unlock')
        if self.perm(p,'Ghostly Dancers'):self.token(p,'Spirit',3,1,{'flying'})
        return True

    def escape_uro(self,p,c):
        if c not in p.graveyard:return False
        cost=CardDef('Uro escape','{G}{G}{U}{U}','Ability','',1,p.name,4)
        others=[z for z in p.graveyard if z.uid!=c.uid]
        if len(others)<5 or not self.pay(p,cost):return False
        for z in sorted(others,key=lambda z:self.generic_card_score(p,z.d.name))[:5]:p.graveyard.remove(z);p.exile.append(z);self.log('exile',p.name,z.d.name,'Uro escape cost')
        p.graveyard.remove(c);p.dungeon['escaping_uro_uid']=c.uid;self._put_card_bf(p,c,'Uro escaped')
        return True

    def xolatoyac_counter(self,p,reason):
        lands=[q for q in p.battlefield if CARDDEF.get(q.name) and CARDDEF[q.name].is_land]
        if not lands:return
        q=max(lands,key=lambda z:self.generic_card_score(p,z.name));q.counters['flood']=q.counters.get('flood',0)+1
        self.log('counters',p.name,'Xolatoyac, the Smiling Flood',f'Put flood counter on {q.name} ({reason})',target=q.name)

    def cascade_once(self,p,limit,reason):
        revealed=[];hit=None
        while p.library:
            c=p.library.pop();revealed.append(c)
            if not c.d.is_land and c.d.mv<limit:
                hit=c;break
        if hit:
            revealed.remove(hit)
            reactive={'Arcane Denial','Counterspell','Remand','Fierce Guardianship','Summary Dismissal','Swan Song'}
            if hit.d.name in reactive:
                revealed.append(hit);self.log('cascade_decline',p.name,hit.d.name,f'{reason} cascade hits {hit.d.name}; decline to cast a counterspell with no beneficial target')
            else:
                p.hand.append(hit);self.log('cascade_hit',p.name,hit.d.name,f'{reason} cascade hits {hit.d.name}',uid=hit.uid);self.cast(p,hit,free=True)
        # Other revealed cards are randomized on bottom; deterministic shuffle of the block is a legal random ordering policy.
        self.rng.shuffle(revealed);p.library=revealed+p.library
        if revealed:self.log('cascade_bottom',p.name,None,f'{reason}: put {len(revealed)} non-hit revealed card(s) on bottom in random order')

    def end_step_triggers(self,p):
        # Active-player beginning-of-end-step triggers.
        if self.perm(p,'Cosmos Elixir'):
            if p.life>40:self.draw(p,1,'Cosmos Elixir end step')
            else:self.gain_life(p,2,'Cosmos Elixir end step')
        if self.perm(p,'Xolatoyac, the Smiling Flood'):
            count=0
            for q in p.battlefield:
                if any(v>0 for v in q.counters.values()):q.tapped=False;count+=1
            self.log('untap_effect',p.name,'Xolatoyac, the Smiling Flood',f'Untapped {count} permanent(s) with counters at end step')
        if self.perm(p,'Midnight Snack') and p.dungeon.get('attacked_turn')==self.turn_number:
            p.dungeon['food']=p.dungeon.get('food',0)+1;self.log('food',p.name,'Midnight Snack','Raid creates a Food token',food=p.dungeon['food'])
        # Indulgent Tormentor: choose opponent that least wants to feed a card; they pay 3 life unless low.
        if False: pass

    def activate_value_abilities(self,p):
        # Deterministic one-pass activation policy for non-mana engines.
        # One planeswalker loyalty activation per own turn.
        sor=self.perm(p,'Sorin, Vengeful Bloodlord')
        if sor and sor.metadata.get('activated_turn')!=self.turn_number:
            targets=[c for c in p.graveyard if c.d.is_creature and c.d.mv<=sor.counters.get('loyalty',4)]
            if targets:
                c=max(targets,key=lambda c:c.d.mv);x=c.d.mv;sor.counters['loyalty']-=x;sor.metadata['activated_turn']=self.turn_number;p.graveyard.remove(c);q=self._put_card_bf(p,c,'Sorin -X');self.log('planeswalker_activation',p.name,sor.name,f'-{x} reanimates {q.name}')
            else:
                sor.counters['loyalty']=sor.counters.get('loyalty',4)+2;sor.metadata['activated_turn']=self.turn_number;opp=min(self.opponents(p),key=lambda x:x.life,default=None)
                if opp:self.lose_life(opp,1,'Sorin +2');self.log('planeswalker_activation',p.name,sor.name,'+2 deals 1 to opponent',target=opp.name)
        amin=self.perm(p,'Aminatou, the Fateshifter')
        if amin and amin.metadata.get('activated_turn')!=self.turn_number:
            # Prefer a safe -1 blink of a high-value own ETB permanent; otherwise +1 draw/putback.
            opts=[q for q in p.battlefield if q.uid!=amin.uid and not (CARDDEF.get(q.name) and CARDDEF[q.name].is_land) and self.ream_card_score(q.name)>=13]
            if amin.counters.get('loyalty',3)>=2 and opts:
                t=max(opts,key=lambda q:self.ream_card_score(q.name));amin.counters['loyalty']-=1;amin.metadata['activated_turn']=self.turn_number
                if not t.token:
                    uid=t.uid;name=t.name;self.leave_battlefield(p,t,'exile','Aminatou Fateshifter -1')
                    c=next((c for c in p.exile if c.uid==uid),None)
                    if c:p.exile.remove(c);self._put_card_bf(p,c,'Aminatou Fateshifter -1 return')
                self.log('planeswalker_activation',p.name,amin.name,f'-1 blinks {t.name}')
            else:
                amin.counters['loyalty']=amin.counters.get('loyalty',3)+1;amin.metadata['activated_turn']=self.turn_number;self.draw(p,1,'Aminatou Fateshifter +1')
                if p.hand:
                    c=min(p.hand,key=lambda c:self.ream_card_score(c.d.name));p.hand.remove(c);p.library.append(c);self.log('put_on_top',p.name,c.d.name,'Aminatou Fateshifter +1')
        mp=self.perm(p,'Expedition Map')
        if mp and not mp.tapped:
            cost=CardDef('Expedition Map ability','{2}','Ability','',1,p.name,2)
            if self.can_pay(p,cost):
                self.pay(p,cost);mp.tapped=True;self.leave_battlefield(p,mp,'graveyard','Expedition Map activation sacrifice')
                lands=[c for c in p.library if c.d.is_land]
                if lands:
                    c=max(lands,key=lambda z:self.generic_card_score(p,z.d.name));p.library.remove(c);p.hand.append(c);self.log('tutor',p.name,c.d.name,'Expedition Map revealed land search',visibility='public');self.rng.shuffle(p.library);self.log('shuffle',p.name,None,'Shuffle after Expedition Map')
        hb=self.perm(p,'Hydra Broodmaster')
        if hb and not hb.metadata.get('monstrous'):
            # choose largest affordable X >=2, capped for simulation size
            for x in range(8,1,-1):
                cost=CardDef('Hydra Broodmaster monstrosity','{'+str(2*x)+'}{G}','Ability','',1,p.name,2*x+1)
                if self.can_pay(p,cost):
                    self.pay(p,cost);hb.metadata['monstrous']=True;self.add_counters(p,hb,'+1/+1',x,'Monstrosity X')
                    for _ in range(x):self.token(p,'Hydra',x,x)
                    self.log('monstrous',p.name,'Hydra Broodmaster',f'Monstrosity {x}; created {x} {x}/{x} Hydras');break
        top=self.perm(p,"Sensei's Divining Top")
        if top and not top.tapped and len(p.hand)<7:
            cost=CardDef('Top look','{1}','Ability','',1,p.name,1)
            if self.can_pay(p,cost) and len(p.library)>=1:
                self.pay(p,cost);seen=p.library[-3:];best=max(seen,key=lambda c:self.ream_card_score(c.d.name) if p.name=='Reaminatour' else self.generic_card_score(p,c.d.name));p.library.remove(best);p.library.append(best);self.log('top_reorder',p.name,"Sensei's Divining Top",f'Looked at top {len(seen)}; put {best.d.name} on top')
            if p.library and (self.ream_card_score(p.library[-1].d.name) if p.name=='Reaminatour' else self.generic_card_score(p,p.library[-1].d.name))>=12:
                top.tapped=True;self.draw(p,1,"Sensei's Divining Top draw ability")
                if top in p.battlefield:
                    p.battlefield.remove(top);p.library.append(CardObj(top.uid,CARDDEF[top.name]));self.log('put_on_top',p.name,top.name,"Sensei's Divining Top puts itself on top",visibility='public')
        room=self.perm(p,'Funeral Room // Awakening Hall')
        if room and not room.metadata.get('awakening_unlocked') and len([c for c in p.graveyard if c.d.is_creature])>=2:
            cost=CardDef('Awakening Hall unlock','{6}{B}{B}','Ability','',1,p.name,8)
            if self.can_pay(p,cost):self.pay(p,cost);self.unlock_awakening_hall(p,room,'paid unlock')
        ms=self.perm(p,'Midnight Snack')
        if ms and p.life_gained_this_turn>0:
            opp=min(self.opponents(p),key=lambda x:x.life,default=None);cost=CardDef('Midnight Snack ability','{2}{B}','Ability','',1,p.name,3)
            if opp and p.life_gained_this_turn>=opp.life and self.can_pay(p,cost):
                self.pay(p,cost);amt=p.life_gained_this_turn;self.leave_battlefield(p,ms,'graveyard','Midnight Snack activation sacrifice');self.lose_life(opp,amt,'Midnight Snack')

    def minsc_minus_two(self,p):
        cmd=self.perm(p,'Minsc & Boo, Timeless Heroes'); boo=self.perm(p,'Boo')
        if not cmd or not boo or cmd.counters.get('loyalty',3)<2:return False
        power=self.power(boo); opp=min(self.opponents(p),key=lambda x:x.life,default=None)
        if not opp:return False
        # Legal deterministic policy: cash in Boo if it kills a player or converts a very large body into >=8 cards.
        if power<opp.life and power<8:return False
        cmd.counters['loyalty']-=2
        self.leave_battlefield(p,boo,'graveyard','Minsc & Boo -2 sacrifice')
        self.lose_life(opp,power,'Minsc & Boo -2 damage')
        if not p.eliminated:self.draw(p,min(power,40),'Minsc & Boo -2 Hamster draw')
        self.log('planeswalker_activation',p.name,'Minsc & Boo, Timeless Heroes',f'-2 sacrifices Boo for {power} damage and {power} cards',target=opp.name)
        if cmd in p.battlefield and cmd.counters.get('loyalty',0)<=0:self.leave_battlefield(p,cmd,'graveyard','0 loyalty state-based action')
        return True

    def minsc_activation(self,p):
        cmd=self.perm(p,'Minsc & Boo, Timeless Heroes')
        if not cmd:return
        boo=self.perm(p,'Boo')
        target=boo or self.strongest_creature(p)
        if target:
            self.add_counters(p,target,'+1/+1',3,'Minsc +1');cmd.counters['loyalty']=cmd.counters.get('loyalty',3)+1

    def cleanup(self,p):
        self.phase='end_step';self.end_step_triggers(p)
        self.phase='cleanup';self.reset_eot_modifiers()
        if not self.has_no_maximum_hand_size(p):
            while len(p.hand)>7:
                card=min(p.hand,key=lambda c:self.generic_card_score(p,c.d.name));p.hand.remove(card);p.graveyard.append(card)
                self.log('discard',p.name,card.d.name,'Cleanup maximum hand size')
        self.log('cleanup',p.name,None,'Cleanup step')

    def max_land_plays(self,p):
        n=1
        if self.perm(p,'Azusa, Lost but Seeking'):n+=2
        if self.perm(p,'Dryad of the Ilysian Grove'):n+=1
        if self.perm(p,'Oracle of Mul Daya'):n+=1
        return n

    def check_static_on_entry(self,p,q):
        # called ad hoc if needed
        pass

    def after_permanent_entry_adjustments(self,p,q):
        if p.name=='Minsc & Boo' and CARDDEF.get(q.name) and CARDDEF[q.name].is_creature:
            if self.perm(p,'Rhythm of the Wild') and q.name!='Rhythm of the Wild':q.keywords.add('haste');self.log('riot',p.name,q.name,'Rhythm of the Wild chooses haste')
            dd=CARDDEF.get(q.name)
            if self.perm(p,'Grumgully, the Generous') and q.name!='Grumgully, the Generous' and not (dd and 'Human' in dd.type_line):self.add_counters(p,q,'+1/+1',1,'Grumgully')

    def check_ream_combo(self):
        p=self.players['Reaminatour']
        if p.eliminated or self.winner:return False
        roles={q.name for q in p.battlefield}
        for q in p.battlefield:
            if q.name=='Body Double' and q.copy_of:roles.add(q.copy_of)
        gy={c.d.name for c in p.graveyard};hand={c.d.name for c in p.hand}
        sensor_enchant='Grim Guardian' in roles
        sensor_death=bool({'Funeral Room // Awakening Hall','The Meathook Massacre'} & roles)
        outlet=bool({'Viscera Seer','Fanatical Devotion','Fallen Ideal'} & roles)
        auras={'Animate Dead','Dance of the Dead','Necromancy'} & roles
        en_count=sum(1 for q in p.battlefield if CARDDEF.get(q.name) and CARDDEF[q.name].is_enchantment)
        if {'Parallax Wave','Felidar Guardian'}<=roles and sensor_enchant:return self.attempt_combo_win(p,'Parallax Wave + Felidar Guardian + Grim Guardian infinite enchantment-ETB drain')
        if {'Starfield of Nyx','Parallax Wave','Grim Guardian'}<=roles and en_count>=5:return self.attempt_combo_win(p,'Starfield + animated Parallax Wave self-reset + Grim Guardian')
        if auras and 'Leonin Relic-Warder' in roles and sensor_enchant:return self.attempt_combo_win(p,'Leonin Relic-Warder + reanimation Aura + Grim Guardian')
        if outlet and {'Karmic Guide','Felidar Guardian'}<=roles and sensor_death:return self.attempt_combo_win(p,'Karmic Guide + Felidar Guardian + sacrifice outlet + death sensor')
        if outlet and {'Reveillark','Felidar Guardian'}<=roles and (sensor_death or sensor_enchant or 'Grim Guardian' in gy):return self.attempt_combo_win(p,'Reveillark + Felidar Guardian + outlet + death/enchantment payload sensor')
        if outlet and {'Reveillark','Karmic Guide'}<=roles and (sensor_death or sensor_enchant or 'Grim Guardian' in gy):return self.attempt_combo_win(p,'Reveillark + Karmic Guide + outlet + sensor')
        if outlet and {'Sun Titan','Changing Loyalty'}<=roles and (sensor_enchant or sensor_death):return self.attempt_combo_win(p,'Sun Titan + Changing Loyalty + sacrifice outlet + sensor')
        # Audited Titan/reanimation families from the prior oscillator-closure work.
        if outlet and 'Sun Titan' in roles and 'Karmic Guide' in roles and auras and (sensor_death or sensor_enchant):return self.attempt_combo_win(p,'Sun Titan + Karmic Guide + reanimation Aura + outlet + sensor')
        if outlet and 'Sun Titan' in roles and len(auras)>=2 and (sensor_death or sensor_enchant):return self.attempt_combo_win(p,'Sun Titan + two reanimation Auras + outlet + sensor')
        if outlet and 'Sun Titan' in roles and 'Leonin Relic-Warder' in roles and auras and (sensor_death or sensor_enchant):return self.attempt_combo_win(p,'Sun Titan + Leonin Relic-Warder + reanimation Aura + outlet + sensor')
        if outlet and {'Parallax Wave','Sun Titan','Leonin Relic-Warder'}<=roles and sensor_enchant:return self.attempt_combo_win(p,'Parallax Wave + Sun Titan + Leonin Relic-Warder + outlet + Grim Guardian')
        oscillator=(bool(auras) and 'Leonin Relic-Warder' in roles) or ({'Parallax Wave','Felidar Guardian'}<=roles) or ({'Starfield of Nyx','Parallax Wave'}<=roles and en_count>=5)
        if oscillator and ('Entity Tracker' in roles or "Victor, Valgavoth's Seneschal" in roles):
            grim_zone='hand' if 'Grim Guardian' in hand else ('library' if any(c.d.name=='Grim Guardian' for c in p.library) else ('graveyard' if 'Grim Guardian' in gy and "Victor, Valgavoth's Seneschal" in roles else None))
            if grim_zone:
                self.log('combo_router',p.name,'Grim Guardian',f'Infinite oscillator + router accesses Grim Guardian from {grim_zone}')
                return self.attempt_combo_win(p,'oscillator + Entity/Victor routes Grim Guardian, then resumes lethal loop')
        return False

    def attempt_combo_win(self,p,reason):
        # Opponents may have instant-speed removal in hand and mana. Try one answer against a combo-critical permanent.
        self.log('combo_attempt',p.name,None,reason)
        critical=['Parallax Wave','Felidar Guardian','Grim Guardian','Leonin Relic-Warder','Starfield of Nyx','Viscera Seer','Sun Titan']
        for op in self.opponents(p):
            for nm in ['Beast Within','Chaos Warp','Pongify','Utter End','Hero\'s Downfall','Murder','Breathe Your Last']:
                c=self.card_in_hand(op,nm)
                if not c or self.can_pay(op,c.d) is None:continue
                targets=[]
                for n in critical:
                    q=self.perm(p,n)
                    if not q:continue
                    d=CARDDEF.get(n)
                    legal=True
                    if nm in {'Pongify','Murder','Breathe Your Last'}:legal=d and d.is_creature
                    if nm=='Hero\'s Downfall':legal=d and (d.is_creature or d.is_planeswalker)
                    if legal:targets.append(q)
                if not targets:continue
                q=max(targets,key=self.perm_threat)
                self.pay(op,c.d);op.hand.remove(c);op.graveyard.append(c);self.mark_appearance(c.d.name,cast=True,realized=True)
                self.log('combo_interaction',op.name,nm,f'{nm} answers {q.name} during combo attempt',target=q.name)
                if nm in {'Utter End','Pongify'}:self.exile_perm(p,q,nm)
                else:self.destroy(p,q,nm)
                return False
        # no answer => deterministic infinite lethal
        for op in list(self.opponents(p)):
            if not op.eliminated:self.lose_life(op,max(1,op.life),'infinite combo: '+reason)
        if not self.winner:
            self.winner='Reaminatour';self.win_turn=self.turn_number;self.win_reason=reason;self.log('winner','Reaminatour',None,'Reaminatour wins via '+reason)
        return True

    def turn(self,p):
        if p.eliminated:return
        self.turn_number+=1
        self.expire_turn_start_effects(p)
        self.round=(self.turn_number-1)//4+1
        for player in self.players.values():player.cards_drawn_this_turn=0
        p.land_plays_used=0
        self.untap(p);self.upkeep(p)
        if p.eliminated or self.winner:return
        self.draw_step(p)
        p.land_play_limit=self.max_land_plays(p)
        self.main_phase(p,False)
        if p.eliminated or self.winner:return
        self.combat(p)
        if p.eliminated or self.winner:return
        self.main_phase(p,True)
        self.cleanup(p)
        self.assert_invariants(f'end_turn_{self.turn_number}')

    def run(self):
        max_global_turns=self.max_turns*4
        while not self.winner and self.turn_number<max_global_turns:
            p=self.players[self.turn_order[self.active_idx]]
            self.turn(p)
            self.active_idx=(self.active_idx+1)%4
            # if 0 or 1 alive finish
            alive=[x for x in self.players.values() if not x.eliminated]
            if len(alive)==1 and not self.winner:
                self.winner=alive[0].name;self.win_turn=self.turn_number;self.win_reason='last player standing'
        if not self.winner:
            # deterministic adjudication at horizon by board/life score, explicitly labeled horizon not a rules win
            alive=[x for x in self.players.values() if not x.eliminated]
            def score(p):
                return p.life + sum(self.perm_threat(q) for q in p.battlefield)*1.5 + len(p.hand)*2
            self.winner=max(alive,key=score).name if alive else None;self.win_turn=self.turn_number;self.win_reason='simulation horizon adjudication'
            self.log('horizon_adjudication',self.winner,None,f'No rules win by {self.max_turns} rounds; board/life score adjudication selects {self.winner}')
        self.assert_invariants('final')
        return self.result()

    def result(self):
        return {'game':self.game_no,'seed':self.seed,'seating':self.turn_order,'winner':self.winner,'turn_number':self.win_turn,'round':(self.win_turn-1)//4+1 if self.win_turn else None,'reason':self.win_reason,'events':len(self.events),'unsupported_count':len(self.material_unsupported),'stat_fallback':sorted(self.stat_fallback)}

    def write_game(self):
        # human-readable log plus JSONL snapshots
        gdir=self.outdir/'games';gdir.mkdir(parents=True,exist_ok=True)
        txt=gdir/f'game_{self.game_no:02d}_seed_{self.seed}.txt'
        with txt.open('w',encoding='utf-8') as f:
            r=self.result();f.write(f'GAME {self.game_no:02d} — seed {self.seed}\nSeating: {" → ".join(self.turn_order)}\nWinner: {self.winner} | turn event {self.win_turn} | round {r["round"]} | {self.win_reason}\n\n')
            for e in self.events:
                f.write(f'[{e["seq"]:04d}] R{e["round"]} T{e["turn"]} {e["phase"]:<16} {e.get("actor") or "TABLE":<12} {e["type"]:<20} {e.get("card") or "":<35} {e["detail"]}\n')
        return txt

# Patch after entry so Rhythm/Grumgully apply to every creature after base ETB handler.
_ORIG_ON_ETB=Game.on_etb
def _patched_on_etb(self,p,q,x_value=0):
    _ORIG_ON_ETB(self,p,q,x_value)
    self.after_permanent_entry_adjustments(p,q)
Game.on_etb=_patched_on_etb
