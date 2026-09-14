"""Hosted conformance for existing-permanent copies and power/excess damage."""
import json
import unittest
from dataclasses import replace
from pathlib import Path
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,RulesViolation,Zone,ZoneMove
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_actor import project_actor
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed,digest,source_facts
from edh_gauntlet.catalog import load_catalog
from edh_gauntlet.rules_subtypes import NONBASIC_LAND_TYPES

CARDS=('mirage-mirror','thespian-s-stage','march-from-velis-vel','ram-through')


class PermanentCopyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        reviewed=load_reviewed(cls.root)
        drafts=json.loads((cls.root/'data/rules/draft_cards.json').read_text(encoding='utf-8'))['drafts']
        rows={r['card_id']:r for r in drafts if r['card_id'] in CARDS}
        cls.rows=rows
        cls.cards={key:validate(decode(rows[key]['program'])) for key in CARDS}
        cls.base=tuple(r['program'] for r in reviewed.values())+tuple(cls.cards.values())

    def game(self,card='mirage-mirror',zone=Zone.BATTLEFIELD,extra=()):
        body=CardProgram('pc-body','Body',('Creature',),subtypes=('Elf',),colors=('G',),power=2,toughness=3,
            mana_value=2,cast=CastSpec(CostSpec(ManaCost(1,('G',)))))
        etb=replace(body,definition_id='pc-etb',name='Entry life',
            abilities=(AbilityProgram('entry-life',EventPattern('zone_changed',to_zone=Zone.BATTLEFIELD,subject='self'),(GainLife(1),)),))
        desert=CardProgram('pc-desert','Desert',('Land',),subtypes=('Desert',))
        gate=CardProgram('pc-gate','Gate',('Land',),subtypes=('Gate',))
        aura=CardProgram('pc-aura','Aura',('Enchantment',),enchant=Selector(Zone.BATTLEFIELD,types=('Creature',)))
        equipment=CardProgram('pc-equipment','Equipment',('Artifact',),subtypes=('Equipment',),
            activated=(ActivatedProgram('equip',CostSpec(),(Attach('source','target'),),
                targets=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled')),timing='sorcery'),))
        remove=CardProgram('pc-remove','Remove',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD)),spell_effects=(Move('target',Zone.GRAVEYARD),))
        phase=replace(remove,definition_id='pc-phase',name='Phase',spell_effects=(PhaseOut('target'),))
        clone=replace(body,definition_id='pc-clone',name='Clone',entry_copy=Selector(Zone.BATTLEFIELD,types=('Creature',)))
        self.programs=self.base+(body,etb,desert,gate,aura,equipment,remove,phase,clone)+extra
        self.state=RulesState(('A','B','C','D'));self.kernel=RulesKernel(self.state,self.programs)
        self.kernel.open_window_for_scenario('A');self.serial=0
        self.source=self.add(self.cards[card].definition_id,'A',zone)
        self.body=self.add('pc-body');self.enemy=self.add('pc-body','B')
        for player in self.state.players:
            for _ in range(12):self.add('catalog:forest',player,Zone.LIBRARY)

    def add(self,definition='pc-body',actor='A',zone=Zone.BATTLEFIELD,**kw):
        self.serial+=1
        return self.state.add_card('pc-object-'+str(self.serial),definition,actor,zone,**kw)

    def window(self,actor='A'):
        if not self.kernel.stack and self.kernel.turn_schedule is None:
            self.kernel.open_window_for_scenario(self.kernel.active,phase=self.kernel.phase,priority_actor=actor)
        while self.kernel.priority!=actor:self.kernel.pass_priority(self.kernel.priority)

    def round(self):
        for _ in self.state.live_players:result=self.kernel.pass_priority(self.kernel.priority)
        return result

    def drain(self):
        for _ in range(400):
            q=self.kernel.pending_choice
            if q:
                self.kernel.answer(q.request_id,q.actor,list(range(len(q.options))) if q.kind=='trigger_order' else list(range(q.minimum)))
            elif self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
            else:return
        self.fail('No idle resolution boundary')

    def fx(self,source,*effects):
        return self.kernel.execute_for_scenario(source,self.state.get(source).controller,effects)

    def activate(self,targets,source=None,ability='copy',mana='CC'):
        source=self.source if source is None else source;self.window()
        if mana:self.state.add_mana('A',tuple(mana))
        self.serial+=1
        quote=self.kernel.quote_activation('pc-act-'+str(self.serial),'A',source,ability,targets)
        return self.kernel.commit_action(quote,Payment(tuple((s,mana.count(s)) for s in sorted(set(mana)))))

    def cast(self,targets,source=None,mana='CCU',alternative=None):
        source=self.source if source is None else source;self.window()
        if mana:self.state.add_mana('A',tuple(mana))
        self.serial+=1
        quote=self.kernel.quote_cast('pc-cast-'+str(self.serial),'A',source,targets,alternative_id=alternative)
        return self.kernel.commit_action(quote,Payment(tuple((s,mana.count(s)) for s in sorted(set(mana)))))

    def respond(self,definition,ref):
        spell=self.add(definition,'A',Zone.HAND);self.cast((ref,),spell,mana='');self.round()

    def copy(self,target=None,source=None):
        self.activate((self.body if target is None else target,),source);self.drain()

    def cleanup(self):
        self.kernel._finish_cleanup_actions();self.kernel.advance();self.drain()

    def restore(self):
        before=self.kernel.snapshot();self.kernel=RulesKernel.restore(before,self.programs);self.state=self.kernel.state
        self.assertEqual(before,self.kernel.snapshot())

    def name(self,ref):return self.kernel.definition(self.state.get(ref)).name
    def zone(self,ref):return self.state.get(self.state.current(ref.card_id)).zone
    def tokens(self):return tuple(o for o in self.state.objects(Zone.BATTLEFIELD) if o.token)

    def march(self,kind='Desert',target=None,alternative=None):
        self.cast((self.body if target is None else target,),mana='CCCCU' if alternative else 'CCU',alternative=alternative)
        self.round();q=self.kernel.pending_choice
        self.assertEqual('subtype',q.kind);self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.key==kind)])
        self.drain()

    def ram(self,source=None,target=None):
        self.cast((self.body if source is None else source,self.enemy if target is None else target),mana='CG');self.drain()

    def test_all_printed_faces_are_exactly_bound(self):
        catalog={c.card_id:c for c in load_catalog(self.root/'data/catalog/cards.json')}
        for key,p in self.cards.items():
            self.assertEqual('draft:'+key,p.definition_id)
            self.assertEqual(digest(source_facts(catalog[key])),digest(self.rows[key]['source_facts']))
            self.assertEqual(p,validate(decode(encode(p))))
            for attr in ('types','subtypes','supertypes','colors'):
                self.assertEqual(set(getattr(catalog[key].faces[0],attr)),set(getattr(p,attr)))
        self.assertEqual(ManaCost(2,('U',)),self.cards['march-from-velis-vel'].cast.cost.mana)
        self.assertEqual(ManaCost(4,('U',)),self.cards['march-from-velis-vel'].cast.alternatives[0].cost.mana)

    def test_mirror_copies_current_values_and_loses_its_activation(self):
        self.game();self.copy()
        self.assertEqual('Body',self.name(self.source))
        self.assertEqual({'Creature'},self.kernel.effective(self.source).types)
        self.assertEqual((),self.kernel.activated_abilities(self.state.get(self.source)))
        with self.assertRaises(RulesViolation):self.activate((self.enemy,))

    def test_mirror_keeps_identity_counters_tap_and_control_history(self):
        self.game();self.state.add_counters(self.source,'+1/+1',2);self.state.set_tapped_batch((self.source,),True)
        before=self.state.get(self.source);events=self.state.event_count;self.copy()
        after=self.state.get(self.source)
        for field in ('ref','definition','owner','controller','token','commander','timestamp','controlled_since','counters','tapped'):
            self.assertEqual(getattr(before,field),getattr(after,field))
        self.assertEqual(events,self.state.event_count)
        self.assertEqual((4,5),(self.kernel.effective(self.source).power,self.kernel.effective(self.source).toughness))

    def test_copy_does_not_apply_entry_counters_tap_or_triggers(self):
        p=CardProgram('pc-entry','Entry land',('Land',),entry_counters=(EntryCounters('ice','ice',10),),
            entry_modifiers=(EntryModifier('tapped',tapped=True),),
            abilities=(AbilityProgram('entry',EventPattern('zone_changed',to_zone=Zone.BATTLEFIELD,subject='self'),(GainLife(10),)),))
        self.game(extra=(p,));target=self.add(p.definition_id);self.copy(target)
        obj=self.state.get(self.source)
        self.assertFalse(obj.tapped);self.assertEqual((),obj.counters);self.assertEqual(40,self.state.life('A'))

    def test_copied_entry_trigger_works_on_a_subsequent_token(self):
        self.game();self.copy(self.add('pc-etb'));self.fx(self.source,CopyTokens('source'));self.drain()
        self.assertEqual(41,self.state.life('A'));self.assertEqual('Entry life',self.kernel.definition(self.tokens()[0]).name)

    def test_copied_upkeep_ability_uses_current_registry(self):
        p=CardProgram('pc-upkeep','Upkeep',('Enchantment',),
            abilities=(AbilityProgram('gain',EventPattern('step_began',step='upkeep',controller_only=True),(GainLife(2),)),))
        self.game(extra=(p,));self.copy(self.add(p.definition_id,'B'));self.kernel.begin_step('A','upkeep');self.drain()
        self.assertEqual(42,self.state.life('A'))

    def test_copies_ignore_target_counters_and_animation(self):
        self.game();land=self.add('catalog:forest')
        self.state.add_counters(land,'+1/+1',4)
        self.fx(land,UntilEndOfTurn('source',(ChangeTypes(('Creature',),()),SetPT(5,5),AddKeywords(('haste',)))))
        self.copy(land)
        self.assertEqual({'Land'},self.kernel.effective(self.source).types);self.assertEqual((),self.state.get(self.source).counters)

    def test_independent_temporary_modifier_survives_copy(self):
        self.game();self.fx(self.source,UntilEndOfTurn('source',(ModifyPT(3,4),)))
        self.copy();self.assertEqual((5,7),(self.kernel.effective(self.source).power,self.kernel.effective(self.source).toughness))

    def test_multiple_queued_copies_resolve_in_stack_order(self):
        self.game();land=self.add('catalog:forest')
        self.activate((self.body,));self.activate((land,));self.round()
        self.assertEqual('Forest',self.name(self.source));self.round()
        self.assertEqual('Body',self.name(self.source));self.assertEqual(2,len(self.state.get(self.source).copy_effects))
        self.cleanup();self.assertEqual('Mirage Mirror',self.name(self.source));self.assertEqual((),self.state.get(self.source).copy_effects)

    def test_copy_expiration_restores_original_abilities(self):
        self.game();self.copy();self.cleanup()
        self.assertEqual(['copy'],[a.ability_id for a in self.kernel.activated_abilities(self.state.get(self.source))])

    def test_copy_source_leaving_does_not_change_new_incarnation(self):
        self.game();self.activate((self.body,));self.respond('pc-remove',self.source);self.drain()
        ref=self.state.current(self.source.card_id)
        self.assertEqual('Mirage Mirror',self.name(ref));self.assertEqual((),self.state.get(ref).copy_effects)

    def test_target_leaving_makes_copy_fail(self):
        self.game();self.activate((self.body,));self.respond('pc-remove',self.body);self.drain()
        self.assertEqual('Mirage Mirror',self.name(self.source))

    def test_phased_copy_source_is_unaffected_by_resolving_activation(self):
        self.game();self.activate((self.body,));self.respond('pc-phase',self.source);self.drain()
        self.assertTrue(self.state.get(self.source).phased);self.assertEqual('Mirage Mirror',self.name(self.source))

    def test_phased_copy_effect_still_expires_at_cleanup(self):
        self.game();self.copy();self.fx(self.source,PhaseOut('source'));self.cleanup()
        self.assertTrue(self.state.get(self.source).phased);self.assertEqual('Mirage Mirror',self.name(self.source))

    def test_mirror_as_unattached_aura_goes_to_graveyard(self):
        self.game();aura=self.add('pc-aura');self.state.attach(aura,self.body);self.copy(aura)
        self.assertEqual(Zone.GRAVEYARD,self.zone(self.source))

    def test_equipment_copy_detaches_when_it_expires(self):
        self.game();self.copy(self.add('pc-equipment'))
        self.activate((self.body,),ability='equip',mana='');self.drain()
        self.assertEqual(self.body,self.state.get(self.source).attached_to)
        self.cleanup();self.assertIsNone(self.state.get(self.source).attached_to)

    def test_copy_of_copy_freezes_values_past_original_expiration(self):
        self.game();self.copy();self.fx(self.source,CopyTokens('source'));token=self.tokens()[0]
        self.cleanup();self.assertEqual('Body',self.kernel.definition(self.state.get(token.ref)).name)
        self.assertEqual('Mirage Mirror',self.name(self.source))

    def test_entry_copy_observes_an_existing_permanent_copy(self):
        self.game();self.copy();ref=self.add('pc-clone','A',Zone.HAND)
        self.kernel.enter(ref);q=self.kernel.pending_choice
        self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.ref==self.source)]);self.drain()
        self.cleanup();self.assertEqual('Body',self.name(self.state.current(ref.card_id)))

    def test_stage_keeps_copy_activation_but_replaces_original_mana(self):
        self.game('thespian-s-stage');self.copy(self.add('catalog:forest'))
        self.assertTrue(self.state.get(self.source).tapped)
        abilities=self.kernel.activated_abilities(self.state.get(self.source))
        self.assertEqual(2,len(abilities));self.assertTrue(any(a.ability_id=='copy' for a in abilities))
        self.assertFalse(any(a.ability_id=='colorless' for a in abilities));self.cleanup()
        self.assertEqual('Forest',self.name(self.source))

    def test_stage_can_copy_again_after_untapping(self):
        self.game('thespian-s-stage');self.copy(self.add('catalog:forest'))
        self.state.set_tapped_batch((self.source,),False);self.copy(self.add('catalog:island'))
        self.assertEqual('Island',self.name(self.source));self.assertEqual(2,len(self.state.get(self.source).copy_effects))

    def test_stage_retained_activation_is_copiable(self):
        self.game('thespian-s-stage');self.copy(self.add('catalog:forest'));self.fx(self.source,CopyTokens('source'))
        token=self.tokens()[0]
        self.assertTrue(any(a.ability_id=='copy' for a in self.kernel.activated_abilities(token)));self.restore()

    def test_stage_copying_itself_retains_distinct_activation_ids(self):
        self.game('thespian-s-stage');self.copy(self.source)
        ids=[a.ability_id for a in self.kernel.activated_abilities(self.state.get(self.source))]
        self.assertEqual(3,len(ids));self.assertEqual(3,len(set(ids)))

    def test_stage_dark_depths_gets_no_ice_and_triggers_sacrifice(self):
        self.game('thespian-s-stage');depths=self.add('catalog:dark-depths','B',Zone.HAND)
        self.kernel.enter(depths);depths=self.state.current(depths.card_id);self.drain()
        self.copy(depths)
        self.assertEqual(Zone.GRAVEYARD,self.zone(self.source))
        self.assertEqual(10,dict(self.state.get(depths).counters)['ice'])
        self.assertEqual(['Marit Lage'],[self.kernel.definition(t).name for t in self.tokens()])

    def test_temporary_overwrite_reveals_earlier_indefinite_copy(self):
        self.game('thespian-s-stage');self.copy(self.add('catalog:forest'))
        self.fx(self.source,Select(Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled'),1,1,(CopyPermanent('source','selected',until_end_of_turn=True),)))
        self.assertEqual('Body',self.name(self.source));self.cleanup();self.assertEqual('Forest',self.name(self.source))

    def test_existing_copy_type_exception_is_replaced_by_new_copy(self):
        self.game();ref=self.add(self.cards['mirage-mirror'].definition_id,'A',Zone.HAND)
        self.state.move((ZoneMove(ref,Zone.BATTLEFIELD,copied_definition=self.cards['mirage-mirror'].definition_id,copied_add_types=('Enchantment',)),),'scenario')
        ref=self.state.current(ref.card_id);self.copy(source=ref)
        self.assertEqual({'Creature'},self.kernel.effective(ref).types)
        self.fx(ref,CopyTokens('source'));self.assertEqual({'Creature'},self.kernel.effective(self.tokens()[0].ref).types)
        self.cleanup();self.assertEqual({'Artifact','Enchantment'},self.kernel.effective(ref).types)

    def test_copy_survives_control_change_and_resets_on_zone_change(self):
        self.game('thespian-s-stage');self.copy(self.add('catalog:forest'))
        self.state.change_control(self.source,'B');self.assertEqual('Forest',self.name(self.source))
        self.state.move((ZoneMove(self.source,Zone.HAND),),'scenario')
        current=self.state.current(self.source.card_id);self.assertEqual("Thespian's Stage",self.name(current))
        self.assertEqual((),self.state.get(current).copy_effects)

    def test_march_choices_are_all_and_only_nonbasic_land_types(self):
        self.game('march-from-velis-vel',Zone.HAND);self.cast((self.body,));self.round()
        q=self.kernel.pending_choice
        self.assertEqual(NONBASIC_LAND_TYPES,{o.key for o in q.options});self.assertEqual((1,1),(q.minimum,q.maximum))
        self.restore()
        with self.assertRaises(RulesViolation):self.kernel.answer(q.request_id,'B',[0])

    def test_march_changes_only_current_controlled_matching_lands(self):
        self.game('march-from-velis-vel',Zone.HAND)
        desert=self.add('pc-desert');gate=self.add('pc-gate');enemy=self.add('pc-desert','B')
        self.state.set_tapped_batch((desert,),True);self.march()
        self.assertEqual('Body',self.name(desert));self.assertTrue(self.state.get(desert).tapped)
        self.assertIn('haste',self.kernel.effective(desert).keywords)
        self.assertEqual('Gate',self.name(gate));self.assertEqual('Desert',self.name(enemy))
        later=self.add('pc-desert');self.assertEqual('Desert',self.name(later))
        self.cleanup();self.assertEqual('Desert',self.name(desert));self.assertNotIn('haste',self.kernel.effective(desert).keywords)

    def test_march_haste_is_separate_from_copiable_values(self):
        self.game('march-from-velis-vel',Zone.HAND);desert=self.add('pc-desert');self.march()
        self.fx(desert,CopyTokens('source'))
        self.assertNotIn('haste',self.kernel.effective(self.tokens()[0].ref).keywords)

    def test_march_accepts_a_type_with_no_matching_lands(self):
        self.game('march-from-velis-vel',Zone.HAND);self.march('Lair')
        self.assertEqual(Zone.GRAVEYARD,self.zone(self.source));self.assertFalse(any(o.copy_effects for o in self.state.objects()))

    def test_march_flashback_uses_alternative_cost_and_exiles(self):
        self.game('march-from-velis-vel',Zone.GRAVEYARD);desert=self.add('pc-desert');self.march(alternative='flashback')
        self.assertEqual('Body',self.name(desert));self.assertEqual(Zone.EXILE,self.zone(self.source))

    def test_march_illegal_target_skips_subtype_choice(self):
        self.game('march-from-velis-vel',Zone.HAND);self.cast((self.body,));self.respond('pc-remove',self.body);self.drain()
        self.assertIsNone(self.kernel.pending_choice);self.assertEqual(Zone.GRAVEYARD,self.zone(self.source))

    def test_march_phased_matching_land_is_ignored(self):
        self.game('march-from-velis-vel',Zone.HAND);desert=self.add('pc-desert');self.state.phase(desert,True);self.march()
        self.assertEqual('Desert',self.name(desert))

    def test_march_copies_target_that_is_itself_a_matching_land(self):
        land=CardProgram('pc-land-body','Desert body',('Creature','Land'),subtypes=('Desert','Dryad'),power=3,toughness=4)
        self.game('march-from-velis-vel',Zone.HAND,extra=(land,));one=self.add(land.definition_id);two=self.add('pc-desert')
        self.march(target=one)
        self.assertEqual('Desert body',self.name(one));self.assertEqual('Desert body',self.name(two))
        self.assertEqual(self.state.get(one).copy_effects[0][2],self.state.get(two).copy_effects[0][2])

    def test_copy_checkpoint_restores_registry_and_underlying_layers(self):
        self.game('thespian-s-stage');self.copy(self.add('catalog:forest'))
        self.fx(self.source,Select(Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled'),1,1,(CopyPermanent('source','selected',until_end_of_turn=True),)))
        self.restore();self.cleanup();self.assertEqual('Forest',self.name(self.source))

    def test_copy_ledger_rejects_unknown_and_invalid_historical_layers(self):
        self.game('thespian-s-stage');self.copy(self.add('catalog:forest'))
        for field,value in ((0,'missing'),(1,'forever'),(2,False),(2,0)):
            snapshot=self.kernel.snapshot();row=next(o for o in snapshot['state']['objects'] if o['ref']==self.source.to_json())
            row['copy_effects'][0][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(RulesViolation):RulesKernel.restore(snapshot,self.programs)

    def test_stage_actor_replay_preserves_copy_activation_snapshot(self):
        self.game('thespian-s-stage');land=self.add('catalog:forest');self.state.add_mana('A',tuple('CC'))
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        command={'kind':'activate','revision':self.kernel.revision,'action_id':'stage-actor','source':self.source.to_json(),
            'ability_id':'copy','targets':[land.to_json()],'x_value':0,'payment':Payment((('C',2),)).to_json()}
        for item in (adapter,replay):
            item.submit('A',command)
            while item.kernel.stack:item.kernel.pass_priority(item.kernel.priority)
        self.assertEqual(self.kernel.snapshot(),replay.kernel.snapshot())
        self.assertEqual('Forest',self.name(self.source))

    def test_ram_normal_damage_is_one_way_and_noncombat(self):
        self.game('ram-through',Zone.HAND);self.ram()
        self.assertEqual(2,self.state.get(self.enemy).damage_marked);self.assertEqual(0,self.state.get(self.body).damage_marked)
        self.assertEqual(40,self.state.life('B'))
        self.assertTrue(all(not e['combat'] for e in self.kernel.semantic_events if e['kind']=='damage_dealt'))

    def test_ram_trample_excess_is_simultaneous(self):
        p=CardProgram('pc-trample','Trample',('Creature',),power=8,toughness=4,keywords=('trample','lifelink'))
        self.game('ram-through',Zone.HAND,extra=(p,));source=self.add(p.definition_id);self.ram(source)
        self.assertEqual(35,self.state.life('B'));self.assertEqual(48,self.state.life('A'));self.assertEqual(Zone.GRAVEYARD,self.zone(self.enemy))
        self.assertEqual(0,self.state.get(source).damage_marked)

    def test_ram_accounts_for_damage_already_marked(self):
        p=CardProgram('pc-trample','Trample',('Creature',),power=5,toughness=4,keywords=('trample',))
        self.game('ram-through',Zone.HAND,extra=(p,));source=self.add(p.definition_id)
        self.kernel._deal_damage([(self.state.get(self.body),self.enemy,2)]);self.ram(source)
        self.assertEqual(36,self.state.life('B'))

    def test_ram_deathtouch_reduces_lethal_to_one(self):
        p=CardProgram('pc-deadly','Deadly',('Creature',),power=5,toughness=4,keywords=('trample','deathtouch'))
        self.game('ram-through',Zone.HAND,extra=(p,));self.ram(self.add(p.definition_id))
        self.assertEqual(36,self.state.life('B'));self.assertEqual(Zone.GRAVEYARD,self.zone(self.enemy))

    def test_ram_excess_ignores_indestructible(self):
        source=CardProgram('pc-trample','Trample',('Creature',),power=8,toughness=4,keywords=('trample',))
        target=CardProgram('pc-indestructible','Indestructible',('Creature',),power=2,toughness=3,keywords=('indestructible',))
        self.game('ram-through',Zone.HAND,extra=(source,target));victim=self.add(target.definition_id,'B');self.ram(self.add(source.definition_id),victim)
        self.assertEqual(35,self.state.life('B'));self.assertEqual(3,self.state.get(victim).damage_marked)

    def test_ram_source_power_is_read_on_resolution(self):
        self.game('ram-through',Zone.HAND);self.cast((self.body,self.enemy),mana='CG')
        self.state.add_counters(self.body,'+1/+1',2);self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.zone(self.enemy));self.assertEqual(40,self.state.life('B'))

    def test_ram_no_damage_if_either_target_leaves(self):
        for which in ('body','enemy'):
            with self.subTest(which=which):
                self.game('ram-through',Zone.HAND);self.cast((self.body,self.enemy),mana='CG')
                self.respond('pc-remove',getattr(self,which));self.drain()
                self.assertEqual(40,self.state.life('B'))
                self.assertFalse(any(e['kind']=='damage_dealt' for e in self.kernel.semantic_events))

    def test_ram_rechecks_target_control(self):
        self.game('ram-through',Zone.HAND);self.cast((self.body,self.enemy),mana='CG')
        self.state.change_control(self.enemy,'A');self.drain()
        self.assertFalse(any(e['kind']=='damage_dealt' for e in self.kernel.semantic_events))

    def test_ram_negative_power_deals_no_damage(self):
        self.game('ram-through',Zone.HAND);self.fx(self.body,UntilEndOfTurn('source',(ModifyPT(-5,0),)))
        self.ram();self.assertEqual(0,self.state.get(self.enemy).damage_marked);self.assertEqual(40,self.state.life('B'))

    def test_new_compiler_rejects_unbound_and_invalid_copy_instructions(self):
        for effect in (CopyPermanent('missing'),CopyPermanent('source',until_end_of_turn=1),
                CopyPermanent('source',retain_activation=True),PowerDamage('missing','source'),
                SelectBySubtype(Selector(Zone.BATTLEFIELD,types=('Creature',)),'nonbasic_land',()),
                SelectBySubtype(Selector(Zone.BATTLEFIELD,types=('Land',)),'creature',())):
            with self.subTest(effect=effect),self.assertRaises(RulesViolation):
                validate(CardProgram('bad','Bad',('Artifact',),spell_effects=(effect,)))

    def test_copy_ledger_atomicity_rejects_duplicate_recipients(self):
        self.game();before=self.state.snapshot()
        with self.assertRaises(RulesViolation):self.state.apply_copy((self.source,self.source),'pc-body')
        self.assertEqual(before,self.state.snapshot())

    def test_copied_static_ability_uses_copy_effect_timestamp(self):
        setter=lambda key,amount:ContinuousProgram(key,Selector(Zone.BATTLEFIELD,types=('Creature',)),(SetPT(amount,amount),))
        low=CardProgram('pc-low','Low',('Enchantment',),continuous=(setter('set',2),))
        high=CardProgram('pc-high','High',('Enchantment',),continuous=(setter('set',7),))
        self.game(extra=(low,high))
        target=self.add(low.definition_id,'B');self.add(high.definition_id,'B')
        self.assertEqual(7,self.kernel.effective(self.body).power)
        self.copy(target);self.assertEqual(2,self.kernel.effective(self.body).power)
        self.cleanup();self.assertEqual(7,self.kernel.effective(self.body).power)

    def test_damage_on_copy_recipient_survives_another_copy(self):
        p=CardProgram('pc-tough','Tough',('Creature',),power=2,toughness=8)
        self.game(extra=(p,));self.copy(self.add(p.definition_id))
        self.kernel._deal_damage([(self.state.get(self.enemy),self.source,2)])
        self.fx(self.source,Select(Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled',
            exclude_source=True,characteristics=(CharacteristicRange('toughness',3,3),)),1,1,
            (CopyPermanent('source','selected',until_end_of_turn=True),)))
        self.assertEqual(2,self.state.get(self.source).damage_marked);self.assertEqual('Body',self.name(self.source))

    def test_stage_copy_target_domain_rejects_nonland_atomically(self):
        self.game('thespian-s-stage');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',self.source,'copy',(self.body,))
        self.assertEqual(before,self.kernel.snapshot())

    def test_ram_group_domains_reject_reversed_targets(self):
        self.game('ram-through',Zone.HAND);before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',self.source,(self.enemy,self.body))
        self.assertEqual(before,self.kernel.snapshot())

    def test_ram_actor_projection_and_checkpoint_preserve_target_groups(self):
        self.game('ram-through',Zone.HAND);self.cast((self.body,self.enemy),mana='CG')
        packet=project_actor(self.kernel,'B')
        self.assertEqual([{'group_id':'dealer','targets':[self.body.to_json()]},
            {'group_id':'victim','targets':[self.enemy.to_json()]}],packet['stack'][0]['target_groups'])
        self.restore();self.drain();self.assertEqual(2,self.state.get(self.enemy).damage_marked)

    def test_copied_land_current_mana_ability_works(self):
        self.game();self.copy(self.add('catalog:forest'))
        self.activate((),ability='intrinsic-land:Forest',mana='')
        self.assertEqual((('G',1),),self.state.mana_pool('A'))

    def test_fixed_spell_groups_can_target_same_object_in_separate_clauses(self):
        target=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',)))
        p=CardProgram('pc-two-clauses','Two clauses',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_targets=TargetSpec(minimum=2,maximum=2,groups=(TargetGroup('one',target),TargetGroup('two',target))),
            spell_effects=(AddCounters('target:one','+1/+1',1),AddCounters('target:two','+1/+1',2)))
        self.game(extra=(p,));spell=self.add(p.definition_id,'A',Zone.HAND)
        self.cast((self.body,self.body),spell,mana='');self.restore();self.drain()
        self.assertEqual(3,dict(self.state.get(self.body).counters)['+1/+1'])

    def test_spell_group_compiler_rejects_variable_or_unbounded_clauses(self):
        selector=Selector(Zone.BATTLEFIELD,types=('Creature',))
        for target in (TargetSpec(selector,0,None,True),
                TargetSpec(minimum=0,maximum=1,groups=(TargetGroup('optional',TargetSpec(selector,0,1)),))):
            with self.subTest(target=target),self.assertRaises(RulesViolation):
                validate(CardProgram('bad','Bad',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
                    spell_targets=target,spell_effects=(AddCounters('target','+1/+1',1),)))
