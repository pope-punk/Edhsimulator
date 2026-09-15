"""Actor packets exclude hidden identities/order, internal tasks and other choices."""
import json
import unittest
from edh_gauntlet.rules_actor import project_actor
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_program import CardProgram,SearchLibrary,Selector,ChooseMana,CostSpec,ActivatedProgram
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment


class ActorProjectionTests(unittest.TestCase):
    def game(self,hidden='secret1',seed=10):
        self.programs=(CardProgram('public','Public source',('Artifact',)),
            CardProgram('own','Own hand',('Instant',)),CardProgram('secret1','SECRET ONE',('Land',)),
            CardProgram('secret2','SECRET TWO',('Creature',),power=1,toughness=1))
        self.state=RulesState(('A','B'),seed=seed)
        self.source=self.state.add_card('source','public','A',Zone.BATTLEFIELD)
        self.state.add_card('mine','own','A',Zone.HAND)
        self.state.add_card('hidden-hand-'+hidden,hidden,'B',Zone.HAND)
        self.state.add_card('hidden-library-'+hidden,hidden,'A',Zone.LIBRARY)
        self.state.add_card('other-library-'+hidden,hidden,'B',Zone.LIBRARY)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
        return project_actor(self.kernel,'A')

    def test_private_information_and_rng_do_not_change_other_actor_packet(self):
        first=self.game('secret1',10);second=self.game('secret2',999)
        self.assertEqual(first,second)
        text=json.dumps(second)
        for private in ('SECRET','hidden-library','hidden-hand','other-library','shuffle_seed','shuffle_nonce','tasks','answers','action_receipts'):
            self.assertNotIn(private,text)
        self.assertEqual(['Own hand'],[row['name'] for row in second['hand']])
        self.assertEqual(1,second['players'][1]['hand_count'])

    def test_read_is_pure_and_mutating_packet_cannot_mutate_kernel(self):
        self.game();before=self.kernel.snapshot();packet=project_actor(self.kernel,'A')
        packet['zones']['battlefield']['A'][0]['name']='forged'
        packet['hand'].clear();packet['players'][0]['mana']['R']=100
        self.assertEqual(before,self.kernel.snapshot())
        self.assertEqual('Public source',project_actor(self.kernel,'A')['zones']['battlefield']['A'][0]['name'])

    def test_unknown_actor_rejected_without_mutation(self):
        self.game();before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):project_actor(self.kernel,'C')
        self.assertEqual(before,self.kernel.snapshot())

    def test_search_is_visible_only_to_searcher_and_expires(self):
        self.game()
        request=self.kernel.execute_for_scenario(self.source,'A',(SearchLibrary(Selector(Zone.LIBRARY,relation='owned'),Zone.HAND),))
        own=project_actor(self.kernel,'A');other=project_actor(self.kernel,'B')
        self.assertEqual('choice',own['decision']['kind'])
        self.assertIn('library_search',own);self.assertNotIn('library_search',other)
        self.assertEqual({'kind':'waiting','actor':'A'},other['decision'])
        self.assertNotIn('hidden-library-secret1',json.dumps(other))
        self.kernel.answer(request.request_id,'A',[0])
        self.assertNotIn('library_search',project_actor(self.kernel,'A'))

    def test_search_menu_has_no_library_order_or_unseen_tail(self):
        self.game();self.state.add_card('second','secret2','A',Zone.LIBRARY)
        other=RulesState.restore(self.state.snapshot())
        order=tuple(o.ref for o in self.state.zone('A',Zone.LIBRARY))
        self.state.reorder('A',Zone.LIBRARY,order)
        other.reorder('A',Zone.LIBRARY,tuple(reversed(order)))
        second_kernel=RulesKernel(other,self.programs);second_kernel.open_window_for_scenario('A')
        for kernel in (self.kernel,second_kernel):
            kernel.execute_for_scenario(self.source,'A',(SearchLibrary(Selector(Zone.LIBRARY,relation='owned'),Zone.HAND),))
        self.assertEqual(project_actor(self.kernel,'A'),project_actor(second_kernel,'A'))

    def test_pending_mana_choice_never_exposes_internal_frame(self):
        state=RulesState(('A','B'));program=CardProgram('rock','Rock',('Artifact',),activated=(
            ActivatedProgram('mana',CostSpec(tap_source=True),(ChooseMana((('G',),('U',))),),mana_ability=True),))
        ref=state.add_card('rock','rock','A',Zone.BATTLEFIELD);kernel=RulesKernel(state,(program,))
        kernel.open_window_for_scenario('A');kernel.commit_action(kernel.quote_activation('mana','A',ref,'mana'),Payment())
        own=project_actor(kernel,'A');other=project_actor(kernel,'B')
        self.assertEqual([],own['stack']);self.assertEqual('mana_choice',own['decision']['choice']['kind'])
        self.assertEqual({'kind':'waiting','actor':'A'},other['decision'])
        self.assertNotIn('tasks',json.dumps(own));self.assertNotIn('effects',json.dumps(own))

    def test_projected_checkpoint_continuation_matches(self):
        self.game();self.kernel.execute_for_scenario(self.source,'A',(SearchLibrary(Selector(Zone.LIBRARY,relation='owned'),Zone.HAND),))
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        for actor in self.state.players:self.assertEqual(project_actor(self.kernel,actor),project_actor(restored,actor))

    def test_turn_draw_frame_does_not_reveal_future_card_identity(self):
        from edh_gauntlet.rules_program import Draw
        self.game();top=self.state.zone('A',Zone.LIBRARY)[-1]
        self.kernel.resolving=self.kernel._frame(top,'A',(Draw(),))
        self.kernel.resolving['turn_based']=True
        packet=project_actor(self.kernel,'B')
        self.assertEqual({'kind':'turn_action','controller':'A','phase':'precombat_main'},packet['resolving'])
        self.assertNotIn('hidden-library-secret1',json.dumps(packet))

    def test_pending_choice_keeps_public_resolution_source_visible(self):
        self.game();self.kernel.execute_for_scenario(self.source,'A',(SearchLibrary(Selector(Zone.LIBRARY,relation='owned'),Zone.HAND),))
        for actor in self.state.players:
            packet=project_actor(self.kernel,actor)
            self.assertEqual('Public source',packet['resolving']['name'])
            self.assertNotIn('tasks',packet['resolving']);self.assertNotIn('bindings',packet['resolving'])

    def test_private_target_reference_is_not_disclosed_by_public_stack(self):
        self.game();hidden=self.state.zone('B',Zone.HAND)[0]
        frame=self.kernel._frame(self.state.get(self.source),'B',(),targets=(hidden.ref,))
        self.kernel.stack.append(frame)
        own=project_actor(self.kernel,'B');other=project_actor(self.kernel,'A')
        self.assertEqual([hidden.ref.to_json()],own['stack'][0]['targets'])
        self.assertEqual([{'hidden':True,'zone':'hand','owner':'B'}],other['stack'][0]['targets'])
        self.assertNotIn(hidden.ref.card_id,json.dumps(other))
