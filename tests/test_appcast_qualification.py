import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import publish_appcast
import release
import sparkle_smoke


class AppcastQualification(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.feed = b'<rss version="2.0"><channel><title>Player</title></channel></rss>'
        self.commit = 'a' * 40
        self.version = '0.2.3'
        metadata = {'version': self.version, 'signature': 'verified-by-native-test',
                    'length': 123, 'minimum_os': '15.7.9', 'feed_url': release.FEED_URL,
                    'asset_url': release.ASSET_ROOT + 'v0.2.3/Jellyfin-Player-0.2.3-Apple-Silicon.zip',
                    'release_notes': 'Release notes'}
        self.candidate = release.update_feed(self.feed, metadata, 'v0.2.3')
        self.record = {'passed': True, 'to': self.version, 'mode': 'current-host',
                       'after_signatures': {'valid': True}, 'manual_reopen': False,
                       'new_pid': 456, 'after_window': {'windows': 1},
                       'base_feed_commit': self.commit,
                       'base_feed_sha256': hashlib.sha256(self.feed).hexdigest(),
                       'appcast_sha256': hashlib.sha256(self.candidate).hexdigest(),
                       'metadata': metadata}
        self.write(self.record)
        legacy = dict(self.record, mode='legacy', manual_reopen=True)
        (self.directory / 'legacy').mkdir()
        (self.directory / 'legacy/result.json').write_text(json.dumps(legacy))

    def write(self, record):
        path = self.directory / 'current-host'
        path.mkdir(exist_ok=True)
        (path / 'result.json').write_text(json.dumps(record))
        (path / 'candidate-appcast.xml').write_bytes(self.candidate)

    def validate(self, feed=None, commit=None):
        return publish_appcast.qualified_appcast(self.directory, self.feed if feed is None else feed,
                                                self.commit if commit is None else commit, self.version)

    def test_only_the_exact_tested_appcast_is_staged(self):
        candidate, _ = self.validate()
        self.assertEqual(candidate, self.candidate)

    def test_historical_installation_uses_an_isolated_fixture_feed(self):
        metadata = dict(self.record['metadata'], version='0.2.2',
                        asset_url=release.ASSET_ROOT + 'v0.2.2/Jellyfin-Player-0.2.2-Apple-Silicon.zip')
        with self.assertRaisesRegex(ValueError, 'strictly newer'):
            sparkle_smoke.installation_appcast(self.candidate, metadata)
        candidate = sparkle_smoke.installation_appcast(self.candidate, metadata, fixture_feed=True)
        self.assertIn(b'<title>0.2.2</title>', candidate)
        self.assertNotIn(b'<title>0.2.3</title>', candidate)

    def test_fixture_evidence_cannot_publish_even_when_other_checks_pass(self):
        self.write(dict(self.record, fixture_feed=True))
        with self.assertRaisesRegex(ValueError, 'fixture'):
            self.validate()

    def test_incomplete_installation_relaunch_and_signatures_are_rejected(self):
        for changes in ({'passed': False}, {'manual_reopen': True}, {'new_pid': None},
                        {'after_window': {'windows': 0}}, {'after_signatures': {'valid': False}}):
            with self.subTest(changes=changes):
                self.write(dict(self.record, **changes))
                with self.assertRaises(ValueError):
                    self.validate()

    def test_concurrent_feed_change_cannot_be_overwritten(self):
        with self.assertRaises(ValueError):
            self.validate(commit='b' * 40)
        with self.assertRaises(ValueError):
            self.validate(feed=self.feed + b'\n')

    def test_another_archive_or_modified_appcast_cannot_be_published(self):
        record = copy.deepcopy(self.record)
        record['metadata']['asset_url'] = 'https://unrelated.invalid/app.zip'
        self.write(record)
        with self.assertRaises(ValueError):
            self.validate()
        self.write(self.record)
        (self.directory / 'current-host/candidate-appcast.xml').write_bytes(self.candidate + b'\n')
        with self.assertRaises(ValueError):
            self.validate()
