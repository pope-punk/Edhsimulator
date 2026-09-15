"""Search-to-top retains chosen ordering while shuffling and hiding the rest."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_adapter import RulesActorAdapter


class TopTutorTests(unittest.TestCase):
    def game(self,key='vampiric-tutor',empty=False,extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+extra
        self.state=RulesState(('A','B'));self.spell=self.state.add_card('spell','catalog:'+key,'A',Zone.HAND)
        if not empty:
            for i,definition in enumerate(('forest','sol-ring','polluted-bonds','forest')):self.state.add_card('card'+str(i),'catalog:'+definition,'A',Zone.LIBRARY)
        for i,program in enumerate(extra):self.state.add_card('observer'+str(i),program.definition_id,'A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('B',priority_actor='A')
        color='W' if key=='enlightened-tutor' else 'B';self.state.add_mana('A',(color,))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.spell),Payment(((color,1),)))
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)

    def test_vampiric_search_is_required_private_and_loses_life(self):
        self.game();q=self.kernel.pending_choice;self.assertEqual(1,q.minimum)
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.answer(q.request_id,'A',[])
        self.assertEqual(before,self.kernel.snapshot());chosen=q.options[0].ref
        self.kernel.answer(q.request_id,'A',[0])
        self.assertEqual(chosen.card_id,self.state.zone('A',Zone.LIBRARY)[-1].ref.card_id)
        self.assertEqual(38,self.state.life('A'));self.assertEqual((),self.state.mana_pool('A'))
        self.assertFalse(any(e['kind']=='cards_revealed' for e in self.kernel.semantic_events))
        adapter=RulesActorAdapter(self.kernel)
        self.assertEqual(chosen.card_id,adapter.packet('A')['library_observation']['cards'][0]['ref']['card_id'])
        self.assertNotIn('library_observation',adapter.packet('B'))
        with self.assertRaises(RulesViolation):self.state.get(chosen)

    def test_enlightened_quality_and_reveal(self):
        self.game('enlightened-tutor');q=self.kernel.pending_choice
        self.assertEqual(0,q.minimum);self.assertEqual({'card1','card2'},{o.ref.card_id for o in q.options})
        chosen=q.options[0].ref;self.kernel.answer(q.request_id,'A',[0])
        self.assertEqual(chosen.card_id,self.state.zone('A',Zone.LIBRARY)[-1].ref.card_id)
        self.assertEqual(40,self.state.life('A'))
        revealed=[e for e in self.kernel.semantic_events if e['kind']=='cards_revealed']
        self.assertEqual([chosen.to_json()],revealed[0]['refs'])

    def test_failed_quality_search_and_empty_library_still_finish(self):
        self.game('enlightened-tutor');q=self.kernel.pending_choice;self.kernel.answer(q.request_id,'A',[])
        self.assertEqual(4,len(self.state.zone('A',Zone.LIBRARY)));self.assertEqual(1,self.state.snapshot()['shuffle_nonce'])
        self.assertNotIn('A',self.kernel.library_observations)
        self.game(empty=True)
        if self.kernel.pending_choice:
            q=self.kernel.pending_choice;self.kernel.answer(q.request_id,'A',[])
        self.assertEqual(38,self.state.life('A'));self.assertEqual(1,self.state.snapshot()['shuffle_nonce'])

    def test_checkpoint_and_actor_replay_shuffle_once_without_zone_changes(self):
        self.game();q=self.kernel.pending_choice;restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        adapter=RulesActorAdapter(self.kernel)
        adapter.submit('A',{'kind':'answer','request_id':q.request_id,'indexes':[1],'revision':self.kernel.revision})
        restored.answer(q.request_id,'A',[1]);self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        for actor in self.state.players:self.assertEqual(adapter.packet(actor),replay.packet(actor))
        self.assertEqual(1,self.state.snapshot()['shuffle_nonce'])
        self.assertFalse(any(e.before.ref.card_id.startswith('card') for e in self.state.events))

    def test_multicard_top_search_uses_one_ordered_selection(self):
        self.game();q=self.kernel.pending_choice;self.kernel.answer(q.request_id,'A',[0])
        source=self.state.current('spell')
        q=self.kernel.execute_for_scenario(source,'A',(SearchLibrary(Selector(Zone.LIBRARY,relation='owned'),Zone.LIBRARY,count=3),))
        self.assertTrue(q.ordered);chosen=[q.options[i].ref.card_id for i in (2,0,1)]
        self.kernel.answer(q.request_id,'A',[2,0,1])
        self.assertEqual(chosen,[o.ref.card_id for o in reversed(self.state.zone('A',Zone.LIBRARY)[-3:])])
        self.assertEqual(chosen,[r['ref']['card_id'] for r in self.kernel.library_observations['A']['cards']])

    def test_top_destination_rejects_tapped_placement(self):
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),spell_effects=(SearchLibrary(Selector(Zone.LIBRARY,relation='owned'),Zone.LIBRARY,tapped=True),)))

    def test_shuffle_trigger_draws_only_after_tutored_card_is_on_top(self):
        observer=CardProgram('observer','Observer',('Enchantment',),abilities=(AbilityProgram('draw',EventPattern('library_shuffled',controller_only=True),(Draw(1),)),))
        self.game(extra=(observer,));q=self.kernel.pending_choice;kernel=self.kernel
        chosen=q.options[0].ref.card_id;kernel.answer(q.request_id,'A',[0])
        self.assertEqual(chosen,kernel.state.zone('A',Zone.LIBRARY)[-1].ref.card_id)
        self.assertEqual(38,kernel.state.life('A'));self.assertEqual(1,len(kernel.stack))
        restored=RulesKernel.restore(kernel.snapshot(),self.programs)
        for k in (kernel,restored):
            while k.stack:k.pass_priority(k.priority)
            self.assertEqual([chosen],[o.ref.card_id for o in k.state.zone('A',Zone.HAND)])
        self.assertEqual(kernel.snapshot(),restored.snapshot())
