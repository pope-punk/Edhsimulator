import tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from edh_gauntlet import referee,engine

class RemandCommanderTests(unittest.TestCase):
    def test_remand_owner_choice_survives_cast_finalization(self):
        for to_command in (True,False):
            with self.subTest(to_command=to_command),tempfile.TemporaryDirectory() as tmp:
                with patch.object(referee.ManualGame,'mulligan'):
                    g=referee.ManualGame(1,1,Path(tmp),capture_event_state=False,capture_decision_state=False)
                p=g.players['Minsc & Boo'];other=g.players['Reaminatour'];card=p.commander
                p.hand=[];p.battlefield=[];g.draw=Mock();g._request_decision=Mock(return_value=to_command)
                g.resolve_simultaneous_triggers=Mock();g.priority_window=Mock();g.mark_appearance=Mock()
                def counter(caster,spell):
                    return g.resolve_counterspell_effect(other,engine.CardObj('remand',engine.CARDDEF['Remand']),caster,spell)
                g.react_to_spell=Mock(side_effect=counter)
                self.assertTrue(g.cast(p,card,commander=True,free=True))
                self.assertEqual(p.command_tax,2)
                self.assertEqual(p.commander is not None,to_command)
                self.assertEqual([c.uid for c in p.hand].count(card.uid),int(not to_command))
                self.assertFalse(any(c.uid==card.uid for c in p.graveyard+p.exile))
                self.assertIs(g._request_decision.call_args.args[1],p)
                g.assert_invariants('after Remand')
