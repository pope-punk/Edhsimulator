"""Eight complete cards sharing guards, payments and public history."""
import json
import unittest
from dataclasses import replace
from pathlib import Path
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState, RulesViolation, Zone, ZoneMove, PlayerRef
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_combat import CombatView, uid
from edh_gauntlet.rules_bundle import load_reviewed, digest, source_facts
from edh_gauntlet.catalog import load_catalog

CARDS=('karmic-guide','alseid-of-life-s-bounty','fanatical-devotion','pongify',
       'dimir-house-guard','midnight-snack','restart-sequence','jyoti-moag-ancient')


class GuardHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        reviewed=load_reviewed(cls.root)
        drafts=json.loads((cls.root/'data/rules/draft_cards.json').read_text(encoding='utf-8'))['drafts']
        cls.rows={row['card_id']:row for row in drafts if row['card_id'] in CARDS}
        cls.cards={key:validate(decode(row['program'])) for key,row in cls.rows.items()}
        cls.base=tuple(row['program'] for row in reviewed.values())+tuple(cls.cards.values())

    def game(self,card='karmic-guide',zone=Zone.BATTLEFIELD,extra=()):
        body=CardProgram('g-body','Body',('Creature',),power=2,toughness=3,
            cast=CastSpec(CostSpec()),mana_value=4)
        black=replace(body,definition_id='g-black',name='Black',colors=('B',))
        white=replace(body,definition_id='g-white',name='White',colors=('W',))
        artifact=replace(body,definition_id='g-artifact',name='Artifact',types=('Artifact','Creature'))
        assassin=replace(body,definition_id='g-assassin',name='Assassin',subtypes=('Assassin',),colors=('U',))
        land=CardProgram('g-land','Land',('Land',))
        forest=replace(body,definition_id='g-dryad',name='Forest Dryad',types=('Land','Creature'),subtypes=('Forest','Dryad'),cast=None)
        remove=CardProgram('g-remove','Remove',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD)),spell_effects=(Move('target',Zone.GRAVEYARD),))
        destroy=replace(remove,definition_id='g-destroy',name='Destroy',spell_effects=(Destroy('target'),))
        black_remove=replace(remove,definition_id='g-black-remove',name='Black Remove',colors=('B',))
        exile=replace(remove,definition_id='g-exile',name='Exile',spell_effects=(Move('target',Zone.EXILE),))
        control=replace(remove,definition_id='g-control',name='Control',spell_effects=(GainControl('target'),))
        pump=replace(remove,definition_id='g-pump',name='Pump',spell_effects=(UntilEndOfTurn('target',(ModifyPT(3,3),)),))
        noop=replace(remove,definition_id='g-noop',name='Noop',spell_targets=None,spell_effects=())
        counter=replace(remove,definition_id='g-counter',name='Counter',spell_targets=TargetSpec(Selector(Zone.STACK)),spell_effects=(Counter(),))
        stifle=replace(noop,definition_id='g-stifle',name='Stifle',spell_effects=(CounterAbilities(),))
        life=tuple(replace(noop,definition_id='g-'+kind+'-'+str(n),name=kind+str(n),
            spell_effects=((GainLife(n) if kind=='gain' else LoseLife('controller',n)),))
            for kind in ('gain','lose') for n in (1,3,4,5,6,7))
        aura=CardProgram('g-aura','Black Aura',('Enchantment',),colors=('B',),enchant=Selector(Zone.BATTLEFIELD,types=('Creature',)),
            cast=CastSpec(CostSpec()),spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',))))
        equipment=CardProgram('g-equipment','Black Equipment',('Artifact',),colors=('B',),subtypes=('Equipment',))
        self.programs=self.base+(body,black,white,artifact,assassin,land,forest,remove,destroy,black_remove,exile,control,pump,noop,counter,stifle,aura,equipment)+life+extra
        self.state=RulesState(('A','B','C','D'));self.kernel=RulesKernel(self.state,self.programs)
        self.kernel.open_window_for_scenario('A');self.serial=0
        self.source=self.add(self.cards[card].definition_id,'A',zone)
        self.body=self.add('g-body');self.other=self.add('g-body','B');self.own_dead=self.add('g-body','A',Zone.GRAVEYARD)
        self.other_dead=self.add('g-body','B',Zone.GRAVEYARD)
        for player in self.state.players:
            for _ in range(12):self.add('g-body',player,Zone.LIBRARY)

    def ident(self):
        self.serial+=1
        return 'g-object-'+str(self.serial)

    def add(self,definition='g-body',actor='A',zone=Zone.BATTLEFIELD,**kw):
        return self.state.add_card(self.ident(),definition,actor,zone,**kw)

    def zone(self,ref):return self.state.get(self.state.current(ref.card_id)).zone

    def window(self,actor='A'):
        if not self.kernel.stack and self.kernel.turn_schedule is None:
            self.kernel.open_window_for_scenario(self.kernel.active,phase=self.kernel.phase if self.kernel.phase in {'precombat_main','postcombat_main','upkeep'} else 'precombat_main',priority_actor=actor)
        while self.kernel.priority!=actor:self.kernel.pass_priority(self.kernel.priority)

    def round(self):
        for _ in self.state.live_players:result=self.kernel.pass_priority(self.kernel.priority)
        return result

    def top(self):
        self.assertTrue(self.kernel.stack)
        return self.round()

    def answer(self,key=None,refs=None,indexes=None):
        q=self.kernel.pending_choice;self.assertIsNotNone(q)
        if indexes is None:
            indexes=[i for i,o in enumerate(q.options) if o.key==key] if refs is None else [next(i for i,o in enumerate(q.options) if o.ref==ref) for ref in refs]
        return self.kernel.answer(q.request_id,q.actor,indexes)

    def payment(self,mana):
        symbols=tuple(mana)
        return Payment(tuple((s,symbols.count(s)) for s in sorted(set(symbols))))

    def cast(self,ref=None,mana=(),targets=(),actor='A',alternative=None):
        ref=self.source if ref is None else ref;self.window(actor)
        if mana:self.state.add_mana(actor,tuple(mana))
        quote=self.kernel.quote_cast(self.ident(),actor,ref,targets,alternative_id=alternative)
        return self.kernel.commit_action(quote,self.payment(mana))

    def response(self,definition='g-remove',targets=(),actor='B',mana=()):
        ref=self.add(definition,actor,Zone.HAND)
        return self.cast(ref,mana,targets,actor)

    def activate(self,ability,ref=None,mana=(),targets=(),actor='A',sacrifice=None):
        ref=self.source if ref is None else ref;self.window(actor)
        if mana:self.state.add_mana(actor,tuple(mana))
        quote=self.kernel.quote_activation(self.ident(),actor,ref,ability,targets)
        payment=self.payment(mana)
        if sacrifice is not None:payment=replace(payment,zone_costs=(('sacrifice-creature',(sacrifice,)),))
        return self.kernel.commit_action(quote,payment)

    def fx(self,ref,*effects,actor='A'):
        self.assertFalse(self.kernel.stack)
        return self.kernel.execute_for_scenario(ref,actor,effects)

    def step(self,phase,actor='A'):
        self.assertFalse(self.kernel.stack);self.assertIsNone(self.kernel.turn_schedule)
        self.kernel.active=actor;self.kernel._begin_phase(phase)
        return self.kernel.advance()

    def enter(self):
        self.kernel.enter(self.source);self.source=self.state.current(self.source.card_id)
        if self.kernel.pending_choice:self.answer(refs=(self.own_dead,))
        return self.source

    def echo_pay(self,mana=None):
        q=self.kernel.mana_payment;self.assertIsNotNone(q)
        if mana:self.state.add_mana(q['actor'],tuple(mana))
        return self.kernel.pay_resolution_mana(self.ident(),q['actor'],q['id'],None if mana is None else self.payment(mana),revision=self.kernel.revision)

    def shield(self,ref=None):
        return self.fx(ref or self.body,Regenerate('source'))

    def tokens(self,name,actor='A'):
        return tuple(obj for obj in self.state.objects(Zone.BATTLEFIELD,controller=actor) if obj.token and self.kernel.definition(obj).name==name)

    def restore(self):
        checkpoint=self.kernel.snapshot()
        other=RulesKernel.restore(checkpoint,self.programs)
        self.assertEqual(checkpoint,other.snapshot())
        self.kernel=other;self.state=other.state

    def attackers_step(self,refs=()):
        self.kernel.begin_turn_for_scenario('A')
        for _ in range(4):self.round()
        self.assertEqual('declare_attackers',self.kernel.phase)
        self.kernel.declare_attackers('A',{ref:'B' for ref in refs},revision=self.kernel.revision)

    def complete_unblocked(self,refs):
        self.attackers_step(refs)
        self.round()
        self.kernel.declare_blockers('B',{uid(ref):[] for ref in refs},revision=self.kernel.revision)
        self.round()

    def test_all_eight_printed_faces_costs_and_source_bindings(self):
        self.assertEqual(set(CARDS),set(self.cards))
        catalog={c.card_id:c for c in load_catalog(self.root/'data/catalog/cards.json')}
        for key,program in self.cards.items():
            with self.subTest(card=key):
                self.assertEqual('draft:'+key,program.definition_id)
                self.assertEqual(digest(source_facts(catalog[key])),digest(self.rows[key]['source_facts']))
                self.assertEqual(program,validate(decode(encode(program))))
                face=catalog[key].faces[0]
                for field in ('types','subtypes','supertypes','colors'):self.assertEqual(set(getattr(face,field)),set(getattr(program,field)))
                for field in ('power','toughness','mana_value'):self.assertEqual(getattr(face,field),getattr(program,field))
                self.assertEqual('instant' if key=='pongify' else 'sorcery',program.cast.timing)
        self.assertEqual(ManaCost(3,('W','W')),self.cards['karmic-guide'].cast.cost.mana)
        self.assertEqual(ManaCost(2,('G','U')),self.cards['jyoti-moag-ancient'].cast.cost.mana)

    def test_karmic_black_spell_target_is_rejected_before_costs(self):
        self.game();spell=self.add('g-black-remove','B',Zone.HAND);self.window('B');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_cast(self.ident(),'B',spell,(self.source,))
        self.assertEqual(before,self.kernel.snapshot())

    def test_karmic_protection_does_not_stop_colorless_or_white_targets(self):
        self.game();self.response(targets=(self.source,));self.top()
        self.assertEqual(Zone.GRAVEYARD,self.zone(self.source))

    def test_protection_rechecks_source_color_on_resolution(self):
        self.game('alseid-of-life-s-bounty')
        spell=self.add('g-black-remove','B',Zone.HAND)
        self.cast(spell,targets=(self.body,),actor='B')
        self.activate('protect',mana='C',targets=(self.body,));self.top();self.answer('B');self.top()
        self.assertEqual(Zone.BATTLEFIELD,self.zone(self.body))

    def test_alseid_pays_before_choosing_color(self):
        self.game('alseid-of-life-s-bounty')
        self.activate('protect',mana='C',targets=(self.body,))
        self.assertEqual(Zone.GRAVEYARD,self.zone(self.source));self.assertIsNone(self.kernel.pending_choice)
        self.top();self.assertEqual('protection_color',self.kernel.pending_choice.kind)
        self.assertEqual(set('WUBRG'),{o.key for o in self.kernel.pending_choice.options})
        self.answer('G');self.assertIn('protection_green',self.kernel.effective(self.body).keywords)

    def test_alseid_can_protect_an_enchantment(self):
        self.game('alseid-of-life-s-bounty');target=self.add(self.cards['fanatical-devotion'].definition_id)
        self.activate('protect',mana='C',targets=(target,));self.top();self.answer('U')
        self.assertIn('protection_blue',self.kernel.effective(target).keywords)

    def test_alseid_cannot_target_opponent_or_plain_land(self):
        self.game('alseid-of-life-s-bounty');land=self.add('g-land')
        for ref in (self.other,land):
            before=self.kernel.snapshot()
            with self.assertRaises(RulesViolation):self.kernel.quote_activation(self.ident(),'A',self.source,'protect',(ref,))
            self.assertEqual(before,self.kernel.snapshot())

    def test_alseid_target_departure_skips_color_choice(self):
        self.game('alseid-of-life-s-bounty');self.activate('protect',mana='C',targets=(self.body,))
        self.response(targets=(self.body,));self.top();self.top()
        self.assertIsNone(self.kernel.pending_choice);self.assertEqual(Zone.GRAVEYARD,self.zone(self.body))

    def test_alseid_can_target_itself_but_sacrifice_invalidates_target(self):
        self.game('alseid-of-life-s-bounty');self.activate('protect',mana='C',targets=(self.source,));self.top()
        self.assertIsNone(self.kernel.pending_choice);self.assertEqual(Zone.GRAVEYARD,self.zone(self.source))

    def test_alseid_color_choice_rejects_wrong_actor_and_bad_option(self):
        self.game('alseid-of-life-s-bounty');self.activate('protect',mana='C',targets=(self.body,));self.top()
        q=self.kernel.pending_choice;before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.answer(q.request_id,'B',[0])
        with self.assertRaises(RulesViolation):self.kernel.answer(q.request_id,'A',[5])
        self.assertEqual(before,self.kernel.snapshot());self.answer('W')

    def test_alseid_protection_expires_at_cleanup(self):
        self.game('alseid-of-life-s-bounty');self.activate('protect',mana='C',targets=(self.body,));self.top();self.answer('B')
        self.kernel._finish_cleanup_actions();self.kernel.advance()
        self.assertNotIn('protection_black',self.kernel.effective(self.body).keywords)

    def test_protection_prevents_damage_and_lifelink_gain(self):
        self.game();black=self.add('g-black','B')
        self.fx(black,UntilEndOfTurn('source',(AddKeywords(('lifelink','deathtouch')),)),actor='B')
        self.kernel._deal_damage(((self.state.get(black),self.source,5),))
        self.assertEqual(0,self.state.get(self.source).damage_marked);self.assertEqual(40,self.state.life('B'))
        self.assertFalse(self.state.get(self.source).deathtouch_hit)
        self.assertFalse(any(e['kind']=='damage_dealt' for e in self.kernel.semantic_events))

    def test_protection_prevents_combat_damage_too(self):
        self.game();black=self.add('g-black','B')
        self.kernel._deal_damage(((self.state.get(black),self.source,9),),combat=True)
        self.kernel.advance();self.assertEqual(Zone.BATTLEFIELD,self.zone(self.source))

    def test_protection_does_not_prevent_other_color_damage(self):
        self.game();white=self.add('g-white','B')
        self.kernel._deal_damage(((self.state.get(white),self.source,2),))
        self.kernel.advance();self.assertEqual(Zone.GRAVEYARD,self.zone(self.source))

    def test_protection_matches_any_color_of_a_multicolor_source(self):
        self.game();black=self.add('g-black','B')
        self.fx(black,UntilEndOfTurn('source',(SetColors(('B','U')),)),actor='B')
        self.kernel._deal_damage(((self.state.get(black),self.source,4),))
        self.assertEqual(0,self.state.get(self.source).damage_marked)

    def test_protection_uses_departed_sources_last_known_colors(self):
        ability=ActivatedProgram('blast',CostSpec(zone_costs=(ZoneCost('self','sacrifice'),)),(Damage('target',5),),targets=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',))))
        source=CardProgram('g-blaster','Blaster',('Creature',),colors=('U',),power=1,toughness=1,activated=(ability,))
        self.game('alseid-of-life-s-bounty',extra=(source,));blaster=self.add('g-blaster','B')
        self.fx(blaster,UntilEndOfTurn('source',(SetColors(('B',)),)),actor='B')
        self.activate('blast',blaster,targets=(self.body,),actor='B')
        self.activate('protect',mana='C',targets=(self.body,));self.top();self.answer('B');self.top()
        self.assertEqual(0,self.state.get(self.body).damage_marked)

    def test_protection_restricts_black_blockers_but_not_white_flyers(self):
        self.game();black=self.add('g-black','B');white=self.add('g-white','B')
        for ref in (black,white):self.fx(ref,UntilEndOfTurn('source',(AddKeywords(('flying',)),)),actor='B')
        view=CombatView(self.kernel)
        self.assertFalse(view.can_block(view.card(black),view.card(self.source)))
        self.assertTrue(view.can_block(view.card(white),view.card(self.source)))

    def test_protection_gain_after_legal_block_keeps_blocked_designation(self):
        self.game('alseid-of-life-s-bounty');blocker=self.add('g-black','B')
        self.attackers_step((self.body,));self.round()
        self.kernel.declare_blockers('B',{uid(self.body):[uid(blocker)]},revision=self.kernel.revision)
        self.activate('protect',mana='C',targets=(self.body,));self.top();self.answer('B')
        self.assertIn(uid(self.body),self.kernel.combat['blocked'])
        self.assertEqual(1,len(self.kernel.combat['blocks'][uid(self.body)]))

    def test_black_aura_cannot_enter_attached_to_protected_creature(self):
        self.game();aura=self.add('g-aura','B',Zone.HAND)
        self.kernel.enter(aura,'B')
        if self.kernel.pending_choice:
            self.assertNotIn(self.source,{o.ref for o in self.kernel.pending_choice.options});self.answer(refs=(self.other,))
        self.assertNotEqual(self.source,self.state.get(self.state.current(aura.card_id)).attached_to)

    def test_protection_removes_attached_aura_and_detaches_equipment(self):
        self.game('alseid-of-life-s-bounty')
        aura=self.add('g-aura');equipment=self.add('g-equipment')
        self.state.attach(aura,self.body);self.state.attach(equipment,self.body)
        self.activate('protect',mana='C',targets=(self.body,));self.top();self.answer('B')
        self.assertEqual(Zone.GRAVEYARD,self.zone(aura));self.assertIsNone(self.state.get(equipment).attached_to)
        self.assertEqual(Zone.BATTLEFIELD,self.zone(equipment))

    def test_protection_does_not_restrict_nontargeted_selection(self):
        self.game();black=self.add('g-black','B');self.fx(black,SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',),relation='opponent_controlled'),(Destroy('selected'),)),actor='B')
        self.assertEqual(Zone.GRAVEYARD,self.zone(self.source))

    def test_protection_color_choice_checkpoint_and_actor_replay(self):
        self.game('alseid-of-life-s-bounty');self.activate('protect',mana='C',targets=(self.body,));self.top()
        adapter=RulesActorAdapter(self.kernel);q=self.kernel.pending_choice
        adapter.submit('A',{'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[2]})
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())
        self.restore();self.assertIn('protection_black',self.kernel.effective(self.body).keywords)

    def test_regeneration_creation_does_not_tap_or_remove_damage(self):
        self.game('fanatical-devotion')
        self.kernel._deal_damage(((self.state.get(self.other),self.body,1),))
        self.activate('regenerate',targets=(self.body,),sacrifice=self.add())
        self.top()
        self.assertFalse(self.state.get(self.body).tapped);self.assertEqual(1,self.state.get(self.body).damage_marked)
        self.assertEqual(1,len(self.kernel.regeneration_shields))

    def test_regeneration_replaces_destroy_and_consumes_one_shield(self):
        self.game('fanatical-devotion');self.shield()
        self.fx(self.body,Destroy('source'))
        self.assertEqual(Zone.BATTLEFIELD,self.zone(self.body));self.assertTrue(self.state.get(self.body).tapped)
        self.assertFalse(self.kernel.regeneration_shields)
        self.fx(self.body,Destroy('source'));self.assertEqual(Zone.GRAVEYARD,self.zone(self.body))

    def test_regeneration_clears_lethal_damage_and_deathtouch(self):
        self.game('fanatical-devotion');self.shield()
        self.fx(self.other,UntilEndOfTurn('source',(AddKeywords(('deathtouch',)),)),actor='B')
        self.kernel._deal_damage(((self.state.get(self.other),self.body,1),));self.kernel.advance()
        obj=self.state.get(self.body);self.assertEqual(0,obj.damage_marked);self.assertFalse(obj.deathtouch_hit);self.assertTrue(obj.tapped)

    def test_regeneration_multiple_shields_require_affected_player_order(self):
        self.game('fanatical-devotion');self.shield();self.shield()
        self.fx(self.body,Destroy('source'));q=self.kernel.pending_choice
        self.assertEqual('replacement_order',q.kind);self.assertEqual('A',q.actor)
        self.assertEqual(2,len(q.options));self.answer(indexes=[1])
        self.assertEqual(1,len(self.kernel.regeneration_shields));self.assertEqual(Zone.BATTLEFIELD,self.zone(self.body))

    def test_regeneration_replacement_choice_survives_checkpoint(self):
        redirect=CardProgram('g-redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,from_zone=Zone.BATTLEFIELD,types=('Creature',)),))
        self.game('fanatical-devotion',extra=(redirect,));self.add('g-redirect');self.shield()
        self.fx(self.body,Destroy('source'));q=self.kernel.pending_choice
        before=self.state.snapshot();self.restore();self.assertEqual(before,self.state.snapshot())
        q=self.kernel.pending_choice;self.answer(indexes=[next(i for i,o in enumerate(q.options) if o.key in self.kernel.regeneration_shields)])
        self.assertEqual(Zone.BATTLEFIELD,self.zone(self.body));self.assertFalse(self.kernel.regeneration_shields)

    def test_exile_replacement_selected_before_regeneration_keeps_shield(self):
        redirect=CardProgram('g-redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,from_zone=Zone.BATTLEFIELD,types=('Creature',)),))
        self.game('fanatical-devotion',extra=(redirect,));self.add('g-redirect');self.shield()
        self.fx(self.body,Destroy('source'));q=self.kernel.pending_choice
        self.answer(indexes=[next(i for i,o in enumerate(q.options) if o.key not in self.kernel.regeneration_shields)])
        self.assertEqual(Zone.EXILE,self.zone(self.body));self.assertEqual(1,len(self.kernel.regeneration_shields))

    def test_regeneration_does_not_save_a_sacrificed_creature(self):
        self.game('fanatical-devotion');self.shield();self.fx(self.body,Sacrifice('source'))
        self.assertEqual(Zone.GRAVEYARD,self.zone(self.body));self.assertEqual(1,len(self.kernel.regeneration_shields))

    def test_regeneration_does_not_save_zero_toughness(self):
        self.game('fanatical-devotion');self.shield();self.fx(self.body,UntilEndOfTurn('source',(SetPT(0,0),)))
        self.assertEqual(Zone.GRAVEYARD,self.zone(self.body));self.assertEqual(1,len(self.kernel.regeneration_shields))

    def test_regeneration_does_not_save_illegal_aura(self):
        self.game('fanatical-devotion');aura=self.add('g-aura');self.state.attach(aura,self.body);self.shield(aura)
        self.fx(self.body,Move('source',Zone.EXILE));self.assertEqual(Zone.GRAVEYARD,self.zone(aura))

    def test_regeneration_does_not_save_legend_rule_loser(self):
        legend=CardProgram('g-legend','Legend',('Creature',),power=2,toughness=2,supertypes=('Legendary',))
        self.game('fanatical-devotion',extra=(legend,));first=self.add('g-legend');self.shield(first);second=self.add('g-legend')
        self.kernel.advance();self.answer(refs=(second,))
        self.assertEqual(Zone.GRAVEYARD,self.zone(first));self.assertEqual(Zone.BATTLEFIELD,self.zone(second))

    def test_indestructible_does_not_consume_a_regeneration_shield(self):
        self.game('fanatical-devotion');self.shield();self.fx(self.body,UntilEndOfTurn('source',(AddKeywords(('indestructible',)),)))
        self.fx(self.body,Destroy('source'));self.assertEqual(1,len(self.kernel.regeneration_shields));self.assertFalse(self.state.get(self.body).tapped)

    def test_regeneration_survives_control_change(self):
        self.game('fanatical-devotion');self.shield();self.fx(self.body,GainControl('source'),actor='B')
        self.fx(self.body,Destroy('source'));self.assertEqual('B',self.state.get(self.body).controller);self.assertTrue(self.state.get(self.body).tapped)

    def test_regeneration_never_follows_blink_incarnation(self):
        self.game('fanatical-devotion');self.shield();old=self.body
        self.fx(old,Move('source',Zone.EXILE));self.body=self.state.current(old.card_id);self.kernel.enter(self.body)
        self.body=self.state.current(old.card_id);self.fx(self.body,Destroy('source'))
        self.assertEqual(Zone.GRAVEYARD,self.zone(self.body))

    def test_regeneration_expires_even_while_recipient_is_phased(self):
        self.game('fanatical-devotion');self.shield();self.fx(self.body,PhaseOut('source'))
        self.kernel._finish_cleanup_actions();self.assertFalse(self.kernel.regeneration_shields)
        self.assertTrue(self.state.get(self.body).phased)

    def test_regeneration_keeps_nondestroyed_objects_in_simultaneous_sba_batch(self):
        self.game('fanatical-devotion');self.shield()
        self.kernel._deal_damage(((self.state.get(self.other),self.body,3),(self.state.get(self.body),self.other,3)))
        self.kernel.advance()
        self.assertEqual(Zone.BATTLEFIELD,self.zone(self.body));self.assertEqual(Zone.GRAVEYARD,self.zone(self.other))
        self.assertEqual(0,self.state.get(self.body).damage_marked)

    def test_regeneration_removes_an_attacker_from_combat(self):
        self.game('fanatical-devotion');self.shield();self.attackers_step((self.body,))
        self.fx(self.body,Destroy('source'))
        self.assertFalse(self.kernel.combat['attackers']);self.assertEqual(Zone.BATTLEFIELD,self.zone(self.body))

    def test_regeneration_removes_blocker_but_preserves_attackers_blocked_status(self):
        self.game('fanatical-devotion');self.shield(self.other);self.attackers_step((self.body,));self.round()
        self.kernel.declare_blockers('B',{uid(self.body):[uid(self.other)]},revision=self.kernel.revision)
        self.fx(self.other,Destroy('source'))
        self.assertEqual([],self.kernel.combat['blocks'][uid(self.body)]);self.assertIn(uid(self.body),self.kernel.combat['blocked'])

    def test_devotion_sacrifice_target_pays_but_does_not_create_shield(self):
        self.game('fanatical-devotion');self.activate('regenerate',targets=(self.body,),sacrifice=self.body);self.top()
        self.assertEqual(Zone.GRAVEYARD,self.zone(self.body));self.assertFalse(self.kernel.regeneration_shields)

    def test_devotion_wrong_sacrifice_is_rejected_atomically(self):
        self.game('fanatical-devotion');quote=self.kernel.quote_activation(self.ident(),'A',self.source,'regenerate',(self.body,));before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,Payment(zone_costs=(('sacrifice-creature',(self.other,)),)))
        self.assertEqual(before,self.kernel.snapshot())

    def test_devotion_can_regenerate_opponents_creature(self):
        self.game('fanatical-devotion');self.activate('regenerate',targets=(self.other,),sacrifice=self.body);self.top()
        self.fx(self.other,Destroy('source'));self.assertEqual(Zone.BATTLEFIELD,self.zone(self.other))

    def test_devotion_countered_activation_keeps_cost_without_shield(self):
        self.game('fanatical-devotion');fodder=self.add()
        self.activate('regenerate',targets=(self.body,),sacrifice=fodder)
        self.response('g-stifle');self.top()
        self.assertFalse(self.kernel.regeneration_shields);self.assertEqual(Zone.GRAVEYARD,self.zone(fodder))

    def test_pongify_destroys_without_using_existing_shield(self):
        self.game('pongify',zone=Zone.HAND);self.shield(self.other)
        self.cast(mana='U',targets=(self.other,));self.top()
        self.assertEqual(Zone.GRAVEYARD,self.zone(self.other));self.assertEqual(1,len(self.tokens('Ape','B')))
        self.assertEqual(1,len(self.kernel.regeneration_shields));ape=self.tokens('Ape','B')[0]
        view=self.kernel.effective(ape.ref);self.assertEqual((3,3),(view.power,view.toughness));self.assertEqual(frozenset(('G',)),view.colors)

    def test_pongify_still_creates_ape_for_indestructible_target(self):
        self.game('pongify',zone=Zone.HAND);self.fx(self.other,UntilEndOfTurn('source',(AddKeywords(('indestructible',)),)),actor='B')
        self.cast(mana='U',targets=(self.other,));self.top()
        self.assertEqual(Zone.BATTLEFIELD,self.zone(self.other));self.assertEqual(1,len(self.tokens('Ape','B')))

    def test_pongify_invalid_target_creates_no_ape(self):
        self.game('pongify',zone=Zone.HAND);self.cast(mana='U',targets=(self.other,))
        self.response('g-exile',(self.other,));self.top();self.top();self.assertFalse(self.tokens('Ape','B'))

    def test_pongify_uses_controller_at_resolution(self):
        self.game('pongify',zone=Zone.HAND);self.cast(mana='U',targets=(self.other,))
        self.response('g-control',(self.other,),actor='C');self.top();self.top()
        self.assertEqual(1,len(self.tokens('Ape','C')));self.assertFalse(self.tokens('Ape','B'))

    def test_pongify_token_does_not_depend_on_graveyard_destination(self):
        redirect=CardProgram('g-redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,from_zone=Zone.BATTLEFIELD,types=('Creature',)),))
        self.game('pongify',zone=Zone.HAND,extra=(redirect,));self.add('g-redirect')
        self.cast(mana='U',targets=(self.other,));self.top()
        self.assertEqual(Zone.EXILE,self.zone(self.other));self.assertEqual(1,len(self.tokens('Ape','B')))

    def test_regeneration_public_shields_hide_later_hidden_incarnations(self):
        self.game('fanatical-devotion');self.shield()
        packet=RulesActorAdapter(self.kernel).packet('B');self.assertEqual(self.body.to_json(),packet['regeneration_shields'][0]['ref'])
        self.fx(self.body,Move('source',Zone.HAND))
        self.assertEqual([],RulesActorAdapter(self.kernel).packet('B')['regeneration_shields'])

    def test_karmic_normal_cast_and_graveyard_return(self):
        self.game(zone=Zone.HAND);self.cast(mana='CCCWW');self.top();self.answer(refs=(self.own_dead,));self.top()
        self.assertEqual(Zone.BATTLEFIELD,self.zone(self.source));self.assertEqual(Zone.BATTLEFIELD,self.zone(self.own_dead))
        view=self.kernel.effective(self.state.current(self.source.card_id));self.assertTrue({'flying','protection_black'}<=view.keywords)

    def test_karmic_enter_target_must_be_own_graveyard_creature(self):
        self.game(zone=Zone.HAND);self.kernel.enter(self.source)
        self.assertIn(self.own_dead,{o.ref for o in self.kernel.pending_choice.options})
        self.assertNotIn(self.other_dead,{o.ref for o in self.kernel.pending_choice.options});self.answer(refs=(self.own_dead,));self.top()

    def test_karmic_echo_decline_sacrifices_source(self):
        self.game();self.kernel.begin_step('A','upkeep');self.top()
        self.echo_pay();self.assertEqual(Zone.GRAVEYARD,self.zone(self.source))

    def test_karmic_echo_paid_only_once_without_new_control(self):
        self.game();self.kernel.begin_step('A','upkeep');self.top();self.echo_pay('CCCWW')
        self.assertEqual(Zone.BATTLEFIELD,self.zone(self.source))
        self.kernel.begin_step('A','upkeep');self.assertFalse(self.kernel.stack)

    def test_karmic_echo_countered_does_not_recur_next_upkeep(self):
        self.game();self.kernel.begin_step('A','upkeep');self.response('g-stifle');self.top()
        self.kernel.begin_step('A','upkeep');self.assertFalse(self.kernel.stack);self.assertEqual(Zone.BATTLEFIELD,self.zone(self.source))

    def test_karmic_echo_uses_upkeep_not_turn_start_boundary(self):
        self.game();self.kernel.begin_step('A','upkeep');self.top();self.echo_pay('CCCWW')
        self.fx(self.source,GainControl('source'),actor='B');self.fx(self.source,GainControl('source'),actor='A')
        self.state.start_turn('A')
        self.assertTrue(self.state.ready_since_turn_start(self.source))
        self.kernel.begin_step('A','upkeep');self.assertTrue(self.kernel.stack);self.top();self.echo_pay()

    def test_karmic_echo_rechecks_new_controller_on_their_upkeep(self):
        self.game();self.kernel.begin_step('A','upkeep');self.top();self.echo_pay('CCCWW')
        self.fx(self.source,GainControl('source'),actor='B')
        self.kernel.begin_step('A','upkeep');self.assertFalse(self.kernel.stack)
        self.kernel.begin_step('B','upkeep');self.top();self.assertEqual('B',self.kernel.mana_payment['actor']);self.echo_pay()
        self.assertEqual(Zone.GRAVEYARD,self.zone(self.source))

    def test_karmic_echo_trigger_cannot_sacrifice_new_controllers_permanent(self):
        self.game();self.kernel.begin_step('A','upkeep')
        self.response('g-control',(self.source,),actor='B');self.top();self.top();self.echo_pay()
        self.assertEqual(Zone.BATTLEFIELD,self.zone(self.source));self.assertEqual('B',self.state.get(self.source).controller)

    def test_karmic_echo_payment_remains_possible_after_source_leaves(self):
        self.game();self.kernel.begin_step('A','upkeep');self.response(targets=(self.source,));self.top();self.top()
        self.echo_pay('CCCWW');self.assertEqual(Zone.GRAVEYARD,self.zone(self.source));self.assertEqual((),self.state.mana_pool('A'))

    def test_karmic_phased_upkeep_advances_history_without_echo(self):
        self.game();self.fx(self.source,PhaseOut('source'))
        self.kernel.begin_step('A','upkeep');self.assertFalse(self.kernel.stack)
        self.state.phase(self.source,False)
        self.kernel.begin_step('A','upkeep');self.assertFalse(self.kernel.stack)

    def test_karmic_echo_payment_rejects_bad_or_unauthorized_packet(self):
        self.game();self.kernel.begin_step('A','upkeep');self.top();q=self.kernel.mana_payment;before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.pay_resolution_mana(self.ident(),'B',q['id'],None,revision=self.kernel.revision)
        with self.assertRaises(RulesViolation):self.kernel.pay_resolution_mana(self.ident(),'A',q['id'],Payment(),revision=self.kernel.revision)
        self.assertEqual(before,self.kernel.snapshot());self.echo_pay()

    def test_karmic_echo_checkpoint_retains_payment_and_history(self):
        self.game();self.kernel.begin_step('A','upkeep');self.top();self.restore();self.echo_pay('CCCWW')
        self.kernel.begin_step('A','upkeep');self.assertFalse(self.kernel.stack)

    def test_dimir_fear_permits_black_and_artifact_blockers(self):
        self.game('dimir-house-guard');black=self.add('g-black','B');artifact=self.add('g-artifact','B')
        view=CombatView(self.kernel)
        self.assertTrue(view.can_block(view.card(black),view.card(self.source)))
        self.assertTrue(view.can_block(view.card(artifact),view.card(self.source)))
        self.assertFalse(view.can_block(view.card(self.other),view.card(self.source)))

    def test_dimir_fear_uses_current_derived_color(self):
        self.game('dimir-house-guard');self.fx(self.other,UntilEndOfTurn('source',(SetColors(('B',)),)),actor='B')
        view=CombatView(self.kernel);self.assertTrue(view.can_block(view.card(self.other),view.card(self.source)))

    def test_dimir_regeneration_reuses_same_shield_lifecycle(self):
        self.game('dimir-house-guard');self.activate('regenerate',sacrifice=self.body);self.top()
        self.fx(self.source,Destroy('source'));self.assertEqual(Zone.BATTLEFIELD,self.zone(self.source));self.assertTrue(self.state.get(self.source).tapped)

    def test_dimir_sacrificing_itself_creates_no_shield(self):
        self.game('dimir-house-guard');self.activate('regenerate',sacrifice=self.source);self.top()
        self.assertEqual(Zone.GRAVEYARD,self.zone(self.source));self.assertFalse(self.kernel.regeneration_shields)

    def test_dimir_transmute_pays_discard_then_searches_matching_mana_value(self):
        self.game('dimir-house-guard',zone=Zone.HAND);self.activate('transmute',mana='CBB')
        self.assertEqual(Zone.GRAVEYARD,self.zone(self.source));self.top()
        q=self.kernel.pending_choice;self.assertEqual('library_search',q.kind)
        self.assertTrue(all(self.kernel.effective(o.ref).mana_value==4 for o in q.options))
        chosen=q.options[0].ref;self.answer(indexes=[0])
        self.assertEqual(Zone.HAND,self.zone(chosen));self.assertTrue(any(e['kind']=='library_shuffled' for e in self.kernel.semantic_events))

    def test_dimir_transmute_may_fail_to_find_and_still_shuffles(self):
        self.game('dimir-house-guard',zone=Zone.HAND);self.activate('transmute',mana='CBB');self.top();self.answer(indexes=[])
        self.assertTrue(any(e['kind']=='library_shuffled' for e in self.kernel.semantic_events))
        self.assertEqual(Zone.GRAVEYARD,self.zone(self.source))

    def test_dimir_transmute_has_hand_and_sorcery_restrictions(self):
        self.game('dimir-house-guard')
        with self.assertRaises(RulesViolation):self.kernel.quote_activation(self.ident(),'A',self.source,'transmute')
        self.game('dimir-house-guard',zone=Zone.HAND);self.kernel.open_window_for_scenario('B',priority_actor='A')
        with self.assertRaises(RulesViolation):self.kernel.quote_activation(self.ident(),'A',self.source,'transmute')

    def test_dimir_transmute_counter_keeps_discard_but_prevents_search(self):
        self.game('dimir-house-guard',zone=Zone.HAND);self.activate('transmute',mana='CBB')
        self.response('g-stifle');self.top();self.assertIsNone(self.kernel.pending_choice)
        self.assertFalse(any(e['kind']=='library_shuffled' for e in self.kernel.semantic_events))

    def test_dimir_transmute_search_privacy_and_checkpoint(self):
        self.game('dimir-house-guard',zone=Zone.HAND);self.activate('transmute',mana='CBB');self.top()
        self.assertIn('library_search',RulesActorAdapter(self.kernel).packet('A'))
        self.assertNotIn('library_search',RulesActorAdapter(self.kernel).packet('B'))
        self.restore();self.answer(indexes=[0])

    def test_snack_normal_cast_after_attacking_still_triggers_raid(self):
        self.game('midnight-snack',zone=Zone.HAND);self.complete_unblocked((self.body,))
        while self.kernel.phase!='postcombat_main':self.round()
        self.cast(mana='CCB');self.top()
        while self.kernel.phase!='end_step':self.round()
        self.top();self.assertEqual(1,len(self.tokens('Food')))

    def test_snack_no_attack_means_no_food(self):
        self.game('midnight-snack');self.step('end_step')
        self.assertFalse(self.kernel.stack);self.assertFalse(self.tokens('Food'))

    def test_snack_raid_remembers_departed_attacker(self):
        self.game('midnight-snack');self.complete_unblocked((self.body,))
        self.fx(self.body,Move('source',Zone.EXILE))
        while self.kernel.phase!='end_step':self.round()
        self.top();self.assertEqual(1,len(self.tokens('Food')))

    def test_snack_raid_resets_on_the_next_turn(self):
        self.game('midnight-snack');self.complete_unblocked((self.body,))
        self.state.start_turn('B');self.assertNotIn('A',self.kernel._history_players('attacked'))
        self.assertFalse(self.kernel._condition_holds(TurnHistoryCondition('attacked'),self.state.get(self.source)))

    def test_snack_food_has_full_mana_tap_sacrifice_life_ability(self):
        self.game('midnight-snack');self.complete_unblocked((self.body,))
        while self.kernel.phase!='end_step':self.round()
        self.top();food=self.tokens('Food')[0]
        self.activate('consume',food.ref,mana='CC');self.top()
        self.assertEqual(43,self.state.life('A'));self.assertEqual(3,self.state.life_gained_this_turn('A'))
        self.assertFalse(self.tokens('Food'))

    def test_snack_counts_actual_gain_not_net_life_change(self):
        self.game('midnight-snack');self.fx(self.source,GainLife(6),LoseLife('controller',7))
        self.activate('life-drain',mana='CCB',targets=(PlayerRef('B'),));self.top()
        self.assertEqual(39,self.state.life('A'));self.assertEqual(34,self.state.life('B'))

    def test_snack_counts_gain_added_after_activation(self):
        self.game('midnight-snack');self.activate('life-drain',mana='CCB',targets=(PlayerRef('B'),))
        self.response('g-gain-4',actor='A');self.top();self.top()
        self.assertEqual(36,self.state.life('B'));self.assertEqual(Zone.GRAVEYARD,self.zone(self.source))

    def test_snack_zero_life_gain_is_zero_loss(self):
        self.game('midnight-snack');self.activate('life-drain',mana='CCB',targets=(PlayerRef('B'),));self.top()
        self.assertEqual(40,self.state.life('B'))

    def test_snack_lifelink_and_replacement_gains_enter_same_ledger(self):
        bonus=CardProgram('g-bonus','Bonus',('Enchantment',),life_gain_replacements=(LifeGainReplacement('extra',1),))
        self.game('midnight-snack',extra=(bonus,));self.add('g-bonus')
        self.fx(self.body,UntilEndOfTurn('source',(AddKeywords(('lifelink',)),)))
        self.kernel._deal_damage(((self.state.get(self.body),'B',2),),combat=True)
        self.assertEqual(3,self.state.life_gained_this_turn('A'))
        self.activate('life-drain',mana='CCB',targets=(PlayerRef('B'),));self.top();self.assertEqual(35,self.state.life('B'))

    def test_snack_targets_only_opponents_and_bad_payment_is_atomic(self):
        self.game('midnight-snack')
        with self.assertRaises(RulesViolation):self.kernel.quote_activation(self.ident(),'A',self.source,'life-drain',(PlayerRef('A'),))
        quote=self.kernel.quote_activation(self.ident(),'A',self.source,'life-drain',(PlayerRef('B'),));before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,Payment())
        self.assertEqual(before,self.kernel.snapshot())

    def test_restart_normal_cost_without_freerunning(self):
        self.game('restart-sequence',zone=Zone.HAND)
        with self.assertRaises(RulesViolation):self.kernel.quote_cast(self.ident(),'A',self.source,(self.own_dead,),alternative_id='freerunning')
        self.cast(mana='CCCB',targets=(self.own_dead,));self.top();self.assertEqual(Zone.BATTLEFIELD,self.zone(self.own_dead))

    def test_restart_freerunning_after_actual_assassin_combat(self):
        self.game('restart-sequence',zone=Zone.HAND);assassin=self.add('g-assassin')
        self.complete_unblocked((assassin,))
        while self.kernel.phase!='postcombat_main':self.round()
        self.cast(mana='CB',targets=(self.own_dead,),alternative='freerunning');self.top()
        self.assertEqual(Zone.BATTLEFIELD,self.zone(self.own_dead));self.assertEqual((),self.state.mana_pool('A'))

    def test_restart_commander_damage_qualifies_even_without_assassin_type(self):
        self.game('restart-sequence',zone=Zone.HAND);commander=self.add('g-body',commander=True)
        self.kernel._deal_damage(((self.state.get(commander),'B',1),),combat=True)
        self.cast(mana='CB',targets=(self.own_dead,),alternative='freerunning');self.top()
        self.assertEqual(Zone.BATTLEFIELD,self.zone(self.own_dead))

    def test_restart_noncombat_or_creature_damage_does_not_qualify(self):
        self.game('restart-sequence',zone=Zone.HAND);assassin=self.add('g-assassin')
        self.kernel._deal_damage(((self.state.get(assassin),'B',1),))
        self.kernel._deal_damage(((self.state.get(assassin),self.other,1),),combat=True)
        self.assertFalse(self.kernel._history_players('freerunning'))

    def test_restart_zero_damage_does_not_qualify(self):
        self.game('restart-sequence',zone=Zone.HAND);assassin=self.add('g-assassin')
        self.kernel._deal_damage(((self.state.get(assassin),'B',0),),combat=True)
        self.assertFalse(self.kernel._history_players('freerunning'))

    def test_restart_remembers_source_controller_and_type_at_damage_time(self):
        self.game('restart-sequence',zone=Zone.HAND);assassin=self.add('g-assassin')
        self.kernel._deal_damage(((self.state.get(assassin),'B',1),),combat=True)
        self.fx(assassin,GainControl('source'),actor='B');self.fx(assassin,Move('source',Zone.EXILE))
        self.assertEqual(frozenset(('A',)),self.kernel._history_players('freerunning'))
        self.cast(mana='CB',targets=(self.own_dead,),alternative='freerunning');self.top()

    def test_restart_does_not_gain_qualification_from_damage_lifelink_changes(self):
        grant=CardProgram('g-grant','Grant',('Enchantment',),continuous=(ContinuousProgram('assassin-at-high-life',
            Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled'),(AddSubtypes('Creature',('Assassin',)),),condition=LifeCondition(minimum=41)),))
        self.game('restart-sequence',zone=Zone.HAND,extra=(grant,));self.add('g-grant')
        self.fx(self.body,UntilEndOfTurn('source',(AddKeywords(('lifelink',)),)))
        self.kernel._deal_damage(((self.state.get(self.body),'B',1),),combat=True)
        self.assertIn('Assassin',self.kernel.effective(self.body).subtypes)
        self.assertFalse(self.kernel._history_players('freerunning'))

    def test_restart_new_turn_clears_qualification_and_life_gain(self):
        self.game('restart-sequence',zone=Zone.HAND);assassin=self.add('g-assassin')
        self.kernel._deal_damage(((self.state.get(assassin),'B',1),),combat=True);self.state.gain_life('A',5)
        self.state.start_turn('B')
        self.assertFalse(self.kernel._history_players('freerunning'));self.assertEqual(0,self.state.life_gained_this_turn('A'))

    def test_restart_freerunning_still_obeys_sorcery_timing(self):
        self.game('restart-sequence',zone=Zone.HAND);assassin=self.add('g-assassin')
        self.kernel._deal_damage(((self.state.get(assassin),'B',1),),combat=True)
        self.kernel.open_window_for_scenario('B',priority_actor='A')
        with self.assertRaises(RulesViolation):self.kernel.quote_cast(self.ident(),'A',self.source,(self.own_dead,),alternative_id='freerunning')

    def test_restart_freerunning_is_public_and_survives_actor_replay(self):
        self.game('restart-sequence',zone=Zone.HAND);assassin=self.add('g-assassin')
        self.kernel._deal_damage(((self.state.get(assassin),'B',1),),combat=True)
        self.state.add_mana('A',tuple('CB'));adapter=RulesActorAdapter(self.kernel)
        self.assertEqual(['A'],adapter.packet('B')['turn_history']['freerunning'])
        adapter.submit('A',{'kind':'cast','action_id':'restart-replay','revision':self.kernel.revision,
            'source':self.source.to_json(),'targets':[self.own_dead.to_json()],'x_value':0,'alternative_id':'freerunning',
            'payment':{'mana':{'C':1,'B':1},'taps':[]}})
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot());self.restore()

    def test_jyoti_no_command_casts_creates_no_dryads(self):
        self.game('jyoti-moag-ancient',zone=Zone.HAND);self.cast(mana='CCGU');self.top();self.top()
        self.assertFalse(self.tokens('Forest Dryad'));self.assertEqual(Zone.BATTLEFIELD,self.zone(self.source))

    def test_jyoti_own_command_cast_counts_itself(self):
        self.game('jyoti-moag-ancient',zone=Zone.HAND)
        commander=self.add(self.cards['jyoti-moag-ancient'].definition_id,'A',Zone.COMMAND,commander=True)
        self.cast(commander,mana='CCGU');self.top();self.top()
        self.assertEqual(1,self.state.command_casts('A'));self.assertEqual(1,len(self.tokens('Forest Dryad')))

    def test_jyoti_counts_countered_commander_casts(self):
        self.game('jyoti-moag-ancient',zone=Zone.HAND)
        commander=self.add('g-body','A',Zone.COMMAND,commander=True);self.cast(commander)
        self.response('g-counter',(self.state.current(commander.card_id),));self.top()
        if self.kernel.pending_choice:self.answer('stay')
        self.cast(mana='CCGU');self.top();self.top()
        self.assertEqual(1,len(self.tokens('Forest Dryad')))

    def test_jyoti_counts_each_of_multiple_commanders(self):
        self.game('jyoti-moag-ancient',zone=Zone.HAND)
        for _ in range(2):
            commander=self.add('g-body','A',Zone.COMMAND,commander=True);self.cast(commander);self.top()
        self.cast(mana='CCGU');self.top();self.top()
        self.assertEqual(2,len(self.tokens('Forest Dryad')));self.assertEqual(2,self.state.command_casts('A'))

    def test_jyoti_commanders_cast_from_hand_do_not_count(self):
        self.game('jyoti-moag-ancient',zone=Zone.HAND)
        commander=self.add('g-body','A',Zone.HAND,commander=True);self.cast(commander);self.top()
        self.cast(mana='CCGU');self.top();self.top()
        self.assertFalse(self.tokens('Forest Dryad'))

    def test_jyoti_tokens_have_printed_types_and_intrinsic_forest_mana(self):
        self.game('jyoti-moag-ancient',zone=Zone.HAND);self.state.record_command_cast('A')
        self.cast(mana='CCGU');self.top();self.top();dryad=self.tokens('Forest Dryad')[0]
        view=self.kernel.effective(dryad.ref)
        self.assertEqual((1,1),(view.power,view.toughness));self.assertEqual(frozenset(('Land','Creature')),view.types)
        self.assertTrue({'Forest','Dryad'}<=view.subtypes);self.assertEqual(frozenset(('G',)),view.colors)
        with self.assertRaises(RulesViolation):self.kernel.quote_activation(self.ident(),'A',dryad.ref,'intrinsic-land:Forest')
        self.state.start_turn('A');self.kernel.open_window_for_scenario('A')
        self.activate('intrinsic-land:Forest',dryad.ref)
        self.assertEqual((('G',1),),self.state.mana_pool('A'))

    def test_jyoti_boosts_only_own_land_creatures_at_each_combat(self):
        self.game('jyoti-moag-ancient');land=self.add('g-dryad');other_land=self.add('g-dryad','B')
        self.step('begin_combat','B');self.top()
        self.assertEqual((4,5),(self.kernel.effective(land).power,self.kernel.effective(land).toughness))
        self.assertEqual(2,self.kernel.effective(self.body).power);self.assertEqual(2,self.kernel.effective(other_land).power)

    def test_jyoti_uses_resolution_power_and_freezes_each_grant(self):
        self.game('jyoti-moag-ancient');land=self.add('g-dryad');self.step('begin_combat')
        self.response('g-pump',(self.source,),actor='A');self.top();self.top()
        self.assertEqual(7,self.kernel.effective(land).power)
        self.fx(self.source,UntilEndOfTurn('source',(ModifyPT(2,2),)))
        self.assertEqual(7,self.kernel.effective(land).power)

    def test_jyoti_departed_source_uses_last_known_power(self):
        self.game('jyoti-moag-ancient');land=self.add('g-dryad')
        self.fx(self.source,UntilEndOfTurn('source',(ModifyPT(3,3),)))
        self.step('begin_combat');self.response(targets=(self.source,));self.top();self.top()
        self.assertEqual(7,self.kernel.effective(land).power)

    def test_jyoti_negative_power_uses_zero_bonus_including_last_known_power(self):
        # CR 107.1b: +X/+X uses zero for a negative calculated X.
        for departed in (False,True):
            with self.subTest(departed=departed):
                self.game('jyoti-moag-ancient');land=self.add('g-dryad')
                self.fx(self.source,UntilEndOfTurn('source',(ModifyPT(-3,0),)))
                self.assertEqual(-1,self.kernel.effective(self.source).power)
                self.step('begin_combat')
                if departed:
                    self.response(targets=(self.source,));self.top()
                self.top()
                self.assertEqual((2,3),(self.kernel.effective(land).power,self.kernel.effective(land).toughness))

    def test_jyoti_land_creatures_entering_later_do_not_receive_old_grant(self):
        self.game('jyoti-moag-ancient');land=self.add('g-dryad');self.step('begin_combat');self.top()
        later=self.add('g-dryad');self.assertEqual(4,self.kernel.effective(land).power);self.assertEqual(2,self.kernel.effective(later).power)
        self.kernel._finish_cleanup_actions();self.assertEqual(2,self.kernel.effective(land).power)

    def test_jyoti_trigger_controller_survives_source_control_change(self):
        self.game('jyoti-moag-ancient');land=self.add('g-dryad');self.step('begin_combat')
        self.response('g-control',(self.source,),actor='B');self.top();self.top()
        self.assertEqual(4,self.kernel.effective(land).power);self.assertEqual('B',self.state.get(self.source).controller)

    def test_guard_checkpoint_versions_reject_legacy_state_and_kernel(self):
        self.game('fanatical-devotion');self.shield();checkpoint=self.kernel.snapshot()
        self.assertEqual(121,checkpoint['schema']);self.assertEqual(14,checkpoint['state']['schema'])
        legacy=json.loads(json.dumps(checkpoint));legacy['schema']=120
        with self.assertRaises(RulesViolation):RulesKernel.restore(legacy,self.programs)
        legacy=json.loads(json.dumps(checkpoint));legacy['state']['schema']=13
        with self.assertRaises(RulesViolation):RulesKernel.restore(legacy,self.programs)
        self.restore()

    def test_guard_checkpoint_rejects_malformed_history_and_shields(self):
        self.game('fanatical-devotion')
        for key,value in (('turn_history',{'turn':0,'attacked':['E'],'freerunning':[]}),
                          ('upkeep_history',{'A':-1}),
                          ('regeneration_shields',{'bad':{'card_id':'x','incarnation':-1}})):
            checkpoint=self.kernel.snapshot();checkpoint[key]=value
            with self.subTest(key=key),self.assertRaises(RulesViolation):RulesKernel.restore(checkpoint,self.programs)

    def test_compiler_rejects_unbound_guards_player_targets_and_history_static_effects(self):
        bad=(
            CardProgram('bad','Bad',('Sorcery',),spell_effects=(Regenerate('missing'),)),
            CardProgram('bad','Bad',('Sorcery',),spell_targets=TargetSpec(players='opponents'),spell_effects=(ChooseProtection('target'),)),
            CardProgram('bad','Bad',('Sorcery',),spell_targets=TargetSpec(players='opponents'),spell_effects=(Regenerate('target'),)),
            CardProgram('bad','Bad',('Creature',),power=1,toughness=1,keywords=('protection_everything',)),
            CardProgram('bad','Bad',('Enchantment',),continuous=(ContinuousProgram('bad',Selector(Zone.BATTLEFIELD),(ModifyPT(1,1),),condition=TurnHistoryCondition('attacked')),)),
            CardProgram('bad','Bad',('Sorcery',),spell_effects=(GainLife(PlayerStatistic('secret')),)),
            CardProgram('bad','Bad',('Creature',),power=1,toughness=1,spell_effects=(UntilEndOfTurn('source',(ModifyPT(SourceStat('power',True),0),)),)),
            CardProgram('bad','Bad',('Enchantment',),abilities=(EchoAbility('bad',EventPattern('step_began',step='upkeep'),()),)),
        )
        for program in bad:
            with self.subTest(program=program),self.assertRaises(RulesViolation):validate(program)

    def test_new_public_facts_do_not_expose_opponents_hand(self):
        self.game('midnight-snack');secret=self.add('g-black','B',Zone.HAND);self.state.gain_life('B',4)
        packet=RulesActorAdapter(self.kernel).packet('A')
        self.assertEqual(4,packet['life_gained_this_turn']['B'])
        self.assertNotIn(secret.card_id,json.dumps(packet))
        self.restore()

    def test_implementation_identity_includes_guard_and_phasing_interpreters(self):
        from edh_gauntlet.rules_identity import IMPLEMENTATION_MANIFEST
        self.assertIn('rules_guard.py',IMPLEMENTATION_MANIFEST['modules'])
        self.assertIn('rules_phasing.py',IMPLEMENTATION_MANIFEST['modules'])


if __name__=='__main__':unittest.main()

