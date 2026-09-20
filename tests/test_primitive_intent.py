"""Whole action lines exercise normalization, waiting and atomic recovery."""
import unittest
from test_primitive_autotap import AutotapTests as _Fixture
from edh_gauntlet import primitive_actions as actions
from edh_gauntlet.rules_state import Zone,RulesViolation

class IntentTests(unittest.TestCase):
    setUp=_Fixture.setUp
    send=_Fixture.send
    main=_Fixture.main
    land=_Fixture.land
    card=_Fixture.card

    def approve(self,commands,passes=True):
        self.game.config['automatic_decider_mana']=1
        frozen=actions.claim(self.game,'Omo')
        steps=[{'id':str(i),'command':c,'seat_turn':2,'phase':'precombat_main',
                'rationale':'Offline integrated intent fixture.','scheduler':{'mode':'hold_full_control'}} for i,c in enumerate(commands)]
        actions.approve(self.game,'Omo',frozen['claim_id'],approve_ids=[],added=steps,pass_priority=passes)

    def resolve(self):
        for _ in range(12):
            if not self.game.kernel.stack:return
            action=self.game.next_action()
            self.assertEqual('priority',action['decision_kind'])
            self.send(action['actor'],{'kind':'pass'})
        self.fail('Fixture stack did not resolve')

    def test_two_sorceries_wait_then_execute_without_replaying(self):
        first=self.card('wayfarer-s-bauble',Zone.HAND)
        second=self.card('expedition-map',Zone.HAND)
        self.approve([{'kind':'cast','source':r.to_json()} for r in (first,second)])
        self.assertTrue(actions.automatic(self.game))
        self.assertEqual(1,self.game.state()['actors']['Omo']['approved']['cursor'])
        self.assertTrue(actions.automatic(self.game)) # authorized pass, not a rejected cast
        self.assertEqual(1,self.game.state()['actors']['Omo']['approved']['cursor'])
        self.resolve()
        self.assertTrue(actions.automatic(self.game))
        self.assertEqual(2,self.game.state()['actors']['Omo']['approved']['cursor'])
        self.assertEqual([],self.game.evidence('Omo',kinds=('batch_rejection',)))
        self.assertEqual(Zone.STACK,self.game.kernel.state.get(self.game.kernel.state.current(second.card_id)).zone)

    def test_wait_does_not_invent_pass_permission(self):
        first=self.card('wayfarer-s-bauble',Zone.HAND);second=self.card('expedition-map',Zone.HAND)
        self.approve([{'kind':'cast','source':r.to_json()} for r in (first,second)],passes=False)
        self.assertTrue(actions.automatic(self.game));head=self.game.store.committed_head()
        self.assertFalse(actions.automatic(self.game))
        self.assertEqual(head,self.game.store.committed_head())
        self.assertEqual(1,self.game.state()['actors']['Omo']['approved']['cursor'])
        self.assertEqual([],self.game.evidence('Omo',kinds=('batch_rejection',)))

    def test_future_activation_validates_without_requiring_present_battlefield(self):
        ref=self.card('wayfarer-s-bauble',Zone.HAND)
        self.card('sol-ring',Zone.BATTLEFIELD)
        ability=next(a for a in self.game.kernel.activated_abilities(self.game.kernel.state.get(ref)) if not a.mana_ability)
        self.approve([{'kind':'cast','source':ref.to_json()},
                      {'kind':'activate','source':{'owned_card':ref.card_id,'zone':'battlefield'},'ability_id':ability.ability_id}])
        self.assertTrue(actions.automatic(self.game));self.assertTrue(actions.automatic(self.game));self.resolve()
        self.assertTrue(actions.automatic(self.game))
        self.assertEqual(2,self.game.state()['actors']['Omo']['approved']['cursor'])
        self.assertEqual(Zone.GRAVEYARD,self.game.kernel.state.get(self.game.kernel.state.current(ref.card_id)).zone)

    def test_room_unlock_uses_the_same_automatic_payment_path(self):
        room=self.card('funeral-room-awakening-hall',Zone.BATTLEFIELD)
        self.card('swamp',Zone.BATTLEFIELD)
        before=self.game.kernel.snapshot()
        self.approve([{'kind':'unlock_room','source':room.to_json(),'door':'left'}])
        self.assertTrue(actions.automatic(self.game),self.game.state()['actors']['Omo'].get('last_rejection'))
        self.assertIn('left',self.game.kernel.state.get(room).unlocked)
        command=self.game.evidence('Omo',kinds=('rationale',))[-1]['value']['command']
        self.assertTrue(command['payment']['mana_actions'])
        from edh_gauntlet.rules_adapter import RulesActorAdapter
        trial=type(self.game.kernel).restore(before,self.game.kernel._base_definitions.values())
        RulesActorAdapter(trial)._execute('Omo',command)
        self.assertEqual(self.game.kernel.snapshot(),trial.snapshot())

    def nonmana(self,route):
        self.game.config['automatic_decider_mana']=1
        self.card('forest',Zone.BATTLEFIELD);ref=self.card('crop-rotation',Zone.HAND)
        spec=self.game.kernel.definition(self.game.kernel.state.get(ref)).cast
        command={'kind':'cast','source':ref.to_json(),
                 'payment':{'zone_costs':{spec.cost.zone_costs[0].cost_id:[self.island.to_json()]}}}
        if route=='batch':self.approve([command]);self.assertTrue(actions.automatic(self.game))
        else:
            frozen=actions.claim(self.game,'Omo')
            if route=='direct':
                actions.submit(self.game,'Omo',frozen['claim_id'],'nonmana-test',command,'Offline fixture.',{'mode':'hold_full_control'})
            else:
                original={'id':'crop','seat_turn':2,'phase':'precombat_main','command':{'kind':'pass'},
                          'rationale':'Offline fixture.','scheduler':{'mode':'hold_full_control'}}
                with self.game.transaction() as state:
                    state['claim']['plans']['actions']={'id':'fixture-plan','value':{'action_sequence':[original]}}
                actions.approve(self.game,'Omo',frozen['claim_id'],approve_ids=['crop'],overrides={'crop':{'command':command}})
                self.assertTrue(actions.automatic(self.game))
        self.assertEqual(Zone.GRAVEYARD,self.game.kernel.state.get(self.game.kernel.state.current(self.island.card_id)).zone)
        accepted=self.game.evidence('Omo',kinds=('rationale',))[-1]['value']['command']
        self.assertEqual({'G':1},accepted['payment']['mana'])
        self.assertEqual(Zone.STACK,self.game.kernel.state.get(self.game.kernel.state.current(ref.card_id)).zone)

    def test_nonmana_cost_direct(self):self.nonmana('direct')
    def test_nonmana_cost_batch(self):self.nonmana('batch')
    def test_nonmana_cost_override(self):self.nonmana('override')

    def test_preflight_rejection_keeps_current_claim_and_prefix(self):
        ref=self.card('aminatou-veil-piercer',Zone.HAND);head=self.game.store.committed_head()
        with self.assertRaisesRegex(RulesViolation,'No batch was approved'):
            self.approve([{'kind':'cast','source':ref.to_json()}])
        self.assertEqual(head,self.game.store.committed_head())
        self.assertIsNotNone(self.game.state()['claim'])
        self.assertIsNone(self.game.state()['actors']['Omo']['approved'])

    def test_failed_step_records_unexecuted_suffix_without_spending(self):
        ref=self.card('aminatou-veil-piercer',Zone.HAND)
        self.card('plains',Zone.BATTLEFIELD);swamp=self.card('swamp',Zone.BATTLEFIELD)
        self.approve([{'kind':'cast','source':ref.to_json()}]);head=self.game.store.committed_head()
        # Offline state change after approval proves execution still revalidates.
        self.game.kernel.state.set_tapped_batch((swamp,),True)
        self.assertFalse(actions.automatic(self.game));self.assertEqual(head,self.game.store.committed_head())
        issue=self.game.evidence('Omo',kinds=('batch_rejection',))[-1]['value']
        self.assertFalse(issue['resources_spent']);self.assertEqual(1,len(issue['unexecuted_steps']))
        self.assertEqual([],issue['completed_step_ids'])

del _Fixture
