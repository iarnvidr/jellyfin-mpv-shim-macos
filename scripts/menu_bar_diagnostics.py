"""Qualify the real packaged recorder through independent AppKit and AX UI."""
import copy
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import time
from menu_bar_playback import PlaybackServer


def exercise_diagnostics(case, out, app, engine, host, snapshot, request, config, probe, ipc):
    root = Path(__file__).resolve().parents[1]
    storage = Path.home() / 'Library/Logs/Jellyfin Player/menu-state'
    control_binary = out / 'menu-diagnostics-control'
    ax = out / 'menu-diagnostics-ax'
    commands = out / 'control-command.txt'
    control_output = out / (case + '-independent-control.jsonl')
    subprocess.run(['xcrun', 'swiftc', str(root / 'tests/native/MenuDiagnosticsControl.swift'),
                    '-o', str(control_binary), '-framework', 'AppKit'], check=True)
    subprocess.run(['xcrun', 'clang', '-fobjc-arc', str(root / 'tests/native/MenuDiagnosticsAX.m'),
                    '-o', str(ax), '-framework', 'Cocoa', '-framework', 'ApplicationServices'], check=True)
    events = []

    def wait(label, callback, seconds=20):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                result = callback()
                if result:
                    return result
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(0.1)
        raise RuntimeError('Diagnostic fixture precondition failed: ' + label)

    def role(name):
        data = (storage / (name + '.json')).read_bytes()
        assert len(data) <= 262144, 'Unbounded role file'
        value = json.loads(data)
        assert len(value['history']) <= 16, 'Unbounded role history'
        assert value['identity']['hostPID'] == host
        if name == 'engine':
            assert value['identity']['pid'] == engine
        return value

    def control_record(phase, after=0):
        rows = [json.loads(line) for line in control_output.read_text().splitlines()]
        return next((row for row in reversed(rows) if row['phase'] == phase and row['wallTime'] >= after), None)

    def set_control(command, options):
        started = time.time()
        commands.write_text(command)
        value = wait('independent control ' + command, lambda: control_record(command, started))
        assert value['requestedPresentationOptions'] == options
        assert value['effectivePresentationOptions'] == options
        assert value['frontmostPID'] == control.pid and value['active'] is True
        assert not value['windowStyleMask'] & (1 << 14), 'Control accidentally entered native fullscreen'
        events.append({'control': command, 'actual': value})

    def press(mode):
        def attempt():
            result = subprocess.run([str(ax), mode, str(host)], capture_output=True, text=True)
            if result.returncode == 0:
                events.append({'ax': mode, 'result': json.loads(result.stdout), 'time': time.time()})
                return True
            return False
        return wait('native AX ' + mode, attempt)

    def copy_report(label, *checks):
        press('copy')
        data = subprocess.check_output(['/usr/bin/pbpaste'])
        destination = out / (case + '-' + label + '.json')
        destination.write_bytes(data)
        subprocess.run(['python3', str(root / 'scripts/check_menu_diagnostics_report.py'),
                        str(destination), *map(str, checks)], check=True)
        return destination, json.loads(data)

    documents = wait('both actual recorder roles', lambda: (role('host'), role('engine')))
    assert documents[0]['identity']['sessionID'] == documents[1]['identity']['sessionID']
    assert documents[0]['identity']['corePID'] == documents[1]['identity']['corePID']
    control = subprocess.Popen([str(control_binary), str(commands), str(control_output)])
    stopped = False
    original_peer = None
    try:
        wait('control launched', lambda: control_record('launched'))
        wait('control actually foreground', lambda: json.loads(subprocess.check_output([str(probe)]))['frontmost']['pid'] == control.pid)
        set_control('normal', 0)
        set_control('hide', 5)

        def background_positive():
            for name in ('host', 'engine'):
                entries = role(name)['history']
                if not any(not e['state']['active']
                           and e['state']['requestedPresentation'] == 0
                           and e['state']['effectivePresentation'] == 5 for e in entries):
                    return False
            return True

        wait('both inactive app roles recorded real external effective-option KVO', background_positive)
        for name in ('host', 'engine'):
            (out / (case + '-' + name + '-positive-source.json')).write_text(json.dumps(role(name), indent=2))
        set_control('normal', 0)
        os.kill(host, signal.SIGURG)  # Same direct route as the browser Settings button.
        first, first_report = copy_report('frozen-first', '--require-peer', '--require-background-effective', '5', '--require-kvo')
        os.kill(host, signal.SIGURG)
        time.sleep(1)
        copy_report('frozen-repeat-visible', '--require-peer', '--same-frozen-as', first)
        press('close')
        time.sleep(0.5)
        os.kill(host, signal.SIGURG)
        second, second_report = copy_report('frozen-new-opening', '--require-peer', '--newer-than', first)
        press('close')
        time.sleep(0.5)

        # Separate app-owned positive: actual intentional legacy fullscreen
        # makes the shipped engine request options 5. This is observability
        # qualification, not a reproduction of the user's windowed failure.
        subprocess.run(['/usr/bin/open', '-a', str(app)], check=True)
        time.sleep(2)
        PlaybackServer.mpv(ipc, ['set_property', 'native-fs', False])
        PlaybackServer.mpv(ipc, ['set_property', 'fullscreen', True])
        wait('actual engine-owned presentation state 5', lambda: any(
            e['state']['requestedPresentation'] == 5 and e['state']['effectivePresentation'] == 5
            and e['state']['active'] for e in role('engine')['history']))
        assert PlaybackServer.mpv(ipc, ['get_property', 'fullscreen']) is True
        (out / (case + '-engine-owned-positive-source.json')).write_text(json.dumps(role('engine'), indent=2))
        os.kill(host, signal.SIGURG)
        _, engine_report = copy_report('engine-hiding-before-settings', '--require-peer', '--require-engine-requested', '5', '--newer-than', second)
        wait('host now active with normal effective options', lambda: any(
            e['monotonic'] > engine_report['cutoffMonotonic'] and e['state']['active']
            and e['state']['requestedPresentation'] == 0
            and e['state']['effectivePresentation'] == 0 for e in role('host')['history']))
        press('close')
        PlaybackServer.mpv(ipc, ['set_property', 'fullscreen', False])
        PlaybackServer.mpv(ipc, ['set_property', 'native-fs', True])
        time.sleep(1)

        # A controlled malformed local peer must be rejected, never copied.
        # Pause only the disposable CI engine to prevent its heartbeat from
        # racing this deliberate fixture payload; always resume in finally.
        os.kill(engine, signal.SIGSTOP)
        stopped = True
        time.sleep(0.2)
        original_peer = role('engine')
        malformed = copy.deepcopy(original_peer)
        private = 'DIAGNOSTIC_PRIVATE_TITLE_https://secret.invalid/token=DO_NOT_COPY'
        malformed['privateSentinel'] = private
        peer_path = storage / 'engine.json'
        peer_path.write_text(json.dumps(malformed))
        os.chmod(peer_path, 0o600)
        os.kill(host, signal.SIGURG)
        _, rejected = copy_report('rejected-private-peer', '--exclude-sentinel', private)
        assert rejected['peer']['status'] == 'unreadableOrInvalid'
        assert 'document' not in rejected['peer']
        press('close')
        malformed_pid = copy.deepcopy(original_peer)
        malformed_pid['identity']['pid'] = 1 << 40
        peer_path.write_text(json.dumps(malformed_pid))
        os.chmod(peer_path, 0o600)
        os.kill(host, signal.SIGURG)
        _, rejected_pid = copy_report('rejected-overflow-pid')
        assert rejected_pid['peer']['status'] == 'unreadableOrInvalid'
        assert 'document' not in rejected_pid['peer']
        peer_path.write_text(json.dumps(original_peer))
        os.chmod(peer_path, 0o600)
        os.kill(engine, signal.SIGCONT)
        stopped = False
        press('close')
        commands.write_text('quit')
        control.wait(timeout=10)
        time.sleep(1)
        mode = stat.S_IMODE(storage.stat().st_mode)
        assert mode == 0o700
        files = list(storage.iterdir())
        assert {p.name for p in files} <= {'host.json', 'engine.json', 'host.json.tmp', 'engine.json.tmp'}
        for path in files:
            assert path.stat().st_size <= 262144
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
        events.append({'storageFiles': len(files), 'storageMode': mode,
                       'firstCutoff': first_report['cutoffMonotonic'], 'secondCutoff': second_report['cutoffMonotonic']})
        snapshot(case + '-after-real-copy-qualification', activate=False, require_frontmost=False)
        result = {'passed': True, 'hostPID': host, 'enginePID': engine,
                  'positiveGlobalOptions': 5, 'normalGlobalOptions': 0,
                  'actualEngineRequestedOptionsFiveBeforeSettings': True,
                  'actualAXCopyAndPasteboard': True, 'frozenVisiblePreserved': True,
                  'newSettingsOpeningRefreshed': True, 'privatePeerRejected': True, 'events': events}
        (out / (case + '-qualification.json')).write_text(json.dumps(result, indent=2))
        return result
    finally:
        if stopped:
            if original_peer is not None:
                peer_path = storage / 'engine.json'
                peer_path.write_text(json.dumps(original_peer))
                os.chmod(peer_path, 0o600)
            os.kill(engine, signal.SIGCONT)
        if control.poll() is None:
            commands.write_text('quit')
            try:
                control.wait(timeout=5)
            except subprocess.TimeoutExpired:
                control.terminate()
