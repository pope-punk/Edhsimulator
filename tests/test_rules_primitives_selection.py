"""Resolution selections do as much as possible; targets and costs stay strict."""
import unittest
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_program import (CardProgram,Select,Selector,Sacrifice,GainLife,Move,
    CostSpec,ActivatedProgram,TargetSpec,CastSpec)
from edh_gauntlet.rules_kernel import RulesKernel


class SelectionTests(unittest.TestCase):
    def game(self,count=0):
        self.programs=(CardProgram('source','Source',('Artifact',)),CardProgram('c','Creature',('Creature',),power=1,toughness=1))
        self.state=RulesState(('A','B'));self.source=self.state.add_card('source','source','A',Zone.BATTLEFIELD)
        self.refs=[self.state.add_card(str(i),'c','A',Zone.BATTLEFIELD) for i in range(count)]
        self.kernel=RulesKernel(self.state,self.programs)

    def select(self,minimum,maximum,**kwargs):
        return self.kernel.execute_for_scenario(self.source,'A',(
            Select(Selector(Zone.BATTLEFIELD,types=('Creature',)),minimum,maximum,(Sacrifice('selected'),),**kwargs),GainLife(1)))

    def test_no_eligible_objects_does_not_prevent_later_effects(self):
        self.game();self.assertIsNone(self.select(3,3));self.assertEqual(41,self.state.life('A'))
        self.assertIsNone(self.kernel.pending_choice)

    def test_shortage_forces_available_set_in_one_atomic_batch(self):
        self.game(2);self.assertIsNone(self.select(3,3))
        self.assertTrue(all(self.state.get(self.state.current(ref.card_id)).zone==Zone.GRAVEYARD for ref in self.refs))
        self.assertEqual(1,len({event.batch for event in self.state.events}))
        self.assertEqual(41,self.state.life('A'))

    def test_real_choice_remains_and_cannot_choose_fewer_than_required(self):
        self.game(3);request=self.select(2,2);before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.answer(request.request_id,'A',[0])
        self.assertEqual(before,self.kernel.snapshot())
        restored=RulesKernel.restore(before,self.programs)
        self.kernel.answer(request.request_id,'A',[0,2]);restored.answer(request.request_id,'A',[0,2])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual(1,len(self.state.objects(Zone.BATTLEFIELD))-1)

    def test_optional_selection_and_ordered_selection_are_not_forced(self):
        self.game(2);request=self.select(0,2);self.assertEqual(0,request.minimum)
        self.kernel.answer(request.request_id,'A',[]);self.assertEqual(2,len(self.state.objects(Zone.BATTLEFIELD))-1)
        self.game(2);request=self.select(2,2,ordered=True)
        self.assertTrue(request.ordered);self.kernel.answer(request.request_id,'A',[1,0])
        self.assertEqual(['1','0'],[event.before.ref.card_id for event in self.state.events])

    def test_group_capacity_still_requires_choosing_between_group_members(self):
        self.game(2);request=self.select(3,3,group_by_controller=True)
        self.assertEqual((1,1),(request.minimum,request.maximum))
        self.kernel.answer(request.request_id,'A',[1])
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.refs[0]).zone)

    def test_tap_cost_cannot_pay_with_only_part_of_required_set(self):
        from edh_gauntlet.rules_casting import Payment
        self.game(1)
        program=CardProgram('source','Source',('Artifact',),activated=(ActivatedProgram('cost',
            CostSpec(tap_selector=Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled'),tap_count=2),(GainLife(1),)),))
        self.kernel=RulesKernel(self.state,(program,self.programs[1]));self.kernel.open_window_for_scenario('A')
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):
            quote=self.kernel.quote_activation('cost','A',self.source,'cost')
            self.kernel.commit_action(quote,Payment(taps=tuple(self.refs)))
        self.assertEqual(before,self.kernel.snapshot())


class BounceLandTests(unittest.TestCase):
    def test_lone_bounce_land_returns_itself_without_replaying_land_action(self):
        from edh_gauntlet.rules_bundle import load_reviewed
        from edh_gauntlet.rules_adapter import RulesActorAdapter
        programs=tuple(r['program'] for r in load_reviewed().values())
        for key in ('gruul-turf','simic-growth-chamber'):
            state=RulesState(('A','B'));ref=state.add_card('bounce','catalog:'+key,'A',Zone.HAND)
            state.add_card('draw','catalog:forest','A',Zone.LIBRARY)
            kernel=RulesKernel(state,programs);kernel.begin_turn_for_scenario('A')
            for _ in range(4):kernel.pass_priority(kernel.priority)
            adapter=RulesActorAdapter(kernel)
            def submit(actor,kind,**fields):return adapter.submit(actor,{'kind':kind,'revision':kernel.revision,**fields})
            submit('A','play_land',action_id='land',source=ref.to_json())
            self.assertTrue(state.get(state.current('bounce')).tapped)
            submit('A','pass');submit('B','pass')
            self.assertIsNone(kernel.pending_choice)
            self.assertEqual(Zone.HAND,state.get(state.current('bounce')).zone)
            self.assertEqual(1,kernel.turn_schedule['land_plays'])
            with self.assertRaises(RulesViolation):submit('A','play_land',action_id='again',source=state.current('bounce').to_json())
            restored=RulesActorAdapter.replay(adapter.archive(),programs)
            self.assertEqual(kernel.snapshot(),restored.kernel.snapshot())

    def test_bounce_selects_controlled_land_but_returns_it_to_its_owner(self):
        from edh_gauntlet.rules_bundle import load_reviewed
        programs=tuple(r['program'] for r in load_reviewed().values())
        state=RulesState(('A','B'));ref=state.add_card('bounce','catalog:gruul-turf','A',Zone.HAND)
        stolen=state.add_card('stolen','catalog:forest','B',Zone.BATTLEFIELD,controller='A')
        state.add_card('other','catalog:island','B',Zone.BATTLEFIELD)
        kernel=RulesKernel(state,programs)
        kernel.execute_for_scenario(ref,'A',(Move('source',Zone.BATTLEFIELD),))
        kernel.pass_priority('A');request=kernel.pass_priority('B')
        self.assertEqual({'bounce','stolen'},{option.ref.card_id for option in request.options})
        choice=next(i for i,o in enumerate(request.options) if o.ref==stolen)
        kernel.answer(request.request_id,'A',[choice])
        self.assertEqual(['stolen'],[obj.ref.card_id for obj in state.zone('B',Zone.HAND)])
        self.assertEqual(Zone.BATTLEFIELD,state.get(state.current('bounce')).zone)
