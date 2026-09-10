"""Dynamic target bounds use current values and exact-source last known data."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class DynamicTargetTests(unittest.TestCase):
    def game(self,trigger=False,power=3):
        targets=TargetSpec(Selector(Zone.GRAVEYARD,types=('Creature',),relation='owned',characteristics=(CharacteristicRange('mana_value',maximum=SourceStat('power',allow_negative=True)),)))
        effect=(Move('target',Zone.BATTLEFIELD),)
        program=validate(CardProgram('source','Source',('Creature',),power=power,toughness=5,
            activated=() if trigger else (ActivatedProgram('return',CostSpec(),effect,targets=targets),),
            abilities=(AbilityProgram('dies',EventPattern('zone_changed',subject='self',from_zone=Zone.BATTLEFIELD,to_zone=Zone.GRAVEYARD),effect,targets=targets),) if trigger else ()))
        self.programs=(program,)+tuple(CardProgram('body'+str(i),'Body '+str(i),('Creature',),mana_value=i,power=1,toughness=1) for i in (0,2,4))
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('source','source','A',Zone.BATTLEFIELD)
        self.targets={i:self.state.add_card('body'+str(i),'body'+str(i),'A',Zone.GRAVEYARD) for i in (0,2,4)}
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)

    def activate(self,target):
        return self.kernel.commit_action(self.kernel.quote_activation('return','A',self.ref,'return',(target,)),Payment())

    def test_quote_checks_bound_and_resolution_rechecks_current_source_power(self):
        self.game();before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.activate(self.targets[4])
        self.assertEqual(before,self.kernel.snapshot());self.activate(self.targets[2])
        self.state.add_counters(self.ref,'-1/-1',2)
        self.drain();self.assertEqual(Zone.GRAVEYARD,self.state.get(self.targets[2]).zone)

    def test_death_target_menu_uses_modified_last_known_power_through_replay(self):
        self.game(trigger=True)
        self.kernel.execute_for_scenario(self.ref,'A',(UntilEndOfTurn('source',(ModifyPT(2,0),)),Destroy('source')))
        q=self.kernel.pending_choice;self.assertEqual('trigger_targets',q.kind)
        self.assertIn(self.targets[4],[o.ref for o in q.options])
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        command={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[next(i for i,o in enumerate(q.options) if o.ref==self.targets[4])]}
        for item in (adapter,replay):item.submit('A',command);self.drain(item.kernel)
        self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot())
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('body4')).zone)

    def test_departed_activated_source_uses_exact_lki_despite_new_incarnation(self):
        self.game();self.activate(self.targets[2])
        before=self.state.objects(Zone.BATTLEFIELD);views=self.kernel.characteristics()
        events=self.state.move((ZoneMove(self.ref,Zone.GRAVEYARD),),'fixture-death')
        self.kernel._collect(events,before,self.state.objects(Zone.BATTLEFIELD),views)
        self.state.move((ZoneMove(self.state.current('source'),Zone.BATTLEFIELD),),'fixture-return')
        self.state.add_counters(self.state.current('source'),'-1/-1',2)
        self.drain();self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('body2')).zone)

    def test_negative_source_power_does_not_admit_zero_mana_value_target(self):
        self.game(power=-1);before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.activate(self.targets[0])
        self.assertEqual(before,self.kernel.snapshot())

    def test_target_bound_rejects_unbound_x_and_result_quantities(self):
        for value in (ChosenX(),SelectedCount(),TargetStat(),EventAmount()):
            spec=TargetSpec(Selector(Zone.BATTLEFIELD,characteristics=(CharacteristicRange('mana_value',maximum=value),)))
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),cast=CastSpec(CostSpec(ManaCost(x_symbols=1))),spell_targets=spec))

    def test_copied_death_trigger_selects_only_copy_controllers_graveyard(self):
        self.game(trigger=True)
        ref=self.state.add_card('copy','body0','B',Zone.HAND)
        self.state.move((ZoneMove(ref,Zone.BATTLEFIELD,'B',copied_definition='source'),),'fixture-copy')
        target=self.state.add_card('btarget','body2','B',Zone.GRAVEYARD)
        self.kernel.execute_for_scenario(self.state.current('copy'),'B',(Destroy('source'),))
        q=self.kernel.pending_choice;self.assertEqual('B',q.actor)
        self.assertIn(target,[o.ref for o in q.options]);self.assertNotIn(self.targets[2],[o.ref for o in q.options])
        self.kernel.answer(q.request_id,'B',[next(i for i,o in enumerate(q.options) if o.ref==target)])
        self.drain();self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('btarget')).zone)
