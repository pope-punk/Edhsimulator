"""Modal declarations bind independent targets and canonical printed order."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,PlayerRef,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_modal import prepare_modal


class ModalPreparationTests(unittest.TestCase):
    def setUp(self):
        creature=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',)))
        self.spec=ModalSpec((SpellMode('boost',(UntilEndOfTurn('target',(ModifyPT(1,1),)),),creature),
            SpellMode('destroy',(Destroy('target'),),creature),SpellMode('draw',(Draw(1,'target'),),TargetSpec(players='all'))),maximum=2)
        self.program=CardProgram('modal','Modal',('Sorcery',),cast=CastSpec(CostSpec(ManaCost(1))),modal=self.spec)
        self.state=RulesState(('A','B'));self.kernel=RulesKernel(self.state,(self.program,CardProgram('elf','Elf',('Creature',),power=1,toughness=1)))
        self.source=self.state.add_card('spell','modal','A',Zone.HAND)
        self.elf=self.state.add_card('elf','elf','A',Zone.BATTLEFIELD)

    def prepare(self,choices,spec=None):
        return prepare_modal(self.kernel,self.state.get(self.source),'A',spec or self.spec,choices)

    def test_printed_order_and_shared_target_across_different_modes(self):
        before=self.kernel.snapshot()
        choices=(('destroy',(self.elf,)),('boost',(self.elf,)))
        self.assertEqual(tuple(reversed(choices)),self.prepare(choices))
        self.assertEqual(before,self.kernel.snapshot())

    def test_mode_specific_target_domains(self):
        self.assertEqual((('boost',(self.elf,)),('draw',(PlayerRef('B'),))),self.prepare((('draw',(PlayerRef('B'),)),('boost',(self.elf,)))))
        for choices in ((('draw',(self.elf,)),),(('boost',(PlayerRef('A'),)),),(('boost',()),)):
            with self.assertRaises(RulesViolation):self.prepare(choices)

    def test_unselected_mode_has_no_target_requirement(self):
        self.assertEqual((('draw',(PlayerRef('A'),)),),self.prepare((('draw',(PlayerRef('A'),)),)))

    def test_invalid_mode_counts_identities_and_packet_shapes(self):
        for choices in ((),(('boost',(self.elf,)),)*2,(('unknown',()),),[('boost',(self.elf,))],(('boost',[self.elf]),),
                (('boost',(self.elf,)),('destroy',(self.elf,)),('draw',(PlayerRef('A'),)))):
            with self.assertRaises(RulesViolation):self.prepare(choices)

    def test_conditional_maximum_reads_captured_actor_state_at_announcement(self):
        spec=replace(self.spec,maximum=1,extra_mode_condition=LifeCondition(40),conditional_maximum=2)
        choices=(('boost',(self.elf,)),('destroy',(self.elf,)))
        self.assertEqual(choices,self.prepare(choices,spec))
        self.state.lose_life_batch(('A',),1)
        with self.assertRaises(RulesViolation):self.prepare(choices,spec)

    def test_declaration_roundtrip_and_validation(self):
        self.assertEqual(self.program,validate(decode(encode(self.program))))
        for spec in (replace(self.spec,minimum=0),replace(self.spec,maximum=True),replace(self.spec,modes=self.spec.modes*2),
                replace(self.spec,conditional_maximum=3),replace(self.spec,extra_mode_condition=LifeCondition(40),conditional_maximum=1)):
            with self.assertRaises(RulesViolation):validate(replace(self.program,modal=spec))
        with self.assertRaises(RulesViolation):validate(replace(self.program,spell_effects=(Draw(),)))
        with self.assertRaises(RulesViolation):validate(replace(self.program,modal=ModalSpec((SpellMode('bad',(Draw(1,'target'),)),))))

    def test_missing_choices_and_unprepared_fixture_fail_before_acceptance(self):
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('C',));before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('cast','A',self.source)
        self.assertEqual(before,self.kernel.snapshot())
        with self.assertRaises(RulesViolation):self.kernel.stage_spell_for_scenario(self.source,'A')
        self.assertEqual(before,self.kernel.snapshot())

    def cast(self,choices,targets=()):
        from edh_gauntlet.rules_casting import Payment
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('C',))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.source,targets,mode_choices=choices),Payment((('C',1),)))

    def drain(self):
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)

    def test_selected_modes_execute_in_printed_order_and_pay_once(self):
        self.cast((('destroy',(self.elf,)),('boost',(self.elf,))))
        self.assertEqual((),self.state.mana_pool('A'));self.assertEqual(1,len(self.kernel.stack))
        self.drain();last=self.kernel.last_known[self.elf][1]
        self.assertEqual(2,last.power);self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('elf')).zone)

    def test_one_illegal_mode_target_does_not_cancel_other_mode(self):
        from edh_gauntlet.rules_state import ZoneMove
        self.state.add_card('draw','elf','B',Zone.LIBRARY)
        self.cast((('boost',(self.elf,)),('draw',(PlayerRef('B'),))))
        self.state.move((ZoneMove(self.elf,Zone.GRAVEYARD),),'scenario_response');self.drain()
        self.assertEqual(1,len(self.state.zone('B',Zone.HAND)))

    def test_all_targets_illegal_cancels_even_selected_nontarget_effects(self):
        from edh_gauntlet.rules_state import ZoneMove
        self.program=replace(self.program,modal=replace(self.spec,modes=(self.spec.modes[0],SpellMode('life',(GainLife(5),)))))
        self.kernel=RulesKernel(self.state,(self.program,CardProgram('elf','Elf',('Creature',),power=1,toughness=1)))
        self.cast((('boost',(self.elf,)),('life',())))
        self.state.move((ZoneMove(self.elf,Zone.GRAVEYARD),),'scenario_response');self.drain()
        self.assertEqual(40,self.state.life('A'))

    def test_legality_is_rechecked_per_mode_not_just_per_object(self):
        from edh_gauntlet.rules_state import ZoneMove
        # Same physical target, but only the second mode accepts an Artifact.
        artifact_target=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Artifact',)))
        modes=(self.spec.modes[0],SpellMode('tap',(SetTapped('target',True),),artifact_target))
        both=CardProgram('elf','Elf',('Creature','Artifact'),power=1,toughness=1)
        self.program=replace(self.program,modal=replace(self.spec,modes=modes))
        changer=CardProgram('changer','Changer',('Enchantment',),continuous=(ContinuousProgram('lose-creature',Selector(Zone.BATTLEFIELD,types=('Artifact',)),(ChangeTypes(remove=('Creature',)),)),))
        self.kernel=RulesKernel(self.state,(self.program,both,changer))
        self.cast((('boost',(self.elf,)),('tap',(self.elf,))))
        self.state.add_card('changer','changer','A',Zone.BATTLEFIELD)
        self.drain();self.assertTrue(self.state.get(self.elf).tapped)
        self.assertFalse(any(e['kind']=='temporary_effect_created' for e in self.kernel.semantic_events))

    def test_nested_choice_replay_retains_mode_targets(self):
        from edh_gauntlet.rules_adapter import RulesActorAdapter
        from edh_gauntlet.rules_casting import PreparedAction,Payment
        modes=(SpellMode('maybe',(May((UntilEndOfTurn('target',(ModifyPT(3,3),)),)),),self.spec.modes[0].targets),self.spec.modes[2])
        self.program=replace(self.program,modal=replace(self.spec,modes=modes))
        self.kernel=RulesKernel(self.state,(self.program,CardProgram('elf','Elf',('Creature',),power=1,toughness=1)))
        self.state.add_card('draw','elf','B',Zone.LIBRARY)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('C',))
        quote=self.kernel.quote_cast('cast','A',self.source,mode_choices=(('maybe',(self.elf,)),('draw',(PlayerRef('B'),))))
        self.assertEqual(quote,PreparedAction.from_json(quote.to_json()));self.kernel.commit_action(quote,Payment((('C',1),)))
        while not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),tuple(self.kernel.definitions.values()))
        request=self.kernel.pending_choice
        command={'kind':'answer','revision':self.kernel.revision,'request_id':request.request_id,'indexes':[0]}
        adapter.submit('A',command);replay.submit('A',command)
        self.assertEqual(adapter.archive(),replay.archive());self.assertEqual(4,self.kernel.effective(self.elf).power)
        self.assertEqual(1,len(self.state.zone('B',Zone.HAND)))

    def test_actor_cast_publishes_modes_and_replays_exactly(self):
        from edh_gauntlet.rules_adapter import RulesActorAdapter
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('C',))
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),tuple(self.kernel.definitions.values()))
        command={'kind':'cast','revision':self.kernel.revision,'action_id':'cast','source':self.source.to_json(),'targets':[],'x_value':0,
                 'payment':{'mana':{'C':1},'taps':[]},'modes':[{'mode_id':'boost','targets':[self.elf.to_json()]}]}
        adapter.submit('A',command);replay.submit('A',command)
        self.assertEqual(adapter.archive(),replay.archive())
        self.assertEqual('boost',adapter.packet('B')['stack'][0]['modes'][0]['mode_id'])

    def test_later_mode_does_not_move_a_target_retired_by_an_earlier_mode(self):
        modes=(self.spec.modes[1],SpellMode('return',(Move('target',Zone.HAND),),self.spec.modes[0].targets))
        self.program=replace(self.program,modal=replace(self.spec,modes=modes))
        self.kernel=RulesKernel(self.state,(self.program,CardProgram('elf','Elf',('Creature',),power=1,toughness=1)))
        self.cast((('destroy',(self.elf,)),('return',(self.elf,))))
        self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('elf')).zone)
        self.assertFalse(self.kernel.pending_choice)
