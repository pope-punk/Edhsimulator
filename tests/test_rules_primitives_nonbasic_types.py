"""Named subtype sets compose with printed lands, counts, searches and copies."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_subtypes import BASIC_LAND_TYPES,NONBASIC_LAND_TYPES,CREATURE_TYPES
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_characteristics import matches,evaluate,evaluate_exhaustive

class NonbasicTypeTests(unittest.TestCase):
    def game(self,zone=Zone.BATTLEFIELD,extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+tuple(extra)
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('nexus','catalog:planar-nexus','A',zone)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
    def activate(self,ref=None,ability='colorless',payment=Payment(),action='mana'):
        return self.kernel.commit_action(self.kernel.quote_activation(action,'A',ref or self.ref,ability),payment)
    def answer(self,index=0,kernel=None):
        kernel=kernel or self.kernel;q=kernel.pending_choice;return kernel.answer(q.request_id,q.actor,[index])

    def test_current_types_everywhere_exclude_basics_and_do_not_grant_colored_abilities(self):
        self.assertEqual({'Cave','Desert','Gate','Lair','Locus','Mine','Planet','Power-Plant','Sphere','Tower','Town',"Urza's"},set(NONBASIC_LAND_TYPES))
        for zone in Zone:
            self.game(zone);view=self.kernel.effective(self.ref);self.assertEqual(NONBASIC_LAND_TYPES,view.subtypes)
            self.assertFalse(view.subtypes&BASIC_LAND_TYPES);self.assertFalse(view.supertypes)
            self.assertTrue(matches(Selector(zone,subtypes=('Gate','Desert')),self.state.get(self.ref),view,self.state.get(self.ref)))
        self.game();self.assertEqual({'colorless','filter'},{a.ability_id for a in self.kernel.activated_abilities(self.state.get(self.ref))})

    def test_land_play_and_colorless_production(self):
        self.game(Zone.HAND);self.state.add_card('draw','catalog:forest','A',Zone.LIBRARY)
        self.kernel.begin_turn_for_scenario('A')
        for _ in range(4):self.kernel.pass_priority(self.kernel.priority)
        self.kernel.play_land('land','A',self.ref,revision=self.kernel.revision)
        self.ref=self.state.current('nexus');self.assertFalse(self.state.get(self.ref).tapped)
        self.activate();self.assertEqual({'C':1},dict(self.state.mana_pool('A')))

    def test_filter_pays_before_choice_and_replays_without_duplicate_output(self):
        self.game();quote=self.kernel.quote_activation('filter','A',self.ref,'filter');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,Payment())
        self.assertEqual(before,self.kernel.snapshot());self.state.add_mana('A',('C',))
        self.activate(ability='filter',payment=Payment((('C',1),)),action='paid-filter')
        self.assertFalse(self.state.mana_pool('A'));self.assertTrue(self.state.get(self.ref).tapped)
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        q=self.kernel.pending_choice;cmd={'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[4]}
        adapter.submit('A',cmd);replay.submit('A',cmd);self.assertEqual(adapter.archive(),replay.archive())
        self.assertEqual({'G':1},dict(self.state.mana_pool('A')))
        with self.assertRaises(RulesViolation):adapter.submit('A',cmd)

    def test_urza_requirements_and_locus_count_use_shared_membership(self):
        for card,expected in (('urza-s-tower',3),('urza-s-mine',2),('urza-s-power-plant',2),('cloudpost',2)):
            self.game();ref=self.state.add_card('land','catalog:'+card,'A',Zone.BATTLEFIELD)
            ability=self.kernel.activated_abilities(self.state.get(ref))[0]
            self.activate(ref,ability.ability_id);self.assertEqual({'C':expected},dict(self.state.mana_pool('A')),card)
        self.game();self.state.phase(self.ref,True);ref=self.state.add_card('tower','catalog:urza-s-tower','A',Zone.BATTLEFIELD)
        self.activate(ref,'mana');self.assertEqual({'C':1},dict(self.state.mana_pool('A')))

    def test_gate_library_search_and_copied_definition(self):
        self.game();hidden=self.state.add_card('hidden','catalog:planar-nexus','A',Zone.LIBRARY)
        self.kernel.execute_for_scenario(self.ref,'A',(SearchLibrary(Selector(Zone.LIBRARY,types=('Land',),subtypes=('Gate',),relation='owned'),Zone.HAND),))
        self.assertEqual({hidden},{o.ref for o in self.kernel.pending_choice.options});self.answer()
        self.assertEqual(Zone.HAND,self.state.get(self.state.current('hidden')).zone)
        copy=self.state.add_card('copy','catalog:forest','B',Zone.HAND)
        self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,'B',copied_definition='catalog:planar-nexus'),),'scenario_copy')
        self.assertEqual(NONBASIC_LAND_TYPES,self.kernel.effective(self.state.current('copy')).subtypes)

    def test_type_removal_preserves_other_categories_and_additive_basic_types_work(self):
        body=CardProgram('body','Body',('Land','Creature'),power=1,toughness=1,all_subtype_sets=('creature','nonbasic_land'))
        strip=CardProgram('strip','Strip',('Enchantment',),continuous=(ContinuousProgram('strip',Selector(Zone.BATTLEFIELD,types=('Creature',)),(ChangeTypes(('Artifact',),('Land',)),)),))
        add=CardProgram('add','Add',('Enchantment',),continuous=(ContinuousProgram('forest',Selector(Zone.BATTLEFIELD,types=('Land',)),(AddSubtypes('Land',('Forest',)),)),))
        self.game(extra=(body,strip,add));ref=self.state.add_card('body','body','A',Zone.BATTLEFIELD)
        self.state.add_card('strip','strip','A',Zone.BATTLEFIELD);self.assertEqual(CREATURE_TYPES,self.kernel.effective(ref).subtypes)
        self.state.add_card('add','add','A',Zone.BATTLEFIELD)
        self.assertEqual(NONBASIC_LAND_TYPES|{'Forest'},self.kernel.effective(self.ref).subtypes)
        self.assertIn('intrinsic-land:Forest',{a.ability_id for a in self.kernel.activated_abilities(self.state.get(self.ref))})
        self.assertEqual(evaluate(self.state.objects(),self.kernel.definitions),evaluate_exhaustive(self.state.objects(),self.kernel.definitions))

    def test_named_set_validation_is_closed_and_immutable(self):
        base=CardProgram('land','Land',('Land',),all_subtype_sets=('nonbasic_land',))
        self.assertEqual(base,decode(encode(validate(base))))
        for sets in (['nonbasic_land'],('nonbasic_land','nonbasic_land'),('basic_land',),('creature',),True):
            with self.assertRaises(RulesViolation):validate(replace(base,all_subtype_sets=sets))

if __name__=='__main__':unittest.main()
