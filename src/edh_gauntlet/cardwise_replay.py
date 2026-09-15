"""Offline, isolated replay observer for operator statistics; no agent transport."""
from __future__ import annotations
import json
import shutil
import tempfile
from pathlib import Path

ACTOR='Reaminatour'


class ZoneObserver:
    def __init__(self,identities):
        self.identities=identities;self.seen=set();self.cast=set()

    def observe(self,players):
        # Never inspect libraries, exile, command zones or copied token identities.
        for player in players.values():
            for zone in ('hand','graveyard','battlefield'):
                for obj in getattr(player,zone,[]):
                    name=self.identities.get(obj.uid)
                    if name is None or getattr(obj,'token',False):continue
                    self.seen.add(name)
                    if zone=='battlefield':self.cast.add(name)

    def event(self,kind,actor,card,extra):
        if kind in {'cast','cast_transformed'}:
            name=self.identities.get(extra.get('uid'))
            if name:self.cast.add(name)
        # Older accepted response shortcuts lack a UID on their cast event.
        if kind in {'counterspell','combo_interaction'} and actor==ACTOR and card in self.seen:
            self.cast.add(card)


def replay(directory,*,identity_root=None):
    from . import campaign,referee,engine,planner_runtime
    from .inspection import InspectionService
    from .strategy import load_strategy_state
    directory=Path(directory).resolve();root=Path(identity_root).resolve() if identity_root else directory.parent
    config=json.loads((directory/'game_config.json').read_text())
    game_number=config['game'];identities={};ordinal=0
    for definition in engine.DECKDEFS[ACTOR]:
        for _ in range(definition.quantity):
            ordinal+=1;identities[f'{ACTOR[:2]}-{game_number:02d}-{ordinal:03d}']=definition.name
    observer=ZoneObserver(identities)

    class ObservedGame(referee.ManualGame):
        def log(self,kind,actor,card,detail,**extra):
            observer.observe(self.players);observer.event(kind,actor,card,extra)
            return super().log(kind,actor,card,detail,**extra)
        def _request_decision(self,*args,**kwargs):
            # Includes opening hands before mulligan/bottom choices.
            observer.observe(self.players)
            return super()._request_decision(*args,**kwargs)
        def _request_multi_decision(self,*args,**kwargs):
            observer.observe(self.players)
            return super()._request_multi_decision(*args,**kwargs)

    def records(name,actor_key):
        path=directory/'continuity'/name
        values=json.loads(path.read_text()) if path.exists() else []
        return [r for r in values if planner_runtime._compatible(r['source_session'],root,game_number,r[actor_key])]

    # Keep any request or incidental replay artifacts away from the live cohort.
    # Original root identity is used only to validate existing public sidecars.
    with tempfile.TemporaryDirectory(prefix='edh-cardwise-') as temporary:
        target=Path(temporary)/directory.name
        shutil.copytree(directory,target,ignore=shutil.ignore_patterns('pilot_turns','postgame_evidence','postgame_review','postgame_learning','games','operator'))
        tape=referee.DecisionTape(target/'decisions.jsonl',Path(temporary)/'unanswered.json')
        game=ObservedGame.__new__(ObservedGame)
        try:
            ObservedGame.__init__(game,config['seed'],game_number,target,
                max_turns=config['max_rounds'],decision_tape=tape,
                inspection_service=InspectionService(strategy=load_strategy_state(target/'strategy_snapshot.json')),
                combo_adjudications=campaign._combo_adjudication_responses(target/campaign.COMBO_ADJUDICATION_JOURNAL),
                planning_contract=config.get('planning_contract',1),
                async_diplomacy=config.get('async_diplomacy')==1,
                decision_roles=config.get('decision_roles')==1,
                combo_deliveries=records('combo_deliveries.json','actor') if config.get('decision_roles')==1 else [],
                diplomacy_posts=records('diplomacy_posts.json','author') if config.get('async_diplomacy')==1 else None,
                proliferate_batch_after=config.get('proliferate_batch_after'),
                selection_batch_after=config.get('selection_batch_after'),
                combat_blocker_batch=config.get('combat_blocker_batch',0),
                combat_damage_batch=config.get('combat_damage_batch',0),turn_batches=config.get('turn_batches',0),
                decision_surface_revision=config.get('decision_surface_revision',1),
                capture_event_state=False,capture_decision_state=False)
            result=game.run();state='terminal'
        except referee.NeedDecision:
            state='unanswered';result=None
        except referee.UnrefereedDecisionError:
            state='rules_blocker';result=None
        observer.observe(game.players)
        return {'seen':sorted(observer.seen),'cast':sorted(observer.cast),'state':state,'result':result,
                'accepted':len(game.decisions),'events':game.seq,
                'decisions_sha256':campaign._sha256_file(target/'decisions.jsonl')}


if __name__=='__main__':
    import sys
    try:print(json.dumps(replay(Path(sys.argv[1])),separators=(',',':')))
    except (Exception,SystemExit) as exc:
        print(json.dumps({'error':type(exc).__name__+': '+str(exc)}));sys.exit(1)
