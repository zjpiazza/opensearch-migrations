"""A stale or undeclared image must not produce a false cached-test success."""
import unittest
from unittest.mock import patch
from load import load


class LoaderTests(unittest.TestCase):
    image = 'custom-elasticsearch:7.10.2'
    expected = 'sha256:' + 'a' * 64
    reference = 'registry:5000/fixtures/elasticsearch:' + 'a' * 64

    @property
    def catalog(self):
        return {'images': {self.image: {'image_id': self.expected, 'reference': self.reference}}}

    def test_undeclared_image_fails_without_building_or_pulling(self):
        with patch('load.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, 'Undeclared'):
                load({'images': {}}, self.image)
            run.assert_not_called()

    def test_correct_local_image_is_reused(self):
        with patch('load.image_id', return_value=self.expected), patch('load.subprocess.run') as run:
            load(self.catalog, self.image)
            run.assert_not_called()

    def test_stale_local_tag_is_replaced_from_verified_image(self):
        with patch('load.image_id', side_effect=['old', self.expected, self.expected, self.expected]), patch('load.subprocess.run') as run:
            load(self.catalog, self.image)
            run.assert_called_once_with(['docker', 'tag', self.reference, self.image], check=True)

    def test_wrong_published_image_fails_before_retag(self):
        with patch('load.image_id', side_effect=[None, None, 'wrong']), patch('load.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, 'does not match'):
                load(self.catalog, self.image)
            run.assert_called_once_with(['docker', 'pull', '--platform=linux/amd64', self.reference], check=True)


if __name__ == '__main__':
    unittest.main()
