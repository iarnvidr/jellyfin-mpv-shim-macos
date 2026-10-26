#!/usr/bin/env python3
"""Compare the exact release with instrumented accessory/regular runs on macOS."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time
from menu_bar_playback import PlaybackServer

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/menu-bar-proof'
OUT.mkdir(parents=True, exist_ok=True)
PROBE = OUT / 'probe'


def run(*args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def snapshot(name, pid=None, require_frontmost=True):
    result = run(PROBE, *([pid] if pid else []), capture_output=True, text=True)
    record = json.loads(result.stdout)
    (OUT / f'{name}.json').write_text(json.dumps(record, indent=2) + '\n')
    shot = subprocess.run(['/usr/sbin/screencapture', '-x', str(OUT / f'{name}.png')], capture_output=True, text=True)
    if shot.returncode:
        raise RuntimeError(f'Screenshot unavailable: {shot.stderr}')
    print(name, json.dumps(record['frontmost']), flush=True)
    if pid and require_frontmost and record['frontmost'].get('pid') != pid:
        raise RuntimeError(f'{name}: activation did not make requested PID {pid} frontmost')
    return record


def request(config, command):
    lines = (config / 'instance.lock').read_text().splitlines()
    with socket.create_connection(('127.0.0.1', int(lines[0])), timeout=5) as connection:
        connection.sendall(('JMS1' + lines[1] + ' MENU ' + json.dumps({'command': command}) + '\n').encode())
        response = connection.makefile('rb').readline()
    if not response.startswith(b'JMS1'):
        raise RuntimeError(repr(response))
    return json.loads(response[4:])


run('xcrun', 'clang', '-fobjc-arc', '-DPROBE_STANDALONE', ROOT / 'tests/native/ProbeMenuBar.m',
    '-o', PROBE, '-framework', 'Cocoa', '-framework', 'ApplicationServices')
snapshot('desktop-before')

# Compile the exact release source with observation added. The only behavioral
# difference between the two instrumented cases is the activation policy value.
source = (ROOT / 'work/NativeScroll.m').read_text()
needle = '[NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];'
assert source.count(needle) == 1
source = source.replace(needle, '''[NSApp setActivationPolicy:
        [NSProcessInfo.processInfo.environment[@"JELLYFIN_MENU_PROBE_REGULAR"] isEqualToString:@"1"]
        ? NSApplicationActivationPolicyRegular : NSApplicationActivationPolicyAccessory];''')
source += '\n#import "' + str(ROOT / 'tests/native/ProbeMenuBar.m') + '"\n'
instrumented = OUT / 'NativeScroll-instrumented.m'
instrumented.write_text(source)
run('xcrun', 'clang', '-c', '-fPIC', '-fobjc-arc', '-fblocks', instrumented, '-o', OUT / 'NativeScroll.o')
run('xcrun', 'swiftc', ROOT / 'work/NativeMenus.swift', ROOT / 'work/NativeSettings.swift',
    ROOT / 'work/NativeMedia.swift', OUT / 'NativeScroll.o', '-emit-library',
    '-o', OUT / 'native-scroll.dylib', '-framework', 'Cocoa', '-framework', 'MediaPlayer')

original = ROOT / 'release/Jellyfin Player.app'
server = PlaybackServer(ROOT, OUT)
summary = []
for case in ['original-release', 'instrumented-accessory', 'instrumented-regular']:
    app = OUT / case / 'Jellyfin Player.app'
    app.parent.mkdir()
    shutil.copytree(original, app, symlinks=True)
    if case != 'original-release':
        # Core launches mpv with its own embedded library, not the outer
        # host's duplicate. Replace each copy and verify the probe ran below.
        libraries = list(app.rglob('native-scroll.dylib'))
        assert libraries
        for library in libraries:
            shutil.copy2(OUT / 'native-scroll.dylib', library)
        run('codesign', '--force', '--deep', '--sign', '-', app)
    config = OUT / case / 'profile'
    config.mkdir()
    ipc = Path('/tmp') / f'menu-proof-{os.getpid()}.sock'
    (config / 'conf.json').write_text(json.dumps({
        'mpv_ext': True, 'mpv_ext_path': None, 'fullscreen': False,
        'browser_fullscreen': False, 'hide_title_bar': False,
        'mpv_ext_ipc': str(ipc), 'client_uuid': case,
    }))
    native = OUT / case / 'native-menus'
    native.mkdir()
    env = dict(os.environ, JELLYFIN_PLAYER_MENU_DIAGNOSTICS=str(native),
               JELLYFIN_MENU_PROBE_OUTPUT=str(OUT / f'{case}-in-process.jsonl'))
    if case == 'instrumented-regular':
        env['JELLYFIN_MENU_PROBE_REGULAR'] = '1'
    prior_sessions = {s['Id'] for s in server.api('GET', '/Sessions')}
    with (OUT / f'{case}-launcher.log').open('w') as log:
        proc = subprocess.Popen([str(app / 'Contents/MacOS/Jellyfin Player'), '--config', str(config),
                                 '--server', server.url, '--username', server.user, '--password', server.password],
                                env=env, stdout=log, stderr=subprocess.STDOUT)
        engine = None
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError(f'{case}: host exited {proc.returncode}')
                state = json.loads(run(PROBE, capture_output=True, text=True).stdout)
                engines = [a for a in state['jellyfinProcesses'] if a['bundle'] == 'org.jellyfin.mpvshim.player']
                if engines and len(list(native.glob('[0-9]*.json'))) >= 2:
                    engine = engines[0]['pid']
                    break
                time.sleep(1)
            if engine is None:
                raise RuntimeError(f'{case}: engine and native menus did not start')
            time.sleep(3)
            run(PROBE, '--dismiss-local-network')
            # The host intentionally forwards activation to the engine after
            # 200 ms. Record that handoff instead of treating it as a failure.
            host_state = snapshot(case + '-host-active', proc.pid, require_frontmost=False)
            engine_state = snapshot(case + '-engine-active', engine)
            server.start_playback(native, ipc, case, prior_sessions)
            snapshot(case + '-playing-windowed', engine)
            if case != 'original-release':
                records = [json.loads(line) for line in (OUT / f'{case}-in-process.jsonl').read_text().splitlines()]
                assert records, 'Instrumented library did not produce runtime records'
                expected_policy = 0 if case == 'instrumented-regular' else 1
                assert engine_state['frontmost']['policy'] == expected_policy, 'Activation policy intervention did not take effect'
            initial = request(config, 'state')
            (OUT / f'{case}-core-state.json').write_text(json.dumps(initial, indent=2) + '\n')
            # Reproduce the transition as well as a cold windowed launch.
            for phase in ['enter-fullscreen', 'leave-fullscreen']:
                result = request(config, 'fullscreen')
                if result.get('ok') is not True:
                    raise RuntimeError(f'{case}: fullscreen action rejected: {result}')
                time.sleep(4)
                snapshot(case + '-' + phase, engine)
            # Switching focus tests both host/engine handoff paths while media
            # continues playing. Finder activation is recorded as its own case.
            finder = json.loads(run('osascript', '-e', 'tell application "System Events" to get unix id of process "Finder"',
                                    capture_output=True, text=True).stdout)
            snapshot(case + '-finder-active', finder)
            snapshot(case + '-playing-after-app-switch', engine)
            for phase in ['zoom', 'restore']:
                result = request(config, 'zoom')
                if result.get('ok') is not True:
                    raise RuntimeError(f'{case}: zoom action rejected: {result}')
                time.sleep(2)
                snapshot(case + '-playing-' + phase, engine)
            result = request(config, 'minimize')
            if result.get('ok') is not True:
                raise RuntimeError(f'{case}: minimize action rejected: {result}')
            time.sleep(2)
            snapshot(case + '-playing-minimized')
            # Activating the outer app exercises the actual reopen handshake.
            snapshot(case + '-playing-reopen', proc.pid, require_frontmost=False)
            snapshot(case + '-playing-reopened-engine', engine)
            request(config, 'fullscreen')
            time.sleep(3)
            snapshot(case + '-playing-fullscreen-before-stop', engine)
            model = request(config, 'state')
            stop = model['now_playing']['commands']['stop']
            assert request(config, stop).get('ok') is True
            time.sleep(4)
            snapshot(case + '-browser-after-fullscreen-stop', engine)
            # Recreate playback, then close its fullscreen window and reopen
            # through the real host activation path rather than setting flags.
            server.start_playback(native, ipc, case + '-second', prior_sessions)
            if not server.mpv(ipc, ['get_property', 'fullscreen']):
                request(config, 'fullscreen')
                time.sleep(3)
            assert request(config, 'close').get('ok') is True
            time.sleep(3)
            snapshot(case + '-closed-from-fullscreen')
            snapshot(case + '-host-reopen-after-fullscreen-close', proc.pid, require_frontmost=False)
            snapshot(case + '-engine-after-fullscreen-close', engine)
            summary.append({'case': case, 'hostPID': proc.pid, 'enginePID': engine,
                            'hostFrontmost': host_state['frontmost'], 'engineFrontmost': engine_state['frontmost']})
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait()
            if engine:
                try: os.kill(engine, signal.SIGTERM)
                except ProcessLookupError: pass
            # Uploaded evidence contains logs and captures, not three app copies.
            shutil.rmtree(app)
            time.sleep(2)
snapshot('desktop-after')
server.close()
(OUT / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print('All three cases captured; compare screenshots with in-process records.', flush=True)
