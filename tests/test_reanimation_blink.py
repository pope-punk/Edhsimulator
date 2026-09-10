import tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from edh_gauntlet import engine,referee


class ReanimationBlinkTests(unittest.TestCase):
    def game(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        with patch.object(referee.ManualGame,'mulligan'):
            game=referee.ManualGame(1,1,Path(tmp.name),capture_event_state=False,capture_decision_state=False)
        for player in game.players.values():
            player.battlefield=[];player.graveyard=[];player.exile=[]
        # Test a blink resolving with its generated triggers awaiting the stack.
        game._ltb_trigger_frames=[[]]
        return game,game.players['Reaminatour']

    def test_no_grave_card_aura_stays_exiled_then_old_creature_is_sacrificed(self):
        for name in ['Animate Dead','Dance of the Dead']:
            with self.subTest(aura=name):
                game,p=self.game()
                body=engine.Perm('body','Body Double',p.name,p.name,copy_of='Felidar Guardian')
                aura=engine.Perm('aura',name,p.name,p.name,attached_to=body.uid)
                p.battlefield=[body,aura]
                game._put_card_bf=Mock()
                self.assertIsNone(game.blink_own_permanent(p,aura,'Felidar Guardian ETB'))
                game._put_card_bf.assert_not_called()
                self.assertEqual([c.uid for c in p.exile],['aura'])
                self.assertIn(body,p.battlefield)
                triggers=game._ltb_trigger_frames[0]
                self.assertEqual(len(triggers),1)
                triggers.pop()['resolve']()
                self.assertNotIn(body,p.battlefield)
                self.assertEqual([c.uid for c in p.graveyard],['body'])
                self.assertEqual([c.uid for c in p.exile],['aura'])

    def test_existing_grave_card_permits_return_including_opponent_graveyard(self):
        for opponent in [False,True]:
            game,p=self.game();owner=next(x for x in game.players.values() if x is not p) if opponent else p
            owner.graveyard=[engine.CardObj('dead',engine.CARDDEF['Felidar Guardian'])]
            aura=engine.Perm('aura','Animate Dead',p.name,p.name);p.battlefield=[aura]
            game._put_card_bf=Mock(return_value='returned')
            self.assertEqual(game.blink_own_permanent(p,aura,'Felidar Guardian ETB'),'returned')
            self.assertEqual(p.exile,[])
            self.assertEqual(game._put_card_bf.call_args.args[1].uid,'aura')

    def test_necromancy_is_not_an_aura_before_its_etb_resolves(self):
        game,p=self.game();card=engine.Perm('necro','Necromancy',p.name,p.name);p.battlefield=[card]
        game._put_card_bf=Mock(return_value='returned')
        self.assertEqual(game.blink_own_permanent(p,card,'Felidar Guardian ETB'),'returned')
        self.assertEqual(p.exile,[])

    def test_felidar_and_dancers_do_not_offer_an_unproved_infinite_army(self):
        game,p=self.game()
        body=engine.Perm('body','Body Double',p.name,p.name,copy_of='Felidar Guardian')
        aura=engine.Perm('aura','Animate Dead',p.name,p.name,attached_to=body.uid)
        dancers=engine.Perm('dancers','Ghostly Dancers',p.name,p.name)
        p.battlefield=[body,aura,dancers]
        game._request_decision=Mock(return_value=aura)
        game._dispatch_etb_triggers=Mock()
        game.felidar_etb(p,body)
        trigger=game._dispatch_etb_triggers.call_args.args[2][0]
        trigger['prepare']();trigger['resolve']()
        self.assertEqual(game._request_decision.call_count,1)
        self.assertEqual(game._request_decision.call_args.args[0],'felidar_blink')
        self.assertNotIn('infinite_spirits_turn',p.dungeon)
        self.assertEqual([c.uid for c in p.exile],['aura'])
