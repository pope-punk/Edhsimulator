"""Pilot-friendly aliases must preserve exact engine authority and actor visibility."""
import json
import unittest
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
from edh_gauntlet.primitive_pilot_document import Document, Labels
from edh_gauntlet.primitive_action_menu import freeze
from edh_gauntlet.primitive_inspection import freeze as knowledge
from edh_gauntlet.rules_state import RulesViolation, Zone
from edh_gauntlet.paths import PROJECT_ROOT

CATALOG=PROJECT_ROOT/'data/catalog/cards.json'
REF={'card_id':'private-long-card-identity','incarnation':3}
SPELL={'card_id':'ghalta-exact-identity','incarnation':9}


def card(name='Remand',ref=None,**extra):
    return {'ref':ref or deepcopy(REF),'name':name,'types':['Instant'],'zone':'hand','owner':'Reaminatour',
            'controller':'Reaminatour','token':False,'tapped':False,'damage':0,'power':None,'toughness':None,**extra}


def packet():
    return {'actor':'Reaminatour','claim_id':'private-claim-id','revision':'738:1554',
            'board':{'decision':{'kind':'priority','actor':'Reaminatour'},'hand':[card()],
                     'stack':[{'id':'frame-235','kind':'spell','source':SPELL,'name':'Ghalta, Primal Hunger','controller':'Minsc & Boo'}]},
            '_action_menu':[{'label':'Cast Remand','command':{'kind':'cast','source':REF},'target_candidates':[SPELL]}]}


class DocumentTests(unittest.TestCase):
    def test_spell_alias_resolves_source_not_stack_frame(self):
        d=Document(CATALOG);text=d.render(packet(),'decider')
        result=d.labels.decode({'command':{'action':'A1','target':'S1'},'rationale':'Test'})
        self.assertEqual({'kind':'cast','source':REF,'targets':[SPELL],'x_value':0},result['command'])
        self.assertNotIn('frame-235',text);self.assertNotIn('private-long-card-identity',text)
        self.assertNotIn('738:1554',text);self.assertNotIn('private-claim-id',text)
        self.assertIn('Counter target spell',text)
        self.assertLess(text.index('## Actions'),text.index('## Current board'))

    def test_old_action_label_rejected_and_old_object_never_rebound(self):
        d=Document(CATALOG);d.render(packet(),'decider')
        p=packet();p['board']['hand'][0]['ref']={**REF,'incarnation':4}
        p['_action_menu'][0]['command']['source']={**REF,'incarnation':4}
        next_doc=Document(CATALOG,d.labels);next_doc.render(p,'decider')
        with self.assertRaisesRegex(RulesViolation,'expired'):next_doc.labels.command({'action':'A1'})
        self.assertEqual(REF,next_doc.labels.decode('C1'))
        self.assertEqual(4,next_doc.labels.command({'action':'A2'})['source']['incarnation'])

    def test_grouping_preserves_stolen_owner_multitype_and_meaningful_zero(self):
        p=packet();p['board']['zones']={'battlefield':{'Elenda':[card(name='Test token',types=['Creature','Enchantment'],zone='battlefield',controller='Elenda',power=0,toughness=1,token=True)]}}
        d=Document(CATALOG);text=d.render(p,'decider')
        self.assertIn('Elenda’s battlefield — Enchantment Creatures',text)
        self.assertIn('"owner":"Reaminatour"',text);self.assertIn('"power":0',text)
        self.assertNotIn('"damage":0',text);self.assertNotIn('"token":false',text)
        self.assertNotIn('"zone":"battlefield"',text)

    def test_planner_ids_guards_batches_and_prose_round_trip(self):
        labels=Labels()
        plan={'id':'proposal-hash','value':{'action_sequence':[{'id':'step-hash','command':{'kind':'cast','source':REF,'targets':[],'x_value':0},'rationale':'Full original prose.'}]}}
        shown=labels.encode(plan);step=shown['value']['action_sequence'][0]['id']
        self.assertEqual(['step-hash'],labels.decode({'batch':{'approve_ids':[step]}})['batch']['approve_ids'])
        label=labels.label(REF,'C')
        self.assertEqual(REF['card_id'],labels.decode({'owned_card':label,'zone':'battlefield'})['owned_card'])
        self.assertEqual({'rationale':label},labels.decode({'rationale':label}))
        self.assertEqual(plan,labels.decode(shown))

    def test_aliases_never_replace_schema_discriminants(self):
        labels=Labels();labels.label('cast');labels.label('sacrifice')
        value={'kind':'cast','payment':{'zone_costs':{'sacrifice':[REF]}},
               'cost':{'cost_id':'sacrifice','kind':'sacrifice'}}
        encoded=labels.encode(value)
        self.assertEqual('cast',encoded['kind'])
        self.assertEqual('sacrifice',encoded['cost']['kind'])
        self.assertEqual(value,labels.decode(encoded))

    def test_menu_identity_cannot_be_overridden(self):
        d=Document(CATALOG);d.render(packet(),'decider')
        with self.assertRaisesRegex(RulesViolation,'identity'):d.labels.command({'action':'A1','source':'S1'})

    def test_diplomat_document_does_not_add_private_cards_or_action_menu(self):
        p={'board':{'stack':[],'zones':{}},'plans':{'long_term':{'value':{'long_term_plan':'Retain the full authorized plan.'}}}}
        text=Document(CATALOG).render(p,'diplomacy')
        self.assertNotIn('Remand',text);self.assertNotIn('## Actions',text)
        self.assertIn('Retain the full authorized plan.',text)


class MenuIntegrationTests(unittest.TestCase):
    def test_remand_target_and_payment_status_are_separate(self):
        # Offline fixture: real catalog definitions, no live run or pilot decisions.
        from edh_gauntlet.rules_bundle import load_reviewed
        from edh_gauntlet.rules_state import RulesState
        from edh_gauntlet.rules_kernel import RulesKernel
        from edh_gauntlet.rules_casting import Payment
        from edh_gauntlet.rules_adapter import RulesActorAdapter
        from collections import Counter
        programs=load_reviewed(PROJECT_ROOT)
        state=RulesState(('Reaminatour','Minsc & Boo'))
        remand=state.add_card('remand','catalog:remand','Reaminatour',Zone.HAND)
        ghalta=state.add_card('ghalta','catalog:ghalta-primal-hunger','Minsc & Boo',Zone.HAND)
        state.add_card('clearing','catalog:silent-clearing','Reaminatour',Zone.BATTLEFIELD)
        state.add_card('orchard','catalog:exotic-orchard','Reaminatour',Zone.BATTLEFIELD)
        kernel=RulesKernel(state,tuple(v['program'] for v in programs.values()))
        kernel.open_window_for_scenario('Minsc & Boo')
        q=kernel.quote_cast('fixture-ghalta','Minsc & Boo',ghalta)
        pool=Counter(q.cost.mana.symbols);pool['C']+=q.cost.mana.generic
        state.add_mana('Minsc & Boo',tuple(c for c,n in pool.items() for _ in range(n)))
        q=kernel.quote_cast('fixture-ghalta','Minsc & Boo',ghalta)
        kernel.commit_action(q,Payment(tuple(pool.items())))
        kernel.pass_priority('Minsc & Boo')
        adapter=RulesActorAdapter(kernel);campaign=SimpleNamespace(kernel=kernel,store=adapter)
        board=adapter.packet('Reaminatour')
        p={'board':board,'_knowledge':knowledge(campaign,'Reaminatour',board)}
        before=kernel.snapshot();p['_action_menu']=freeze(campaign,'Reaminatour',p)
        self.assertEqual(before,kernel.snapshot())
        row=next(r for r in p['_action_menu'] if r['label']=='Cast Remand')
        self.assertEqual([state.current('ghalta').to_json()],row['target_candidates'])
        self.assertIn('Automatic payment not established',row['availability'])
        self.assertTrue(all(not a.mana_ability for r in p['_action_menu'] if r['command'].get('kind')=='activate'
            for a in kernel.activated_abilities(state.get(__import__('edh_gauntlet.rules_state',fromlist=['ObjectRef']).ObjectRef.from_json(r['command']['source']))) if a.ability_id==r['command']['ability_id']))
        state.add_mana('Reaminatour',('U','C'))
        p['_action_menu']=freeze(campaign,'Reaminatour',p)
        row=next(r for r in p['_action_menu'] if r['label']=='Cast Remand')
        self.assertIn('automatic mana checked',row['availability'])
        self.assertIn('changed parameters are rechecked',row['availability'])
        d=Document(CATALOG);d.render(p,'decider')
        action=next(a for a,c in d.labels.actions.items() if c.get('source')==remand.to_json())
        command=d.labels.command({'action':action,'target':'S1'})
        from edh_gauntlet.primitive_autotap import payment
        command.update(action_id='fixture-remand',revision=kernel.revision)
        command['payment']=payment(kernel,'Reaminatour',{**command,'autotap':{}})
        adapter.submit('Reaminatour',command)
        self.assertEqual('Remand',adapter.packet('Reaminatour')['stack'][0]['name'])


class DocumentHostTests(unittest.TestCase):
    def setUp(self):
        from tempfile import TemporaryDirectory
        from edh_gauntlet.primitive_campaign import PrimitiveCampaign
        from edh_gauntlet.primitive_host import PrimitiveRunner
        from test_primitive_host import FakeServer
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.game=PrimitiveCampaign._create(Path(self.tmp.name)/'game',seed=93,starting_player='Omo')
        self.addCleanup(self.game.close)
        self.server=FakeServer();self.runner=PrimitiveRunner(self.game,self.server)
        self.addCleanup(self.runner.timing.close)

    def test_fresh_host_accepts_alias_and_records_original_exact_command(self):
        self.runner.pump();thread=self.runner.lanes[('Omo','decider')]
        sent=next(p for m,p in reversed(self.server.calls) if m=='turn/start')['input'][0]['text']
        self.assertTrue(sent.startswith('# Pilot working document'))
        self.assertNotIn('action_facts',sent)
        request=self.game.kernel.pending_choice.request_id
        self.runner.handle({'id':'answer','method':'item/tool/call','params':{
            'threadId':thread,'turnId':self.runner.running[thread],'tool':'edh_act',
            'arguments':{'command':{'action':'A1','indexes':[0]},'rationale':'Offline test keep.',
                         'scheduler':{'mode':'hold_full_control'}}}})
        self.assertIn(thread,self.runner.waiting)
        record=self.game.store._adapter.records[-1]['command']
        self.assertEqual(request,record['request_id']);self.assertEqual('answer',record['kind'])
        self.assertNotIn('action',record)

    def test_inspection_schema_accepts_alias_only_for_planners(self):
        from edh_gauntlet.primitive_host import schemas
        for role in ('short_term_planner','long_term_planner'):
            schema=schemas(role,pilot_document=True)[0]
            self.assertIn('Current C/S object label',json.dumps(schema))
        for role in ('decider','diplomacy'):
            self.assertNotIn('edh_inspect',json.dumps(schemas(role,pilot_document=True)))

    def test_unchanged_sections_only_after_successful_delivery_and_fresh_context_full(self):
        p=packet();d=Document(CATALOG);first=d.render(p,'decider')
        warm=Document(CATALOG,d.labels);second=warm.render(p,'decider')
        self.assertNotIn('Unchanged since',second)
        self.assertNotIn('## hand\n',second)
        self.assertLess(len(second),len(first))
        self.assertNotIn('Counter target spell',second)
        self.assertIn('Counter target spell',Document(CATALOG).render(p,'decider'))
        self.assertEqual(p,packet())
