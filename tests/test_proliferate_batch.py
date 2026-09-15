import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from edh_gauntlet import engine, referee, campaign


class ProliferateBatchTests(unittest.TestCase):
    def game(self, cutoff=0):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        with patch.object(referee.ManualGame,'mulligan'):
            g=referee.ManualGame(1,1,Path(tmp.name),proliferate_batch_after=cutoff,
                decision_tape=referee.DecisionTape(Path(tmp.name)/"decisions.jsonl"),
                decision_surface_revision=6,capture_event_state=False,capture_decision_state=False)
        for p in g.players.values():p.battlefield=[];p.energy=0
        p=g.players['Omo'];other=g.players['Elenda']
        sage=engine.Perm('sage','Evolution Sage',p.name,p.name)
        own=engine.Perm('own','Plant',p.name,p.name,counters={'+1/+1':2,'stun':1,'shield':0})
        opponent=engine.Perm('other','Plant',other.name,other.name,counters={'+1/+1':3})
        p.battlefield=[sage,own];other.battlefield=[opponent];other.energy=2
        land=engine.Perm('land','Forest',p.name,p.name)
        g.on_landfall(p,land)
        resolve=p.dungeon['pending_landfall_triggers']['land'][0]['resolve']
        return g,p,other,own,opponent,resolve

    def test_one_selection_all_counter_kinds_and_player_energy(self):
        g,p,other,own,opponent,resolve=self.game()
        g._request_multi_decision=Mock(return_value=[(p,own),(other,None)])
        g._request_decision=Mock()
        resolve()
        g._request_multi_decision.assert_called_once();g._request_decision.assert_not_called()
        call=g._request_multi_decision.call_args
        self.assertEqual(len(call.args[3]),3)
        self.assertIn('[other]',call.args[4]((other,opponent)))
        self.assertTrue(call.kwargs['allow_pass']);self.assertFalse(call.kwargs['scheduler_passable'])
        self.assertEqual(own.counters,{'+1/+1':3,'stun':2,'shield':0})
        self.assertEqual(opponent.counters,{'+1/+1':3});self.assertEqual(other.energy,3)

    def test_empty_selection_changes_nothing(self):
        g,p,other,own,opponent,resolve=self.game()
        g._request_multi_decision=Mock(return_value=[]);resolve()
        self.assertEqual(own.counters['+1/+1'],2);self.assertEqual(other.energy,2)

    def test_legacy_resolution_crossing_cutoff_stays_legacy(self):
        g,p,other,own,opponent,resolve=self.game(cutoff=1)
        g.decision_counter=0
        def choose(*args,**kwargs):g.decision_counter+=1;return True
        g._request_decision=Mock(side_effect=choose);g._request_multi_decision=Mock()
        resolve()
        self.assertEqual(g._request_decision.call_count,2);g._request_multi_decision.assert_not_called()
        self.assertEqual(other.energy,2)
        g._request_multi_decision.return_value=[];resolve()
        g._request_multi_decision.assert_called_once()

    def test_sleeping_scheduler_does_not_choose_empty_for_pilot(self):
        g,p,other,own,opponent,resolve=self.game()
        g.scheduler.before_decision=Mock(side_effect=lambda game,player,passable:passable)
        with self.assertRaises(referee.NeedDecision) as caught:resolve()
        request=caught.exception.request
        self.assertEqual(request['kind'],'proliferate_selection')
        self.assertTrue(request['multi_select']);self.assertEqual(len(request['options']),3)

    def test_absent_binding_retains_old_game(self):
        g,p,other,own,opponent,resolve=self.game(cutoff=None)
        g._request_decision=Mock(return_value=False);g._request_multi_decision=Mock();resolve()
        self.assertEqual(g._request_decision.call_count,2);g._request_multi_decision.assert_not_called()

    def test_phased_out_recipient_is_not_selectable(self):
        g,p,other,own,opponent,resolve=self.game()
        own.metadata['phased_out']=True
        g._request_multi_decision=Mock(return_value=[]);resolve()
        self.assertNotIn((p,own),g._request_multi_decision.call_args.args[3])

    def test_no_recipients_needs_no_decision(self):
        g,p,other,own,opponent,resolve=self.game()
        own.counters={};opponent.counters={};other.energy=0
        resolve()
        self.assertEqual(g.decision_counter,0)
