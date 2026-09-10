"""Library menus hide order and shuffles preserve deterministic accepted prefixes."""
import unittest
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_program import CardProgram,SearchLibrary,Selector,ZoneReplacement
from edh_gauntlet.rules_kernel import RulesKernel


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.state=RulesState(('A','B'),seed=20260909)
        self.programs=[CardProgram('source','Source',('Enchantment',)),CardProgram('land','Land',('Land',),subtypes=('Forest',)),
                       CardProgram('creature','Creature',('Creature',),power=2,toughness=2)]
        self.source=self.state.add_card('source','source','A',Zone.BATTLEFIELD)
        self.refs=[self.state.add_card(str(i),'land' if i%2==0 else 'creature','A',Zone.LIBRARY) for i in range(8)]
        self.kernel=RulesKernel(self.state,self.programs)

    def search(self,quality=True,**kwargs):
        selector=Selector(Zone.LIBRARY,relation='owned',types=('Land',) if quality else ())
        return self.kernel.execute_for_scenario(self.source,'A',(SearchLibrary(selector,Zone.HAND,**kwargs),))

    def test_quality_search_can_find_nothing_but_still_shuffles(self):
        request=self.search();self.assertEqual(0,request.minimum)
        self.kernel.answer(request.request_id,'A',[])
        self.assertEqual(8,len(self.state.zone('A',Zone.LIBRARY)))
        self.assertEqual(1,self.state.snapshot()['shuffle_nonce'])
        self.assertFalse(any(e['kind']=='cards_revealed' for e in self.kernel.semantic_events))

    def test_unqualified_search_must_find_requested_quantity_when_available(self):
        request=self.search(False,count=2);self.assertEqual(2,request.minimum)
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.answer(request.request_id,'A',[])
        self.assertEqual(before,self.kernel.snapshot())
        self.kernel.answer(request.request_id,'A',[0,1])
        self.assertEqual(2,len(self.state.zone('A',Zone.HAND)))

    def test_private_search_menu_does_not_depend_on_library_order(self):
        request=self.search();first=request.options
        other=RulesState.restore(self.state.snapshot())
        other.reorder('A',Zone.LIBRARY,[obj.ref for obj in reversed(other.zone('A',Zone.LIBRARY))])
        kernel=RulesKernel(other,self.programs)
        second=kernel.execute_for_scenario(self.source,'A',(SearchLibrary(Selector(Zone.LIBRARY,relation='owned',types=('Land',)),Zone.HAND),)).options
        self.assertEqual(first,second)
        with self.assertRaises(RulesViolation):self.kernel.answer(request.request_id,'B',[0])

    def test_search_authorizes_full_unordered_inspection_only_for_searcher(self):
        with self.assertRaises(RulesViolation):self.kernel.inspect_library_search('A')
        request=self.search()
        inspected=self.kernel.inspect_library_search('A')
        self.assertEqual(8,len(inspected));self.assertEqual(4,len(request.options))
        self.assertEqual({ref.card_id for ref in self.refs},{o.ref.card_id for o in inspected})
        with self.assertRaises(RulesViolation):self.kernel.inspect_library_search('B')
        self.kernel.answer(request.request_id,'A',[0])
        with self.assertRaises(RulesViolation):self.kernel.inspect_library_search('A')

    def test_reveal_is_explicit_and_shuffles_retire_old_library_references(self):
        request=self.search(reveal=True);chosen=request.options[0].ref
        self.kernel.answer(request.request_id,'A',[0])
        revealed=[e for e in self.kernel.semantic_events if e['kind']=='cards_revealed']
        self.assertEqual([chosen.to_json()],revealed[0]['refs'])
        self.assertEqual(Zone.HAND,self.state.get(self.state.current(chosen.card_id)).zone)
        for ref in self.refs:
            with self.assertRaises(RulesViolation):self.state.get(ref)
        self.assertEqual(1,len(self.state.events)) # Only the selected card changed zones.

    def test_checkpoint_repeats_same_shuffle_and_advances_rng_once(self):
        request=self.search();restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        for kernel in (self.kernel,restored):kernel.answer(request.request_id,'A',[0])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.state.shuffle_library('A');restored.state.shuffle_library('A')
        self.assertEqual(self.state.snapshot(),restored.state.snapshot())
        self.assertEqual(2,self.state.snapshot()['shuffle_nonce'])

    def test_suspended_move_replacement_does_not_repeat_search_or_shuffle(self):
        for key,destination in (('grave',Zone.GRAVEYARD),('exile',Zone.EXILE)):
            self.programs.append(CardProgram(key,key,('Enchantment',),replacements=(ZoneReplacement(key,Zone.HAND,destination),)))
            self.state.add_card(key,key,'B',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs)
        request=self.search();replacement=self.kernel.answer(request.request_id,'A',[0])
        self.assertEqual('replacement_order',replacement.kind)
        self.assertEqual(0,self.state.snapshot()['shuffle_nonce'])
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        for kernel in (self.kernel,restored):kernel.answer(replacement.request_id,replacement.actor,[0])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual(1,self.state.snapshot()['shuffle_nonce'])
        self.assertEqual(1,len([e for e in self.kernel.semantic_events if e['kind']=='library_searched']))

    def test_empty_library_search_is_not_a_failed_draw(self):
        state=RulesState(('A','B'));source=state.add_card('s','source','A',Zone.BATTLEFIELD)
        kernel=RulesKernel(state,self.programs)
        self.assertIsNone(kernel.execute_for_scenario(source,'A',(SearchLibrary(Selector(Zone.LIBRARY,relation='owned'),Zone.HAND),)))
        self.assertEqual(('A','B'),state.live_players);self.assertEqual(1,state.snapshot()['shuffle_nonce'])

    def test_fixed_seed_is_reproducible_and_conserves_physical_cards(self):
        before={o.ref.card_id for o in self.state.zone('A',Zone.LIBRARY)}
        copied=RulesState.restore(self.state.snapshot());self.state.shuffle_library('A');copied.shuffle_library('A')
        self.assertEqual(self.state.snapshot(),copied.snapshot())
        self.assertEqual(before,{o.ref.card_id for o in self.state.zone('A',Zone.LIBRARY)})
        self.assertEqual((),self.state.events)

    def test_authored_tutors_cast_and_resolve_through_shared_search(self):
        from edh_gauntlet.rules_bundle import load_reviewed
        from edh_gauntlet.rules_casting import Payment
        rows=load_reviewed();programs=[row['program'] for row in rows.values()]
        for key in ('diabolic-tutor','sylvan-scrying','nature-s-lore','three-visits'):
            state=RulesState(('A','B'),seed=99)
            state.add_card('forest',rows['forest']['program'].definition_id,'A',Zone.LIBRARY)
            state.add_card('island',rows['island']['program'].definition_id,'A',Zone.LIBRARY)
            spell=state.add_card('tutor',rows[key]['program'].definition_id,'A',Zone.HAND)
            kernel=RulesKernel(state,programs);kernel.open_window_for_scenario('A')
            if key=='diabolic-tutor':symbols=('B','B','C','C');payment=(('B',2),('C',2))
            else:symbols=('G','C');payment=(('G',1),('C',1))
            state.add_mana('A',symbols)
            kernel.commit_action(kernel.quote_cast('cast','A',spell),Payment(payment))
            kernel.pass_priority('A');request=kernel.pass_priority('B')
            self.assertEqual('library_search',request.kind)
            forest_index=next(i for i,option in enumerate(request.options) if option.ref.card_id=='forest')
            kernel.answer(request.request_id,'A',[forest_index])
            destination=Zone.BATTLEFIELD if key in {'nature-s-lore','three-visits'} else Zone.HAND
            self.assertEqual(destination,state.get(state.current('forest')).zone)
            self.assertEqual(1,state.snapshot()['shuffle_nonce'])
            self.assertEqual(key=='sylvan-scrying',any(e['kind']=='cards_revealed' for e in kernel.semantic_events))
            self.assertEqual(Zone.GRAVEYARD,state.get(state.current('tutor')).zone)
