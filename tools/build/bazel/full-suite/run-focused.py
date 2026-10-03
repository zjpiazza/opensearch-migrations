#!/usr/bin/env python3
"""Run configured long-test shards on selected worker pools, with coverage validation."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[4]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pool', choices=['integration', 'integration-large', 'all'], required=True,
                        help='all combines both integration pools in one invocation')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--instance', required=True)
    parser.add_argument('--bazel', type=Path, default=ROOT / 'bazelw')
    args = parser.parse_args()
    runtime = ROOT / 'build/full-suite'
    inventory = json.loads((runtime / 'inventory.json').read_text())
    selected = [t for t in inventory['targets'] if t.get('shard_count', 1) > 1
                and t.get('exec_properties', {}).get('workload') in
                ({'integration', 'integration-large'} if args.pool == 'all' else {args.pool})]
    if not selected:
        parser.error('No configured long-test shards on the selected pool; run sharding.py first')
    baseline = args.baseline.resolve(strict=True)
    bazel = args.bazel.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    labels = ['@full_suite//:' + t['target'] for t in selected]
    command = [str(bazel), '--output_base=' + str(output / 'client'), 'test',
               '--config=buildbarn-rerun-tests', '--remote_instance_name=' + args.instance,
               '--keep_going', '--test_timeout=7200',
               '--build_event_json_file=' + str(output / 'results.bep.json'),
               '--execution_log_json_file=' + str(output / 'results.execution.json'),
               '--profile=' + str(output / 'profile.json.gz'),
               '--symlink_prefix=' + str(output / 'bazel-'), *labels]
    (output / 'inventory.json').write_text(json.dumps(inventory, indent=2) + '\n')
    (output / 'coverage-baseline.json').write_bytes(baseline.read_bytes())
    metadata = {
        'pool': args.pool, 'selected_targets': selected, 'command': command,
        'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'runtime_build_sha256': hashlib.sha256((runtime / 'BUILD.bazel').read_bytes()).hexdigest(),
        'coverage_baseline_sha256': hashlib.sha256(baseline.read_bytes()).hexdigest(),
        'cache_policy': 'test-result reuse disabled; build results, input blobs and private Docker caches may be reused',
        'measurement_scope': 'execution of pre-exported Gradle bytecode, not compilation or source re-export',
    }
    (output / 'experiment.json').write_text(json.dumps(metadata, indent=2) + '\n')
    started = time.time()
    with (output / 'bazel.log').open('w') as log:
        child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        status = {'phase': 'running', 'pid': child.pid, 'started_at_epoch': started,
                  'target_count': len(selected), 'shard_count': sum(t['shard_count'] for t in selected)}
        (output / 'status.json').write_text(json.dumps(status, indent=2) + '\n')
        print(json.dumps(status), flush=True)
        code = child.wait()
    status.update(phase='finished', exit_code=code, elapsed_seconds=round(time.time() - started, 3))
    (output / 'status.json').write_text(json.dumps(status, indent=2) + '\n')
    print(json.dumps(status), flush=True)
    summary = ['python3', str(Path(__file__).with_name('summarize.py')),
               str(output / 'results.bep.json'), '--testlogs',
               str(output / 'client/execroot/_main/bazel-out/k8-fastbuild/testlogs/external/+_repo_rules+full_suite'),
               '--baseline', str(baseline), '--inventory', str(output / 'inventory.json'),
               '--output', str(output / 'summary.json'), '--require-complete']
    for label in labels:
        summary += ['--target', label]
    validated = subprocess.run(summary, cwd=ROOT)
    status['validation_exit_code'] = validated.returncode
    (output / 'status.json').write_text(json.dumps(status, indent=2) + '\n')
    return code or validated.returncode


if __name__ == '__main__':
    raise SystemExit(main())
