"""Player targets share admission/revalidation/replay; player draws retain APNAP cursors."""
import json
import unittest
from edh_gauntlet.rules_program import (CardProgram,TargetSpec,Selector,CastSpec,CostSpec,ActivatedProgram,
    AbilityProgram,EventPattern,Damage,GainLife,LoseLife,Draw,Move,ZoneReplacement,validate)
from edh_gauntlet.rules_state import RulesState,Zone,PlayerRef,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed


class PlayerTargetTests(unittest.TestCase):
    def setup_spell(self,effects=(Damage('target',2),),spec=TargetSpec(players='opponents'),*,active='A',actor='A',extra=()):
        self.program=CardProgram('spell','Spell',('Instant',),cast=CastSpec(CostSpec(),'instant'),spell_targets=spec,spell_effects=effects)
        self.programs=(self.program,CardProgram('creature','Creature',('Creature',),power=1,toughness=10),*extra)
        self.state=RulesState(('A','B','C'));self.source=self.state.add_card('spell','spell',actor,Zone.HAND)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario(active,priority_actor=actor);self.actor=actor

    def cast(self,targets):
        return self.kernel.commit_action(self.kernel.quote_cast('cast',self.actor,self.source,targets),Payment())

    def resolve(self):
        for _ in self.state.live_players:result=self.kernel.pass_priority(self.kernel.priority)
        return result

    def test_player_only_target_admission_is_exact_and_atomic(self):
        self.setup_spell();before=self.kernel.snapshot()
        object_ref=self.source
        for targets in ((PlayerRef('A'),),(PlayerRef('unknown'),),(object_ref,),(),(PlayerRef('B'),PlayerRef('B'))):
            with self.assertRaises(RulesViolation):self.cast(targets)
            self.assertEqual(before,self.kernel.snapshot())
        self.cast((PlayerRef('B'),));self.resolve();self.assertEqual(38,self.state.life('B'))

    def test_mixed_object_player_targets_share_damage_and_group_validation(self):
        self.setup_spell(spec=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',)),2,2,True,'all'))
        ref=self.state.add_card('creature','creature','B',Zone.BATTLEFIELD);before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.cast((ref,PlayerRef('B')))
        self.assertEqual(before,self.kernel.snapshot())
        self.cast((ref,PlayerRef('C')));self.resolve()
        self.assertEqual(2,self.state.get(ref).damage_marked);self.assertEqual(38,self.state.life('C'))

    def test_departed_player_target_fizzles_all_effects(self):
        self.setup_spell((Damage('target',2),GainLife(5)));self.cast((PlayerRef('B'),))
        self.state.lose_life_batch(('B',),40);self.kernel.advance();self.assertEqual(('A','C'),self.state.live_players)
        self.resolve();self.assertEqual(40,self.state.life('A'))
        self.assertTrue(any(e['kind']=='all_targets_illegal' for e in self.kernel.semantic_events))

    def test_partial_player_targets_keep_surviving_targets(self):
        self.setup_spell(spec=TargetSpec(minimum=2,maximum=2,players='opponents'))
        self.cast((PlayerRef('B'),PlayerRef('C')));self.state.lose_life_batch(('B',),40);self.kernel.advance()
        self.resolve();self.assertEqual(38,self.state.life('C'))

    def test_adapter_binds_player_targets_and_replays_public_summary(self):
        self.setup_spell();adapter=RulesActorAdapter(self.kernel)
        command={'kind':'cast','revision':self.kernel.revision,'action_id':'cast','source':self.source.to_json(),
            'targets':[{'player':'B'}],'x_value':0,'payment':{'mana':{},'taps':[]}}
        for bad in ({'player':'B','card_id':'secret'},{'player':4},{'player':'missing'}):
            before=adapter.archive()
            with self.assertRaises(RulesViolation):adapter.submit('A',{**command,'targets':[bad]})
            self.assertEqual(before,adapter.archive())
        packet=adapter.submit('A',command);self.assertEqual([{'player':'B'}],packet['stack'][0]['targets'])
        restored=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.assertEqual(packet,restored.packet('A'))
        for actor in self.state.players:
            cmd={'kind':'pass','revision':self.kernel.revision};adapter.submit(actor,cmd);restored.submit(actor,cmd)
        self.assertEqual(adapter.archive(),restored.archive());self.assertEqual(38,self.state.life('B'))

    def test_draws_for_controller_and_target_follow_active_player_order(self):
        self.setup_spell((Draw(2,'controller_and_target'),),TargetSpec(players='opponents'),active='A',actor='B')
        for player in ('A','B'):
            for i in range(2):self.state.add_card(player+str(i),'creature',player,Zone.LIBRARY)
        self.cast((PlayerRef('A'),));self.resolve()
        self.assertEqual(['A','A','B','B'],[e['player'] for e in self.kernel.semantic_events if e['kind']=='card_drawn'])
        for player in ('A','B'):self.assertEqual(2,len(self.state.zone(player,Zone.HAND)))

    def test_pending_draw_replacement_retains_cursor_actor_and_private_menu(self):
        replacement=CardProgram('replacement','Replacement',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.HAND,Zone.EXILE,from_zone=Zone.LIBRARY,optional=True),))
        self.setup_spell((Draw(2,'controller_and_target'),),TargetSpec(players='opponents'),active='A',actor='B',extra=(replacement,))
        self.state.add_card('replacement','replacement','C',Zone.BATTLEFIELD)
        for player in ('A','B'):
            for i in range(2):self.state.add_card(player+'secret'+str(i),'creature',player,Zone.LIBRARY)
        self.cast((PlayerRef('A'),));request=self.resolve();self.assertEqual('A',request.actor)
        adapter=RulesActorAdapter(self.kernel);packet=adapter.packet('B');self.assertNotIn('Asecret',json.dumps(packet))
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs);actors=[]
        while request:
            actors.append(request.actor)
            self.kernel.answer(request.request_id,request.actor,[1]);restored.answer(request.request_id,request.actor,[1])
            self.assertEqual(self.kernel.snapshot(),restored.snapshot());request=self.kernel.pending_choice
        self.assertEqual(['A','A','B','B'],actors)
        for player in ('A','B'):self.assertEqual(2,len(self.state.zone(player,Zone.HAND)))
        self.assertEqual(4,sum(e['kind']=='card_drawn' for e in self.kernel.semantic_events))

    def test_large_draw_uses_one_frame_task_and_no_prompt_when_unopposed(self):
        self.setup_spell((Draw(20,'target'),),TargetSpec(players='opponents'))
        for i in range(20):self.state.add_card(str(i),'creature','B',Zone.LIBRARY)
        self.cast((PlayerRef('B'),));self.assertEqual(1,len(self.kernel.stack[-1]['tasks']))
        before=self.kernel._serial;self.resolve()
        self.assertLess(self.kernel._serial-before,5);self.assertEqual(20,len(self.state.zone('B',Zone.HAND)))

    def test_life_loss_is_atomic_and_is_not_damage_or_payment(self):
        self.setup_spell((LoseLife('opponents',3),),None)
        self.cast(());self.resolve()
        self.assertEqual((40,37,37),tuple(self.state.life(p) for p in self.state.players))
        self.assertFalse(any(e['kind']=='damage_dealt' for e in self.kernel.semantic_events))
        self.assertEqual(['B','C'],[e['player'] for e in self.kernel.semantic_events if e['kind']=='life_lost'])
        before=self.state.snapshot()
        for players,amount in ((('B','B'),1),(('missing',),1),(('B',),-1),(('B',),True)):
            with self.assertRaises(RulesViolation):self.state.lose_life_batch(players,amount)
            self.assertEqual(before,self.state.snapshot())
        sequence=self.state.sequence;self.state.lose_life_batch(('B','C'),40)
        self.assertEqual(sequence+1,self.state.sequence);self.assertEqual(-3,self.state.life('B'))

    def test_compiler_rejects_mismatched_target_and_effect_domains(self):
        for spec,effect in ((TargetSpec(),Draw()),(TargetSpec(players='opponents'),Move('target',Zone.HAND)),
                (TargetSpec(Selector(Zone.BATTLEFIELD),players='all'),Draw(1,'target')),
                (None,LoseLife('target',1)),(TargetSpec(players='unknown'),Damage('target',1))):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),spell_targets=spec,spell_effects=(effect,)))


class AuthoredPlayerCardTests(unittest.TestCase):
    def setUp(self):
        self.programs=tuple(row['program'] for row in load_reviewed().values());self.state=RulesState(('A','B','C'));self.kernel=RulesKernel(self.state,self.programs)

    def add(self,key,zone=Zone.BATTLEFIELD,actor='A',name=None):return self.state.add_card(name or key,'catalog:'+key,actor,zone)

    def drain(self):
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)
        return self.kernel.pending_choice

    def answer(self,indexes):
        r=self.kernel.pending_choice;self.kernel.answer(r.request_id,r.actor,indexes);return self.drain()

    def test_lush_oasis_enters_tapped_and_chooses_only_opponents(self):
        source=self.add('lush-oasis',Zone.HAND);self.kernel.enter(source);r=self.kernel.pending_choice
        self.assertEqual(['B','C'],[o.player for o in r.options]);self.answer([1])
        self.assertEqual(39,self.state.life('C'));ref=self.state.current('lush-oasis');self.assertTrue(self.state.get(ref).tapped)
        self.state.start_turn('A');self.kernel.open_window_for_scenario('A')
        r=self.kernel.commit_action(self.kernel.quote_activation('mana','A',ref,'mana'),Payment())
        self.kernel.answer(r.request_id,'A',[1]);self.assertEqual((('U',1),),self.state.mana_pool('A'))

    def test_loran_destroys_optional_artifact_and_draws_for_both_in_apnap_order(self):
        artifact=self.add('sol-ring',actor='C');source=self.add('loran-of-the-third-path',Zone.HAND,actor='B')
        self.kernel.enter(source);self.answer([0]);self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('sol-ring')).zone)
        ref=self.state.current('loran-of-the-third-path');self.state.start_turn('B')
        for player in ('A','B'):self.add('forest',Zone.LIBRARY,player,player+'draw')
        self.kernel.open_window_for_scenario('A',priority_actor='B')
        self.kernel.commit_action(self.kernel.quote_activation('draw','B',ref,'draw',(PlayerRef('A'),)),Payment());self.drain()
        self.assertEqual(['A','B'],[e['player'] for e in self.kernel.semantic_events if e['kind']=='card_drawn'])
        self.assertTrue(self.state.get(ref).tapped)

    def test_arena_own_upkeep_draws_and_loses_life(self):
        self.add('phyrexian-arena');self.add('forest',Zone.LIBRARY)
        self.kernel.begin_turn_for_scenario('A');self.drain()
        self.assertEqual(39,self.state.life('A'));self.assertEqual(1,len(self.state.zone('A',Zone.HAND)))
        self.assertFalse(any(e['kind']=='damage_dealt' for e in self.kernel.semantic_events))

    def test_grim_guardian_triggers_for_own_enchantments_including_self(self):
        source=self.add('grim-guardian',Zone.HAND);self.kernel.enter(source);self.drain()
        self.assertEqual((40,39,39),tuple(self.state.life(p) for p in self.state.players))
        enemy=self.add('phyrexian-arena',Zone.HAND,'B');self.kernel.enter(enemy);self.drain()
        self.assertEqual((40,39,39),tuple(self.state.life(p) for p in self.state.players))
        own=self.add('phyrexian-arena',Zone.HAND,name='own');self.kernel.enter(own);self.drain()
        self.assertEqual((40,38,38),tuple(self.state.life(p) for p in self.state.players))

    def test_coinsmith_and_blight_priest_share_gain_trigger_and_life_loss(self):
        self.add('marauding-blight-priest');source=self.add('underworld-coinsmith',Zone.HAND)
        self.kernel.enter(source);self.drain();self.assertEqual((41,39,39),tuple(self.state.life(p) for p in self.state.players))
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',tuple('CWB'))
        self.kernel.commit_action(self.kernel.quote_activation('drain','A',self.state.current('underworld-coinsmith'),'drain'),Payment((('C',1),('W',1),('B',1))))
        self.assertEqual(40,self.state.life('A'));self.drain();self.assertEqual((40,38,38),tuple(self.state.life(p) for p in self.state.players))
