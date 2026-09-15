"""Fenced next-game initialization; no pilot decisions or historical migrations."""
from pathlib import Path
import uuid
from .primitive_campaign import PrimitiveCampaign,configuration
from .primitive_lifecycle import stopped_prefix
from .primitive_reports import verified_result
from .rules_adapter import digest
from .rules_setup import fresh_pod
from .rules_state import RulesViolation
from .runtime_store import read,write


def advance(campaign,game):
    """Caller owns host-driver lock. A prepared zero-action game is retryable."""
    root=campaign.root;manifest=read(root/'cohort.json');number=campaign.binding['game_number']
    if type(game) is not int or game!=number+1:raise RulesViolation('Advance only the next scheduled game')
    if (root/'HOST_PAUSED.json').exists():raise RulesViolation('An operator pause prevents advancement')
    if campaign.next_action().get('kind')!='advance_game':raise RulesViolation('The current lifecycle does not permit advancement')
    if game>manifest['target_games']:raise RulesViolation('Campaign is complete')
    stopped_prefix(campaign,campaign.store.committed_head())
    seal,_,_=verified_result(campaign.directory)
    state=campaign.state()
    if state['pending']:raise RulesViolation('Reconcile pending input before advancement')
    if digest({actor:{key:seat[key] for key in ('standing','seed','personality')}
               for actor,seat in state['actors'].items()})!=campaign.config['strategy_sha256']:
        raise RulesViolation('Frozen strategy changed')
    from .primitive_campaign import frozen_strategy
    if digest(frozen_strategy(campaign.assets))!=campaign.config['strategy_sha256']:
        raise RulesViolation('Started campaign strategy differs from current assets')
    schedule=campaign.config['campaign'];players=tuple(campaign.kernel.state.players)
    starter=players[(players.index(schedule['starting_player'])+game-1)%len(players)]
    config=configuration(campaign.assets,seed=schedule['seed_start']+game-1,
                         starting_player=starter,max_rounds=schedule['max_rounds'])
    config['campaign']=schedule
    intent_path=root/'ADVANCE.json';intent=read(intent_path,{})
    expected={'from_game':number,'to_game':game,'terminal_sha256':digest(seal),'config':config}
    if intent:
        if any(intent.get(key)!=value for key,value in expected.items()):raise RulesViolation('Prepared advancement differs from this terminal prefix')
    else:
        intent={**expected,'binding':{'cohort_id':campaign.binding['cohort_id'],'game_number':game,
                   'branch_id':str(uuid.uuid4()),'contract_sha256':digest(config)}}
        write(intent_path,intent)
    directory=root/f'game_{game:02d}';staging=root/f'.advancing-game-{game:02d}'
    if not directory.exists():
        if staging.exists():
            # Never overwrite uncertain initialization. A complete zero-action
            # staging database can be audited and published on exact retry.
            from .rules_bundle import load_reviewed
            from .rules_durable import DurableRulesAdapter
            store=DurableRulesAdapter.open(staging/'rules.sqlite',tuple(row['program'] for row in load_reviewed(campaign.assets).values()),binding=intent['binding'])
            try:
                from .primitive_journal import verify
                verify(store.connection,intent['binding'])
                if store.generation:raise RulesViolation('Prepared next game contains accepted actions')
            finally:store.close()
        else:
            kernel=fresh_pod(seed=config['seed'],starting_player=starter,root=campaign.assets)
            fresh=PrimitiveCampaign._initialize(root,campaign.assets,config,kernel,intent['binding'],directory=staging,publish=False)
            fresh.close()
        staging.rename(directory)
    if read(directory/'game_config.json')!=config:raise RulesViolation('Next-game configuration differs from prepared advancement')
    from .rules_bundle import load_reviewed
    from .rules_durable import DurableRulesAdapter
    from .primitive_journal import verify
    prepared=DurableRulesAdapter.open(directory/'rules.sqlite',tuple(row['program'] for row in load_reviewed(campaign.assets).values()),binding=intent['binding'])
    try:
        verify(prepared.connection,intent['binding'])
        if prepared.generation:raise RulesViolation('Prepared next game contains accepted actions')
    finally:prepared.close()
    runtime=root/'host_runtime'
    if runtime.exists():
        archived=campaign.directory/'host_runtime'
        if archived.exists():raise RulesViolation('Historical host archive already exists')
        runtime.rename(archived)
    manifest.update(active_game=game,binding=intent['binding'])
    write(root/'cohort.json',manifest)
    write(campaign.directory/'advancement.json',intent)
    intent_path.unlink()
    return PrimitiveCampaign.open(root,recover=False)
