"""Combat target domains use current membership, including orphaned blockers."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_combat import uid
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class CombatTargetTests(unittest.TestCase):
    def game(self,keywords=(),extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(
            CardProgram('body','Body',('Creature',),power=3,toughness=5,keywords=keywords),
            CardProgram('legend','Legend',('Creature',),supertypes=('Legendary',),power=2,toughness=2))+tuple(extra)
        self.state=RulesState(('A','B'));self.attacker=self.state.add_card('attacker','body','A',Zone.BATTLEFIELD)
        self.blocker=self.state.add_card('blocker','body','B',Zone.BATTLEFIELD);self.bystander=self.state.add_card('bystander','body','A',Zone.BATTLEFIELD)
        self.ref=self.state.add_card('eiganjo','catalog:eiganjo-seat-of-the-empire','B',Zone.HAND)
        for actor in ('A','B'):self.state.add_card('draw'+actor,'catalog:forest',actor,Zone.LIBRARY)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.begin_turn_for_scenario('A')
        for _ in range(4):self.round()
    def round(self):
        for _ in self.state.players:self.kernel.pass_priority(self.kernel.priority)
    def block(self):
        self.kernel.declare_attackers('A',{self.attacker:'B'},revision=self.kernel.revision);self.round()
        self.kernel.declare_blockers('B',{uid(self.attacker):[uid(self.blocker)]},revision=self.kernel.revision)
    def legal(self,kind='attacking_or_blocking',kernel=None):
        kernel=kernel or self.kernel
        spec=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',)),combat=kind)
        frame={'source':kernel.state.get(kernel.state.current('eiganjo')).to_json(),'controller':'B'}
        return {o.ref for o in kernel._target_options(spec,frame)}
    def channel(self,target,generic=2):
        if self.kernel.priority=='A':self.kernel.pass_priority('A')
        self.state.add_mana('B',('C',)*generic+('W',))
        quote=self.kernel.quote_activation('channel','B',self.ref,'channel',(target,))
        self.assertEqual(ManaCost(generic,('W',)),quote.cost.mana)
        self.kernel.commit_action(quote,Payment(((('C',generic),) if generic else ())+(('W',1),)))
    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)

    def test_printed_channel_uses_discount_and_four_damage(self):
        self.game();self.block();self.state.add_card('legend','legend','B',Zone.BATTLEFIELD)
        self.channel(self.attacker,generic=1);self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('eiganjo')).zone)
        self.drain();self.assertEqual(4,self.state.get(self.attacker).damage_marked);self.assertFalse(self.state.mana_pool('B'))

    def test_target_domains_and_inspection_are_pure(self):
        self.game();before=self.kernel.snapshot();self.assertFalse(self.legal());self.assertEqual(before,self.kernel.snapshot())
        self.block();before=self.kernel.snapshot()
        self.assertEqual({self.attacker},self.legal('attacking'));self.assertEqual({self.blocker},self.legal('blocking'))
        self.assertEqual({self.attacker,self.blocker},self.legal());self.assertEqual(before,self.kernel.snapshot())
        self.kernel.pass_priority('A');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','B',self.ref,'channel',(self.bystander,))
        self.assertEqual(before,self.kernel.snapshot())

    def test_blocker_remains_blocking_after_attacker_leaves_but_assigns_no_damage(self):
        self.game();self.block();self.state.move((ZoneMove(self.attacker,Zone.HAND),),'response');self.kernel._combat_prune()
        self.assertEqual({self.blocker},self.legal());self.assertEqual([],self.kernel._prepare_damage()['assignments'])
        self.channel(self.blocker);self.drain();self.assertEqual(4,self.state.get(self.blocker).damage_marked)

    def test_orphaned_blocker_can_create_first_strike_step_and_survives_replay(self):
        self.game(('first_strike',));self.block()
        self.state.move((ZoneMove(self.attacker,Zone.GRAVEYARD),),'response');self.kernel._combat_prune()
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        for kernel in (self.kernel,replay.kernel):kernel._start_damage_step(first=True)
        self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot());self.assertEqual('first_strike_damage',self.kernel.phase)
        self.assertEqual([],self.kernel._prepare_damage()['assignments'])

    def test_target_that_phases_out_fizzles_without_refunding_cost(self):
        self.game();self.block();self.channel(self.attacker)
        self.state.phase(self.attacker,True);before=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(before.archive(),self.programs)
        self.drain();self.drain(replay.kernel);self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot())
        self.assertEqual(0,self.state.get(self.attacker).damage_marked);self.assertFalse(self.state.mana_pool('B'))
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('eiganjo')).zone)

    def test_blocker_control_change_removes_only_that_blocker(self):
        self.game();self.block();self.state.change_control(self.blocker,'A');self.kernel._combat_prune()
        self.assertEqual({self.attacker},self.legal());self.assertIn(uid(self.attacker),self.kernel.combat['blocked'])
        self.assertEqual([],self.kernel._prepare_damage()['assignments'])

    def test_end_combat_membership_ends_at_postcombat_main(self):
        self.game();self.block();self.kernel._begin_phase('end_combat');self.assertEqual({self.attacker,self.blocker},self.legal())
        self.kernel._begin_phase('postcombat_main');self.assertFalse(self.legal())

    def test_combat_target_validation_and_codec(self):
        spec=TargetSpec(Selector(Zone.BATTLEFIELD),combat='blocking')
        self.assertEqual(spec,decode(encode(spec)))
        for bad in (replace(spec,combat='blocked'),replace(spec,combat=True),replace(spec,selector=Selector(Zone.GRAVEYARD)),replace(spec,selector=None,players='all'),replace(spec,players='opponents')):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),spell_targets=bad,spell_effects=(Damage('target',1),)))

    def test_trigger_target_menu_uses_same_membership_and_replays(self):
        target=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',)),combat='blocking')
        observer=CardProgram('observer','Observer',('Enchantment',),abilities=(AbilityProgram('end',EventPattern('step_began',step='end_combat'),(Damage('target',1),),targets=target),))
        self.game(extra=(observer,));self.state.add_card('observer','observer','A',Zone.BATTLEFIELD);self.block()
        self.state.move((ZoneMove(self.attacker,Zone.HAND),),'response');self.kernel._combat_prune()
        self.kernel._begin_phase('end_combat');self.kernel.advance();q=self.kernel.pending_choice
        self.assertEqual({self.blocker},{o.ref for o in q.options})
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        cmd={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[0]}
        adapter.submit(q.actor,cmd);replay.submit(q.actor,cmd);self.drain();self.drain(replay.kernel)
        self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot());self.assertEqual(1,self.state.get(self.blocker).damage_marked)
