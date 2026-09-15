"""Target quantities retain exact last known characteristics after movement."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_adapter import RulesActorAdapter


class TargetStatisticTests(unittest.TestCase):
    def game(self,colors=('G','U'),types=('Creature',),keywords=()):
        body=CardProgram('body','Body',types,colors=colors,power=3 if 'Creature' in types else None,toughness=3 if 'Creature' in types else None,keywords=keywords)
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(body,)
        self.state=RulesState(('A','B'));self.spell=self.state.add_card('spell','catalog:breathe-your-last','A',Zone.HAND)
        self.body=self.state.add_card('body','body','B',Zone.BATTLEFIELD)
        if 'Planeswalker' in types:self.state.add_counters(self.body,'loyalty',4)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('B',priority_actor='A')

    def cast(self):
        self.state.add_mana('A',('B','B','C'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.spell,(self.body,)),Payment((('B',2),('C',1))))

    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack:kernel.pass_priority(kernel.priority)

    def test_printed_spell_counts_each_color_and_can_destroy_planeswalker(self):
        for types in (('Creature',),('Planeswalker',)):
            for colors in ((),('B',),('W','U','B','R','G')):
                self.game(colors,types);self.cast();self.drain()
                self.assertEqual(40+len(colors),self.state.life('A'))
                self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('body')).zone)
                self.assertEqual((),self.state.mana_pool('A'))

    def test_indestructible_target_still_supplies_current_colors(self):
        self.game(keywords=('indestructible',));self.cast();self.drain()
        self.assertEqual(42,self.state.life('A'));self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.body).zone)

    def test_temporary_colors_are_retained_as_last_known_after_destruction(self):
        self.game(colors=())
        self.kernel.execute_for_scenario(self.body,'B',(UntilEndOfTurn('source',(SetColors(('W','B','G')),)),))
        self.kernel.open_window_for_scenario('B',priority_actor='A');self.cast()
        adapter=RulesActorAdapter(self.kernel)
        while self.kernel.stack:adapter.submit(self.kernel.priority,{'kind':'pass','revision':self.kernel.revision})
        self.assertEqual(43,self.state.life('A'))
        self.assertEqual(frozenset(),self.kernel.effective(self.state.current('body')).colors)
        replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        for actor in self.state.players:self.assertEqual(adapter.packet(actor),replay.packet(actor))

    def test_all_illegal_target_skips_life_gain_and_does_not_follow_blink(self):
        self.game();self.cast();self.state.move((ZoneMove(self.body,Zone.EXILE),),'fixture-response')
        self.state.move((ZoneMove(self.state.current('body'),Zone.BATTLEFIELD),),'fixture-return');self.drain()
        self.assertEqual(40,self.state.life('A'));self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('body')).zone)

    def test_retained_quantity_survives_checkpoint_between_instructions(self):
        self.game()
        frame=self.kernel._frame(self.state.get(self.spell),'A',(Destroy('target'),May((GainLife(TargetStat('color_count')),))),targets=(self.body,))
        self.kernel.resolving=frame;self.kernel.advance();q=self.kernel.pending_choice
        self.assertEqual('may',q.kind);restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        for kernel in (self.kernel,restored):kernel.answer(q.request_id,'A',[0])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertEqual(42,self.state.life('A'))

    def test_statistic_validation_and_codec(self):
        for statistic in (TargetStat('nonsense'),TargetStat('power','minimum'),TargetStat('color_count')):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),spell_effects=(GainLife(statistic),)))
        good=CardProgram('good','Good',('Instant',),spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',))),spell_effects=(GainLife(TargetStat('power','maximum')),))
        self.assertEqual(good,decode(encode(validate(good))))

    def test_generic_target_statistics_aggregate_distinct_objects(self):
        self.game();other=self.state.add_card('other','body','B',Zone.BATTLEFIELD)
        frame=self.kernel._frame(self.state.get(self.spell),'A',(GainLife(TargetStat('power','maximum')),GainLife(TargetStat('power','sum'))),targets=(self.body,other,self.body))
        self.kernel.resolving=frame;self.kernel.advance();self.assertEqual(49,self.state.life('A'))
        for statistic in (TargetStat('nonsense'),TargetStat('power','minimum')):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',))),spell_effects=(GainLife(statistic),)))
