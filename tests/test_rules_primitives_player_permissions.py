"""Player permissions combine without assigning individual land plays to sources."""
import unittest
from edh_gauntlet.rules_program import (CardProgram,PlayerPermissions,GrantPermissions,Draw,ZoneReplacement,validate,encode,decode)
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_casting import Payment


class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.programs=tuple(row['program'] for row in load_reviewed().values())
        self.state=RulesState(('A','B'));self.kernel=RulesKernel(self.state,self.programs)
        for actor in ('A','B'):
            for i in range(7):self.add('forest',Zone.LIBRARY,actor,actor+'library'+str(i))

    def add(self,key,zone=Zone.BATTLEFIELD,actor='A',name=None):
        return self.state.add_card(name or key,'catalog:'+key,actor,zone)

    def passes(self):
        result=None
        for _ in self.state.live_players:result=self.kernel.pass_priority(self.kernel.priority)
        return result

    def main(self):
        self.kernel.begin_turn_for_scenario('A');self.passes();self.passes()
        self.assertEqual('precombat_main',self.kernel.phase)

    def play(self,ref,name=None):
        return self.kernel.play_land(name or ref.card_id,'A',ref,revision=self.kernel.revision)

    def to_cleanup(self):
        self.passes();boundary=self.passes()
        self.kernel.declare_attackers('A',{},revision=boundary.revision)
        self.passes();self.passes();self.passes();return self.passes()

    def test_azusa_grants_three_total_and_does_not_reset_used_plays_when_blinked(self):
        source=self.add('azusa-lost-but-seeking');self.main()
        lands=[self.add('forest',Zone.HAND,name='land'+str(i)) for i in range(4)]
        for land in lands[:3]:self.play(land)
        self.state.move((ZoneMove(source,Zone.EXILE),),'fixture')
        self.state.move((ZoneMove(self.state.current(source.card_id),Zone.BATTLEFIELD),),'fixture')
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.play(lands[3])
        self.assertEqual(before,self.kernel.snapshot());self.assertEqual(3,self.kernel.turn_schedule['land_plays'])

    def test_losing_permission_recomputes_limit_without_refunding_used_plays(self):
        source=self.add('azusa-lost-but-seeking');self.main();self.play(self.state.zone('A',Zone.HAND)[0].ref)
        self.state.move((ZoneMove(source,Zone.GRAVEYARD),),'fixture')
        extra=self.add('forest',Zone.HAND,name='extra')
        with self.assertRaises(RulesViolation):self.play(extra)
        self.assertEqual(1,self.kernel.player_permissions()['A']['land_play_limit'])
        self.state.move((ZoneMove(self.state.current(source.card_id),Zone.BATTLEFIELD),),'fixture')
        self.play(extra);self.assertEqual(2,self.kernel.turn_schedule['land_plays'])

    def test_permissions_follow_controller_and_ignore_phased_sources(self):
        source=self.add('azusa-lost-but-seeking')
        self.state.change_control(source,'B')
        self.assertEqual(1,self.kernel.player_permissions()['A']['land_play_limit'])
        self.assertEqual(3,self.kernel.player_permissions()['B']['land_play_limit'])
        self.state.phase(source,True);self.assertEqual(1,self.kernel.player_permissions()['B']['land_play_limit'])
        self.state.phase(source,False);self.assertEqual(3,self.kernel.player_permissions()['B']['land_play_limit'])

    def test_body_double_inherits_permission_from_copied_definition(self):
        self.add('azusa-lost-but-seeking',Zone.GRAVEYARD,'B');copy=self.add('body-double',Zone.HAND)
        request=self.kernel.enter(copy)
        index=next(i for i,o in enumerate(request.options) if o.ref and o.ref.card_id=='azusa-lost-but-seeking')
        self.kernel.answer(request.request_id,'A',[index])
        self.assertEqual(3,self.kernel.player_permissions()['A']['land_play_limit'])
        self.assertEqual(1,self.kernel.player_permissions()['B']['land_play_limit'])

    def test_graveyard_land_permission_preserves_ownership_timing_and_play_limit(self):
        source=self.add('ramunap-excavator');own=self.add('forest',Zone.GRAVEYARD,name='own');enemy=self.add('forest',Zone.GRAVEYARD,'B','enemy')
        self.main();before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.play(enemy)
        self.assertEqual(before,self.kernel.snapshot())
        self.play(own);extra=self.add('forest',Zone.GRAVEYARD,name='extra')
        with self.assertRaises(RulesViolation):self.play(extra)
        self.assertEqual(1,self.kernel.turn_schedule['land_plays'])
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('own')).zone)
        self.state.move((ZoneMove(source,Zone.GRAVEYARD),),'fixture')
        self.assertEqual(['hand'],self.kernel.player_permissions()['A']['land_zones'])

    def test_graveyard_adapter_action_replays_without_exposing_extra_private_zones(self):
        self.add('ramunap-excavator');ref=self.add('forest',Zone.GRAVEYARD);self.main();adapter=RulesActorAdapter(self.kernel)
        packet=adapter.submit('A',{'kind':'play_land','revision':self.kernel.revision,'action_id':'land','source':ref.to_json()})
        row=next(r for r in packet['players'] if r['seat']=='A')
        self.assertEqual(['graveyard','hand'],row['permissions']['land_zones'])
        self.assertEqual(1,packet['turn']['land_plays_used'])
        replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.assertEqual(adapter.archive(),replay.archive());self.assertEqual(adapter.packet('B'),replay.packet('B'))

    def test_urban_evolution_draws_three_and_adds_to_static_allowance_until_cleanup(self):
        self.add('azusa-lost-but-seeking');self.main();initial=len(self.state.zone('A',Zone.HAND))
        spell=self.add('urban-evolution',Zone.HAND);self.state.add_mana('A',tuple('CCCGU'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',spell),Payment((('C',3),('G',1),('U',1))))
        self.passes();self.assertEqual(initial+3,len(self.state.zone('A',Zone.HAND)))
        self.assertEqual(4,self.kernel.player_permissions()['A']['land_play_limit'])
        for i in range(4):self.play(self.add('forest',Zone.HAND,name='played'+str(i)))
        self.to_cleanup();self.assertEqual('B',self.kernel.active)
        self.assertEqual(3,self.kernel.player_permissions()['A']['land_play_limit']);self.assertEqual([],self.kernel.player_effects)
        self.assertEqual(0,self.kernel.turn_schedule['land_plays'])

    def test_temporary_permissions_stack_and_do_not_depend_on_source_survival(self):
        source=self.add('sol-ring');self.main()
        for _ in range(2):self.kernel.execute_for_scenario(source,'A',(GrantPermissions(PlayerPermissions(additional_land_plays=1)),))
        self.state.move((ZoneMove(source,Zone.GRAVEYARD),),'fixture')
        self.assertEqual(3,self.kernel.player_permissions()['A']['land_play_limit'])
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.assertEqual(self.kernel.player_permissions(),restored.player_permissions())
        self.to_cleanup();self.assertEqual(1,self.kernel.player_permissions()['A']['land_play_limit'])

    def test_tower_and_vessel_allow_large_hands_and_produce_colorless_mana(self):
        for key in ('reliquary-tower','thought-vessel'):
            self.setUp();source=self.add(key);self.main()
            for i in range(9):self.add('forest',Zone.HAND,name='extra'+str(i))
            self.kernel.commit_action(self.kernel.quote_activation('mana','A',source,'mana'),Payment())
            self.assertEqual((('C',1),),self.state.mana_pool('A'))
            self.to_cleanup();self.assertEqual('B',self.kernel.active)
            self.assertEqual(10,len(self.state.zone('A',Zone.HAND)))

    def test_lost_hand_size_permission_requires_one_batched_cleanup_discard(self):
        source=self.add('thought-vessel');self.main()
        for i in range(9):self.add('forest',Zone.HAND,name='extra'+str(i))
        self.state.move((ZoneMove(source,Zone.GRAVEYARD),),'fixture')
        request=self.to_cleanup();self.assertEqual(3,request.minimum);self.assertEqual(3,request.maximum)
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.kernel.answer(request.request_id,'A',[0,1,2]);restored.answer(request.request_id,'A',[0,1,2])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertEqual(7,len(self.state.zone('A',Zone.HAND)))

    def test_temporary_unlimited_hand_size_expires_after_discard_step(self):
        source=self.add('sol-ring');self.main()
        for i in range(9):self.add('forest',Zone.HAND,name='extra'+str(i))
        self.kernel.execute_for_scenario(source,'A',(GrantPermissions(PlayerPermissions(no_maximum_hand_size=True)),))
        self.to_cleanup();self.assertEqual(10,len(self.state.zone('A',Zone.HAND)))
        self.assertEqual(7,self.kernel.player_permissions()['A']['maximum_hand_size'])
        self.assertEqual([],self.kernel.player_effects)

    def test_compiler_rejects_unsupported_permission_shapes(self):
        for value in (PlayerPermissions(-1),PlayerPermissions(True),PlayerPermissions(no_maximum_hand_size=1),
                PlayerPermissions(land_zones=(Zone.LIBRARY,)),PlayerPermissions(land_zones=(Zone.GRAVEYARD,Zone.GRAVEYARD)),PlayerPermissions(land_zones=('graveyard',))):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Enchantment',),player_permissions=value))
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),spell_effects=(GrantPermissions(PlayerPermissions(),'forever'),)))
        value=PlayerPermissions(2,True,(Zone.GRAVEYARD,));self.assertEqual(value,decode(encode(value)))
