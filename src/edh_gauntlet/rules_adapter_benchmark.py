"""Synthetic actor-packet and event-cursor costs; no host or model is launched."""
import argparse,json,statistics
from pathlib import Path
from time import perf_counter_ns
from .rules_state import RulesState,Zone,ZoneMove
from .rules_program import CardProgram
from .rules_kernel import RulesKernel
from .rules_actor import project_actor
from .rules_identity import IMPLEMENTATION_ID


def measure(repeats=7):
    if type(repeats) is not int or repeats<1:raise ValueError('Positive repetitions required')
    cases=[]
    for history in (0,1000,10000):
        state=RulesState(('A','B','C','D'))
        program=CardProgram('card','Synthetic card',('Artifact',))
        for player in state.players:
            for i in range(7):state.add_card(player+'hand'+str(i),'card',player,Zone.HAND)
            for i in range(70):state.add_card(player+'library'+str(i),'card',player,Zone.LIBRARY)
            for i in range(10):state.add_card(player+'field'+str(i),'card',player,Zone.BATTLEFIELD)
        ref=state.add_card('history','card','A',Zone.GRAVEYARD)
        for i in range(history):
            state.move((ZoneMove(ref,Zone.EXILE if i%2==0 else Zone.GRAVEYARD),),'synthetic-history');ref=state.current('history')
        kernel=RulesKernel(state,(program,));kernel.open_window_for_scenario('A');kernel.characteristics()
        packet_samples=[];old_samples=[];new_samples=[];cursor=state.event_count
        for _ in range(repeats):
            start=perf_counter_ns();packet=project_actor(kernel,'A');packet_samples.append((perf_counter_ns()-start)/1e6)
            start=perf_counter_ns()
            for _ in range(1000):old=state.events[cursor:]
            old_samples.append((perf_counter_ns()-start)/1e6/1000)
            start=perf_counter_ns()
            for _ in range(1000):new=state.events_since(cursor)
            new_samples.append((perf_counter_ns()-start)/1e6/1000)
            if old!=new:raise AssertionError('Event cursor changed semantics')
        cases.append({'prior_zone_events':history,'public_permanents':40,'cards_per_hand':7,
            'packet_bytes':len(json.dumps(packet,separators=(',',':')).encode()),
            'packet_median_ms':statistics.median(packet_samples),'packet_samples_ms':packet_samples,
            'full_history_slice_median_ms':statistics.median(old_samples),
            'incremental_cursor_median_ms':statistics.median(new_samples)})
    return {'schema':1,'implementation_sha256':IMPLEMENTATION_ID,'repeats':repeats,
        'scope':'Synthetic current-packet and empty-event-tail costs; excludes inference, live queues, durable storage and production replay throughput',
        'cases':cases}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repeats',type=int,default=7);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report=measure(args.repeats);args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
