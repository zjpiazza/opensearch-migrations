"""Bound individual CAS objects without changing the logical artifact's checksum."""
import hashlib
from pathlib import Path

CHUNK_BYTES = 64 * 1024 * 1024


def read_parts(item, paths):
    for name in item.get('chunks', [item['file']]):
        with paths[name].open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                yield block


def verify(item, paths):
    hasher = hashlib.sha256()
    for block in read_parts(item, paths):
        hasher.update(block)
    if hasher.hexdigest() != item['sha256']:
        raise ValueError('Input checksum mismatch: ' + item['file'])


class ChunkWriter:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.hasher = hashlib.sha256()
        self.stream = None
        self.part = 0
        self.size = 0

    def write(self, data):
        self.hasher.update(data)
        total = len(data)
        while data:
            if self.stream is None:
                self.stream = (self.directory / f'part-{self.part:05d}').open('wb')
                self.size = 0
                self.part += 1
            count = min(len(data), CHUNK_BYTES - self.size)
            self.stream.write(data[:count])
            self.size += count
            data = data[count:]
            if self.size == CHUNK_BYTES:
                self.stream.close()
                self.stream = None
        return total

    def close(self):
        if self.stream:
            self.stream.close()
            self.stream = None
