"""Explicit stopped-host telemetry repair; never changes a bound game contract."""
import argparse
from pathlib import Path
from .paths import PROJECT_ROOT
from .rules_adapter import digest
from .rules_state import RulesViolation
from .runtime_store import read, write, locked
from .primitive_release import CHECKS, SCOPE, fingerprint

ALLOWED = {'host_telemetry.py', 'primitive_campaign.py', 'primitive_telemetry_repair.py'}
SHARED = {'host_runtime.py', 'host_routing.py', 'host_failures.py', 'host_telemetry.py',
          'communications.py', 'agent_architecture.py', 'scheduler.py'}


def host_hash(modules):
    return digest({name:sha for name,sha in modules.items()
                   if name.startswith('primitive_') or name in SHARED})


def checked_release(receipt):
    body = receipt['evidence']
    if (receipt['sha256'] != digest(body) or body['schema'] != 1 or body['scope'] != SCOPE
            or body['checks'] != {key:True for key in CHECKS}
            or type(body['test_count']) is not int or body['test_count'] < 1):
        raise RulesViolation('Telemetry repair requires complete release evidence')
    return body['fingerprint']


def validate(proof, binding, config, root):
    try:
        if proof['schema'] != 1 or proof['binding'] != binding:
            raise RulesViolation('Telemetry repair binding changed')
        old = checked_release(proof['before']); new = checked_release(proof['after'])
        if new != fingerprint(root) or host_hash(old['modules']) != config['host_implementation']:
            raise RulesViolation('Telemetry repair implementation mismatch')
        if {k:v for k,v in old.items() if k != 'modules'} != {k:v for k,v in new.items() if k != 'modules'}:
            raise RulesViolation('Telemetry repair cannot change rules, assets, policy or strategy')
        changed = {k for k in old['modules'].keys() | new['modules'].keys()
                   if old['modules'].get(k) != new['modules'].get(k)}
        if not changed or not changed <= ALLOWED or 'host_telemetry.py' not in changed:
            raise RulesViolation('Changes exceed the telemetry repair scope')
        commit = proof['commit']
        if type(commit['sequence']) is not int or commit['sequence'] < 0 or type(commit['sha256']) is not str:
            raise RulesViolation('Invalid telemetry repair prefix')
    except (KeyError, TypeError, ValueError) as exc:
        raise RulesViolation('Incomplete telemetry repair evidence') from exc


def fence(campaign, proof):
    previous = read(campaign.root/'host_runtime/process.json', {})
    state = campaign.state()
    if (previous.get('active') is not False or previous.get('contexts_unloaded') is not True
            or previous.get('binding') != campaign.binding
            or previous.get('generation') != state['transport_generation']
            or previous.get('commit') != proof['commit']
            or campaign.store.committed_head() != proof['commit']
            or state.get('terminal') or state.get('blocker')
            or (state.get('paused') or {}).get('reason') != 'host_stopped'):
        raise RulesViolation('Telemetry repair requires an exact fenced host-stopped prefix')


def verify_prefix(campaign, proof, *, candidate=False):
    commit = proof['commit']; connection = campaign.store.connection
    row = (connection.execute('SELECT sha FROM commands WHERE seq=?', (commit['sequence'],)).fetchone()
           if commit['sequence'] else connection.execute('SELECT sha FROM header WHERE id=1').fetchone())
    if row != (commit['sha256'],):
        raise RulesViolation('Telemetry repair accepted prefix changed')
    if candidate:
        fence(campaign, proof)
    elif campaign.state().get('telemetry_repair') != digest(proof):
        raise RulesViolation('Telemetry repair is not recorded in the host journal')


def install(path, before, after, *, root=PROJECT_ROOT):
    from .primitive_campaign import PrimitiveCampaign
    path = Path(path).resolve()
    with locked(path, 'host-driver', timeout=0):
        marker = read(path/'host_runtime/process.json', {})
        proof = {'schema':1, 'binding':read(path/'cohort.json', {})['binding'],
                 'commit':marker.get('commit'), 'before':read(before), 'after':read(after)}
        campaign = PrimitiveCampaign.open(path, root=root, recover=False, telemetry_repair=proof)
        try:
            with campaign.transaction() as state:
                existing = state.get('telemetry_repair')
                if existing and existing != digest(proof):
                    raise RulesViolation('A different telemetry repair is already installed')
                if not existing:
                    state['telemetry_repair'] = digest(proof)
                    for actor in state['actors']:
                        campaign.record(actor, 'transport_repair', {'scope':'telemetry', 'sha256':digest(proof),
                                                                   'commit':proof['commit']})
            write(path/'host_runtime/telemetry_repair.json', proof)
            return {'installed':True, 'commit':proof['commit'], 'sha256':digest(proof)}
        finally:
            campaign.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort', type=Path, required=True)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    args = parser.parse_args()
    import json
    print(json.dumps(install(args.cohort, args.before, args.after)))


if __name__ == '__main__':
    main()
