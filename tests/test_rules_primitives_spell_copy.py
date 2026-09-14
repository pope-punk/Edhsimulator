"""Hosted checks for demonstrate, replicate and explicit special-mana spending."""
import json
import unittest
from collections import Counter as Counts
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,RulesObject,RulesViolation,Zone,ZoneMove,ObjectRef,PlayerRef,ResourcePayment
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment,PreparedAction
from edh_gauntlet.rules_choices import ChoiceRequest,CopyTargetRequest
from edh_gauntlet.rules_actor import project_actor
from edh_gauntlet.rules_bundle import load_reviewed,digest,source_facts
from edh_gauntlet.catalog import load_catalog

CARDS=('replication-technique','changing-loyalty','sunken-palace','delighted-halfling')


class SpellCopyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        reviewed=load_reviewed(cls.root)
        drafts=json.loads((cls.root/'data/rules/draft_cards.json').read_text(encoding='utf-8'))['drafts']
        cls.rows={r['card_id']:r for r in drafts if r['card_id'] in CARDS}
        cls.cards={key:validate(decode(row['program'])) for key,row in cls.rows.items()}
        cls.base=tuple(r['program'] for r in reviewed.values())+tuple(cls.cards.values())
        cls.prefix='draft:'

    def game(self,extra=()):
        body=CardProgram('cp-body','Body',('Creature',),power=2,toughness=3,cast=CastSpec(CostSpec(ManaCost(1))))
        legendary=replace(body,definition_id='cp-legend',name='Legend',supertypes=('Legendary',))
        counter=CardProgram('cp-counter','Counter',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.STACK)),spell_effects=(Counter('target'),))
        draw=CardProgram('cp-draw','Draw',('Instant',),cast=CastSpec(CostSpec(ManaCost(1)),timing='instant'),spell_effects=(Draw(1),))
        machine=CardProgram('cp-machine','Machine',('Artifact',),activated=(
            ActivatedProgram('draw',CostSpec(ManaCost(1)),(Draw(1),)),))
        self.programs=self.base+(body,legendary,counter,draw,machine)+extra
        self.state=RulesState(('A','B','C','D'),seed=31);self.kernel=RulesKernel(self.state,self.programs);self.serial=0
        self.palace=self.add(self.cards['sunken-palace'].definition_id)
        self.halfling=self.add(self.cards['delighted-halfling'].definition_id)
        self.body=self.add();self.other=self.add();self.enemy=self.add(actor='B')
        for player in self.state.players:
            for _ in range(10):self.add('catalog:forest',player,Zone.LIBRARY)
        self.state.start_turn('A');self.kernel.open_window_for_scenario('A')

    def add(self,definition='cp-body',actor='A',zone=Zone.BATTLEFIELD,**kw):
        self.serial+=1
        return self.state.add_card('cp-object-'+str(self.serial),definition,actor,zone,**kw)

    def hand(self,key):return self.add(self.cards[key].definition_id,zone=Zone.HAND)
    def current(self,ref):return self.state.get(self.state.current(ref.card_id))
    def events(self,kind):return [row for row in self.kernel.semantic_events if row['kind']==kind]
    def tags(self):return tuple(self.state.mana_tags('A'))

    def payment(self,normal='',tags=(),**kw):
        self.state.add_mana('A',normal)
        symbols=normal+''.join(self.state.mana_tags('A')[unit]['symbol'] for unit in tags)
        return Payment(tuple(sorted(Counts(symbols).items())),tagged_mana=tuple(tags),**kw)

    def cast(self,ref,normal='',targets=(),tags=(),**kw):
        if self.kernel.priority is None and not self.kernel.stack:self.kernel.open_window_for_scenario('A')
        while self.kernel.priority!='A':self.kernel.pass_priority(self.kernel.priority)
        payment=self.payment(normal,tags)
        quote=self.kernel.quote_cast('cp-cast-'+str(len(self.kernel.action_receipts)),'A',ref,targets,**kw)
        self.kernel.commit_action(quote,payment)
        return next((f for f in self.kernel.stack if f['spell'] and f['source']['ref']['card_id']==ref.card_id),None)

    def activate(self,ref,ability,normal='',tags=(),**kw):
        payment=self.payment(normal,tags,**kw)
        quote=self.kernel.quote_activation('cp-activate-'+str(len(self.kernel.action_receipts)),'A',ref,ability)
        self.kernel.commit_action(quote,payment)

    def answer(self,indexes):
        request=self.kernel.pending_choice
        self.assertIsNotNone(request)
        return self.kernel.answer(request.request_id,request.actor,indexes)

    def choose(self,key):
        request=self.kernel.pending_choice
        return self.answer([next(i for i,o in enumerate(request.options) if o.key==key)])

    def copy_targets(self,*refs):
        request=self.kernel.pending_choice;self.assertEqual('copy_targets',request.kind)
        indexes=[]
        for slot,ref in enumerate(refs):
            indexes.append(next(i for i,o in enumerate(request.options) if o.group==str(slot)
                and (o.key.endswith(':keep') if ref is None else o.ref==ref or isinstance(ref,PlayerRef) and o.player==ref.player)))
        return self.answer(indexes)

    def default(self):
        q=self.kernel.pending_choice
        if q.kind=='copy_targets':return self.answer([i for i,o in enumerate(q.options) if o.key.endswith(':keep')])
        if q.kind=='trigger_order':return self.answer(list(range(len(q.options))))
        return self.answer(list(range(q.minimum)))

    def until_choice(self):
        for _ in range(120):
            if self.kernel.pending_choice:return self.kernel.pending_choice
            if not self.kernel.stack:return None
            self.kernel.pass_priority(self.kernel.priority)
        self.fail('No choice boundary')

    def drain(self):
        for _ in range(500):
            if self.kernel.pending_choice:self.default()
            elif self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
            else:return
        self.fail('Resolution did not finish')

    def top(self):
        identity=self.kernel.stack[-1]['id']
        for _ in range(40):
            if self.kernel.pending_choice or not any(f['id']==identity for f in self.kernel.stack):return
            self.kernel.pass_priority(self.kernel.priority)
        self.fail('Top frame did not resolve')

    def restore(self):
        value=self.kernel.snapshot();self.kernel=RulesKernel.restore(value,self.programs);self.state=self.kernel.state
        self.assertEqual(value,self.kernel.snapshot())

    def tagged(self,rider='copy',symbols='U'):
        source=self.halfling if rider=='legendary' else self.palace
        self.state.add_special_mana('A',tuple(symbols),rider,self.state.get(source))
        return self.tags()

    def palace_mana(self):
        refs=tuple(self.add(zone=Zone.GRAVEYARD) for _ in range(7))
        self.activate(self.palace,'copy-mana','CU',zone_costs=(('exile-seven',refs),))
        self.choose('U')
        return refs

    def test_complete_printed_faces_and_program_serialization(self):
        catalog={c.card_id:c for c in load_catalog(self.root/'data/catalog/cards.json')}
        self.assertEqual(set(CARDS),set(self.cards))
        for key,program in self.cards.items():
            self.assertEqual(self.prefix+key,program.definition_id)
            self.assertEqual(program,validate(decode(encode(program))))
            row=self.rows[key];actual=row.get('source_facts_sha256') or digest(row['source_facts'])
            self.assertEqual(digest(source_facts(catalog[key])),actual)

    def test_compiler_rejects_unbound_copy_instruction(self):
        with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Instant',),spell_effects=(CopyCaptured(),)))

    def test_compiler_rejects_special_mana_outside_battlefield_mana_activation(self):
        for program in (CardProgram('bad','Bad',('Instant',),spell_effects=(SpecialMana(('U',),'copy'),)),
                CardProgram('bad','Bad',('Artifact',),activated=(ActivatedProgram('bad',CostSpec(),(SpecialMana(('U',),'bad'),),mana_ability=True),))):
            with self.subTest(program=program):
                with self.assertRaises(RulesViolation):validate(program)

    def test_compiler_rejects_invalid_replicate_cost(self):
        original=self.cards['changing-loyalty']
        for mana in (None,ManaCost(),ManaCost(-1),ManaCost(1,x_symbols=1)):
            with self.subTest(mana=mana):
                with self.assertRaises(RulesViolation):validate(replace(original,cast=replace(original.cast,replicate_cost=mana)))

    def test_demonstrate_decline_creates_only_original_token(self):
        self.game();self.cast(self.hand('replication-technique'),'CCCCU',(self.body,))
        self.until_choice();self.assertEqual('demonstrate',self.kernel.pending_choice.kind)
        self.choose('no');self.drain()
        self.assertEqual(5,len(self.state.objects(Zone.BATTLEFIELD,controller='A')))
        self.assertEqual([],self.events('stack_object_copied'))

    def test_demonstrate_opponent_sees_own_copy_and_resolves_first(self):
        self.game();self.cast(self.hand('replication-technique'),'CCCCU',(self.body,))
        self.until_choice();self.choose('yes');self.copy_targets(self.other)
        self.assertEqual('demonstrate_opponent',self.kernel.pending_choice.kind)
        self.choose('B')
        self.assertEqual('B',self.kernel.pending_choice.actor)
        self.assertEqual(self.other.to_json(),self.kernel.stack[-1]['targets'][0])
        self.copy_targets(self.enemy)
        self.assertEqual(['A','A','B'],[f['controller'] for f in self.kernel.stack])
        self.drain();self.assertEqual(2,len(self.state.objects(Zone.BATTLEFIELD,controller='B')))
        self.assertEqual(1,len(self.events('spell_cast')))

    def test_demonstrate_checkpoint_after_first_copy_does_not_duplicate(self):
        self.game();self.cast(self.hand('replication-technique'),'CCCCU',(self.body,))
        self.until_choice();self.choose('yes');self.copy_targets(None);self.restore()
        self.choose('B');self.restore();self.copy_targets(self.enemy);self.drain()
        self.assertEqual(2,len(self.events('stack_object_copied')))

    def test_demonstrate_can_keep_illegal_original_target(self):
        self.game();self.cast(self.hand('replication-technique'),'CCCCU',(self.body,))
        self.until_choice();self.choose('yes');self.copy_targets(None);self.choose('B')
        self.copy_targets(None);self.drain()
        self.assertEqual(1,len(self.state.objects(Zone.BATTLEFIELD,controller='B')))
        self.assertEqual(2,len(self.events('stack_object_copied')))

    def test_demonstrate_original_can_be_countered_before_trigger(self):
        self.game();original=self.cast(self.hand('replication-technique'),'CCCCU',(self.body,))
        self.cast(self.add('cp-counter',zone=Zone.HAND),targets=(ObjectRef.from_json(original['source']['ref']),))
        self.top();self.until_choice();self.choose('yes');self.copy_targets(self.other);self.choose('B');self.copy_targets(self.enemy)
        self.drain();self.assertEqual(2,len(self.events('stack_object_copied')))
        self.assertEqual(2,len(self.events('spell_cast')))

    def test_replicate_zero_is_not_a_copy_trigger(self):
        self.game();ref=self.hand('changing-loyalty');self.cast(ref,'CB',(self.enemy,))
        self.assertEqual(1,len(self.kernel.stack));self.drain()
        self.assertEqual(self.enemy,self.current(ref).attached_to)

    def test_replicate_quote_adds_cost_before_reduction(self):
        self.game();ref=self.hand('changing-loyalty')
        quote=self.kernel.quote_cast('quote','A',ref,(self.enemy,),replicate=3)
        self.assertEqual(7,quote.cost.mana.generic);self.assertEqual(('B',),quote.cost.mana.symbols)
        self.assertEqual(quote,PreparedAction.from_json(quote.to_json()))

    def test_replicate_rejects_invalid_or_unrelated_declaration(self):
        self.game();ref=self.hand('changing-loyalty')
        for count in (-1,True,1.5):
            with self.subTest(count=count):
                with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',ref,(self.enemy,),replicate=count)
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',self.hand('replication-technique'),(self.body,),replicate=1)

    def test_replicate_underpayment_is_atomic(self):
        self.game();ref=self.hand('changing-loyalty');self.state.add_mana('A','CB')
        quote=self.kernel.quote_cast('bad','A',ref,(self.enemy,),replicate=2);before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,Payment((('B',1),('C',1))))
        self.assertEqual(before,self.kernel.snapshot())

    def test_changing_loyalty_flash_allows_opponent_turn(self):
        self.game();self.kernel.active='B';self.kernel.phase='end_step'
        self.cast(self.hand('changing-loyalty'),'CB',(self.enemy,));self.drain()
        self.assertEqual(1,len([o for o in self.state.objects(Zone.BATTLEFIELD) if o.attached_to==self.enemy]))

    def test_replicated_permanents_are_noncards_then_aura_tokens(self):
        self.game();self.cast(self.hand('changing-loyalty'),'CCCCCB',(self.enemy,),replicate=2)
        self.until_choice();self.copy_targets(self.body);self.copy_targets(self.other)
        objects=self.state.objects(Zone.STACK);copies=[o for o in objects if o.spell_copy]
        self.assertEqual(2,len(copies));self.assertTrue(all(not o.token and not o.commander for o in copies))
        self.restore();self.drain()
        auras=[o for o in self.state.objects(Zone.BATTLEFIELD) if o.token]
        self.assertEqual({self.body,self.other},{o.attached_to for o in auras})
        self.assertTrue(all(not o.spell_copy for o in auras))
        self.assertEqual([],self.events('tokens_created'))
        self.assertEqual(1,len(self.events('spell_cast')))

    def test_replicate_survives_countered_original(self):
        self.game();original=self.cast(self.hand('changing-loyalty'),'CCCB',(self.enemy,),replicate=1)
        self.cast(self.add('cp-counter',zone=Zone.HAND),targets=(ObjectRef.from_json(original['source']['ref']),))
        self.top();self.until_choice();self.copy_targets(self.body);self.drain()
        self.assertEqual(1,len([o for o in self.state.objects(Zone.BATTLEFIELD) if o.token and o.attached_to==self.body]))

    def test_countered_permanent_copy_ceases_without_becoming_token(self):
        self.game();self.cast(self.hand('changing-loyalty'),'CCCB',(self.enemy,),replicate=1)
        self.until_choice();self.copy_targets(self.body);copy=self.kernel.stack[-1]
        ref=ObjectRef.from_json(copy['source']['ref'])
        self.cast(self.add('cp-counter',zone=Zone.HAND),targets=(ref,));self.drain()
        self.assertNotIn(ref.card_id,{o.ref.card_id for o in self.state.objects()})
        self.assertEqual(1,len(self.events('spell_copy_ceased')))

    def test_aura_returns_dead_creature_under_its_controller(self):
        self.game();aura=self.hand('changing-loyalty');self.cast(aura,'CB',(self.enemy,));self.drain()
        self.kernel.execute_for_scenario(self.palace,'A',(SelectAll(Selector(Zone.BATTLEFIELD,relation='opponent_controlled'),(Destroy('selected'),)),))
        self.drain();self.assertEqual('A',self.current(self.enemy).controller)
        self.assertEqual(Zone.GRAVEYARD,self.current(aura).zone)

    def test_aura_and_creature_dying_simultaneously_retains_return(self):
        self.game();aura=self.hand('changing-loyalty');self.cast(aura,'CB',(self.enemy,));self.drain()
        self.kernel.execute_for_scenario(self.palace,'A',(SelectAll(Selector(Zone.BATTLEFIELD,any_types=('Creature','Enchantment')),(Destroy('selected'),)),))
        self.drain();self.assertEqual(Zone.BATTLEFIELD,self.current(self.enemy).zone)
        self.assertEqual('A',self.current(self.enemy).controller)

    def test_aura_exile_is_not_death(self):
        self.game();self.cast(self.hand('changing-loyalty'),'CB',(self.enemy,));self.drain()
        self.kernel.execute_for_scenario(self.palace,'A',(SelectAll(Selector(Zone.BATTLEFIELD,relation='opponent_controlled'),(Move('selected',Zone.EXILE),)),))
        self.drain();self.assertEqual(Zone.EXILE,self.current(self.enemy).zone)

    def test_aura_cannot_return_a_departed_token(self):
        self.game();token=self.add(actor='B',token=True);self.cast(self.hand('changing-loyalty'),'CB',(token,));self.drain()
        self.kernel.execute_for_scenario(self.palace,'A',(SelectAll(Selector(Zone.BATTLEFIELD,relation='opponent_controlled'),(Destroy('selected'),)),))
        self.drain();self.assertNotIn(token.card_id,{o.ref.card_id for o in self.state.objects()})

    def test_sunken_palace_enters_tapped(self):
        self.game();ref=self.add(self.cards['sunken-palace'].definition_id,zone=Zone.HAND)
        self.kernel.execute_for_scenario(ref,'A',(Move('source',Zone.BATTLEFIELD),))
        self.assertTrue(self.current(ref).tapped)

    def test_sunken_palace_basic_blue_is_unrestricted(self):
        self.game();self.activate(self.palace,'blue')
        self.assertEqual({'U':1},dict(self.state.mana_pool('A')));self.assertEqual((),self.tags())
        self.assertEqual([],self.kernel.stack)

    def test_sunken_palace_exiles_exact_seven_as_atomic_cost(self):
        self.game();refs=self.palace_mana()
        self.assertTrue(all(self.current(ref).zone==Zone.EXILE for ref in refs))
        self.assertTrue(self.current(self.palace).tapped);self.assertEqual(1,len(self.tags()))
        self.assertEqual({'U':1},dict(self.state.mana_pool('A')));self.restore()

    def test_sunken_palace_rejects_six_or_duplicate_exile_payment(self):
        for duplicate in (False,True):
            self.game();refs=tuple(self.add(zone=Zone.GRAVEYARD) for _ in range(6))
            payment=self.payment('CU',zone_costs=(('exile-seven',refs+(refs[0],) if duplicate else refs),))
            quote=self.kernel.quote_activation('bad','A',self.palace,'copy-mana');before=self.kernel.snapshot()
            with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,payment)
            self.assertEqual(before,self.kernel.snapshot())

    def test_sunken_palace_rejects_opponents_graveyard(self):
        self.game();refs=tuple(self.add(actor='B',zone=Zone.GRAVEYARD) for _ in range(7))
        payment=self.payment('CU',zone_costs=(('exile-seven',refs),))
        quote=self.kernel.quote_activation('bad','A',self.palace,'copy-mana');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,payment)
        self.assertEqual(before,self.kernel.snapshot())

    def test_paid_palace_mana_copies_spell_without_another_cast(self):
        self.game();self.palace_mana();self.cast(self.add('cp-draw',zone=Zone.HAND),tags=self.tags())
        self.drain();self.assertEqual(2,len(self.state.zone('A',Zone.HAND)))
        self.assertEqual(1,len(self.events('spell_cast')));self.assertEqual(1,len(self.events('stack_object_copied')))

    def test_paid_palace_mana_copies_activated_ability(self):
        self.game();tags=self.tagged();machine=self.add('cp-machine')
        self.activate(machine,'draw',tags=tags);self.drain()
        self.assertEqual(2,len(self.state.zone('A',Zone.HAND)));self.assertEqual(1,len(self.events('ability_activated')))
        self.assertFalse(self.events('stack_object_copied')[0]['spell'])

    def test_mana_ability_is_not_copied(self):
        producer=CardProgram('cp-producer','Producer',('Artifact',),activated=(
            ActivatedProgram('mana',CostSpec(ManaCost(1)),(AddMana(('G',)),),mana_ability=True),))
        self.game((producer,));tags=self.tagged();self.activate(self.add('cp-producer'),'mana',tags=tags);self.drain()
        self.assertEqual({'G':1},dict(self.state.mana_pool('A')))
        self.assertEqual([],self.events('stack_object_copied'));self.assertEqual(1,len(self.events('copy_not_created')))

    def test_palace_rider_survives_land_departure(self):
        self.game();tags=self.tagged()
        self.state.move((ZoneMove(self.palace,Zone.GRAVEYARD),),'fixture')
        self.cast(self.add('cp-draw',zone=Zone.HAND),tags=tags);self.restore();self.drain()
        self.assertEqual(2,len(self.state.zone('A',Zone.HAND)))

    def test_palace_copy_survives_original_counter(self):
        self.game();tags=self.tagged();original=self.cast(self.add('cp-draw',zone=Zone.HAND),tags=tags)
        self.cast(self.add('cp-counter',zone=Zone.HAND),targets=(ObjectRef.from_json(original['source']['ref']),))
        self.drain();self.assertEqual(1,len(self.state.zone('A',Zone.HAND)))

    def test_ordinary_mana_of_same_color_does_not_spend_tagged_unit(self):
        self.game();self.tagged();self.cast(self.add('cp-draw',zone=Zone.HAND),'U');self.drain()
        self.assertEqual(1,len(self.tags()));self.assertEqual([],self.events('stack_object_copied'))

    def test_tagged_unit_cannot_be_spent_by_color_alone(self):
        self.game();self.tagged();ref=self.add('cp-draw',zone=Zone.HAND)
        quote=self.kernel.quote_cast('bad','A',ref);before=self.kernel.snapshot()
        with self.assertRaisesRegex(RulesViolation,'explicitly'):self.kernel.commit_action(quote,Payment((('U',1),)))
        self.assertEqual(before,self.kernel.snapshot())

    def test_tagged_payment_rejects_duplicate_or_other_player_unit(self):
        self.game();tags=self.tagged()
        for units in ((tags[0],tags[0]),('unavailable',)):
            with self.subTest(units=units):
                with self.assertRaises(RulesViolation):self.state.tagged_payment('A',units)
        with self.assertRaises(RulesViolation):self.state.tagged_payment('B',tags)

    def test_pool_emptying_expires_special_mana(self):
        self.game();self.tagged();self.state.empty_mana_pools()
        self.assertEqual((),self.tags());self.assertEqual((),self.state.mana_pool('A'));self.restore()

    def test_doubled_palace_mana_has_one_delayed_trigger(self):
        doubler=CardProgram('cp-double','Double',('Enchantment',),tapped_mana_replacements=(TappedManaReplacement('double',2),))
        self.game((doubler,));self.add('cp-double');self.palace_mana();units=self.tags();self.assertEqual(2,len(units))
        self.cast(self.add('cp-draw',zone=Zone.HAND),tags=(units[0],));self.drain()
        self.assertEqual('spent_copy',self.state.mana_tags('A')[units[1]]['rider'])
        self.cast(self.add('cp-draw',zone=Zone.HAND),tags=(units[1],));self.drain()
        self.assertEqual(1,len(self.events('stack_object_copied')))

    def test_separate_palace_mana_batches_each_copy(self):
        custom=CardProgram('cp-two','Two',('Instant',),cast=CastSpec(CostSpec(ManaCost(2)),timing='instant'),spell_effects=(Draw(1),))
        self.game((custom,));self.tagged();self.tagged()
        self.cast(self.add('cp-two',zone=Zone.HAND),tags=self.tags());self.drain()
        self.assertEqual(3,len(self.state.zone('A',Zone.HAND)));self.assertEqual(2,len(self.events('stack_object_copied')))

    def test_halfling_colorless_is_unrestricted(self):
        self.game();self.activate(self.halfling,'colorless')
        self.assertEqual({'C':1},dict(self.state.mana_pool('A')));self.assertEqual((),self.tags())

    def test_halfling_offers_all_five_colors_and_requires_readiness(self):
        self.game();self.activate(self.halfling,'legendary-mana')
        self.assertEqual(list('WUBRG'),[o.key for o in self.kernel.pending_choice.options]);self.choose('G')
        self.assertEqual('G',self.state.mana_tags('A')[self.tags()[0]]['symbol'])
        fresh=self.add(self.cards['delighted-halfling'].definition_id)
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('sick','A',fresh,'legendary-mana')

    def test_halfling_rejects_nonlegendary_spell_atomically(self):
        self.game();tags=self.tagged('legendary','G');ref=self.add(zone=Zone.HAND)
        quote=self.kernel.quote_cast('bad','A',ref);before=self.kernel.snapshot()
        with self.assertRaisesRegex(RulesViolation,'legendary'):self.kernel.commit_action(quote,Payment((('G',1),),tagged_mana=tags))
        self.assertEqual(before,self.kernel.snapshot())

    def test_halfling_rejects_activated_ability_payment(self):
        self.game();tags=self.tagged('legendary','G');ref=self.add('cp-machine')
        quote=self.kernel.quote_activation('bad','A',ref,'draw');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.commit_action(quote,Payment((('G',1),),tagged_mana=tags))
        self.assertEqual(before,self.kernel.snapshot())

    def test_halfling_paid_legendary_spell_cannot_be_countered(self):
        self.game();tags=self.tagged('legendary','G');ref=self.add('cp-legend',zone=Zone.HAND)
        original=self.cast(ref,tags=tags);self.assertTrue(original['cannot_be_countered']);self.restore()
        self.cast(self.add('cp-counter',zone=Zone.HAND),targets=(self.current(ref).ref,));self.drain()
        self.assertEqual(Zone.BATTLEFIELD,self.current(ref).zone);self.assertEqual([],self.events('spells_countered'))

    def test_halfling_immunity_survives_source_departure(self):
        self.game();tags=self.tagged('legendary','G');self.state.move((ZoneMove(self.halfling,Zone.GRAVEYARD),),'fixture')
        ref=self.add('cp-legend',zone=Zone.HAND);self.cast(ref,tags=tags)
        self.cast(self.add('cp-counter',zone=Zone.HAND),targets=(self.current(ref).ref,));self.drain()
        self.assertEqual(Zone.BATTLEFIELD,self.current(ref).zone)

    def test_copy_does_not_inherit_halfling_counter_immunity(self):
        legend=CardProgram('cp-expensive','Expensive',('Creature',),supertypes=('Legendary',),power=1,toughness=1,cast=CastSpec(CostSpec(ManaCost(2))))
        self.game((legend,));self.tagged('legendary','G');self.tagged('copy','U')
        ref=self.add('cp-expensive',zone=Zone.HAND);original=self.cast(ref,tags=self.tags());self.top()
        copy=self.kernel.stack[-1];self.assertTrue(copy['copied']);self.assertNotIn('cannot_be_countered',copy)
        self.assertTrue(original['cannot_be_countered'])
        self.cast(self.add('cp-counter',zone=Zone.HAND),targets=(ObjectRef.from_json(copy['source']['ref']),));self.drain()
        self.assertEqual(Zone.BATTLEFIELD,self.current(ref).zone);self.assertEqual(1,len(self.events('spells_countered')))

    def test_halfling_can_pay_alternative_generic_cost(self):
        legend=CardProgram('cp-alt','Alternative',('Creature',),supertypes=('Legendary',),power=1,toughness=1,
            cast=CastSpec(CostSpec(ManaCost(4)),alternatives=(AlternativeCost('alternate',CostSpec(ManaCost(1))),)))
        self.game((legend,));tags=self.tagged('legendary','G')
        original=self.cast(self.add('cp-alt',zone=Zone.HAND),tags=tags,alternative_id='alternate')
        self.assertTrue(original['cannot_be_countered'])

    def test_halfling_can_pay_additional_kicker_cost(self):
        legend=CardProgram('cp-kick','Kicker',('Creature',),supertypes=('Legendary',),power=1,toughness=1,
            cast=KickerCast(CostSpec(),kicker=CostSpec(ManaCost(1))))
        self.game((legend,));tags=self.tagged('legendary','G')
        original=self.cast(self.add('cp-kick',zone=Zone.HAND),tags=tags,kicker=True)
        self.assertTrue(original['cannot_be_countered']);self.assertTrue(original['kicker'])

    def test_actor_sees_own_mana_unit_ids_without_other_private_state(self):
        self.game();units=self.tagged()
        own=project_actor(self.kernel,'A');other=project_actor(self.kernel,'B')
        self.assertEqual(set(units),set(next(p for p in own['players'] if p['seat']=='A')['tagged_mana']))
        self.assertNotIn('tagged_mana',next(p for p in other['players'] if p['seat']=='A'))
        self.assertNotIn('mana_tags',other)

    def test_tagged_payment_roundtrip_and_stale_snapshot_rejection(self):
        self.game();tags=self.tagged();payment=Payment((('U',1),),tagged_mana=tags)
        self.assertEqual(payment,Payment.from_json(payment.to_json()))
        value=self.state.snapshot();value['mana']['A']={}
        with self.assertRaises(RulesViolation):RulesState.restore(value)

    def test_resolution_payment_spends_palace_mana_without_copying(self):
        self.game();tags=self.tagged()
        self.kernel.execute_for_scenario(self.palace,'A',(PayMana(ManaCost(1),(GainLife(1),)),))
        window=self.kernel.mana_payment
        self.kernel.pay_resolution_mana('resolve-pay','A',window['id'],Payment((('U',1),),tagged_mana=tags),revision=self.kernel.revision)
        self.assertEqual(41,self.state.life('A'));self.assertEqual([],self.events('stack_object_copied'))

    def test_resolution_payment_rejects_halfling_mana(self):
        self.game();tags=self.tagged('legendary','G')
        self.kernel.execute_for_scenario(self.palace,'A',(PayMana(ManaCost(1),(GainLife(1),)),))
        window=self.kernel.mana_payment;before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):
            self.kernel.pay_resolution_mana('bad','A',window['id'],Payment((('G',1),),tagged_mana=tags),revision=self.kernel.revision)
        self.assertEqual(before,self.kernel.snapshot())

    def test_target_assignment_allows_swaps_and_rejects_duplicates(self):
        from edh_gauntlet.rules_choices import Option
        a=ObjectRef('a',1);b=ObjectRef('b',1)
        options=(Option('0:keep','Keep',ref=a,group='0'),Option('0:b','B',ref=b,group='0'),
            Option('1:keep','Keep',ref=b,group='1'),Option('1:a','A',ref=a,group='1'))
        q=CopyTargetRequest('q','A','copy_targets','Targets',options,2,2,False,False,'revision',
            (('0',1,1),('1',1,1)),(None,)*4,(True,False,True,False))
        self.assertEqual((1,3),q.validate('A',[1,3]));self.assertEqual(q,ChoiceRequest.from_json(q.to_json()))
        with self.assertRaises(RulesViolation):q.validate('A',[0,3])
        with self.assertRaises(RulesViolation):q.validate('B',[0,2])

    def test_copy_preserves_x_and_modal_choice(self):
        modal=CardProgram('cp-modal','Modal',('Instant',),cast=CastSpec(CostSpec(ManaCost(x_symbols=1)),timing='instant'),
            modal=ModalSpec((SpellMode('draw',(Draw(ChosenX()),)),SpellMode('life',(GainLife(3),)))))
        self.game((modal,));tags=self.tagged()
        self.cast(self.add('cp-modal',zone=Zone.HAND),'C',tags=tags,x_value=2,mode_choices=(('draw',()),))
        self.top();copy=self.kernel.stack[-1]
        self.assertEqual(2,copy['chosen_x']);self.assertEqual('draw',copy['mode_groups'][0]['mode_id'])
        self.restore();self.drain();self.assertEqual(4,len(self.state.zone('A',Zone.HAND)));self.assertEqual(40,self.state.life('A'))

    def test_copy_preserves_division_when_targets_change(self):
        divided=CardProgram('cp-divided','Divided',('Instant',),cast=CastSpec(CostSpec(ManaCost(1)),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',)),1,2),
            spell_effects=(PlaceDividedCounters('+1/+1',3),))
        self.game((divided,));tags=self.tagged()
        self.cast(self.add('cp-divided',zone=Zone.HAND),targets=(self.body,self.other),tags=tags,
            counter_division=((self.body,1),(self.other,2)))
        self.until_choice();self.copy_targets(self.other,self.body);self.restore();self.drain()
        self.assertEqual(3,dict(self.current(self.body).counters)['+1/+1'])
        self.assertEqual(3,dict(self.current(self.other).counters)['+1/+1'])

    def test_copy_retains_opponent_controller_target_groups(self):
        spell=CardProgram('cp-groups','Groups',('Instant',),cast=CastSpec(CostSpec(ManaCost(1)),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',),relation='opponent_controlled'),
                minimum=1,maximum=2,group_by_controller=True),
            spell_effects=(AddCounters('target','+1/+1',1),))
        with self.assertRaises(RulesViolation):validate(replace(spell,spell_targets=replace(spell.spell_targets,maximum=None)))
        self.game((spell,));third=self.add(actor='C');fourth=self.add(actor='D');tags=self.tagged()
        self.cast(self.add('cp-groups',zone=Zone.HAND),targets=(self.enemy,third),tags=tags)
        self.until_choice();self.copy_targets(self.enemy,fourth);self.restore();self.drain()
        self.assertEqual(2,dict(self.current(self.enemy).counters)['+1/+1'])
        self.assertEqual(1,dict(self.current(third).counters)['+1/+1'])
        self.assertEqual(1,dict(self.current(fourth).counters)['+1/+1'])

    def test_copied_target_request_rejects_illegal_duplicate_without_accepting(self):
        spell=CardProgram('cp-targets','Targets',('Instant',),cast=CastSpec(CostSpec(ManaCost(1)),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD,types=('Creature',)),2,2),
            spell_effects=(AddCounters('target','+1/+1',1),))
        self.game((spell,));tags=self.tagged()
        self.cast(self.add('cp-targets',zone=Zone.HAND),targets=(self.body,self.other),tags=tags);self.until_choice()
        q=self.kernel.pending_choice;indexes=[next(i for i,o in enumerate(q.options) if o.ref==self.body and o.group==str(slot)) for slot in range(2)]
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.answer(indexes)
        self.assertEqual(before,self.kernel.snapshot());self.copy_targets(None,None);self.drain()

    def test_copy_retains_paid_sacrifice_facts(self):
        spell=CardProgram('cp-sac','Sacrifice draw',('Sorcery',),
            cast=CastSpec(CostSpec(ManaCost(1),zone_costs=(ZoneCost('sac','sacrifice',
                Selector(Zone.BATTLEFIELD,types=('Creature',),relation='controlled'),1),))),
            spell_effects=(Draw(PaidCostStat('sac','power')),))
        self.game((spell,));tags=self.tagged();ref=self.add('cp-sac',zone=Zone.HAND)
        payment=self.payment(tags=tags,zone_costs=(('sac',(self.body,)),))
        quote=self.kernel.quote_cast('sac-cast','A',ref);self.kernel.commit_action(quote,payment)
        self.restore();self.drain()
        self.assertEqual(4,len(self.state.zone('A',Zone.HAND)));self.assertEqual(Zone.GRAVEYARD,self.current(self.body).zone)

    def test_two_replicated_auras_do_not_return_one_creature_twice(self):
        self.game();self.cast(self.hand('changing-loyalty'),'CCCB',(self.enemy,),replicate=1)
        self.until_choice();self.copy_targets(None);self.drain()
        before=len(self.state.events)
        self.kernel.execute_for_scenario(self.palace,'A',(SelectAll(Selector(Zone.BATTLEFIELD,relation='opponent_controlled'),(Destroy('selected'),)),))
        self.drain()
        returned=[event for event in self.state.events[before:] if event.after.ref.card_id==self.enemy.card_id and event.after.zone==Zone.BATTLEFIELD]
        self.assertEqual(1,len(returned));self.assertEqual('A',self.current(self.enemy).controller)

    def test_replicate_trigger_can_be_countered_without_countering_original(self):
        stopper=CardProgram('cp-stop','Stop abilities',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_effects=(CounterAbilities('all'),))
        self.game((stopper,));aura=self.hand('changing-loyalty');self.cast(aura,'CCCB',(self.enemy,),replicate=1)
        self.cast(self.add('cp-stop',zone=Zone.HAND));self.drain()
        self.assertEqual(self.enemy,self.current(aura).attached_to);self.assertEqual([],self.events('stack_object_copied'))

    def test_new_target_hexproof_uses_copy_controller(self):
        protected=CardProgram('cp-protected','Protected',('Creature',),power=2,toughness=2,keywords=('hexproof',))
        self.game((protected,));protected_ref=self.add('cp-protected',actor='B')
        self.cast(self.hand('replication-technique'),'CCCCU',(self.body,))
        self.until_choice();self.choose('yes');self.copy_targets(None);self.choose('B')
        self.assertIn(protected_ref,{o.ref for o in self.kernel.pending_choice.options})
        self.copy_targets(protected_ref);self.drain()
        self.assertEqual(2,len([o for o in self.state.objects(Zone.BATTLEFIELD,controller='B') if self.kernel.definition(o).name=='Protected']))

    def test_actor_adapter_replays_replicate_and_target_choices(self):
        from edh_gauntlet.rules_adapter import RulesActorAdapter
        self.game();ref=self.hand('changing-loyalty');payment=self.payment('CCCB')
        adapter=RulesActorAdapter(self.kernel)
        adapter.submit('A',{'kind':'cast','revision':self.kernel.revision,'action_id':'adapter-replicate',
            'source':ref.to_json(),'targets':[self.enemy.to_json()],'x_value':0,'replicate':1,'payment':payment.to_json()})
        for _ in range(80):
            q=self.kernel.pending_choice
            if q:
                indexes=[i for i,o in enumerate(q.options) if o.key.endswith(':keep')] if q.kind=='copy_targets' else list(range(q.minimum))
                adapter.submit(q.actor,{'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':indexes})
            elif self.kernel.stack:adapter.submit(self.kernel.priority,{'kind':'pass','revision':self.kernel.revision})
            else:break
        else:self.fail('Adapter did not finish')
        archive=adapter.archive();replayed=RulesActorAdapter.replay(archive,self.programs)
        self.assertEqual(archive,replayed.archive());self.assertEqual(1,len(self.events('stack_object_copied')))

    def test_actor_adapter_replays_explicit_mana_payment(self):
        from edh_gauntlet.rules_adapter import RulesActorAdapter
        self.game();tags=self.tagged('legendary','G');ref=self.add('cp-legend',zone=Zone.HAND)
        adapter=RulesActorAdapter(self.kernel)
        adapter.submit('A',{'kind':'cast','revision':self.kernel.revision,'action_id':'adapter-legend',
            'source':ref.to_json(),'targets':[],'x_value':0,'payment':Payment((('G',1),),tagged_mana=tags).to_json()})
        self.assertTrue(self.kernel.stack[-1]['cannot_be_countered'])
        archive=adapter.archive();self.assertEqual(archive,RulesActorAdapter.replay(archive,self.programs).archive())
