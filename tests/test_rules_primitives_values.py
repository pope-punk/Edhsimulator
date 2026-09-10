"""Resolution-time quantities and action-bound X share one closed evaluator."""
import json
import unittest
from edh_gauntlet.rules_program import (CardProgram,ActivatedProgram,AbilityProgram,EventPattern,CostSpec,ManaCost,CastSpec,
    ZoneCost,Selector,TargetSpec,ChosenX,CountObjects,ScaledValue,ProduceMana,Draw,GainLife,Damage,AddCounters,
    May,AddMana,ZoneReplacement,encode,decode,validate)
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed


class QuantityTests(unittest.TestCase):
    def setup_activation(self,effects,*,cost=CostSpec(),mana=False,extra=()):
        self.program=CardProgram('source','Source',('Artifact',),activated=(ActivatedProgram('use',cost,effects,mana_ability=mana),))
        self.programs=(self.program,*extra);self.state=RulesState(('A','B'))
        self.ref=self.state.add_card('source','source','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def activate(self,x=0,mana=()):
        quote=self.kernel.quote_activation('use','A',self.ref,'use',x_value=x)
        return self.kernel.commit_action(quote,Payment(mana))

    def resolve(self):
        self.kernel.pass_priority('A');return self.kernel.pass_priority('B')

    def test_x_is_bound_to_ability_and_survives_sacrificed_source_and_checkpoint(self):
        self.setup_activation((May((GainLife(ScaledValue(ChosenX(),2)),)),),
            cost=CostSpec(ManaCost(x_symbols=1),zone_costs=(ZoneCost('sac','sacrifice'),)))
        self.state.add_mana('A',('C',)*3);self.activate(3,(('C',3),))
        self.assertEqual(0,self.kernel.stack[-1]['source']['cast_x'])
        self.assertEqual(3,self.kernel.stack[-1]['chosen_x'])
        self.assertEqual(3,RulesActorAdapter(self.kernel).packet('B')['stack'][0]['chosen_x'])
        request=self.resolve();restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.kernel.answer(request.request_id,'A',[0]);restored.answer(request.request_id,'A',[0])
        self.assertEqual(46,self.state.life('A'));self.assertEqual(self.kernel.snapshot(),restored.snapshot())

    def test_x_spell_damage_and_life_use_announced_value(self):
        spell=CardProgram('spell','Spell',('Instant',),cast=CastSpec(CostSpec(ManaCost(x_symbols=2)),'instant'),
            spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',))),
            spell_effects=(Damage('target',ChosenX()),GainLife(ChosenX())))
        creature=CardProgram('creature','Creature',('Creature',),power=1,toughness=10)
        state=RulesState(('A','B'));source=state.add_card('spell','spell','A',Zone.HAND);target=state.add_card('target','creature','B',Zone.BATTLEFIELD)
        kernel=RulesKernel(state,(spell,creature));kernel.open_window_for_scenario('A');state.add_mana('A',('C',)*8)
        kernel.commit_action(kernel.quote_cast('cast','A',source,(target,),x_value=4),Payment((('C',8),)))
        kernel.pass_priority('A');kernel.pass_priority('B')
        self.assertEqual(4,state.get(target).damage_marked);self.assertEqual(44,state.life('A'))
        self.assertEqual(0,state.get(state.current('spell')).cast_x)

    def test_count_is_evaluated_at_resolution_after_paid_sacrifice(self):
        count=CountObjects(Selector(Zone.BATTLEFIELD,types=('Artifact',)))
        self.setup_activation((ProduceMana(count,('G',)),),cost=CostSpec(zone_costs=(ZoneCost('sac','sacrifice'),)),mana=True)
        self.activate();self.assertEqual((),self.state.mana_pool('A'))
        self.assertFalse(any(e['kind']=='mana_added' for e in self.kernel.semantic_events))

    def test_count_uses_current_board_at_each_instruction(self):
        creature=CardProgram('creature','Creature',('Creature',),power=1,toughness=4)
        count=CountObjects(Selector(Zone.BATTLEFIELD,types=('Creature',)))
        self.setup_activation((GainLife(count),),extra=(creature,));self.activate()
        self.state.add_card('late','creature','B',Zone.BATTLEFIELD)
        self.resolve();self.assertEqual(41,self.state.life('A'))

    def test_variable_draw_is_classified_as_nonmana_and_fixed_before_draw_replacements(self):
        replacement=CardProgram('replacement','Replacement',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.HAND,Zone.EXILE,from_zone=Zone.LIBRARY,optional=True),))
        count=CountObjects(Selector(Zone.BATTLEFIELD))
        self.setup_activation((AddMana(('G',)),Draw(count)),extra=(replacement,))
        self.state.add_card('replacement','replacement','B',Zone.BATTLEFIELD)
        for i in range(3):self.state.add_card(str(i),'source','A',Zone.LIBRARY)
        self.activate();request=self.resolve()
        # Two draws were fixed before the first replacement decision, not re-counted per card.
        while request:
            request=self.kernel.answer(request.request_id,'A',[1])
        self.assertEqual(2,len(self.state.zone('A',Zone.HAND)))
        self.assertEqual(1,len(self.state.zone('A',Zone.LIBRARY)))

    def test_x_counter_amount_and_zero_are_not_false_counter_events(self):
        for x in (0,3):
            self.setup_activation((AddCounters('source','charge',ChosenX()),),cost=CostSpec(ManaCost(x_symbols=1)))
            if x:self.state.add_mana('A',('C',)*x)
            self.activate(x,(('C',x),) if x else ());self.resolve()
            self.assertEqual((('charge',x),) if x else (),self.state.get(self.ref).counters)
            self.assertEqual(int(x>0),sum(e['kind']=='counters_added' for e in self.kernel.semantic_events))

    def test_large_mana_choice_is_compact_and_replays_once(self):
        self.setup_activation((ProduceMana(ScaledValue(ChosenX(),10000),tuple('WUBRG')),),cost=CostSpec(ManaCost(x_symbols=1)),mana=True)
        self.state.add_mana('A',('C',));adapter=RulesActorAdapter(self.kernel)
        packet=adapter.submit('A',{'kind':'activate','revision':self.kernel.revision,'action_id':'large','source':self.ref.to_json(),
            'ability_id':'use','targets':[],'x_value':1,'payment':{'mana':{'C':1},'taps':[]}})
        request=packet['decision']['choice'];self.assertLess(len(json.dumps(request)),2000)
        pending=adapter.archive();restored=RulesActorAdapter.replay(pending,self.programs)
        command={'kind':'answer','revision':self.kernel.revision,'request_id':request['request_id'],'indexes':[3]}
        adapter.submit('A',command);restored.submit('A',command)
        self.assertEqual((('R',10000),),self.state.mana_pool('A'));self.assertEqual(adapter.archive(),restored.archive())
        self.assertEqual([],self.kernel.stack);self.assertEqual('A',self.kernel.priority)

    def test_invalid_quantities_and_unbound_x_fail_during_compilation(self):
        for value in (True,-1,'x',ScaledValue(1,-1),ScaledValue(1,True),CountObjects(Selector(Zone.HAND))):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),spell_effects=(Draw(value),)))
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),spell_effects=(Draw(ChosenX()),)))
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Enchantment',),abilities=(AbilityProgram('etb',EventPattern('zone_changed',to_zone=Zone.BATTLEFIELD,subject='self'),(GainLife(ChosenX()),)),)))
        for options in ((),('G','G'),('X',),('GG',)):
            with self.assertRaises(RulesViolation):self.setup_activation((ProduceMana(1,options),),mana=True)
        value=1
        for _ in range(18):value=ScaledValue(value,1)
        with self.assertRaises(RulesViolation):self.setup_activation((GainLife(value),))
        value=ScaledValue(CountObjects(Selector(Zone.BATTLEFIELD)),2)
        self.assertEqual(value,decode(encode(value)))


class AuthoredCountManaTests(unittest.TestCase):
    def setup_card(self,key,zone=Zone.BATTLEFIELD):
        self.programs=tuple(r['program'] for r in load_reviewed().values())
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('source','catalog:'+key,'A',zone)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')

    def activate(self,ability='mana',mana=()):
        return self.kernel.commit_action(self.kernel.quote_activation('one','A',self.ref,ability),Payment(mana))

    def test_priest_counts_all_elves_including_self_but_not_phased_or_departed(self):
        self.setup_card('priest-of-titania')
        self.state.start_turn('A')
        self.state.add_card('opponent','catalog:llanowar-elves','B',Zone.BATTLEFIELD)
        phased=self.state.add_card('phased','catalog:elvish-mystic','A',Zone.BATTLEFIELD);self.state.phase(phased,True)
        self.state.add_card('grave','catalog:fyndhorn-elves','A',Zone.GRAVEYARD)
        self.activate();self.assertEqual((('G',2),),self.state.mana_pool('A'))
        self.assertTrue(self.state.get(self.ref).tapped);self.assertEqual([],self.kernel.stack)

    def test_cloudpost_entry_and_opponent_locus_count(self):
        self.setup_card('cloudpost',Zone.HAND);self.kernel.enter(self.ref)
        self.ref=self.state.current('source');self.assertTrue(self.state.get(self.ref).tapped)
        self.kernel.open_window_for_scenario('A');self.state.start_turn('A')
        self.state.add_card('other','catalog:cloudpost','B',Zone.BATTLEFIELD)
        self.activate();self.assertEqual((('C',2),),self.state.mana_pool('A'))

    def test_baldurs_gate_entry_threshold_and_owned_other_gate_mana(self):
        for count in (1,2):
            self.setup_card('baldur-s-gate',Zone.HAND)
            for i in range(count):self.state.add_card('gate'+str(i),'catalog:simic-guildgate','A',Zone.BATTLEFIELD)
            self.state.add_card('enemy','catalog:simic-guildgate','B',Zone.BATTLEFIELD)
            self.kernel.enter(self.ref);self.ref=self.state.current('source')
            self.assertEqual(count<2,self.state.get(self.ref).tapped)
            self.kernel.open_window_for_scenario('A');self.state.start_turn('A');self.state.add_mana('A',('C','C'))
            request=self.activate('gate-mana',(('C',2),));self.assertEqual(5,len(request.options))
            self.kernel.answer(request.request_id,'A',[0]);self.assertEqual((('W',count),),self.state.mana_pool('A'))
