import base64
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work'
PUBLIC_KEY = 'zCAIKbF8Cdw3YMyWxxPjwCrZStPTh9FADpsqb/ODJLk='


class SparklePublicKeyTests(unittest.TestCase):
    def test_tracked_key_is_valid_and_pinned_in_build(self):
        key = (WORK / 'sparkle-public-key.txt').read_text().strip()
        self.assertEqual(key, PUBLIC_KEY)
        self.assertEqual(len(base64.b64decode(key, validate=True)), 32)
        build = (WORK / 'build.py').read_text()
        self.assertIn("SUPublicEDKey=public_key", build)
        self.assertIn("env_public_key != public_key", build)
        self.assertIn("'SPARKLE_PUBLIC_ED_KEY'", build)

    def test_compiler_command_uses_helper_bundle_frameworks_rpath(self):
        import ast
        tree = ast.parse((WORK / 'build.py').read_text())
        commands = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == 'command']
        helper = next(node for node in commands if any(
            isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == 'str'
            and any(isinstance(part, ast.BinOp) and isinstance(part.op, ast.Div)
                    and isinstance(part.right, ast.Constant) and part.right.value == 'Updater.swift'
                    for part in ast.walk(arg))
            for arg in node.args))
        args = [arg.value for arg in ast.walk(helper) if isinstance(arg, ast.Constant) and isinstance(arg.value, str)]
        self.assertIn('@executable_path/../../../../Frameworks', args)
        self.assertNotIn('@executable_path/../../../Frameworks', args)

    def test_swift_dyld_smoke_precedes_gui_and_is_exact(self):
        source = (WORK / 'Updater.swift').read_text()
        smoke = source.index('arguments == ["--dyld-smoke"]')
        gui = source.index('NSApplication.shared')
        self.assertLess(smoke, gui)
        self.assertIn('_ = SPUUpdater.self', source)
        self.assertIn('JELLYFIN_PLAYER_SPARKLE_DYLD_OK', source)
        self.assertIn('exit(2)', source)
        self.assertIn('hostBundle.bundleIdentifier == "org.jellyfin.mpvshim.local"', source)

    def test_build_smoke_is_bounded_and_checks_marker_and_exit(self):
        build = (WORK / 'build.py').read_text()
        self.assertIn("capture_output=True,timeout=30", build)
        self.assertIn("result.returncode != 0", build)
        self.assertIn("JELLYFIN_PLAYER_SPARKLE_DYLD_OK", build)
        self.assertIn("os.kill(exc.pid", build)

    def test_seed_format_contract(self):
        # Sparkle's sign_update input is a base64-encoded Ed25519 private seed,
        # exactly 32 bytes; never load or manufacture the secret in this test.
        self.assertEqual(len(base64.b64decode(PUBLIC_KEY, validate=True)), 32)


if __name__ == '__main__':
    unittest.main()
