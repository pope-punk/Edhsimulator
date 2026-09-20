import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]/'tools'))
from pilot_text_preview import groups,render

class PilotTextTests(unittest.TestCase):
 def test_heading_carries_location_and_all_types(self):
  obj={'name':'Test','ref':{'card_id':'exact-id','incarnation':2},'types':['Creature','Artifact'],'zone':'battlefield','owner':'B','controller':'A','tapped':False,'damage':0,'power':0,'toughness':1,'subtypes':['Elf']}
  result=groups([obj])
  self.assertIn('A’s battlefield — Artifact Creatures',result)
  self.assertIn('owner: B',result);self.assertIn('power: 0',result);self.assertIn('Elf',result)
  self.assertNotIn('controller:',result);self.assertNotIn('zone:',result);self.assertNotIn('"types"',result);self.assertNotIn('damage:',result)
  self.assertIn('"card_id":"exact-id","incarnation":2',result)
  own={**obj,'owner':'A'};self.assertNotIn('owner:',groups([own]))
 def test_original_order_visible_in_graveyard(self):
  a={'name':'First','ref':{'card_id':'a','incarnation':1},'types':['Creature'],'zone':'graveyard','controller':'A','owner':'A'}
  b={**a,'name':'Second','types':['Land']};c={**a,'name':'Third'}
  result=groups([a,b,c]);self.assertIn('Third [position 3]',result);self.assertIn('Second [position 2]',result)
 def test_delta_resets_not_omitted(self):
  result=render({'previous_board':{'encoding':'primitive_board_delta_v1','base_id':'original','changes':[['set',['tapped'],False],['set',['damage'],0]]}})
  self.assertIn('Set: tapped\n\nfalse',result.replace('\nfalse','\n\nfalse'))
  self.assertIn('0',result)

if __name__=='__main__':unittest.main()
