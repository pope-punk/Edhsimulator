import tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from edh_gauntlet import engine,referee

class StarfieldTests(unittest.TestCase):
    def game(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        with patch.object(referee.ManualGame,'mulligan'):
            g=referee.ManualGame(1,1,Path(tmp.name),decision_surface_revision=6,capture_event_state=False,capture_decision_state=False)
        for p in g.players.values():p.battlefield=[];p.graveyard=[]
        p=g.players['Reaminatour'];p.battlefield=[engine.Perm('sf','Starfield of Nyx',p.name,p.name)]
        p.graveyard=[engine.CardObj('wave',engine.CARDDEF['Parallax Wave'])]
        g.resolve_simultaneous_triggers=Mock()
        # A sleeping scheduler suppresses only passable choices.
        g.scheduler.before_decision=Mock(side_effect=lambda game,player,passable:passable)
        return g,p
    def test_sleeping_seat_still_puts_targeted_trigger_on_stack(self):
        g,p=self.game();g.upkeep(p)
        triggers=g.resolve_simultaneous_triggers.call_args.args[1]
        self.assertEqual(len(triggers),1);self.assertEqual(triggers[0]['source'],'Starfield of Nyx')
        self.assertIn('Parallax Wave',triggers[0]['label'])
        self.assertFalse(g.scheduler.before_decision.call_args.kwargs['passable'])
        self.assertEqual(len(p.graveyard),1)
    def test_may_return_is_a_separate_resolution_choice(self):
        for accept in (True,False):
            g,p=self.game();g.upkeep(p);trigger=g.resolve_simultaneous_triggers.call_args.args[1][0]
            g._request_decision=Mock(return_value=accept);g._put_card_bf=Mock()
            trigger['resolve']()
            self.assertEqual(g._request_decision.call_args.args[0],'starfield_return')
            self.assertEqual(g._put_card_bf.call_count,int(accept))
            self.assertEqual(len(p.graveyard),int(not accept))
    def test_removed_or_new_incarnation_target_cannot_be_returned(self):
        g,p=self.game();g.upkeep(p);trigger=g.resolve_simultaneous_triggers.call_args.args[1][0]
        p.graveyard=[engine.CardObj('wave',engine.CARDDEF['Parallax Wave'])]
        g._request_decision=Mock();g._put_card_bf=Mock();trigger['resolve']()
        g._request_decision.assert_not_called();g._put_card_bf.assert_not_called()
