"""Attack events retain the specific defending player for shared effects."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_adapter import RulesActorAdapter


class DefendingPlayerTests(unittest.TestCase):
    def game(self,count=1,extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+extra
        self.state=RulesState(('A','B','C'))
        self.lands=[self.state.add_card('land'+str(i),'catalog:restless-fortress','A',Zone.BATTLEFIELD) for i in range(count)]
        for p in self.state.players:
            for i in range(3):self.state.add_card('draw'+p+str(i),'catalog:forest',p,Zone.LIBRARY)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.begin_turn_for_scenario('A')

    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack or kernel.pending_choice:
            if kernel.pending_choice:
                q=kernel.pending_choice;self.assertEqual('trigger_order',q.kind)
                kernel.answer(q.request_id,q.actor,list(range(len(q.options))))
            else:kernel.pass_priority(kernel.priority)

    def animate(self,ref):
        self.state.add_mana('A',('W','B','C','C'))
        self.kernel.commit_action(self.kernel.quote_activation('animate'+str(self.state.sequence),'A',ref,'animate'),Payment((('W',1),('B',1),('C',2))))
        self.drain()

    def attack(self,assignments=None,through_adapter=False):
        for ref in self.lands:self.animate(ref)
        for _ in range(4):
            for p in self.state.players:self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual('declare_attackers',self.kernel.phase)
        assignments=assignments or {self.lands[0]:'B'}
        if through_adapter:
            adapter=RulesActorAdapter(self.kernel)
            adapter.submit('A',{'kind':'attack','attackers':[{'source':ref.to_json(),'defender':player} for ref,player in assignments.items()],'revision':self.kernel.revision})
            return adapter
        self.kernel.declare_attackers('A',assignments,revision=self.kernel.revision)

    def test_paid_animation_entry_and_each_mana_choice(self):
        self.game();self.animate(self.lands[0]);view=self.kernel.effective(self.lands[0])
        self.assertEqual({'Land','Creature'},set(view.types));self.assertEqual({'Nightmare'},set(view.subtypes))
        self.assertEqual({'W','B'},set(view.colors));self.assertEqual((1,4),(view.power,view.toughness))
        self.assertEqual((),self.state.mana_pool('A'))
        for index,color in enumerate('WB'):
            self.game();q=self.kernel.commit_action(self.kernel.quote_activation('mana','A',self.lands[0],'mana'),Payment())
            self.kernel.answer(q.request_id,'A',[index]);self.assertEqual(((color,1),),self.state.mana_pool('A'))
        self.game();ref=self.state.add_card('entry','catalog:restless-fortress','A',Zone.HAND)
        self.kernel.execute_for_scenario(ref,'A',(Move('source',Zone.BATTLEFIELD),))
        self.assertTrue(self.state.get(self.state.current('entry')).tapped)

    def test_two_attackers_capture_different_defenders_and_actor_replay(self):
        self.game(2);adapter=self.attack(dict(zip(self.lands,('B','C'))),through_adapter=True)
        while self.kernel.pending_choice:
            q=self.kernel.pending_choice
            adapter.submit(q.actor,{'kind':'answer','request_id':q.request_id,'indexes':list(range(len(q.options))),'revision':self.kernel.revision})
        self.assertEqual({'B','C'},{f['defending_player'] for f in adapter.packet('C')['stack']})
        while self.kernel.stack:adapter.submit(self.kernel.priority,{'kind':'pass','revision':self.kernel.revision})
        self.assertEqual((44,38,38),tuple(self.state.life(p) for p in self.state.players))
        replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        for p in self.state.players:self.assertEqual(adapter.packet(p),replay.packet(p))

    def test_source_departure_retains_defender_across_checkpoint(self):
        self.game();self.attack();self.state.move((ZoneMove(self.lands[0],Zone.EXILE),),'fixture-response')
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.drain();self.drain(restored)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual((42,38,40),tuple(self.state.life(p) for p in self.state.players))

    def test_control_change_does_not_redirect_gain_or_loss(self):
        self.game();self.attack();self.state.change_control_batch((self.lands[0],),'C');self.drain()
        self.assertEqual((42,38,40),tuple(self.state.life(p) for p in self.state.players))

    def test_copied_fortress_inherits_attack_and_animation(self):
        self.game();self.state.move((ZoneMove(self.lands[0],Zone.GRAVEYARD),),'fixture-remove')
        ref=self.state.add_card('copy','catalog:forest','A',Zone.HAND)
        self.state.move((ZoneMove(ref,Zone.BATTLEFIELD,copied_definition='catalog:restless-fortress'),),'fixture-copy')
        self.lands=[self.state.current('copy')]
        # This copy is new this turn; grant haste through the shared layer.
        self.kernel.execute_for_scenario(self.lands[0],'A',(UntilEndOfTurn('source',(AddKeywords(('haste',)),)),))
        self.attack({self.lands[0]:'C'});self.drain()
        self.assertEqual((42,40,38),tuple(self.state.life(p) for p in self.state.players))

    def test_generic_observer_draw_and_tokens_use_each_attack_defender(self):
        token=CardProgram('gift','Gift',('Creature',),power=1,toughness=1)
        observer=CardProgram('observer','Observer',('Enchantment',),abilities=(AbilityProgram('gift',EventPattern('creature_attacks'),(Draw(1,players='defending_player'),CreateTokens(token,1,players='defending_player'))),))
        self.game(extra=(observer,));self.state.add_card('observer','observer','C',Zone.BATTLEFIELD)
        self.attack({self.lands[0]:'B'});self.drain()
        self.assertEqual(1,len([o for o in self.state.objects(Zone.HAND) if o.owner=='B']))
        gifts=[o for o in self.state.objects(Zone.BATTLEFIELD) if o.definition=='gift']
        self.assertEqual(['B'],[o.controller for o in gifts])

    def test_defender_binding_is_only_available_to_attack_triggers(self):
        token=CardProgram('gift','Gift',('Creature',),power=1,toughness=1)
        for effect in (LoseLife('defending_player',1),Draw(1,players='defending_player'),Mill(1,players='defending_player'),CreateTokens(token,1,players='defending_player')):
            for kind in ('zone_changed','creature_blocks','step_began'):
                event=EventPattern(kind,step='upkeep' if kind=='step_began' else None)
                with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Enchantment',),abilities=(AbilityProgram('bad',event,(effect,)),)))
