"""Optional entry-copy orientation composes with inherited land programs."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed


class VesuvaTests(unittest.TestCase):
    def game(self,model='forest',extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(CardProgram('catalog:fixture','Fixture Land',('Land',),abilities=(AbilityProgram('entry',EventPattern('zone_changed',subject='self',to_zone=Zone.BATTLEFIELD),(GainLife(2),)),)),)
        self.programs+=extra
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('vesuva','catalog:vesuva','A',Zone.HAND)
        self.model=self.state.add_card('model','catalog:'+model,'B',Zone.BATTLEFIELD)
        for i,program in enumerate(extra):self.state.add_card('extra'+str(i),program.definition_id,'A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs)

    def enter(self):return self.kernel.execute_for_scenario(self.ref,'A',(Move('source',Zone.BATTLEFIELD),))

    def test_accepting_copy_enters_tapped_and_declining_does_not(self):
        for accept in (False,True):
            self.game();q=self.enter();restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
            for k in (self.kernel,restored):k.answer(q.request_id,'A',[0] if accept else [])
            self.assertEqual(self.kernel.snapshot(),restored.snapshot())
            obj=self.state.get(self.state.current('vesuva'));self.assertEqual(accept,obj.tapped)
            self.assertEqual('catalog:forest' if accept else None,obj.copied_definition)
            self.assertEqual({'Forest'} if accept else set(),set(self.kernel.effective(obj.ref).subtypes))
            self.assertEqual(1,len(self.state.events));self.assertEqual(accept,self.state.events[0].after.tapped)

    def test_copy_does_not_inherit_animation_colors_stats_or_counters(self):
        self.game('lumbering-falls');self.state.add_counters(self.model,'+1/+1',2)
        self.kernel.execute_for_scenario(self.model,'B',(UntilEndOfTurn('source',(ChangeTypes(add=('Creature',)),SetColors(('G','U')),SetPT(3,3))),))
        q=self.enter();self.kernel.answer(q.request_id,'A',[0])
        view=self.kernel.effective(self.state.current('vesuva'))
        self.assertEqual({'Land'},set(view.types));self.assertEqual(frozenset(),view.colors)
        self.assertIsNone(view.power);self.assertEqual((),self.state.get(self.state.current('vesuva')).counters)
        self.assertTrue(self.state.get(self.state.current('vesuva')).tapped)

    def test_copied_entry_trigger_belongs_to_entering_copy_controller(self):
        self.game('fixture');q=self.enter();self.kernel.answer(q.request_id,'A',[0])
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual(42,self.state.life('A'));self.assertEqual(40,self.state.life('B'))
        self.assertTrue(self.state.get(self.state.current('vesuva')).tapped)

    def test_copy_orientation_requires_valid_copy_declaration(self):
        program=CardProgram('bad','Bad',('Land',),entry_copy_tapped=True)
        with self.assertRaises(RulesViolation):validate(program)
        with self.assertRaises(RulesViolation):validate(replace(program,entry_copy=Selector(Zone.BATTLEFIELD),entry_copy_tapped=1))
        good=replace(program,entry_copy=Selector(Zone.BATTLEFIELD,types=('Land',)))
        self.assertEqual(good,decode(encode(validate(good))))

    def test_tapped_copy_proposal_is_seen_by_later_entry_replacements(self):
        observer=CardProgram('observer','Observer',('Enchantment',),entry_counters=(EntryCounters('tapped','charge',1,Selector(Zone.BATTLEFIELD,types=('Land',),tapped=True)),))
        for accept in (False,True):
            self.game(extra=(observer,));q=self.enter()
            restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
            for kernel in (self.kernel,restored):
                kernel.answer(q.request_id,'A',[0] if accept else [])
                obj=kernel.state.get(kernel.state.current('vesuva'))
                self.assertEqual((('charge',1),) if accept else (),obj.counters)
            self.assertEqual(self.kernel.snapshot(),restored.snapshot())

    def test_copy_of_an_existing_copy_uses_its_copiable_definition(self):
        from edh_gauntlet.rules_state import ZoneMove
        self.game()
        self.state.move((ZoneMove(self.model,Zone.HAND),),'fixture-remove')
        other=self.state.add_card('other','catalog:vesuva','B',Zone.HAND)
        self.state.move((ZoneMove(other,Zone.BATTLEFIELD,copied_definition='catalog:forest'),),'fixture-copy')
        q=self.enter();self.kernel.answer(q.request_id,'A',[0])
        obj=self.state.get(self.state.current('vesuva'))
        self.assertEqual('catalog:forest',obj.copied_definition);self.assertTrue(obj.tapped)
        self.assertIsNone(self.kernel.pending_choice)

    def test_later_untap_replacement_rechecks_tapped_counter_eligibility(self):
        observer=CardProgram('observer','Observer',('Enchantment',),entry_counters=(EntryCounters('tapped','charge',1,Selector(Zone.BATTLEFIELD,types=('Land',),tapped=True)),))
        untapper=CardProgram('catalog:untapper','Untapper',('Land',),entry_modifiers=(EntryModifier('untap',tapped=False),))
        for counter_first in (False,True):
            self.game('untapper',extra=(observer,untapper));q=self.enter()
            self.kernel.answer(q.request_id,'A',[next(i for i,o in enumerate(q.options) if o.ref==self.model)])
            q=self.kernel.pending_choice;self.assertEqual('replacement_order',q.kind)
            prefix='entry-counter:' if counter_first else 'entry:'
            self.kernel.answer(q.request_id,'A',[next(i for i,o in enumerate(q.options) if o.key.startswith(prefix))])
            obj=self.state.get(self.state.current('vesuva'))
            self.assertFalse(obj.tapped)
            self.assertEqual((('charge',1),) if counter_first else (),obj.counters)
            self.assertIsNone(self.kernel.pending_choice)
