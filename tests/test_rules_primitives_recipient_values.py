"""Per-recipient values bind before a simultaneous temporary-effect batch."""
from dataclasses import replace
import unittest
from unittest.mock import patch
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter


class RecipientValueTests(unittest.TestCase):
    def game(self,extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(CardProgram('driver','Driver',('Artifact',)),)+tuple(extra)
        self.state=RulesState(('A','B'));self.kernel=RulesKernel(self.state,self.programs)
        self.ref=self.state.add_card('driver','driver','A',Zone.BATTLEFIELD)
    def elf(self,name='elf'):return self.state.add_card(name,'catalog:llanowar-elves','A',Zone.BATTLEFIELD)
    def drain(self):
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)
    def double(self):
        self.kernel.execute_for_scenario(self.ref,'A',(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',)),(UntilEndOfTurn('selected',(ModifyPT(RecipientStat('power',True),RecipientStat('toughness',True)),)),)),))

    def test_distinct_power_toughness_and_counters_are_doubled_individually(self):
        self.game();elf=self.elf();other=self.state.add_card('other','catalog:halana-and-alena-partners','A',Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(elf,'A',(AddCounters('source','+1/+1',2),));self.double()
        self.assertEqual((6,6),(self.kernel.effective(elf).power,self.kernel.effective(elf).toughness))
        self.assertEqual((4,6),(self.kernel.effective(other).power,self.kernel.effective(other).toughness))
        self.assertEqual(2,len(self.kernel.temporary_effects))

    def test_equal_results_share_one_record_and_one_timestamp(self):
        self.game()
        for i in range(100):self.elf(str(i))
        before=self.state.sequence;self.double()
        self.assertEqual(before+1,self.state.sequence);self.assertEqual(1,len(self.kernel.temporary_effects));self.assertEqual(100,len(self.kernel.temporary_effects[0]['refs']))

    def test_all_values_are_read_before_any_effect_is_installed(self):
        self.game();self.elf();self.state.add_card('other','catalog:terastodon','A',Zone.BATTLEFIELD)
        original=self.kernel._quantity;reads=[]
        def quantity(value,frame):
            if isinstance(value,RecipientStat):reads.append(len(self.kernel.temporary_effects))
            return original(value,frame)
        with patch.object(self.kernel,'_quantity',side_effect=quantity):self.double()
        self.assertEqual([0,0,0,0],reads)
        self.assertEqual(1,len({r['source']['timestamp'] for r in self.kernel.temporary_effects}))

    def test_negative_doubling_preserves_signed_power(self):
        debuff=CardProgram('debuff','Debuff',('Enchantment',),continuous=(ContinuousProgram('minus',Selector(Zone.BATTLEFIELD,types=('Creature',)),(ModifyPT(-3,0),)),))
        self.game((debuff,));elf=self.elf();self.state.add_card('debuff','debuff','B',Zone.BATTLEFIELD)
        self.double();self.assertEqual(-4,self.kernel.effective(elf).power);self.assertEqual(2,self.kernel.effective(elf).toughness)
        self.kernel._finish_cleanup_actions();self.assertEqual(-2,self.kernel.effective(elf).power)

    def test_default_stat_clamps_and_nested_signed_arithmetic_is_explicit(self):
        self.game();elf=self.elf();self.kernel.execute_for_scenario(elf,'A',(UntilEndOfTurn('source',(ModifyPT(-3,0),)),))
        self.kernel.execute_for_scenario(elf,'A',(UntilEndOfTurn('source',(ModifyPT(RecipientStat(),0),)),))
        self.assertEqual(-2,self.kernel.effective(elf).power)
        self.kernel.execute_for_scenario(elf,'A',(UntilEndOfTurn('source',(ModifyPT(ScaledValue(RecipientStat(allow_negative=True),2),0),)),))
        self.assertEqual(-6,self.kernel.effective(elf).power)

    def test_later_doubling_uses_current_value_then_all_expire(self):
        self.game();elf=self.elf();self.double();self.double();self.assertEqual(4,self.kernel.effective(elf).power)
        self.kernel._finish_cleanup_actions();self.assertEqual(1,self.kernel.effective(elf).power)

    def test_unleash_fury_pays_in_response_and_only_doubles_power(self):
        self.game();elf=self.elf();ref=self.state.add_card('spell','catalog:unleash-fury','A',Zone.HAND)
        self.kernel.open_window_for_scenario('B',priority_actor='A');self.state.add_mana('A',('R','C'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',ref,(elf,)),Payment((('R',1),('C',1))));self.drain()
        self.assertEqual((2,1),(self.kernel.effective(elf).power,self.kernel.effective(elf).toughness))

    def test_unnatural_growth_triggers_on_opponents_combat_and_replays_groups(self):
        self.game();elf=self.elf();other=self.state.add_card('other','catalog:halana-and-alena-partners','A',Zone.BATTLEFIELD)
        self.state.add_card('growth','catalog:unnatural-growth','A',Zone.BATTLEFIELD)
        self.kernel.active='B';self.kernel._collect_step('begin_combat');self.kernel.advance()
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        while self.kernel.stack:
            actor=self.kernel.priority;command={'kind':'pass','revision':self.kernel.revision};adapter.submit(actor,command);replay.submit(actor,command)
        self.assertEqual(adapter.archive(),replay.archive());self.assertEqual(2,self.kernel.effective(elf).power);self.assertEqual(6,self.kernel.effective(other).toughness)

    def test_glimmerpost_counts_both_players_loci_including_itself(self):
        self.game();self.state.add_card('other','catalog:cloudpost','B',Zone.BATTLEFIELD)
        ref=self.state.add_card('post','catalog:glimmerpost','A',Zone.HAND);self.kernel.enter(ref,'A');self.drain();self.assertEqual(42,self.state.life('A'))

    def test_hall_returns_only_own_enchantment_to_library_top(self):
        self.game();land=self.state.add_card('hall','catalog:hall-of-heliod-s-generosity','A',Zone.BATTLEFIELD)
        own=self.state.add_card('own','catalog:unnatural-growth','A',Zone.GRAVEYARD);other=self.state.add_card('other','catalog:unnatural-growth','B',Zone.GRAVEYARD)
        self.state.add_card('bottom','catalog:forest','A',Zone.LIBRARY)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('W','C'))
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',land,'recover',(other,))
        self.kernel.commit_action(self.kernel.quote_activation('recover','A',land,'recover',(own,)),Payment((('W',1),('C',1))));self.drain()
        self.assertEqual('own',self.state.zone('A',Zone.LIBRARY)[-1].ref.card_id)

    def test_healers_hawk_cast_has_both_printed_keywords(self):
        self.game();ref=self.state.add_card('hawk','catalog:healer-s-hawk','A',Zone.HAND);self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('W',))
        self.kernel.commit_action(self.kernel.quote_cast('hawk','A',ref),Payment((('W',1),)));self.drain()
        view=self.kernel.effective(self.state.current('hawk'));self.assertEqual({'flying','lifelink'},view.keywords);self.assertEqual((1,1),(view.power,view.toughness))

    def test_heros_downfall_accepts_planeswalker_and_rejects_land(self):
        walker=CardProgram('walker','Walker',('Planeswalker',))
        self.game((walker,));victim=self.state.add_card('walker','walker','B',Zone.BATTLEFIELD);land=self.state.add_card('land','catalog:forest','B',Zone.BATTLEFIELD)
        ref=self.state.add_card('spell','catalog:hero-s-downfall','A',Zone.HAND);self.kernel.open_window_for_scenario('B',priority_actor='A');self.state.add_mana('A',('B','B','C'))
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',ref,(land,))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',ref,(victim,)),Payment((('B',2),('C',1))));self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('walker')).zone)

    def test_recipient_values_reject_outside_temporary_changes(self):
        base=CardProgram('test','Test',('Artifact',))
        for effect in (GainLife(RecipientStat()),UntilEndOfTurn('source',(ModifyPT(RecipientStat('loyalty'),0),)),UntilEndOfTurn('source',(ModifyPT(RecipientStat(allow_negative=1),0),))):
            with self.assertRaises(RulesViolation):validate(replace(base,spell_effects=(effect,)))
        with self.assertRaises(RulesViolation):validate(replace(base,entry_counters=(EntryCounters('bad','+1/+1',RecipientStat()),)))
