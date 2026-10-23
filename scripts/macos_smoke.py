#!/usr/bin/env python3
"""Exercise moved packaged macOS executables and collect native GUI evidence."""
import argparse, json, os, pathlib, plistlib, re, shutil, socket, subprocess, sys, tempfile, time

TEMP_HOME = None

PROBE_SOURCE = '''import AppKit
import CoreGraphics
import Foundation
let pid = pid_t(CommandLine.arguments[1])!
let app = NSRunningApplication(processIdentifier: pid)
let includePanels = CommandLine.arguments.contains("--panels")
let windows = (CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as? [[String: Any]] ?? []).filter {
    ($0[kCGWindowOwnerPID as String] as? Int) == Int(pid) &&
    (includePanels || ($0[kCGWindowLayer as String] as? Int) == 0)
}
let payload: [String: Any] = [
    "pid": Int(pid), "registered": app?.isTerminated == false,
    "bundlePath": app?.bundleURL?.path ?? "",
    "localizedName": app?.localizedName ?? "",
    "hidden": app?.isHidden ?? false,
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


def ipc_command(endpoint, command):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        connection.connect(str(endpoint))
        connection.sendall((json.dumps({'command': command, 'request_id': 1}) + '\n').encode())
        with connection.makefile('rb') as responses:
            for line in responses:
                response = json.loads(line)
                if response.get('request_id') == 1:
                    return response
    return None


def ipc_property(endpoint, name):
    response=ipc_command(endpoint,['get_property',name])
    return response.get('data') if response and response.get('error')=='success' else None


def visible_descendant(probe_bin, pid):
    pending=[pid]; seen=set()
    while pending:
        candidate=pending.pop()
        if candidate in seen: continue
        seen.add(candidate)
        probe=run([str(probe_bin),str(candidate)],timeout=10)
        if probe.returncode==0 and json.loads(probe.stdout).get('windows'):
            return json.loads(probe.stdout)
        pending.extend(int(child) for child in run(['/usr/bin/pgrep','-P',str(candidate)],timeout=5).stdout.split())
    return None


def verify_same_app_restore(exe, config, env, owner_pid, probe_bin):
    deadline=time.monotonic()+20
    # Wait for the app's activation handler, independently of the first blank
    # mpv window. A listener ACK after that handler is the actual readiness test.
    while time.monotonic()<deadline:
        try:
            lines=(config/'instance.lock').read_text().splitlines()
            with socket.create_connection(('127.0.0.1',int(lines[0])),timeout=2) as connection:
                connection.sendall(b'JMS1'+lines[1].encode()+b'\n')
                if connection.recv(8)==b'JMS1OK': break
        except (OSError,ValueError,IndexError): pass
        time.sleep(0.2)
    else: raise RuntimeError('main browser never acknowledged window activation')
    command=run(['/bin/ps','-ww','-p',str(owner_pid),'-o','command='],timeout=5).stdout
    endpoint=re.search(r'--input-ipc-server=([^\s]+)',command)
    if not endpoint: raise RuntimeError('could not locate the real app engine IPC socket')
    endpoint=endpoint[1]
    response=ipc_command(endpoint,['set_property','window-minimized',True])
    if not response or response.get('error')!='success': raise RuntimeError('could not minimize the actual player window')
    deadline=time.monotonic()+5
    while time.monotonic()<deadline and not ipc_property(endpoint,'window-minimized'): time.sleep(0.1)
    if not ipc_property(endpoint,'window-minimized'): raise RuntimeError('actual app window did not minimize')
    second=run([str(exe),'--config',str(config)],env=env,timeout=15)
    if second.returncode!=0: raise RuntimeError('second launch failed to acknowledge the running app')
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        if not ipc_property(endpoint,'window-minimized') and visible_descendant(probe_bin,owner_pid):
            break
        time.sleep(0.2)
    else: raise RuntimeError('second launch did not restore a minimized window')
    ipc_command(endpoint,['set_property','user-data/jellyfin-window-action',{'action':'hide'}])
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        state=json.loads(run([str(probe_bin),str(owner_pid)],timeout=10).stdout)
        if state.get('hidden'): break
        time.sleep(0.1)
    else: raise RuntimeError('could not hide the real AppKit application')
    second=run([str(exe),'--config',str(config)],env=env,timeout=15)
    if second.returncode!=0: raise RuntimeError('second launch did not acknowledge hidden-app activation')
    state=json.loads(run([str(probe_bin),str(owner_pid)],timeout=10).stdout)
    if state.get('hidden') or not state.get('windows'): raise RuntimeError('second launch did not unhide the native app')
    return {'name':'second launch restores minimized and hidden native windows after acknowledgement','passed':True}


def verify_legacy_conflict(root, app, env, base, probe_bin, evidence):
    fixture=base/'Jellyfin MPV Shim.app'
    (fixture/'Contents/MacOS').mkdir(parents=True)
    (fixture/'Contents/Info.plist').write_bytes(plistlib.dumps({
        'CFBundleExecutable':'Jellyfin MPV Shim','CFBundleIdentifier':'org.jellyfin.legacy-fixture',
        'CFBundleName':'Jellyfin MPV Shim','CFBundleShortVersionString':'0.1.0','CFBundlePackageType':'APPL'}))
    executable=fixture/'Contents/MacOS/Jellyfin MPV Shim'
    compile=run(['/usr/bin/xcrun','clang','-fobjc-arc',str(root/'tests/native/legacy_instance.m'),'-framework','Cocoa','-o',str(executable)],timeout=120)
    if compile.returncode: raise RuntimeError('legacy instance fixture failed to compile: '+compile.stderr)
    run(['/usr/bin/codesign','--force','--sign','-',str(fixture)],timeout=30)
    reports=[]
    for mode in ('hidden','minimized'):
        config=base/f'legacy-{mode}'; config.mkdir()
        ready=config/'ready'
        legacy=subprocess.Popen([str(executable),str(config),mode,str(ready)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        newcomer=None
        try:
            deadline=time.monotonic()+15
            while not ready.exists():
                if legacy.poll() is not None or time.monotonic()>deadline: raise RuntimeError('legacy fixture could not hold lock and hide/minimize')
                time.sleep(0.2)
            report=pathlib.Path(env['HOME'])/'Library/Logs/Jellyfin MPV Shim/startup-diagnostic.json'
            report.unlink(missing_ok=True)
            newcomer=subprocess.Popen([str(app/'Contents/MacOS/Jellyfin Player'),'--config',str(config)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            deadline=time.monotonic()+25
            while not report.exists():
                if newcomer.poll() is not None or time.monotonic()>deadline: raise RuntimeError('upgrade conflict did not produce a startup diagnostic')
                time.sleep(0.2)
            data=json.loads(report.read_text())
            if str(fixture) not in data['reason'] or str(legacy.pid) not in data['reason'] or '0.1.0' not in data['reason']:
                raise RuntimeError('upgrade conflict omitted legacy app path, PID or version')
            dialogs=[]
            while time.monotonic()<deadline:
                for pid in run(['/usr/bin/pgrep','-P',str(newcomer.pid)],timeout=5).stdout.split():
                    probe=run([str(probe_bin),pid,'--panels'],timeout=10)
                    if probe.returncode==0 and json.loads(probe.stdout).get('windows'):
                        dialogs.append(int(pid))
                if dialogs: break
                time.sleep(0.2)
            if not dialogs: raise RuntimeError('upgrade conflict did not show an actionable native dialog')
            import fcntl
            with (config/'instance.lock.guard').open('r+') as guard:
                try: fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError: pass
                else: raise RuntimeError('upgrade conflict lost protection of shared settings')
            if legacy.poll() is not None: raise RuntimeError('new app stopped legacy process without user action')
            for pid in dialogs: os.kill(pid,15)
            newcomer.wait(timeout=10)
            if newcomer.returncode != 1: raise RuntimeError('instance conflict must exit with a failure status')
            (evidence/f'legacy-{mode}.json').write_text(json.dumps(data,indent=2)+'\n')
            reports.append({'name':f'legacy {mode} instance produces native conflict dialog and preserves lock','passed':True})
        finally:
            if newcomer is not None:
                for pid in run(['/usr/bin/pgrep','-P',str(newcomer.pid)],timeout=5).stdout.split():
                    try: os.kill(int(pid),15)
                    except ProcessLookupError: pass
                stop_process(newcomer)
            stop_process(legacy)
    return reports


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
                str(player), '--no-config', '--no-terminal', '--force-window=yes', '--title=Jellyfin Player',
                '--vo=gpu-next', '--gpu-api=vulkan', '--gpu-context=macvk', '--ao=null',
                f'--log-file={evidence / "gpu-playback.log"}',
                '--loop-file=inf', f'--input-ipc-server={endpoint}', str(video),
            ], env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 60
                observed={}
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError(f'branded mpv exited during playback: {process.returncode}; see mpv.log')
                    try:
                        params = ipc_property(endpoint, 'video-params')
                        first = ipc_property(endpoint, 'time-pos')
                        if isinstance(params, dict) and params.get('w') == 160 and params.get('h') == 90 and isinstance(first, (int, float)):
                            time.sleep(0.5)
                            second = ipc_property(endpoint, 'time-pos')
                            identity = ipc_property(endpoint, 'user-data/jellyfin-macos-branding')
                            vo = ipc_property(endpoint, 'current-vo')
                            observed={'params':params,'first':first,'second':second,'identity':identity,'vo':vo}
                            if isinstance(second, (int, float)) and second > first and vo == 'gpu-next':
                                if not isinstance(identity, dict) or identity.get('name') != 'Jellyfin Player' or identity.get('iconMatchesJellyfin') is not True:
                                    time.sleep(0.2)
                                    continue
                                return {'name': 'bundled mpv decodes video and advances playback',
                                        'passed': True, 'videoParams': params, 'timePositions': [first, second],
                                        'videoOutput': vo, 'runtimeBranding': identity}
                    except (OSError, ValueError):
                        pass
                    time.sleep(0.2)
                raise RuntimeError('windowed playback or runtime branding did not pass: '+json.dumps(observed)+'; see gpu-playback.log')
            finally:
                stop_process(process)


def main():
    global TEMP_HOME
    if sys.platform != 'darwin':
        print('UNSUPPORTED: native smoke requires macOS; host is ' + sys.platform)
        return 0
    root=pathlib.Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser()
    parser.add_argument('--app', type=pathlib.Path, default=root/'work/dist/Jellyfin Player.app')
    parser.add_argument('--evidence', type=pathlib.Path, default=root/'outputs/macos-smoke-evidence')
    parser.add_argument('--upgrade-check', action='store_true')
    options=parser.parse_args()
    app=options.app
    if not app.is_dir(): raise RuntimeError(f'packaged app missing: {app}')
    evidence=options.evidence; evidence.mkdir(parents=True,exist_ok=True)
    base=pathlib.Path(tempfile.mkdtemp(prefix='jellyfin smoke ')); home=base/'home'; home.mkdir(); TEMP_HOME=home
    moved=base/'MOVED app with spaces'/'Jellyfin Player.app'; moved.parent.mkdir(); shutil.copytree(app,moved,symlinks=True)
    sys.path.insert(0, str(root/'work'))
    from bundle_signing import verify_bundle
    from player_runtime import player_environment
    signature_report=verify_bundle(moved)
    (evidence/'signatures.json').write_text(json.dumps(signature_report,indent=2)+'\n')
    player=moved/'Contents/Resources/mpv.app/Contents/MacOS/mpv'
    inherited={**os.environ,'HOME':str(home),'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','TMPDIR':str(base),'LANG':'en_US.UTF-8','LC_ALL':'en_US.UTF-8'}
    env={**inherited,'DYLD_PRINT_LIBRARIES':'1'}
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
    config=base/'settings'; config.mkdir()
    # The reported installation used the external backend with a null path.
    (config/'conf.json').write_text(json.dumps({'mpv_ext':True,'mpv_ext_path':None}))
    proc=subprocess.Popen([str(exe),'--config',str(config)],env=env,stdout=log,stderr=subprocess.STDOUT)
    try:
        deadline=time.time()+40; windows=0; owner_pids=[]; owner_details=[]
        while time.time()<deadline:
            if proc.poll() is not None: raise RuntimeError(f'main app exited during startup: {proc.returncode}')
            probe=run([str(probe_bin),str(proc.pid)],timeout=10)
            if probe.returncode==0:
                state=json.loads(probe.stdout); windows=state['windows']
                if windows and (not state.get('windowNames') or any('Jellyfin Player' in name for name in state['windowNames'])): break
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
            if windows:
                # mpv creates an initially untitled/default-titled window before
                # applying the client's UI properties. Wait for branding, just
                # as we wait for the first visible window within this deadline.
                if state.get('windowNames') and not any('Jellyfin Player' in name for name in state['windowNames']):
                    windows=0
                    time.sleep(.2)
                    continue
                break
            time.sleep(1)
        (evidence/'window-probe-result.json').write_text(json.dumps({'launcherPID':proc.pid,'ownerDetails':owner_details},indent=2)+'\n')
        if not windows: raise RuntimeError('native CGWindowList probe found no app-owned descendant window')
        if state.get('localizedName') and state['localizedName'] != 'Jellyfin Player':
            raise RuntimeError(f'player has the wrong running-app name: {state["localizedName"]}')
        if state.get('windowNames') and not any('Jellyfin Player' in name for name in state['windowNames']):
            raise RuntimeError(f'player has the wrong visible window title: {state["windowNames"]}')
        shot=run(['/usr/sbin/screencapture','-x',str(evidence/'player.png')],timeout=20)
        result['tests'].append({'name':'screen capture', 'status':'captured' if shot.returncode == 0 else 'unavailable', 'message':shot.stderr})
        result['tests'].append({'name':'native app liveness and ownerPID window','launcherPID':proc.pid,'ownerPID':state['pid'],'ownerDetails':owner_details,'windowCount':windows,'passed':True})
        player=moved/'Contents/Resources/mpv.app/Contents/MacOS/mpv'
        if not player.is_file(): raise RuntimeError(f'branded mpv executable missing: {player}')
        player_env=player_environment(player,moved/'Contents/Frameworks',inherited)
        player_env['DYLD_PRINT_LIBRARIES']='1'
        result['tests'].append(verify_playback(player,player_env,evidence))
        loaded=(evidence/'mpv.log').read_text()
        if '/opt/homebrew/' in loaded or '/usr/local/Cellar/' in loaded:
            raise RuntimeError('packaged player loaded a Homebrew native dependency')
        if not any('mpv.app/Contents/Frameworks/libMoltenVK.dylib' in line for line in loaded.splitlines()):
            raise RuntimeError('windowed Vulkan playback did not load bundled MoltenVK')
        result['tests'].append({'name':'Vulkan uses bundled MoltenVK only','passed':True})
        if options.upgrade_check:
            result['tests'].append(verify_same_app_restore(exe,config,env,state['pid'],probe_bin))
        stop_process(proc)
        if proc.returncode != 0: raise RuntimeError(f'main app did not shut down cleanly on SIGTERM: {proc.returncode}')
        result['tests'].append({'name':'main app handles SIGTERM and exits cleanly','returncode':proc.returncode,'passed':True})
        if options.upgrade_check:
            reopened=subprocess.Popen([str(exe),'--config',str(config)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    if reopened.poll() is not None: raise RuntimeError('app exited when reopened after clean shutdown')
                    if visible_descendant(probe_bin,reopened.pid): break
                    time.sleep(0.5)
                else: raise RuntimeError('no usable window after quit and reopen')
            finally:
                stop_process(reopened)
            if reopened.returncode!=0: raise RuntimeError('reopened app did not exit cleanly')
            result['tests'].append({'name':'quit and reopen with the same settings produces a native window','passed':True})
            result['tests'].extend(verify_legacy_conflict(root,moved,env,base,probe_bin,evidence))
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
