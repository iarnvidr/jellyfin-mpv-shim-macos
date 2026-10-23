from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'work'))
import bundle_signing


class ExplicitSigning(unittest.TestCase):
    def fixture(self, root):
        app=Path(root)/'Jellyfin Player.app'
        nested=app/'Contents/Resources/mpv.app'
        library=nested/'Contents/Frameworks/libMoltenVK.dylib'
        library.parent.mkdir(parents=True)
        library.write_bytes(bytes.fromhex('cffaedfe')+b'mach-o')
        (nested/'Contents/Info.plist').write_bytes(b'plist')
        (library.parent/'alias.dylib').symlink_to(library.name)
        return app,nested,library

    def test_signs_resource_app_and_its_library_before_outer_app(self):
        with tempfile.TemporaryDirectory() as directory:
            app,nested,library=self.fixture(directory)
            with patch.object(bundle_signing.subprocess,'run',return_value=Mock(returncode=0,stdout='',stderr='')) as run:
                bundle_signing.sign_bundle(app)
            calls=[call.args[0] for call in run.call_args_list]
            signing=[c for c in calls if '--sign' in c]
            self.assertEqual([c[-1] for c in signing],[str(library),str(nested),str(app)])
            self.assertTrue(all('--deep' not in c for c in calls))
            self.assertEqual(len([c for c in calls if '--verify' in c]),3)

    def test_nested_failure_blocks_even_if_outer_signature_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            app,nested,library=self.fixture(directory)
            def verify(command,**kwargs):
                bad=command[-1]==str(library)
                return Mock(returncode=int(bad),stdout='',stderr='invalid signature' if bad else '')
            with patch.object(bundle_signing.subprocess,'run',side_effect=verify):
                with self.assertRaisesRegex(ValueError,'libMoltenVK'):
                    bundle_signing.verify_bundle(app)
