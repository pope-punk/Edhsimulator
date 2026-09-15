"""Reproducible, engine-only synthetic benchmarks; never launches a game."""
import argparse
import hashlib
import json
import math
import platform
import statistics
from dataclasses import asdict
from pathlib import Path
from time import perf_counter_ns
from .rules_state import RulesState, Zone
from .rules_program import (CardProgram, ContinuousProgram, Selector, ModifyPT,
    ChangeTypes, SetPT, CountCondition)
from .rules_characteristics import evaluate, evaluate_exhaustive
from .rules_kernel import RulesKernel
from .rules_identity import IMPLEMENTATION_ID


def fixture(kind):
    state = RulesState(('A', 'B', 'C', 'D'))
    programs = {
        'creature': CardProgram('creature', 'Benchmark creature', ('Creature',), power=2, toughness=2),
        'buff': CardProgram('buff', 'Benchmark modifier', ('Enchantment',), continuous=(
            ContinuousProgram('buff', Selector(Zone.BATTLEFIELD, ('Creature',)), (ModifyPT(1, 1),)),)),
        'animation': CardProgram('animation', 'Benchmark animation', ('Enchantment',), mana_value=3,
            continuous=(ContinuousProgram('animate', Selector(Zone.BATTLEFIELD, ('Enchantment',), exclude_source=True),
                (ChangeTypes(add=('Creature',)), SetPT(3, 3)),
                condition=CountCondition(Selector(Zone.BATTLEFIELD, ('Enchantment',)), 5)),)),
    }
    creature_count, buff_count, animation_count = {
        'independent_modifiers': (96, 24, 0), 'mixed_layers': (48, 8, 2), 'no_continuous_effects': (120, 0, 0),
    }[kind]
    for definition, count in (('creature', creature_count), ('buff', buff_count), ('animation', animation_count)):
        for index in range(count):
            state.add_card(definition + str(index), definition, state.players[index % 4], Zone.BATTLEFIELD)
    return state, programs


def summarize(samples):
    ordered = sorted(samples)
    return {'samples_ms': samples, 'median_ms': statistics.median(samples),
            'p95_ms': ordered[math.ceil(len(ordered) * .95) - 1]}


def digest_views(views):
    rows = []
    for ref, view in sorted(views.items()):
        data = asdict(view)
        data = {key: sorted(value) if isinstance(value, (set, frozenset)) else value for key, value in data.items()}
        rows.append({'ref': ref.to_json(), 'view': data})
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def measure(repeats=7):
    if type(repeats) is not int or repeats < 1:
        raise ValueError('Benchmark repetitions must be positive')
    cases = []
    for kind in ('independent_modifiers', 'mixed_layers', 'no_continuous_effects'):
        state, programs = fixture(kind); objects = state.objects()
        optimized = evaluate(objects, programs); expected = evaluate_exhaustive(objects, programs)
        if optimized != expected:
            raise AssertionError('Characteristic mismatch: ' + kind)
        samples = {'optimized_cold': [], 'exhaustive_cold': [], 'kernel_warm': []}
        kernel = RulesKernel(state, programs.values()); kernel.characteristics()
        for iteration in range(repeats):
            # Alternate order to reduce a systematic warmup/order bias. Both
            # direct evaluators rebuild views; neither reads the kernel cache.
            order = (('optimized_cold', evaluate), ('exhaustive_cold', evaluate_exhaustive))
            for label, function in order[::1 if iteration % 2 == 0 else -1]:
                start = perf_counter_ns(); actual = function(objects, programs)
                samples[label].append((perf_counter_ns() - start) / 1_000_000)
                if actual != expected: raise AssertionError('Nondeterministic benchmark output')
            start = perf_counter_ns()
            for _ in range(1000): kernel.characteristics()
            samples['kernel_warm'].append((perf_counter_ns() - start) / 1_000_000 / 1000)
        timings = {label: summarize(values) for label, values in samples.items()}
        cases.append({'case': kind, 'objects': len(objects), 'continuous_effects': sum(
            len(programs[obj.effective_definition].continuous) for obj in objects),
            'semantic_parity': True, 'result_sha256': digest_views(expected), 'timings': timings,
            'median_speedup_vs_exhaustive': timings['exhaustive_cold']['median_ms'] / timings['optimized_cold']['median_ms']})
    return {'schema': 1, 'scope': 'Synthetic characteristic evaluation only; excludes inference, transport and live gameplay',
        'implementation_sha256': IMPLEMENTATION_ID, 'python': platform.python_version(),
        'platform': platform.platform(), 'repeats': repeats,
        'reference': 'Same evaluator with dependency pruning disabled; not a legacy-host latency baseline', 'cases': cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, default=7)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(); report = measure(args.repeats)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'repeats': report['repeats'], 'cases': [
        {'case': row['case'], 'optimized_median_ms': row['timings']['optimized_cold']['median_ms'],
         'exhaustive_median_ms': row['timings']['exhaustive_cold']['median_ms'],
         'speedup': row['median_speedup_vs_exhaustive'], 'semantic_parity': row['semantic_parity']} for row in report['cases']]}, indent=2))


if __name__ == '__main__':
    main()
