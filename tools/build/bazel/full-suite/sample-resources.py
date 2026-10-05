#!/usr/bin/env python3
"""Record node and Buildbarn pod usage from kubelet summaries during a benchmark."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import time


def get(*args):
    return json.loads(subprocess.check_output(['kubectl', '--context', 'do-atl1-bazel', *args],
                                             timeout=15, stderr=subprocess.PIPE))


def sample(node):
    name = node['metadata']['name']
    row = {'node': name, 'pool': node['metadata']['labels'].get('doks.digitalocean.com/node-pool'),
           'allocatable': node['status']['allocatable']}
    try:
        summary = get('get', '--raw', '/api/v1/nodes/' + name + '/proxy/stats/summary')
        row['usage'] = {k: summary['node'].get(k) for k in ('cpu', 'memory', 'fs')}
        row['pods'] = [{k: p.get(k) for k in ('podRef', 'cpu', 'memory', 'ephemeral-storage', 'containers')}
                       for p in summary['pods'] if p['podRef']['namespace'] == 'migrations-buildbarn']
    except (subprocess.SubprocessError, ValueError) as error:
        row['error'] = str(error)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    output = args.run.with_suffix('.resources.jsonl')
    with output.open('a') as log, ThreadPoolExecutor(max_workers=8) as executor:
        while True:
            started = time.monotonic()
            report = {'sampled_at_epoch': time.time()}
            try:
                nodes = get('get', 'nodes', '-o', 'json')['items']
                report['nodes'] = list(executor.map(sample, nodes))
            except (subprocess.SubprocessError, ValueError) as error:
                report['error'] = str(error)
            log.write(json.dumps(report) + '\n')
            log.flush()
            if args.once:
                break
            time.sleep(max(1, 20 - (time.monotonic() - started)))


if __name__ == '__main__':
    main()
