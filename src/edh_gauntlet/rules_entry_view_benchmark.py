"""Synthetic prospective-entry evaluation parity and timing; no live gameplay."""
import argparse,hashlib,json,platform
from dataclasses import replace
from pathlib import Path
from time import perf_counter_ns
from .rules_benchmark import summarize
from .rules_kernel import RulesKernel
from .rules_state import RulesState,Zone
from .rules_program import CardProgram,ContinuousProgram,Selector,ModifyPT
from .rules_replacements import ZoneProposal
from .rules_identity import IMPLEMENTATION_ID

class UncachedEntryKernel(RulesKernel):
    def _proposal_view(self,proposal):return self._compute_proposal_view(proposal)

def fixture(cls,incoming=24):
    body=CardProgram('body','Synthetic creature',('Creature',),power=2,toughness=2)
    anthem=CardProgram('anthem','Synthetic anthem',('Enchantment',),continuous=(ContinuousProgram('boost',Selector(Zone.BATTLEFIELD,types=('Creature',)),(ModifyPT(1,1),)),))
    state=RulesState(('A','B','C','D'))
    for i in range(80):state.add_card('board'+str(i),'anthem' if i<2 else 'body',state.players[i%4],Zone.BATTLEFIELD)
    refs=[state.add_card('entry'+str(i),'body','A',Zone.HAND) for i in range(incoming)]
    return cls(state,(body,anthem)),tuple(ZoneProposal(state.get(ref),Zone.BATTLEFIELD,'A') for ref in refs)

def execute(kernel,proposals,passes,material=False):
    results=[]
    for step in range(passes):
        for p in proposals:
            p=replace(p,used=frozenset({str(step)}),trace=({'step':step},),counters=(('+1/+1',step+1),) if material else ())
            results.append(kernel._proposal_view(p))
    return results

def measure(repeats=7,incoming=24,passes=6):
    if any(type(v) is not int or v<1 for v in (repeats,incoming,passes)):raise ValueError('Positive benchmark sizes required')
    cases=[]
    for material in (False,True):
        samples={'cached':[],'uncached':[]};expected=None
        for iteration in range(repeats):
            order=(('cached',RulesKernel),('uncached',UncachedEntryKernel))
            for label,cls in order[::1 if iteration%2==0 else -1]:
                kernel,proposals=fixture(cls,incoming);before=kernel.snapshot()
                start=perf_counter_ns();result=execute(kernel,proposals,passes,material);samples[label].append((perf_counter_ns()-start)/1e6)
                if kernel.snapshot()!=before:raise AssertionError('Entry inspection changed semantic state')
                if expected is None:expected=result
                elif expected!=result:raise AssertionError('Prospective entry characteristics differ')
        timing={key:summarize(values) for key,values in samples.items()}
        cases.append({'case':'material_changes' if material else 'bookkeeping_only','incoming':incoming,'passes':passes,'semantic_parity':True,
            'result_sha256':hashlib.sha256(json.dumps([{'object':obj.to_json(),'view':view.__dict__} for obj,view in expected],sort_keys=True,default=lambda value:sorted(value)).encode()).hexdigest(),'timings':timing,
            'median_speedup_vs_uncached':timing['uncached']['median_ms']/timing['cached']['median_ms']})
    return {'schema':1,'scope':'Synthetic prospective-entry evaluation; excludes construction, inference, transport and live gameplay',
        'implementation_sha256':IMPLEMENTATION_ID,'python':platform.python_version(),'platform':platform.platform(),'repeats':repeats,'cache_limit':RulesKernel.ENTRY_VIEW_CACHE_LIMIT,'cases':cases}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repeats',type=int,default=7);parser.add_argument('--output',type=Path)
    args=parser.parse_args();report=measure(args.repeats)
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
