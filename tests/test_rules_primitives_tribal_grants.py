"""Static tribal grants use the same selector and layer engine as other effects."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState, Zone, RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter


class TribalGrantTests(unittest.TestCase):
    def setUp(self):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(
            CardProgram('illusion','Illusion',('Creature',),subtypes=('Illusion',),power=1,toughness=1),
            CardProgram('angel','Angel',('Creature',),subtypes=('Angel',),power=2,toughness=2),
            CardProgram('false-angel','False Angel',('Artifact',),subtypes=('Angel',)),
            CardProgram('illusion-lord','Illusion Lord',('Creature',),subtypes=('Illusion',),power=2,toughness=2,
                continuous=load_reviewed()['lord-of-the-unreal']['program'].continuous),)
        self.state=RulesState(('A','B'));self.kernel=RulesKernel(self.state,self.programs)

    def add(self,key,definition,actor='A',zone=Zone.BATTLEFIELD):
        return self.state.add_card(key,definition,actor,zone)

    def drain(self):
        while self.kernel.stack and not self.kernel.pending_choice:
            self.kernel.pass_priority(self.kernel.priority)

    def test_lyra_excludes_self_opponents_and_noncreatures(self):
        lyra=self.add('lyra','catalog:lyra-dawnbringer');angel=self.add('angel','angel')
        enemy=self.add('enemy','angel','B');false=self.add('false','false-angel')
        self.assertEqual(5,self.kernel.effective(lyra).power)
        self.assertTrue({'flying','first_strike','lifelink'}<=self.kernel.effective(lyra).keywords)
        self.assertEqual(3,self.kernel.effective(angel).power);self.assertIn('lifelink',self.kernel.effective(angel).keywords)
        self.assertEqual(2,self.kernel.effective(enemy).power);self.assertNotIn('lifelink',self.kernel.effective(enemy).keywords)
        self.assertNotIn('lifelink',self.kernel.effective(false).keywords)

    def test_source_control_and_recipient_control_update_membership(self):
        lord=self.add('lord','catalog:lord-of-the-unreal');own=self.add('own','illusion');enemy=self.add('enemy','illusion','B')
        self.assertEqual(2,self.kernel.effective(own).power)
        self.state.change_control(lord,'B')
        self.assertEqual(1,self.kernel.effective(own).power);self.assertNotIn('hexproof',self.kernel.effective(own).keywords)
        self.assertEqual(2,self.kernel.effective(enemy).power)
        self.state.change_control(own,'B');self.assertIn('hexproof',self.kernel.effective(own).keywords)

    def test_new_recipient_and_source_departure_recompute_static_grants(self):
        lord=self.add('lord','catalog:lord-of-the-unreal');creature=self.add('later','illusion',zone=Zone.HAND)
        self.kernel.enter(creature,'A');creature=self.state.current('later')
        self.assertEqual(2,self.kernel.effective(creature).power)
        self.kernel.execute_for_scenario(lord,'A',(Move('source',Zone.GRAVEYARD),))
        self.assertEqual(1,self.kernel.effective(creature).power);self.assertNotIn('hexproof',self.kernel.effective(creature).keywords)

    def test_overlapping_grants_stack_stats_and_survive_one_source_leaving(self):
        first=self.add('first','catalog:lord-of-the-unreal');second=self.add('second','catalog:lord-of-the-unreal')
        creature=self.add('creature','illusion');self.assertEqual(3,self.kernel.effective(creature).power)
        self.kernel.execute_for_scenario(first,'A',(Move('source',Zone.GRAVEYARD),))
        self.assertEqual(2,self.kernel.effective(creature).power);self.assertIn('hexproof',self.kernel.effective(creature).keywords)
        self.state.phase(second,True);self.assertEqual(1,self.kernel.effective(creature).power)
        self.state.phase(second,False);self.assertEqual(2,self.kernel.effective(creature).power)

    def test_non_other_selector_can_include_its_source(self):
        source=self.add('self','illusion-lord');self.assertEqual(3,self.kernel.effective(source).power)
        self.assertIn('hexproof',self.kernel.effective(source).keywords)

    def test_copied_lord_inherits_static_program_and_replays(self):
        self.add('dead','catalog:lord-of-the-unreal',zone=Zone.GRAVEYARD)
        copy=self.add('double','catalog:body-double',zone=Zone.HAND);creature=self.add('creature','illusion')
        self.kernel.enter(copy,'A');request=self.kernel.pending_choice
        self.kernel.answer(request.request_id,'A',(next(i for i,o in enumerate(request.options) if o.ref and o.ref.card_id=='dead'),))
        self.assertEqual(2,self.kernel.effective(creature).power)
        adapter=RulesActorAdapter(self.kernel);restored=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.assertEqual(adapter.packet('A'),restored.packet('A'));self.assertIn('hexproof',restored.kernel.effective(creature).keywords)

    def test_granted_hexproof_rejects_enemy_target_but_allows_controller(self):
        self.add('lord','catalog:lord-of-the-unreal');creature=self.add('creature','illusion')
        enemy=self.add('enemy-spell','catalog:murder','B',Zone.HAND);own=self.add('own-spell','catalog:murder',zone=Zone.HAND)
        self.kernel.open_window_for_scenario('B');self.state.add_mana('B',('B','B','C'))
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('enemy','B',enemy,(creature,))
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('B','B','C'))
        self.kernel.commit_action(self.kernel.quote_cast('own','A',own,(creature,)),Payment((('B',2),('C',1))))
        self.drain();self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('creature')).zone)

    def test_both_cards_pay_printed_costs_and_apply_grants_on_resolution(self):
        for key,definition,mana,payment in (
            ('lord-of-the-unreal','illusion',('U','U'),(('U',2),)),
            ('lyra-dawnbringer','angel',('W','W','C','C','C'),(('W',2),('C',3)))):
            with self.subTest(card=key):
                state=RulesState(('A','B'));kernel=RulesKernel(state,self.programs)
                creature=state.add_card('creature',definition,'A',Zone.BATTLEFIELD)
                card=state.add_card('spell','catalog:'+key,'A',Zone.HAND);base=kernel.effective(creature).power
                kernel.open_window_for_scenario('A');state.add_mana('A',mana)
                kernel.commit_action(kernel.quote_cast('cast','A',card),Payment(payment))
                self.assertEqual(base,kernel.effective(creature).power)
                while kernel.stack:kernel.pass_priority(kernel.priority)
                self.assertEqual(base+1,kernel.effective(creature).power);self.assertEqual((),state.mana_pool('A'))
