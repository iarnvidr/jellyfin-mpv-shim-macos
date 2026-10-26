"""Isolated real Jellyfin server and media for the macOS menu-bar diagnostic."""
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request


def wait_for(description, check, seconds=90):
    deadline = time.monotonic() + seconds
    last_error = None
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (OSError, ValueError, KeyError) as error:
            last_error = repr(error)
        time.sleep(1)
    raise RuntimeError(f'Timed out waiting for {description}; last error: {last_error}')


class PlaybackServer:
    def __init__(self, root, out):
        self.out = out
        self.url = 'http://127.0.0.1:8096'
        self.token = None
        self.user = 'menubar'
        self.password = 'temporary-ci-playback'
        binaries = list((root / 'server').rglob('jellyfin'))
        self.binary = next(p for p in binaries if p.is_file() and os.access(p, os.X_OK))
        ffmpeg = next(p for p in (root / 'server').rglob('ffmpeg') if p.is_file() and os.access(p, os.X_OK))
        media = out / 'media'
        media.mkdir()
        # Ten minutes allows all three activation-policy runs to use the same
        # actual file, without stopping halfway through the window transitions.
        subprocess.run([str(ffmpeg), '-hide_banner', '-loglevel', 'error',
                        '-f', 'lavfi', '-i', 'testsrc2=size=960x540:rate=24',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                        '-t', '600', '-c:v', 'libx264', '-preset', 'ultrafast',
                        '-crf', '30', '-c:a', 'aac', '-movflags', '+faststart',
                        str(media / 'Menu Bar Playback Proof.mp4')], check=True)
        self.log = (out / 'jellyfin-server.log').open('w')
        self.proc = subprocess.Popen([str(self.binary), '--datadir', str(out / 'server-data'),
                                      '--cachedir', str(out / 'server-cache'), '--nowebclient',
                                      '--ffmpeg', str(ffmpeg)], stdout=self.log, stderr=subprocess.STDOUT)
        wait_for('Jellyfin startup', lambda: self.api('GET', '/System/Info/Public'))
        wait_for('startup API ready', lambda: self.api('GET', '/Startup/Configuration'))
        self.api('POST', '/Startup/Configuration', {'UICulture': 'en-US', 'MetadataCountryCode': 'US',
                                                   'PreferredMetadataLanguage': 'en'})
        self.api('GET', '/Startup/User')
        self.api('POST', '/Startup/User', {'Name': self.user, 'Password': self.password})
        self.api('POST', '/Startup/Complete')
        auth = self.api('POST', '/Users/AuthenticateByName', {'Username': self.user, 'Pw': self.password})
        self.token = auth['AccessToken']
        self.user_id = auth['User']['Id']
        self.api('POST', '/Library/VirtualFolders?' + urllib.parse.urlencode({
            'name': 'Proof', 'collectionType': 'movies', 'paths': str(media), 'refreshLibrary': 'true'}))
        self.item = wait_for('indexed playable movie', lambda: next(iter(self.api('GET',
            '/Items?' + urllib.parse.urlencode({'userId': self.user_id, 'recursive': 'true',
                                               'includeItemTypes': 'Movie'}))['Items']), None))
        (out / 'server-item.json').write_text(json.dumps(self.item, indent=2))

    def api(self, method, path, body=None):
        headers = {'Authorization': 'MediaBrowser Client="Menu Bar Proof", Device="CI", DeviceId="menu-bar-proof", Version="1"'}
        if self.token:
            headers['X-Emby-Token'] = self.token
        data = None if body is None else json.dumps(body).encode()
        if data is not None:
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(self.url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            if error.code == 503:
                raise OSError(f'{method} {path}: server starting (503)') from error
            raise RuntimeError(f'{method} {path}: {error.code}: {error.read().decode()[:1000]}') from error

    def start_playback(self, native, ipc, case, excluded_sessions=()):
        session = wait_for('connected player session', lambda: next(iter(sorted((s for s in self.api('GET', '/Sessions')
            if s.get('SupportsRemoteControl') and s.get('IsActive') and s.get('Client') != 'Menu Bar Proof'
            and s['Id'] not in excluded_sessions),
            key=lambda s: s.get('LastActivityDate', ''), reverse=True)), None))
        self.api('POST', f'/Sessions/{session["Id"]}/Playing?' + urllib.parse.urlencode({
            'playCommand': 'PlayNow', 'itemIds': self.item['Id']}))
        playing = wait_for('server NowPlayingItem', lambda: next((s for s in self.api('GET', '/Sessions')
            if s.get('Id') == session['Id'] and s.get('NowPlayingItem', {}).get('Id') == self.item['Id']), None))
        wait_for('host Now Playing publication', lambda: self.host_active(native))
        # A server session alone does not establish decoded/advancing playback.
        first = wait_for('mpv playback position', lambda: self.position(ipc))
        time.sleep(3)
        second = self.position(ipc)
        if second <= first + 1:
            raise RuntimeError(f'mpv did not advance: {first} -> {second}')
        host = json.loads((native / 'now-playing-host.json').read_text())
        if host['title'] != playing['NowPlayingItem']['Name']:
            raise RuntimeError(f'Host title does not match server item: {host}')
        video = self.mpv(ipc, ['get_property', 'video-params'])
        if not video or video.get('w', 0) <= 0 or video.get('h', 0) <= 0:
            raise RuntimeError(f'No decoded video parameters: {video}')
        record = {'session': playing, 'host': host,
                  'mpvPositionBefore': first, 'mpvPositionAfter': second,
                  'mpvVideoParams': video}
        (self.out / f'{case}-playback-evidence.json').write_text(json.dumps(record, indent=2))
        print(f'{case}: server session + host Now Playing + mpv position {first} -> {second}', flush=True)

    def host_active(self, native):
        path = native / 'now-playing-host.json'
        return path.exists() and json.loads(path.read_text()).get('active')

    @staticmethod
    def mpv(ipc, command):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(5)
            connection.connect(str(ipc))
            connection.sendall((json.dumps({'command': command, 'request_id': 723}) + '\n').encode())
            stream = connection.makefile('rb')
            while line := stream.readline():
                result = json.loads(line)
                if result.get('request_id') == 723:
                    if result.get('error') != 'success':
                        raise ValueError(result)
                    return result.get('data')
        raise RuntimeError('mpv IPC disconnected')

    def position(self, ipc):
        return self.mpv(ipc, ['get_property', 'time-pos'])

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.log.close()
