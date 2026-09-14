"""Cast declarations, exact life notes, cleanup and paid-cost last-known facts."""
import json
import unittest
from dataclasses import replace
from pathlib import Path
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,RulesViolation,Zone,ZoneMove
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment,PreparedAction
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed,digest,source_facts
from edh_gauntlet.catalog import load_catalog

CARDS=('necromancy','nullpriest-of-oblivion','sigarda-s-splendor','wonderscape-sage')


class RecordedFactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        reviewed=load_reviewed(cls.root)
        drafts=json.loads((cls.root/'data/rules/draft_cards.json').read_text(encoding='utf-8'))['drafts']
        cls.rows={row['card_id']:row for row in drafts if row['card_id'] in CARDS}
        cls.cards={key:validate(decode(row['program'])) for key,row in cls.rows.items()}
        cls.base=tuple(row['program'] for row in reviewed.values())+tuple(cls.cards.values())

    def game(self,key='necromancy',*,zone=Zone.HAND,extra=()):
        body=CardProgram('n-body','Body',('Creature',),power=2,toughness=3)
        land=CardProgram('n-land','Land',('Land',))
        basic=CardProgram('n-basic','Basic',('Land',),supertypes=('Basic',),subtypes=('Forest',))
        cave=CardProgram('n-cave','Cave',('Land',),subtypes=('Cave',))
        remove=CardProgram('n-remove','Remove',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD)),spell_effects=(Move('target',Zone.GRAVEYARD),))
        counter=replace(remove,definition_id='n-counter',name='Counter',spell_targets=TargetSpec(Selector(Zone.STACK)),spell_effects=(Counter(),))
        stifle=replace(remove,definition_id='n-stifle',name='Stifle',spell_targets=None,spell_effects=(CounterAbilities(),))
        noop=replace(remove,definition_id='n-noop',name='Noop',spell_targets=None,spell_effects=())
        white=replace(noop,definition_id='n-white',name='White',colors=('W',))
        exile=replace(remove,definition_id='n-exile',name='Exile',spell_effects=(Move('target',Zone.EXILE),))
        control=replace(remove,definition_id='n-control',name='Control',spell_effects=(GainControl('target'),))
        returner=replace(remove,definition_id='n-return',name='Return',spell_targets=TargetSpec(Selector(Zone.EXILE)),
            spell_effects=(Move('target',Zone.BATTLEFIELD),))
        life=tuple(replace(noop,definition_id='n-'+kind+'-'+str(n),name=kind+str(n),
            spell_effects=((GainLife(n) if kind=='gain' else LoseLife('controller',n)),))
            for kind in ('gain','lose') for n in (1,3,4,5,6,7))
        self.programs=self.base+(body,land,basic,cave,remove,counter,stifle,noop,white,exile,control,returner)+life+extra
        self.state=RulesState(('A','B','C','D'));self.kernel=RulesKernel(self.state,self.programs)
        self.kernel.open_window_for_scenario('A');self.number=0
        self.source=self.state.add_card('source',self.cards[key].definition_id,'A',zone)
        self.body=self.state.add_card('body','n-body','B',Zone.GRAVEYARD)
        self.own=self.state.add_card('own','n-body','A',Zone.GRAVEYARD)
        self.land=self.state.add_card('land','n-land','A',Zone.BATTLEFIELD)
        for player in self.state.players:
            for n in range(12):self.state.add_card('library-'+player+'-'+str(n),'n-body',player,Zone.LIBRARY)

    def ident(self):
        self.number+=1
        return 'n-action-'+str(self.number)

    def window(self,actor='A'):
        if not self.kernel.stack and self.kernel.turn_schedule is None:self.kernel.open_window_for_scenario(self.kernel.active,phase=self.kernel.phase or 'precombat_main',priority_actor=actor)
        while self.kernel.priority!=actor:self.kernel.pass_priority(self.kernel.priority)

    def top(self):
        self.assertTrue(self.kernel.stack)
        for _ in self.state.live_players:result=self.kernel.pass_priority(self.kernel.priority)
        return result

    def targets(self,refs):
        q=self.kernel.pending_choice;self.assertEqual('trigger_targets',q.kind)
        return self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.ref==ref) for ref in refs])

    def effect(self,ref,*effects,actor='A'):
        if not self.kernel.stack:return self.kernel.execute_for_scenario(ref,actor,effects)
        # Responses use real announcements and priority; the scenario gate stays closed.
        self.assertEqual(1,len(effects));effect=effects[0];targets=()
        if isinstance(effect,(GainLife,LoseLife)):
            definition='n-'+('gain' if isinstance(effect,GainLife) else 'lose')+'-'+str(effect.amount)
        elif isinstance(effect,GainControl):
            definition='n-control';targets=(ref,)
        elif isinstance(effect,Move):
            definition='n-exile' if effect.destination==Zone.EXILE else 'n-remove';targets=(ref,)
        else:self.fail('Add an explicit response fixture for this effect')
        self.response(targets,definition,actor);return self.top()
    def hand(self,actor='A'):return len(self.state.zone(actor,Zone.HAND))
    def current(self,card='source'):return self.state.current(card)
    def zone(self,card='source'):return self.state.get(self.current(card)).zone

    def cast(self,ref=None,*,actor='A',targets=(),mana=(),kicker=False,alternative_id=None):
        ref=self.source if ref is None else ref;self.window(actor);symbols=tuple(mana)
        if symbols:self.state.add_mana(actor,symbols)
        quote=self.kernel.quote_cast(self.ident(),actor,ref,targets,kicker=kicker,alternative_id=alternative_id)
        return self.kernel.commit_action(quote,Payment(tuple((s,symbols.count(s)) for s in sorted(set(symbols)))))

    def response(self,targets=(),definition='n-remove',actor='B'):
        ref=self.state.add_card(self.ident(),definition,actor,Zone.HAND)
        return self.cast(ref,actor=actor,targets=targets)

    def advance_to(self,phase,actor=None):
        for _ in range(200):
            if self.kernel.phase==phase and (actor is None or self.kernel.active==actor):return
            self.assertIsNone(self.kernel.pending_choice);self.assertFalse(self.kernel.stack)
            if self.kernel.phase=='declare_attackers' and self.kernel.priority is None:
                self.kernel.declare_attackers(self.kernel.active,{},revision=self.kernel.revision)
            else:self.kernel.pass_priority(self.kernel.priority)
        self.fail('Phase not reached')

    def step_fixture(self,step,actor='A'):
        self.kernel._idle();self.assertIsNone(self.kernel.turn_schedule);self.assertFalse(self.kernel.stack)
        self.kernel.active=actor;self.kernel._begin_phase(step)
        return self.kernel.advance()

    def reanimate(self,*,other_turn=False):
        self.game()
        if other_turn:self.kernel.open_window_for_scenario('B',phase='end_step',priority_actor='A')
        self.cast(mana='CCB');self.top();self.targets((self.body,));self.top()
        self.source=self.current();self.body=self.current('body')

    def splendor(self):
        self.game('sigarda-s-splendor');self.kernel.enter(self.source);self.source=self.current()

    def note(self,ref=None):
        return self.kernel.object_notes[self.kernel._attachment_key(ref or self.source)]['values']['life']

    def sage(self):
        self.game('wonderscape-sage',zone=Zone.BATTLEFIELD)
        self.state.start_turn('A');self.kernel.open_window_for_scenario('A')

    def use_sage(self,land=None):
        self.window()
        return self.kernel.commit_action(self.kernel.quote_activation(self.ident(),'A',self.source,'return-draw'),
            Payment(zone_costs=(('land-return',(self.land if land is None else land,)),)))

    def discard_one(self):
        q=self.kernel.pending_choice;self.assertIsNotNone(q)
        return self.kernel.answer(q.request_id,q.actor,[0])

    def test_complete_printed_faces_source_hashes_and_codec(self):
        catalog={c.card_id:c for c in load_catalog(self.root/'data/catalog/cards.json')}
        self.assertEqual(set(CARDS),set(self.cards))
        for key,program in self.cards.items():
            with self.subTest(card=key):
                self.assertEqual(digest(source_facts(catalog[key])),digest(self.rows[key]['source_facts']))
                self.assertEqual(self.rows[key]['program'],encode(program))
                face=catalog[key].faces[0]
                for field in ('types','subtypes','supertypes','colors'):
                    self.assertEqual(set(getattr(face,field)),set(getattr(program,field)))
                for field in ('mana_value','power','toughness'):self.assertEqual(getattr(face,field),getattr(program,field))
                self.assertEqual(catalog[key].name,program.name)

    def test_necromancy_main_phase_cast_is_unattached_enchantment_until_trigger(self):
        self.game();self.cast(mana='CCB');self.assertEqual('sorcery',self.kernel.stack[-1]['cast_timing'])
        self.assertEqual(3,self.kernel.effective(self.current()).mana_value);self.top()
        self.assertNotIn('Aura',self.kernel.effective(self.current()).subtypes)
        self.targets((self.body,));self.top()
        self.assertIn('Aura',self.kernel.effective(self.current()).subtypes)
        self.assertEqual(self.current('body'),self.state.get(self.current()).attached_to)
        self.assertEqual('A',self.state.get(self.current('body')).controller)
        self.assertFalse(any(d.get('step')=='cleanup' for d in self.kernel.delayed_triggers))

    def test_necromancy_other_turn_cast_binds_cleanup_to_entered_incarnation(self):
        self.reanimate(other_turn=True)
        delayed=next(d for d in self.kernel.delayed_triggers if d.get('step')=='cleanup')
        self.assertEqual([self.source.to_json()],delayed['bindings']['moved'])
        self.step_fixture('cleanup','B');self.top();self.top()
        self.assertEqual(Zone.GRAVEYARD,self.zone());self.assertEqual(Zone.GRAVEYARD,self.zone('body'))

    def test_necromancy_own_main_with_another_spell_is_nonsorcery_timing(self):
        self.game();self.response(definition='n-noop');self.cast(mana='CCB')
        self.assertEqual('other',self.kernel.stack[-1]['cast_timing'])
        self.top();self.targets((self.body,));self.top();self.top()
        self.assertTrue(any(d.get('step')=='cleanup' for d in self.kernel.delayed_triggers))

    def test_necromancy_cast_fact_does_not_change_when_stack_empties(self):
        self.game();self.kernel.open_window_for_scenario('B',phase='end_step',priority_actor='A')
        self.cast(mana='CCB');self.kernel.active='A';self.kernel.phase='precombat_main'
        self.top();self.targets((self.body,));self.top()
        self.assertTrue(any(d.get('step')=='cleanup' for d in self.kernel.delayed_triggers))

    def test_necromancy_not_cast_has_no_cleanup_sacrifice(self):
        self.game();self.kernel.enter(self.source);self.targets((self.body,));self.top()
        self.assertFalse(any(d.get('step')=='cleanup' for d in self.kernel.delayed_triggers))

    def test_necromancy_countered_spell_never_schedules_cleanup(self):
        self.game();self.kernel.open_window_for_scenario('B',phase='end_step',priority_actor='A')
        self.cast(mana='CCB');self.response((self.current(),),definition='n-counter');self.top()
        self.assertFalse(self.kernel.delayed_triggers);self.assertEqual(Zone.GRAVEYARD,self.zone())

    def test_necromancy_replaced_entry_does_not_register_a_permanent_cleanup(self):
        redirect=CardProgram('redirect','Redirect',('Artifact',),replacements=(
            ZoneReplacement('redirect',Zone.BATTLEFIELD,Zone.EXILE,from_zone=Zone.STACK,types=('Enchantment',)),))
        self.game(extra=(redirect,));self.state.add_card('redirect','redirect','A',Zone.BATTLEFIELD)
        self.kernel.open_window_for_scenario('B',phase='end_step',priority_actor='A');self.cast(mana='CCB');self.top()
        self.assertEqual(Zone.EXILE,self.zone());self.assertFalse(self.kernel.delayed_triggers)

    def test_necromancy_entry_trigger_countered_leaves_plain_enchantment(self):
        self.game();self.cast(mana='CCB');self.top();self.targets((self.body,))
        self.response(definition='n-stifle');self.top()
        self.assertEqual(Zone.GRAVEYARD,self.zone('body'));self.assertNotIn('Aura',self.kernel.effective(self.current()).subtypes)

    def test_necromancy_source_removed_before_entry_trigger_does_not_reanimate(self):
        self.game();self.cast(mana='CCB');self.top();self.targets((self.body,))
        self.response((self.current(),));self.top();self.top()
        self.assertEqual(Zone.GRAVEYARD,self.zone('body'))

    def test_necromancy_illegal_target_leaves_plain_enchantment(self):
        self.game();self.cast(mana='CCB');self.top();self.targets((self.body,))
        self.state.move((ZoneMove(self.body,Zone.EXILE),),'fixture');self.top()
        self.assertEqual(Zone.BATTLEFIELD,self.zone());self.assertNotIn('Aura',self.kernel.effective(self.current()).subtypes)

    def test_necromancy_prohibited_return_becomes_unattached_aura_and_dies(self):
        cage=CardProgram('cage','Cage',('Artifact',),entry_restrictions=(Selector(Zone.GRAVEYARD,types=('Creature',)),))
        self.game(extra=(cage,));self.state.add_card('cage','cage','A',Zone.BATTLEFIELD)
        self.cast(mana='CCB');self.top();self.targets((self.body,));self.top()
        self.assertEqual(Zone.GRAVEYARD,self.zone());self.assertEqual(Zone.GRAVEYARD,self.zone('body'))

    def test_necromancy_cleanup_sacrifices_through_current_controller(self):
        self.reanimate(other_turn=True);self.effect(self.source,GainControl('source'),actor='C')
        self.step_fixture('cleanup','B');self.assertEqual('A',self.kernel.stack[-1]['controller']);self.top();self.top()
        self.assertEqual(Zone.GRAVEYARD,self.zone());self.assertEqual(Zone.GRAVEYARD,self.zone('body'))

    def test_necromancy_actual_creature_departure_removes_aura(self):
        self.reanimate();self.effect(self.body,Move('source',Zone.EXILE))
        self.assertEqual(Zone.GRAVEYARD,self.zone());self.top();self.assertEqual(Zone.EXILE,self.zone('body'))

    def test_necromancy_phasing_skips_one_shot_cleanup_and_preserves_attachment(self):
        self.reanimate(other_turn=True);self.effect(self.body,PhaseOut('source'))
        self.step_fixture('cleanup','B');self.top();self.assertTrue(self.state.get(self.source).phased)
        self.assertFalse(any(d.get('step')=='cleanup' for d in self.kernel.delayed_triggers))
        self.kernel.begin_turn_for_scenario('A');self.assertFalse(self.state.get(self.source).phased)
        self.assertEqual(self.body,self.state.get(self.source).attached_to)

    def test_necromancy_actual_cleanup_discards_before_delayed_trigger_and_repeats(self):
        self.game();self.kernel.begin_turn_for_scenario('A');self.advance_to('end_step')
        self.cast(mana='CCB');self.top();self.targets((self.body,));self.top()
        for n in range(8):self.state.add_card('extra-'+str(n),'n-body','A',Zone.HAND)
        excess=self.hand()-7;self.advance_to('cleanup')
        self.assertIsNotNone(self.kernel.pending_choice);self.assertFalse(self.kernel.stack)
        q=self.kernel.pending_choice;self.kernel.answer(q.request_id,q.actor,list(range(excess)))
        self.assertEqual(7,self.hand());self.assertTrue(self.kernel.stack)
        self.top();self.top();self.advance_to('upkeep','B')
        self.assertEqual(Zone.GRAVEYARD,self.zone());self.assertEqual(Zone.GRAVEYARD,self.zone('body'))

    def test_necromancy_checkpoint_and_actor_replay_keep_cleanup_and_attachment(self):
        self.reanimate(other_turn=True);self.step_fixture('cleanup','B')
        adapter=RulesActorAdapter(self.kernel)
        for _ in self.state.live_players:adapter.submit(self.kernel.priority,{'kind':'pass','revision':self.kernel.revision})
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())
        self.assertEqual(self.kernel.snapshot(),RulesKernel.restore(self.kernel.snapshot(),self.programs).snapshot())

    def test_necromancy_aura_conversion_is_not_copiable(self):
        copy=CardProgram('copy','Copy',('Enchantment',),entry_copy=Selector(Zone.BATTLEFIELD,types=('Enchantment',)))
        self.game(extra=(copy,));self.cast(mana='CCB');self.top();self.targets((self.body,));self.top()
        ref=self.state.add_card('copy','copy','A',Zone.HAND);self.kernel.enter(ref)
        q=self.kernel.pending_choice;self.kernel.answer(q.request_id,q.actor,
            [next(i for i,o in enumerate(q.options) if o.ref==self.current())])
        self.assertNotIn('Aura',self.kernel.effective(self.current('copy')).subtypes)
        self.targets((self.own,));self.top();self.assertIn('Aura',self.kernel.effective(self.current('copy')).subtypes)

    def test_nullpriest_unkicked_retains_printed_cost_keywords_and_no_target(self):
        self.game('nullpriest-of-oblivion');self.cast(mana='CB');self.top()
        self.assertIsNone(self.kernel.pending_choice);self.assertFalse(self.kernel.stack)
        self.assertEqual(frozenset(('menace','lifelink')),self.kernel.effective(self.current()).keywords)
        self.assertEqual(2,self.kernel.effective(self.current()).mana_value)

    def test_nullpriest_kicker_is_additional_and_returns_own_target(self):
        self.game('nullpriest-of-oblivion');self.window()
        quote=self.kernel.quote_cast('inspect','A',self.source,kicker=True)
        self.assertEqual(ManaCost(4,('B','B')),quote.cost.mana)
        self.cast(mana='CCCCBB',kicker=True);self.assertTrue(RulesActorAdapter(self.kernel).packet('B')['stack'][0]['kicker'])
        self.top();self.assertNotIn(self.body,{o.ref for o in self.kernel.pending_choice.options})
        self.targets((self.own,));self.top()
        self.assertEqual(Zone.BATTLEFIELD,self.zone('own'))
        self.assertIn('kicked',self.state.get(self.current()).entry_flags)

    def test_nullpriest_kicker_reductions_apply_after_additional_cost(self):
        reducer=CardProgram('reducer','Reducer',('Artifact',),cost_modifiers=(
            CostModifier('reduce',Selector(Zone.STACK,types=('Creature',),relation='controlled'),-3),))
        self.game('nullpriest-of-oblivion',extra=(reducer,));self.state.add_card('reducer','reducer','A',Zone.BATTLEFIELD)
        self.window();quote=self.kernel.quote_cast('inspect','A',self.source,kicker=True)
        self.assertEqual(ManaCost(1,('B','B')),quote.cost.mana)
        self.cast(mana='CBB',kicker=True);self.top();self.targets((self.own,));self.top()
        self.assertEqual(Zone.BATTLEFIELD,self.zone('own'))

    def test_nullpriest_kicker_combines_with_alternative_instead_of_replacing_it(self):
        original=self.cards['nullpriest-of-oblivion']
        free=replace(original,definition_id='free-kicker',cast=replace(original.cast,
            alternatives=(AlternativeCost('free',CostSpec()),)))
        self.game('nullpriest-of-oblivion',extra=(free,));ref=self.state.add_card('free','free-kicker','A',Zone.HAND)
        self.cast(ref,mana='CCCB',kicker=True,alternative_id='free');self.top();self.targets((self.own,));self.top()
        self.assertIn('kicked',self.state.get(self.current('free')).entry_flags)

    def test_nullpriest_kicker_wrong_payment_is_atomic(self):
        self.game('nullpriest-of-oblivion');self.window();self.state.add_mana('A',('C','B'))
        quote=self.kernel.quote_cast('bad','A',self.source,kicker=True);before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,Payment((('B',1),('C',1))))
        self.assertEqual(before,self.kernel.snapshot())

    def test_nullpriest_kicker_quote_tampering_and_reuse_are_rejected(self):
        self.game('nullpriest-of-oblivion');self.window();quote=self.kernel.quote_cast('quote','A',self.source)
        with self.assertRaises(RulesViolation):self.kernel.commit_action(replace(quote,kicker=True),Payment())
        self.assertEqual(PreparedAction.from_json(quote.to_json()),quote)
        self.cast(mana='CB')
        with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,Payment())

    def test_nullpriest_kicker_rejects_nondeclaration_values_and_other_spells(self):
        self.game('nullpriest-of-oblivion');self.window()
        for value in (1,'yes',None):
            with self.subTest(value=value),self.assertRaises(RulesViolation):
                self.kernel.quote_cast('bad','A',self.source,kicker=value)
        ref=self.state.add_card('plain','n-noop','A',Zone.HAND)
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',ref,kicker=True)

    def test_nullpriest_kicked_entry_target_leaves_before_resolution(self):
        self.game('nullpriest-of-oblivion');self.cast(mana='CCCCBB',kicker=True);self.top();self.targets((self.own,))
        self.state.move((ZoneMove(self.own,Zone.EXILE),),'fixture');self.top()
        self.assertEqual(Zone.EXILE,self.zone('own'))

    def test_nullpriest_source_departure_does_not_cancel_kicked_trigger(self):
        self.game('nullpriest-of-oblivion');self.cast(mana='CCCCBB',kicker=True);self.top();self.targets((self.own,))
        self.response((self.current(),));self.top();self.top();self.assertEqual(Zone.BATTLEFIELD,self.zone('own'))

    def test_nullpriest_blink_does_not_inherit_kicker(self):
        self.game('nullpriest-of-oblivion');self.cast(mana='CCCCBB',kicker=True);self.top();self.targets((self.own,));self.top()
        self.effect(self.current(),Move('source',Zone.EXILE));ref=self.current();self.kernel.enter(ref)
        self.assertFalse(self.state.get(self.current()).entry_flags);self.assertFalse(self.kernel.stack)

    def test_nullpriest_countered_cast_retains_spent_kicker_without_entry(self):
        self.game('nullpriest-of-oblivion');self.cast(mana='CCCCBB',kicker=True)
        self.response((self.current(),),definition='n-counter');self.top()
        self.assertEqual((),self.state.mana_pool('A'));self.assertEqual(Zone.GRAVEYARD,self.zone('own'))
        self.assertFalse(self.state.get(self.current()).entry_flags)

    def test_nullpriest_adapter_cast_and_checkpoint_replay_preserve_kicker(self):
        self.game('nullpriest-of-oblivion');self.window();self.state.add_mana('A',tuple('CCCCBB'))
        adapter=RulesActorAdapter(self.kernel)
        adapter.submit('A',{'kind':'cast','action_id':'adapter-cast','revision':self.kernel.revision,
            'source':self.source.to_json(),'targets':[],'x_value':0,'kicker':True,
            'payment':{'mana':{'C':4,'B':2},'taps':[]}})
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())
        self.assertEqual(self.kernel.snapshot(),RulesKernel.restore(self.kernel.snapshot(),self.programs).snapshot())

    def test_sigarda_normal_cast_notes_entry_without_triggering_its_own_spell(self):
        self.game('sigarda-s-splendor');self.cast(mana='CCWW');self.top();self.source=self.current()
        self.assertEqual(40,self.state.life('A'));self.assertEqual(40,self.note());self.assertFalse(self.kernel.stack)

    def test_sigarda_entry_note_is_public_replacement_not_a_trigger(self):
        self.splendor();self.assertEqual(40,self.note());self.assertFalse(self.kernel.stack)
        packet=RulesActorAdapter(self.kernel).packet('B')
        self.assertEqual([{'ref':self.source.to_json(),'values':{'life':40}}],packet['object_notes'])

    def test_sigarda_equal_life_upkeep_draws_and_updates(self):
        self.splendor();before=self.hand();self.kernel.begin_step('A','upkeep');self.top()
        self.assertEqual(before+1,self.hand());self.assertEqual(40,self.note())

    def test_sigarda_lower_life_skips_draw_but_sets_next_baseline(self):
        self.splendor();self.effect(self.source,LoseLife('controller',5));before=self.hand()
        self.kernel.begin_step('A','upkeep');self.top();self.assertEqual(before,self.hand());self.assertEqual(35,self.note())
        self.kernel.begin_step('A','upkeep');self.top();self.assertEqual(before+1,self.hand())

    def test_sigarda_comparison_uses_resolution_life(self):
        self.splendor();self.kernel.begin_step('A','upkeep');self.effect(self.source,LoseLife('controller',1))
        self.top();self.assertEqual(0,self.hand());self.assertEqual(39,self.note())

    def test_sigarda_notes_before_separate_draw_trigger_resolves(self):
        observer=CardProgram('draw-loss','Draw loss',('Enchantment',),abilities=(
            AbilityProgram('draw-loss',EventPattern('card_drawn',controller_only=True),(LoseLife('controller',1),)),))
        self.game('sigarda-s-splendor',extra=(observer,));self.state.add_card('observer','draw-loss','A',Zone.BATTLEFIELD)
        self.kernel.enter(self.source);self.source=self.current();self.kernel.begin_step('A','upkeep');self.top()
        self.assertEqual(40,self.note());self.assertEqual(40,self.state.life('A'))
        self.top();self.assertEqual(39,self.state.life('A'));self.assertEqual(40,self.note())

    def test_sigarda_trigger_survives_source_departure(self):
        self.splendor();old=self.source;self.kernel.begin_step('A','upkeep')
        self.response((self.source,));self.top()
        self.assertEqual({'life':40},RulesActorAdapter(self.kernel).packet('B')['stack'][0]['source_notes'])
        self.top();self.assertEqual(1,self.hand());self.assertEqual(40,self.note(old))

    def test_sigarda_new_incarnation_has_independent_note_from_old_trigger(self):
        self.splendor();old=self.source;self.kernel.begin_step('A','upkeep')
        self.effect(self.source,Move('source',Zone.EXILE));self.effect(self.own,GainLife(7))
        self.response((self.current(),),definition='n-return',actor='A');self.top()
        new=self.current();self.assertEqual(47,self.note(new))
        self.effect(self.own,LoseLife('controller',3));self.top()
        self.assertEqual(44,self.note(old));self.assertEqual(47,self.note(new))

    def test_sigarda_control_change_keeps_note_and_uses_current_trigger_controller(self):
        self.splendor();self.effect(self.source,GainControl('source'),actor='B')
        self.effect(self.own,LoseLife('controller',5),actor='B');before=self.hand('B')
        self.kernel.begin_step('B','upkeep');self.top()
        self.assertEqual(before,self.hand('B'));self.assertEqual(35,self.note())

    def test_sigarda_existing_trigger_uses_original_controller_after_control_change(self):
        self.splendor();self.kernel.begin_step('A','upkeep')
        self.effect(self.source,GainControl('source'),actor='B');self.effect(self.own,GainLife(3))
        self.top();self.assertEqual(43,self.note());self.assertEqual(1,self.hand('A'));self.assertEqual(0,self.hand('B'))

    def test_sigarda_only_actual_own_white_casts_trigger(self):
        self.splendor();self.response(definition='n-white',actor='B');self.top();self.assertEqual(40,self.state.life('A'))
        self.response(definition='n-noop',actor='A');self.top();self.assertEqual(40,self.state.life('A'))
        self.response(definition='n-white',actor='A');self.assertEqual(2,len(self.kernel.stack))
        self.top();self.assertEqual(41,self.state.life('A'));self.top()

    def test_sigarda_multicolor_white_spell_counts_once_and_counter_does_not_undo_gain(self):
        multi=CardProgram('multi','Multi',('Instant',),colors=('W','U'),cast=CastSpec(CostSpec(),timing='instant'))
        self.game('sigarda-s-splendor',extra=(multi,));self.kernel.enter(self.source);self.source=self.current()
        ref=self.state.add_card('multi','multi','A',Zone.HAND);self.cast(ref);self.top()
        self.assertEqual(41,self.state.life('A'));self.response((self.current('multi'),),definition='n-counter');self.top()
        self.assertEqual(41,self.state.life('A'));self.assertEqual(Zone.GRAVEYARD,self.zone('multi'))

    def test_sigarda_phasing_preserves_notes_and_suppresses_upkeep(self):
        self.splendor();self.effect(self.source,LoseLife('controller',3));self.effect(self.source,PhaseOut('source'))
        self.kernel.begin_step('A','upkeep');self.assertFalse(self.kernel.stack);self.assertEqual(40,self.note())
        self.kernel.begin_turn_for_scenario('A');self.top();self.assertEqual(37,self.note())

    def test_sigarda_entry_copy_notes_own_controller_life(self):
        copy=CardProgram('copy','Copy',('Enchantment',),entry_copy=Selector(Zone.BATTLEFIELD,types=('Enchantment',)))
        self.game('sigarda-s-splendor',extra=(copy,));self.kernel.enter(self.source);self.source=self.current()
        self.effect(self.own,LoseLife('controller',6),actor='B');ref=self.state.add_card('copy','copy','B',Zone.HAND);self.kernel.enter(ref)
        q=self.kernel.pending_choice;self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.ref==self.source)])
        self.assertEqual(34,self.note(self.current('copy')));self.assertEqual(40,self.note())

    def test_sigarda_entry_notes_replacement_order_with_life_payment(self):
        noted=CardProgram('noted-land','Noted land',('Land',),entry_modifiers=(
            EntryLifeNote('note'),EntryPayment('pay',life=2)))
        self.game('sigarda-s-splendor',extra=(noted,));ref=self.state.add_card('noted','noted-land','A',Zone.HAND)
        self.kernel.enter(ref);q=self.kernel.pending_choice
        self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.key.endswith(':pay'))])
        q=self.kernel.pending_choice;self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.key=='pay')])
        self.assertEqual(38,self.note(self.current('noted')));self.assertEqual(38,self.state.life('A'))

    def test_sigarda_entry_prohibition_leaves_no_note(self):
        cage=CardProgram('cage','Cage',('Artifact',),entry_restrictions=(Selector(Zone.GRAVEYARD,types=('Enchantment',)),))
        self.game('sigarda-s-splendor',zone=Zone.GRAVEYARD,extra=(cage,));self.state.add_card('cage','cage','A',Zone.BATTLEFIELD)
        self.kernel.enter(self.source);self.assertFalse(self.kernel.object_notes);self.assertEqual(Zone.GRAVEYARD,self.zone())

    def test_sigarda_checkpoint_and_actor_replay_keep_exact_note(self):
        self.splendor();self.effect(self.source,LoseLife('controller',4));self.kernel.begin_step('A','upkeep')
        adapter=RulesActorAdapter(self.kernel)
        for _ in self.state.live_players:adapter.submit(self.kernel.priority,{'kind':'pass','revision':self.kernel.revision})
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())
        self.assertEqual(self.kernel.snapshot(),RulesKernel.restore(self.kernel.snapshot(),self.programs).snapshot())

    def test_sage_normal_cast_retains_flying_stats_and_mana_cost(self):
        self.game('wonderscape-sage');self.cast(mana='CU');self.top()
        view=self.kernel.effective(self.current());self.assertEqual((1,3),(view.power,view.toughness));self.assertIn('flying',view.keywords)
        self.assertEqual((),self.state.mana_pool('A'))

    def test_sage_pays_tap_and_land_return_before_responses(self):
        self.sage();self.use_sage()
        self.assertTrue(self.state.get(self.source).tapped);self.assertEqual(Zone.HAND,self.zone('land'))
        self.response(definition='n-stifle');self.top();self.assertEqual(1,self.hand())
        self.assertEqual(Zone.HAND,self.zone('land'))

    def test_sage_nonbasic_land_without_subtype_still_requires_discard(self):
        self.sage();self.use_sage();self.top()
        self.assertEqual(2,self.hand());self.discard_one();self.assertEqual(1,self.hand())

    def test_sage_basic_land_type_requires_discard(self):
        self.sage();ref=self.state.add_card('basic','n-basic','A',Zone.BATTLEFIELD)
        self.use_sage(ref);self.top();self.assertIsNotNone(self.kernel.pending_choice);self.discard_one()
        self.assertEqual(1,self.hand())

    def test_sage_nonbasic_land_type_avoids_discard_even_with_basic_supertype(self):
        typed=CardProgram('typed','Typed',('Land',),supertypes=('Basic',),subtypes=('Forest','Cave'))
        self.game('wonderscape-sage',zone=Zone.BATTLEFIELD,extra=(typed,));self.state.start_turn('A');self.kernel.open_window_for_scenario('A')
        ref=self.state.add_card('typed','typed','A',Zone.BATTLEFIELD);self.use_sage(ref);self.top()
        self.assertIsNone(self.kernel.pending_choice);self.assertEqual(2,self.hand())

    def test_sage_borrowed_land_returns_to_owner_and_uses_old_subtypes(self):
        self.sage();ref=self.state.add_card('cave','n-cave','B',Zone.BATTLEFIELD)
        self.effect(ref,GainControl('source'));self.use_sage(ref);self.top()
        self.assertEqual(1,self.hand('A'));self.assertEqual(1,self.hand('B'));self.assertIsNone(self.kernel.pending_choice)

    def test_sage_copied_land_uses_battlefield_copy_before_return(self):
        copy=CardProgram('copy','Copy',('Land',),entry_copy=Selector(Zone.BATTLEFIELD,types=('Land',)))
        self.game('wonderscape-sage',zone=Zone.BATTLEFIELD,extra=(copy,));self.state.start_turn('A');self.kernel.open_window_for_scenario('A')
        cave=self.state.add_card('cave','n-cave','A',Zone.BATTLEFIELD);ref=self.state.add_card('copy','copy','A',Zone.HAND);self.kernel.enter(ref)
        q=self.kernel.pending_choice;self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.ref==cave)])
        self.use_sage(self.current('copy'));self.top()
        self.assertIsNone(self.kernel.pending_choice);self.assertNotIn('Cave',self.kernel.effective(self.current('copy')).subtypes)

    def test_sage_everything_counter_on_forest_uses_expanded_nonbasic_types(self):
        self.sage();self.state.add_card('omo','catalog:omo-queen-of-vesuva','A',Zone.BATTLEFIELD)
        ref=self.state.add_card('forest','n-basic','A',Zone.BATTLEFIELD);self.state.add_counters(ref,'everything',1)
        self.use_sage(ref);self.top();self.assertIsNone(self.kernel.pending_choice)
        self.assertEqual(2,self.hand());self.assertEqual((),self.state.get(self.current('forest')).counters)

    def test_sage_ineligible_return_payment_is_atomic(self):
        self.sage();bad=self.state.add_card('opponent','n-land','B',Zone.BATTLEFIELD);self.window()
        quote=self.kernel.quote_activation('bad','A',self.source,'return-draw');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,Payment(zone_costs=(('land-return',(bad,)),)))
        self.assertEqual(before,self.kernel.snapshot())

    def test_sage_cannot_tap_with_summoning_sickness(self):
        self.game('wonderscape-sage',zone=Zone.BATTLEFIELD);self.window();before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',self.source,'return-draw')
        self.assertEqual(before,self.kernel.snapshot())

    def test_sage_return_replacement_still_retains_prepaid_subtypes(self):
        redirect=CardProgram('redirect','Redirect',('Artifact',),replacements=(
            ZoneReplacement('redirect',Zone.HAND,Zone.EXILE,from_zone=Zone.BATTLEFIELD,types=('Land',)),))
        self.game('wonderscape-sage',zone=Zone.BATTLEFIELD,extra=(redirect,));self.state.start_turn('A');self.kernel.open_window_for_scenario('A')
        self.state.add_card('redirect','redirect','A',Zone.BATTLEFIELD);ref=self.state.add_card('cave','n-cave','A',Zone.BATTLEFIELD)
        self.use_sage(ref);self.top();self.assertEqual(Zone.EXILE,self.zone('cave'));self.assertIsNone(self.kernel.pending_choice)

    def test_sage_source_removed_after_payment_does_not_stop_draw(self):
        self.sage();self.use_sage();self.response((self.source,));self.top();self.top();self.discard_one()
        self.assertEqual(1,self.hand());self.assertEqual(Zone.GRAVEYARD,self.zone())

    def test_sage_public_paid_facts_do_not_expose_other_hand_cards(self):
        self.sage();self.state.add_card('sentinel-secret','n-body','A',Zone.HAND)
        ref=self.state.add_card('cave','n-cave','A',Zone.BATTLEFIELD);self.use_sage(ref)
        packet=RulesActorAdapter(self.kernel).packet('B')
        self.assertEqual({'land-return':['Cave']},packet['stack'][0]['paid_cost_subtypes'])
        self.assertNotIn('sentinel-secret',json.dumps(packet))
        discard=CardProgram('discarder','Discarder',('Artifact',),activated=(
            ActivatedProgram('discard',CostSpec(zone_costs=(ZoneCost('discard','discard',
                selector=Selector(Zone.HAND,relation='owned')),)),(Draw(),)),))
        self.game('wonderscape-sage',zone=Zone.BATTLEFIELD,extra=(discard,))
        device=self.state.add_card('device','discarder','A',Zone.BATTLEFIELD)
        secret=self.state.add_card('private-cost','n-body','A',Zone.HAND);self.window()
        self.kernel.commit_action(self.kernel.quote_activation('private-cost','A',device,'discard'),
            Payment(zone_costs=(('discard',(secret,)),)))
        public=RulesActorAdapter(self.kernel).packet('B')['stack'][0]
        self.assertNotIn('paid_cost_subtypes',public);self.assertNotIn('paid_cost_stats',public)

    def test_sage_actor_replay_restores_paid_subtypes_and_discard_choice(self):
        self.sage();self.use_sage();adapter=RulesActorAdapter(self.kernel)
        for _ in self.state.live_players:adapter.submit(self.kernel.priority,{'kind':'pass','revision':self.kernel.revision})
        q=self.kernel.pending_choice;adapter.submit('A',{'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[0]})
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())
        self.assertEqual(self.kernel.snapshot(),RulesKernel.restore(self.kernel.snapshot(),self.programs).snapshot())

    def test_unbound_life_notes_paid_subtypes_and_quantity_values_are_rejected(self):
        bad=(
            CardProgram('bad','Bad',('Sorcery',),spell_effects=(NoteLife(),)),
            CardProgram('bad','Bad',('Sorcery',),spell_effects=(CompareLifeNote(),)),
            CardProgram('bad','Bad',('Sorcery',),spell_effects=(IfPaidCostSubtype('missing',sets=('nonbasic_land',)),)),
            CardProgram('bad','Bad',('Artifact',),activated=(ActivatedProgram('bad',
                CostSpec(zone_costs=(ZoneCost('hidden','discard',selector=Selector(Zone.HAND,relation='owned')),)),
                (IfPaidCostSubtype('hidden',sets=('nonbasic_land',)),)),)),
            CardProgram('bad','Bad',('Sorcery',),spell_effects=(IfQuantityAtLeast(MovedCount(),1,()),)),
            CardProgram('bad','Bad',('Enchantment',),entry_modifiers=(EntryLifeNote('bad',note_id=''),)),
            CardProgram('bad','Bad',('Instant',),cast=CleanupCast(CostSpec(),timing='instant')),
            CardProgram('bad','Bad',('Creature',),cast=KickerCast(CostSpec(),kicker=CostSpec(life=2)),power=1,toughness=1),
            CardProgram('bad','Bad',('Enchantment',),abilities=(AbilityProgram('bad',ColoredSpellEvent('spell_cast',colors=('Q',)),()),)),
        )
        for program in bad:
            with self.subTest(program=program),self.assertRaises(RulesViolation):validate(program)

    def test_note_checkpoint_layout_and_old_kernel_rejection(self):
        self.splendor();checkpoint=self.kernel.snapshot()
        self.assertEqual(120,checkpoint['schema']);self.assertEqual(13,checkpoint['state']['schema'])
        self.assertEqual(checkpoint,RulesKernel.restore(checkpoint,self.programs).snapshot())
        checkpoint['schema']=119
        with self.assertRaises(RulesViolation):RulesKernel.restore(checkpoint,self.programs)


if __name__=='__main__':unittest.main()
