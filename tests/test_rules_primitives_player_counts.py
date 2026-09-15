"""Live-player predicates compose with entry replacement and trigger lookback."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_characteristics import condition_holds,condition_selectors,evaluate,evaluate_exhaustive


class PlayerCountTests(unittest.TestCase):
    lands={'morphic-pool':('U','B'),'sea-of-clouds':('W','U'),'spire-garden':('R','G'),'vault-of-champions':('W','B')}
    def make(self,players=('A','B','C','D'),extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+tuple(extra)
        self.state=RulesState(players);self.kernel=RulesKernel(self.state,self.programs)

    def enter(self,key):
        ref=self.state.add_card('land','catalog:'+key,'A',Zone.HAND)
        self.kernel.execute_for_scenario(ref,'A',(Move('source',Zone.BATTLEFIELD),))
        return self.state.current('land')

    def test_all_four_lands_use_one_two_and_three_opponent_threshold(self):
        for key in self.lands:
            for count in (2,3,4):
                self.make(tuple('ABCD'[:count]));ref=self.enter(key)
                self.assertEqual(count==2,self.state.get(ref).tapped,(key,count))

    def test_departed_players_do_not_count_for_entry(self):
        self.make();self.kernel._depart_players(('C','D'));self.kernel.advance()
        ref=self.enter('morphic-pool');self.assertTrue(self.state.get(ref).tapped)

    def test_later_departure_does_not_retap_an_existing_land(self):
        self.make();ref=self.enter('sea-of-clouds');self.assertFalse(self.state.get(ref).tapped)
        self.kernel._depart_players(('C','D'));self.kernel.advance()
        self.assertFalse(self.state.get(ref).tapped)

    def test_each_mana_color_and_suspended_choice_restore(self):
        for key,colors in self.lands.items():
            for index,symbol in enumerate(colors):
                self.make();ref=self.enter(key);self.kernel.open_window_for_scenario('A')
                self.kernel.commit_action(self.kernel.quote_activation('mana','A',ref,'mana'),Payment())
                request=self.kernel.pending_choice;self.assertEqual('mana_choice',request.kind)
                restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
                for kernel in (self.kernel,restored):kernel.answer(request.request_id,'A',(index,))
                self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertEqual(((symbol,1),),self.state.mana_pool('A'))
                self.assertTrue(self.state.get(ref).tapped)

    def test_counts_compose_with_boolean_conditions_and_require_explicit_state(self):
        self.make();ref=self.state.add_card('source','catalog:forest','A',Zone.BATTLEFIELD);obj=self.state.get(ref)
        condition=AllConditions((PlayerCountCondition(3),NotCondition(PlayerCountCondition(5,'all')),PlayerCountCondition(1,'controller')))
        self.assertTrue(condition_holds(condition,obj,(),{},live_players=('A','B','C','D')))
        self.assertFalse(condition_holds(condition,obj,(),{},live_players=('A','B','C')))
        self.assertEqual((),tuple(condition_selectors(condition)))
        with self.assertRaises(RulesViolation):condition_holds(condition,obj,(),{})
        for c in (PlayerCountCondition(-1),PlayerCountCondition(True),PlayerCountCondition(1,'invalid')):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Sorcery',),spell_effects=(IfCondition(c,(Draw(),)),)))

    def test_continuous_player_count_updates_and_matches_exhaustive(self):
        buff=CardProgram('buff','Buff',('Creature',),power=2,toughness=2,continuous=(ContinuousProgram('boost',Selector(Zone.BATTLEFIELD), (ModifyPT(2,2),),subject='self',condition=PlayerCountCondition(3)),))
        self.make(extra=(buff,));ref=self.state.add_card('buff','buff','A',Zone.BATTLEFIELD)
        self.assertEqual(4,self.kernel.effective(ref).power)
        self.kernel._depart_players(('D',));self.kernel.advance();self.assertEqual(2,self.kernel.effective(ref).power)
        args={'live_players':self.state.live_players}
        self.assertEqual(evaluate(self.state.objects(),self.kernel.definitions,**args),evaluate_exhaustive(self.state.objects(),self.kernel.definitions,**args))

    def test_departure_leaves_trigger_uses_pre_event_player_count(self):
        watcher=CardProgram('watcher','Watcher',('Enchantment',),abilities=(AbilityProgram('leaves',EventPattern('zone_changed',from_zone=Zone.BATTLEFIELD,types=('Creature',)),(GainLife(5),),occurrence_condition=PlayerCountCondition(3)),))
        self.make(extra=(watcher,));self.state.add_card('watcher','watcher','A',Zone.BATTLEFIELD)
        self.state.add_card('departing','catalog:llanowar-elves','D',Zone.BATTLEFIELD)
        self.kernel._depart_players(('D',));self.kernel.advance();self.assertEqual(1,len(self.kernel.stack))
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual(45,self.state.life('A'))
