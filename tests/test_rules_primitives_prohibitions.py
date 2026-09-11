"""Entry and casting prohibitions inspect origins and override permissions."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class ProhibitionTests(unittest.TestCase):
    def game(self,source_zone=Zone.BATTLEFIELD):
        self.spell=CardProgram('spell','Permission fixture',('Instant',),cast=CastSpec(CostSpec(),'instant',origin_zones=(Zone.HAND,Zone.GRAVEYARD,Zone.EXILE)),spell_effects=(GainLife(1),))
        self.body=CardProgram('body','Body',('Creature',),power=2,toughness=2)
        self.artifact=CardProgram('copy-artifact','Copy artifact',('Artifact',),entry_copy=Selector(Zone.BATTLEFIELD,types=('Creature',)))
        self.copy_body=CardProgram('copy-body','Copy creature',('Creature',),power=2,toughness=2,entry_copy=Selector(Zone.BATTLEFIELD,types=('Artifact',)))
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(self.spell,self.body,self.artifact,self.copy_body)
        self.state=RulesState(('A','B'));self.source=self.state.add_card('kunoros','catalog:kunoros-hound-of-athreos','A',source_zone)
        self.ref=self.state.add_card('body','body','B',Zone.GRAVEYARD)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
    def move(self,ref):self.kernel.execute_for_scenario(ref,'A',(Move('source',Zone.BATTLEFIELD),))
    def drain(self,k=None):
        k=k or self.kernel
        while k.stack and not k.pending_choice:k.pass_priority(k.priority)
    def test_creature_entry_is_blocked_without_changing_incarnation_or_triggering(self):
        self.game();before=self.state.get(self.ref);self.move(self.ref)
        self.assertEqual(before,self.state.get(self.ref));self.assertIsNone(self.kernel.pending_choice)
        self.assertEqual(1,len([e for e in self.kernel.semantic_events if e['kind']=='entry_prohibited']))
        god=self.state.add_card('god','catalog:xenagos-god-of-revels','A',Zone.GRAVEYARD);self.move(god)
        self.assertEqual(Zone.GRAVEYARD,self.state.get(god).zone)
    def test_origin_types_control_copy_entry_legality(self):
        self.game();self.state.add_card('target','body','A',Zone.BATTLEFIELD)
        artifact=self.state.add_card('artifact','copy-artifact','A',Zone.GRAVEYARD);self.move(artifact)
        q=self.kernel.pending_choice;self.assertEqual('entry_copy',q.kind)
        self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.ref.card_id=='target')])
        self.assertIn('Creature',self.kernel.effective(self.state.current('artifact')).types)
        body=self.state.add_card('copy-body','copy-body','A',Zone.GRAVEYARD);self.move(body)
        self.assertIsNone(self.kernel.pending_choice);self.assertEqual(Zone.GRAVEYARD,self.state.get(body).zone)
    def test_simultaneous_batch_moves_only_permitted_cards_and_allows_token_creation(self):
        self.game();artifact=self.state.add_card('rock','catalog:sol-ring','A',Zone.GRAVEYARD)
        self.kernel.execute_for_scenario(self.source,'A',(SelectAll(Selector(Zone.GRAVEYARD),(Move('selected',Zone.BATTLEFIELD),)),))
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.ref).zone);self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('rock')).zone)
        self.kernel.execute_for_scenario(self.source,'A',(CreateTokens(self.body),))
        self.assertTrue(any(o.token for o in self.state.objects(Zone.BATTLEFIELD)))
    def test_incoming_prohibition_does_not_block_itself_or_simultaneous_entrants(self):
        self.game(Zone.GRAVEYARD)
        self.kernel.execute_for_scenario(self.source,'A',(SelectAll(Selector(Zone.GRAVEYARD),(Move('selected',Zone.BATTLEFIELD),)),))
        for name in ('kunoros','body'):self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current(name)).zone)
    def test_casting_prohibition_overrides_permission_but_exile_and_hand_work(self):
        self.game()
        for actor in ('A','B'):
            self.kernel.open_window_for_scenario(actor)
            ref=self.state.add_card(actor,'spell',actor,Zone.GRAVEYARD);before=self.kernel.snapshot()
            with self.assertRaises(RulesViolation):self.kernel.quote_cast('blocked'+actor,actor,ref)
            self.assertEqual(before,self.kernel.snapshot())
            self.state.move((ZoneMove(ref,Zone.EXILE),),'scenario_exile')
            self.kernel.commit_action(self.kernel.quote_cast('exile'+actor,actor,self.state.current(actor)),Payment());self.drain()
            self.assertEqual(41,self.state.life(actor))
        hand=self.state.add_card('hand','spell','B',Zone.HAND);self.kernel.open_window_for_scenario('B')
        self.kernel.commit_action(self.kernel.quote_cast('hand','B',hand),Payment());self.drain();self.assertEqual(42,self.state.life('B'))
    def test_phasing_departure_and_copied_sources_use_shared_rules(self):
        self.game();self.state.phase(self.source,True);self.move(self.ref);self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('body')).zone)
        self.state.phase(self.source,False)
        self.state.move((ZoneMove(self.source,Zone.HAND),),'scenario_departure')
        copy=self.state.add_card('copy','body','B',Zone.HAND);self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,'B',copied_definition='catalog:kunoros-hound-of-athreos'),),'scenario_copy')
        target=self.state.add_card('new','body','A',Zone.GRAVEYARD);self.move(target);self.assertEqual(Zone.GRAVEYARD,self.state.get(target).zone)
        self.state.change_control(self.state.current('copy'),'A');self.move(target);self.assertEqual(Zone.GRAVEYARD,self.state.get(target).zone)
    def test_paid_cast_rechecks_prohibition_and_retains_printed_keywords(self):
        self.game(Zone.HAND);spell=self.state.add_card('s','spell','A',Zone.GRAVEYARD);quote=self.kernel.quote_cast('stale','A',spell)
        self.state.add_mana('A',('C','W','B'))
        self.kernel.commit_action(self.kernel.quote_cast('kunoros','A',self.source),Payment((('C',1),('W',1),('B',1))));self.drain()
        self.assertTrue({'vigilance','menace','lifelink'}<=self.kernel.effective(self.state.current('kunoros')).keywords)
        self.kernel.open_window_for_scenario('A')
        with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,Payment())
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('new','A',spell)
    def test_blocked_resolution_checkpoint_replay(self):
        self.game();a=RulesActorAdapter(self.kernel);b=RulesActorAdapter.replay(a.archive(),self.programs)
        for k in (self.kernel,b.kernel):k.execute_for_scenario(self.ref,'A',(Move('source',Zone.BATTLEFIELD),GainLife(1)))
        self.assertEqual(a.archive(),b.archive());self.assertEqual(41,self.state.life('A'))
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs);self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.game()
        self.state.add_card('copy-entry','copy-artifact','A',Zone.GRAVEYARD)
        self.kernel.execute_for_scenario(self.source,'A',(SelectAll(Selector(Zone.GRAVEYARD),(Move('selected',Zone.BATTLEFIELD),)),))
        self.assertEqual('entry_copy',self.kernel.pending_choice.kind)
        self.assertFalse(any(e['kind']=='entry_prohibited' for e in self.kernel.semantic_events))
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        for k in (self.kernel,restored):
            q=k.pending_choice;k.answer(q.request_id,q.actor,[])
            self.assertEqual(1,sum(e['kind']=='entry_prohibited' for e in k.semantic_events))
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
    def test_closed_prohibition_validation_and_codec(self):
        self.game();program=load_reviewed()['kunoros-hound-of-athreos']['program'];self.assertEqual(program,decode(encode(program)))
        for restrictions in ([],(Selector(Zone.HAND),),(Selector(Zone.BATTLEFIELD),)):
            with self.assertRaises(RulesViolation):validate(replace(program,entry_restrictions=restrictions))
        for restriction in (CastRestriction(Selector(Zone.HAND),(Zone.HAND,)),CastRestriction(Selector(Zone.STACK),()),CastRestriction(Selector(Zone.STACK),('graveyard',))):
            with self.assertRaises(RulesViolation):validate(replace(program,casting_restrictions=(restriction,)))

if __name__=='__main__':unittest.main()
