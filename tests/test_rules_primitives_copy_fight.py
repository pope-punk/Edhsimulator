"""Hosted conformance for durable copiable token values and fight."""
import json
import unittest
from dataclasses import replace
from pathlib import Path
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,RulesViolation,ObjectRef,Zone,ZoneMove
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_actor import project_actor
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed,digest,source_facts
from edh_gauntlet.catalog import load_catalog

CARDS=('scute-swarm','helm-of-the-host','lazotep-quarry','aggressive-biomancy')


class CopyFightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        reviewed=load_reviewed(cls.root)
        drafts=json.loads((cls.root/'data/rules/draft_cards.json').read_text(encoding='utf-8'))['drafts']
        cls.rows={r['card_id']:r for r in drafts if r['card_id'] in CARDS}
        cls.cards={key:validate(decode(row['program'])) for key,row in cls.rows.items()}
        cls.base=tuple(r['program'] for r in reviewed.values())+tuple(cls.cards.values())

    def game(self,card='scute-swarm',zone=Zone.BATTLEFIELD,extra=()):
        body=CardProgram('cp-body','Body',('Creature',),subtypes=('Elf',),colors=('G',),power=2,toughness=3,
            mana_value=2,cast=CastSpec(CostSpec(ManaCost(1,('G',)))))
        legend=replace(body,definition_id='cp-legend',name='Legend',supertypes=('Legendary',))
        etb=replace(body,definition_id='cp-etb',name='Entry life',
            abilities=(AbilityProgram('entry-life',EventPattern('zone_changed',to_zone=Zone.BATTLEFIELD,subject='self'),(GainLife(1),)),))
        land=CardProgram('cp-land','Forest Dryad',('Land','Creature'),subtypes=('Forest','Dryad'),colors=('G',),power=1,toughness=1)
        remove=CardProgram('cp-remove','Remove',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD)),spell_effects=(Move('target',Zone.GRAVEYARD),))
        self.programs=self.base+(body,legend,etb,land,remove)+extra
        self.state=RulesState(('A','B','C','D'));self.kernel=RulesKernel(self.state,self.programs)
        self.kernel.open_window_for_scenario('A');self.serial=0
        self.source=self.add(self.cards[card].definition_id,'A',zone)
        self.body=self.add('cp-body');self.enemy=self.add('cp-body','B')
        for player in self.state.players:
            for _ in range(12):self.add('catalog:forest',player,Zone.LIBRARY)

    def add(self,definition='cp-body',actor='A',zone=Zone.BATTLEFIELD,**kw):
        self.serial+=1
        return self.state.add_card('cp-object-'+str(self.serial),definition,actor,zone,**kw)

    def window(self,actor='A'):
        if not self.kernel.stack and self.kernel.turn_schedule is None:
            self.kernel.open_window_for_scenario(self.kernel.active,phase=self.kernel.phase,priority_actor=actor)
        while self.kernel.priority!=actor:self.kernel.pass_priority(self.kernel.priority)

    def drain(self,targets=False):
        for _ in range(400):
            q=self.kernel.pending_choice
            if q:
                if q.kind=='trigger_order':indexes=list(range(len(q.options)))
                elif q.kind=='targets' and not targets:indexes=[]
                else:indexes=list(range(q.minimum))
                self.kernel.answer(q.request_id,q.actor,indexes)
            elif self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
            else:return
        self.fail('Resolution did not reach an idle boundary')

    def round(self):
        for _ in self.state.live_players:result=self.kernel.pass_priority(self.kernel.priority)
        return result

    def fx(self,source,*effects):
        return self.kernel.execute_for_scenario(source,self.state.get(source).controller,effects)

    def cast(self,source=None,targets=(),x=0,mana='',actor='A'):
        source=self.source if source is None else source;self.window(actor)
        if mana:self.state.add_mana(actor,tuple(mana))
        self.serial+=1
        quote=self.kernel.quote_cast('cp-cast-'+str(self.serial),actor,source,targets,x_value=x)
        return self.kernel.commit_action(quote,Payment(tuple((s,mana.count(s)) for s in sorted(set(mana)))))

    def activate(self,ability,targets=(),x=0,mana='',zones=(),source=None,actor='A'):
        source=self.source if source is None else source;self.window(actor)
        if mana:self.state.add_mana(actor,tuple(mana))
        self.serial+=1
        quote=self.kernel.quote_activation('cp-act-'+str(self.serial),actor,source,ability,targets,x_value=x)
        return self.kernel.commit_action(quote,Payment(tuple((s,mana.count(s)) for s in sorted(set(mana))),zone_costs=zones))

    def tokens(self):return tuple(o for o in self.state.objects(Zone.BATTLEFIELD) if o.token)

    def landfall(self,count=5,actor='A'):
        for _ in range(count):self.add('catalog:forest',actor)
        ref=self.add('catalog:forest',actor,Zone.HAND)
        self.kernel.enter(ref)
        return self.state.current(ref.card_id)

    def remove(self,ref):
        spell=self.add('cp-remove','A',Zone.HAND);self.cast(spell,(ref,))
        self.round()

    def combat(self,actor='A'):
        self.kernel.begin_turn_for_scenario(actor)
        for _ in range(3):self.round()
        self.assertEqual('begin_combat',self.kernel.phase)

    def equip(self,ref=None):
        self.activate('equip',(self.body if ref is None else ref,),mana='CCCCC');self.drain()

    def clone(self,ref=None,**changes):
        ref=self.body if ref is None else ref
        return self.fx(ref,CopyTokens('source',**changes))

    def quarry(self,definition='cp-body',x=2,desert=None):
        ref=self.add(definition,'A',Zone.GRAVEYARD)
        desert=self.source if desert is None else desert
        self.activate('copy',(ref,),x=x,mana='C'*(x+2),zones=(('desert',(desert,)),))
        self.drain()
        return ref

    def restore(self):
        before=self.kernel.snapshot();self.kernel=RulesKernel.restore(before,self.programs);self.state=self.kernel.state
        self.assertEqual(before,self.kernel.snapshot())

    def test_all_four_complete_source_bindings(self):
        catalog={c.card_id:c for c in load_catalog(self.root/'data/catalog/cards.json')}
        self.assertEqual(set(CARDS),set(self.cards))
        for key,p in self.cards.items():
            self.assertEqual('draft:'+key,p.definition_id)
            self.assertEqual(digest(source_facts(catalog[key])),digest(self.rows[key]['source_facts']))
            self.assertEqual(p,validate(decode(encode(p))))
            for attr in ('types','subtypes','supertypes','colors'):
                self.assertEqual(set(getattr(catalog[key].faces[0],attr)),set(getattr(p,attr)))
        self.assertEqual(3,len(self.cards['lazotep-quarry'].activated))
        self.assertEqual(ManaCost(0,('G','U'),2),self.cards['aggressive-biomancy'].cast.cost.mana)

    def test_scute_below_six_makes_plain_insect(self):
        self.game();self.landfall(4);self.drain();token=self.tokens()[0];p=self.kernel.definition(token)
        self.assertEqual((1,1,('G',),('Insect',)),(p.power,p.toughness,p.colors,p.subtypes))
        self.assertFalse(p.abilities);self.assertEqual(0,p.mana_value)

    def test_scute_six_makes_source_copy(self):
        self.game();self.landfall();self.drain();p=self.kernel.definition(self.tokens()[0])
        self.assertEqual('Scute Swarm',p.name);self.assertEqual(3,p.mana_value);self.assertEqual(1,len(p.abilities))

    def test_scute_checks_land_count_at_resolution(self):
        self.game();land=self.landfall();self.remove(land);self.drain()
        self.assertFalse(self.kernel.definition(self.tokens()[0]).abilities)

    def test_scute_can_cross_threshold_after_trigger(self):
        self.game();self.landfall(4);self.add('catalog:forest');self.drain()
        self.assertEqual('Scute Swarm',self.kernel.definition(self.tokens()[0]).name)

    def test_scute_ignores_opponents_land_entry(self):
        self.game();self.landfall(actor='B');self.drain();self.assertFalse(self.tokens())

    def test_scute_uses_source_last_known_copy_values(self):
        self.game();self.landfall();self.remove(self.source);self.drain()
        self.assertEqual('Scute Swarm',self.kernel.definition(self.tokens()[0]).name)

    def test_scute_copies_keep_landfall_and_share_definition(self):
        self.game();self.landfall();self.drain();first=self.tokens()[0]
        ref=self.add('catalog:forest','A',Zone.HAND);self.kernel.enter(ref);self.drain()
        self.assertEqual(3,len(self.tokens()))
        self.assertEqual(1,len({t.definition for t in self.tokens()}));self.assertEqual(first.definition,self.tokens()[-1].definition)

    def test_copy_does_not_inherit_counters_damage_tap_or_temporary_changes(self):
        self.game();self.fx(self.body,AddCounters('source','+1/+1',2),UntilEndOfTurn('source',(ModifyPT(3,3),AddKeywords(('haste',)))))
        self.state.set_tapped_batch((self.body,),True);self.clone();token=self.tokens()[0];view=self.kernel.effective(token.ref)
        self.assertEqual((2,3),(view.power,view.toughness));self.assertFalse(token.tapped);self.assertFalse(token.counters);self.assertNotIn('haste',view.keywords)

    def test_copy_preserves_mana_cost_and_activated_abilities(self):
        self.game();elf=self.add('catalog:llanowar-elves');self.clone(elf);token=self.tokens()[0]
        self.assertEqual(1,self.kernel.effective(token.ref).mana_value)
        self.state.start_turn('A');self.activate('produce-mana',source=token.ref)
        self.assertEqual((('G',1),),self.state.mana_pool('A'))

    def test_copy_of_an_entry_copy_uses_its_copiable_values(self):
        self.game();clone=self.add('catalog:body-double','A',Zone.HAND);target=self.add('cp-body','A',Zone.GRAVEYARD)
        self.kernel.enter(clone);q=self.kernel.pending_choice
        index=next(i for i,o in enumerate(q.options) if o.ref==target);self.kernel.answer(q.request_id,q.actor,[index]);self.drain()
        self.clone(self.state.current(clone.card_id));self.assertEqual('Body',self.kernel.definition(self.tokens()[0]).name)

    def test_copy_preserves_entry_counters(self):
        p=CardProgram('cp-counter','Counter body',('Creature',),power=0,toughness=0,entry_counters=(EntryCounters('three','+1/+1',3),))
        self.game(extra=(p,));ref=self.add(p.definition_id);self.clone(ref)
        self.assertEqual({'+1/+1':3},dict(self.tokens()[0].counters))

    def test_copy_triggers_original_entry_abilities(self):
        self.game();ref=self.add('cp-etb');self.clone(ref);self.drain();self.assertEqual(41,self.state.life('A'))

    def test_helm_cast_and_equip_payment(self):
        self.game('helm-of-the-host',Zone.HAND);self.cast(mana='CCCC');self.drain();self.source=self.state.current(self.source.card_id)
        self.equip();self.assertEqual(self.body,self.state.get(self.source).attached_to)

    def test_helm_equip_is_sorcery_speed_and_controller_only(self):
        self.game('helm-of-the-host')
        with self.assertRaises(RulesViolation):self.activate('equip',(self.enemy,),mana='CCCCC')
        self.kernel.open_window_for_scenario('B',priority_actor='A')
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',self.source,'equip',(self.body,))

    def test_helm_unattached_makes_nothing(self):
        self.game('helm-of-the-host');self.combat();self.drain();self.assertFalse(self.tokens())

    def test_helm_only_triggers_on_own_combat(self):
        self.game('helm-of-the-host');self.equip();self.combat('B');self.drain();self.assertFalse(self.tokens())

    def test_helm_creates_nonlegendary_hasty_copy(self):
        self.game('helm-of-the-host');legend=self.add('cp-legend');self.equip(legend);self.combat();self.drain()
        token=self.tokens()[0];view=self.kernel.effective(token.ref)
        self.assertEqual('Legend',self.kernel.definition(token).name);self.assertNotIn('Legendary',view.supertypes);self.assertIn('haste',view.keywords)

    def test_helm_haste_is_indefinite_but_not_copiable(self):
        self.game('helm-of-the-host');self.equip();self.combat();self.drain();token=self.tokens()[0]
        self.assertTrue(any(r.get('duration')=='indefinite' for r in self.kernel.temporary_effects))
        self.kernel.turn_schedule=None;self.clone(token.ref);second=self.tokens()[-1]
        self.assertNotIn('haste',self.kernel.effective(second.ref).keywords);self.restore()

    def test_helm_creature_departure_prevents_copy(self):
        self.game('helm-of-the-host');self.equip();self.combat();self.remove(self.body);self.drain();self.assertFalse(self.tokens())

    def test_helm_departure_retains_last_equipped_creature(self):
        self.game('helm-of-the-host');self.equip();self.combat();self.remove(self.source);self.drain()
        self.assertEqual('Body',self.kernel.definition(self.tokens()[0]).name)

    def test_helm_both_departures_use_last_known_values(self):
        self.game('helm-of-the-host');self.equip();self.combat();self.remove(self.source);self.remove(self.body);self.drain()
        self.assertEqual('Body',self.kernel.definition(self.tokens()[0]).name)

    def test_quarry_base_colorless_mana(self):
        self.game('lazotep-quarry');self.activate('mana');self.assertEqual((('C',1),),self.state.mana_pool('A'))

    def test_quarry_creature_sacrifice_produces_chosen_color(self):
        self.game('lazotep-quarry');self.activate('creature-mana',zones=(('creature',(self.body,)),))
        q=self.kernel.pending_choice;self.assertEqual(5,len(q.options));self.kernel.answer(q.request_id,q.actor,[1])
        self.assertEqual((('U',1),),self.state.mana_pool('A'));self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current(self.body.card_id)).zone)

    def test_quarry_rejects_missing_sacrifice_atomically(self):
        self.game('lazotep-quarry');q=self.kernel.quote_activation('bad','A',self.source,'creature-mana');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(q,Payment())
        self.assertEqual(before,self.kernel.snapshot())

    def test_quarry_may_sacrifice_itself_and_creates_modified_copy(self):
        self.game('lazotep-quarry');target=self.quarry();token=self.tokens()[0];view=self.kernel.effective(token.ref)
        self.assertEqual((4,4,{'B'},{'Zombie'}),(view.power,view.toughness,view.colors,view.subtypes))
        self.assertEqual(2,view.mana_value);self.assertEqual('Body',self.kernel.definition(token).name)
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current(target.card_id)).zone)
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current(self.source.card_id)).zone)

    def test_quarry_rejects_wrong_target_mana_value(self):
        self.game('lazotep-quarry');ref=self.add('cp-body','A',Zone.GRAVEYARD)
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('wrong-x','A',self.source,'copy',(ref,),x_value=1)

    def test_quarry_rejects_opponents_graveyard(self):
        self.game('lazotep-quarry');ref=self.add('cp-body','B',Zone.GRAVEYARD)
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('opponent','A',self.source,'copy',(ref,),x_value=2)

    def test_quarry_sorcery_timing(self):
        self.game('lazotep-quarry');ref=self.add('cp-body','A',Zone.GRAVEYARD);self.kernel.open_window_for_scenario('B',priority_actor='A')
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('timing','A',self.source,'copy',(ref,),x_value=2)

    def test_quarry_copy_preserves_land_types(self):
        self.game('lazotep-quarry');self.quarry('cp-land',x=0);view=self.kernel.effective(self.tokens()[0].ref)
        self.assertEqual({'Creature','Land'},view.types);self.assertEqual({'Forest','Zombie'},view.subtypes)

    def test_quarry_removes_characteristic_defining_power(self):
        p=CardProgram('cp-star','Star',('Creature',),power=0,toughness=0,characteristic_pt=CountObjects(Selector(Zone.BATTLEFIELD,types=('Land',))))
        self.game('lazotep-quarry',extra=(p,));self.quarry(p.definition_id,x=0)
        self.assertIsNone(self.kernel.definition(self.tokens()[0]).characteristic_pt)
        self.assertEqual((4,4),(self.kernel.effective(self.tokens()[0].ref).power,self.kernel.effective(self.tokens()[0].ref).toughness))

    def test_quarry_replaces_all_creature_types_but_not_land_type_sets(self):
        p=CardProgram('cp-changeling','All types',('Creature','Land'),power=1,toughness=1,all_subtype_sets=('creature','land'))
        self.game('lazotep-quarry',extra=(p,));self.quarry(p.definition_id,x=0);view=self.kernel.effective(self.tokens()[0].ref)
        self.assertIn('Zombie',view.subtypes);self.assertIn('Forest',view.subtypes);self.assertNotIn('Elf',view.subtypes)

    def test_quarry_original_entry_ability_still_triggers(self):
        self.game('lazotep-quarry');self.quarry('cp-etb');self.assertEqual(41,self.state.life('A'))

    def test_quarry_exceptions_are_copiable(self):
        self.game('lazotep-quarry');self.quarry();first=self.tokens()[0];self.clone(first.ref);second=self.tokens()[-1]
        self.assertEqual(first.definition,second.definition);self.assertEqual({'Zombie'},self.kernel.effective(second.ref).subtypes)

    def test_biomancy_zero_x_creates_nothing(self):
        self.game('aggressive-biomancy',Zone.HAND);self.cast(targets=(self.body,),x=0,mana='GU');self.drain();self.assertFalse(self.tokens())

    def test_biomancy_cost_requires_twice_x(self):
        self.game('aggressive-biomancy',Zone.HAND);self.state.add_mana('A',tuple('CCGU'))
        q=self.kernel.quote_cast('wrong','A',self.source,(self.body,),x_value=2);before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(q,Payment((('C',2),('G',1),('U',1))))
        self.assertEqual(before,self.kernel.snapshot())

    def test_biomancy_two_tokens_enter_in_one_batch(self):
        self.game('aggressive-biomancy',Zone.HAND);self.cast(targets=(self.body,),x=2,mana='CCCCGU');self.round()
        self.assertEqual(2,len(self.tokens()));refs={t.ref for t in self.tokens()}
        self.assertEqual(1,len({e.batch for e in self.state.events if e.after.ref in refs}))
        self.drain();self.assertEqual(0,self.state.get(self.enemy).damage_marked)

    def test_biomancy_illegal_target_creates_nothing(self):
        self.game('aggressive-biomancy',Zone.HAND);self.cast(targets=(self.body,),x=1,mana='CCGU');self.remove(self.body);self.drain();self.assertFalse(self.tokens())

    def test_biomancy_can_decline_fight_targets(self):
        self.game('aggressive-biomancy',Zone.HAND);self.cast(targets=(self.body,),x=1,mana='CCGU');self.drain()
        self.assertEqual(0,self.state.get(self.enemy).damage_marked);self.assertEqual(1,len(self.tokens()))

    def test_biomancy_fight_trigger_uses_token_as_damage_source(self):
        self.game('aggressive-biomancy',Zone.HAND);self.cast(targets=(self.body,),x=1,mana='CCGU');self.round();q=self.kernel.pending_choice
        index=next(i for i,o in enumerate(q.options) if o.ref==self.enemy);self.kernel.answer(q.request_id,q.actor,[index]);self.drain()
        token=self.tokens()[0];self.assertEqual(2,self.state.get(self.enemy).damage_marked);self.assertEqual(2,token.damage_marked)
        damage=[e for e in self.kernel.semantic_events if e['kind']=='damage_dealt'];self.assertEqual(2,len(damage));self.assertTrue(all(not e['combat'] for e in damage))

    def test_biomancy_copy_of_copy_adds_another_fight_ability(self):
        self.game('aggressive-biomancy',Zone.HAND);self.cast(targets=(self.body,),x=1,mana='CCGU');self.drain();first=self.tokens()[0]
        spell=self.add(self.cards['aggressive-biomancy'].definition_id,'A',Zone.HAND);self.cast(spell,(first.ref,),x=1,mana='CCGU');self.drain()
        abilities=self.kernel.definition(self.tokens()[-1]).abilities;self.assertEqual(2,len(abilities));self.assertEqual(2,len({a.ability_id for a in abilities}))

    def test_biomancy_keeps_original_entry_triggers(self):
        self.game('aggressive-biomancy',Zone.HAND);ref=self.add('cp-etb');self.cast(targets=(ref,),x=2,mana='CCCCGU');self.drain()
        self.assertEqual(42,self.state.life('A'))

    def test_fight_simultaneously_deals_both_powers(self):
        self.game();self.fx(self.body,Select(Selector(Zone.BATTLEFIELD,types=('Creature',),relation='opponent_controlled'),1,1,(Fight('source','selected'),)))
        self.assertIsNone(self.kernel.pending_choice)
        self.assertEqual(2,self.state.get(self.body).damage_marked);self.assertEqual(2,self.state.get(self.enemy).damage_marked)

    def test_fight_missing_first_creature_deals_no_damage(self):
        self.game('aggressive-biomancy',Zone.HAND);self.cast(targets=(self.body,),x=1,mana='CCGU');self.round();q=self.kernel.pending_choice
        self.kernel.answer(q.request_id,q.actor,[0]);token=self.tokens()[0];self.remove(token.ref);self.drain()
        self.assertEqual(0,self.state.get(self.enemy).damage_marked)

    def test_fight_noncreature_participant_prevents_both_halves(self):
        self.game();land=self.add('catalog:forest')
        self.fx(land,Select(Selector(Zone.BATTLEFIELD,types=('Creature',),relation='opponent_controlled'),1,1,(Fight('source','selected'),)))
        self.assertIsNone(self.kernel.pending_choice);self.assertEqual(0,self.state.get(self.enemy).damage_marked)

    def test_fight_itself_deals_twice_power(self):
        p=CardProgram('cp-big','Big',('Creature',),power=2,toughness=8)
        self.game(extra=(p,));ref=self.add(p.definition_id);self.fx(ref,Fight('source','source'));self.assertEqual(4,self.state.get(ref).damage_marked)

    def test_fight_negative_power_is_zero(self):
        p=CardProgram('cp-negative','Negative',('Creature',),power=-2,toughness=5)
        self.game(extra=(p,));ref=self.add(p.definition_id)
        self.fx(ref,Select(Selector(Zone.BATTLEFIELD,types=('Creature',),relation='opponent_controlled'),1,1,(Fight('source','selected'),)))
        self.assertIsNone(self.kernel.pending_choice)
        self.assertEqual(0,self.state.get(self.enemy).damage_marked);self.assertEqual(2,self.state.get(ref).damage_marked)

    def test_copy_registry_preserves_base_bundle_and_read_only_maps(self):
        self.game();base=self.kernel.bundle;self.clone();self.assertEqual(base,self.kernel.bundle)
        with self.assertRaises(TypeError):self.kernel.definitions['bad']=self.kernel.definition(self.tokens()[0])
        self.assertEqual(1,len(self.kernel.copy_programs));self.restore()

    def test_copy_registry_reuses_identical_values(self):
        self.game();self.clone();first=self.tokens()[0];self.clone(first.ref);self.clone()
        self.assertEqual(1,len(self.kernel.copy_programs));self.assertEqual(1,len({t.definition for t in self.tokens()}))

    def test_copy_registry_rejects_modified_digest_and_unknown_parent(self):
        self.game();self.clone()
        for field,value in (('definition_id','copy:forged'),('parent','missing')):
            snapshot=self.kernel.snapshot();snapshot['copy_programs'][0][field]=value
            with self.assertRaises(RulesViolation):RulesKernel.restore(snapshot,self.programs)

    def test_copy_registry_rejects_changed_exception_values(self):
        self.game();self.clone(nonlegendary=True);snapshot=self.kernel.snapshot()
        snapshot['copy_programs'][0]['changes']['power']=7;snapshot['copy_programs'][0]['changes']['toughness']=7
        with self.assertRaises(RulesViolation):RulesKernel.restore(snapshot,self.programs)

    def test_copy_registry_restores_pending_entry_replacement(self):
        p=CardProgram('cp-counter','Counter body',('Creature',),power=0,toughness=0,entry_counters=(EntryCounters('one','+1/+1',1),))
        mods=tuple(CardProgram(k,k,('Enchantment',),counter_replacements=(CounterReplacement(k,Selector(Zone.BATTLEFIELD),kind='+1/+1',multiplier=m,additional=a),)) for k,m,a in (('cp-double',2,0),('cp-plus',1,1)))
        self.game(extra=(p,)+mods);ref=self.add(p.definition_id)
        for mod in mods:self.add(mod.definition_id)
        before=self.state.snapshot();self.clone(ref);self.assertEqual(before,self.state.snapshot());self.assertIsNotNone(self.kernel.pending_choice)
        self.restore();self.drain();self.assertEqual(1,len(self.tokens()))

    def test_copied_token_projection_retains_public_characteristics(self):
        self.game();self.clone();packet=project_actor(self.kernel,'B');encoded=json.dumps(packet)
        self.assertIn(self.tokens()[0].ref.card_id,encoded);self.assertIn('Body',encoded)

    def test_copied_tokens_die_and_cannot_return(self):
        self.game();self.clone();token=self.tokens()[0]
        self.fx(token.ref,WithMoved('source',Zone.EXILE,(Move('moved',Zone.BATTLEFIELD),)))
        self.assertFalse(self.tokens());self.restore()

    def test_copy_compiler_rejects_invalid_exceptions(self):
        for change in ({'power':2},{'nonlegendary':1},{'colors':('C',)},{'creature_types':('Forest',)},{'abilities':[]}):
            with self.subTest(change=change),self.assertRaises(RulesViolation):
                validate(CardProgram('bad','Bad',('Artifact',),spell_effects=(CopyTokens('source',**change),)))

    def test_quarry_actor_replay_preserves_x_payment_and_copy(self):
        self.game('lazotep-quarry');target=self.add('cp-body','A',Zone.GRAVEYARD);self.state.add_mana('A',tuple('CCCC'))
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        command={'kind':'activate','revision':self.kernel.revision,'action_id':'quarry-actor',
            'source':self.source.to_json(),'ability_id':'copy','targets':[target.to_json()],'x_value':2,
            'payment':Payment((('C',4),),zone_costs=(('desert',(self.source,)),)).to_json()}
        for item in (adapter,replay):
            item.submit('A',command)
            while item.kernel.stack:item.kernel.pass_priority(item.kernel.priority)
        self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot())
        token=self.tokens()[0];self.assertEqual((4,4),(self.kernel.effective(token.ref).power,self.kernel.effective(token.ref).toughness))
        self.assertEqual(2,self.kernel.action_receipts['quarry-actor']['action']['x_value'])

    def test_target_compiler_requires_x_cost_for_x_characteristic_bounds(self):
        selector=Selector(Zone.GRAVEYARD,types=('Creature',),relation='owned',
            characteristics=(CharacteristicRange('mana_value',ChosenX(),ChosenX()),))
        for x_symbols in (0,1):
            p=CardProgram('cp-x','X target',('Land',),activated=(ActivatedProgram('copy',
                CostSpec(ManaCost(x_symbols=x_symbols)),(Move('target',Zone.EXILE),),targets=TargetSpec(selector)),))
            if x_symbols:validate(p)
            else:
                with self.assertRaises(RulesViolation):validate(p)

    def test_copy_compiler_rejects_unbound_subjects(self):
        for effect in (CopyTokens('missing'),Fight('missing','source')):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Artifact',),spell_effects=(effect,)))

    def test_scute_phased_source_still_resolves_its_existing_trigger(self):
        phase=CardProgram('cp-phase','Phase',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD)),spell_effects=(PhaseOut('target'),))
        self.game(extra=(phase,));self.landfall();spell=self.add(phase.definition_id,'A',Zone.HAND)
        self.cast(spell,(self.source,));self.round();self.drain()
        self.assertEqual('Scute Swarm',self.kernel.definition(self.tokens()[0]).name)

    def test_fight_lifelink_and_deathtouch_apply_without_combat(self):
        p=CardProgram('cp-deadly','Deadly',('Creature',),power=1,toughness=5,keywords=('lifelink','deathtouch'))
        self.game(extra=(p,));ref=self.add(p.definition_id)
        self.fx(ref,Select(Selector(Zone.BATTLEFIELD,types=('Creature',),relation='opponent_controlled'),1,1,(Fight('source','selected'),)))
        self.assertIsNone(self.kernel.pending_choice)
        self.assertEqual(41,self.state.life('A'));self.assertEqual(2,self.state.get(ref).damage_marked)
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current(self.enemy.card_id)).zone)

    def test_fight_lethal_damage_does_not_prevent_return_damage(self):
        p=CardProgram('cp-lethal','Lethal',('Creature',),power=4,toughness=1)
        self.game(extra=(p,));ref=self.add(p.definition_id)
        self.fx(ref,Select(Selector(Zone.BATTLEFIELD,types=('Creature',),relation='opponent_controlled'),1,1,(Fight('source','selected'),)))
        self.assertIsNone(self.kernel.pending_choice)
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current(ref.card_id)).zone)
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current(self.enemy.card_id)).zone)

    def test_copy_preserves_copiable_type_additions(self):
        self.game();ref=self.add('cp-body',zone=Zone.HAND)
        self.state.move((ZoneMove(ref,Zone.BATTLEFIELD,copied_definition='cp-body',copied_add_types=('Enchantment',)),),'scenario')
        ref=self.state.current(ref.card_id)
        self.clone(ref);view=self.kernel.effective(self.tokens()[0].ref)
        self.assertEqual({'Creature','Enchantment'},view.types);self.restore()

    def test_helm_haste_survives_end_of_turn(self):
        self.game('helm-of-the-host');self.equip();self.combat();self.drain();token=self.tokens()[0]
        for _ in range(30):
            if self.kernel.active=='B':break
            if self.kernel.phase=='declare_attackers' and self.kernel.priority is None:
                self.kernel.declare_attackers('A',{},revision=self.kernel.revision)
            else:self.round()
        self.assertEqual('B',self.kernel.active);self.assertIn('haste',self.kernel.effective(token.ref).keywords)

    def test_checkpoint_requires_copy_registry_schema(self):
        self.game();snapshot=self.kernel.snapshot();self.assertEqual(123,snapshot['schema']);self.assertEqual(14,snapshot['state']['schema'])
        snapshot['schema']=122
        with self.assertRaises(RulesViolation):RulesKernel.restore(snapshot,self.programs)
        from edh_gauntlet.rules_identity import IMPLEMENTATION_MANIFEST
        self.assertIn('rules_copy.py',IMPLEMENTATION_MANIFEST['modules'])
