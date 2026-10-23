import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / 'scripts' / 'macos_smoke.py'


class MacOSSmokeTests(unittest.TestCase):
    def test_smoke_has_native_assertions_and_real_executables(self):
        source = SCRIPT.read_text()
        self.assertIn("'--dyld-smoke'", source)
        self.assertIn('Contents/Frameworks/Sparkle.framework/', source)
        self.assertIn('Contents/MacOS/Jellyfin Player', source)
        self.assertIn('Contents/Resources/mpv.app/Contents/MacOS/mpv', source)
        self.assertIn('lavfi://testsrc', source)
        self.assertIn('screencapture', source)
        self.assertIn('Accessibility permissions', source)
        self.assertIn("root/'work/dist/Jellyfin Player.app'", source)

    def test_non_macos_is_explicitly_unsupported(self):
        spec = importlib.util.spec_from_file_location('macos_smoke', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        original = module.sys.platform
        try:
            module.sys.platform = 'linux'
            with _CaptureStdout() as output:
                self.assertEqual(module.main(), 0)
            self.assertIn('UNSUPPORTED', output.value)
        finally:
            module.sys.platform = original


class _CaptureStdout:
    def __enter__(self):
        import contextlib
        import io
        self.buffer = io.StringIO()
        self.redirect = contextlib.redirect_stdout(self.buffer)
        self.redirect.__enter__()
        return self

    def __exit__(self, *args):
        self.redirect.__exit__(*args)
        self.value = self.buffer.getvalue()


if __name__ == '__main__':
    unittest.main()
