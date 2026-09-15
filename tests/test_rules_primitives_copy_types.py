"""Copiable additive type exceptions survive copying and reset across zones."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_replacements import ZoneProposal

class CopyTypesTests(unittest.TestCase):
    def setUp(self):
        self.land=CardProgram('land','Fixture land',('Land',),subtypes=('Island',),supertypes=('Basic',),abilities=(AbilityProgram('entry',EventPattern('zone_changed',to_zone=Zone.BATTLEFIELD,subject='self'),(GainLife(1),)),))
        self.clone=CardProgram('clone','Fixture clone',('Enchantment',),entry_copy=Selector(Zone.BATTLEFIELD,types=('Enchantment',)))
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(self.land,self.clone)
        self.state=RulesState(('A','B'));self.landref=self.state.add_card('land','land','B',Zone.BATTLEFIELD)
        self.ref=self.state.add_card('copy','catalog:copy-land','A',Zone.HAND)
        self.k=RulesKernel(self.state,self.programs);self.k.open_window_for_scenario('A')
    def drain(self,k=None):
        k=k or self.k
        while k.stack and not k.pending_choice:k.pass_priority(k.priority)
    def enter(self,ref,target=None,k=None):
        k=k or self.k;k.execute_for_scenario(ref,'A',(Move('source',Zone.BATTLEFIELD),))
        q=k.pending_choice
        k.answer(q.request_id,q.actor,[] if target is None else [next(i for i,o in enumerate(q.options) if o.ref.card_id==target)])
        self.drain(k)
        return k.state.current(ref.card_id)
    def test_paid_cast_inherits_land_types_mana_and_etb(self):
        self.state.add_mana('A',('C','C','U'))
        self.k.commit_action(self.k.quote_cast('cast','A',self.ref),Payment((('C',2),('U',1))));self.drain()
        q=self.k.pending_choice;self.k.answer(q.request_id,q.actor,[0]);self.drain()
        ref=self.state.current('copy');v=self.k.effective(ref)
        self.assertEqual(frozenset(('Land','Enchantment')),v.types);self.assertIn('Island',v.subtypes);self.assertIn('Basic',v.supertypes)
        self.assertEqual(0,v.mana_value);self.assertEqual(41,self.state.life('A'))
        self.k.open_window_for_scenario('A')
        abilities=self.k.activated_abilities(self.state.get(ref))
        self.assertTrue(abilities)
        self.k.commit_action(self.k.quote_activation('mana','A',ref,'intrinsic-land:Island'),Payment())
        self.assertEqual({'U':1},dict(self.state.mana_pool('A')))
    def test_declining_copy_retains_printed_enchantment(self):
        ref=self.enter(self.ref);self.assertEqual(frozenset(('Enchantment',)),self.k.effective(ref).types)
        self.assertEqual((),self.state.get(ref).copied_add_types);self.assertEqual(40,self.state.life('A'))
    def test_copy_of_copy_inherits_exception_even_without_own_exception(self):
        self.enter(self.ref,'land')
        clone=self.state.add_card('clone','clone','A',Zone.HAND);new=self.enter(clone,'copy')
        self.assertEqual(('Enchantment',),self.state.get(new).copied_add_types)
        self.assertEqual(frozenset(('Land','Enchantment')),self.k.effective(new).types)
        self.assertEqual(42,self.state.life('A'))
    def test_noncopy_effects_counters_and_tapped_status_are_not_copied(self):
        self.state.set_tapped_batch((self.landref,),True)
        self.k.execute_for_scenario(self.landref,'B',(AddCounters('source','charge',2),UntilEndOfTurn('source',(ChangeTypes(add=('Artifact',)),)),))
        ref=self.enter(self.ref,'land')
        self.assertNotIn('Artifact',self.k.effective(ref).types);self.assertFalse(self.state.get(ref).tapped)
        self.assertFalse(self.state.get(ref).token);self.assertEqual((),self.state.get(ref).counters)
    def test_zone_change_resets_exception_and_new_copy_can_be_declined(self):
        ref=self.enter(self.ref,'land');self.k.execute_for_scenario(ref,'A',(Move('source',Zone.HAND),))
        hand=self.state.current('copy');self.assertEqual((),self.state.get(hand).copied_add_types)
        self.assertEqual(3,self.k.effective(hand).mana_value)
        ref=self.enter(hand);self.assertEqual(frozenset(('Enchantment',)),self.k.effective(ref).types)
    def test_pending_copy_and_completed_actor_archive_roundtrip(self):
        self.k.execute_for_scenario(self.ref,'A',(Move('source',Zone.BATTLEFIELD),))
        restored=RulesKernel.restore(self.k.snapshot(),self.programs)
        for k in (self.k,restored):
            q=k.pending_choice;k.answer(q.request_id,q.actor,[0]);self.drain(k)
        self.assertEqual(self.k.snapshot(),restored.snapshot())
        a=RulesActorAdapter(self.k);b=RulesActorAdapter.replay(a.archive(),self.programs)
        self.assertEqual(a.archive(),b.archive())
    def test_cache_distinguishes_copiable_type_exception(self):
        proposal=ZoneProposal(self.state.get(self.ref),Zone.BATTLEFIELD,'A',copied_definition='land')
        ordinary=self.k._proposal_view(proposal)
        enchanted=self.k._proposal_view(replace(proposal,copied_add_types=('Enchantment',)))
        self.assertNotIn('Enchantment',ordinary[1].types);self.assertIn('Enchantment',enchanted[1].types)
    def test_closed_codec_and_invalid_exceptions(self):
        p=load_reviewed()['copy-land']['program'];self.assertEqual(p,decode(encode(p)))
        for value in (['Enchantment'],('NoSuchType',),('Enchantment','Enchantment')):
            with self.assertRaises(RulesViolation):validate(replace(p,entry_copy_add_types=value))
        with self.assertRaises(RulesViolation):validate(replace(p,entry_copy=None))
        before=self.state.snapshot()
        with self.assertRaises(RulesViolation):self.state.move((ZoneMove(self.ref,Zone.BATTLEFIELD,copied_add_types=('Enchantment',)),),'invalid')
        self.assertEqual(before,self.state.snapshot())

if __name__=='__main__':unittest.main()
