"""Life-loss results and life-gain trigger amounts are bound to their actual occurrence."""
import unittest
from edh_gauntlet.rules_program import (CardProgram,CastSpec,CostSpec,TargetSpec,WithLifeLost,LoseLife,LifeLost,EventAmount,
    GainLife,May,AbilityProgram,EventPattern,validate)
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment


class LifeResultTests(unittest.TestCase):
    def setUp(self):
        self.programs=tuple(row['program'] for row in load_reviewed().values());self.state=RulesState(('A','B','C'))
        self.kernel=RulesKernel(self.state,self.programs)

    def add(self,key,zone=Zone.BATTLEFIELD,actor='A',name=None):return self.state.add_card(name or key,'catalog:'+key,actor,zone)

    def drain(self):
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)
        return self.kernel.pending_choice

    def answer(self,indexes):
        r=self.kernel.pending_choice;self.kernel.answer(r.request_id,r.actor,indexes);return self.drain()

    def test_exsanguinate_and_debt_gain_the_actual_total_lost(self):
        for key,symbols,mana,loss in (('exsanguinate',tuple('CCCBB'),(('C',3),('B',2)),3),
                ('debt-to-the-deathless',tuple('CCCWWBB'),(('C',3),('W',2),('B',2)),6)):
            self.setUp();source=self.add(key,Zone.HAND);self.kernel.open_window_for_scenario('A');self.state.add_mana('A',symbols)
            self.kernel.commit_action(self.kernel.quote_cast('cast','A',source,x_value=3),Payment(mana));self.drain()
            self.assertEqual((40+loss*2,40-loss,40-loss),tuple(self.state.life(p) for p in self.state.players))
            self.assertEqual([loss*2],[e['amount'] for e in self.kernel.semantic_events if e['kind']=='life_gained'])

    def test_zero_loss_produces_no_gain_trigger(self):
        self.add('defiant-bloodlord');source=self.add('exsanguinate',Zone.HAND)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('B','B'))
        self.kernel.commit_action(self.kernel.quote_cast('zero','A',source),Payment((('B',2),)));self.drain()
        self.assertIsNone(self.kernel.pending_choice);self.assertFalse(self.kernel.stack)
        self.assertFalse(any(e['kind'] in ('life_lost','life_gained') for e in self.kernel.semantic_events))

    def test_nested_life_results_restore_without_overwriting_outer_value(self):
        program=CardProgram('nested','Nested',('Sorcery',),cast=CastSpec(CostSpec()),spell_effects=(
            WithLifeLost('opponents',3,(WithLifeLost('controller',1,(GainLife(LifeLost()),)),May((GainLife(LifeLost()),)))),))
        source=self.state.add_card('source','nested','A',Zone.HAND);programs=(*self.programs,program);self.kernel=RulesKernel(self.state,programs)
        self.kernel.stage_spell_for_scenario(source,'A');request=self.drain()
        self.assertEqual(40,self.state.life('A'));restored=RulesKernel.restore(self.kernel.snapshot(),programs)
        self.kernel.answer(request.request_id,'A',[0]);restored.answer(request.request_id,'A',[0])
        self.assertEqual(46,self.state.life('A'));self.assertEqual(self.kernel.snapshot(),restored.snapshot())

    def test_bloodlord_captures_each_gain_amount_and_target_choice_survives_checkpoint(self):
        source=self.add('defiant-bloodlord')
        self.kernel.execute_for_scenario(source,'A',(GainLife(2),GainLife(5)))
        amounts=[]
        while self.kernel.pending_choice:
            request=self.kernel.pending_choice
            indexes=list(range(len(request.options))) if request.kind!='trigger_targets' else [0]
            self.answer(indexes)
        amounts=[e['amount'] for e in self.kernel.semantic_events if e['kind']=='life_lost']
        self.assertEqual([5,2],amounts);self.assertEqual(33,self.state.life('B'))
        self.kernel.execute_for_scenario(source,'A',(GainLife(4),));request=self.kernel.pending_choice
        self.assertIn('amount 4',request.prompt)
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.kernel.answer(request.request_id,'A',[1]);restored.answer(request.request_id,'A',[1])
        from edh_gauntlet.rules_adapter import RulesActorAdapter
        self.assertEqual(4,RulesActorAdapter(self.kernel).packet('B')['stack'][0]['event_amount'])
        while self.kernel.stack:
            actor=self.kernel.priority;self.kernel.pass_priority(actor);restored.pass_priority(actor)
        self.assertEqual(36,self.state.life('C'));self.assertEqual(self.kernel.snapshot(),restored.snapshot())

    def test_lifelink_sources_supply_separate_captured_gain_amounts(self):
        self.add('defiant-bloodlord');one=self.add('arvad-the-cursed');two=self.add('arvad-the-cursed',name='second')
        # Exercise the damage batch directly before SBA removes duplicate legends.
        self.kernel._deal_damage([(self.state.get(one),'B',2),(self.state.get(one),'C',3),(self.state.get(two),'B',4)])
        self.assertEqual([5,4],[t['values']['event_amount'] for t in self.kernel.pending_triggers])

    def test_compiler_rejects_unbound_numeric_results(self):
        for value in (LifeLost(),EventAmount()):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),spell_effects=(GainLife(value),)))
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Enchantment',),abilities=(AbilityProgram('upkeep',EventPattern('step_began',step='upkeep'),(GainLife(EventAmount()),)),)))
