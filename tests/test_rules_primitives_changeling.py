"""All-creature-type characteristics compose with copies, layers and compact views."""
from dataclasses import replace
import hashlib,json,unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_creature_types import CREATURE_TYPES
from edh_gauntlet.rules_actor import _card
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_characteristics import evaluate,evaluate_exhaustive,matches

class ChangelingTests(unittest.TestCase):
    def game(self,zone=Zone.BATTLEFIELD,extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+tuple(extra)
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('mauler','catalog:taurean-mauler','A',zone)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
    def drain(self,kernel=None):
        kernel=kernel or self.kernel
        while kernel.stack and not kernel.pending_choice:kernel.pass_priority(kernel.priority)
    def cast_enemy(self,drain=True):
        ref=self.state.add_card('spell','catalog:sol-ring','B',Zone.HAND)
        self.kernel.open_window_for_scenario('B');self.state.add_mana('B',('C',))
        self.kernel.commit_action(self.kernel.quote_cast('enemy','B',ref),Payment((('C',1),)))
        if drain:self.drain()

    def test_complete_pinned_types_apply_in_every_zone_and_not_noncreature_types(self):
        self.assertEqual('7c8629d5c8bf2559f1656f485ec4707687c128acc40abb6516eec8fb4dd40b09',hashlib.sha256(json.dumps(sorted(CREATURE_TYPES),ensure_ascii=False,separators=(',',':')).encode()).hexdigest())
        self.assertEqual(324,len(CREATURE_TYPES));self.assertTrue({'Time Lord','Hamster',"C'tan","Shi'ar",'Drix','Shapeshifter'}<=CREATURE_TYPES)
        self.assertFalse({'Forest','Gate','Treasure','Aura','Equipment','Legendary'}&CREATURE_TYPES)
        for zone in Zone:
            self.game(zone);self.assertEqual(CREATURE_TYPES,self.kernel.effective(self.ref).subtypes)
            frame={'source':self.state.get(self.ref).to_json(),'controller':'A'}
            for subtype in ('Elf','Hamster','Time Lord'):
                self.assertTrue(matches(Selector(zone,subtypes=(subtype,)),self.state.get(self.ref),self.kernel.effective(self.ref),self.state.get(self.ref)))
            self.assertFalse(matches(Selector(zone,excluded_subtypes=('Elf',)),self.state.get(self.ref),self.kernel.effective(self.ref),self.state.get(self.ref)))

    def test_printed_paid_cast_and_opponent_optional_counter(self):
        self.game(Zone.HAND);self.state.add_mana('A',('C','C','R'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.ref),Payment((('C',2),('R',1))))
        self.drain();self.ref=self.state.current('mauler');self.assertIsNone(self.kernel.pending_choice)
        self.assertFalse(self.state.get(self.ref).counters);self.cast_enemy();q=self.kernel.pending_choice
        self.assertEqual(('may','A'),(q.kind,q.actor));self.kernel.answer(q.request_id,'A',[0]);self.drain()
        self.assertEqual({'+1/+1':1},dict(self.state.get(self.ref).counters));self.assertEqual(3,self.kernel.effective(self.ref).power)

    def test_decline_control_change_replay_and_departed_source(self):
        for departed in (False,True):
            self.game();self.cast_enemy(drain=False);self.state.change_control(self.ref,'B')
            if departed:self.state.move((ZoneMove(self.ref,Zone.HAND),),'scenario_response')
            self.drain();q=self.kernel.pending_choice;self.assertEqual('A',q.actor)
            self.kernel.answer(q.request_id,'A',[0]);self.drain()
            current=self.state.get(self.state.current('mauler'))
            self.assertEqual({} if departed else {'+1/+1':1},dict(current.counters))
        self.game();self.cast_enemy();adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        q=self.kernel.pending_choice;cmd={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[1]}
        adapter.submit('A',cmd);replay.submit('A',cmd);self.assertEqual(adapter.archive(),replay.archive())
        self.assertFalse(self.state.get(self.ref).counters)

    def test_copy_inherits_types_but_plain_shapeshifter_does_not(self):
        self.game();copy=self.state.add_card('copy','catalog:forest','B',Zone.HAND)
        self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,'B',copied_definition='catalog:taurean-mauler'),),'scenario_copy')
        copy=self.state.current('copy');self.assertEqual(CREATURE_TYPES,self.kernel.effective(copy).subtypes)
        plain=self.state.add_card('plain','catalog:body-double','B',Zone.GRAVEYARD)
        self.assertEqual({'Shapeshifter'},set(self.kernel.effective(plain).subtypes))
        self.state.move((ZoneMove(copy,Zone.GRAVEYARD),),'scenario_departure')
        self.assertEqual({'Forest'},set(self.kernel.effective(self.state.current('copy')).subtypes))

    def test_tribal_anthem_and_removing_last_supporting_card_type(self):
        anthem=CardProgram('anthem','Anthem',('Enchantment',),continuous=(ContinuousProgram('elf',Selector(Zone.BATTLEFIELD,subtypes=('Elf',)),(ModifyPT(1,1),AddKeywords(('flying',)))),))
        strip=CardProgram('strip','Strip',('Enchantment',),continuous=(ContinuousProgram('strip',Selector(Zone.BATTLEFIELD,subtypes=('Shapeshifter',)),(ChangeTypes(('Artifact',),('Creature',)),)),))
        self.game(extra=(anthem,strip));self.state.add_card('anthem','anthem','A',Zone.BATTLEFIELD)
        self.assertEqual(3,self.kernel.effective(self.ref).power);self.assertIn('flying',self.kernel.effective(self.ref).keywords)
        self.state.add_card('strip','strip','B',Zone.BATTLEFIELD);view=self.kernel.effective(self.ref)
        self.assertFalse(view.subtypes);self.assertNotIn('flying',view.keywords);self.assertIsNone(view.power)
        args=(self.state.objects(),self.kernel.definitions)
        self.assertEqual(evaluate(*args),evaluate_exhaustive(*args))

    def test_kindred_retains_creature_types_and_compact_projection_is_lossless(self):
        kindred=CardProgram('kindred','Kindred',('Kindred','Artifact'),subtypes=('Equipment',),all_subtype_sets=('creature',))
        self.game(extra=(kindred,));ref=self.state.add_card('kindred','kindred','A',Zone.BATTLEFIELD)
        card=_card(self.kernel,self.state.get(ref),self.kernel.characteristics())
        self.assertTrue(card['all_creature_types']);self.assertEqual(['Equipment'],card['subtypes'])
        self.assertEqual(self.kernel.effective(ref).subtypes,CREATURE_TYPES|set(card['subtypes']))
        self.assertLess(len(json.dumps(card)),1000)
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs);self.assertEqual(self.kernel.snapshot(),restored.snapshot())

    def test_invalid_characteristics_are_rejected(self):
        for program in (CardProgram('bad','Bad',('Artifact',),all_subtype_sets=('creature',)),CardProgram('bad','Bad',('Creature',),power=1,toughness=1,all_subtype_sets=1)):
            with self.assertRaises(RulesViolation):validate(program)

if __name__=='__main__':unittest.main()
