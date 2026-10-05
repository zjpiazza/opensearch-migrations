#!/usr/bin/env python3
"""Materialize declared Gradle fixtures and execute one exported test target."""
import json
import gzip
from collections import deque
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time
import xml.etree.ElementTree as ET


def main():
    started = time.monotonic()
    spec_path = Path(sys.argv[1]).resolve()
    # Every spec lives under specs/ in the generated repository.
    bundle = spec_path.parent.parent
    spec = json.loads(spec_path.read_text())
    work = Path(os.environ['TEST_TMPDIR']) / 'workspace'
    work.mkdir(parents=True)
    for archive in spec['archives']:
        with tarfile.open(bundle / archive) as tar:
            tar.extractall(work)
    output = Path(os.environ['TEST_UNDECLARED_OUTPUTS_DIR']).resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    shards = int(env.get('TEST_TOTAL_SHARDS', '1'))
    shard_index = int(env.get('TEST_SHARD_INDEX', '0'))
    if not 0 <= shard_index < shards:
        raise ValueError('Invalid Bazel shard coordinates')
    docker_host = env.get('CI_COMPARISON_DOCKER_HOST') or env.get('DOCKER_HOST') or 'tcp://127.0.0.1:2375'
    testcontainers_host = env.get('CI_COMPARISON_TESTCONTAINERS_HOST_OVERRIDE') or '127.0.0.1'
    docker_socket = env.get('CI_COMPARISON_DOCKER_SOCKET_OVERRIDE') or '/var/run/docker.sock'
    env.update({'HOME': str(work / '.home'), 'AWS_EC2_METADATA_DISABLED': 'true',
                'AWS_CONFIG_FILE': '/dev/null', 'AWS_SHARED_CREDENTIALS_FILE': '/dev/null',
                'DOCKER_HOST': docker_host, 'TESTCONTAINERS_HOST_OVERRIDE': testcontainers_host})
    Path(env['HOME']).mkdir(exist_ok=True)
    # The daemon owns its socket; Testcontainers' Ryuk container mounts that socket.
    env['TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE'] = docker_socket
    cwd = work / spec['workingDirectory']
    cwd.mkdir(parents=True, exist_ok=True)
    if spec['kind'] == 'npm':
        if shards > 1:
            raise ValueError('npm checks do not support this Jupiter shard adapter')
        node = bundle / spec['nodeHome']
        env['PATH'] = str(node / 'bin') + ':' + env.get('PATH', '')
        command = [str(node / 'bin/node'), str(node / 'lib/node_modules/npm/bin/npm-cli.js'), *spec['args']]
    else:
        java = bundle / spec['javaHome'] / 'bin/java'
        cp = [str(work / p) if directory else str(bundle / p) for p, directory in spec['classpath']]
        cp.insert(0, str(bundle / spec['console']))
        props = {k: v.replace('@ROOT@', str(work)) for k, v in spec['properties'].items()}
        if shards > 1:
            cp.insert(1, str(bundle / spec['shardHelper']))
            props['junit.jupiter.extensions.autodetection.enabled'] = 'true'
            props['junit.jupiter.extensions.autodetection.include'] = 'org.opensearch.migrations.testinfra.BazelShardCondition'
            props['bazel.shard.grouping'] = sys.argv[3] if len(sys.argv) > 3 else 'fixture-index'
        # Java does not derive user.home from HOME. Graal and fixtures extract
        # runtime resources there; the worker UID's default home is unwritable.
        if len(sys.argv) > 4:
            props['test.image.catalog'] = str(Path(sys.argv[4]).resolve(strict=True))
            props['test.image.loader'] = str(Path(sys.argv[5]).resolve(strict=True))
            props.pop('test.image.builder', None)
        props['user.home'] = env['HOME']
        props['java.io.tmpdir'] = str(work / '.tmp')
        Path(props['java.io.tmpdir']).mkdir(exist_ok=True)
        command = [str(java), *spec['jvmArgs'], '-ea']
        if spec.get('maxHeapSize'): command += ['-Xmx' + spec['maxHeapSize']]
        if spec.get('minHeapSize'): command += ['-Xms' + spec['minHeapSize']]
        if spec.get('jacoco'):
            command += ['-javaagent:' + str(bundle / spec['jacoco']) + '=destfile=' + str(output / 'jacoco.exec')]
        command += [f'-D{k}={v}' for k, v in sorted(props.items())]
        command += ['-cp', ':'.join(cp), 'org.junit.platform.console.ConsoleLauncher', 'execute',
                    '--select-class=' + sys.argv[2], '--fail-if-no-tests', '--disable-banner',
                    '--details=summary', '--reports-dir=' + str(output / 'junit')]
        for key, flag in [('includeTags','include-tag'),('excludeTags','exclude-tag'),
                          ('includeEngines','include-engine'),('excludeEngines','exclude-engine')]:
            for value in spec[key]: command.append('--' + flag + '=' + value)
    print('Gradle task:', spec['task'], 'class:', sys.argv[2], flush=True)
    # Preserve complete diagnostics without making Bazel transfer the same large
    # stdout twice (test.log and its fallback synthetic test.xml).
    prepared = time.monotonic()
    print('Fixture preparation seconds:', round(prepared - started, 3), flush=True)
    tail = deque(maxlen=4)
    with gzip.open(output / 'test-output.log.gz', 'wb', compresslevel=1) as log:
        with subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT) as child:
            for chunk in iter(lambda: child.stdout.read(16384), b''):
                log.write(chunk)
                tail.append(chunk)
            code = child.wait()
    executed = time.monotonic()
    print(b''.join(tail).decode('utf-8', errors='replace')[-8000:], flush=True)
    reports = ET.Element('testsuites')
    filtered = 0
    for report in sorted((output / 'junit').glob('*.xml')):
        tree = ET.parse(report)
        suite = tree.getroot()
        # Other shards own these cases; do not count them as skipped coverage.
        for parent in suite.iter():
            for case in list(parent):
                skipped = case.find('skipped') if case.tag == 'testcase' else None
                if skipped is not None and 'Bazel shard: owned by ' in (skipped.attrib.get('message', '') + (skipped.text or '')):
                    parent.remove(case)
                    filtered += 1
        cases = list(suite.iter('testcase'))
        suite.set('tests', str(len(cases)))
        suite.set('skipped', str(sum(c.find('skipped') is not None for c in cases)))
        tree.write(report, encoding='utf-8', xml_declaration=True)
        reports.append(suite)
    if not list(reports) or (code and not reports.findall('.//failure') and not reports.findall('.//error')):
        suite = ET.SubElement(reports, 'testsuite', name=spec['task'], tests='1', failures=str(int(code != 0)))
        case = ET.SubElement(suite, 'testcase', name=sys.argv[2] or spec['task'], classname=spec['task'])
        if code:
            ET.SubElement(case, 'failure', message='Process exit code ' + str(code)).text = (
                'See test-output.log.gz for complete diagnostics.')
    ET.ElementTree(reports).write(os.environ['XML_OUTPUT_FILE'], encoding='utf-8', xml_declaration=True)
    (output / 'invocation.json').write_text(json.dumps({'task':spec['task'], 'class':sys.argv[2], 'exit_code':code,
                                                      'shard_index':shard_index, 'shard_count':shards, 'cases_owned_by_other_shards':filtered,
                                                      'timing_seconds': {
                                                          'preparation': round(prepared - started, 3),
                                                          'execution': round(executed - prepared, 3),
                                                          'reporting': round(time.monotonic() - executed, 3),
                                                          'total': round(time.monotonic() - started, 3),
                                                      }}))
    return code


if __name__ == '__main__':
    sys.exit(main())
