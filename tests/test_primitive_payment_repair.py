"""The explicit repair never rewrites a contract, prefix or pilot choice."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from edh_gauntlet import primitive_payment_repair as repair
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet.primitive_release import fingerprint
from edh_gauntlet.primitive_telemetry_repair import host_hash
from edh_gauntlet.rules_state import RulesViolation
from edh_gauntlet.runtime_store import write,read
from test_primitive_telemetry_repair import receipt

class PaymentRepairTests(TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(TemporaryDirectory()));self.path=self.root/'run'
        self.new=fingerprint();self.old=deepcopy(self.new)
        self.old['modules']['primitive_autotap.py']='old-filter-solver'
        self.old['modules'].pop('primitive_payment_repair.py')
        with patch('edh_gauntlet.primitive_campaign.host_implementation',return_value=host_hash(self.old['modules'])):
            game=PrimitiveCampaign._create(self.path,seed=19,starting_player='Omo')
        with game.transaction() as state:state['paused']={'reason':'pilot_help_requested'}
        self.config=deepcopy(game.config);self.binding=deepcopy(game.binding);self.commit=game.store.committed_head();self.state=game.state();game.close()
        ident={'pid':99999999,'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'start_ticks':1}
        self.process={'active':False,'contexts_unloaded':True,'binding':self.binding,'generation':0,'commit':self.commit,
                      'host_identity':ident,'transport_identity':ident,'transport_session':ident['pid']}
        write(self.path/'host_runtime/process.json',self.process)
        self.before=self.root/'before.json';self.after=self.root/'after.json'
        write(self.before,receipt(self.old));write(self.after,receipt(self.new))

    def test_exact_replay_and_idempotent_install_preserve_contract_and_state(self):
        with self.assertRaises(RulesViolation):PrimitiveCampaign.open(self.path,recover=False)
        result=repair.install(self.path,self.before,self.after)
        self.assertTrue(result['replay_verified'])
        self.assertEqual(result,repair.install(self.path,self.before,self.after))
        game=PrimitiveCampaign.open(self.path,recover=False)
        try:
            state=game.state();state.pop('payment_repair')
            self.assertEqual(self.state,state);self.assertEqual(self.commit,game.store.committed_head())
            self.assertEqual(self.config,game.config)
        finally:game.close()

    def test_pause_active_process_and_frontier_mismatch_block_install(self):
        for change in ({'active':True},{'contexts_unloaded':False},{'generation':2},{'commit':{'sequence':1,'sha256':'other'}}):
            write(self.path/'host_runtime/process.json',{**self.process,**change})
            with self.assertRaises(RulesViolation):repair.install(self.path,self.before,self.after)
        write(self.path/'host_runtime/process.json',self.process)
        write(self.path/'HOST_PAUSED.json',{'reason':'user_stop'})
        with self.assertRaises(RulesViolation):repair.install(self.path,self.before,self.after)
        self.assertFalse((self.path/'host_runtime/payment_repair.json').exists())

    def test_unrelated_changes_are_not_authorized_by_payment_repair(self):
        for kind,name in [('modules','rules_state.py'),('assets','docs/HOST_RUNTIME.md')]:
            old=deepcopy(self.old);old[kind][name]='unrelated-change'
            proof={'schema':1,'scope':'pure_filter_autotap','authorization':repair.AUTHORIZATION,
                   'binding':self.binding,'commit':self.commit,'before':receipt(old),'after':receipt(self.new)}
            with self.assertRaises(RulesViolation):repair.validate(proof,self.binding,{**self.config,'host_implementation':host_hash(old['modules'])},Path(__file__).resolve().parents[1])
