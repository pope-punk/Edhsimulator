"""Measure atomic fixed-token creation and public packet costs with checkpoint checks."""
import json,statistics,time
from pathlib import Path
from edh_gauntlet.rules_program import CardProgram,CreateTokens
from edh_gauntlet.rules_state import RulesState,Zone
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_actor import project_actor
from edh_gauntlet.rules_identity import IMPLEMENTATION_ID

def measure(repeats=7):
 rows=[]
 for count in (1,10,100):
  samples=[];packets=[]
  for _ in range(repeats):
   token=CardProgram('token:bench','Bench Token',('Creature',),power=1,toughness=1,colors=('G',))
   effect=CreateTokens(token,count);source=CardProgram('source','Source',('Artifact',),spell_effects=(effect,))
   state=RulesState(('A','B'));ref=state.add_card('source','source','A',Zone.BATTLEFIELD);kernel=RulesKernel(state,(source,))
   start=time.perf_counter_ns();kernel.execute_for_scenario(ref,'A',(effect,));samples.append((time.perf_counter_ns()-start)/1e6)
   assert len(state.events)==count and len({e.batch for e in state.events})==1
   start=time.perf_counter_ns();packet=project_actor(kernel,'B');packets.append((time.perf_counter_ns()-start)/1e6)
   assert RulesKernel.restore(kernel.snapshot(),(source,)).snapshot()==kernel.snapshot()
  rows.append({'tokens':count,'creation_median_ms':statistics.median(samples),'creation_samples_ms':samples,
   'packet_median_ms':statistics.median(packets),'packet_samples_ms':packets,'one_atomic_batch':True,'checkpoint_parity':True})
 v={'schema':1,'implementation_sha256':IMPLEMENTATION_ID,'repeats':repeats,
  'scope':'Synthetic fixed-token creation and current public packet; no triggers, modifiers, inference, transport, live queues or production throughput claims','cases':rows}
 return v


def main():
 import argparse
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repeats',type=int,default=7);parser.add_argument('--output',type=Path,required=True)
 args=parser.parse_args()
 if args.repeats<1:parser.error('repeats must be positive')
 report=measure(args.repeats);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps([{k:r[k] for k in ('tokens','creation_median_ms','packet_median_ms')} for r in report['cases']]))


if __name__=='__main__':main()
