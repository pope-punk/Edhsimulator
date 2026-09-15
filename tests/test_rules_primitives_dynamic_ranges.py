"""Resolution-time numeric selections compose with retained source quantities."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class DynamicRangeTests(unittest.TestCase):
    def game(self):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+tuple(
            CardProgram('body'+str(i),'Body '+str(i),('Creature',),mana_value=i,power=2,toughness=2) for i in range(3))+(CardProgram('safe','Safe',('Artifact',),mana_value=1,keywords=('indestructible',)),)
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('blast','catalog:blast-zone','A',Zone.HAND)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.enter(self.ref);self.ref=self.state.current('blast')
        self.kernel.open_window_for_scenario('A')

    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)

    def test_printed_entry_colorless_mana_and_xx_charge_cost(self):
        self.game();self.assertEqual((('charge',1),),self.state.get(self.ref).counters)
        self.kernel.commit_action(self.kernel.quote_activation('mana','A',self.ref,'mana'),Payment())
        self.assertEqual((('C',1),),self.state.mana_pool('A'))
        self.state.set_tapped_batch((self.ref,),False)
        self.state.add_mana('A',('C',)*5)
        quote=self.kernel.quote_activation('charge','A',self.ref,'charge',x_value=3)
        self.kernel.commit_action(quote,Payment((('C',6),)));self.drain()
        self.assertEqual((('charge',4),),self.state.get(self.ref).counters);self.assertEqual((),self.state.mana_pool('A'))

    def test_destroy_matches_retained_count_all_controllers_and_preserves_indestructible(self):
        self.game()
        for owner in ('A','B'):
            for i in range(3):self.state.add_card(owner+str(i),'body'+str(i),owner,Zone.BATTLEFIELD)
        self.state.add_card('safe','safe','B',Zone.BATTLEFIELD)
        self.state.add_card('land','catalog:forest','B',Zone.BATTLEFIELD)
        self.state.add_mana('A',('C',)*3)
        self.kernel.commit_action(self.kernel.quote_activation('destroy','A',self.ref,'destroy'),Payment((('C',3),)))
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('blast')).zone)
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        for kernel in (self.kernel,replay.kernel):self.drain(kernel)
        self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot())
        for owner in ('A','B'):
            for i in range(3):self.assertEqual(Zone.GRAVEYARD if i==1 else Zone.BATTLEFIELD,self.state.get(self.state.current(owner+str(i))).zone)
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('safe')).zone)
        moved=[e for e in self.state.events if e.before.ref.card_id in ('A1','B1')]
        self.assertEqual(1,len({e.batch for e in moved}))

    def test_select_prompt_freezes_dynamic_range_and_restores(self):
        self.game();self.state.add_card('one','body1','A',Zone.BATTLEFIELD);self.state.add_card('two','body2','A',Zone.BATTLEFIELD)
        self.state.add_card('other-one','body1','B',Zone.BATTLEFIELD)
        bound=SourceCounter('charge')
        effect=Select(Selector(Zone.BATTLEFIELD,types=('Creature',),characteristics=(CharacteristicRange('mana_value',bound,bound),)),1,1,(GainLife(3),))
        q=self.kernel.execute_for_scenario(self.ref,'A',(effect,));self.assertEqual({'one','other-one'},{o.ref.card_id for o in q.options})
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        for kernel in (self.kernel,restored):kernel.answer(q.request_id,'A',[0])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertEqual(43,self.state.life('A'))

    def test_generic_range_evaluates_after_preceding_effect_and_signed_literals_work(self):
        self.game();self.state.add_card('one','body1','A',Zone.BATTLEFIELD);self.state.add_card('two','body2','A',Zone.BATTLEFIELD)
        selector=Selector(Zone.BATTLEFIELD,types=('Creature',),characteristics=(CharacteristicRange('mana_value',-1,SourceCounter('charge')),))
        self.kernel.execute_for_scenario(self.ref,'A',(AddCounters('source','charge',1),SelectAll(selector,(GainLife(SelectedCount()),))))
        self.assertEqual(42,self.state.life('A'))

    def test_x_bound_is_bound_to_announced_action(self):
        spell=validate(CardProgram('spell','Spell',('Sorcery',),cast=CastSpec(CostSpec(ManaCost(x_symbols=1))),spell_effects=(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',),characteristics=(CharacteristicRange('mana_value',maximum=ChosenX()),)),(GainLife(SelectedCount()),)),)))
        self.game();self.programs+=(spell,);self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
        ref=self.state.add_card('spell','spell','A',Zone.HAND)
        for i in range(3):self.state.add_card('body'+str(i),'body'+str(i),'B',Zone.BATTLEFIELD)
        self.state.add_mana('A',('C',));self.kernel.commit_action(self.kernel.quote_cast('cast','A',ref,x_value=1),Payment((('C',1),)));self.drain()
        self.assertEqual(42,self.state.life('A'))

    def test_validation_rejects_unbound_and_wrong_timing_expressions(self):
        dynamic=Selector(Zone.BATTLEFIELD,characteristics=(CharacteristicRange('mana_value',maximum=SourceCounter('charge')),))
        validate(CardProgram('targeted','Targeted',('Instant',),spell_targets=TargetSpec(dynamic)))
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Artifact',),continuous=(ContinuousProgram('bad',dynamic,(ModifyPT(1,1),)),)))
        for value in (ChosenX(),TargetStat(),True):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Sorcery',),spell_effects=(SelectAll(Selector(Zone.BATTLEFIELD,characteristics=(CharacteristicRange('mana_value',maximum=value),)),()),)))

    def test_signed_source_power_bound_excludes_zero_mana_value(self):
        self.game();source=self.state.add_card('source','body0','A',Zone.BATTLEFIELD)
        self.state.add_card('zero','body0','B',Zone.BATTLEFIELD)
        selector=Selector(Zone.BATTLEFIELD,types=('Creature',),characteristics=(CharacteristicRange('mana_value',maximum=SourceStat('power',allow_negative=True)),))
        self.kernel.execute_for_scenario(source,'A',(UntilEndOfTurn('source',(SetPT(-2,2),)),SelectAll(selector,(GainLife(SelectedCount()),))))
        self.assertEqual(40,self.state.life('A'))
        self.assertEqual(0,self.kernel._quantity(SourceStat('power'),{'source':self.state.get(source).to_json()}))

    def test_signed_source_bound_retains_departed_power_through_checkpoint(self):
        self.game();source=self.state.add_card('source','body0','A',Zone.BATTLEFIELD)
        self.state.add_card('zero','body0','B',Zone.BATTLEFIELD)
        selector=Selector(Zone.BATTLEFIELD,types=('Creature',),characteristics=(CharacteristicRange('mana_value',maximum=SourceStat('power',allow_negative=True)),))
        q=self.kernel.execute_for_scenario(source,'A',(UntilEndOfTurn('source',(SetPT(-2,2),)),Destroy('source'),May((SelectAll(selector,(GainLife(SelectedCount()),)),))))
        self.assertEqual('may',q.kind);restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        for kernel in (self.kernel,restored):kernel.answer(q.request_id,'A',[0])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertEqual(40,self.state.life('A'))

    def test_signed_source_statistic_is_scoped_to_bounds_and_boolean_validated(self):
        signed=SourceStat('power',allow_negative=True)
        self.assertEqual(signed,decode(encode(signed)))
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),spell_effects=(GainLife(signed),)))
        for flag in (1,'yes',None):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),spell_effects=(SelectAll(Selector(Zone.BATTLEFIELD,characteristics=(CharacteristicRange('power',maximum=SourceStat('power',allow_negative=flag)),)),()),)))
