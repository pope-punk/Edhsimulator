"""Exercise the model-facing sequence tool with no planner action proposal."""
import test_primitive_batch_choices as fixtures
import test_primitive_host as transport
from edh_gauntlet import primitive_actions as actions
from edh_gauntlet.primitive_host import PrimitiveRunner
from edh_gauntlet.rules_state import RulesViolation


class DirectManaSequenceTests(fixtures.ManaBatchTests):
    def approve(self,labels=None):
        steps=self.steps(labels);server=transport.FakeServer();runner=PrimitiveRunner(self.game,server)
        self.addCleanup(runner.timing.close)
        runner.pump();thread=runner.lanes[('Omo','decider')]
        self.assertNotIn('actions',runner.inputs[thread]['plans'])
        self.assertTrue(runner.inputs[thread]['batch_context']['direct_sequence_available'])
        args={'sequence':[{'id':s['id'],'command':s['command']} for s in steps],
              'rationale':'Produce the chosen mana as one known line.','scheduler':{'mode':'hold_full_control'}}
        runner.handle({'id':'sequence-call','method':'item/tool/call','params':{'threadId':thread,
            'turnId':runner.running[thread],'callId':'sequence-call','tool':'edh_act','arguments':args}})
        self.assertIn(thread,runner.waiting)
        self.assertEqual(4,runner.waiting_receipts[thread]['approved'])
        self.assertEqual(1,runner.tool_counts[thread])

    def test_invalid_sequence_keeps_claim_and_accepted_prefix(self):
        frozen=actions.claim(self.game,'Omo');before=self.game.store.committed_head()
        with self.assertRaises(RulesViolation):
            actions.approve_sequence(self.game,'Omo',frozen['claim_id'],
                sequence=[{'id':'color','command':{'kind':'answer','choice_from':{'step_id':'missing','option_labels':['{U}']},'indexes':[0]}}],
                rationale='Synthetic invalid continuation.',scheduler={'mode':'hold_full_control'})
        self.assertEqual(before,self.game.store.committed_head())
        self.assertEqual(frozen,self.game.state()['claim'])

    def test_direct_sequence_cannot_bind_another_seat(self):
        frozen=actions.claim(self.game,'Omo');before=self.game.store.committed_head()
        with self.assertRaises(RulesViolation):
            actions.approve_sequence(self.game,'Elenda',frozen['claim_id'],sequence=[{'id':'pass','command':{'kind':'pass'}}],
                rationale='Synthetic unauthorized seat.',scheduler={'mode':'hold_full_control'})
        self.assertEqual(before,self.game.store.committed_head())

    def test_snarl_black_choice_and_bauble_cast_run_from_one_tool_submission(self):
        from edh_gauntlet.rules_state import Zone
        # Declared synthetic initial objects; never modify a live game or its journal.
        snarl=self.game.kernel.state.add_card('fixture-snarl','catalog:shineshadow-snarl','Omo',Zone.BATTLEFIELD)
        bauble=self.game.kernel.state.add_card('fixture-bauble','catalog:wayfarer-s-bauble','Omo',Zone.HAND)
        server=transport.FakeServer();runner=PrimitiveRunner(self.game,server);self.addCleanup(runner.timing.close)
        runner.pump();thread=runner.lanes[('Omo','decider')]
        args={'sequence':[
            {'id':'tap','command':{'kind':'activate','source':snarl.to_json(),'ability_id':'mana','targets':[],'x_value':0,'payment':{'mana':{},'taps':[]}}},
            {'id':'color','command':{'kind':'answer','choice_from':{'step_id':'tap','option_labels':['1 {W}','1 {B}']},'indexes':[1]}},
            {'id':'cast','command':{'kind':'cast','source':bauble.to_json(),'targets':[],'x_value':0,'payment':{'mana':{'B':1},'taps':[]}}}],
            'rationale':'Tap Snarl for black and spend it on Bauble.','scheduler':{'mode':'hold_full_control'}}
        runner.handle({'id':'cast-line','method':'item/tool/call','params':{'threadId':thread,'turnId':runner.running[thread],
            'callId':'cast-line','tool':'edh_act','arguments':args}})
        self.assertEqual(3,runner.waiting_receipts[thread]['approved'])
        before=self.game.store.generation
        for index in range(3):self.assertTrue(actions.automatic(self.game),(index,self.game.state()['actors']['Omo'].get('last_rejection')))
        self.assertEqual(before+3,self.game.store.generation)
        self.assertEqual(1,runner.tool_counts[thread])
        self.assertEqual(Zone.STACK,self.game.kernel.state.get(self.game.kernel.state.current(bauble.card_id)).zone)
        records=self.game.evidence('Omo',kinds=('rationale',))[-3:]
        self.assertEqual(['activate','answer','cast'],[r['value']['command']['kind'] for r in records])
        approvals={r['value']['control']['sequence']['id'] for r in records}
        self.assertEqual(1,len(approvals))
