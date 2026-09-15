"""Actor relations and captured event players are shared trigger semantics."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter

class EventPlayerTests(unittest.TestCase):
    def game(self,kind='spell_cast',relation='opponent_controlled',effects=None):
        effects=(LoseLife('event_controllers',1),) if effects is None else effects
        self.watcher=CardProgram('watch','Watcher',('Enchantment',),abilities=(AbilityProgram('event',EventPattern(kind,recipient_relation=relation),effects),))
        self.spell=CardProgram('spell','Spell',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),spell_effects=(GainLife(0),),activated=(ActivatedProgram('use',CostSpec(),(GainLife(0),),zone=Zone.HAND),))
        self.programs=(self.watcher,self.spell,CardProgram('land','Land',('Land',)))
        self.state=RulesState(('A','B','C'));self.ref=self.state.add_card('watch','watch','A',Zone.BATTLEFIELD)
        self.source=self.state.add_card('spell','spell','B',Zone.HAND)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('B')
    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack or kernel.pending_choice:
            if kernel.pending_choice:
                q=kernel.pending_choice;kernel.answer(q.request_id,q.actor,list(range(q.minimum)))
            else:kernel.pass_priority(kernel.priority)

    def test_relations_match_every_supported_actor_event(self):
        for kind in ACTOR_EVENTS:
            for relation in ('any','controlled','opponent_controlled'):
                for actor in ('A','B','C'):
                    self.game(kind,relation)
                    if kind in {'spell_cast','ability_activated'}:self.kernel._collect_announcement(kind,self.state.get(self.source),actor)
                    else:self.kernel._player_event(kind,actor,amount=2)
                    expected=relation=='any' or (actor=='A')==(relation=='controlled')
                    self.assertEqual(int(expected),len(self.kernel.pending_triggers),(kind,relation,actor))
                    if expected:self.assertEqual([actor],self.kernel.pending_triggers[0]['values']['event_controllers'])

    def test_paid_opponent_cast_captures_actor_across_control_change_and_replay(self):
        self.game();self.kernel.commit_action(self.kernel.quote_cast('cast','B',self.source),Payment())
        self.state.change_control(self.ref,'C')
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.drain();self.drain(replay.kernel);self.assertEqual(adapter.archive(),replay.archive())
        self.assertEqual(39,self.state.life('B'));self.assertEqual(40,self.state.life('A'));self.assertEqual(40,self.state.life('C'))

    def test_draws_generate_one_trigger_per_card_and_keep_captured_player(self):
        self.game('card_drawn')
        for i in range(2):self.state.add_card('draw'+str(i),'land','B',Zone.LIBRARY)
        self.kernel.execute_for_scenario(self.source,'B',(Draw(2),));self.drain()
        self.assertEqual(38,self.state.life('B'));self.assertEqual(40,self.state.life('A'))
        self.assertEqual(2,sum(e['kind']=='card_drawn' for e in self.kernel.semantic_events))

    def test_real_activation_filters_own_actor_and_copied_phased_observers(self):
        self.game('ability_activated');copy=self.state.add_card('copy','land','C',Zone.HAND)
        self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,'C',copied_definition='watch'),),'scenario_copy')
        self.state.phase(self.ref,True)
        self.kernel.commit_action(self.kernel.quote_activation('use','B',self.source,'use'),Payment());self.drain()
        self.assertEqual(39,self.state.life('B'))
        self.game('ability_activated');self.state.change_control(self.ref,'B')
        self.kernel.commit_action(self.kernel.quote_activation('use','B',self.source,'use'),Payment());self.drain()
        self.assertEqual(40,self.state.life('B'))

    def test_life_amount_and_cast_x_bindings_coexist_with_event_player(self):
        self.game('life_gained',effects=(LoseLife('event_controllers',EventAmount()),))
        self.kernel.execute_for_scenario(self.source,'B',(GainLife(3),));self.drain();self.assertEqual(40,self.state.life('B'))
        self.game(effects=(LoseLife('event_controllers',EventX()),))
        before=self.state.get(self.source);self.kernel._collect_announcement('spell_cast',replace(before,cast_x=3),'B')
        self.kernel.advance();self.drain();self.assertEqual(37,self.state.life('B'))

    def test_invalid_relations_and_unbound_event_recipients_remain_rejected(self):
        self.game();base=self.watcher;ability=base.abilities[0]
        for pattern in (EventPattern('spell_cast',controller_only=True,recipient_relation='opponent_controlled'),EventPattern('step_began',step='upkeep',recipient_relation='controlled'),EventPattern('becomes_tapped',recipient_relation='controlled')):
            with self.assertRaises(RulesViolation):validate(replace(base,abilities=(replace(ability,event=pattern),)))
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Sorcery',),spell_effects=(LoseLife('event_controllers',1),)))
        good=replace(ability,event=EventPattern('card_drawn',controller_only=True,recipient_relation='controlled'))
        validate(replace(base,abilities=(good,)));self.assertEqual(good,decode(encode(good)))

if __name__=='__main__':unittest.main()
