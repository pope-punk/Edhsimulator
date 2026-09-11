"""Type-qualified target restrictions and relative-life continuous effects."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class SourceTargetRestrictionTests(unittest.TestCase):
    def game(self,extra=(),zone=Zone.BATTLEFIELD,starting=40):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+tuple(extra)
        self.state=RulesState(('A','B'),starting_life=starting)
        self.ref=self.state.add_card('elenda','catalog:elenda-saint-of-dusk','A',zone)
        self.other=self.state.add_card('other','catalog:elvish-mystic','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)
    def frame(self,ref,actor='B'):return {'source':self.state.get(ref).to_json(),'controller':actor}
    def legal(self,frame,kernel=None):
        kernel=kernel or self.kernel
        return {o.ref for o in kernel._target_query(Selector(Zone.BATTLEFIELD,types=('Creature',)),frame)}
    def spell(self,kind):
        return CardProgram(kind,kind,(kind,),cast=CastSpec(CostSpec(),timing='instant'),spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',))),spell_effects=(Damage('target',1),))

    def test_paid_cast_and_relative_thresholds_do_not_buff_other_creatures(self):
        self.game(zone=Zone.HAND,starting={'A':20,'B':40})
        self.state.add_mana('A',('C','C','W','B'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.ref),Payment((('C',2),('W',1),('B',1))))
        self.drain();self.ref=self.state.current('elenda');self.assertFalse(self.state.mana_pool('A'))
        for life,power,menace in ((20,4,False),(21,5,True),(29,5,True),(30,10,True),(19,4,False)):
            delta=life-self.state.life('A')
            if delta>=0:self.state.gain_life('A',delta)
            else:self.state.lose_life_batch(('A',),-delta)
            view=self.kernel.effective(self.ref);self.assertEqual((power,power),(view.power,view.toughness))
            self.assertEqual(menace,'menace' in view.keywords);self.assertIn('lifelink',view.keywords)
            self.assertEqual(1,self.kernel.effective(self.other).power)

    def test_announcement_filters_enemy_instants_but_not_own_or_sorceries(self):
        self.game((self.spell('Instant'),self.spell('Sorcery')))
        instant=self.state.add_card('instant','Instant','B',Zone.HAND);sorcery=self.state.add_card('sorcery','Sorcery','B',Zone.HAND)
        before=self.kernel.snapshot();self.assertNotIn(self.ref,self.legal(self.frame(instant)))
        self.assertIn(self.ref,self.legal(self.frame(instant,'A')));self.assertIn(self.ref,self.legal(self.frame(sorcery)))
        self.assertEqual(before,self.kernel.snapshot())
        self.kernel.open_window_for_scenario('B');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','B',instant,(self.ref,))
        self.assertEqual(before,self.kernel.snapshot());self.kernel.commit_action(self.kernel.quote_cast('good','B',sorcery,(self.ref,)),Payment())
        self.drain();self.assertEqual(1,self.state.get(self.ref).damage_marked)

    def test_control_change_rechecks_at_resolution_and_replay_matches(self):
        self.game((self.spell('Instant'),));spell=self.state.add_card('spell','Instant','A',Zone.HAND)
        self.kernel.commit_action(self.kernel.quote_cast('own','A',spell,(self.ref,)),Payment())
        self.state.change_control(self.ref,'B')
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.drain();self.drain(replay.kernel);self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot())
        self.assertEqual(0,self.state.get(self.ref).damage_marked)

    def test_ability_uses_departed_instant_source_not_new_incarnation(self):
        activation=ActivatedProgram('channel',CostSpec(zone_costs=(ZoneCost('discard','discard'),)),(Damage('target',1),),targets=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',))),zone=Zone.HAND)
        instant=CardProgram('channel','Channel',('Instant',),activated=(activation,))
        self.game((instant,));source=self.state.add_card('source','channel','A',Zone.HAND)
        self.kernel.commit_action(self.kernel.quote_activation('channel','A',source,'channel',(self.ref,)),Payment())
        self.state.change_control(self.ref,'B')
        # Returning the physical card does not change the old activation's source.
        self.state.move((ZoneMove(self.state.current('source'),Zone.HAND),),'scenario_return')
        self.drain();self.assertEqual(0,self.state.get(self.ref).damage_marked)

    def test_current_and_last_known_copied_source_types_and_nontargeted_selection(self):
        instant=self.spell('Instant');self.game((instant,))
        source=self.state.add_card('source','catalog:forest','B',Zone.HAND)
        self.state.move((ZoneMove(source,Zone.BATTLEFIELD,'B',copied_definition='Instant'),),'synthetic_copy')
        source=self.state.current('source');frame=self.frame(source)
        self.assertNotIn(self.ref,self.legal(frame));self.assertIn(self.ref,{o.ref for o in self.kernel._query(Selector(Zone.BATTLEFIELD),frame)})
        before=self.state.objects(Zone.BATTLEFIELD);views=self.kernel.characteristics()
        events=self.state.move((ZoneMove(source,Zone.GRAVEYARD),),'scenario_departure')
        self.kernel._collect(events,before,self.state.objects(Zone.BATTLEFIELD),views)
        self.assertNotIn(self.ref,self.legal(frame))
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs);self.assertNotIn(self.ref,self.legal(frame,restored))
        self.assertIn(self.ref,self.legal(self.frame(self.state.current('source'))))

    def test_life_loss_can_make_existing_damage_lethal(self):
        self.game();self.state.gain_life('A',10)
        self.state.damage_batch(({'source':self.state.get(self.other),'target':self.ref,'amount':6},));self.kernel.advance()
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.ref).zone)
        self.kernel.execute_for_scenario(self.other,'A',(LoseLife('controller',1),));self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('elenda')).zone)

    def test_simultaneous_lifelink_changes_toughness_before_lethal_check(self):
        self.game()
        self.kernel._deal_damage(((self.state.get(self.ref),'B',1),(self.state.get(self.other),self.ref,4)))
        self.kernel.advance();self.assertEqual(41,self.state.life('A'))
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.ref).zone)
        self.assertEqual(5,self.kernel.effective(self.ref).toughness)

    def test_copied_elenda_inherits_restriction_and_uses_current_controller_life(self):
        self.game((self.spell('Instant'),),starting={'A':20,'B':40})
        copy=self.state.add_card('copy','catalog:forest','B',Zone.HAND)
        self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,'B',copied_definition='catalog:elenda-saint-of-dusk'),),'synthetic_copy')
        copy=self.state.current('copy');self.state.gain_life('B',10)
        self.assertEqual(10,self.kernel.effective(copy).power)
        instant=self.state.add_card('spell','Instant','A',Zone.HAND)
        self.assertNotIn(copy,self.legal(self.frame(instant,'A')))
        self.state.change_control(copy,'A');self.assertEqual(4,self.kernel.effective(copy).power)
        self.assertIn(copy,self.legal(self.frame(instant,'A')))
        self.state.phase(copy,True);self.assertNotIn(copy,self.legal(self.frame(instant,'A')))

    def test_type_union_and_validation_preserve_unqualified_restrictions(self):
        self.game((self.spell('Instant'),self.spell('Sorcery')))
        for restriction in (TargetRestriction(),TargetRestriction(True),TargetRestriction(True,('Instant','Sorcery'))):
            self.assertEqual(restriction,decode(encode(restriction)))
            guard=CardProgram('guard','Guard',('Creature',),power=1,toughness=1,target_restrictions=(restriction,))
            validate(guard);self.game((guard,self.spell('Sorcery')))
            guarded=self.state.add_card('guard','guard','A',Zone.BATTLEFIELD)
            source=self.state.add_card('spell','Sorcery','B',Zone.HAND)
            self.assertNotIn(guarded,self.legal(self.frame(source)))
            self.assertEqual(restriction.opponents_only,guarded in self.legal(self.frame(source,'A')))
        for bad in (TargetRestriction(source_types=['Instant']),TargetRestriction(source_types=('instant',)),TargetRestriction(source_types=('Instant','Instant')),TargetRestriction(opponents_only=1)):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Artifact',),target_restrictions=(bad,)))

if __name__=='__main__':unittest.main()
