#!/usr/bin/env python3
"""Exercise moved packaged macOS executables and collect native GUI evidence."""
import json, os, pathlib, shutil, socket, subprocess, sys, tempfile, time

TEMP_HOME = None

PROBE_SOURCE = '''import AppKit
import CoreGraphics
import Foundation
let pid = pid_t(CommandLine.arguments[1])!
let app = NSRunningApplication(processIdentifier: pid)
let windows = (CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as? [[String: Any]] ?? []).filter {
    ($0[kCGWindowOwnerPID as String] as? Int) == Int(pid) &&
    ($0[kCGWindowLayer as String] as? Int) == 0
}
let payload: [String: Any] = [
    "pid": Int(pid), "registered": app?.isTerminated == false,
    "bundlePath": app?.bundleURL?.path ?? "",
    "localizedName": app?.localizedName ?? "",
    "windows": windows.count,
    "windowNames": windows.compactMap { $0[kCGWindowName as String] as? String },
    "windowBounds": windows.compactMap { $0[kCGWindowBounds as String] as? [String: Any] }
]
let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
print(String(decoding: data, as: UTF8.self))
'''


def run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, **kw)


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def retain_logs(evidence):
    copied = []
    logs = TEMP_HOME / 'Library/Logs/Jellyfin MPV Shim' if TEMP_HOME else None
    if logs and logs.exists():
        for item in logs.rglob('*'):
            if item.is_file():
                destination = evidence / 'home-logs' / item.relative_to(logs)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, destination)
                copied.append(str(destination.relative_to(evidence)))
    return copied


def ipc_property(endpoint, name):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        connection.connect(str(endpoint))
        connection.sendall((json.dumps({'command': ['get_property', name], 'request_id': 1}) + '\n').encode())
        with connection.makefile('rb') as responses:
            for line in responses:
                response = json.loads(line)
                if response.get('request_id') == 1:
                    return response.get('data') if response.get('error') == 'success' else None
    return None


def verify_playback(player, env, evidence):
    # A finite Y4M clip exercises the demuxer/decoder without a network service,
    # ffmpeg executable, audio device, or third-party test dependency.
    with tempfile.TemporaryDirectory(prefix='jf-playback-', dir='/tmp') as directory:
        fixture = pathlib.Path(directory)
        video = fixture / 'test.y4m'
        with video.open('wb') as output:
            output.write(b'YUV4MPEG2 W160 H90 F10:1 Ip A1:1 C420jpeg\n')
            for frame in range(40):
                output.write(b'FRAME\n')
                output.write(bytes([16 + frame]) * (160 * 90))
                output.write(bytes([128]) * (160 * 90 // 2))
        endpoint = fixture / 'mpv.sock'
        with (evidence / 'mpv.log').open('w') as log:
            process = subprocess.Popen([
                str(player), '--no-config', '--no-terminal', '--vo=null', '--ao=null',
                '--loop-file=inf', f'--input-ipc-server={endpoint}', str(video),
            ], env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError(f'branded mpv exited during playback: {process.returncode}; see mpv.log')
                    try:
                        params = ipc_property(endpoint, 'video-params')
                        first = ipc_property(endpoint, 'time-pos')
                        if isinstance(params, dict) and params.get('w') == 160 and params.get('h') == 90 and isinstance(first, (int, float)):
                            time.sleep(0.5)
                            second = ipc_property(endpoint, 'time-pos')
                            if isinstance(second, (int, float)) and second > first:
                                return {'name': 'bundled mpv decodes video and advances playback',
                                        'passed': True, 'videoParams': params, 'timePositions': [first, second]}
                    except (OSError, ValueError):
                        pass
                    time.sleep(0.2)
                raise RuntimeError('bundled mpv did not decode and advance the test video; see mpv.log')
            finally:
                stop_process(process)


def main():
    global TEMP_HOME
    if sys.platform != 'darwin':
        print('UNSUPPORTED: native smoke requires macOS; host is ' + sys.platform)
        return 0
    root=pathlib.Path(__file__).resolve().parents[1]
    app=root/'work/dist/Jellyfin Player.app'
    if not app.is_dir(): raise RuntimeError(f'packaged app missing: {app}')
    evidence=root/'outputs/macos-smoke-evidence'; evidence.mkdir(parents=True,exist_ok=True)
    base=pathlib.Path(tempfile.mkdtemp(prefix='jellyfin smoke ')); home=base/'home'; home.mkdir(); TEMP_HOME=home
    moved=base/'MOVED app with spaces'/'Jellyfin Player.app'; moved.parent.mkdir(); shutil.copytree(app,moved,symlinks=True)
    env={**os.environ,'HOME':str(home),'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','TMPDIR':str(base),'LANG':'en_US.UTF-8','LC_ALL':'en_US.UTF-8','DYLD_PRINT_LIBRARIES':'1'}
    result={'host':run(['/usr/bin/sw_vers']).stdout,'app':str(moved),'profile':str(home),'tests':[]}
    helper=moved/'Contents/Helpers/Mac Updater.app/Contents/MacOS/Mac Updater'
    if not helper.is_file(): raise RuntimeError(f'updater executable missing: {helper}')
    dyld=run([str(helper),'--dyld-smoke'],env=env,timeout=60)
    (evidence/'updater-dyld.log').write_text(dyld.stdout+'\n--- stderr ---\n'+dyld.stderr)
    framework=str(moved/'Contents/Frameworks/Sparkle.framework/')
    ok=dyld.returncode==0 and 'JELLYFIN_PLAYER_SPARKLE_DYLD_OK' in dyld.stdout and framework in dyld.stdout+dyld.stderr
    result['tests'].append({'name':'moved updater loads bundled Sparkle','returncode':dyld.returncode,'framework':framework,'passed':ok})
    if not ok: raise RuntimeError('updater did not load Sparkle from moved bundle; see updater-dyld.log')
    exe=moved/'Contents/MacOS/Jellyfin Player'
    if not exe.is_file(): raise RuntimeError(f'main executable missing: {exe}')
    probe_source=evidence/'window_probe.swift'
    probe_source.write_text(PROBE_SOURCE)
    probe_bin=evidence/'window-probe'
    compiled=run(['/usr/bin/xcrun','swiftc',str(probe_source),'-o',str(probe_bin)],timeout=120)
    (evidence/'window-probe-compile.log').write_text(compiled.stdout+'\n--- stderr ---\n'+compiled.stderr)
    if compiled.returncode: raise RuntimeError('native AppKit/CGWindow probe compilation failed')
    log=(evidence/'player.log').open('w')
    proc=subprocess.Popen([str(exe)],env=env,stdout=log,stderr=subprocess.STDOUT)
    try:
        deadline=time.time()+40; windows=0; owner_pids=[]; owner_details=[]
        while time.time()<deadline:
            if proc.poll() is not None: raise RuntimeError(f'main app exited during startup: {proc.returncode}')
            probe=run([str(probe_bin),str(proc.pid)],timeout=10)
            if probe.returncode==0:
                state=json.loads(probe.stdout); windows=state['windows']
                if windows: break
            # A launcher started as a raw executable need not be registered with
            # LaunchServices, so NSRunningApplication may return nil for its PID.
            # Discover and probe actual descendant PIDs on every poll instead.
            pending=[proc.pid]; seen={proc.pid}; owner_pids=[]
            while pending:
                parent=pending.pop(0)
                for child_text in run(['/usr/bin/pgrep','-P',str(parent)],timeout=5).stdout.split():
                    child=int(child_text)
                    if child not in seen:
                        seen.add(child); pending.append(child); owner_pids.append(child)
            for candidate in owner_pids:
                candidate_probe=run([str(probe_bin),str(candidate)],timeout=10)
                if candidate_probe.returncode==0:
                    candidate_state=json.loads(candidate_probe.stdout); owner_details.append(candidate_state)
                    if candidate_state.get('windows'):
                        windows=candidate_state['windows']; state=candidate_state; break
            if windows: break
            time.sleep(1)
        (evidence/'window-probe-result.json').write_text(json.dumps({'launcherPID':proc.pid,'ownerDetails':owner_details},indent=2)+'\n')
        if not windows: raise RuntimeError('native CGWindowList probe found no app-owned descendant window')
        shot=run(['/usr/sbin/screencapture','-x',str(evidence/'player.png')],timeout=20)
        result['tests'].append({'name':'screen capture', 'status':'captured' if shot.returncode == 0 else 'unavailable', 'message':shot.stderr})
        result['tests'].append({'name':'native app liveness and ownerPID window','launcherPID':proc.pid,'ownerPID':state['pid'],'ownerDetails':owner_details,'windowCount':windows,'passed':True})
        player=moved/'Contents/Resources/mpv.app/Contents/MacOS/mpv'
        if not player.is_file(): raise RuntimeError(f'branded mpv executable missing: {player}')
        result['tests'].append(verify_playback(player,env,evidence))
        stop_process(proc)
        if proc.returncode != 0: raise RuntimeError(f'main app did not shut down cleanly on SIGTERM: {proc.returncode}')
        result['tests'].append({'name':'main app handles SIGTERM and exits cleanly','returncode':proc.returncode,'passed':True})
    finally:
        stop_process(proc)
        log.close()
        result['logs'] = retain_logs(evidence)
    (evidence/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2)); return 0


def retain_failure(exc):
    if sys.platform != 'darwin': return
    evidence=pathlib.Path(__file__).resolve().parents[1]/'outputs/macos-smoke-evidence'
    evidence.mkdir(parents=True,exist_ok=True)
    copied=retain_logs(evidence)
    (evidence/'result.json').write_text(json.dumps({'passed':False,'error':str(exc),'logs':copied},indent=2)+'\n')


if __name__=='__main__':
    try: sys.exit(main())
    except Exception as exc:
        print('SMOKE FAILED: '+str(exc),file=sys.stderr)
        try: retain_failure(exc)
        except Exception as retain_exc: print('EVIDENCE RETENTION FAILED: '+str(retain_exc),file=sys.stderr)
        sys.exit(1)
