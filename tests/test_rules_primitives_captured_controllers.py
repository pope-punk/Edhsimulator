"""Lexical controller captures retain recipients without changing the resolving actor."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import (CardProgram,WithControllers,CreateTokens,Destroy,Move,SelectAll,Selector,
    GainLife,EntryCounters,CounterReplacement,TargetSpec,CastSpec,CostSpec,ManaCost,validate)
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter


class CapturedControllerTests(unittest.TestCase):
    def game(self,token=None,extra=()):
        self.token=token or CardProgram('token:gift','Gift Token',('Creature',),power=3,toughness=3,colors=('G',))
        self.source=CardProgram('source','Source',('Artifact',),spell_effects=(CreateTokens(self.token),))
        self.creature=CardProgram('creature','Creature',('Creature',),power=1,toughness=1)
        self.programs=(self.source,self.creature,*extra);self.state=RulesState(('A','B','C'))
        self.ref=self.state.add_card('source','source','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs,active_player='C')

    def test_stolen_objects_give_tokens_to_former_controller_not_owner_or_actor(self):
        self.game();victim=self.state.add_card('victim','creature','C',Zone.BATTLEFIELD,controller='B')
        self.kernel.execute_for_scenario(self.ref,'A',(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',)),
            (WithControllers('selected',(Destroy('selected'),CreateTokens(self.token,players='captured_controllers'),GainLife(1))),)),))
        token=next(o for o in self.state.objects() if o.token)
        self.assertEqual(('B','B'),(token.owner,token.controller));self.assertEqual(41,self.state.life('A'))
        self.assertEqual(40,self.state.life('B'));self.assertEqual('C',self.state.get(self.state.current('victim')).owner)

    def test_duplicate_controllers_contribute_each_object_and_commit_one_token_batch(self):
        self.game()
        for i,p in enumerate(('B','B','C')):self.state.add_card(str(i),'creature',p,Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(self.ref,'A',(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',)),
            (WithControllers('selected',(Destroy('selected'),CreateTokens(self.token,2,'captured_controllers'))),)),))
        tokens=[o for o in self.state.objects() if o.token]
        self.assertEqual(4,sum(o.owner=='B' for o in tokens));self.assertEqual(2,sum(o.owner=='C' for o in tokens))
        events=[e for e in self.state.events if e.cause=='token_created'];self.assertEqual(1,len({e.batch for e in events}))
        self.assertEqual(['C','C','B','B','B','B'],[e.after.owner for e in events])

    def test_nested_capture_restores_outer_recipients(self):
        self.game();self.state.add_card('b','creature','B',Zone.BATTLEFIELD);self.state.add_card('c','creature','C',Zone.BATTLEFIELD)
        inner=SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',),relation='opponent_controlled'),
            (WithControllers('selected',(CreateTokens(self.token,players='captured_controllers'),)),))
        self.kernel.execute_for_scenario(self.ref,'A',(WithControllers('source',(inner,CreateTokens(self.token,players='captured_controllers'))),))
        self.assertEqual(['C','B','A'],[o.owner for o in self.state.objects() if o.token])

    def test_pending_token_replacement_after_removal_retains_actor_and_exact_replay(self):
        token=CardProgram('token:gift','Gift Token',('Creature',),power=0,toughness=0,entry_counters=(EntryCounters('one','+1/+1',1),))
        mods=tuple(CardProgram(k,k,('Enchantment',),counter_replacements=(CounterReplacement(k,Selector(Zone.BATTLEFIELD,relation='controlled'),kind='+1/+1',multiplier=m,additional=a),)) for k,m,a in (('double',2,0),('plus',1,1)))
        self.game(token,mods);self.state.add_card('victim','creature','B',Zone.BATTLEFIELD)
        for mod in mods:self.state.add_card(mod.name,mod.definition_id,'B',Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(self.ref,'A',(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',)),
            (WithControllers('selected',(Destroy('selected'),CreateTokens(token,players='captured_controllers'))),)),))
        r=self.kernel.pending_choice;self.assertEqual('B',r.actor)
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('victim')).zone)
        self.assertFalse(any(o.token for o in self.state.objects()))
        adapter=RulesActorAdapter(self.kernel);restored=RulesActorAdapter.replay(adapter.archive(),self.programs)
        command={'kind':'answer','revision':self.kernel.revision,'request_id':r.request_id,'indexes':[0]}
        adapter.submit('B',command);restored.submit('B',command);self.assertEqual(adapter.archive(),restored.archive())
        self.assertEqual('B',next(o.owner for o in self.state.objects() if o.token))

    def test_player_targets_can_create_tokens_without_object_capture(self):
        self.game();spell=CardProgram('gift','Gift',('Instant',),cast=CastSpec(CostSpec()),
            spell_targets=TargetSpec(None,players='opponents'),spell_effects=(CreateTokens(self.token,players='target'),))
        self.kernel=RulesKernel(self.state,(*self.programs,spell));ref=self.state.add_card('gift','gift','A',Zone.HAND)
        from edh_gauntlet.rules_state import PlayerRef
        self.kernel.open_window_for_scenario('A');self.kernel.commit_action(self.kernel.quote_cast('gift','A',ref,(PlayerRef('B'),)),Payment())
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual('B',next(o.owner for o in self.state.objects() if o.token))

    def test_departed_ability_source_uses_its_bound_last_known_controller(self):
        from edh_gauntlet.rules_program import ActivatedProgram,CounterCost
        self.game()
        program=CardProgram('fragile','Fragile',('Creature',),power=0,toughness=0,
            activated=(ActivatedProgram('gift',CostSpec(counter_costs=(CounterCost('+1/+1',1),)),
                (WithControllers('source',(CreateTokens(self.token,players='captured_controllers'),)),)),))
        ref=self.state.add_card('fragile','fragile','A',Zone.BATTLEFIELD);self.state.add_counters(ref,'+1/+1',1)
        self.kernel=RulesKernel(self.state,(*self.programs,program));self.kernel.open_window_for_scenario('A')
        self.kernel.commit_action(self.kernel.quote_activation('gift','A',ref,'gift'),Payment())
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('fragile')).zone)
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual('A',next(o.owner for o in self.state.objects() if o.token))

    def test_compiler_rejects_escaped_capture_and_wrong_target_domain(self):
        self.game()
        for effects,spec in (((CreateTokens(self.token,players=[]),),None),
                ((WithControllers([],()),),None),
                ((CreateTokens(self.token,players='captured_controllers'),),None),
                ((WithControllers('missing',(CreateTokens(self.token),)),),None),
                ((CreateTokens(self.token,players='target'),),TargetSpec(Selector(Zone.BATTLEFIELD))),
                ((WithControllers('target',(CreateTokens(self.token),)),),TargetSpec(None,players='all'))):
            with self.assertRaises(RulesViolation):validate(replace(self.source,spell_effects=effects,spell_targets=spec))

class AuthoredControllerGiftTests(unittest.TestCase):
    def game(self):
        from edh_gauntlet.rules_bundle import load_reviewed
        self.programs=tuple(r['program'] for r in load_reviewed().values());self.state=RulesState(('A','B'))
        self.kernel=RulesKernel(self.state,self.programs)

    def test_beast_within_creates_even_when_indestructible_prevents_destruction(self):
        self.game();victim=CardProgram('indestructible','Indestructible',('Creature',),power=1,toughness=1,keywords=('indestructible',))
        self.kernel=RulesKernel(self.state,(*self.programs,victim))
        target=self.state.add_card('target','indestructible','B',Zone.BATTLEFIELD)
        spell=self.state.add_card('spell','catalog:beast-within','A',Zone.HAND)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('G','C','C'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',spell,(target,)),Payment((('G',1),('C',2))))
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(target).zone)
        token=next(o for o in self.state.objects() if o.token);self.assertEqual('B',token.owner)
        self.assertEqual((3,3),(self.kernel.effective(token.ref).power,self.kernel.effective(token.ref).toughness))

    def test_beast_within_illegal_target_prevents_token(self):
        self.game();target=self.state.add_card('target','catalog:forest','B',Zone.BATTLEFIELD)
        spell=self.state.add_card('spell','catalog:beast-within','A',Zone.HAND)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('G','C','C'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',spell,(target,)),Payment((('G',1),('C',2))))
        from edh_gauntlet.rules_state import ZoneMove
        self.state.move((ZoneMove(target,Zone.GRAVEYARD),),'scenario_target_departed')
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
        self.assertFalse(any(o.token for o in self.state.objects()))

    def test_swan_song_counters_spell_and_gives_controller_blue_flying_bird(self):
        self.game();target=self.state.add_card('target','catalog:opt','B',Zone.HAND)
        spell=self.state.add_card('spell','catalog:swan-song','A',Zone.HAND)
        self.kernel.open_window_for_scenario('B');self.state.add_mana('B',('U',));self.state.add_mana('A',('U',))
        self.kernel.commit_action(self.kernel.quote_cast('opt','B',target),Payment((('U',1),)))
        self.kernel.pass_priority('B')
        self.kernel.commit_action(self.kernel.quote_cast('swan','A',spell,(self.state.current('target'),)),Payment((('U',1),)))
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('target')).zone)
        self.assertIsNone(self.kernel.pending_choice)
        token=next(o for o in self.state.objects() if o.token);view=self.kernel.effective(token.ref)
        self.assertEqual('B',token.owner);self.assertEqual({'U'},view.colors);self.assertEqual({'flying'},view.keywords)
        self.assertEqual((2,2),(view.power,view.toughness))

if __name__=='__main__':unittest.main()

