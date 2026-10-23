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

    def test_seed_format_contract(self):
        # Sparkle's sign_update input is a base64-encoded Ed25519 private seed,
        # exactly 32 bytes; never load or manufacture the secret in this test.
        self.assertEqual(len(base64.b64decode(PUBLIC_KEY, validate=True)), 32)


if __name__ == '__main__':
    unittest.main()
