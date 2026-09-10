"""Numeric reads retain exact derived characteristics across departures."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_adapter import RulesActorAdapter


class CharacteristicValuesTests(unittest.TestCase):
    def game(self):
        self.buff=CardProgram('buff','Buff',('Enchantment',),continuous=(ContinuousProgram('boost',Selector(Zone.BATTLEFIELD,types=('Creature',)),(ModifyPT(3,3),)),))
        self.driver=CardProgram('driver','Driver',('Artifact',))
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(self.buff,self.driver)
        self.state=RulesState(('A','B'));self.kernel=RulesKernel(self.state,self.programs)
        self.ref=self.state.add_card('driver','driver','A',Zone.BATTLEFIELD)

    def drain(self):
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)

    def test_departure_retains_simultaneous_modifier_and_counters(self):
        self.game();hierophant=self.state.add_card('hierophant','catalog:elenda-s-hierophant','A',Zone.BATTLEFIELD)
        self.state.add_card('buff','buff','A',Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(self.ref,'A',(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',)),(AddCounters('selected','+1/+1',2),)),))
        self.assertEqual(6,self.kernel.effective(hierophant).power)
        self.kernel.execute_for_scenario(self.ref,'A',(SelectAll(Selector(Zone.BATTLEFIELD,any_types=('Creature','Enchantment')),(Destroy('selected'),)),))
        self.drain();tokens=[o for o in self.state.objects(Zone.BATTLEFIELD) if o.token]
        self.assertEqual(6,len(tokens));self.assertEqual(6,self.kernel.last_known[hierophant][1].power)
        self.assertTrue(all('lifelink' in self.kernel.effective(o.ref).keywords for o in tokens))

    def test_live_source_reads_current_modifiers_not_announcement_snapshot(self):
        self.game();elf=self.state.add_card('elf','catalog:llanowar-elves','A',Zone.BATTLEFIELD)
        frame=self.kernel._frame(self.state.get(elf),'A',())
        self.state.add_card('buff','buff','B',Zone.BATTLEFIELD)
        self.assertEqual(4,self.kernel._quantity(SourceStat(),frame))
        self.assertEqual(1,self.kernel._quantity(SourceStat('mana_value'),frame))

    def test_returned_incarnation_does_not_replace_old_information(self):
        self.game();elf=self.state.add_card('elf','catalog:llanowar-elves','A',Zone.BATTLEFIELD)
        self.state.add_card('buff','buff','A',Zone.BATTLEFIELD)
        frame=self.kernel._frame(self.state.get(elf),'A',())
        self.kernel.execute_for_scenario(elf,'A',(AddCounters('source','+1/+1',2),WithMoved('source',Zone.EXILE,(Move('moved',Zone.BATTLEFIELD),))))
        self.assertEqual(6,self.kernel._quantity(SourceStat(),frame))
        self.assertEqual(4,self.kernel.effective(self.state.current('elf')).power)
        replay=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.assertEqual(6,replay._quantity(SourceStat(),frame));self.assertEqual(self.kernel.snapshot(),replay.snapshot())

    def test_departed_damage_uses_same_derived_view(self):
        self.game();elf=self.state.add_card('elf','catalog:llanowar-elves','A',Zone.BATTLEFIELD)
        self.state.add_card('buff','buff','A',Zone.BATTLEFIELD);source=self.state.get(elf)
        self.kernel.execute_for_scenario(elf,'A',(Move('source',Zone.GRAVEYARD),))
        self.assertEqual(4,self.kernel._damage_source(source)[1].power)

    def test_battlefield_aggregates_use_current_filtered_characteristics(self):
        self.game();self.state.add_card('own','catalog:llanowar-elves','A',Zone.BATTLEFIELD)
        self.state.add_card('other','catalog:terastodon','B',Zone.BATTLEFIELD)
        frame=self.kernel._frame(self.state.get(self.ref),'A',())
        own=Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled')
        self.assertEqual(1,self.kernel._quantity(BattlefieldStat(own),frame))
        self.assertEqual(10,self.kernel._quantity(BattlefieldStat(Selector(Zone.BATTLEFIELD,types=('Creature',)),operation='sum'),frame))
        self.assertEqual(0,self.kernel._quantity(BattlefieldStat(Selector(Zone.BATTLEFIELD,subtypes=('Dragon',))),frame))
        self.assertEqual(0,self.kernel._quantity(SourceStat(),frame))

    def test_copied_hierophant_death_uses_copy_power_and_trigger(self):
        self.game();grave=self.state.add_card('grave','catalog:elenda-s-hierophant','B',Zone.GRAVEYARD)
        double=self.state.add_card('double','catalog:body-double','A',Zone.HAND)
        self.kernel.enter(double,'A');r=self.kernel.pending_choice
        index=next(i for i,o in enumerate(r.options) if o.ref==grave)
        self.kernel.answer(r.request_id,r.actor,(index,))
        self.state.add_card('buff','buff','A',Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(self.state.current('double'),'A',(Destroy('source'),));self.drain()
        self.assertEqual(4,sum(o.token for o in self.state.objects(Zone.BATTLEFIELD)))

    def test_life_gain_counter_and_private_archive_continuation(self):
        self.game();hierophant=self.state.add_card('hierophant','catalog:elenda-s-hierophant','A',Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(self.ref,'A',(GainLife(2),));self.drain()
        self.assertEqual(2,self.kernel.effective(hierophant).power)
        self.kernel.execute_for_scenario(hierophant,'A',(Destroy('source'),))
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.assertNotIn('last_known',adapter.packet('B'))
        while self.kernel.stack:
            actor=self.kernel.priority;command={'kind':'pass','revision':self.kernel.revision}
            adapter.submit(actor,command);replay.submit(actor,command)
        self.assertEqual(adapter.archive(),replay.archive());self.assertEqual(2,sum(o.token for o in self.state.objects(Zone.BATTLEFIELD)))

    def test_negative_power_counts_as_zero_without_changing_characteristics(self):
        self.game();elf=self.state.add_card('elf','catalog:llanowar-elves','A',Zone.BATTLEFIELD)
        weak=CardProgram('weak','Weak',('Enchantment',),continuous=(ContinuousProgram('weaken',Selector(Zone.BATTLEFIELD,types=('Creature',)),(ModifyPT(-3,0),)),))
        programs=self.programs+(weak,);self.kernel=RulesKernel(self.state,programs)
        self.state.add_card('weak','weak','B',Zone.BATTLEFIELD)
        frame=self.kernel._frame(self.state.get(elf),'A',())
        self.assertEqual(-2,self.kernel.effective(elf).power)
        self.assertEqual(0,self.kernel._quantity(SourceStat(),frame))
        self.assertEqual(0,self.kernel._quantity(BattlefieldStat(Selector(Zone.BATTLEFIELD,types=('Creature',))),frame))

    def test_invalid_statistics_and_entry_self_reads_reject(self):
        base=CardProgram('test','Test',('Artifact',))
        for expr in (SourceStat('loyalty'),BattlefieldStat(Selector(Zone.GRAVEYARD)),BattlefieldStat(Selector(Zone.BATTLEFIELD),operation='median')):
            with self.assertRaises(RulesViolation):validate(replace(base,spell_effects=(GainLife(expr),)))
        with self.assertRaises(RulesViolation):validate(replace(base,entry_counters=(EntryCounters('bad','+1/+1',ScaledValue(SourceStat(),2)),)))
