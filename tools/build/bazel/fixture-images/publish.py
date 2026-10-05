#!/usr/bin/env python3
"""Publish a recoverable image artifact; this side-effecting action is never cached."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request


def existing(registry, repository, tag, expected):
    url = 'http://' + registry + '/v2/' + repository + '/manifests/' + tag
    request = urllib.request.Request(url, headers={'Accept': 'application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.manifest.v1+json'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
            if json.loads(raw)['config']['digest'] != expected:
                raise ValueError('Registry tag points at unexpected image content')
            return registry + '/' + repository + '@' + digest
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def main():
    archive, manifest, output = map(Path, sys.argv[1:4])
    registry = sys.argv[4]
    item = json.loads(manifest.read_text())
    expected = item['image_id']
    repository = 'fixtures/elasticsearch'
    tag = expected.removeprefix('sha256:')
    reference = existing(registry, repository, tag, expected)
    if reference is None:
        os.environ['HOME'] = tempfile.mkdtemp(prefix='docker-home-', dir=os.getcwd())
        hasher = hashlib.sha256()
        # Validate the complete artifact before mutating the Docker daemon.
        for part in sorted(archive.iterdir()):
            with part.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024*1024), b''):
                    hasher.update(chunk)
        if hasher.hexdigest() != item['archive_sha256']:
            raise ValueError('Fixture archive checksum mismatch')
        with subprocess.Popen(['docker', 'load'], stdin=subprocess.PIPE) as child:
            for part in sorted(archive.iterdir()):
                with part.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024*1024), b''):
                        child.stdin.write(chunk)
            child.stdin.close()
            if child.wait():
                raise RuntimeError('docker load failed')
        actual = subprocess.check_output(['docker', 'image', 'inspect', '--format={{.Id}}', item['image']], text=True).strip()
        if actual != expected:
            raise ValueError('Archive image identity mismatch')
        named = registry + '/' + repository + ':' + tag
        subprocess.run(['docker', 'tag', expected, named], check=True)
        subprocess.run(['docker', 'push', named], check=True)
        reference = existing(registry, repository, tag, expected)
        if reference is None:
            raise RuntimeError('Published image is missing')
    output.write_text(json.dumps(dict(image=item['image'], image_id=expected, reference=reference), sort_keys=True)+'\n')
    print('Published verified fixture:', reference, flush=True)


if __name__ == '__main__':
    main()
