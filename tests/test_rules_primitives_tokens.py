"""Token definitions, atomic entries, inheritance and public projection."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import (CardProgram,CreateTokens,EntryCounters,CounterReplacement,Selector,
    CountObjects,AbilityProgram,EventPattern,GainLife,Move,SelectAll,ActivatedProgram,CostSpec,ZoneCost,
    AddMana,CastSpec,validate)
from edh_gauntlet.rules_state import RulesState,RulesObject,ObjectRef,Zone,ZoneMove,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_actor import project_actor
from edh_gauntlet.rules_casting import Payment


class TokenTests(unittest.TestCase):
    def game(self,token=None,amount=2,extra=()):
        self.token=token or CardProgram('token:plant','Plant Token',('Creature',),subtypes=('Plant',),power=0,toughness=1,colors=('G',))
        self.effect=CreateTokens(self.token,amount)
        self.source=CardProgram('source','Source',('Artifact',),spell_effects=(self.effect,))
        self.programs=(self.source,*extra);self.state=RulesState(('A','B'))
        self.ref=self.state.add_card('source','source','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs)

    def create(self):return self.kernel.execute_for_scenario(self.ref,'A',(self.effect,))
    def tokens(self):return tuple(o for o in self.state.objects(Zone.BATTLEFIELD) if o.token)

    def test_one_atomic_batch_preserves_definitions_ownership_and_public_colors(self):
        self.game();self.create();tokens=self.tokens()
        self.assertEqual(2,len(tokens));self.assertTrue(all(o.owner==o.controller=='A' for o in tokens))
        self.assertEqual(1,len({e.batch for e in self.state.events}))
        self.assertTrue(all(self.kernel.effective(o.ref).colors=={'G'} for o in tokens))
        packet=project_actor(self.kernel,'B')
        rows=packet['zones']['battlefield']['A'] if 'zones' in packet else packet['public_zones']['battlefield']['A']
        self.assertTrue(all(r['colors']==['G'] for r in rows if r['token']))
        self.assertEqual(1,sum(e['kind']=='tokens_created' for e in self.kernel.semantic_events))

    def test_token_etbs_queue_after_whole_batch_and_can_be_ordered(self):
        token=CardProgram('token:etb','ETB Token',('Creature',),power=1,toughness=1,
            abilities=(AbilityProgram('life',EventPattern('zone_changed',to_zone=Zone.BATTLEFIELD,subject='self'),(GainLife(1),)),))
        self.game(token);r=self.create();self.assertEqual('trigger_order',r.kind)
        self.assertEqual(2,len(self.tokens()));self.assertEqual(40,self.state.life('A'))
        self.kernel.answer(r.request_id,r.actor,[0,1])
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual(42,self.state.life('A'))

    def test_pending_replacements_allocate_nothing_and_restore_exactly(self):
        token=CardProgram('token:counter','Counter Token',('Creature',),power=0,toughness=0,
            entry_counters=(EntryCounters('one','+1/+1',1),))
        mods=tuple(CardProgram(k,k,('Enchantment',),counter_replacements=(CounterReplacement(k,Selector(Zone.BATTLEFIELD),kind='+1/+1',multiplier=m,additional=a),))
            for k,m,a in (('double',2,0),('plus',1,1)))
        self.game(token,extra=mods)
        for p in mods:self.state.add_card(p.name,p.definition_id,'A',Zone.BATTLEFIELD)
        before=self.state.snapshot();self.create();self.assertEqual(before,self.state.snapshot())
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        while self.kernel.pending_choice:
            r=self.kernel.pending_choice;self.kernel.answer(r.request_id,r.actor,[0]);restored.answer(r.request_id,r.actor,[0])
            self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual(2,len(self.tokens()));self.assertEqual(1,len({e.batch for e in self.state.events}))

    def test_tokens_die_and_cannot_return_through_blink(self):
        self.game();self.create();refs=tuple(o.ref for o in self.tokens())
        from edh_gauntlet.rules_program import WithMoved
        self.kernel.execute_for_scenario(self.ref,'A',(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',)),
            (WithMoved('selected',Zone.EXILE,(Move('moved',Zone.BATTLEFIELD),)),)),))
        self.assertFalse(self.tokens());self.assertTrue(all(o.ref not in refs for o in self.state.objects()))
        self.assertEqual(2,sum(e['kind']=='token_ceased' for e in self.kernel.semantic_events))

    def test_zero_and_counted_creation_and_unique_identity_after_ceasing(self):
        self.game(amount=0);self.create();self.assertEqual((),self.state.events)
        self.game(amount=CountObjects(Selector(Zone.BATTLEFIELD)))
        self.create();first={o.ref.card_id for o in self.tokens()};self.assertEqual(1,len(first))
        self.kernel.execute_for_scenario(self.ref,'A',(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',)),(Move('selected',Zone.GRAVEYARD),)),))
        self.create();self.assertTrue(first.isdisjoint({o.ref.card_id for o in self.tokens()}))

    def test_token_activated_program_survives_sacrifice_payment(self):
        token=CardProgram('token:mana','Mana Token',('Artifact',),activated=(ActivatedProgram('mana',
            CostSpec(tap_source=True,zone_costs=(ZoneCost('sac','sacrifice'),)),(AddMana(('G',)),),mana_ability=True),))
        self.game(token,amount=1);self.create();ref=self.tokens()[0].ref
        self.kernel.open_window_for_scenario('A');self.kernel.commit_action(self.kernel.quote_activation('mana','A',ref,'mana'),Payment())
        self.assertEqual((('G',1),),self.state.mana_pool('A'));self.assertFalse(self.tokens())

    def test_duplicate_definitions_and_invalid_programs_reject(self):
        self.game()
        for token in (replace(self.token,colors=('G','G')),replace(self.token,cast=CastSpec(CostSpec())),replace(self.token,types=('Instant',))):
            with self.assertRaises(RulesViolation):validate(replace(self.source,spell_effects=(CreateTokens(token),)))
        conflicting=replace(self.token,power=2)
        with self.assertRaises(RulesViolation):RulesKernel(self.state,(self.source,conflicting))

    def test_invalid_creation_state_transaction_is_atomic(self):
        self.game();before=self.state.snapshot()
        token=RulesObject(ObjectRef('new',0),'token:plant','A','A',Zone.OUTSIDE,token=True)
        for proposed in (replace(token,token=False),replace(token,owner='B'),replace(token,ref=ObjectRef('source',0))):
            with self.assertRaises(RulesViolation):self.state.move((ZoneMove(proposed.ref,Zone.BATTLEFIELD),),'create',creates=(proposed,))
            self.assertEqual(before,self.state.snapshot())

class AuthoredTokenTests(unittest.TestCase):
    def game(self,key):
        from edh_gauntlet.rules_bundle import load_reviewed
        self.programs=tuple(r['program'] for r in load_reviewed().values())
        self.state=RulesState(('A','B'));self.ref=self.state.add_card('source','catalog:'+key,'A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs)

    def drain(self):
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)

    def test_avenger_counts_lands_then_landfall_grows_all_plants(self):
        self.game('avenger-of-zendikar')
        for i in range(3):self.state.add_card('land'+str(i),'catalog:forest','A',Zone.BATTLEFIELD)
        ref=self.state.add_card('avenger','catalog:avenger-of-zendikar','A',Zone.HAND)
        self.kernel.execute_for_scenario(ref,'A',(Move('source',Zone.BATTLEFIELD),));self.drain()
        # Both Avengers observe landfall, but only the entering one makes Plants.
        plants=[o for o in self.state.objects(Zone.BATTLEFIELD) if o.token];self.assertEqual(3,len(plants))
        land=self.state.add_card('newland','catalog:forest','A',Zone.HAND)
        self.kernel.execute_for_scenario(land,'A',(Move('source',Zone.BATTLEFIELD),))
        r=self.kernel.pending_choice;self.kernel.answer(r.request_id,r.actor,list(range(len(r.options))))
        while self.kernel.stack or self.kernel.pending_choice:
            if self.kernel.pending_choice:
                r=self.kernel.pending_choice;self.kernel.answer(r.request_id,r.actor,[0])
            else:self.kernel.pass_priority(self.kernel.priority)
        self.assertTrue(all(dict(self.state.get(o.ref).counters)['+1/+1']==2 for o in plants))

    def test_baloths_optional_token_has_complete_printed_characteristics(self):
        self.game('rampaging-baloths');ref=self.state.add_card('land','catalog:forest','A',Zone.HAND)
        self.kernel.execute_for_scenario(ref,'A',(Move('source',Zone.BATTLEFIELD),));self.drain()
        r=self.kernel.pending_choice;self.assertEqual('may',r.kind);self.kernel.answer(r.request_id,r.actor,[0])
        token=next(o for o in self.state.objects(Zone.BATTLEFIELD) if o.token);view=self.kernel.effective(token.ref)
        self.assertEqual((4,4),(view.power,view.toughness));self.assertEqual({'G'},view.colors)
        self.assertEqual({'Beast'},view.subtypes)

    def test_hour_tests_desert_threshold_after_searched_lands_enter(self):
        from edh_gauntlet.rules_program import CreateTokens
        self.game('hour-of-promise')
        for i in range(2):self.state.add_card('desert'+str(i),'catalog:lush-oasis','A',Zone.BATTLEFIELD)
        land=self.state.add_card('found','catalog:lush-oasis','A',Zone.LIBRARY)
        program=self.kernel.definition(self.state.get(self.ref))
        self.kernel.execute_for_scenario(self.ref,'A',program.spell_effects)
        r=self.kernel.pending_choice;self.kernel.answer(r.request_id,r.actor,[0]);self.drain()
        tokens=[o for o in self.state.objects(Zone.BATTLEFIELD) if o.token];self.assertEqual(2,len(tokens))
        self.assertTrue(self.state.get(self.state.current('found')).tapped)
        self.assertTrue(all(self.kernel.effective(o.ref).colors=={'B'} for o in tokens))

    def test_trading_post_all_four_abilities_use_shared_payments_and_stack(self):
        for ability in ('discard-life','goat','recover-artifact','sacrifice-draw'):
            self.game('trading-post');self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('C',))
            targets=();zones=()
            if ability=='discard-life':
                ref=self.state.add_card('cost','catalog:forest','A',Zone.HAND);zones=(('discard',(ref,)),)
            elif ability=='recover-artifact':
                ref=self.state.add_card('cost','catalog:llanowar-elves','A',Zone.BATTLEFIELD);zones=(('sacrifice',(ref,)),)
                targets=(self.state.add_card('target','catalog:sol-ring','A',Zone.GRAVEYARD),)
            elif ability=='sacrifice-draw':
                zones=(('sacrifice',(self.ref,)),);self.state.add_card('draw','catalog:forest','A',Zone.LIBRARY)
            self.kernel.commit_action(self.kernel.quote_activation(ability,'A',self.ref,ability,targets),Payment((('C',1),),zone_costs=zones));self.drain()
            if ability=='discard-life':self.assertEqual(44,self.state.life('A'))
            elif ability=='goat':
                self.assertEqual(39,self.state.life('A'));token=next(o for o in self.state.objects() if o.token)
                view=self.kernel.effective(token.ref);self.assertEqual((0,1,{'W'}),(view.power,view.toughness,view.colors))
            elif ability=='recover-artifact':self.assertEqual(Zone.HAND,self.state.get(self.state.current('target')).zone)
            else:self.assertEqual(Zone.HAND,self.state.get(self.state.current('draw')).zone)

if __name__=='__main__':unittest.main()

