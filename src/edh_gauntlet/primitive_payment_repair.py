"""User-authorized filter-payment repair at an exact unloaded host frontier.

The bound contract, accepted tape, strategic choices and engine identity stay
unchanged. A signed-by-digest local receipt records the explicit implementation
exception, with full replay parity before any live input is refreshed.
"""
import argparse
from pathlib import Path
from .paths import PROJECT_ROOT
from .rules_adapter import RulesActorAdapter,digest
from .rules_state import RulesViolation
from .runtime_store import read,write,locked
from .primitive_release import fingerprint
from .primitive_telemetry_repair import checked_release,host_hash

ALLOWED={'primitive_autotap.py','primitive_mana_preferences.py','primitive_action_menu.py',
         'primitive_pilot_document.py','primitive_decider_mana.py','primitive_host.py',
         'primitive_campaign.py','primitive_payment_repair.py'}
AUTHORIZATION='fix these items and resume the game'


def validate(proof,binding,config,root):
    try:
        if (proof['schema']!=1 or proof['scope']!='pure_filter_autotap' or proof['binding']!=binding
                or proof['authorization']!=AUTHORIZATION):raise RulesViolation('Payment repair binding or authority changed')
        old=checked_release(proof['before']);new=checked_release(proof['after'])
        if new!=fingerprint(root) or host_hash(old['modules'])!=config['host_implementation']:
            raise RulesViolation('Payment repair implementation mismatch')
        changed={k for k in old['modules'].keys()|new['modules'].keys() if old['modules'].get(k)!=new['modules'].get(k)}
        if not {'primitive_autotap.py','primitive_payment_repair.py'}<=changed or not changed<=ALLOWED:
            raise RulesViolation('Changes exceed the filter-payment repair scope')
        if {k:v for k,v in old.items() if k!='modules'}!={k:v for k,v in new.items() if k!='modules'}:
            raise RulesViolation('Payment repair cannot change rules identity, assets, policy, strategy or web code')
        if config.get('autotap')!=1 or config.get('automatic_decider_mana')!=1 or config.get('pilot_document')!=1:
            raise RulesViolation('Payment repair requires the existing automatic-mana document contract')
        if type(proof['commit']['sequence']) is not int or type(proof['commit']['sha256']) is not str:
            raise RulesViolation('Invalid repair frontier')
    except (KeyError,TypeError,ValueError) as e:raise RulesViolation('Incomplete payment repair proof') from e


def verify_prefix(campaign,proof,*,candidate=False):
    expected=proof['commit'];db=campaign.store.connection
    row=db.execute('SELECT sha FROM commands WHERE seq=?',(expected['sequence'],)).fetchone() if expected['sequence'] else db.execute('SELECT sha FROM header WHERE id=1').fetchone()
    if row!=(expected['sha256'],):raise RulesViolation('Payment repair accepted prefix changed')
    state=campaign.state()
    if not candidate:
        if state.get('payment_repair')!=digest(proof):raise RulesViolation('Payment repair is not recorded')
        return
    from .primitive_recovery import verify_exited
    process=read(campaign.root/'host_runtime/process.json',{})
    if (process.get('active') is not False or process.get('contexts_unloaded') is not True
        or process.get('binding')!=campaign.binding or process.get('generation')!=state['transport_generation']
        or process.get('commit')!=expected or campaign.store.committed_head()!=expected
        or state.get('terminal') or state.get('blocker') or state.get('pending')
        or (state.get('paused') or {}).get('reason') not in ('host_stopped','pilot_help_requested','pilot_help_answered')
        or (campaign.root/'HOST_PAUSED.json').exists()):raise RulesViolation('Payment repair requires an exact stopped technical frontier')
    verify_exited(process['host_identity'])
    verify_exited(process['transport_identity'],session=process.get('transport_session'))


def install(path,before,after,*,root=PROJECT_ROOT):
    from .primitive_campaign import PrimitiveCampaign
    path=Path(path).resolve()
    with locked(path,'host-driver',timeout=0):
        process=read(path/'host_runtime/process.json',{})
        proof={'schema':1,'scope':'pure_filter_autotap','authorization':AUTHORIZATION,
               'binding':read(path/'cohort.json',{})['binding'],'commit':process.get('commit'),
               'before':read(before),'after':read(after)}
        campaign=PrimitiveCampaign.open(path,root=root,recover=False,payment_repair=proof)
        try:
            replay=RulesActorAdapter.replay(campaign.store.archive(),tuple(campaign.kernel.definitions.values()))
            if replay.kernel.snapshot()!=campaign.kernel.snapshot():raise RulesViolation('Payment repair replay differs from accepted state')
            with campaign.transaction() as state:
                existing=state.get('payment_repair')
                if existing and existing!=digest(proof):raise RulesViolation('Different payment repair already installed')
                if not existing:
                    state['payment_repair']=digest(proof)
                    if state.get('claim'):
                        from .primitive_action_menu import freeze
                        claim=state['claim'];claim['_action_menu']=freeze(campaign,claim['actor'],claim)
                        claim['technical_update']='Automatic payment now handles supported pure paid mana filters and their color choices. Submit the intended spell/ability without mana instructions. The original decision, board, plans and accepted actions are preserved.'
                    for actor in state['actors']:
                        campaign.record(actor,'payment_repair',{'commit':proof['commit'],'sha256':digest(proof),'scope':proof['scope']})
            write(path/'host_runtime/payment_repair.json',proof)
            return {'installed':True,'commit':proof['commit'],'sha256':digest(proof),'replay_verified':True}
        finally:campaign.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cohort',type=Path,required=True);p.add_argument('--before',type=Path,required=True);p.add_argument('--after',type=Path,required=True)
    a=p.parse_args()
    import json
    print(json.dumps(install(a.cohort,a.before,a.after)))

if __name__=='__main__':main()
