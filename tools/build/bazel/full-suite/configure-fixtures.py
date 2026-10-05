#!/usr/bin/env python3
"""Wire reviewed long tests to narrow, graph-connected Bazel image catalogs."""
import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def configure(runtime, policy):
    found = set()
    lines = []
    for line in (runtime/'BUILD.bazel').read_text().splitlines():
        if line.startswith('exported_test('):
            keywords = ast.parse(line,mode='eval').body.keywords
            name = ast.literal_eval(next(k.value for k in keywords if k.arg=='name'))
            if name in policy:
                values = {k.arg:ast.literal_eval(k.value) for k in keywords}
                values['fixture_catalog'] = '@fixture_images//:catalog_'+name
                found.add(name)
                line = 'exported_test('+', '.join(k+'='+repr(v) for k,v in values.items())+')'
        lines.append(line)
    if found != set(policy):
        raise ValueError('Fixture policy targets missing from runtime: '+repr(set(policy)-found))
    (runtime/'BUILD.bazel').write_text('\n'.join(lines)+'\n')
    return len(found)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime',type=Path,default=ROOT/'build/full-suite')
    p.add_argument('--policy',type=Path,default=ROOT/'tools/build/bazel/fixture-images/long-test-images.json')
    args=p.parse_args()
    print('Configured',configure(args.runtime,json.loads(args.policy.read_text())['classes']),'long-test image catalogs')
