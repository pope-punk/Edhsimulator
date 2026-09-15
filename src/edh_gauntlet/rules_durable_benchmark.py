"""Measure synthetic local durable commits and bounded engine recovery."""
import argparse
import json
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
from .rules_program import CardProgram,ActivatedProgram,CostSpec,AddMana
from .rules_state import RulesState,Zone
from .rules_kernel import RulesKernel
from .rules_durable import DurableRulesAdapter
from .rules_identity import IMPLEMENTATION_ID


def measure(repeats=3,commands=65):
    if type(repeats) is not int or repeats<1 or type(commands) is not int or commands<2:raise ValueError('Invalid benchmark size')
    binding={'cohort_id':'synthetic-benchmark','game_number':1,'branch_id':'original','contract_sha256':'0'*64}
    cases=[]
    for interval in (1,32):
        ordinary=[];checkpoints=[];all_commits=[];reopens=[];tail=None
        for _ in range(repeats):
            program=CardProgram('rock','Rock',('Artifact',),activated=(ActivatedProgram('mana',CostSpec(),(AddMana(('C',)),),mana_ability=True),))
            state=RulesState(('A','B'));ref=state.add_card('rock','rock','A',Zone.BATTLEFIELD);kernel=RulesKernel(state,(program,));kernel.open_window_for_scenario('A')
            with TemporaryDirectory(prefix='primitive-journal-benchmark-') as directory:
                path=Path(directory)/'journal.sqlite';store=DurableRulesAdapter.create(path,kernel,binding=binding,checkpoint_interval=interval)
                try:
                    for index in range(commands):
                        command={'kind':'activate','revision':store.packet('A')['revision'],'action_id':str(index),'ability_id':'mana','source':ref.to_json(),'targets':[],'x_value':0,'payment':{'mana':{},'taps':[]}}
                        start=perf_counter();store.submit('A',str(index),command);elapsed=(perf_counter()-start)*1000
                        all_commits.append(elapsed);(checkpoints if (index+1)%interval==0 else ordinary).append(elapsed)
                    expected=store.archive()
                finally:store.close()
                start=perf_counter();store=DurableRulesAdapter.open(path,(program,),binding=binding);reopens.append((perf_counter()-start)*1000)
                try:
                    assert store.archive()==expected and store.generation==commands
                    tail=store.replayed_count;assert tail<interval
                finally:store.close()
        cases.append({'checkpoint_interval':interval,'commands_per_run':commands,'repeats':repeats,
            'median_commit_ms':median(all_commits),'median_regular_commit_ms':median(ordinary) if ordinary else None,
            'median_checkpoint_commit_ms':median(checkpoints) if checkpoints else None,'median_reopen_ms':median(reopens),
            'replayed_commands_on_open':tail})
    return {'schema':1,'implementation_sha256':IMPLEMENTATION_ID,
        'scope':'Synthetic SQLite FULL/WAL on local temporary storage; includes engine execution and actor packet creation, excludes inference, network, production disks and campaign integration',
        'cases':cases}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repeats',type=int,default=3);parser.add_argument('--commands',type=int,default=65);parser.add_argument('--output',type=Path)
    args=parser.parse_args();result=measure(args.repeats,args.commands);payload=json.dumps(result,indent=2)
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(payload+'\n')
    print(payload)


if __name__=='__main__':main()
