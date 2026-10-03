#!/usr/bin/env python3
"""Bind a test's declared image dependencies to verified registry references."""
import json
from pathlib import Path
import sys

output, registry, *manifests = sys.argv[1:]
images = {}
for path in manifests:
    item = json.loads(Path(path).read_text())
    expected = item['image_id']
    # Receipts come from the uncached publication dependency. A cache eviction
    # may rebuild an image; publish that exact output before exposing its identity.
    reference = item['reference']
    if not reference.startswith(registry + '/fixtures/elasticsearch@sha256:'):
        raise ValueError('Unexpected fixture publication reference')
    images[item['image']] = {'image_id':expected, 'reference':reference}
Path(output).write_text(json.dumps({'images':images},sort_keys=True,indent=2)+'\n')
