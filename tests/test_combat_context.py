import unittest
from types import SimpleNamespace as Obj
from unittest.mock import Mock
from edh_gauntlet.referee import ManualGame


class CombatContextTests(unittest.TestCase):
    def test_removed_attacker_absent_from_blocker_packet_and_damage(self):
        for batch in (1, 2):
            with self.subTest(batch=batch):
                game=ManualGame.__new__(ManualGame)
                gone=Obj(uid='hydra',name='Removed creature',metadata={},tapped=False,copy_of=None)
                kept=Obj(uid='boo',name='Boo',metadata={},tapped=False,copy_of=None)
                blocker=Obj(uid='blocker',name='Blocker',metadata={},tapped=False,copy_of=None)
                attacker=Obj(name='Minsc & Boo',battlefield=[gone,kept],eliminated=False)
                defender=Obj(name='Omo',battlefield=[blocker],eliminated=False)
                game.players={attacker.name:attacker,defender.name:defender}
                game.combat_blocker_batch=batch;game.turn_number=1;game.winner=None;game.pilot_terminal=None
                game.keywords_for=lambda p:set()
                game.perm=lambda *a:None
                game.is_creature_perm=lambda p:True
                game.effective_power=lambda p:2
                game.effective_toughness=lambda p:2
                game.can_block=lambda *a:True
                game.wake_priority_object_passes=Mock();game.clear_priority_seat_snooze=Mock()
                game.resolve_simultaneous_triggers=Mock()
                def priority(*args):
                    if args[1]=='after attackers are declared':attacker.battlefield.remove(gone)
                game.priority_window=priority
                packets=[]
                def request(*args,**kwargs):
                    packets.append(kwargs['request_metadata'])
                    return {'boo':[]} if batch==2 else []
                game._request_multi_decision=request
                game.resolve_combat_damage_steps=Mock()
                game.resolve_combat(attacker,(defender,None),[gone,kept])
                self.assertEqual(len(packets),1)
                context=packets[0]['combat_context']
                self.assertEqual(context['attackers'],['boo'])
                self.assertEqual(set(context['attacker_destinations']),{'boo'})
                self.assertEqual(game.resolve_combat_damage_steps.call_args.args[3],[kept])
