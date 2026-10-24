from pathlib import Path
import plistlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'work'))
from mac_update import main_bundle


class MainBundle(unittest.TestCase):
    def test_nested_core_finds_the_containing_player_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / 'Jellyfin Player.app'
            core = app / 'Contents/Helpers/Jellyfin Player Core.app'
            executable = core / 'Contents/MacOS/Jellyfin Player Core'
            executable.parent.mkdir(parents=True)
            executable.touch()
            for bundle, identity in [(app, 'org.jellyfin.mpvshim.local'),
                                     (core, 'org.jellyfin.mpvshim.core')]:
                (bundle / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': identity}))
            self.assertEqual(main_bundle(executable), app)

    def test_unrelated_application_is_not_an_update_target(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'Other.app/Contents/MacOS/Other'
            executable.parent.mkdir(parents=True)
            executable.touch()
            self.assertIsNone(main_bundle(executable))
