"""Casting permissions and cost filters bind the actual pre-stack origin."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_adapter import RulesActorAdapter

class CastOriginTests(unittest.TestCase):
    def game(self,origins=(Zone.HAND,Zone.COMMAND,Zone.GRAVEYARD,Zone.EXILE)):
        self.spell=CardProgram('spell','Origin fixture',('Instant',),cast=CastSpec(CostSpec(ManaCost(2,('U',))),'instant',origin_zones=origins),spell_effects=(GainLife(1),))
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(self.spell,)
        self.state=RulesState(('A','B'));self.lamia=self.state.add_card('lamia','catalog:gravebreaker-lamia','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)
    def test_only_graveyard_origin_gets_lamia_discount(self):
        self.game()
        for zone in (Zone.HAND,Zone.GRAVEYARD,Zone.EXILE,Zone.COMMAND):
            ref=self.state.add_card(zone.value,'spell','A',zone,commander=zone==Zone.COMMAND)
            before=self.kernel.snapshot();q=self.kernel.quote_cast(zone.value,'A',ref)
            self.assertEqual(ManaCost(1 if zone==Zone.GRAVEYARD else 2,('U',)),q.cost.mana)
            self.assertEqual(before,self.kernel.snapshot())
    def test_modifier_never_grants_permission_and_command_still_requires_commander(self):
        self.game((Zone.HAND,Zone.COMMAND))
        for zone in (Zone.GRAVEYARD,Zone.EXILE,Zone.COMMAND):
            ref=self.state.add_card(zone.value,'spell','A',zone);before=self.kernel.snapshot()
            with self.assertRaises(RulesViolation):self.kernel.quote_cast(zone.value,'A',ref)
            self.assertEqual(before,self.kernel.snapshot())
        self.game();ref=self.state.add_card('foreign','spell','B',Zone.GRAVEYARD)
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('foreign','A',ref)
    def test_paid_graveyard_cast_replay_and_duplicate_suppression(self):
        self.game();ref=self.state.add_card('s','spell','A',Zone.GRAVEYARD);self.state.add_mana('A',('C','U'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',ref),Payment((('C',1),('U',1))))
        self.assertEqual(Zone.STACK,self.state.get(self.state.current('s')).zone)
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.drain();self.drain(replay.kernel);self.assertEqual(adapter.archive(),replay.archive());self.assertEqual(41,self.state.life('A'))
        self.kernel.open_window_for_scenario('A')
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('cast','A',self.state.current('s'))
    def test_multiple_copies_clamp_generic_without_reducing_colored_cost(self):
        self.game()
        for i in range(3):
            ref=self.state.add_card('copy'+str(i),'spell','A',Zone.HAND)
            self.state.move((ZoneMove(ref,Zone.BATTLEFIELD,'A',copied_definition='catalog:gravebreaker-lamia'),),'scenario_copy')
        spell=self.state.add_card('s','spell','A',Zone.GRAVEYARD)
        self.assertEqual(ManaCost(0,('U',)),self.kernel.quote_cast('cast','A',spell).cost.mana)
        self.state.add_mana('A',('C',));before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(self.kernel.quote_cast('cast','A',spell),Payment((('C',1),)))
        self.assertEqual(before,self.kernel.snapshot())
    def test_source_control_and_phasing_invalidate_old_quotes(self):
        self.game();ref=self.state.add_card('s','spell','A',Zone.GRAVEYARD);q=self.kernel.quote_cast('cast','A',ref)
        self.state.change_control(self.lamia,'B');self.assertEqual(2,self.kernel.quote_cast('fresh','A',ref).cost.mana.generic)
        self.state.add_mana('A',('C','U'))
        with self.assertRaises(RulesViolation):self.kernel.commit_action(q,Payment((('C',1),('U',1))))
        self.state.change_control(self.lamia,'A');self.state.phase(self.lamia,True)
        self.assertEqual(2,self.kernel.quote_cast('phased','A',ref).cost.mana.generic)
    def test_lamia_paid_entry_search_is_mandatory_and_shuffles(self):
        self.game();self.state.move((ZoneMove(self.lamia,Zone.HAND),),'scenario_setup');self.lamia=self.state.current('lamia')
        first=self.state.add_card('first','catalog:forest','A',Zone.LIBRARY);self.state.add_card('other','spell','A',Zone.LIBRARY)
        self.state.add_mana('A',('C',)*4+('B',))
        self.kernel.commit_action(self.kernel.quote_cast('lamia','A',self.lamia),Payment((('C',4),('B',1))));self.drain()
        q=self.kernel.pending_choice;self.assertEqual('library_search',q.kind);self.assertEqual(1,q.minimum)
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.answer(q.request_id,q.actor,[])
        self.assertEqual(before,self.kernel.snapshot())
        self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.ref==first)]);self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('first')).zone)
        self.assertEqual(1,len([e for e in self.kernel.semantic_events if e['kind']=='library_shuffled']))
        self.assertIn('lifelink',self.kernel.effective(self.state.current('lamia')).keywords)
    def test_empty_library_search_and_foreign_inspection_boundary(self):
        self.game();self.kernel.execute_for_scenario(self.lamia,'A',(SearchLibrary(Selector(Zone.LIBRARY,relation='owned'),Zone.GRAVEYARD),))
        self.assertIsNone(self.kernel.pending_choice)
        self.state.add_card('s','spell','A',Zone.LIBRARY)
        self.kernel.execute_for_scenario(self.lamia,'A',(SearchLibrary(Selector(Zone.LIBRARY,relation='owned'),Zone.GRAVEYARD),))
        with self.assertRaises(RulesViolation):self.kernel.inspect_library_search('B')
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        for k in (self.kernel,restored):q=k.pending_choice;k.answer(q.request_id,q.actor,[0])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
    def test_closed_origin_codec_and_validation(self):
        self.game();self.assertEqual(self.spell,decode(encode(self.spell)))
        for zones in ([],(),(Zone.LIBRARY,),(Zone.STACK,),(Zone.HAND,Zone.HAND),('hand',)):
            with self.assertRaises(RulesViolation):validate(replace(self.spell,cast=replace(self.spell.cast,origin_zones=zones)))
        for zones in ([],(Zone.BATTLEFIELD,),(Zone.GRAVEYARD,Zone.GRAVEYARD),('graveyard',)):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Enchantment',),cost_modifiers=(CostModifier('bad',Selector(Zone.STACK),-1,zones),)))

if __name__=='__main__':unittest.main()
