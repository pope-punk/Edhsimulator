"""Full card programs with phasing, owned steps and opponent-authored choices."""
import json
import unittest
from dataclasses import replace
from pathlib import Path
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,RulesViolation,Zone,ZoneMove,PlayerRef
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed,digest,source_facts
from edh_gauntlet.catalog import load_catalog

CARDS=('talon-gates-of-madara','desert-warfare','indulgent-tormentor','volatile-fault')


class PhasingChoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        reviewed=load_reviewed(cls.root)
        cls.rows={key:reviewed[key]['review'] for key in CARDS}
        cls.cards={key:reviewed[key]['program'] for key in CARDS}
        cls.base=tuple(row['program'] for row in reviewed.values())

    def game(self,key='talon-gates-of-madara',*,zone=Zone.BATTLEFIELD,extra=()):
        body=CardProgram('p-body','Body',('Creature',),power=2,toughness=4)
        basic=CardProgram('p-basic','Basic',('Land',),subtypes=('Forest',),supertypes=('Basic',))
        land=CardProgram('p-land','Land',('Land',),subtypes=('Cave',))
        desert=CardProgram('p-desert','Desert',('Land',),subtypes=('Desert',))
        remove=CardProgram('p-remove','Remove',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD)),spell_effects=(Move('target',Zone.GRAVEYARD),))
        stifle=replace(remove,definition_id='p-stifle',name='Stifle',spell_targets=None,spell_effects=(CounterAbilities(),))
        self.programs=self.base+(body,basic,land,desert,remove,stifle)+extra
        self.state=RulesState(('A','B','C','D'));self.kernel=RulesKernel(self.state,self.programs)
        self.kernel.open_window_for_scenario('A');self.number=0
        self.source=self.state.add_card('source',self.cards[key].definition_id,'A',zone)
        self.body=self.state.add_card('body','p-body','B',Zone.BATTLEFIELD)
        self.other=self.state.add_card('other','p-body','A',Zone.BATTLEFIELD)
        self.land=self.state.add_card('land','p-land','B',Zone.BATTLEFIELD)
        for p in self.state.players:
            for n in range(10):self.state.add_card('library-'+p+'-'+str(n),'p-body',p,Zone.LIBRARY)
        self.basic=self.state.add_card('basic','p-basic','B',Zone.LIBRARY)

    def ident(self):
        self.number+=1
        return 'p-action-'+str(self.number)

    def window(self,actor='A'):
        if not self.kernel.stack and self.kernel.turn_schedule is None:self.kernel.open_window_for_scenario('A',priority_actor=actor)
        while self.kernel.priority!=actor:self.kernel.pass_priority(self.kernel.priority)

    def top(self):
        self.assertTrue(self.kernel.stack)
        for _ in self.state.live_players:result=self.kernel.pass_priority(self.kernel.priority)
        return result

    def choose(self,key):
        q=self.kernel.pending_choice;self.assertIsNotNone(q)
        return self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.key==key)])

    def targets(self,refs=()):
        q=self.kernel.pending_choice;self.assertEqual('trigger_targets',q.kind)
        return self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options)
            if o.ref==ref or isinstance(ref,str) and o.player==ref) for ref in refs])

    def order(self):
        q=self.kernel.pending_choice;self.assertEqual('trigger_order',q.kind)
        return self.kernel.answer(q.request_id,q.actor,list(range(len(q.options))))

    def effect(self,ref,*effects,actor='A'):
        return self.kernel.execute_for_scenario(ref,actor,effects)

    def cast(self,ref,actor='A',targets=(),mana=()):
        self.window(actor);symbols=tuple(mana)
        if symbols:self.state.add_mana(actor,symbols)
        return self.kernel.commit_action(self.kernel.quote_cast(self.ident(),actor,ref,targets),
            Payment(tuple((s,symbols.count(s)) for s in sorted(set(symbols)))))

    def response(self,targets=(),definition='p-remove',actor='B'):
        ref=self.state.add_card(self.ident(),definition,actor,Zone.HAND)
        return self.cast(ref,actor,targets)

    def activate(self,ability,targets=(),mana=()):
        self.window();symbols=tuple(mana)
        if symbols:self.state.add_mana('A',symbols)
        return self.kernel.commit_action(self.kernel.quote_activation(self.ident(),'A',self.source,ability,targets),
            Payment(tuple((s,symbols.count(s)) for s in sorted(set(symbols)))))

    def fault(self):return self.activate('fault',(self.land,),'C')
    def hand(self,actor):return len(self.state.zone(actor,Zone.HAND))
    def token_refs(self,subtype):return tuple(o.ref for o in self.state.objects(Zone.BATTLEFIELD) if o.token and subtype in self.kernel.effective(o.ref).subtypes)

    def discover_step(self,actor,step,*,kernel=None):
        # Focused trigger fixture; integration cases below traverse real turns.
        kernel=self.kernel if kernel is None else kernel
        kernel._idle();self.assertIsNone(kernel.turn_schedule);self.assertFalse(kernel.stack)
        kernel.active=actor;kernel._begin_phase(step)
        return kernel.advance()

    def end_step(self,actor='A'):
        self.discover_step(actor,'end_step')
        if self.kernel.pending_choice:self.order()

    def deserts(self,count=5,owner='A'):
        return tuple(self.state.add_card('desert-'+owner+'-'+str(n),'p-desert',owner,Zone.BATTLEFIELD) for n in range(count))

    def upkeep_choice(self,opponent='B'):
        self.kernel.begin_step('A','upkeep');self.targets((opponent,));self.top()
        self.assertEqual(opponent,self.kernel.pending_choice.actor)

    def advance_to(self,phase,actor=None):
        for _ in range(180):
            if self.kernel.phase==phase and (actor is None or self.kernel.active==actor):return
            self.assertIsNone(self.kernel.pending_choice);self.assertFalse(self.kernel.stack)
            if self.kernel.phase=='declare_attackers' and self.kernel.priority is None:
                self.kernel.declare_attackers(self.kernel.active,{},revision=self.kernel.revision)
            else:self.kernel.pass_priority(self.kernel.priority)
        self.fail('Phase not reached')

    def test_full_printed_faces_hashes_costs_and_codec(self):
        catalog={c.card_id:c for c in load_catalog(self.root/'data/catalog/cards.json')}
        self.assertEqual(set(CARDS),set(self.cards))
        for key,program in self.cards.items():
            with self.subTest(card=key):
                self.assertEqual(digest(source_facts(catalog[key])),self.rows[key]['source_facts_sha256'])
                self.assertEqual(self.rows[key]['program'],encode(program))
                face=catalog[key].faces[0]
                for field in ('types','subtypes','supertypes','colors'):
                    self.assertEqual(set(getattr(face,field)),set(getattr(program,field)))
                for field in ('mana_value','power','toughness'):self.assertEqual(getattr(face,field),getattr(program,field))
                self.assertEqual(catalog[key].name,program.name)

    def test_talon_normal_land_play_and_optional_entry_target(self):
        self.game(zone=Zone.HAND);self.kernel.begin_turn_for_scenario('A');self.advance_to('precombat_main')
        self.kernel.play_land(self.ident(),'A',self.source,revision=self.kernel.revision);self.targets();self.top()
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('source')).zone)
        self.assertFalse(self.state.get(self.body).phased)

    def test_talon_entry_phases_target_without_zone_change(self):
        self.game(zone=Zone.HAND);self.kernel.enter(self.source);self.targets((self.body,))
        before=self.state.get(self.body);events=len(self.state.events)
        self.top();after=self.state.get(self.body)
        self.assertTrue(after.phased);self.assertEqual(before.ref,after.ref)
        self.assertEqual(before.timestamp,after.timestamp);self.assertEqual(events,len(self.state.events))

    def test_talon_colorless_and_five_color_mana_modes(self):
        for color in range(5):
            with self.subTest(color=color):
                self.game();self.activate('color',mana='C');self.choose(str(color))
                self.assertEqual((('WUBRG'[color],1),),self.state.mana_pool('A'));self.assertTrue(self.state.get(self.source).tapped)
        self.game();self.activate('colorless');self.assertEqual((('C',1),),self.state.mana_pool('A'))

    def test_talon_hand_activation_reveals_source_then_enters_and_triggers(self):
        self.game(zone=Zone.HAND);self.activate('hand-entry',mana='CCCC')
        packet=RulesActorAdapter(self.kernel).packet('B')
        self.assertEqual([self.source.to_json()],[r['ref'] for r in packet['revealed_hand']])
        self.assertEqual('hand-entry',packet['stack'][0]['ability_id'])
        self.top();self.targets((self.body,));self.top()
        self.assertEqual([],RulesActorAdapter(self.kernel).packet('B')['revealed_hand'])
        self.assertTrue(self.state.get(self.body).phased)

    def test_talon_countered_hand_activation_retains_hand_card_and_spent_mana(self):
        self.game(zone=Zone.HAND);self.activate('hand-entry',mana='CCCC')
        self.response(definition='p-stifle');self.top()
        self.assertEqual(Zone.HAND,self.state.get(self.source).zone);self.assertEqual((),self.state.mana_pool('A'))
        self.assertEqual([],RulesActorAdapter(self.kernel).packet('B')['revealed_hand'])

    def test_talon_hand_activation_does_not_follow_new_incarnation(self):
        self.game(zone=Zone.HAND);self.activate('hand-entry',mana='CCCC')
        self.state.move((ZoneMove(self.source,Zone.GRAVEYARD),),'fixture')
        self.state.move((ZoneMove(self.state.current('source'),Zone.HAND),),'fixture')
        self.top();self.assertEqual(Zone.HAND,self.state.get(self.state.current('source')).zone)

    def test_talon_illegal_entry_target_does_not_phase_a_new_object(self):
        self.game(zone=Zone.HAND);self.kernel.enter(self.source);self.targets((self.body,))
        self.response((self.body,));self.top();self.top()
        self.assertFalse(self.kernel.phase_links);self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('body')).zone)

    def test_phase_preserves_counters_tap_and_control_history_until_real_untap(self):
        self.game();self.state.add_counters(self.body,'test',3);self.state.set_tapped_batch((self.body,),True)
        before=self.state.get(self.body);self.effect(self.body,PhaseOut('source'))
        self.assertEqual(before.counters,self.state.get(self.body).counters)
        self.assertEqual(before.controlled_since,self.state.get(self.body).controlled_since)
        self.kernel.begin_turn_for_scenario('B');after=self.state.get(self.body)
        self.assertFalse(after.phased);self.assertFalse(after.tapped);self.assertEqual(before.timestamp,after.timestamp)

    def test_phase_indirect_equipment_follows_root_not_equipment_controller(self):
        equipment=CardProgram('equipment','Equipment',('Artifact',),subtypes=('Equipment',))
        self.game(extra=(equipment,));ref=self.state.add_card('equipment','equipment','A',Zone.BATTLEFIELD)
        self.state.attach(ref,self.body);self.effect(self.body,PhaseOut('source'))
        self.kernel.begin_turn_for_scenario('A');self.assertTrue(self.state.get(ref).phased)
        self.advance_to('upkeep','B')
        self.assertFalse(self.state.get(ref).phased);self.assertEqual(self.body,self.state.get(ref).attached_to)

    def test_phase_direct_aura_detaches_on_return_after_subject_leaves(self):
        aura=CardProgram('aura','Aura',('Enchantment',),subtypes=('Aura',),enchant=Selector(Zone.BATTLEFIELD,types=('Creature',)))
        self.game(extra=(aura,));ref=self.state.add_card('aura','aura','A',Zone.BATTLEFIELD);self.state.attach(ref,self.body)
        self.effect(ref,PhaseOut('source'));self.effect(self.body,Move('source',Zone.GRAVEYARD))
        self.kernel.begin_turn_for_scenario('A')
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('aura')).zone)

    def test_phase_multiple_selected_attachments_use_indirect_precedence(self):
        equipment=CardProgram('equipment','Equipment',('Artifact',),subtypes=('Equipment',))
        self.game(extra=(equipment,));ref=self.state.add_card('equipment','equipment','A',Zone.BATTLEFIELD)
        self.state.attach(ref,self.body);self.kernel._phase_out((ref,self.body))
        self.assertEqual(self.body.to_json(),self.kernel.phase_links[self.kernel._phase_key(ref)]['root'])
        self.kernel.begin_turn_for_scenario('A');self.assertTrue(self.state.get(ref).phased)

    def test_phase_keyword_phases_out_then_in_on_following_own_untap(self):
        phased=CardProgram('phaser','Phaser',('Creature',),power=2,toughness=2,keywords=('phasing',))
        self.game(extra=(phased,));ref=self.state.add_card('phaser','phaser','A',Zone.BATTLEFIELD)
        self.kernel.begin_turn_for_scenario('A');self.assertTrue(self.state.get(ref).phased)
        self.advance_to('upkeep','B');self.advance_to('upkeep','A')
        self.assertFalse(self.state.get(ref).phased)

    def test_phase_departed_controller_returns_at_skipped_seat_slot(self):
        self.game();ref=self.state.add_card('borrowed','p-body','C',Zone.BATTLEFIELD)
        self.effect(ref,GainControl('source'),actor='B');self.effect(ref,PhaseOut('source'))
        self.kernel._depart_players(('B',));self.kernel.advance()
        self.assertEqual('C',self.state.get(ref).controller);self.assertTrue(self.state.get(ref).phased)
        self.kernel.begin_turn_for_scenario('C');self.assertFalse(self.state.get(ref).phased)

    def test_phase_departure_during_own_turn_does_not_restore_on_immediate_next_seat(self):
        self.game();ref=self.state.add_card('borrowed','p-body','C',Zone.BATTLEFIELD)
        self.effect(ref,GainControl('source'),actor='B');self.effect(ref,PhaseOut('source'))
        self.kernel.open_window_for_scenario('B');self.kernel._depart_players(('B',));self.kernel.advance()
        self.kernel.begin_turn_for_scenario('C');self.assertTrue(self.state.get(ref).phased)
        self.advance_to('upkeep','D');self.advance_to('upkeep','A');self.advance_to('upkeep','C')
        self.assertFalse(self.state.get(ref).phased)

    def test_phase_owned_departure_does_not_trigger_battlefield_leaves(self):
        observer=CardProgram('observer','Observer',('Enchantment',),abilities=(AbilityProgram('left',
            EventPattern('zone_changed',from_zone=Zone.BATTLEFIELD,types=('Creature',)),(GainLife(1),)),))
        self.game(extra=(observer,));self.state.add_card('observer','observer','A',Zone.BATTLEFIELD)
        self.effect(self.body,PhaseOut('source'));self.kernel._depart_players(('B',));self.kernel.advance()
        self.assertEqual(40,self.state.life('A'));self.assertFalse(self.kernel.stack)

    def test_phase_orphaned_indirect_attachment_does_not_return_by_itself(self):
        equipment=CardProgram('equipment','Equipment',('Artifact',),subtypes=('Equipment',))
        self.game(extra=(equipment,));ref=self.state.add_card('equipment','equipment','A',Zone.BATTLEFIELD);self.state.attach(ref,self.body)
        self.effect(self.body,PhaseOut('source'));self.kernel._depart_players(('B',));self.kernel.advance()
        packet=RulesActorAdapter(self.kernel).packet('A')
        self.assertEqual(ref.to_json(),packet['phasing'][0]['ref'])
        self.assertIsNone(packet['phasing'][0]['return_controller'])
        self.kernel.begin_turn_for_scenario('A');self.assertTrue(self.state.get(ref).phased)

    def test_phase_counter_duration_expires_but_counter_survives(self):
        self.game();self.state.add_counters(self.body,'test',1)
        self.effect(self.body,WhileCounter('source',(AddKeywords(('haste',)),),'test'))
        self.effect(self.body,PhaseOut('source'));self.kernel.begin_turn_for_scenario('B')
        self.assertNotIn('haste',self.kernel.effective(self.body).keywords);self.assertEqual((('test',1),),self.state.get(self.body).counters)

    def test_phase_checkpoint_and_actor_replay_restore_same_untap(self):
        self.game(zone=Zone.HAND);self.activate('hand-entry',mana='CCCC');self.top();self.targets((self.body,))
        adapter=RulesActorAdapter(self.kernel)
        for _ in self.state.live_players:adapter.submit(self.kernel.priority,{'kind':'pass','revision':self.kernel.revision})
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())
        packet=RulesActorAdapter(self.kernel).packet('C')
        self.assertEqual('B',packet['phasing'][0]['return_controller'])
        self.assertEqual(self.body.to_json(),packet['phasing'][0]['ref'])
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.kernel.begin_turn_for_scenario('B');restored.begin_turn_for_scenario('B')
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())

    def test_desert_normal_cast_retains_cost_and_printed_behavior(self):
        self.game('desert-warfare',zone=Zone.HAND);self.cast(self.source,mana='CCCG');self.top()
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('source')).zone)
        self.assertEqual((),self.state.mana_pool('A'))

    def test_desert_sacrifice_returns_only_at_next_own_end_step(self):
        self.game('desert-warfare');ref=self.deserts(1)[0]
        self.effect(ref,Sacrifice('source'));self.top()
        self.kernel.begin_turn_for_scenario('B');self.advance_to('end_step','B')
        self.assertFalse(self.kernel.stack)
        self.advance_to('end_step','A');self.top()
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current(ref.card_id)).zone)

    def test_desert_destroy_does_not_count_as_sacrifice(self):
        self.game('desert-warfare');ref=self.deserts(1)[0]
        self.effect(ref,Destroy('source'));self.assertFalse(self.kernel.stack);self.assertFalse(self.kernel.delayed_triggers)

    def test_desert_discard_and_mill_capture_exact_graveyard_objects(self):
        for origin in (Zone.HAND,Zone.LIBRARY):
            with self.subTest(origin=origin):
                self.game('desert-warfare');ref=self.state.add_card('returned','p-desert','A',origin)
                self.effect(ref,Discard('source') if origin==Zone.HAND else Mill(1));self.top()
                self.end_step();self.top()
                self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('returned')).zone)

    def test_desert_does_not_recover_opponents_discard(self):
        self.game('desert-warfare');ref=self.state.add_card('discarded','p-desert','B',Zone.HAND)
        self.effect(ref,Discard('source'),actor='B');self.assertFalse(self.kernel.stack)

    def test_desert_recovers_borrowed_sacrificed_desert_under_trigger_controller(self):
        self.game('desert-warfare');ref=self.state.add_card('borrowed','p-desert','B',Zone.BATTLEFIELD)
        self.effect(ref,GainControl('source'));self.effect(ref,Sacrifice('source'));self.top()
        self.end_step();self.top();self.assertEqual('A',self.state.get(self.state.current('borrowed')).controller)

    def test_desert_sacrifice_replacement_keeps_public_successor(self):
        redirect=CardProgram('redirect','Redirect',('Artifact',),replacements=(
            ZoneReplacement('redirect',Zone.GRAVEYARD,Zone.EXILE,from_zone=Zone.BATTLEFIELD,types=('Land',)),))
        self.game('desert-warfare',extra=(redirect,));self.state.add_card('redirect','redirect','A',Zone.BATTLEFIELD)
        ref=self.deserts(1)[0];self.effect(ref,Sacrifice('source'));self.top()
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current(ref.card_id)).zone)
        self.end_step();self.top();self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current(ref.card_id)).zone)

    def test_desert_hidden_replacement_is_not_tracked(self):
        redirect=CardProgram('redirect','Redirect',('Artifact',),replacements=(
            ZoneReplacement('redirect',Zone.GRAVEYARD,Zone.HAND,from_zone=Zone.BATTLEFIELD,types=('Land',)),))
        self.game('desert-warfare',extra=(redirect,));self.state.add_card('redirect','redirect','A',Zone.BATTLEFIELD)
        ref=self.deserts(1)[0];self.effect(ref,Sacrifice('source'));self.top();self.end_step();self.top()
        self.assertEqual(Zone.HAND,self.state.get(self.state.current(ref.card_id)).zone)

    def test_desert_moved_graveyard_incarnation_does_not_return(self):
        self.game('desert-warfare');ref=self.deserts(1)[0];self.effect(ref,Sacrifice('source'));self.top()
        self.state.move((ZoneMove(self.state.current(ref.card_id),Zone.EXILE),),'fixture')
        self.state.move((ZoneMove(self.state.current(ref.card_id),Zone.GRAVEYARD),),'fixture')
        self.end_step();self.top();self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current(ref.card_id)).zone)

    def test_desert_source_departure_does_not_cancel_registered_return(self):
        self.game('desert-warfare');ref=self.deserts(1)[0];self.effect(ref,Sacrifice('source'));self.top()
        self.effect(self.source,Move('source',Zone.GRAVEYARD));self.end_step();self.top()
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current(ref.card_id)).zone)

    def test_desert_end_step_registration_waits_for_next_own_end_step(self):
        self.game('desert-warfare');self.end_step();ref=self.deserts(1)[0];self.effect(ref,Sacrifice('source'));self.top()
        self.assertFalse(self.kernel.stack);self.end_step('B');self.assertFalse(self.kernel.stack)
        self.end_step('A');self.top();self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current(ref.card_id)).zone)

    def test_desert_combat_threshold_checked_at_occurrence_and_resolution(self):
        self.game('desert-warfare');refs=self.deserts(4)
        self.discover_step('A','begin_combat');self.assertFalse(self.kernel.stack)
        fifth=self.state.add_card('fifth','p-desert','A',Zone.BATTLEFIELD)
        self.discover_step('A','begin_combat');self.response((fifth,));self.top();self.top()
        self.assertFalse(self.token_refs('Sand'))

    def test_desert_combat_counts_resolution_deserts_and_grants_noncopyable_haste(self):
        copy=CardProgram('copy','Copy',('Creature',),power=0,toughness=0,
            entry_copy=Selector(Zone.BATTLEFIELD,types=('Creature',),subtypes=('Sand',)))
        self.game('desert-warfare',extra=(copy,));self.deserts(5);self.discover_step('A','begin_combat')
        self.state.add_card('sixth','p-desert','A',Zone.BATTLEFIELD);self.top()
        refs=self.token_refs('Sand');self.assertEqual(6,len(refs))
        for ref in refs:
            self.assertEqual(frozenset(('R','G','W')),self.kernel.effective(ref).colors)
            self.assertIn('haste',self.kernel.effective(ref).keywords)
            self.assertNotIn('haste',self.kernel.definition(self.state.get(ref)).keywords)
        ref=self.state.add_card('copy','copy','A',Zone.HAND);self.kernel.enter(ref)
        q=self.kernel.pending_choice;self.kernel.answer(q.request_id,q.actor,
            [next(i for i,o in enumerate(q.options) if o.ref==refs[0])])
        self.assertNotIn('haste',self.kernel.effective(self.state.current('copy')).keywords)
        self.assertEqual(1,self.kernel.effective(self.state.current('copy')).power)

    def test_desert_granted_haste_survives_cleanup_and_phasing(self):
        self.game('desert-warfare');self.deserts(5);self.kernel.begin_turn_for_scenario('A')
        self.advance_to('begin_combat');self.top();ref=self.token_refs('Sand')[0]
        self.effect(ref,PhaseOut('source'));self.advance_to('upkeep','B')
        self.assertTrue(self.state.get(ref).phased)
        self.advance_to('upkeep','A');self.assertFalse(self.state.get(ref).phased)
        self.assertIn('haste',self.kernel.effective(ref).keywords)

    def test_desert_granted_haste_does_not_apply_to_a_new_incarnation(self):
        self.game('desert-warfare');self.deserts(5);self.discover_step('A','begin_combat');self.top()
        refs=self.token_refs('Sand');self.effect(refs[0],Move('source',Zone.EXILE));self.kernel._finish_cleanup_actions()
        self.assertFalse(any(refs[0].to_json() in row['refs'] for row in self.kernel.temporary_effects))

    def test_desert_no_retroactive_recovery_and_no_opponent_combat_trigger(self):
        self.game('desert-warfare',zone=Zone.HAND);ref=self.deserts(1)[0];self.effect(ref,Sacrifice('source'))
        self.kernel.enter(self.source);self.end_step();self.assertFalse(self.kernel.stack)
        self.deserts(5,owner='B');self.discover_step('B','begin_combat');self.assertFalse(self.kernel.stack)

    def test_desert_delayed_step_capture_checkpoint_replays(self):
        self.game('desert-warfare');ref=self.deserts(1)[0];self.effect(ref,Sacrifice('source'));self.top()
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.end_step();self.discover_step('A','end_step',kernel=restored)
        adapter=RulesActorAdapter(self.kernel)
        for _ in self.state.live_players:adapter.submit(self.kernel.priority,{'kind':'pass','revision':self.kernel.revision})
        for _ in restored.state.live_players:restored.pass_priority(restored.priority)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())

    def test_tormentor_normal_cast_flying_and_cost(self):
        self.game('indulgent-tormentor',zone=Zone.HAND);self.cast(self.source,mana='CCCBB');self.top()
        self.assertIn('flying',self.kernel.effective(self.state.current('source')).keywords)
        self.assertEqual((),self.state.mana_pool('A'))

    def test_tormentor_decline_draws_for_controller(self):
        self.game('indulgent-tormentor');self.upkeep_choice();self.choose('decline')
        self.assertEqual(1,self.hand('A'));self.assertEqual(40,self.state.life('B'))

    def test_tormentor_life_payment_is_a_real_payment_and_prevents_draw(self):
        self.game('indulgent-tormentor');self.upkeep_choice();self.choose('life')
        self.assertEqual(37,self.state.life('B'));self.assertEqual(3,self.state.life_lost_this_turn('B'))
        self.assertEqual(0,self.hand('A'))

    def test_tormentor_payer_chooses_own_creature_to_sacrifice(self):
        self.game('indulgent-tormentor');self.upkeep_choice()
        q=self.kernel.pending_choice
        self.assertEqual([self.body],[o.ref for o in q.options if o.ref])
        self.choose(next(o.key for o in q.options if o.ref==self.body))
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('body')).zone);self.assertEqual(0,self.hand('A'))

    def test_tormentor_payment_options_exclude_unpayable_life_and_phased_creatures(self):
        self.game('indulgent-tormentor');self.state.lose_life_batch(('B',),38)
        self.effect(self.body,PhaseOut('source'));self.upkeep_choice()
        self.assertEqual(['decline'],[o.key for o in self.kernel.pending_choice.options])
        self.choose('decline');self.assertEqual(1,self.hand('A'))

    def test_tormentor_can_pay_exact_life_then_lose_after_resolution(self):
        self.game('indulgent-tormentor');self.state.lose_life_batch(('B',),37)
        self.upkeep_choice();self.choose('life')
        self.assertNotIn('B',self.state.live_players);self.assertEqual(0,self.hand('A'))

    def test_tormentor_wrong_actor_and_invalid_answer_leave_state_unchanged(self):
        self.game('indulgent-tormentor');self.upkeep_choice();q=self.kernel.pending_choice;before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.answer(q.request_id,'A',[0])
        with self.assertRaises(RulesViolation):self.kernel.answer(q.request_id,'B',[99])
        self.assertEqual(before,self.kernel.snapshot())

    def test_tormentor_source_departure_does_not_cancel_upkeep_choice(self):
        self.game('indulgent-tormentor');self.kernel.begin_step('A','upkeep');self.targets(('B',))
        self.response((self.source,));self.top();self.top();self.choose('decline')
        self.assertEqual(1,self.hand('A'))

    def test_tormentor_sacrifice_replacement_still_pays(self):
        redirect=CardProgram('redirect','Redirect',('Artifact',),replacements=(
            ZoneReplacement('redirect',Zone.GRAVEYARD,Zone.EXILE,from_zone=Zone.BATTLEFIELD,types=('Creature',)),))
        self.game('indulgent-tormentor',extra=(redirect,));self.state.add_card('redirect','redirect','A',Zone.BATTLEFIELD)
        self.upkeep_choice();self.choose(next(o.key for o in self.kernel.pending_choice.options if o.ref==self.body))
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('body')).zone);self.assertEqual(0,self.hand('A'))

    def test_tormentor_choice_checkpoint_and_actor_replay(self):
        self.game('indulgent-tormentor');self.upkeep_choice();adapter=RulesActorAdapter(self.kernel);q=self.kernel.pending_choice
        adapter.submit('B',{'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[next(i for i,o in enumerate(q.options) if o.key=='life')]})
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())

    def test_fault_mana_cost_and_source_sacrifice_precede_response(self):
        self.game('volatile-fault');self.fault()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('source')).zone)
        self.assertEqual((),self.state.mana_pool('A'));self.assertEqual(self.land,self.state.current('land'))
        self.response(definition='p-stifle');self.top()
        self.assertEqual(self.land,self.state.current('land'));self.assertFalse(self.token_refs('Treasure'))

    def test_fault_nonbasic_opponent_target_restrictions_are_atomic(self):
        self.game('volatile-fault');basic=self.state.add_card('basic-field','p-basic','B',Zone.BATTLEFIELD)
        own=self.state.add_card('own-land','p-land','A',Zone.BATTLEFIELD)
        before=self.kernel.snapshot()
        for target in (basic,own,self.body):
            with self.subTest(target=target),self.assertRaises(RulesViolation):
                self.kernel.quote_activation('bad','A',self.source,'fault',(target,))
        self.assertEqual(before,self.kernel.snapshot())

    def test_fault_opponent_may_decline_search_but_controller_gets_treasure(self):
        self.game('volatile-fault');self.fault();self.top()
        self.assertEqual('B',self.kernel.pending_choice.actor);self.assertEqual('optional_search',self.kernel.pending_choice.kind)
        self.choose('no');self.assertEqual(1,len(self.token_refs('Treasure')))
        self.assertFalse(any(e['kind']=='library_shuffled' for e in self.kernel.semantic_events))

    def test_fault_search_is_private_to_searcher_and_returns_under_their_control(self):
        self.game('volatile-fault');self.fault();self.top()
        with self.assertRaises(RulesViolation):self.kernel.inspect_library_search('B')
        self.choose('yes');q=self.kernel.pending_choice
        self.assertEqual('library_search',q.kind);self.assertEqual('B',q.actor)
        self.assertTrue(self.kernel.inspect_library_search('B'))
        with self.assertRaises(RulesViolation):self.kernel.inspect_library_search('A')
        a=RulesActorAdapter(self.kernel).packet('A');b=RulesActorAdapter(self.kernel).packet('B')
        self.assertNotIn('library_search',a);self.assertIn('library_search',b)
        self.kernel.answer(q.request_id,'B',[next(i for i,o in enumerate(q.options) if o.ref==self.basic)])
        current=self.state.get(self.state.current('basic'))
        self.assertEqual(Zone.BATTLEFIELD,current.zone);self.assertEqual('B',current.controller)
        self.assertFalse(current.tapped);self.assertEqual(1,len(self.token_refs('Treasure')))

    def test_fault_failed_find_still_shuffles_and_makes_treasure(self):
        self.game('volatile-fault');self.fault();self.top();self.choose('yes');q=self.kernel.pending_choice
        self.kernel.answer(q.request_id,'B',[])
        self.assertEqual(1,len(self.token_refs('Treasure')))
        self.assertTrue(any(e['kind']=='library_shuffled' and e['player']=='B' for e in self.kernel.semantic_events))

    def test_fault_indestructible_target_still_offers_search(self):
        immortal=CardProgram('immortal','Immortal',('Land',),keywords=('indestructible',))
        self.game('volatile-fault',extra=(immortal,));self.land=self.state.add_card('immortal','immortal','B',Zone.BATTLEFIELD)
        self.fault();self.top();self.assertEqual(self.land,self.state.current('immortal'))
        self.choose('no');self.assertEqual(1,len(self.token_refs('Treasure')))

    def test_fault_illegal_target_prevents_search_and_treasure(self):
        self.game('volatile-fault');self.fault();self.response((self.land,));self.top();self.top()
        self.assertIsNone(self.kernel.pending_choice);self.assertFalse(self.token_refs('Treasure'))

    def test_fault_uses_resolution_controller_of_target_and_snapshot_during_search(self):
        self.game('volatile-fault');self.fault()
        self.state.change_control(self.land,'C');self.top()
        self.assertEqual('C',self.kernel.pending_choice.actor)
        self.choose('no');self.assertEqual(1,len(self.token_refs('Treasure')))

    def test_fault_treasure_has_real_tap_sacrifice_mana_ability(self):
        self.game('volatile-fault');self.fault();self.top();self.choose('no')
        treasure=self.token_refs('Treasure')[0];self.window('A')
        self.kernel.commit_action(self.kernel.quote_activation(self.ident(),'A',treasure,'mana'),Payment())
        self.choose('4');self.assertEqual((('G',1),),self.state.mana_pool('A'))
        self.assertFalse(self.token_refs('Treasure'))

    def test_fault_search_checkpoint_actor_replay_and_hidden_reference_retirement(self):
        self.game('volatile-fault');self.fault();self.top();self.choose('yes')
        adapter=RulesActorAdapter(self.kernel);q=self.kernel.pending_choice
        adapter.submit('B',{'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[]})
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())
        with self.assertRaises(RulesViolation):adapter._visible_ref(self.basic.to_json(),'A')

    def test_phasing_removes_attacker_immediately(self):
        self.game();self.kernel.begin_turn_for_scenario('A');self.advance_to('declare_attackers')
        self.kernel.declare_attackers('A',{self.other:'B'},revision=self.kernel.revision)
        self.effect(self.other,PhaseOut('source'));self.assertFalse(self.kernel.combat['attackers'])

    def test_phasing_token_retains_physical_identity(self):
        token=CardProgram('phase-token','Token',('Creature',),power=1,toughness=1)
        maker=CardProgram('maker','Maker',('Sorcery',),spell_effects=(CreateTokens(token),))
        self.game(extra=(maker,));self.effect(self.other,CreateTokens(token))
        ref=next(o.ref for o in self.state.objects(Zone.BATTLEFIELD) if o.token)
        self.effect(ref,PhaseOut('source'));self.kernel.begin_turn_for_scenario('A')
        self.assertEqual(ref,self.state.current(ref.card_id));self.assertTrue(self.state.get(ref).token)

    def test_phasing_preserves_source_duration_exile_until_actual_departure(self):
        holder=CardProgram('holder','Holder',('Artifact',),activated=(
            ActivatedProgram('hold',CostSpec(),(ExileUntilSourceLeaves('target'),),
                targets=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',)))),))
        self.game(extra=(holder,));self.source=self.state.add_card('holder','holder','A',Zone.BATTLEFIELD)
        self.activate('hold',(self.body,));self.top()
        self.effect(self.source,PhaseOut('source'));self.assertEqual(Zone.EXILE,self.state.get(self.state.current('body')).zone)
        self.kernel.begin_turn_for_scenario('A');self.effect(self.source,Move('source',Zone.GRAVEYARD))
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('body')).zone)

    def test_untracked_manual_phasing_remains_fenced(self):
        self.game();self.state.phase(self.body,True);before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.begin_turn_for_scenario('B')
        self.assertEqual(before,self.kernel.snapshot())

    def test_new_nodes_roundtrip_and_reject_uncaptured_players_or_wrong_targets(self):
        parent=CardProgram('parent-token','Parent',('Creature',),power=1,toughness=1)
        child=CardProgram('child-token','Child',('Creature',),power=1,toughness=1)
        maker=CardProgram('nested-maker','Nested maker',('Sorcery',),
            spell_effects=(WithCreatedTokens(parent,effects=(CreateTokens(child),)),))
        self.game(extra=(maker,));self.effect(self.other,*maker.spell_effects)
        self.assertEqual({'parent-token','child-token'},{o.definition for o in self.state.objects(Zone.BATTLEFIELD) if o.token})
        self.effect(self.other,SearchLibrary(SupertypeSelector(Zone.LIBRARY,relation='owned',
            excluded_supertypes=('Basic',)),Zone.HAND))
        q=self.kernel.pending_choice;self.assertEqual('library_search',q.kind);self.assertTrue(q.options)
        self.kernel.answer(q.request_id,q.actor,[])
        self.assertEqual(0,self.hand('A'))
        bad=(
            CardProgram('bad','Bad',('Instant',),spell_effects=(PhaseOut('missing'),)),
            CardProgram('bad','Bad',('Instant',),spell_effects=(PayLifeOrSacrifice(3,Selector(Zone.BATTLEFIELD,relation='controlled')),)),
            CardProgram('bad','Bad',('Instant',),spell_effects=(SearchByPlayer(Selector(Zone.LIBRARY,relation='owned'),Zone.BATTLEFIELD),)),
            CardProgram('bad','Bad',('Instant',),spell_targets=TargetSpec(players='opponents'),spell_effects=(PhaseOut('target'),)),
            CardProgram('bad','Bad',('Instant',),spell_targets=TargetSpec(players='opponents'),
                spell_effects=(PayLifeOrSacrifice(True,Selector(Zone.BATTLEFIELD,relation='controlled')),)),
        )
        for program in bad:
            with self.subTest(program=program),self.assertRaises(RulesViolation):validate(program)

    def test_qualified_event_rejects_invalid_cause_or_hidden_zone_alias(self):
        for event in (ZoneEventPattern('step_began',step='upkeep',subtypes=('Desert',)),
                      ZoneEventPattern('zone_changed',from_zone=Zone.HAND,cause='sacrifice'),
                      ZoneEventPattern('zone_changed',cause='whatever'),
                      ZoneEventPattern('zone_changed',destination_owned=1)):
            with self.subTest(event=event),self.assertRaises(RulesViolation):
                validate(CardProgram('bad','Bad',('Enchantment',),abilities=(AbilityProgram('bad',event,()),)))

    def test_new_checkpoint_layout_preserves_state_schema_and_rejects_old_kernel(self):
        self.game();checkpoint=self.kernel.snapshot()
        self.assertEqual(119,checkpoint['schema']);self.assertEqual(13,checkpoint['state']['schema'])
        self.assertEqual(checkpoint,RulesKernel.restore(checkpoint,self.programs).snapshot())
        checkpoint['schema']=118
        with self.assertRaises(RulesViolation):RulesKernel.restore(checkpoint,self.programs)


if __name__=='__main__':unittest.main()
