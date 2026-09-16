import unittest
from copy import deepcopy
from edh_gauntlet.rules_program import CardProgram
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet import primitive_actions as actions,primitive_combo as combo
import test_primitive_batch_choices as fixtures


def response(proposal='proof',sha='0'*64,verdict='approved',operations=None,players=('A','B','C','D')):
    return {'schema':1,'proposal_id':proposal,'request_sha256':sha,'verdict':verdict,'rules_basis':'Offline independent-adjudicator fixture.','public_summary':'Fixture shortcut verdict.','operations':operations if operations is not None else [{'op':'damage_player','player':p,'amount':'infinite'} for p in players[1:]] if verdict=='approved' else []}


class ShortcutRulesTests(unittest.TestCase):
    def game(self):
        self.state=RulesState(('A','B','C','D'));self.defs=(CardProgram('body','Body',('Creature',),power=2,toughness=2),)
        self.kernel=RulesKernel(self.state,self.defs);self.kernel.open_window_for_scenario('A')
        for p in self.state.players:self.state.add_card(p,'body',p,Zone.BATTLEFIELD)

    def command(self,r):return {'kind':'adjudicated_combo','action_id':'combo-test','revision':self.kernel.revision,'response':r}

    def test_approved_shortcut_is_terminal_and_replays(self):
        self.game();before=self.kernel.snapshot();cmd=self.command(response())
        RulesActorAdapter(self.kernel)._execute('A',cmd)
        self.assertEqual(['A'],self.kernel.outcome['winners'])
        replay=RulesKernel.restore(before,self.defs);RulesActorAdapter(replay)._execute('A',cmd)
        self.assertEqual(self.kernel.snapshot(),replay.snapshot())

    def test_bounce_and_life_operations(self):
        self.game();cmd=self.command(response(operations=[{'op':'bounce_permanents','players':'opponents'},{'op':'set_life','player':'A','value':100}]))
        RulesActorAdapter(self.kernel)._execute('A',cmd)
        self.assertEqual(100,self.state.life('A'))
        self.assertEqual(3,len(self.state.objects(Zone.HAND)))

    def test_invalid_bounce_is_atomic(self):
        self.game();before=self.kernel.snapshot()
        cmd=self.command(response(operations=[{'op':'set_life','player':'A','value':100},{'op':'bounce_permanents','players':'opponents','uids':['missing@1']}]))
        with self.assertRaises(RulesViolation):RulesActorAdapter(self.kernel)._execute('A',cmd)
        self.assertEqual(before,self.kernel.snapshot())


class ComboHostTests(unittest.TestCase):
    setUp=fixtures.ManaBatchTests.setUp
    main=fixtures.ManaBatchTests.main
    send=fixtures.ManaBatchTests.send
    land=fixtures.ManaBatchTests.land

    def propose(self):
        actor='Omo';turn=self.game.state()['actors'][actor]['turns']
        with self.game.transaction() as s:s['actors'][actor]['plans']['actions']={'id':'proposal','value':{'combo_proposal':{'proposal_text':'Offline fixture loop and outcome.','seat_turn':turn,'phase':'precombat_main','requires':[]}}}
        claim=actions.claim(self.game,actor)
        combo.propose(self.game,actor,claim['claim_id'],claim['combo_offer']['proposal_id'])
        return self.game.store.committed_head()

    def test_consents_adjudication_and_duplicate_receipt(self):
        before=self.propose()
        for _ in range(3):
            next_action=self.game.next_action();self.assertEqual('combo_consent',next_action['decision_kind'])
            actor=next_action['actor'];claim=actions.claim(self.game,actor)
            combo.consent(self.game,actor,claim['claim_id'],True,'No disruption in this fixture.')
        self.assertEqual('adjudicate_combo',self.game.next_action()['kind'])
        request=self.game.state()['combo']['request']
        r=response(request['proposal_id'],request['request_sha256'],operations=[{'op':'damage_player','player':p,'amount':'infinite'} for p in self.game.kernel.state.players if p!='Omo'])
        combo.adjudicate(self.game,r,before)
        self.assertEqual(['Omo'],self.game.state()['terminal']['winners'])
        after=self.game.store.committed_head();combo.adjudicate(self.game,r,before)
        self.assertEqual(after,self.game.store.committed_head())

    def test_decline_returns_priority_and_blocks_direct_results(self):
        before=self.propose();actor=self.game.next_action()['actor'];claim=actions.claim(self.game,actor)
        combo.consent(self.game,actor,claim['claim_id'],False,'Can interact in fixture.')
        self.assertEqual('Omo',self.game.next_action()['actor']);self.assertEqual(before,self.game.store.committed_head())
        with self.assertRaises(RulesViolation):actions.bind_command(self.game,'Omo',{'kind':'adjudicated_combo'},'fake')
        self.assertIsNone(combo.offer(self.game,'Omo'))
