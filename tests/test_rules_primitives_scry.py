"""Scry is one actor-private ordered partition; unseen library order stays intact."""
import unittest
from edh_gauntlet.rules_program import CardProgram,Scry,Draw,AbilityProgram,EventPattern,GainLife
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_adapter import RulesActorAdapter


class ScryTests(unittest.TestCase):
    def game(self,count=5):
        self.programs=[CardProgram('source','Source',('Artifact',))]
        self.state=RulesState(('A','B'));self.source=self.state.add_card('source','source','A',Zone.BATTLEFIELD)
        for i in range(count):
            self.programs.append(CardProgram(str(i),'Card '+str(i),('Land',)))
            self.state.add_card(str(i),str(i),'A',Zone.LIBRARY)
        self.kernel=RulesKernel(self.state,self.programs)

    def order(self):return [obj.ref.card_id for obj in reversed(self.state.zone('A',Zone.LIBRARY))]

    def test_one_partition_sets_top_and_bottom_order_without_touching_middle(self):
        self.game();request=self.kernel.execute_for_scenario(self.source,'A',(Scry(3),))
        self.assertEqual(['4','3','2'],[o.ref.card_id for o in request.options if o.ref])
        self.assertTrue(request.ordered);self.assertEqual((4,4),(request.minimum,request.maximum))
        self.kernel.answer(request.request_id,'A',[1,3,2,0]) # Top 3, then bottom 2,4.
        self.assertEqual(['3','1','0','2','4'],self.order())
        self.assertEqual(0,self.state.event_count)
        self.assertEqual(1,len([e for e in self.kernel.semantic_events if e['kind']=='scried']))

    def test_all_top_and_all_bottom_keep_requested_order(self):
        for indexes,expected in (([1,0,2],['3','4','2','1','0']),([2,1,0],['2','1','0','3','4'])):
            self.game();request=self.kernel.execute_for_scenario(self.source,'A',(Scry(2),))
            self.kernel.answer(request.request_id,'A',indexes);self.assertEqual(expected,self.order())

    def test_zero_is_no_event_but_empty_library_still_scries(self):
        self.game(0);self.assertIsNone(self.kernel.execute_for_scenario(self.source,'A',(Scry(0),)))
        self.assertFalse(any(e['kind']=='scried' for e in self.kernel.semantic_events))
        self.assertIsNone(self.kernel.execute_for_scenario(self.source,'A',(Scry(2),)))
        self.assertEqual(1,len([e for e in self.kernel.semantic_events if e['kind']=='scried']))

    def test_short_library_does_not_require_nonexistent_cards(self):
        self.game(1);request=self.kernel.execute_for_scenario(self.source,'A',(Scry(5),))
        self.assertEqual(2,len(request.options));self.kernel.answer(request.request_id,'A',[1,0])
        self.assertEqual(['0'],self.order())

    def test_private_request_excludes_unseen_tail_and_other_actors(self):
        import json
        self.game();self.kernel.execute_for_scenario(self.source,'A',(Scry(2),))
        adapter=RulesActorAdapter(self.kernel);own=adapter.packet('A');other=adapter.packet('B')
        self.assertNotIn('Card 2',json.dumps(own));self.assertNotIn('Card 4',json.dumps(other))
        self.assertNotIn('library_search',own)
        self.assertEqual({'kind':'waiting','actor':'A'},other['decision'])
        with self.assertRaises(RulesViolation):self.kernel.inspect_library_search('A')

    def test_bad_partitions_are_atomic_and_pending_archive_replays(self):
        self.game();self.kernel.execute_for_scenario(self.source,'A',(Scry(2),Draw()))
        adapter=RulesActorAdapter(self.kernel);request=self.kernel.pending_choice;before=self.kernel.snapshot()
        for actor,indexes in (('B',[0,1,2]),('A',[0,1]),('A',[0,0,2]),('A',[0,1,3])):
            with self.assertRaises(RulesViolation):adapter.submit(actor,{'kind':'answer','revision':self.kernel.revision,'request_id':request.request_id,'indexes':indexes})
            self.assertEqual(before,self.kernel.snapshot())
        adapter.submit('A',{'kind':'answer','revision':self.kernel.revision,'request_id':request.request_id,'indexes':[1,2,0]})
        self.assertEqual(['3'],[obj.ref.card_id for obj in self.state.zone('A',Zone.HAND)])
        replayed=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.assertEqual(self.kernel.snapshot(),replayed.kernel.snapshot())

    def test_scry_event_triggers_after_partition_even_for_empty_library(self):
        for count in (0,2):
            self.game(count)
            observer=CardProgram('observer','Observer',('Enchantment',),abilities=(
                AbilityProgram('scry-life',EventPattern('scried',controller_only=True),(GainLife(1),)),))
            self.state.add_card('observer','observer','A',Zone.BATTLEFIELD)
            self.kernel=RulesKernel(self.state,(*self.programs,observer))
            request=self.kernel.execute_for_scenario(self.source,'A',(Scry(2),))
            if count:self.kernel.answer(request.request_id,'A',[0,1,2])
            self.assertEqual(40,self.state.life('A'));self.assertEqual(1,len(self.kernel.stack))
            self.kernel.pass_priority('A');self.kernel.pass_priority('B');self.assertEqual(41,self.state.life('A'))


class AuthoredScryTests(unittest.TestCase):
    def test_opt_draws_after_scry_and_replays_with_private_projection(self):
        from edh_gauntlet.rules_bundle import load_reviewed
        programs=tuple(r['program'] for r in load_reviewed().values())
        state=RulesState(('A','B'));ref=state.add_card('opt','catalog:opt','B',Zone.HAND)
        state.add_card('bottom','catalog:forest','B',Zone.LIBRARY)
        state.add_card('top','catalog:island','B',Zone.LIBRARY)
        kernel=RulesKernel(state,programs);kernel.open_window_for_scenario('A',priority_actor='B');state.add_mana('B',('U',))
        adapter=RulesActorAdapter(kernel)
        def submit(actor,kind,**fields):return adapter.submit(actor,{'kind':kind,'revision':kernel.revision,**fields})
        submit('B','cast',action_id='opt',source=ref.to_json(),targets=[],x_value=0,payment={'mana':{'U':1},'taps':[]})
        submit('B','pass');packet=submit('A','pass')
        self.assertEqual('waiting',packet['decision']['kind'])
        request=adapter.packet('B')['decision']['choice'];self.assertEqual('scry',request['kind'])
        submit('B','answer',request_id=request['request_id'],indexes=[1,0])
        self.assertEqual(['bottom'],[o.ref.card_id for o in state.zone('B',Zone.HAND)])
        self.assertEqual(Zone.GRAVEYARD,state.get(state.current('opt')).zone)
        replayed=RulesActorAdapter.replay(adapter.archive(),programs)
        self.assertEqual(kernel.snapshot(),replayed.kernel.snapshot())

    def test_temple_enters_tapped_and_scries_on_trigger_resolution(self):
        from edh_gauntlet.rules_bundle import load_reviewed
        from edh_gauntlet.rules_program import Move
        programs=tuple(r['program'] for r in load_reviewed().values())
        for key in ('temple-of-mystery','temple-of-silence'):
            state=RulesState(('A','B'));ref=state.add_card('temple','catalog:'+key,'A',Zone.HAND)
            state.add_card('look','catalog:forest','A',Zone.LIBRARY)
            kernel=RulesKernel(state,programs)
            kernel.execute_for_scenario(ref,'A',(Move('source',Zone.BATTLEFIELD),))
            self.assertTrue(state.get(state.current('temple')).tapped)
            self.assertIsNone(kernel.pending_choice);self.assertEqual('entry-scry',kernel.stack[-1]['ability_id'])
            kernel.pass_priority('A');request=kernel.pass_priority('B')
            self.assertEqual('scry',request.kind);kernel.answer(request.request_id,'A',[0,1])
            self.assertEqual('look',state.zone('A',Zone.LIBRARY)[-1].ref.card_id)
