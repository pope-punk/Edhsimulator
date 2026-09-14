"""Hosted conformance for overload, monstrous transitions, eternalize and Finale."""
import json
import unittest
from dataclasses import replace
from pathlib import Path
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,RulesViolation,Zone,ZoneMove
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_actor import project_actor
from edh_gauntlet.rules_bundle import load_reviewed,digest,source_facts
from edh_gauntlet.catalog import load_catalog

CARDS=('fangs-of-kalonia','hydra-broodmaster','fanatic-of-rhonas','finale-of-revelation')


class TransitionCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        reviewed=load_reviewed(cls.root)
        drafts=json.loads((cls.root/'data/rules/draft_cards.json').read_text(encoding='utf-8'))['drafts']
        cls.rows={r['card_id']:r for r in drafts if r['card_id'] in CARDS}
        cls.cards={key:validate(decode(cls.rows[key]['program'])) for key in CARDS}
        cls.base=tuple(r['program'] for r in reviewed.values())+tuple(cls.cards.values())

    def game(self,card='fangs-of-kalonia',zone=Zone.HAND,extra=()):
        body=CardProgram('tr-body','Body',('Creature',),subtypes=('Elf',),colors=('G',),power=2,toughness=3)
        large=replace(body,definition_id='tr-large',name='Large',power=4,toughness=4)
        warded=replace(body,definition_id='tr-shroud',name='Shroud',keywords=('shroud',))
        remove=CardProgram('tr-remove','Remove',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD)),spell_effects=(Move('target',Zone.GRAVEYARD),))
        counter=CardProgram('tr-counter','Counter',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.STACK)),spell_effects=(Counter(),))
        stop=CardProgram('tr-stop','Stop abilities',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_effects=(CounterAbilities(),))
        self.programs=self.base+(body,large,warded,remove,counter,stop)+extra
        self.state=RulesState(('A','B','C','D'),seed=29);self.kernel=RulesKernel(self.state,self.programs)
        self.serial=0;self.source=self.add(self.cards[card].definition_id,'A',zone)
        self.body=self.add();self.enemy=self.add(actor='B')
        for player in self.state.players:
            for _ in range(20):self.add('catalog:forest',player,Zone.LIBRARY)
        self.state.start_turn('A');self.kernel.open_window_for_scenario('A')

    def add(self,definition='tr-body',actor='A',zone=Zone.BATTLEFIELD,**kw):
        self.serial+=1
        return self.state.add_card('tr-object-'+str(self.serial),definition,actor,zone,**kw)

    def window(self,actor='A'):
        if not self.kernel.stack and self.kernel.turn_schedule is None:
            self.kernel.open_window_for_scenario(self.kernel.active,phase=self.kernel.phase,priority_actor=actor)
        while self.kernel.priority!=actor:self.kernel.pass_priority(self.kernel.priority)

    def round(self):
        for _ in self.state.live_players:result=self.kernel.pass_priority(self.kernel.priority)
        return result

    def drain(self):
        for _ in range(600):
            q=self.kernel.pending_choice
            if q:
                self.kernel.answer(q.request_id,q.actor,list(range(len(q.options))) if q.kind=='trigger_order' else list(range(q.minimum)))
            elif self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
            else:return
        self.fail('No idle resolution boundary')

    def pay(self,mana):
        return Payment(tuple((s,mana.count(s)) for s in sorted(set(mana))))

    def cast(self,targets=(),source=None,mana='CG',alternative=None,x=0):
        source=self.source if source is None else source;self.window()
        if mana:self.state.add_mana('A',tuple(mana))
        self.serial+=1
        quote=self.kernel.quote_cast('tr-cast-'+str(self.serial),'A',source,targets,alternative_id=alternative,x_value=x)
        return self.kernel.commit_action(quote,self.pay(mana))

    def activate(self,ability='monstrosity',source=None,mana='G',x=0):
        source=self.source if source is None else source;self.window()
        if mana:self.state.add_mana('A',tuple(mana))
        self.serial+=1
        quote=self.kernel.quote_activation('tr-act-'+str(self.serial),'A',source,ability,(),x_value=x)
        return self.kernel.commit_action(quote,self.pay(mana))

    def fx(self,source,*effects):
        return self.kernel.execute_for_scenario(source,self.state.get(source).controller,effects)

    def respond(self,definition,targets=()):
        self.cast(targets,self.add(definition,'A',Zone.HAND),mana='');self.round()

    def restore(self):
        before=self.kernel.snapshot();self.kernel=RulesKernel.restore(before,self.programs);self.state=self.kernel.state
        self.assertEqual(before,self.kernel.snapshot())

    def counts(self,ref):return dict(self.state.get(ref).counters).get('+1/+1',0)
    def zone(self,ref):return self.state.get(self.state.current(ref.card_id)).zone
    def tokens(self):return tuple(o for o in self.state.objects(Zone.BATTLEFIELD) if o.token)
    def hand(self,actor='A'):return self.state.objects(Zone.HAND,owner=actor)

    def replacement(self,identity='tr-double',multiplier=2,divisor=1,additional=0):
        return CardProgram(identity,identity,('Enchantment',),counter_replacements=(
            CounterReplacement('counters',Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled'),
                kind='+1/+1',multiplier=multiplier,divisor=divisor,additional=additional),))

    def test_source_faces_and_corrected_hydra_cost_are_bound(self):
        catalog={c.card_id:c for c in load_catalog(self.root/'data/catalog/cards.json')}
        for key,p in self.cards.items():
            self.assertEqual('draft:'+key,p.definition_id)
            self.assertEqual(digest(source_facts(catalog[key])),self.rows[key]['source_facts_sha256'])
            self.assertEqual(p,validate(decode(encode(p))))
        self.assertEqual(ManaCost(4,('G','G')),self.cards['hydra-broodmaster'].cast.cost.mana)
        self.assertEqual('{4}{G}{G}',catalog['hydra-broodmaster'].faces[0].mana_cost)
        self.assertEqual((1,4),(self.cards['fanatic-of-rhonas'].power,self.cards['fanatic-of-rhonas'].toughness))

    def test_fangs_places_then_doubles_existing_counters_only_on_target(self):
        self.game();self.state.add_counters(self.body,'+1/+1',3);self.state.add_counters(self.enemy,'+1/+1',2)
        self.cast((self.body,));self.drain()
        self.assertEqual(8,self.counts(self.body));self.assertEqual(2,self.counts(self.enemy))
        self.assertEqual(Zone.GRAVEYARD,self.zone(self.source))

    def test_fangs_empty_target_starts_with_two(self):
        self.game();self.cast((self.body,));self.drain();self.assertEqual(2,self.counts(self.body))

    def test_fangs_overload_is_nontargeted_and_includes_shroud(self):
        self.game();shroud=self.add('tr-shroud');phased=self.add();self.state.phase(phased,True)
        self.cast(mana='CCCCGG',alternative='overload')
        self.assertEqual([],self.kernel.stack[-1]['targets']);self.assertIsNone(self.kernel.stack[-1]['target_spec'])
        self.restore();self.drain()
        self.assertEqual(2,self.counts(self.body));self.assertEqual(2,self.counts(shroud))
        self.assertEqual(0,self.counts(self.enemy));self.assertEqual(0,self.counts(phased))

    def test_fangs_ordinary_cast_rejects_shroud_without_payment(self):
        self.game();ref=self.add('tr-shroud');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',self.source,(ref,))
        self.assertEqual(before,self.kernel.snapshot())

    def test_fangs_target_and_overload_declarations_are_distinct(self):
        self.game()
        for targets,alternative in (((),None),((self.body,),'overload'),((self.enemy,),None)):
            before=self.kernel.snapshot()
            with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',self.source,targets,alternative_id=alternative)
            self.assertEqual(before,self.kernel.snapshot())

    def test_fangs_illegal_target_does_not_resolve(self):
        self.game();self.cast((self.body,));self.respond('tr-remove',(self.body,));self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.zone(self.source));self.assertEqual(0,self.counts(self.state.current(self.body.card_id)))

    def test_fangs_target_control_is_rechecked(self):
        self.game();self.cast((self.body,));self.state.change_control(self.body,'B');self.drain()
        self.assertEqual(0,self.counts(self.body))

    def test_fangs_prevented_first_placement_does_not_double_old_counters(self):
        rule=self.replacement(multiplier=1,divisor=2);self.game(extra=(rule,));self.add(rule.definition_id)
        self.state.add_counters(self.body,'+1/+1',6);self.cast((self.body,));self.drain()
        self.assertEqual(6,self.counts(self.body))

    def test_fangs_replacements_apply_to_both_placements(self):
        rule=self.replacement();self.game(extra=(rule,));self.add(rule.definition_id)
        self.cast((self.body,));self.drain();self.assertEqual(6,self.counts(self.body))

    def test_fangs_overload_with_no_creatures_still_resolves(self):
        self.game();self.state.move((ZoneMove(self.body,Zone.GRAVEYARD),),'fixture')
        self.cast(mana='CCCCGG',alternative='overload');self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.zone(self.source));self.assertEqual(0,self.counts(self.enemy))

    def test_fangs_overload_cost_is_modified_but_mana_value_is_two(self):
        tax=CardProgram('tr-tax','Tax',('Enchantment',),cost_modifiers=(
            CostModifier('tax',Selector(Zone.STACK,types=('Sorcery',)),1),))
        self.game(extra=(tax,));self.add(tax.definition_id)
        self.state.add_mana('A',tuple('CCCCCGG'))
        quote=self.kernel.quote_cast('taxed','A',self.source,(),alternative_id='overload')
        self.assertEqual(5,quote.cost.mana.generic);self.kernel.commit_action(quote,self.pay('CCCCCGG'))
        ref=self.state.current(self.source.card_id);self.assertEqual(2,self.kernel.effective(ref).mana_value)

    def test_hydra_monstrous_transition_and_sized_tokens(self):
        self.game('hydra-broodmaster',Zone.BATTLEFIELD);self.activate(mana='CCCCCCG',x=3);self.drain()
        self.assertTrue(self.state.get(self.source).monstrous);self.assertEqual(3,self.counts(self.source))
        self.assertEqual(10,self.kernel.effective(self.source).power);self.assertEqual(3,len(self.tokens()))
        for token in self.tokens():
            p=self.kernel.definition(token)
            self.assertEqual((3,3),(p.power,p.toughness));self.assertEqual(('Hydra',),p.subtypes)
            self.assertEqual(('G',),p.colors);self.assertEqual(0,p.mana_value);self.assertFalse(token.monstrous)

    def test_hydra_activation_charges_x_twice(self):
        self.game('hydra-broodmaster',Zone.BATTLEFIELD);self.state.add_mana('A',tuple('CCCCG'))
        quote=self.kernel.quote_activation('xx','A',self.source,'monstrosity',(),x_value=2)
        self.assertEqual(4,quote.cost.mana.generic);self.kernel.commit_action(quote,self.pay('CCCCG'));self.drain()
        self.assertEqual(2,len(self.tokens()))

    def test_hydra_zero_still_becomes_monstrous_and_triggers(self):
        self.game('hydra-broodmaster',Zone.BATTLEFIELD);self.activate();self.round()
        self.assertTrue(self.state.get(self.source).monstrous);self.assertEqual(0,self.counts(self.source))
        self.assertEqual(1,len(self.kernel.stack));self.drain();self.assertEqual((),self.tokens())
        self.assertEqual([],self.kernel.copy_programs)

    def test_hydra_counter_multiplier_does_not_multiply_captured_x(self):
        rule=self.replacement();self.game('hydra-broodmaster',Zone.BATTLEFIELD,extra=(rule,));self.add(rule.definition_id)
        self.activate(mana='CCCCG',x=2);self.drain()
        self.assertEqual(4,self.counts(self.source));self.assertEqual(2,len(self.tokens()))
        self.assertEqual(2,self.kernel.definition(self.tokens()[0]).power)

    def test_hydra_prevented_counters_still_make_it_monstrous(self):
        rule=self.replacement(multiplier=1,divisor=2)
        self.game('hydra-broodmaster',Zone.BATTLEFIELD,extra=(rule,));self.add(rule.definition_id)
        self.activate(mana='CCG',x=1);self.drain()
        self.assertTrue(self.state.get(self.source).monstrous);self.assertEqual(0,self.counts(self.source));self.assertEqual(1,len(self.tokens()))

    def test_hydra_repeated_activation_pays_but_does_nothing(self):
        self.game('hydra-broodmaster',Zone.BATTLEFIELD);self.activate(mana='CCG',x=1);self.drain()
        self.activate(mana='CCCCG',x=2);self.drain()
        self.assertEqual(1,self.counts(self.source));self.assertEqual(1,len(self.tokens()));self.assertEqual((),self.state.mana_pool('A'))

    def test_hydra_queued_activations_only_first_to_resolve_matters(self):
        self.game('hydra-broodmaster',Zone.BATTLEFIELD)
        self.activate(mana='CCG',x=1);self.activate(mana='CCCCG',x=2);self.drain()
        self.assertEqual(2,self.counts(self.source));self.assertEqual(2,len(self.tokens()))

    def test_hydra_counter_removal_does_not_remove_designation(self):
        self.game('hydra-broodmaster',Zone.BATTLEFIELD);self.activate(mana='CCG',x=1);self.drain()
        self.fx(self.source,RemoveCounters('source','+1/+1',1));self.activate(mana='CCG',x=1);self.drain()
        self.assertTrue(self.state.get(self.source).monstrous);self.assertEqual(0,self.counts(self.source));self.assertEqual(1,len(self.tokens()))

    def test_hydra_trigger_keeps_x_after_source_leaves(self):
        self.game('hydra-broodmaster',Zone.BATTLEFIELD);self.activate(mana='CCCCG',x=2);self.round()
        self.respond('tr-remove',(self.source,));self.restore();self.drain()
        self.assertEqual(2,len(self.tokens()));self.assertFalse(self.state.get(self.state.current(self.source.card_id)).monstrous)

    def test_hydra_activation_fails_if_source_leaves(self):
        self.game('hydra-broodmaster',Zone.BATTLEFIELD);self.activate(mana='CCG',x=1)
        self.respond('tr-remove',(self.source,));self.drain();self.assertEqual((),self.tokens())

    def test_hydra_phased_source_is_not_made_monstrous(self):
        self.game('hydra-broodmaster',Zone.BATTLEFIELD);self.activate(mana='CCG',x=1);self.state.phase(self.source,True);self.drain()
        self.assertFalse(self.state.get(self.source).monstrous);self.assertEqual((),self.tokens())

    def test_hydra_designation_survives_control_and_copy_changes(self):
        self.game('hydra-broodmaster',Zone.BATTLEFIELD);self.activate();self.drain()
        self.fx(self.source,Select(Selector(Zone.BATTLEFIELD,types=('Creature',),exclude_source=True,relation='controlled'),1,1,
            (CopyPermanent('source','selected'),)))
        self.drain();self.state.change_control(self.source,'B');self.restore()
        self.assertTrue(self.state.get(self.source).monstrous);self.assertEqual('Body',self.kernel.definition(self.state.get(self.source)).name)

    def test_hydra_copy_does_not_copy_designation_or_counters(self):
        self.game('hydra-broodmaster',Zone.BATTLEFIELD);self.activate(mana='CCG',x=1);self.drain()
        self.fx(self.source,CopyTokens('source'));self.drain()
        clone=next(t for t in self.tokens() if self.kernel.definition(t).name=='Hydra Broodmaster')
        self.assertFalse(clone.monstrous);self.assertEqual((),clone.counters);self.assertEqual(7,self.kernel.effective(clone.ref).power)

    def test_hydra_token_size_is_copiable_and_checkpointed(self):
        self.game('hydra-broodmaster',Zone.BATTLEFIELD);self.activate(mana='CCCCG',x=2);self.drain();token=self.tokens()[0]
        self.fx(token.ref,CopyTokens('source'));self.restore()
        self.assertEqual([2,2,2],[self.kernel.definition(t).power for t in self.tokens()])

    def test_hydra_fresh_incarnation_can_become_monstrous_again(self):
        self.game('hydra-broodmaster',Zone.BATTLEFIELD);self.activate();self.drain()
        self.fx(self.source,Move('source',Zone.HAND));self.source=self.state.current(self.source.card_id)
        self.kernel.enter(self.source);self.drain();self.source=self.state.current(self.source.card_id)
        self.assertFalse(self.state.get(self.source).monstrous)
        self.activate(mana='CCG',x=1);self.drain();self.assertEqual(1,len(self.tokens()))

    def test_hydra_transition_waits_for_counter_replacement_choices(self):
        double=self.replacement();plus=self.replacement('tr-plus',multiplier=1,additional=1)
        self.game('hydra-broodmaster',Zone.BATTLEFIELD,extra=(double,plus));self.add(double.definition_id);self.add(plus.definition_id)
        self.activate(mana='CCG',x=1);self.round();self.assertIsNotNone(self.kernel.pending_choice)
        self.assertFalse(self.state.get(self.source).monstrous);self.assertEqual(0,self.counts(self.source))
        self.restore();self.drain();self.assertTrue(self.state.get(self.source).monstrous)
        self.assertIn(self.counts(self.source),(3,4));self.assertEqual(1,len(self.tokens()))

    def test_monstrous_designation_is_public_and_schema_bound(self):
        self.game('hydra-broodmaster',Zone.BATTLEFIELD);self.activate();self.drain()
        packet=project_actor(self.kernel,'B')
        self.assertTrue(any(row.get('monstrous') for row in packet['zones']['battlefield']['A']))
        self.assertGreaterEqual(self.kernel.CHECKPOINT_SCHEMA,125);self.assertGreaterEqual(self.state.CHECKPOINT_SCHEMA,16)
        snap=self.state.snapshot();next(o for o in snap['objects'] if o['ref']==self.source.to_json())['monstrous']='yes'
        with self.assertRaises(RulesViolation):RulesState.restore(snap)

    def test_fanatic_normal_mana_is_immediate(self):
        self.game('fanatic-of-rhonas',Zone.BATTLEFIELD);self.activate('green',mana='')
        self.assertEqual((('G',1),),self.state.mana_pool('A'));self.assertEqual([],self.kernel.stack)
        self.assertTrue(self.state.get(self.source).tapped)

    def test_fanatic_ferocious_checks_power_not_its_four_toughness(self):
        self.game('fanatic-of-rhonas',Zone.BATTLEFIELD);before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',self.source,'ferocious',())
        self.assertEqual(before,self.kernel.snapshot())

    def test_fanatic_ferocious_uses_derived_controlled_power(self):
        self.game('fanatic-of-rhonas',Zone.BATTLEFIELD);self.fx(self.body,UntilEndOfTurn('source',(ModifyPT(2,0),)))
        self.activate('ferocious',mana='');self.assertEqual((('G',4),),self.state.mana_pool('A'))

    def test_fanatic_does_not_count_opponent_or_phased_power(self):
        self.game('fanatic-of-rhonas',Zone.BATTLEFIELD);self.add('tr-large','B');large=self.add('tr-large');self.state.phase(large,True)
        with self.assertRaises(RulesViolation):self.activate('ferocious',mana='')

    def test_fanatic_both_tap_abilities_require_readiness(self):
        self.game('fanatic-of-rhonas',Zone.BATTLEFIELD);young=self.add(self.cards['fanatic-of-rhonas'].definition_id);self.add('tr-large')
        for ability in ('green','ferocious'):
            with self.subTest(ability=ability),self.assertRaises(RulesViolation):
                self.kernel.quote_activation('young','A',young,ability,())

    def test_eternalize_exiles_as_cost_and_creates_costless_black_four_four(self):
        self.game('fanatic-of-rhonas',Zone.GRAVEYARD);self.activate('eternalize',mana='CCGG')
        self.assertEqual(Zone.EXILE,self.zone(self.source));self.assertEqual((),self.tokens())
        self.restore();self.drain();token=self.tokens()[0];p=self.kernel.definition(token)
        self.assertEqual((4,4,0),(p.power,p.toughness,p.mana_value));self.assertEqual(('B',),p.colors)
        self.assertEqual({'Zombie','Snake','Druid'},set(p.subtypes));self.assertIsNone(p.cast)
        self.assertEqual(3,len(p.activated));self.assertFalse(token.tapped)

    def test_eternalize_requires_sorcery_timing_and_own_graveyard(self):
        self.game('fanatic-of-rhonas',Zone.GRAVEYARD);self.kernel.open_window_for_scenario('B',priority_actor='A')
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('timing','A',self.source,'eternalize',())
        self.kernel.open_window_for_scenario('A');foreign=self.add(self.cards['fanatic-of-rhonas'].definition_id,'B',Zone.GRAVEYARD)
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('owner','A',foreign,'eternalize',())
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('zone','A',self.body,'eternalize',())

    def test_eternalize_countered_ability_does_not_refund_exile(self):
        self.game('fanatic-of-rhonas',Zone.GRAVEYARD);self.activate('eternalize',mana='CCGG')
        self.respond('tr-stop');self.drain();self.assertEqual((),self.tokens());self.assertEqual(Zone.EXILE,self.zone(self.source))

    def test_eternalized_token_itself_enables_ferocious_when_ready(self):
        self.game('fanatic-of-rhonas',Zone.GRAVEYARD);self.activate('eternalize',mana='CCGG');self.drain();token=self.tokens()[0]
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('young','A',token.ref,'ferocious',())
        self.state.start_turn('A');self.activate('ferocious',token.ref,mana='');self.assertEqual((('G',4),),self.state.mana_pool('A'))

    def test_eternalize_exceptions_remain_copiable(self):
        self.game('fanatic-of-rhonas',Zone.GRAVEYARD);self.activate('eternalize',mana='CCGG');self.drain();token=self.tokens()[0]
        self.fx(token.ref,CopyTokens('source'));self.restore()
        for token in self.tokens():
            p=self.kernel.definition(token)
            self.assertEqual((4,4,0),(p.power,p.toughness,p.mana_value));self.assertEqual(('B',),p.colors)
            self.assertIsNone(p.cast);self.assertIn('Zombie',p.subtypes)

    def test_eternalize_token_adds_no_devotion(self):
        self.game('fanatic-of-rhonas',Zone.GRAVEYARD);self.activate('eternalize',mana='CCGG');self.drain();token=self.tokens()[0]
        self.assertFalse(self.kernel._condition_holds(DevotionCondition(('G',),1),token))
        self.assertFalse(self.kernel._condition_holds(DevotionCondition(('B',),1),token))

    def test_fanatic_copied_conditional_ability_keeps_restriction(self):
        self.game('fanatic-of-rhonas',Zone.BATTLEFIELD);self.fx(self.source,CopyTokens('source'));self.drain();token=self.tokens()[0]
        self.state.start_turn('A')
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('restriction','A',token.ref,'ferocious',())
        self.add('tr-large');self.activate('ferocious',token.ref,mana='');self.assertEqual((('G',4),),self.state.mana_pool('A'))

    def test_finale_zero_draws_nothing_but_exiles_itself(self):
        self.game('finale-of-revelation');self.cast(mana='UU');self.drain()
        self.assertEqual(0,len(self.hand()));self.assertEqual(Zone.EXILE,self.zone(self.source))
        self.assertEqual(0,self.state.snapshot()['shuffle_nonce']);self.assertEqual([],self.kernel.player_effects)

    def test_finale_nine_uses_only_small_branch(self):
        self.game('finale-of-revelation');grave=self.add(zone=Zone.GRAVEYARD)
        land=self.add('catalog:forest');self.state.set_tapped_batch((land,),True)
        self.cast(mana='CCCCCCCCCUU',x=9);self.drain()
        self.assertEqual(9,len(self.hand()));self.assertEqual(Zone.GRAVEYARD,self.zone(grave))
        self.assertTrue(self.state.get(land).tapped);self.assertEqual(0,self.state.snapshot()['shuffle_nonce'])
        self.assertEqual([],self.kernel.player_effects);self.assertEqual(Zone.EXILE,self.zone(self.source))

    def test_finale_ten_shuffles_own_graveyard_and_can_untap_opponent_lands(self):
        self.game('finale-of-revelation');grave=self.add(zone=Zone.GRAVEYARD);foreign=self.add(actor='B',zone=Zone.GRAVEYARD)
        lands=[self.add('catalog:forest','B' if i<2 else 'A') for i in range(6)]
        self.state.set_tapped_batch(lands,True)
        self.cast(mana='CCCCCCCCCCUU',x=10);self.round();q=self.kernel.pending_choice
        self.assertEqual(10,len(self.hand()));self.assertEqual(0,q.minimum);self.assertEqual(5,q.maximum)
        chosen=lands[:5];indices=[i for i,o in enumerate(q.options) if o.ref in chosen]
        self.kernel.answer(q.request_id,q.actor,indices);self.drain()
        self.assertTrue(all(not self.state.get(r).tapped for r in chosen));self.assertTrue(self.state.get(lands[5]).tapped)
        self.assertNotEqual(Zone.GRAVEYARD,self.zone(grave));self.assertEqual(Zone.GRAVEYARD,self.zone(foreign))
        self.assertEqual(1,self.state.snapshot()['shuffle_nonce']);self.assertEqual(Zone.EXILE,self.zone(self.source))
        self.assertIsNone(self.kernel.player_permissions()['A']['maximum_hand_size'])

    def test_finale_can_decline_all_land_untaps(self):
        self.game('finale-of-revelation');land=self.add('catalog:forest');self.state.set_tapped_batch((land,),True)
        self.cast(mana='CCCCCCCCCCUU',x=10);self.drain()
        self.assertTrue(self.state.get(land).tapped);self.assertIsNone(self.kernel.player_permissions()['A']['maximum_hand_size'])

    def test_finale_land_choice_rejects_six_and_replays_without_redrawing(self):
        self.game('finale-of-revelation');lands=[self.add('catalog:forest') for _ in range(6)]
        self.cast(mana='CCCCCCCCCCUU',x=10);self.round();q=self.kernel.pending_choice
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.answer(q.request_id,q.actor,list(range(6)))
        self.assertEqual(before,self.kernel.snapshot());self.restore();q=self.kernel.pending_choice
        self.kernel.answer(q.request_id,q.actor,[]);self.drain()
        self.assertEqual(10,len(self.hand()));self.assertEqual(1,self.state.snapshot()['shuffle_nonce'])

    def test_finale_phased_lands_are_not_choices(self):
        self.game('finale-of-revelation');land=self.add('catalog:forest');phased=self.add('catalog:forest')
        self.state.phase(phased,True);self.cast(mana='CCCCCCCCCCUU',x=10);self.round();q=self.kernel.pending_choice
        self.assertEqual([land],[o.ref for o in q.options]);self.drain()

    def test_finale_empty_graveyard_still_shuffles_and_retires_library_refs(self):
        self.game('finale-of-revelation');old=self.state.objects(Zone.LIBRARY,owner='A')[0].ref
        self.cast(mana='CCCCCCCCCCUU',x=10);self.drain()
        self.assertEqual(1,self.state.snapshot()['shuffle_nonce'])
        with self.assertRaises(RulesViolation):self.state.get(old)

    def test_finale_permission_survives_cleanup_while_temporary_grants_expire(self):
        self.game('finale-of-revelation');self.cast(mana='CCCCCCCCCCUU',x=10);self.drain()
        self.fx(self.body,GrantPermissions(PlayerPermissions(additional_land_plays=1)))
        self.assertEqual(2,self.kernel.player_permissions()['A']['land_play_limit'])
        self.kernel._finish_cleanup_actions();self.restore();self.state.start_turn('B');self.kernel._finish_cleanup_actions()
        self.assertIsNone(self.kernel.player_permissions()['A']['maximum_hand_size'])
        self.assertEqual(1,self.kernel.player_permissions()['A']['land_play_limit'])
        self.assertEqual(7,self.kernel.player_permissions()['B']['maximum_hand_size'])

    def test_finale_countered_spell_does_not_shuffle_draw_or_exile_itself(self):
        self.game('finale-of-revelation');self.cast(mana='CCCCCCCCCCUU',x=10)
        self.respond('tr-counter',(self.state.current(self.source.card_id),));self.drain()
        self.assertEqual(0,len(self.hand()));self.assertEqual(Zone.GRAVEYARD,self.zone(self.source))
        self.assertEqual(0,self.state.snapshot()['shuffle_nonce']);self.assertEqual([],self.kernel.player_effects)

    def test_finale_draw_and_shuffle_triggers_wait_until_spell_finishes(self):
        watcher=CardProgram('tr-watch','Watcher',('Enchantment',),abilities=(
            AbilityProgram('draw',EventPattern('card_drawn',controller_only=True),(GainLife(1),)),
            AbilityProgram('shuffle',EventPattern('library_shuffled',controller_only=True),(GainLife(2),))))
        self.game('finale-of-revelation',extra=(watcher,));self.add(watcher.definition_id);self.add('catalog:forest')
        self.cast(mana='CCCCCCCCCCUU',x=10);self.round()
        self.assertEqual(40,self.state.life('A'));self.assertEqual(Zone.STACK,self.zone(self.source))
        self.drain();self.assertEqual(52,self.state.life('A'));self.assertEqual(Zone.EXILE,self.zone(self.source))

    def test_overload_compiler_rejects_hidden_target_dependency(self):
        p=self.cards['fangs-of-kalonia'];alt=replace(p.cast.alternatives[0],effects=(AddCounters('target','+1/+1',1),))
        with self.assertRaises(RulesViolation):validate(replace(p,cast=replace(p.cast,alternatives=(alt,))))

    def test_counter_recipients_are_lexically_scoped(self):
        with self.assertRaises(RulesViolation):
            validate(CardProgram('bad','Bad',('Sorcery',),spell_effects=(MultiplyCounters('counter_recipients','+1/+1'),)))

    def test_sized_tokens_require_bound_event_x(self):
        token=CardProgram('tr-token','Token',('Creature',),power=0,toughness=0)
        with self.assertRaises(RulesViolation):
            validate(CardProgram('bad','Bad',('Sorcery',),spell_effects=(CreateSizedTokens(token,1,power=EventX(),toughness=EventX()),)))

    def test_conditional_activation_requires_explicit_battlefield_condition(self):
        for ability in (ConditionalActivated('bad',CostSpec(),(GainLife(1),)),
                ConditionalActivated('bad',CostSpec(),(GainLife(1),),zone=Zone.GRAVEYARD,condition=CountCondition(Selector(Zone.BATTLEFIELD),1))):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Artifact',),activated=(ability,)))

    def test_shuffle_graveyard_prevents_mana_ability_classification(self):
        ability=ActivatedProgram('library',CostSpec(),(ShuffleGraveyard(),AddMana(('G',))))
        self.assertFalse(activation_is_mana(ability))
        with self.assertRaises(RulesViolation):
            validate(CardProgram('bad','Bad',('Artifact',),activated=(replace(ability,mana_ability=True),)))

    def test_fangs_replacement_choice_checkpoint_does_not_repeat_first_placement(self):
        double=self.replacement();plus=self.replacement('tr-plus',multiplier=1,additional=1)
        self.game(extra=(double,plus));self.add(double.definition_id);self.add(plus.definition_id)
        self.cast((self.body,));self.round();self.assertIsNotNone(self.kernel.pending_choice)
        self.assertEqual(0,self.counts(self.body));self.restore()
        q=self.kernel.pending_choice;self.kernel.answer(q.request_id,q.actor,[0])
        self.assertIsNotNone(self.kernel.pending_choice);first=self.counts(self.body);self.assertIn(first,(3,4))
        self.restore();self.drain();self.assertIn(self.counts(self.body),(first*3+1,first*3+2))

    def test_fangs_overload_only_doubles_successful_first_recipients(self):
        rule=CardProgram('tr-elf-half','Elf half',('Enchantment',),counter_replacements=(
            CounterReplacement('half',Selector(Zone.BATTLEFIELD,subtypes=('Elf',)),kind='+1/+1',divisor=2),))
        other=CardProgram('tr-human','Human',('Creature',),subtypes=('Human',),power=2,toughness=2)
        self.game(extra=(rule,other));self.add(rule.definition_id);human=self.add(other.definition_id)
        self.state.add_counters(self.body,'+1/+1',4);self.state.add_counters(human,'+1/+1',2)
        self.cast(mana='CCCCGG',alternative='overload');self.drain()
        self.assertEqual(4,self.counts(self.body));self.assertEqual(6,self.counts(human))

    def test_monstrous_trigger_has_an_independently_counterable_stack_frame(self):
        self.game('hydra-broodmaster',Zone.BATTLEFIELD);self.activate(mana='CCG',x=1);self.round()
        self.respond('tr-stop');self.drain()
        self.assertTrue(self.state.get(self.source).monstrous);self.assertEqual(1,self.counts(self.source))
        self.assertEqual((),self.tokens())

    def test_monstrous_transition_applies_to_a_permanent_that_is_no_longer_a_creature(self):
        land=CardProgram('tr-monstrous-land','Land with trigger',('Land',),abilities=(
            AbilityProgram('transition',EventPattern('becomes_monstrous',subject='self'),(GainLife(3),)),))
        self.game('hydra-broodmaster',Zone.BATTLEFIELD,extra=(land,));self.activate(mana='CCG',x=1)
        ref=self.add(land.definition_id);self.state.apply_copy((self.source,),land.definition_id)
        self.drain();self.assertTrue(self.state.get(self.source).monstrous)
        self.assertEqual(1,self.counts(self.source));self.assertEqual(43,self.state.life('A'));self.assertEqual((),self.tokens())

    def test_finale_untaps_even_a_land_with_an_untap_step_restriction(self):
        land=CardProgram('tr-still-land','Still land',('Land',),continuous=(ContinuousProgram('skip',Selector(Zone.BATTLEFIELD),(SkipUntap(),),subject='self'),))
        self.game('finale-of-revelation',extra=(land,));ref=self.add(land.definition_id);self.state.set_tapped_batch((ref,),True)
        self.cast(mana='CCCCCCCCCCUU',x=10);self.round();q=self.kernel.pending_choice
        self.kernel.answer(q.request_id,q.actor,[0]);self.drain();self.assertFalse(self.state.get(ref).tapped)

    def test_shuffle_instruction_respects_zone_replacement_then_still_shuffles(self):
        rule=CardProgram('tr-grave-exile','Grave exile',('Enchantment',),replacements=(
            ZoneReplacement('exile',Zone.LIBRARY,Zone.EXILE,from_zone=Zone.GRAVEYARD),))
        self.game(extra=(rule,));self.add(rule.definition_id);grave=self.add(zone=Zone.GRAVEYARD)
        self.fx(self.body,ShuffleGraveyard());self.drain()
        self.assertEqual(Zone.EXILE,self.zone(grave));self.assertEqual(1,self.state.snapshot()['shuffle_nonce'])

    def test_compiler_rejects_sized_token_without_a_program(self):
        with self.assertRaises(RulesViolation):
            validate(CardProgram('bad','Bad',('Sorcery',),spell_effects=(CreateSizedTokens(None),)))

    def test_costless_copy_registry_rejects_tampered_mana_exception(self):
        self.game('fanatic-of-rhonas',Zone.GRAVEYARD);self.activate('eternalize',mana='CCGG');self.drain()
        snap=self.kernel.snapshot();snap['copy_programs'][0]['remove_mana_cost']=False
        with self.assertRaises(RulesViolation):RulesKernel.restore(snap,self.programs)
