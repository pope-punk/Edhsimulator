import tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from edh_gauntlet import engine,referee

class CopyTriggerTests(unittest.TestCase):
    def game(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        with patch.object(referee.ManualGame,'mulligan'):
            g=referee.ManualGame(1,1,Path(tmp.name),capture_event_state=False,capture_decision_state=False)
        for p in g.players.values():p.battlefield=[];p.graveyard=[]
        g.check_sba=Mock();g.resolve_simultaneous_triggers=Mock()
        return g,g.players['Reaminatour']

    def test_body_double_uro_trigger_sacrifices_physical_body_double(self):
        g,p=self.game();q=g._put_card_bf(p,engine.CardObj('copy',engine.CARDDEF['Body Double']),'test',copy_of="Uro, Titan of Nature's Wrath")
        triggers=g.resolve_simultaneous_triggers.call_args.args[1]
        sacrifice=next(t for t in triggers if t['label']=='sacrifice Uro unless it escaped')
        self.assertIn(q,p.battlefield);sacrifice['resolve']()
        self.assertNotIn(q,p.battlefield)
        self.assertEqual([(c.uid,c.d.name) for c in p.graveyard],[('copy','Body Double')])

    def test_old_uro_trigger_cannot_sacrifice_a_new_incarnation(self):
        g,p=self.game();q=g._put_card_bf(p,engine.CardObj('copy',engine.CARDDEF['Body Double']),'test',copy_of="Uro, Titan of Nature's Wrath")
        trigger=next(t for t in g.resolve_simultaneous_triggers.call_args.args[1] if t['label'].startswith('sacrifice Uro'))
        g.leave_battlefield(p,q,'exile','test');card=p.exile.pop()
        new=g._put_card_bf(p,card,'return',copy_of="Uro, Titan of Nature's Wrath")
        trigger['resolve']();self.assertIn(new,p.battlefield)

    def test_copied_solemn_death_draws_and_keeps_physical_identity(self):
        g,p=self.game();q=engine.Perm('copy','Body Double',p.name,p.name,copy_of='Solemn Simulacrum');p.battlefield=[q]
        g.draw=Mock();g.leave_battlefield(p,q,'graveyard','test')
        triggers=g.resolve_simultaneous_triggers.call_args.args[1]
        next(t for t in triggers if t['label']=='draw a card')['resolve']()
        g.draw.assert_called_once();self.assertEqual(p.graveyard[0].d.name,'Body Double')

    def test_actually_escaped_uro_still_triggers_but_is_not_sacrificed(self):
        g,p=self.game();p.dungeon['escaping_uro_uid']='uro'
        q=g._put_card_bf(p,engine.CardObj('uro',engine.CARDDEF["Uro, Titan of Nature's Wrath"]),'test')
        trigger=next(t for t in g.resolve_simultaneous_triggers.call_args.args[1] if t['label'].startswith('sacrifice Uro'))
        trigger['resolve']();self.assertIn(q,p.battlefield)

    def test_ability_lookup_uses_copied_name(self):
        g,p=self.game();q=engine.Perm('copy','Body Double',p.name,p.name,copy_of='Grim Guardian');p.battlefield=[q]
        self.assertIs(g.perm(p,'Grim Guardian'),q)
        self.assertIsNone(g.perm(p,'Body Double'))

    def test_copied_overseer_keeps_its_creature_entry_trigger(self):
        g,p=self.game();g.gain_life=Mock();g.draw=Mock()
        g._put_card_bf(p,engine.CardObj('copy',engine.CARDDEF['Body Double']),'test',copy_of='Inspiring Overseer')
        triggers=g.resolve_simultaneous_triggers.call_args.args[1]
        self.assertEqual(len(triggers),1);triggers[0]['resolve']()
        g.gain_life.assert_called_once();g.draw.assert_called_once()

    def test_removed_reanimation_aura_does_not_return_its_graveyard_target(self):
        g,p=self.game();card=engine.CardObj('body',engine.CARDDEF['Body Double']);p.graveyard=[card]
        aura=engine.Perm('aura','Animate Dead',p.name,p.name)
        g._put_card_bf=Mock()
        g.resolve_reanimation_aura_trigger(p,aura,p,card)
        self.assertEqual(p.graveyard,[card]);g._put_card_bf.assert_not_called()
