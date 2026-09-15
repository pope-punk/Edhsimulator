"""Follow-ups depend on actual movement; announced X binds one target batch."""
from dataclasses import replace
import unittest
from edh_gauntlet.rules_program import (CardProgram,TargetSpec,Selector,ChosenX,CostSpec,ManaCost,CastSpec,
    WithZoneResult,WithMoved,Move,Destroy,CreateTokens,GainLife,ZoneReplacement,SelectAll,SetTapped,
    AbilityProgram,EventPattern,ActivatedProgram,validate)
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove,RulesViolation,PlayerRef
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter


class ZoneResultTests(unittest.TestCase):
    def game(self,extra=()):
        self.token=CardProgram('token','Token',('Creature',),power=1,toughness=1)
        self.source=CardProgram('source','Source',('Artifact',),spell_effects=(CreateTokens(self.token),))
        self.creature=CardProgram('creature','Creature',('Creature',),power=1,toughness=1)
        self.programs=(self.source,self.creature,*extra);self.state=RulesState(('A','B'))
        self.ref=self.state.add_card('source','source','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs)

    def test_destroy_results_exclude_indestructible_and_wrong_destination(self):
        shield=CardProgram('shield','Shield',('Creature',),power=1,toughness=1,keywords=('indestructible',))
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,relation='owned'),))
        self.game((shield,redirect));self.state.add_card('redirect','redirect','A',Zone.BATTLEFIELD)
        for key,definition,owner in (('normal','creature','B'),('shield','shield','B'),('redirected','creature','A')):
            self.state.add_card(key,definition,owner,Zone.BATTLEFIELD)
        effect=SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',)),(WithZoneResult(Destroy('selected'),Zone.GRAVEYARD,
            (CreateTokens(self.token,players='moved_controllers'),GainLife(1))),))
        self.kernel.execute_for_scenario(self.ref,'A',(effect,))
        self.assertEqual(1,sum(o.token for o in self.state.objects()));self.assertEqual(41,self.state.life('A'))
        self.assertEqual('B',next(o.owner for o in self.state.objects() if o.token))
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('shield')).zone)
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('redirected')).zone)

    def test_no_qualifying_movement_does_not_run_followup(self):
        self.game();self.kernel.execute_for_scenario(self.ref,'A',(WithZoneResult(Move('source',Zone.BATTLEFIELD),Zone.BATTLEFIELD,(GainLife(4),)),))
        self.assertEqual(40,self.state.life('A'));self.assertEqual((),self.state.events)

    def test_nested_zone_results_restore_outer_controller_group(self):
        self.game();self.state.add_card('victim','creature','B',Zone.BATTLEFIELD)
        nested=WithZoneResult(Move('source',Zone.EXILE),Zone.EXILE,(CreateTokens(self.token,players='moved_controllers'),))
        self.kernel.execute_for_scenario(self.ref,'A',(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',)),
            (WithZoneResult(Move('selected',Zone.EXILE),Zone.EXILE,(nested,CreateTokens(self.token,players='moved_controllers'))),)),))
        self.assertEqual(['A','B'],[o.owner for o in self.state.objects() if o.token])

    def test_existing_with_moved_exposes_results_and_after_references(self):
        self.game();self.state.add_card('victim','creature','B',Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(self.ref,'A',(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',)),
            (WithMoved('selected',Zone.EXILE,(CreateTokens(self.token,players='moved_controllers'),Move('moved',Zone.HAND))),)),))
        self.assertEqual(Zone.HAND,self.state.get(self.state.current('victim')).zone)
        self.assertEqual('B',next(o.owner for o in self.state.objects() if o.token))

    def test_result_count_is_scoped_and_counts_actual_events(self):
        from edh_gauntlet.rules_program import MovedCount
        self.game()
        for i in range(3):self.state.add_card(str(i),'creature','B',Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(self.ref,'A',(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',)),
            (WithZoneResult(Move('selected',Zone.EXILE),Zone.EXILE,(GainLife(MovedCount()),)),)),))
        self.assertEqual(43,self.state.life('A'))
        with self.assertRaises(RulesViolation):validate(replace(self.source,spell_effects=(GainLife(MovedCount()),)))

    def test_pending_result_replacement_replays_before_followup_once(self):
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,optional=True),))
        self.game((redirect,));self.state.add_card('redirect','redirect','B',Zone.BATTLEFIELD)
        self.state.add_card('victim','creature','B',Zone.BATTLEFIELD)
        self.kernel.execute_for_scenario(self.ref,'A',(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',)),
            (WithZoneResult(Destroy('selected'),Zone.GRAVEYARD,(CreateTokens(self.token,players='moved_controllers'),)),)),))
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('victim')).zone)
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        r=self.kernel.pending_choice;index=next(i for i,o in enumerate(r.options) if o.key=='no')
        command={'kind':'answer','revision':self.kernel.revision,'request_id':r.request_id,'indexes':[index]}
        adapter.submit(r.actor,command);replay.submit(r.actor,command)
        self.assertEqual(adapter.archive(),replay.archive());self.assertEqual(1,sum(o.token for o in self.state.objects()))

    def test_scope_operation_and_player_target_validation(self):
        self.game()
        for effects,spec in (((CreateTokens(self.token,players='moved_controllers'),),None),
                ((WithZoneResult(GainLife(1),Zone.GRAVEYARD,()),),None),
                ((WithZoneResult(Move('target',Zone.EXILE),Zone.EXILE,()),),TargetSpec(None,players='all'))):
            with self.assertRaises(RulesViolation):validate(replace(self.source,spell_effects=effects,spell_targets=spec))

    def test_countering_a_spell_does_not_remove_its_independent_cast_trigger(self):
        from edh_gauntlet.rules_program import Counter
        spell=CardProgram('cast-trigger','Cast Trigger',('Instant',),cast=CastSpec(CostSpec()),
            abilities=(AbilityProgram('cast-life',EventPattern('spell_cast',subject='self'),(GainLife(3),)),))
        counter=CardProgram('counter','Counter',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.STACK)),spell_effects=(Counter('target'),))
        self.game((spell,counter));a=self.state.add_card('spell','cast-trigger','A',Zone.HAND)
        b=self.state.add_card('counter','counter','B',Zone.HAND)
        self.kernel.open_window_for_scenario('A');self.kernel.commit_action(self.kernel.quote_cast('cast','A',a),Payment())
        self.assertEqual(2,len(self.kernel.stack));self.kernel.pass_priority('A')
        self.kernel.commit_action(self.kernel.quote_cast('counter','B',b,(self.state.current('spell'),)),Payment())
        self.kernel.pass_priority('B');self.kernel.pass_priority('A')
        self.assertEqual(1,len(self.kernel.stack));self.assertFalse(self.kernel.stack[0]['spell'])
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('spell')).zone)
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual(43,self.state.life('A'))

    def test_x_target_bounds_require_own_cast_or_activation_x(self):
        self.game();spec=TargetSpec(Selector(Zone.BATTLEFIELD),ChosenX(),ChosenX())
        for program in (replace(self.source,spell_targets=spec),replace(self.source,abilities=(AbilityProgram('x',EventPattern('step_began',step='upkeep'),(),targets=spec),))):
            with self.assertRaises(RulesViolation):validate(program)
        validate(replace(self.source,cast=CastSpec(CostSpec(ManaCost(x_symbols=1))),spell_targets=spec))
        validate(replace(self.source,activated=(ActivatedProgram('x',CostSpec(ManaCost(x_symbols=1)),(),targets=spec),)))

    def test_orientation_batch_validates_before_mutation(self):
        self.game();other=self.state.add_card('other','creature','B',Zone.HAND);before=self.state.snapshot()
        with self.assertRaises(RulesViolation):self.state.set_tapped_batch((self.ref,other),True)
        self.assertEqual(before,self.state.snapshot())
        self.kernel.execute_for_scenario(self.ref,'A',(SetTapped('source',True),SetTapped('source',True),SetTapped('source',False)))
        self.assertFalse(self.state.get(self.ref).tapped)
        self.assertEqual(2,sum(e['kind'] in {'objects_tapped','objects_untapped'} for e in self.kernel.semantic_events))


class AuthoredZoneResultTests(unittest.TestCase):
    def game(self,extra=()):
        from edh_gauntlet.rules_bundle import load_reviewed
        self.programs=tuple(row['program'] for row in load_reviewed().values())+tuple(extra)
        self.state=RulesState(('A','B','C'));self.kernel=RulesKernel(self.state,self.programs)

    def drain(self):
        while self.kernel.stack and not self.kernel.pending_choice:self.kernel.pass_priority(self.kernel.priority)

    def test_curse_binds_x_rejects_wrong_count_then_handles_partial_legality_and_redirect(self):
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('grave',Zone.EXILE,Zone.GRAVEYARD,relation='owned'),))
        self.game((redirect,));self.state.add_card('redirect','redirect','C',Zone.BATTLEFIELD)
        targets=tuple(self.state.add_card('target'+p,'catalog:llanowar-elves',p,Zone.BATTLEFIELD,controller='B') for p in ('A','B','C'))
        spell=self.state.add_card('spell','catalog:curse-of-the-swine','A',Zone.HAND)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('U','U','C','C','C'))
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_cast('bad','A',spell,targets[:2],x_value=3)
        self.assertEqual(before,self.kernel.snapshot())
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',spell,targets,x_value=3),Payment((('U',2),('C',3))))
        self.state.move((ZoneMove(targets[0],Zone.HAND),),'scenario_target_departed')
        self.drain();tokens=[o for o in self.state.objects() if o.token]
        self.assertEqual(1,len(tokens));self.assertEqual('B',tokens[0].owner)
        self.assertEqual(Zone.EXILE,self.state.get(self.state.current('targetB')).zone)
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('targetC')).zone)
        self.assertEqual((),self.state.mana_pool('A'))

    def test_curse_zero_targets_resolves_and_creates_nothing(self):
        self.game();spell=self.state.add_card('spell','catalog:curse-of-the-swine','A',Zone.HAND)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('U','U'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',spell,x_value=0),Payment((('U',2),)));self.drain()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('spell')).zone)
        self.assertFalse(any(o.token for o in self.state.objects()))

    def test_terastodon_tokens_only_for_graveyard_results(self):
        shield=CardProgram('shield','Shield',('Artifact',),keywords=('indestructible',))
        redirect=CardProgram('redirect','Redirect',('Enchantment',),replacements=(ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE,relation='owned'),))
        self.game((shield,redirect));self.state.add_card('redirect','redirect','C',Zone.BATTLEFIELD)
        targets=(self.state.add_card('normal','catalog:forest','B',Zone.BATTLEFIELD),self.state.add_card('shield','shield','B',Zone.BATTLEFIELD),self.state.add_card('redirected','catalog:forest','C',Zone.BATTLEFIELD))
        ref=self.state.add_card('source','catalog:terastodon','A',Zone.HAND)
        self.kernel.execute_for_scenario(ref,'A',(Move('source',Zone.BATTLEFIELD),));r=self.kernel.pending_choice
        indexes=[i for i,o in enumerate(r.options) if o.ref in targets];self.kernel.answer(r.request_id,r.actor,indexes);self.drain()
        r=self.kernel.pending_choice;self.kernel.answer(r.request_id,r.actor,[0]);self.drain()
        tokens=[o for o in self.state.objects() if o.token];self.assertEqual(1,len(tokens));self.assertEqual('B',tokens[0].owner)
        self.assertEqual(3,self.kernel.effective(tokens[0].ref).power)

    def test_magus_pays_x_once_and_untaps_remaining_legal_lands(self):
        self.game();ref=self.state.add_card('magus','catalog:magus-of-the-candelabra','A',Zone.BATTLEFIELD)
        lands=tuple(self.state.add_card('land'+str(i),'catalog:forest','A',Zone.BATTLEFIELD) for i in range(2))
        self.state.add_card('draw','catalog:forest','A',Zone.LIBRARY);self.kernel.begin_turn_for_scenario('A')
        self.state.set_tapped_batch(lands,True);self.state.add_mana('A',('C','C'))
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.quote_activation('bad','A',ref,'untap',lands[:1],x_value=2)
        self.assertEqual(before,self.kernel.snapshot())
        self.kernel.commit_action(self.kernel.quote_activation('untap','A',ref,'untap',lands,x_value=2),Payment((('C',2),)))
        self.assertTrue(self.state.get(ref).tapped);self.assertTrue(self.state.get(lands[0]).tapped)
        self.state.move((ZoneMove(lands[1],Zone.GRAVEYARD),),'scenario_target_departed');self.drain()
        self.assertFalse(self.state.get(lands[0]).tapped);self.assertTrue(self.state.get(ref).tapped)
        self.assertEqual((),self.state.mana_pool('A'))

if __name__=='__main__':unittest.main()
