import unittest
from copy import deepcopy
from test_primitive_autotap import AutotapTests as _Fixture
from edh_gauntlet import primitive_actions as actions
from edh_gauntlet.rules_state import Zone,RulesViolation
from edh_gauntlet.rules_adapter import RulesActorAdapter

class AdditionalManaTests(unittest.TestCase):
    setUp=_Fixture.setUp
    send=_Fixture.send
    main=_Fixture.main
    land=_Fixture.land
    card=_Fixture.card
    submit=_Fixture.submit

    def case(self,life=40):
        kernel=self.game.kernel
        kernel.state.set_tapped_batch((self.grove,),True)
        clearing=self.card('silent-clearing',Zone.BATTLEFIELD)
        self.card('plains',Zone.BATTLEFIELD)
        self.card('swamp',Zone.BATTLEFIELD)
        spell=self.card('aminatou-veil-piercer',Zone.HAND)
        kernel.state.lose_life_batch(('Omo',),kernel.state.life('Omo')-life)
        return clearing,{'kind':'cast','source':spell.to_json(),'targets':[],'x_value':0}

    def test_life_land_funds_four_mana_cast_and_replays(self):
        clearing,command=self.case();kernel=self.game.kernel;before=kernel.snapshot()
        self.submit(command)
        self.assertEqual(39,kernel.state.life('Omo'))
        self.assertTrue(kernel.state.get(clearing).tapped)
        record=self.game.evidence('Omo',kinds=('rationale',))[-1]['value']['command']
        trial=type(kernel).restore(before,kernel._base_definitions.values())
        RulesActorAdapter(trial)._execute('Omo',record)
        self.assertEqual(kernel.snapshot(),trial.snapshot())

    def test_legal_payment_to_zero_is_not_refused(self):
        _,command=self.case(life=1);kernel=self.game.kernel
        bound=actions.bind_command(self.game,'Omo',command,'lethal-payment')
        RulesActorAdapter(kernel)._execute('Omo',bound)
        self.assertNotIn('Omo',kernel.state.live_players)
        self.assertIn('lethal-payment',kernel.action_receipts)

    def test_free_source_is_preferred_to_life_payment(self):
        clearing,command=self.case();self.card('forest',Zone.BATTLEFIELD)
        self.submit(command)
        self.assertEqual(40,self.game.kernel.state.life('Omo'))
        self.assertFalse(self.game.kernel.state.get(clearing).tapped)

    def test_self_sacrifice_mana_is_automatic(self):
        kernel=self.game.kernel;kernel.state.set_tapped_batch((self.island,self.grove),True)
        blossom=self.card('lotus-blossom',Zone.BATTLEFIELD)
        kernel.state.add_counters(blossom,'petal',2)
        spell=self.card('wayfarer-s-bauble',Zone.HAND)
        self.submit({'kind':'cast','source':spell.to_json(),'targets':[],'x_value':0})
        self.assertEqual(Zone.GRAVEYARD,kernel.state.get(kernel.state.current(blossom.card_id)).zone)
        self.assertEqual(1,sum(dict(kernel.state.mana_pool('Omo')).values()))

del _Fixture
