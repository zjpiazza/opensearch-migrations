#!/usr/bin/env python3
"""Export prepared Gradle runtimes as a generated Bazel repository.

Run exportBazelTestRuntime first. Each task/class has its actual runtime inputs;
Gradle still performs compilation, dependency resolution, and fixture generation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile

from worker_routing import properties as worker_properties
from sharding import build_helper, policy as shard_policy

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / 'build/full-suite'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def clean_name(value):
    return re.sub(r'[^A-Za-z0-9_.-]', '_', value).strip('_')


def normalized(info):
    info.uid = info.gid = 0
    info.uname = info.gname = ''
    info.mtime = 0
    return info


def archive(name, paths):
    dest = OUT / 'archives' / (name + '.tar')
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest, 'w') as tar:
        for p in sorted(set(paths)):
            tar.add(p, arcname=p.relative_to(ROOT).as_posix(), filter=normalized)
    return dest.relative_to(OUT).as_posix()


def copy_file(path):
    try:
        suffix = 'project/' + path.relative_to(ROOT).as_posix()
    except ValueError:
        # Stable Maven coordinates/hash, independent of the client home directory.
        s = path.as_posix()
        suffix = 'maven/' + s.split('/files-2.1/', 1)[1] if '/files-2.1/' in s else 'other/' + hashlib.sha256(path.read_bytes()).hexdigest() + '/' + path.name
    dest = OUT / 'inputs' / suffix
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists(): dest.unlink()
    shutil.copy2(path, dest)
    return dest.relative_to(OUT).as_posix()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', type=Path, default=ROOT / 'build/full-suite-export.json')
    parser.add_argument('--unsharded', action='store_true', help='Retain class-level execution for an A/B baseline')
    parser.add_argument('--fixture-images', action='store_true', help='Declare prepared Bazel image catalogs for the reviewed long integration tests')
    args = parser.parse_args()
    manifest = json.loads(args.export.read_text())
    assert Path(manifest['root']) == ROOT
    OUT.mkdir(parents=True, exist_ok=True)
    tools = OUT / 'tools'; tools.mkdir(exist_ok=True)
    console = tools / 'junit-platform-console-standalone-1.14.0.jar'
    if not console.exists():
        urllib.request.urlretrieve('https://repo.maven.apache.org/maven2/org/junit/platform/junit-platform-console-standalone/1.14.0/junit-platform-console-standalone-1.14.0.jar', console)
    expected_console_sha256 = '097022055fe55a34b33b868be077629190d4a1c66c571478338686074ccf6e97'
    if hashlib.sha256(console.read_bytes()).hexdigest() != expected_console_sha256:
        raise RuntimeError('JUnit Console SHA-256 mismatch: ' + str(console))
    java_home = Path(manifest['java'][0]['javaHome'])
    if (tools / 'jdk').exists():
        shutil.rmtree(tools / 'jdk')
    shutil.copytree(java_home, tools / 'jdk', symlinks=True)
    # Drop non-runtime Gradle installation markers from the exported toolchain.
    subprocess.run([str(java_home/'bin/javac'), '-cp', str(console), '-d', str(tools), str(ROOT/'tools/build/bazel/full-suite/DiscoverTests.java')], check=True)
    build_helper(java_home, tools)
    sharding = shard_policy(args.unsharded)
    agent = next(Path.home().glob('.gradle/caches/modules-2/files-2.1/org.jacoco/org.jacoco.agent/0.8.13/*/*.jar'))
    with zipfile.ZipFile(agent) as z: (tools/'jacocoagent.jar').write_bytes(z.read('jacocoagent.jar'))
    tracked = subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    fixtures = [ROOT/p for p in tracked if p and (('/src/test/resources/' in p) or '/test-resources/' in p or '/custom_transform/' in p)]
    fixtures += [ROOT/'tools/build/bazel/full-suite/build-image.py',
                 ROOT/'tests/fixtures/images/elasticsearch/versions.json',
                 ROOT/'tests/fixtures/images/elasticsearch/dockerfiles']
    shared = archive('fixtures', fixtures)
    directory_archives = {}
    lines = ['load("@@//tools/build/bazel/full-suite:defs.bzl", "exported_test")',
             'filegroup(name="jdk", srcs=glob(["tools/jdk/**"], exclude=["**/BUILD", "**/BUILD.bazel"]))']
    evidence = {'java_tasks': [], 'npm_tasks': [], 'targets': [], 'limitations': ['Gradle prepares and compiles the runtimes; this is an execution-only Bazel bridge.']}
    for task in manifest['java']:
        if not task['enabled'] or not task['candidateClasses']:
            evidence['java_tasks'].append({'task':task['task'], 'classes':[], 'reason':'disabled or no class files'})
            continue
        ident = clean_name(task['task'])
        candidates = set()
        for filename in task['candidateClasses']:
            for root in task['testClasses']:
                try: rel = Path(filename).relative_to(root)
                except ValueError: continue
                name = rel.as_posix().removesuffix('.class').replace('/','.')
                if '$' not in name and name not in ('module-info','package-info'):
                    candidates.add(name)
        path = OUT / 'discovery' / (ident+'.txt'); write(path, '\n'.join(sorted(candidates))+'\n')
        cp = ':'.join([str(console), str(tools), *task['classpath']])
        command = [str(java_home/'bin/java'), '-cp', cp, 'DiscoverTests', str(path)]
        for key, flag in [('includeTags','includeTag'),('excludeTags','excludeTag'),('includeEngines','includeEngine'),('excludeEngines','excludeEngine')]:
            for value in task[key]: command += [flag,value]
        result = subprocess.run(command, text=True, capture_output=True)
        write(OUT/'discovery'/(ident+'.log'), result.stdout+result.stderr)
        if result.returncode: raise RuntimeError('Discovery failed: '+task['task']+'\n'+result.stderr[-4000:])
        classes = sorted({s.split('\t')[1] for s in result.stdout.splitlines() if s.startswith('BAZEL_CLASS\t')})
        evidence['java_tasks'].append({'task':task['task'],'classes':classes})
        if not classes: continue
        spec = {k:task[k] for k in ['task','workingDirectory','jvmArgs','minHeapSize','maxHeapSize','includeTags','excludeTags','includeEngines','excludeEngines']}
        spec.update(kind='java',javaHome='tools/jdk',console=console.relative_to(OUT).as_posix(),classpath=[],archives=[shared],shardHelper='tools/bazel-sharding.jar')
        spec['properties'] = {k:v.replace(str(ROOT),'@ROOT@') for k,v in task['properties'].items()}
        spec['properties']['test.image.builder'] = '@ROOT@/tools/build/bazel/full-suite/build-image.py'
        if task['jacocoEnabled']: spec['jacoco']='tools/jacocoagent.jar'
        data = [':jdk',spec['console'],spec.get('jacoco')]
        for filename in task['classpath']:
            path = Path(filename)
            if path.is_dir():
                relative = path.relative_to(ROOT).as_posix()
                if relative not in directory_archives:
                    directory_archives[relative] = archive(clean_name(relative), [path])
                spec['archives'].append(directory_archives[relative])
                spec['classpath'].append([relative,True])
            else:
                name = copy_file(path); data.append(name);spec['classpath'].append([name,False])
        for value in task['properties'].values():
            if value.startswith(str(ROOT)) and Path(value).is_file(): spec['archives'].append(archive(ident+'-property',[Path(value)]))
        spec['archives']=list(dict.fromkeys(spec['archives']))
        filename='specs/'+ident+'.json';write(OUT/filename,json.dumps(spec,indent=2)+'\n')
        group=ident+'_runtime'; lines.append('filegroup(name='+repr(group)+', srcs='+repr(sorted(set(filter(None,data+spec['archives']))))+')')
        for cls in classes:
            target=ident+'__'+cls
            shard = sharding.get(task['task']+'|'+cls, {})
            count = shard.get('count', 1)
            if not isinstance(count, int) or not 1 <= count <= 50:
                raise ValueError('Invalid shard count for '+target)
            grouping = shard.get('grouping', 'fixture-index')
            if grouping not in ('fixture-index', 'independent'):
                raise ValueError('Invalid shard grouping for '+target)
            target_data = [':'+group] + ([spec['shardHelper']] if count > 1 else [])
            lines.append('exported_test(name='+repr(target)+', spec='+repr(filename)+', data='+repr(target_data)+', test_class='+repr(cls)+', shard_count='+repr(count if count > 1 else 0)+', shard_grouping='+repr(grouping)+', size="enormous", timeout="eternal", exec_properties='+repr(worker_properties(task['task'],cls))+')')
            evidence['targets'].append({'target':target,'task':task['task'],'class':cls,'shard_count':count,'shard_grouping':grouping,'exec_properties':worker_properties(task['task'],cls)})
        print(task['task'],len(classes),'classes',flush=True)
    unknown = set(sharding) - {t['task']+'|'+t['class'] for t in evidence['targets']}
    if unknown:
        raise ValueError('Shard configuration refers to undiscovered classes: '+repr(sorted(unknown)))
    npm_archives={}
    for task in manifest['npm']:
        ident=clean_name(task['task']); working=task['workingDirectory']
        project='apps/orchestration' if working.startswith('apps/orchestration/') else working
        if project not in npm_archives:
            base=ROOT/project
            paths=[p for p in base.iterdir() if p.name not in ('build','.gradle','coverage','.git')]
            npm_archives[project]=archive(clean_name(project),paths)
        node='tools/node-'+Path(task['nodeHome']).name
        if not (OUT/node).exists(): shutil.copytree(task['nodeHome'], OUT/node, symlinks=True)
        spec=dict(task,kind='npm',nodeHome=node,archives=[npm_archives[project],shared])
        filename='specs/'+ident+'.json'; write(OUT/filename,json.dumps(spec,indent=2)+'\n')
        lines.append('exported_test(name='+repr(ident)+', spec='+repr(filename)+', data=glob(['+repr(node+'/**')+'])+'+repr(spec['archives'])+', size="large", exec_properties='+repr(worker_properties(task['task']))+')')
        evidence['npm_tasks'].append(task['task']); evidence['targets'].append({'target':ident,'task':task['task'],'exec_properties':worker_properties(task['task'])})
    lines.append('test_suite(name="all_tests", tests='+repr([':'+t['target'] for t in evidence['targets']])+')')
    write(OUT/'BUILD.bazel','\n\n'.join(lines)+'\n');write(OUT/'WORKSPACE.bazel','workspace(name="full_suite")\n')
    write(OUT/'inventory.json',json.dumps(evidence,indent=2)+'\n')
    if args.fixture_images:
        subprocess.run(['python3', str(Path(__file__).with_name('configure-fixtures.py')), '--runtime', str(OUT)], check=True)
    print('Exported',len(evidence['targets']),'targets')


if __name__ == '__main__': main()
