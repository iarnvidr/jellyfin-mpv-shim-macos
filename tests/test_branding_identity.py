"""Static branding regression contracts, runnable with stdlib unittest."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BrandingIdentity(unittest.TestCase):
    def test_main_and_player_bundles_have_jellyfin_player_identity(self):
        build = (ROOT / 'work/build.py').read_text()
        self.assertIn("NAME='Jellyfin Player'", build)
        self.assertIn("CFBundleName='Jellyfin Player'", build)
        self.assertIn("CFBundleDisplayName='Jellyfin Player'", build)
        self.assertIn("CFBundleExecutable='Jellyfin Player'", build)
        self.assertTrue("CFBundleIdentifier='org.jellyfin.mpvshim.local'" in build or
                        "'org.jellyfin.mpvshim.local'" in build)
        self.assertIn("CFBundleIdentifier='org.jellyfin.mpvshim.player'", build)
        self.assertIn("CFBundleIconFile='jellyfin.icns'", build)
        self.assertIn("shutil.copy2(WORK/'source/jellyfin.icns'", build)

    def test_branding_preserves_user_paths_and_settings(self):
        launch = (ROOT / 'work/launch.py').read_text()
        compat = (ROOT / 'work/local_compat.py').read_text()
        self.assertIn('Library/Logs/Jellyfin MPV Shim', launch)
        self.assertIn('Library/Caches/Jellyfin MPV Shim', compat)
        self.assertIn('Jellyfin Player ', compat)
        self.assertNotIn('rmtree', (ROOT / 'work/build.py').read_text())

    def test_sparkle_receives_actual_main_app_bundle(self):
        updater = (ROOT / 'work/Updater.swift').read_text()
        launcher = (ROOT / 'work/mac_update.py').read_text()
        self.assertIn('org.jellyfin.mpvshim.local', updater)
        self.assertIn('hostBundle: hostBundle, applicationBundle: hostBundle', updater)
        self.assertIn("parent.suffix == '.app'", launcher)
        self.assertIn("Contents/Helpers/Mac Updater.app", launcher)


if __name__ == "__main__":
    unittest.main()
