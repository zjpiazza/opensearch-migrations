#!/usr/bin/env python3
"""Materialize declared Gradle fixtures and execute one exported test target."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile


def main():
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
    env.update({'HOME': str(work / '.home'), 'AWS_EC2_METADATA_DISABLED': 'true',
                'AWS_CONFIG_FILE': '/dev/null', 'AWS_SHARED_CREDENTIALS_FILE': '/dev/null',
                'DOCKER_HOST': 'tcp://127.0.0.1:2375', 'TESTCONTAINERS_HOST_OVERRIDE': '127.0.0.1'})
    Path(env['HOME']).mkdir(exist_ok=True)
    # The daemon owns its socket; Testcontainers' Ryuk container mounts that socket.
    env['TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE'] = '/var/run/docker.sock'
    cwd = work / spec['workingDirectory']
    cwd.mkdir(parents=True, exist_ok=True)
    if spec['kind'] == 'npm':
        node = bundle / spec['nodeHome']
        env['PATH'] = str(node / 'bin') + ':' + env.get('PATH', '')
        command = [str(node / 'bin/node'), str(node / 'lib/node_modules/npm/bin/npm-cli.js'), *spec['args']]
    else:
        java = bundle / spec['javaHome'] / 'bin/java'
        cp = [str(work / p) if directory else str(bundle / p) for p, directory in spec['classpath']]
        cp.insert(0, str(bundle / spec['console']))
        props = {k: v.replace('@ROOT@', str(work)) for k, v in spec['properties'].items()}
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
    result = subprocess.run(command, cwd=cwd, env=env)
    (output / 'invocation.json').write_text(json.dumps({'task':spec['task'], 'class':sys.argv[2], 'exit_code':result.returncode}))
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
