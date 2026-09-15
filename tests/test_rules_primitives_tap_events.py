"""Orientation transitions are shared by effects, payments and attacks."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class TapEventTests(unittest.TestCase):
    def game(self,extra=(),zone=Zone.BATTLEFIELD):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+tuple(extra)
        self.state=RulesState(('A','B'));self.city=self.state.add_card('city','catalog:city-of-brass','A',zone)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)
    def trigger_count(self):
        return sum(e['kind']=='trigger_created' and e['ability']=='tap-damage' for e in self.kernel.semantic_events)

    def test_mana_choice_finishes_before_damage_trigger_and_replay(self):
        self.game();q=self.kernel.commit_action(self.kernel.quote_activation('mana','A',self.city,'mana'),Payment())
        self.assertEqual(5,len(q.options));self.assertEqual(40,self.state.life('A'));self.assertFalse(self.kernel.stack)
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        cmd={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[0]}
        adapter.submit('A',cmd);replay.submit('A',cmd)
        self.assertEqual(adapter.archive(),replay.archive());self.assertEqual(1,sum(n for _,n in self.state.mana_pool('A')))
        self.assertEqual(40,self.state.life('A'));self.assertEqual(1,len(self.kernel.stack))
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):adapter.submit('A',cmd)
        self.assertEqual(before,self.kernel.snapshot());self.drain();self.drain(replay.kernel)
        self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot());self.assertEqual(39,self.state.life('A'))
        self.assertEqual(1,self.trigger_count())

    def test_external_tap_captures_controller_not_effect_actor(self):
        self.game();self.kernel.execute_for_scenario(self.city,'B',(SetTapped('source',True),));self.assertEqual(1,self.trigger_count())
        self.state.change_control(self.city,'B')
        self.drain();self.assertEqual((39,40),(self.state.life('A'),self.state.life('B')))

    def test_no_trigger_for_entering_tapped_repeated_tap_untap_or_phasing(self):
        self.game(zone=Zone.HAND)
        self.kernel.execute_for_scenario(self.city,'A',(Move('source',Zone.BATTLEFIELD,tapped=True),));self.city=self.state.current('city')
        self.kernel.execute_for_scenario(self.city,'A',(SetTapped('source',True),));self.assertEqual(0,self.trigger_count())
        self.kernel.execute_for_scenario(self.city,'A',(SetTapped('source',False),));self.assertEqual(0,self.trigger_count())
        self.state.phase(self.city,True);self.kernel.execute_for_scenario(self.city,'A',(SetTapped('source',True),));self.assertEqual(0,self.trigger_count())
        self.state.phase(self.city,False);self.kernel.execute_for_scenario(self.city,'A',(SetTapped('source',True),));self.drain();self.assertEqual(1,self.trigger_count())

    def test_copied_land_inherits_trigger_and_damage_source(self):
        self.game();forest=self.state.add_card('copy','catalog:forest','B',Zone.HAND)
        self.state.move((ZoneMove(forest,Zone.BATTLEFIELD,'B',copied_definition='catalog:city-of-brass'),),'copy')
        copied=self.state.current('copy');self.kernel.execute_for_scenario(copied,'A',(SetTapped('source',True),));self.drain()
        self.assertEqual((40,39),(self.state.life('A'),self.state.life('B')));self.assertEqual(1,self.trigger_count())

    def test_tap_selection_and_sacrifice_payment_keep_departing_trigger(self):
        ability=ActivatedProgram('pay',CostSpec(tap_selector=Selector(Zone.BATTLEFIELD,types=('Land',),relation='controlled'),tap_count=1,
            zone_costs=(ZoneCost('sac','sacrifice',Selector(Zone.BATTLEFIELD,types=('Land',),relation='controlled')),)),(GainLife(2),))
        self.game((CardProgram('payer','Payer',('Artifact',),activated=(ability,)),));payer=self.state.add_card('payer','payer','A',Zone.BATTLEFIELD)
        self.kernel.commit_action(self.kernel.quote_activation('pay','A',payer,'pay'),Payment(taps=(self.city,),zone_costs=(('sac',(self.city,)),)))
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('city')).zone);self.assertEqual(1,self.trigger_count())
        self.assertEqual(2,len(self.kernel.stack));self.drain();self.assertEqual(41,self.state.life('A'))

    def test_general_observer_filters_and_event_subject_binding(self):
        observer=CardProgram('observer','Observer',('Enchantment',),abilities=(AbilityProgram('untap',EventPattern('becomes_tapped',types=('Land',),controller_only=True),(SetTapped('event_subject',False),)),))
        self.game((observer,));self.state.add_card('observer','observer','A',Zone.BATTLEFIELD)
        own=self.state.add_card('own','catalog:forest','A',Zone.BATTLEFIELD);other=self.state.add_card('other','catalog:forest','B',Zone.BATTLEFIELD)
        for ref in (own,other):self.kernel.execute_for_scenario(ref,'B',(SetTapped('source',True),));self.drain()
        self.assertFalse(self.state.get(own).tapped);self.assertTrue(self.state.get(other).tapped)

    def test_attack_taps_trigger_but_vigilance_does_not(self):
        for vigilance in (False,True):
            city=load_reviewed()['city-of-brass']['program']
            body=replace(city,definition_id='body',name='Body',types=('Creature',),power=2,toughness=2,keywords=('vigilance',) if vigilance else ())
            self.game((body,));ref=self.state.add_card('body','body','A',Zone.BATTLEFIELD)
            for actor in ('A','B'):self.state.add_card('draw'+actor,'catalog:forest',actor,Zone.LIBRARY)
            self.kernel.begin_turn_for_scenario('A')
            for _ in range(4):
                for actor in ('A','B'):self.kernel.pass_priority(actor)
            self.kernel.declare_attackers('A',{ref:'B'},revision=self.kernel.revision)
            self.assertEqual(0 if vigilance else 1,self.trigger_count())

    def test_compiler_rejects_unimplemented_orientation_filters(self):
        event=EventPattern('becomes_tapped',subject='self');ability=AbilityProgram('tap',event,(GainLife(1),));base=CardProgram('test','Test',('Land',),abilities=(ability,))
        self.assertEqual(base,validate(decode(encode(base))))
        for bad in (replace(event,from_zone=Zone.HAND),replace(event,step='upkeep'),replace(event,recipient_relation='opponent_controlled'),replace(event,exclude_source=True),replace(event,counter_kind='charge')):
            with self.assertRaises(RulesViolation):validate(replace(base,abilities=(replace(ability,event=bad),)))

    def test_pending_cost_replacement_does_not_tap_or_trigger_until_commit(self):
        payer=CardProgram('payer','Payer',('Artifact',),activated=(ActivatedProgram('pay',CostSpec(
            tap_selector=Selector(Zone.BATTLEFIELD,types=('Land',),relation='controlled'),tap_count=1,
            zone_costs=(ZoneCost('sac','sacrifice',Selector(Zone.BATTLEFIELD,types=('Land',),relation='controlled')),)),(GainLife(2),)),))
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,optional=True),))
        self.game((payer,redirect));ref=self.state.add_card('payer','payer','A',Zone.BATTLEFIELD);self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD)
        self.kernel.commit_action(self.kernel.quote_activation('pay','A',ref,'pay'),Payment(taps=(self.city,),zone_costs=(('sac',(self.city,)),)))
        self.assertFalse(self.state.get(self.city).tapped);self.assertEqual(0,self.trigger_count())
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        for kernel in (self.kernel,restored):
            q=kernel.pending_choice;kernel.answer(q.request_id,q.actor,[0])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertEqual(1,self.trigger_count())
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('city')).zone)
        self.drain();self.drain(restored);self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual(41,self.state.life('A'))
