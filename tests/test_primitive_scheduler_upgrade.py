"""Scheduler upgrades preserve the accepted game and reject broader migrations."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from edh_gauntlet import primitive_scheduler_upgrade as repair
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet.primitive_release import fingerprint, CHECKS, SCOPE
from edh_gauntlet.rules_adapter import digest
from edh_gauntlet.rules_state import RulesViolation
from edh_gauntlet.runtime_store import write, read


def receipt(fp):
    body = {'schema':1, 'scope':SCOPE, 'fingerprint':fp, 'checks':{k:True for k in CHECKS}, 'test_count':10}
    return {'evidence':body, 'sha256':digest(body)}


class SchedulerUpgradeTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.path = self.base/'cohort'
        self.new = fingerprint(); self.old = deepcopy(self.new)
        self.old['modules']['primitive_actions.py'] = 'old-actions'
        self.old['modules']['rules_combat.py'] = 'old-combat'
        self.old['modules']['primitive_campaign.py'] = 'old-campaign'
        self.old['modules'].pop('primitive_scheduler_upgrade.py')
        with patch('edh_gauntlet.primitive_campaign.host_implementation', return_value=repair.host_hash(self.old['modules'])):
            campaign = PrimitiveCampaign._create(self.path, seed=19, starting_player='Omo')
        self.binding = campaign.binding; self.config = campaign.config
        while campaign.kernel.pending_choice:
            choice=campaign.kernel.pending_choice
            campaign.submit(choice.actor,'setup:'+str(campaign.store.generation),
                {'kind':'answer','revision':campaign.kernel.revision,'request_id':choice.request_id,
                 'indexes':[0] if choice.kind=='mulligan' else []},rationale='Offline upgrade fixture.')
        with campaign.transaction() as state:
            state['paused'] = {'reason':'host_stopped'}
        self.state = campaign.state(); self.commit = campaign.store.committed_head()
        campaign.close()
        self.process = {'active':False, 'contexts_unloaded':True, 'binding':self.binding,
                        'generation':0, 'commit':self.commit}
        write(self.path/'host_runtime/process.json', self.process)
        self.before = self.base/'before.json'; self.after = self.base/'after.json'
        write(self.before, receipt(self.old)); write(self.after, receipt(self.new))

    def test_install_is_idempotent_and_preserves_game_state_and_contract(self):
        with self.assertRaises(RulesViolation):PrimitiveCampaign.open(self.path, recover=False)
        result = repair.install(self.path, self.before, self.after)
        campaign = PrimitiveCampaign.open(self.path, recover=False)
        state = campaign.state(); state.pop('scheduler_upgrade')
        self.assertEqual(self.state, state)
        self.assertEqual(self.commit, campaign.store.committed_head())
        count = campaign.store.connection.execute('SELECT COUNT(*) FROM host_evidence').fetchone()[0]
        campaign.close()
        self.assertEqual(result, repair.install(self.path, self.before, self.after))
        campaign = PrimitiveCampaign.open(self.path, recover=False)
        self.assertEqual(count, campaign.store.connection.execute('SELECT COUNT(*) FROM host_evidence').fetchone()[0])
        campaign.close()
        self.assertEqual(self.config, read(self.path/'game_01/game_config.json'))

    def test_other_module_or_policy_changes_rejected(self):
        for kind, name in [('modules','rules_state.py'), ('assets','data/rules/primitive_cards.json')]:
            old = deepcopy(self.old); old[kind][name] = 'changed'
            proof = {'schema':1,'scope':'empty_combat_own_upkeep','binding':self.binding,'before':receipt(old),'after':receipt(self.new),'commit':self.commit}
            config = {**self.config, 'host_implementation':repair.host_hash(old['modules'])}
            with self.assertRaises(RulesViolation):repair.validate(proof, self.binding, config, Path(__file__).resolve().parents[1])

    def test_active_unloaded_generation_and_prefix_fences(self):
        for change in [{'active':True}, {'contexts_unloaded':False}, {'generation':7}, {'commit':{'sequence':99,'sha256':'bad'}}]:
            write(self.path/'host_runtime/process.json', {**self.process, **change})
            with self.assertRaises(RulesViolation):repair.install(self.path, self.before, self.after)
        self.assertFalse((self.path/'host_runtime/scheduler_upgrade.json').exists())

    def test_sidecar_write_failure_retries_without_duplicate_evidence(self):
        with patch.object(repair, 'write', side_effect=OSError('disk')):
            with self.assertRaises(OSError):repair.install(self.path, self.before, self.after)
        with self.assertRaises(RulesViolation):PrimitiveCampaign.open(self.path, recover=False)
        repair.install(self.path, self.before, self.after)
        campaign = PrimitiveCampaign.open(self.path, recover=False)
        count = campaign.store.connection.execute("SELECT COUNT(*) FROM host_evidence WHERE kind='scheduler_upgrade'").fetchone()[0]
        self.assertEqual(4, count); campaign.close()

    def test_copied_or_tampered_sidecar_cannot_open(self):
        repair.install(self.path, self.before, self.after)
        sidecar = self.path/'host_runtime/scheduler_upgrade.json'
        original = read(sidecar)
        for change in [{'binding':{}}, {'commit':{'sequence':0,'sha256':'bad'}}, {'before':{}}]:
            write(sidecar, {**original, **change})
            with self.assertRaises(RulesViolation):PrimitiveCampaign.open(self.path, recover=False)
        write(sidecar, original)
        campaign = PrimitiveCampaign.open(self.path, recover=False)
        with campaign.transaction() as state:state.pop('scheduler_upgrade')
        campaign.close()
        with self.assertRaises(RulesViolation):PrimitiveCampaign.open(self.path, recover=False)

    def test_replay_failure_does_not_install_upgrade(self):
        with patch.object(repair.RulesActorAdapter,'replay',side_effect=RulesViolation('diverged')):
            with self.assertRaisesRegex(RulesViolation,'diverged'):
                repair.install(self.path,self.before,self.after)
        self.assertFalse((self.path/'host_runtime/scheduler_upgrade.json').exists())

    def test_snoozes_clear_once_but_new_directives_survive_reopen(self):
        with patch('edh_gauntlet.primitive_campaign.host_implementation',return_value=repair.host_hash(self.old['modules'])):
            campaign=PrimitiveCampaign.open(self.path,recover=False)
        directive={'mode':'snooze_table','remaining':9,'time':{'occurrences':9,'edge':'beginning','phase':'upkeep'},'wake_condition':'deadline_only'}
        with campaign.transaction() as state:state['actors']['Omo']['snooze']=directive
        campaign.close()
        repair.install(self.path,self.before,self.after)
        campaign=PrimitiveCampaign.open(self.path,recover=False)
        self.assertIsNone(campaign.state()['actors']['Omo']['snooze'])
        with campaign.transaction() as state:state['actors']['Omo']['snooze']=directive
        campaign.close()
        repair.install(self.path,self.before,self.after)
        campaign=PrimitiveCampaign.open(self.path,recover=False)
        self.assertEqual(directive,campaign.state()['actors']['Omo']['snooze'])
        campaign.close()
