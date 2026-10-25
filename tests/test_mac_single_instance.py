import json
from pathlib import Path
import plistlib
import sys
import socket
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'work'))
import mac_single_instance
from startup import StartupFailure
from jellyfin_mpv_shim import single_instance


class MacInstanceUpgrade(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.root=Path(self.directory.name)
        self.guard=str(self.root/'instance.lock')
        self.original=single_instance.SingleInstance
        self.config_patch=patch.object(single_instance.conffile,'get',return_value=self.guard)
        self.config_patch.start()
        app=self.root/'Jellyfin Player.app'
        (app/'Contents').mkdir(parents=True)
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString':'0.2.1'}))
        self.cls=mac_single_instance.install(app/'Contents/MacOS/Jellyfin Player')
        self.instances=[]

    def tearDown(self):
        for instance in reversed(self.instances): instance.release()
        single_instance.SingleInstance=self.original
        self.config_patch.stop()
        self.directory.cleanup()

    def instance(self,cls=None):
        instance=(cls or self.cls)()
        self.instances.append(instance)
        return instance

    def test_legacy_hidden_instance_remains_exclusive_and_names_upgrade_conflict(self):
        legacy=self.instance(self.original)
        hidden={'value':True}
        legacy.on_activate=lambda: hidden.update(value=False)
        self.assertTrue(legacy.acquire())
        old={'pid':123,'app':'/Applications/Jellyfin MPV Shim.app','version':'0.1.0'}
        newcomer=self.instance()
        with patch.object(mac_single_instance,'legacy_owner',return_value=old):
            with self.assertRaisesRegex(StartupFailure,r'Jellyfin MPV Shim.app.*version 0.1.0, PID 123'):
                newcomer.acquire()
        self.assertTrue(hidden['value'])
        self.assertTrue(legacy.holds_lock)
        self.assertFalse(newcomer.holds_lock)
        legacy.release()
        self.assertTrue(newcomer.acquire())

    def test_same_app_acknowledges_after_restoring_hidden_or_minimized_window(self):
        for state in ('hidden','minimized'):
            with self.subTest(state=state):
                primary=self.instance()
                window={'state':state}
                primary.on_activate=lambda: window.update(state='visible')
                self.assertTrue(primary.acquire())
                newcomer=self.instance()
                self.assertFalse(newcomer.acquire())
                self.assertEqual(window['state'],'visible')
                primary.release()

    def test_failed_activation_is_not_a_successful_handoff(self):
        primary=self.instance()
        def broken(): raise RuntimeError('no window')
        primary.on_activate=broken
        self.assertTrue(primary.acquire())
        with self.assertRaisesRegex(StartupFailure,'did not confirm'):
            self.instance().acquire()
        self.assertTrue(primary.holds_lock)

    def test_unready_primary_does_not_acknowledge_show(self):
        primary=self.instance()
        self.assertTrue(primary.acquire())
        with self.assertRaisesRegex(StartupFailure,'did not confirm'):
            self.instance().acquire()

    def test_guard_access_failure_is_closed(self):
        with patch.object(self.original,'_try_lock',return_value=None):
            with self.assertRaisesRegex(StartupFailure,'lock cannot be opened'):
                self.instance().acquire()

    def test_early_owner_can_reenter_upstream_start_without_releasing_profile(self):
        primary=self.instance()
        self.assertTrue(primary.acquire())
        endpoint=Path(self.guard).read_bytes()
        self.assertTrue(primary.acquire())
        self.assertTrue(primary.holds_lock)
        self.assertEqual(Path(self.guard).read_bytes(),endpoint)
        with self.assertRaises(StartupFailure): self.instance().acquire()

    def test_magic_header_without_ok_is_not_an_acknowledgement(self):
        from unittest.mock import MagicMock
        connection=MagicMock()
        connection.recv.side_effect=[b'JMS1',b'']
        instance=self.instance()
        with patch.object(instance,'_read_lock',return_value=(123,b'token')), patch.object(mac_single_instance.socket,'create_connection') as factory:
            factory.return_value.__enter__.return_value=connection
            self.assertFalse(instance._request(b'SHOW'))

    def test_ui_handler_return_without_a_new_native_ack_is_rejected(self):
        single_instance.SingleInstance=self.original
        cls=mac_single_instance.install(self.root/'Jellyfin Player.app/Contents/MacOS/Jellyfin Player',activation_check=lambda:'stale-ack')
        primary=self.instance(cls)
        primary.on_activate=lambda:None
        self.assertTrue(primary.acquire())
        with self.assertRaisesRegex(StartupFailure,'did not confirm'):
            self.instance(cls).acquire()

    def test_current_version_at_a_different_install_path_is_an_upgrade_conflict(self):
        primary=self.instance()
        self.assertTrue(primary.acquire())
        lines=Path(self.guard).read_text().splitlines()
        metadata=json.loads(lines[2]); metadata['app']='/Volumes/Installer/Jellyfin Player.app'
        Path(self.guard).write_text('\n'.join([*lines[:2],json.dumps(metadata)])+'\n')
        with self.assertRaisesRegex(StartupFailure,'/Volumes/Installer'):
            self.instance().acquire()

    def test_native_menu_protocol_authenticates_and_handles_fragmented_requests(self):
        calls = []
        single_instance.SingleInstance = self.original
        cls = mac_single_instance.install(self.root/'Jellyfin Player.app/Contents/MacOS/Jellyfin Player',
            menu_handler=lambda command: calls.append(command) or {'ok': True})
        primary = self.instance(cls)
        self.assertTrue(primary.acquire())
        port, token = primary._read_lock()
        for credential, expected in [(b'wrong', b''), (token, b'JMS1{"ok": true}\n')]:
            with socket.create_connection(('127.0.0.1', port), timeout=2) as connection:
                connection.sendall(b'JMS1' + credential + b' MENU {"comm')
                connection.sendall(b'and":"settings"}\n')
                self.assertEqual(connection.recv(256), expected)
        self.assertEqual(calls, ['settings'])
