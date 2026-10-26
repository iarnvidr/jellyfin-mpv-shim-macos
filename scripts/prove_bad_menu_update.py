#!/usr/bin/env python3
"""Diagnostic only: update an observed bad-menu 0.2.9 session using the public feed."""
import getpass
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tarfile
import time
import traceback
from menu_bar_launch import launch
from menu_bar_playback import PlaybackServer, wait_for
from sparkle_smoke import released_archive, download
import release
from bundle_signing import verify_bundle

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/bad-menu-update'
OUT.mkdir(parents=True, exist_ok=True)
PROBE = OUT / 'probe'
OCR = OUT / 'ocr'
IPC = Path('/tmp/bad-menu-update.sock')
PROFILE = Path('/Users') / getpass.getuser() / 'Library/Application Support/jellyfin-mpv-shim'
APP = Path('/Applications/Jellyfin Player.app')
EVENTS = OUT / 'observations.jsonl'
FEED = 'https://raw.githubusercontent.com/iarnvidr/jellyfin-mpv-shim-macos/updates/appcast.xml'
result = {'passed': False, 'from': '0.2.9', 'to': '0.2.11', 'productionFeed': FEED,
          'modeChangeViaDiagnosticIPC': True, 'actualUserTriggerEstablished': False,
          'observer': 'Read-only AppKit timer loaded with LLDB; released bundle bytes unchanged'}
server = None


def run(*args, **kw):
    return subprocess.run(list(map(str, args)), check=True, **kw)


def desktop():
    return json.loads(run(PROBE, capture_output=True, text=True).stdout)


def process_state(pid):
    p = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'pid=,ppid=,stat=,comm='], capture_output=True, text=True)
    return {'pid': pid, 'psStatus': p.returncode, 'process': p.stdout.strip()}


def observe(pid, label):
    # No presentation/activation expression is executed. The loaded timer only
    # reads NSApp state; its source and debugger transcript are retained.
    p = subprocess.run(['xcrun', 'lldb', '--batch', '-p', str(pid),
                        '-o', 'process load ' + str(OUT / 'observer.dylib'), '-o', 'process detach'],
                       capture_output=True, text=True, timeout=40)
    (OUT / (label + '-lldb.log')).write_text(p.stdout + p.stderr)
    def record():
        if not EVENTS.exists():
            return None
        return next((d for d in reversed([json.loads(x) for x in EVENTS.read_text().splitlines()]) if d['pid'] == pid), None)
    return wait_for('actual in-process AppKit observer ' + str(pid), record, seconds=10)


def latest(pid):
    return next(d for d in reversed([json.loads(x) for x in EVENTS.read_text().splitlines()]) if d['pid'] == pid)


def snapshot(label):
    state = desktop()
    state['processes'] = {key: process_state(pid) for key, pid in result.get('oldPIDs', {}).items()}
    state['installedVersion'] = plistlib.loads((APP / 'Contents/Info.plist').read_bytes())['CFBundleShortVersionString']
    try:
        state['mpvFullscreen'] = PlaybackServer.mpv(IPC, ['get_property', 'fullscreen'])
        state['mpvNativeFs'] = PlaybackServer.mpv(IPC, ['get_property', 'native-fs'])
    except (OSError, ValueError, RuntimeError) as error:
        state['mpvReadError'] = str(error)
    png = OUT / (label + '.png')
    run('/usr/sbin/screencapture', '-x', png)
    state['pixels'] = json.loads(run(OCR, png, capture_output=True, text=True).stdout)
    (OUT / (label + '.json')).write_text(json.dumps(state, indent=2))
    return state


try:
    assert os.environ.get('GITHUB_ACTIONS') == 'true', 'Disposable macOS CI only'
    assert not PROFILE.exists() and not APP.exists(), 'Refusing to replace an existing app/profile'
    run('xcrun', 'clang', '-fobjc-arc', '-DPROBE_STANDALONE', ROOT / 'tests/native/ProbeMenuBar.m', '-o', PROBE, '-framework', 'Cocoa', '-framework', 'ApplicationServices')
    run('xcrun', 'swiftc', ROOT / 'tests/native/ReadMenuBar.swift', '-o', OCR, '-framework', 'AppKit', '-framework', 'Vision')
    observer = (ROOT / 'tests/native/ProbeMenuBar.m').read_text().replace('if (!path) return;', 'if (!path) path = @' + json.dumps(str(EVENTS)) + ';')
    (OUT / 'observer.m').write_text(observer)
    run('xcrun', 'clang', '-dynamiclib', '-fobjc-arc', OUT / 'observer.m', '-o', OUT / 'observer.dylib', '-framework', 'Cocoa', '-framework', 'ApplicationServices')
    run('codesign', '--force', '--sign', '-', OUT / 'observer.dylib')
    verifier = OUT / 'verify-update'
    run('xcrun', 'swiftc', ROOT / 'tests/native/VerifyUpdate.swift', '-o', verifier)
    old = OUT / 'old'; old.mkdir()
    archive, _ = released_archive('0.2.9', old, verifier)
    result['oldArchiveSHA256'] = release.checksum(archive)
    run('ditto', '-x', '-k', archive, APP.parent)
    result['beforeSignatures'] = verify_bundle(APP)
    lock = dict(line.split('=', 1) for line in (ROOT / 'work/native-dependencies.lock').read_text().splitlines() if line and not line.startswith('#'))
    sdk_archive = OUT / 'sparkle.tar.xz'
    download(lock['SPARKLE_URL'], sdk_archive)
    assert release.checksum(sdk_archive) == lock['SPARKLE_SHA256']
    sdk = OUT / 'sparkle'; sdk.mkdir()
    with tarfile.open(sdk_archive) as tar:
        tar.extractall(sdk, filter='data')
    contents = OUT / 'Update Test.app/Contents'
    (contents / 'MacOS').mkdir(parents=True)
    (contents / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'org.jellyfin.mpvshim.update-test', 'CFBundleExecutable': 'AutoUpdate', 'CFBundlePackageType': 'APPL', 'CFBundleVersion': '1', 'LSUIElement': True}))
    cli = contents / 'MacOS/AutoUpdate'
    run('xcrun', 'clang', '-fobjc-arc', '-fblocks', ROOT / 'tests/native/AutoUpdate.m', '-o', cli, '-F', sdk, '-framework', 'AppKit', '-framework', 'Sparkle', '-Wl,-rpath,' + str(sdk))
    # Supported Sparkle scheduling preference on this disposable CI account:
    # prevent an unsolicited startup update window from repairing focus before
    # the positive condition. The explicit driver still checks the public feed.
    run('defaults', 'write', 'org.jellyfin.mpvshim.local', 'SUEnableAutomaticChecks', '-bool', 'false')
    result['startupAutomaticChecksDisabled'] = True
    PROFILE.mkdir(parents=True)
    (PROFILE / 'conf.json').write_text(json.dumps({'fullscreen': False, 'browser_fullscreen': False, 'hide_title_bar': False, 'mpv_ext_ipc': str(IPC), 'video_volume': 37}))
    (PROFILE / 'mpv.conf').write_text('native-fs=no\n')
    (PROFILE / 'update-test-sentinel').write_text('preserve bad-state profile')
    native = OUT / 'native-menus'; native.mkdir()
    env = dict(os.environ, JELLYFIN_PLAYER_MENU_DIAGNOSTICS=str(native), JELLYFIN_MENU_PROBE_OUTPUT=str(EVENTS))
    with (OUT / 'launch.log').open('w') as log:
        host = launch(APP, PROFILE, env, log, PROBE, through_launchservices=True)
    def engine():
        return next((p for p in desktop()['jellyfinProcesses'] if p['bundlePath'] == str(APP / 'Contents/Resources/mpv.app')), None)
    old_engine = wait_for('exact released engine', engine)['pid']
    time.sleep(3)
    run(PROBE, '--dismiss-local-network', capture_output=True)
    old_engine = wait_for('exact engine after prompt', engine)['pid']
    old_core = json.loads((PROFILE / 'instance.lock').read_text().splitlines()[2])['pid']
    result['oldPIDs'] = {'host': host.pid, 'core': old_core, 'engine': old_engine}
    observe(old_engine, 'old-engine')
    server = PlaybackServer(ROOT, OUT)
    run(PROBE, '--login', old_engine, server.url, server.user, server.password)
    time.sleep(3)
    server.start_playback(native, IPC, 'old-real-playback')
    for command in [['set_property', 'native-fs', False], ['set_property', 'fullscreen', True],
                    ['set_property', 'native-fs', True], ['set_property', 'fullscreen', False],
                    ['set_property', 'fullscreen', False]]:
        PlaybackServer.mpv(IPC, command)
        time.sleep(4)
    before = snapshot('positive-before-update')
    observed = latest(old_engine)
    (OUT / 'positive-before-appkit.json').write_text(json.dumps(observed, indent=2))
    assert before['frontmost']['pid'] == old_engine
    assert before['mpvFullscreen'] is False
    assert any(w['pid'] == old_engine and w.get('AXFullScreen') is False for w in before['jellyfinAXWindows'])
    assert observed['presentationOptions'] == 5 and observed['systemPresentationOptions'] == 5 and observed['menuBarVisible'] is False
    assert before['pixels']['top22NonBlackPixels'] == 0 and not before['pixels']['words'], 'Positive whole-strip disappearance not established'
    result['positiveBeforeEstablished'] = True
    # The normal automatic Sparkle driver uses the actual public production feed.
    # No app version, bundle, feed metadata or presentation state is modified.
    with (OUT / 'automatic-installation.log').open('w') as log:
        completed = subprocess.run([str(cli), str(APP), FEED], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=150)
    result['installationStatus'] = completed.returncode
    assert completed.returncode == 0
    def new_engine():
        candidates = [p for p in desktop()['jellyfinProcesses'] if p['bundlePath'] == str(APP / 'Contents/Resources/mpv.app') and p['pid'] != old_engine]
        return candidates[-1] if candidates else None
    new = wait_for('automatically relaunched exact new engine', new_engine, seconds=60)
    time.sleep(3)
    after = snapshot('after-update-first-passive')
    result['afterFirstPassive'] = {'frontmostPID': after['frontmost'].get('pid'), 'version': after['installedVersion'], 'enginePID': new['pid']}
    result['oldProcessesAfter'] = {k: process_state(v) for k, v in result['oldPIDs'].items()}
    result['afterSignatures'] = verify_bundle(APP)
    result['retainedProfile'] = (PROFILE / 'update-test-sentinel').read_text() == 'preserve bad-state profile'
    result['retainedVolume'] = json.loads((PROFILE / 'conf.json').read_text()).get('video_volume') == 37
    assert after['installedVersion'] == '0.2.11'
    assert all(p['psStatus'] != 0 for p in result['oldProcessesAfter'].values()), 'An old host/core/engine remains alive'
    assert after['frontmost']['pid'] == new['pid'], 'New engine is not naturally frontmost'
    assert any('Jellyfin' in w['text'] for w in after['pixels']['words']), 'Automatic update did not restore a visible menu strip'
    result['newAppKit'] = observe(new['pid'], 'new-engine-after-passive-capture')
    result['passed'] = True
except Exception as error:
    result['error'] = str(error)
    (OUT / 'traceback.log').write_text(traceback.format_exc())
    raise
finally:
    (OUT / 'result.json').write_text(json.dumps(result, indent=2))
    if server:
        server.close()
