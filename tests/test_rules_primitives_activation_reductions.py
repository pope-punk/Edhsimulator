"""Dynamic activation reductions share quoted costs and atomic payments."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class ActivationReductionTests(unittest.TestCase):
    def game(self,extra=(),zone=Zone.HAND):
        legends=tuple(CardProgram('legend'+str(i),'Legend '+str(i),('Creature',),supertypes=('Legendary',),power=2,toughness=2) for i in range(5))
        self.programs=tuple(r['program'] for r in load_reviewed().values())+legends+tuple(extra)
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('otawara','catalog:otawara-soaring-city','A',zone)
        self.target=self.state.add_card('target','catalog:sol-ring','B',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
    def legend(self,i=0,actor='A'):return self.state.add_card('legend'+str(i),'legend'+str(i),actor,Zone.BATTLEFIELD)
    def quote(self):return self.kernel.quote_activation('channel','A',self.ref,'channel',(self.target,))
    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)

    def test_printed_channel_preserves_colored_cost_and_floors_generic(self):
        for count in (0,1,3,5):
            self.game()
            for i in range(count):self.legend(i)
            quote=self.quote();generic=max(0,3-count)
            self.assertEqual(ManaCost(generic,('U',)),quote.cost.mana)
            self.state.add_mana('A',('C',)*generic+('U',));quote=self.quote()
            payment=Payment(((('C',generic),) if generic else ())+(('U',1),))
            self.kernel.commit_action(quote,payment)
            self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('otawara')).zone)
            self.drain();self.assertEqual(Zone.HAND,self.state.get(self.state.current('target')).zone);self.assertFalse(self.state.mana_pool('A'))

    def test_reduction_observes_control_phasing_and_derived_creature_type(self):
        self.game();ref=self.legend();other=self.legend(1,'B');land=self.state.add_card('land','catalog:otawara-soaring-city','A',Zone.BATTLEFIELD)
        self.assertEqual(2,self.quote().cost.mana.generic)
        self.state.phase(ref,True);self.assertEqual(3,self.quote().cost.mana.generic)
        self.state.change_control(other,'A');self.assertEqual(2,self.quote().cost.mana.generic)
        # A land's legendary supertype alone is insufficient; animation supplies Creature.
        self.kernel.execute_for_scenario(land,'A',(UntilEndOfTurn('source',(ChangeTypes(add=('Creature',)),SetPT(2,2))),))
        self.kernel.open_window_for_scenario('A');self.assertEqual(1,self.quote().cost.mana.generic)

    def test_stale_discount_quote_and_wrong_colored_payment_are_atomic(self):
        self.game();ref=self.legend();quote=self.quote();self.state.change_control(ref,'B');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,Payment((('C',2),('U',1))))
        self.assertEqual(before,self.kernel.snapshot())
        self.state.add_mana('A',('C',)*4);before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(self.quote(),Payment((('C',4),)))
        self.assertEqual(before,self.kernel.snapshot())

    def test_channel_targets_and_activation_zones_are_enforced(self):
        self.game();land=self.state.add_card('land','catalog:forest','B',Zone.BATTLEFIELD)
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',self.ref,'channel',(land,))
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('mana','A',self.ref,'mana')
        self.state.move((ZoneMove(self.ref,Zone.BATTLEFIELD),),'play');self.ref=self.state.current('otawara')
        with self.assertRaises(RulesViolation):self.quote()
        self.kernel.commit_action(self.kernel.quote_activation('mana','A',self.ref,'mana'),Payment())
        self.assertEqual((('U',1),),self.state.mana_pool('A'))

    def test_pending_discard_replacement_recovers_without_double_payment(self):
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,from_zone=Zone.HAND,optional=True),))
        self.game((redirect,));self.legend();self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD);self.state.add_mana('A',('C','C','U'))
        self.kernel.commit_action(self.quote(),Payment((('C',2),('U',1))));q=self.kernel.pending_choice
        self.assertEqual(Zone.HAND,self.state.get(self.ref).zone);self.assertEqual((('C',2),('U',1)),self.state.mana_pool('A'))
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        cmd={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[0]}
        adapter.submit(q.actor,cmd);replay.submit(q.actor,cmd);self.assertEqual(adapter.archive(),replay.archive())
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('otawara')).zone);self.assertFalse(self.state.mana_pool('A'))
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):adapter.submit(q.actor,cmd)
        self.assertEqual(before,self.kernel.snapshot());self.drain();self.drain(replay.kernel);self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot())

    def test_target_departure_does_not_refund_channel_payment(self):
        self.game();self.state.add_mana('A',('C','C','C','U'));self.kernel.commit_action(self.quote(),Payment((('C',3),('U',1))))
        self.state.move((ZoneMove(self.target,Zone.GRAVEYARD),),'response');self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('target')).zone)
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('otawara')).zone);self.assertFalse(self.state.mana_pool('A'))

    def test_generic_discount_locks_before_sacrificing_counted_permanent(self):
        selector=Selector(Zone.BATTLEFIELD,types=('Creature',),supertypes=('Legendary',),relation='controlled')
        ability=ActivatedProgram('pay',CostSpec(ManaCost(3,('U',)),zone_costs=(ZoneCost('sac','sacrifice',selector),)),(GainLife(1),),generic_reduction=CountObjects(selector))
        self.game((CardProgram('payer','Payer',('Artifact',),activated=(ability,)),));legend=self.legend();payer=self.state.add_card('payer','payer','A',Zone.BATTLEFIELD);self.state.add_mana('A',('C','C','U'))
        quote=self.kernel.quote_activation('pay','A',payer,'pay');self.assertEqual(2,quote.cost.mana.generic)
        self.kernel.commit_action(quote,Payment((('C',2),('U',1)),zone_costs=(('sac',(legend,)),)));self.drain()
        self.assertEqual(41,self.state.life('A'));self.assertFalse(self.state.mana_pool('A'))
        self.kernel.open_window_for_scenario('A')
        self.assertEqual(3,self.kernel.quote_activation('next','A',payer,'pay').cost.mana.generic)

    def test_variable_generic_cost_and_validation(self):
        ability=ActivatedProgram('x',CostSpec(ManaCost(0,('U',),2)),(GainLife(1),),generic_reduction=2)
        self.game((CardProgram('payer','Payer',('Artifact',),activated=(ability,)),));ref=self.state.add_card('payer','payer','A',Zone.BATTLEFIELD)
        quote=self.kernel.quote_activation('x','A',ref,'x',x_value=3);self.assertEqual(ManaCost(4,('U',)),quote.cost.mana)
        for reduction in (-1,True,ChosenX(),SourceStat('power')):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Artifact',),activated=(replace(ability,generic_reduction=reduction),)))
        self.assertEqual(ability,decode(encode(ability)))
