"""Resolved control effects retain default control and independent durations."""
import json
import unittest
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_program import CardProgram,GainControl,validate
from edh_gauntlet.rules_kernel import RulesKernel


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.state=RulesState(('A','B','C'))
        self.ref=self.state.add_card('creature','creature','A',Zone.BATTLEFIELD)
        self.program=CardProgram('creature','Creature',('Creature',),power=2,toughness=2)

    def test_expiring_later_effect_reveals_earlier_controller(self):
        first=self.state.change_control(self.ref,'B')
        second=self.state.change_control(self.ref,'C')
        self.state.end_control_effects((second,))
        self.assertEqual('B',self.state.get(self.ref).controller)
        self.state.end_control_effects((first,))
        self.assertEqual('A',self.state.get(self.ref).controller)

    def test_ending_earlier_effect_does_not_override_later_effect(self):
        first=self.state.change_control(self.ref,'B')
        self.state.change_control(self.ref,'C')
        before=self.state.get(self.ref).controlled_since
        self.assertEqual((),self.state.end_control_effects((first,)))
        self.assertEqual('C',self.state.get(self.ref).controller)
        self.assertEqual(before,self.state.get(self.ref).controlled_since)

    def test_same_controller_effect_survives_earlier_expiration_without_resetting_readiness(self):
        first=self.state.change_control(self.ref,'B')
        self.state.start_turn('B')
        second=self.state.change_control(self.ref,'B')
        self.state.end_control_effects((first,))
        self.assertTrue(self.state.ready_since_turn_start(self.ref))
        self.assertEqual('B',self.state.get(self.ref).controller)
        self.state.end_control_effects((second,))
        self.assertEqual('A',self.state.get(self.ref).controller)
        self.assertFalse(self.state.ready_since_turn_start(self.ref))

    def test_default_controller_can_differ_from_owner(self):
        self.state.move((ZoneMove(self.ref,Zone.EXILE),),'exile')
        self.state.move((ZoneMove(self.state.current('creature'),Zone.BATTLEFIELD,controller='B'),),'reanimate')
        ref=self.state.current('creature')
        key=self.state.change_control(ref,'C')
        self.state.end_control_effects((key,))
        self.assertEqual('B',self.state.get(ref).controller)

    def test_blink_retires_every_old_incarnation_effect(self):
        key=self.state.change_control(self.ref,'B')
        self.state.move((ZoneMove(self.ref,Zone.EXILE),),'blink')
        self.state.move((ZoneMove(self.state.current('creature'),Zone.BATTLEFIELD),),'return')
        before=self.state.snapshot()
        with self.assertRaises(RulesViolation):self.state.end_control_effects((key,))
        self.assertEqual(before,self.state.snapshot())
        self.assertEqual({},before['control_effects'])
        self.assertEqual('A',self.state.get(self.state.current('creature')).controller)

    def test_invalid_batch_and_expiration_are_atomic(self):
        other=self.state.add_card('hand','creature','A',Zone.HAND)
        before=self.state.snapshot()
        with self.assertRaises(RulesViolation):self.state.change_control_batch((self.ref,other),'B')
        self.assertEqual(before,self.state.snapshot())
        key=self.state.change_control(self.ref,'B');before=self.state.snapshot()
        with self.assertRaises(RulesViolation):self.state.end_control_effects((key,'missing'))
        self.assertEqual(before,self.state.snapshot())

    def test_duration_expiration_while_phased_retains_incarnation(self):
        self.state.change_control(self.ref,'B',duration='until_end_of_turn')
        self.state.phase(self.ref,True)
        self.state.expire_turn_control()
        self.assertTrue(self.state.get(self.ref).phased)
        self.assertEqual('A',self.state.get(self.ref).controller)
        self.state.phase(self.ref,False)
        self.assertEqual('A',self.state.get(self.ref).controller)

    def test_closed_primitive_and_checkpoint_expiration_parity(self):
        kernel=RulesKernel(self.state,(self.program,))
        kernel.execute_for_scenario(self.ref,'B',(GainControl('source','until_end_of_turn'),))
        checkpoint=kernel.snapshot();restored=RulesKernel.restore(checkpoint,(self.program,))
        kernel._finish_cleanup_actions();restored._finish_cleanup_actions()
        self.assertEqual(kernel.snapshot(),restored.snapshot())
        self.assertEqual('A',self.state.get(self.ref).controller)
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',(),spell_effects=(GainControl('source','while_source_present'),)))

    def test_restore_rejects_inconsistent_control_and_missing_base(self):
        self.state.change_control(self.ref,'B')
        checkpoint=self.state.snapshot()
        invalid=json.loads(json.dumps(checkpoint));invalid['objects'][0]['controller']='C'
        with self.assertRaises(RulesViolation):RulesState.restore(invalid)
        invalid=json.loads(json.dumps(checkpoint));invalid['control_bases']={}
        with self.assertRaises(RulesViolation):RulesState.restore(invalid)

    def test_real_turn_cleanup_expires_control_and_clears_damage(self):
        self.state.change_control(self.ref,'B',duration='until_end_of_turn')
        self.state.damage_batch(({'source':self.state.get(self.ref),'target':self.ref,'amount':1},))
        kernel=RulesKernel(self.state,(self.program,))
        self.state.add_card('draw','creature','A',Zone.LIBRARY)
        kernel.begin_turn_for_scenario('A')
        for _ in range(40):
            if self.state.turn_active=='B':break
            if kernel.phase=='declare_attackers' and kernel.priority is None:
                kernel.declare_attackers('A',{},revision=kernel.revision)
            else:kernel.pass_priority(kernel.priority)
        self.assertEqual('B',self.state.turn_active)
        self.assertEqual('A',self.state.get(self.ref).controller)
        self.assertEqual(0,self.state.get(self.ref).damage_marked)
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.ref).zone)
