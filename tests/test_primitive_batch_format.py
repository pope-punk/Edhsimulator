"""Pilot approval remains explicit while redundant step bookkeeping is inherited."""
import unittest
import test_primitive_batch_choices as fixtures
from edh_gauntlet import primitive_actions as actions
from edh_gauntlet.rules_state import RulesViolation


class BatchFormatTests(unittest.TestCase):
    setUp=fixtures.ManaBatchTests.setUp
    send=fixtures.ManaBatchTests.send
    main=fixtures.ManaBatchTests.main
    land=fixtures.ManaBatchTests.land
    steps=fixtures.ManaBatchTests.steps

    def proposal(self):
        steps=self.steps()[:2]
        with self.game.transaction() as state:
            state['actors']['Omo']['plans']['actions']={'id':'proposal','value':{'action_sequence':steps}}
        return actions.claim(self.game,'Omo'),steps

    def test_omitted_rejects_never_approve_omitted_actions(self):
        claim,steps=self.proposal()
        head=self.game.store.committed_head()
        result=actions.approve(self.game,'Omo',claim['claim_id'],approve_ids=['island'],pass_priority=False)
        self.assertEqual(1,result['approved'])
        self.assertEqual(head,self.game.store.committed_head())
        self.assertEqual([steps[0]],self.game.state()['actors']['Omo']['approved']['steps'])
        self.assertEqual(['grove'],self.game.evidence('Omo',kinds=('batch_approval',))[-1]['value']['rejected'])
        self.assertTrue(actions.automatic(self.game))
        self.assertTrue(self.game.kernel.state.get(self.island).tapped)
        self.assertFalse(self.game.kernel.state.get(self.grove).tapped)
        self.assertFalse(actions.automatic(self.game))

    def test_command_only_override_inherits_step_not_old_command_fields(self):
        claim,steps=self.proposal()
        actions.approve(self.game,'Omo',claim['claim_id'],approve_ids=['island'],
                        overrides={'island':{'command':{'kind':'pass'}}},pass_priority=False)
        chosen=self.game.state()['actors']['Omo']['approved']['steps'][0]
        self.assertEqual({'kind':'pass'},chosen['command'])
        self.assertEqual({k:v for k,v in steps[0].items() if k!='command'},
                         {k:v for k,v in chosen.items() if k!='command'})

    def test_invalid_edits_preserve_claim_and_accepted_prefix(self):
        claim,steps=self.proposal();head=self.game.store.committed_head()
        for patch in ({'id':'grove'},{'typo':True},{'command':{'kind':'bogus'}}):
            with self.subTest(patch=patch),self.assertRaises(RulesViolation):
                actions.approve(self.game,'Omo',claim['claim_id'],approve_ids=['island'],overrides={'island':patch})
            self.assertEqual(head,self.game.store.committed_head())
            self.assertEqual(claim['claim_id'],self.game.state()['claim']['claim_id'])

    def test_invalid_ids_and_explicit_incomplete_rejection_are_not_guessed(self):
        claim,_=self.proposal()
        for args in ({'approve_ids':['unknown']},{'approve_ids':['island','island']},
                     {'approve_ids':['island'],'reject_ids':[]},{'approve_ids':[{}]}):
            with self.subTest(args=args),self.assertRaises(RulesViolation):
                actions.approve(self.game,'Omo',claim['claim_id'],**args)

    def test_executed_step_cannot_be_reapproved(self):
        claim,_=self.proposal()
        with self.game.transaction() as state:
            state['actors']['Omo']['executed_steps']={'proposal':['island']}
        with self.assertRaisesRegex(RulesViolation,'already executed'):
            actions.approve(self.game,'Omo',claim['claim_id'],approve_ids=['island'])
        actions.approve(self.game,'Omo',claim['claim_id'],approve_ids=['grove'])
        self.assertEqual(['grove'],[s['id'] for s in self.game.state()['actors']['Omo']['approved']['steps']])
