"""Check the cache boundary: byte identity and offline recipe safety."""
import gzip
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import chunks
from offline import render

ROOT = Path(__file__).resolve().parents[4]


class FixtureInputTests(unittest.TestCase):
    def test_chunked_archive_round_trip_and_corruption(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(chunks, 'CHUNK_BYTES', 31):
            directory = Path(temp)
            data = bytes(range(256)) * 5
            writer = chunks.ChunkWriter(directory)
            with gzip.GzipFile(filename='', mode='wb', fileobj=writer, mtime=0) as stream:
                stream.write(data)
            writer.close()
            paths = {p.name: p for p in sorted(directory.iterdir())}
            self.assertGreater(len(paths), 1)
            self.assertTrue(all(p.stat().st_size <= 31 for p in paths.values()))
            item = dict(file='archive.tar.gz', chunks=list(paths), sha256=writer.hasher.hexdigest())
            chunks.verify(item, paths)
            self.assertEqual(gzip.decompress(b''.join(chunks.read_parts(item, paths))), data)
            next(iter(paths.values())).write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                chunks.verify(item, paths)

    def test_recipe_keeps_runtime_and_removes_network_acquisition(self):
        original = (ROOT/'tests/fixtures/images/elasticsearch/dockerfiles/Dockerfile').read_text()
        offline = render(original)
        for command in ['dnf install', 'apk add', 'curl -fSL', 'install --batch repository-gcs']:
            self.assertNotIn(command, offline)
        for setting in ['USER 1000', 'HEALTHCHECK --interval=10s', 'LD_PRELOAD',
                        'xpack.security.enabled: false', 'xpack.ml.enabled: false',
                        'file:///tmp/repository-gcs.zip', 'gcc -shared -fPIC']:
            self.assertIn(setting, offline)
        # A changed source acquisition block must fail, rather than silently
        # introducing a network dependency into a supposedly offline build.
        with self.assertRaisesRegex(ValueError, 'exactly one acquisition block'):
            render(original.replace('RUN dnf install', 'RUN yum install'))


if __name__ == '__main__':
    unittest.main()
