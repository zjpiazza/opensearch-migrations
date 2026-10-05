#!/usr/bin/env python3
"""Explicitly refresh a dependency snapshot; never cache this networked action."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

recipe, archive, metadata = map(Path, sys.argv[1:])
os.environ['HOME'] = tempfile.mkdtemp(prefix='docker-home-', dir=os.getcwd())
tag = 'bazel-fixture-input:' + hashlib.sha256(recipe.read_bytes()).hexdigest()
subprocess.run(['docker', 'build', '--platform=linux/amd64', '-t', tag, '-'],
               input=recipe.read_bytes(), check=True)
image_id = subprocess.check_output(['docker', 'image', 'inspect', '--format={{.Id}}', tag], text=True).strip()
packages = subprocess.check_output(['docker', 'run', '--rm', '--entrypoint=/bin/sh', tag, '-c',
    'if command -v apk >/dev/null; then apk info -vv; else rpm -qa; fi'], text=True).splitlines()
archive.parent.mkdir(parents=True, exist_ok=True)
with archive.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as out:
    with subprocess.Popen(['docker', 'save', tag], stdout=subprocess.PIPE) as child:
        while chunk := child.stdout.read(1024 * 1024):
            out.write(chunk)
        if child.wait():
            raise RuntimeError('docker save failed')
with archive.open('rb') as stream:
    hasher = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        hasher.update(chunk)
    digest = hasher.hexdigest()
metadata.write_text(json.dumps(dict(image_id=image_id, tag=tag, archive_sha256=digest,
    archive_bytes=archive.stat().st_size, recipe_sha256=hashlib.sha256(recipe.read_bytes()).hexdigest(),
    packages=sorted(packages)), indent=2) + '\n')
