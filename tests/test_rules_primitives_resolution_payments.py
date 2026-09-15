"""Resolution mana windows, source-bound enchantments and actual draw ordinals."""
import json
import unittest
from dataclasses import replace
from pathlib import Path

from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState, Zone, ZoneMove, RulesViolation, PlayerRef
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_choices import ManaPaymentBoundary
from edh_gauntlet.rules_actor import decision_for_actor
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed, source_facts, digest
from edh_gauntlet.catalog import load_catalog


CARDS=('dawn-of-hope','rhystic-study','smothering-tithe','gleaming-splendor')


class ResolutionPaymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        reviewed=load_reviewed(cls.root)
        cls.rows={key:reviewed[key]['review'] for key in CARDS}
        cls.cards={key:reviewed[key]['program'] for key in CARDS}
        cls.base=tuple(r['program'] for r in reviewed.values())

    def game(self,key='dawn-of-hope',*,extra=(),source_zone=Zone.BATTLEFIELD):
        self.key=key
        body=CardProgram('payment-body','Body',('Creature',),power=2,toughness=3)
        spell=CardProgram('payment-spell','Spell',('Instant',),cast=CastSpec(CostSpec(),timing='instant'))
        land=CardProgram('payment-land','Land',('Land',),subtypes=('Forest',))
        rock=CardProgram('payment-rock','Rock',('Artifact',),activated=(
            ActivatedProgram('choose',CostSpec(tap_source=True),(ChooseMana((('W',),('U',),('G',))),),mana_ability=True),
            ActivatedProgram('ordinary',CostSpec(),(GainLife(1),))))
        self.programs=self.base+(body,spell,land,rock)+extra
        self.state=RulesState(('A','B','C','D'));self.kernel=RulesKernel(self.state,self.programs)
        self.kernel.open_window_for_scenario('A')
        self.source=self.state.add_card('source',self.cards[key].definition_id,'A',source_zone)
        self.bodies={p:self.state.add_card('body-'+p,'payment-body',p,Zone.BATTLEFIELD) for p in self.state.players}
        for p in self.state.players:
            for n in range(12):self.state.add_card('library-'+p+'-'+str(n),'payment-body',p,Zone.LIBRARY)
        self.number=0

    def ident(self):
        self.number+=1
        return 'action-'+str(self.number)

    def top(self):
        self.assertTrue(self.kernel.stack)
        result=None
        for _ in self.state.live_players:result=self.kernel.pass_priority(self.kernel.priority)
        return result

    def settle(self):
        for _ in range(60):
            self.assertIsNone(self.kernel.pending_choice)
            self.assertIsNone(self.kernel.mana_payment)
            if not self.kernel.stack:return
            self.top()
        self.fail('Unexpected trigger loop')

    def effect(self,player,*effects):
        return self.kernel.execute_for_scenario(self.bodies[player],player,effects)

    def payment(self,mana=None,*,actor=None,request=None,revision=None,action_id=None):
        window=self.kernel.mana_payment
        return self.kernel.pay_resolution_mana(action_id or self.ident(),actor or window['actor'],
            request or window['id'],None if mana is None else Payment(tuple(sorted(mana.items()))),
            revision=revision or self.kernel.revision)

    def choose(self,key):
        q=self.kernel.pending_choice;self.assertIsNotNone(q)
        return self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.key==key)])

    def hand(self,p):return len(self.state.objects(Zone.HAND,owner=p))
    def tokens(self,kind):return tuple(o for o in self.state.objects(Zone.BATTLEFIELD) if o.token and kind in self.kernel.effective(o.ref).subtypes)

    def life_window(self):
        self.effect('A',GainLife(3))
        self.assertEqual(1,len(self.kernel.stack))
        return self.top()

    def draw_window(self):
        self.effect('B',Draw(1))
        return self.top()

    def cast_opponent(self,player='B'):
        self.kernel.open_window_for_scenario('A',priority_actor=player)
        ref=self.state.add_card(self.ident(),'payment-spell',player,Zone.HAND)
        self.kernel.commit_action(self.kernel.quote_cast(self.ident(),player,ref),Payment())
        return ref

    def activate(self,player,ref,ability,mana=None):
        quote=self.kernel.quote_activation(self.ident(),player,ref,ability)
        return self.kernel.commit_action(quote,Payment(tuple(sorted((mana or {}).items()))))

    def test_printed_faces_and_exact_source_bindings(self):
        catalog={c.card_id:c for c in load_catalog(self.root/'data/catalog/cards.json')}
        self.assertEqual(set(CARDS),set(self.cards))
        for key,program in self.cards.items():
            with self.subTest(card=key):
                self.assertEqual(digest(source_facts(catalog[key])),self.rows[key]['source_facts_sha256'])
                self.assertEqual(self.rows[key]['program'],encode(program))
                face=catalog[key].faces[0]
                self.assertEqual(1,len(catalog[key].faces))
                for field in ('types','subtypes','supertypes','colors'):
                    self.assertEqual(set(getattr(face,field)),set(getattr(program,field)))
                for field in ('power','toughness','mana_value'):
                    self.assertEqual(getattr(face,field),getattr(program,field))
                self.assertEqual(catalog[key].name,program.name)

    def test_all_four_normal_casting_costs_and_entry(self):
        for key in CARDS:
            with self.subTest(card=key):
                self.game(key,source_zone=Zone.HAND)
                cost=self.cards[key].cast.cost.mana
                quote=self.kernel.quote_cast(self.ident(),'A',self.source)
                self.assertEqual(cost,quote.cost.mana)
                symbols=cost.symbols+('C',)*cost.generic
                self.state.add_mana('A',symbols)
                quote=self.kernel.quote_cast(self.ident(),'A',self.source)
                self.kernel.commit_action(quote,Payment(tuple((s,symbols.count(s)) for s in sorted(set(symbols)))))
                self.settle()
                self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('source')).zone)
                self.assertEqual((),self.state.mana_pool('A'))

    def test_dawn_pays_once_and_draws_one_for_a_single_gain_event(self):
        self.game();boundary=self.life_window()
        self.assertIsInstance(boundary,ManaPaymentBoundary);self.assertEqual('A',boundary.actor)
        self.state.add_mana('A',('G','U'))
        self.payment({'G':1,'U':1})
        self.assertEqual(1,self.hand('A'));self.assertEqual(43,self.state.life('A'))
        self.assertIsNone(self.kernel.mana_payment);self.assertEqual((),self.state.mana_pool('A'))

    def test_dawn_decline_keeps_mana_and_does_not_draw(self):
        self.game();self.life_window();self.state.add_mana('A',('C','C'))
        self.payment();self.assertEqual(0,self.hand('A'));self.assertEqual((('C',2),),self.state.mana_pool('A'))

    def test_dawn_opponent_life_gain_and_zero_gain_do_not_trigger(self):
        self.game();self.effect('B',GainLife(4));self.assertFalse(self.kernel.stack)
        self.effect('A',GainLife(0));self.assertFalse(self.kernel.stack)

    def test_distinct_life_events_offer_distinct_payments(self):
        self.game();self.effect('A',GainLife(1),GainLife(1))
        q=self.kernel.pending_choice;self.assertEqual('trigger_order',q.kind)
        self.kernel.answer(q.request_id,q.actor,list(range(len(q.options))))
        self.assertEqual(2,len(self.kernel.stack))
        first=self.top().request_id;self.payment()
        second=self.top().request_id;self.assertNotEqual(first,second)
        self.payment();self.assertEqual(0,self.hand('A'))

    def test_dawn_soldier_activation_uses_printed_cost_and_lifelink(self):
        self.game();self.state.add_mana('A',('C','C','C','W'))
        self.activate('A',self.source,'soldier',{'C':3,'W':1});self.top()
        token,=self.tokens('Soldier');view=self.kernel.effective(token.ref)
        self.assertEqual((1,1),(view.power,view.toughness));self.assertEqual(frozenset(('W',)),view.colors)
        self.assertIn('lifelink',view.keywords);self.assertFalse(self.kernel.stack)

    def test_rhystic_opponent_pays_before_optional_draw(self):
        self.game('rhystic-study');self.cast_opponent();boundary=self.top()
        self.assertEqual('B',boundary.actor);self.assertIsNone(self.kernel.pending_choice)
        self.state.add_mana('B',('G',));self.payment({'G':1})
        self.assertIsNone(self.kernel.pending_choice);self.assertEqual(0,self.hand('A'))
        self.assertEqual(1,len(self.kernel.stack));self.settle()

    def test_rhystic_decline_offers_controller_optional_draw(self):
        self.game('rhystic-study');self.cast_opponent();self.top();self.payment()
        q=self.kernel.pending_choice;self.assertEqual(('A','may'),(q.actor,q.kind))
        self.choose('yes');self.assertEqual(1,self.hand('A'));self.settle()

    def test_rhystic_controller_can_decline_draw_after_nonpayment(self):
        self.game('rhystic-study');self.cast_opponent();self.top();self.payment();self.choose('no')
        self.assertEqual(0,self.hand('A'));self.settle()

    def test_rhystic_own_spell_does_not_trigger(self):
        self.game('rhystic-study');self.cast_opponent('A')
        self.assertEqual(1,len(self.kernel.stack));self.settle();self.assertIsNone(self.kernel.mana_payment)

    def test_rhystic_captures_each_spells_actual_caster(self):
        self.game('rhystic-study')
        for p in ('B','C','D'):
            self.cast_opponent(p);self.assertEqual(p,self.top().actor)
            self.payment();self.choose('no');self.settle()

    def test_tithe_paid_and_unpaid_branches(self):
        self.game('smothering-tithe');self.assertEqual('B',self.draw_window().actor)
        self.state.add_mana('B',('G','G'));self.payment({'G':2})
        self.assertEqual(0,len(self.tokens('Treasure')))
        self.draw_window();self.payment();token,=self.tokens('Treasure')
        self.assertEqual('A',token.controller);self.assertEqual(2,self.hand('B'))

    def test_tithe_controller_draw_does_not_trigger(self):
        self.game('smothering-tithe');self.effect('A',Draw(2))
        self.assertFalse(self.kernel.stack);self.assertEqual(0,len(self.tokens('Treasure')))

    def test_tithe_each_card_in_multi_draw_has_its_own_payment(self):
        self.game('smothering-tithe');self.effect('B',Draw(3))
        q=self.kernel.pending_choice;self.assertEqual('trigger_order',q.kind)
        self.kernel.answer(q.request_id,q.actor,list(range(len(q.options))))
        ids=[]
        for _ in range(3):
            ids.append(self.top().request_id);self.payment()
        self.assertEqual(3,len(set(ids)));self.assertEqual(3,len(self.tokens('Treasure')))

    def test_treasure_is_tap_sacrifice_for_one_mana_of_a_chosen_color(self):
        self.game('smothering-tithe');self.draw_window();self.payment()
        token,=self.tokens('Treasure');self.kernel.open_window_for_scenario('A')
        self.activate('A',token.ref,'mana')
        q=self.kernel.pending_choice
        self.assertEqual(5,len(q.options));self.kernel.answer(q.request_id,'A',[2])
        self.assertEqual((('B',1),),self.state.mana_pool('A'));self.assertFalse(self.tokens('Treasure'))
        self.assertFalse(any(o.ref.card_id==token.ref.card_id for o in self.state.objects()))

    def test_payment_rejects_wrong_actor_stale_id_and_stale_revision_atomically(self):
        self.game();self.life_window();self.state.add_mana('A',('G','G'))
        before=self.kernel.snapshot()
        for kwargs in ({'actor':'B'},{'request':'missing'},{'revision':'stale'}):
            with self.subTest(kwargs=kwargs),self.assertRaises(RulesViolation):self.payment({'G':2},**kwargs)
            self.assertEqual(before,self.kernel.snapshot())

    def test_payment_rejects_insufficient_overpaid_and_malformed_mana(self):
        self.game();self.life_window();self.state.add_mana('A',('G','G','G'))
        before=self.kernel.snapshot()
        for mana in ({'G':1},{'G':3},{'W':2},{'G':-2},{'G':True}):
            with self.subTest(mana=mana),self.assertRaises(RulesViolation):self.payment(mana)
            self.assertEqual(before,self.kernel.snapshot())

    def test_payment_receipt_cannot_be_reused(self):
        self.game();self.life_window();window=dict(self.kernel.mana_payment)
        self.payment(action_id='once');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):
            self.kernel.pay_resolution_mana('once','A',window['id'],None,revision=self.kernel.revision)
        self.assertEqual(before,self.kernel.snapshot())

    def test_payment_rejects_taps_zone_costs_and_empty_identity(self):
        self.game();self.life_window();before=self.kernel.snapshot();window=self.kernel.mana_payment
        for packet in (Payment(taps=(self.bodies['A'],)),Payment(zone_costs=(('bad',()),))):
            with self.assertRaises(RulesViolation):
                self.kernel.pay_resolution_mana('bad','A',window['id'],packet,revision=self.kernel.revision)
            self.assertEqual(before,self.kernel.snapshot())
        with self.assertRaises(RulesViolation):
            self.kernel.pay_resolution_mana('','A',window['id'],None,revision=self.kernel.revision)

    def test_land_mana_can_be_activated_without_priority_and_pay_parent(self):
        self.game()
        lands=[self.state.add_card('land-'+str(n),'payment-land','A',Zone.BATTLEFIELD) for n in range(2)]
        self.life_window()
        for ref in lands:
            self.assertIsNone(self.kernel.priority)
            result=self.activate('A',ref,'intrinsic-land:Forest')
            self.assertIsInstance(result,ManaPaymentBoundary)
        self.payment({'G':2});self.assertEqual(1,self.hand('A'))
        self.assertTrue(all(self.state.get(ref).tapped for ref in lands))

    def test_only_payers_instant_mana_abilities_are_available(self):
        slow=CardProgram('slow','Slow',('Artifact',),activated=(
            ActivatedProgram('slow',CostSpec(),(AddMana(('G',)),),timing='sorcery',mana_ability=True),))
        self.game(extra=(slow,))
        rock=self.state.add_card('rock','payment-rock','A',Zone.BATTLEFIELD)
        other=self.state.add_card('other','payment-rock','B',Zone.BATTLEFIELD)
        slowref=self.state.add_card('slow','slow','A',Zone.BATTLEFIELD)
        self.life_window();before=self.kernel.snapshot()
        for p,ref,ability in (('A',rock,'ordinary'),('B',other,'choose'),('A',other,'choose'),('A',slowref,'slow')):
            with self.assertRaises(RulesViolation):self.kernel.quote_activation(self.ident(),p,ref,ability)
            self.assertEqual(before,self.kernel.snapshot())
        with self.assertRaises(RulesViolation):self.kernel.pass_priority('A')

    def test_summoning_sick_mana_creature_is_not_available(self):
        elf=CardProgram('elf','Elf',('Creature',),power=1,toughness=1,activated=(
            ActivatedProgram('mana',CostSpec(tap_source=True),(AddMana(('G',)),),mana_ability=True),))
        self.game(extra=(elf,));ref=self.state.add_card('elf','elf','A',Zone.BATTLEFIELD)
        self.life_window();before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_activation(self.ident(),'A',ref,'mana')
        self.assertEqual(before,self.kernel.snapshot())

    def test_mana_choice_restores_parent_and_checkpoint(self):
        self.game();rock=self.state.add_card('rock','payment-rock','A',Zone.BATTLEFIELD)
        self.life_window();parent=self.kernel.resolving['id'];self.activate('A',rock,'choose')
        self.assertNotEqual(parent,self.kernel.resolving['id'])
        q=self.kernel.pending_choice;restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.kernel.answer(q.request_id,'A',[2]);restored.answer(q.request_id,'A',[2])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual(parent,self.kernel.resolving['id']);self.assertIsNone(self.kernel.priority)
        self.payment();self.assertEqual(0,self.hand('A'));self.assertEqual((('G',1),),self.state.mana_pool('A'))

    def test_payment_checkpoint_preserves_parent_task_identity(self):
        self.game();self.life_window();self.state.add_mana('A',('C','C'))
        checkpoint=self.kernel.snapshot();restored=RulesKernel.restore(checkpoint,self.programs)
        self.assertGreaterEqual(checkpoint['schema'],115);self.assertIs(restored.resolving,restored.mana_payment['parent'])
        window=self.kernel.mana_payment;revision=self.kernel.revision
        self.payment({'C':2},action_id='pay')
        restored.pay_resolution_mana('pay','A',window['id'],Payment((('C',2),)),revision=revision)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        checkpoint['schema']=114
        with self.assertRaises(RulesViolation):RulesKernel.restore(checkpoint,self.programs)

    def test_child_mana_generated_triggers_wait_until_parent_finishes(self):
        rock=CardProgram('life-rock','Life Rock',('Artifact',),activated=(
            ActivatedProgram('mana',CostSpec(tap_source=True),(GainLife(1),AddMana(('G',))),mana_ability=True),))
        self.game(extra=(rock,));ref=self.state.add_card('rock','life-rock','A',Zone.BATTLEFIELD)
        self.life_window();self.activate('A',ref,'mana')
        self.assertEqual(1,len(self.kernel.pending_triggers));self.assertFalse(self.kernel.stack)
        self.payment();self.assertEqual(1,len(self.kernel.stack))
        self.top();self.payment();self.assertEqual(44,self.state.life('A'))

    def test_sacrificed_treasure_mana_choice_resumes_suspended_payment(self):
        self.game();token=self.cards['smothering-tithe'].abilities[0].effects[0].otherwise[0].token
        ref=self.state.add_card('treasure',token.definition_id,'A',Zone.BATTLEFIELD,token=True)
        self.life_window();self.state.add_mana('A',('C',));self.activate('A',ref,'mana')
        self.assertIsNotNone(self.kernel.pending_choice)
        checkpoint=self.kernel.snapshot();restored=RulesKernel.restore(checkpoint,self.programs)
        q=self.kernel.pending_choice
        self.kernel.answer(q.request_id,'A',[0]);restored.answer(q.request_id,'A',[0])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.payment({'C':1,'W':1});self.assertEqual(1,self.hand('A'));self.assertFalse(self.tokens('Treasure'))

    def test_adapter_journal_replays_pay_mana_and_nested_mana_choice(self):
        self.game();rock=self.state.add_card('rock','payment-rock','A',Zone.BATTLEFIELD)
        self.life_window();self.state.add_mana('A',('C',));adapter=RulesActorAdapter(self.kernel)
        adapter.submit('A',{'kind':'activate','revision':self.kernel.revision,'action_id':'rock','source':rock.to_json(),
            'targets':[],'x_value':0,'payment':{'mana':{},'taps':[]},'ability_id':'choose'})
        q=self.kernel.pending_choice
        adapter.submit('A',{'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':[0]})
        window=self.kernel.mana_payment
        adapter.submit('A',{'kind':'pay_mana','revision':self.kernel.revision,'action_id':'pay','request_id':window['id'],
            'payment':{'mana':{'C':1,'W':1},'taps':[]}})
        self.assertEqual(1,self.hand('A'))
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())

    def test_actor_window_is_authenticated_and_does_not_disclose_private_parent(self):
        self.game('rhystic-study');self.cast_opponent();self.top();adapter=RulesActorAdapter(self.kernel)
        self.assertEqual('mana_payment',adapter.packet('B')['decision']['kind'])
        self.assertEqual({'kind':'waiting','actor':'B'},adapter.packet('C')['decision'])
        public=adapter.packet('C')['resolution_payment']
        self.assertNotIn('parent',public);self.assertNotIn('tasks',public)
        encoded=json.dumps(adapter.packet('C'));self.assertNotIn('library-A-11',encoded)
        before=self.kernel.snapshot()
        command={'kind':'pay_mana','revision':self.kernel.revision,'action_id':'pay',
            'request_id':self.kernel.mana_payment['id'],'payment':None}
        with self.assertRaises(RulesViolation):adapter.submit('A',command)
        self.assertEqual(before,self.kernel.snapshot());self.assertEqual([],adapter.records)
        adapter.submit('B',command);self.assertEqual('choice',adapter.packet('A')['decision']['kind'])

    def test_paid_and_unpaid_nested_effects_keep_lexical_bindings(self):
        for paid in (False,True):
            with self.subTest(paid=paid):
                self.game();self.state.add_card('second','payment-body','A',Zone.BATTLEFIELD)
                selector=Selector(Zone.BATTLEFIELD,('Creature',),relation='controlled')
                self.effect('A',Select(selector,1,1,(PayMana(ManaCost(1),(AddCounters('selected','+1/+1',1),),
                    (AddCounters('selected','+1/+1',2),)),)))
                q=self.kernel.pending_choice
                self.kernel.answer(q.request_id,'A',[next(i for i,o in enumerate(q.options) if o.ref==self.bodies['A'])])
                if paid:self.state.add_mana('A',('C',))
                self.payment({'C':1} if paid else None)
                self.assertEqual(1 if paid else 2,dict(self.state.get(self.bodies['A']).counters).get('+1/+1'))

    def test_multiple_payment_instructions_resume_once_in_order(self):
        self.game();self.effect('A',PayMana(ManaCost(),(GainLife(1),)),PayMana(ManaCost(),(Draw(1),)))
        first=self.kernel.mana_payment['id'];self.payment({})
        self.assertNotEqual(first,self.kernel.mana_payment['id']);self.payment({})
        self.assertEqual(1,self.hand('A'));self.assertEqual(41,self.state.life('A'))
        self.top();self.payment()

    def test_payment_fixed_colored_colorless_and_hybrid_costs(self):
        self.game();self.effect('A',PayMana(ManaCost(1,('W/U','C')),(Draw(1),)))
        self.state.add_mana('A',('G','G','C','U'))
        with self.assertRaises(RulesViolation):self.payment({'G':2,'C':1})
        self.payment({'G':1,'C':1,'U':1});self.assertEqual(1,self.hand('A'))

    def test_compiler_rejects_unbound_payers_variable_costs_and_nested_mana_payments(self):
        for effect in (PayMana(ManaCost(),(),players='event_controllers'),PayMana(ManaCost(x_symbols=1),()),
                       PayMana(ManaCost(),(),players='all'),PayMana(ManaCost(),[],())):
            with self.subTest(effect=effect),self.assertRaises(RulesViolation):
                validate(CardProgram('bad','Bad',('Instant',),spell_effects=(effect,)))
        with self.assertRaises(RulesViolation):
            validate(CardProgram('bad','Bad',('Artifact',),activated=(ActivatedProgram('mana',CostSpec(),
                (AddMana(('G',)),PayMana(ManaCost(),())),mana_ability=True),)))

    def test_gleaming_second_draw_only_not_first_third_or_controller(self):
        self.game('gleaming-splendor')
        self.effect('B',Draw(1));self.assertFalse(self.kernel.stack)
        self.effect('B',Draw(1));self.assertEqual(1,len(self.kernel.stack));self.settle()
        self.effect('B',Draw(1));self.assertFalse(self.kernel.stack)
        self.effect('A',Draw(3));self.assertFalse(self.kernel.stack)
        self.assertEqual(1,len(self.tokens('Treasure')))

    def test_gleaming_counts_each_opponent_and_resets_each_turn(self):
        self.game('gleaming-splendor')
        for p in ('B','C','D'):
            self.effect(p,Draw(2));self.settle()
        self.assertEqual(3,len(self.tokens('Treasure')))
        self.state.start_turn('C')
        self.assertEqual({'A':0,'B':0,'C':0,'D':0},RulesActorAdapter(self.kernel).packet('A')['draw_counts'])
        self.effect('B',Draw(2));self.settle()
        self.assertEqual(4,len(self.tokens('Treasure')))

    def test_gleaming_sees_first_draw_before_it_entered(self):
        self.game('gleaming-splendor',source_zone=Zone.HAND)
        self.effect('B',Draw(1));self.kernel.enter(self.source)
        self.effect('B',Draw(1));self.settle();self.assertEqual(1,len(self.tokens('Treasure')))

    def test_gleaming_no_retroactive_trigger_after_second_draw(self):
        self.game('gleaming-splendor',source_zone=Zone.HAND)
        self.effect('B',Draw(2));self.kernel.enter(self.source)
        self.effect('B',Draw(1));self.assertFalse(self.kernel.stack);self.assertFalse(self.tokens('Treasure'))

    def test_gleaming_ordinary_hand_addition_does_not_count_as_draw(self):
        self.game('gleaming-splendor')
        self.state.move((ZoneMove(self.state.objects(Zone.LIBRARY,owner='B')[0].ref,Zone.HAND,'B'),),'fixture-hand-add')
        self.effect('B',Draw(1));self.assertFalse(self.kernel.stack)
        self.assertEqual(1,self.kernel.draw_counts['B'])

    def test_gleaming_multiple_draw_counts_survive_checkpoint(self):
        self.game('gleaming-splendor');self.effect('B',Draw(1))
        self.kernel=RulesKernel.restore(self.kernel.snapshot(),self.programs);self.state=self.kernel.state
        self.effect('B',Draw(1));self.settle();self.assertEqual(1,len(self.tokens('Treasure')))

    def test_gleaming_two_distinct_player_targets_and_printed_activation_cost(self):
        self.game('gleaming-splendor');before=self.kernel.snapshot()
        for targets in ((PlayerRef('B'),),(PlayerRef('B'),PlayerRef('B')),()):
            with self.assertRaises(RulesViolation):
                self.kernel.quote_activation(self.ident(),'A',self.source,'two-players-draw',targets)
            self.assertEqual(before,self.kernel.snapshot())
        self.state.add_mana('A',('C','C','W'))
        quote=self.kernel.quote_activation(self.ident(),'A',self.source,'two-players-draw',(PlayerRef('C'),PlayerRef('B')))
        self.assertEqual(ManaCost(2,('W',)),quote.cost.mana)
        self.kernel.commit_action(quote,Payment((('C',2),('W',1))));self.top()
        events=[e for e in self.kernel.semantic_events if e['kind']=='card_drawn']
        self.assertEqual(['B','C'],[e['player'] for e in events]);self.assertEqual((1,1),(self.hand('B'),self.hand('C')))

    def test_gleaming_activation_can_include_controller_and_trigger_second_draw(self):
        self.game('gleaming-splendor');self.effect('B',Draw(1));self.kernel.open_window_for_scenario('A')
        self.state.add_mana('A',('C','C','W'))
        quote=self.kernel.quote_activation(self.ident(),'A',self.source,'two-players-draw',(PlayerRef('A'),PlayerRef('B')))
        self.kernel.commit_action(quote,Payment((('C',2),('W',1))));self.settle()
        self.assertEqual((1,2),(self.hand('A'),self.hand('B')));self.assertEqual(1,len(self.tokens('Treasure')))

    def test_failed_draw_does_not_increment_ordinal_or_create_treasure(self):
        self.game('gleaming-splendor');self.effect('B',Draw(1))
        self.state.move(tuple(ZoneMove(o.ref,Zone.GRAVEYARD,'B') for o in self.state.objects(Zone.LIBRARY,owner='B')),'fixture-empty')
        self.effect('B',Draw(1))
        self.assertEqual(1,self.kernel.draw_counts['B']);self.assertFalse(self.tokens('Treasure'))
        self.assertNotIn('B',self.state.live_players)

    def test_departed_event_player_takes_unpaid_branch(self):
        self.game('smothering-tithe');self.effect('B',Draw(1))
        self.state.lose_life_batch(('B',),40);self.kernel.advance()
        self.assertNotIn('B',self.state.live_players)
        self.top();self.assertIsNone(self.kernel.mana_payment);self.assertEqual(1,len(self.tokens('Treasure')))

    def test_trigger_keeps_original_controller_after_source_control_changes(self):
        # A response changes control without rewriting the existing trigger.
        control=CardProgram('control','Control',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD)),spell_effects=(GainControl('target'),))
        self.game('dawn-of-hope',extra=(control,));self.effect('A',GainLife(1))
        self.kernel.pass_priority('A')
        ref=self.state.add_card('control','control','B',Zone.HAND)
        quote=self.kernel.quote_cast(self.ident(),'B',ref,(self.source,))
        self.kernel.commit_action(quote,Payment());self.top()
        self.assertEqual('B',self.state.get(self.source).controller)
        self.assertEqual('A',self.top().actor);self.payment()

    def test_gleaming_two_targets_resolves_for_surviving_player(self):
        self.game('gleaming-splendor');self.state.add_mana('A',('C','C','W'))
        quote=self.kernel.quote_activation(self.ident(),'A',self.source,'two-players-draw',(PlayerRef('B'),PlayerRef('C')))
        self.kernel.commit_action(quote,Payment((('C',2),('W',1))))
        self.state.lose_life_batch(('B',),40);self.kernel.advance();self.top()
        self.assertNotIn('B',self.state.live_players);self.assertEqual(1,self.hand('C'))

    def test_draw_ordinal_compiler_and_strict_codec(self):
        self.game('gleaming-splendor')
        program=self.cards[self.key];ability=program.abilities[0]
        for event in (replace(ability.event,occurrence=0),replace(ability.event,occurrence=True),
                      replace(ability.event,kind='life_gained'),replace(ability.event,subject='self')):
            with self.assertRaises(RulesViolation):validate(replace(program,abilities=(replace(ability,event=event),)))
        encoded=encode(ability.event);del encoded['occurrence']
        with self.assertRaises(RulesViolation):decode(encoded)


if __name__=='__main__':unittest.main()
