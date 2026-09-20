import importlib.util
from pathlib import Path
import unittest
from copy import deepcopy
spec=importlib.util.spec_from_file_location('sparse',Path(__file__).parents[1]/'tools/sparse_packet.py')
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)

class SparseTests(unittest.TestCase):
 def test_defaults_absence_zero_and_unrelated_fields(self):
  obj={'ref':{'card_id':'id','incarnation':0},'name':'Test','types':['Creature'],'zone':'battlefield','commander':False,'token':False,'tapped':True,'damage':0,'power':0,'toughness':0,'counters':{},'unknown':False}
  other={**obj};del other['commander'];other['tapped']=False
  packet={'board':[obj,other],'payment':{'mana':{'G':0}},'changes':[['set',['damage'],0],['set',['tapped'],False]]};before=deepcopy(packet)
  sparse,stats=s.encode(packet)
  self.assertEqual(s.decode(sparse),packet);self.assertEqual(packet,before)
  self.assertNotIn('damage',sparse['board'][0]);self.assertEqual(sparse['board'][0]['power'],0)
  self.assertIs(sparse['board'][0]['unknown'],False);self.assertEqual(sparse['payment'],packet['payment'])
  self.assertEqual(sparse['changes'],packet['changes']);self.assertNotIn('commander',s.decode(sparse)['board'][1])
 def test_decode_before_delta_restores_defaults(self):
  from edh_gauntlet.primitive_delivery import board_packet,expand
  from edh_gauntlet.rules_adapter import digest
  obj={'ref':{'card_id':'id','incarnation':1},'name':'Land','types':['Land'],'zone':'battlefield','tapped':True,'damage':2,'token':False}
  old={'objects':[obj]};new={'objects':[{**obj,'tapped':False,'damage':0}]}
  value={'board':board_packet(new,old,digest(old))}
  sparse,_=s.encode(value);expanded,_=expand(s.decode(sparse),{'boards':{digest(old):old}})
  self.assertEqual(expanded['board'],new)
 def test_grouped_locations_preserve_owner_and_list_order(self):
  obj={'ref':{'card_id':'a','incarnation':1},'name':'Test','types':['Creature'],'zone':'battlefield','controller':'A','owner':'A','damage':0}
  stolen={**obj,'ref':{'card_id':'b','incarnation':2},'owner':'B'}
  other={**obj,'ref':{'card_id':'c','incarnation':1},'controller':'C'}
  packet={'board':{'zones':{'battlefield':[obj,stolen,other,obj]}}}
  sparse,_=s.encode(packet);grouped,stats=s.group_locations(sparse)
  self.assertEqual(s.decode(s.ungroup_locations(grouped)),packet)
  self.assertEqual(stats['groups'],3)
  groups=grouped['board']['zones']['battlefield']['_object_groups']
  self.assertEqual(groups[0]['objects'][1]['owner'],'B')
  self.assertNotIn('zone',groups[0]['objects'][0])
 def test_marker_collision(self):
  with self.assertRaises(ValueError):s.encode({'x':{'_s':False}})

if __name__=='__main__':unittest.main()
