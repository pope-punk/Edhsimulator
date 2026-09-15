"""Player events use copied subscriptions and preserve occurrence boundaries."""
import unittest
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove
from edh_gauntlet.rules_program import CardProgram,AbilityProgram,EventPattern,GainLife,Draw,SearchLibrary,Selector
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed


class PlayerEventTests(unittest.TestCase):
    def setUp(self):
        rows=load_reviewed();self.programs=[row['program'] for row in rows.values()]
        self.programs.extend((CardProgram('source','Source',('Creature',),power=2,toughness=2,keywords=('lifelink',)),
                              CardProgram('copy','Copy',('Creature',),power=0,toughness=0)))
        self.state=RulesState(('A','B','C'))
        self.source=self.state.add_card('source','source','A',Zone.BATTLEFIELD)
        self.pridemate=self.state.add_card('pridemate',rows['ajani-s-pridemate']['program'].definition_id,'A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs)

    def drain(self):
        for _ in range(30):
            if self.kernel.pending_choice:
                request=self.kernel.pending_choice
                self.kernel.answer(request.request_id,request.actor,list(range(len(request.options))))
            elif self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
            else:return
        self.fail('Stack did not drain')

    def test_authored_pridemate_triggers_once_for_a_gain_not_once_per_life(self):
        self.kernel.execute_for_scenario(self.source,'A',(GainLife(5),));self.drain()
        self.assertEqual(1,dict(self.state.get(self.pridemate).counters)['+1/+1'])
        self.assertEqual(45,self.state.life('A'))

    def test_zero_life_and_another_players_gain_do_not_trigger(self):
        self.kernel.execute_for_scenario(self.source,'A',(GainLife(0),))
        self.kernel.execute_for_scenario(self.source,'B',(GainLife(5),))
        self.assertFalse(self.kernel.stack);self.assertEqual((),self.state.get(self.pridemate).counters)

    def test_copied_creature_inherits_player_event_subscription(self):
        ref=self.state.add_card('copy','copy','A',Zone.HAND)
        self.state.move((ZoneMove(ref,Zone.BATTLEFIELD,copied_definition=self.state.get(self.pridemate).definition),),'copy-fixture')
        copy=self.state.current('copy')
        self.kernel.execute_for_scenario(self.source,'A',(GainLife(1),));self.drain()
        self.assertEqual(1,dict(self.state.get(copy).counters)['+1/+1'])

    def test_lifelink_splits_gains_by_source_but_not_by_damage_recipient(self):
        other=self.state.add_card('other','source','A',Zone.BATTLEFIELD)
        self.kernel._deal_damage([(self.state.get(self.source),'B',2),(self.state.get(self.source),'C',1),
                                  (self.state.get(other),'B',3)])
        self.assertEqual(2,len(self.kernel.pending_triggers))
        self.assertEqual([3,3],[e['amount'] for e in self.kernel.semantic_events if e['kind']=='life_gained'])
        self.kernel.advance();self.drain()
        self.assertEqual(2,dict(self.state.get(self.pridemate).counters)['+1/+1'])
        self.assertEqual(46,self.state.life('A'))

    def test_each_draw_is_a_separate_player_event(self):
        watcher=CardProgram('watch','Watcher',('Enchantment',),abilities=(AbilityProgram('draw-life',EventPattern('card_drawn',controller_only=True),(GainLife(1),)),))
        self.programs.append(watcher);self.state.add_card('watch','watch','A',Zone.BATTLEFIELD)
        for i in range(3):self.state.add_card('draw'+str(i),'source','A',Zone.LIBRARY)
        self.kernel=RulesKernel(self.state,self.programs)
        self.kernel.execute_for_scenario(self.source,'A',(Draw(3),));self.drain()
        self.assertEqual(43,self.state.life('A'))
        self.assertEqual(3,dict(self.state.get(self.pridemate).counters)['+1/+1'])

    def test_empty_library_shuffle_still_triggers(self):
        watcher=CardProgram('watch','Watcher',('Enchantment',),abilities=(AbilityProgram('shuffle-life',EventPattern('library_shuffled',controller_only=True),(GainLife(1),)),))
        self.programs.append(watcher);self.state.add_card('watch','watch','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs)
        self.kernel.execute_for_scenario(self.source,'A',(SearchLibrary(Selector(Zone.LIBRARY,relation='owned'),Zone.HAND),));self.drain()
        self.assertEqual(41,self.state.life('A'))
        self.assertEqual(1,dict(self.state.get(self.pridemate).counters)['+1/+1'])
