"""Independent trigger target clauses retain legality and placement multiplicity."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_adapter import RulesActorAdapter

class TargetGroupTests(unittest.TestCase):
    def spec(self,minimum=0):
        return TargetSpec(minimum=2*minimum,maximum=2,groups=(
            TargetGroup('land',TargetSpec(Selector(Zone.BATTLEFIELD,types=('Land',)),minimum,1)),
            TargetGroup('creature',TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',)),minimum,1))))
    def game(self,minimum=0,bodies=True):
        self.watcher=CardProgram('watch','Watcher',('Enchantment',),abilities=(AbilityProgram('groups',
            EventPattern('step_began',step='upkeep'),(AddCounters('target','everything',1),GainLife(1)),targets=self.spec(minimum)),))
        self.programs=(self.watcher,CardProgram('land','Land',('Land',)),CardProgram('creature','Creature',('Creature',),power=2,toughness=2),
            CardProgram('both','Both',('Land','Creature'),power=2,toughness=2),
            CardProgram('strip','Strip',('Enchantment',),continuous=(ContinuousProgram('strip',Selector(Zone.BATTLEFIELD,types=('Land',)),(ChangeTypes((),('Creature',)),)),)))
        self.state=RulesState(('A','B'));self.source=self.state.add_card('watch','watch','A',Zone.BATTLEFIELD)
        if bodies:
            self.land=self.state.add_card('land','land','A',Zone.BATTLEFIELD)
            self.creature=self.state.add_card('creature','creature','B',Zone.BATTLEFIELD)
            self.both=self.state.add_card('both','both','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
        self.kernel._begin_phase('upkeep');self.kernel.advance()
    def choose(self,pairs,kernel=None):
        kernel=kernel or self.kernel;q=kernel.pending_choice
        indexes=[next(i for i,o in enumerate(q.options) if o.group==group and o.ref==ref) for group,ref in pairs]
        kernel.answer(q.request_id,q.actor,indexes)
    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack:kernel.pass_priority(kernel.priority)
    def test_one_batched_menu_enforces_each_clause(self):
        self.game();q=self.kernel.pending_choice
        self.assertEqual((('land',0,1),('creature',0,1)),q.group_bounds)
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.choose([('land',self.land),('land',self.both)])
        self.assertEqual(before,self.kernel.snapshot())
        self.choose([('land',self.land),('creature',self.creature)]);self.drain()
        for ref in (self.land,self.creature):self.assertEqual(1,dict(self.state.get(ref).counters)['everything'])
    def test_same_physical_target_gets_two_counters_in_one_event(self):
        self.game();self.choose([('land',self.both),('creature',self.both)]);self.drain()
        self.assertEqual(2,dict(self.state.get(self.both).counters)['everything'])
        events=[e for e in self.kernel.semantic_events if e['kind']=='counters_added']
        self.assertEqual(1,len(events));self.assertEqual(2,events[0]['amount'])
    def test_one_clause_becomes_illegal_without_invalidating_other(self):
        self.game();self.choose([('land',self.both),('creature',self.both)])
        # Remove the creature type before resolution: that clause is illegal,
        # even though its physical target remains legal for the land clause.
        self.state.add_card('strip','strip','A',Zone.BATTLEFIELD)
        self.drain();self.assertEqual(1,dict(self.state.get(self.both).counters)['everything'])
        self.assertEqual(41,self.state.life('A'))
    def test_all_chosen_targets_illegal_fizzles_but_zero_chosen_resolves(self):
        self.game();self.choose([('land',self.land)]);self.state.phase(self.land,True);self.drain()
        self.assertEqual(40,self.state.life('A'))
        self.game();self.choose([]);self.drain();self.assertEqual(41,self.state.life('A'))
    def test_empty_optional_clauses_need_no_prompt_required_clause_unplaceable(self):
        self.game(bodies=False);self.assertIsNone(self.kernel.pending_choice);self.drain();self.assertEqual(41,self.state.life('A'))
        self.game(minimum=1)
        # Start a separate fixture with a land-only domain and a required empty
        # creature clause; total menu size alone must not admit the trigger.
        state=RulesState(('A','B'));state.add_card('w','watch','A',Zone.BATTLEFIELD)
        for i in range(3):state.add_card(str(i),'land','A',Zone.BATTLEFIELD)
        k=RulesKernel(state,self.programs);k.open_window_for_scenario('A');k._begin_phase('upkeep');k.advance()
        self.assertIsNone(k.pending_choice);self.assertFalse(k.stack)
        self.assertTrue(any(e['kind']=='trigger_unplaceable' for e in k.semantic_events))
    def test_pending_choice_and_placed_groups_replay_exactly(self):
        self.game();a=RulesActorAdapter(self.kernel);b=RulesActorAdapter.replay(a.archive(),self.programs)
        q=self.kernel.pending_choice;indexes=[i for i,o in enumerate(q.options) if o.ref==self.both]
        cmd={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':indexes}
        a.submit('A',cmd);b.submit('A',cmd);self.assertEqual(a.archive(),b.archive())
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.drain();self.drain(b.kernel);self.drain(restored)
        self.assertEqual(self.kernel.snapshot(),b.kernel.snapshot());self.assertEqual(self.kernel.snapshot(),restored.snapshot())
    def test_named_clause_bindings_do_not_apply_other_clauses_effects(self):
        self.game()
        watcher=replace(self.watcher,abilities=(replace(self.watcher.abilities[0],effects=(
            AddCounters('target:land','land-mark',1),AddCounters('target:creature','creature-mark',3))),))
        programs=(watcher,)+self.programs[1:]
        state=RulesState(('A','B'));state.add_card('w','watch','A',Zone.BATTLEFIELD)
        land=state.add_card('l','land','A',Zone.BATTLEFIELD);body=state.add_card('c','creature','B',Zone.BATTLEFIELD)
        k=RulesKernel(state,programs);k.open_window_for_scenario('A');k._begin_phase('upkeep');k.advance()
        self.choose([('land',land),('creature',body)],k);self.drain(k)
        self.assertEqual({'land-mark':1},dict(state.get(land).counters))
        self.assertEqual({'creature-mark':3},dict(state.get(body).counters))

    def test_repeated_physical_target_moves_once(self):
        self.game()
        watcher=replace(self.watcher,abilities=(replace(self.watcher.abilities[0],effects=(Move('target',Zone.HAND),)),))
        state=RulesState(('A','B'));state.add_card('w','watch','A',Zone.BATTLEFIELD)
        both=state.add_card('b','both','B',Zone.BATTLEFIELD)
        k=RulesKernel(state,(watcher,)+self.programs[1:]);k.open_window_for_scenario('A');k._begin_phase('upkeep');k.advance()
        self.choose([('land',both),('creature',both)],k);self.drain(k)
        self.assertEqual(Zone.HAND,state.get(state.current('b')).zone)
        self.assertEqual(both.incarnation+1,state.current('b').incarnation)

    def test_delayed_effect_captures_named_clause_after_target_revalidation(self):
        self.game()
        delayed=DelayedTrigger(EventPattern('zone_changed',from_zone=Zone.BATTLEFIELD,subject='self'),
            (AddCounters('target:land','later',2),))
        watcher=replace(self.watcher,abilities=(replace(self.watcher.abilities[0],effects=(delayed,)),))
        programs=(watcher,)+self.programs[1:];state=RulesState(('A','B'))
        source=state.add_card('w','watch','A',Zone.BATTLEFIELD);land=state.add_card('l','land','A',Zone.BATTLEFIELD)
        k=RulesKernel(state,programs);k.open_window_for_scenario('A');k._begin_phase('upkeep');k.advance()
        self.choose([('land',land)],k);self.drain(k)
        self.assertEqual([land.to_json()],k.delayed_triggers[0]['bindings']['target:land'])
        restored=RulesKernel.restore(k.snapshot(),programs)
        for kernel in (k,restored):
            before=kernel.state.objects(Zone.BATTLEFIELD);views=kernel.characteristics()
            events=kernel.state.move((ZoneMove(source,Zone.GRAVEYARD),),'scenario')
            kernel._collect(events,before,kernel.state.objects(Zone.BATTLEFIELD),views);kernel.advance();self.drain(kernel)
        self.assertEqual(2,dict(state.get(land).counters)['later']);self.assertEqual(k.snapshot(),restored.snapshot())

    def test_closed_validation_and_codec_reject_unsupported_announcement_paths(self):
        self.game();spec=self.spec();self.assertEqual(spec,decode(encode(spec)))
        bads=(replace(spec,minimum=1),replace(spec,groups=list(spec.groups)),replace(spec,groups=(spec.groups[0],)*2),
            replace(spec,selector=Selector(Zone.BATTLEFIELD)),replace(spec,groups=(TargetGroup('bad',TargetSpec(players='all',minimum=0,maximum=2)),)),
            replace(spec,groups=(TargetGroup('nested',spec),)))
        for bad in bads:
            with self.assertRaises(RulesViolation):validate(replace(self.watcher,abilities=(replace(self.watcher.abilities[0],targets=bad),)))
        with self.assertRaises(RulesViolation):validate(CardProgram('s','Spell',('Instant',),spell_targets=spec,spell_effects=(AddCounters('target','test',1),)))
        with self.assertRaises(RulesViolation):validate(CardProgram('a','Activation',('Artifact',),activated=(ActivatedProgram('use',CostSpec(),(AddCounters('target','test',1),),targets=spec),)))

if __name__=='__main__':unittest.main()
