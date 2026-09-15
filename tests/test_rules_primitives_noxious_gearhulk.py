"""Successful destruction can have a replaced destination and retained toughness."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_adapter import RulesActorAdapter


class NoxiousGearhulkTests(unittest.TestCase):
    def game(self,indestructible=False,redirect=False,token=False):
        body=CardProgram('body','Body',('Creature',),power=3,toughness=7,keywords=('indestructible',) if indestructible else ())
        replacement=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,from_zone=Zone.BATTLEFIELD),))
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(body,replacement)
        self.state=RulesState(('A','B'));self.gear=self.state.add_card('gear','catalog:noxious-gearhulk','A',Zone.HAND)
        self.body=self.state.add_card('body','body','B',Zone.BATTLEFIELD,token=token)
        if redirect:self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def enter(self,cast=False):
        if cast:
            self.state.add_mana('A',('B','B','C','C','C','C'))
            self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.gear),Payment((('B',2),('C',4))))
            while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)
        else:self.kernel.execute_for_scenario(self.gear,'A',(Move('source',Zone.BATTLEFIELD),))
        q=self.kernel.pending_choice;self.assertEqual('trigger_targets',q.kind)
        self.assertNotIn(self.state.current('gear'),[o.ref for o in q.options])
        self.kernel.answer(q.request_id,'A',[next(i for i,o in enumerate(q.options) if o.ref==self.body)])
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual('may',self.kernel.pending_choice.kind)
        return self.kernel.pending_choice

    def test_printed_cast_and_successful_destruction(self):
        self.game();q=self.enter(cast=True);self.kernel.answer(q.request_id,'A',[0])
        self.assertEqual(47,self.state.life('A'));self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('body')).zone)
        view=self.kernel.effective(self.state.current('gear'));self.assertEqual((5,4),(view.power,view.toughness));self.assertIn('menace',view.keywords)
        self.assertEqual((),self.state.mana_pool('A'))

    def test_indestructibility_or_decline_prevents_life_gain(self):
        for indestructible,choice in ((True,0),(False,1)):
            self.game(indestructible=indestructible);q=self.enter();self.kernel.answer(q.request_id,'A',[choice])
            self.assertEqual(40,self.state.life('A'));self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.body).zone)

    def test_replaced_destination_still_counts_as_destruction(self):
        self.game(redirect=True);q=self.enter();self.kernel.answer(q.request_id,'A',[0])
        self.assertEqual(47,self.state.life('A'));self.assertEqual(Zone.EXILE,self.state.get(self.state.current('body')).zone)

    def test_token_uses_derived_last_known_toughness_before_ceasing(self):
        self.game(token=True);self.kernel.execute_for_scenario(self.body,'B',(UntilEndOfTurn('source',(ModifyPT(0,4),)),))
        q=self.enter();self.kernel.answer(q.request_id,'A',[0]);self.assertEqual(51,self.state.life('A'))
        self.assertFalse(any(o.ref.card_id=='body' for o in self.state.objects()))

    def test_optional_choice_checkpoint_and_actor_replay(self):
        self.game(redirect=True);q=self.enter();restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        adapter=RulesActorAdapter(self.kernel)
        adapter.submit('A',{'kind':'answer','request_id':q.request_id,'indexes':[0],'revision':self.kernel.revision})
        restored.answer(q.request_id,'A',[0]);self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        for actor in self.state.players:self.assertEqual(adapter.packet(actor),replay.packet(actor))

    def test_destination_independent_result_is_generic_and_validated(self):
        self.game()
        effect=WithZoneResult(Move('source',Zone.EXILE),None,(GainLife(MovedCount()),))
        program=validate(CardProgram('generic','Generic',('Instant',),spell_effects=(effect,)))
        self.assertEqual(program,decode(encode(program)))
        self.kernel.execute_for_scenario(self.gear,'A',(effect,));self.assertEqual(41,self.state.life('A'))
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),spell_effects=(WithZoneResult(Destroy('source'),'any',(GainLife(1),)),)))

    def test_copied_entry_ability_retains_its_controller_and_last_known_target(self):
        from edh_gauntlet.rules_state import ZoneMove
        self.game();copy=self.state.add_card('copy','catalog:forest','A',Zone.HAND)
        before=self.state.objects(Zone.BATTLEFIELD);views=self.kernel.characteristics()
        events=self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,copied_definition='catalog:noxious-gearhulk'),),'fixture-copy')
        self.kernel._collect(events,before,self.state.objects(Zone.BATTLEFIELD),views)
        q=self.kernel.advance();self.assertEqual('trigger_targets',q.kind)
        self.kernel.answer(q.request_id,'A',[next(i for i,o in enumerate(q.options) if o.ref==self.body)])
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)
        q=self.kernel.pending_choice;restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        for kernel in (self.kernel,restored):kernel.answer(q.request_id,'A',[0])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertEqual(47,self.state.life('A'))
        self.assertEqual('catalog:noxious-gearhulk',self.state.get(self.state.current('copy')).copied_definition)
