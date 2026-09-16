import unittest
import test_primitive_batch_choices as fixtures
from edh_gauntlet import primitive_actions as actions
from edh_gauntlet.primitive_autotap import validate
from edh_gauntlet.rules_state import Zone,RulesViolation

class AutotapTests(unittest.TestCase):
    setUp=fixtures.ManaBatchTests.setUp
    send=fixtures.ManaBatchTests.send
    main=fixtures.ManaBatchTests.main
    land=fixtures.ManaBatchTests.land
    def card(self,name,zone):
        return self.game.kernel.state.add_card('autotap-'+name,'catalog:'+name,'Omo',zone)

    def command(self,reserve=None):
        ref=self.card('wayfarer-s-bauble',Zone.HAND)
        cmd={'kind':'cast','source':ref.to_json(),'targets':[],'x_value':0}
        if reserve is not None:cmd['autotap']={'reserve':reserve}
        return cmd

    def submit(self,cmd):
        frozen=actions.claim(self.game,'Omo')
        return actions.submit(self.game,'Omo',frozen['claim_id'],'autotap-test',cmd,'Offline test.',{'mode':'hold_full_control'})

    def test_default_cast_bundles_tap_and_payment(self):
        cmd=self.command();before=self.game.store.generation
        self.submit(cmd)
        self.assertEqual(before+1,self.game.store.generation)
        self.assertEqual(Zone.STACK,self.game.kernel.state.get(self.game.kernel.state.current(cmd['source']['card_id'])).zone)
        record=self.game.evidence('Omo',kinds=('rationale',))[-1]['value']['command']
        self.assertTrue(record['payment']['mana_actions'])
        self.assertNotIn('autotap',record)

    def test_reserve_blue_keeps_island(self):
        self.submit(self.command({'U':1}))
        self.assertFalse(self.game.kernel.state.get(self.island).tapped)
        self.assertTrue(self.game.kernel.state.get(self.grove).tapped)

    def test_impossible_reservation_is_atomic(self):
        cmd=self.command({'W':1});head=self.game.store.committed_head()
        with self.assertRaisesRegex(RulesViolation,'preserving'):self.submit(cmd)
        self.assertEqual(head,self.game.store.committed_head())
        self.assertFalse(self.game.kernel.state.get(self.island).tapped)
        self.assertIsNotNone(self.game.state()['claim'])

    def test_flexible_source_reserve_black_spends_white_elsewhere(self):
        snarl=self.card('shineshadow-snarl',Zone.BATTLEFIELD)
        # Reserve both existing sources as well, forcing Snarl to produce white.
        cmd=self.command({'U':1,'C':1})
        self.submit(cmd)
        self.assertTrue(self.game.kernel.state.get(snarl).tapped)
        record=self.game.evidence('Omo',kinds=('rationale',))[-1]['value']['command']
        self.assertEqual(['activate','answer'],[r['kind'] for r in record['payment']['mana_actions']])

    def test_old_contract_requires_explicit_payment(self):
        self.game.config.pop('autotap')
        with self.assertRaisesRegex(RulesViolation,'fresh autotap'):self.submit(self.command())

    def test_manual_payment_overrides_default(self):
        cmd=self.command();cmd['payment']={'mana':{},'taps':[]}
        head=self.game.store.committed_head()
        with self.assertRaises(RulesViolation):self.submit(cmd)
        self.assertEqual(head,self.game.store.committed_head())

    def test_reservation_schema_rejects_booleans_and_unknowns(self):
        for reserve in ({'B':True},{'purple':1},{'B':-1}):
            with self.assertRaises(RulesViolation):validate({'kind':'cast','autotap':{'reserve':reserve}})

    def test_decider_override_changes_planner_reservation(self):
        snarl=self.card('shineshadow-snarl',Zone.BATTLEFIELD)
        # One flexible source can preserve black OR white, never both.
        cmd=self.command({'B':1})
        frozen=actions.claim(self.game,'Omo')
        turn=self.game.state()['actors']['Omo']['turns']
        step={'id':'cast','seat_turn':turn,'phase':'precombat_main','command':cmd,
              'rationale':'Synthetic planner proposal.','scheduler':{'mode':'hold_full_control'}}
        with self.game.transaction() as state:
            state['claim']['plans']['actions']={'id':'synthetic-proposal','value':{'action_sequence':[step]}}
        from copy import deepcopy
        override=deepcopy(step);override['command']['autotap']['reserve']={'W':1}
        actions.approve(self.game,'Omo',frozen['claim_id'],approve_ids=['cast'],reject_ids=[],overrides={'cast':override})
        self.assertEqual({'W':1},self.game.state()['actors']['Omo']['approved']['steps'][0]['command']['autotap']['reserve'])
        before=self.game.store.generation
        self.assertTrue(actions.automatic(self.game))
        self.assertEqual(before+1,self.game.store.generation)
        self.assertFalse(self.game.kernel.state.get(snarl).tapped)
        self.assertEqual(['cast'],self.game.state()['actors']['Omo']['executed_steps']['synthetic-proposal'])

    def test_one_flexible_source_cannot_reserve_two_colors(self):
        self.card('shineshadow-snarl',Zone.BATTLEFIELD)
        with self.assertRaisesRegex(RulesViolation,'preserving'):self.submit(self.command({'W':1,'B':1}))

    def test_serialized_payment_replays_exactly(self):
        from edh_gauntlet.rules_adapter import RulesActorAdapter
        kernel=self.game.kernel;cmd=self.command({'U':1})
        before=kernel.snapshot()
        self.submit(cmd)
        recorded=self.game.evidence('Omo',kinds=('rationale',))[-1]['value']['command']
        replay=type(kernel).restore(before,kernel._base_definitions.values())
        RulesActorAdapter(replay)._execute('Omo',recorded)
        self.assertEqual(kernel.snapshot(),replay.snapshot())

    def test_invalid_final_payment_does_not_tap_sources(self):
        from edh_gauntlet.rules_adapter import RulesActorAdapter
        kernel=self.game.kernel;cmd=self.command();cmd=actions.bind_command(self.game,'Omo',cmd,'bad-final')
        cmd['payment']['mana']={}
        before=kernel.snapshot()
        with self.assertRaises(RulesViolation):RulesActorAdapter(kernel)._execute('Omo',cmd)
        self.assertEqual(before,kernel.snapshot())

    def test_city_trigger_does_not_disable_other_sources(self):
        city=self.card('city-of-brass',Zone.BATTLEFIELD)
        self.submit(self.command({'U':1}))
        self.assertFalse(self.game.kernel.state.get(city).tapped)
        self.assertTrue(self.game.kernel.state.get(self.grove).tapped)

    def test_activation_defaults_to_autotap_with_explicit_ability_choice(self):
        ref=self.card('wayfarer-s-bauble',Zone.BATTLEFIELD)
        ability=self.game.kernel.activated_abilities(self.game.kernel.state.get(ref))[0]
        cmd={'kind':'activate','source':ref.to_json(),'ability_id':ability.ability_id,'targets':[],'x_value':0}
        self.submit(cmd)
        self.assertTrue(self.game.kernel.state.get(self.island).tapped)
        self.assertTrue(self.game.kernel.state.get(self.grove).tapped)
        self.assertEqual(Zone.GRAVEYARD,self.game.kernel.state.get(self.game.kernel.state.current(ref.card_id)).zone)

    def test_direct_sequence_defaults_to_autotap(self):
        cmd=self.command({'U':1});frozen=actions.claim(self.game,'Omo')
        actions.approve_sequence(self.game,'Omo',frozen['claim_id'],sequence=[{'id':'cast','command':cmd}],
            rationale='Synthetic direct line.',scheduler={'mode':'hold_full_control'})
        self.assertTrue(actions.automatic(self.game))
        self.assertFalse(self.game.kernel.state.get(self.island).tapped)
        self.assertEqual(1,self.game.state()['actors']['Omo']['approved']['cursor'])

    def test_reserved_capacity_excludes_explicit_sacrifice(self):
        # Crop Rotation's author-selected sacrificed land cannot also be held back.
        forest=self.card('forest',Zone.BATTLEFIELD)
        ref=self.card('crop-rotation',Zone.HAND)
        spec=self.game.kernel.definition(self.game.kernel.state.get(ref)).cast
        cost=spec.cost.zone_costs[0]
        cmd={'kind':'cast','source':ref.to_json(),'targets':[],'x_value':0,
             'autotap':{'reserve':{'U':1}},
             'payment':{'mana':{},'taps':[], 'zone_costs':{cost.cost_id:[self.island.to_json()]}}}
        before=self.game.store.committed_head()
        with self.assertRaisesRegex(RulesViolation,'preserv'):self.submit(cmd)
        self.assertEqual(before,self.game.store.committed_head())
        self.assertFalse(self.game.kernel.state.get(forest).tapped)

    def test_zero_mana_loyalty_ability_uses_default_empty_payment(self):
        from edh_gauntlet.rules_program import LoyaltyCost
        kernel=self.game.kernel
        definition=next(key for key,d in kernel.definitions.items() if d.name=='Minsc & Boo, Timeless Heroes')
        ref=kernel.state.add_card('autotap-walker',definition,'Omo',Zone.BATTLEFIELD)
        ability=next(a for a in kernel.activated_abilities(kernel.state.get(ref)) if isinstance(a.cost,LoyaltyCost) and a.cost.loyalty>0)
        self.submit({'kind':'activate','source':ref.to_json(),'ability_id':ability.ability_id,'targets':[],'x_value':0})
        self.assertFalse(kernel.state.get(self.island).tapped)
        self.assertFalse(kernel.state.get(self.grove).tapped)

    def tag(self,symbol='U',rider='copy'):
        state=self.game.kernel.state
        state.add_special_mana('Omo',(symbol,),rider,state.get(self.island))
        return next(reversed(state.mana_tags('Omo')))

    def test_selected_tag_plus_autotapped_remainder_replays(self):
        from edh_gauntlet.rules_adapter import RulesActorAdapter
        tag=self.tag();self.card('forest',Zone.BATTLEFIELD)
        ref=self.card('cultivate',Zone.HAND)
        cmd={'kind':'cast','source':ref.to_json(),'targets':[],'x_value':0,'autotap':{'tagged_mana':[tag]}}
        kernel=self.game.kernel;before=kernel.snapshot()
        self.submit(cmd)
        recorded=self.game.evidence('Omo',kinds=('rationale',))[-1]['value']['command']
        self.assertEqual([tag],recorded['payment']['tagged_mana'])
        self.assertEqual(3,sum(recorded['payment']['mana'].values()))
        self.assertTrue(recorded['payment']['mana_actions'])
        self.assertNotIn(tag,kernel.state.mana_tags('Omo'))
        replay=type(kernel).restore(before,kernel._base_definitions.values())
        RulesActorAdapter(replay)._execute('Omo',recorded)
        self.assertEqual(kernel.snapshot(),replay.snapshot())

    def test_default_does_not_spend_unselected_tag(self):
        tag=self.tag();self.submit(self.command())
        self.assertIn(tag,self.game.kernel.state.mana_tags('Omo'))
        recorded=self.game.evidence('Omo',kinds=('rationale',))[-1]['value']['command']
        self.assertNotIn('tagged_mana',recorded['payment'])
        self.assertTrue(recorded['payment']['mana_actions'])

    def test_tag_restrictions_remain_atomic(self):
        tag=self.tag(rider='legendary');cmd=self.command();cmd['autotap']={'tagged_mana':[tag]}
        head=self.game.store.committed_head()
        with self.assertRaisesRegex(RulesViolation,'legendary'):self.submit(cmd)
        self.assertEqual(head,self.game.store.committed_head())
        self.assertIn(tag,self.game.kernel.state.mana_tags('Omo'))
        self.assertFalse(self.game.kernel.state.get(self.island).tapped)

    def test_tag_selection_requires_current_unique_ids(self):
        cmd=self.command()
        for tags in (['missing'],['x','x'],[None]):
            cmd['autotap']={'tagged_mana':tags}
            with self.assertRaises(RulesViolation):self.submit(cmd)

    def test_unselected_tag_does_not_satisfy_reserve(self):
        self.tag('W');cmd=self.command({'W':1})
        with self.assertRaisesRegex(RulesViolation,'preserving'):self.submit(cmd)

    def test_opponent_stack_spell_rules_are_delivered_without_hidden_hand(self):
        import json
        from edh_gauntlet.primitive_inspection import freeze,action_facts
        cmd=self.command();self.submit(cmd)
        board=self.game.store.packet('Elenda')
        knowledge=freeze(self.game,'Elenda',board)
        ref=board['stack'][-1]['source']
        self.assertIn(json.dumps(ref,sort_keys=True),knowledge)
        facts=action_facts({'_knowledge':knowledge})
        self.assertIn(ref,[row['source'] for row in facts['objects']])
        hidden=self.game.store.packet('Omo')['hand'][0]['ref']
        self.assertNotIn(json.dumps(hidden,sort_keys=True),knowledge)
