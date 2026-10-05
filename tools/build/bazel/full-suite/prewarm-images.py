#!/usr/bin/env python3
"""Populate an internal Distribution mirror, verifying every Linux/amd64 blob.

Use an authenticated kubectl port-forward to the image-cache service. Downloads
stream through this client without retaining another local copy. The resulting
report records tag resolution and byte counts; it does not pin test image tags.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import urllib.request

ACCEPT = ', '.join([
    'application/vnd.oci.image.index.v1+json',
    'application/vnd.docker.distribution.manifest.list.v2+json',
    'application/vnd.oci.image.manifest.v1+json',
    'application/vnd.docker.distribution.manifest.v2+json',
])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', default='http://127.0.0.1:15000')
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new output file to preserve earlier preparation evidence')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {'started_at_epoch': time.time(), 'registry': args.registry,
              'inventory': json.loads(args.inventory.read_text()), 'images': [], 'status': 'running'}
    seen = set()

    def save():
        args.output.write_text(json.dumps(report, indent=2) + '\n')

    def fetch(repo, path, expected=None, size=None):
        request = urllib.request.Request(args.registry.rstrip('/') + '/v2/' + repo + '/' + path,
                                         headers={'Accept': ACCEPT})
        for attempt in range(3):
            try:
                digest = hashlib.sha256()
                count = 0
                parts = []
                with urllib.request.urlopen(request, timeout=180) as response:
                    while chunk := response.read(1024 * 1024):
                        digest.update(chunk)
                        count += len(chunk)
                        if path.startswith('manifests/'):
                            parts.append(chunk)
                actual = 'sha256:' + digest.hexdigest()
                if expected is not None and actual != expected:
                    raise ValueError('Digest mismatch: ' + path)
                if size is not None and count != size:
                    raise ValueError('Size mismatch: ' + path)
                return b''.join(parts), actual, count
            except (OSError, TimeoutError):
                if attempt == 2:
                    raise
                time.sleep(5 * (attempt + 1))

    save()
    try:
        for image in report['inventory']['images']:
            started = time.monotonic()
            repo, tag = image.rsplit(':', 1)
            raw, digest, _ = fetch(repo, 'manifests/' + tag)
            manifest = json.loads(raw)
            if 'manifests' in manifest:
                descriptor = next(m for m in manifest['manifests']
                                  if m['platform'].get('architecture') == 'amd64'
                                  and m['platform'].get('os') == 'linux')
                raw, digest, _ = fetch(repo, 'manifests/' + descriptor['digest'], descriptor['digest'])
                manifest = json.loads(raw)
            blobs = [manifest['config'], *manifest['layers']]
            fetched = 0
            for blob in blobs:
                # Verify a shared blob once per repository, avoiding duplicate transfers.
                key = repo, blob['digest']
                if key not in seen:
                    fetch(repo, 'blobs/' + blob['digest'], blob['digest'], blob['size'])
                    seen.add(key)
                    fetched += blob['size']
            row = {'image': image, 'manifest': digest, 'verified_new_bytes': fetched,
                   'image_bytes': sum(b['size'] for b in blobs),
                   'seconds': round(time.monotonic() - started, 3)}
            report['images'].append(row)
            save()
            print(json.dumps(row), flush=True)
        report['status'] = 'complete'
    except Exception as error:
        report.update(status='failed', error=repr(error), failed_image=image)
        raise
    finally:
        report['elapsed_seconds'] = round(time.time() - report['started_at_epoch'], 3)
        save()


if __name__ == '__main__':
    main()
