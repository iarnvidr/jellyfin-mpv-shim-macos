"""Static release contracts that can run on non-macOS CI."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"


class BundledRuntimeContract(unittest.TestCase):
    def test_launcher_uses_only_bundled_client_and_player(self):
        source = (WORK / "launch.py").read_text()
        tree = ast.parse(source)
        imports = {alias.name for node in ast.walk(tree)
                   if isinstance(node, ast.Import) for alias in node.names}
        self.assertNotIn("runtime_update", imports)
        self.assertNotIn("managed_launch", imports)
        self.assertNotIn("sys.path.insert", source)
        self.assertIn("import jellyfin_mpv_shim", source)
        self.assertIn("Resources/mpv.app/Contents/MacOS/mpv", source)
        self.assertIn("enable_gui", source)

    def test_legacy_runtime_updater_is_not_a_launch_dependency(self):
        source = (WORK / "mac_update.py").read_text()
        self.assertNotIn("import runtime_update", source)
        self.assertIn("Component updates are retired", source)
        self.assertIn("def check()", source)
        self.assertIn("Sparkle", source)
        self.assertNotIn("pypi.org", source)
        self.assertNotIn("zipfile", source)
        self.assertIn("SPUUpdater", (WORK / "Updater.swift").read_text())


class MacIntegrationContract(unittest.TestCase):
    def test_native_scrolling_and_settings_update_entry_remain(self):
        compat = (WORK / "local_compat.py").read_text()
        native = (WORK / "NativeScroll.m").read_text()
        self.assertIn("player_environment", compat)
        self.assertIn("DYLD_INSERT_LIBRARIES", (WORK / 'player_runtime.py').read_text())
        self.assertIn("mpvtk-native-scroll", compat)
        self.assertIn("scrollingDeltaY", native)
        self.assertIn("Check for Updates", compat)
        self.assertIn("_settings_form", compat)
        self.assertIn("_check_updates", compat)

    def test_sparkle_is_hosted_for_main_application(self):
        source = (WORK / "Updater.swift").read_text()
        self.assertIn("applicationBundle: hostBundle", source)
        self.assertIn("hostBundle: hostBundle", source)
        self.assertIn("SPUStandardUserDriver", source)
        self.assertIn("checkForUpdates()", source)
        build = (WORK / "build.py").read_text()
        self.assertIn("-framework','Sparkle", build)
        self.assertIn("SUFeedURL", build)
        self.assertIn("SUPublicEDKey", build)


if __name__ == "__main__":
    unittest.main()
