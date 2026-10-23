#!/usr/bin/env python3
"""Exercise moved packaged macOS executables and collect native GUI evidence."""
import json, os, pathlib, shutil, subprocess, sys, tempfile, time

TEMP_HOME = None


def run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, **kw)


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
    probe_source.write_text('''import AppKit\nimport CoreGraphics\nimport Foundation\nlet pid = pid_t(CommandLine.arguments[1])!\nlet app = NSRunningApplication(processIdentifier: pid)\nlet windows = (CGWindowListCopyWindowInfo([.optionAll], kCGNullWindowID) as? [[String: Any]] ?? []).filter { ($0[kCGWindowOwnerPID as String] as? Int) == Int(pid) }\nlet names = windows.compactMap { $0[kCGWindowName as String] as? String }\nprint((try! JSONSerialization.data(withJSONObject: ["pid": Int(pid), "alive": app != nil && !app.isTerminated, "windows": windows.count, "windowNames": names], options: [.sortedKeys])).map { String(UnicodeScalar($0)) }.joined())\n''')
    probe_bin=evidence/'window-probe'
    compiled=run(['/usr/bin/xcrun','swiftc',str(probe_source),'-o',str(probe_bin)],timeout=120)
    (evidence/'window-probe-compile.log').write_text(compiled.stdout+'\n--- stderr ---\n'+compiled.stderr)
    if compiled.returncode: raise RuntimeError('native AppKit/CGWindow probe compilation failed')
    log=(evidence/'player.log').open('w')
    proc=subprocess.Popen([str(exe)],env=env,stdout=log,stderr=subprocess.STDOUT)
    try:
        deadline=time.time()+60; windows=[]; alive=False
        while time.time()<deadline:
            if proc.poll() is not None: raise RuntimeError(f'main app exited during startup: {proc.returncode}')
            probe=run([str(probe_bin),str(proc.pid)],timeout=10)
            if probe.returncode==0:
                state=json.loads(probe.stdout); alive=state['alive']; windows=state['windows']
                if alive and windows: break
            time.sleep(1)
        if not alive: raise RuntimeError('native NSRunningApplication probe reports app not alive')
        if not windows: raise RuntimeError('native CGWindowList probe found no app-owned window for launcher PID')
        shot=run(['/usr/sbin/screencapture','-x',str(evidence/'player.png')],timeout=20)
        if shot.returncode: raise RuntimeError('screencapture failed: '+shot.stderr)
        result['tests'].append({'name':'native app liveness and ownerPID window','pid':proc.pid,'windowCount':windows,'passed':True})
        player=moved/'Contents/Resources/mpv.app/Contents/MacOS/mpv'
        if not player.is_file(): raise RuntimeError(f'branded mpv executable missing: {player}')
        mpvlog=(evidence/'mpv.log').open('w')
        mpv=subprocess.Popen([str(player),'--no-config','--idle=yes','--force-window=yes','--keep-open=yes','--vo=null','lavfi://testsrc=size=160x90:rate=1'],env=env,stdout=mpvlog,stderr=subprocess.STDOUT)
        try:
            time.sleep(3)
            if mpv.poll() is not None: raise RuntimeError(f'branded mpv exited during synthetic playback: {mpv.returncode}')
            info=run(['/usr/bin/plutil','-p',str(moved/'Contents/Info.plist')])
            if info.returncode or 'Jellyfin Player' not in info.stdout: raise RuntimeError('app metadata verification failed')
            descendants=run(['/usr/bin/pgrep','-P',str(proc.pid)]).stdout.split()
            result['tests'].append({'name':'branded mpv synthetic lavfi playback alive','pid':mpv.pid,'launcherChildren':descendants,'passed':True})
        finally:
            if mpv.poll() is None: mpv.send_signal(__import__('signal').SIGTERM)
            try: mpv.wait(timeout=15)
            except subprocess.TimeoutExpired: mpv.kill(); mpv.wait()
            mpvlog.close()
        quit_result=run(['/usr/bin/osascript','-e','tell application "Jellyfin Player" to quit'],timeout=10)
        if quit_result.returncode: proc.terminate()
        try: proc.wait(timeout=15)
        except subprocess.TimeoutExpired: proc.terminate(); proc.wait(timeout=10)
        if proc.returncode not in (0,-15): raise RuntimeError(f'main app graceful quit failed: {proc.returncode}')
        result['tests'].append({'name':'main app graceful quit','returncode':proc.returncode,'passed':True})
    finally:
        if proc.poll() is None: proc.terminate(); proc.wait(timeout=10)
        log.close()
    (evidence/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2)); return 0


def retain_failure(exc):
    if sys.platform != 'darwin': return
    evidence=pathlib.Path(__file__).resolve().parents[1]/'outputs/macos-smoke-evidence'
    evidence.mkdir(parents=True,exist_ok=True)
    copied=[]
    logs=TEMP_HOME/'Library/Logs/Jellyfin MPV Shim' if TEMP_HOME else None
    if logs and logs.exists():
        for item in logs.rglob('*'):
            if item.is_file():
                dest=evidence/'home-logs'/item.relative_to(logs)
                dest.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(item,dest); copied.append(str(dest.relative_to(evidence)))
    (evidence/'result.json').write_text(json.dumps({'passed':False,'error':str(exc),'logs':copied},indent=2)+'\n')


if __name__=='__main__':
    try: sys.exit(main())
    except Exception as exc:
        print('SMOKE FAILED: '+str(exc),file=sys.stderr)
        try: retain_failure(exc)
        except Exception as retain_exc: print('EVIDENCE RETENTION FAILED: '+str(retain_exc),file=sys.stderr)
        sys.exit(1)
