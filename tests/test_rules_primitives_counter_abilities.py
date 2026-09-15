"""Ability countering affects waiting stack frames, not resolving or future triggers."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed

class CounterAbilitiesTests(unittest.TestCase):
    def game(self,extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(
            CardProgram('engine','Engine',('Artifact',),activated=(ActivatedProgram('gain',CostSpec(),(GainLife(3),)),),abilities=(AbilityProgram('upkeep',EventPattern('step_began',step='upkeep',controller_only=True),(GainLife(5),)),)),
            CardProgram('spell','Spell',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),spell_effects=(GainLife(7),)))+tuple(extra)
        self.state=RulesState(('A','B'));self.engine=self.state.add_card('engine','engine','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
    def cast(self,key,definition='spell'):
        ref=self.state.add_card(key,definition,'A',Zone.HAND)
        if definition=='catalog:summary-dismissal':self.state.add_mana('A',('C','C','U','U'));payment=Payment((('C',2),('U',2)))
        else:payment=Payment()
        self.kernel.commit_action(self.kernel.quote_cast(key,'A',ref),payment)
    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)
    def activation(self):self.kernel.commit_action(self.kernel.quote_activation('gain','A',self.engine,'gain'),Payment())

    def test_dismissal_exiles_other_spells_and_counters_activated_and_triggered_abilities(self):
        self.game();self.kernel.begin_step('A','upkeep');self.activation();self.cast('victim');self.cast('dismissal','catalog:summary-dismissal');self.drain()
        self.assertEqual(40,self.state.life('A'));self.assertFalse(self.kernel.stack)
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('victim')).zone);self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('dismissal')).zone)
        events=[e for e in self.kernel.semantic_events if e['kind']=='abilities_countered'];self.assertEqual(2,len(events[0]['frames']))
        self.assertFalse(any(e['kind']=='spells_countered' for e in self.kernel.semantic_events))

    def test_new_trigger_waiting_for_placement_is_not_countered(self):
        watch=CardProgram('watch','Watch',('Enchantment',),abilities=(AbilityProgram('exile',EventPattern('zone_changed',from_zone=Zone.STACK,to_zone=Zone.EXILE),(GainLife(2),)),))
        self.game((watch,));self.state.add_card('watch','watch','A',Zone.BATTLEFIELD)
        self.cast('victim');self.cast('dismissal','catalog:summary-dismissal');self.drain();self.assertEqual(42,self.state.life('A'))

    def test_counter_domain_uses_ability_controller_not_current_source_controller(self):
        sweep=CardProgram('sweep','Sweep',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),spell_effects=(CounterAbilities('controller'),))
        self.game((sweep,));self.activation();self.state.change_control(self.engine,'B');self.cast('sweep','sweep');self.drain()
        self.assertEqual(40,self.state.life('A'));self.assertFalse(self.kernel.stack)

    def test_countering_opponents_preserves_own_ability_and_spells(self):
        sweep=CardProgram('sweep','Sweep',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),spell_effects=(CounterAbilities('opponents'),))
        self.game((sweep,));self.activation();self.cast('victim');self.cast('sweep','sweep');self.drain();self.assertEqual(50,self.state.life('A'))

    def test_replay_after_exile_replacement_continues_countering_once(self):
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('hand',Zone.EXILE,Zone.HAND,from_zone=Zone.STACK,optional=True),))
        self.game((redirect,));self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD)
        self.activation();self.cast('victim');self.cast('dismissal','catalog:summary-dismissal');self.drain();self.assertEqual(2,len(self.kernel.stack))
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs);q=self.kernel.pending_choice
        command={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[0]}
        adapter.submit(q.actor,command);replay.submit(q.actor,command);self.assertEqual(adapter.archive(),replay.archive());self.assertEqual(40,self.state.life('A'))
        self.assertEqual(1,sum(e['kind']=='abilities_countered' for e in self.kernel.semantic_events));self.assertEqual(Zone.HAND,self.state.get(self.state.current('victim')).zone)

    def test_resolving_ability_continues_and_invalid_domains_are_rejected(self):
        sweeper=CardProgram('sweeper','Sweeper',('Artifact',),activated=(ActivatedProgram('sweep',CostSpec(),(CounterAbilities(),GainLife(2))),))
        self.game((sweeper,));self.activation();ref=self.state.add_card('sweeper','sweeper','A',Zone.BATTLEFIELD)
        self.kernel.commit_action(self.kernel.quote_activation('sweep','A',ref,'sweep'),Payment());self.drain();self.assertEqual(42,self.state.life('A'))
        self.assertEqual(CounterAbilities(),decode(encode(CounterAbilities())))
        for bad in (None,[],1,'target'):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Sorcery',),spell_effects=(CounterAbilities(bad),)))
