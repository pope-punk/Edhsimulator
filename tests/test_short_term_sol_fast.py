"""Bound short-term model/tier settings, with no inference or gameplay."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from edh_gauntlet import agent_architecture as architecture
from edh_gauntlet.host_runtime import Runner
from edh_gauntlet.host_routing import Routing
from edh_gauntlet.runtime_store import write


class SolFastTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); (self.root/'game_01').mkdir()
        self.binding = {'agent_architecture':1, 'planning_contract':4, 'planner_stages':True,
                        'plan_tiers':True, 'context_handling':1, 'short_term_sol_fast':1}
        write(self.root/'game_01'/'game_config.json', self.binding)

    def runner(self):
        runner = Runner.__new__(Runner)
        runner.root = self.root; runner.game = 1; runner.directory = self.root/'host_runtime'
        runner.contexts = SimpleNamespace(enabled=False, values={}, save=Mock())
        runner.routing = Routing(); runner.routing.primary.update(architecture.models(self.root,1))
        runner.server = Mock(); runner.timing = Mock(); runner.metrics = {}
        return runner

    def test_short_term_uses_sol_fast_and_high_effort_only_when_bound(self):
        runner = self.runner(); params = runner.context_parameters('A', architecture.SHORT)
        self.assertEqual('gpt-5.6-sol', params['model'])
        self.assertEqual('fast', params['serviceTier'])
        self.assertEqual('high', params['config']['model_reasoning_effort'])
        self.assertNotIn('serviceTier', runner.context_parameters('A', architecture.LONG))
        self.assertEqual('gpt-5.6-terra', runner.context_parameters('A', 'decider')['model'])

    def test_existing_unbound_games_keep_terra_and_inherited_tier(self):
        self.binding.pop('short_term_sol_fast'); write(self.root/'game_01'/'game_config.json', self.binding)
        params = self.runner().context_parameters('A', architecture.SHORT)
        self.assertEqual('gpt-5.6-terra', params['model'])
        self.assertNotIn('serviceTier', params)

    def test_each_turn_including_capacity_fallback_retains_saved_tier(self):
        runner = self.runner(); runner.threads = {'thread':('A', architecture.SHORT)}
        runner.contexts.values['thread'] = {'model':'gpt-5.6-sol', 'reasoning_effort':'high', 'service_tier':'fast'}
        with patch('edh_gauntlet.host_runtime.write'):
            runner.start_turn('thread','test input')
            self.assertEqual('fast', runner.server.call.call_args.args[1]['serviceTier'])
            runner.routing.overloaded('gpt-5.6-sol'); runner.start_turn('thread','test retry')
        params = runner.server.call.call_args.args[1]
        self.assertEqual('gpt-5.6-terra', params['model'])
        self.assertEqual('fast', params['serviceTier']); self.assertEqual('high', params['effort'])
        self.assertEqual('fast', runner.timing.record.call_args.kwargs['service_tier'])

    def test_checkpoint_replacement_passes_saved_tier_and_effort(self):
        runner = self.runner(); runner.threads = {'thread':('A',architecture.SHORT)}
        runner.contexts.values['thread'] = {'model':'gpt-5.6-sol','reasoning_effort':'high','service_tier':'fast'}
        runner.server.call.side_effect = RuntimeError('test stop before creating transport')
        with self.assertRaisesRegex(RuntimeError,'test stop'): runner.rotate_context('thread')
        method, params = runner.server.call.call_args.args
        self.assertEqual('thread/start', method)
        self.assertEqual('fast', params['serviceTier']); self.assertEqual('gpt-5.6-sol', params['model'])
        self.assertEqual('high', params['config']['model_reasoning_effort'])

    def test_binding_is_versioned_and_requires_split_architecture(self):
        architecture.validate_binding(self.binding)
        for value in (True,2,'1'):
            with self.assertRaises(ValueError): architecture.validate_binding({**self.binding,'short_term_sol_fast':value})
        with self.assertRaises(ValueError): architecture.validate_binding({'short_term_sol_fast':1})

    def test_campaign_propagates_policy_without_retrofitting_persisted_game(self):
        from edh_gauntlet.campaign import game_config, _game_config_with_bound_surface
        manifest = {'target_games':2,'seed_start':1,'max_rounds':2,'decision_surface_revision':6,
            'planning_runtime':{'contract':4,'stages':True,'tiers':True,'context_handling':1,
                                'agent_architecture':1,'short_term_sol_fast':1}}
        fresh = game_config(manifest, 1)
        self.assertEqual(1, fresh['short_term_sol_fast'])
        legacy = {key:value for key,value in fresh.items() if key!='short_term_sol_fast'}
        write(self.root/'game_01'/'game_config.json', legacy)
        self.assertNotIn('short_term_sol_fast', _game_config_with_bound_surface(self.root, manifest, 1))
        self.assertEqual(1, _game_config_with_bound_surface(self.root, manifest, 2)['short_term_sol_fast'])
