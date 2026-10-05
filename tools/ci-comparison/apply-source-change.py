#!/usr/bin/env python3
"""Apply one deterministic source mutation for CI cache-invalidation trials."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]

CHANGES = {
    'none': None,
    'leaf': {
        'path': 'apps/dashboards/src/main/java/org/opensearch/migrations/dashboards/savedobjects/SavedObjectParser.java',
        'before': 'Skipping the exported summary line.',
        'after': 'Skipping the exported dashboard summary line.',
        'intent': 'leaf implementation change in dashboards parsing code',
    },
    'shared': {
        'path': 'libs/runtime/src/main/java/org/opensearch/migrations/jcommander/EnvVarParameterPuller.java',
        'before': 'Could not access field: {}',
        'after': 'Could not access parameter field: {}',
        'intent': 'shared-library implementation change in runtime utilities',
    },
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trial', choices=sorted(CHANGES))
    parser.add_argument('--output', type=Path, default=ROOT / 'build/ci-comparison/source-change.json')
    args = parser.parse_args()

    change = CHANGES[args.trial]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if change is None:
        args.output.write_text(json.dumps({'trial': args.trial, 'changed': False}, indent=2) + '\n')
        print('No source mutation requested')
        return 0

    path = ROOT / change['path']
    text = path.read_text()
    if text.count(change['before']) != 1:
        print(f"Expected source text not found exactly once in {change['path']}", file=sys.stderr)
        return 1
    path.write_text(text.replace(change['before'], change['after']))
    record = {'trial': args.trial, 'changed': True, **change}
    args.output.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
