"""Ordinary zone movement retires waiting spell frames, not independent abilities."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_casting import Payment

class StackDepartureTests(unittest.TestCase):
    def game(self,destination=Zone.EXILE,extra=()):
        self.programs=(CardProgram('victim','Victim',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),spell_effects=(GainLife(7),)),
            CardProgram('move','Move',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),spell_targets=TargetSpec(Selector(Zone.STACK)),spell_effects=(Move('target',destination),)),
            CardProgram('engine','Engine',('Artifact',),activated=(ActivatedProgram('gain',CostSpec(),(GainLife(3),)),)),
            CardProgram('kill','Kill',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD)),spell_effects=(Move('target',Zone.EXILE),)))+tuple(extra)
        self.state=RulesState(('A','B'));self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
    def cast(self,key,definition='victim',targets=()):
        ref=self.state.add_card(key,definition,'A',Zone.HAND)
        self.kernel.commit_action(self.kernel.quote_cast(key,'A',ref,targets),Payment());return self.state.current(key)
    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)

    def test_exile_return_and_graveyard_move_remove_waiting_spell(self):
        for destination in (Zone.EXILE,Zone.HAND,Zone.GRAVEYARD):
            self.game(destination);victim=self.cast('victim');self.cast('move','move',(victim,));self.drain()
            self.assertFalse(self.kernel.stack);self.assertEqual(40,self.state.life('A'))
            self.assertEqual(destination,self.state.get(self.state.current('victim')).zone)
            self.assertFalse(any(e['kind']=='spells_countered' for e in self.kernel.semantic_events))

    def test_destination_choice_keeps_spell_until_commit_then_replays_removal(self):
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('hand',Zone.EXILE,Zone.HAND,from_zone=Zone.STACK,optional=True),))
        self.game(extra=(redirect,));self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD)
        victim=self.cast('victim');self.cast('move','move',(victim,));self.drain()
        self.assertEqual(1,len(self.kernel.stack));self.assertEqual(Zone.STACK,self.state.get(victim).zone)
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs);q=self.kernel.pending_choice
        command={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[0]}
        adapter.submit(q.actor,command);replay.submit(q.actor,command);self.assertEqual(adapter.archive(),replay.archive());self.assertFalse(self.kernel.stack)
        self.assertEqual(40,self.state.life('A'));self.assertEqual(Zone.HAND,self.state.get(self.state.current('victim')).zone)

    def test_removing_ability_source_keeps_independent_ability(self):
        self.game();source=self.state.add_card('engine','engine','A',Zone.BATTLEFIELD)
        self.kernel.commit_action(self.kernel.quote_activation('ability','A',source,'gain'),Payment())
        self.cast('kill','kill',(source,));self.drain();self.assertEqual(43,self.state.life('A'));self.assertEqual(Zone.EXILE,self.state.get(self.state.current('engine')).zone)

    def test_mass_stack_exile_removes_all_waiting_spells_and_preserves_ability(self):
        mass=CardProgram('mass','Mass',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),spell_effects=(SelectAll(Selector(Zone.STACK,exclude_source=True),(Move('selected',Zone.EXILE),)),))
        self.game(extra=(mass,));source=self.state.add_card('engine','engine','A',Zone.BATTLEFIELD)
        self.kernel.commit_action(self.kernel.quote_activation('ability','A',source,'gain'),Payment())
        self.cast('one');self.cast('two');self.cast('mass','mass');self.drain()
        self.assertEqual(43,self.state.life('A'));self.assertEqual({'one','two'},{o.ref.card_id for o in self.state.zone('A',Zone.EXILE)})

    def test_moving_resolving_spell_does_not_cancel_its_remaining_instructions(self):
        spell=CardProgram('self','Self',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),spell_effects=(Move('source',Zone.EXILE),GainLife(2)))
        self.game(extra=(spell,));self.cast('self','self');self.drain();self.assertEqual(42,self.state.life('A'));self.assertEqual(Zone.EXILE,self.state.get(self.state.current('self')).zone)
