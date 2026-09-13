"""Exile-until-leaves cards and immediate, simultaneous, resumable returns."""
import json
import unittest
from dataclasses import replace
from pathlib import Path

from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState, Zone, ZoneMove, RulesViolation, PlayerRef
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter
from edh_gauntlet.rules_bundle import load_reviewed, source_facts
from edh_gauntlet.catalog import load_catalog


class ExileDurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        reviewed=load_reviewed(cls.root)
        draft=json.loads((cls.root/'data/rules/draft_cards.json').read_text(encoding='utf-8'))
        cls.rows={r['card_id']:r for r in draft['drafts']}
        cls.cards={key:validate(decode(cls.rows[key]['program'])) for key in ('grasp-of-fate','prayer-of-binding')}
        cls.base=tuple(r['program'] for r in reviewed.values())+tuple(cls.cards.values())

    def game(self,key='prayer-of-binding',*,players=('A','B','C','D'),extra=(),body=None):
        self.key=key
        body=body or CardProgram('body','Body',('Creature',),power=2,toughness=3)
        self.answer=CardProgram('answer','Removal fixture',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD)),spell_effects=(Move('target',Zone.HAND),))
        aura=CardProgram('aura','Aura fixture',('Enchantment',),subtypes=('Aura',),enchant=Selector(Zone.BATTLEFIELD,('Creature',)))
        self.programs=self.base+(body,self.answer,aura)+extra
        self.state=RulesState(players);self.kernel=RulesKernel(self.state,self.programs)
        self.kernel.open_window_for_scenario('A')
        self.bodies={p:self.state.add_card('body-'+p,'body',p,Zone.BATTLEFIELD) for p in players}
        self.source=self.state.add_card('source',self.cards[key].definition_id,'A',Zone.HAND)

    def current(self,key='source'):return self.state.get(self.state.current(key))

    def resolve_top(self):
        for _ in self.state.live_players:self.kernel.pass_priority(self.kernel.priority)
        return self.kernel.pending_choice

    def targets(self,*refs):
        q=self.kernel.pending_choice;self.assertIsNotNone(q);self.assertEqual('trigger_targets',q.kind)
        indexes=[next(i for i,o in enumerate(q.options) if o.ref==ref) for ref in refs]
        self.kernel.answer(q.request_id,q.actor,indexes)

    def enter(self,*refs):
        self.kernel.enter(self.source)
        self.targets(*refs);self.resolve_top()

    def remove(self,ref=None,program=None,action='remove'):
        if self.kernel.priority is None:self.kernel.open_window_for_scenario('A')
        actor=self.kernel.priority
        source=self.state.add_card(action,program or 'answer',actor,Zone.HAND)
        self.kernel.commit_action(self.kernel.quote_cast(action,actor,source,(ref or self.current().ref,)),Payment())
        return self.resolve_top()

    def test_source_facts_and_card_metadata(self):
        catalog={c.card_id:c for c in load_catalog(self.root/'data/catalog/cards.json')}
        for key,p in self.cards.items():
            self.assertEqual(source_facts(catalog[key]),self.rows[key]['source_facts'])
            self.assertEqual(p,validate(decode(encode(p))))
            self.assertEqual(1,len(p.abilities));self.assertIsInstance(p.abilities[0].effects[0],ExileUntilSourceLeaves)
            self.assertIsNone(p.abilities[0].source_must_remain)

    def test_prayer_can_cast_on_opponents_turn_and_gains_life_without_target(self):
        self.game();self.kernel.open_window_for_scenario('B',priority_actor='A')
        self.state.add_mana('A',('C','C','C','W'))
        self.kernel.commit_action(self.kernel.quote_cast('prayer','A',self.source),Payment((('C',3),('W',1))))
        self.resolve_top();self.targets();self.resolve_top()
        self.assertEqual(42,self.state.life('A'));self.assertEqual({},self.kernel.exile_durations)
        self.assertEqual(Zone.BATTLEFIELD,self.current().zone)

    def test_grasp_normal_cast_and_one_optional_target_per_opponent(self):
        self.game('grasp-of-fate',players=('A','B','C','D','E','F'))
        other=self.state.add_card('second-B','body','B',Zone.BATTLEFIELD)
        self.state.add_card('land','catalog:forest','B',Zone.BATTLEFIELD)
        self.state.add_mana('A',('C','W','W'))
        self.kernel.commit_action(self.kernel.quote_cast('grasp','A',self.source),Payment((('C',1),('W',2))))
        self.resolve_top();q=self.kernel.pending_choice
        self.assertEqual(5,q.maximum);self.assertEqual(0,q.minimum);self.assertTrue(q.groups)
        self.assertNotIn('land',{o.ref.card_id for o in q.options});self.assertNotIn('body-A',{o.ref.card_id for o in q.options})
        bad=[next(i for i,o in enumerate(q.options) if o.ref==r) for r in (other,self.bodies['B'])]
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.answer(q.request_id,'A',bad)
        self.assertEqual(before,self.kernel.snapshot())
        self.targets(*(self.bodies[p] for p in ('B','C','D','E','F')));self.resolve_top()
        self.assertTrue(all(self.current('body-'+p).zone==Zone.EXILE for p in ('B','C','D','E','F')))
        self.remove();self.assertTrue(all(self.current('body-'+p).zone==Zone.BATTLEFIELD for p in ('B','C','D','E','F')))

    def test_prayer_source_leaving_before_trigger_prevents_exile_but_not_life(self):
        self.game();self.kernel.enter(self.source);self.targets(self.bodies['B'])
        self.remove();self.assertEqual(Zone.BATTLEFIELD,self.current('body-B').zone)
        self.resolve_top();self.assertEqual(42,self.state.life('A'));self.assertEqual({},self.kernel.exile_durations)

    def test_grasp_source_leaving_before_trigger_does_not_exile_targets(self):
        self.game('grasp-of-fate');self.kernel.enter(self.source);self.targets(self.bodies['B'],self.bodies['C'])
        self.remove();self.resolve_top()
        self.assertEqual({},self.kernel.exile_durations)
        self.assertEqual(Zone.BATTLEFIELD,self.current('body-B').zone);self.assertEqual(Zone.BATTLEFIELD,self.current('body-C').zone)

    def test_prayer_illegal_chosen_target_prevents_life_but_zero_targets_does_not(self):
        self.game();self.kernel.enter(self.source);self.targets(self.bodies['B'])
        self.remove(self.bodies['B']);self.resolve_top()
        self.assertEqual(40,self.state.life('A'));self.assertEqual({},self.kernel.exile_durations)

    def test_grasp_rechecks_controller_and_resolves_remaining_legal_targets(self):
        self.game('grasp-of-fate');self.kernel.enter(self.source);self.targets(self.bodies['B'],self.bodies['C'])
        self.state.change_control(self.bodies['B'],'C');self.resolve_top()
        self.assertEqual(Zone.BATTLEFIELD,self.current('body-B').zone)
        self.assertEqual(Zone.EXILE,self.current('body-C').zone)

    def test_return_uses_owner_and_creates_a_new_incarnation_without_counters(self):
        self.game();stolen=self.state.add_card('stolen','body','A',Zone.BATTLEFIELD,controller='B')
        self.state.add_counters(stolen,'+1/+1',3);self.enter(stolen)
        exiled=self.current('stolen').ref;self.assertNotEqual(stolen,exiled)
        self.remove();returned=self.current('stolen')
        self.assertEqual(Zone.BATTLEFIELD,returned.zone);self.assertEqual('A',returned.controller)
        self.assertEqual((),returned.counters);self.assertNotEqual(exiled,returned.ref)

    def test_return_is_immediate_before_next_instruction_and_has_no_stack_trigger(self):
        follow=replace(self.answer if hasattr(self,'answer') else CardProgram('temp','Temp',('Instant',)),
            definition_id='follow',name='Return then destroy',cast=CastSpec(CostSpec(),timing='instant'),
            spell_targets=TargetSpec(Selector(Zone.BATTLEFIELD)),
            spell_effects=(Move('target',Zone.HAND),
                SelectAll(Selector(Zone.BATTLEFIELD,('Creature',),relation='opponent_controlled'),(Destroy('selected'),))))
        self.game(extra=(follow,));self.enter(self.bodies['B'])
        self.remove(program='follow')
        self.assertEqual(Zone.GRAVEYARD,self.current('body-B').zone)
        self.assertFalse(any(f.get('ability_id')=='return-exile' for f in self.kernel.stack))
        self.assertEqual({},self.kernel.exile_durations)

    def test_simultaneous_source_departures_return_all_cards_in_one_batch(self):
        wipe=CardProgram('wipe','Wipe enchantments',('Instant',),cast=CastSpec(CostSpec(),timing='instant'),
            spell_effects=(SelectAll(Selector(Zone.BATTLEFIELD,('Enchantment',)),(Destroy('selected'),)),))
        self.game(extra=(wipe,));self.enter(self.bodies['B'])
        second=self.state.add_card('second',self.cards['prayer-of-binding'].definition_id,'A',Zone.HAND)
        self.kernel.enter(second);self.targets(self.bodies['C']);self.resolve_top()
        self.kernel.open_window_for_scenario('A');ref=self.state.add_card('wipe','wipe','A',Zone.HAND)
        self.kernel.commit_action(self.kernel.quote_cast('wipe','A',ref),Payment());self.resolve_top()
        returned=[e for e in self.state.events if e.cause=='exile_duration_ended']
        self.assertEqual(2,len(returned));self.assertEqual(1,len({e.batch for e in returned}))
        self.assertEqual({'body-B','body-C'},{e.after.ref.card_id for e in returned})

    def test_phasing_and_control_changes_do_not_end_the_exile(self):
        self.game();self.enter(self.bodies['B']);source=self.current().ref
        self.state.phase(source,True);self.kernel.advance()
        self.assertEqual(Zone.EXILE,self.current('body-B').zone)
        self.state.phase(source,False);self.state.change_control(source,'C');self.kernel.advance()
        self.assertEqual(Zone.EXILE,self.current('body-B').zone)
        self.remove();self.assertEqual(Zone.BATTLEFIELD,self.current('body-B').zone)

    def test_source_copy_change_does_not_erase_existing_return_obligation(self):
        self.game();self.enter(self.bodies['B'])
        ref=self.current().ref
        # Isolated state fixture: the exact source survives a definition change.
        self.state._objects[ref.card_id]=replace(self.state.get(ref),copied_definition='body')
        self.remove();self.assertEqual(Zone.BATTLEFIELD,self.current('body-B').zone)

    def test_exiled_token_ceases_and_cannot_return(self):
        self.game();token=self.state.add_card('token','body','B',Zone.BATTLEFIELD,token=True)
        self.enter(token);self.assertNotIn('token',{o.ref.card_id for o in self.state.objects()})
        self.remove();self.assertNotIn('token',{o.ref.card_id for o in self.state.objects()})

    def test_moved_exile_card_and_new_exile_incarnation_are_not_recaptured(self):
        self.game();self.enter(self.bodies['B']);ref=self.current('body-B').ref
        self.state.move((ZoneMove(ref,Zone.HAND,'B'),),'fixture')
        self.state.move((ZoneMove(self.state.current('body-B'),Zone.EXILE,'B'),),'fixture')
        self.remove();self.assertEqual(Zone.EXILE,self.current('body-B').zone)

    def test_commander_can_leave_exile_and_is_not_returned_from_command(self):
        self.game();ref=self.state.add_card('commander','body','B',Zone.BATTLEFIELD,commander=True)
        self.kernel.enter(self.source);self.targets(ref);self.resolve_top()
        q=self.kernel.pending_choice;self.assertEqual('commander_sba',q.kind)
        self.kernel.answer(q.request_id,'B',[next(i for i,o in enumerate(q.options) if o.key=='command')])
        self.remove();self.assertEqual(Zone.COMMAND,self.current('commander').zone)

    def test_returned_aura_choice_checkpoint_and_actor_replay(self):
        self.game()
        aura=self.state.add_card('aura','aura','B',Zone.HAND)
        self.kernel.enter(aura)
        q=self.kernel.pending_choice;self.assertEqual('aura_attachment',q.kind)
        self.kernel.answer(q.request_id,q.actor,[next(i for i,o in enumerate(q.options) if o.ref==self.bodies['B'])])
        self.enter(self.current('aura').ref);self.kernel.open_window_for_scenario('A')
        remove=self.state.add_card('remove','answer','A',Zone.HAND)
        adapter=RulesActorAdapter(self.kernel)
        adapter.submit('A',{'kind':'cast','revision':self.kernel.revision,'action_id':'remove','source':remove.to_json(),
            'targets':[self.current().ref.to_json()],'x_value':0,'payment':{'mana':{},'taps':[]}})
        for _ in self.state.live_players:adapter.submit(self.kernel.priority,{'kind':'pass','revision':self.kernel.revision})
        q=self.kernel.pending_choice;self.assertEqual('aura_attachment',q.kind);self.assertEqual('B',q.actor)
        self.assertEqual(Zone.HAND,self.current().zone);self.assertEqual(Zone.EXILE,self.current('aura').zone)
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        indexes=[next(i for i,o in enumerate(q.options) if o.ref==self.bodies['C'])]
        adapter.submit('B',{'kind':'answer','revision':self.kernel.revision,'request_id':q.request_id,'indexes':indexes})
        restored.answer(q.request_id,'B',indexes)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual(self.kernel.snapshot(),RulesActorAdapter.replay(adapter.archive(),self.programs).kernel.snapshot())
        self.assertEqual(self.bodies['C'],self.current('aura').attached_to)

    def test_exile_and_return_replacements_only_record_actual_exile_incarnations(self):
        redirect=CardProgram('redirect','Redirect exile',('Enchantment',),
            replacements=(ZoneReplacement('redirect',Zone.EXILE,Zone.GRAVEYARD,from_zone=Zone.BATTLEFIELD),))
        self.game(extra=(redirect,));self.state.add_card('redirect','redirect','C',Zone.BATTLEFIELD)
        self.enter(self.bodies['B']);self.assertEqual({},self.kernel.exile_durations)
        self.assertEqual(Zone.GRAVEYARD,self.current('body-B').zone);self.assertEqual(42,self.state.life('A'))

    def test_departed_source_owner_returns_surviving_players_cards(self):
        self.game();self.enter(self.bodies['B'])
        self.kernel._depart_players(('A',));self.kernel.advance()
        self.assertEqual(Zone.BATTLEFIELD,self.current('body-B').zone);self.assertEqual('B',self.current('body-B').controller)
        self.assertEqual({},self.kernel.exile_durations)

    def test_checkpoint_layout_and_invalid_duration_programs(self):
        self.game();checkpoint=self.kernel.snapshot()
        self.assertEqual(114,checkpoint['schema'])
        checkpoint['schema']=113
        with self.assertRaises(RulesViolation):RulesKernel.restore(checkpoint,self.programs)
        with self.assertRaises(RulesViolation):
            validate(CardProgram('bad','Bad',('Instant',),spell_effects=(ExileUntilSourceLeaves('source'),)))
        with self.assertRaises(RulesViolation):
            validate(CardProgram('bad','Bad',('Enchantment',),activated=(ActivatedProgram('bad',CostSpec(),
                (ExileUntilSourceLeaves('target'),),TargetSpec(players='opponents')),)))
        with self.assertRaises(RulesViolation):
            validate(CardProgram('bad','Bad',('Enchantment',),activated=(ActivatedProgram('bad',CostSpec(),
                (ExileUntilSourceLeaves('source'),),zone=Zone.HAND),)))
        with self.assertRaises(RulesViolation):
            validate(CardProgram('bad','Bad',('Instant',),spell_targets=TargetSpec(Selector(Zone.STACK),maximum=None)))
