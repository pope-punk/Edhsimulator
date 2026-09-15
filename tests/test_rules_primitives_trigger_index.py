"""Indexed trigger discovery must match definition-wide scanning exactly."""
import unittest
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_trigger_benchmark import ScanningRulesKernel,measure
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_bundle import load_reviewed

class TriggerIndexTests(unittest.TestCase):
    def pair(self):
        kinds=('spell_cast','ability_activated','creature_attacks','creature_blocks','becomes_blocked','damage_dealt','damage_received','life_gained','card_drawn','library_searched','library_shuffled','scried','surveilled','counters_added','becomes_tapped')
        abilities=tuple(AbilityProgram(kind,EventPattern(kind),(GainLife(1),)) for kind in kinds)+(
            AbilityProgram('entry',EventPattern('zone_changed',to_zone=Zone.BATTLEFIELD),(GainLife(1),)),
            AbilityProgram('death',EventPattern('zone_changed',Zone.BATTLEFIELD,Zone.GRAVEYARD),(GainLife(1),)),
            AbilityProgram('upkeep',EventPattern('step_began',step='upkeep',controller_only=True),(GainLife(1),)))
        programs=(CardProgram('observer','Observer',('Creature',),power=2,toughness=2,abilities=abilities),CardProgram('blank','Blank',('Creature',),power=2,toughness=2))
        state=RulesState(('A','B'));state.add_card('a','observer','A',Zone.BATTLEFIELD);state.add_card('b','observer','B',Zone.BATTLEFIELD);state.add_card('c','blank','A',Zone.HAND)
        return RulesKernel(state,programs),ScanningRulesKernel(RulesState.restore(state.snapshot()),programs)
    def same(self,pair):self.assertEqual(pair[0].snapshot(),pair[1].snapshot())

    def test_index_matches_all_authored_programs_and_is_immutable(self):
        programs=tuple(row['program'] for row in load_reviewed().values());state=RulesState(('A','B'));kernel=RulesKernel(state,programs)
        for i,program in enumerate(programs):
            ref=state.add_card(str(i),program.definition_id,'A',Zone.BATTLEFIELD);source=state.get(ref)
            for kind in {a.event.kind for a in program.abilities}|{'absent'}:
                self.assertEqual(tuple(a for a in program.abilities if a.event.kind==kind),kernel._trigger_abilities(source,kind))
        with self.assertRaises(TypeError):kernel._trigger_index['bad']={}
        with self.assertRaises(TypeError):kernel._trigger_index[programs[0].definition_id]['bad']=()

    def test_player_and_announcement_discovery_parity(self):
        pair=self.pair()
        for kernel in pair:
            source=kernel.state.get(kernel.state.current('a'))
            for kind in ('life_gained','card_drawn','library_searched','library_shuffled','scried','surveilled'):kernel._player_event(kind,'A',amount=2)
            for kind in ('spell_cast','ability_activated','creature_attacks','creature_blocks','becomes_blocked','damage_dealt','damage_received'):kernel._collect_announcement(kind,source,'A',values={'event_amount':2,'defending_player':'B'})
        self.same(pair)

    def test_entry_death_and_tap_discovery_parity(self):
        pair=self.pair()
        for kernel in pair:
            before=kernel.state.objects(Zone.BATTLEFIELD);views=kernel.characteristics()
            events=kernel.state.move((ZoneMove(kernel.state.current('c'),Zone.BATTLEFIELD),),'entry')
            kernel._collect(events,before,kernel.state.objects(Zone.BATTLEFIELD),views)
            before=kernel.state.objects(Zone.BATTLEFIELD);views=kernel.characteristics();ref=kernel.state.current('a')
            kernel.state.set_tapped_batch((ref,),True);kernel._collect_tapped((ref,),before)
            before=kernel.state.objects(Zone.BATTLEFIELD);views=kernel.characteristics()
            events=kernel.state.move((ZoneMove(ref,Zone.GRAVEYARD),),'death')
            kernel._collect(events,before,kernel.state.objects(Zone.BATTLEFIELD),views)
        self.same(pair)

    def test_step_counter_and_checkpoint_continuation_parity(self):
        pair=self.pair()
        for kernel in pair:
            kernel._collect_step('upkeep');kernel._collect_counters(kernel.state.current('a'),{'+1/+1':2},'B')
        self.same(pair)
        pair=(RulesKernel.restore(pair[0].snapshot(),pair[0].definitions.values()),ScanningRulesKernel.restore(pair[1].snapshot(),pair[1].definitions.values()))
        for kernel in pair:kernel._collect_step('upkeep')
        self.same(pair)

    def test_copy_control_and_phasing_do_not_stale_the_index(self):
        pair=self.pair()
        for kernel in pair:
            ref=kernel.state.current('c');kernel.state.move((ZoneMove(ref,Zone.BATTLEFIELD,'B',copied_definition='observer'),),'copy')
            kernel.state.phase(kernel.state.current('a'),True);kernel.state.change_control(kernel.state.current('b'),'A')
            kernel._collect_step('upkeep');kernel._player_event('card_drawn','B')
        self.same(pair)
        self.assertEqual(3,len(pair[0].pending_triggers))

    def test_synthetic_benchmark_requires_exact_snapshot_parity(self):
        report=measure(repeats=1,events=2)
        self.assertEqual(2,len(report['cases']));self.assertTrue(all(row['semantic_parity'] for row in report['cases']))
        with self.assertRaises(ValueError):measure(repeats=0)
