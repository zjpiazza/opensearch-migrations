#!/usr/bin/env python3
"""Materialize a pinned fixture image; never build images from inside a test."""
import json
from pathlib import Path
import subprocess
import sys
import time


def image_id(reference):
    result = subprocess.run(['docker', 'image', 'inspect', '--format={{.Id}}', reference],
                            text=True, capture_output=True)
    return result.stdout.strip() if result.returncode == 0 else None


def load(catalog, image):
    started = time.monotonic()
    entry = catalog['images'].get(image)
    if entry is None:
        raise ValueError('Undeclared fixture image: ' + image)
    expected = entry['image_id']
    reference = entry['reference']
    if not expected.startswith('sha256:') or len(expected) != 71:
        raise ValueError('Invalid pinned image ID for ' + image)
    reused = image_id(image) == expected
    if not reused:
        if image_id(reference) != expected:
            subprocess.run(['docker', 'pull', '--platform=linux/amd64', reference], check=True)
        if image_id(reference) != expected:
            raise ValueError('Published fixture image does not match declared image ID: ' + reference)
        subprocess.run(['docker', 'tag', reference, image], check=True)
    if image_id(image) != expected:
        raise ValueError('Local fixture image ID mismatch: ' + image)
    print('FIXTURE_IMAGE_READY_RESULT ' + json.dumps(dict(image=image, image_id=expected,
        reused_local_image=reused, elapsed_seconds=round(time.monotonic()-started,3))), flush=True)


if __name__ == '__main__':
    load(json.loads(Path(sys.argv[1]).read_text()), sys.argv[2])
