from copy import deepcopy
from unittest import TestCase
from edh_gauntlet.primitive_delivery import prepare,expand,size
from edh_gauntlet.rules_adapter import digest


class DeliveryTests(TestCase):
    def packet(self,actor='A'):
        board={'turn':1,'cards':[{'ref':str(i),'text':'rules '*100} for i in range(30)]}
        old=deepcopy(board);old['turn']=0
        return {'game':1,'actor':actor,'context_handling':1,'board':board,'previous_board':old,
                'action_facts':{'objects':[{'source':{'card_id':'x','incarnation':1},'rules_id':'rule'}],
                                'rules':{'rule':{'text':'ability '*1000}},'format':'original'},
                'messages':[{'id':'one','text':'message '*100}], 'plans':{'short_term':'retain prose'}}

    def same(self,expected,actual):
        expected=deepcopy(expected);actual=deepcopy(actual)
        expected['action_facts'].pop('format');actual['action_facts'].pop('format')
        self.assertEqual(expected,actual)

    def test_baseline_and_changed_packet_roundtrip_without_losing_previous_board(self):
        first=self.packet();untouched=deepcopy(first)
        sent,state=prepare(first,'decider');decoded,memory=expand(sent);self.same(first,decoded)
        self.assertEqual(untouched,first)
        second=deepcopy(first);second['board']['turn']=2;second['previous_board']=first['board']
        second['action_facts']['rules']['new']={'text':'new ability'}
        second['action_facts']['objects'][0]['rules_id']='new'
        second['messages'].append({'id':'two','text':'new public message'})
        sent2,state2=prepare(second,'decider',state);decoded2,_=expand(sent2,memory)
        self.same(second,decoded2);self.assertLess(size(sent2),size(second)*.3)
        self.assertIn('new',sent2['action_facts']['rules']);self.assertNotIn('rule',sent2['action_facts']['rules'])
        self.assertEqual('primitive_board_delta_v1',sent2['board']['encoding'])

    def test_new_conversation_and_other_actor_receive_complete_rules(self):
        first=self.packet();_,state=prepare(first,'decider')
        for previous,packet in [(None,first),(state,self.packet('B'))]:
            sent,_=prepare(packet,'decider',previous)
            self.assertEqual(first['action_facts']['rules'],sent['action_facts']['rules'])
            self.same(packet,expand(sent)[0])

    def test_unknown_board_or_rule_baseline_is_rejected(self):
        first=self.packet();_,state=prepare(first,'decider');second=deepcopy(first);second['board']['turn']=2
        sent,_=prepare(second,'decider',state)
        with self.assertRaises(ValueError):expand(sent)

    def test_empty_current_messages_and_changed_rule_incarnation_remain_exact(self):
        first=self.packet();sent,state=prepare(first,'decider');_,memory=expand(sent)
        second=deepcopy(first);second['messages']=[];second['action_facts']['objects'][0]['source']['incarnation']=2
        sent,_=prepare(second,'decider',state);self.same(second,expand(sent,memory)[0])
