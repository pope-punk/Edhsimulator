"""Damage instructions re-read recipients after earlier instructions resolve."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter


class DamageResolutionTests(unittest.TestCase):
    def game(self,effects,types=('Creature',),extra=()):
        self.programs=(CardProgram('spell','Spell',('Instant',),keywords=('lifelink',),cast=CastSpec(CostSpec(),timing='instant'),spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD,any_types=('Creature','Planeswalker','Battle'))),spell_effects=effects),
            CardProgram('body','Body',types,power=4 if 'Creature' in types else None,toughness=4 if 'Creature' in types else None),*extra)
        self.state=RulesState(('A','B'));self.spell=self.state.add_card('spell','spell','A',Zone.HAND)
        self.body=self.state.add_card('body','body','B',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def cast_and_drain(self):
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.spell,(self.body,)),Payment())
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)

    def test_target_moved_earlier_in_resolution_is_skipped_and_later_effect_runs(self):
        self.game((Move('target',Zone.EXILE),Damage('target',2),GainLife(1)))
        self.cast_and_drain()
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('body')).zone)
        self.assertEqual(41,self.state.life('A'))
        self.assertFalse(any(e['kind']=='damage_dealt' for e in self.kernel.semantic_events))

    def test_target_blinked_earlier_is_not_confused_with_new_incarnation(self):
        self.game((WithMoved('target',Zone.EXILE,(Move('moved',Zone.BATTLEFIELD),)),Damage('target',2),GainLife(1)))
        self.cast_and_drain();obj=self.state.get(self.state.current('body'))
        self.assertEqual(Zone.BATTLEFIELD,obj.zone);self.assertNotEqual(self.body,obj.ref)
        self.assertEqual(0,obj.damage_marked);self.assertEqual(41,self.state.life('A'))

    def test_recipient_losing_creature_type_during_resolution_cannot_take_damage(self):
        # Removing the source of an animation effect changes the target before damage.
        animator=CardProgram('animator','Animator',('Enchantment',),continuous=(ContinuousProgram('animate',Selector(Zone.BATTLEFIELD,types=('Artifact',)),(ChangeTypes(add=('Creature',)),SetPT(4,4))),))
        self.game((SelectAll(Selector(Zone.BATTLEFIELD,types=('Enchantment',)),(Destroy('selected'),)),Damage('target',2),GainLife(1)),types=('Artifact',),extra=(animator,))
        self.state.add_card('animator','animator','A',Zone.BATTLEFIELD)
        self.cast_and_drain();self.assertEqual(0,self.state.get(self.body).damage_marked)
        self.assertEqual(41,self.state.life('A'))

    def test_spell_damage_to_counter_permanents_replays_through_actor_commands(self):
        for card_type,counter in (('Planeswalker','loyalty'),('Battle','defense')):
            self.game((Damage('target',2),),(card_type,));self.state.add_counters(self.body,counter,4)
            adapter=RulesActorAdapter(self.kernel)
            adapter.submit('A',{'kind':'cast','revision':self.kernel.revision,'action_id':'cast','source':self.spell.to_json(),'targets':[self.body.to_json()],'x_value':0,'payment':{'mana':{},'taps':[]}})
            while self.kernel.stack:adapter.submit(self.kernel.priority,{'kind':'pass','revision':self.kernel.revision})
            self.assertEqual(((counter,2),),self.state.get(self.body).counters);self.assertEqual(42,self.state.life('A'))
            replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
            for actor in ('A','B'):self.assertEqual(adapter.packet(actor),replay.packet(actor))
