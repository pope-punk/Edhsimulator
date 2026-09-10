"""Panda's death targets retain power and exclude the source's public successor."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class PandaTests(unittest.TestCase):
    def game(self,zone=Zone.BATTLEFIELD):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+tuple(CardProgram('body'+str(i),'Body '+str(i),('Creature',),mana_value=i,power=1,toughness=1) for i in (0,2,4,6))+(CardProgram('bear','Bear',('Creature',),subtypes=('Bear',),mana_value=1,power=1,toughness=1),)
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('panda','catalog:fiendish-panda','A',zone)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)

    def test_printed_cast_and_one_counter_per_life_event(self):
        self.game(Zone.HAND);self.state.add_mana('A',('C','C','W','B'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.ref),Payment((('C',2),('W',1),('B',1))));self.drain();self.ref=self.state.current('panda')
        self.kernel.execute_for_scenario(self.ref,'A',(GainLife(5),));self.drain()
        self.assertEqual((('+1/+1',1),),self.state.get(self.ref).counters)
        self.kernel.execute_for_scenario(self.ref,'B',(GainLife(3),));self.drain()
        self.assertEqual((('+1/+1',1),),self.state.get(self.ref).counters)

    def test_death_uses_last_power_and_restricts_subtype_and_owner_across_replay(self):
        self.game()
        for i in (2,4,6):self.state.add_card('body'+str(i),'body'+str(i),'A',Zone.GRAVEYARD)
        self.state.add_card('bear','bear','A',Zone.GRAVEYARD);self.state.add_card('opponent','body2','B',Zone.GRAVEYARD)
        q=self.kernel.execute_for_scenario(self.ref,'A',(UntilEndOfTurn('source',(ModifyPT(2,0),)),Destroy('source')))
        self.assertEqual({'body2','body4'},{o.ref.card_id for o in q.options})
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        command={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[next(i for i,o in enumerate(q.options) if o.ref.card_id=='body4')]}
        for item in (adapter,replay):item.submit('A',command);self.drain(item.kernel)
        self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot());self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('body4')).zone)

    def test_copy_cannot_target_its_own_nonbear_graveyard_successor(self):
        self.game(Zone.GRAVEYARD);ref=self.state.add_card('copy','body0','B',Zone.HAND)
        self.state.move((ZoneMove(ref,Zone.BATTLEFIELD,'B',copied_definition='catalog:fiendish-panda'),),'fixture-copy')
        self.state.add_card('other','body2','B',Zone.GRAVEYARD)
        q=self.kernel.execute_for_scenario(self.state.current('copy'),'B',(Destroy('source'),))
        # One legal target still has a target-choice boundary; source successor is excluded.
        self.assertEqual('B',q.actor);self.assertEqual(['other'],[o.ref.card_id for o in q.options])
        self.kernel.answer(q.request_id,'B',[0]);self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('copy')).zone)
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('other')).zone)

    def test_negative_power_death_has_no_zero_cost_target(self):
        self.game();self.state.add_card('zero','body0','A',Zone.GRAVEYARD)
        self.kernel.execute_for_scenario(self.ref,'A',(UntilEndOfTurn('source',(SetPT(-1,2),)),Destroy('source')))
        self.assertIsNone(self.kernel.pending_choice);self.assertFalse(self.kernel.stack)
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('zero')).zone)

    def test_target_leaving_graveyard_invalidates_return(self):
        self.game();target=self.state.add_card('target','body2','A',Zone.GRAVEYARD)
        q=self.kernel.execute_for_scenario(self.ref,'A',(Destroy('source'),));self.kernel.answer(q.request_id,'A',[0])
        self.state.move((ZoneMove(target,Zone.EXILE),),'fixture-response');self.drain()
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('target')).zone)

    def test_successor_exclusion_is_exact_and_not_a_permanent_card_id_ban(self):
        self.game(Zone.GRAVEYARD);ref=self.state.add_card('copy','body0','A',Zone.HAND)
        self.state.move((ZoneMove(ref,Zone.BATTLEFIELD,'A',copied_definition='catalog:fiendish-panda'),),'fixture-copy')
        self.state.add_card('other','body2','A',Zone.GRAVEYARD)
        self.kernel.execute_for_scenario(self.state.current('copy'),'A',(Destroy('source'),))
        occurrence=self.kernel.pending_triggers[0]
        successor=self.state.current('copy')
        self.state.move((ZoneMove(successor,Zone.EXILE),),'fixture-move')
        self.state.move((ZoneMove(self.state.current('copy'),Zone.GRAVEYARD),),'fixture-return')
        context={'source':occurrence['source'],'controller':'A','values':occurrence['values']}
        spec=decode(occurrence['ability']).targets
        self.assertIn(self.state.current('copy'),[o.ref for o in self.kernel._target_options(spec,context)])
        with self.assertRaises(RulesViolation):self.kernel.answer(self.kernel.pending_choice.request_id,'A',[0])
