"""Paid mana filters are sequenced automatically without inventing resources."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from test_primitive_autotap import AutotapTests as _Fixture
from edh_gauntlet import primitive_autotap as auto,primitive_actions as actions
from edh_gauntlet.rules_state import Zone,RulesViolation
from edh_gauntlet.rules_program import CostSpec,ManaCost
from edh_gauntlet.rules_adapter import RulesActorAdapter

class FilterAutotapTests(unittest.TestCase):
    setUp=_Fixture.setUp
    send=_Fixture.send
    main=_Fixture.main
    land=_Fixture.land
    card=_Fixture.card
    submit=_Fixture.submit

    def map_case(self,seed=True):
        self.game.config['automatic_decider_mana']=1
        self.game.kernel.state.set_tapped_batch((self.island,self.grove),True)
        basin=self.card('overflowing-basin',Zone.BATTLEFIELD)
        stage=self.card('thespian-s-stage',Zone.BATTLEFIELD) if seed else None
        ref=self.card('expedition-map',Zone.BATTLEFIELD)
        ability=self.game.kernel.activated_abilities(self.game.kernel.state.get(ref))[0]
        command={'kind':'activate','source':ref.to_json(),'ability_id':ability.ability_id,'targets':[],'x_value':0}
        return basin,stage,ref,command

    def test_map_uses_stage_then_basin_and_replays_exactly(self):
        basin,stage,ref,command=self.map_case();kernel=self.game.kernel;before=kernel.snapshot()
        self.submit(command)
        record=self.game.evidence('Omo',kinds=('rationale',))[-1]['value']['command']
        line=record['payment']['mana_actions']
        self.assertEqual([stage.to_json(),basin.to_json()],[c['source'] for c in line])
        self.assertEqual({'C':1},line[1]['payment']['mana'])
        self.assertEqual(2,sum(record['payment']['mana'].values()))
        self.assertEqual({},dict(kernel.state.mana_pool('Omo')))
        self.assertEqual(Zone.GRAVEYARD,kernel.state.get(kernel.state.current(ref.card_id)).zone)
        trial=type(kernel).restore(before,kernel._base_definitions.values())
        RulesActorAdapter(trial)._execute('Omo',record)
        self.assertEqual(kernel.snapshot(),trial.snapshot())

    def test_unfunded_filters_cannot_bootstrap_each_other(self):
        basin,_,_,command=self.map_case(seed=False)
        self.game.kernel.state.add_card('second-basin','catalog:overflowing-basin','Omo',Zone.BATTLEFIELD)
        before=self.game.kernel.snapshot()
        with self.assertRaisesRegex(RulesViolation,'no payment'):self.submit(command)
        self.assertEqual(before,self.game.kernel.snapshot())

    def test_hybrid_filter_uses_own_prior_mana_and_color_choice(self):
        kernel=self.game.kernel
        q=SimpleNamespace(cost=CostSpec(mana=ManaCost(symbols=('U','U'))))
        result=auto.filter_payment(kernel,'Omo',q,(0,)*6,(0,)*6,set())
        self.assertIsNotNone(result)
        _,line,spent=result
        self.assertEqual({'U':1},line[1]['payment']['mana'])
        self.assertEqual('answer',line[2]['kind']);self.assertEqual(2,spent[auto.COLORS.index('U')])

    def test_invalid_final_cost_does_not_leave_any_filter_tapped(self):
        _,_,_,command=self.map_case();kernel=self.game.kernel
        bound=actions.bind_command(self.game,'Omo',command,'filter-test')
        bound['payment']['mana']={};before=kernel.snapshot()
        with self.assertRaises(RulesViolation):RulesActorAdapter(kernel)._execute('Omo',bound)
        self.assertEqual(before,kernel.snapshot())

    def test_filter_cannot_consume_tagged_mana_as_unrestricted(self):
        basin,_,_,command=self.map_case(seed=False);kernel=self.game.kernel
        kernel.state.add_special_mana('Omo',('C',),'legendary',kernel.state.get(basin))
        with self.assertRaises(RulesViolation):self.submit(command)
        self.assertFalse(kernel.state.get(basin).tapped)

    def test_menu_explains_automatic_filter_payment(self):
        _,_,ref,_=self.map_case()
        packet=actions.claim(self.game,'Omo')
        entry=next(r for r in packet['_action_menu'] if r['command'].get('source')==ref.to_json())
        self.assertIn('automatic mana checked',entry['availability'])
        self.assertNotIn('not established',entry['availability'])
