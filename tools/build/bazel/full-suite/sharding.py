"""Configure reviewed long-test shards without re-exporting compiled runtimes."""
import argparse
import ast
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[4]
HELPER = 'tools/bazel-sharding.jar'


def policy(unsharded=False, path=None):
    return {} if unsharded else json.loads((path or Path(__file__).with_name('sharding.json')).read_text())['classes']


def build_helper(java_home, directory):
    classes = directory / 'shard-classes'
    if classes.exists():
        shutil.rmtree(classes)
    classes.mkdir(parents=True)
    subprocess.run([str(java_home/'bin/javac'), '-cp',
                    str(directory/'junit-platform-console-standalone-1.14.0.jar'),
                    '-d', str(classes), str(Path(__file__).with_name('BazelShardCondition.java'))], check=True)
    service = classes/'META-INF/services/org.junit.jupiter.api.extension.Extension'
    service.parent.mkdir(parents=True)
    service.write_text('org.opensearch.migrations.testinfra.BazelShardCondition\n')
    # Fixed ZIP metadata preserves cache keys when the compiled helper is unchanged.
    with zipfile.ZipFile(directory/'bazel-sharding.jar', 'w') as jar:
        for entry in sorted(classes.rglob('*')):
            if entry.is_file():
                info = zipfile.ZipInfo(entry.relative_to(classes).as_posix(), (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                jar.writestr(info, entry.read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, default=ROOT/'build/full-suite')
    parser.add_argument('--unsharded', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--policy', type=Path, help='Optional policy for a focused shard-count experiment')
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    inventory = json.loads((runtime/'inventory.json').read_text())
    targets = {t['target']: t for t in inventory['targets']}
    configured = policy(path=args.policy)
    available = {t['task']+'|'+t.get('class', '') for t in targets.values()}
    if set(configured)-available:
        raise ValueError('Configured long classes are absent from this runtime')
    lines = []
    specs = set()
    updated = []
    for line in (runtime/'BUILD.bazel').read_text().splitlines():
        if not line.startswith('exported_test('):
            lines.append(line)
            continue
        call = ast.parse(line, mode='eval').body
        name = ast.literal_eval(next(k.value for k in call.keywords if k.arg == 'name'))
        target = targets[name]
        key = target['task']+'|'+target.get('class', '')
        if key not in configured:
            lines.append(line)
            continue
        values = {keyword.arg: ast.literal_eval(keyword.value) for keyword in call.keywords}
        selected = configured[key]
        count = 1 if args.unsharded else selected['count']
        grouping = selected.get('grouping', 'fixture-index')
        if not isinstance(count, int) or not 1 <= count <= 50 or grouping not in ('fixture-index', 'independent'):
            raise ValueError('Invalid shard configuration for '+key)
        values['shard_count'] = count if count > 1 else 0
        values['shard_grouping'] = grouping
        values['data'] = [value for value in values.get('data', []) if value != HELPER]
        if count > 1:
            values['data'].append(HELPER)
        # Keep compatibility with the existing routing-only updater.
        values['exec_properties'] = values.pop('exec_properties')
        lines.append('exported_test('+', '.join(k+'='+repr(v) for k, v in values.items())+')')
        target.update(shard_count=count, shard_grouping=grouping)
        specs.add(values['spec'])
        updated.append(name)
    if len(updated) != len(configured):
        raise ValueError('Refusing partial shard update: BUILD and inventory disagree')
    print(json.dumps({'updated_classes':len(updated),
                      'selected_tasks':sum(targets[name]['shard_count'] for name in updated),
                      'dry_run':args.dry_run, 'compiled_runtime_archives':'unchanged'}, indent=2))
    if args.dry_run:
        return
    build_helper(runtime/'tools/jdk', runtime/'tools')
    for filename in specs:
        path = runtime/filename
        spec = json.loads(path.read_text())
        spec['shardHelper'] = HELPER
        path.write_text(json.dumps(spec, indent=2)+'\n')
    (runtime/'BUILD.bazel').write_text('\n'.join(lines)+'\n')
    (runtime/'inventory.json').write_text(json.dumps(inventory, indent=2)+'\n')


if __name__ == '__main__':
    main()
