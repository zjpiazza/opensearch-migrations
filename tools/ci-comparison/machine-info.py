#!/usr/bin/env python3
"""Write hardware/toolchain details for CI comparison evidence."""
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time


def run(command):
    exe = command[0]
    if shutil.which(exe) is None and not Path(exe).exists():
        return None
    try:
        completed = subprocess.run(command, text=True, capture_output=True, timeout=30)
    except Exception as exc:
        return {'error': repr(exc)}
    return {
        'exit_code': completed.returncode,
        'stdout': completed.stdout.strip(),
        'stderr': completed.stderr.strip(),
    }


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('build/ci-comparison/machine-info.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    info = {
        'timestamp_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'platform': platform.platform(),
        'machine': platform.machine(),
        'processor': platform.processor(),
        'python': sys.version,
        'environment': {k: os.environ.get(k) for k in [
            'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_REF', 'GITHUB_SHA',
            'RUNNER_OS', 'RUNNER_ARCH', 'RUNNER_NAME', 'ImageOS', 'ImageVersion',
        ] if k in os.environ},
        'commands': {
            'nproc': run(['nproc']),
            'lscpu': run(['lscpu']),
            'free': run(['free', '-h']),
            'df': run(['df', '-h']),
            'docker_version': run(['docker', 'version']),
            'docker_info': run(['docker', 'info']),
            'java_version': run(['java', '-version']),
            # Avoid invoking Gradle or Bazel here: both can mutate caches that the
            # benchmark is trying to measure. Their versions are present in build logs.
            'git_head': run(['git', 'rev-parse', 'HEAD']),
            'git_status': run(['git', 'status', '--short']),
        },
    }
    output.write_text(json.dumps(info, indent=2, sort_keys=True) + '\n')
    print(output)


if __name__ == '__main__':
    main()
