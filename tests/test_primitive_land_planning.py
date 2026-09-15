"""A hand land supplies conditional mana facts for a one-call land/tap/cast line."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet.primitive_host import PrimitiveRunner
from edh_gauntlet.primitive_inspection import action_facts
from edh_gauntlet import primitive_actions as actions
from edh_gauntlet.rules_state import Zone,RulesViolation
from edh_gauntlet.rules_casting import intrinsic_land_mana
from test_primitive_host import FakeServer


class LandPlanningTests(TestCase):
    def test_all_basic_land_types_share_engine_ids_and_colors(self):
        for subtype,color in [('Plains','W'),('Island','U'),('Swamp','B'),('Mountain','R'),('Forest','G')]:
            ability,=intrinsic_land_mana([subtype])
            self.assertEqual('intrinsic-land:'+subtype,ability.ability_id)
            self.assertTrue(ability.cost.tap_source)
            self.assertEqual((color,),ability.effects[0].symbols)
        self.assertEqual((),intrinsic_land_mana(['Gate']))

    def test_hand_forest_can_be_planned_played_tapped_and_spent_from_one_tool_call(self):
        directory=self.enterContext(TemporaryDirectory())
        game=PrimitiveCampaign._create(Path(directory)/'game',seed=93,starting_player='Omo')
        self.addCleanup(game.close)
        while game.kernel.pending_choice:
            choice=game.kernel.pending_choice
            game.submit(choice.actor,'keep:'+str(game.store.generation),
                {'kind':'answer','request_id':choice.request_id,'revision':game.kernel.revision,
                 'indexes':[0] if choice.kind=='mulligan' else []},rationale='Offline setup.')
        while game.kernel.phase!='precombat_main':
            game.submit(game.kernel.priority,'pass:'+str(game.store.generation),
                {'kind':'pass','revision':game.kernel.revision},rationale='Offline setup.')
        forest=game.kernel.state.add_card('fixture-forest','catalog:forest','Omo',Zone.HAND)
        bauble=game.kernel.state.add_card('fixture-bauble','catalog:wayfarer-s-bauble','Omo',Zone.HAND)
        self.assertEqual((),game.kernel.activated_abilities(game.kernel.state.get(forest)))
        server=FakeServer();runner=PrimitiveRunner(game,server);self.addCleanup(runner.timing.close)
        runner.pump();thread=runner.lanes[('Omo','decider')]
        facts=action_facts(runner.inputs[thread]);key=next(row['rules_id'] for row in facts['objects'] if row['source']==forest.to_json())
        rules=facts['rules'][key]
        self.assertNotIn('activated_abilities',rules)
        self.assertIn('Not usable from hand',rules['intrinsic_land_mana']['condition'])
        ability=rules['intrinsic_land_mana']['abilities'][0]['ability_id']
        self.assertEqual('intrinsic-land:Forest',ability)
        args={'sequence':[
            {'id':'land','command':{'kind':'play_land','source':forest.to_json()}},
            {'id':'tap','command':{'kind':'activate','source':{'owned_card':forest.card_id,'zone':'battlefield'},
                'ability_id':ability,'targets':[],'x_value':0,'payment':{'mana':{},'taps':[]}}},
            {'id':'cast','command':{'kind':'cast','source':bauble.to_json(),'targets':[],'x_value':0,'payment':{'mana':{'G':1},'taps':[]}}}],
            'rationale':'Play Forest, produce green and cast Bauble.','scheduler':{'mode':'hold_full_control'}}
        runner.handle({'id':'land-line','method':'item/tool/call','params':{'threadId':thread,
            'turnId':runner.running[thread],'callId':'land-line','tool':'edh_act','arguments':args}})
        before=game.store.generation
        for _ in range(3):self.assertTrue(actions.automatic(game))
        self.assertEqual(before+3,game.store.generation)
        self.assertEqual(1,runner.tool_counts[thread])
        self.assertEqual(Zone.STACK,game.kernel.state.get(game.kernel.state.current(bauble.card_id)).zone)
        self.assertTrue(game.kernel.state.get(game.kernel.state.current(forest.card_id)).tapped)
