"""Batched combat choices use real object incarnations and simultaneous damage."""
import unittest
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_program import CardProgram,AbilityProgram,EventPattern,GainLife,Damage
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_combat import CombatChoiceBoundary,uid


class CombatTests(unittest.TestCase):
    def setup_game(self,attackers=((2,2,()),),blockers=((2,2,()),)):
        self.state=RulesState(('A','B','C'));self.programs=[];self.attackers=[];self.blockers=[]
        for owner,specs,refs in (('A',attackers,self.attackers),('B',blockers,self.blockers)):
            for index,(power,toughness,keywords) in enumerate(specs):
                name=owner+str(index)
                self.programs.append(CardProgram(name,name,('Creature',),power=power,toughness=toughness,keywords=keywords))
                refs.append(self.state.add_card(name,name,owner,Zone.BATTLEFIELD))
        land=CardProgram('land','Land',('Land',));self.programs.append(land)
        for owner in self.state.players:self.state.add_card('draw'+owner,'land',owner,Zone.LIBRARY)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.begin_turn_for_scenario('A')
        self.pass_round();self.pass_round();self.pass_round();self.pass_round()
        self.assertEqual('declare_attackers',self.kernel.phase)

    def pass_round(self):
        for _ in self.state.players:boundary=self.kernel.pass_priority(self.kernel.priority)
        return boundary

    def attack(self):
        self.kernel.declare_attackers('A',{ref:'B' for ref in self.attackers},revision=self.kernel.revision)
        return self.pass_round()

    def block(self,assignments=None):
        boundary=self.attack()
        self.assertEqual('blockers',boundary.kind)
        assignments=assignments if assignments is not None else {uid(self.attackers[0]):[uid(ref) for ref in self.blockers]}
        self.kernel.declare_blockers('B',assignments,revision=self.kernel.revision)
        return self.pass_round()

    def test_mutual_lethal_damage_commits_deaths_simultaneously(self):
        self.setup_game();self.block()
        deaths=[event for event in self.state.events if event.cause=='permanent_sba']
        self.assertEqual(2,len(deaths));self.assertEqual(1,len({event.batch for event in deaths}))
        self.assertTrue(all(event.before.damage_marked==2 for event in deaths))

    def test_unblocked_damage_and_vigilance(self):
        self.setup_game(((3,3,('vigilance',)),),())
        self.block({uid(self.attackers[0]):[]})
        self.assertEqual(37,self.state.life('B'))
        self.assertFalse(self.state.get(self.attackers[0]).tapped)

    def test_blocking_new_creatures_does_not_require_readiness(self):
        self.setup_game();self.assertFalse(self.state.ready_since_turn_start(self.blockers[0]))
        self.block();self.assertEqual(40,self.state.life('B'))

    def test_flying_and_menace_restrict_blocker_choices(self):
        self.setup_game(((3,3,('flying','menace')),),((1,1,()),(1,1,('reach',)),(1,1,('flying',))))
        boundary=self.attack();spec=boundary.specification
        eligible=spec['eligibility_groups'][spec['attackers'][0]['eligible_group']]
        self.assertNotIn(uid(self.blockers[0]),eligible)
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.declare_blockers('B',{uid(self.attackers[0]):[uid(self.blockers[1])]},revision=self.kernel.revision)
        self.assertEqual(before,self.kernel.snapshot())
        self.kernel.declare_blockers('B',{uid(self.attackers[0]):[uid(self.blockers[1]),uid(self.blockers[2])]},revision=self.kernel.revision)

    def test_blocker_cannot_be_reused_across_attackers(self):
        self.setup_game(((2,2,()),(2,2,())),((4,4,()),));self.attack()
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):
            self.kernel.declare_blockers('B',{uid(ref):[uid(self.blockers[0])] for ref in self.attackers},revision=self.kernel.revision)
        self.assertEqual(before,self.kernel.snapshot())

    def test_trample_damage_is_one_validated_batch(self):
        self.setup_game(((5,5,('trample',)),),((2,2,()),(2,2,())))
        boundary=self.block();self.assertEqual('combat_damage',boundary.kind)
        source=uid(self.attackers[0]);first,second=map(uid,self.blockers)
        bad={source:{'blockers':{first:1,second:2},'defender':2}}
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.assign_combat_damage('A',bad,revision=boundary.revision)
        self.assertEqual(before,self.kernel.snapshot())
        good={source:{'blockers':{first:2,second:2},'defender':1}}
        self.kernel.assign_combat_damage('A',good,revision=boundary.revision)
        self.assertEqual(39,self.state.life('B'))
        self.assertEqual(4,self.state.get(self.attackers[0]).damage_marked)
        self.assertTrue(all(self.state.get(self.state.current(ref.card_id)).zone==Zone.GRAVEYARD for ref in self.blockers))

    def test_no_damage_to_defender_after_last_blocker_leaves_without_trample(self):
        self.setup_game(((5,5,()),),((2,2,()),));self.attack()
        self.kernel.declare_blockers('B',{uid(self.attackers[0]):[uid(self.blockers[0])]},revision=self.kernel.revision)
        self.state.move((ZoneMove(self.blockers[0],Zone.EXILE),),'response')
        self.pass_round();self.assertEqual(40,self.state.life('B'))

    def test_first_strike_kills_before_regular_damage(self):
        self.setup_game(((2,2,('first_strike',)),),((2,2,()),));self.block()
        self.assertEqual('first_strike_damage',self.kernel.phase)
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current(self.blockers[0].card_id)).zone)
        self.pass_round();self.assertEqual('combat_damage',self.kernel.phase)
        self.assertEqual(0,self.state.get(self.attackers[0]).damage_marked)

    def test_double_strike_with_trample_has_two_damage_steps(self):
        self.setup_game(((4,4,('double_strike','trample')),),((2,2,()),));boundary=self.block()
        self.kernel.assign_combat_damage('A',{uid(self.attackers[0]):{'blockers':{uid(self.blockers[0]):2},'defender':2}},revision=boundary.revision)
        self.assertEqual(38,self.state.life('B'))
        self.pass_round();self.assertEqual(34,self.state.life('B'))

    def test_lifelink_is_simultaneous_even_when_its_source_dies(self):
        self.setup_game(((2,2,('lifelink',)),),((3,3,()),));self.block()
        self.assertEqual(42,self.state.life('A'))
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current(self.attackers[0].card_id)).zone)

    def test_deathtouch_and_indestructible(self):
        for keywords,zone in (((),Zone.GRAVEYARD),(('indestructible',),Zone.BATTLEFIELD)):
            self.setup_game(((1,1,('deathtouch',)),),((5,5,keywords),));self.block()
            current=self.state.get(self.state.current(self.blockers[0].card_id))
            self.assertEqual(zone,current.zone)
            if zone==Zone.BATTLEFIELD:self.assertFalse(current.deathtouch_hit)

    def test_control_loss_removes_attacker_even_if_control_is_regained(self):
        self.setup_game();self.attack()
        self.state.change_control(self.attackers[0],'B');self.state.change_control(self.attackers[0],'A')
        # A direct fixture change invalidates an outstanding declaration; advance
        # removes that combatant before any new blocker request is prepared.
        self.kernel.advance();self.assertEqual([],self.kernel.combat['attackers'])
        self.pass_round();self.assertEqual(40,self.state.life('B'))

    def test_damage_choice_is_detached_and_checkpoint_replay_matches(self):
        self.setup_game(((5,5,('trample',)),),((2,2,()),));boundary=self.block()
        snapshot=self.kernel.snapshot();restored=RulesKernel.restore(snapshot,self.programs)
        boundary.specification['sources'][0]['power']=500
        self.assertEqual(5,self.kernel.combat['damage_pending']['specification']['sources'][0]['power'])
        answer={uid(self.attackers[0]):{'blockers':{uid(self.blockers[0]):2},'defender':3}}
        self.kernel.assign_combat_damage('A',answer,revision=boundary.revision)
        restored.assign_combat_damage('A',answer,revision=boundary.revision)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())

    def test_lethal_combat_damage_eliminates_defender_and_preserves_surviving_seats(self):
        self.setup_game(((40,40,()),),());self.attack()
        self.kernel.declare_blockers('B',{uid(self.attackers[0]):[]},revision=self.kernel.revision)
        self.kernel.pass_priority('A');self.kernel.pass_priority('B')
        self.kernel.pass_priority('C')
        self.assertEqual(('A','C'),self.state.live_players)
        self.assertEqual(0,self.state.life('B'))
        self.assertEqual('A',self.kernel.priority)

    def test_damage_primitive_uses_shared_damage_and_sbas(self):
        self.setup_game(((2,2,('deathtouch',)),),((9,9,()),))
        # Independent scenario engine, using authored source/target bindings.
        kernel=RulesKernel(self.state,self.programs)
        kernel.execute_for_scenario(self.attackers[0],'A',(Damage('source',1),))
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current(self.attackers[0].card_id)).zone)

    def test_deathtouch_trample_needs_no_more_damage_on_already_lethal_blocker(self):
        self.setup_game(((3,3,('deathtouch','trample')),),((2,2,('indestructible',)),))
        self.state.damage_batch(({'source':self.state.get(self.attackers[0]),'target':self.blockers[0],'amount':2},))
        boundary=self.block()
        self.assertEqual(0,boundary.specification['sources'][0]['blockers'][0]['lethal'])
        self.kernel.assign_combat_damage('A',{uid(self.attackers[0]):{'blockers':{uid(self.blockers[0]):0},'defender':3}},revision=boundary.revision)
        self.assertEqual(37,self.state.life('B'))

    def test_multiple_defenders_receive_separate_block_choices_and_one_damage_batch(self):
        self.setup_game(((4,4,('trample',)),(4,4,('trample',))),((2,2,()),))
        other=self.state.add_card('Cblock','B0','C',Zone.BATTLEFIELD)
        self.kernel.declare_attackers('A',{self.attackers[0]:'B',self.attackers[1]:'C'},revision=self.kernel.revision)
        boundary=self.pass_round();self.assertEqual('B',boundary.actor)
        boundary=self.kernel.declare_blockers('B',{uid(self.attackers[0]):[uid(self.blockers[0])]},revision=boundary.revision)
        self.assertEqual('C',boundary.actor)
        self.kernel.declare_blockers('C',{uid(self.attackers[1]):[uid(other)]},revision=boundary.revision)
        boundary=self.pass_round()
        self.assertEqual(['B','C'],[row['defender'] for row in boundary.specification['sources']])
        self.kernel.assign_combat_damage('A',{
            uid(self.attackers[0]):{'blockers':{uid(self.blockers[0]):2},'defender':2},
            uid(self.attackers[1]):{'blockers':{uid(other):2},'defender':2}},revision=boundary.revision)
        self.assertEqual((38,38),(self.state.life('B'),self.state.life('C')))

    def test_commander_damage_tracks_physical_identity_across_blinks(self):
        state=RulesState(('A','B'))
        ref=state.add_card('commander','body','A',Zone.BATTLEFIELD,commander=True)
        state.damage_batch(({'source':state.get(ref),'target':'B','amount':3,'combat':True},))
        state.move((ZoneMove(ref,Zone.EXILE),),'blink')
        state.move((ZoneMove(state.current('commander'),Zone.BATTLEFIELD),),'return')
        state.damage_batch(({'source':state.get(state.current('commander')),'target':'B','amount':4,'combat':True},))
        snapshot=state.snapshot()
        self.assertEqual([{'player':'B','card_id':'commander','amount':7}],snapshot['commander_damage'])
        self.assertEqual(snapshot,RulesState.restore(snapshot).snapshot())
        for row in ({'player':'Z','card_id':'commander','amount':7},
                    {'player':'B','card_id':'missing','amount':7},
                    {'player':'B','card_id':'commander','amount':True}):
            invalid={**snapshot,'commander_damage':[row]}
            with self.assertRaises(RulesViolation):RulesState.restore(invalid)
        with self.assertRaises(RulesViolation):
            RulesState.restore({**snapshot,'commander_damage':snapshot['commander_damage']*2})
