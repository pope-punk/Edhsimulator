import unittest
from copy import deepcopy
from edh_gauntlet.primitive_command_schema import validate
from edh_gauntlet.rules_state import RulesViolation
from test_primitive_planning import PrimitivePlanningTests as _Fixture
from edh_gauntlet import primitive_planning as planning

class CommandSchemaTests(unittest.TestCase):
    def test_empty_land_targets_are_canonicalized(self):
        command={'kind':'play_land','source':{'owned_card':'island','zone':'hand'},'targets':[]}
        validate(command)
        self.assertNotIn('targets',command)

    def test_meaningful_land_targets_and_unknown_fields_are_rejected(self):
        for extra in ({'targets':[{'player':'Omo'}]},{'x_value':0},{'unexpected':True}):
            with self.assertRaisesRegex(RulesViolation,'play_land command fields'):
                validate({'kind':'play_land','source':{},**extra})

    def test_native_combat_assignment_objects_remain_valid(self):
        validate({'kind':'block','assignments':{'attacker@4':[]}})
        validate({'kind':'damage','assignments':{'attacker@4':{'blockers':{},'defender':2}}})
        with self.assertRaisesRegex(RulesViolation,'requires an object'):
            validate({'kind':'block','assignments':[]})

    def test_symbolic_future_payment_references_remain_valid(self):
        validate({'kind':'activate','source':{'owned_card':'card','zone':'battlefield'},'ability_id':'use','targets':[],'x_value':0,
                  'payment':{'mana':{},'taps':[],'zone_costs':{'sacrifice':[{'owned_card':'food','zone':'battlefield'}]}}})

    def test_generic_is_not_a_payment_mana_type(self):
        base={'kind':'cast','source':{'card_id':'spell','incarnation':0},'targets':[],'x_value':0}
        for mana in ({'W':1,'U':1,'B':1,'generic':1},{'U':True},{'B':-1}):
            with self.assertRaisesRegex(RulesViolation,'actual mana spent'):
                validate({**base,'payment':{'mana':mana,'taps':[]}})
        validate({**base,'payment':{'mana':{'W':2,'U':1,'B':1},'taps':[]}})

    def test_default_target_and_x_fields_are_shared(self):
        command={'kind':'cast','source':{'card_id':'spell','incarnation':0}}
        validate(command)
        self.assertEqual([],command['targets']);self.assertEqual(0,command['x_value'])

    def test_nonmana_selections_keep_automatic_payment(self):
        command={'kind':'activate','source':{'owned_card':'card','zone':'battlefield'},'ability_id':'use',
                 'payment':{'zone_costs':{'sacrifice':[{'owned_card':'food','zone':'battlefield'}]}}}
        validate(command)
        self.assertEqual({},command['autotap'])
        self.assertEqual({},command['payment']['mana'])
        self.assertIn('zone_costs',command['payment'])
        with self.assertRaisesRegex(RulesViolation,'declines only'):
            validate({'kind':'cast','source':{'card_id':'spell','incarnation':0},'payment':None})

class PublicationSchemaTests(unittest.TestCase):
    setUp=_Fixture.setUp
    def test_land_normalization_keeps_raw_retry_idempotent(self):
        job=planning.claim(self.game,'Omo',planning.SHORT)
        prose={'short_term_plan':'Play the proposed land.','continuity':'Fixture.','long_term_validity':'pending','long_term_invalid_reason':''}
        planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'short_term',prose)
        value={'action_sequence':[{'id':'land','seat_turn':1,'phase':'precombat_main','command':{'kind':'play_land','source':{'owned_card':'fixture','zone':'hand'},'targets':[]},'rationale':'Fixture.','scheduler':{'mode':'hold_full_control'}}],
               'phase_coverage':{'precombat_main':{'status':'planned'},'combat':{'status':'no_action','reason':'Fixture.'},'postcombat_main':{'status':'no_action','reason':'Fixture.'}}}
        original=deepcopy(value)
        first=planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'actions',value)
        self.assertEqual(first,planning.publish(self.game,'Omo',planning.SHORT,job['job_id'],'actions',value))
        self.assertEqual(original,value)
        stored=self.game.state()['actors']['Omo']['plans']['actions']['value']['action_sequence'][0]['command']
        self.assertNotIn('targets',stored)

del _Fixture
