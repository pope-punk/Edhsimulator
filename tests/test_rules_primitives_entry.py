"""Entry replacements happen before atomic moves and inherit copied programs."""
import unittest
from edh_gauntlet.rules_program import (CardProgram,EntryModifier,CountCondition,Selector,Move,
    ZoneReplacement,SelectAll,AbilityProgram,EventPattern,GainLife,validate)
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel


class EntryTests(unittest.TestCase):
    def game(self,modifiers=(EntryModifier('tapped'),),copy=False):
        self.programs=[CardProgram('land','Land',('Land',),entry_modifiers=modifiers),
            CardProgram('basic','Basic',('Land',),supertypes=('Basic',)),
            CardProgram('copy','Copy',('Creature',),power=1,toughness=1,
                        entry_copy=Selector(Zone.GRAVEYARD))]
        self.state=RulesState(('A','B'))
        self.ref=self.state.add_card('enter','copy' if copy else 'land','A',Zone.HAND)
        self.kernel=RulesKernel(self.state,self.programs)

    def enter(self):return self.kernel.execute_for_scenario(self.ref,'A',(Move('source',Zone.BATTLEFIELD),))

    def test_entry_event_already_tapped_with_no_extra_tap_event(self):
        self.game();self.enter()
        event=self.state.events[0]
        self.assertTrue(event.after.tapped)
        self.assertEqual(1,len(self.state.events))
        self.assertTrue(self.state.get(self.state.current('enter')).tapped)
        self.assertIsNone(self.kernel.pending_choice)

    def test_conditional_entry_counts_existing_lands_and_current_controller(self):
        condition=CountCondition(Selector(Zone.BATTLEFIELD,types=('Land',),relation='controlled',exclude_source=True),2)
        for mine,opponents,expected in ((0,2,True),(1,1,True),(2,0,False)):
            self.game((EntryModifier('slow',condition=condition,unless=True),))
            for i in range(mine):self.state.add_card('mine'+str(i),'basic','A',Zone.BATTLEFIELD)
            for i in range(opponents):self.state.add_card('other'+str(i),'basic','B',Zone.BATTLEFIELD)
            self.enter();self.assertEqual(expected,self.state.get(self.state.current('enter')).tapped)

    def test_simultaneous_lands_do_not_count_each_other(self):
        condition=CountCondition(Selector(Zone.BATTLEFIELD,types=('Land',),relation='controlled'),2)
        self.game((EntryModifier('slow',condition=condition,unless=True),))
        self.state.add_card('one','basic','A',Zone.BATTLEFIELD)
        other=self.state.add_card('other','land','A',Zone.HAND)
        self.kernel.execute_for_scenario(self.ref,'A',(SelectAll(Selector(Zone.HAND,relation='owned'),(Move('selected',Zone.BATTLEFIELD),)),))
        events=self.state.events
        self.assertEqual(2,len(events));self.assertEqual(events[0].batch,events[1].batch)
        self.assertTrue(all(e.after.tapped for e in events))

    def test_copy_inherits_entry_modifier_after_copy_choice_and_restore(self):
        self.game(copy=True);self.state.add_card('model','land','A',Zone.GRAVEYARD)
        request=self.enter();before=self.state.snapshot()
        self.assertEqual('entry_copy',request.kind)
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.kernel.answer(request.request_id,'A',[0]);restored.answer(request.request_id,'A',[0])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertTrue(self.state.get(self.state.current('enter')).tapped)
        self.assertEqual('land',self.state.events[0].after.copied_definition)
        self.assertNotEqual(before,self.state.snapshot())

    def test_redirected_entry_does_not_keep_battlefield_attributes(self):
        self.game();redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(
            ZoneReplacement('exile',Zone.BATTLEFIELD,Zone.EXILE),))
        self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,(*self.programs,redirect))
        request=self.enter();self.assertEqual('replacement_order',request.kind)
        index=next(i for i,o in enumerate(request.options) if o.key.startswith('entry:'))
        self.kernel.answer(request.request_id,'A',[index])
        obj=self.state.get(self.state.current('enter'))
        self.assertEqual(Zone.EXILE,obj.zone);self.assertFalse(obj.tapped)

    def test_opposing_entry_replacements_order_once_before_commit(self):
        self.game((EntryModifier('tap',True),EntryModifier('untap',False)))
        request=self.enter();before=self.state.snapshot()
        self.assertEqual('replacement_order',request.kind)
        with self.assertRaises(RulesViolation):self.kernel.answer(request.request_id,'B',[0])
        self.assertEqual(before,self.state.snapshot())
        self.kernel.answer(request.request_id,'A',[0])
        self.assertFalse(self.state.get(self.state.current('enter')).tapped)
        traces=[e for e in self.kernel.semantic_events if e['kind']=='replacement_considered']
        self.assertEqual(2,len(traces))

    def test_low_level_entry_attributes_validate_atomically(self):
        self.game();before=self.state.snapshot()
        for move in (ZoneMove(self.ref,Zone.GRAVEYARD,tapped=True),ZoneMove(self.ref,Zone.BATTLEFIELD,tapped=1)):
            with self.assertRaises(RulesViolation):self.state.move((move,),'invalid')
            self.assertEqual(before,self.state.snapshot())

    def test_compiler_rejects_malformed_entry_modifiers(self):
        for modifiers in ([EntryModifier('tap')],(EntryModifier('tap',1),),(EntryModifier('tap',unless=True),),
                          (EntryModifier('tap'),EntryModifier('tap'))):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Land',),entry_modifiers=modifiers))


class AuthoredEntryTests(unittest.TestCase):
    def game(self,key,lands=(),main=False):
        from edh_gauntlet.rules_bundle import load_reviewed
        programs=tuple(r['program'] for r in load_reviewed().values())
        self.state=RulesState(('A','B'))
        self.ref=self.state.add_card('entry','catalog:'+key,'A',Zone.HAND)
        for i,land in enumerate(lands):self.state.add_card('land'+str(i),'catalog:'+land,'A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,programs)
        if main:
            self.state.add_card('draw','catalog:forest','A',Zone.LIBRARY)
            self.kernel.begin_turn_for_scenario('A')
            for _ in range(4):self.kernel.pass_priority(self.kernel.priority)
        else:self.kernel.open_window_for_scenario('A')

    def test_diamonds_cast_tapped_and_cannot_produce_mana_until_untapped(self):
        from edh_gauntlet.rules_casting import Payment
        for key in ('charcoal-diamond','marble-diamond'):
            self.game(key);self.state.add_mana('A',('C','C'))
            self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.ref),Payment((('C',2),)))
            self.kernel.pass_priority('A');self.kernel.pass_priority('B')
            self.kernel.open_window_for_scenario('A')
            ref=self.state.current('entry');self.assertTrue(self.state.get(ref).tapped)
            with self.assertRaises(RulesViolation):self.kernel.quote_activation('mana','A',ref,'mana')

    def test_slow_land_special_actions_use_existing_lands(self):
        for key in ('deserted-beach','dreamroot-cascade','rockfall-vale','shattered-sanctum','shipwreck-marsh'):
            for lands,tapped in ((('forest',),True),(('forest','island'),False)):
                self.game(key,lands,main=True)
                self.kernel.play_land('play','A',self.ref,revision=self.kernel.revision)
                self.assertEqual(tapped,self.state.get(self.state.current('entry')).tapped)
                self.assertEqual(1,self.kernel.turn_schedule['land_plays'])
                self.assertEqual([],self.kernel.stack)

    def test_cinder_glade_counts_basic_supertype_not_basic_land_types(self):
        for lands,tapped in ((('forest','island'),False),(('forest','cinder-glade'),True)):
            self.game('cinder-glade',lands)
            self.kernel.execute_for_scenario(self.ref,'A',(Move('source',Zone.BATTLEFIELD),))
            ref=self.state.current('entry');self.assertEqual(tapped,self.state.get(ref).tapped)
            self.assertEqual({'intrinsic-land:Forest','intrinsic-land:Mountain'},
                             {a.ability_id for a in self.kernel.activated_abilities(self.state.get(ref))})

    def test_tapped_lifegain_land_still_gets_normal_entry_trigger(self):
        self.game('scoured-barrens',main=True)
        self.kernel.play_land('play','A',self.ref,revision=self.kernel.revision)
        self.assertTrue(self.state.get(self.state.current('entry')).tapped)
        self.assertEqual(40,self.state.life('A'))
        self.assertEqual('entry-life',self.kernel.stack[-1]['ability_id'])
        self.kernel.pass_priority('A');self.kernel.pass_priority('B')
        self.assertEqual(41,self.state.life('A'))
