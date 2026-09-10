"""External entry orientation and filtered movement results compose generically."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed


class SpelunkingTests(unittest.TestCase):
    def game(self,spell_zone=Zone.BATTLEFIELD,extra=()):
        cave=CardProgram('cave','Cave',('Land',),subtypes=('Cave',),entry_modifiers=(EntryModifier('tap'),))
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(cave,*extra)
        self.state=RulesState(('A','B'));self.spell=self.state.add_card('spelunking','catalog:spelunking','A',spell_zone)
        self.state.add_card('draw','catalog:forest','A',Zone.LIBRARY)
        for i,program in enumerate(extra):self.state.add_card('extra'+str(i),program.definition_id,'A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs)

    def order(self,kernel=None,global_first=False):
        kernel=kernel or self.kernel
        while kernel.pending_choice:
            q=kernel.pending_choice;self.assertEqual('replacement_order',q.kind)
            prefix='entry-global:' if global_first else 'entry:'
            kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.key.startswith(prefix))])

    def cast_to_selection(self):
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('G','C','C'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.spell),Payment((('G',1),('C',2))))
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual('selection',self.kernel.pending_choice.kind)
        return self.kernel.pending_choice

    def test_printed_cast_draw_optional_cave_and_four_life(self):
        self.game(Zone.HAND);cave=self.state.add_card('handcave','cave','A',Zone.HAND)
        q=self.cast_to_selection();self.assertEqual(2,len(self.state.zone('A',Zone.HAND)))
        self.kernel.answer(q.request_id,'A',[next(i for i,o in enumerate(q.options) if o.ref==cave)]);self.order()
        self.assertEqual(44,self.state.life('A'));self.assertFalse(self.state.get(self.state.current('handcave')).tapped)
        self.assertEqual((),self.state.mana_pool('A'))

    def test_decline_or_non_cave_does_not_gain_life(self):
        for decline in (False,True):
            self.game(Zone.HAND);q=self.cast_to_selection()
            self.kernel.answer(q.request_id,'A',[] if decline else [0])
            self.assertEqual(40,self.state.life('A'))
            self.assertEqual(Zone.HAND if decline else Zone.BATTLEFIELD,self.state.get(self.state.current('draw')).zone)

    def test_external_orientation_tracks_control_and_excludes_opponent_lands(self):
        self.game()
        for owner in ('B','A'):
            ref=self.state.add_card('land'+owner,'cave',owner,Zone.HAND)
            self.kernel.execute_for_scenario(ref,owner,(Move('source',Zone.BATTLEFIELD),));self.order()
            self.assertEqual(owner=='B',self.state.get(self.state.current('land'+owner)).tapped)
        self.state.change_control_batch((self.spell,),'B')
        ref=self.state.add_card('newB','cave','B',Zone.HAND)
        self.kernel.execute_for_scenario(ref,'B',(Move('source',Zone.BATTLEFIELD),));self.order()
        self.assertFalse(self.state.get(self.state.current('newB')).tapped)

    def test_replacement_order_is_atomic_and_restores_either_outcome(self):
        for global_first in (False,True):
            self.game();ref=self.state.add_card('land','cave','A',Zone.HAND);before=self.state.snapshot()
            self.kernel.execute_for_scenario(ref,'A',(Move('source',Zone.BATTLEFIELD),))
            self.assertEqual(before,self.state.snapshot());restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
            self.order(global_first=global_first);self.order(restored,global_first=global_first)
            self.assertEqual(self.kernel.snapshot(),restored.snapshot())
            self.assertEqual(global_first,self.state.get(self.state.current('land')).tapped)

    def test_result_filter_reads_derived_subtype_and_excludes_redirected_entry(self):
        grant=CardProgram('grant','Grant',('Enchantment',),continuous=(ContinuousProgram('caves',Selector(Zone.BATTLEFIELD,types=('Land',)),(AddSubtypes('Land',('Cave',)),)),))
        self.game(Zone.HAND,extra=(grant,));q=self.cast_to_selection();self.kernel.answer(q.request_id,'A',[0])
        self.assertEqual(44,self.state.life('A'))
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.BATTLEFIELD,Zone.EXILE,types=('Land',)),))
        self.game(Zone.HAND,extra=(redirect,));cave=self.state.add_card('cave','cave','A',Zone.HAND)
        q=self.cast_to_selection();self.kernel.answer(q.request_id,'A',[next(i for i,o in enumerate(q.options) if o.ref==cave)])
        while self.kernel.pending_choice:
            q=self.kernel.pending_choice
            index=next(i for i,o in enumerate(q.options) if not o.key.startswith(('entry:','entry-global:')))
            self.kernel.answer(q.request_id,'A',[index])
        self.assertEqual(40,self.state.life('A'));self.assertEqual(Zone.EXILE,self.state.get(self.state.current('cave')).zone)

    def test_simultaneous_source_entry_does_not_supply_external_replacement(self):
        self.game(Zone.HAND);self.state.add_card('cave','cave','A',Zone.HAND)
        self.kernel.execute_for_scenario(self.spell,'A',(SelectAll(Selector(Zone.HAND,relation='owned'),(Move('selected',Zone.BATTLEFIELD),)),))
        self.assertTrue(self.state.get(self.state.current('cave')).tapped)

    def test_selector_validation(self):
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Enchantment',),entry_modifiers=(EntryModifier('bad',selector=Selector(Zone.HAND)),)))
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),spell_effects=(WithZoneResult(Move('source',Zone.EXILE),Zone.EXILE,(),selector=Selector(Zone.BATTLEFIELD)),)))

    def test_phased_source_stops_replacing_entries_and_resumes_with_same_identity(self):
        self.game();original=self.spell
        for phased in (True,False):
            self.state.phase(self.spell,phased)
            ref=self.state.add_card('land'+str(phased),'cave','A',Zone.HAND)
            self.kernel.enter(ref);self.order()
            self.assertEqual(phased,self.state.get(self.state.current(ref.card_id)).tapped)
            self.assertEqual(original,self.state.current('spelunking'))

    def test_copied_entry_trigger_and_static_effect_use_copy_controller_after_restore(self):
        from edh_gauntlet.rules_state import ZoneMove
        from edh_gauntlet.rules_adapter import RulesActorAdapter
        self.game(Zone.GRAVEYARD)
        copy=self.state.add_card('copy','catalog:forest','B',Zone.HAND)
        cave=self.state.add_card('bcave','cave','B',Zone.HAND)
        self.state.add_card('bdraw','catalog:forest','B',Zone.LIBRARY)
        before=self.state.objects(Zone.BATTLEFIELD);views=self.kernel.characteristics()
        events=self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,'B',copied_definition='catalog:spelunking'),),'fixture-copy')
        self.kernel._collect(events,before,self.state.objects(Zone.BATTLEFIELD),views);self.kernel.advance()
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)
        q=self.kernel.pending_choice;self.assertEqual('B',q.actor)
        self.assertEqual('selection',q.kind)
        adapter=RulesActorAdapter(self.kernel)
        adapter.submit('B',{'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,
            'indexes':[next(i for i,o in enumerate(q.options) if o.ref==cave)]})
        replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.order();self.order(replay.kernel)
        self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot())
        self.assertEqual(44,self.state.life('B'));self.assertEqual(40,self.state.life('A'))
        self.assertFalse(self.state.get(self.state.current('bcave')).tapped)
        self.assertEqual(Zone.HAND,self.state.get(self.state.current('bdraw')).zone)

    def test_two_external_sources_each_apply_once_in_competing_order(self):
        self.game();self.state.add_card('second','catalog:spelunking','A',Zone.BATTLEFIELD)
        ref=self.state.add_card('land','cave','A',Zone.HAND);self.kernel.enter(ref)
        keys=[]
        while self.kernel.pending_choice:
            q=self.kernel.pending_choice
            candidates=[(i,o) for i,o in enumerate(q.options) if o.key.startswith('entry-global:')]
            self.assertTrue(candidates)
            i,option=candidates[0];keys.append(option.key)
            self.kernel.answer(q.request_id,q.actor,[i])
        self.assertEqual(2,len(set(keys)))
        self.assertTrue(self.state.get(self.state.current('land')).tapped)
