#!/usr/bin/env python3
"""Build one fixture offline from declared, verified inputs and export its bytes."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from offline import render
from chunks import ChunkWriter, read_parts, verify


def sha256(path):
    with Path(path).open('rb') as stream:
        hasher = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(chunk)
        return hasher.hexdigest()


def inspect(tag):
    result = subprocess.run(['docker', 'image', 'inspect', '--format={{.Id}}', tag],
                            text=True, capture_output=True)
    return result.stdout.strip() if result.returncode == 0 else None


def main():
    spec_file, dockerfile, fix, archive, manifest, *paths = map(Path, sys.argv[1:])
    spec = json.loads(spec_file.read_text())
    inputs = {p.name: p for p in paths}
    os.environ['HOME'] = tempfile.mkdtemp(prefix='docker-home-', dir=os.getcwd())
    engine = subprocess.check_output(['docker', 'version', '--format={{.Server.Version}}'], text=True).strip()
    if engine != spec['docker_engine']:
        raise ValueError('Docker engine differs from declared toolchain: ' + engine)
    for item in [*spec['inputs'].values(), *spec['tools'].values()]:
        verify(item, inputs)
    for item in spec['tools'].values():
        if inspect(item['tag']) != item['image_id']:
            with subprocess.Popen(['docker', 'load'], stdin=subprocess.PIPE) as child:
                for block in read_parts(item, inputs):
                    child.stdin.write(block)
                child.stdin.close()
                if child.wait():
                    raise RuntimeError('Toolchain docker load failed')
        if inspect(item['tag']) != item['image_id']:
            raise ValueError('Toolchain image ID mismatch: ' + item['tag'])
    with tempfile.TemporaryDirectory(prefix='fixture-', dir=os.getcwd()) as tmp:
        context = Path(tmp)
        (context / 'Dockerfile').write_text(render(dockerfile.read_text()))
        shutil.copyfile(fix, context / 'cgroup_fix.c')
        for role, name in [('distribution', 'elasticsearch.tar.gz'), ('plugin', 'repository-gcs.zip')]:
            with (context / name).open('wb') as dest:
                for block in read_parts(spec['inputs'][role], inputs):
                    dest.write(block)
        tag = 'custom-elasticsearch:' + spec['version']
        args = {'ES_VERSION': spec['version'], 'CORRETTO_VERSION': spec['java'],
                'JAVA_HOME_PATH': spec['java_home'], 'SOURCE_DATE_EPOCH': '0',
                'DOWNLOADER_IMAGE': spec['tools']['utilities']['tag'],
                'CONFIG_BUILDER_IMAGE': spec['tools']['utilities']['tag'],
                'CGROUP_BUILDER_IMAGE': spec['tools']['compiler']['tag'],
                'RUNTIME_IMAGE': spec['tools']['runtime']['tag']}
        command = ['docker', 'build', '--platform=linux/amd64', '--network=none', '--pull=false', '-t', tag]
        for key, value in sorted(args.items()):
            command += ['--build-arg', key + '=' + value]
        subprocess.run([*command, str(context)], check=True)
        image_id = inspect(tag)
        if not image_id:
            raise RuntimeError('Image build did not produce ' + tag)
        archive.parent.mkdir(parents=True, exist_ok=True)
        raw = ChunkWriter(archive)
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=1) as out:
            with subprocess.Popen(['docker', 'save', tag], stdout=subprocess.PIPE) as child:
                while chunk := child.stdout.read(1024 * 1024):
                    out.write(chunk)
                if child.wait():
                    raise RuntimeError('docker save failed')
        raw.close()
        manifest.write_text(json.dumps({'image': tag, 'image_id': image_id,
            'archive_sha256': raw.hasher.hexdigest(), 'archive_format': 'docker-save-gzip-chunks', 'platform': 'linux/amd64'}, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
