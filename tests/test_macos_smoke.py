import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).parents[1] / 'scripts' / 'macos_smoke.py'


class MacOSSmokeTests(unittest.TestCase):
    def test_ipc_matches_property_response_among_events_and_other_requests(self):
        spec = importlib.util.spec_from_file_location('macos_smoke', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        connection = MagicMock()
        connection.makefile.return_value = io.BytesIO(
            b'{"event":"start-file"}\n'
            b'{"request_id":2,"error":"success","data":"unrelated"}\n'
            b'{"request_id":1,"error":"success","data":{"w":160,"h":90}}\n')
        with patch.object(module.socket, 'socket') as factory:
            factory.return_value.__enter__.return_value = connection
            self.assertEqual(module.ipc_property('/tmp/test.sock', 'video-params'), {'w':160,'h':90})
        request = json.loads(connection.sendall.call_args.args[0])
        self.assertEqual(request['command'], ['get_property', 'video-params'])

    def test_unavailable_property_cannot_count_as_playback(self):
        spec = importlib.util.spec_from_file_location('macos_smoke', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        connection = MagicMock()
        connection.makefile.return_value = io.BytesIO(
            b'{"request_id":1,"error":"property unavailable"}\n')
        with patch.object(module.socket, 'socket') as factory:
            factory.return_value.__enter__.return_value = connection
            self.assertIsNone(module.ipc_property('/tmp/test.sock', 'time-pos'))

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
