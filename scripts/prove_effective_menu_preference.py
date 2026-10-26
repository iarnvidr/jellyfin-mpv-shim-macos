#!/usr/bin/env python3
"""Disposable CI: require an effective Finder auto-hide control before app comparison."""
import json
import os
from pathlib import Path
import subprocess
import time
from menu_bar_launch import launch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/effective-menu-preference'
OUT.mkdir(parents=True, exist_ok=True)
PROBE = OUT / 'probe'
OCR = OUT / 'ocr'
APP = ROOT / 'release/Jellyfin Player.app'

def run(*args, **kw):
    return subprocess.run(list(map(str, args)), check=True, **kw)

run('xcrun', 'clang', '-fobjc-arc', '-DPROBE_STANDALONE', ROOT / 'tests/native/ProbeMenuBar.m', '-o', PROBE, '-framework', 'Cocoa', '-framework', 'ApplicationServices')
run('xcrun', 'swiftc', ROOT / 'tests/native/ReadMenuBar.swift', '-o', OCR, '-framework', 'AppKit', '-framework', 'Vision')


def control(value, label):
    result = subprocess.run([str(PROBE), '--menu-auto-hide', value], text=True, capture_output=True)
    (OUT / (label + '-settings.jsonl')).write_text(result.stdout)
    (OUT / (label + '-settings.stderr')).write_text(result.stderr)
    records = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    return result.returncode, next((r for r in reversed(records) if 'current' in r), {})


def dismiss():
    subprocess.run(['killall', 'System Settings'], capture_output=True)
    time.sleep(1)


def capture(label, target=None):
    if target is not None:
        run('open', '-a', target)
        time.sleep(3)
    records = {}
    for point, xy in [('away', (512, 384)), ('edge', (512, 0))]:
        run(PROBE, '--pointer', *xy, capture_output=True)
        time.sleep(3)
        state = json.loads(run(PROBE, capture_output=True, text=True).stdout)
        png = OUT / (label + '-' + point + '.png')
        run('/usr/sbin/screencapture', '-x', png)
        pixels = json.loads(run(OCR, png, capture_output=True, text=True).stdout)
        state['pixels'] = pixels
        (OUT / (label + '-' + point + '.json')).write_text(json.dumps(state, indent=2))
        records[point] = state
    return records


def finder_control(mode):
    states = capture(mode.lower() + '-finder', 'Finder')
    seen = {point: any(word['text'] == 'Finder' for word in state['pixels']['words']) for point, state in states.items()}
    assert all(s['frontmost'].get('bundle') == 'com.apple.finder' for s in states.values()), 'Finder was not frontmost'
    expected = {'away': mode == 'Never', 'edge': True}
    assert seen == expected, f'Preference is not EFFECTIVE in Finder: {mode}: {seen} expected {expected}'
    return {'requested': mode, 'finderOCR': seen, 'effectVerified': True}


def set_mode(mode):
    code, _ = control(mode, mode.lower() + '-set')
    readcode, value = control('read', mode.lower() + '-readback')
    assert not code and not readcode and value.get('current') == mode, f'Actual UI control did not read back {mode}: {value}'
    dismiss()
    return finder_control(mode)


def cold_launch(label):
    config = OUT / label / 'profile'
    config.mkdir(parents=True)
    (config / 'conf.json').write_text(json.dumps({'fullscreen': False, 'browser_fullscreen': False, 'hide_title_bar': False, 'window_width': 1280, 'window_height': 720}))
    native = OUT / label / 'native-menus'
    native.mkdir()
    env = dict(os.environ, JELLYFIN_PLAYER_MENU_DIAGNOSTICS=str(native), JELLYFIN_MENU_PROBE_OUTPUT=str(OUT / (label + '-events.jsonl')))
    with (OUT / (label + '-launch.log')).open('w') as log:
        proc = launch(APP, config, env, log, PROBE, through_launchservices=True)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        subprocess.run([str(PROBE), '--dismiss-local-network'], capture_output=True)
        state = json.loads(run(PROBE, capture_output=True, text=True).stdout)
        expected = (APP / 'Contents/Resources/mpv.app').resolve()
        engines = [p for p in state['jellyfinProcesses'] if Path(p['bundlePath']).resolve() == expected]
        if engines:
            time.sleep(3)
            return proc
        time.sleep(1)
    raise RuntimeError('Exact-bundle browser engine did not start')


code, initial = control('read', 'original')
original = initial.get('current')
result = {'original': original, 'comparisons': []}
proc = None
try:
    assert not code and original in ('Always', 'Never', 'In Full Screen Only', 'On Desktop Only'), 'Actual UI control unavailable; no effective-preference inference'
    result['comparisons'].append(set_mode('Never'))
    proc = cold_launch('cold-never')
    capture('cold-never-browser-passive')
    capture('cold-never-browser-explicit-reopen', APP)
    result['comparisons'].append(set_mode('Always'))
    capture('existing-host-always-browser', APP)
    proc.terminate(); proc.wait(20); proc = None
    time.sleep(3)
    proc = cold_launch('cold-always')
    capture('cold-always-browser-passive')
    capture('cold-always-browser-explicit-reopen', APP)
    result['comparisons'].append(set_mode('Never'))
    capture('existing-host-never-browser', APP)
    result['status'] = 'effective-control-and-comparison-complete'
finally:
    if proc:
        proc.terminate()
        proc.wait(20)
    if original:
        control(original, 'restore')
        restorecode, restored = control('read', 'restored-readback')
        result['restored'] = not restorecode and restored.get('current') == original
        assert result['restored'], 'UI preference not restored'
    dismiss()
    (OUT / 'result.json').write_text(json.dumps(result, indent=2))
