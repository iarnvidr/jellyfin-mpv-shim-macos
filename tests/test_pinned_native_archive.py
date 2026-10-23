import hashlib
from pathlib import Path
import unittest


class PinnedNativeArchive(unittest.TestCase):
    def test_preserved_archive_matches_the_verified_upstream_input(self):
        root = Path(__file__).resolve().parents[1]
        lock = dict(line.split('=', 1) for line in
                    (root / 'work/native-dependencies.lock').read_text().splitlines()
                    if line and not line.startswith('#'))
        archive = root / lock['MPV_ARCHIVE']
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), lock['MPV_SHA256'])
