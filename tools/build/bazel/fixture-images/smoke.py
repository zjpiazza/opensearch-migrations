#!/usr/bin/env python3
"""Exercise a cached fixture artifact after removing that image from this worker."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
from load import load


def docker(*args, **kwargs):
    return subprocess.check_output(['docker', *args], text=True, **kwargs).strip()


def main():
    archive, manifest = map(Path, sys.argv[1:3])
    item = json.loads(manifest.read_text())
    expected = item['image_id']
    os.environ['DOCKER_HOST'] = 'tcp://127.0.0.1:2375'
    # One test per Docker-capable worker; only remove this fixture image, not
    # arbitrary worker images. Existing base layers may still be warm.
    inspect = subprocess.run(['docker', 'image', 'inspect', expected], capture_output=True)
    if inspect.returncode == 0:
        docker('image', 'rm', '--force', expected)
    assert subprocess.run(['docker', 'image', 'inspect', expected], capture_output=True).returncode != 0
    registry = sys.argv[3] if len(sys.argv)>3 else ''
    if registry:
        load({'images':{item['image']:{'image_id':expected,
            'reference':registry+'/fixtures/elasticsearch:'+expected.removeprefix('sha256:')}}}, item['image'])
    else:
        hasher = hashlib.sha256()
        with subprocess.Popen(['docker', 'load'], stdin=subprocess.PIPE) as child:
            for part in sorted(archive.iterdir()):
                with part.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024*1024), b''):
                        hasher.update(block)
                        child.stdin.write(block)
            child.stdin.close()
            if child.wait():
                raise RuntimeError('Fixture image load failed')
        assert hasher.hexdigest() == item['archive_sha256']
    assert docker('image', 'inspect', '--format={{.Id}}', item['image']) == expected
    container = docker('run', '-d', '-p', '127.0.0.1::9200', '-e', 'ES_JAVA_OPTS=-Xms256m -Xmx256m', expected)
    try:
        binding = json.loads(docker('inspect', '--format={{json .NetworkSettings.Ports}}', container))['9200/tcp'][0]
        base = 'http://127.0.0.1:' + binding['HostPort']
        def request(path, method='GET', value=None):
            data = None if value is None else json.dumps(value).encode()
            req = urllib.request.Request(base+path, data=data, method=method, headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req, timeout=5) as response:
                return json.load(response)
        deadline = time.monotonic()+120
        while True:
            try:
                version = request('/')['version']['number']
                break
            except (OSError, urllib.error.URLError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)
        assert version == item['image'].split(':')[-1]
        request('/cache-smoke/_doc/1?refresh=true', 'PUT', {'proof':'cached-fixture'})
        assert request('/cache-smoke/_doc/1')['_source']['proof'] == 'cached-fixture'
        node = next(iter(request('/_nodes/plugins')['nodes'].values()))
        assert any(p['name']=='repository-gcs' for p in node['plugins']+node.get('modules',[]))
        output = Path(os.environ['TEST_UNDECLARED_OUTPUTS_DIR'])/'fixture-smoke.json'
        output.write_text(json.dumps(dict(image=item['image'], image_id=expected,
            absent_before_load=True, source='registry' if registry else 'archive', version=version, document_round_trip=True, gcs_plugin_present=True), indent=2)+'\n')
    except Exception:
        print(docker('logs', container), flush=True)
        raise
    finally:
        docker('rm', '--force', '--volumes', container)


if __name__ == '__main__':
    main()
