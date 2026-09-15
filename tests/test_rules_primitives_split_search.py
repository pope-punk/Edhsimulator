"""Search partitions share one selection and one simultaneous movement batch."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed

class SplitSearchTests(unittest.TestCase):
    spell_id = 'cultivate'
    def game(self,extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+tuple(extra)
        self.state=RulesState(('A','B'));self.spell=self.state.add_card(self.spell_id,'catalog:'+self.spell_id,'A',Zone.HAND)
        self.refs=[self.state.add_card(str(i),'catalog:'+d,'A',Zone.LIBRARY) for i,d in enumerate(('forest','island','sol-ring','command-tower'))]
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def cast(self):
        self.state.add_mana('A',('C','C','G'));self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.spell),Payment((('C',2),('G',1))))
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)
        return self.kernel.pending_choice
    def answer(self,indexes,kernel=None):
        kernel=kernel or self.kernel;q=kernel.pending_choice;return kernel.answer(q.request_id,q.actor,indexes)

    def test_printed_cast_order_assigns_destinations_in_one_batch_then_shuffles_once(self):
        self.game();q=self.cast();self.assertEqual('library_search',q.kind);self.assertTrue(q.ordered)
        self.assertEqual({self.refs[0],self.refs[1]},{o.ref for o in q.options});self.assertEqual((0,2),(q.minimum,q.maximum))
        self.assertNotIn('library_search',RulesActorAdapter(self.kernel).packet('B'))
        self.answer([1,0]);island=self.state.get(self.state.current('1'));forest=self.state.get(self.state.current('0'))
        self.assertEqual(Zone.BATTLEFIELD,island.zone);self.assertTrue(island.tapped);self.assertEqual(Zone.HAND,forest.zone)
        events=[e for e in self.state.events if e.before.ref in self.refs[:2]];self.assertEqual(2,len(events));self.assertEqual(1,len({e.batch for e in events}))
        self.assertEqual(1,sum(e['kind']=='library_shuffled' for e in self.kernel.semantic_events))
        self.assertEqual(1,sum(e['kind']=='cards_revealed' for e in self.kernel.semantic_events))

    def test_finding_zero_or_one_assigns_first_to_battlefield_and_still_shuffles(self):
        for choices in ([],[0]):
            self.game();self.cast();self.answer(choices)
            self.assertFalse(self.state.zone('A',Zone.HAND))
            self.assertEqual(len(choices),len(self.state.zone('A',Zone.BATTLEFIELD)))
            self.assertEqual(1,sum(e['kind']=='library_shuffled' for e in self.kernel.semantic_events))

    def test_pending_secondary_replacement_keeps_both_groups_unmoved_and_replays(self):
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.HAND,Zone.EXILE,from_zone=Zone.LIBRARY,optional=True),))
        self.game((redirect,));self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD);self.cast();self.answer([0,1])
        for ref in self.refs:self.assertEqual(Zone.LIBRARY,self.state.get(ref).zone)
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs);q=self.kernel.pending_choice
        command={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[0]}
        adapter.submit(q.actor,command);replay.submit(q.actor,command);self.assertEqual(adapter.archive(),replay.archive())
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('0')).zone);self.assertEqual(Zone.EXILE,self.state.get(self.state.current('1')).zone)
        events=[e for e in self.state.events if e.before.ref in self.refs[:2]];self.assertEqual(1,len({e.batch for e in events}))
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):adapter.submit(q.actor,command)
        self.assertEqual(before,self.kernel.snapshot())

    def test_primary_replacement_does_not_promote_secondary_card(self):
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.BATTLEFIELD,Zone.EXILE,from_zone=Zone.LIBRARY,optional=True),))
        self.game((redirect,));self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD);self.cast();self.answer([0,1]);restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.answer([0]);self.answer([0],restored);self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('0')).zone);self.assertEqual(Zone.HAND,self.state.get(self.state.current('1')).zone)

    def test_general_reverse_partition_supports_secondary_tapped_entry(self):
        self.game();effect=SearchLibrary(Selector(Zone.LIBRARY,types=('Land',),relation='owned'),Zone.HAND,count=3,secondary_destination=Zone.BATTLEFIELD,primary_count=2,secondary_tapped=True)
        self.kernel.execute_for_scenario(self.spell,'A',(effect,));self.answer([0,1,2])
        found=[e for e in self.state.events if e.before.zone==Zone.LIBRARY]
        self.assertEqual(2,sum(e.after.zone==Zone.HAND for e in found));self.assertEqual(1,sum(e.after.zone==Zone.BATTLEFIELD and e.after.tapped for e in found));self.assertEqual(1,len({e.batch for e in found}))

    def test_invalid_partition_fields_are_rejected(self):
        base=CardProgram('test','Test',('Sorcery',));good=SearchLibrary(Selector(Zone.LIBRARY,relation='owned'),Zone.BATTLEFIELD,count=2,secondary_destination=Zone.HAND)
        self.assertEqual(good,decode(encode(good)))
        for bad in (replace(good,primary_count=0),replace(good,primary_count=True),replace(good,primary_count=3),replace(good,secondary_destination=Zone.LIBRARY),replace(good,secondary_destination=Zone.BATTLEFIELD),replace(good,secondary_tapped=True),replace(good,secondary_destination=None,primary_count=2)):
            with self.assertRaises(RulesViolation):validate(replace(base,spell_effects=(bad,)))


class KodamasReachTests(SplitSearchTests):
    """Run the same behavioral contract against the separately bound Arcane card."""
    spell_id = 'kodama-s-reach'

    def test_arcane_characteristics_and_sorcery_timing(self):
        self.game()
        program=load_reviewed()[self.spell_id]['program']
        self.assertEqual(('Arcane',),program.subtypes)
        self.assertEqual(('Sorcery',),program.types)
        self.state.add_mana('A',('C','C','G'))
        self.kernel.open_window_for_scenario('B')
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('off-turn','A',self.spell)
        self.assertEqual(before,self.kernel.snapshot())
