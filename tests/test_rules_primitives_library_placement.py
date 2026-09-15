"""Ordered zone moves place cards top-to-bottom, with one shared choice."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_adapter import RulesActorAdapter


class LibraryPlacementTests(unittest.TestCase):
    def game(self,library=5):
        self.programs=tuple(r['program'] for r in load_reviewed().values())
        self.state=RulesState(('A','B'))
        self.spell=self.state.add_card('spell','catalog:brainstorm','A',Zone.HAND)
        self.old=self.state.add_card('old','catalog:forest','A',Zone.HAND)
        for i in range(library):self.state.add_card('card'+str(i),'catalog:forest','A',Zone.LIBRARY)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('B',priority_actor='A')

    def cast(self):
        self.state.add_mana('A',('U',));self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.spell),Payment((('U',1),)))
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)
        return self.kernel.pending_choice

    def test_brainstorm_draws_three_then_puts_any_two_back_in_order_with_replay(self):
        self.game();q=self.cast();self.assertEqual('selection',q.kind);self.assertTrue(q.ordered)
        self.assertEqual((2,2,4),(q.minimum,q.maximum,len(q.options)))
        indexes=[next(i for i,o in enumerate(q.options) if o.ref.card_id==name) for name in ('old','card4')]
        adapter=RulesActorAdapter(self.kernel);restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        adapter.submit('A',{'kind':'answer','request_id':q.request_id,'indexes':indexes,'revision':self.kernel.revision})
        restored.answer(q.request_id,'A',indexes);self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual(['old','card4'],[o.ref.card_id for o in reversed(self.state.zone('A',Zone.LIBRARY)[-2:])])
        self.assertEqual(2,len(self.state.zone('A',Zone.HAND)));self.assertEqual((),self.state.mana_pool('A'))
        replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        for actor in self.state.players:self.assertEqual(adapter.packet(actor),replay.packet(actor))
        self.assertNotIn('library_observation',adapter.packet('B'))
        self.assertEqual(['old','card4'],[r['ref']['card_id'] for r in adapter.packet('A')['library_observation']['cards']])

    def test_bottom_placement_keeps_selected_top_to_bottom_order(self):
        self.game();q=self.kernel.execute_for_scenario(self.spell,'A',(Select(Selector(Zone.HAND,relation='owned'),2,2,(Move('selected',Zone.LIBRARY,library_position='bottom'),),ordered=True),))
        names=[q.options[i].ref.card_id for i in (1,0)];self.kernel.answer(q.request_id,'A',[1,0])
        self.assertEqual(list(reversed(names)),[o.ref.card_id for o in self.state.zone('A',Zone.LIBRARY)[:2]])
        self.assertEqual('card4',self.state.zone('A',Zone.LIBRARY)[-1].ref.card_id)

    def test_failed_draw_does_not_skip_required_putback_before_player_loss(self):
        self.game(library=0);q=self.cast();self.assertIsNotNone(q)
        self.assertEqual((1,1),(q.minimum,q.maximum));self.assertIsNone(self.kernel.outcome)
        self.kernel.answer(q.request_id,'A',[0]);self.assertNotIn('A',self.state.live_players)
        self.assertTrue(any(e.before.ref.card_id=='old' and e.after.zone==Zone.LIBRARY for e in self.state.events))

    def test_multiowner_moves_preserve_each_library_order(self):
        self.game();other=self.state.add_card('other','catalog:forest','B',Zone.HAND)
        self.kernel.execute_for_scenario(self.spell,'A',(SelectAll(Selector(Zone.HAND),(Move('selected',Zone.LIBRARY,library_position='top'),)),))
        self.assertEqual(['spell','old'],[o.ref.card_id for o in reversed(self.state.zone('A',Zone.LIBRARY)[-2:])])
        self.assertEqual(['other'],[o.ref.card_id for o in self.state.zone('B',Zone.LIBRARY)])

    def test_redirected_cards_are_not_placed_back_into_library(self):
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.LIBRARY,Zone.EXILE,from_zone=Zone.HAND),))
        self.game();self.programs+=(redirect,);self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs)
        self.kernel.execute_for_scenario(self.spell,'A',(SelectAll(Selector(Zone.HAND,relation='owned'),(Move('selected',Zone.LIBRARY,library_position='top'),)),))
        self.assertEqual(5,len(self.state.zone('A',Zone.LIBRARY)));self.assertEqual(2,len(self.state.zone('A',Zone.EXILE)))
        self.assertNotIn('A',self.kernel.library_observations)

    def test_placement_validation(self):
        for move in (Move('source',Zone.HAND,library_position='top'),Move('source',Zone.LIBRARY,library_position='middle'),Move('source',Zone.LIBRARY,library_position=True)):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),spell_effects=(move,)))

    def test_existing_library_cards_can_be_positioned_without_changing_identity(self):
        for position in ('top','bottom'):
            self.game();before={o.ref.card_id:o.ref for o in self.state.zone('A',Zone.LIBRARY)}
            events=len(self.state.events)
            # Synthetic retained references; ordinary Select still forbids
            # library access without an explicit visibility operation.
            frame=self.kernel._frame(self.state.get(self.spell),'A',(Move('selected',Zone.LIBRARY,library_position=position),))
            frame['bindings']['selected']=[before[name].to_json() for name in ('card1','card3')]
            self.kernel.resolving=frame
            restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
            self.kernel.advance();restored.advance();self.assertEqual(self.kernel.snapshot(),restored.snapshot())
            library=self.state.zone('A',Zone.LIBRARY);placed=library[-2:] if position=='top' else library[:2]
            self.assertEqual(['card1','card3'],[o.ref.card_id for o in reversed(placed)])
            self.assertEqual(before,{o.ref.card_id:o.ref for o in library});self.assertEqual(events,len(self.state.events))

    def test_mixed_existing_and_incoming_cards_keep_original_order(self):
        self.game();existing=self.state.current('card1')
        frame=self.kernel._frame(self.state.get(self.spell),'A',(Move('selected',Zone.LIBRARY,library_position='top'),))
        frame['bindings']['selected']=[existing.to_json(),self.old.to_json()]
        self.kernel.resolving=frame
        self.kernel.advance()
        self.assertEqual(['card1','old'],[o.ref.card_id for o in reversed(self.state.zone('A',Zone.LIBRARY)[-2:])])
        self.assertEqual(existing,self.state.current('card1'))
        self.assertEqual(1,len(self.state.events));self.assertEqual('old',self.state.events[0].before.ref.card_id)

    def test_commander_replacement_pauses_before_atomic_ordered_placement(self):
        self.game();commander=self.state.add_card('commander','catalog:forest','A',Zone.HAND,commander=True)
        q=self.kernel.execute_for_scenario(self.spell,'A',(Select(Selector(Zone.HAND,relation='owned'),2,2,(Move('selected',Zone.LIBRARY,library_position='top'),),ordered=True),))
        indexes=[next(i for i,o in enumerate(q.options) if o.ref.card_id==name) for name in ('commander','old')]
        before=self.state.snapshot();self.kernel.answer(q.request_id,'A',indexes)
        q=self.kernel.pending_choice;self.assertEqual('commander_destination',q.kind)
        self.assertEqual(before,self.state.snapshot())
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        index=next(i for i,o in enumerate(q.options) if o.key=='original')
        for kernel in (self.kernel,restored):kernel.answer(q.request_id,'A',[index])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual(['commander','old'],[o.ref.card_id for o in reversed(self.state.zone('A',Zone.LIBRARY)[-2:])])
