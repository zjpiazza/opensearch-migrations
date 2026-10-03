#!/usr/bin/env python3
"""Verify pinned fixture inputs and generate one independent Bazel target per version."""
import argparse
import json
from pathlib import Path
import shutil
from fetch import digest, ROOT
from chunks import materialize_parts

HERE = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inputs', type=Path, default=ROOT/'build/fixture-image-inputs')
    p.add_argument('--snapshot-outputs', type=Path)
    p.add_argument('--refresh-toolchain-lock', action='store_true')
    args = p.parse_args()
    args.inputs.mkdir(parents=True, exist_ok=True)
    tool_lock_path = HERE/'toolchains.lock.json'
    if args.refresh_toolchain_lock:
        if not args.snapshot_outputs:
            p.error('--snapshot-outputs required to refresh toolchain lock')
        tools = {}
        for key in ['utilities', 'compiler8', 'runtime8', 'runtime11', 'runtime17', 'runtime21']:
            meta = json.loads((args.snapshot_outputs/('refresh_'+key+'.json')).read_text())
            archive = args.snapshot_outputs/('refresh_'+key+'.tar.gz')
            if digest(archive) != meta['archive_sha256']:
                raise ValueError('Snapshot checksum mismatch: ' + key)
            dest = args.inputs/(key+'.tar.gz')
            shutil.copyfile(archive, dest)
            tools[key] = dict(file=dest.name, sha256=meta['archive_sha256'], image_id=meta['image_id'],
                              tag=meta['tag'], packages=meta['packages'], recipe_sha256=meta['recipe_sha256'])
        tool_lock_path.write_text(json.dumps(tools, indent=2, sort_keys=True)+'\n')
    tools = json.loads(tool_lock_path.read_text())
    downloads = json.loads((HERE/'downloads.lock.json').read_text())
    tools = {key:materialize_parts(args.inputs, item, remove_original=True) for key,item in tools.items()}
    for version in downloads.values():
        for role in ['distribution', 'plugin']:
            version[role] = materialize_parts(args.inputs, version[role], remove_original=True)
    lines = ['load("@@//tools/build/bazel/fixture-images:defs.bzl", "offline_fixture_image", "fixture_publish", "fixture_smoke_test", "fixture_catalog")',
             'package(default_visibility=["//visibility:public"])']
    for minor, item in sorted(downloads.items()):
        major, small = map(int, minor.split('.'))
        java = '8' if major <= 5 or major == 6 and small <= 4 else '11' if major == 6 or major == 7 and small <= 10 else '17' if major == 7 else '21'
        runtime = tools['runtime'+java]
        compiler = tools['compiler8'] if major == 5 and small in (1, 2) else runtime
        spec = dict(version=item['version'], java=java, docker_engine='28.5.2',
                    java_home='/usr/lib/jvm/java-8-amazon-corretto' if java == '8' else '/usr/lib/jvm/java-'+java+'-amazon-corretto',
                    inputs={k:item[k] for k in ['distribution','plugin']},
                    tools={'runtime': runtime, 'compiler': compiler, 'utilities':tools['utilities']})
        name = 'es_'+minor.replace('.','_')
        (args.inputs/(name+'.json')).write_text(json.dumps(spec,indent=2,sort_keys=True)+'\n')
        files = sorted({name for i in [*spec['inputs'].values(), *spec['tools'].values()] for name in i.get('chunks', [i['file']])})
        lines.append('offline_fixture_image(name='+repr(name)+', spec='+repr(name+'.json')+', inputs='+repr(files)+
                     ', dockerfile="@@//tests/fixtures/images/elasticsearch:dockerfiles/Dockerfile", '+
                     'cgroup_fix="@@//tests/fixtures/images/elasticsearch:dockerfiles/cgroup_fix.c", exec_properties={"workload":"integration"})')
        lines.append('fixture_publish(name='+repr(name+'_publish')+', image='+repr(':'+name)+', registry="buildbarn-image-cache.migrations-buildbarn.svc.cluster.local:5000", tags=["manual"], exec_properties={"workload":"integration"})')
        lines.append('fixture_smoke_test(name='+repr(name+'_smoke')+', image='+repr(':'+name)+', tags=["manual"], size="large", exec_properties={"workload":"integration"})')
        lines.append('fixture_smoke_test(name='+repr(name+'_registry_smoke')+', image='+repr(':'+name)+', publication='+repr(':'+name+'_publish')+', registry="buildbarn-image-cache.migrations-buildbarn.svc.cluster.local:5000", tags=["manual"], size="large", exec_properties={"workload":"integration"})')
        lines.append('filegroup(name='+repr(name+'_manifest')+', srcs=['+repr(':'+name)+'], output_group="manifest")')
    policy = json.loads((HERE/'long-test-images.json').read_text())['classes']
    for target, versions in policy.items():
        minors = ['.'.join(version.split('.')[:2]) for version in versions]
        if not all(minor in downloads for minor in minors):
            continue
        labels = [':es_'+minor.replace('.','_')+'_publish' for minor in minors]
        lines.append('fixture_catalog(name='+repr('catalog_'+target)+', publications='+repr(labels)+
                     ', registry="buildbarn-image-cache.migrations-buildbarn.svc.cluster.local:5000", exec_properties={"workload":"integration"})')
    (args.inputs/'BUILD.bazel').write_text('\n\n'.join(lines)+'\n')
    (args.inputs/'WORKSPACE.bazel').write_text('workspace(name="fixture_images")\n')
    print('Generated', len(downloads), 'fixture targets')


if __name__ == '__main__':
    main()
