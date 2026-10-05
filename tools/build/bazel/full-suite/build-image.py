#!/usr/bin/env python3
"""Build the original ES fixture Dockerfile without starting a nested Gradle build."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[4]
match = re.fullmatch(r':custom-es-images:buildImage_es_(\d+)_(\d+)', sys.argv[1])
if not match:
    raise SystemExit('Unsupported image task: '+sys.argv[1])
major, minor = map(int, match.groups())
info = json.loads((root/'tests/fixtures/images/elasticsearch/versions.json').read_text())[f'{major}.{minor}']
corretto = '8' if major <= 5 or (major == 6 and minor <= 4) else '11' if major == 6 or (major == 7 and minor <= 10) else '17' if major == 7 else '21'
base = 'amazoncorretto:8-alpine' if corretto == '8' else f'amazoncorretto:{corretto}-al2023-headless'
home = '/usr/lib/jvm/java-8-amazon-corretto' if corretto == '8' else f'/usr/lib/jvm/java-{corretto}-amazon-corretto'
context = root/'tests/fixtures/images/elasticsearch/dockerfiles'
command = ['docker','build','--build-arg','CORRETTO_VERSION='+corretto,'--build-arg','BASE_IMAGE='+base,
           '--build-arg','JAVA_HOME_PATH='+home,'--build-arg','ES_VERSION='+info['version'],
           '--build-arg','TARBALL_URL='+info['url'],'--build-arg','DOWNLOADER_IMAGE=amazonlinux:2023',
           '--build-arg','CONFIG_BUILDER_IMAGE=amazonlinux:2023','-f',str(context/'Dockerfile'),
           '-t','custom-elasticsearch:'+info['version'],str(context)]
started = time.monotonic()
code = subprocess.call(command,env=os.environ.copy())
print('FIXTURE_IMAGE_BUILD_RESULT ' + json.dumps({
    'task': sys.argv[1], 'image': 'custom-elasticsearch:' + info['version'],
    'elapsed_seconds': round(time.monotonic() - started, 3), 'exit_code': code,
}), flush=True)
sys.exit(code)
