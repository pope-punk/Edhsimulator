"""Attached-object departure observers and the narrow Aura identity exception."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed

class AttachmentObserverTests(unittest.TestCase):
    def game(self):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(CardProgram('body','Body',('Creature',),subtypes=('Human',),power=2,toughness=3),)
        self.state=RulesState(('A','B'));self.host=self.state.add_card('host','body','B',Zone.BATTLEFIELD)
        self.other=self.state.add_card('other','body','B',Zone.BATTLEFIELD)
        self.aura=self.state.add_card('aura','catalog:angelic-destiny','A',Zone.HAND)
        self.k=RulesKernel(self.state,self.programs);self.k.open_window_for_scenario('A')
        self.state.add_mana('A',('C','C','W','W'))
        self.k.commit_action(self.k.quote_cast('cast','A',self.aura,(self.host,)),Payment((('C',2),('W',2))));self.drain();self.aura=self.state.current('aura')
    def drain(self,k=None):
        k=k or self.k
        while k.stack and not k.pending_choice:k.pass_priority(k.priority)
    def kill(self,ref):self.k.execute_for_scenario(ref,'A',(Destroy('source'),))
    def zone(self,name):return self.state.get(self.state.current(name)).zone
    def test_printed_cast_bonuses_and_exact_attached_creature_death(self):
        self.game();view=self.k.effective(self.host)
        self.assertEqual((6,7),(view.power,view.toughness));self.assertTrue({'flying','first_strike'}<=view.keywords)
        self.assertTrue({'Human','Angel'}<=view.subtypes)
        self.kill(self.other);self.assertFalse(self.k.stack);self.assertEqual(Zone.BATTLEFIELD,self.zone('aura'))
        self.kill(self.host);self.assertEqual(Zone.GRAVEYARD,self.zone('aura'));self.assertEqual(1,len(self.k.stack))
        self.drain();self.assertEqual(Zone.HAND,self.zone('aura'))
    def test_aura_death_alone_and_non_graveyard_host_departures_do_not_trigger(self):
        for subject,destination in (('aura',Zone.GRAVEYARD),('host',Zone.HAND),('host',Zone.EXILE)):
            self.game();ref=self.aura if subject=='aura' else self.host
            self.k.execute_for_scenario(ref,'A',(Move('source',destination),))
            self.assertFalse(self.k.stack);self.assertEqual(Zone.GRAVEYARD,self.zone('aura'))
    def test_simultaneous_deaths_find_the_aura_successor(self):
        self.game();self.k.execute_for_scenario(self.aura,'A',(SelectAll(Selector(Zone.BATTLEFIELD),(Destroy('selected'),)),))
        self.assertEqual(1,len(self.k.stack));self.drain();self.assertEqual(Zone.HAND,self.zone('aura'))
    def test_distinct_later_destruction_in_same_resolution_is_not_sba_tracking(self):
        self.game();self.k.execute_for_scenario(self.aura,'A',(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',)),(Destroy('selected'),)),Destroy('source')))
        self.assertEqual(1,len(self.k.stack));self.drain();self.assertEqual(Zone.GRAVEYARD,self.zone('aura'))
    def test_aura_exile_in_same_batch_does_not_qualify(self):
        self.game()
        # Commit and collect one simultaneous mixed-destination event batch.
        before=self.state.objects(Zone.BATTLEFIELD);views=self.k.characteristics()
        events=self.state.move((ZoneMove(self.host,Zone.GRAVEYARD),ZoneMove(self.aura,Zone.EXILE)),'fixture_batch')
        self.k._collect(events,before,self.state.objects(Zone.BATTLEFIELD),views);self.k.advance();self.drain()
        self.assertEqual(Zone.EXILE,self.zone('aura'))
    def test_old_trigger_does_not_follow_a_later_graveyard_incarnation(self):
        self.game();self.kill(self.host);grave=self.state.current('aura')
        self.state.move((ZoneMove(grave,Zone.EXILE),),'response')
        self.state.move((ZoneMove(self.state.current('aura'),Zone.GRAVEYARD),),'response')
        later=self.state.current('aura');self.drain();self.assertEqual(later,self.state.current('aura'))
        self.assertEqual(Zone.GRAVEYARD,self.zone('aura'))
    def test_stolen_and_copied_auras_return_to_their_owners(self):
        self.game();self.state.change_control(self.aura,'B');self.kill(self.host);self.drain()
        self.assertEqual(['aura'],[o.ref.card_id for o in self.state.zone('A',Zone.HAND)])
        self.game();self.k.execute_for_scenario(self.aura,'A',(Move('source',Zone.EXILE),))
        copy=self.state.add_card('copy','catalog:forest','B',Zone.HAND)
        self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,'B',copied_definition='catalog:angelic-destiny',attached_to=self.host),),'fixture_copy')
        self.kill(self.host);self.drain();obj=self.state.get(self.state.current('copy'))
        self.assertEqual(('B',Zone.HAND,'catalog:forest'),(obj.owner,obj.zone,obj.effective_definition))
    def test_pending_return_actor_replay_preserves_exact_binding(self):
        self.game();self.kill(self.host);a=RulesActorAdapter(self.k);b=RulesActorAdapter.replay(a.archive(),self.programs)
        self.drain();self.drain(b.kernel);self.assertEqual(self.k.snapshot(),b.kernel.snapshot())
        self.assertEqual(Zone.HAND,self.zone('aura'))
    def test_checkpoint_before_unattached_aura_sba_retains_tracking(self):
        self.game();self.k.execute_for_scenario(self.host,'A',(Destroy('source'),May((GainLife(1),))))
        self.assertEqual('may',self.k.pending_choice.kind)
        self.assertEqual(Zone.BATTLEFIELD,self.zone('aura'))
        restored=RulesKernel.restore(self.k.snapshot(),self.programs)
        for k in (self.k,restored):
            q=k.pending_choice;k.answer(q.request_id,q.actor,[1]);self.drain(k)
        self.assertEqual(self.k.snapshot(),restored.snapshot());self.assertEqual(Zone.HAND,self.zone('aura'))
    def test_closed_event_and_binding_validation(self):
        p=load_reviewed()['angelic-destiny']['program'];self.assertEqual(p,decode(encode(p)))
        ability=p.abilities[0]
        for event in (EventPattern('spell_cast',subject='attached'),EventPattern('zone_changed',to_zone=Zone.BATTLEFIELD,subject='attached')):
            with self.assertRaises(RulesViolation):validate(replace(p,abilities=(replace(ability,event=event),)))
        with self.assertRaises(RulesViolation):validate(replace(p,enchant=None))

if __name__=='__main__':unittest.main()
