"""Remote conformance for mana capability queries and convoke payment."""
import json
import unittest
from dataclasses import replace
from pathlib import Path
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,RulesViolation,ObjectRef,Zone,ZoneMove
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed,digest,source_facts
from edh_gauntlet.catalog import load_catalog

CARDS=('exotic-orchard','fellwar-stone','horizon-of-progress','devouring-light')


class ManaConvokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        reviewed=load_reviewed(cls.root)
        drafts=json.loads((cls.root/'data/rules/draft_cards.json').read_text(encoding='utf-8'))['drafts']
        cls.rows={row['card_id']:row for row in drafts if row['card_id'] in CARDS}
        cls.cards={key:validate(decode(row['program'])) for key,row in cls.rows.items()}
        cls.base=tuple(row['program'] for row in reviewed.values())+tuple(cls.cards.values())

    def game(self,card='exotic-orchard',zone=Zone.BATTLEFIELD,extra=(),identities=None):
        body=CardProgram('m-body','Body',('Creature',),power=2,toughness=3,cast=CastSpec(CostSpec()))
        white=replace(body,definition_id='m-white',name='White',colors=('W',))
        green=replace(body,definition_id='m-green',name='Green',colors=('G',))
        both=replace(body,definition_id='m-both',name='Both',colors=('W','G'))
        black=replace(body,definition_id='m-black',name='Black',colors=('B',))
        blue=replace(body,definition_id='m-blue',name='Blue',colors=('U',))
        land=CardProgram('m-land','Land',('Land',))
        forest=replace(land,definition_id='m-forest',name='Forest',subtypes=('Forest',))
        island=replace(land,definition_id='m-island',name='Island',subtypes=('Island',))
        plain=replace(land,definition_id='m-plains',name='Plains',subtypes=('Plains',))
        colorless=replace(land,definition_id='m-colorless',name='Colorless',
            activated=(ActivatedProgram('mana',CostSpec(tap_source=True),(AddMana(('C',)),),mana_ability=True),))
        costly=replace(land,definition_id='m-costly',name='Costly',
            activated=(ActivatedProgram('mana',CostSpec(ManaCost(9),life=99,tap_source=True),(ChooseMana((('W',),('G',))),),mana_ability=True),))
        mana_creature=replace(green,definition_id='m-mana-creature',name='Mana creature',
            activated=(ActivatedProgram('mana',CostSpec(tap_source=True),(AddMana(('G',)),),mana_ability=True),))
        remove=CardProgram('m-remove','Remove',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD)),spell_effects=(Move('target',Zone.GRAVEYARD),))
        control=replace(remove,definition_id='m-control',name='Control',spell_effects=(GainControl('target'),))
        counter=replace(remove,definition_id='m-counter',name='Counter',spell_targets=TargetSpec(Selector(Zone.STACK)),spell_effects=(Counter(),))
        self.programs=self.base+(body,white,green,both,black,blue,land,forest,island,plain,colorless,costly,mana_creature,remove,control,counter)+extra
        self.state=RulesState(('A','B','C','D'),commander_identities=identities)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A');self.serial=0
        self.source=self.add(self.cards[card].definition_id,'A',zone)
        self.white=self.add('m-white');self.second=self.add('m-white');self.body=self.add('m-body');self.enemy=self.add('m-body','B')
        for player in self.state.players:
            for _ in range(10):self.add('m-body',player,Zone.LIBRARY)

    def ident(self):
        self.serial+=1
        return 'm-object-'+str(self.serial)

    def add(self,definition='m-body',actor='A',zone=Zone.BATTLEFIELD,**kw):
        return self.state.add_card(self.ident(),definition,actor,zone,**kw)

    def mana(self,symbols):
        return tuple((s,symbols.count(s)) for s in sorted(set(symbols)))

    def window(self,actor='A'):
        while self.kernel.priority!=actor:self.kernel.pass_priority(self.kernel.priority)

    def round(self):
        for _ in self.state.live_players:result=self.kernel.pass_priority(self.kernel.priority)
        return result

    def top(self):
        self.assertTrue(self.kernel.stack)
        return self.round()

    def choose(self,indexes):
        q=self.kernel.pending_choice;self.assertIsNotNone(q)
        return self.kernel.answer(q.request_id,q.actor,indexes)

    def color(self,symbol):
        q=self.kernel.pending_choice
        return self.choose([next(i for i,o in enumerate(q.options) if '{'+symbol+'}' in o.label)])

    def activate(self,ability='mana',source=None,mana='',actor='A'):
        source=self.source if source is None else source;self.window(actor)
        if mana:self.state.add_mana(actor,tuple(mana))
        quote=self.kernel.quote_activation(self.ident(),actor,source,ability)
        return self.kernel.commit_action(quote,Payment(self.mana(mana)))

    def cast(self,source=None,targets=(),mana='',convoke=(),actor='A',alternative=None):
        source=self.source if source is None else source;self.window(actor)
        if mana:self.state.add_mana(actor,tuple(mana))
        quote=self.kernel.quote_cast(self.ident(),actor,source,targets,alternative_id=alternative)
        return self.kernel.commit_action(quote,Payment(self.mana(mana),convoke=convoke))

    def fx(self,source,*effects):
        return self.kernel.execute_for_scenario(source,self.state.get(source).controller,effects)

    def attackers(self):
        self.kernel.begin_turn_for_scenario('B')
        for _ in range(4):self.round()
        self.assertEqual('declare_attackers',self.kernel.phase)
        self.kernel.declare_attackers('B',{self.enemy:'A'},revision=self.kernel.revision)
        self.window('A')

    def light(self,mana='',convoke=(),target=None):
        return self.cast(targets=(target or self.enemy,),mana=mana,convoke=convoke)

    def reject_payment(self,payment,target=None):
        self.window('A')
        quote=self.kernel.quote_cast(self.ident(),'A',self.source,(target or self.enemy,))
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,payment)
        self.assertEqual(before,self.kernel.snapshot())

    def restore(self):
        before=self.kernel.snapshot();kernel=RulesKernel.restore(before,self.programs)
        self.assertEqual(before,kernel.snapshot());self.kernel=kernel;self.state=kernel.state

    def test_all_four_source_bindings_and_complete_faces(self):
        catalog={c.card_id:c for c in load_catalog(self.root/'data/catalog/cards.json')}
        self.assertEqual(set(CARDS),set(self.cards))
        for key,program in self.cards.items():
            with self.subTest(card=key):
                self.assertEqual('draft:'+key,program.definition_id)
                self.assertEqual(digest(source_facts(catalog[key])),digest(self.rows[key]['source_facts']))
                self.assertEqual(program,validate(decode(encode(program))))
                face=catalog[key].faces[0]
                for attr in ('types','subtypes','supertypes','colors'):self.assertEqual(set(getattr(face,attr)),set(getattr(program,attr)))
                self.assertEqual(face.mana_value,program.mana_value)
        self.assertEqual(3,len(self.cards['horizon-of-progress'].activated))
        self.assertIsInstance(self.cards['devouring-light'].cast,ConvokeCast)
        self.assertEqual(ManaCost(1,('W','W')),self.cards['devouring-light'].cast.cost.mana)

    def test_orchard_no_opposing_lands_still_pays_tap(self):
        self.game();self.activate()
        self.assertTrue(self.state.get(self.source).tapped);self.assertEqual((),self.state.mana_pool('A'))
        self.assertIsNone(self.kernel.pending_choice);self.assertFalse(self.kernel.stack)

    def test_orchard_ignores_own_land_mana(self):
        self.game();self.add('m-forest')
        self.assertEqual((),self.kernel.land_mana_options(LandMana(),'A'));self.activate()
        self.assertEqual((),self.state.mana_pool('A'))

    def test_orchard_uses_any_opponents_land(self):
        self.game();self.add('m-forest','D');self.activate()
        self.assertEqual((('G',1),),self.state.mana_pool('A'))

    def test_orchard_cannot_make_colorless(self):
        self.game();self.add('m-colorless','B');self.activate()
        self.assertEqual((),self.state.mana_pool('A'))

    def test_orchard_offers_union_of_opponents_colors(self):
        self.game();self.add('m-forest','B');self.add('m-island','C');self.activate()
        self.assertEqual(2,len(self.kernel.pending_choice.options));self.color('U')
        self.assertEqual((('U',1),),self.state.mana_pool('A'))

    def test_orchard_ignores_tapped_and_unaffordable_costs(self):
        self.game();land=self.add('m-costly','B');self.state.set_tapped_batch((land,),True)
        before=self.kernel.snapshot();self.assertEqual(('W','G'),self.kernel.land_mana_options(LandMana(),'A'))
        self.assertEqual(before,self.kernel.snapshot());self.activate();self.color('G')
        self.assertEqual(40,self.state.life('B'));self.assertTrue(self.state.get(land).tapped)

    def test_orchard_does_not_copy_pain_land_damage(self):
        self.game();self.add('catalog:adarkar-wastes','B');self.activate();self.color('W')
        self.assertEqual(40,self.state.life('A'));self.assertEqual(40,self.state.life('B'))

    def test_orchard_ignores_nonland_mana_sources(self):
        self.game();self.add('m-mana-creature','B')
        self.assertEqual((),self.kernel.land_mana_options(LandMana(),'A'))

    def test_orchard_uses_derived_land_type(self):
        self.game();source=self.add('m-mana-creature','B')
        self.fx(source,UntilEndOfTurn('source',(ChangeTypes(add=('Land',)),)))
        self.assertEqual(('G',),self.kernel.land_mana_options(LandMana(),'A'))

    def test_orchard_uses_newly_granted_intrinsic_land_abilities(self):
        self.game();source=self.add('m-land','B')
        self.fx(source,UntilEndOfTurn('source',(AddSubtypes('Land',('Plains','Island')),)))
        self.assertEqual(('W','U'),self.kernel.land_mana_options(LandMana(),'A'))

    def test_orchard_uses_chromatic_lantern_grant(self):
        self.game();self.add('m-land','B');self.add('catalog:chromatic-lantern','B')
        self.assertEqual(tuple('WUBRG'),self.kernel.land_mana_options(LandMana(),'A'))

    def test_orchard_phased_land_is_unavailable(self):
        self.game();ref=self.add('m-forest','B');self.fx(ref,PhaseOut('source'))
        self.assertEqual((),self.kernel.land_mana_options(LandMana(),'A'))

    def test_orchard_tracks_control_changes_without_stale_cache(self):
        self.game();ref=self.add('m-forest','B')
        self.assertEqual(('G',),self.kernel.land_mana_options(LandMana(),'A'))
        self.state.change_control(ref,'A')
        self.assertEqual((),self.kernel.land_mana_options(LandMana(),'A'))

    def test_two_orchards_without_grounding_make_no_mana(self):
        self.game();self.add(self.cards['exotic-orchard'].definition_id,'B')
        self.assertTrue(all(not types for types in self.kernel.could_produce_mana().values()))
        self.activate();self.assertEqual((),self.state.mana_pool('A'))

    def test_orchard_recursive_chain_reaches_grounded_color(self):
        self.game();other=self.add(self.cards['exotic-orchard'].definition_id,'B');self.add('m-forest')
        table=self.kernel.could_produce_mana();self.assertEqual(frozenset('G'),table[self.source]);self.assertEqual(frozenset('G'),table[other])
        self.activate();self.assertEqual((('G',1),),self.state.mana_pool('A'))

    def test_orchard_long_dependency_cycle_converges(self):
        self.game();refs=[self.source]
        for actor in ('B','C','D'):
            refs.append(self.add(self.cards['exotic-orchard'].definition_id,actor))
        self.add('m-island','C');self.add('m-plains','D')
        table=self.kernel.could_produce_mana()
        for ref in refs:self.assertEqual(frozenset(('W','U')),table[ref])
        self.assertEqual(table,self.kernel.could_produce_mana())

    def test_unseeded_horizon_self_reference_makes_no_mana(self):
        self.game('horizon-of-progress');self.activate()
        self.assertEqual(39,self.state.life('A'));self.assertEqual((),self.state.mana_pool('A'))

    def test_horizon_self_reference_can_be_grounded_by_intrinsic_ability(self):
        self.game('horizon-of-progress');self.fx(self.source,UntilEndOfTurn('source',(AddSubtypes('Land',('Forest',)),)))
        self.activate();self.assertEqual((('G',1),),self.state.mana_pool('A'));self.assertEqual(39,self.state.life('A'))

    def test_horizon_can_make_colorless(self):
        self.game('horizon-of-progress');self.add('m-colorless');self.activate()
        self.assertEqual((('C',1),),self.state.mana_pool('A'))

    def test_horizon_excludes_only_opponents_production(self):
        self.game('horizon-of-progress');self.add('m-forest','B');self.activate()
        self.assertEqual((),self.state.mana_pool('A'));self.assertEqual(39,self.state.life('A'))

    def test_horizon_and_orchard_cycle_respects_colorless_filter(self):
        self.game('horizon-of-progress');other=self.add(self.cards['exotic-orchard'].definition_id,'B');self.add('m-colorless')
        table=self.kernel.could_produce_mana();self.assertEqual(frozenset('C'),table[self.source]);self.assertEqual(frozenset(),table[other])

    def test_fellwar_stone_cast_and_mana_activation(self):
        self.game('fellwar-stone',Zone.HAND);self.add('m-island','B');self.cast(mana='CC');self.top()
        self.source=self.state.current(self.source.card_id);self.activate()
        self.assertEqual((('U',1),),self.state.mana_pool('A'));self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.source).zone)

    def test_fellwar_stone_uses_shared_empty_colorless_rule(self):
        self.game('fellwar-stone');self.add('m-colorless','B');self.activate()
        self.assertEqual((),self.state.mana_pool('A'));self.assertTrue(self.state.get(self.source).tapped)

    def test_conditional_land_output_uses_current_branch(self):
        land=CardProgram('m-conditional','Conditional',('Land',),activated=(ActivatedProgram('mana',CostSpec(tap_source=True),
            (IfCondition(CountCondition(Selector(Zone.BATTLEFIELD,types=('Land',),relation='controlled'),2),(AddMana(('R',)),),(AddMana(('U',)),)),),mana_ability=True),))
        self.game(extra=(land,));self.add('m-conditional','B')
        self.assertEqual(('U',),self.kernel.land_mana_options(LandMana(),'A'));self.add('m-land','B')
        self.assertEqual(('R',),self.kernel.land_mana_options(LandMana(),'A'))

    def test_zero_quantity_does_not_claim_possible_colors(self):
        land=CardProgram('m-zero','Zero',('Land',),activated=(ActivatedProgram('mana',CostSpec(tap_source=True),
            (ProduceMana(SourceCounter('petal'),('R','G')),),mana_ability=True),))
        self.game(extra=(land,));ref=self.add('m-zero','B')
        self.assertEqual((),self.kernel.land_mana_options(LandMana(),'A'));self.state.add_counters(ref,'petal',1)
        self.assertEqual(('R','G'),self.kernel.land_mana_options(LandMana(),'A'))

    def test_baldurs_gate_needs_positive_other_gate_count(self):
        self.game();self.add('catalog:baldur-s-gate','B')
        self.assertEqual(('C',),tuple(sorted(self.kernel.could_produce_mana()[self.state.zone('B',Zone.BATTLEFIELD)[-1].ref])))
        self.assertEqual((),self.kernel.land_mana_options(LandMana(),'A'));self.add('catalog:simic-guildgate','B')
        self.assertEqual(tuple('WUBRG'),self.kernel.land_mana_options(LandMana(),'A'))

    def test_commander_identity_mana_is_read_without_inference(self):
        self.game(identities={'A':('W',),'B':('U','G'),'C':(),'D':()});self.add('catalog:command-tower','B')
        self.assertEqual(('U','G'),self.kernel.land_mana_options(LandMana(),'A'))

    def test_mana_multiplier_preserves_types_without_side_effects(self):
        self.game();self.add('m-forest','B');self.add('catalog:mana-reflection')
        before=self.kernel.snapshot();self.assertEqual(('G',),self.kernel.land_mana_options(LandMana(),'A'))
        self.assertEqual(before,self.kernel.snapshot());self.activate();self.assertEqual((('G',2),),self.state.mana_pool('A'))

    def test_triggered_land_mana_counts_without_triggering_it(self):
        land=CardProgram('m-trigger','Trigger',('Land',),abilities=(AbilityProgram('mana',EventPattern('card_drawn',controller_only=True),(AddMana(('B',)),)),))
        self.game(extra=(land,));self.add('m-trigger','B');before=self.kernel.snapshot()
        self.assertEqual(('B',),self.kernel.land_mana_options(LandMana(),'A'));self.assertEqual(before,self.kernel.snapshot())

    def test_targeted_land_ability_can_define_mana_type(self):
        land=CardProgram('m-targeted','Targeted',('Land',),activated=(ActivatedProgram('mana',CostSpec(),
            (AddMana(('R',)),),targets=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',))),mana_ability=False),))
        self.game(extra=(land,));self.add('m-targeted','B')
        self.assertEqual(('R',),self.kernel.land_mana_options(LandMana(),'A'))

    def test_capability_query_rejects_unimplemented_mutating_prefix(self):
        land=CardProgram('m-mutating','Mutating',('Land',),activated=(ActivatedProgram('mana',CostSpec(),
            (AddCounters('source','petal',1),ProduceMana(SourceCounter('petal'),('G',))),mana_ability=True),))
        self.game(extra=(land,));self.add('m-mutating','B');before=self.kernel.snapshot()
        with self.assertRaisesRegex(RulesViolation,'state-changing prefixes'):self.kernel.land_mana_options(LandMana(),'A')
        self.assertEqual(before,self.kernel.snapshot())

    def test_mana_choice_checkpoint_and_actor_replay(self):
        self.game();self.add('m-costly','B');self.activate();self.restore()
        adapter=RulesActorAdapter(self.kernel);q=self.kernel.pending_choice
        adapter.submit('A',{'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[0]})
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())

    def test_mana_choice_rejects_wrong_actor_and_option(self):
        self.game();self.add('m-costly','B');self.activate();q=self.kernel.pending_choice;before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.answer(q.request_id,'B',[0])
        with self.assertRaises(RulesViolation):self.kernel.answer(q.request_id,'A',[99])
        self.assertEqual(before,self.kernel.snapshot())

    def test_horizon_puts_optional_own_hand_land_tapped(self):
        self.game('horizon-of-progress');land=self.add('m-forest','A',Zone.HAND);self.activate('place-land',mana='CCC');self.top()
        q=self.kernel.pending_choice;self.choose([next(i for i,o in enumerate(q.options) if o.ref==land)])
        obj=self.state.get(self.state.current(land.card_id));self.assertEqual(Zone.BATTLEFIELD,obj.zone);self.assertTrue(obj.tapped)

    def test_horizon_can_decline_land_without_refunding_cost(self):
        self.game('horizon-of-progress');land=self.add('m-forest','A',Zone.HAND);self.activate('place-land',mana='CCC');self.top();self.choose([])
        self.assertEqual(Zone.HAND,self.state.get(land).zone);self.assertTrue(self.state.get(self.source).tapped);self.assertEqual((),self.state.mana_pool('A'))

    def test_horizon_empty_hand_resolves_without_choice(self):
        self.game('horizon-of-progress');self.activate('place-land',mana='CCC');self.top()
        self.assertIsNone(self.kernel.pending_choice);self.assertFalse(self.kernel.stack)

    def test_horizon_selection_excludes_other_hands_and_nonlands(self):
        self.game('horizon-of-progress');land=self.add('m-forest','A',Zone.HAND);self.add('m-forest','B',Zone.HAND);self.add('m-body','A',Zone.HAND)
        self.activate('place-land',mana='CCC');self.top()
        self.assertEqual([land],[o.ref for o in self.kernel.pending_choice.options])

    def test_horizon_land_choice_preserves_privacy_and_restore(self):
        self.game('horizon-of-progress');land=self.add('m-forest','A',Zone.HAND);self.activate('place-land',mana='CCC');self.top()
        self.assertNotIn(land.card_id,json.dumps(RulesActorAdapter(self.kernel).packet('B')));self.restore();self.choose([0])

    def test_horizon_sacrifices_as_cost_then_draws(self):
        self.game('horizon-of-progress');before=len(self.state.zone('A',Zone.HAND));self.activate('draw',mana='C')
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current(self.source.card_id)).zone)
        self.assertEqual(before,len(self.state.zone('A',Zone.HAND)));self.top()
        self.assertEqual(before+1,len(self.state.zone('A',Zone.HAND)))

    def test_horizon_countered_draw_keeps_sacrifice_and_payment(self):
        # CounterAbilities is tested through a real spell above the activation.
        stifle=CardProgram('m-stifle','Stifle',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),spell_effects=(CounterAbilities(),))
        # Use a fresh fixture with the complete registry; never mutate definitions.
        self.game('horizon-of-progress',extra=(stifle,));before=len(self.state.zone('A',Zone.HAND))
        self.activate('draw',mana='C');spell=self.add('m-stifle','B',Zone.HAND);self.cast(spell,actor='B');self.top()
        self.assertFalse(self.kernel.stack);self.assertEqual(before,len(self.state.zone('A',Zone.HAND)))
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current(self.source.card_id)).zone)

    def test_devouring_light_normal_mana_payment(self):
        self.game('devouring-light',Zone.HAND);self.attackers();self.light(mana='CWW');self.top()
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current(self.enemy.card_id)).zone)

    def test_devouring_light_all_convoke_makes_no_mana(self):
        self.game('devouring-light',Zone.HAND);self.attackers()
        self.light(convoke=((self.white,'W'),(self.second,'W'),(self.body,'generic')))
        for ref in (self.white,self.second,self.body):self.assertTrue(self.state.get(ref).tapped)
        self.assertEqual((),self.state.mana_pool('A'));self.top()
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current(self.enemy.card_id)).zone)

    def test_devouring_light_mixed_mana_and_convoke(self):
        self.game('devouring-light',Zone.HAND);self.attackers();self.light(mana='W',convoke=((self.white,'W'),(self.body,'generic')))
        self.assertFalse(self.state.get(self.second).tapped);self.top()

    def test_convoke_accepts_summoning_sick_creatures(self):
        self.game('devouring-light',Zone.HAND);self.attackers();fresh=self.add('m-white')
        self.assertFalse(self.state.ready_since_turn_start(fresh))
        self.light(mana='CW',convoke=((fresh,'W'),));self.assertTrue(self.state.get(fresh).tapped);self.top()

    def test_convoke_can_use_colorless_creature_for_generic(self):
        self.game('devouring-light',Zone.HAND);self.attackers();self.light(mana='WW',convoke=((self.body,'generic'),));self.top()

    def test_convoke_uses_derived_colors(self):
        self.game('devouring-light',Zone.HAND);self.fx(self.body,UntilEndOfTurn('source',(SetColors(('W',)),)));self.attackers()
        self.light(mana='CW',convoke=((self.body,'W'),));self.top()

    def test_convoke_rejects_wrong_color_atomically(self):
        self.game('devouring-light',Zone.HAND);self.attackers();self.state.add_mana('A',tuple('CW'))
        self.reject_payment(Payment(self.mana('CW'),convoke=((self.body,'W'),)))

    def test_convoke_rejects_duplicate_creature_atomically(self):
        self.game('devouring-light',Zone.HAND);self.attackers();self.state.add_mana('A',('C',))
        self.reject_payment(Payment(self.mana('C'),convoke=((self.white,'W'),(self.white,'W'))))

    def test_convoke_rejects_opponents_creature(self):
        self.game('devouring-light',Zone.HAND);self.attackers();enemy=self.add('m-white','B');self.state.add_mana('A',tuple('CW'))
        self.reject_payment(Payment(self.mana('CW'),convoke=((enemy,'W'),)))

    def test_convoke_rejects_tapped_or_phased_creatures(self):
        for phased in (False,True):
            with self.subTest(phased=phased):
                self.game('devouring-light',Zone.HAND)
                if phased:self.fx(self.white,PhaseOut('source'))
                else:self.state.set_tapped_batch((self.white,),True)
                self.attackers();self.state.add_mana('A',tuple('CW'))
                self.reject_payment(Payment(self.mana('CW'),convoke=((self.white,'W'),)))

    def test_convoke_rejects_noncreature_and_hidden_sources(self):
        for zone in (Zone.BATTLEFIELD,Zone.HAND):
            with self.subTest(zone=zone):
                self.game('devouring-light',Zone.HAND);ref=self.add('m-forest',zone=zone);self.attackers();self.state.add_mana('A',tuple('WW'))
                self.reject_payment(Payment(self.mana('WW'),convoke=((ref,'generic'),)))

    def test_convoke_rejects_underpayment_and_overpayment(self):
        for mana in ('W','CCWW'):
            with self.subTest(mana=mana):
                self.game('devouring-light',Zone.HAND);self.attackers();self.state.add_mana('A',tuple(mana))
                self.reject_payment(Payment(self.mana(mana),convoke=((self.white,'W'),)))

    def test_convoke_never_pays_colored_requirement_as_generic(self):
        self.game('devouring-light',Zone.HAND);self.attackers();self.state.add_mana('A',('W',))
        self.reject_payment(Payment(self.mana('W'),convoke=((self.body,'generic'),(self.white,'generic'))))

    def test_convoke_creature_cannot_also_pay_a_tap_cost(self):
        fixture=replace(self.cards['devouring-light'],definition_id='m-tap-spell',name='Tap spell',
            cast=ConvokeCast(CostSpec(ManaCost(1,('W','W')),tap_selector=Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled'),tap_count=1),timing='instant'))
        self.game('devouring-light',Zone.HAND,extra=(fixture,));self.source=self.add('m-tap-spell','A',Zone.HAND);self.attackers();self.state.add_mana('A',tuple('CW'))
        self.reject_payment(Payment(self.mana('CW'),taps=(self.white,),convoke=((self.white,'W'),)))

    def test_convoke_follows_final_cost_reduction(self):
        reducer=CardProgram('m-reducer','Reducer',('Enchantment',),cost_modifiers=(CostModifier('less',Selector(Zone.STACK,types=('Instant',),relation='controlled'),-1),))
        self.game('devouring-light',Zone.HAND,extra=(reducer,));self.add('m-reducer');self.attackers()
        self.light(convoke=((self.white,'W'),(self.second,'W')));self.top()

    def test_convoke_follows_final_cost_increase(self):
        tax=CardProgram('m-tax','Tax',('Enchantment',),cost_modifiers=(CostModifier('more',Selector(Zone.STACK,types=('Instant',),relation='opponent_controlled'),2),))
        self.game('devouring-light',Zone.HAND,extra=(tax,));self.add('m-tax','B');self.attackers()
        self.light(mana='CC',convoke=((self.white,'W'),(self.second,'W'),(self.body,'generic')));self.top()

    def test_convoke_works_with_alternative_cost(self):
        fixture=replace(self.cards['devouring-light'],definition_id='m-alternative',name='Alternative',
            cast=replace(self.cards['devouring-light'].cast,alternatives=(AlternativeCost('other',CostSpec(ManaCost(0,('W',)))),)))
        self.game('devouring-light',Zone.HAND,extra=(fixture,));self.source=self.add('m-alternative','A',Zone.HAND);self.attackers()
        self.cast(targets=(self.enemy,),convoke=((self.white,'W'),),alternative='other');self.top()

    def test_convoke_hybrid_cost_uses_existing_color_solver(self):
        fixture=replace(self.cards['devouring-light'],definition_id='m-hybrid',name='Hybrid',
            cast=ConvokeCast(CostSpec(ManaCost(0,('W/U','U/B'))),timing='instant'))
        self.game('devouring-light',Zone.HAND,extra=(fixture,));self.source=self.add('m-hybrid','A',Zone.HAND);black=self.add('m-black');self.attackers()
        self.light(convoke=((self.white,'W'),(black,'B')));self.top()

    def test_convoke_cannot_pay_explicit_colorless_symbol(self):
        fixture=replace(self.cards['devouring-light'],definition_id='m-colorless-spell',name='Colorless spell',
            cast=ConvokeCast(CostSpec(ManaCost(1,('C',))),timing='instant'))
        self.game('devouring-light',Zone.HAND,extra=(fixture,));self.source=self.add('m-colorless-spell','A',Zone.HAND);self.attackers()
        self.reject_payment(Payment(convoke=((self.white,'W'),(self.body,'generic'))))

    def test_nonconvoke_spell_rejects_creature_payment(self):
        self.game('devouring-light',Zone.HAND);self.source=self.add('m-remove','A',Zone.HAND);self.attackers()
        self.reject_payment(Payment(convoke=((self.body,'generic'),)))

    def test_activation_rejects_convoke(self):
        self.game('horizon-of-progress');self.state.add_mana('A',tuple('CC'))
        quote=self.kernel.quote_activation(self.ident(),'A',self.source,'place-land');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,Payment(self.mana('CC'),convoke=((self.body,'generic'),)))
        self.assertEqual(before,self.kernel.snapshot())

    def test_convoke_keeps_taps_when_spell_is_countered(self):
        self.game('devouring-light',Zone.HAND);self.attackers();self.light(convoke=((self.white,'W'),(self.second,'W'),(self.body,'generic')))
        stack_source=self.state.current(self.source.card_id);counter=self.add('m-counter','B',Zone.HAND)
        self.cast(counter,targets=(stack_source,),actor='B');self.top()
        self.assertTrue(self.state.get(self.white).tapped);self.assertFalse(self.kernel.stack)

    def test_light_rejects_noncombat_target_before_payment(self):
        self.game('devouring-light',Zone.HAND);before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_cast(self.ident(),'A',self.source,(self.enemy,))
        self.assertEqual(before,self.kernel.snapshot())

    def test_light_can_target_a_blocker_that_convokes_it(self):
        self.game('devouring-light',Zone.HAND);self.attackers()
        while self.kernel.priority is not None:self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual('declare_blockers',self.kernel.phase)
        from edh_gauntlet.rules_combat import uid
        self.kernel.declare_blockers('A',{uid(self.enemy):[uid(self.white)]},revision=self.kernel.revision)
        self.light(target=self.white,mana='CW',convoke=((self.white,'W'),));self.top()
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current(self.white.card_id)).zone)

    def test_light_rechecks_departed_target_without_refunding_convoke(self):
        self.game('devouring-light',Zone.HAND);self.attackers();self.light(mana='CW',convoke=((self.white,'W'),))
        removal=self.add('m-remove','B',Zone.HAND);self.cast(removal,targets=(self.enemy,),actor='B');self.top();self.top()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current(self.enemy.card_id)).zone);self.assertTrue(self.state.get(self.white).tapped)

    def test_convoke_cast_checkpoint_and_actor_replay(self):
        self.game('devouring-light',Zone.HAND);self.attackers();self.state.add_mana('A',tuple('CW'))
        adapter=RulesActorAdapter(self.kernel)
        self.assertTrue(next(row for row in adapter.packet('A')['hand'] if row['ref']==self.source.to_json())['convoke'])
        adapter.submit('A',{'kind':'cast','revision':self.kernel.revision,'action_id':'convoke-replay','source':self.source.to_json(),
            'targets':[self.enemy.to_json()],'x_value':0,'payment':{'mana':{'C':1,'W':1},'taps':[],'convoke':[{'ref':self.white.to_json(),'color':'W'}]}})
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot());self.restore()
        receipt=self.kernel.action_receipts['convoke-replay']
        self.assertEqual([{'ref':self.white.to_json(),'color':'W'}],receipt['payment']['convoke'])

    def test_actor_rejects_hidden_convoke_reference_without_revealing_identity(self):
        self.game('devouring-light',Zone.HAND);hidden=self.add('m-white','B',Zone.HAND);self.attackers();self.state.add_mana('A',tuple('CW'))
        adapter=RulesActorAdapter(self.kernel);before=self.kernel.snapshot()
        with self.assertRaisesRegex(RulesViolation,'not visible'):
            adapter.submit('A',{'kind':'cast','revision':self.kernel.revision,'action_id':'bad-hidden','source':self.source.to_json(),
                'targets':[self.enemy.to_json()],'x_value':0,'payment':{'mana':{'C':1,'W':1},'taps':[],'convoke':[{'ref':hidden.to_json(),'color':'W'}]}})
        self.assertEqual(before,self.kernel.snapshot());self.assertNotIn(hidden.card_id,json.dumps(adapter.packet('A')))

    def test_payment_codec_retains_convoke_and_legacy_shape(self):
        ref=ObjectRef('visible',0);payment=Payment((('W',1),),convoke=((ref,'generic'),))
        self.assertEqual(payment,Payment.from_json(payment.to_json()))
        self.assertEqual(Payment(),Payment.from_json({'mana':{},'taps':[]}))

    def test_payment_rejects_malformed_convoke_packets(self):
        for rows in ({},[{}],[{'ref':{},'color':'W','extra':1}]):
            with self.subTest(rows=rows),self.assertRaises(RulesViolation):Payment.from_json({'mana':{},'taps':[],'convoke':rows})

    def test_compiler_rejects_bad_land_mana_query_and_classification(self):
        for effect in (LandMana('owned'),LandMana('controlled',1),LandMana([],True)):
            with self.subTest(effect=effect),self.assertRaises(RulesViolation):
                validate(CardProgram('bad','Bad',('Land',),activated=(ActivatedProgram('mana',CostSpec(),(effect,),mana_ability=True),)))
        with self.assertRaises(RulesViolation):
            validate(CardProgram('bad','Bad',('Land',),activated=(ActivatedProgram('mana',CostSpec(),(LandMana(),),mana_ability=False),)))

    def test_checkpoint_identity_rejects_prior_kernel_layout(self):
        self.game();checkpoint=self.kernel.snapshot();self.assertEqual(122,checkpoint['schema']);self.assertEqual(14,checkpoint['state']['schema'])
        checkpoint['schema']=121
        with self.assertRaises(RulesViolation):RulesKernel.restore(checkpoint,self.programs)
        from edh_gauntlet.rules_identity import IMPLEMENTATION_MANIFEST
        self.assertIn('rules_mana.py',IMPLEMENTATION_MANIFEST['modules'])
