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

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/menu-bar-proof'
OUT.mkdir(parents=True, exist_ok=True)
PROBE = OUT / 'probe'


def run(*args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def snapshot(name, pid=None):
    result = run(PROBE, *([pid] if pid else []), capture_output=True, text=True)
    record = json.loads(result.stdout)
    (OUT / f'{name}.json').write_text(json.dumps(record, indent=2) + '\n')
    shot = subprocess.run(['/usr/sbin/screencapture', '-x', str(OUT / f'{name}.png')], capture_output=True, text=True)
    if shot.returncode:
        raise RuntimeError(f'Screenshot unavailable: {shot.stderr}')
    print(name, json.dumps(record['frontmost']), flush=True)
    if pid and record['frontmost'].get('pid') != pid:
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
summary = []
for case in ['original-release', 'instrumented-accessory', 'instrumented-regular']:
    app = OUT / case / 'Jellyfin Player.app'
    app.parent.mkdir()
    shutil.copytree(original, app, symlinks=True)
    if case != 'original-release':
        shutil.copy2(OUT / 'native-scroll.dylib', app / 'Contents/Frameworks/native-scroll.dylib')
        run('codesign', '--force', '--deep', '--sign', '-', app)
    config = OUT / case / 'profile'
    config.mkdir()
    (config / 'conf.json').write_text(json.dumps({
        'mpv_ext': True, 'mpv_ext_path': None, 'fullscreen': False,
        'browser_fullscreen': False, 'hide_title_bar': False,
    }))
    native = OUT / case / 'native-menus'
    native.mkdir()
    env = dict(os.environ, JELLYFIN_PLAYER_MENU_DIAGNOSTICS=str(native),
               JELLYFIN_MENU_PROBE_OUTPUT=str(OUT / f'{case}-in-process.jsonl'))
    if case == 'instrumented-regular':
        env['JELLYFIN_MENU_PROBE_REGULAR'] = '1'
    with (OUT / f'{case}-launcher.log').open('w') as log:
        proc = subprocess.Popen([str(app / 'Contents/MacOS/Jellyfin Player'), '--config', str(config)],
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
            host_state = snapshot(case + '-host-active', proc.pid)
            engine_state = snapshot(case + '-engine-active', engine)
            initial = request(config, 'state')
            (OUT / f'{case}-core-state.json').write_text(json.dumps(initial, indent=2) + '\n')
            # Reproduce the transition as well as a cold windowed launch.
            for phase in ['enter-fullscreen', 'leave-fullscreen']:
                result = request(config, 'fullscreen')
                if result.get('ok') is not True:
                    raise RuntimeError(f'{case}: fullscreen action rejected: {result}')
                time.sleep(4)
                snapshot(case + '-' + phase, engine)
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
(OUT / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print('All three cases captured; compare screenshots with in-process records.', flush=True)
