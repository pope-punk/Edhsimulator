"""Omo composes shared target clauses, counter placement and subtype sets."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_subtypes import LAND_TYPES,CREATURE_TYPES
from edh_gauntlet.rules_actor import _card

class OmoTests(unittest.TestCase):
    def game(self,zone=Zone.HAND):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(
            CardProgram('animated','Animated land',('Land','Creature'),subtypes=('Forest','Elf'),power=2,toughness=3),)
        self.state=RulesState(('A','B'));self.omo=self.state.add_card('omo','catalog:omo-queen-of-vesuva','A',zone)
        self.land=self.state.add_card('land','catalog:forest','B',Zone.BATTLEFIELD)
        self.creature=self.state.add_card('creature','catalog:elvish-mystic','B',Zone.BATTLEFIELD)
        self.animated=self.state.add_card('animated','animated','A',Zone.BATTLEFIELD)
        for actor in ('A','B'):self.state.add_card('draw'+actor,'catalog:forest',actor,Zone.LIBRARY)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)
    def choose(self,pairs,kernel=None):
        kernel=kernel or self.kernel;q=kernel.pending_choice
        indexes=[next(i for i,o in enumerate(q.options) if o.group==group and o.ref==ref) for group,ref in pairs]
        kernel.answer(q.request_id,q.actor,indexes);self.drain(kernel)
    def cast(self,color='G'):
        self.state.add_mana('A',('C','C',color));quote=self.kernel.quote_cast('cast:'+str(self.omo.incarnation),'A',self.omo)
        self.assertEqual(ManaCost(2,('G/U',)),quote.cost.mana)
        self.kernel.commit_action(quote,Payment((('C',2),(color,1))));self.drain();self.omo=self.state.current('omo')
    def test_paid_hybrid_cast_enters_once_and_targets_any_controllers(self):
        for color in ('G','U'):
            self.game();self.cast(color);q=self.kernel.pending_choice
            self.assertEqual((('land',0,1),('creature',0,1)),q.group_bounds)
            self.assertIn(self.omo,{o.ref for o in q.options if o.group=='creature'})
            self.choose([('land',self.land),('creature',self.creature)])
            self.assertEqual(LAND_TYPES,self.kernel.effective(self.land).subtypes)
            self.assertEqual(CREATURE_TYPES,self.kernel.effective(self.creature).subtypes)
            self.assertFalse(self.state.mana_pool('A'))
            self.assertEqual(1,len([e for e in self.kernel.semantic_events if e['kind']=='trigger_placed']))
    def test_attack_trigger_uses_real_declaration_and_optional_empty_answer(self):
        self.game(Zone.BATTLEFIELD);self.kernel.begin_turn_for_scenario('A')
        for _ in range(8):self.kernel.pass_priority(self.kernel.priority)
        self.kernel.declare_attackers('A',{self.omo:'B'},revision=self.kernel.revision)
        self.assertIsNotNone(self.kernel.pending_choice)
        self.choose([]);self.assertFalse(self.state.get(self.omo).counters)
        placed=[e for e in self.kernel.semantic_events if e['kind']=='trigger_placed'];self.assertEqual(1,len(placed))
    def test_land_creature_can_fill_both_clauses_and_gets_only_land_types(self):
        self.game();self.cast();self.choose([('land',self.animated),('creature',self.animated)])
        self.assertEqual(2,dict(self.state.get(self.animated).counters)['everything'])
        self.assertEqual(LAND_TYPES|{'Elf'},self.kernel.effective(self.animated).subtypes)
        self.assertEqual(5,len([a for a in self.kernel.activated_abilities(self.state.get(self.animated)) if a.ability_id.startswith('intrinsic-land:')]))
    def test_source_departure_preserves_trigger_and_counters_without_type_grants(self):
        self.game();self.cast();q=self.kernel.pending_choice
        self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.group=='creature' and o.ref==self.creature)])
        self.state.move((ZoneMove(self.omo,Zone.HAND),),'scenario_response');self.drain()
        self.assertEqual({'everything':1},dict(self.state.get(self.creature).counters))
        self.assertEqual({'Elf','Druid'},set(self.kernel.effective(self.creature).subtypes))
        self.kernel.open_window_for_scenario('A');self.omo=self.state.current('omo');self.cast('U');self.choose([])
        self.assertEqual(CREATURE_TYPES,self.kernel.effective(self.creature).subtypes)
        self.state.phase(self.omo,True);self.assertEqual({'Elf','Druid'},set(self.kernel.effective(self.creature).subtypes))
        self.state.phase(self.omo,False);self.assertEqual(CREATURE_TYPES,self.kernel.effective(self.creature).subtypes)
    def test_copied_entry_inherits_trigger_and_static_abilities(self):
        self.game();copy=self.state.add_card('copy','catalog:forest','A',Zone.HAND)
        before=self.state.objects(Zone.BATTLEFIELD);views=self.kernel.characteristics()
        events=self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,'A',copied_definition='catalog:omo-queen-of-vesuva'),),'scenario_copy')
        self.kernel._collect(events,before,self.state.objects(Zone.BATTLEFIELD),views);self.kernel.advance()
        self.choose([('land',self.land),('creature',self.creature)])
        self.assertEqual(CREATURE_TYPES,self.kernel.effective(self.creature).subtypes)
        self.assertEqual(LAND_TYPES,self.kernel.effective(self.land).subtypes)
        self.assertEqual(Zone.HAND,self.state.get(self.omo).zone)
    def test_actor_replay_retains_batched_targets_and_compact_subtype_projection(self):
        self.game();self.cast();a=RulesActorAdapter(self.kernel);b=RulesActorAdapter.replay(a.archive(),self.programs)
        q=self.kernel.pending_choice;indexes=[i for i,o in enumerate(q.options) if o.group=='creature' and o.ref==self.creature]
        cmd={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':indexes}
        a.submit('A',cmd);b.submit('A',cmd);self.drain();self.drain(b.kernel)
        self.assertEqual(a.archive(),b.archive())
        self.assertTrue(_card(self.kernel,self.state.get(self.creature),self.kernel.characteristics())['all_creature_types'])
        self.assertEqual([], _card(self.kernel,self.state.get(self.creature),self.kernel.characteristics())['subtypes'])

if __name__=='__main__':unittest.main()
