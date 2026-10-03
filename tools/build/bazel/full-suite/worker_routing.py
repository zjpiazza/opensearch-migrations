"""Explicit platform routing shared by runtime export and routing-only updates."""
import json
from pathlib import Path

POLICY = json.loads(Path(__file__).with_name('worker-routing.json').read_text())


def properties(task, test_class=''):
    if task in POLICY['large_tasks'] or test_class in POLICY['large_classes']:
        return {'workload': POLICY['default'] if POLICY.get('unified_integration') else 'integration-large'}
    if task in POLICY['lightweight_tasks']:
        return {}
    return {'workload': POLICY['default']}


if __name__ == '__main__':
    # Update only platform routing in an existing export, leaving runtime bytes intact.
    import ast
    import re
    from collections import Counter

    root = Path(__file__).resolve().parents[4]
    output = root / 'build/full-suite'
    inventory = json.loads((output / 'inventory.json').read_text())
    targets = {t['target']: t for t in inventory['targets']}
    seen = set()

    def replace(match):
        prefix, name, suffix = match.groups()
        target = targets[ast.literal_eval(name)]
        selected = properties(target['task'], target.get('class', ''))
        target['exec_properties'] = selected
        seen.add(target['target'])
        return prefix + name + suffix + repr(selected) + ')'

    build = output / 'BUILD.bazel'
    updated = re.sub(r"(exported_test\(name=)('[^']+')(.*?, exec_properties=)\{[^}]*\}\)",
                     replace, build.read_text())
    if seen != targets.keys():
        raise SystemExit('Refusing partial routing update: target inventory does not match BUILD.bazel')
    build.write_text(updated)
    (output / 'inventory.json').write_text(json.dumps(inventory, indent=2) + '\n')
    print(dict(Counter(t['exec_properties'].get('workload', 'lightweight') for t in targets.values())))
