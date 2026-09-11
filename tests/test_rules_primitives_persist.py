"""Persist composes death-counter predicates and counters on zone entry."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class PersistTests(unittest.TestCase):
    def game(self,extra=(),zone=Zone.BATTLEFIELD):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+tuple(extra)
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('archmage','catalog:glen-elendra-archmage','A',zone)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)
    def die(self):
        self.kernel.execute_for_scenario(self.ref,'A',(Sacrifice('source'),))
    def persist_count(self):
        return sum(e['kind']=='trigger_created' and e['ability']=='persist' for e in self.kernel.semantic_events)

    def test_printed_cast_and_two_sacrifice_counter_activations(self):
        self.game(zone=Zone.HAND);self.state.add_mana('A',('C','C','C','U'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.ref),Payment((('C',3),('U',1))));self.drain()
        self.ref=self.state.current('archmage');self.assertIn('flying',self.kernel.effective(self.ref).keywords)
        for i in range(2):
            victim=self.state.add_card('spell'+str(i),'catalog:sol-ring','B',Zone.HAND)
            self.kernel.stage_spell_for_scenario(victim,'B');self.kernel.pass_priority('B');self.state.add_mana('A',('U',))
            self.kernel.commit_action(self.kernel.quote_activation('counter'+str(i),'A',self.ref,'counter',(self.state.current(victim.card_id),)),Payment((('U',1),)))
            self.drain();self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current(victim.card_id)).zone)
            self.ref=self.state.current('archmage')
            self.assertEqual(Zone.BATTLEFIELD if i==0 else Zone.GRAVEYARD,self.state.get(self.ref).zone)
            if i==0:self.assertEqual({'-1/-1':1},dict(self.state.get(self.ref).counters))
        self.assertEqual(1,self.persist_count())

    def test_counter_annihilation_reenables_persist_only_if_creature_survives(self):
        self.game();self.state.add_counters(self.ref,'-1/-1',1)
        self.kernel.execute_for_scenario(self.ref,'A',(AddCounters('source','+1/+1',1),))
        self.assertFalse(self.state.get(self.ref).counters);self.die();self.drain();self.assertEqual(1,self.persist_count())
        self.game();self.state.add_counters(self.ref,'+1/+1',1)
        self.kernel.execute_for_scenario(self.ref,'A',(AddCounters('source','-1/-1',3),))
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('archmage')).zone)
        self.assertEqual(0,self.persist_count())

    def test_copied_persist_returns_printed_card_under_owner_control(self):
        self.game();ref=self.state.add_card('copy','catalog:forest','B',Zone.HAND)
        self.state.move((ZoneMove(ref,Zone.BATTLEFIELD,'A',copied_definition='catalog:glen-elendra-archmage'),),'copy')
        self.ref=self.state.current('copy');self.die();self.drain();obj=self.state.get(self.state.current('copy'))
        self.assertEqual(('B',Zone.BATTLEFIELD,'catalog:forest'),(obj.controller,obj.zone,obj.effective_definition))
        self.assertEqual({'-1/-1':1},dict(obj.counters));self.assertEqual(1,self.persist_count())

    def test_old_persist_does_not_follow_a_new_graveyard_incarnation(self):
        self.game();self.die();grave=self.state.current('archmage')
        self.state.move((ZoneMove(grave,Zone.EXILE),),'response');exile=self.state.current('archmage')
        self.state.move((ZoneMove(exile,Zone.GRAVEYARD),),'response');latest=self.state.current('archmage')
        self.drain();self.assertEqual(Zone.GRAVEYARD,self.state.get(latest).zone);self.assertNotEqual(grave,latest)

    def test_graveyard_replacement_prevents_death_trigger(self):
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE),))
        self.game((redirect,));self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD)
        self.die();self.assertEqual(Zone.EXILE,self.state.get(self.state.current('archmage')).zone);self.assertEqual(0,self.persist_count())

    def test_return_replacement_checkpoint_and_duplicate_rejection(self):
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.BATTLEFIELD,Zone.EXILE,from_zone=Zone.GRAVEYARD,optional=True),))
        self.game((redirect,));self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD);self.die();self.drain()
        q=self.kernel.pending_choice;self.assertIsNotNone(q)
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        cmd={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[1]}
        adapter.submit(q.actor,cmd);replay.submit(q.actor,cmd);self.assertEqual(adapter.archive(),replay.archive())
        obj=self.state.get(self.state.current('archmage'));self.assertEqual(Zone.BATTLEFIELD,obj.zone);self.assertEqual({'-1/-1':1},dict(obj.counters))
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):adapter.submit(q.actor,cmd)
        self.assertEqual(before,self.kernel.snapshot())

    def test_entry_counters_use_replacements_and_etb_predicates_before_sba(self):
        observer=CardProgram('observer','Observer',('Enchantment',),abilities=(AbilityProgram('seen-two',EventPattern('zone_changed',to_zone=Zone.BATTLEFIELD,counters=(CounterRange('-1/-1',2),)),(GainLife(3),)),))
        self.game((observer,));self.state.add_card('observer','observer','A',Zone.BATTLEFIELD)
        self.state.add_card('vorinclex','catalog:vorinclex-monstrous-raider','A',Zone.BATTLEFIELD)
        self.die();self.drain()
        arrivals=[e.after for e in self.state.events if e.after.ref.card_id=='archmage' and e.after.zone==Zone.BATTLEFIELD]
        self.assertEqual({'-1/-1':2},dict(arrivals[0].counters));self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('archmage')).zone)
        self.assertEqual(1,self.persist_count());self.assertEqual(43,self.state.life('A'))

    def test_generic_movement_supports_multiple_counter_kinds_and_redirect(self):
        self.game(zone=Zone.HAND)
        self.kernel.execute_for_scenario(self.ref,'A',(Move('source',Zone.BATTLEFIELD,counters=(('+1/+1',2),('charge',3))),))
        obj=self.state.get(self.state.current('archmage'));self.assertEqual({'+1/+1':2,'charge':3},dict(obj.counters));self.assertEqual(4,self.kernel.effective(obj.ref).power)
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.BATTLEFIELD,Zone.EXILE),))
        self.game((redirect,),zone=Zone.HAND);self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(self.ref,'A',(Move('source',Zone.BATTLEFIELD,counters=(('charge',3),)),))
        obj=self.state.get(self.state.current('archmage'));self.assertEqual(Zone.EXILE,obj.zone);self.assertFalse(obj.counters)

    def test_counter_predicate_and_entry_counter_validation(self):
        base=CardProgram('test','Test',('Sorcery',));move=Move('source',Zone.BATTLEFIELD,counters=(('charge',2),))
        self.assertEqual(move,decode(encode(move)))
        for bad in (replace(move,destination=Zone.HAND),replace(move,counters=(('charge',True),)),replace(move,counters=(('charge',0),)),replace(move,counters=(('charge',1),('charge',2))),replace(move,counters=(('',2),))):
            with self.assertRaises(RulesViolation):validate(replace(base,spell_effects=(bad,)))
        event=EventPattern('zone_changed',Zone.BATTLEFIELD,Zone.GRAVEYARD,counters=(CounterRange('-1/-1',0,0),))
        for bad in (replace(event,kind='becomes_tapped',from_zone=None,to_zone=None),replace(event,counters=(CounterRange('charge',2,1),))):
            with self.assertRaises(RulesViolation):validate(CardProgram('test','Test',('Creature',),power=1,toughness=1,abilities=(AbilityProgram('bad',bad,(GainLife(1),)),)))
