"""Explicit fenced upgrade for own-upkeep snoozes and forced empty combat."""
import argparse
from pathlib import Path
from .paths import PROJECT_ROOT
from .rules_adapter import RulesActorAdapter, digest
from .rules_state import RulesViolation
from .runtime_store import read, write, locked
from .primitive_release import fingerprint
from .primitive_telemetry_repair import checked_release, host_hash, fence

ALLOWED={'primitive_actions.py','rules_combat.py','primitive_campaign.py',
         'primitive_scheduler_upgrade.py','primitive_host.py'}
POLICIES={'docs/HOST_AGENT_POLICY.md','docs/HOST_RUNTIME.md'}


def validate(proof,binding,config,root):
    try:
        if proof['schema']!=1 or proof['scope']!='empty_combat_own_upkeep' or proof['binding']!=binding:
            raise RulesViolation('Scheduler upgrade binding changed')
        old=checked_release(proof['before']);new=checked_release(proof['after'])
        if new!=fingerprint(root) or host_hash(old['modules'])!=config['host_implementation']:
            raise RulesViolation('Scheduler upgrade implementation mismatch')
        changed={k for k in old['modules'].keys()|new['modules'].keys()
                 if old['modules'].get(k)!=new['modules'].get(k)}
        if not {'primitive_actions.py','rules_combat.py'}<=changed or not changed<=ALLOWED:
            raise RulesViolation('Changes exceed scheduler upgrade scope')
        if {k:v for k,v in old.items() if k not in {'modules','assets'}}!={k:v for k,v in new.items() if k not in {'modules','assets'}}:
            raise RulesViolation('Scheduler upgrade cannot change rules identity, web assets or strategy')
        assets={k for k in old['assets'].keys()|new['assets'].keys() if old['assets'].get(k)!=new['assets'].get(k)}
        if not assets<=POLICIES:raise RulesViolation('Scheduler upgrade cannot change card/deck assets')
        commit=proof['commit']
        if type(commit['sequence']) is not int or commit['sequence']<0 or type(commit['sha256']) is not str:
            raise RulesViolation('Invalid scheduler upgrade prefix')
    except (KeyError,TypeError,ValueError) as exc:
        raise RulesViolation('Incomplete scheduler upgrade evidence') from exc


def verify_prefix(campaign,proof,*,candidate=False):
    commit=proof['commit'];connection=campaign.store.connection
    row=(connection.execute('SELECT sha FROM commands WHERE seq=?',(commit['sequence'],)).fetchone()
         if commit['sequence'] else connection.execute('SELECT sha FROM header WHERE id=1').fetchone())
    if row!=(commit['sha256'],):raise RulesViolation('Scheduler upgrade accepted prefix changed')
    if candidate:fence(campaign,proof)
    elif campaign.state().get('scheduler_upgrade')!=digest(proof):
        raise RulesViolation('Scheduler upgrade is not recorded in the host journal')


def install(path,before,after,*,root=PROJECT_ROOT):
    from .primitive_campaign import PrimitiveCampaign
    path=Path(path).resolve()
    with locked(path,'host-driver',timeout=0):
        marker=read(path/'host_runtime/process.json',{})
        proof={'schema':1,'scope':'empty_combat_own_upkeep','binding':read(path/'cohort.json',{})['binding'],
               'commit':marker.get('commit'),'before':read(before),'after':read(after)}
        campaign=PrimitiveCampaign.open(path,root=root,recover=False,scheduler_upgrade=proof)
        try:
            # Full deterministic replay, never a submission to the running game.
            archive=campaign.store.archive()
            replay=RulesActorAdapter.replay(archive,tuple(campaign.kernel.definitions.values()))
            if replay.kernel.snapshot()!=campaign.kernel.snapshot():
                raise RulesViolation('Scheduler upgrade replay differs from current state')
            with campaign.transaction() as state:
                existing=state.get('scheduler_upgrade')
                if existing and existing!=digest(proof):raise RulesViolation('Different scheduler upgrade already installed')
                if not existing:
                    state['scheduler_upgrade']=digest(proof)
                    for actor,seat in state['actors'].items():
                        seat['snooze']=None
                        campaign.record(actor,'scheduler_upgrade',{'commit':proof['commit'],'sha256':digest(proof),
                            'notice':'Existing snooze cleared at authorized upgrade. All future snoozes end at own next upkeep; forced empty attacks retain snoozes.'})
            write(path/'host_runtime/scheduler_upgrade.json',proof)
            return {'installed':True,'commit':proof['commit'],'sha256':digest(proof),'replay_verified':True}
        finally:campaign.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort',type=Path,required=True)
    parser.add_argument('--before',type=Path,required=True)
    parser.add_argument('--after',type=Path,required=True)
    args=parser.parse_args()
    import json
    print(json.dumps(install(args.cohort,args.before,args.after)))


if __name__=='__main__':main()
