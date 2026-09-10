"""Mana classification concerns immediate effects, not card names or future triggers."""
import unittest
from edh_gauntlet.rules_program import (CardProgram,ActivatedProgram,CostSpec,AddMana,GainLife,Draw,
    May,DelayedTrigger,EventPattern,ChooseCommanderMana,validate,activation_is_mana)
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter


class ManaEffectTests(unittest.TestCase):
    def game(self,effects,cost=CostSpec(tap_source=True),mana=True):
        self.program=CardProgram('rock','Rock',('Artifact',),activated=(ActivatedProgram('use',cost,effects,mana_ability=mana),))
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('rock','rock','B',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,(self.program,));self.kernel.open_window_for_scenario('A',priority_actor='B')

    def activate(self):return self.kernel.commit_action(self.kernel.quote_activation('one','B',self.ref,'use'),Payment())

    def test_mana_and_life_resolve_before_sba_and_keep_nonactive_priority(self):
        self.game((AddMana(('C',)),GainLife(1)),CostSpec(life=40,tap_source=True))
        self.assertIsNone(self.activate());self.assertEqual(1,self.state.life('B'))
        self.assertEqual((('C',1),),self.state.mana_pool('B'))
        self.assertEqual(('A','B'),self.state.live_players);self.assertEqual([],self.kernel.stack)
        self.assertEqual('B',self.kernel.priority)
        kinds=[e['kind'] for e in self.kernel.semantic_events]
        self.assertLess(kinds.index('ability_activated'),kinds.index('mana_added'))
        self.assertLess(kinds.index('mana_added'),kinds.index('life_gained'))

    def test_optional_mana_branch_resumes_in_place_without_stack(self):
        self.game((May((AddMana(('G',)),GainLife(2))),))
        request=self.activate();restored=RulesKernel.restore(self.kernel.snapshot(),(self.program,))
        self.assertEqual([],self.kernel.stack);self.assertEqual(40,self.state.life('B'))
        self.kernel.answer(request.request_id,'B',[0]);restored.answer(request.request_id,'B',[0])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual(42,self.state.life('B'));self.assertEqual('B',self.kernel.priority)

    def test_nested_commander_identity_is_checked_before_payment(self):
        self.game((May((ChooseCommanderMana(),)),));before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.activate()
        self.assertEqual(before,self.kernel.snapshot())

    def test_library_movement_makes_activation_nonmana(self):
        self.game((AddMana(('G',)),Draw()),mana=False)
        self.state.add_card('draw','rock','B',Zone.LIBRARY)
        self.activate();self.assertEqual((),self.state.mana_pool('B'))
        self.assertEqual(1,len(self.kernel.stack))
        self.kernel.pass_priority('B');self.kernel.pass_priority('A')
        self.assertEqual((('G',1),),self.state.mana_pool('B'))
        self.assertEqual(Zone.HAND,self.state.get(self.state.current('draw')).zone)
        with self.assertRaises(RulesViolation):self.game((AddMana(('G',)),Draw()),mana=True)

    def test_future_delayed_effect_does_not_classify_creating_activation(self):
        delayed_mana=DelayedTrigger(EventPattern('zone_changed',from_zone=Zone.BATTLEFIELD,subject='self'),(AddMana(('G',)),))
        self.game((delayed_mana,),mana=False)
        self.assertFalse(activation_is_mana(self.program.activated[0]))
        self.activate();self.assertEqual(1,len(self.kernel.stack))
        delayed_draw=DelayedTrigger(EventPattern('zone_changed',from_zone=Zone.BATTLEFIELD,subject='self'),(Draw(),))
        self.game((AddMana(('G',)),delayed_draw))
        self.assertIsNone(self.activate());self.assertEqual(1,len(self.kernel.delayed_triggers))
        self.assertEqual((('G',1),),self.state.mana_pool('B'))

    def test_lifegain_only_cannot_be_flagged_as_mana(self):
        with self.assertRaises(RulesViolation):self.game((GainLife(1),))

    def test_pure_mana_fast_path_emits_the_same_production_event(self):
        self.game((AddMana(('C','C')),));self.activate()
        events=[e for e in self.kernel.semantic_events if e['kind']=='mana_added']
        self.assertEqual(1,len(events));self.assertEqual(['C','C'],events[0]['symbols'])
        self.assertEqual('B',events[0]['player'])

    def test_pristine_talisman_completes_before_pridemate_trigger_placement(self):
        from edh_gauntlet.rules_bundle import load_reviewed
        programs=tuple(r['program'] for r in load_reviewed().values())
        state=RulesState(('A','B'));ref=state.add_card('talisman','catalog:pristine-talisman','B',Zone.BATTLEFIELD)
        cat=state.add_card('cat','catalog:ajani-s-pridemate','B',Zone.BATTLEFIELD)
        kernel=RulesKernel(state,programs);kernel.open_window_for_scenario('A',priority_actor='B')
        adapter=RulesActorAdapter(kernel)
        adapter.submit('B',{'kind':'activate','revision':kernel.revision,'action_id':'mana','source':ref.to_json(),
                           'ability_id':'mana','targets':[],'x_value':0,'payment':{'mana':{},'taps':[]}})
        self.assertEqual(41,state.life('B'));self.assertEqual((('C',1),),state.mana_pool('B'))
        self.assertEqual(1,len(kernel.stack));self.assertEqual(cat.card_id,kernel.stack[0]['source']['ref']['card_id'])
        self.assertEqual((),state.get(cat).counters);self.assertEqual('B',kernel.priority)
        for actor in ('B','A'):adapter.submit(actor,{'kind':'pass','revision':kernel.revision})
        self.assertEqual((('+1/+1',1),),state.get(cat).counters)
        restored=RulesActorAdapter.replay(adapter.archive(),programs)
        self.assertEqual(kernel.snapshot(),restored.kernel.snapshot())

    def test_raw_library_selection_cannot_bypass_search_visibility(self):
        from edh_gauntlet.rules_program import Select,Selector
        with self.assertRaisesRegex(RulesViolation,'visibility'):
            self.game((Select(Selector(Zone.LIBRARY),0,1,(GainLife(1),)),),mana=False)

    def test_controller_damage_uses_damage_pipeline_including_lifelink(self):
        from dataclasses import replace
        from edh_gauntlet.rules_program import Damage
        self.game((AddMana(('G',)),Damage('controller',1)))
        self.program=replace(self.program,keywords=('lifelink',))
        self.kernel=RulesKernel(self.state,(self.program,));self.kernel.open_window_for_scenario('A',priority_actor='B')
        self.activate();self.assertEqual(40,self.state.life('B'))
        events=self.kernel.semantic_events
        self.assertEqual(1,len([e for e in events if e['kind']=='damage_dealt']))
        self.assertEqual(1,len([e for e in events if e['kind']=='life_gained']))

    def test_lethal_mana_damage_finishes_ability_before_player_loss(self):
        from edh_gauntlet.rules_program import Damage,ChooseMana
        self.game((ChooseMana((('G',),('U',))),Damage('controller',1)),CostSpec(life=39,tap_source=True))
        request=self.activate();self.assertEqual(1,self.state.life('B'))
        self.assertEqual(('A','B'),self.state.live_players)
        result=self.kernel.answer(request.request_id,'B',[0]);self.assertEqual(('A',),result.winners)
        kinds=[e['kind'] for e in self.kernel.semantic_events]
        self.assertLess(kinds.index('mana_added'),kinds.index('damage_dealt'))

    def test_authored_pain_sources_keep_free_and_damaging_modes_distinct(self):
        from edh_gauntlet.rules_bundle import load_reviewed
        programs=tuple(r['program'] for r in load_reviewed().values())
        keys=('adarkar-wastes','caves-of-koilos','karplusan-forest','yavimaya-coast',
              'talisman-of-dominance','talisman-of-hierarchy','talisman-of-progress')
        for key in keys:
            for ability in ('colorless','colored'):
                state=RulesState(('A','B'));ref=state.add_card('mana','catalog:'+key,'A',Zone.BATTLEFIELD)
                kernel=RulesKernel(state,programs);kernel.open_window_for_scenario('A');adapter=RulesActorAdapter(kernel)
                packet=adapter.submit('A',{'kind':'activate','revision':kernel.revision,'action_id':'mana','source':ref.to_json(),
                    'ability_id':ability,'targets':[],'x_value':0,'payment':{'mana':{},'taps':[]}})
                self.assertEqual(40,state.life('A'));self.assertTrue(state.get(ref).tapped)
                if ability=='colored':
                    self.assertEqual((),state.mana_pool('A'));request=packet['decision']['choice']
                    self.assertEqual(2,len(request['options']))
                    adapter.submit('A',{'kind':'answer','revision':kernel.revision,'request_id':request['request_id'],'indexes':[1]})
                    self.assertEqual(39,state.life('A'))
                else:self.assertEqual((('C',1),),state.mana_pool('A'))
                self.assertEqual([],kernel.stack);self.assertEqual(1,len(kernel.action_receipts))
                restored=RulesActorAdapter.replay(adapter.archive(),programs)
                self.assertEqual(kernel.snapshot(),restored.kernel.snapshot())
