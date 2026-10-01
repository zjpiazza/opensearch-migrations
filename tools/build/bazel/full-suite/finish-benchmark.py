#!/usr/bin/env python3
"""Finish an in-progress seed run, then measure the three approved scenarios.

Run in this worktree with Node and the Bazel wrapper available. Keeps a status
file and stops on incomplete coverage or failed tests. Does not deploy anything.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[4]
TOOLS = ROOT / 'tools/build/bazel/full-suite'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--seed-bep', type=Path, required=True)
parser.add_argument('--seed-testlogs', type=Path, required=True)
parser.add_argument('--seed-client-pid', type=int, required=True)
parser.add_argument('--baseline', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--instance', default='migrations-pilot')
parser.add_argument('--scenarios', nargs='+', choices=('unchanged', 'leaf', 'shared'),
                    default=['unchanged', 'leaf', 'shared'])
args = parser.parse_args()
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=False)
state = {'phase': 'waiting-for-seed', 'completed_scenarios': []}


def save(**updates):
    state.update(updates)
    state['updated_at_epoch'] = time.time()
    temporary = out / 'status.tmp'
    temporary.write_text(json.dumps(state, indent=2) + '\n')
    temporary.replace(out / 'status.json')
    print(json.dumps(state), flush=True)


def run(command, log):
    with log.open('w') as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)


def summarize(bep, testlogs, destination):
    run(['python3', str(TOOLS / 'summarize.py'), str(bep.resolve()),
         '--testlogs', str(testlogs.resolve()), '--baseline', str(args.baseline.resolve()),
         '--output', str(destination), '--require-complete'], destination.with_suffix('.log'))


restore_needed = False
try:
    save()
    while True:
        # The producer can be writing its final line while we read the BEP.
        lines = args.seed_bep.read_text().splitlines()
        events = []
        for index, line in enumerate(lines):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                if index != len(lines) - 1:
                    raise
        if any('buildMetrics' in event for event in events):
            break
        if not Path('/proc', str(args.seed_client_pid)).exists():
            raise RuntimeError('Seed client exited without a complete BEP; inspect seed log before resuming')
        time.sleep(15)
    save(phase='validating-seed')
    summarize(args.seed_bep, args.seed_testlogs, out / 'seed.summary.json')
    for scenario in args.scenarios:
        save(phase=scenario)
        restore_needed |= scenario != 'unchanged'
        target = out / scenario
        run(['python3', str(TOOLS / 'benchmark.py'), scenario, '--output', str(target),
             '--instance', args.instance],
            out / (scenario + '.driver.log'))
        summarize(target / 'results.bep.json',
                  target / 'client/execroot/_main/bazel-out/k8-fastbuild/testlogs/external/+_repo_rules+full_suite',
                  target / 'summary.json')
        state['completed_scenarios'].append(scenario)
        save()
    save(phase='measurements-complete')
except Exception as error:
    save(phase='failed', error=str(error))
    raise
finally:
    if restore_needed:
        # benchmark.py restores source in its own finally block. Restore the
        # exported runtime too, so later Bazel commands see that restored source.
        try:
            start = time.monotonic()
            run(['./gradlew', '-I', str(TOOLS / 'export.gradle'), 'exportBazelTestRuntime',
                 '--max-workers=3', '-x', 'spotlessCheck', '--console=plain'], out / 'restore-gradle.log')
            run(['python3', str(TOOLS / 'prepare.py')], out / 'restore-export.log')
            save(runtime_restored=True, restore_seconds=time.monotonic() - start)
        except Exception as error:
            save(runtime_restored=False, restore_error=str(error))
            raise
