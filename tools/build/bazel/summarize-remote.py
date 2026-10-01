#!/usr/bin/env python3
"""Extract a compact execution report without publishing raw Bazel event environments."""
import argparse
from collections import Counter
import json
from pathlib import Path


def objects(path):
    decoder = json.JSONDecoder()
    text = path.read_text()
    offset = 0
    while offset < len(text):
        if text[offset].isspace():
            offset += 1
            continue
        obj, offset = decoder.raw_decode(text, offset)
        yield obj


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefix', type=Path, help='Prefix of .bep.json and .execution.json logs')
    args = parser.parse_args()
    events = list(objects(Path(str(args.prefix) + '.bep.json')))
    actions = list(objects(Path(str(args.prefix) + '.execution.json')))
    summary = next(e['testSummary'] for e in events if 'testSummary' in e)
    metrics = next(e['buildMetrics'] for e in events if 'buildMetrics' in e)
    print(json.dumps({
        'test_status': summary['overallStatus'],
        'test_runs': summary.get('totalRunCount'),
        'cached_test_runs': summary.get('totalNumCached', 0),
        'wall_time_ms': metrics.get('timingMetrics', {}).get('wallTimeInMs'),
        'action_runners': dict(Counter(a.get('runner', 'unspecified') for a in actions)),
        'remote_cache_hits': sum(bool(a.get('cacheHit')) for a in actions),
        'actions': [{'target': a.get('targetLabel'), 'mnemonic': a.get('mnemonic'),
                     'runner': a.get('runner'), 'cache_hit': a.get('cacheHit', False),
                     'exit_code': a.get('exitCode')} for a in actions
                    if a.get('mnemonic') in ('Javac', 'TestRunner')],
    }, indent=2))


if __name__ == '__main__':
    main()
