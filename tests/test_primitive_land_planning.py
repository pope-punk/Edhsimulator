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
        self.land_line(False)

    def test_combined_planner_publication_can_be_approved_as_one_mana_batch(self):
        self.land_line(True)

    def land_line(self,planner):
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
        if planner:
            from edh_gauntlet import primitive_planning as planning
            # Finish the real opening strategic job, then publish one atomic tactical job.
            job=planning.claim(game,'Omo',planning.LONG)
            planning.publish(game,'Omo',planning.LONG,job['job_id'],'long_term',
                {'long_term_plan':'Develop mana in the fixture.','diplomacy':[{'id':'fixture','text':'Fixture public note.','expires_turn':999}]})
            job=planning.claim(game,'Omo',planning.SHORT)
            proposal={'action_sequence':[{**step,'seat_turn':1,'phase':'precombat_main',
                      'rationale':args['rationale'],'scheduler':args['scheduler']} for step in args['sequence']],
                      'phase_coverage':{phase:({'status':'planned'} if phase=='precombat_main' else {'status':'no_action','reason':'Fixture.'}) for phase in planning.PHASES}}
            planning.publish(game,'Omo',planning.SHORT,job['job_id'],'short_term_and_actions',
                {'short_term':{'short_term_plan':'Play Forest, tap it and cast Bauble.','continuity':'No land played.',
                               'long_term_validity':'valid' if 'long_term' in job['plans'] else 'pending','long_term_invalid_reason':''},'actions':proposal})
            # Existing claims are immutable; model a new delivery before approving the new plan.
            with game.transaction() as state:state['claim']=None
            frozen=actions.claim(game,'Omo');runner.inputs[thread]=frozen
            args={'batch':{'approve_ids':['land','tap','cast'],'reject_ids':[],'pass_priority':False}}
        runner.handle({'id':'land-line','method':'item/tool/call','params':{'threadId':thread,
            'turnId':runner.running[thread],'callId':'land-line','tool':'edh_act','arguments':args}})
        before=game.store.generation
        for _ in range(3):self.assertTrue(actions.automatic(game))
        self.assertEqual(before+3,game.store.generation)
        self.assertEqual(1,runner.tool_counts[thread])
        self.assertEqual(Zone.STACK,game.kernel.state.get(game.kernel.state.current(bauble.card_id)).zone)
        self.assertTrue(game.kernel.state.get(game.kernel.state.current(forest.card_id)).tapped)

    def test_host_plays_glasswing_back_land_with_explicit_face(self):
        from edh_gauntlet.primitive_host import COMMANDS
        self.assertIn('play_land:{kind:"play_land",source:REF,face:"front"|"back"}',COMMANDS)
        directory=self.enterContext(TemporaryDirectory())
        game=PrimitiveCampaign._create(Path(directory)/'game',seed=93,starting_player='Elenda')
        self.addCleanup(game.close)
        while game.kernel.pending_choice:
            choice=game.kernel.pending_choice
            game.submit(choice.actor,'keep:'+str(game.store.generation),
                {'kind':'answer','request_id':choice.request_id,'revision':game.kernel.revision,
                 'indexes':[0] if choice.kind=='mulligan' else []},rationale='Offline setup.')
        while game.kernel.phase!='precombat_main':
            game.submit(game.kernel.priority,'pass:'+str(game.store.generation),
                {'kind':'pass','revision':game.kernel.revision},rationale='Offline setup.')
        card=game.kernel.state.add_card('fixture-modal','catalog:glasswing-grace-age-graced-chapel','Elenda',Zone.HAND)
        server=FakeServer();runner=PrimitiveRunner(game,server);self.addCleanup(runner.timing.close)
        runner.pump();thread=runner.lanes[('Elenda','decider')]
        before=game.store.generation
        runner.handle({'id':'modal-land','method':'item/tool/call','params':{'threadId':thread,
            'turnId':runner.running[thread],'callId':'modal-land','tool':'edh_act','arguments':{
                'sequence':[{'id':'land','command':{'kind':'play_land','source':card.to_json(),'face':'back'}}],
                'rationale':'Play the back land face.','scheduler':{'mode':'hold_full_control'}}}})
        self.assertTrue(actions.automatic(game))
        self.assertEqual(before+1,game.store.generation)
        current=game.kernel.state.get(game.kernel.state.current(card.card_id))
        self.assertEqual(Zone.BATTLEFIELD,current.zone)
        self.assertTrue(current.back_face)
        self.assertEqual(1,game.kernel.turn_schedule['land_plays'])
