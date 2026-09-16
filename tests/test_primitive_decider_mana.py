import json
import unittest
from copy import deepcopy
from edh_gauntlet import primitive_actions as actions
from edh_gauntlet.rules_state import Zone,RulesViolation
from edh_gauntlet.primitive_decider_mana import presentation
from edh_gauntlet.primitive_mana_preferences import portfolio_score,profiles,hand_costs
from edh_gauntlet.primitive_autotap import payment
import test_primitive_autotap as auto_tests
import test_primitive_batch_choices as batch_tests


class DeciderManaTests(unittest.TestCase):
    send=batch_tests.ManaBatchTests.send
    main=batch_tests.ManaBatchTests.main
    land=batch_tests.ManaBatchTests.land
    card=auto_tests.AutotapTests.card
    command=auto_tests.AutotapTests.command
    submit=auto_tests.AutotapTests.submit

    def setUp(self):
        batch_tests.ManaBatchTests.setUp(self)
        self.game.config['automatic_decider_mana']=1

    def test_direct_cast_automatic_and_manual_paths_rejected(self):
        cmd=self.command()
        with self.game.transaction() as state:
            state['actors']['Omo']['last_rejection']='Old unrelated target error'
            state['actors']['Omo']['last_rejection_context']={'command':{'kind':'cast'},'commit':self.game.store.committed_head()}
        f=actions.claim(self.game,'Omo');head=self.game.store.committed_head()
        mana={'kind':'activate','source':self.island.to_json(),'ability_id':self.game.kernel.activated_abilities(self.game.kernel.state.get(self.island))[0].ability_id,'targets':[],'x_value':0}
        for bad in (mana,{**cmd,'autotap':{}},{**cmd,'payment':{'mana':{'U':1},'taps':[]}}):
            with self.assertRaises(RulesViolation):actions.submit(self.game,'Omo',f['claim_id'],'bad',bad,'test',{'mode':'hold_full_control'})
            with self.assertRaises(RulesViolation):actions.approve_sequence(self.game,'Omo',f['claim_id'],sequence=[{'id':'bad','command':bad}],rationale='test',scheduler={'mode':'hold_full_control'})
        self.assertEqual(head,self.game.store.committed_head())
        self.submit(cmd)
        self.assertNotIn('last_rejection',self.game.state()['actors']['Omo'])
        self.assertNotIn('last_rejection_context',self.game.state()['actors']['Omo'])
        self.assertEqual(Zone.STACK,self.game.kernel.state.get(self.game.kernel.state.current(cmd['source']['card_id'])).zone)

    def test_accept_planner_mana_but_reject_changed_payment(self):
        f=actions.claim(self.game,'Omo');turn=self.game.state()['actors']['Omo']['turns']
        ability=self.game.kernel.activated_abilities(self.game.kernel.state.get(self.island))[0].ability_id
        cmd={'kind':'activate','source':self.island.to_json(),'ability_id':ability,'targets':[],'x_value':0,'payment':{'mana':{},'taps':[]}}
        step={'id':'mana','seat_turn':turn,'phase':'precombat_main','command':cmd,'rationale':'Planner authored mana.','scheduler':{'mode':'hold_full_control'}}
        with self.game.transaction() as state:state['claim']['plans']['actions']={'id':'p','value':{'action_sequence':[step]}}
        changed=deepcopy(cmd);changed['source']=self.grove.to_json();changed['ability_id']=self.game.kernel.activated_abilities(self.game.kernel.state.get(self.grove))[0].ability_id
        with self.assertRaises(RulesViolation):actions.approve(self.game,'Omo',f['claim_id'],approve_ids=['mana'],overrides={'mana':{'command':changed}})
        actions.approve(self.game,'Omo',f['claim_id'],approve_ids=['mana'])
        self.assertTrue(actions.automatic(self.game));self.assertTrue(self.game.kernel.state.get(self.island).tapped)

    def test_hand_aware_payment_preserves_blue(self):
        cmd=self.command();self.card('brainstorm',Zone.HAND)
        # Existing Island and Grove(colorless) can each pay the Bauble.
        self.submit(cmd)
        self.assertFalse(self.game.kernel.state.get(self.island).tapped)
        self.assertTrue(self.game.kernel.state.get(self.grove).tapped)

    def test_no_opponent_hand_in_preferences(self):
        cmd=self.command();bound={**cmd,'autotap':{},'action_id':'test','revision':self.game.kernel.revision}
        before=payment(self.game.kernel,'Omo',bound,smart=True)
        self.game.kernel.state.add_card('enemy-secret','catalog:counterspell','Elenda',Zone.HAND)
        self.assertEqual(before,payment(self.game.kernel,'Omo',bound,smart=True))


class ManaPresentationTests(unittest.TestCase):
    def test_mana_menu_removed_without_changing_plans_or_original(self):
        mana={'ability_id':'mana','mana_ability':True};normal={'ability_id':'draw'}
        original={'board':{'abilities':[mana,normal]},'action_facts':{'activated_abilities':[mana,normal],'intrinsic_land_mana':[mana]},'plans':{'actions':[mana]}}
        view=presentation(original)
        self.assertEqual([normal],view['board']['abilities'])
        self.assertEqual([normal],view['action_facts']['activated_abilities'])
        self.assertNotIn('intrinsic_land_mana',view['action_facts'])
        self.assertEqual(original['plans'],view['plans']);self.assertEqual(2,len(original['board']['abilities']))

    def test_one_dual_cannot_fund_two_spells(self):
        sources=[(None,[((1,0,0,0,0,0),[]),((0,1,0,0,0,0),[])])]
        self.assertEqual((1,2),portfolio_score([(1,(1,0,0,0,0,0)),(1,(0,1,0,0,0,0))],profiles((0,)*6,sources)))

    def test_prompt_excludes_manual_mana_instructions(self):
        from edh_gauntlet.primitive_host import instructions
        text=instructions('Omo','decider',automatic_mana=True)
        self.assertNotIn('autotap:{reserve:',text)
        self.assertNotIn('payment.mana_actions',text)
        self.assertIn('EXACT_NON_MANA_ID',text)

import test_rules_primitives_resolution_payments as resolution_tests
from edh_gauntlet.rules_adapter import RulesActorAdapter

class AutomaticResolutionTests(unittest.TestCase):
    setUpClass=classmethod(resolution_tests.ResolutionPaymentTests.setUpClass.__func__)
    game=resolution_tests.ResolutionPaymentTests.game
    effect=resolution_tests.ResolutionPaymentTests.effect
    top=resolution_tests.ResolutionPaymentTests.top
    life_window=resolution_tests.ResolutionPaymentTests.life_window

    def test_resolution_payment_bundles_mana_and_replays(self):
        self.game()
        land=self.state.add_card('land','payment-land','A',Zone.BATTLEFIELD)
        rock=self.state.add_card('rock','payment-rock','A',Zone.BATTLEFIELD)
        self.life_window()
        command={'kind':'pay_mana','request_id':self.kernel.mana_payment['id'],'autotap':{},'action_id':'auto-pay','revision':self.kernel.revision}
        before=self.kernel.snapshot()
        command['payment']=payment(self.kernel,'A',command,smart=True);command.pop('autotap')
        RulesActorAdapter(self.kernel)._execute('A',command)
        self.assertIsNone(self.kernel.mana_payment)
        self.assertTrue(self.state.get(land).tapped);self.assertTrue(self.state.get(rock).tapped)
        self.assertEqual(1,len(self.state.objects(Zone.HAND,owner='A')))
        replay=type(self.kernel).restore(before,self.programs)
        RulesActorAdapter(replay)._execute('A',command)
        self.assertEqual(self.kernel.snapshot(),replay.snapshot())

    def test_failed_payment_leaves_live_state_untouched(self):
        self.game();self.state.add_card('land','payment-land','A',Zone.BATTLEFIELD);self.life_window()
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):payment(self.kernel,'A',{'kind':'pay_mana','request_id':self.kernel.mana_payment['id'],'autotap':{},'action_id':'test'},smart=True)
        self.assertEqual(before,self.kernel.snapshot())

from edh_gauntlet.rules_program import CardProgram,CastSpec,CostSpec,ManaCost,ActivatedProgram,AddMana
from edh_gauntlet.rules_state import RulesState
from edh_gauntlet.rules_kernel import RulesKernel

class ManaPreferenceTests(unittest.TestCase):
    def game(self):
        self.state=RulesState(('A','B','C','D'))
        programs=[]
        for color in 'WURG':
            programs.append(CardProgram('land-'+color,'Land '+color,('Land',),activated=(ActivatedProgram('mana',CostSpec(tap_source=True),(AddMana((color,)),),mana_ability=True),)))
            programs.append(CardProgram('spell-'+color,'Spell '+color,('Instant',),cast=CastSpec(CostSpec(mana=ManaCost(symbols=(color,))),timing='instant')))
        programs.append(CardProgram('generic','Generic',('Instant',),cast=CastSpec(CostSpec(mana=ManaCost(generic=1)),timing='instant')))
        self.kernel=RulesKernel(self.state,programs);self.kernel.open_window_for_scenario('A')
        self.serial=0

    def cast(self,ref):
        self.serial+=1
        cmd={'kind':'cast','source':ref.to_json(),'targets':[],'x_value':0,'autotap':{},'action_id':'cast-'+str(self.serial),'revision':self.kernel.revision}
        cmd['payment']=payment(self.kernel,'A',cmd,smart=True);cmd.pop('autotap')
        RulesActorAdapter(self.kernel)._execute('A',cmd)
        return cmd

    def test_preserves_two_different_followup_casts(self):
        self.game()
        lands={c:self.state.add_card('land-'+c,'land-'+c,'A',Zone.BATTLEFIELD) for c in 'UWR'}
        a=self.state.add_card('a','generic','A',Zone.HAND)
        b=self.state.add_card('b','spell-U','A',Zone.HAND)
        c=self.state.add_card('c','spell-W','A',Zone.HAND)
        self.cast(a)
        self.assertTrue(self.state.get(lands['R']).tapped)
        self.assertFalse(self.state.get(lands['U']).tapped)
        self.assertFalse(self.state.get(lands['W']).tapped)
        self.cast(b);self.cast(c)
        self.assertEqual(3,len(self.kernel.stack))

    def test_floating_mana_preserves_color_for_next_card(self):
        self.game();self.state.add_mana('A',('G','R'))
        a=self.state.add_card('a','generic','A',Zone.HAND)
        b=self.state.add_card('b','spell-G','A',Zone.HAND)
        cmd=self.cast(a);self.assertEqual({'R':1},cmd['payment']['mana'])
        self.cast(b);self.assertEqual((),self.state.mana_pool('A'))

    def test_tagged_mana_selected_without_decider_fields(self):
        self.game();source=self.state.add_card('source','land-R','A',Zone.BATTLEFIELD)
        self.state.add_special_mana('A',('R',),'copy',self.state.get(source))
        tag=next(iter(self.state.mana_tags('A')))
        card=self.state.add_card('a','generic','A',Zone.HAND)
        cmd=self.cast(card)
        self.assertEqual([tag],cmd['payment']['tagged_mana'])
        self.assertFalse(self.state.get(source).tapped)
