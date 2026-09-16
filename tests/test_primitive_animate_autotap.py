import unittest
import test_rules_primitives_animate_dead as fixture
from edh_gauntlet.rules_state import Zone
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.primitive_autotap import payment

class AnimateAutomaticTests(unittest.TestCase):
    setUpClass=classmethod(fixture.AnimateDeadCardTests.setUpClass.__func__)
    game=fixture.AnimateDeadCardTests.game
    add=fixture.AnimateDeadCardTests.add
    current=fixture.AnimateDeadCardTests.current
    drain=fixture.AnimateDeadCardTests.drain

    def test_animate_targets_relic_warder_with_automatic_payment_and_replay(self):
        self.game();aura=self.add('animate-dead',zone=Zone.HAND)
        warder=self.add('leonin-relic-warder',zone=Zone.GRAVEYARD)
        self.add('swamp');self.add('forest')
        before=self.kernel.snapshot()
        cmd={'kind':'cast','action_id':'animate-auto','revision':self.kernel.revision,'source':aura.to_json(),'targets':[warder.to_json()],'x_value':0,'autotap':{}}
        cmd['payment']=payment(self.kernel,'A',cmd,smart=True);cmd.pop('autotap')
        RulesActorAdapter(self.kernel)._execute('A',cmd)
        self.assertEqual(Zone.STACK,self.current(aura).zone)
        replay=type(self.kernel).restore(before,self.programs)
        RulesActorAdapter(replay)._execute('A',cmd)
        self.assertEqual(self.kernel.snapshot(),replay.snapshot())
        self.drain()
        self.assertEqual(Zone.BATTLEFIELD,self.current(warder).zone)
        self.assertEqual(self.current(warder).ref,self.current(aura).attached_to)
