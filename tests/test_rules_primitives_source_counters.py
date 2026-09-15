"""Source-counter quantities preserve the exact sacrificed incarnation."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class SourceCounterTests(unittest.TestCase):
    def game(self,zone=Zone.BATTLEFIELD,extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+tuple(extra)
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('lotus','catalog:lotus-blossom','A',zone)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def activate(self,actor='A'):
        self.kernel.open_window_for_scenario(actor)
        return self.kernel.commit_action(self.kernel.quote_activation('mana',actor,self.ref,'mana'),Payment())

    def drain(self):
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)

    def test_printed_cast_and_only_controller_upkeep_optional_counter(self):
        self.game(Zone.HAND);self.state.add_mana('A',('C','C'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.ref),Payment((('C',2),)));self.drain();self.ref=self.state.current('lotus')
        self.kernel.begin_step('B','upkeep');self.assertFalse(self.kernel.stack)
        for choice,expected in ((1,0),(0,1)):
            self.kernel.begin_step('A','upkeep');self.drain();q=self.kernel.pending_choice
            self.assertEqual('may',q.kind);self.kernel.answer(q.request_id,'A',[choice])
            self.assertEqual(expected,dict(self.state.get(self.ref).counters).get('petal',0))

    def test_sacrifice_retains_only_petal_count_and_replays_pending_mana_once(self):
        self.game();self.state.add_counters(self.ref,'petal',3);self.state.add_counters(self.ref,'charge',9)
        q=self.activate();self.assertEqual('mana_choice',q.kind);self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('lotus')).zone)
        self.assertEqual((),self.state.get(self.state.current('lotus')).counters);self.assertFalse(self.kernel.stack)
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        command={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[2]}
        adapter.submit('A',command);replay.submit('A',command)
        self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot());self.assertEqual((('B',3),),self.state.mana_pool('A'))
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):adapter.submit('A',command)
        self.assertEqual(before,self.kernel.snapshot())

    def test_zero_counters_still_pays_sacrifice_without_choice(self):
        self.game();self.assertIsNone(self.activate())
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('lotus')).zone);self.assertEqual((),self.state.mana_pool('A'))
        self.assertEqual(1,len(self.kernel.action_receipts))

    def test_replaced_sacrifice_destination_preserves_count_and_atomic_payment(self):
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,optional=True),))
        self.game(extra=(redirect,));self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD);self.state.add_counters(self.ref,'petal',4)
        before=self.state.snapshot();q=self.activate();self.assertEqual(before,self.state.snapshot())
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        for kernel in (self.kernel,restored):
            kernel.answer(q.request_id,'A',[0]);r=kernel.pending_choice;self.assertEqual('mana_choice',r.kind)
            kernel.answer(r.request_id,'A',[4])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertEqual(Zone.EXILE,self.state.get(self.state.current('lotus')).zone)
        self.assertEqual((('G',4),),self.state.mana_pool('A'))

    def test_new_incarnation_counters_do_not_replace_departed_source_information(self):
        self.game();self.state.add_counters(self.ref,'petal',2);q=self.activate()
        self.state.move((ZoneMove(self.state.current('lotus'),Zone.BATTLEFIELD),),'fixture-return')
        self.state.add_counters(self.state.current('lotus'),'petal',20)
        self.assertEqual(2,self.kernel._quantity(SourceCounter('petal'),self.kernel.resolving))
        with self.assertRaises(RulesViolation):self.kernel.answer(q.request_id,'A',[0])
        self.assertEqual((),self.state.mana_pool('A'))

    def test_copied_ability_uses_copy_counters_and_controller(self):
        self.game(Zone.GRAVEYARD);copy=self.state.add_card('copy','catalog:forest','B',Zone.HAND)
        self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,'B',copied_definition='catalog:lotus-blossom'),),'fixture-copy')
        self.ref=self.state.current('copy');self.state.add_counters(self.ref,'petal',5)
        q=self.activate('B');self.kernel.answer(q.request_id,'B',[1])
        self.assertEqual((('U',5),),self.state.mana_pool('B'));self.assertEqual((),self.state.mana_pool('A'))

    def test_generic_quantity_composition_and_validation(self):
        self.game();self.state.add_counters(self.ref,'charge',3)
        self.kernel.execute_for_scenario(self.ref,'A',(GainLife(ScaledValue(SourceCounter('charge'),2)),))
        self.assertEqual(46,self.state.life('A'));self.assertEqual(SourceCounter('petal'),decode(encode(SourceCounter('petal'))))
        for kind in ('',1,None):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Artifact',),spell_effects=(GainLife(SourceCounter(kind)),)))
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Artifact',),entry_counters=(EntryCounters('bad','petal',SourceCounter('petal')),)))
