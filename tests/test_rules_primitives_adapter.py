"""Authenticated-seat commands, incremental prefix verification and safe stops."""
import unittest
from copy import deepcopy
from edh_gauntlet.rules_adapter import RulesActorAdapter,AcceptedTransitionError
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_program import (CardProgram,CostSpec,ManaCost,CastSpec,GainLife,
    ActivatedProgram,ChooseMana,SearchLibrary,Selector,Move)
from edh_gauntlet.rules_kernel import RulesKernel


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.programs=(CardProgram('spell','Spell',('Instant',),cast=CastSpec(CostSpec(ManaCost(0,('G',))),'instant'),spell_effects=(GainLife(2),)),
            CardProgram('rock','Rock',('Artifact',),activated=(ActivatedProgram('mana',CostSpec(tap_source=True),(ChooseMana((('G',),('U',))),),mana_ability=True),)),
            CardProgram('land','Land',('Land',)))
        self.state=RulesState(('A','B'));self.rock=self.state.add_card('rock','rock','A',Zone.BATTLEFIELD)
        self.spell=self.state.add_card('spell','spell','A',Zone.HAND)
        self.hidden=self.state.add_card('hidden','spell','B',Zone.HAND)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.open_window_for_scenario('A')
        self.adapter=RulesActorAdapter(self.kernel)

    def command(self,kind,**fields):return {'kind':kind,'revision':self.kernel.revision,**fields}

    def activate(self):
        return self.command('activate',action_id='mana',source=self.rock.to_json(),targets=[],x_value=0,
                            ability_id='mana',payment={'mana':{},'taps':[]})

    def produce(self):
        packet=self.adapter.submit('A',self.activate());request=packet['decision']['choice']
        self.adapter.submit('A',self.command('answer',request_id=request['request_id'],indexes=[0]))

    def test_one_command_casting_payment_and_exact_replay(self):
        self.produce()
        self.adapter.submit('A',self.command('cast',action_id='cast',source=self.spell.to_json(),targets=[],x_value=0,payment={'mana':{'G':1},'taps':[]}))
        self.adapter.submit('A',self.command('pass'));self.adapter.submit('B',self.command('pass'))
        self.assertEqual(42,self.state.life('A'));self.assertEqual(5,len(self.adapter.records))
        replayed=RulesActorAdapter.replay(self.adapter.archive(),self.programs)
        self.assertEqual(self.kernel.snapshot(),replayed.kernel.snapshot())
        for actor in self.state.players:self.assertEqual(self.adapter.packet(actor),replayed.packet(actor))

    def test_authenticated_actor_cannot_be_replaced_in_payload(self):
        before=self.kernel.snapshot();command=self.activate();command['actor']='A'
        with self.assertRaises(RulesViolation):self.adapter.submit('B',command)
        with self.assertRaises(RulesViolation):self.adapter.submit('B',self.activate())
        self.assertEqual(before,self.kernel.snapshot());self.assertEqual([],self.adapter.records)

    def test_hidden_reference_and_unknown_reference_have_same_error(self):
        messages=[]
        for ref in (self.hidden.to_json(),{'card_id':'does-not-exist','incarnation':0}):
            command=self.command('cast',action_id='bad',source=ref,targets=[],x_value=0,payment={'mana':{},'taps':[]})
            with self.assertRaises(RulesViolation) as raised:self.adapter.submit('A',command)
            messages.append(str(raised.exception))
        self.assertEqual(messages[0],messages[1]);self.assertEqual([],self.adapter.records)

    def test_stale_and_duplicate_submissions_do_not_pay_again(self):
        command=self.activate();self.adapter.submit('A',command);before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.adapter.submit('A',command)
        self.assertEqual(before,self.kernel.snapshot());self.assertEqual(1,len(self.adapter.records))

    def test_bad_payment_and_wrong_choice_actor_have_no_journal_entries(self):
        before=self.kernel.snapshot()
        command=self.command('cast',action_id='bad',source=self.spell.to_json(),targets=[],x_value=0,payment={'mana':{},'taps':[]})
        with self.assertRaises(RulesViolation):self.adapter.submit('A',command)
        self.assertEqual(before,self.kernel.snapshot());self.assertEqual([],self.adapter.records)
        self.adapter.submit('A',self.activate());request=self.kernel.pending_choice
        with self.assertRaises(RulesViolation):self.adapter.submit('B',self.command('answer',request_id=request.request_id,indexes=[0]))
        self.assertEqual(1,len(self.adapter.records))

    def test_caller_mutation_cannot_change_journal_or_initial_state(self):
        command=self.activate();self.adapter.submit('A',command);archive=self.adapter.archive()
        command['payment']['mana']['R']=9;archive['records'][0]['command']['kind']='pass';archive['initial'].clear()
        replayed=RulesActorAdapter.replay(self.adapter.archive(),self.programs)
        self.assertEqual(self.kernel.snapshot(),replayed.kernel.snapshot())

    def test_changed_command_hash_and_final_snapshot_are_detected(self):
        self.produce();archive=self.adapter.archive()
        for field in ('command','sha256','final'):
            changed=deepcopy(archive)
            if field=='command':changed['records'][1]['command']['indexes']=[1]
            elif field=='sha256':changed['records'][0]['sha256']='forged'
            else:changed['final_sha256']='forged'
            with self.assertRaises(RulesViolation):RulesActorAdapter.replay(changed,self.programs)

    def test_private_archive_is_never_embedded_in_packet(self):
        self.produce();packet=self.adapter.packet('A')
        self.assertNotIn('initial',packet);self.assertNotIn('records',packet);self.assertNotIn('semantic_events',packet)

    def test_search_choice_uses_same_command_protocol(self):
        self.state.add_card('find','land','A',Zone.LIBRARY)
        self.kernel.execute_for_scenario(self.rock,'A',(SearchLibrary(Selector(Zone.LIBRARY,relation='owned'),Zone.HAND),))
        adapter=RulesActorAdapter(self.kernel);request=adapter.packet('A')['decision']['choice']
        adapter.submit('A',self.command('answer',request_id=request['request_id'],indexes=[0]))
        restored=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.assertEqual(self.kernel.snapshot(),restored.kernel.snapshot())
        self.assertNotIn('library_search',adapter.packet('A'))

    def test_production_factory_stays_closed(self):
        with self.assertRaisesRegex(RulesViolation,'not admitted for production'):RulesActorAdapter.for_production(self.kernel)

    def test_failure_after_answer_acceptance_is_sealed_and_replayable(self):
        from edh_gauntlet.rules_program import May,Select
        # Inject an interpreter failure after accepting May, before any event
        # fires. Failure handling must not depend on preserving a rules defect.
        self.kernel.execute_for_scenario(self.rock,'A',(May((Select(Selector(Zone.BATTLEFIELD,types=('Creature',)),1,1,(GainLife(1),)),)),))
        adapter=RulesActorAdapter(self.kernel);request=adapter.packet('A')['decision']['choice']
        from unittest.mock import patch
        with patch.object(RulesKernel,'_insert',side_effect=RulesViolation('Injected execution failure')):
            with self.assertRaises(AcceptedTransitionError):
                adapter.submit('A',self.command('answer',request_id=request['request_id'],indexes=[0]))
        self.assertTrue(adapter.failed);self.assertEqual(1,len(adapter.records))
        self.assertEqual('engine_stopped',adapter.packet('A')['decision']['kind'])
        before=self.kernel.snapshot()
        with self.assertRaises(AcceptedTransitionError):adapter.submit('A',self.command('pass'))
        self.assertEqual(before,self.kernel.snapshot())
        with patch.object(RulesKernel,'_insert',side_effect=RulesViolation('Injected execution failure')):
            restored=RulesActorAdapter.replay(adapter.archive(),self.programs)
        self.assertEqual(adapter.archive(),restored.archive())

    def test_event_cursor_returns_only_new_immutable_events(self):
        from edh_gauntlet.rules_state import ZoneMove
        cursor=self.state.event_count
        self.state.move((ZoneMove(self.spell,Zone.GRAVEYARD),),'fixture')
        delta=self.state.events_since(cursor)
        self.assertEqual(1,len(delta));self.assertEqual(self.spell,delta[0].before.ref)
        self.assertEqual((),self.state.events_since(self.state.event_count))
        for bad in (-1,True,self.state.event_count+1):
            with self.assertRaises(RulesViolation):self.state.events_since(bad)


class AdapterCombatTests(unittest.TestCase):
    def test_attack_block_and_damage_batches_share_replay_protocol(self):
        from edh_gauntlet.rules_combat import uid
        state=RulesState(('A','B'))
        programs=(CardProgram('attacker','Attacker',('Creature',),power=5,toughness=5,keywords=('trample',)),
                  CardProgram('blocker','Blocker',('Creature',),power=2,toughness=2),CardProgram('land','Land',('Land',)))
        attacker=state.add_card('attack','attacker','A',Zone.BATTLEFIELD)
        blockers=[state.add_card('block'+str(i),'blocker','B',Zone.BATTLEFIELD) for i in range(2)]
        state.add_card('draw','land','A',Zone.LIBRARY)
        kernel=RulesKernel(state,programs);kernel.begin_turn_for_scenario('A')
        for _ in range(8):kernel.pass_priority(kernel.priority)
        adapter=RulesActorAdapter(kernel)
        def submit(actor,kind,**fields):return adapter.submit(actor,{'kind':kind,'revision':kernel.revision,**fields})
        self.assertEqual('declare_attackers',adapter.packet('A')['decision']['kind'])
        submit('A','attack',attackers=[{'source':attacker.to_json(),'defender':'B'}])
        submit('A','pass');submit('B','pass')
        self.assertEqual('declare_blockers',adapter.packet('B')['decision']['kind'])
        self.assertEqual('waiting',adapter.packet('A')['decision']['kind'])
        submit('B','block',assignments={uid(attacker):[uid(ref) for ref in blockers]})
        submit('A','pass');submit('B','pass')
        self.assertEqual('combat_damage',adapter.packet('A')['decision']['kind'])
        submit('A','damage',assignments={uid(attacker):{'blockers':{uid(ref):2 for ref in blockers},'defender':1}})
        self.assertEqual(39,state.life('B'))
        restored=RulesActorAdapter.replay(adapter.archive(),programs)
        self.assertEqual(kernel.snapshot(),restored.kernel.snapshot())
