#!/usr/bin/env python3
"""Fetch fixture distributions/plugins and explicitly record or verify their hashes.

The refresh operation is preparation, not a cacheable build. Later builds consume
only these exact bytes and run Docker RUN instructions with networking disabled.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
from chunks import materialize_parts

ROOT = Path(__file__).resolve().parents[4]


def digest(path):
    with path.open('rb') as f:
        hasher = hashlib.sha256()
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            hasher.update(chunk)
        return hasher.hexdigest()


def download(url, path):
    if not path.exists():
        partial = path.with_suffix(path.suffix + '.partial')
        subprocess.run(['curl', '-fSL', '--http1.1', '--retry', '5', '--retry-all-errors',
                        '--connect-timeout', '30', '--max-time', '600', '-o', str(partial), url], check=True)
        partial.replace(path)
    return {'file': path.name, 'url': url, 'sha256': digest(path), 'bytes': path.stat().st_size}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('versions', nargs='+', help='Minor versions such as 7.10')
    p.add_argument('--output', type=Path, default=ROOT/'build/fixture-image-inputs')
    p.add_argument('--lock', type=Path, default=Path(__file__).with_name('downloads.lock.json'))
    p.add_argument('--refresh-lock', action='store_true')
    p.add_argument('--chunk-inputs', action='store_true', help='Retain only verified CAS-sized parts for large downloads')
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    versions = json.loads((ROOT/'tests/fixtures/images/elasticsearch/versions.json').read_text())
    lock = json.loads(args.lock.read_text()) if args.lock.exists() else {}
    for minor in args.versions:
        if not args.refresh_lock and minor not in lock:
            raise ValueError('No pinned inputs for ' + minor + '; explicitly refresh the lock first')
        item = versions[minor]
        version = item['version']
        url = item['url'].replace('ARCH', 'x86_64')
        distribution = args.output/f'elasticsearch-{version}.tar.gz'
        record = {'version': version, 'distribution': download(url, distribution)}
        plugin = args.output/f'repository-gcs-{version}.zip'
        with tarfile.open(distribution) as tar:
            bundled = any('/modules/repository-gcs/' in member.name for member in tar)
        if int(minor.split('.')[0]) < 5 or bundled:
            plugin.write_bytes(b'')
            record['plugin'] = {'file': plugin.name, 'sha256': digest(plugin), 'bytes': 0,
                                'reason': 'bundled module' if bundled else 'not supported'}
        else:
            record['plugin'] = download(f'https://artifacts.elastic.co/downloads/elasticsearch-plugins/repository-gcs/repository-gcs-{version}.zip', plugin)
        if args.refresh_lock:
            lock[minor] = record
            args.lock.write_text(json.dumps(lock, indent=2, sort_keys=True)+'\n')
        elif record != lock[minor]:
            raise ValueError('Fixture inputs differ from lock: ' + minor)
        if args.chunk_inputs:
            for role in ['distribution', 'plugin']:
                materialize_parts(args.output, record[role], remove_original=True)
        print(minor, 'verified', flush=True)


if __name__ == '__main__':
    main()
