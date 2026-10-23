"""Preserve the shared profile lock, but make upgrade conflicts visible."""
import json
import logging
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import tempfile

from startup import StartupFailure

log = logging.getLogger('single_instance')


def app_identity(executable):
    executable = Path(executable)
    app = next((p for p in executable.parents if p.suffix == '.app'), None)
    version = 'unknown'
    if app:
        try:
            with (app/'Contents/Info.plist').open('rb') as source:
                version = plistlib.load(source).get('CFBundleShortVersionString', 'unknown')
        except (OSError, ValueError):
            pass
    return {'pid': os.getpid(), 'app': str(app or executable), 'version': version}


def legacy_owner(endpoint):
    if not endpoint:
        return {'pid': 'unknown', 'app': 'unknown application', 'version': 'unknown'}
    try:
        port, _ = endpoint
        found = subprocess.run(['/usr/sbin/lsof', '-nP', '-t', f'-iTCP:{port}', '-sTCP:LISTEN'],
                               capture_output=True, text=True, timeout=3)
        pids = list(dict.fromkeys(found.stdout.split()))
        if len(pids) != 1 or not pids[0].isdigit(): raise ValueError('ambiguous listener')
        pid = int(pids[0])
        process = subprocess.run(['/bin/ps', '-ww', '-p', str(pid), '-o', 'comm='],
                                 capture_output=True, text=True, timeout=3)
        owner = app_identity(process.stdout.strip())
        owner['pid'] = pid
        return owner
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {'pid': 'unknown', 'app': 'unknown application', 'version': 'unknown'}


def install(executable, activation_check=None):
    from jellyfin_mpv_shim import single_instance
    original = single_instance.SingleInstance
    identity = app_identity(executable)

    class MacSingleInstance(original):
        def __init__(self):
            super().__init__()
            self._initial_activation = self.on_activate

        def _try_lock(self):
            result = super()._try_lock()
            if result is None:
                raise StartupFailure('The shared settings lock cannot be opened. Check access to your Jellyfin MPV Shim settings folder before trying again.')
            return result

        def _write_endpoint(self, port):
            # Keep the legacy first two lines. New metadata says that SHOW is
            # acknowledged only after the activation handler has returned.
            metadata = dict(identity, activation_ack=2)
            with tempfile.NamedTemporaryFile(mode='w', dir=Path(self._lockpath).parent, delete=False) as stream:
                stream.write(f'{port}\n{self._token.decode("ascii")}\n{json.dumps(metadata)}\n')
                staging = stream.name
            os.replace(staging, self._lockpath)

        def _handoff_to_existing(self):
            try:
                lines = Path(self._lockpath).read_text().splitlines()
                owner = json.loads(lines[2]) if len(lines) > 2 else legacy_owner(self._read_lock())
            except (OSError, ValueError, IndexError):
                owner = legacy_owner(self._read_lock())
            log.warning('Instance owner: app=%s version=%s PID=%s', owner.get('app'), owner.get('version'), owner.get('pid'))
            details = f"{owner.get('app', 'unknown application')} (version {owner.get('version', 'unknown')}, PID {owner.get('pid', 'unknown')})"
            if owner.get('app') != identity['app'] or owner.get('version') != identity['version']:
                raise StartupFailure(f'Another Jellyfin app is using your settings:\n{details}\n\nQuit that app, then open Jellyfin Player again. Both versions cannot safely use the same settings at once.')
            if owner.get('activation_ack') == 2 and self._request(b'SHOW'):
                log.info('Running Jellyfin Player acknowledged window activation: %s', details)
                return True
            raise StartupFailure(f'The running app did not confirm that it showed its window:\n{details}\n\nQuit that instance and reopen Jellyfin Player. If it is unresponsive, use Activity Monitor to quit the identified process.')

        def _request(self, command):
            if command != b'SHOW': return super()._request(command)
            endpoint = self._read_lock()
            if not endpoint: return False
            port, token = endpoint
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=2) as connection:
                    connection.sendall(single_instance._MAGIC+token+b'\n')
                    reply = b''
                    while len(reply) < 6:
                        chunk = connection.recv(6-len(reply))
                        if not chunk: break
                        reply += chunk
                return reply == single_instance._MAGIC+b'OK'
            except OSError:
                return False

        def _serve_one(self, conn):
            try:
                conn.settimeout(3)
                data = conn.recv(64)
                if not data.startswith(single_instance._MAGIC): return
                parts = data[len(single_instance._MAGIC):].strip().split()
                if not parts or parts[0] != self._token: return
                command = parts[1] if len(parts) > 1 else b'SHOW'
                if command == b'STOP':
                    conn.sendall(single_instance._MAGIC+b'OK')
                    self.on_stop()
                elif command == b'SHOW' and self.on_activate is not self._initial_activation:
                    previous = activation_check() if activation_check else None
                    self.on_activate()
                    if activation_check and activation_check() == previous:
                        return
                    conn.sendall(single_instance._MAGIC+b'OK')
            except Exception as error:
                log.warning('Instance activation failed: %s', type(error).__name__)
            finally:
                conn.close()

    single_instance.SingleInstance = MacSingleInstance
    return MacSingleInstance
