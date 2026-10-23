import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'work'))
import startup


class StartupDiagnostics(unittest.TestCase):
    def test_killed_engine_is_bounded_and_retains_status(self):
        # Run the real backend + Mac integration in a separate interpreter so
        # its process patches cannot change the test runner's environment.
        with tempfile.TemporaryDirectory() as directory:
            engine=Path(directory)/'mpv'
            engine.write_text('#!/bin/sh\necho "Library not loaded: missing-library" >&2\nkill -KILL $$\n')
            engine.chmod(0o755)
            program='''
import json, pathlib, sys, time
sys.path.insert(0, sys.argv[1])
import jellyfin_mpv_shim, local_compat, startup, python_mpv_jsonipc
local_compat.apply(pathlib.Path(sys.argv[2]), pathlib.Path(jellyfin_mpv_shim.__file__).parent)
try:
    python_mpv_jsonipc.MPV(mpv_location=sys.argv[2]+'/mpv', ipc_socket=sys.argv[2]+'/ipc')
except python_mpv_jsonipc.MPVProcessError:
    time.sleep(.1)
    print(json.dumps({'attempts':startup.ENGINE_ATTEMPTS,'exit':startup.ENGINE_PROCESS.poll(),'output':list(startup.ENGINE_OUTPUT)}))
'''
            result=subprocess.run([sys.executable,'-c',program,str(ROOT/'work'),directory],capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr[-1000:])
            data=json.loads(result.stdout.splitlines()[-1])
            self.assertEqual(data['attempts'],1)
            self.assertEqual(data['exit'],-9)
            self.assertTrue(any('missing-library' in row for row in data['output']))

    def make_report(self, directory, status, failure, signatures, output=None):
        app=Path(directory)/'Jellyfin Player.app'
        (app/'Contents').mkdir(parents=True)
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString':'0.2.1'}))
        engine=app/'Contents/Resources/mpv.app/Contents/MacOS/mpv'
        engine.parent.mkdir(parents=True); engine.touch()
        if output is None: output=['server connected https://private.example?token=secret','Library not loaded: example.dylib']
        with patch.object(startup,'signature_results',return_value=signatures), patch.object(startup,'ENGINE_PROCESS',Mock(poll=lambda:status)), patch.object(startup,'ENGINE_ATTEMPTS',2), patch.object(startup,'ENGINE_FAILURE',failure), patch.object(startup,'ENGINE_OUTPUT',output):
            report,message=startup.write_report(RuntimeError('token=secret'),app,engine,Path(directory)/'logs')
        return json.loads(report.read_text()),message

    def test_invalid_signatures_are_reported_and_private_context_is_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            report,message=self.make_report(directory,-9,'MPV not started.',[{'valid':False}])
            self.assertIn('signature is invalid',message)
            self.assertEqual(report['attempts'],2)
            self.assertNotIn('secret',json.dumps(report))
            self.assertNotIn('private.example',json.dumps(report))

    def test_ipc_timeout_is_distinguished_from_cleanup_termination(self):
        with tempfile.TemporaryDirectory() as directory:
            # SIGTERM here was issued by the backend's timeout cleanup.
            report,message=self.make_report(directory,-15,'MPV start timed out.',[{'valid':True}],output=[])
            self.assertIn('IPC connection',message)

    def test_sigkill_alone_is_not_claimed_to_be_signature_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(startup,'signature_results',return_value=[{'valid':True}]), patch.object(startup,'ENGINE_PROCESS',Mock(poll=lambda:-9)), patch.object(startup,'ENGINE_ATTEMPTS',1), patch.object(startup,'ENGINE_FAILURE','MPV not started.'), patch.object(startup,'ENGINE_OUTPUT',[]):
                app=Path(directory)/'app.app'; (app/'Contents').mkdir(parents=True)
                (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString':'0.2.1'}))
                engine=app/'mpv'; engine.touch()
                _,message=startup.write_report(RuntimeError(),app,engine,Path(directory)/'logs')
            self.assertIn('signal: 9',message)
            self.assertNotIn('signature',message)
