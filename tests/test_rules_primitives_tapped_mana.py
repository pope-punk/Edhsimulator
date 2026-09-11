"""Tapped-for-mana provenance applies shared production replacements exactly once."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class TappedManaTests(unittest.TestCase):
    def game(self,effects=(AddMana(('G',)),),cost=CostSpec(tap_source=True),mana=True,extra=()):
        self.rock=CardProgram('rock','Rock',('Artifact',),activated=(ActivatedProgram('use',cost,effects,mana_ability=mana),))
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(self.rock,)+tuple(extra)
        self.state=RulesState(('A','B'),commander_identities={'A':('G',),'B':('U','G')})
        self.ref=self.state.add_card('rock','rock','B',Zone.BATTLEFIELD)
        self.reflection=self.state.add_card('reflection','catalog:mana-reflection','B',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A',priority_actor='B')
    def activate(self,payment=Payment()):
        return self.kernel.commit_action(self.kernel.quote_activation('use','B',self.ref,'use'),payment)
    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)
    def answer(self,index):
        q=self.kernel.pending_choice;return self.kernel.answer(q.request_id,q.actor,[index])

    def test_fast_path_doubles_each_symbol_and_has_one_production_event(self):
        self.game((AddMana(('C','C','G','U')),));self.activate()
        self.assertEqual({'C':4,'G':2,'U':2},dict(self.state.mana_pool('B')))
        events=[e for e in self.kernel.semantic_events if e['kind']=='mana_added'];self.assertEqual(1,len(events))
        self.assertEqual(8,len(events[0]['symbols']));self.assertFalse(self.kernel.stack);self.assertEqual('B',self.kernel.priority)

    def test_choice_variants_double_the_chosen_bundle_and_recover(self):
        for effect,index,expected in ((ProduceMana(3,('G','U')),1,{'U':6}),(ChooseMana((('G','U'),('C','C'))),0,{'G':2,'U':2}),(ChooseCommanderMana(),1,{'G':2})):
            self.game((effect,));self.activate();adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
            q=self.kernel.pending_choice;cmd={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[index]}
            adapter.submit('B',cmd);replay.submit('B',cmd)
            self.assertEqual(adapter.archive(),replay.archive());self.assertEqual(expected,dict(self.state.mana_pool('B')))
            before=self.kernel.snapshot()
            with self.assertRaises(RulesViolation):adapter.submit('B',cmd)
            self.assertEqual(before,self.kernel.snapshot());self.assertEqual('B',self.kernel.priority)

    def test_no_tap_symbol_and_nonmana_library_ability_are_not_doubled(self):
        self.game(cost=CostSpec());self.activate();self.assertEqual({'G':1},dict(self.state.mana_pool('B')))
        self.game(cost=CostSpec(tap_selector=Selector(Zone.BATTLEFIELD,types=('Artifact',),relation='controlled'),tap_count=1))
        self.activate(Payment(taps=(self.ref,)));self.assertTrue(self.state.get(self.ref).tapped)
        self.assertEqual({'G':1},dict(self.state.mana_pool('B')))
        self.game((AddMana(('G',)),Draw(1)),mana=False)
        self.state.add_card('draw','catalog:forest','B',Zone.LIBRARY);self.activate();self.assertFalse(self.state.mana_pool('B'))
        self.drain();self.assertEqual({'G':1},dict(self.state.mana_pool('B')))

    def test_tap_and_sacrifice_cost_keeps_provenance_after_source_departure(self):
        for effect in (AddMana(('G',)),ProduceMana(1,('G',))):
            self.game((effect,),CostSpec(tap_source=True,zone_costs=(ZoneCost('sac','sacrifice'),)))
            self.activate();self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('rock')).zone)
            self.assertEqual({'G':2},dict(self.state.mana_pool('B')))

    def test_multiple_copied_replacements_control_and_phasing(self):
        self.game();copy=self.state.add_card('copy','catalog:forest','B',Zone.HAND)
        self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,'B',copied_definition='catalog:mana-reflection'),),'scenario_copy')
        enemy=self.state.add_card('enemy','catalog:mana-reflection','A',Zone.BATTLEFIELD)
        phased=self.state.add_card('phased','catalog:mana-reflection','B',Zone.BATTLEFIELD);self.state.phase(phased,True)
        self.activate();self.assertEqual({'G':4},dict(self.state.mana_pool('B')))
        self.game();self.state.change_control(self.reflection,'A');self.activate();self.assertEqual({'G':1},dict(self.state.mana_pool('B')))

    def test_independent_tap_trigger_does_not_inherit_production_marker(self):
        observer=CardProgram('observer','Observer',('Enchantment',),abilities=(AbilityProgram('tap',EventPattern('becomes_tapped'),(AddMana(('U',)),)),))
        self.game(extra=(observer,));self.state.add_card('observer','observer','B',Zone.BATTLEFIELD)
        self.activate();self.assertEqual({'G':2},dict(self.state.mana_pool('B')));self.drain()
        self.assertEqual({'G':2,'U':1},dict(self.state.mana_pool('B')))

    def test_printed_cast_then_native_land_and_granted_mana_abilities(self):
        self.game();self.state.move((ZoneMove(self.reflection,Zone.HAND),),'scenario_hand')
        self.kernel.open_window_for_scenario('B')
        self.state.add_mana('B',('C',)*4+('G','G'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','B',self.state.current('reflection')),Payment((('C',4),('G',2))))
        self.drain();self.kernel.open_window_for_scenario('B')
        forest=self.state.add_card('forest','catalog:forest','B',Zone.BATTLEFIELD)
        ability=self.kernel.activated_abilities(self.state.get(forest))[0]
        self.kernel.commit_action(self.kernel.quote_activation('forest','B',forest,ability.ability_id),Payment())
        self.assertEqual({'G':2},dict(self.state.mana_pool('B')))
        self.state.add_card('lantern','catalog:chromatic-lantern','B',Zone.BATTLEFIELD)
        land=self.state.add_card('land','catalog:forest','B',Zone.BATTLEFIELD)
        granted=next(a for a in self.kernel.activated_abilities(self.state.get(land)) if a.ability_id.startswith('granted:'))
        self.kernel.commit_action(self.kernel.quote_activation('grant','B',land,granted.ability_id),Payment());self.answer(0)
        self.assertEqual(4,sum(dict(self.state.mana_pool('B')).values()))

    def test_sacrificed_replacement_is_gone_before_mana_is_produced(self):
        cost=CostSpec(tap_source=True,zone_costs=(ZoneCost('sac','sacrifice',Selector(Zone.BATTLEFIELD,types=('Enchantment',),relation='controlled')),))
        self.game(cost=cost);self.activate(Payment(zone_costs=(('sac',(self.reflection,)),)))
        self.assertEqual({'G':1},dict(self.state.mana_pool('B')))

    def test_pending_cost_replacement_does_not_produce_mana_early_and_replays(self):
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('redirect',Zone.GRAVEYARD,Zone.EXILE,types=('Artifact',),optional=True),))
        self.game((ProduceMana(1,('G',)),),CostSpec(tap_source=True,zone_costs=(ZoneCost('sac','sacrifice'),)),extra=(redirect,))
        self.state.add_card('redirect','redirect','A',Zone.BATTLEFIELD);self.activate()
        self.assertFalse(self.state.mana_pool('B'));self.assertFalse(self.state.get(self.ref).tapped)
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        while self.kernel.pending_choice:
            q=self.kernel.pending_choice;cmd={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[0]}
            adapter.submit(q.actor,cmd);replay.submit(q.actor,cmd);self.assertEqual(adapter.archive(),replay.archive())
        self.assertEqual({'G':2},dict(self.state.mana_pool('B')))
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('rock')).zone)

    def test_replacement_validation_and_zero_mana(self):
        self.game((ProduceMana(0,('G',)),),mana=False);self.activate();self.drain();self.assertFalse(self.state.mana_pool('B'))
        rule=TappedManaReplacement('triple',3,'all');self.assertEqual(rule,decode(encode(rule)))
        for bad in (replace(rule,multiplier=True),replace(rule,multiplier=1),replace(rule,players='owner'),replace(rule,replacement_id='')):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Enchantment',),tapped_mana_replacements=(bad,)))
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Enchantment',),tapped_mana_replacements=(rule,rule)))

if __name__=='__main__':unittest.main()
