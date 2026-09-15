"""Last-known target information extends across supported public zones."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment


class PublicLastKnownTests(unittest.TestCase):
    def test_countered_x_spell_retains_stack_mana_value_through_checkpoint(self):
        xspell=CardProgram('x','X Spell',('Instant',),mana_value=1,colors=('U',),cast=CastSpec(CostSpec(ManaCost(0,('U',),1)),timing='instant'),spell_effects=(GainLife(1),))
        answer=CardProgram('answer','Answer',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),spell_targets=TargetSpec(Selector(Zone.STACK)),spell_effects=(Counter(),May((GainLife(TargetStat('mana_value')),))))
        programs=(xspell,answer);state=RulesState(('A','B'));x=state.add_card('x','x','A',Zone.HAND);response=state.add_card('answer','answer','B',Zone.HAND)
        kernel=RulesKernel(state,programs);kernel.open_window_for_scenario('A');state.add_mana('A',('U','C','C','C','C','C'))
        kernel.commit_action(kernel.quote_cast('x','A',x,x_value=5),Payment((('U',1),('C',5))))
        kernel.pass_priority('A')
        kernel.commit_action(kernel.quote_cast('answer','B',response,(state.current('x'),)),Payment())
        while not kernel.pending_choice:kernel.pass_priority(kernel.priority)
        q=kernel.pending_choice;self.assertEqual('may',q.kind)
        restored=RulesKernel.restore(kernel.snapshot(),programs)
        for k in (kernel,restored):k.answer(q.request_id,'B',[0])
        self.assertEqual(kernel.snapshot(),restored.snapshot());self.assertEqual(46,state.life('B'))
        self.assertEqual(1,kernel.effective(state.current('x')).mana_value)

    def test_public_card_target_retains_information_when_moved_to_hidden_zone(self):
        for zone in (Zone.GRAVEYARD,Zone.EXILE,Zone.COMMAND):
            with self.subTest(zone=zone):
                body=CardProgram('body','Body',('Creature',),power=3,toughness=4)
                spell=CardProgram('spell','Spell',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),spell_targets=TargetSpec(Selector(zone,types=('Creature',))),spell_effects=(Move('target',Zone.HAND),GainLife(TargetStat('power'))))
                programs=(body,spell);state=RulesState(('A','B'));target=state.add_card('body','body','B',zone);source=state.add_card('spell','spell','A',Zone.HAND)
                kernel=RulesKernel(state,programs);kernel.open_window_for_scenario('A')
                kernel.commit_action(kernel.quote_cast('cast','A',source,(target,)),Payment())
                while kernel.stack:kernel.pass_priority(kernel.priority)
                self.assertEqual(43,state.life('A'));self.assertEqual(Zone.HAND,state.get(state.current('body')).zone)

    def test_hidden_departures_do_not_create_public_last_known_entries(self):
        body=CardProgram('body','Secret',('Creature',),power=2,toughness=3)
        state=RulesState(('A','B'));ref=state.add_card('body','body','B',Zone.HAND)
        kernel=RulesKernel(state,(body,))
        kernel.execute_for_scenario(ref,'B',(Move('source',Zone.EXILE),))
        self.assertNotIn(ref,kernel.last_known)
        public=state.current('body');kernel.execute_for_scenario(public,'B',(Move('source',Zone.HAND),))
        self.assertEqual({public},set(kernel.last_known))
        self.assertEqual(3,kernel.last_known[public][1].toughness)
