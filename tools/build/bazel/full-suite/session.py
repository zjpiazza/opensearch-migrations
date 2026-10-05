#!/usr/bin/env python3
"""Run a focused benchmark in tmux with an automatically reconnected frontend tunnel.

Usage: session.py SESSION -- --pool all --output ... --baseline ... --instance ...
The session owns localhost:8980 exclusively. Detaching/closing a terminal does
not stop the benchmark. The session exits when validation finishes; logs remain.
"""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[4]


@contextmanager
def tunnel(log_path, service="frontend", local_port=8980, remote_port=8980):
    # Refuse to borrow a tunnel whose lifetime this session does not control.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', local_port))
    stop = threading.Event()
    ready = threading.Event()

    def maintain():
        with log_path.open('a') as log:
            while not stop.is_set():
                child = subprocess.Popen([
                    'kubectl', '--context', 'do-atl1-bazel', '-n', 'migrations-buildbarn',
                    'port-forward', '--address', '127.0.0.1', 'service/' + service, f'{local_port}:{remote_port}',
                ], stdout=log, stderr=subprocess.STDOUT)
                try:
                    while child.poll() is None and not stop.wait(1):
                        try:
                            with socket.create_connection(('127.0.0.1', local_port), timeout=1):
                                ready.set()
                        except OSError:
                            pass
                finally:
                    if child.poll() is None:
                        child.terminate()
                        try:
                            child.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait()
                stop.wait(2)

    thread = threading.Thread(target=maintain, daemon=True)
    thread.start()
    try:
        if not ready.wait(60):
            raise RuntimeError('Service tunnel was not ready within 60 seconds; see ' + str(log_path))
        yield
    finally:
        stop.set()
        thread.join(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--foreground', action='store_true')
    parser.add_argument('session')
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.session or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in args.session):
        parser.error('Use lowercase letters, numbers, hyphens or underscores for the session name')
    command_args = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    options = argparse.ArgumentParser(add_help=False)
    options.add_argument('--output', type=Path, required=True)
    output = options.parse_known_args(command_args)[0].output.resolve()
    if output.exists():
        parser.error('Evidence output already exists; choose a new run name')
    output.parent.mkdir(parents=True, exist_ok=True)
    if not args.foreground:
        command = [sys.executable, str(Path(__file__).resolve()), '--foreground', args.session, '--', *command_args]
        subprocess.run(['tmux', 'new-session', '-d', '-s', args.session, '-c', str(ROOT),
                        shlex.join(command)], check=True)
        print('Started tmux session ' + args.session)
        print('Supervisor log: ' + str(output.with_suffix('.session.log')))
        return 0
    log_path = output.with_suffix('.session.log')
    metadata = {'session': args.session, 'started_at_epoch': time.time(), 'arguments': command_args}
    with log_path.open('x') as log:
        log.write(json.dumps(metadata) + '\n')
        log.flush()
        try:
            with tunnel(output.with_suffix('.tunnel.log')):
                sampler = subprocess.Popen([sys.executable, str(Path(__file__).with_name('sample-resources.py')),
                                            '--run', str(output)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
                try:
                    result = subprocess.run([sys.executable, str(Path(__file__).with_name('run-focused.py')),
                                             *command_args], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
                finally:
                    sampler.terminate()
                    sampler.wait(timeout=20)
                metadata.update(exit_code=result.returncode, finished_at_epoch=time.time())
                log.write(json.dumps(metadata) + '\n')
                return result.returncode
        except Exception as error:
            log.write(repr(error) + '\n')
            raise


if __name__ == '__main__':
    raise SystemExit(main())
