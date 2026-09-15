"""Distinct-name library search and actor-bound revealed-card partitioning."""
from dataclasses import replace
import unittest,json
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,PlayerRef,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_actor import project_actor

class SearchPartitionTests(unittest.TestCase):
    def game(self):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(CardProgram('redirect','Graveyard replacement',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE),)),)
        self.s=RulesState(('A','B','C'),seed=45)
        for card_id,definition in [('f1','forest'),('f2','forest'),('i','island'),('s','swamp'),('m','mountain'),('p','plains')]:self.s.add_card(card_id,'catalog:'+definition,'A',Zone.LIBRARY)
        self.ref=self.s.add_card('gifts','catalog:gifts-ungiven','A',Zone.HAND)
        self.k=RulesKernel(self.s,self.programs);self.k.open_window_for_scenario('A');self.s.add_mana('A',('C','C','C','U'))
    def cast(self):
        self.k.commit_action(self.k.quote_cast('cast','A',self.ref,(PlayerRef('B'),)),Payment((('C',3),('U',1))));self.drain()
    def drain(self,k=None):
        k=k or self.k
        while k.stack and not k.pending_choice:k.pass_priority(k.priority)
    def select(self,names,k=None):
        k=k or self.k;q=k.pending_choice
        k.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.ref.card_id==name) for name in names])
    def test_paid_search_and_opponent_partition_are_batched_and_separate(self):
        self.game();self.cast();q=self.k.pending_choice
        self.assertEqual(('A','library_search',0,4,True),(q.actor,q.kind,q.minimum,q.maximum,q.one_per_group))
        self.select(['f1','i','s','m']);q=self.k.pending_choice
        self.assertEqual(('B','search_partition',2,2),(q.actor,q.kind,q.minimum,q.maximum))
        self.select(['i','m']);self.drain()
        self.assertEqual({'f1','s'},{o.ref.card_id for o in self.s.zone('A',Zone.HAND)})
        self.assertEqual({'gifts','i','m'},{o.ref.card_id for o in self.s.zone('A',Zone.GRAVEYARD)})
        self.assertEqual(1,self.s.snapshot()['shuffle_nonce'])
        for kind in ('library_searched','cards_revealed','library_shuffled'):self.assertEqual(1,sum(e['kind']==kind for e in self.k.semantic_events))
    def test_duplicate_names_and_wrong_actor_are_rejected_without_mutation(self):
        self.game();self.cast();q=self.k.pending_choice;before=self.k.snapshot()
        with self.assertRaises(RulesViolation):self.select(['f1','f2'])
        self.assertEqual(before,self.k.snapshot())
        with self.assertRaises(RulesViolation):self.k.answer(q.request_id,'B',[0])
        self.assertEqual(before,self.k.snapshot())
    def test_zero_one_and_two_results_have_forced_partition_without_extra_prompt(self):
        for names in ([],['f1'],['f1','i']):
            self.game();self.cast();self.select(names);self.drain()
            self.assertIsNone(self.k.pending_choice);self.assertFalse(self.s.zone('A',Zone.HAND))
            self.assertEqual(set(names)|{'gifts'},{o.ref.card_id for o in self.s.zone('A',Zone.GRAVEYARD)})
            self.assertEqual(1,self.s.snapshot()['shuffle_nonce'])
    def test_partition_player_sees_only_revealed_candidates(self):
        self.game();self.cast()
        with self.assertRaises(RulesViolation):self.k.inspect_library_search('B')
        self.select(['f1','i','s','m'])
        self.assertEqual({'f1','i','s','m'},{o.ref.card_id for o in self.k.pending_choice.options})
        for actor in ('A','B','C'):
            with self.assertRaises(RulesViolation):self.k.inspect_library_search(actor)
        b=json.dumps(project_actor(self.k,'B'));c=json.dumps(project_actor(self.k,'C'))
        self.assertNotIn('"f2"',b);self.assertNotIn('"p"',b);self.assertNotIn('search_partition',c)
    def test_checkpoint_at_each_choice_preserves_search_and_reveal_once(self):
        self.game();self.cast();restored=RulesKernel.restore(self.k.snapshot(),self.programs)
        for k in (self.k,restored):self.select(['f1','i','s','m'],k)
        self.assertEqual(self.k.snapshot(),restored.snapshot())
        a=RulesActorAdapter(self.k);b=RulesActorAdapter.replay(a.archive(),self.programs)
        for k in (self.k,b.kernel):self.select(['f1','s'],k);self.drain(k)
        self.assertEqual(self.k.snapshot(),b.kernel.snapshot())
        self.assertEqual(1,sum(e['kind']=='cards_revealed' for e in self.k.semantic_events))
    def test_single_name_capacity_and_controller_partition_are_general(self):
        s=RulesState(('A','B'));p=CardProgram('source','Source',('Artifact',));land=CardProgram('land','Same name',('Land',))
        ref=s.add_card('source','source','A',Zone.BATTLEFIELD)
        for i in range(5):s.add_card(str(i),'land','A',Zone.LIBRARY)
        k=RulesKernel(s,(p,land));k.execute_for_scenario(ref,'A',(SearchLibrary(Selector(Zone.LIBRARY,relation='owned'),Zone.HAND,count=4,distinct_names=True,secondary_destination=Zone.GRAVEYARD,partition_player='controller'),))
        q=k.pending_choice;self.assertEqual(1,q.maximum);k.answer(q.request_id,'A',[0])
        self.assertEqual(1,len(s.zone('A',Zone.HAND)));self.assertEqual(4,len(s.zone('A',Zone.LIBRARY)))
    def test_graveyard_replacement_applies_to_only_the_chosen_partition(self):
        self.game();self.s.add_card('rip','redirect','C',Zone.BATTLEFIELD);self.cast();self.select(['f1','i','s','m']);self.select(['f1','i']);self.drain()
        self.assertEqual({'f1','i','gifts'},{o.ref.card_id for o in self.s.zone('A',Zone.EXILE)})
        self.assertEqual({'s','m'},{o.ref.card_id for o in self.s.zone('A',Zone.HAND)})
    def test_codec_and_closed_partition_validation(self):
        p=load_reviewed()['gifts-ungiven']['program'];self.assertEqual(p,decode(encode(p)));effect=p.spell_effects[0]
        for bad in (replace(effect,reveal=False),replace(effect,secondary_destination=None),replace(effect,partition_player='opponents'),replace(effect,distinct_names=1)):
            with self.assertRaises(RulesViolation):validate(replace(p,spell_effects=(bad,)))
        for targets in (None,TargetSpec(players='opponents',maximum=2),TargetSpec(Selector(Zone.BATTLEFIELD))):
            with self.assertRaises(RulesViolation):validate(replace(p,spell_targets=targets))
        self.game()
        with self.assertRaises(RulesViolation):self.k.quote_cast('self','A',self.ref,(PlayerRef('A'),))

if __name__=='__main__':unittest.main()
