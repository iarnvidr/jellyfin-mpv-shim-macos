#!/usr/bin/env python3
"""Exercise published playback, launch paths, window state and menu ownership."""
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
from menu_bar_launch import launch
from menu_bar_preferences import exercise_preferences

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/menu-bar-proof'
OUT.mkdir(parents=True, exist_ok=True)
PROBE = OUT / 'probe'
CURRENT_IPC = None


def run(*args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def snapshot(name, pid=None, require_frontmost=True, activate=True):
    # Passive captures preserve a failed transition before activation has any
    # chance to repair it. Focus switching/reopen explicitly opt into activation.
    result = run(PROBE, *([pid] if pid and activate else []), capture_output=True, text=True)
    record = json.loads(result.stdout)
    if CURRENT_IPC and CURRENT_IPC.exists():
        properties = {}
        for prop in ('fullscreen', 'native-fs', 'window-maximized', 'window-minimized', 'ontop', 'border', 'time-pos',
                     'options/macos-app-activation-policy'):
            try:
                properties[prop] = PlaybackServer.mpv(CURRENT_IPC, ['get_property', prop])
            except (OSError, ValueError, RuntimeError) as error:
                properties[prop] = {'error': str(error)}
        record['mpvState'] = properties
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


def active_profile(config):
    path = config / 'users.json'
    if not path.exists():
        return None
    users = json.loads(path.read_text())
    return next((u for u in users['users'] if u['id'] == users['active']), None)


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
cases = ['original-release'] if os.environ.get('JELLYFIN_MENU_PROOF_ORIGINAL_ONLY') == '1' else [
    'original-release', 'instrumented-accessory', 'instrumented-regular', 'stable-accessory']
if os.environ.get('JELLYFIN_MENU_PROOF_SCENARIO') == 'launchservices':
    cases = ['original-raw', 'original-launchservices']
if os.environ.get('JELLYFIN_MENU_PROOF_SCENARIO') == 'configurations':
    cases = ['original-launchservices', 'original-reused-maximized', 'original-reused-titleless-maximized',
             'original-reused-system-level', 'original-reused-start-fullscreen']
for case in cases:
    app = OUT / case / 'Jellyfin Player.app'
    app.parent.mkdir()
    shutil.copytree(original, app, symlinks=True)
    original_case = case.startswith('original-')
    launchservices = case == 'original-launchservices' or case.startswith('original-reused-')
    if not original_case:
        # Core launches mpv with its own embedded library, not the outer
        # host's duplicate. Replace each copy and verify the probe ran below.
        libraries = list(app.rglob('native-scroll.dylib'))
        assert libraries
        for library in libraries:
            shutil.copy2(OUT / 'native-scroll.dylib', library)
        run('codesign', '--force', '--deep', '--sign', '-', app)
    config = OUT / case / 'profile'
    reused = case.startswith('original-reused-')
    if reused:
        shutil.copytree(OUT / 'original-launchservices/profile', config,
                        ignore=shutil.ignore_patterns('instance.lock', '*.sock'))
    else:
        config.mkdir()
    ipc = Path('/tmp') / f'menu-proof-{os.getpid()}.sock'
    CURRENT_IPC = ipc
    settings = json.loads((config / 'conf.json').read_text()) if reused else {
        'mpv_ext': True, 'mpv_ext_path': None, 'fullscreen': False,
        'browser_fullscreen': False, 'hide_title_bar': False,
        'client_uuid': case,
    }
    settings['mpv_ext_ipc'] = str(ipc)
    if 'maximized' in case:
        settings['window_maximized'] = True
    if 'titleless' in case:
        settings['hide_title_bar'] = True
    if 'start-fullscreen' in case:
        settings.update(fullscreen=True, browser_fullscreen=True)
    (config / 'conf.json').write_text(json.dumps(settings))
    (OUT / f'{case}-requested-settings.json').write_text(json.dumps({
        k: settings.get(k) for k in ('fullscreen', 'browser_fullscreen', 'hide_title_bar',
                                    'window_maximized', 'window_width', 'window_height')}, indent=2))
    mpv_options = []
    if os.environ.get('JELLYFIN_MENU_PROOF_NATIVE_FS') == 'no':
        mpv_options.append('native-fs=no')
    if case == 'stable-accessory':
        # Keep mpv's own VO initialization consistent with the hosted app's
        # policy, instead of default regular -> branding accessory transitions.
        mpv_options.append('macos-app-activation-policy=accessory')
    if case == 'original-reused-system-level':
        mpv_options.extend(['ontop=yes', 'ontop-level=system'])
    if mpv_options:
        (config / 'mpv.conf').write_text('\n'.join(mpv_options) + '\n')
    native = OUT / case / 'native-menus'
    native.mkdir()
    env = dict(os.environ, JELLYFIN_PLAYER_MENU_DIAGNOSTICS=str(native),
               JELLYFIN_MENU_PROBE_OUTPUT=str(OUT / f'{case}-in-process.jsonl'))
    if case == 'instrumented-regular':
        env['JELLYFIN_MENU_PROBE_REGULAR'] = '1'
    prior_sessions = {s['Id'] for s in server.api('GET', '/Sessions')}
    with (OUT / f'{case}-launcher.log').open('w') as log:
        proc = launch(app, config, env, log, PROBE, through_launchservices=launchservices)
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
            snapshot(case + '-cold-launch-before-prompt')
            run(PROBE, '--dismiss-local-network')
            snapshot(case + '-cold-launch', engine, require_frontmost=False, activate=False)
            # The host intentionally forwards activation to the engine after
            # 200 ms. Record that handoff instead of treating it as a failure.
            host_state = snapshot(case + '-host-active', proc.pid, require_frontmost=False, activate=not launchservices)
            engine_state = snapshot(case + '-engine-active', engine, require_frontmost=not launchservices, activate=not launchservices)
            # The GUI intentionally uses its own login path; CLI credential
            # flags are only consumed by the upstream command-line UI.
            saved_user = active_profile(config)
            if not saved_user or not saved_user.get('credentials'):
                run(PROBE, '--login', engine, server.url, server.user, server.password)
            time.sleep(3)
            snapshot(case + '-after-real-login', engine, activate=False)
            device_id = active_profile(config)['device_id']
            server.start_playback(native, ipc, case, prior_sessions, device_id=device_id)
            if server.mpv(ipc, ['get_property', 'fullscreen']):
                snapshot(case + '-startup-fullscreen-playing', engine, activate=False)
                request(config, 'fullscreen')
                time.sleep(4)
            playing_state = snapshot(case + '-playing-windowed', engine, activate=False)
            if reused:
                # This is a real second Finder/LaunchServices launch using the
                # same saved profile while the first instance is playing.
                run('/usr/bin/open', '-n', '-a', app, '--args', '--config', config)
                time.sleep(3)
                snapshot(case + '-second-launch-while-playing', engine, activate=False)
            if not original_case:
                records = [json.loads(line) for line in (OUT / f'{case}-in-process.jsonl').read_text().splitlines()]
                assert records, 'Instrumented library did not produce runtime records'
                expected_policy = 0 if case == 'instrumented-regular' else 1
                assert engine_state['frontmost']['policy'] == expected_policy, 'Activation policy intervention did not take effect at launch'
                if case == 'stable-accessory':
                    assert playing_state['frontmost']['policy'] == 1, 'Stable accessory policy did not survive media initialization'
                    assert playing_state['mpvState']['options/macos-app-activation-policy'] == 'accessory'
                if case == 'instrumented-regular':
                    assert playing_state['frontmost']['policy'] == 0, 'Regular policy did not survive media initialization'
            initial = request(config, 'state')
            (OUT / f'{case}-core-state.json').write_text(json.dumps(initial, indent=2) + '\n')
            if case == 'original-launchservices' and os.environ.get('JELLYFIN_MENU_PROOF_SCENARIO') == 'launchservices':
                exercise_preferences(OUT, app, ipc, config, request, snapshot, PROBE)
            # Reproduce the transition as well as a cold windowed launch.
            for phase in ['enter-fullscreen', 'leave-fullscreen']:
                result = request(config, 'fullscreen')
                if result.get('ok') is not True:
                    raise RuntimeError(f'{case}: fullscreen action rejected: {result}')
                time.sleep(4)
                snapshot(case + '-' + phase, engine, activate=False)
                if phase == 'leave-fullscreen':
                    time.sleep(2)
                    snapshot(case + '-leave-fullscreen-later', engine, activate=False)
            # Switching focus tests both host/engine handoff paths while media
            # continues playing. Finder activation is recorded as its own case.
            finder = json.loads(run('osascript', '-e', 'tell application "System Events" to get unix id of process "Finder"',
                                    capture_output=True, text=True).stdout)
            snapshot(case + '-finder-active', finder)
            refocus = snapshot(case + '-playing-after-app-switch', engine, require_frontmost=False)
            if refocus['frontmost'].get('pid') != engine:
                print(f'{case}: direct engine activation failed after app switch; recorded before host reopen recovery', flush=True)
                run('/usr/bin/open', '-a', app)
                time.sleep(3)
                snapshot(case + '-playing-after-host-reopen', engine, activate=False)
            for phase in ['zoom', 'restore']:
                result = request(config, 'zoom')
                if result.get('ok') is not True:
                    raise RuntimeError(f'{case}: zoom action rejected: {result}')
                time.sleep(2)
                snapshot(case + '-playing-' + phase, engine, activate=False)
            result = request(config, 'minimize')
            if result.get('ok') is not True:
                raise RuntimeError(f'{case}: minimize action rejected: {result}')
            time.sleep(2)
            snapshot(case + '-playing-minimized')
            # Activating the outer app exercises the actual reopen handshake.
            snapshot(case + '-playing-reopen', proc.pid, require_frontmost=False)
            snapshot(case + '-playing-reopened-engine', engine, activate=False)
            request(config, 'fullscreen')
            time.sleep(3)
            snapshot(case + '-playing-fullscreen-before-stop', engine, activate=False)
            model = request(config, 'state')
            stop = model['now_playing']['commands']['stop']
            assert request(config, stop).get('ok') is True
            time.sleep(4)
            snapshot(case + '-browser-after-fullscreen-stop', engine, activate=False)
            # Recreate playback, then close its fullscreen window and reopen
            # through the real host activation path rather than setting flags.
            server.start_playback(native, ipc, case + '-second', prior_sessions, device_id=device_id)
            if not server.mpv(ipc, ['get_property', 'fullscreen']):
                request(config, 'fullscreen')
                time.sleep(3)
            assert request(config, 'close').get('ok') is True
            time.sleep(3)
            snapshot(case + '-closed-from-fullscreen')
            # LaunchServices sends applicationShouldHandleReopen; mere host
            # activation intentionally leaves a deliberately closed window shut.
            run('/usr/bin/open', '-a', app)
            time.sleep(3)
            snapshot(case + '-host-reopen-after-fullscreen-close')
            snapshot(case + '-engine-after-fullscreen-close', engine, activate=False)
            summary.append({'case': case, 'hostPID': proc.pid, 'enginePID': engine,
                            'launchServices': launchservices, 'profile': str(config), 'bundle': str(app),
                            'hostFrontmost': host_state['frontmost'], 'engineFrontmost': engine_state['frontmost'],
                            'playingFrontmost': playing_state['frontmost'],
                            'directEngineRefocusSucceeded': refocus['frontmost'].get('pid') == engine})
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
print(f'Captured {len(summary)} diagnostic cases; compare actual screenshot pixels and runtime records.', flush=True)
