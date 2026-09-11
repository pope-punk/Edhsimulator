"""Synthetic trigger-discovery parity and timing; excludes gameplay and inference."""
import argparse
import hashlib
import json
import platform
from pathlib import Path
from time import perf_counter_ns
from .rules_benchmark import summarize
from .rules_kernel import RulesKernel
from .rules_state import RulesState,Zone
from .rules_program import CardProgram,AbilityProgram,EventPattern,GainLife
from .rules_identity import IMPLEMENTATION_ID


class ScanningRulesKernel(RulesKernel):
    """Reference bypasses only indexing; collectors retain all original filters."""
    def _trigger_abilities(self,source,kind):
        return self.definition(source).abilities


def fixture(kernel_type):
    kinds=('zone_changed','spell_cast','ability_activated','creature_attacks',
        'creature_blocks','becomes_blocked','damage_dealt','damage_received','counters_added','becomes_tapped')
    abilities=tuple(AbilityProgram('unrelated-'+kind,EventPattern(kind),(GainLife(1),)) for kind in kinds)
    ordinary=CardProgram('ordinary','Synthetic observer',('Creature',),power=2,toughness=2,abilities=abilities)
    listener=CardProgram('listener','Synthetic upkeep listener',('Enchantment',),abilities=abilities+(
        AbilityProgram('upkeep',EventPattern('step_began',step='upkeep',controller_only=True),(GainLife(1),)),))
    state=RulesState(('A','B','C','D'))
    for i in range(120):state.add_card(str(i),'listener' if i<4 else 'ordinary',state.players[i%4],Zone.BATTLEFIELD)
    return kernel_type(state,(ordinary,listener))


def execute(kernel,case,events):
    for _ in range(events):
        if case=='unobserved_draw':kernel._player_event('card_drawn','A')
        else:kernel._collect_step('upkeep')


def measure(repeats=7,events=100):
    if type(repeats) is not int or repeats<1 or type(events) is not int or events<1:raise ValueError('Positive integer benchmark sizes required')
    cases=[]
    for case in ('unobserved_draw','sparse_upkeep'):
        samples={'indexed':[],'scanning':[]};expected=None
        for iteration in range(repeats):
            order=(('indexed',RulesKernel),('scanning',ScanningRulesKernel))
            for label,cls in order[::1 if iteration%2==0 else -1]:
                kernel=fixture(cls)  # Construction is outside discovery timing.
                start=perf_counter_ns();execute(kernel,case,events);samples[label].append((perf_counter_ns()-start)/1e6)
                snapshot=kernel.snapshot()
                if expected is None:expected=snapshot
                elif snapshot!=expected:raise AssertionError('Trigger-discovery mismatch: '+case)
        timings={label:summarize(rows) for label,rows in samples.items()}
        cases.append({'case':case,'objects':120,'events':events,'semantic_parity':True,
            'snapshot_sha256':hashlib.sha256(json.dumps(expected,sort_keys=True).encode()).hexdigest(),
            'timings':timings,'median_speedup_vs_scanning':timings['scanning']['median_ms']/timings['indexed']['median_ms']})
    return {'schema':1,'scope':'Synthetic trigger discovery only; excludes construction, inference, transport and live gameplay',
        'implementation_sha256':IMPLEMENTATION_ID,'python':platform.python_version(),'platform':platform.platform(),
        'reference':'Identical collectors with definition-wide scanning instead of event indexing','repeats':repeats,'cases':cases}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repeats',type=int,default=7);parser.add_argument('--events',type=int,default=100);parser.add_argument('--output',type=Path)
    args=parser.parse_args();report=measure(args.repeats,args.events)
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
