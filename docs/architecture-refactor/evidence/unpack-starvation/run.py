#!/usr/bin/env python3
"""Diagnostic using an existing full-suite export; does not rebuild or modify it."""
import json
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[4]
bundle = root / 'build/full-suite'
spec = json.loads((bundle / 'specs/DocumentsFromSnapshotMigration_isolatedTest.json').read_text())
classpath = ':'.join(str(bundle / path) for path, directory in spec['classpath'] if not directory)
with tempfile.TemporaryDirectory(prefix='unpack-probe-') as output:
    subprocess.run([str(bundle / 'tools/jdk/bin/javac'), '-proc:none', '-cp', classpath,
                    '-d', output, str(Path(__file__).with_name('UnpackProbe.java'))], check=True)
    for processors in (1, 4):
        print(f'Visible CPUs: {processors}', flush=True)
        subprocess.run([str(bundle / 'tools/jdk/bin/java'), f'-XX:ActiveProcessorCount={processors}',
                        '-cp', output + ':' + classpath, 'UnpackProbe'], check=True, timeout=30)
